#!/usr/bin/env python3
"""Original SoC controller0 host binds and enumerates the real TEST peer; no DMA submitted."""
import hashlib
import json
import re
import time
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('soc0_host_helpers',Path(__file__).with_name('observe_native_init.py'))
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
IRQS=helpers.IRQS
RAW_SHA='6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95'

def installed_irqs_host(raw):
    """Host-aware: IRQ198 is shared with dw-plat-pcie-msi/PME/AER once the host binds."""
    clean=raw.replace(b'\r',b'')
    found=[]
    for irq in IRQS:
        m=re.search(rb'^\s*'+str(irq).encode()+rb':\s+\d+\s+GIC-0\s+'+str(irq).encode()+
            rb'\s+(?:Level|Edge)\s+([^\n]*)$',clean,re.M)
        assert m and b'PCIeDMAC' in m.group(1),'missing PCIeDMAC IRQ row '+str(irq)
        found.append(m.group(1).decode())
    return found

def observe(qmp,serial_command,run,proc,console,result):
    raw=console.read_bytes().replace(b'\r',b'')
    if re.search(rb'WARNING: CPU:|Kernel panic|BUG:|Oops:|Unable to handle kernel|Internal error:',raw):
        raise ValueError('kernel fault during SoC host probe; preserve evidence')
    assert b'PCI0: PHY ready in ' in raw
    assert b'PCI0: PHY SRAM timeout' not in raw and b'PCI0: handover' not in raw
    assert not re.search(rb'probe of [^\n]*sony-test-pcie0 failed',raw)
    trace=(run/'output/boot-trace.log').read_text(errors='replace')
    if re.search(r"Invalid (?:read|write)[^\n]*region 'test-phy-init-region\d+'",trace):
        raise ValueError('validity-layer rejection inside PHY/DBI regions')
    observed=serial_command(proc,console,'cat /proc/interrupts\ntrue',timeout=15)
    (run/'native-soc0-irqs.txt').write_bytes(observed)
    names=installed_irqs_host(observed)
    assert 'dw-plat-pcie-msi' in names[0],'host MSI handler absent from shared IRQ198: '+names[0]
    result['native_soc0_irq_names']=names
    observed=serial_command(proc,console,
        'for p in /sys/bus/platform/devices/*sony-test-pcie0; do\n'
        'if test -d "$p"; then\n'
        'if test -e "$p/driver"; then echo SOC0_HOST_BOUND=1; else echo SOC0_HOST_BOUND=0; fi\nfi\ndone\n'
        'for d in /sys/bus/pci/devices/*; do\n'
        'echo PCI_DEV_${d##*/}\ncat "$d/vendor" "$d/device" "$d/class"\ndone\ntrue',timeout=20)
    (run/'native-soc0-sysfs.txt').write_bytes(observed)
    clean=observed.replace(b'\r',b'')
    assert b'\nSOC0_HOST_BOUND=1\n' in clean,'host driver not bound'
    assert b'\nPCI_DEV_0000:00:00.0\n' in clean and b'\nPCI_DEV_0000:01:00.0\n' in clean
    m=re.search(rb'PCI_DEV_0000:00:00.0\n(0x104d)\n(0x911d)\n(0x060400)\n',clean)
    assert m,'root port not enumerated with Sony VID/DID/class'
    m=re.search(rb'PCI_DEV_0000:01:00.0\n(0x1b36)\n(0x0005)\n(0x00ff00)\n',clean)
    assert m,'TEST peer not enumerated via original viewport/CFG0 path'
    qmp('stop')
    try:
        deadline=time.monotonic()+10
        while qmp('query-status')['running']:
            assert time.monotonic()<deadline,'owned VM did not pause'
            time.sleep(.05)
        props={key:qmp('qom-get',{'path':'/machine/sony-pcie-scu-test','property':key}) for key in
            ('last-accepted-words','last-image-matches','completed-clear-jobs','ready-read-before-upload',
             'apply-after-upload','dbi-accesses','rejected-accesses','lane-status','link-status')}
        (run/'native-soc0-properties.json').write_text(json.dumps(props,indent=2)+'\n')
        assert props['completed-clear-jobs']==1 and props['last-accepted-words']==4096 and props['last-image-matches']==1
        assert props['ready-read-before-upload']==1 and props['apply-after-upload']==1
        assert props['lane-status']==0 and props['link-status']==2,'lane calibrated + link up expected after LTSSM'
        assert props['rejected-accesses']==0,'unmodeled register access occurred: '+str(props)
        assert props['dbi-accesses']>0
        # Original notify callback (2a2538 pins): engines ENABLED-but-idle, +c=1/+2c=1.
        engines=[]
        for offset,label in ((0xc,'write'),(0x2c,'read')):
            text=qmp('human-monitor-command',{'command-line':'xp /1wx 0x%x'%(0xf7380000+offset)})
            (run/('native-soc0-engine-'+label+'.txt')).write_text(text)
            words=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[-1]);assert len(words)==1;engines.append(int(words[0],16))
        assert engines==[1,1],'notify callback engine state mismatch: '+str(engines)
        text=qmp('human-monitor-command',{'command-line':'xp /8192bx 0x602000000'})
        (run/'native-soc0-upload-hmp.txt').write_text(text)
        data=bytearray()
        for line in text.splitlines():
            if ':' in line:data.extend(int(v,16) for v in re.findall(r'0x([0-9a-fA-F]{2})\b',line.split(':',1)[1]))
        assert len(data)==8192 and hashlib.sha256(data).hexdigest()==RAW_SHA
        (run/'native-soc0-upload-raw.bin').write_bytes(data)
    finally:qmp('cont')
    token='NATIVE_SOC0_HOST_CPU_RESUMED_'+run.name.replace('-','_')
    resumed=serial_command(proc,console,'echo '+token,timeout=15)
    (run/'native-soc0-cpu-resumed.txt').write_bytes(resumed)
    assert ('\n'+token+'\n').encode() in resumed.replace(b'\r',b'')
    result.update(native_soc0_host_verified=True,native_soc0_host_bound=True,native_test_peer_enumerated=True,
        native_sram_upload_verified=True,native_phy_sram_raw_sha256=RAW_SHA,native_soc0_engines=engines,
        native_soc0_cpu_resumed=True,test_sram_clear_policy_used=True,
        original_silicon_init_producer_verified=False,dma_executed=False,native_of_host_success=True)
    result['ok']=True
