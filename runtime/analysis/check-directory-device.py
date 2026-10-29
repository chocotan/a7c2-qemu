"""Independent QEMU vvfat test, no camera boot and no physical media."""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile

from directory_geometry import check_boot
from directory_sd import directory_lease
from directory_snapshot import read_commit_status
from menu_live import connect_in_run

BASE = Path(__file__).resolve().parent


def main():
    binary = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else BASE.parent/'sources/qemu-11.1.2/build-sony-ui/qemu-system-aarch64'
    if not binary.is_file():
        raise ValueError('QEMU binary missing')
    root_parent = BASE/'directory-sd-tests'
    root_parent.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='directory-device-', dir=BASE/'menu-runs'))
    root = Path(tempfile.mkdtemp(prefix='device-card-', dir=root_parent))
    proof = dict(ok=False, scope='QEMU directory vvfat only, no original Fsys or capture',
                 directory=str(root), binary=str(binary), firmware_format_verified=False)
    with directory_lease(root) as lease:
        extra = os.dup(lease['fd'])
        proc = None
        try:
            original = bytes((i * 29 + 7) & 255 for i in range(512))
            (root/'INPUT.BIN').write_bytes(original)
            scratch = run/'vvfat-writeback';scratch.mkdir(mode=0o700)
            command = ['bwrap','--unshare-all','--die-with-parent','--clearenv',
                '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib','/lib64',
                '--proc','/proc','--dev','/dev','--tmpfs','/tmp',
                '--ro-bind',str(binary),'/tools/qemu-system-aarch64',
                '--ro-bind',str(BASE.parent/'sources/qemu-tools/usr/lib'),'/tools/usr/lib',
                '--dir','/sd','--bind-fd',str(extra),'/sd',
                '--dir','/var/tmp','--bind',str(scratch),'/var/tmp',
                '--bind',str(run),'/out','--chdir','/','--setenv','LD_LIBRARY_PATH','/tools/usr/lib',
                '--','/tools/qemu-system-aarch64','-machine','none','-nodefaults','-display','none','-S',
                '-qmp','unix:/out/qmp.sock,server=on,wait=off',
                '-blockdev','driver=vvfat,node-name=card,dir=/sd,rw=on,fat-type=32,total-sectors=500000000']
            with (run/'console.log').open('wb') as output:
                proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                         stderr=subprocess.STDOUT, pass_fds=(extra,))
                socket_path = run/'qmp.sock'
                deadline = __import__('time').monotonic()+30
                while not socket_path.exists():
                    if proc.poll() is not None:
                        raise RuntimeError('QEMU exited before QMP: '+(run/'console.log').read_text(errors='replace'))
                    if __import__('time').monotonic()>deadline:
                        raise TimeoutError('QMP socket timeout')
                    __import__('time').sleep(.05)
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(30);connect_in_run(client,run,'qmp.sock');stream=client.makefile('rwb',buffering=0)
                    greeting = stream.readline()
                    if b'QMP' not in greeting:raise RuntimeError('QMP greeting missing')
                    def qmp(name,args=None):
                        stream.write((json.dumps({'execute':name,**({'arguments':args} if args else {}), 'id':name})+'\n').encode())
                        while True:
                            line=stream.readline()
                            if not line:raise RuntimeError('QMP closed')
                            message=json.loads(line)
                            if message.get('id')==name:
                                if 'error' in message:raise RuntimeError(str(message))
                                return message.get('return')
                    def io(command):
                        start=(run/'console.log').stat().st_size
                        qmp('human-monitor-command',{'command-line':f'qemu-io card "{command}"'})
                        with (run/'console.log').open('rb') as console:
                            console.seek(start)
                            return console.read().decode(errors='replace')
                    def read_bytes(offset,length):
                        text=io(f'read -v {offset} {length}')
                        result=bytearray()
                        for line in text.splitlines():
                            match=re.match(r'\s*([0-9a-fA-F]+):\s*((?:[0-9a-fA-F]{2}\s+){1,16})',line)
                            if not match:continue
                            words=re.findall(r'[0-9a-fA-F]{2}',match[2])
                            if words:
                                assert int(match[1],16)==offset+len(result), (match[1],offset,len(result),text)
                                result.extend(int(word,16) for word in words)
                        if len(result)!=length:raise RuntimeError(f'QEMU read shape {offset}/{length}: {text}')
                        (run/f'read-{offset:x}.txt').write_text(text)
                        return bytes(result)
                    qmp('qmp_capabilities')
                    mbr=read_bytes(0,512);boot=read_bytes(63*512,512)
                    info=read_bytes(64*512,512);backup=read_bytes(69*512,512)
                    backup_info=read_bytes(70*512,512)
                    layout=check_boot(mbr,boot,info)
                    assert backup==boot and backup_info==info
                    assert len(read_bytes(255999999488,512))==512
                    proof['geometry_verified']=True
                    # Linux page writeback can cross reserved->FAT at LBA88..95.
                    boundary_offset=(layout['offset_fat']-7)*512
                    boundary=read_bytes(boundary_offset,8*512)
                    (run/'fat-boundary.bin').write_bytes(boundary)
                    io(f'write -s /out/fat-boundary.bin {boundary_offset} {len(boundary)}')
                    io('flush')
                    assert read_bytes(boundary_offset,len(boundary))==boundary
                    proof['fat_boundary_write_verified']=True
                    protected=bytearray(boundary)
                    protected[0]^=1
                    (run/'fat-boundary-bad.bin').write_bytes(protected)
                    rejected=io(f'write -s /out/fat-boundary-bad.bin {boundary_offset} {len(boundary)}')
                    if not any(word in rejected for word in ('protected sector','write failed','Input/output error')):
                        raise RuntimeError('Changed protected FAT-boundary byte was not rejected: '+rejected)
                    assert read_bytes(boundary_offset,len(boundary))==boundary
                    proof['protected_boundary_reject_verified']=True
                    root_bytes=read_bytes(layout['offset_root']*512,layout['sectors_per_cluster']*512)
                    entry=None
                    for i in range(0,len(root_bytes),32):
                        candidate=root_bytes[i:i+32]
                        if candidate[:11]==b'INPUT   BIN' and candidate[11] not in (0x0f,0x28):
                            entry=candidate;break
                    if entry is None:raise RuntimeError('INPUT.BIN not found in FAT root')
                    cluster=int.from_bytes(entry[26:28],'little') | int.from_bytes(entry[20:22],'little')<<16
                    size=int.from_bytes(entry[28:32],'little')
                    assert size==len(original) and cluster>=2
                    data_offset=layout['offset_root']*512+(cluster-2)*layout['sectors_per_cluster']*512
                    assert read_bytes(data_offset,size)==original
                    proof['existing_host_file_read_verified']=True
                    replacement=bytes([0x5a])*512
                    io(f'write -P 0x5a {data_offset} 512')
                    io('flush')
                    assert (root/'INPUT.BIN').read_bytes()==replacement
                    assert read_bytes(data_offset,512)==replacement
                    proof.update(host_writeback_verified=True,flush_verified=True,
                                 replacement_sha256=hashlib.sha256(replacement).hexdigest())
                    proof['ok']=True
                    qmp('quit')
                    proc.wait(timeout=15)
        except BaseException as error:
            proof['error']=f'{type(error).__name__}: {error}'
        finally:
            if proc is not None and proc.poll() is None:
                try:
                    # A normal QMP close is the only cleanup route for a writable directory.
                    if 'qmp' in locals():
                        qmp('quit')
                    proc.wait(timeout=15)
                except BaseException as error:
                    proof['cleanup_error']=f'{type(error).__name__}: {error}'
                    (run/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
                    print('DIRECTORY_DEVICE_RETAINED',run,flush=True)
                    proc.wait()
            proof['owned_qemu_exited']=proc is None or proc.poll() is not None
            os.close(extra)
        proof['directory_commit_status']=read_commit_status(run/'console.log')
        status=proof['directory_commit_status']
        proof['directory_commit_clean_verified']=bool(
            status['available'] and not status['pending'] and not status['closed_pending'])
        proof['host_directory_after_exit_verified']=bool(
            proof.get('host_writeback_verified') and proof['owned_qemu_exited'] and
            proof['directory_commit_clean_verified'])
        if not proof['directory_commit_clean_verified'] and not proof.get('error'):
            proof['error']='Directory vvfat commit tracking is unavailable or still pending'
        proof['ok']=bool(proof['ok'] and proof['owned_qemu_exited'] and proof['directory_commit_clean_verified'])
        (run/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
        print('DIRECTORY_DEVICE_RESULT',run,json.dumps(proof),flush=True)
    return 0 if proof['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
