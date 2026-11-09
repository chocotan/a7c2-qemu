import hashlib
from pathlib import Path
import stat
import subprocess

import pytest
import original_cold_boot as cold


@pytest.mark.parametrize('damage',['none','missing-pivot','wrong-order','release-failed','marker-only'])
def test_original_handoff_chain_requires_every_ordered_stage(damage):
    rows=[b'PRODUCT_COLD_BEFORE_ORIGINAL_INIT',b'+ . /sbin/initrc/setup_rootfs',b'+ /sbin/pivot_root . /rootfs/initrd',b'+ exec busybox chroot . /bin/ash -c',b'COLD_RAM0_RELEASE original_rc=0 zero_prefix=1 bytes=512',b'PRODUCT_COLD_INIT2 parent=1',b'PRODUCT_COLD_BOOTIN pid=455']
    if damage=='missing-pivot':rows.pop(2)
    if damage=='wrong-order':rows[2],rows[3]=rows[3],rows[2]
    if damage=='release-failed':rows[4]=rows[4].replace(b'original_rc=0',b'original_rc=1')
    if damage=='marker-only':rows=rows[-1:]
    raw=b'\n'.join(rows)
    if damage=='none':assert cold.verify_chain_log(raw)['original_script_handoff_order_verified']
    else:
        with pytest.raises(ValueError):cold.verify_chain_log(raw)


def test_guest_environment_only_explicit_product_exports():
    selected=cold.guest_environment({'MENU_CRYPT_LIB':'1','MENU_KERNEL_SCRIPT':'/tmp/unreviewed','LD_PRELOAD':'/tmp/foreign.so','MENU_RM_FILE':'1'})
    assert selected['MENU_CRYPT_LIB']=='1' and selected['MENU_RM_FILE']=='1'
    assert 'MENU_KERNEL_SCRIPT' not in selected and 'LD_PRELOAD' not in selected
    with pytest.raises(ValueError):cold.guest_environment({'MENU_RM_FILE':'1;touch /bad'})


def test_ext2_original_scripts_preserved_and_helpers_read_back(tmp_path,monkeypatch):
    image=tmp_path/'ram0.ext2'
    with image.open('wb') as stream:stream.truncate(4*1024**2)
    subprocess.run(['mke2fs','-q','-t','ext2','-F',str(image)],check=True,capture_output=True)
    original=tmp_path/'init';original.write_bytes(b'#!/bin/sh\necho original\n');original.chmod(0o755)
    for command in ('mkdir /sbin','write '+cold.quote(original)+' /sbin/init'):
        subprocess.run(['debugfs','-w','-R',command,str(image)],check=True,capture_output=True)
    digest=hashlib.sha256(original.read_bytes()).hexdigest();monkeypatch.setattr(cold,'ORIGINAL_SCRIPTS',{'/sbin/init':digest})
    helper=tmp_path/'helper';helper.write_bytes(b'owned helper\n');helper.chmod(0o700)
    result=cold._patch(image,tmp_path,{'/qemu/helper':helper},[('/simulation','/qemu')])
    assert result['original_untouched_entries_verified'] and result['original_scripts']['/sbin/init']==digest
    assert cold._patch(image,tmp_path,{},[('/simulation','/qemu')])['original_untouched_entries_verified']
    with pytest.raises(ValueError,match='conflicts'):cold._patch(image,tmp_path,{},[('/simulation','/elsewhere')])
    with pytest.raises(ValueError,match='Refuse replacing'):cold._patch(image,tmp_path,{'/sbin/init':helper})
    monkeypatch.setattr(cold,'ORIGINAL_SCRIPTS',{'/sbin/init':'0'*64})
    with pytest.raises(ValueError,match='identity differs'):cold._patch(image,tmp_path,{})


def test_bootstrap_hands_mount_and_pivot_to_original_init():
    script=(cold.SOURCE/'bootstrap.sh').read_text()
    assert script.index('insmod /qemu/sony_persistent_flash.ko')<script.index('PRODUCT_COLD_BEFORE_ORIGINAL_INIT')
    assert script.rstrip().endswith('exec /bin/busybox sh -x /sbin/init')
    assert 'mount -t ext2' not in script and 'pivot_root' not in script
    wrapper=(cold.SOURCE/'bootin.sh').read_text()
    assert wrapper.index('sh /simulation/reset-runtime.sh')<wrapper.index('/simulation/ramfb-viewer')
    reset=cold.storage.runtime_reset_commands()
    assert any('/tmp/headless-osd-frame.bin ' in command for command in reset)
    assert not any('*' in command or 'Backup' in command for command in reset)
    for source in cold.SOURCE.glob('*.sh'):subprocess.run(['sh','-n',str(source)],check=True,capture_output=True)


