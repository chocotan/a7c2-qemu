#!/usr/bin/env python3
"""Original CCF records, PCIe parent rates, divider/mux fields and save-init behavior."""
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[3]
BASE=0xffffff8008080000
PINS={0x25fa60:'04220090',0x25fa68:'817401f9',0x25fa6c:'620800b9',0x25fa70:'600800f9',0x25fa74:'c0035fd6',
    0x260298:'73620091',0x2602c4:'641240b9',0x2602cc:'59f6ff97',
    0x2604a0:'73a20091',0x2604c8:'631a4329',0x2604d8:'c9200011',0x2604dc:'c7100011',
    0x2604f8:'5afeff97',0x2605b8:'73820091',0x2605e8:'67764039',0x2605ec:'66724039',
    0x2605f0:'651a40b9',0x2605fc:'bffeff97',0x25fedc:'2120d99a',0x25fee4:'21040051',
    0x25ff08:'78c20039',0x25ff14:'76ca0039',0x25ff1c:'7b6a0429',
    0x25fe00:'60d30094',0x25fe18:'7326c21a',0x25fe1c:'7302010a',0x25fe38:'1f00136b',
    0x2600b8:'b2d20094',0x2600dc:'a500020a',0x2600e8:'26f5ff97',
    0x2601a0:'77aa0039',0x2601ac:'76220429',0x25d510:'400300b4',0x25d578:'22040011',
    0x5c9808:'81423691',0x5c980c:'22038052',0x5c9810:'9458f297'}


def main():
    b=(ROOT/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    assert len(b)==6610952 and hashlib.sha256(b).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
    for p,raw in PINS.items():assert b[p:p+4]==bytes.fromhex(raw),hex(p)
    def text(p):return b[p-BASE:b.index(0,p-BASE)].decode() if p else None
    fixed={}
    for i in range(17):
        ident,name,rate=struct.unpack_from('<QQI',b,0x629620+i*24);fixed[text(name)]=rate
    selected=[];masks=[0]*9;gates={}
    for a in range(0x629ab0,0x62a370,32):
        ident,name,parent,reg,bit=struct.unpack_from('<QQQII',b,a)
        gates[ident]={'id':ident,'name':text(name),'parent':text(parent),'status_offset':reg,'bit':bit}
        masks[reg//16]|=1<<bit
    for ident,reg,bit,rate in ((62,0x80,1,99000000),(63,0x80,2,396000000),
            (64,0x80,3,396000000),(65,0x80,4,396000000),(66,0x80,5,1000000),
            (29,0x30,18,None),(30,0x30,19,None)):
        row=gates[ident];assert (row['status_offset'],row['bit'])==(reg,bit)
        assert (fixed[row['parent']] if row['parent'] else None)==rate
        selected.append(dict(row,fixed_parent_rate=rate))
    assert masks==[0x1f000,0,0x30f,0x2c000c,0x13fffc0,0xdf7c0,0,0,0x3efbefbe]
    div=[]
    for i in range(5):
        a=0x6297b8+32*i;ident,name,parent,reg=struct.unpack_from('<QQQI',b,a)
        assert ident==102+i and reg==0x10c+4*i and b[a+28:a+32]==bytes((0,8,0,0))
        div.append(reg)
    mux_masks={}
    for i in range(15):
        a=0x629858+i*40;ident,name,parents,count,reg=struct.unpack_from('<QQQII',b,a)
        shift,width=b[a+32:a+34];assert count in (2,4) and count==1<<width
        assert reg in (0x210,0x220,0x230);mux_masks[reg]=mux_masks.get(reg,0)|(((1<<width)-1)<<shift)
    assert mux_masks=={0x210:0x1f000000,0x220:0x11111,0x230:0x3ff}
    print(json.dumps({'status':'PASS_STATIC_CCF_STARTUP_INPUTS','pins':len(PINS),
        'controller0_clocks':selected,'fixed_records':17,'gate_records':70,'gate_masks':list(map(hex,masks)),
        'divider_status_offsets':list(map(hex,div)),'divider_width':8,'flags0_encoding_zero_divides_by':1,
        'mux_status_masks':{hex(k):hex(v) for k,v in mux_masks.items()},'mux_encoding_zero_selects_valid_parent0':True,
        'save_init':'records pointers/count only; no register read','save_table':'62a398','save_count':25,
        'silicon_boot_values':'unknown; do not substitute raw RAM0','runtime_provider_verified':False},indent=2))


if __name__=='__main__':main()
