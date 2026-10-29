#!/usr/bin/env python3
"""Original PCIe diagnostic parent creation and pre-probe clock-state dependency."""
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[3]
BASE=0xffffff8008080000
PINS={0x31d2d8:'00800b91',0x31d2dc:'010080d2',0x31d2e4:'8f1ff997',
    0x31d2f0:'20e803f9',0x31d320:'acffff97',0x31d328:'400500b4',
    0x31d33c:'010280d2',0x31d340:'ba7efb97',0x31d34c:'751ff997',
    0x31d1e8:'337cb39b',0x31d1ec:'021040f9',0x31d1f8:'350c40f9',
    0x31d200:'223440f9',0x31d204:'217840b9',0x31d20c:'421000d1',
    0x31d210:'420040b9',0x31d21c:'4224c19a',0x31d220:'e2030036',
    0x31d268:'a00240b9',0x31d274:'00001c32',0x31d278:'a00200b9'}


def main():
    b=(ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    assert len(b)==6610952 and hashlib.sha256(b).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
    for p,raw in PINS.items():assert b[p:p+4]==bytes.fromhex(raw),hex(p)
    assert b[0x5612e0:0x5612ec]==b'driver/pcie\0'
    target,string=struct.unpack_from('<QQ',b,0x5833f0);assert target==BASE+0x640f58
    at=string-BASE;assert b[at:at+10]==b'udif_pcie\0'
    assert struct.unpack_from('<Q',b,0x640f58+0x28)[0]==BASE+0x477a30
    assert struct.unpack_from('<Q',b,0x477a30)[0]==BASE+0x63e5d8
    assert struct.unpack_from('<I',b,0x63e5d8+0x18)[0]==5
    assert struct.unpack_from('<Q',b,0x63e5d8+0x20)[0]==BASE+0x63e8c8
    assert struct.unpack_from('<Q',b,0x640f58+0x38)[0]==BASE+0x641080
    assert struct.unpack_from('<Q',b,0x641080)[0]==BASE+0x31d2d0
    assert struct.unpack_from('<Q',b,0x641080+0x10)[0]==BASE+0x31d300
    for index,bit in enumerate((3,11,7,15,19)):
        slot=0x63e8c8+index*0x98
        assert struct.unpack_from('<Q',b,slot+0x68)[0]==0xfffffffff1388314
        assert struct.unpack_from('<I',b,slot+0x78)[0]==bit
    print(json.dumps({'status':'PASS_STATIC_PCIE_PROC_DEPENDENCY','pins':len(PINS),
        'original_parent_creator':'pcie_init31d2d0 -> proc_mkdir(driver/pcie)',
        'per_controller_creator':'pcie_probe31d300','pre_probe_status_pa':'f1388310',
        'clock_bits':[3,11,7,15,19],'legacy_all_ones_stub_is_not_valid_clock_evidence':True,
        'native_pcie_probe_or_phy_runtime_verified':False},indent=2))


if __name__=='__main__':main()
