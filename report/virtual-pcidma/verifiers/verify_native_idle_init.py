#!/usr/bin/env python3
"""Bound original idle-init worker gates and real API identities; no runtime proof."""
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[3]
BASE=0xffffff8008080000
PINS={0x2a2e44:'f967fd97',0x2a2e64:'b708fb97',0x2a2e68:'603209f9',
    0x2a3a64:'47e30194',0x2a3a68:'1f0c0071',0x2a3a7c:'a0000054',
    0x2a3abc:'1165f697',0x2a3aec:'741e00f9',0x2a3b00:'2a87f697',
    0x5cbdb0:'7f0e00b9',0x2a1fdc:'7f7c00a9',0x2a406c:'a563f697',
    0x2a407c:'cb85f697',0x5cbf14:'db2cf597',0x2a3f18:'602649f9',
    0x2a3f24:'60000036',0x2a3f28:'600e40b9',0x2a3f2c:'60020035',
    0x2a3f30:'007682d2',0x2a3264:'605240b9',0x2a3268:'c0fdff34'}


def main():
    b=(ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    assert len(b)==6610952 and hashlib.sha256(b).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
    for p,raw in PINS.items():assert b[p:p+4]==bytes.fromhex(raw),hex(p)
    for record,target,name in ((0x580490,0x165140,b'proc_create_data'),
            (0x5832d0,0x317280,b'udif_cdev_register'),(0x57d9e0,0x3cf00,b'kthread_create_on_node'),
            (0x584050,0x457a8,b'wake_up_process')):
        target_actual,pointer=struct.unpack_from('<QQ',b,record)
        assert target_actual==BASE+target;pointer-=BASE
        assert b[pointer:pointer+len(name)+1]==name+b'\0'
    records=[]
    for index,(engine,wrapper,irq) in enumerate(((0xf7380000,0xf11c0000,198),(0xf6b80000,0xf1140000,200),
            (0xf6f80000,0xf1180000,202),(0xf7780000,0xf1200000,204),(0xf6780000,0xf1100000,206))):
        at=0x62ed00+index*0x13b0
        assert struct.unpack_from('<Q',b,at+0x1248)[0]==0xffffffff00000000|engine
        assert struct.unpack_from('<Q',b,at+0x1250)[0]==0xffffffff00000000|wrapper
        assert struct.unpack_from('<I',b,at+0x1238)[0]==irq
        records.append({'index':index,'engine':hex(engine),'wrapper':hex(wrapper),'irq':irq})
    assert struct.unpack_from('<5I',b,0x640ec8)==(1,)*5
    print(json.dumps({'status':'PASS_STATIC_IDLE_INIT_GATES','pins':len(PINS),'exports':4,
        'proc_create_data_is_not_workqueue_allocation':True,'all_five_records_present':records,
        'stallmon_requires_connected':True,'aspm_worker_pending_gate_pinned':True,
        'runtime_init_or_irq_verified':False,'controller0_only_input_proven':False},indent=2))


if __name__=='__main__':main()
