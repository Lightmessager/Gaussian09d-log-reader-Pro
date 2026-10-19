"""Explicit RF7 diagnostic entry, shared by source and the actual frozen EXE.

Only runs with --validate-rf7 and an isolated validation configuration. It uses
the production controller, MainWindow, resources, save chain and export worker.
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
from time import monotonic
import traceback


def memory_snapshot():
    class Entry(ctypes.Structure):
        _fields_ = [("size",wintypes.DWORD),("usage",wintypes.DWORD),("pid",wintypes.DWORD),
                    ("heap",ctypes.c_size_t),("module",wintypes.DWORD),("threads",wintypes.DWORD),
                    ("parent",wintypes.DWORD),("priority",wintypes.LONG),("flags",wintypes.DWORD),("image",wintypes.WCHAR*260)]
    class Memory(ctypes.Structure):
        _fields_ = [("size",wintypes.DWORD),("faults",wintypes.DWORD),*[(n,ctypes.c_size_t) for n in
            ("peak_ws","ws","peak_paged","paged","peak_nonpaged","nonpaged","pagefile","peak_pagefile","private")]]
    kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel.CreateToolhelp32Snapshot.argtypes=(wintypes.DWORD,wintypes.DWORD);kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    kernel.Process32FirstW.argtypes=(wintypes.HANDLE,ctypes.POINTER(Entry));kernel.Process32NextW.argtypes=kernel.Process32FirstW.argtypes
    kernel.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD);kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    psapi.GetProcessMemoryInfo.argtypes=(wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD)
    snapshot=kernel.CreateToolhelp32Snapshot(2,0); processes={}
    try:
        entry=Entry();entry.size=ctypes.sizeof(entry);more=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
        while more:
            processes[entry.pid]=(entry.parent,entry.image);more=kernel.Process32NextW(snapshot,ctypes.byref(entry))
    finally: kernel.CloseHandle(snapshot)
    descendants={os.getpid()}
    while True:
        expanded=descendants|{pid for pid,(parent,_) in processes.items() if parent in descendants}
        if expanded==descendants:break
        descendants=expanded
    rows=[]
    for pid in sorted(descendants):
        image=processes.get(pid,(None,"python"))[1]
        if pid!=os.getpid() and "qtwebengine" not in image.lower():continue
        handle=kernel.OpenProcess(0x1010,False,pid);memory=Memory();memory.size=ctypes.sizeof(memory)
        try:
            if handle and psapi.GetProcessMemoryInfo(handle,ctypes.byref(memory),memory.size):
                rows.append({"pid":pid,"image":image,"ui":pid==os.getpid(),"private_bytes":memory.private,"working_set":memory.ws})
        finally:
            if handle:kernel.CloseHandle(handle)
    return {"processes":rows,"ui_private":sum(p["private_bytes"] for p in rows if p["ui"]),
            "webengine_private":sum(p["private_bytes"] for p in rows if not p["ui"])}


def percentile(values, fraction):
    return sorted(values)[min(len(values)-1, max(0, int((len(values)-1)*fraction+.5)))] if values else None


def main(arguments):
    config=json.loads(Path(arguments[0]).read_text(encoding="utf-8"));out=Path(config["out"]);out.mkdir(parents=True,exist_ok=True)
    os.environ["QT_SCALE_FACTOR"]=config.get("scale_factor","0.8");os.environ.pop("QT_QPA_PLATFORM",None)
    os.environ["QTEST_MOUSEEVENT_DELAY"]="0"
    kernel=ctypes.WinDLL("kernel32",use_last_error=True);kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
    if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),0xFFFFFF3F):raise ctypes.WinError(ctypes.get_last_error())
    from PySide6.QtCore import QPoint, Qt, qVersion, QEventLoop, QTimer
    from PySide6.QtGui import QIcon, QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from . import APP_NAME, VERSION_LABEL, __version__
    from .core.models import snapshot_to_dict
    from .storage import ProjectRepository, StorageError
    from .storage.preferences import LocalPreferences
    from .services.controller import ProjectController
    from .ui.main_window import MainWindow
    from .ui.expression_editor import ExpressionDialog
    from .ui.theme import apply_theme
    resources=Path(__file__).resolve().parent/"resources"
    prefs=out/"preferences.ini"
    LocalPreferences(prefs).save(language=config.get("language","en"),theme=config.get("theme","dark"),
        window_geometry=None,recent_projects=[],reduce_motion=True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs,True)
    app=QApplication([]);app.setQuitOnLastWindowClosed(False);app.setOrganizationName(APP_NAME);app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION_LABEL);app.setApplicationDisplayName(APP_NAME+" "+VERSION_LABEL)
    app.setWindowIcon(QIcon(str(resources/"icons/app-icon.png")));apply_theme(app,config.get("theme","dark"),reduce_motion=True)
    controller=ProjectController(out/"recovery",prefs);window=MainWindow(controller);window.setWindowIcon(app.windowIcon());window.show();panel=window.profile
    report={"passed":False,"checks":{},"screenshots":[],"events":[],"phase":config.get("phase","primary"),
        "application":APP_NAME,"version":__version__,"pid":os.getpid(),"frozen":bool(getattr(sys,"frozen",False)),
        "executable":sys.executable,"affinity":"0xffffff3f","qt":qVersion(),"python":sys.version,"os":platform.platform(),
        "cpu":platform.processor(),"scale_factor":os.environ["QT_SCALE_FACTOR"],"resources":str(resources)}
    editor=None

    def pump(milliseconds):
        # Match QApplication.exec: release the GIL while Qt waits, so the serial
        # Python worker is not delayed by the observer's QTest.qWait calls.
        loop=QEventLoop();QTimer.singleShot(milliseconds,loop.quit);loop.exec()

    def wait(predicate,timeout=50):
        deadline=monotonic()+timeout
        while not predicate():
            pump(5)
            if monotonic()>deadline:raise TimeoutError(f"RF7 timeout {controller.operation}, JS={panel.javascript_errors[:3]}, failure={panel.failure}")

    def js(code):
        values=[];panel.page.runJavaScript("JSON.stringify("+code+")",values.append);wait(lambda:bool(values),15)
        return json.loads(values[0]) if values[0] else None

    def stable():
        # Long QTest.qWait calls hold the Python GIL on this PySide build and
        # starve the actual serial worker. Pump in short steps like normal exec.
        until=monotonic()+.45
        while monotonic()<until:pump(10)
        def idle():
            return not controller.busy and not controller._workspace_timer.isActive() and not controller._pending_structure and not controller._pending_preferences and panel.ready and panel.last_payload is not None and panel.summary.get("render_id")==panel.last_payload["render_id"]
        deadline=monotonic()+50
        while True:
            wait(idle)
            queue=js("!window.grpr.queueState.running&&!window.grpr.queueState.pending&&window.grpr.shown.render_id==="+str(panel.last_payload["render_id"]))
            if queue and idle():return
            QTest.qWait(10)
            if monotonic()>deadline:raise TimeoutError("RF7 stable render")

    def capture(name,widget=None):
        QTest.qWait(160);image=(widget or window).grab();path=out/(name+".png");assert image.save(str(path))
        report["screenshots"].append({"file":str(path),"pixels":[image.width(),image.height()],"dpr":image.devicePixelRatio(),
            "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"capture":"unmodified QWidget.grab"})

    def mouse(x,y):
        window.raise_();window.activateWindow();panel.webview.setFocus()
        return window.windowHandle(),panel.webview.mapTo(window,QPoint(round(x),round(y)))

    def drag(dx,dy,count=36):
        r=js("(()=>{const r=document.getElementById('plot').getBoundingClientRect();return {x:r.x+r.width*.55,y:r.y+70}})()")
        target,p=mouse(r["x"],r["y"]);QTest.mouseMove(target,p);QTest.mousePress(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,p)
        for i in range(1,count+1):
            QTest.mouseMove(target,p+QPoint(round(dx*i/count),round(dy*i/count)),0);QTest.qWait(5)
        QTest.mouseRelease(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,p+QPoint(dx,dy));stable()
        report["events"].append({"action":"native_drag","start":[r["x"],r["y"]],"delta":[dx,dy],"moves":count,"camera":js("window.grpr.renderer3d.viewport()")})

    def select(path,point):
        xy=js("window.grpr.pointPosition("+json.dumps(path["id"])+","+json.dumps(point["entry_id"])+")")
        target,p=mouse(xy["x"],xy["y"]);QTest.mouseClick(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,p);stable()
        report["events"].append({"action":"native_select","path_id":path["id"],"entry_id":point["entry_id"],"node_id":point["node_id"],"xy":xy,"selected":[list(p) for p in panel._selection]})

    try:
        controller.bootstrap();wait(lambda:not controller.busy)
        controller.open_project(Path(config["project"]),ignore_recovery=True);wait(lambda:not controller.busy and controller.project is not None)
        window.navigation.setCurrentRow(2);window.compact_tabs.setCurrentIndex(1)
        width,height=config.get("size",[1672,941]);window.setGeometry(60,60,width,height);stable()
        phase=config.get("phase","primary")
        report["dpr"]=window.devicePixelRatioF();report["client_size"]=[window.width(),window.height()]
        report["screen_geometry"]=list(window.screen().geometry().getRect())
        report["checks"]["identity_and_version"]=window.brand.text()==APP_NAME and bool(VERSION_LABEL) and VERSION_LABEL in window.windowTitle()
        report["checks"]["requested_runtime"]=report["frozen"]==config.get("frozen",False)
        report["checks"]["requested_dpr"]=abs(report["dpr"]-config.get("dpr",1))<.05
        if phase=="restore":
            expected=json.loads(Path(config["expected"]).read_text(encoding="utf-8"))
            report["checks"]["fresh_project_state"]=snapshot_to_dict(controller.plot_state)==expected["state"]
            actual=next(n for n in controller.project.nodes if n.id==expected["node_id"]).expression
            report["checks"]["last_expression_restored"]=snapshot_to_dict(actual)==expected["expression"]
            report["checks"]["fresh_three_camera"]=js("window.grpr.renderer3d.viewport()")==expected["camera"]
            editor=ExpressionDialog(controller,node_id=expected["node_id"],language=window.language,parent=window);editor.show();QTest.qWait(200)
            capture("editor-fresh-process",editor);editor.reject();wait(lambda:not editor.isVisible());editor=None
            capture("restored-default")
        else:
            controller.set_plot_state(mode="3d",compare=True,hidden_paths=[],viewports={},details_visible=True,details_drawer_open=False);stable()
            a,b=panel.last_payload["paths"][:2];point=a["points"][1]
            window.chart_selected(a["id"],point["node_id"],point["entry_id"]);panel.set_table_selection([(a["id"],point["entry_id"])]);stable()
            wait(lambda:js("Boolean(window.profileInspector.molecule?.diagnostics().objects)"),15)
            report["checks"]["actual_three_and_molecule"]=js("window.grpr.diagnostics().three_version==='170'&&window.grpr.diagnostics().curtains===2&&Boolean(window.profileInspector.molecule?.diagnostics().objects)")
            report["webgl_device"]=js("(()=>{const gl=window.grpr.renderer3d.renderer.getContext(),e=gl.getExtension('WEBGL_debug_renderer_info');return {version:gl.getParameter(gl.VERSION),vendor:e?gl.getParameter(e.UNMASKED_VENDOR_WEBGL):gl.getParameter(gl.VENDOR),renderer:e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}})()")
            expected_values=[[0,15.060,-5.020,-15.688],[0,11.420,-2.800,-12.400]]
            report["checks"]["scientific_oracle"]=all(abs(n["value"]-v)<.00001 for p,row in zip(panel.last_payload["paths"],expected_values) for n,v in zip(p["points"],row))
            if width<=1000:
                js("document.getElementById('show-details').click()");stable()
                report["checks"]["narrow_details_drawer"]=js("document.body.classList.contains('mobile-details-open')")
            capture("default-3d")
            if phase=="primary":
                origin=panel.webview.mapTo(window,QPoint(0,0))
                regions=js("Object.fromEntries(['main-column','profile-toolbar','inspector-shell','bottom-tools','orientation-placeholder','molecule-placeholder','details-fields','overview-placeholder','table-placeholder'].map(id=>{const e=document.getElementById(id),r=e.getBoundingClientRect();return [id,{x:r.x,y:r.y,w:r.width,h:r.height,scrollHeight:e.scrollHeight,clientHeight:e.clientHeight}]}))")
                for r in regions.values():r["x"]+=origin.x();r["y"]+=origin.y()
                expected={"main-column":[208,59,1056,871],"profile-toolbar":[216,69,1035,49],"inspector-shell":[1272,59,387,854],"bottom-tools":[477,854,441,56],"orientation-placeholder":[216,747,150,155]}
                report["regions"]=regions;report["boundary_errors"]={k:max(abs(regions[k][a]-v) for a,v in zip(("x","y","w","h"),values)) for k,values in expected.items()}
                report["checks"]["macro_layout"]=max(report["boundary_errors"].values())<=4
                report["checks"]["right_panel_no_scroll"]=regions["inspector-shell"]["scrollHeight"]<=regions["inspector-shell"]["clientHeight"]+1
                diag=js("window.grpr.diagnostics()");bounds=diag["bounds"];size=js("[document.getElementById('plot').clientWidth,document.getElementById('plot').clientHeight]")
                report["coverage"]=[(max(p[a] for p in bounds)-min(p[a] for p in bounds))/s for a,s in zip(("x","y"),size)]
                report["checks"]["default_coverage"] = .88<=report["coverage"][0]<=.94 and .76<=report["coverage"][1]<=.86
                report["label_metrics"]=js("(()=>{const e=[...document.querySelectorAll('.scene-label')].map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,font:parseFloat(getComputedStyle(e).fontSize),text:e.textContent}});return {labels:e,overlaps:e.flatMap((a,i)=>e.slice(0,i).filter(b=>Math.min(a.x+a.w,b.x+b.w)>Math.max(a.x,b.x)&&Math.min(a.y+a.h,b.y+b.h)>Math.max(a.y,b.y))).length}})()")
                report["checks"]["readable_node_labels"]=report["label_metrics"]["overlaps"]==0 and min(n["font"] for n in report["label_metrics"]["labels"])>=16
                report["checks"]["one_webengine_no_old_toolbar"]=len(window.findChildren(type(panel.webview)))==1 and not panel.toolbar_panel.isVisible()
                # Native pointer drag, with renderer frame times measured in Chromium.
                js("(()=>{const s=window.grpr.renderer3d;window.__rf7Draw=s.draw.bind(s);window.__rf7Frames=[];s.draw=()=>{const start=performance.now();window.__rf7Draw();window.__rf7Frames.push({at:performance.now(),ms:performance.now()-start})};window.__rf7Trusted=[];document.addEventListener('pointermove',e=>{if(e.isTrusted&&e.buttons)window.__rf7Trusted.push(performance.now())});return true})()")
                before=js("window.grpr.renderer3d.viewport()");drag(150,30,120)
                frames=js("window.__rf7Frames");trusted=js("window.__rf7Trusted")
                active=[f for f in frames if trusted and trusted[0]<=f["at"]<=trusted[-1]+30]
                fps=(len(active)-1)*1000/(active[-1]["at"]-active[0]["at"]) if len(active)>1 else 0
                intervals=[active[i]["at"]-active[i-1]["at"] for i in range(1,len(active))]
                report["performance"]={"native_drag_fps":fps,"native_pointer_moves":len(trusted),"frames":len(active),"frame_interval_p50":percentile(intervals,.5),"frame_interval_p95":percentile(intervals,.95),"draw_ms_p50":percentile([f["ms"] for f in active],.5),"draw_ms_p95":percentile([f["ms"] for f in active],.95)}
                report["checks"]["native_orbit"]=js("window.grpr.renderer3d.viewport()")!=before
                report["checks"]["drag_fps_target"]=fps>=45 and len(active)>=30 and len(trusted)>=30
                capture("rotated");js("(()=>{window.grpr.renderer3d.draw=window.__rf7Draw;return true})()")
                js("window.grpr.workbenchAction({action:'dragmode',mode:'pan'})");stable();before=js("window.grpr.renderer3d.viewport().target");drag(45,-25)
                report["checks"]["native_pan"]=js("window.grpr.renderer3d.viewport().target")!=before;capture("panned")
                js("window.grpr.reset()");stable();select(b,b["points"][2])
                report["checks"]["native_select_and_details"]=panel._selection[-1]==(b["id"],b["points"][2]["entry_id"]) and panel.last_payload["inspector"]["detail"]["entry_id"]==b["points"][2]["entry_id"]
                select(a,point)
                latency=[]
                for node in [a["points"][2],point,a["points"][3],point,a["points"][0],point]:
                    js("(()=>{window.__rf7Latency={};const id="+json.dumps(node["entry_id"])+";const down=e=>{if(!e.isTrusted)return;document.removeEventListener('pointerdown',down);const start=performance.now();function poll(){const d=window.grpr.shown.inspector;if(d?.detail?.entry_id===id){window.__rf7Latency.selection??=performance.now()-start;if(d.structure?.status==='available'){window.__rf7Latency.details=performance.now()-start;return;}}if(performance.now()-start<5000)requestAnimationFrame(poll);}requestAnimationFrame(poll);};document.addEventListener('pointerdown',down);return true})()")
                    select(a,node);wait(lambda:js("Boolean(window.__rf7Latency.details)"));latency.append(js("window.__rf7Latency"))
                report["performance"]["selection_ms_p50"]=percentile([r["selection"] for r in latency],.5);report["performance"]["selection_ms_p95"]=percentile([r["selection"] for r in latency],.95)
                report["performance"]["details_ms_p50"]=percentile([r["details"] for r in latency],.5);report["performance"]["details_ms_p95"]=percentile([r["details"] for r in latency],.95)
                report["performance"]["latency_samples"]=latency
                report["checks"]["selection_latency_target"]=report["performance"]["selection_ms_p95"]<100
                report["checks"]["details_latency_target"]=report["performance"]["details_ms_p95"]<200
                js("window.grpr.workbenchAction({action:'path',path_id:"+json.dumps(b["id"])+",visible:false})");stable();capture("hidden-b")
                report["checks"]["path_hide"]=js("window.grpr.diagnostics().curtains") == 1
                js("window.grpr.workbenchAction({action:'path',path_id:"+json.dumps(b["id"])+",visible:true})");stable()
                samples=[]
                for count in (0,20,50,100):
                    if count:js("(()=>{const s=window.grpr.renderer3d;for(let i=0;i<"+str(count-(samples[-1]["updates"] if samples else 0))+";i++){s.setData(window.grpr.shown);s.draw();}return true})()")
                    QTest.qWait(100);samples.append({"updates":count,"scene":js("window.grpr.diagnostics()"),"memory":memory_snapshot()})
                report["resource_samples"]=samples;keys=("objects","pick_objects","labels","geometries","textures","listeners")
                report["checks"]["stable_100_updates"]=all(all(r["scene"][k]==samples[0]["scene"][k] for k in keys) for r in samples)
                report["checks"]["webengine_memory_recorded"]=all(any(not p["ui"] for p in r["memory"]["processes"]) for r in samples)
                QTest.qWait(350);f=js("window.grpr.diagnostics().frames");m=js("window.profileInspector.molecule.diagnostics().frames");QTest.qWait(400)
                report["checks"]["idle_scenes_stop"]=js("window.grpr.diagnostics().frames")==f and js("window.profileInspector.molecule.diagnostics().frames")==m
                for view,language in (("2d","en"),("2d","zh_CN"),("3d","en")):
                    window.language_combo.setCurrentIndex(window.language_combo.findData(language));stable()
                    js("window.grpr.workbenchAction({action:'mode',mode:"+json.dumps(view)+"})");wait(lambda view=view:panel.last_payload["view"]==view);stable()
                    if view=="2d":capture("two-d-"+language)
                report["checks"]["two_d_three_d_selection_retained"]=panel._selection[-1]==(a["id"],point["entry_id"])
                # Every publication uses the production worker and frozen Agg entry.
                for format in ("png","html","workbench_png"):
                    dest=out/("export-3d-"+format);assert panel.export_to(dest,format,language="en")
                    wait(lambda dest=dest:(dest/"manifest.json").is_file() and not controller.busy and not panel._capture);stable()
                report["checks"]["new_renderer_exports"]=json.loads((out/"export-3d-png/manifest.json").read_text())["raster_source"]=="Three.js ProfileRenderer.capture"
                js("window.grpr.workbenchAction({action:'mode',mode:'2d'})");stable()
                for format in ("png","svg","pdf"):
                    dest=out/("export-2d-"+format);assert panel.export_to(dest,format,language="en");wait(lambda dest=dest:(dest/"manifest.json").is_file() and not controller.busy);stable()
                report["checks"]["paper_exports"]=all((out/("export-2d-"+f)/("profile."+f)).is_file() for f in ("png","svg","pdf"))
                js("window.grpr.workbenchAction({action:'mode',mode:'3d'})");stable();js("window.grpr.reset()");stable()
                node_id=point["node_id"];editor=ExpressionDialog(controller,node_id=node_id,language="en",parent=window);editor.show();editor.tabs.setCurrentIndex(1)
                original=editor.text.toPlainText();editor.text.setFocus();editor.text.moveCursor(QTextCursor.MoveOperation.End);QTest.keyClicks(editor.text," + 0.000001")
                capture("editor-before-save",editor);QTest.mouseClick(editor.save_button,Qt.MouseButton.LeftButton)
                wait(lambda:not controller.busy and not editor._save_requested);capture("editor-saved",editor)
                report["checks"]["explicit_expression_saved"]=str(controller.path) in editor.save_status.text()
                saved=controller.backend.save
                def failure(*args,**kwargs):raise StorageError("rf7_injected_save_failure")
                controller.backend.save=failure;editor.text.moveCursor(QTextCursor.MoveOperation.End);QTest.keyClicks(editor.text," + 0.000001");QTest.mouseClick(editor.save_button,Qt.MouseButton.LeftButton)
                wait(lambda:not controller.busy and not editor._save_requested);capture("editor-save-failed",editor)
                report["checks"]["save_failure_keeps_editor_and_draft"]=editor.isVisible() and editor.save_button.isEnabled() and "0.000001 + 0.000001" in editor.text.toPlainText()
                controller.backend.save=saved;QTest.mouseClick(editor.save_button,Qt.MouseButton.LeftButton);wait(lambda:not controller.busy and not editor._save_requested)
                editor.reject();wait(lambda:not editor.isVisible());editor=None;stable();controller.save();wait(lambda:not controller.busy);stable()
                expected={"state":snapshot_to_dict(controller.plot_state),"camera":js("window.grpr.renderer3d.viewport()"),"node_id":node_id,
                    "expression":snapshot_to_dict(next(n for n in controller.project.nodes if n.id==node_id).expression)}
                (out/"restart-expected.json").write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding="utf-8")
                with ProjectRepository(controller.path,read_only=True) as repo:
                    disk=repo.load()
                report["checks"]["last_input_on_disk"]=snapshot_to_dict(next(n for n in disk.nodes if n.id==node_id).expression)==expected["expression"]
            else:
                report["checks"]["toolbar_fits_or_scrolls"]=js("(()=>{const e=document.getElementById('profile-toolbar');return e.clientWidth>0&&e.scrollWidth>=e.clientWidth})()")
                js("window.grpr.workbenchAction({action:'mode',mode:'2d'})");stable();capture("two-d")
        report["javascript_errors"]=panel.javascript_errors;report["blocked_requests"]=panel.blocked_requests
        report["checks"]["no_js_or_remote_errors"]=not panel.javascript_errors and not panel.blocked_requests
        report["resource_sha256"]={p.relative_to(resources).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in resources.rglob("*") if p.is_file()}
        if report["frozen"]:report["executable_sha256"]=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
        report["passed"]=all(report["checks"].values())
    except Exception as error:
        report["error"]=str(error);report["traceback"]=traceback.format_exc()
    finally:
        if editor is not None:editor.timer.stop();editor._dirty=False;editor.reject()
        (out/"validation.json").write_text(json.dumps(snapshot_to_dict(report),ensure_ascii=False,indent=2),encoding="utf-8")
        controller._workspace_timer.stop()
        if not controller.busy and not controller._closed:controller.close();wait(lambda:controller._closed)
        window.close();app.quit()
    return 0 if report["passed"] else 1
