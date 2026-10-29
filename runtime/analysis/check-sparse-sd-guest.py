#!/usr/bin/env python3
"""Disposable helper-only QEMU smoke test: no camera app, no physical media."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from initramfs_identity import verify_image
from menu_live import serial_command
from sd_sparse import parse_map, TOTAL

BASE=Path(__file__).resolve().parent


def main():
    env={k:v for k,v in os.environ.items() if not k.startswith(('MENU_','QEMU_','A7C2_','SONY_'))}
    env.update(SEED_BACKUP='alllang',QEMU_TIMEOUT_SECONDS='0',QEMU_CPU_COUNT='1')
    with (BASE/'.menu-probe.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        output=Path(tempfile.mkdtemp(prefix='sparse-helper-',dir=BASE/'menu-runs'))
        proof={'ok':False,'scope':'helper-only QEMU; camera app/format/capture not executed'}
        proc=None
        try:
            built=subprocess.run(['bash',str(BASE/'prepare-menu-initramfs.sh')],env=env,
                                  capture_output=True,check=True,timeout=120)
            (output/'initramfs-build.log').write_bytes(built.stdout+built.stderr)
            image=BASE/'menu-initramfs.cpio'
            helper=BASE/'menu-root/simulation/sd-sparse'
            proof['verified_initramfs']=verify_image(image,{'simulation/sd-sparse':hashlib.sha256(helper.read_bytes()).hexdigest()},
                        forbidden=('tmp/sd10g.ready','tmp/sony-sd10g/card.img'))
            env['QEMU_OUTPUT_DIR']=str(output)
            command=['bash',str(BASE/'qemu-kernel-probe.sh'),'4096',
                     str(BASE/'qemu-virt-board/virt-packed.dtb'),'1','1',str(image)]
            console=output/'console.log'
            with console.open('wb') as log:
                proc=subprocess.Popen(command,env=env,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT)
                deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    if proc.poll() is not None:raise RuntimeError('Helper VM exited before shell')
                    raw=console.read_bytes()
                    if b'/ #' in raw:break
                    time.sleep(.1)
                else:raise TimeoutError('No helper guest shell')
                def run(name,command):
                    raw=serial_command(proc,console,command,timeout=40,allow_faulted_cleanup=True)
                    (output/name).write_bytes(raw)
                    return raw
                run('create.txt','mount -t proc proc /proc && mount -t tmpfs -o size=512m tmpfs /tmp && '
                    'mkdir /tmp/sony-sd10g && mount -t tmpfs -o size=512m tmpfs /tmp/sony-sd10g && '
                    '/simulation/sd-sparse create && : > /image_mmca && '
                    'mount -o bind /tmp/sony-sd10g/card.img /image_mmca')
                empty=parse_map(run('empty-map.txt','/simulation/sd-sparse map'),TOTAL)
                assert not empty['ranges'] and empty['allocated_bytes']==0
                # Read/write actual high offsets via guest dd; these are disposable zero test pages.
                run('high-offset-write.txt',
                    'dd if=/dev/zero of=/image_mmca bs=4096 seek=524288 count=1 conv=notrunc && '
                    'dd if=/dev/zero of=/image_mmca bs=4096 seek=1048576 count=1 conv=notrunc && '
                    'dd if=/dev/zero of=/image_mmca bs=4096 seek=2621439 count=1 conv=notrunc')
                mapped=parse_map(run('written-map.txt','/simulation/sd-sparse map'),TOTAL)
                assert mapped['data_bytes']>=3*4096 and mapped['allocated_bytes']<1024*1024
                for point in (2*1024**3,4*1024**3,TOTAL-1):
                    assert sum(a<=point<a+b for a,b in mapped['ranges'])==1
                run('memory.txt','grep -E "^(MemAvailable|Shmem|MemFree):" /proc/meminfo; ls -l /image_mmca')
                proof.update(ok=True,empty_map=empty,written_map=mapped,
                             original_menu_format_verified=False,physical_media_access=False)
        except BaseException as error:
            proof['error']=f'{type(error).__name__}: {error}'
            raise
        finally:
            if proc is not None and proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proof['ok']=False;proof['cleanup_error']='Owned helper VM retained; no SIGKILL'
            proof['owned_vm_exited']=proc is None or proc.poll() is not None
            (output/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
            print('SPARSE_HELPER_GUEST_RESULT',output,json.dumps(proof),flush=True)
    return 0 if proof['ok'] and proof['owned_vm_exited'] else 1


if __name__=='__main__':raise SystemExit(main())
