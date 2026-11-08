from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import persistent_storage as storage


def test_persistent_selection_requires_an_existing_restorable_usr_file(tmp_path,monkeypatch):
    import menu_control
    root=tmp_path/'analysis';(root/'menu-root/usr/bin').mkdir(parents=True)
    (root/'menu-root/usr/bin/tool').write_bytes(b'original')
    source=tmp_path/'new';source.write_bytes(b'replacement')
    monkeypatch.setattr(menu_control,'BASE',root)
    vm=menu_control.VM(natural_boot=True,persistent_storage=True)
    for path in ('/usr/bin/missing','/etc/profile','/usr/../etc/a'):
        with pytest.raises(ValueError):vm.select_firmware_test(source,path)
    selected=vm.select_firmware_test(source,'/usr/bin/tool')
    assert selected['staged_readback_verified'] and selected['guest_path']=='/usr/bin/tool'
    restored=vm.select_firmware_test()
    assert restored['original'] and restored['restore_path']=='/usr/bin/tool'
    assert vm.select_firmware_test()['restore_path']=='/usr/bin/tool'


def test_inherited_descriptor_exact_identity_and_regular_file(tmp_path):
    disk=tmp_path/'camera.emmc';disk.write_bytes(b'virtual disk')
    fd=os.open(disk,os.O_RDWR)
    try:
        info=os.fstat(fd);env=dict(A7C2_STORAGE_PROFILE=storage.PROFILE,A7C2_EMMC_INSTANCE=str(tmp_path),A7C2_EMMC_FD=str(fd),A7C2_EMMC_DEV=str(info.st_dev),A7C2_EMMC_INO=str(info.st_ino))
        assert storage.inherited_fd(env)==fd
        for change in (dict(A7C2_STORAGE_PROFILE='wrong'),dict(A7C2_EMMC_INO=str(info.st_ino+1)),dict(A7C2_EMMC_FD='0'),dict(A7C2_EMMC_FD='1e9')):
            with pytest.raises(ValueError):storage.inherited_fd(dict(env,**change))
    finally:os.close(fd)
    fd=os.open('/dev/null',os.O_RDONLY)
    try:
        info=os.fstat(fd)
        with pytest.raises(ValueError):storage.inherited_fd(dict(env,A7C2_EMMC_FD=str(fd),A7C2_EMMC_DEV=str(info.st_dev),A7C2_EMMC_INO=str(info.st_ino)))
    finally:os.close(fd)


def test_missing_profile_never_enables_storage():
    assert storage.inherited_fd({}) is None


@pytest.mark.parametrize('damage',['none','sysfs-blank','not-frozen','short-count','echo-only','duplicate'])
def test_shutdown_requires_actual_full_disk_freeze_and_thaws_failure(tmp_path,damage):
    raw=b'PERSISTENT_STORAGE_FREEZE_BEGIN\n1 19\nPERSISTENT_STORAGE_FREEZE_END\n';commands=[]
    if damage=='sysfs-blank':raw=raw.replace(b'1 19\n',b'1 19\n\n')
    if damage=='not-frozen':raw=raw.replace(b'1 19',b'0 0')
    if damage=='short-count':raw=raw.replace(b'1 19',b'1 18')
    if damage=='echo-only':raw=b'echo PERSISTENT_STORAGE_FREEZE_BEGIN\n1 19\necho PERSISTENT_STORAGE_FREEZE_END\n'
    if damage=='duplicate':raw+=raw
    def serial(script):
        commands.append(script)
        assert script.startswith('( ') and script.endswith(' )')
        assert 'rmmod' not in script and 'kill ' not in script
        return b'0 0\n' if 'echo 0 >' in script else raw
    if damage in ('none','sysfs-blank'):assert storage.prepare_shutdown(serial,tmp_path)['frozen_verified'] and len(commands)==1
    else:
        with pytest.raises(ValueError,match='frozen'):storage.prepare_shutdown(serial,tmp_path)
        assert not (tmp_path/'persistent-shutdown.json').exists()
        assert len(commands)==2 and 'echo 0 >' in commands[-1]
        assert (tmp_path/'persistent-shutdown-thaw.raw').read_bytes()==b'0 0\n'
    assert (tmp_path/'persistent-shutdown.raw').read_bytes()==raw


