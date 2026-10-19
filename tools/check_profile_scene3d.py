"""RF3: visible source application, real WebEngine, measured client/DOM boundaries.

Run on the interactive Windows desktop. Captures are unmodified Qt window grabs.
Only the current process uses the documented compatibility CPU affinity.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import monotonic
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--restore-only", action="store_true", help="Fresh-process camera restore from previous run's saved project")
    parser.add_argument("--scale-factor", default="0.8", help="0.8 × this desktop's 125%% scale gives DPR 1")
    args = parser.parse_args()
    os.environ["QT_SCALE_FACTOR"] = args.scale_factor
    os.environ.pop("QT_QPA_PLATFORM", None)
    from diagnose_static_runtime import windows_affinity
    modes, _, select_affinity = windows_affinity()
    affinity = modes["default"] & 0xFFFFFF3F
    select_affinity(affinity)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.storage import ProjectRepository
    from gaussianreadpro.storage.preferences import LocalPreferences
    from gaussianreadpro.ui.main_window import MainWindow
    import gaussianreadpro.ui.main_window as main_module
    from gaussianreadpro.ui.theme import apply_theme

    folder = ROOT / "artifacts/rf3"
    folder.mkdir(parents=True, exist_ok=True)
    prefs = folder / "preferences.ini"
    LocalPreferences(prefs).save(language="en", theme="dark", window_geometry=None, recent_projects=[], reduce_motion=True)
    fixture = ROOT / "artifacts/rf0/profile-replica.grproj"
    project_file = folder / "rf3-scene.grproj"
    if not project_file.exists():
        with ProjectRepository(fixture, read_only=True) as repo:
            project = repo.load()
        with ProjectRepository(project_file, create=True) as repo:
            repo.save(project)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app, "dark", reduce_motion=True)
    controller = ProjectController(folder / "recovery", prefs)

    class IdentifiedWindow(MainWindow):
        def setWindowTitle(self, text):
            super().setWindowTitle(str(text) + f" [RF3 source · PID {os.getpid()}]")

    window = IdentifiedWindow(controller)
    window.show()
    report = {"stage": "RF3", "passed": False, "pid": os.getpid(), "source_module": main_module.__file__,
              "affinity": hex(affinity), "screenshots": [], "checks": {}}
    bridge_events=[]

    def wait_for(predicate, timeout=30):
        deadline = monotonic() + timeout
        while not predicate():
            QTest.qWait(30)
            if monotonic() > deadline:
                raise TimeoutError(f"RF3 wait timed out; operation={controller.operation}; JS={window.profile.javascript_errors}; failure={window.profile.failure}; last_events={bridge_events[-4:]}")
        QTest.qWait(80)

    def js(code):
        result = []
        window.profile.page.runJavaScript('JSON.stringify(eval('+json.dumps(code)+'))', lambda value: result.append(value))
        wait_for(lambda: bool(result), 15)
        return json.loads(result[0]) if result[0] else None

    def stable():
        QTest.qWait(550)  # Let the existing 400 ms workspace persistence finish first.
        wait_for(lambda: not controller.busy and window.profile.ready and window.profile.summary.get("render_id") == (window.profile.last_payload or {}).get("render_id"))
        wait_for(lambda: js("Boolean(window.grpr.shown && !window.grpr.queueState.running && !window.grpr.queueState.pending && !window.grpr.queueState.resizePending && window.grpr.shown.render_id === " + str(window.profile.last_payload["render_id"]) + ")"))

    def capture(name):
        window.raise_()
        window.activateWindow()
        QTest.qWait(250)
        window.repaint()
        QTest.qWait(250)
        image = window.grab()
        path = folder / name
        if not image.save(str(path)):
            raise RuntimeError("Screenshot could not be saved")
        report["screenshots"].append({"path": str(path), "pixels": [image.width(), image.height()], "dpr": image.devicePixelRatio(),
                                      "sha256": sha256(path.read_bytes()).hexdigest(), "capture": "Unmodified QWidget.grab of the real visible Qt/WebEngine application client"})

    try:
        controller.bootstrap()
        wait_for(lambda: not controller.busy)
        controller.open_project(project_file, ignore_recovery=True)
        wait_for(lambda: not controller.busy and controller.project is not None)
        if args.restore_only:
            window.navigation.setCurrentRow(2);window.compact_tabs.setCurrentIndex(1);window.setGeometry(80,80,1672,941)
            stable()
            expected=json.loads((folder/'restart-expected.json').read_text())
            actual=js('window.grpr.diagnostics().viewport')
            report['expected']=expected;report['actual']=actual
            report['checks']['fresh_process_camera_restore']=expected==actual
            report['checks']['three_webgl_renderer']=js('window.grpr.diagnostics().three_version')=='170'
            js('window.grpr.renderer3d.orbit(45,0);window.grpr.renderer3d.invalidate()')
            window.profile._camera_preset_changed(4)
            QTest.qWait(200)
            report['checks']['saved_camera_menu_uses_three_state']=js('window.grpr.diagnostics().viewport')==expected
            report['source_hashes']={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in [ROOT/'src/gaussianreadpro/ui/profile_view.py',ROOT/'src/gaussianreadpro/resources/plot/profile.js',ROOT/'src/gaussianreadpro/resources/plot/scene3d.js',ROOT/'src/gaussianreadpro/resources/plot/replica.css']}
            capture('rf3-fresh-process-restored.png')
            report['passed']=all(report['checks'].values())
            controller.close();wait_for(lambda: controller._closed)
            return 0 if report['passed'] else 1
        controller.set_plot_state(mode="3d", compare=True, hidden_paths=[], viewports={})
        window.navigation.setCurrentRow(2)
        window.compact_tabs.setCurrentIndex(1)
        window.setGeometry(80, 80, 1672, 941)
        stable()
        window.profile.bridge.eventSignal.connect(lambda raw: bridge_events.append(json.loads(raw)))
        selected = window.profile.last_payload["paths"][0]["points"][1]
        window.chart_selected(window.profile.last_payload["paths"][0]["id"], selected["node_id"], selected["entry_id"])
        window.profile.set_table_selection([(window.profile.last_payload["paths"][0]["id"], selected["entry_id"])])
        stable()
        report["screen"] = {"geometry": list(window.screen().geometry().getRect()), "dpr": window.devicePixelRatioF(), "platform": app.platformName()}
        report["client_size"] = [window.width(), window.height()]
        origin = window.profile.webview.mapTo(window, QPoint(0, 0))
        dom = json.loads(js("JSON.stringify(Object.fromEntries(['main-column','profile-toolbar','inspector-shell','molecule-placeholder','details-fields','overview-placeholder','table-placeholder','bottom-tools','orientation-placeholder'].map(id=>{const e=document.getElementById(id),r=e.getBoundingClientRect();return [id,{x:r.x,y:r.y,w:r.width,h:r.height,scrollHeight:e.scrollHeight,clientHeight:e.clientHeight}]})))"))
        for row in dom.values():
            row["x"] += origin.x()
            row["y"] += origin.y()
        report["regions"] = dom
        expected = {"main-column": [208, 59, 1056, 871], "profile-toolbar": [216, 69, 1035, 49], "inspector-shell": [1272, 59, 387, 854],
                    "bottom-tools": [477, 854, 441, 56], "orientation-placeholder": [216, 747, 150, 155]}
        errors = {key: max(abs(actual[k] - target) for k, target in zip(("x", "y", "w", "h"), values)) for key, values in expected.items() for actual in [dom[key]]}
        report["boundary_errors_dip"] = errors
        topbar, sidebar = window.findChild(type(window.sidebar), "topbar"), window.sidebar
        report["qt_regions"] = {"topbar": list(topbar.geometry().getRect()), "sidebar": list(sidebar.geometry().getRect()), "webview_origin": [origin.x(), origin.y()]}
        report["checks"]["fixed_canvas"] = report["client_size"] == [1672, 941] and abs(window.devicePixelRatioF() - 1) < .01
        report["checks"]["macro_boundaries"] = max(errors.values()) <= 4 and topbar.height() == 50 and sidebar.width() == 196
        report["checks"]["single_webengine"] = len(window.findChildren(type(window.profile.webview))) == 1
        report["checks"]["no_old_toolbar_or_tabs"] = not window.profile.toolbar_panel.isVisible() and not window.compact_tabs.isVisible()
        report["checks"]["right_panel_no_scroll"] = dom["inspector-shell"]["scrollHeight"] <= dom["inspector-shell"]["clientHeight"] + 1
        capture("rf3-en-dark-1672x941.png")
        diag = json.loads(js("JSON.stringify(window.grpr.diagnostics())"))
        report["initial_scene"] = diag
        report["checks"]["three_webgl_renderer"] = diag["three_version"] == "170" and diag["pick_objects"] == 8 and diag["curtains"] == 2
        bounds = diag["bounds"]
        width, height = js("[document.getElementById('plot').clientWidth,document.getElementById('plot').clientHeight]")
        coverage = [(max(p[axis] for p in bounds)-min(p[axis] for p in bounds))/size for axis, size in (("x",width),("y",height))]
        report["default_bounds_fraction"] = coverage
        report["checks"]["default_fit"] = .88 <= coverage[0] <= .94 and .76 <= coverage[1] <= .86
        report["checks"]["common_energy_axis"] = diag["z_range"] == [-20,20]
        labels = json.loads(js("JSON.stringify([...document.querySelectorAll('.scene-label')].map(e=>{const r=e.getBoundingClientRect();return {text:e.textContent,x:r.x,y:r.y,w:r.width,h:r.height}}))"))
        overlaps = [(i,j) for i,a in enumerate(labels) for j,b in enumerate(labels[:i]) if min(a['x']+a['w'],b['x']+b['w'])>max(a['x'],b['x']) and min(a['y']+a['h'],b['y']+b['h'])>max(a['y'],b['y'])]
        report["checks"]["eight_readable_labels"] = len(labels) == 8 and not overlaps

        def mouse_point(x,y):
            web = window.profile.webview
            target = web.focusProxy() or web
            window.raise_(); window.activateWindow(); web.setFocus()
            return window.windowHandle(), web.mapTo(window,QPoint(round(x),round(y)))

        def drag(x,y,dx,dy):
            target,point=mouse_point(x,y)
            QTest.mouseMove(target,point)
            QTest.qWait(100)
            QTest.mousePress(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point)
            for i in range(1,9):
                QTest.mouseMove(target,point+QPoint(round(dx*i/8),round(dy*i/8)),25)
            QTest.mouseRelease(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point+QPoint(dx,dy))
            QTest.qWait(650)
            stable()

        bpath = window.profile.last_payload['paths'][1]
        bpoint = bpath['points'][2]
        xy = js('window.grpr.pointPosition('+json.dumps(bpath['id'])+','+json.dumps(bpoint['entry_id'])+')')
        target,point=mouse_point(xy['x'],xy['y'])
        js("window.rf3Mouse=[];['pointerdown','pointermove','pointerup'].forEach(k=>document.addEventListener(k,e=>window.rf3Mouse.push({type:k,trusted:e.isTrusted,x:e.clientX,y:e.clientY,buttons:e.buttons,target:e.target.className})));true")
        QTest.mouseMove(target,point)
        QTest.qWait(150)
        QTest.mouseClick(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point)
        stable()
        report["checks"]["real_mouse_identity_selection"] = (bpath['id'],bpoint['entry_id']) in window.profile._selection
        report['selection_debug']={'xy':xy,'selection':window.profile._selection,'events':bridge_events[-4:]}
        camera_before = js('window.grpr.diagnostics().viewport')
        drag(400,170,160,65)
        camera_after = js('window.grpr.diagnostics().viewport')
        report["checks"]["real_mouse_orbit_and_drag_threshold"] = camera_before != camera_after and (bpath['id'],bpoint['entry_id']) in window.profile._selection
        from gaussianreadpro.core.models import snapshot_to_dict
        report["checks"]["camera_persisted"] = any(snapshot_to_dict(v.get('three_v1')) == camera_after for v in controller.plot_state.get('viewports',{}).values())
        capture('rf3-rotated-transparency.png')
        drag(400,170,280,-55)
        capture('rf3-back-transparency.png')
        report['checks']['transparent_curtains_no_depth_writes']=js("window.grpr.renderer3d.group.children.filter(o=>o.userData.decoration==='curtain').every(o=>o.material.depthWrite===false && o.material.transparent)")
        js("document.querySelector('[data-drag=pan]').click()")
        stable()
        before_pan = js('window.grpr.diagnostics().viewport')
        drag(600,200,50,-35)
        after_pan = js('window.grpr.diagnostics().viewport')
        report["checks"]["real_mouse_pan"] = before_pan['target'] != after_pan['target']
        cube = js("(()=>{const s=window.grpr.renderer3d,t=s.cubeTargets.find(t=>t.direction[2]===1),r=s.cubeCanvas.getBoundingClientRect();return {x:r.x+t.x*r.width/150,y:r.y+t.y*r.height/155}})()")
        target,point=mouse_point(cube['x'],cube['y'])
        QTest.mouseClick(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point)
        stable()
        cube_view=js('window.grpr.diagnostics().viewport')
        report['checks']['live_cube_axis_click'] = abs(cube_view['position'][0]-cube_view['target'][0])<1e-6 and abs(cube_view['position'][1]-cube_view['target'][1])<1e-6 and cube_view['up']==[0,1,0]
        capture('rf3-top-view.png')
        js("document.getElementById('reset-control').click()")
        stable()
        report['checks']['reset_camera'] = js('window.grpr.diagnostics().viewport.zoom') == 1
        # An explicit legacy preset is migrated in real WebGL, then passed through Python's allowlist.
        legacy={'eye':{'x':-1.1,'y':-1.9,'z':1.05},'center':{'x':.1,'y':0,'z':0},'up':{'x':0,'y':0,'z':1}}
        js('window.grpr.setCamera('+json.dumps(legacy)+')')
        stable()
        migrated=js('window.grpr.diagnostics()')
        expected_target=[.1*migrated['extent'][0]/2,0,0]
        expected_position=[legacy['eye'][a]*migrated['extent'][i]/2+expected_target[i] for i,a in enumerate(('x','y','z'))]
        report['checks']['explicit_legacy_conversion'] = migrated['migration']=='plotly-v1' and all(abs(a-b)<1e-8 for a,b in zip(expected_position,migrated['viewport']['position']))
        report['migration_debug']=migrated
        # Recreate the renderer to exercise a fresh Three scene against persisted clean state.
        saved_view=migrated['viewport']
        js("window.grpr.renderer3d.context=null;window.grpr.renderer3d.setData({...window.grpr.shown,viewport:{three_v1:"+json.dumps(saved_view)+"}})")
        QTest.qWait(250)
        report['checks']['new_scene_camera_restore'] = js('window.grpr.diagnostics().viewport') == saved_view
        js("document.getElementById('reset-control').click()")
        stable()
        report['resource_samples']=json.loads(js("JSON.stringify((()=>{const s=window.grpr.renderer3d,rows=[];for(let i=0;i<100;i++){s.setData(window.grpr.shown);s.draw();if(i===0||i===49||i===99)rows.push(s.diagnostics());}return rows;})())"))
        report['checks']['bounded_100_updates'] = all(all(row[key]==report['resource_samples'][0][key] for key in ('objects','pick_objects','labels','geometries','textures','listeners')) for row in report['resource_samples'])
        QTest.qWait(350)
        frames=js('window.grpr.diagnostics().frames')
        QTest.qWait(500)
        report['checks']['idle_no_permanent_raf'] = js('window.grpr.diagnostics().frames')==frames and not js('window.grpr.diagnostics().raf_pending')
        report['checks']['html_tooltip_all_sources'] = js("document.querySelector('.scene-tooltip').textContent.includes('Multiple sources') && document.querySelector('.scene-tooltip').textContent.includes('Job 1') && document.querySelector('.scene-tooltip').textContent.includes('line 4')")
        report['checks']['capture_png'] = js("window.grpr.renderer3d.capture().startsWith('data:image/png;base64,')")
        report['mouse_events']=js('window.rf3Mouse')
        scientific_values = [[p["value"] for p in path["points"]] for path in window.profile.last_payload["paths"]]
        scene_frames=js('window.grpr.diagnostics().frames')
        js("document.querySelector('[data-mode=\"2d\"]').click()")
        wait_for(lambda: (window.profile.last_payload or {}).get("view") == "2d")
        stable()
        report["checks"]["dimension_button"] = window.profile.last_payload["view"] == "2d"
        QTest.qWait(450)
        report['checks']['hidden_three_stops_raf']=js('window.grpr.diagnostics().frames')<=scene_frames+1
        js("document.querySelector('[data-mode=\"3d\"]').click()")
        wait_for(lambda: (window.profile.last_payload or {}).get("view") == "3d")
        stable()
        js("document.querySelectorAll('#path-controls button')[1].click()")
        wait_for(lambda: bool(window.profile.state.get("hidden_paths")))
        stable()
        js("document.querySelectorAll('#path-controls button')[1].click()")
        wait_for(lambda: not window.profile.state.get("hidden_paths"))
        stable()
        report["checks"]["path_controls"] = all(p["visible"] for p in window.profile.last_payload["paths"])
        js("document.getElementById('compare-control').click()")
        wait_for(lambda: not window.profile.state.get("compare"))
        stable()
        js("document.getElementById('compare-control').click()")
        wait_for(lambda: window.profile.state.get("compare"))
        stable()
        report["checks"]["compare_control"] = len(window.profile.last_payload["paths"]) == 2
        # Feed a real Python-generated missing-value run to the renderer, without mutating the project.
        from copy import deepcopy
        from gaussianreadpro.core.plot_spec import visual_curve_runs
        gap=deepcopy(window.profile.last_payload)
        gap['paths'][1]['points'][1].update(valid=False,value=None,value_label='—',selected=False)
        gap['paths'][1]['curve_runs']=visual_curve_runs([(p['x'],p['value']) if p['valid'] else None for p in gap['paths'][1]['points']])
        js('window.grpr.renderer3d.setData('+json.dumps(gap)+')')
        QTest.qWait(100)
        report['checks']['invalid_node_gap_and_pick_exclusion']=js('window.grpr.diagnostics().pick_objects')==7 and js('window.grpr.renderer3d.data.paths[1].curve_runs.length')==2
        js('window.grpr.renderer3d.setData(window.grpr.shown)')
        QTest.qWait(100)
        window.profile.page.runJavaScript('window.GRPR_FORCE_NO_WEBGL=true')
        window.profile._fingerprint=None;window.profile.refresh()
        wait_for(lambda: window.profile.last_payload.get('view')=='2d')
        stable()
        report['checks']['explicit_webgl_fallback']=bool(js("document.getElementById('notice').textContent.includes('showing 2D')"))
        report['fallback_notice']=js("document.getElementById('notice').textContent")
        js("window.GRPR_FORCE_NO_WEBGL=false;document.querySelector('[data-mode=\"3d\"]').click()")
        stable()
        report["checks"]["scientific_values_unchanged"] = [[p["value"] for p in path["points"]] for path in window.profile.last_payload["paths"]] == scientific_values
        for row in range(3, 11):
            window.navigation.setCurrentRow(row)
            app.processEvents()
            assert window.stack.currentIndex() == row
        report["checks"]["independent_analysis_routes"] = True
        window.navigation.setCurrentRow(2)
        window.language_combo.setCurrentIndex(window.language_combo.findData("zh_CN"))
        window.theme_combo.setCurrentIndex(window.theme_combo.findData("light"))
        window.resize(1440, 900)
        stable()
        capture("rf3-cn-light-1440x900.png")
        report["checks"]["cn_light_smoke"] = window.profile.last_payload["language"] == "zh_CN" and not window.profile.last_payload["dark"]
        window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
        window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark"))
        window.resize(1672, 941)
        stable()
        report["javascript_errors"] = window.profile.javascript_errors
        report["renderer"] = {"name": "Three.js dedicated renderer", "runtime_version": window.profile.summary.get("three_version"), "view": window.profile.summary.get("view")}
        report["checks"]["javascript_no_errors"] = not window.profile.javascript_errors
        drag(400,170,-90,25)
        expected=js('window.grpr.diagnostics().viewport')
        (folder/'restart-expected.json').write_text(json.dumps(expected),encoding='utf-8')
        report['restart_expected']=expected
        assert controller.save(project_file)
        wait_for(lambda: not controller.busy)
        report["source_hashes"] = {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in [ROOT / "src/gaussianreadpro/ui/main_window.py", ROOT / "src/gaussianreadpro/ui/profile_view.py", ROOT / "src/gaussianreadpro/services/controller.py", ROOT / "src/gaussianreadpro/core/plot_spec.py", ROOT / "src/gaussianreadpro/ui/theme.py", ROOT / "src/gaussianreadpro/ui/glass_widgets.py", ROOT / "src/gaussianreadpro/presentation/palette.py", ROOT / "src/gaussianreadpro/resources/themes/lavender_sunset.json", *[ROOT / "src/gaussianreadpro/resources/plot" / name for name in ("profile.html", "profile.js", "scene3d.js", "replica.css", "replica_controls.js")], *sorted((ROOT / "src/gaussianreadpro/resources/icons").glob("*.svg"))]}
        manifest=json.loads((ROOT/'src/gaussianreadpro/resources/plot/vendor/three-manifest.json').read_text(encoding='utf-8-sig'))
        report['checks']['offline_three_assets']=all(sha256((ROOT/'src/gaussianreadpro/resources/plot/vendor'/asset['file']).read_bytes()).hexdigest()==asset['sha256'] for asset in manifest['assets']) and not window.profile.blocked_requests
        report["passed"] = all(report["checks"].values())
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        report['bridge_events_tail']=bridge_events[-12:]
        (folder / ("restore-validation.json" if args.restore_only else "validation.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k:report[k] for k in ('stage','passed','pid','checks')} | {'error':report.get('error')}, ensure_ascii=False, indent=2), flush=True)
    if args.keep_open and report["passed"]:
        return app.exec()
    controller.close()
    wait_for(lambda: controller._closed)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
