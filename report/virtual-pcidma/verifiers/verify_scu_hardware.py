#!/usr/bin/env python3
"""Independently replay actual qtest SCU writes/readbacks using native bit numbers."""
import argparse
import hashlib
import json
from pathlib import Path
from verify_hardware import transactions

HERE=Path(__file__).resolve().parent
HCLK=0xf1388080
RESET=0xf1388310
WRAPPERS=(0xf11e0380,0xf1160380,0xf11a0380,0xf1220380,0xf1120380)
HMASK=sum(1<<b for b in (1,7,13,19,25))
RMASK=sum(1<<b for b in (3,11,7,15,19))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);p.add_argument('run',type=Path)
    a=p.parse_args();proof=json.loads((a.candidate/'build-proof.json').read_text());r=json.loads((a.run/'result.json').read_text())
    digest=hashlib.sha256((a.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==r['binary_sha256'] and r['verified']
    for name,sha in proof['model_source_sha256'].items():
        assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    assert 'dev: a7c2-test-pcie-scu,' in (a.run/'enabled/qtree.txt').read_text()
    assert 'dev: a7c2-test-pcie-scu,' not in (a.run/'disabled/qtree.txt').read_text()
    raw=(a.run/'enabled/qemu.log').read_bytes();events=transactions(raw.decode())
    hclk=0;reset=RMASK;wrappers=[0]*5;valid=[0]*5;negative=0;readbacks=0;reset_seen=False
    for e in events:
        if e['op']=='writel':
            addr,value=e['address'],e['value']
            if addr in (HCLK+4,HCLK+8):
                if value&~HMASK:negative+=1;continue
                hclk=(hclk|value) if addr==HCLK+4 else (hclk&~value)
            elif addr in (RESET+4,RESET+8):
                if value&~RMASK:negative+=1;continue
                reset=(reset|value) if addr==RESET+4 else (reset&~value)
            elif addr in WRAPPERS:
                i=WRAPPERS.index(addr);hbit=(1,7,13,19,25)[i];rbit=(3,11,7,15,19)[i]
                if value&~0x10 or not hclk&(1<<hbit) or reset&(1<<rbit):negative+=1;continue
                wrappers[i]=value;valid[i]+=1
            elif addr in (HCLK,RESET):negative+=1
        elif e['op']=='readl':
            addr,value=e['address'],e['value']
            if addr==HCLK:assert value==hclk;readbacks+=1
            elif addr==RESET:
                if value==RMASK and reset==0 and all(w==0x10 for w in wrappers):
                    assert hclk==0;reset=RMASK;wrappers=[0]*5;reset_seen=True
                assert value==reset;readbacks+=1
            elif addr in WRAPPERS:
                i=WRAPPERS.index(addr)
                if hclk&(1<<(1,7,13,19,25)[i]) and not reset&(1<<(3,11,7,15,19)[i]):
                    assert value==wrappers[i];readbacks+=1
    assert all(v>=1 for v in valid) and negative>=16 and readbacks>=30 and reset_seen
    review={'status':'PASS_TEST_SCU_HARDWARE_ONLY','binary_sha256':digest,
        'controllers_with_real_gated_write_and_readback':5,'invalid_writes_no_mutation':negative,
        'actual_state_readbacks':readbacks,'qmp_reset_effect_observed':reset_seen,
        'trace_sha256':hashlib.sha256(raw).hexdigest(),'virtual_reset_policy_only':True,
        'native_udif_or_soc_host_or_capture_verified':False}
    (HERE.parent/'scu-hardware-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS actual SCU HCLK/reset state/readback, five gated wrapper writes, rejection and reset; NO native init/PHY claim')


if __name__=='__main__':main()
