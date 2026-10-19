"""S0 offline Qt/Plotly prototype and actual mouse-click smoke check."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from decimal import Decimal
from pathlib import Path

import PySide6
from PySide6.QtCore import QObject, QPoint, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtTest import QTest
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

RESOURCES = Path(__file__).resolve().parent / "resources" / "plot"
PROJECT_ID = "a39a9a9e-b9c4-46ad-bf90-8105a676d8fe"
IDS = ["92c733ed-c8e1-47cf-bdb1-a8bc183ca14a", "916c7e03-91d0-47e1-a4a2-6e912e6e44e1",
       "6438a233-9a68-4c94-a28c-0c5d49afcf31", "ccf34401-a051-457a-b824-744c549a42bd"]


def sample_payload() -> dict:
    raw = [("R", "-150.0"), ("TS1", "-149.976"), ("I1", "-150.008"), ("P", "-150.025")]
    factor, reference = Decimal("627.509474063"), Decimal("-150.0")
    return {"protocol_version": 1, "project_id": PROJECT_ID, "revision": 1,
            "view": "2d", "unit": "kcal_mol", "energy_label": "Relative energy",
            "reference_label": "R", "points": [
                {"node_id": IDS[i], "entry_id": IDS[i], "label": label, "x": i,
                 "value": float((Decimal(energy) - reference) * factor),
                 "role": "transition_state" if label == "TS1" else "unspecified"}
                for i, (label, energy) in enumerate(raw)]}


class OfflineRequests(QWebEngineUrlRequestInterceptor):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.allowed_schemes = set()
        self.blocked = []

    def interceptRequest(self, info):
        scheme = info.requestUrl().scheme()
        if scheme in {"file", "qrc", "data", "about"}:
            self.allowed_schemes.add(scheme)
        else:
            self.blocked.append(info.requestUrl().toString())
            info.block(True)


class Bridge(QObject):
    dataChanged = Signal(str)
    ready = Signal(int, str)
    did_render = Signal(int, str)
    selected = Signal(str, int)
    failed = Signal(str)

    @Slot(int, str)
    def pageReady(self, protocol, version):
        self.ready.emit(protocol, version)

    @Slot(int, str)
    def rendered(self, revision, summary):
        self.did_render.emit(revision, summary)

    @Slot(str, int)
    def pointSelected(self, node_id, revision):
        self.selected.emit(node_id, revision)

    @Slot(str)
    def pageError(self, error):
        self.failed.emit(error)


class DiagnosticPage(QWebEnginePage):
    def __init__(self, profile, parent):
        super().__init__(profile, parent)
        self.errors = []

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.errors.append({"message": message, "line": line, "source": source})


class PrototypeWindow(QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.payload = sample_payload()
        self.completed = False
        self.click_sent = False
        self.report = {"stage": "S0", "frozen": bool(getattr(sys, "frozen", False)),
                       "platform": platform.platform(), "python": platform.python_version(),
                       "pyside6": PySide6.__version__, "synthetic_data": True,
                       "checks": {}, "errors": []}
        self.setWindowTitle("GaussianReaderPro · S0 offline feasibility")
        self.resize(1080, 740)
        container = QWidget()
        container.setStyleSheet("QWidget { background:#f7f9fc; }")
        layout = QVBoxLayout(container)
        title = QLabel("GaussianReaderPro  ·  Offline Qt + Plotly prototype")
        title.setStyleSheet("font-size:20px;font-weight:600;color:#27334a;padding:12px;")
        layout.addWidget(title)
        self.view = QWebEngineView()
        layout.addWidget(self.view, 1)
        self.status = QLabel("Loading local resources… / 正在加载本地资源")
        self.status.setStyleSheet("padding:10px;color:#5367b8;")
        layout.addWidget(self.status)
        self.setCentralWidget(container)
        # An unnamed profile is off-the-record, avoiding persistent user profile writes.
        self.profile = QWebEngineProfile(self)
        self.requests = OfflineRequests(self.profile)
        self.profile.setUrlRequestInterceptor(self.requests)
        self.page = DiagnosticPage(self.profile, self.view)
        self.view.setPage(self.page)
        self.channel = QWebChannel(self.page)
        self.bridge = Bridge(self.channel)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)
        self.bridge.ready.connect(self.on_ready)
        self.bridge.did_render.connect(self.on_rendered)
        self.bridge.selected.connect(self.on_selected)
        self.bridge.failed.connect(self.fail)
        self.view.loadFinished.connect(self.on_loaded)
        self.page.loadingChanged.connect(self.on_loading_changed)
        self.page.renderProcessTerminated.connect(self.on_process_terminated)
        vendor = RESOURCES / "vendor" / "plotly.min.js"
        if not vendor.is_file():
            QTimer.singleShot(0, lambda: self.fail("Missing local Plotly asset; run tools/vendor_plotly.py"))
        else:
            self.report["plotly_sha256"] = hashlib.sha256(vendor.read_bytes()).hexdigest()
            self.view.load(QUrl.fromLocalFile(str(RESOURCES / "index.html")))
        if args.self_test:
            QTimer.singleShot(45000, lambda: self.fail("Self-test timed out") if not self.completed else None)

    def on_loaded(self, success):
        self.report["checks"]["local_page_loaded"] = bool(success)
        if not success:
            QTimer.singleShot(200, lambda: self.fail("Local page failed to load"))

    def on_loading_changed(self, info):
        self.report.setdefault("load_events", []).append(
            {"status": str(info.status()), "code": info.errorCode(), "description": info.errorString(),
             "url": info.url().toString()})

    def on_process_terminated(self, status, code):
        self.report["renderer_termination"] = {"status": str(status), "code": code}
        self.fail("WebEngine renderer terminated")

    def on_ready(self, protocol, version):
        if protocol != 1:
            self.fail(f"Unexpected bridge protocol {protocol}")
            return
        self.report["checks"]["webchannel_handshake"] = True
        self.report["plotly_version"] = version
        self.bridge.dataChanged.emit(json.dumps(self.payload, allow_nan=False))

    def on_rendered(self, revision, raw_summary):
        try:
            summary = json.loads(raw_summary)
            assert revision == self.payload["revision"]
            assert summary["point_count"] == 4
            assert summary["ids"] == IDS
            assert len(summary["values"]) == 4
            assert all(math.isclose(a, p["value"], rel_tol=1e-12, abs_tol=1e-12)
                       for a, p in zip(summary["values"], self.payload["points"]))
            assert summary["svg_count"] > 0
        except (ValueError, AssertionError, KeyError, TypeError) as exc:
            self.fail(f"Rendered data check failed: {exc}")
            return
        self.report["checks"]["plotly_svg_rendered"] = True
        self.report["checks"]["python_values_preserved"] = True
        self.report["render_summary"] = summary
        self.status.setText("Local chart ready. Click a point / 点击节点验证交互")
        if self.args.self_test and not self.click_sent:
            self.click_sent = True
            QTimer.singleShot(500, lambda: self.page.runJavaScript("JSON.stringify(window.s0PointPosition(1))", self.click_point))

    def click_point(self, position):
        if isinstance(position, str):
            try:
                position = json.loads(position)
            except ValueError:
                position = None
        if not isinstance(position, dict) or not {"x", "y"}.issubset(position):
            self.fail("Could not locate rendered TS1 marker")
            return
        point = QPoint(round(position["x"]), round(position["y"]))
        self.report["mouse_click_position"] = {"x": point.x(), "y": point.y()}
        self.view.setFocus()
        target = self.view.focusProxy() or self.view
        QTest.mouseClick(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)

    def on_selected(self, node_id, revision):
        if node_id not in IDS or revision != self.payload["revision"]:
            self.fail("Invalid or outdated selection event")
            return
        label = self.payload["points"][IDS.index(node_id)]["label"]
        self.status.setText(f"Selected: {label} · UUID {node_id}")
        if self.args.self_test:
            if node_id != IDS[1]:
                self.fail("Mouse click selected a different node")
                return
            self.report["checks"]["actual_mouse_click_roundtrip"] = True
            self.report["selected_node_id"] = node_id
            QTimer.singleShot(300, self.finish)

    def fail(self, error):
        if self.completed:
            return
        self.report["errors"].append(error)
        self.status.setText(error)
        if self.args.self_test:
            self.finish()

    def finish(self):
        if self.completed:
            return
        self.completed = True
        self.report["request_schemes"] = sorted(self.requests.allowed_schemes)
        self.report["blocked_remote_requests"] = self.requests.blocked
        self.report["javascript_errors"] = self.page.errors
        self.report["checks"]["no_remote_requests"] = not self.requests.blocked
        self.report["checks"]["no_javascript_errors"] = not self.page.errors
        if self.args.screenshot:
            self.args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            self.report["checks"]["screenshot_saved"] = self.grab().save(str(self.args.screenshot))
        required = ["local_page_loaded", "webchannel_handshake", "plotly_svg_rendered",
                    "python_values_preserved", "actual_mouse_click_roundtrip",
                    "no_remote_requests", "no_javascript_errors"]
        self.report["passed"] = not self.report["errors"] and all(self.report["checks"].get(k) for k in required)
        self.args.report.parent.mkdir(parents=True, exist_ok=True)
        self.args.report.write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
        QApplication.instance().exit(0 if self.report["passed"] else 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("artifacts/s0/qt-smoke.json"))
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("GaussianReaderPro-S0")
    window = PrototypeWindow(args)
    window.show()
    result = app.exec()
    # Release page before off-the-record profile to prevent WebEngine shutdown warnings.
    window.view.setPage(None)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