@pytest.mark.parametrize('damage',['none','wrong-root','writable','duplicate','old-root','not-root'])
def test_mountinfo_requires_actual_original_readonly_root_and_released_ram0(damage):
    raw=b'17 0 253:135 / / ro,noatime - ext2 /dev/nflasha7 ro,sync\n26 17 253:143 / /usr ro - ext2 /dev/nflasha15 ro,sync\nUid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\n'
    if damage=='wrong-root':raw=raw.replace(b'/dev/nflasha7 ',b'/dev/ram0 ')
    if damage=='writable':raw=raw.replace(b'ro,noatime',b'rw,noatime')
    if damage=='duplicate':raw+=raw.splitlines()[0]+b'\n'
    if damage=='old-root':raw+=b'27 17 1:0 / /initrd rw - ext2 /dev/ram0 rw\n'
    if damage=='not-root':raw=raw.replace(b'Uid:\t0',b'Uid:\t1')
    if damage=='none':assert cold.verify_root_observation(raw)['old_root_unmounted_verified']
    else:
        with pytest.raises(ValueError):cold.verify_root_observation(raw)


def test_menu_control_rejects_blank_or_hud_like_pixels():
    from PIL import Image,ImageDraw
    for color in ('black','white','orange'):
        image=Image.new('RGB',(640,480),color)
        assert not cold.original_menu_pixels(image)
    image=Image.new('RGB',(640,480),'black');ImageDraw.Draw(image).text((160,0),'J-FINE 14M AF-S',fill='white')
    assert not cold.original_menu_pixels(image) and not cold.original_menu_pixels(image.resize((320,240)))
    assert cold.chinese_language_rows(image)=={'target':None,'selected':None}
    assert cold.chinese_language_rows(Image.new('RGB',(640,480),(180,50,0)))=={'target':None,'selected':None}


def test_guest_elf_readback_rejects_wrong_file_bytes(tmp_path):
    originals={}
    for relative in ('usr/bin/im.elf','usr/lib/appFw.so','usr/lib/libObj.so'):
        path=tmp_path/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(relative.encode());originals[relative]=cold.sha(path)
    script=cold.guest_identity_script({'guest_inputs':originals})
    for relative in sorted(originals,key=len,reverse=True):script=script.replace('/'+relative,str(tmp_path/relative))
    path=tmp_path/'verify.sh';path.write_text(script)
    assert subprocess.run(['sh',str(path)],capture_output=True).returncode==0
    (tmp_path/'usr/lib/appFw.so').write_bytes(b'wrong original identity')
    assert subprocess.run(['sh',str(path)],capture_output=True).returncode==78


def test_cold_preflight_rejects_other_import_before_creating_output(tmp_path,monkeypatch):
    import json
    (tmp_path/'native-assets.json').write_text(json.dumps({'model':'another-camera','version':'2.01'}))
    monkeypatch.setattr(cold,'ANALYSIS',tmp_path)
    with pytest.raises(ValueError,match='official2.01'):cold.prepare(tmp_path/'unused-instance',tmp_path/'not-created',{})
    assert not (tmp_path/'not-created').exists()


def test_fonts_are_reused_only_after_full_digest_readback(tmp_path):
    simulation=tmp_path/'simulation';fonts=simulation/'language-fonts';fonts.mkdir(parents=True);destination=tmp_path/'images';destination.mkdir()
    source=fonts/'font.ltt';source.write_bytes(b'original font content')
    count=tmp_path/'space-calls';audit=simulation/'audit';audit.write_text('#!/bin/sh\necho checked >> '+str(count)+'\n');audit.chmod(0o755)
    script=cold.font_install_script({'font.ltt':source}).replace('/simulation',str(simulation)).replace('/tmp/images',str(destination)).replace('/bin/busybox cp','cp');path=tmp_path/'install.sh';path.write_text(script)
    subprocess.run(['sh',str(path)],check=True,capture_output=True)
    first=(destination/'font.ltt').stat();assert (destination/'font.ltt').read_bytes()==source.read_bytes() and len(count.read_text().splitlines())==1
    subprocess.run(['sh',str(path)],check=True,capture_output=True)
    assert (destination/'font.ltt').stat().st_mtime_ns==first.st_mtime_ns and len(count.read_text().splitlines())==1
    (destination/'font.ltt').write_bytes(b'bad');source.write_bytes(b'changed after manifest')
    assert subprocess.run(['sh',str(path)],capture_output=True).returncode!=0
    shim=(cold.SOURCE/'insmod.sh').read_text()
    assert shim.index('init2-attempted')<shim.index('mount --bind /usr/bin/bootin.elf')
    assert shim.index('PRODUCT_COLD_ORIGINAL_BOOTIN_IDENTITY_FAILED')<shim.index('mount --bind /usr/bin/bootin.elf')


