#!/usr/bin/env python3
"""Independent replay: original SoC host probe bound + TEST peer enumerated via real DBI/viewport."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from verify_enumeration import fdt_nodes
HERE=Path(__file__).resolve().parent
RAW_SHA='6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);p.add_argument('run',type=Path);a=p.parse_args()
    r=json.loads((a.run/'result.json').read_text());proof=json.loads((a.candidate/'build-proof.json').read_text())
    digest=hashlib.sha256((a.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==r['candidate_binary_sha256']
    assert r['ok'] and r['vm_exited'] and not r['retained_no_force_kill'] and not r.get('cleanup_error')
    assert r['native_soc0_host_verified'] and r['native_soc0_host_bound'] and r['native_test_peer_enumerated']
    assert not any(r[key] for key in ('camera_app_started','sd_attached','dma_executed','capture_verified',
        'original_silicon_init_producer_verified'))
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    console=(a.run/'console.log').read_bytes().replace(b'\r',b'')
    assert not re.search(rb'WARNING: CPU:|Kernel panic|BUG:|Oops:|Unable to handle kernel|Internal error:',console)
    assert b'PCI0: PHY ready in ' in console and not re.search(rb'probe of [^\n]*sony-test-pcie0 failed',console)
    sysfs=(a.run/'native-soc0-sysfs.txt').read_bytes().replace(b'\r',b'')
    assert b'\nSOC0_HOST_BOUND=1\n' in sysfs
    assert re.search(rb'PCI_DEV_0000:00:00.0\n0x104d\n0x911d\n0x060400\n',sysfs)
    assert re.search(rb'PCI_DEV_0000:01:00.0\n0x1b36\n0x0005\n0x00ff00\n',sysfs)
    irqs=(a.run/'native-soc0-irqs.txt').read_bytes().replace(b'\r',b'')
    for i,irq in enumerate((198,200,202,204,206)):
        m=re.search(rb'^\s*'+str(irq).encode()+rb':\s+\d+\s+GIC-0\s+'+str(irq).encode()+
            rb'\s+(?:Level|Edge)\s+([^\n]*)$',irqs,re.M)
        assert m and b'PCIeDMAC' in m.group(1)
        if i==0:assert b'dw-plat-pcie-msi' in m.group(1),'host MSI handler must share IRQ198'
    props=json.loads((a.run/'native-soc0-properties.json').read_text())
    assert props['rejected-accesses']==0 and props['dbi-accesses']>0
    assert props['lane-status']==0 and props['link-status']==2 and props['completed-clear-jobs']==1
    assert props['last-accepted-words']==4096 and props['last-image-matches']==1
    assert props['ready-read-before-upload']==1 and props['apply-after-upload']==1
    raw=(a.run/'native-soc0-upload-raw.bin').read_bytes()
    assert len(raw)==8192 and hashlib.sha256(raw).hexdigest()==RAW_SHA
    assert r['native_soc0_engines']==[1,1]  # notify callback 2a2538 pins: enabled-but-idle
    trace=(a.run/'output/boot-trace.log').read_bytes()
    assert not re.search(rb"Invalid (?:read|write)[^\n]*region 'test-phy-init-region\d+'",trace)
    # Original VID/DID writes are 16-bit (pinned 249df4/249e18: x3=2).
    assert re.search(rb"memory_region_ops_write .*?addr 0xf7000000 value 0x104d size 2 ",trace)
    assert re.search(rb"memory_region_ops_write .*?addr 0xf7000002 value 0x911d size 2 ",trace)
    assert re.search(rb"memory_region_ops_write .*?addr 0xf11e01ac value 0x44 size 4 ",trace)  # RC mode + LTSSM
    events=[(int(m.group(1),16),int(m.group(2),16),int(m.group(3))) for m in re.finditer(
        rb"memory_region_ops_write .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name 'test-phy-init-region7'",trace)]
    data=[v for v in events if 0xf11d8000<=v[0]<0xf11dc000]
    assert data==[(0xf11d8000+4*i,w,4) for i,w in enumerate(struct.unpack('<4096H',raw))]
    nodes=fdt_nodes((a.run/'output/virt.dtb').read_bytes())
    assert nodes['/sony-test-pcie0']['status']==b'okay\0'
    for label in ('write','read'):
        text=(a.run/('native-soc0-engine-'+label+'.txt')).read_text()
        words=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[-1]);assert len(words)==1 and int(words[0],16)==1
    token='NATIVE_SOC0_HOST_CPU_RESUMED_'+a.run.name.replace('-','_')
    assert ('\n'+token+'\n').encode() in (a.run/'native-soc0-cpu-resumed.txt').read_bytes().replace(b'\r',b'')
    review={'status':'PASS_SOC0_HOST_BOUND_AND_PEER_ENUMERATED','binary_sha256':digest,
        'original_cpu_dword_writes':4096,'raw_sha256':RAW_SHA,
        'root_port_ids':'104d:911d','peer_ids':'1b36:0005','engines_enabled_idle':[1,1],
        'irq198_shared_with_host_msi':True,
        'lane_link_under_explicit_test_policy':True,'trace_sha256':hashlib.sha256(trace).hexdigest(),
        'bar_assignment_or_dma_or_silicon_calibration_verified':False}
    (HERE.parent/'native-soc0-host-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS original SoC host bound + real TEST peer enumerated via DBI/viewport; engines enabled-idle; NO DMA/data/silicon claim')

if __name__=='__main__':main()
