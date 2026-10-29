#!/usr/bin/env python3
"""Replay actual expanded PHY table writes/readback, refusing READY/native host claims."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

HERE=Path(__file__).resolve().parent
RAW_SHA='6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95'
STREAM_SHA='963669fdc92d57141fa41095ecd7c5a1b972162d2e699a702ebfc8b6c1ef64dc'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);p.add_argument('run',type=Path);a=p.parse_args()
    proof=json.loads((a.candidate/'build-proof.json').read_text());r=json.loads((a.run/'result.json').read_text())
    digest=hashlib.sha256((a.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==r['binary_sha256'] and r['verified'] and not r['init_done_advertised'] and not r['native_firmware_or_host_executed']
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    assert 'dev: a7c2-test-phy-sram,' not in (a.run/'disabled/qtree.txt').read_text()
    assert 'dev: a7c2-test-phy-sram,' in (a.run/'enabled/qtree.txt').read_text()
    data=(a.run/'enabled/positive-readback.bin').read_bytes();assert len(data)==16384 and hashlib.sha256(data).hexdigest()==STREAM_SHA
    words=struct.unpack('<4096I',data);assert all(w<=0xffff for w in words)
    raw=struct.pack('<4096H',*words);assert hashlib.sha256(raw).hexdigest()==RAW_SHA and raw[-1800:]==bytes(1800)
    log=(a.run/'enabled/qemu.log').read_bytes()
    writes=[tuple(int(x,16) if i<2 else int(x) for i,x in enumerate(m.groups())) for m in re.finditer(
        rb"memory_region_ops_write .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name 'test-phy-sram-data'",log)]
    expected=[(0xf11d8000+4*i,w,4) for i,w in enumerate(words)]
    assert any(writes[i:i+4096]==expected for i,v in enumerate(writes) if v==expected[0])
    get=lambda name:json.loads((a.run/('enabled/'+name+'-properties.json')).read_text())
    positive=get('positive');assert positive=={'accepted-words':4096,'image-matches':1,'apply-seen':1,'input-sha256':RAW_SHA,'control':2}
    for name in ('empty-apply','late-write','altered','missing-zero'):
        negative=get(name);assert negative['image-matches']==0 and not negative['control']&4
    assert get('empty-apply')['accepted-words']==0 and get('missing-zero')['accepted-words']==4095
    assert get('altered')['accepted-words']==4096 and get('altered')['input-sha256']!=RAW_SHA
    review={'status':'PASS_TEST_PHY_SRAM_DATA_ONLY','binary_sha256':digest,
        'actual_ordered_dword_writes':4096,'actual_readback_bytes':len(data),'raw_sha256':RAW_SHA,'stream_sha256':STREAM_SHA,
        'empty_apply_and_missing_zero_and_changed_payload_and_late_write_rejected':True,
        'trace_sha256':hashlib.sha256(log).hexdigest(),'phy_init_done_or_lane_or_link_or_native_host_verified':False}
    (HERE.parent/'phy-sram-hardware-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS actual4096table writes/readback/hash and negativecontrols; NO INIT_DONE/lane/link/native host')


if __name__=='__main__':main()
