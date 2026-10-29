#!/usr/bin/env python3
"""Original CCF API execution plus hardware effects; no PHY/PCI/DMA admission."""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
EXPECTED=((62,99000000),(63,396000000),(64,396000000),(65,396000000),(66,1000000),(29,0),(30,0))


def actual_rows(raw):
    raw=raw.replace(b'\r',b'')
    rows=re.findall(rb'^(?:\[\s*\d+(?:\.\d+)?\]\s*)?NATIVE_CCF_CLOCK: id=(\d+) rate=(\d+) before=(\d+) enabled=(\d+) after=(\d+)\s*$',raw,re.M)
    return [tuple(int(v) for v in row) for row in rows]


def observe(qmp,serial_command,run,proc,console,result):
    client=HERE/'ccf-client';checked=subprocess.run([sys.executable,'-B',str(client/'check_client.py')],check=True,capture_output=True,text=True)
    (run/'native-ccf-host-abi.json').write_text(checked.stdout)
    payload=(client/'sony_ccf_client.ko').read_bytes();digest=hashlib.sha256(payload).hexdigest()
    assert digest==json.loads(checked.stdout)['sha256'];result['native_ccf_client_sha256']=digest
    trace_path=run/'output/boot-trace.log';trace_offset=trace_path.stat().st_size
    command=('cat > /tmp/sony_ccf_client.b64 <<\'NATIVE_CCF_B64_END\'\n'+base64.encodebytes(payload).decode()+'NATIVE_CCF_B64_END\n'
        '/usr/bin/openssl base64 -d -in /tmp/sony_ccf_client.b64 -out /tmp/sony_ccf_client.ko\n'
        '/usr/bin/openssl dgst -sha256 /tmp/sony_ccf_client.ko > /tmp/ccf.sha\ncat /tmp/ccf.sha\n'
        'if grep -q "'+digest+'$" /tmp/ccf.sha; then\ninsmod /tmp/sony_ccf_client.ko\n'
        'echo NATIVE_CCF_LOAD_RC=$?\ngrep "^sony_ccf_client " /proc/modules\nfi\ntrue')
    raw=serial_command(proc,console,command,timeout=30);(run/'native-ccf-client.txt').write_bytes(raw);clean=raw.replace(b'\r',b'')
    expected=[(ident,rate,0,1,0) for ident,rate in EXPECTED]
    if (b'\nNATIVE_CCF_LOAD_RC=0\n' not in clean or not re.search(rb'^sony_ccf_client\s+\d+\s+\d+\s+.*\bLive\b',clean,re.M)
            or actual_rows(clean)!=expected or b'NATIVE_CCF_PASS:' not in clean):
        raise ValueError('Actual original CCF clock API rows/load state differ')
    if re.search(rb'WARNING: CPU:|Kernel panic|BUG:',console.read_bytes()):raise ValueError('Kernel warning/fault during CCF client')
    trace=trace_path.read_bytes()[trace_offset:];(run/'native-ccf-client-mmio.log').write_bytes(trace)
    events=[]
    for m in re.finditer(rb"memory_region_ops_write .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name 'test-pcie-scu-region0'",trace):
        address,value,size=m.groups();events.append((int(address,16),int(value,16),int(size)))
    for ident,_ in EXPECTED:
        address,mask=(0xf1388080,1<<(ident-61)) if ident>=62 else (0xf1388030,1<<(ident-11))
        setting=(address+4,mask,4);clearing=(address+8,mask,4)
        assert setting in events and clearing in events and events.index(setting)<events.index(clearing)
    result['native_ccf_api_rows']=[list(row) for row in expected]
    result['native_ccf_gate_sequences_verified']=True
    qmp('stop')
    try:
        assert not qmp('query-status')['running']
        for address,label in ((0xf1388030,'gate30'),(0xf1388080,'gate80')):
            text=qmp('human-monitor-command',{'command-line':f'xp /1wx 0x{address:x}'})
            (run/('native-ccf-'+label+'.txt')).write_text(text)
            values=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[1]);assert len(values)==1 and int(values[0],16)==0
    finally:qmp('cont')
    token='NATIVE_CCF_CPU_RESUMED_'+run.name.replace('-','_')
    raw=serial_command(proc,console,'echo '+token,timeout=15);(run/'native-ccf-cpu-resumed.txt').write_bytes(raw)
    assert ('\n'+token+'\n').encode() in raw.replace(b'\r',b'')
    result['native_ccf_provider_verified']=True;result['native_ccf_cpu_resumed']=True
