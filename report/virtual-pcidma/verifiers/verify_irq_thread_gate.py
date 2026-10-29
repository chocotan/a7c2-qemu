#!/usr/bin/env python3
"""Original IRQ thread initial-wake gate; static only, no handler execution."""
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[3]
BASE=0xffffff8008080000
PINS={0x6ae28:'81020191',0x6ae2c:'40008052',0x6ae34:'a3110694',
    0x6b794:'d3020191',0x6b7c0:'5c0f0694',0x6b7c4:'e0020035',
    0x6b7c8:'86d20e94',0x6b7d0:'141000f9',0x6b7e0:'e10313aa',
    0x6b7e4:'00008052',0x6b7e8:'c0feff54',0x6b820:'004138d5',
    0x6b838:'e10316aa',0x6b83c:'e00315aa',0x6b840:'e0023fd6',
    0x1ef4dc:'420003aa',0x1ef548:'227c5fc8',0x1ef54c:'4024c39a',
    0x1ef550:'4200248a',0x1ef554:'22fc05c8',0x1ef560:'00004092'}


def main():
    b=(ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    assert len(b)==6610952 and hashlib.sha256(b).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
    for p,value in PINS.items():assert b[p:p+4]==bytes.fromhex(value),hex(p)
    for record,target,name in ((0x581270,0x1ef4c0,b'set_bit'),(0x582c70,0x1ef530,b'test_and_clear_bit')):
        value,pointer=struct.unpack_from('<QQ',b,record);assert value==BASE+target
        pointer-=BASE;assert b[pointer:pointer+len(name)+1]==name+b'\0'
    print(json.dumps({'status':'PASS_STATIC_IRQ_THREAD_WAIT_GATE','pins':len(PINS),
        'create_sets_bit2':'action+40h','callback_requires_consuming_bit0':True,
        'initial_wake_is_not_itself_handler_invocation':True,'runtime_irq_registration_verified':False},indent=2))


if __name__=='__main__':main()
