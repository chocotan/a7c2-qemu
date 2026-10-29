#!/usr/bin/env python3
"""Independent TEST clear-job data/trace review. Never upgrades it to silicon/PHY/link proof."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
HERE=Path(__file__).resolve().parent
RAW_SHA='6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);p.add_argument('run',type=Path);a=p.parse_args()
    proof=json.loads((a.candidate/'build-proof.json').read_text());r=json.loads((a.run/'result.json').read_text())
    digest=hashlib.sha256((a.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==r['binary_sha256'] and r['verified']
    assert not any(r[key] for key in ('original_silicon_producer_known','native_probe_executed','lane_calibrated','link_up'))
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    assert 'dev: a7c2-test-scu-phy-init,' in (a.run/'enabled/qtree.txt').read_text()
    assert 'dev: a7c2-test-scu-phy-init,' not in (a.run/'disabled/qtree.txt').read_text()
    root=a.run/'enabled';partial=(root/'partial-clear.bin').read_bytes()
    assert len(partial)==16384 and partial[:256]==bytes(256) and partial[256:]==b'\xff\xff\0\0'*(4096-64)
    assert (root/'full-clear.bin').read_bytes()==bytes(16384)
    raw=(root/'uploaded-raw-readback.bin').read_bytes();assert len(raw)==8192 and hashlib.sha256(raw).hexdigest()==RAW_SHA
    props=json.loads((root/'positive-properties.json').read_text())
    assert props=={'completed-clear-jobs':1,'last-cleared-words':4096,'last-accepted-words':4096,'last-image-matches':1,'last-input-sha256':RAW_SHA,'ready-read-before-upload':1,'apply-after-upload':1}
    assert json.loads((root/'not-ready.json').read_text())=={'lane_status':15,'link_status':0}
    assert json.loads((root/'calibrated.json').read_text())=={'lane_status':0,'link_status':2,'core_control':0x44}
    assert json.loads((root/'dbi.json').read_text())=={'root_ids':'0x911d104d','peer_ids':'0x00051b36','absent_read':'0xffffffff','aer_status_after_clear':0}
    assert r['test_functional_lane_link_verified'] and r['dbi_model_verified']
    assert json.loads((root/'clock-loss.json').read_text())=={'control':0,'completed_jobs':0}
    assert json.loads((root/'bypass.json').read_text())=={'control':1,'completed_jobs':0}
    for label in ('bypass','apb-reset'):
        assert json.loads((root/('midway-'+label+'.json')).read_text())=={'control':0,'completed_jobs':0}
    assert json.loads((root/'reset-pending.json').read_text())=={'completed_jobs':0,'last_cleared':0}
    assert json.loads((root/'early-apply.json').read_text())=={'completed_jobs':1,'last_match':0,'last_count':0,'last_sha':''}
    log=(root/'qemu.log').read_bytes();writes=[]
    for m in re.finditer(rb"memory_region_ops_write .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name 'test-phy-init-region7'",log):
        address,value,size=(int(v,16) if i<2 else int(v) for i,v in enumerate(m.groups()))
        if 0xf11d8000<=address<0xf11dc000:writes.append((address,value,size))
    expected=[(0xf11d8000+4*i,w,4) for i,w in enumerate(struct.unpack('<4096H',raw))]
    assert any(writes[i:i+4096]==expected for i,v in enumerate(writes) if v==expected[0])
    review={'status':'PASS_EXPLICIT_TEST_CLEAR_POLICY_ONLY','test_clear_policy_verified':True,'binary_sha256':digest,
        'actual_partial_and_full_storage_clear_verified':True,'actual_original_table_writes':4096,
        'mid_job_bypass_apb_reset_device_reset_and_early_apply_negatives':True,
        'raw_sha256':RAW_SHA,
        'test_functional_lane_status_after_calib':0,'test_functional_link_status_after_ltssm':2,
        'trace_sha256':hashlib.sha256(log).hexdigest(),'silicon_calibration_or_training_or_native_probe_or_host_verified':False}
    (HERE.parent/'phy-init-hardware-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS explicit TEST real SRAM clear job/storage/4096 writes/gated negatives; NOT silicon producer/native host')

if __name__=='__main__':main()
