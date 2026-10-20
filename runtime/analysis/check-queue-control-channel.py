#!/usr/bin/env python3
"""Serial QEMU monitor-only fixture: no firmware, CPU, disks, USB or network."""
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

from request_queue_watch import CONTROL_SOCKET, resume_owned_debug_cpu

BASE=Path(__file__).resolve().parent
QEMU=BASE.parent/'sources/qemu-11.1.2/build-sony-ui/qemu-system-aarch64'


def main():
    with (BASE/'.menu-probe.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix='sony-qmp-control-') as tmp:
            root=Path(tmp);fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
            with (root/'qemu.log').open('wb') as log:
                proc=subprocess.Popen([str(QEMU),'-machine','none','-nodefaults','-display','none','-nic','none','-S',
                    '-qmp','unix:primary.sock,server=on,wait=off',
                    '-qmp',f'unix:{CONTROL_SOCKET},server=on,wait=off'],cwd=root,stdout=log,stderr=subprocess.STDOUT)
                try:
                    with socket.socket(socket.AF_UNIX) as primary:
                        primary.settimeout(4);deadline=time.monotonic()+8
                        while True:
                            try:primary.connect(f'/proc/self/fd/{fd}/primary.sock');break
                            except (FileNotFoundError,ConnectionRefusedError):
                                if proc.poll() is not None or time.monotonic()>deadline:
                                    raise RuntimeError((root/'qemu.log').read_text(errors='replace')[-4000:])
                                time.sleep(.05)
                        with primary.makefile('rwb') as stream:
                            assert 'QMP' in json.loads(stream.readline(65536))
                            sequence=0
                            def qmp(command):
                                nonlocal sequence
                                sequence+=1
                                stream.write((json.dumps({'execute':command,'id':sequence})+'\n').encode());stream.flush()
                                for _ in range(32):
                                    reply=json.loads(stream.readline(65536))
                                    if 'event' in reply:continue
                                    assert reply.get('id')==sequence and 'error' not in reply
                                    return reply
                                raise RuntimeError('Fixture QMP event limit')
                            qmp('qmp_capabilities');qmp('cont');qmp('stop')
                            assert qmp('query-status')['return']['status']=='paused'
                            # Primary stays connected: cleanup must not wait for SDK QMP/serial.
                            assert resume_owned_debug_cpu(fd)['cpu_running_verified']
                            assert qmp('query-status')['return']['running'] is True
                            qmp('quit');proc.wait(timeout=5)
                    print('PRIVATE_DUAL_QMP_RESUME_PASS; monitor-only machine none, no firmware/CPU/media')
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        try:proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)
                    os.close(fd)


if __name__=='__main__':main()
