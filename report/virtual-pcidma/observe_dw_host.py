#!/usr/bin/env python3
"""Original-kernel PCI core TEST host observation; no PCIDMA or PHY completion."""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ECAM=0x4010000000


def parse_host(data):
    data=data.replace(b'\r',b'')
    loaded=bool(b'\nOWNED_DW_HOST_LOAD_RC=0\n' in data and
        re.search(rb'^sony_dw_test_host\s+\d+\s+\d+\s+\S+\s+Live\b',data,re.M))
    bus=re.search(rb'PCI_CORE_TEST_BUS: domain=(-?\d+) bus=(\d+)\b',data)
    endpoints=re.findall(rb'PCI_CORE_TEST_ENDPOINT: id=([0-9a-f]{8}) bar0=([0-9a-f]{8}) reads=(\d+) writes=(\d+)',data)
    endpoint=endpoints[0] if len(endpoints)==1 else None
    valid=bool(loaded and bus and bus.groups()==(b'0',b'0') and endpoint and
        endpoint[0]==b'00051b36' and int(endpoint[2])>0 and int(endpoint[3])>0 and
        b'DW_TEST_HOST_ENUM_PASS:' in data)
    if valid:
        bar=int(endpoint[1],16)
        valid=0x10000000<=bar<=0x1f000000 and bar%0x1000000==0
    else:bar=None
    return {'dw_test_host_loaded':loaded,'dw_test_host_enum_markers_verified':valid,
            'dw_test_host_bar':hex(bar) if bar is not None else None}


def word(qmp,address,run,label):
    text=qmp('human-monitor-command',{'command-line':f'xp /1wx 0x{address:x}'})
    (run/(label+'.txt')).write_text(text)
    values=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[-1])
    if len(values)!=1:raise ValueError('QMP did not return one actual config word')
    return int(values[0],16)


def parse_controls(trace):
    events=[]
    for row in re.finditer(r"memory_region_ops_write .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name '(test-root-(?:dbi|wrapper))'",trace):
        address,value,size,name=row.groups();address=int(address,16)
        base,extent=(0xf7000000,4096) if name=='test-root-dbi' else (0xf11c0000,0x40000)
        # CPU log backend reports absolute PA; some trace consumers use MR offset.
        if base<=address<base+extent:address-=base
        elif not 0<=address<extent:raise ValueError('MMIO trace address outside named region')
        events.append((name,address,int(value,16),int(size)))
    controls=[e for e in events if (e[0],e[1]) in (('test-root-wrapper',0x20380),('test-root-dbi',0x8bc))]
    expected=[('test-root-wrapper',0x20380,0,4),('test-root-dbi',0x8bc,1,4),
              ('test-root-dbi',0x8bc,0,4),('test-root-wrapper',0x20380,0x40,4)]
    return controls==expected,events


