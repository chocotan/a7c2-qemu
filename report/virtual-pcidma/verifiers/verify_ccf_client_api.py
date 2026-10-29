#!/usr/bin/env python3
"""Original exported CCF/OF surface used by the diagnostic; no private layout calls."""
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[3]
BASE=0xffffff8008080000
EXPORTS={'clk_put':(0x579350,0x258328),'of_clk_get_by_name':(0x57ee30,0x2587d0),
    'of_node_put':(0x57f160,0x30c730),'__clk_is_enabled':(0x584930,0x258a30),
    'clk_disable':(0x585cb0,0x259150),'clk_enable':(0x585ce0,0x259270),
    'clk_get_rate':(0x585d60,0x2599f0),'clk_prepare':(0x585fa0,0x2594e8),
    'clk_unprepare':(0x5860e0,0x25add0),'of_find_node_opts_by_path':(0x57ef90,0x3093e8)}
PINS={0x2587d0:'000100b4',0x2587d8:'e20301aa',0x2587e0:'010c40f9',
    0x2587e4:'b1ffff97',0x258a30:'400200b4',0x258a34:'000040f9',
    0x258a3c:'211840f9',0x258a50:'20003fd6',0x258a58:'e0079f1a',
    0x2594f8:'130040f9',0x259510:'e003132a',0x2599fc:'000040f9',
    0x309418:'930000b4',0x309424:'600200f9'}


def main():
    b=(ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    assert len(b)==6610952 and hashlib.sha256(b).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
    for name,(record,target) in EXPORTS.items():
        value,pointer=struct.unpack_from('<QQ',b,record);assert value==BASE+target
        pointer-=BASE;assert b[pointer:pointer+len(name)+1]==name.encode()+b'\0'
    for at,raw in PINS.items():assert b[at:at+4]==bytes.fromhex(raw),hex(at)
    print(json.dumps({'status':'PASS_STATIC_CCF_CLIENT_API','exports':len(EXPORTS),'pins':len(PINS),
        'node_lookup_allows_null_options':True,'normal_clock_handle_arguments_only':True,
        'runtime_provider_or_rates_verified':False},indent=2))


if __name__=='__main__':main()
