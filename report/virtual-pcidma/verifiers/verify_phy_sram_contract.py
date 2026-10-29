#!/usr/bin/env python3
"""Original selected PHY input and timeout/apply distinction; never extract public raw firmware."""
import hashlib
import json
from pathlib import Path
import struct
from verify_enumeration import fdt_nodes

ROOT=Path(__file__).resolve().parents[3]
BASE=0xffffff8008080000
PINS={0x249b30:'012040b9',0x249b34:'3f000071',0x249b38:'640b407a',
    0x249b3c:'60060054',0x249b44:'13198052',0x249b50:'73060071',
    0x249b54:'e0300054',0x249b68:'7ef0ff97',0x249b6c:'20ff1736',
    0x249b70:'e0018092',0x249b7c:'fc071132',0x249b80:'1b503b8b',
    0x249b88:'73021b8b',0x249b8c:'1b008052',0x249b94:'600a40b9',
    0x249ba8:'9c130011',0x249bac:'02d87b78',0x249bb0:'7b070011',
    0x249bb8:'70f0ff97',0x249bc0:'7f03006b',0x249bc4:'ebfeff54',
    0x249bd0:'13008052',0x249be8:'02001f32',0x249bf8:'60f0ff97',
    0x249c00:'332e0035',0x24a174:'13008012',0x24a17c:'97feff17'}


def main():
    n=ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked'
    b=(n/'0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    dtb=(n/'0800_appli/setting/cxd90057.dtb').read_bytes()
    assert len(b)==6610952 and hashlib.sha256(b).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
    assert hashlib.sha256(dtb).hexdigest()=='c5735ad9c6da8c48fb24eeee0bb743d07c486a47d5db19bef13b5eaea24ad280'
    for a,raw in PINS.items():assert b[a:a+4]==bytes.fromhex(raw),hex(a)
    pointer,count=struct.unpack_from('<Qi',b,0x45ffc0)
    assert pointer==BASE+0x4601c0 and count==4096
    table=b[pointer-BASE:pointer-BASE+2*count];assert len(table)==8192
    assert hashlib.sha256(table).hexdigest()=='6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95'
    words=struct.unpack('<4096H',table);stream=b''.join(struct.pack('<I',v) for v in words)
    assert len(stream)==0x4000
    controller=fdt_nodes(dtb)['/soc/pcie_i']
    assert controller['firm-id']==struct.pack('>I',1) and controller['num-lanes']==struct.pack('>I',4)
    tail=0
    for value in reversed(words):
        if value:break
        tail+=1
    print(json.dumps({'status':'PASS_STATIC_PHY_SRAM_INPUT','pins':len(PINS),
        'firm_id':1,'descriptor':'45ffc0','table_raw_start':'4601c0','halfwords':count,
        'input_bytes':len(table),'input_sha256':hashlib.sha256(table).hexdigest(),
        'mmio_writes':4096,'mmio_start_offset':'18000','mmio_last_offset':'1bffc',
        'zero_extended_mmio_stream_sha256':hashlib.sha256(stream).hexdigest(),'trailing_zero_halfwords':tail,
        'poll_limit':200,'timeout_still_writes_bit1':True,'apply_bit_not_upload_completion':True,
        'sram_readback_in_this_loop':False,'bit2_hardware_producer':'unresolved',
        'current_context20_gate_semantics':'unresolved; never force it','runtime_upload_verified':False},indent=2))


if __name__=='__main__':main()
