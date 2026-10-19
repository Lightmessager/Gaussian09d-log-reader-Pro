from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from gaussianreadpro.services.structure_preview import StructurePreviewService, parse_orientation, infer_bonds


def block(kind="Standard", x=0, unit="Angstroms", closing=True, number=6):
    return f" {kind} orientation:\n -----\n Center Atomic Atomic Coordinates ({unit})\n Number Number Type X Y Z\n -----\n 1 {number} 0 {x} 0 0\n 2 1 0 1.0 0 0\n" + (" -----\n" if closing else "")


def test_last_complete_standard_priority_input_and_job_bounds():
    lines=(block("Input",10)+block(x=1)+block(x=2)+block(x=99,closing=False)).splitlines()
    value=parse_orientation(lines,1,len(lines))
    assert value['orientation']=='Standard' and value['atoms'][0]['xyz'][0]==2
    first=block("Input",10).splitlines()
    limited=parse_orientation(lines,1,len(first))
    assert limited['orientation']=='Input' and limited['atoms'][0]['xyz'][0]==10
    assert parse_orientation(lines,len(lines),len(lines))['status']=='no_structure'


@pytest.mark.parametrize('text',[block(x='nan'),block(x='inf'),block(number=0),block(number=119),block(closing=False)])
def test_bad_or_partial_coordinates_never_become_models(text):
    assert parse_orientation(text.splitlines(),1,len(text.splitlines()))['status']=='invalid_orientation'


def test_units_and_cancellation_are_explicit():
    text=block(unit="Bohr")
    assert parse_orientation(text.splitlines(),1,100)['status']=='unsupported_units'
    assert parse_orientation(block().splitlines(),1,100,lambda:True)['status']=='cancelled'
    assert infer_bonds([{'atomic_number':6,'xyz':[0,0,0]}],lambda:True) is None


def test_verified_read_cache_is_rechecked_and_scoped_excerpt(tmp_path):
    text='SYNTHETIC TEST\n'+block()+"job two\n"+block(x=99)
    file=tmp_path/'model.log';file.write_text(text,encoding='utf-8')
    source=SimpleNamespace(id='source',sha256=sha256(file.read_bytes()).hexdigest(),original_name=file.name)
    end=len(('SYNTHETIC TEST\n'+block()).splitlines())
    job=SimpleNamespace(id='job-one',ordinal=0,start_line=1,end_line=end)
    connection=SimpleNamespace(state='available',path=file)
    service=StructurePreviewService()
    value=service.read(source,job,connection,line=end-1)
    assert value['status']=='available' and value['atoms'][0]['xyz']==[0,0,0]
    assert value['source_sha256']==source.sha256 and value['job_id']=='job-one' and value['synthetic']
    assert value['excerpt']['end']<=end and 'job two' not in value['excerpt']['text']
    value['atoms'][0]['xyz'][0]=123
    assert service.read(source,job,connection)['atoms'][0]['xyz'][0]==0
    file.write_text(text.replace('1.0','2.0'),encoding='utf-8')
    assert service.read(source,job,connection)['status']=='changed'
    assert service.read(source,job,SimpleNamespace(state='missing',path=None))['status']=='missing'
    assert service.read(source,job,connection,lambda:True)['status']=='cancelled'


def test_limits_and_unknown_atoms_are_not_fake_bonds(tmp_path,monkeypatch):
    import gaussianreadpro.services.structure_preview as module
    monkeypatch.setattr(module,'MAX_BYTES',2)
    file=tmp_path/'large.log';file.write_text('large')
    source=SimpleNamespace(id='s',sha256=sha256(file.read_bytes()).hexdigest(),original_name='large.log')
    job=SimpleNamespace(id='j',ordinal=0,start_line=1,end_line=1)
    assert StructurePreviewService().read(source,job,SimpleNamespace(state='available',path=file))['status']=='size_limit'
    assert infer_bonds([{'atomic_number':118,'xyz':[0,0,0]},{'atomic_number':6,'xyz':[1,0,0]}])==[]
