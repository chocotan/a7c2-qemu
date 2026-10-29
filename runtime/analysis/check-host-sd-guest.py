#!/usr/bin/env python3
"""One helper-only USB VM; retain file lease until confirmed QMP shutdown."""
import fcntl
import hashlib
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import sys

from host_sd import card_lease, TOTAL
from host_sd_profile import prepare_profile
from directory_sd import directory_lease
from directory_sd_profile import prepare_profile as prepare_directory_profile
from directory_snapshot import read_commit_status
from initramfs_identity import verify_image
from menu_live import serial_command

BASE=Path(__file__).resolve().parent


def fat_host_path(root, logical):
    current = root
    for component in logical.split('/'):
        matches = []
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.name.casefold() == component.casefold():
                    if entry.is_symlink():
                        raise ValueError('FAT host path contains a symlink')
                    matches.append(entry)
        if len(matches) != 1:
            raise FileNotFoundError(f'FAT path is absent or ambiguous: {logical} at {current}')
        current = Path(matches[0].path)
    return current


def quit_qmp(run):
    # AF_UNIX absolute path can exceed sun_path; connect relative to pinned cwd.
    cwd=os.open('.',os.O_RDONLY|os.O_DIRECTORY)
    try:
        os.chdir(run)
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(10);connection.connect('qmp.sock')
            stream=connection.makefile('rwb',buffering=0)
            assert 'QMP' in json.loads(stream.readline())
            for name in ('qmp_capabilities','quit'):
                stream.write((json.dumps({'execute':name,'id':name})+'\n').encode())
                while True:
                    line=stream.readline()
                    if not line:raise RuntimeError('QMP closed before command reply')
                    message=json.loads(line)
                    if message.get('id')==name:
                        if message.get('return')!={}:raise RuntimeError(str(message))
                        break
    finally:os.fchdir(cwd);os.close(cwd)