def test_new_cold_cli_instance_creation_and_busy_lock_guard(tmp_path,monkeypatch):
    import runpy,sys,fcntl,os
    api=runpy.run_path(str(cold.ANALYSIS.parents[1]/'tools/run-original-cold.py'));main=api['main'];scope=main.__globals__;events=[]
    monkeypatch.setitem(scope,'ANALYSIS',tmp_path);monkeypatch.setitem(scope,'product_input_bindings',lambda:events.append('preflight'))
    monkeypatch.setattr(scope['storage'],'ensure_instance',lambda base:events.append(('new-instance',base)) or base/'default')
    def actual(instance,output,seconds):
        fd=os.open(tmp_path/'.menu-probe.lock',os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally:os.close(fd)
        events.append(('run',instance,output,seconds));return {'verified':True}
    monkeypatch.setitem(scope,'run',actual);output=tmp_path/'fresh'
    monkeypatch.setattr(sys,'argv',['run-original-cold','--new-instance','--output',str(output)])
    assert main()==0 and events[0]=='preflight' and events[1]==('new-instance',output/'storage')
    assert events[2][1]==output/'storage/default'
    blocked=tmp_path/'busy';fd=os.open(tmp_path/'.menu-probe.lock',os.O_RDWR)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);monkeypatch.setattr(sys,'argv',['run-original-cold','--new-instance','--output',str(blocked)])
        with pytest.raises(ValueError,match='Another product session'):main()
        assert not blocked.exists() and len(events)==3
    finally:os.close(fd)


@pytest.mark.parametrize('damage',['none','new-file','outside-usr','symlink','too-big'])
def test_cold_file_tests_stage_bytes_and_reject_unsafe_or_unrestorable_selection(tmp_path,monkeypatch,damage):
    analysis=tmp_path/'analysis';source=tmp_path/'overwrite';payload=tmp_path/'payload';payload.mkdir()
    original=analysis/'menu-root/usr/bin/tool';original.parent.mkdir(parents=True);original.write_bytes(b'original')
    selected=source/('etc/profile' if damage=='outside-usr' else 'usr/bin/new' if damage=='new-file' else 'usr/bin/tool')
    selected.parent.mkdir(parents=True);selected.write_bytes(b'candidate')
    if damage=='symlink':selected.unlink();selected.symlink_to(original)
    if damage=='too-big':monkeypatch.setattr(__import__('firmware_development'),'MAX_FILE_BYTES',2)
    monkeypatch.setattr(cold,'ANALYSIS',analysis);monkeypatch.setattr(cold.storage,'ANALYSIS',analysis)
    if damage!='none':
        with pytest.raises((ValueError,OSError)):cold.stage_file_selection(payload,{'A7C2_OVERWRITE_DIR':str(source)})
        return
    staged=cold.stage_file_selection(payload,{'A7C2_OVERWRITE_DIR':str(source)})
    entries=cold.storage.stage_file_tests(payload,staged)
    assert (payload/'persistent-test-0').read_bytes()==b'candidate' and original.read_bytes()==b'original'
    assert entries[0]['new_sha256']==hashlib.sha256(b'candidate').hexdigest()
    script=(payload/'persistent-apply-test').read_text()
    assert script.index('/before')<script.index('remount,rw /usr')<script.index('cp /simulation/persistent-test-0')
    second=tmp_path/'second-payload';second.mkdir()
    cold.storage.stage_file_tests(second,cold.stage_file_selection(second,{'A7C2_OVERWRITE_DIR':str(source)}))
    import re
    marker=r'/log/qemu/filetest-[a-f0-9]+\.applied'
    assert re.findall(marker,script)==re.findall(marker,(second/'persistent-apply-test').read_text())


