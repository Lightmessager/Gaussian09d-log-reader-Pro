from dataclasses import replace

from gaussianreadpro.core import calculate_path
from gaussianreadpro.core.models import new_id, PathEntry
from gaussianreadpro.core.plot_spec import build_plot_spec, plot_payload, clean_view_state
from gaussianreadpro.presentation.profile_view_model import inspector_payload
from gaussianreadpro.storage.sources import SourceConnection
from s2_helpers import project as sample_project


def model():
    project,_,_=sample_project()
    project=replace(project,source_files=tuple(replace(s,sha256='a'*64) for s in project.source_files),
                    nodes=tuple(replace(n,role='transition_state') if i==1 else n for i,n in enumerate(project.nodes)))
    a=project.paths[0]
    b=replace(a,id=new_id(),label='Path B',entries=tuple(PathEntry(new_id(),e.node_id,i) for i,e in enumerate(a.entries[:-1])))
    project=replace(project,paths=(a,b))
    spec=build_plot_spec(project,[calculate_path(project,p.id) for p in project.paths])
    connections=tuple(SourceConnection(s.id,'available',None) for s in project.source_files)
    return project,spec,connections


def test_no_label_or_index_matching_and_explicit_identity_pairs():
    project,spec,connections=model();a,b=project.paths
    payload=plot_payload(spec,a.id,compare=True)
    vm=inspector_payload(project,payload,{},connections)
    assert len(vm['table_rows'])==len(a.entries)+len(b.entries)
    assert all(sum(c is not None for c in r['cells'])==1 for r in vm['table_rows'])
    state=clean_view_state({'step_pairs':[[[a.id,a.entries[1].id],[b.id,b.entries[0].id]]]},spec)
    vm=inspector_payload(project,payload,state,connections)
    row=vm['table_rows'][0]
    assert row['cells'][0]['entry_id']==a.entries[1].id and row['cells'][1]['entry_id']==b.entries[0].id
    assert row['paired'] and len(vm['table_rows'])==len(a.entries)+len(b.entries)-1


def test_last_selected_detail_barrier_requires_explicit_predecessor():
    project,spec,connections=model();a=project.paths[0]
    selection=[(a.id,a.entries[0].id),(a.id,a.entries[1].id)]
    payload=plot_payload(spec,a.id,compare=True,selected=selection)
    vm=inspector_payload(project,payload,{},connections,selection)
    assert vm['detail']['entry_id']==a.entries[1].id and vm['detail']['barrier'] is None
    assert vm['detail']['absolute_hartree'] is not None and vm['structure_candidates']
    marked=plot_payload(spec,a.id,selected=selection,state={'barrier':{'path_id':a.id,'from_entry':a.entries[0].id,'to_entry':a.entries[1].id}})
    vm=inspector_payload(project,marked,{},connections,selection)
    assert vm['detail']['barrier'] is not None
    assert all(s['source_sha256'] and s['job_ordinal'] for s in vm['detail']['sources'])


def test_unavailable_source_suppresses_detail_and_molecule_candidates():
    project,spec,connections=model();a=project.paths[0];key=(a.id,a.entries[1].id)
    payload=plot_payload(spec,a.id,selected=[key])
    vm=inspector_payload(project,payload,{},tuple(replace(c,state='changed') for c in connections),[key])
    assert not vm['detail']['valid'] and vm['detail']['value'] is None
    assert vm['detail']['absolute_hartree'] is None and not vm['structure_candidates']


def test_pair_allowlist_rejects_duplicates_foreign_and_same_path(tmp_path):
    project,spec,_=model();a,b=project.paths
    group=[[a.id,a.entries[0].id],[b.id,b.entries[0].id]]
    raw=[group,group,[[a.id,a.entries[1].id],[a.id,a.entries[2].id]],[[new_id(),new_id()],[b.id,b.entries[1].id]],'bad']
    assert clean_view_state({'step_pairs':raw},spec)['step_pairs']==[group]
    from gaussianreadpro.storage import ProjectRepository
    from gaussianreadpro.core.models import snapshot_to_dict
    file=tmp_path/'paired.grproj'
    with ProjectRepository(file,create=True) as repo:repo.save(replace(project,plot_state={'step_pairs':[group]}))
    with ProjectRepository(file,read_only=True) as repo:restored=repo.load()
    assert snapshot_to_dict(restored.plot_state)['step_pairs']==[group] and restored.schema_version==1


from test_workbench import app,workbench,settle


def test_structure_worker_queues_latest_and_rejects_old_revision(workbench,app):
    from threading import Event
    from PySide6.QtTest import QTest
    window,controller=workbench
    project,spec,connections=model();source=project.source_files[0];job=source.jobs[0]
    controller.project=project;controller.plot_spec=spec;controller.connections=connections
    gate=Event();started=Event();calls=[];results=[]
    def read(*args,**kwargs):
        calls.append(True)
        if len(calls)==1:started.set();gate.wait(3)
        return {'status':'no_structure'}
    controller.structure_service.read=read
    controller.structureReady.connect(results.append)
    request={'project_id':project.id,'revision':project.revision,'source_file_id':source.id,'job_id':job.id,'request_id':'old'}
    controller.request_structure(request)
    assert started.wait(2)
    controller.project=replace(project,revision=project.revision+1)
    controller.request_structure({**request,'revision':controller.project.revision,'request_id':'latest'})
    gate.set()
    for _ in range(100):
        app.processEvents();QTest.qWait(10)
        if results:break
    assert [r['request_id'] for r in results]==['latest'] and len(calls)==2
    assert controller.pool.maxThreadCount()==1


def test_copy_action_uses_guarded_current_numeric_value(workbench,app):
    import json
    from PySide6.QtTest import QTest
    window,controller=workbench
    project,spec,connections=model();controller.project=project
    panel=window.profile
    envelope={'project_id':project.id,'revision':project.revision,'render_id':99}
    panel.last_payload={**envelope,'unit_label':'kcal/mol','inspector':{'detail':{'valid':True,'value':15.06}}}
    panel.handle_event(json.dumps({**envelope,'type':'workbench_action','action':'copy_value'}))
    QTest.qWait(50)
    assert app.clipboard().text()=='15.06 kcal/mol'


def test_multi_source_prompt_updates_even_when_both_signatures_are_empty(workbench):
    window,controller=workbench
    project,spec,connections=model();controller.project=project;controller.connections=connections
    panel=window.profile;panel.spec=spec;panel.active_path=project.paths[0].id;panel.ready=False
    panel._selection=[(project.paths[0].id,project.paths[0].entries[2].id)]
    panel._structure_signature=None;panel._structure_data={'status':'no_selection'}
    panel.refresh()
    assert len(panel.last_payload['inspector']['structure_candidates'])==2
    assert panel.last_payload['inspector']['structure']['status']=='choose_source'
    assert panel._structure_requested_signature is None