def main():
    fsys_test='--original-fsys' in sys.argv
    directory_test='--directory-fsys' in sys.argv
    nested_test='--nested-fsys' in sys.argv
    seed_backup='--seed-backup' in sys.argv
    if nested_test and not directory_test:
        raise ValueError('Nested Fsys diagnostic requires directory vvfat')
    if directory_test and not (fsys_test and seed_backup):
        raise ValueError('Directory diagnostic requires original Fsys and original ALLLANG Backup')
    if seed_backup and not fsys_test:raise ValueError('Backup setup is only for the original-Fsys diagnostic')
    env={k:v for k,v in os.environ.items() if not k.startswith(('MENU_','QEMU_','A7C2_','SONY_'))}
    env.update(SEED_BACKUP='alllang',QEMU_TIMEOUT_SECONDS='0',QEMU_CPU_COUNT='1')
    with (BASE/'.menu-probe.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run=Path(tempfile.mkdtemp(prefix='directory-sd-helper-' if directory_test else 'host-sd-helper-',dir=BASE/'menu-runs'))
        disk=None if directory_test else Path(tempfile.mkdtemp(prefix='transport-check-',dir=BASE/'host-sd'))
        if directory_test:(BASE/'directory-sd-tests').mkdir(exist_ok=True)
        directory_root=Path(tempfile.mkdtemp(prefix='directory-card-',dir=BASE/'directory-sd-tests')) if directory_test else None
        proof=dict(ok=False,scope='directory virtual FAT and original nested Fsys IO, no format or capture' if nested_test else 'directory virtual FAT and original Fsys IO, no format or capture' if directory_test else 'standard virtual USB and raw block IO only, no original Fsys/format/capture',
                   nested_fsys_test=nested_test,
                   directory=str(directory_root) if directory_root else None,
                   disk=str(disk/'card.img') if disk else None,physical_media_access=False)
        with ExitStack() as stack:
            lease=stack.enter_context(directory_lease(directory_root) if directory_test else card_lease(disk))
            profile_builder=prepare_directory_profile if directory_test else prepare_profile
            extra=fcntl.fcntl(lease['fd'],fcntl.F_DUPFD_CLOEXEC,40)
            proc=None
            try:
                if fsys_test and not directory_test:
                    # Host FAT is ONLY a test fixture; the user card stays blank for original UI format.
                    formatted=subprocess.run(['mkfs.fat','-F','32','-s','64',f'/proc/self/fd/{lease["fd"]}'],
                        pass_fds=(lease['fd'],),capture_output=True,check=True,timeout=60)
                    (run/'host-fixture-mkfs.log').write_bytes(formatted.stdout+formatted.stderr)
                    proof['scope']='host FAT32 unit fixture and original Fsys block IO; not camera UI format or capture'
                if directory_test:
                    (directory_root/'INPUT.BIN').write_bytes(b'original host directory input\x00\xff')
                profile=profile_builder(BASE,{**lease,'fd':extra})
                env.update(profile,QEMU_OUTPUT_DIR=str(run))
                if directory_test:
                    env['MENU_RM_FILE']='1'
                    built=subprocess.run(['bash',str(BASE/'build-observers.sh')],env=env,
                                         capture_output=True,check=True,timeout=120)
                    (run/'observer-build.log').write_bytes(built.stdout+built.stderr)
                build=subprocess.run(['bash',str(BASE/'prepare-menu-initramfs.sh')],env=env,capture_output=True,check=True,timeout=120)
                (run/'initramfs-build.log').write_bytes(build.stdout+build.stderr)
                helper=BASE/'menu-root/simulation/host-sd-probe'
                proof['verified_helper']=verify_image(BASE/'menu-initramfs.cpio',
                    {'simulation/host-sd-probe':hashlib.sha256(helper.read_bytes()).hexdigest()})
                if fsys_test:
                    proof['verified_fsys_inputs']=verify_image(BASE/'menu-initramfs.cpio',{
                        'simulation/'+name:hashlib.sha256((BASE/'menu-root/simulation'/name).read_bytes()).hexdigest()
                        for name in ('host-block-sd.so','file-media-config.so','menu-observe.so','fsys-file-test')} | {
                        'usr/lib/'+name:hashlib.sha256((BASE/'menu-root/usr/lib'/name).read_bytes()).hexdigest()
                        for name in ('libInfraMediaCommon.so','libInfraFsys.so')})
                if seed_backup:
                    proof['verified_alllang_seed']=verify_image(BASE/'menu-initramfs.cpio',{
                        name:hashlib.sha256((BASE/'menu-root'/name).read_bytes()).hexdigest()
                        for name in ('seed-backup.bin','usr/kmod/backup.ko','usr/kmod/stream.ko','usr/kmod/stream2.ko')})
                with (run/'console.log').open('wb') as output:
                    proc=subprocess.Popen(['bash',profile['MENU_KERNEL_SCRIPT'],'4096',profile['MENU_DTB'],
                        '1','1',str(BASE/'menu-initramfs.cpio')],env=env,stdin=subprocess.PIPE,
                        stdout=output,stderr=subprocess.STDOUT,pass_fds=(extra,))
                    deadline=time.monotonic()+100
                    while time.monotonic()<deadline:
                        if proc.poll() is not None:raise RuntimeError('Owned USB VM exited before shell')
                        if b'/ #' in (run/'console.log').read_bytes():break
                        time.sleep(.1)
                    else:raise TimeoutError('No USB helper guest shell')
                    def execute(name,command,timeout=60):
                        start=(run/'console.log').stat().st_size
                        try:
                            raw=serial_command(proc,run/'console.log',command,timeout=timeout,allow_faulted_cleanup=True)
                        except BaseException:
                            with (run/'console.log').open('rb') as console:
                                console.seek(start);(run/(name+'.failed-partial')).write_bytes(console.read())
                            raise
                        (run/name).write_bytes(raw);return raw
                    # Original SCSI uses the original UDIF/UIPC event services.
                    execute('modules.txt',
                        'mount -t proc proc /proc && mount -t sysfs sysfs /sys; '
                        'for m in /kmod/devno.ko /usr/kmod/osal_utm.ko /usr/kmod/osal_uipc.ko '
                        '/usr/kmod/scsi_mod.ko /usr/kmod/sd_mod.ko /usr/kmod/usb-storage.ko '
                        '/usr/kmod/xhci-hcd.ko /usr/kmod/xhci-plat-hcd.ko; do '
                        'insmod "$m" && echo HOST_SD_MOD_OK=$m || echo HOST_SD_MOD_FAIL=$m; done; '
                        'sleep 4; cat /proc/partitions; ls -l /dev/sda; '
                        'cat /sys/block/sda/size; true')
                    if fsys_test:
                        if seed_backup:
                            seeded=execute('original-backup-setup.txt',
                                'mount -t tmpfs tmpfs /setting && '
                                'cp /seed-backup.bin /setting/Backup.bin && '
                                'insmod /usr/kmod/backup.ko Backup_load=1 Backup_save=0 && '
                                'test -c /dev/backup && insmod /usr/kmod/stream.ko && '
                                'insmod /usr/kmod/stream2.ko && '
                                '/usr/bin/openssl dgst -sha256 /setting/Backup.bin')
                            seed_sha=proof['verified_alllang_seed']['seed-backup.bin']
                            assert seed_sha.encode() in seeded
                            proof['original_alllang_backup_loaded']=True
                        execute('block-bind.txt',': > /image_mmca && mount -o bind /dev/sda /image_mmca')
                        raw=execute('original-fsys.txt',
                            'A7C2_FILE_MEDIA_TEST=1 A7C2_HOST_BLOCK_SD=1 MENU_OBSERVE_SELFTEST=1 '
                            'LD_PRELOAD=/simulation/host-block-sd.so:/simulation/file-media-config.so:/simulation/menu-observe.so '
                            '/simulation/fsys-file-test '+('host-nested' if nested_test else 'host-256'),timeout=120)
                        assert b'FSYS_HOST_BLOCK_TEST_PASS' in raw and b'HOST_BLOCK_SD_CAPACITY' in raw
                        if nested_test:assert b'FSYS_HOST_NESTED_TEST_PASS' in raw
                        assert b'HOST_BLOCK_SD_FSYNC' in raw
                        proof['original_fsys_diagnostic_verified']=True
                    else:
                        raw=execute('raw-io.txt','/simulation/host-sd-probe raw-test')
                        assert b'HOST_SD_PROBE_PASS scope=raw_virtual_USB_transport' in raw
                        proof['guest_raw_io_verified']=True
            except BaseException as error:
                proof['error']=f'{type(error).__name__}: {error}'
            finally:
                if proc is not None and proc.poll() is None:
                    try:quit_qmp(run);proc.wait(timeout=15)
                    except BaseException as error:proof['cleanup_error']=f'{type(error).__name__}: {error}'
                proof['owned_vm_exited']=proc is None or proc.poll() is not None
                if directory_test and proof['owned_vm_exited']:
                    proof['directory_commit_status']=read_commit_status(run/'console.log')
                    status=proof['directory_commit_status']
                    proof['directory_commit_clean_verified']=bool(
                        status['available'] and not status['pending'] and not status['closed_pending'])
                # Never release this disk's lease while its owned writer may still exist.
                if not proof['owned_vm_exited']:
                    (run/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
                    print('HOST_SD_HELPER_RETAINED',run,flush=True)
                    while proc.poll() is None:time.sleep(1)
                os.close(extra)
            if proof.get('guest_raw_io_verified') and proof['owned_vm_exited']:
                for n,offset in enumerate((0,4*1024**3+512,TOTAL-512)):
                    expected=bytes((0x31+n*37+i*13)&255 for i in range(512))
                    assert os.pread(lease['fd'],512,offset)==expected
                proof.update(ok=True,host_after_exit_readback_verified=True)
            if directory_test and proof.get('original_fsys_diagnostic_verified') and proof['owned_vm_exited']:
                try:
                    if not proof.get('directory_commit_clean_verified'):
                        raise RuntimeError('directory vvfat closed without a clean host commit')
                    probe_path=fat_host_path(directory_root,'QTEST/PROBE.BIN')
                    actual=probe_path.read_bytes()
                    expected=bytes((i*37+9)&255 for i in range(4096))
                    assert actual==expected
                    assert (directory_root/'INPUT.BIN').read_bytes()==b'original host directory input\x00\xff'
                    nested_bytes=0
                    if nested_test:
                        nested_path=fat_host_path(directory_root,'QTEST/NESTED/DEEP/BIG.BIN')
                        nested=nested_path.read_bytes()
                        expected_nested=bytes((i*37+9)&255 for i in range(1048576))
                        assert nested==expected_nested
                        nested_bytes=len(nested)
                        proof['nested_fsys_test_file_sha256']=hashlib.sha256(nested).hexdigest()
                        proof['nested_host_fat_path']=str(nested_path.relative_to(directory_root))
                    proof.update(ok=True,host_after_exit_readback_verified=True,
                                 original_fsys_test_file_bytes=len(actual),nested_fsys_test_file_bytes=nested_bytes,
                                 original_fsys_logical_path='QTEST/PROBE.BIN',
                                 host_fat_path=str(probe_path.relative_to(directory_root)),
                                 fat_case_insensitive_unique_lookup=True,
                                 original_fsys_test_file_sha256=hashlib.sha256(actual).hexdigest(),
                                 formatted_by_camera=False,
                                 filesystem_image_check='not_applicable_directory_vvfat')
                except BaseException as error:
                    proof.update(ok=False,error=f'host directory validation: {type(error).__name__}: {error}')
            elif proof.get('original_fsys_diagnostic_verified') and proof['owned_vm_exited']:
                try:
                    checked=subprocess.run(['fsck.fat','-n',f'/proc/self/fd/{lease["fd"]}'],pass_fds=(lease['fd'],),
                                           capture_output=True,timeout=60)
                    (run/'host-after-fsys-fsck.txt').write_bytes(checked.stdout+checked.stderr)
                    proof['host_fsck_rc']=checked.returncode
                    with (run/'test-file-host-readback.bin').open('xb') as output:
                        subprocess.run(['7z','e','-so',str(disk/'card.img'),'QTEST/PROBE.BIN'],
                            stdout=output,stderr=subprocess.PIPE,check=True,timeout=30)
                    actual=(run/'test-file-host-readback.bin').read_bytes()
                    assert actual==bytes((i*37+9)&255 for i in range(4096))
                    proof.update(ok=checked.returncode==0,host_after_exit_readback_verified=True,
                                 original_fsys_test_file_bytes=len(actual),formatted_by_camera=False)
                    if checked.returncode:proof['error']='Strict readonly fsck failed; no repair or pass override'
                except BaseException as error:
                    proof.update(ok=False,error=f'host validation: {type(error).__name__}: {error}')
            (run/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
            print('HOST_SD_HELPER_RESULT',run,json.dumps(proof),flush=True)
    return 0 if proof['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
