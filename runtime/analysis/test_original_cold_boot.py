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


def test_actual_audit_copy_hash_and_unsafe_release_argument(tmp_path):
    binary=tmp_path/'audit'
    subprocess.run(['cc','-DCOLD_AUDIT_HOST','-O2',str(cold.SOURCE/'cold-start-audit.c'),'-o',str(binary)],check=True,capture_output=True)
    source=tmp_path/'source';source.write_bytes(bytes(range(256))*17);target=tmp_path/'target'
    result=subprocess.run([str(binary),'copy',str(source),str(target),str(source.stat().st_size),cold.sha(source),'600'],capture_output=True,text=True)
    assert result.returncode==0 and target.read_bytes()==source.read_bytes() and stat.S_IMODE(target.stat().st_mode)==0o600
    rejected=subprocess.run([str(binary),'copy',str(source),str(tmp_path/'wrong'),str(source.stat().st_size),'0'*64,'600'],capture_output=True)
    assert rejected.returncode==7
    assert subprocess.run([str(binary),'release','/dev/sda'],capture_output=True).returncode==2
