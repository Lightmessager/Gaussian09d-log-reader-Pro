"""Small RF7 timing diagnostic; no screenshots or writes to the original fixture."""
import json
from pathlib import Path
import sys
from time import monotonic
from uuid import uuid4
import os
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tools")]
os.environ["QT_SCALE_FACTOR"]="0.8"
from diagnose_static_runtime import windows_affinity
m,_,s=windows_affinity();s(m["default"]&0xffffff3f)
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt,QPoint
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.storage import ProjectRepository
from gaussianreadpro.storage.preferences import LocalPreferences
from gaussianreadpro.ui.main_window import MainWindow
from build_profile_rf4_fixture import main as fixture

out=ROOT/"artifacts/rf7"/("structure-trace-"+uuid4().hex[:8]);out.mkdir(parents=True)
with ProjectRepository(fixture(),read_only=True) as r:p=r.load()
with ProjectRepository(out/"p.grproj",create=True) as r:r.save(p)
LocalPreferences(out/"prefs.ini").save(language="en",theme="dark",recent_projects=[],reduce_motion=True)
app=QApplication([]);app.setQuitOnLastWindowClosed(False);c=ProjectController(out/"recovery",out/"prefs.ini");w=MainWindow(c);w.show()
def wait(f):
    t=monotonic()
    while not f():
        QTest.qWait(15)
        if monotonic()-t>45:raise TimeoutError(c.operation)
def js(code):
    v=[];w.profile.page.runJavaScript("JSON.stringify("+code+")",v.append);wait(lambda:bool(v));return json.loads(v[0]) if v[0] else None
c.bootstrap();wait(lambda:not c.busy);c.open_project(out/"p.grproj",ignore_recovery=True);wait(lambda:not c.busy and c.project is not None)
w.navigation.setCurrentRow(2);w.compact_tabs.setCurrentIndex(1);w.setGeometry(60,60,1672,941)
QTest.qWait(1000);wait(lambda:w.profile.ready and not c.busy and not c._workspace_timer.isActive())
wait(lambda:w.profile.summary.get("render_id")==w.profile.last_payload["render_id"])
wait(lambda:js("Boolean(window.grpr.renderer3d?.nodes?.length)"))
events=[];start=monotonic()
def log(event,**data):events.append({"ms":round((monotonic()-start)*1000,2),"event":event,**data})
original=c.request_structure
def request(q):log("request",busy=c.busy,op=c.operation,signature=q.get("signature"));return original(q)
c.request_structure=request
c.busyChanged.connect(lambda busy,op:log("busy",busy=busy,op=op))
c.structureReady.connect(lambda r:log("result",signature=r.get("signature"),status=r["structure"]["status"],current=w.profile._structure_signature))
w.profile.bridge.dataChanged.connect(lambda raw:log("payload",entry=json.loads(raw).get("inspector",{}).get("detail",{}).get("entry_id"),status=json.loads(raw).get("inspector",{}).get("structure",{}).get("status")))
path=w.profile.last_payload["paths"][0];n=path["points"][2]
xy=js("window.grpr.pointPosition("+json.dumps(path["id"])+","+json.dumps(n["entry_id"])+")")
w.raise_();w.activateWindow();point=w.profile.webview.mapTo(w,QPoint(round(xy["x"]),round(xy["y"])));start=monotonic()
QTest.mouseClick(w.windowHandle(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point)
end=monotonic()+1.6
while monotonic()<end:QTest.qWait(10)
(out/"trace.json").write_text(json.dumps(events,indent=2),encoding="utf-8");print(json.dumps(events,indent=2))
wait(lambda:not c.busy);c.close();wait(lambda:c._closed);w.close();app.quit()
