#!/usr/bin/env python3
"""Original pcidma_connect/transfer_async: one direct AP->PCI write + PCI->AP read-back,
real IRQ/thread/callback path, data verified in both guest and QEMU."""
import base64
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
PATTERN=bytes((i*29+7)&0xff for i in range(256))

def irq198_count(raw):
    clean=raw.replace(b'\r',b'')
    m=re.search(rb'^\s*198:\s+(\d+)\s+GIC-0\s+198\s+(?:Level|Edge)\s+([^\n]*)$',clean,re.M)
    assert m and b'PCIeDMAC' in m.group(2),'missing PCIeDMAC IRQ198 row'
    return int(m.group(1))

def observe(qmp,serial_command,run,proc,console,result):
    client=HERE/'pcidma-client'
    checked=subprocess.run([sys.executable,'-B',str(client/'check_client.py')],check=True,capture_output=True,text=True)
    (run/'native-pcidma-client-abi.json').write_text(checked.stdout)
    payload=(client/'sony_pcidma_xfer.ko').read_bytes();digest=hashlib.sha256(payload).hexdigest()
    assert digest==json.loads(checked.stdout)['sha256'];result['native_pcidma_client_sha256']=digest
    trace_path=run/'output/boot-trace.log';trace_offset=trace_path.stat().st_size
    # Cross-check peer BAR0 assignment before the module computes it itself.
    observed=serial_command(proc,console,
        'cat /sys/bus/pci/devices/0000:01:00.0/resource\n'
        'cat /proc/interrupts\ntrue',timeout=15)
    (run/'native-pcidma-before.txt').write_bytes(observed)
    clean=observed.replace(b'\r',b'')
    m=re.search(rb'^(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+0x[0-9a-f]+$',clean,re.M)
    assert m,'peer BAR0 resource row missing'
    bar_start=int(m.group(1),16);assert bar_start,'peer BAR0 unassigned'
    result['native_pcidma_peer_bar0']=hex(bar_start)
    irq_before=irq198_count(observed)
    command=('cat > /tmp/sony_pcidma_xfer.b64 <<\'NATIVE_PCIDMA_B64_END\'\n'+base64.encodebytes(payload).decode()+'NATIVE_PCIDMA_B64_END\n'
        '/usr/bin/openssl base64 -d -in /tmp/sony_pcidma_xfer.b64 -out /tmp/sony_pcidma_xfer.ko\n'
        '/usr/bin/openssl dgst -sha256 /tmp/sony_pcidma_xfer.ko > /tmp/x.sha\ncat /tmp/x.sha\n'
        'if grep -q "'+digest+'$" /tmp/x.sha; then\ninsmod /tmp/sony_pcidma_xfer.ko\n'
        'echo NATIVE_PCIDMA_LOAD_RC=$?\ngrep "^sony_pc_pci_dma_xfer " /proc/modules\nfi\ntrue')
    raw=serial_command(proc,console,command,timeout=45);(run/'native-pcidma-client.txt').write_bytes(raw)
    clean=raw.replace(b'\r',b'')
    if b'\nNATIVE_PCIDMA_LOAD_RC=0\n' not in clean or not re.search(rb'^sony_pc_pci_dma_xfer\s+\d+\s+\d+\s+.*\bLive\b',clean,re.M):
        raise ValueError('client module did not load Live')
    if re.search(rb'NATIVE_PCIDMA_FAILED',clean):raise ValueError('client reported failure')
    rows=re.findall(rb'^(?:\[\s*\d+(?:\.\d+)?\]\s*)?NATIVE_PCIDMA_(CONNECT|CALLBACK|WRITE_DONE|PASS):([^\n]*)$',clean,re.M)
    names=[r[0] for r in rows]
    assert names==[b'CONNECT',b'CALLBACK',b'WRITE_DONE',b'CALLBACK',b'PASS'],names
    m=re.search(rb'peer_bar=(\d+)',rows[0][1]);assert m and int(m.group(1))==bar_start,'module/sysfs BAR mismatch'
    for row in (rows[1],rows[3]):
        assert b'status=0' in row[1],'callback status nonzero: '+row[1]
    assert b'status=0 cookie=1234605616436508552' in rows[1][1]  # 0x1122334455667788 unsigned
    assert b'status=0 cookie=11936128518282651045' in rows[3][1]  # 0xa5a5a5a5a5a5a5a5 unsigned (%lu)
    observed=serial_command(proc,console,'cat /proc/interrupts\ntrue',timeout=15)
    (run/'native-pcidma-after.txt').write_bytes(observed)
    irq_after=irq198_count(observed)
    assert irq_after>=irq_before+2,f'IRQ198 did not fire for both transfers: {irq_before}->{irq_after}'
    result['native_pcidma_irq198_counts']=[irq_before,irq_after]
    if re.search(rb'WARNING: CPU:|Kernel panic|BUG:|Oops:',console.read_bytes()):
        raise ValueError('kernel warning/fault during PCI DMA transfer')
    (run/'native-pcidma-mmio.log').write_bytes(trace_path.read_bytes()[trace_offset:])
    qmp('stop')
    try:
        deadline=time.monotonic()+10
        while qmp('query-status')['running']:
            assert time.monotonic()<deadline,'owned VM did not pause'
            time.sleep(.05)
        text=qmp('human-monitor-command',{'command-line':'xp /64wx 0x600000000'})
        (run/'native-pcidma-peer-ram.txt').write_text(text)
        words=[int(v,16) for v in re.findall(r'0x([0-9a-fA-F]{8})',text)]
        assert len(words)==64,'peer RAM read incomplete'
        actual=b''.join(w.to_bytes(4,'little') for w in words)
        assert actual==PATTERN,'peer RAM does not hold the AP->PCI written pattern'
        engines=[]
        for offset,label in ((0xc,'write-enable'),(0x2c,'read-enable'),(0x4c,'write-status'),(0xa0,'read-status')):
            text=qmp('human-monitor-command',{'command-line':'xp /1wx 0x%x'%(0xf7380000+offset)})
            (run/('native-pcidma-engine-'+label+'.txt')).write_text(text)
            w=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[-1]);assert len(w)==1;engines.append(int(w[0],16))
        assert engines==[1,1,0,0],'engine not enabled-idle with cleared status: '+str(engines)
        result['native_pcidma_engine_state']=engines
    finally:qmp('cont')
    token='NATIVE_PCIDMA_CPU_RESUMED_'+run.name.replace('-','_')
    resumed=serial_command(proc,console,'echo '+token,timeout=15)
    (run/'native-pcidma-cpu-resumed.txt').write_bytes(resumed)
    assert ('\n'+token+'\n').encode() in resumed.replace(b'\r',b'')
    result.update(native_pcidma_transfer_verified=True,native_pcidma_cpu_resumed=True,
        dma_executed=True,capture_verified=False)
    result['ok']=True
