#!/usr/bin/env python3
"""Check actual PCI config/BAR/bridge-gated DMA trace; not a kernel/PHY proof."""
import argparse
import hashlib
import json
from pathlib import Path
from verify_hardware import transactions

HERE=Path(__file__).resolve().parent
PORT=0x3f008000
ENDPOINT=0x3f100000
BAR=0x10000000
B=0xf7380000
PEER=0x600000000
AP_SOURCE=0x410010000
AP_DEST=0x410020000
GIC_PENDING=0x08000218


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate',type=Path);parser.add_argument('run',type=Path)
    args=parser.parse_args();proof=json.loads((args.candidate/'build-proof.json').read_text())
    result=json.loads((args.run/'result.json').read_text())
    binary=args.candidate/'build/qemu-system-aarch64'
    digest=hashlib.sha256(binary.read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==result['binary_sha256'] and result['hardware_verified']
    for name,expected in proof['model_source_sha256'].items():
        assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==expected
    assert 'dev: a7c2-test-pcie-peer,' in (args.run/'enabled/qtree.txt').read_text()
    assert 'dev: a7c2-test-pcie-peer,' not in (args.run/'disabled/qtree.txt').read_text()
    trace=(args.run/'enabled/qemu.log').read_text();events=transactions(trace)
    reads=lambda address:[e['value'] for e in events if e['op']=='readl' and e['address']==address]
    assert reads(ENDPOINT)==[0x00051b36]
    assert reads(ENDPOINT+0x34)[0]&255==0x70
    assert reads(ENDPOINT+0x70)[0]&255==0x10
    assert reads(ENDPOINT+0x10)==[0xff000000]
    regs={};writes={};rings=[]
    for index,e in enumerate(events):
        if e['op']=='write':writes[e['address']]=e['bytes']
        if e['op']=='writel':
            regs[e['address']]=e['value']
            if e['address'] in (B+0x10,B+0x30):rings.append((index,e,regs.copy(),writes.copy()))
    assert len(rings)==5
    original=rings[0][3][AP_SOURCE]
    other=rings[2][3][BAR+16]
    assert len(original)==len(other)==256 and original!=other
    peer1=b'\xa5'*16+original+b'\xa5'*(4096-272)
    peer2=b'\xa5'*16+other+b'\xa5'*(4096-272)
    for ordinal,(index,ring,state,_) in enumerate(rings):
        end=rings[ordinal+1][0] if ordinal+1<len(rings) else len(events)
        following=events[index+1:end]
        assert ring['value']==0 and (ring['address']==B+0x30)==(ordinal==2)
        assert state[PORT+0x18]==0x10100 and state[ENDPOINT+0x10]==BAR
        assert state.get(ENDPOINT+4,0)==(0 if ordinal in (0,3) else 6)
        assert state[PORT+0x20]==(0x0000fff0 if ordinal==4 else 0x10f01000)
        status=B+(0xa0 if ordinal==2 else 0x4c)
        observed=[e['value'] for e in following if e['op']=='readl' and e['address']==status]
        assert observed[:2]==[0x10000 if ordinal in (0,3,4) else 1,0]
        pending=[e['value']&0x40 for e in following if e['op']=='readl' and e['address']==GIC_PENDING]
        assert pending[:3]==[0,0x40,0]
        def buffers(address):
            return [(n,e['bytes']) for n,e in enumerate(following) if e['op']=='read' and e['address']==address]
        if ordinal==0:
            data=buffers(PEER);assert data[0][1]==b'\xa5'*4096
        elif ordinal==1:
            data=buffers(PEER);assert data[0][1]==peer1 and buffers(BAR)[0][1]==peer1
        elif ordinal==2:
            data=buffers(AP_DEST);assert data[0][1]==b'\xa5'*16+other+b'\xa5'*16
            assert buffers(PEER+16)[0][1]==other
        else:
            data=buffers(PEER);assert data[0][1]==peer2
        assert not any(e['op']=='write' for e in following[:data[0][0]])
    review={'status':'PASS_REAL_PCIE_BAR_HARDWARE_ONLY','binary_sha256':digest,
            'real_config_bar_and_bridge_consumed':True,'bidirectional_dma_gic_and_guards':True,
            'disabled_command_and_closed_bridge_abort':True,
            'final_peer_sha256':hashlib.sha256(peer2).hexdigest(),
            'trace_sha256':hashlib.sha256(trace.encode()).hexdigest(),
            'original_kernel_api_verified':False,'sony_phy_or_cp_verified':False,'capture_verified':False}
    serialized=json.dumps(review,indent=2)+'\n'
    (HERE.parent/('pcie-peer-validation-'+digest[:12]+'.json')).write_text(serialized)
    (HERE.parent/'pcie-peer-validation.json').write_text(serialized)
    print('MAIN_PASS real PCIe config/BAR/commands/bridge-gated DMA/GIC bytes; NO original kernel/Sony PHY/CP')


if __name__=='__main__':main()
