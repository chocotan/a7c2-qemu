#!/usr/bin/env python3
"""Replay saved QEMU CCF bank transactions independently of the C implementation."""
import argparse
import hashlib
import json
from pathlib import Path
from verify_hardware import transactions

HERE=Path(__file__).resolve().parent
B=0xf1388000
WRAPPERS=(0xf11e0380,0xf1160380,0xf11a0380,0xf1220380,0xf1120380)
MASKS={16*i:v for i,v in enumerate((0x1f000,0,0x30f,0x2c000c,0x13fffc0,0xdf7c0,0,0,0x3efbefbe))}
MASKS.update({0x210:0x1f000000,0x220:0x11111,0x230:0x3ff})
MASKS.update({0x300+16*i:0xffffffff for i in range(8)})
DIRECT={0x10c+4*i for i in range(5)}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);p.add_argument('run',type=Path)
    a=p.parse_args();r=json.loads((a.run/'result.json').read_text());proof=json.loads((a.candidate/'build-proof.json').read_text())
    digest=hashlib.sha256((a.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==r['binary_sha256'] and r['verified'] and r['ccf_banks_verified']
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    assert 'dev: a7c2-test-scu-ccf,' in (a.run/'enabled/qtree.txt').read_text()
    assert 'dev: a7c2-test-scu-ccf,' not in (a.run/'disabled/qtree.txt').read_text()
    raw=(a.run/'enabled/qemu.log').read_bytes();events=transactions(raw.decode())
    state={offset:0 for offset in set(MASKS)|DIRECT};state[0x310]=0x88888
    wrappers=[0]*5;reads=bad=0;seen=set();reset_seen=False;wrapper_writes=[0]*5
    for event in events:
        if event['op'] not in ('writel','readl'):continue
        address,value=event['address'],event['value'];offset=address-B
        if address in WRAPPERS:
            i=WRAPPERS.index(address);active=bool(state[0x80]&(1<<(1,7,13,19,25)[i])) and not state[0x310]&(1<<(3,11,7,15,19)[i])
            if event['op']=='writel':
                if active and not value&~16:wrappers[i]=value;wrapper_writes[i]+=1
                else:bad+=1
            elif active:assert value==wrappers[i];reads+=1
            continue
        if event['op']=='writel':
            if offset in DIRECT:
                if value&~0xff:bad+=1
                else:state[offset]=value
            elif offset in MASKS:bad+=1
            else:
                status=offset&~15;port=offset&15
                if status in MASKS and port in (4,8):
                    if value&~MASKS[status]:bad+=1
                    elif port==4:state[status]|=value
                    else:state[status]&=~value
        elif offset in state:
            if offset==0x310 and value==0x88888 and state[offset]==0 and all(v==16 for v in wrappers):
                state={key:0 for key in state};state[0x310]=0x88888;wrappers=[0]*5;reset_seen=True
            assert value==state[offset],(hex(address),hex(value),hex(state[offset]))
            reads+=1;seen.add(offset)
    assert all(n>=1 for n in wrapper_writes) and reset_seen and bad>=25
    assert set(MASKS)|DIRECT<=seen
    review={'status':'PASS_TEST_CCF_REGISTERS_ONLY','binary_sha256':digest,
        'status_banks':len(MASKS),'direct_dividers':len(DIRECT),'actual_readbacks':reads,
        'rejected_writes_no_mutation':bad,'five_gated_wrappers':True,'reset_effect_observed':True,
        'trace_sha256':hashlib.sha256(raw).hexdigest(),'native_provider_or_soc_host_or_capture_verified':False}
    (HERE.parent/'ccf-hardware-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS actual CCF bank/divider/mux/reset/gated-wrapper readbacks; NO native provider/host/PHY claim')


if __name__=='__main__':main()