@pytest.mark.parametrize('damage',['none','no-freeze','stale-freeze','failed-later-save','unrecovered-owner','changed-export'])
def test_cold_live_eof_requires_current_save_and_actual_full_freeze(tmp_path,damage):
    import json
    from original_cold_live import saved_for_close
    (tmp_path/'SD').mkdir();raw=b'PERSISTENT_STORAGE_FREEZE_BEGIN\\n1 19\\nPERSISTENT_STORAGE_FREEZE_END\\n'
    (tmp_path/'persistent-shutdown.raw').write_bytes(raw)
    internal=dict(frozen_verified=True,frozen_partitions=19,original_freeze_bdev_used=True,raw_sha256=hashlib.sha256(raw).hexdigest())
    exported=dict(ok=True,flush_lifecycle=dict(ok=True));state=dict(save_verified=True)
    if damage=='no-freeze':internal['frozen_partitions']=18
    if damage=='stale-freeze':(tmp_path/'persistent-shutdown.raw').write_bytes(b'different')
    if damage=='failed-later-save':state['save_verified']=False
    if damage=='unrecovered-owner':exported['flush_lifecycle']['ok']=False
    (tmp_path/'persistent-shutdown.json').write_text(json.dumps(internal))
    path=tmp_path/'SD/export.json';path.write_text(json.dumps(exported));state['sd_export_sha256']=cold.sha(path)
    if damage=='changed-export':path.write_text(json.dumps(dict(exported,changed=True)))
    (tmp_path/'cold-live-session.json').write_text(json.dumps(state))
    assert saved_for_close(tmp_path) is (damage=='none')


def test_cold_live_current_failed_shutdown_invalidates_previous_success(tmp_path,monkeypatch):
    import json,menu_live,sd_export_lifecycle
    import original_cold_live as live
    (tmp_path/'build').mkdir();(tmp_path/'build/result.json').write_text('{}')
    built=dict(helper_sources={'media-camera.fat':{'bytes':4096}},sd_card={'bytes':4096},ram0_sha256='a'*64,kernel_sha256='b'*64,overwrite={'entries':[]})
    def exported(export_once,serial,sequence,publish):
        row=dict(ok=True,card_published=True,sha256='c'*64,flush_lifecycle=dict(ok=True));(tmp_path/'SD').mkdir(exist_ok=True);publish(row);return row
    monkeypatch.setattr(sd_export_lifecycle,'export_with_flush_lifecycle',exported)
    def frozen(serial,run):
        (run/'persistent-shutdown.raw').write_bytes(b'freeze')
        row=dict(frozen_verified=True,frozen_partitions=19,original_freeze_bdev_used=True,raw_sha256=hashlib.sha256(b'freeze').hexdigest())
        (run/'persistent-shutdown.json').write_text(json.dumps(row));return row
    monkeypatch.setattr(live.storage,'prepare_shutdown',frozen)
    def protocol(proc,run,fd,**callbacks):
        callbacks['sd_export']();callbacks['storage_shutdown'](lambda command:b'',run)
        assert live.saved_for_close(run)
        callbacks['sd_export']()
        def failed(*args):raise OSError('current freeze command lost before raw readback')
        monkeypatch.setattr(live.storage,'prepare_shutdown',failed)
        with pytest.raises(OSError):callbacks['storage_shutdown'](lambda command:b'',run)
        raise RuntimeError('VM 控制通道已关闭')
    monkeypatch.setattr(menu_live,'run_live',protocol);monkeypatch.setenv('MENU_CONTROL_FD','99');monkeypatch.delenv('A7C2_SETTINGS_PERSIST',raising=False)
    with pytest.raises(ValueError,match='retain owner'):live.live_session(None,tmp_path,None,built)
    assert not live.saved_for_close(tmp_path)


