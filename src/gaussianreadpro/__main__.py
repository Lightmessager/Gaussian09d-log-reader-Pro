"""Production workbench entry point; S0 prototype remains separately available."""
import argparse
import json
from pathlib import Path
import sys


def _webengine_smoke(app, report_path):
    """Load the shipped local chart page and verify its Qt WebChannel handshake."""
    from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QMainWindow

    resources = Path(__file__).resolve().parent / "resources" / "plot"
    result = {"passed": False, "loaded": False, "protocol": None, "plotly": None, "errors": []}
    window = QMainWindow()
    view = QWebEngineView(window)
    window.setCentralWidget(view)
    channel = QWebChannel(view.page())

    class SmokeBridge(QObject):
        dataChanged = Signal(str)
        resetRequested = Signal()
        imageRequested = Signal(str)

        @Slot(int, str)
        def pageReady(self, protocol, version):
            result.update(protocol=protocol, plotly=version, passed=(protocol == 2), loaded=True)
            QTimer.singleShot(0, finish)

        @Slot(str)
        def failed(self, message):
            result["errors"].append(str(message))

    bridge = SmokeBridge(channel)
    channel.registerObject("bridge", bridge)
    view.page().setWebChannel(channel)

    def finish():
        Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        app.exit(0 if result["passed"] else 1)

    def load_finished(ok):
        result["loaded"] = bool(ok)
        if not ok:
            result["errors"].append("profile.html failed to load")
            QTimer.singleShot(0, finish)

    view.loadFinished.connect(load_finished)
    QTimer.singleShot(30000, lambda: (result["errors"].append("WebEngine smoke timed out"), finish()))
    window.resize(640, 480)
    window.show()
    view.load(QUrl.fromLocalFile(str(resources / "profile.html")))
    return app.exec()

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--render-static":
        from .services.static_plot_worker import main as render_static
        return render_static(sys.argv[2:])
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from .services.controller import ProjectController
    from .storage.preferences import default_recovery_directory
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme
    parser = argparse.ArgumentParser(description="GaussianReadPro research workbench")
    parser.add_argument("project", nargs="?", type=Path)
    parser.add_argument("--preferences", type=Path, help="Use a separate preferences INI file")
    parser.add_argument("--recovery-directory", type=Path)
    parser.add_argument("--webengine-smoke-report", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setOrganizationName("GaussianReadPro")
    app.setApplicationName("GaussianReadPro")
    icon_path = Path(__file__).resolve().parent / "resources" / "icons" / "app-icon.png"
    app.setWindowIcon(QIcon(str(icon_path)))
    apply_theme(app)
    if args.webengine_smoke_report:
        return _webengine_smoke(app, args.webengine_smoke_report)
    controller = ProjectController(args.recovery_directory or default_recovery_directory(), args.preferences)
    window = MainWindow(controller)
    window.setWindowIcon(app.windowIcon())
    window.show()
    def resume(preferences, _candidates):
        recent = preferences.get("recent_projects", [])
        target = args.project or (recent[0] if recent else None)
        if target:
            QTimer.singleShot(0, lambda: window.open_path(target))
    controller.bootstrapped.connect(resume)
    QTimer.singleShot(0, controller.bootstrap)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
