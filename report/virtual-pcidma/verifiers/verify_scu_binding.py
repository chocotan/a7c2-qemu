#!/usr/bin/env python3
"""Bind UDIF HCLK and misleading DEVCLK fields to original clock/reset providers."""
import hashlib
import json
from pathlib import Path
import struct
from verify_enumeration import fdt_nodes

ROOT=Path(__file__).resolve().parents[3]
BASE=0xffffff8008080000
PINS={0x5c96ec:'656cf397',0x5c97b4:'e15af297',0x2603c8:'a7200011',
    0x2603cc:'a6100011',0x2603dc:'f7fdff97',0x25fc64:'636e01a9',
    0x25fc68:'79620429',0x25fc6c:'772a00b9',
    0x2611cc:'ad0d0194',0x2611e8:'c8800094',0x2611f4:'620040f9',
    0x261200:'61220091',0x261204:'625a00b9',0x261218:'630600f9',
    0x26107c:'23fc45d3',0x261090:'015040b9',0x261098:'2110030b',
    0x26109c:'b9ce0094',0x2610a8:'73120012',0x2610ac:'0024d39a',
    0x2610b0:'00000012',0x2610cc:'4220c11a',0x2610dc:'61100011',
    0x2610e4:'a1d30094',0x261114:'21200011',0x261118:'2110030b',
    0x26111c:'93d30094'}


def main():
    n=ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked'
    b=(n/'0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    dtb=(n/'0800_appli/setting/cxd90057.dtb').read_bytes()
    assert len(b)==6610952 and hashlib.sha256(b).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
    assert hashlib.sha256(dtb).hexdigest()=='c5735ad9c6da8c48fb24eeee0bb743d07c486a47d5db19bef13b5eaea24ad280'
    for at,raw in PINS.items():assert b[at:at+4]==bytes.fromhex(raw),hex(at)
    assert struct.unpack_from('<4Q',b,0x4661c0)==(0,BASE+0x2610c0,BASE+0x2610f0,BASE+0x261078)
    nodes=fdt_nodes(dtb);scu=nodes['/soc/scu@F1388000'];rst=nodes['/soc/scu@F1388000/rst@300']
    assert struct.unpack('>4I',scu['reg'])==(0,0xf1388000,0,0x2000)
    assert struct.unpack('>4I',rst['reg'])==(0,0x300,0,0x80)
    assert rst['syscon']==struct.pack('>I',4)
    ids=[]
    for name,bit in zip(('pcie_i','pcie_m0','pcie_m1','pcie_c','pcie_n'),(3,11,7,15,19)):
        props=nodes['/soc/'+name];assert props['reset-names'].split(b'\0')[3]==b'rst_apb'
        cells=struct.unpack('>'+'I'*(len(props['resets'])//4),props['resets']);ident=cells[7]
        assert ident==32+bit and cells[6]==3
        assert 0x300+(ident>>5)*16==0x310;ids.append(ident)
    hclk=[]
    for at in range(0x629ab0,0x62a370,0x20):
        ident,name,parent,offset,bit=struct.unpack_from('<QQQII',b,at)
        if offset==0x80 and bit in (1,7,13,19,25):hclk.append((ident,offset,bit))
    assert hclk==[(62,0x80,1),(67,0x80,7),(72,0x80,13),(77,0x80,19),(82,0x80,25)]
    print(json.dumps({'status':'PASS_STATIC_EXACT_SCU_BINDING','pins':len(PINS),
        'hclk_status_set_clear':['f1388080','f1388084','f1388088'],
        'devclk_field_is_apb_reset_not_clock':True,'reset_status_assert_deassert':['f1388310','f1388314','f1388318'],
        'reset_ids':ids,'reset_status_one_means_asserted':True,
        'silicon_reset_state':'unknown; virtual test policy must be explicit','runtime_model_verified':False},indent=2))


if __name__=='__main__':main()
