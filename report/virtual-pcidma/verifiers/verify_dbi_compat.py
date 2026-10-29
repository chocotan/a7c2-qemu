#!/usr/bin/env python3
"""Independent actual DBI-control/Root-Port-config trace proof, TEST hardware only."""
import argparse
import hashlib
import json
from pathlib import Path
from verify_hardware import transactions

HERE=Path(__file__).resolve().parent
PORT=0x3f008000
DBI=0xf7000000
WRAPPER=0xf11c0000


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate',type=Path);parser.add_argument('run',type=Path)
    args=parser.parse_args();proof=json.loads((args.candidate/'build-proof.json').read_text())
    result=json.loads((args.run/'result.json').read_text())
    digest=hashlib.sha256((args.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==result['binary_sha256'] and result['hardware_verified']
    for name,expected in proof['model_source_sha256'].items():
        assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==expected
    assert 'dev: a7c2-test-root-dbi,' in (args.run/'enabled/qtree.txt').read_text()
    trace=(args.run/'enabled/qemu.log').read_text();events=transactions(trace)
    # Derive the PCIe capability from actual config reads, not the auto flag.
    candidates=[e for e in events if e['op']=='readl' and PORT+0x40<=e['address']<PORT+0x100
                and e['value']&255==0x10]
    assert candidates
    cap=candidates[0]['address']-PORT
    assert cap==int(result['dbi_compatibility']['capability'],16)
    slot=cap+0x14
    values=[e['value'] for e in events if e['op']=='readl' and e['address']==PORT+slot]
    assert len(values)==5
    old=values[0];different=old^(1<<19)
    assert values==[old,old,old,different,old]
    flags=[e['bytes'] for e in events if e['op']=='read' and e['address']==PORT+cap+2]
    assert len(flags)==3 and flags[0]==flags[2]
    changed=(int.from_bytes(flags[0],'little')^0x100).to_bytes(2,'little')
    assert flags[1]==changed
    assert [e['value'] for e in events if e['op']=='readl' and e['address']==DBI+0x8bc]==[0]
    assert [e['value'] for e in events if e['op']=='readl' and e['address']==WRAPPER+0x20380]==[0x40]
    assert not any(e['op'] in ('write','writel') and e['address'] in (PORT+slot,PORT+cap+2) for e in events)
    control=0x40;unlock=0;slot_writes=[];flag_writes=[]
    for e in events:
        if e['op']=='writel':
            if e['address']==WRAPPER+0x20380:control=e['value']
            if e['address']==DBI+0x8bc:unlock=e['value']
            if e['address']==DBI+slot:slot_writes.append((control,unlock,e['value']))
        if e['op']=='write' and e['address']==DBI+cap+2:flag_writes.append((control,unlock,e['bytes']))
    assert slot_writes==[(0x40,0,different),(0x40,1,different),(0,1,different),(0,1,old),(0x40,0,different)]
    assert flag_writes==[(0,1,changed),(0,1,flags[0])]
    assert control==0x40 and unlock==0
    review={'status':'PASS_TEST_DBI_HARDWARE_ONLY','binary_sha256':digest,'root_pcie_capability':hex(cap),
            'actual_ecam_slot_flags_and_capabilities_changed':True,'locked_or_wrong_sequence_prevents_change':True,
            'original_values_restored_and_locked':True,'trace_sha256':hashlib.sha256(trace.encode()).hexdigest(),
            'silicon_reset_phy_semantics_verified':False,'kernel_context_or_api_verified':False,'capture_verified':False}
    (HERE.parent/'dbi-compat-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS actual DBI sequence controls real Root Port ECAM RO fields; NO kernel context/PHY/CP claim')


if __name__=='__main__':main()
