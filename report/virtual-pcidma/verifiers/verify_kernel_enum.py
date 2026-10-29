#!/usr/bin/env python3
"""Independent saved-byte review: actual original-kernel TEST PCI enumeration only."""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);p.add_argument('run',type=Path)
    a=p.parse_args();r=json.loads((a.run/'result.json').read_text())
    proof=json.loads((a.candidate/'build-proof.json').read_text())
    digest=hashlib.sha256((a.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==r['candidate_binary_sha256']
    for name,sha in proof['model_source_sha256'].items():
        assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    assert r['ok'] and r['vm_exited'] and not r.get('cleanup_error') and not r['retained_no_force_kill']
    assert not any(r[key] for key in ('camera_app_started','sd_attached','udif_driver_start_requested','dma_executed','capture_verified'))
    loaded=(a.run/'owned-dw-host.txt').read_text().replace('\r','')
    sha='2d62cd0c51361b0a91e47e71ffae1e45b098e459cb3eb3dc94d87e8edb36e2d3'
    assert 'SHA2-256(/tmp/sony_dw_test_host.ko)= '+sha in loaded
    assert '\nOWNED_DW_HOST_LOAD_RC=0\n' in loaded
    assert re.search(r'^sony_dw_test_host\s+\d+\s+\d+\s+.*\bLive\b',loaded,re.M)
    assert 'PCI_CORE_TEST_BUS: domain=0 bus=0' in loaded
    assert 'PCI_CORE_TEST_ENDPOINT: id=00051b36 bar0=10000000 reads=322 writes=72' in loaded
    sysfs=(a.run/'dw-host-sysfs.txt').read_text().replace('\r','')
    def envelope(name):
        match=re.search('^'+name+'_BEGIN\n(.*?)\n'+name+'_END$',sysfs,re.M|re.S)
        assert match,name
        return match[1]
    assert envelope('DW_SYSFS_IDENTITY').splitlines()==['0x1b36','0x0005','0x00ff00']
    resource=envelope('DW_SYSFS_RESOURCE')
    start,end,flags=(int(x,16) for x in resource.splitlines()[0].split())
    assert (start,end,flags)==(0x10000000,0x10ffffff,0x40200)
    irqs=envelope('DW_ACTUAL_IRQS');assert not re.search(r'^\s*198:',irqs,re.M) and 'PCIeDMAC' not in irqs
    def word(name):
        raw=(a.run/name).read_text();values=re.findall(r'0x([0-9a-fA-F]+)',raw.split(':',1)[1]);assert len(values)==1
        return int(values[0],16)
    assert word('dw-qmp-endpoint-id.txt')==0x00051b36
    assert word('dw-qmp-endpoint-class.txt')>>8==0x00ff00
    assert word('dw-qmp-endpoint-bar.txt')==start
    assert word('dw-qmp-dbi-control.txt')==0 and word('dw-qmp-wrapper-control.txt')==0x40
    assert word('dw-qmp-pcidma-write-engine.txt')==word('dw-qmp-pcidma-read-engine.txt')==0
    root=word('dw-qmp-root-cap-0x54.txt');assert root&255==0x10 and (root>>20)&15==4
    raw=(a.run/'output/boot-trace.log').read_bytes();events=[]
    for m in re.finditer(rb"memory_region_ops_write .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name '(test-root-(?:dbi|wrapper))'",raw):
        addr,value,size,name=m.groups();events.append((int(addr,16),int(value,16),int(size),name.decode()))
    assert [e[0] for e in events[:6]]==[0xf11e0380,0xf70008bc,0xf7000056,0xf7000068,0xf70008bc,0xf11e0380]
    assert [events[i][1] for i in (0,1,4,5)]==[0,1,0,0x40]
    assert events[2][1]==root>>16 and events[2][2]==2 and events[3][2]==4
    token='DW_HOST_CPU_RESUMED_'+a.run.name.replace('-','_')
    assert '\n'+token+'\n' in (a.run/'dw-host-cpu-resumed.txt').read_text().replace('\r','')
    console=(a.run/'console.log').read_text(errors='replace')
    assert 'blacklisting initcall __boottime___udif_init_pcidma' in console
    assert 'blacklisting initcall __boottime___udif_init_udif_pcie' in console
    review={'status':'PASS_ORIGINAL_KERNEL_TEST_PCI_ENUM_ONLY','binary_sha256':digest,
        'module_sha256':sha,'bdf':'0000:01:00.0','vendor_device':'1b36:0005','bar0':[hex(start),hex(end)],
        'actual_sysfs_and_independent_qmp_agree':True,'guest_native_quirk_control_sequence':True,
        'rootport_type':4,'root_mmio_writes':len(events),'trace_sha256':hashlib.sha256(raw).hexdigest(),
        'write_and_read_engines':0,'irq198_installed':False,'native_initcalls_blacklisted':True,
        'cpu_resumed_and_owned_vm_exited':True,'original_pcidma_api_or_soc_phy_verified':False,'capture_verified':False}
    (HERE.parent/'kernel-enum-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS actual kernel TEST PCI device/resources/sysfs/QMP/control sequence; engine0 and missing IRQ198 are NEGATIVE evidence')


if __name__=='__main__':main()
