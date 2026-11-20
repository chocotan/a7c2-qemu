"""Host-only checks of the actual functional-camera raw-card export routing."""
import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import backup_profile


HERE=Path(__file__).resolve().parent


def test_ui_binds_selected_seed_before_backup_profile():
    source=(HERE/'menu_control.py').read_text()
    start=source.index("if self.card_seed and not host_sd and not directory_sd:env['A7C2_SD_IMAGE']")
    prepare=source.index('env.update(prepare_backup_profile(BASE,env))',start)
    launch=source.index('process = subprocess.Popen(self.command',prepare)
    assert start<prepare<launch
    assert "env['A7C2_SD_IMAGE']=" not in source[prepare:launch]


def test_ram_camera_admission_requires_exact_single_card_profile():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    guard=next(node for node in tree.body if isinstance(node,ast.If) and any(
        isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='error' and
        call.args and isinstance(call.args[0],ast.Constant) and
        str(call.args[0].value).startswith('Functional-camera RAM card requires') for call in ast.walk(node)))
    class Parser:
        def error(self,message):raise ValueError(message)
    valid={'A7C2_SD_IMAGE':'/synthetic/card.img','A7C2_FUNCTIONAL_CAMERA':backup_profile.FUNCTIONAL_CAMERA_PROFILE,
           'MENU_FUNCTIONAL_CAMERA':backup_profile.FUNCTIONAL_CAMERA_PROFILE}
    def run(values):
        scope=dict(ram_capture_media='direct-bootin-ram-card-1g-v1',rm_file=True,
                   os=SimpleNamespace(environ=values),FUNCTIONAL_CAMERA_PROFILE=backup_profile.FUNCTIONAL_CAMERA_PROFILE,
                   parser=Parser())
        exec(compile(ast.fix_missing_locations(ast.Module(body=[guard],type_ignores=[])),'<capture-admission>','exec'),scope)
    run(valid)
    for update in ({'A7C2_SD_IMAGE':''},{'MENU_FUNCTIONAL_CAMERA':''},{'A7C2_DIRECTORY_SD':'/other'},
                   {'A7C2_HOST_SD':'256gb'},{'QEMU_SONY_USB_NET':'1'},{'QEMU_NATIVE_AP_CP_LINK':'1'}):
        with pytest.raises(ValueError,match='requires'):run(dict(valid,**update))


def test_ram_profile_receipt_rejects_seed_or_source_drift(tmp_path,monkeypatch):
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    block=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
               any(isinstance(item,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='source_paths'
                   for target in item.targets) for item in node.body))
    fake=lambda path:({'path':str(path),'bytes':7,'sha256':'a'*64,'identity':[1,2,7,3,4]},None)
    monkeypatch.setattr(backup_profile,'_bound_profile_input',fake)
    paths={'source_backup_seed':tmp_path/'menu-root/seed-backup.bin',
           'source_script':tmp_path/'qemu-kernel-probe.sh',
           'source_board':tmp_path/'qemu-virt-board/virt-packed.dtb',
           'official_board':tmp_path/'unpacked/firmware.tar_unpacked/0800_appli/setting/cxd90057.dtb',
           'source_binary':tmp_path/'qemu-system-aarch64'}
    receipt={name:fake(path)[0] for name,path in paths.items()}
    receipt.update(schema='a7c2-functional-camera-ram-media-v1',physical_compatible=False,
                   media_profile='direct-bootin-ram-card-1g-v1',media_seed_source=str(tmp_path/'card.img'),
                   media_seed_bytes=1024**3,media_seed_sha256='b'*64,media_seed_identity=[1,2,1024**3,3,4],
                   usb_ethernet_added=False,directory_sd_added=False)
    def run(value):
        scope=dict(os=SimpleNamespace(environ={'A7C2_FUNCTIONAL_CAMERA_MEDIA':'direct-bootin-ram-card-1g-v1'}),base=tmp_path,
                   selected_binary=paths['source_binary'],backup_profile_receipt=value,sd_seed=tmp_path/'card.img',
                   sd_seed_bytes=1024**3,sd_seed_sha256='b'*64,sd_seed_identity=[1,2,1024**3,3,4])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[block],type_ignores=[])),'<capture-receipt>','exec'),scope)
    run(receipt)
    for change in ({'schema':'old'},{'physical_compatible':True},
                   {'media_seed_sha256':'c'*64},{'media_seed_identity':[1,3,1024**3,3,4]},
                   {'source_script':dict(receipt['source_script'],sha256='d'*64)},
                   {'usb_ethernet_added':True}):
        with pytest.raises(ValueError,match='differs|changed'):run(dict(receipt,**change))


