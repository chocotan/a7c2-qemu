#!/usr/bin/env python3
"""Exercise the actual upstream controller registers, with no guest/USB device."""
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time


def main(binary):
    env={k:v for k,v in os.environ.items() if not k.startswith(('QEMU_','SONY_','MENU_'))}
    env['QEMU_SONY_USB_DWC3']='1'
    process=subprocess.Popen([str(binary),'-machine','virt,secure=off','-cpu','cortex-a35',
        '-m','4096','-accel','tcg','-S','-nodefaults','-display','none','-monitor','none',
        '-serial','none','-nic','none','-qtest','stdio','-qtest-log','/dev/null'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        commands='readb 0xf10c0000\nreadl 0xf10c0004\nreadl 0xf10cc120\nreadl 0xf10cc110\nreadl 0xf10cc140\n'
        process.stdin.write(commands);process.stdin.flush()
        values=[];pending=b''
        selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
        until=time.monotonic()+15
        while len(values)<5 and time.monotonic()<until:
            if not selector.select(max(0,until-time.monotonic())):break
            chunk=os.read(process.stdout.fileno(),4096)
            if not chunk:break
            pending+=chunk
            while b'\n' in pending:
                line,pending=pending.split(b'\n',1)
                if line.startswith(b'OK 0x'):values.append(int(line.split()[1],16))
        selector.close()
        if len(values)!=5:
            raise RuntimeError('Controller register readback incomplete: '+repr(values))
        caplength,hcsparams,synopsys,gctl,hwparams=values
        print('UPSTREAM_DWC3_REGISTER_READBACK',*[hex(value) for value in values])
        if not (0x20<=caplength<=0x100 and caplength%4==0 and (hcsparams>>24)>0):
            raise RuntimeError('Upstream xHCI capabilities are invalid')
        # MODE is a hardware capability in GHWPARAMS0; GCTL is writable
        # operational state and need not already have been configured by a guest.
        if synopsys>>16!=0x5533 or hwparams&7!=1:
            raise RuntimeError('Upstream DWC3 identity/host-mode readback is invalid')
        print('UPSTREAM_DWC3_REAL_REGISTERS_PASS',*[hex(value) for value in values])
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)


if __name__=='__main__':main(Path(sys.argv[1]).resolve(strict=True))
