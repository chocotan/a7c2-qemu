#!/usr/bin/env python3
"""Original CPU upload under explicit TEST clear policy, followed by required probe failure."""
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
    assert r['native_sram_upload_verified'] and r['native_of_probe_expected_lane_failure'] and r['test_sram_clear_policy_used']
    assert r['native_invalid_mem_logging_enabled']
    assert not any(r[key] for key in ('camera_app_started','sd_attached','dma_executed','capture_verified','native_of_host_success','original_silicon_init_producer_verified'))
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    console=(a.run/'console.log').read_bytes().replace(b'\r',b'')
    assert not re.search(rb'WARNING: CPU:|Kernel panic|BUG:|Oops:|Unable to handle kernel|Internal error:',console)
    assert not any(s in console for s in (b'PCI0: handover',b'PCI0: PHY SRAM timeout',b'PCI0: PHY ready'))
    assert re.search(rb'probe of [^\n]*sony-test-pcie0 failed with error -1',console)
    nodes=fdt_nodes((a.run/'output/virt.dtb').read_bytes());node=nodes['/sony-test-pcie0']
    assert node['compatible']==b'snps,dw-pcie\0' and node['status']==b'okay\0'
    assert node['firm-id']==struct.pack('>I',1) and node['num-lanes']==struct.pack('>I',4)
    handles=[struct.unpack('>I',nodes['/sony-test-scu/'+name]['phandle'])[0] for name in ('clock-controller@0','rst@300')]
    for field,handle,ids in (('clocks',handles[0],(62,63,64,65,66,29,30)),('resets',handles[1],(32,33,34,35,118,119))):
        assert struct.unpack('>'+str(2*len(ids))+'I',node[field])==tuple(v for i in ids for v in (handle,i))
    raw=(a.run/'native-phy-upload-raw.bin').read_bytes();assert len(raw)==8192 and hashlib.sha256(raw).hexdigest()==RAW_SHA
    props=json.loads((a.run/'native-phy-properties.json').read_text())
    assert props['last-accepted-words']==4096 and props['last-image-matches']==1 and props['last-input-sha256']==RAW_SHA
    assert props['ready-read-before-upload']==1 and props['apply-after-upload']==1
    assert props['completed-clear-jobs']==1 and props['last-cleared-words']==4096 and props['rejected-accesses']==props['dbi-accesses']==0
    trace=(a.run/'output/boot-trace.log').read_bytes();events=[]
    assert not re.search(rb"Invalid (?:read|write)[^\n]*region 'test-phy-init-region\d+'",trace)
    views=[v for v in (a.run/'native-phy-mtree.txt').read_text().split('FlatView #') if 'AS "cpu-memory-0", root: system' in v]
    assert len(views)==1
    mappings=[(int(low,16),int(high,16),kind,name) for low,high,kind,name in re.findall(
        r'^\s*([0-9a-fA-F]{16})-([0-9a-fA-F]{16}) \(prio -?\d+, ([^)]*)\): (\S+)',views[0],re.M)]
    for address,index in ((0xf1388000,0),(0xf138837c,1),(0xf11d8000,7),(0xf11dbffc,7),(0xf11e00ac,7),
                          (0xf11e0380,2),(0xf11e038c,8),(0xf11ffffc,8),(0xf7000000,9),(0x602000000,10)):
        assert [(kind,name) for lo,hi,kind,name in mappings if lo<=address<=hi]==[('i/o','test-phy-init-region'+str(index))]
    for m in re.finditer(rb"memory_region_ops_(read|write) .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name 'test-phy-init-region7'",trace):
        op,address,value,size=m.groups();events.append((op,int(address,16),int(value,16),int(size)))
    data=[v for v in events if v[0]==b'write' and 0xf11d8000<=v[1]<0xf11dc000]
    assert data==[(b'write',0xf11d8000+4*i,w,4) for i,w in enumerate(struct.unpack('<4096H',raw))]
    # Read-side proof uses model counters (read tracing was dropped after the 10.5GB pl011 log).
    assert (b'write',0xf11e00ac,6,4) in events[events.index(data[-1])+1:]
    irqs=(a.run/'native-phy-irqs.txt').read_bytes().replace(b'\r',b'')
    for irq in (198,200,202,204,206):assert re.search(rb'^\s*'+str(irq).encode()+rb':\s+\d+\s+GIC-0\s+'+str(irq).encode()+rb'\s+(?:Level|Edge)\s+PCIeDMAC\s*$',irqs,re.M)
    platform=(a.run/'native-phy-platform.txt').read_bytes().replace(b'\r',b'')
    assert b'Csnps,dw-pcie' in platform and b'NATIVE_PHY_BOUND=0\n' in platform and b'NATIVE_PHY_BOUND=1\n' not in platform
    for label in ('write','read'):
        text=(a.run/('native-phy-engine-'+label+'.txt')).read_text();values=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[-1]);assert len(values)==1 and int(values[0],16)==0
    token='NATIVE_PHY_UPLOAD_CPU_RESUMED_'+a.run.name.replace('-','_')
    assert ('\n'+token+'\n').encode() in (a.run/'native-phy-cpu-resumed.txt').read_bytes().replace(b'\r',b'')
    review={'status':'PASS_ORIGINAL_UPLOAD_UNDER_TEST_CLEAR_POLICY_EXPECTED_PROBE_FAILURE',
        'binary_sha256':digest,'actual_original_cpu_dword_writes':4096,'raw_readback_bytes':8192,'raw_sha256':RAW_SHA,
        'test_policy_not_original_silicon_producer':True,'expected_lane_failure_and_unbound_driver':True,
        'dma_engines_zero':True,'trace_sha256':hashlib.sha256(trace).hexdigest(),
        'cpu_flatview_explicit_regions_and_no_validation_layer_rejections':True,
        'original_phy_calibration_or_host_or_link_or_dma_or_frame_verified':False}
    (HERE.parent/'native-phy-upload-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS original CPU SRAM upload ONLY under explicit TEST clear policy; expected probe failure; NO original PHY/host/link/DMA')

if __name__=='__main__':main()
