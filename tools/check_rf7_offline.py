"""Open the actual EXE-exported HTML after relocation, with network blocked."""
import json
import os
from pathlib import Path
import shutil
import sys
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def main():
    from diagnose_static_runtime import windows_affinity
    modes, _, select = windows_affinity(); select(modes["default"] & 0xFFFFFF3F)
    os.environ["QT_SCALE_FACTOR"] = "0.8"
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
    from PySide6.QtWebEngineWidgets import QWebEngineView
    app = QApplication([])
    summary = json.loads((ROOT / "artifacts/rf7/frozen-primary-latest.json").read_text())
    source = Path(summary["run"]) / "export-3d-html"
    out = ROOT / ("artifacts/rf7/offline-relocated-" + uuid4().hex[:8])
    shutil.copytree(source, out)
    blocked, errors = [], []
    class OnlyLocal(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            if info.requestUrl().scheme() not in ("file", "data", "blob", "about"):
                blocked.append(info.requestUrl().toString()); info.block(True)
    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source):
            if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                errors.append(message)
    view = QWebEngineView(); profile = QWebEngineProfile(view)
    guard = OnlyLocal(profile); profile.setUrlRequestInterceptor(guard)
    page = Page(profile, view); view.setPage(page)
    view.resize(1476, 891); view.show()
    def wait(predicate, timeout=40):
        deadline = monotonic() + timeout
        while not predicate():
            QTest.qWait(10)
            if monotonic() > deadline: raise TimeoutError(str(errors))
    def js(code):
        result = []; page.runJavaScript("JSON.stringify(" + code + ")", result.append)
        wait(lambda: bool(result), 10)
        return json.loads(result[0]) if result[0] else None
    report = {"source": str(source), "relocated": str(out), "host": "source Qt WebEngine, EXE-produced HTML", "checks": {}}
    try:
        view.load(QUrl.fromLocalFile(str(out / "profile.html")))
        wait(lambda: js("Boolean(window.grpr?.renderer3d?.nodes?.length)"))
        report["diagnostics"] = js("window.grpr.diagnostics()")
        check = report["checks"]
        check["actual_three_r170"] = report["diagnostics"]["three_version"] == "170"
        check["no_qt_bridge"] = not js("Boolean(window.qt)")
        wait(lambda: js("Boolean(window.profileInspector?.molecule?.diagnostics().objects)"))
        check["embedded_molecule"] = True
        js("window.grpr.workbenchAction({action:'mode',mode:'2d'})")
        wait(lambda: js("window.grpr.shown.view==='2d'&&Boolean(document.querySelector('svg.main-svg'))"))
        check["two_d"] = True
        js("window.grpr.workbenchAction({action:'mode',mode:'3d'})")
        wait(lambda: js("window.grpr.shown.view==='3d'"))
        check["camera_retained"] = js("window.grpr.renderer3d.viewport()") == report["diagnostics"]["viewport"]
        js("document.getElementById('compare-control').click()")
        wait(lambda: js("window.grpr.shown.compare===false"))
        js("document.getElementById('compare-control').click()")
        wait(lambda: js("window.grpr.shown.compare===true&&window.grpr.shown.paths.filter(p=>p.visible).length===2"))
        check["compare_round_trip"] = True
        # Match the 1100px Qt window's 64px navigation strip. Check actual DOM
        # geometry, since scrollWidth>=clientWidth alone misses text overflow.
        view.resize(1036, 770)
        wait(lambda: js("document.documentElement.clientWidth===1036"))
        QTest.qWait(300)
        check["mid_toolbar_text_inside_buttons"] = js("['compare-control','reset-control','export-control'].every(id=>{const e=document.getElementById(id);return e.scrollWidth<=e.clientWidth+1})")
        check["mid_toolbar_overflow_accessible"] = js("(()=>{const e=document.getElementById('profile-toolbar');return e.scrollWidth>e.clientWidth&&getComputedStyle(e).overflowX==='auto'})()")
        check["mid_cube_and_tools_separate"] = js("(()=>{const a=document.getElementById('orientation-placeholder').getBoundingClientRect(),b=document.getElementById('bottom-tools').getBoundingClientRect();return a.bottom<=b.top})()")
        check["mid_tooltip_avoids_energy_title"] = js("(()=>{const a=document.querySelector('.scene-tooltip').getBoundingClientRect(),b=document.querySelector('.scene-axis-label.z-title').getBoundingClientRect();return Math.min(a.right,b.right)<=Math.max(a.left,b.left)||Math.min(a.bottom,b.bottom)<=Math.max(a.top,b.top)})()")
        check["no_network_or_js_errors"] = not blocked and not errors
        report["passed"] = all(check.values())
    except Exception as error:
        report["passed"] = False; report["error"] = str(error)
    report["blocked"] = blocked; report["javascript_errors"] = errors
    (ROOT / "artifacts/rf7/offline-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)); view.close()
    page.deleteLater(); QTest.qWait(50)
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