def run_host(qmp,serial_command,run,proc,console,result):
    client=HERE/'dw-test-host'
    checked=subprocess.run([sys.executable,'-B',str(client/'check_client.py')],check=True,capture_output=True,text=True)
    (run/'dw-host-host-check.json').write_text(checked.stdout)
    payload=(client/'sony_dw_test_host.ko').read_bytes();digest=hashlib.sha256(payload).hexdigest()
    assert digest==json.loads(checked.stdout)['sha256'];result['dw_test_host_sha256']=digest
    command=('cat > /tmp/sony_dw_test_host.b64 <<\'OWNED_DW_HOST_B64_END\'\n'
        +base64.encodebytes(payload).decode('ascii')+'OWNED_DW_HOST_B64_END\n'
        '/usr/bin/openssl base64 -d -in /tmp/sony_dw_test_host.b64 -out /tmp/sony_dw_test_host.ko\n'
        '/usr/bin/openssl dgst -sha256 /tmp/sony_dw_test_host.ko > /tmp/dw-host.sha\ncat /tmp/dw-host.sha\n'
        'if grep -q "'+digest+'$" /tmp/dw-host.sha; then\n'
        'insmod /tmp/sony_dw_test_host.ko\necho OWNED_DW_HOST_LOAD_RC=$?\n'
        'grep "^sony_dw_test_host " /proc/modules\n'
        'else echo OWNED_DW_HOST_IDENTITY_REJECTED; fi\ntrue')
    qmp('trace-event-set-state',{'name':'memory_region_ops_write','enable':True})
    try:observed=serial_command(proc,console,command,timeout=45)
    finally:qmp('trace-event-set-state',{'name':'memory_region_ops_write','enable':False})
    (run/'owned-dw-host.txt').write_bytes(observed);result.update(parse_host(observed))
    result['ok']=result['ok'] and result['dw_test_host_enum_markers_verified']
    if not result['ok']:return
    trace=(run/'output/boot-trace.log').read_text(errors='replace')
    verified,events=parse_controls(trace)
    (run/'dw-host-mmio-events.json').write_text(json.dumps(events,indent=2)+'\n')
    result['dw_test_host_control_sequence_verified']=verified
    if not verified:raise ValueError('Actual guest MMIO trace does not establish expected quirk control sequence')
    command=('if true; then\necho DW_SYSFS_IDENTITY_BEGIN\n'
        'cat /sys/bus/pci/devices/0000:01:00.0/vendor\n'
        'cat /sys/bus/pci/devices/0000:01:00.0/device\n'
        'cat /sys/bus/pci/devices/0000:01:00.0/class\n'
        'echo DW_SYSFS_IDENTITY_END\necho DW_SYSFS_RESOURCE_BEGIN\n'
        'cat /sys/bus/pci/devices/0000:01:00.0/resource\n'
        'echo DW_SYSFS_RESOURCE_END\necho DW_ACTUAL_IRQS_BEGIN\ncat /proc/interrupts\n'
        'echo DW_ACTUAL_IRQS_END\nfi\ntrue')
    observed=serial_command(proc,console,command,timeout=15)
    (run/'dw-host-sysfs.txt').write_bytes(observed);clean=observed.replace(b'\r',b'')
    ids=re.search(rb'^DW_SYSFS_IDENTITY_BEGIN\n(.*?)\nDW_SYSFS_IDENTITY_END$',clean,re.M|re.S)
    resources=re.search(rb'^DW_SYSFS_RESOURCE_BEGIN\n(.*?)\nDW_SYSFS_RESOURCE_END$',clean,re.M|re.S)
    if not ids or not resources:raise ValueError('No actual sysfs identity/resource envelope')
    # QEMU PCI_CLASS_OTHERS is numeric 00ff here, yielding class 00ff00.
    if ids[1].splitlines()!=[b'0x1b36',b'0x0005',b'0x00ff00']:raise ValueError('Actual sysfs identity differs')
    entries=resources[1].splitlines();start,end,flags=map(lambda x:int(x,16),entries[0].split())
    bar=int(result['dw_test_host_bar'],16)
    if start!=bar or end-start+1!=0x1000000 or not flags&0x200:
        raise ValueError('Actual kernel BAR resource differs from configured TEST RAM')
    result['dw_test_host_sysfs_verified']=True
    result['dw_test_host_resource_sha256']=hashlib.sha256(resources[1]).hexdigest()
    qmp('stop')
    try:
        assert not qmp('query-status')['running']
        assert word(qmp,ECAM+0x100000,run,'dw-qmp-endpoint-id')==0x00051b36
        assert word(qmp,ECAM+0x100008,run,'dw-qmp-endpoint-class')>>8==0x00ff00
        assert word(qmp,ECAM+0x100010,run,'dw-qmp-endpoint-bar')&0xfffffff0==bar
        assert word(qmp,0xf70008bc,run,'dw-qmp-dbi-control')==0
        assert word(qmp,0xf11e0380,run,'dw-qmp-wrapper-control')==0x40
        result['observed_pcidma_write_engine']=word(qmp,0xf738000c,run,'dw-qmp-pcidma-write-engine')
        result['observed_pcidma_read_engine']=word(qmp,0xf738002c,run,'dw-qmp-pcidma-read-engine')
        cap=word(qmp,ECAM+0x8034,run,'dw-qmp-root-cap')&255
        seen=set();root_cap=0
        while cap and len(seen)<48:
            assert cap not in seen;seen.add(cap)
            value=word(qmp,ECAM+0x8000+cap,run,'dw-qmp-root-cap-'+hex(cap))
            if value&255==0x10:
                root_cap=cap;assert (value>>20)&15==4;break
            cap=value>>8&255
        assert root_cap
        result['dw_test_host_qmp_config_and_type_verified']=True
    finally:qmp('cont')
    token='DW_HOST_CPU_RESUMED_'+run.name.replace('-','_')
    observed=serial_command(proc,console,'echo '+token,timeout=15)
    (run/'dw-host-cpu-resumed.txt').write_bytes(observed)
    assert ('\n'+token+'\n').encode() in observed.replace(b'\r',b'')
    result['dw_test_host_cpu_resumed']=True
