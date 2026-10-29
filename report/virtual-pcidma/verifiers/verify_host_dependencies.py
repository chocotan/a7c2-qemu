#!/usr/bin/env python3
"""Required reset/clock lookup pins and official controller0 OF schema; static only."""
import hashlib
import json
from pathlib import Path
import struct
from verify_enumeration import fdt_nodes

ROOT=Path(__file__).resolve().parents[3]
N=ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked'
PINS={
    0x249844:'7f0e00f1',0x24985c:'04008052',0x249860:'03008052',
    0x249864:'02008052',0x24987c:'04008052',0x249880:'23008052',
    0x249884:'02008052',0x249888:'6a5d0094',0x24989c:'48020054',
    0x2498a0:'7f1a00f1',0x2498b4:'04008052',0x2498cc:'595d0094',
    0x2498f8:'53028012',0x24994c:'cd390094',0x249958:'88010054',
    0x24995c:'7fe200f1',0x249978:'c2390094',0x249998:'53028012',
    0x260e58:'781c0053',0x260e6c:'941c0053',0x260e84:'e403142a',
    0x260e88:'e303182a',0x260e94:'2fffff97',0x260b74:'961c0053',
    0x260b88:'2ca30294',0x260bb8:'2ca80294',0x260bc8:'96020035',
    0x260c10:'34008092',0x260c94:'94408092',0x260cdc:'c1070054',
    0x260dd8:'b4028092',0x2580c4:'cd010094',0x258820:'a2ffff97',
    0x258844:'63feff97',0x258860:'1f1408b1',0x258864:'c1feff54',
}


def main():
    image=(N/'0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    dtb=(N/'0800_appli/setting/cxd90057.dtb').read_bytes()
    assert len(image)==6610952 and hashlib.sha256(image).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
    assert len(dtb)==16875 and hashlib.sha256(dtb).hexdigest()=='c5735ad9c6da8c48fb24eeee0bb743d07c486a47d5db19bef13b5eaea24ad280'
    for a,raw in PINS.items():assert image[a:a+4]==bytes.fromhex(raw),hex(a)
    nodes=fdt_nodes(dtb);consumer=nodes['/soc/pcie_i']
    for prop,phandle,indices in (('clocks',2,(0x3e,0x3f,0x40,0x41,0x42,0x1d,0x1e)),
                                ('resets',3,(0x20,0x21,0x22,0x23,0x76,0x77))):
        expected=tuple(v for index in indices for v in (phandle,index))
        assert struct.unpack('>'+'I'*len(expected),consumer[prop])==expected
    providers={struct.unpack('>I',p['phandle'])[0]:p for p in nodes.values() if 'phandle' in p}
    assert providers[2]['compatible']==b'cxd,900xx-clock\0'
    assert providers[3]['compatible']==b'cxd900xx,reset\0'
    assert providers[2]['#clock-cells']==providers[3]['#reset-cells']==struct.pack('>I',1)
    print(json.dumps({'status':'PASS_STATIC_HOST_DEPENDENCIES','pins':len(PINS),
        'reset_lookups':6,'last_two_shared_not_optional':True,'clock_lookups':7,
        'probe_lookup_error_becomes_ENODEV':True,'official_providers_verified':True,
        'runtime_provider_or_host_init_verified':False},indent=2))


if __name__=='__main__':main()