def test_generated_overlay_preserves_original_and_applies_file_only_once(tmp_path,monkeypatch):
    root=tmp_path/'analysis';(root/'menu-root/usr/lib').mkdir(parents=True)
    (root/'menu-root/usr/lib/libIMDB.so').write_bytes(b'validated adapter')
    module=tmp_path/'module.ko';module.write_bytes(b'checked module')
    source=tmp_path/'test.so';source.write_bytes(b'test program')
    monkeypatch.setattr(storage,'ANALYSIS',root);monkeypatch.setattr(storage,'module_file',lambda:module)
    captured={}
    def builder(base,overlay,output):
        captured['script']=(overlay/'simulation/persistent-apply-test').read_text()
        assert (overlay/'simulation/persistent-test-0').read_bytes()==source.read_bytes()
        return dict(entries=[])
    monkeypatch.setattr(storage,'build_overlay_initramfs',builder)
    entry=dict(path='usr/lib/appFw.so',source=str(source),new_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),size=source.stat().st_size,mode=0o100755)
    storage.augment_initramfs(tmp_path/'base',tmp_path/'output',dict(entries=[entry]))
    script=captured['script']
    assert script.index('/before')<script.index('remount,rw /usr')<script.index('cp /simulation/persistent-test-0')
    assert script.index('sync')<script.index('remount,ro /usr')<script.index('.applied\n')
    assert 'if [ ! -f /log/qemu/filetest-' in script
    assert 'SHA2-256(/usr/lib/appFw.so)' in script
    for path in ('usr/lib/a;touch-secret','usr/../etc/a','etc/profile'):
        with pytest.raises(ValueError):storage.augment_initramfs(tmp_path/'base',tmp_path/('out-'+str(len(path))),dict(entries=[dict(entry,path=path)]))


def test_restore_marker_is_stable_per_selection_and_changes_for_new_restore(tmp_path,monkeypatch):
    root=tmp_path/'analysis';folder=root/'menu-root/usr/lib';folder.mkdir(parents=True)
    (folder/'libIMDB.so').write_bytes(b'adapter');(folder/'appFw.so').write_bytes(b'original')
    module=tmp_path/'module';module.write_bytes(b'module');scripts=[]
    monkeypatch.setattr(storage,'ANALYSIS',root);monkeypatch.setattr(storage,'module_file',lambda:module)
    def builder(base,overlay,output):
        scripts.append((overlay/'simulation/persistent-apply-test').read_text());return dict(entries=[])
    monkeypatch.setattr(storage,'build_overlay_initramfs',builder)
    for choice in ('choice-one','choice-one','choice-two'):
        storage.augment_initramfs(tmp_path/'base',tmp_path/'out',restore_path='/usr/lib/appFw.so',restore_selection=choice)
    assert scripts[0]==scripts[1] and scripts[1]!=scripts[2]


def test_storage_lease_released_only_after_exact_owner_tree_is_gone(tmp_path,monkeypatch):
    import menu_control
    vm=menu_control.VM(natural_boot=True,persistent_storage=True)
    events=[]
    @contextmanager
    def context():
        events.append('enter');yield {};events.append('exit')
    active=context();active.__enter__();vm.storage_context=active;vm.storage_lease={}
    process=SimpleNamespace(pid=12345,poll=lambda:None)
    with pytest.raises(RuntimeError):vm._release_storage_lease(process)
    assert vm.storage_context is active and events==['enter']
    process.poll=lambda:0
    monkeypatch.setattr(menu_control.os,'killpg',lambda *args:(_ for _ in ()).throw(ProcessLookupError()))
    vm._release_storage_lease(process)
    assert events==['enter','exit'] and vm.storage_context is None


def test_selecting_storage_never_recreates_existing_valid_instance(tmp_path,monkeypatch):
    base=tmp_path/'storage';instance=base/'default';instance.mkdir(parents=True)
    called=[]
    @contextmanager
    def lease(path):
        called.append(path);yield {}
    monkeypatch.setattr(storage.disk,'lease',lease)
    assert storage.ensure_instance(base)==instance
    assert called==[instance]


def test_mounting_real_volume_does_not_seed_over_saved_configuration(monkeypatch):
    monkeypatch.setattr(storage,'sha',lambda path:'a'*64)
    commands=storage.mount_commands(dict(entries=[dict(path='usr/lib/appFw.so',new_sha256='b'*64)]))
    assert any('WBSHD=/tmp_wbshd/shared.XXXXXX' in x and 'MALLOC_OPTIONS=gfffffffff' in x for x in commands)
    assert any('/dev/cnflasha15 /usr' in x for x in commands)
    assert any('/dev/cnflasha2 /setting' in x for x in commands)
    assert any('mount --bind /tmp /etc' in x for x in commands)
    assert any('mount --bind /tmp /var' in x for x in commands)
    reset='rm -f /tmp/rm-file.claim /tmp/headless-osd.claim /tmp/gui-model.claim'
    assert reset in commands and commands.index(reset)<commands.index('/simulation/persistent-apply-test || { echo PERSISTENT_STORAGE_FAILED=file-test; exit 1; }')
    resets=[x for x in commands if x.startswith('rm -f /tmp/')]
    assert any('/tmp/sd-flush.request' in x and '/tmp/date-clock.ready' in x for x in resets)
    assert not any('*' in x or 'Backup' in x for x in resets)
    assert not any('cp /seed-backup' in x for x in commands)
    assert any('mmio_base=0x0b010000' in x for x in commands)
    vfat=[x for x in commands if 'mount -t vfat' in x]
    assert len(vfat)==3 and all('sync,posix_attr' in x for x in vfat)
    assert any('posix_attr,batch_sync' in x for x in vfat)
    assert any('PERSISTENT_GUEST_ELF_VERIFIED path=/usr/lib/appFw.so sha256='+('b'*64) in x for x in commands)
    assert sum('PERSISTENT_GUEST_ELF_VERIFIED' in x for x in commands)==6
