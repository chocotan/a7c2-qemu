#!/usr/bin/env python3
"""Bounded RSP fixture: original args captured, no register/memory writes."""
import json
from pathlib import Path
import runpy
import select
import socket
import tempfile
import threading
import time


def main():
    module=runpy.run_path(str(Path(__file__).with_name('boot-fatal-probe.py')))
    with tempfile.TemporaryDirectory(prefix='fatal-rsp-') as folder:
        run=Path(folder);(run/'console.log').write_text('OBS OBSERVER_READY pid=123 base=0x100000000\n')
        listener=socket.socket(socket.AF_UNIX);listener.bind(str(run/'fatal-gdb.sock'));listener.listen(1)
        failures=[];seen=[]
        def serve():
            conn=None
            try:
                conn,_=listener.accept()
                def packet(text):
                    data=text.encode();conn.sendall(b'$'+data+b'#'+f'{sum(data)&255:02x}'.encode())
                continuing=0
                while True:
                    byte=conn.recv(1)
                    if not byte:break
                    if byte==b'\x03':packet('T02thread:p1.1;');continue
                    if byte!=b'$':continue
                    data=b''
                    while True:
                        byte=conn.recv(1)
                        if byte==b'#':break
                        if not byte:raise ValueError('Truncated fixture request')
                        data+=byte
                    if int(conn.recv(2),16)!=(sum(data)&255):raise ValueError('Bad fixture checksum')
                    conn.sendall(b'+');command=data.decode();seen.append(command)
                    if command=='?':packet('T05thread:p1.1;')
                    elif command=='qC':packet('QCp1.1')
                    elif command.startswith(('Z0,','z0,','Hg')):packet('OK')
                    elif command=='c':
                        continuing+=1
                        if continuing==2:packet('T05thread:p1.1;')
                    elif command=='g':
                        regs=[0]*31;regs[1]=0x2000;regs[2]=0x1c3;regs[3]=0x11;regs[19]=0x3000
                        data=b''.join(value.to_bytes(8,'little') for value in regs)
                        data+=(0x4000).to_bytes(8,'little')
                        data+=(0x100000000+module['BootFatalProbe'].OFFSET).to_bytes(8,'little')+bytes(4)
                        packet(data.hex())
                    elif command.startswith('m2000,'):packet(b'sequence/sequence_boot.cpp\0'.hex())
                    elif command.startswith('m3000,'):packet(b'void model::sequence_boot::run_i()\0'.hex())
                    else:raise ValueError('Unexpected request: '+command)
            except (ConnectionResetError,BrokenPipeError) as error:
                # The client closes after its final resume without waiting for
                # an ACK. Only accept this teardown once capture was written.
                if not (run/'original-boot-fatal.json').is_file():failures.append(error)
            except BaseException as error:failures.append(error)
            finally:
                if conn:conn.close()
        worker=threading.Thread(target=serve,daemon=True);worker.start()
        probe=module['BootFatalProbe'](run,lambda sock,root,name:sock.connect(str(root/name)))
        try:
            until=time.monotonic()+5
            while time.monotonic()<until:
                probe.check()
                if probe.captured:break
                select.select([probe.socket],[],[],0.1)
            if not probe.captured:raise ValueError('Missing original fatal capture')
            record=json.loads((run/'original-boot-fatal.json').read_text())
            if (record['source_line'],record['original_error'],record['source_file'])!=(0x1c3,'0x11','sequence/sequence_boot.cpp'):
                raise ValueError('Original arguments were not preserved')
            if any(command.startswith(('P','G','M')) for command in seen):raise ValueError('Mutating RSP request')
        finally:
            probe.close();worker.join(2);listener.close()
        if failures:raise failures[0]
    print('BOOT_FATAL_RSP_READ_ONLY_CAPTURE_PASS')


if __name__=='__main__':main()
