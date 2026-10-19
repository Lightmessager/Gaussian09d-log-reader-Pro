"""Frozen UX v2 smoke: exercise the default UI's visible rename and builder buttons."""
import ctypes
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from time import monotonic


@contextmanager
def _save_dialog_target(dialog_type, target):
    original = dialog_type.getSaveFileName
    dialog_type.getSaveFileName = staticmethod(lambda *args, **kwargs: (str(target), ""))
    try:
        yield
    finally:
        dialog_type.getSaveFileName = original


def _set_affinity():
    if sys.platform != "win32":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.SetProcessAffinityMask.restype = ctypes.c_int
    mask = 0xFFFFFF3F
    if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), mask):
        raise ctypes.WinError(ctypes.get_last_error())
    return hex(mask)


def _pump(milliseconds):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _wait(app, predicate, label, seconds=45):
    deadline = monotonic() + seconds
    while not predicate():
        app.processEvents()
        _pump(8)
        if monotonic() > deadline:
            raise TimeoutError(label)


def _screenshot(widget, path):
    image = widget.grab()
    if image.isNull() or not image.save(str(path)):
        raise RuntimeError(f"Could not capture {path.name}")
    return {"path": str(path), "size": [image.width(), image.height()],
            "dpr": image.devicePixelRatio()}


def _modal_responder(app, text):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

    state = {"input_accepted": False, "rename_confirmed": False}
    timer = QTimer(app)
    timer.setInterval(20)

    def answer():
        for widget in QApplication.topLevelWidgets():
            if not widget.isVisible():
                continue
            if isinstance(widget, QInputDialog) and not state["input_accepted"]:
                widget.setTextValue(text)
                state["input_accepted"] = True
                widget.accept()
                return
            if isinstance(widget, QMessageBox) and not state["rename_confirmed"]:
                yes = widget.button(QMessageBox.StandardButton.Yes)
                if yes is not None:
                    state["rename_confirmed"] = True
                    yes.click()
                    return

    timer.timeout.connect(answer)
    timer.start()
    return timer, state


