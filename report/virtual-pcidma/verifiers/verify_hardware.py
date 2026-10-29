#!/usr/bin/env python3
"""Independently check actual qtest traffic, source bytes and GIC transitions."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

HERE=Path(__file__).resolve().parent
B=0xf7380000
PEER=0x600000000
PCI=0x04000000
PENDING=0x08000218
BIT=0x40


def transactions(text):
    pending=None; events=[]
    for line in text.splitlines():
        request=re.match(r'\[R [^]]*\] (.*)$',line)
        response=re.match(r'\[S [^]]*\] (.*)$',line)
        if request:
            assert pending is None
            pending=request[1].split()
        elif response:
            assert pending is not None and response[1].startswith('OK')
            op=pending[0]; values=pending[1:]; event={'op':op}
            if op in ('write','read','writel','readl'):
                event['address']=int(values[0],0)
                if op=='write':
                    event['bytes']=bytes.fromhex(values[2].removeprefix('0x'))
                    assert len(event['bytes'])==int(values[1],0)
                elif op=='read':
                    event['bytes']=bytes.fromhex(response[1][2:].strip().removeprefix('0x'))
                    assert len(event['bytes'])==int(values[1],0)
                elif op=='writel':event['value']=int(values[1],0)
                else:event['value']=int(response[1][2:].strip(),0)
            events.append(event); pending=None
    assert pending is None
    return events


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate',type=Path); parser.add_argument('run',type=Path)
    args=parser.parse_args(); proof=json.loads((args.candidate/'build-proof.json').read_text())
    result=json.loads((args.run/'result.json').read_text())
    binary=args.candidate/'build/qemu-system-aarch64'
    digest=hashlib.sha256(binary.read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==result['binary_sha256']
    for name,expected in proof['model_source_sha256'].items():
        assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==expected
    assert result['hardware_verified'] and len(result['requests'])==18 and len(result['faults'])==3
    assert 'dev: sony-virtual-pcidma,' in (args.run/'enabled/qtree.txt').read_text()
    assert 'dev: sony-virtual-pcidma,' not in (args.run/'disabled/qtree.txt').read_text()
    log=(args.run/'enabled/qemu.log').read_text(); events=transactions(log)
    registers={}; memory_writes={}; rings=[]
    for index,event in enumerate(events):
        if event['op']=='write':memory_writes[event['address']]=(index,event['bytes'])
        if event['op']=='writel':
            registers[event['address']]=event['value']
            if event['address'] in (B+0x10,B+0x30):
                rings.append((index,event,registers.copy(),memory_writes.copy()))
    assert len(rings)==21
    checks=[]
    for ordinal,(index,event,regs,writes) in enumerate(rings):
        end=rings[ordinal+1][0] if ordinal+1<len(rings) else len(events)
        following=events[index+1:end]
        direction=int(event['address']==B+0x30); ch=event['value']
        assert 0<=ch<8
        status=B+(0xa0 if direction else 0x4c)
        channel=B+0x200+direction*0x100+ch*0x200
        linked=bool(regs[channel]&0x200)
        assert regs[B+(0x2c if direction else 0xc)]==1
        assert regs[B+(0x168 if direction else 0x128)+ch*4]==1
        pending=[v['value']&BIT for v in following if v['op']=='readl' and v['address']==PENDING]
        assert pending[:3]==[0,BIT,0], (ordinal,'actual masked/unmasked/cleared GIC pending')
        statuses=[v['value'] for v in following if v['op']=='readl' and v['address']==status]
        expected=1<<(ch+(16 if ordinal>=18 else 0))
        assert statuses[:2]==[expected,0], (ordinal,'done/abort and W1C')
        if ordinal>=18:
            peer=[v['bytes'] for v in following if v['op']=='read' and v['address']==PEER]
            assert peer and peer[0]==b'\xa5'*4096
            checks.append({'fault':result['faults'][ordinal-18]['kind'],'actual_abort_gic_peer_verified':True})
            continue
        declared=result['requests'][ordinal]
        assert (direction,ch,linked)==(declared['direction'],declared['channel'],declared['linked'])
        if linked:
            pointer=regs[channel+0x1c] | regs[channel+0x20]<<32
            _,program=writes[pointer]
            control,length,source,target=struct.unpack_from('<IIQQ',program)
            assert control==9 and struct.unpack_from('<I',program,24)[0]==6
        else:
            length=regs[channel+8]
            source=regs[channel+0xc] | regs[channel+0x10]<<32
            target=regs[channel+0x14] | regs[channel+0x18]<<32
        assert length==256
        source_physical=PEER+source-PCI if direction else source
        target_physical=target if direction else PEER+target-PCI
        _,payload=writes[source_physical]; assert len(payload)==256
        guard_index,guard=writes[target_physical-16]
        assert guard==b'\xa5'*288 and guard_index<index
        data_reads=[(j,v['bytes']) for j,v in enumerate(following)
                    if v['op']=='read' and v['address']==target_physical-16]
        assert data_reads and data_reads[0][1]==b'\xa5'*16+payload+b'\xa5'*16
        assert not any(v['op']=='write' for v in following[:data_reads[0][0]])
        source_reads=[v['bytes'] for v in following if v['op']=='read' and v['address']==source_physical]
        assert source_reads and source_reads[0]==payload
        states=[v['value'] for v in following if v['op']=='readl' and v['address']==channel]
        assert states and states[0]&0x60==0x60
        checks.append({'direction':direction,'channel':ch,'linked':linked,
                       'actual_data_sha256':hashlib.sha256(payload).hexdigest(),
                       'guards_source_gic_and_ack_verified':True})
    review={'status':'PASS_HARDWARE_ONLY','binary_sha256':digest,'direct_cases':16,'linked_cases':2,
            'fault_cases':3,'raw_trace_sha256':hashlib.sha256(log.encode()).hexdigest(),
            'checks':checks,'original_driver_verified':False,'cp_or_capture_verified':False}
    (HERE.parent/'hardware-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS actual qtest source/data/guards/GIC198/W1C/deassert: 16direct+2LLI+3fault; NO original PCI driver/CP/CMOS')


if __name__=='__main__':main()
