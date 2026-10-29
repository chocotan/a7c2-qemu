#!/usr/bin/env python3
"""Original PCIDMA API/host-init admission pins. Read-only, static evidence only."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[3]
DEFAULT=ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
BASE=0xffffff8008080000
SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
PINS={
    0x2a2234:'1f100071',0x2a2268:'fb03012a',0x2a22e4:'b5050094',
    0x2a2318:'7a1600b9',0x2a2334:'1f230071',0x2a23c0:'031080d2',
    0x2a23d4:'2300a0f2',0x31b52c:'007808d5',0x31b534:'017438d5',
    0x2a253c:'1f100071',0x2a2558:'81000035',0x2a2570:'012449f9',
    0x2a2574:'42001f32',0x2a2578:'24300091',0x2a257c:'020400b9',
    0x2a2580:'830000b9',0x2a2590:'24b00091',0x2a2594:'830000b9',
    0x2a2588:'24600191',0x2a258c:'820000b9',0x2a2598:'21b00291',
    0x2a259c:'220000b9',0x2a25b0:'410000b9',0x2a25b8:'410000b9',
    0x2a25bc:'01500191',0x2a25c0:'3f0000b9',0x2a25c4:'00a00291',
    0x2a25c8:'1f0000b9',
}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('image',nargs='?',type=Path,default=DEFAULT)
    b=parser.parse_args().image.read_bytes()
    assert len(b)==6610952 and hashlib.sha256(b).hexdigest()==SHA
    for address,raw in PINS.items():assert b[address:address+4]==bytes.fromhex(raw),hex(address)
    for record,target,name in ((0x57fe40,0x2a2230,b'pcidma_connect'),
            (0x57fe50,0x2a20c8,b'pcidma_transfer_async'),(0x580c50,0x6c8b0,b'request_threaded_irq')):
        value,ptr=struct.unpack_from('<QQ',b,record);assert value==BASE+target
        ptr-=BASE;assert b[ptr:ptr+len(name)+1]==name+b'\0'
    for target in (0x31de10,0x2a2538):
        assert not any(struct.unpack_from('<Q',b,p)[0]==BASE+target for p in range(0x570000,0x590000,16))
    print(json.dumps({'status':'PASS_STATIC_ADMISSION_PINS','pins':len(PINS),'kernel_sha256':SHA,
        'producer_and_callback_have_no_export_in_verified_region':True,
        'host_callback_enables_write_and_read_engines_at_0c_2c':True,
        'runtime_irq_or_host_initialization_verified':False,'dma_executed':False},indent=2))


if __name__=='__main__':main()