def main(arguments):
    report_path = None
    app = controller = window = None
    report = {"passed": False, "checks": {}, "events": [], "screenshots": [],
              "application": None, "version": None, "frozen": bool(getattr(sys, "frozen", False)),
              "executable": sys.executable}
    try:
        if len(arguments) != 1:
            raise ValueError("Expected one U8 validation JSON config path")
        config = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
        out = Path(config["out"]).resolve()
        out.mkdir(parents=True, exist_ok=True)
        report_path = out / "frozen-ui-validation.json"
        report["affinity"] = _set_affinity()

        from PySide6.QtCore import Qt, qVersion, QTimer
        from PySide6.QtGui import QIcon
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
        from . import APP_NAME, VERSION_LABEL, __version__
        from .services.controller import ProjectController
        from .ui.main_window import MainWindow
        from .ui.reaction_builder import ReactionBuilderDialog
        from .ui.theme import apply_theme
        from .storage.preferences import LocalPreferences

        app = QApplication([sys.argv[0]])
        app.setQuitOnLastWindowClosed(False)
        app.setOrganizationName(APP_NAME)
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(VERSION_LABEL)
        app.setApplicationDisplayName(APP_NAME + " " + VERSION_LABEL)
        resources = Path(__file__).resolve().parent / "resources"
        app.setWindowIcon(QIcon(str(resources / "icons" / "app-icon.png")))
        preferences = out / "preferences.ini"
        LocalPreferences(preferences).save(language="zh_CN", theme="light", reduce_motion=True,
                                           recent_projects=[], window_geometry=None)
        apply_theme(app, "light", reduce_motion=True)

        controller = ProjectController(out / "recovery", preferences)
        window = MainWindow(controller)
        window.setWindowIcon(app.windowIcon())
        window.resize(1440, 900)
        window.show()
        controller.bootstrap()
        _wait(app, lambda: not controller.busy, "bootstrap default home")
        app.processEvents()

        report.update(application=APP_NAME, version=__version__, version_label=VERSION_LABEL,
                      qt=qVersion(), screen=list(window.screen().geometry().getRect()),
                      initial_project_id=None if controller.project is None else controller.project.id)
        report["screenshots"].append(_screenshot(window, out / "default-home.png"))
        report["checks"]["default_home"] = (
            window.isVisible() and window.navigation.currentRow() == 0 and controller.project is None)
        report["checks"]["version_visible"] = (
            window.brand.text() == APP_NAME and VERSION_LABEL in window.windowTitle())
        report["checks"]["visible_new_and_rename_actions"] = (
            window.new_button.isVisibleTo(window) and window.new_button.isEnabled() and
            window.project_name.isVisibleTo(window))

        # Click the shipped new-project action and answer the actual Qt text dialog.
        responder, answer_state = _modal_responder(app, "U8 Frozen Project")
        QTest.mouseClick(window.new_button, Qt.MouseButton.LeftButton)
        responder.stop()
        report["events"].append({"action": "click_visible_new_project", **answer_state})
        _wait(app, lambda: controller.project is not None and not controller.busy,
              "create project from packaged home")
        project_id = controller.project.id
        report["checks"]["new_project_created"] = bool(project_id)

        target = out / "U8 Frozen Project.grproj"
        with _save_dialog_target(QFileDialog, target):
            QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
        _wait(app, lambda: not controller.busy and controller.path == target.resolve() and target.is_file(),
              "save project through packaged save action")
        report["events"].append({"action": "click_visible_save_project", "file": str(target)})

        # Click the project-name button, rename the saved project, and confirm the
        # application's actual rename prompt inside this isolated test directory.
        responder, answer_state = _modal_responder(app, "U8 Frozen Renamed")
        QTest.mouseClick(window.project_name, Qt.MouseButton.LeftButton)
        responder.stop()
        report["events"].append({"action": "click_visible_project_name", **answer_state})
        renamed = out / "U8 Frozen Renamed.grproj"
        _wait(app, lambda: not controller.busy and controller.path == renamed.resolve() and renamed.is_file(),
              "rename project through packaged name button")
        report["checks"]["project_renamed"] = (
            not target.exists() and window.project_name.text() == renamed.stem and
            controller.project.id == project_id)

        report["checks"]["visible_builder_action"] = (
            window.builder_button.isVisibleTo(window) and window.builder_button.isEnabled())
        dialog_state = {}
        builder_timer = QTimer(app)
        builder_timer.setInterval(20)

        def close_builder():
            for candidate in QApplication.topLevelWidgets():
                if isinstance(candidate, ReactionBuilderDialog) and candidate.isVisible():
                    dialog_state.update({"visible": True,
                                         "title": candidate.windowTitle(),
                                         "path_id": candidate.path_combo.currentData(),
                                         "cancel_visible": candidate.cancel_button.isVisible()})
                    report["screenshots"].append(_screenshot(candidate, out / "reaction-builder.png"))
                    QTest.mouseClick(candidate.cancel_button, Qt.MouseButton.LeftButton)
                    builder_timer.stop()
                    return

        builder_timer.timeout.connect(close_builder)
        builder_timer.start()
        QTest.mouseClick(window.builder_button, Qt.MouseButton.LeftButton)
        builder_timer.stop()
        report["events"].append({"action": "click_visible_edit_reaction_path"})
        report["builder_dialog"] = dialog_state
        report["checks"]["builder_opened_from_visible_action"] = (
            dialog_state.get("visible") is True and dialog_state.get("cancel_visible") is True)

        window.close()
        _wait(app, lambda: controller._closed and not window.isVisible(),
              "close packaged UI validation window")
        report["project_file"] = str(renamed)
        report["passed"] = all(report["checks"].values()) and report["frozen"]
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if controller is not None and not controller._closed and not controller.busy:
            controller.close()
            if app is not None:
                try:
                    _wait(app, lambda: controller._closed, "shutdown validation controller", 10)
                except Exception:
                    pass
        if report_path is not None:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if app is not None:
            app.quit()
    return 0 if report["passed"] else 1
