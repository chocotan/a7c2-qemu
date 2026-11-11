import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('cp_notify_stage',Path(__file__).with_name('stage-notify.py'))
stage=importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
sha=lambda data:hashlib.sha256(data).hexdigest()


def fixture(tmp_path,monkeypatch):
    tree=tmp_path/'qemu'
    board='#include "hw/core/qdev-properties.h"\nvoid init(void) {\n    const char *gpio18 = g_getenv("QEMU_CP_GPIO18_PROFILE");\n}\n'
    ap_board='#include "hw/core/qdev-properties.h"\nvoid init(void) {\n    create_gic(vms, sysmem);\n}\n'
    original={'hw/core/null-machine.c':board.encode(),'hw/arm/virt.c':ap_board.encode(),
              'hw/gpio/meson.build':b'# fixture\n','hw/gpio/gpio18.h':b'old core\n'}
    for name,data in original.items():
        p=tree/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    parent=tree/'cp-gpio18-stage.json'
    parent.write_text(json.dumps({'outputs':{k:sha(v) for k,v in original.items()}}))
    sources=tmp_path/'sources';sources.mkdir()
    for name in stage.FILES:(sources/name).write_text('new '+name+'\n')
    monkeypatch.setattr(stage,'PARENT_SHA',sha(parent.read_bytes()))
    monkeypatch.setattr(stage,'BASES',{k:sha(v) for k,v in original.items() if k!='hw/gpio/gpio18.h'})
    monkeypatch.setattr(stage,'HERE',sources)
    return tree,original


def test_explicit_notify_profile_and_readback(tmp_path,monkeypatch):
    tree,original=fixture(tmp_path,monkeypatch)
    proof=stage.stage(tree)
    assert proof['default_off'] and not proof['physical_compatible'] and not proof['cp_irq_supported']
    assert proof['ap_gic_spis']==[60,59]
    assert stage.stage(tree)==proof
    for name,data in original.items():
        if name in stage.BASES:assert (tree/'cp-notify-before'/name).read_bytes()==data
    board=(tree/'hw/core/null-machine.c').read_text()
    assert board.count(stage.INSERT)==1
    assert 'QEMU_CP_GPIO18_PROFILE' in stage.INSERT and 'qemu_chr_find("notify-peer")' in board
    assert '0xf102e000' in board and '0xf102f000' in board
    ap_board=(tree/'hw/arm/virt.c').read_text()
    assert ap_board.count(stage.AP_INSERT)==1
    assert 'vms->gic, 60' in ap_board and 'vms->gic, 59' in ap_board
    for name,digest in proof['outputs'].items():assert sha((tree/name).read_bytes())==digest


def test_unknown_parent_refuses_before_write(tmp_path,monkeypatch):
    tree,original=fixture(tmp_path,monkeypatch)
    (tree/'cp-gpio18-stage.json').write_text('{}')
    with pytest.raises(ValueError,match='parent stage differs'):stage.stage(tree)
    assert (tree/'hw/core/null-machine.c').read_bytes()==original['hw/core/null-machine.c']
    assert not (tree/'cp-notify-before').exists()


def test_inherited_core_drift_refuses_before_write(tmp_path,monkeypatch):
    tree,original=fixture(tmp_path,monkeypatch)
    (tree/'hw/gpio/gpio18.h').write_text('changed')
    with pytest.raises(ValueError,match='Inherited'):stage.stage(tree)
    assert (tree/'hw/core/null-machine.c').read_bytes()==original['hw/core/null-machine.c']


def test_restaging_rejects_changed_adapter(tmp_path,monkeypatch):
    tree,_=fixture(tmp_path,monkeypatch)
    stage.stage(tree)
    (tree/'hw/gpio/notify-qemu.c').write_text('changed')
    with pytest.raises(ValueError,match='stage drift'):stage.stage(tree)
