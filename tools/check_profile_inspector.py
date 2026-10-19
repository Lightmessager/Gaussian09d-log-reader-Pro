"""RF4: visible source application, real WebEngine, measured client/DOM boundaries.

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
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]


def main():
    parser = argparse.ArgumentParser()
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

    folder = ROOT / "artifacts/rf4"
    folder.mkdir(parents=True, exist_ok=True)
    prefs = folder / "preferences.ini"
    LocalPreferences(prefs).save(language="en", theme="dark", window_geometry=None, recent_projects=[], reduce_motion=True)
    from build_profile_rf4_fixture import main as fixture_builder
    fixture = fixture_builder()
    project_file = folder / ("rf4-scene-"+uuid4().hex[:10]+".grproj")
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
            super().setWindowTitle(str(text) + f" [RF4 source · PID {os.getpid()}]")

    window = IdentifiedWindow(controller)
    copied=[]
    window.profile.clipboard_writer=copied.append
    window.show()
    report = {"stage": "RF4", "passed": False, "pid": os.getpid(), "source_module": main_module.__file__,
              "affinity": hex(affinity), "screenshots": [], "checks": {}}
    report['project_file']=str(project_file)
    bridge_events=[]

    def wait_for(predicate, timeout=30):
        deadline = monotonic() + timeout
        while not predicate():
            QTest.qWait(30)
            if monotonic() > deadline:
                raise TimeoutError(f"RF4 wait timed out; operation={controller.operation}; JS={window.profile.javascript_errors}; failure={window.profile.failure}; last_events={bridge_events[-4:]}")
        QTest.qWait(80)

    def js(code):
        result = []
        window.profile.page.runJavaScript('JSON.stringify(eval('+json.dumps(code)+'))', lambda value: result.append(value))
        wait_for(lambda: bool(result), 15)
        return json.loads(result[0]) if result[0] else None

    def stable():
        QTest.qWait(550)  # Let the existing 400 ms workspace persistence finish first.
        wait_for(lambda: not controller.busy and not controller._workspace_timer.isActive() and not controller._pending_structure and (window.profile.last_payload or {}).get('inspector',{}).get('structure',{}).get('status')!='loading')
        wait_for(lambda: not controller.busy and window.profile.ready and window.profile.summary.get("render_id") == (window.profile.last_payload or {}).get("render_id"))
        wait_for(lambda: js("Boolean(window.grpr.shown && !window.grpr.queueState.running && !window.grpr.queueState.pending && !window.grpr.queueState.resizePending && window.grpr.shown.render_id === " + str(window.profile.last_payload["render_id"]) + ")"))
        wait_for(lambda: not controller.busy and (window.profile.last_payload or {}).get('inspector',{}).get('structure',{}).get('status')!='loading')

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
        controller.bootstrap();wait_for(lambda:not controller.busy)
        controller.open_project(project_file,ignore_recovery=True);wait_for(lambda:not controller.busy and controller.project is not None)
        controller.set_plot_state(mode='3d',compare=True,hidden_paths=[])
        window.navigation.setCurrentRow(2);window.compact_tabs.setCurrentIndex(1);window.setGeometry(80,80,1672,941)
        stable()
        window.profile.bridge.eventSignal.connect(lambda raw:bridge_events.append(json.loads(raw)))
        first=window.profile.last_payload['paths'][0]
        window.chart_selected(first['id'],first['points'][1]['node_id'],first['points'][1]['entry_id'])
        window.profile.set_table_selection([(first['id'],first['points'][1]['entry_id'])]);stable()
        wait_for(lambda: js('Boolean(window.profileInspector?.molecule?.key)'))
        vm=window.profile.last_payload['inspector'];d=vm['detail'];structure=vm['structure']
        report['checks']['real_three_molecule']=structure['status']=='available' and len(structure['atoms'])==4 and js('window.profileInspector.molecule.diagnostics().objects')==10
        report['checks']['standard_priority_provenance']=structure['orientation']=='Standard' and structure['atoms'][0]['xyz']==[0,0,0] and bool(structure['source_sha256']) and structure['line_start']>=structure['job_start'] and structure['line_end']<=structure['job_end']
        report['checks']['real_detail_energy_barrier']=d['value_label']=='+15.060' and d['barrier_label']=='+15.060' and d['absolute_hartree'] is not None
        report['checks']['explicit_id_table']=len(vm['table_rows'])==4 and all(r['paired'] for r in vm['table_rows'])
        report['checks']['overview_nodes_only']=js("document.querySelectorAll('#overview-chart circle[role=button]').length")==8
        report['checks']['source_trace_complete']=len(d['sources'])>=2 and all(s['line'] and s['source_sha256'] and s['job_ordinal'] for s in d['sources'])
        report['checks']['single_webengine']=len(window.findChildren(type(window.profile.webview)))==1
        report['checks']['source_is_synthetic']=structure['synthetic'] and 'Synthetic' in js("document.getElementById('structure-status').textContent")

        def click_selector(selector,modifiers=Qt.KeyboardModifier.NoModifier):
            r=js("(()=>{const r=document.querySelector("+json.dumps(selector)+").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
            location=window.profile.webview.mapTo(window,QPoint(round(r['x']),round(r['y'])))
            window.activateWindow();window.profile.webview.setFocus()
            QTest.mouseMove(window.windowHandle(),location);QTest.qWait(100)
            QTest.mouseClick(window.windowHandle(),Qt.MouseButton.LeftButton,modifiers,location)
            stable()

        b=window.profile.last_payload['paths'][1];node=b['points'][2]
        selector='#key-energy-table button[data-entry-id="'+node['entry_id']+'"]'
        click_selector(selector)
        report['checks']['real_table_click_selection']=window.profile.last_payload['inspector']['detail']['entry_id']==node['entry_id'] and js("document.querySelector('#overview-chart circle[data-entry-id=\""+node['entry_id']+"\"]').previousSibling.tagName") is not None
        a=window.profile.last_payload['paths'][0];node_a=a['points'][0]
        click_selector('#overview-chart circle[data-entry-id="'+node_a['entry_id']+'"]')
        report['checks']['real_overview_click_selection']=window.profile.last_payload['inspector']['detail']['entry_id']==node_a['entry_id'] and (a['id'],node_a['entry_id']) in window.profile._selection
        click_selector('#key-energy-table button[data-entry-id="'+node['entry_id']+'"]',Qt.KeyboardModifier.ControlModifier)
        js("document.getElementById('pair-steps').click()")
        stable()
        report['checks']['explicit_pair_action']=any({tuple(k) for k in g}=={(a['id'],node_a['entry_id']),(b['id'],node['entry_id'])} for g in controller.plot_state['step_pairs'])
        # Restore the fixture pair groups so the final visual evidence is the intended default.
        with ProjectRepository(fixture,read_only=True) as repo:original=repo.load()
        from gaussianreadpro.core.models import snapshot_to_dict
        controller.set_plot_state(step_pairs=snapshot_to_dict(original.plot_state['step_pairs']))
        window.profile.set_table_selection([(a['id'],a['points'][1]['entry_id'])]);window.chart_selected(a['id'],a['points'][1]['node_id'],a['points'][1]['entry_id']);stable()
        report['before_copy']={'detail':window.profile.last_payload['inspector']['detail'],'selection':window.profile._selection,'button':js("(()=>{const b=document.querySelector('[data-action=copy_value]');return {disabled:b.disabled,html:b.outerHTML}})()"),'shown':js('window.grpr.shown.render_id'),'current':window.profile.last_payload['render_id'],'revision':controller.project.revision,'payload_revision':window.profile.last_payload['revision']}
        js("document.querySelector('[data-action=copy_value]').click()")
        wait_for(lambda: bool(copied))
        report['checks']['guarded_copy_payload']=abs(float(copied[-1].split()[0])-15.06)<1e-8
        report['limitations']=['This final combined run records the clipboard writer payload. Real Qt Windows clipboard readback passed separately in PID 27448 (native-clipboard-validation.json), and the regular Qt regression also checks clipboard readback.']
        js("document.querySelector('[data-action=locate_source]').click()")
        js("document.querySelector('#source-list .source-link').click()")
        wait_for(lambda: hasattr(window,'_profile_source_dialog') and window._profile_source_dialog.isVisible())
        viewer=window._profile_source_dialog
        from PySide6.QtWidgets import QPlainTextEdit
        excerpt=viewer.findChild(QPlainTextEdit,'profileSourceExcerpt')
        report['checks']['verified_log_viewer']=bool(excerpt.textCursor().selectedText()) and 'Sum of electronic' in excerpt.toPlainText()
        viewer.close();stable()
        js("document.getElementById('source-list').hidden=true")
        # Real molecule drag, wheel mode bounds, idle behavior, reuse/disposal counts.
        r=js("(()=>{const r=document.querySelector('.molecule-canvas').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
        point=window.profile.webview.mapTo(window,QPoint(round(r['x']),round(r['y'])))
        before=js('window.profileInspector.molecule.diagnostics().rotation')
        QTest.mouseMove(window.windowHandle(),point);QTest.mousePress(window.windowHandle(),Qt.MouseButton.LeftButton,pos=point)
        QTest.mouseMove(window.windowHandle(),point+QPoint(35,16),50);QTest.mouseRelease(window.windowHandle(),Qt.MouseButton.LeftButton,pos=point+QPoint(35,16));QTest.qWait(200)
        report['checks']['real_molecule_rotation']=before!=js('window.profileInspector.molecule.diagnostics().rotation')
        QTest.mouseDClick(window.windowHandle(),Qt.MouseButton.LeftButton,pos=point);QTest.qWait(100)
        report['checks']['molecule_reset']=js('window.profileInspector.molecule.diagnostics().rotation')[:3]==[0,0,0]
        frames=js('window.profileInspector.molecule.diagnostics().frames');QTest.qWait(400)
        report['checks']['molecule_idle_no_raf']=frames==js('window.profileInspector.molecule.diagnostics().frames')
        samples=js("(()=>{const m=window.profileInspector.molecule,rows=[],original=window.grpr.shown.inspector.structure;for(let i=0;i<100;i++){m.setData({...original,line_start:original.line_start+(i%2)},true);m.renderer.render(m.scene,m.camera);if(i===0||i===49||i===99)rows.push(m.diagnostics());}m.setData(original,true);return rows;})()")
        report['resource_samples']=samples
        report['checks']['molecule_100_updates_bounded']=all(s['objects']==samples[0]['objects'] and s['geometries']==samples[0]['geometries'] for s in samples)
        js("document.querySelector('[data-action=hide]').click()")
        QTest.qWait(200);hidden_frames=js('window.profileInspector.molecule.diagnostics().frames');QTest.qWait(200)
        report['checks']['hidden_details_stop_molecule']=js("document.body.classList.contains('details-hidden')") and hidden_frames==js('window.profileInspector.molecule.diagnostics().frames')
        js("document.getElementById('show-details').click()")
        stable()
        # A real multi-source expression requires an explicit molecule choice.
        from gaussianreadpro.core.expressions import render_expression,compile_expression
        doc=next(n.expression for n in controller.project.nodes if n.id==a['points'][1]['node_id'])
        first_doc=next(n.expression for n in controller.project.nodes if n.id==a['points'][0]['node_id'])
        combined=compile_expression(render_expression(doc,controller.project.alias_bindings)+' + '+render_expression(first_doc,controller.project.alias_bindings),controller.project.alias_bindings).expression
        window.profile._molecule_choice=None
        assert controller.set_expression(combined,node_id=a['points'][1]['node_id'])
        stable()
        report['multi_source_debug']={'candidates':len(window.profile.last_payload['inspector']['structure_candidates']),'status':window.profile.last_payload['inspector']['structure']['status'],'choice':window.profile.last_payload['inspector']['structure_choice'],'molecule':js('window.profileInspector.molecule.diagnostics()'),'canvas':js("(()=>{const c=document.querySelector('.molecule-canvas');return {hidden:c.hidden,display:getComputedStyle(c).display,html:c.outerHTML.slice(0,200)}})()")}
        report['checks']['multi_source_requires_choice']=len(window.profile.last_payload['inspector']['structure_candidates'])==2 and window.profile.last_payload['inspector']['structure']['status']=='choose_source' and js('window.profileInspector.molecule.diagnostics().objects')==0 and js("getComputedStyle(document.querySelector('.molecule-canvas')).display==='none'")
        if not report['checks']['multi_source_requires_choice']:
            raise AssertionError('Multi-source state: '+json.dumps(report['multi_source_debug']))
        js("document.getElementById('structure-source').value='1';document.getElementById('structure-source').dispatchEvent(new Event('change'))")
        stable()
        chosen=window.profile.last_payload['inspector']
        report['checks']['explicit_source_selector']=chosen['structure']['status']=='available' and chosen['structure']['source_file_id']==chosen['structure_candidates'][1]['source_file_id']
        assert controller.set_expression(doc,node_id=a['points'][1]['node_id'])
        stable()
        capture('rf4-en-dark-1672x941.png')
        window.language_combo.setCurrentIndex(window.language_combo.findData('zh_CN'));window.theme_combo.setCurrentIndex(window.theme_combo.findData('light'));stable()
        report['checks']['cn_light']=js("document.getElementById('structure-status').textContent.includes('合成示例')")
        capture('rf4-cn-light-1672x941.png')
        report['checks']['no_js_errors']=not window.profile.javascript_errors
        report['javascript_errors']=window.profile.javascript_errors
        report['detail']=window.profile.last_payload['inspector']['detail'];report['structure']=window.profile.last_payload['inspector']['structure']
        files=['ui/profile_view.py','ui/main_window.py','services/controller.py','services/structure_preview.py','presentation/profile_view_model.py','core/plot_spec.py','resources/plot/profile.js','resources/plot/profile.html','resources/plot/replica.css','resources/plot/inspector_view.js','resources/plot/molecule_view.js','resources/plot/replica_controls.js']
        report['source_hashes']={f:sha256((ROOT/'src/gaussianreadpro'/f).read_bytes()).hexdigest() for f in files}
        report['passed']=all(report['checks'].values())
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        (folder/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('pid','passed','checks')}|{'error':report.get('error')},ensure_ascii=False,indent=2),flush=True)
    controller.close();wait_for(lambda:controller._closed)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

