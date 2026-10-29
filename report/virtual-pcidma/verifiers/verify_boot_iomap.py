#!/usr/bin/env python3
"""Original setup_arch -> map_io -> normal page mapper + official iomap schema."""
import hashlib
import json
from pathlib import Path
import struct
from verify_enumeration import fdt_nodes

ROOT=Path(__file__).resolve().parents[3]
N=ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked'
PINS={0x5b3a78:'420d0094',0x5b6f84:'000080d2',0x5b6f94:'81e22c91',
    0x5b6fa4:'bf4bf597',0x5b6fbc:'5946f597',0x5b6fe8:'4e46f597',
    0x5b7014:'4346f597',0x5b7040:'040080d2',0x5b7044:'230080d2',
    0x5b7048:'d045f597',0x5b70b8:'3f0c0071',0x5b70bc:'c9000054',
    0x5b70d8:'00b01891',0x5b70dc:'00486138',0x5b70e0:'61000010',
    0x5b70e4:'2088208b',0x5b70e8:'00001fd6',0x5b70f8:'21000014',
    0x5b717c:'c10400f0',0x5b7180:'e4e081d2',0x5b7184:'e0e080d2',
    0x5b7194:'3f0070f2',0x5b7198:'8410809a',0x5b7068:'a32740f9',
    0x5b706c:'a18b43a9',0x5b7074:'001c46f9',0x5b7080:'fe7ee997',
    0x5b70a8:'7e4bf597',0x16c7c:'470001ca',0x16c88:'ff2c40f2'}


def main():
    b=(N/'0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    dtb=(N/'0800_appli/setting/cxd90057.dtb').read_bytes()
    assert len(b)==6610952 and hashlib.sha256(b).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
    assert hashlib.sha256(dtb).hexdigest()=='c5735ad9c6da8c48fb24eeee0bb743d07c486a47d5db19bef13b5eaea24ad280'
    for address,value in PINS.items():assert b[address:address+4]==bytes.fromhex(value),hex(address)
    for a,text in ((0x527b38,b'iomap'),(0x527b40,b'phys'),(0x527b60,b'virt'),(0x5476e8,b'size'),(0x527ad0,b'memtype')):
        assert b[a:a+len(text)+1]==text+b'\0'
    assert b[0x43762c:0x437630]==bytes.fromhex('da030b13')
    props=fdt_nodes(dtb)['/iomem@0xf0000000']
    assert props['device_type']==b'iomap\0' and props['memtype']==struct.pack('>I',1)
    for name,value in (('phys',0xf0000000),('virt',0xfffffffff0000000),('size',0x0e000000)):
        assert props[name]==struct.pack('>Q',value)
    print(json.dumps({'status':'PASS_STATIC_NORMAL_BOOT_IOMAP_ROUTE','pins':len(PINS),
        'boot_call':'5b3a78 -> 5b6f80','normal_mapping_call':'5b7080 -> 16c78',
        'official_schema_verified':True,'runtime_mapping_verified':False},indent=2))


if __name__=='__main__':main()
