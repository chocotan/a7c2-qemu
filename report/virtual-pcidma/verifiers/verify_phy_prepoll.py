#!/usr/bin/env python3
"""Offline pre-poll pins; no target execution or SRAM-table re-verification."""
import hashlib,json,struct
from pathlib import Path
R=Path(__file__).resolve().parents[3]
K=R/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
b=K.read_bytes()
assert len(b)==6610952
assert hashlib.sha256(b).hexdigest()=='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
PINS={0x249a30:'1f2000b9',0x249a3c:'a0380034',0x24a154:'23008052',0x24a164:'432000b9',0x24a16c:'35feff17',0x249b34:'3f000071',0x249b38:'640b407a',0x249b3c:'60060054',0x249fa0:'02741e12',0x249fb8:'d0feff17',0x249e98:'18830091',0x247f34:'81820039'}
for a,h in PINS.items():assert b[a:a+4]==bytes.fromhex(h),hex(a)
for a,z,h in [(0x249a28,0x249b70,'d891fa063d3cd59f67175b0322416abef9cfe77e05d920a0427193e2dea50a79'),(0x249f94,0x249fbc,'a8878a91821e2fa8b034bd129c68d5e36b4ecc3b0869ce8957e79088efcb3d70'),(0x24a150,0x24a170,'ce10c144685b315ef17f00babb885fb31d6b0d6252d1c39745a8fb232c4e6a6f')]:assert hashlib.sha256(b[a:z]).hexdigest()==h
t=[b[0x522300+i:b.index(0,0x522300+i)].decode() for i in struct.unpack_from('<256H',b,0x522700)]
p=0x4aac00;s={}
for i in range(41265):
 n=b[p];name=''.join(t[v] for v in b[p+1:p+1+n]);p+=1+n
 s[struct.unpack_from('<I',b,0x482500+4*i)[0]]=name[1:]
CALLS={0x249a38:'reset_control_status',0x249a54:'reset_control_assert',0x249a64:'clk_prepare',0x249a7c:'clk_prepare',0x249a90:'clk_prepare',0x249aac:'clk_prepare',0x249ac0:'clk_prepare',0x249ad8:'reset_control_deassert',0x249afc:'reset_control_deassert',0x249b08:'reset_control_deassert',0x249b18:'reset_control_deassert',0x249b5c:'__const_udelay',0x249b68:'dw_pcie_readl_phy',0x249fb0:'dw_pcie_writel_phy',0x24a03c:'clk_enable',0x24a01c:'clk_enable',0x249ffc:'clk_enable',0x249fdc:'clk_enable',0x249fc0:'clk_enable'}
for a,name in CALLS.items():
 w=struct.unpack_from('<I',b,a)[0];assert w>>26==0x25
 q=w&0x3ffffff;q=q-(1<<26) if q&(1<<25) else q
 assert s[a+4*q]==name,(hex(a),name)
g=[]
for a in range(0x629ab0,0x62a370,0x20):
 i,n,parent,reg,bit=struct.unpack_from('<QQQII',b,a)
 if 62<=i<=66:g.append((i,reg,bit))
assert g==[(62,128,1),(63,128,2),(64,128,3),(65,128,4),(66,128,5)]
print(json.dumps({'status':'PASS_STATIC_PREPOLL','instruction_pins':len(PINS),'range_hashes':3,'symbol_bound_calls':len(CALLS),'controller0_gates':g,'runtime_verified':False,'bit2_hardware_producer':'unknown','new_callee_slices':3,'new_callee_slices_rejected_for_address_error':3},indent=2))
