#!/usr/bin/env python3
"""Recover original compressed symbols and boot registration edges; never execute them."""
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[3]


def main():
    b=(ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    assert len(b)==6610952 and hashlib.sha256(b).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
    assert struct.unpack_from('<Q',b,0x4aaa00)[0]==0xffffff8008080000
    count=struct.unpack_from('<Q',b,0x4aab00)[0];assert count==41265
    offsets=struct.unpack_from('<'+'I'*count,b,0x482500)
    assert all(x<=y for x,y in zip(offsets,offsets[1:]))
    indices=struct.unpack_from('<256H',b,0x522700)
    tokens=[b[0x522300+i:b.index(0,0x522300+i)].decode('ascii') for i in indices]
    position=0x4aac00;symbols={}
    for address in offsets:
        length=b[position];position+=1
        name=''.join(tokens[c] for c in b[position:position+length]);position+=length
        symbols.setdefault(name[1:],[]).append(address)
    assert position==0x521c25
    expected={'ioremap_page_range':0x1f31c8,'udif_devices':0x63e230,'setup_arch':0x5b3638,'map_io':0x5b6f80,
        'pcidma_init':0x5cbd3c,'__boottime___udif_init_pcidma':0x5cbed0,
        '__boottime___udif_init_udif_pcie':0x5d0304,
        '__boottime_cxd900xx_reset_init':0x5c9830,'__boottime_dw_plat_pcie_driver_init':0x5c8d0c}
    for name,address in expected.items():assert symbols[name]==[address],name
    pins={0x5cbeec:'42c01e91',0x5cbef0:'21008052',0x5cbef4:'028c1ff8',
        0x5cbef8:'8638f597',0x5d0320:'42203b91',0x5d0324:'21008052',
        0x5d0328:'42400291',0x5d032c:'028c1ff8',0x5d0330:'7827f597',
        0x5cbe80:'4859f397',0x5cbe94:'df160071',0x5cbeac:'6742f597',
        0x5c9844:'000300b0',0x5c984c:'00a01591',0x5c9850:'cee0f297'}
    for address,value in pins.items():assert b[address:address+4]==bytes.fromhex(value),hex(address)
    # Original arch-init reset registration precedes device-init DW registration;
    # do not infer runtime provider binding or shared-reset correctness from this.
    for name,address in {'__initcall3_start':0x5dfa90,'__initcall4_start':0x5dfad8,
                         '__initcall6_start':0x5dfd58,'__initcall7_start':0x5e0278,
                         '__initcall_cxd900xx_reset_init3':0x5dfaa8,
                         '__initcall_dw_plat_pcie_driver_init6':0x5e0040}.items():assert symbols[name]==[address]
    assert struct.unpack_from('<Q',b,0x5dfaa8)[0]==0xffffff8008080000+0x5c9830
    assert struct.unpack_from('<Q',b,0x5e0040)[0]==0xffffff8008080000+0x5c8d0c
    print(json.dumps({'status':'PASS_STATIC_NATIVE_INIT_ENTRIES','symbols':count,'pins':len(pins),
        'native_entries':{k:hex(v) for k,v in expected.items()},
        'pcidma_registration_descriptor':'62e7b0','pcie_registration_descriptor':'640f58',
        'reset_arch_init_precedes_dw_device_init':True,'runtime_provider_or_shared_reset_proven':False,
        'late_call_or_descriptor_lifetime_proven':False,'normal_boot_runtime_verified':False},indent=2))


if __name__=='__main__':main()
