#!/usr/bin/env python3
"""Independent replay of the expected-frontier run: lane gate passed, abort exactly at first DBI read."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from verify_enumeration import fdt_nodes
HERE=Path(__file__).resolve().parent
RAW_SHA='6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95'
PC_BASE=0xffffff8008080000

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);p.add_argument('run',type=Path);a=p.parse_args()
    r=json.loads((a.run/'result.json').read_text());proof=json.loads((a.candidate/'build-proof.json').read_text())
    digest=hashlib.sha256((a.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==r['candidate_binary_sha256']
    assert r['ok'] and r['vm_exited'] and not r['retained_no_force_kill'] and not r.get('cleanup_error')
    assert r['native_phy_frontier_verified'] and r['native_phy_ready_passed'] and r['native_sram_upload_verified']
    assert not any(r[key] for key in ('camera_app_started','sd_attached','dma_executed','capture_verified',
        'native_of_host_success','original_silicon_init_producer_verified','dbi_model_present'))
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    console=(a.run/'console.log').read_bytes().replace(b'\r',b'')
    assert b'PCI0: PHY ready in ' in console and b'Unhandled fault: synchronous external abort' in console
    assert b'PCI0: PHY SRAM timeout' not in console and b'PCI0: handover' not in console
    m=re.search(rb'pc : \[<([0-9a-f]+)>\]',console);assert m
    pc=int(m.group(1),16)-PC_BASE;assert pc==0x245c90 or 0x245ea0<=pc<0x245f20,hex(pc)
    assert pc==r['native_frontier_fault_pc_raw']
    fa=re.search(rb'Unhandled fault: synchronous external abort \(0x[0-9a-f]+\) at 0x([0-9a-f]+)',console);assert fa
    assert int(fa.group(1),16)&0xfff==0x8bc,'fault address is not DBI+0x8bc'
    nodes=fdt_nodes((a.run/'output/virt.dtb').read_bytes())
    assert nodes['/sony-test-pcie0']['status']==b'okay\0'
    props=json.loads((a.run/'native-frontier-properties.json').read_text())
    assert props=={'last-accepted-words':4096,'last-image-matches':1,'completed-clear-jobs':1,
        'ready-read-before-upload':1,'apply-after-upload':1,'dbi-accesses':1,'rejected-accesses':1,
        'lane-status':0,'link-status':0}
    raw=(a.run/'native-frontier-upload-raw.bin').read_bytes()
    assert len(raw)==8192 and hashlib.sha256(raw).hexdigest()==RAW_SHA
    trace=(a.run/'output/boot-trace.log').read_bytes()
    assert not re.search(rb"Invalid (?:read|write)[^\n]*region 'test-phy-init-region\d+'",trace)
    events=[(m.group(1),int(m.group(2),16),int(m.group(3),16),int(m.group(4)),int(m.group(5))) for m in re.finditer(
        rb"memory_region_ops_(read|write) .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name 'test-phy-init-region(\d+)'",trace)]
    data=[v for v in events if v[0]==b'write' and v[4]==7 and 0xf11d8000<=v[1]<0xf11dc000]
    assert data==[(b'write',0xf11d8000+4*i,w,4,7) for i,w in enumerate(struct.unpack('<4096H',raw))]
    assert (b'write',0xf11e00ac,6,4,7) in events[events.index(data[-1])+1:]
    assert not [v for v in events if v[4]==9],'unexpected DBI-region write before the aborting read'
    for label in ('write','read'):
        text=(a.run/('native-frontier-engine-'+label+'.txt')).read_text()
        words=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[-1]);assert len(words)==1 and int(words[0],16)==0
    review={'status':'PASS_FRONTIER_EVIDENCE_ONLY','binary_sha256':digest,
        'original_cpu_dword_writes':4096,'raw_sha256':RAW_SHA,'lane_gate_passed_under_test_policy':True,
        'fault_pc_raw':'0x%x'%pc,'abort_at_first_unmodeled_dbi_read':True,'link_status_remained':0,
        'dma_engines_zero':True,'trace_sha256':hashlib.sha256(trace).hexdigest(),
        'host_bound_or_link_or_dma_or_silicon_calibration_verified':False}
    (HERE.parent/'native-phy-frontier-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS frontier evidence: PHY-ready passed under TEST policy, abort exactly at first DBI read; NO host/link/DMA/silicon claim')

if __name__=='__main__':main()