def test_cold_control_requires_real_owner_socket_and_current_lock(tmp_path,monkeypatch):
    import os,socket
    import original_cold_live as live
    monkeypatch.setattr(live,'ANALYSIS',tmp_path)
    path=tmp_path/'.menu-probe.lock';path.touch();fd=os.open(path,os.O_RDWR)
    try:
        parent,child=socket.socketpair()
        with parent,child:
            env=dict(A7C2_BOOT_PROFILE='original-init-cold',A7C2_USE_PERSISTENT_STORAGE='1',MENU_CONTROL_FD=str(child.fileno()),MENU_CONTROL_OWNER_PID=str(os.getpid()),MENU_PROBE_LOCK_FD=str(fd))
            assert live.validate_control(env)==child.fileno()
            for wrong in (dict(MENU_CONTROL_OWNER_PID=str(os.getpid()+1)),dict(A7C2_USE_PERSISTENT_STORAGE='0'),dict(A7C2_DIRECTORY_SD='/foreign')):
                with pytest.raises(ValueError):live.validate_control(dict(env,**wrong))
    finally:os.close(fd)


def test_cold_controller_cannot_drop_disk_or_reset_unbound_instance():
    from menu_control import VM
    vm=VM(natural_boot=True,boot_profile='original-init-cold')
    assert vm.status()['boot_profile']=='original-init-cold' and vm.persistent_storage
    with pytest.raises(ValueError,match='持久'):vm.configure_storage(False)
    with pytest.raises(ValueError,match='未绑定'):vm.reset_configuration(confirmed=True)
    for args in (dict(natural_boot=False),dict(natural_boot=True,usb_net=True),dict(natural_boot=True,command=['unused'])):
        with pytest.raises(ValueError):VM(boot_profile='original-init-cold',**args)


def test_cold_settings_import_never_copies_over_subsequent_disk_settings(tmp_path):
    helpers=cold.settings_import(tmp_path,{})
    script=helpers['install-settings.sh'].read_text()
    assert 'if [ ! -f /log/qemu/original-cold-settings-imported ]; then' in script
    assert 'no-legacy-snapshot' in script and 'cp ' not in script
    with pytest.raises(ValueError,match='size'):cold.settings_import(tmp_path,dict(A7C2_SETTINGS_RESTORE=str(helpers['install-settings.sh']),A7C2_SETTINGS_RESTORE_SHA='0'*64))


def test_settings_storage_domain_is_explicit_and_space_arithmetic_checked(tmp_path):
    source=cold.ANALYSIS/'user-settings-checkpoint.c';test=tmp_path/'storage-guard.c'
    test.write_text('#define HOST_PURE\n#include "'+str(source)+'"\n#include <assert.h>\nint main(void){unsigned char out=0,values[2]={2,2}; char reservation[]="memrsv=0x00400000@0x41e600000:uc"; assert(storage_type_ok(0x01021994,0)); assert(!storage_type_ok(0x4d44,0)); assert(storage_type_ok(0x4d44,1)); assert(!storage_type_ok(0x01021994,1)); assert(!storage_type_ok(0xef53,1)); assert(!storage_type_ok(0x4d44,2)); assert(space_ok(210,16384)); assert(!space_ok(209,16384)); assert(!space_ok(UINT64_MAX,4096)); assert(!space_ok(1,0)); assert(number("25",255,&out)&&out==25); assert(!number("256",255,&out)); assert(changed(values)); assert(reserved(reservation)); assert(!reserved("none")); assert(fnv((const unsigned char *)"a",1)); assert(!parse((const unsigned char *)"",0,values)); return 0;}\n')
    for flags,name in ((['-O2'],'strict'),(['-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer'],'sanitized')):
        binary=tmp_path/name
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',*flags,str(test),'-o',str(binary)],check=True,capture_output=True)
        subprocess.run([str(binary)],check=True,capture_output=True)


def test_actual_audit_copy_hash_and_unsafe_release_argument(tmp_path):
    binary=tmp_path/'audit'
    subprocess.run(['cc','-DCOLD_AUDIT_HOST','-O2',str(cold.SOURCE/'cold-start-audit.c'),'-o',str(binary)],check=True,capture_output=True)
    source=tmp_path/'source';source.write_bytes(bytes(range(256))*17);target=tmp_path/'target'
    result=subprocess.run([str(binary),'copy',str(source),str(target),str(source.stat().st_size),cold.sha(source),'600'],capture_output=True,text=True)
    assert result.returncode==0 and target.read_bytes()==source.read_bytes() and stat.S_IMODE(target.stat().st_mode)==0o600
    rejected=subprocess.run([str(binary),'copy',str(source),str(tmp_path/'wrong'),str(source.stat().st_size),'0'*64,'600'],capture_output=True)
    assert rejected.returncode==7
    assert subprocess.run([str(binary),'release','/dev/sda'],capture_output=True).returncode==2