def extracted():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    outer=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='export_virtual_sd')
    raw=next(node for node in outer.body if isinstance(node,ast.Assign) and
             any(isinstance(target,ast.Name) and target.id=='raw_capture' for target in node.targets))
    functions=[node for node in outer.body if isinstance(node,ast.FunctionDef) and node.name in ('export_once','publish_final')]
    assert len(functions)==2
    return ast.fix_missing_locations(ast.Module(body=[raw,*functions],type_ignores=[]))


@pytest.mark.parametrize(('camera','rm','directory','host','size','expected'),[
    (True,True,None,None,1024**3,True),
    (False,True,None,None,1024**3,False),
    (True,False,None,None,1024**3,False),
    (True,True,4,None,1024**3,False),
    (True,True,None,5,1024**3,False),
    (True,True,None,None,512*1024**2,False),
])
def test_raw_capture_selection_uses_only_explicit_functional_camera(camera,rm,directory,host,size,expected,tmp_path):
    calls=[]
    @contextmanager
    def directory_context(_path):yield 'parent'
    scope=dict(functional_camera=object() if camera else None,rm_file=rm,
               directory_sd_fd=directory,host_sd_fd=host,manifest={'rm_file_image_bytes':size},
               sd_sparse='1',out=tmp_path,last_sd_export_sha=[None],
               pending_sd_sequence=[None],download=lambda *_:None,barrier_serial=lambda *_args,**_kw:None,
               native_pair=None,os=SimpleNamespace(environ={}),directory=directory_context,
               export_card=lambda *_args,**kw:calls.append(('export',kw)) or {},
               report=lambda *_args:calls.append(('report',)),
               write_capture_export_proof=lambda *_args:calls.append(('proof',)))
    exec(compile(extracted(),str(HERE/'qemu-menu-probe.py'),'exec'),scope)
    assert scope['raw_capture'] is expected
    if directory is None and host is None:
        scope['export_once']('quiesced')
        assert calls[-1][1]['sparse'] is (not expected)
    scope['publish_final']({'ok':True,'flush_lifecycle':{'ok':False}})
    assert (('proof',) in calls) is expected


def test_existing_native_diagnostic_proof_path_is_preserved(tmp_path):
    @contextmanager
    def directory_context(_path):yield 'parent'
    calls=[]
    scope=dict(functional_camera=None,rm_file=True,directory_sd_fd=None,host_sd_fd=None,
               manifest={'rm_file_image_bytes':1024**3},sd_sparse='',out=tmp_path,
               last_sd_export_sha=[None],pending_sd_sequence=[None],download=None,barrier_serial=None,
               native_pair=object(),os=SimpleNamespace(environ={'MENU_NATIVE_CAPTURE_DIAGNOSTIC':'1'}),
               directory=directory_context,export_card=None,report=lambda *_:None,
               write_capture_export_proof=lambda *_:calls.append(True))
    exec(compile(extracted(),str(HERE/'qemu-menu-probe.py'),'exec'),scope)
    assert not scope['raw_capture']
    scope['publish_final']({'ok':True,'flush_lifecycle':{'ok':False}})
    assert calls==[True]


def test_failed_export_never_publishes_capture_proof(tmp_path):
    @contextmanager
    def directory_context(_path):yield 'parent'
    calls=[]
    scope=dict(functional_camera=object(),rm_file=True,directory_sd_fd=None,host_sd_fd=None,
               manifest={'rm_file_image_bytes':1024**3},sd_sparse='',out=tmp_path,
               last_sd_export_sha=[None],pending_sd_sequence=[None],download=None,barrier_serial=None,
               native_pair=None,os=SimpleNamespace(environ={}),directory=directory_context,
               export_card=None,report=lambda *_:None,write_capture_export_proof=lambda *_:calls.append(True))
    exec(compile(extracted(),str(HERE/'qemu-menu-probe.py'),'exec'),scope)
    scope['publish_final']({'ok':False,'flush_lifecycle':{'ok':False}})
    assert not calls
