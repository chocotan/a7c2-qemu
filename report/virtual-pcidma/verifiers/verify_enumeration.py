#!/usr/bin/env python3
"""Pinned original PCI config paths and public DT resources; offline only."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

HERE = Path(__file__).resolve().parent
UNPACKED = HERE.parents[2]/'runtime/analysis/unpacked/firmware.tar_unpacked'
KERNEL = UNPACKED/'0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
DTB = UNPACKED/'0800_appli/setting/cxd90057.dtb'
BASE = 0xffffff8008080000
KERNEL_SHA = '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
DTB_SHA = 'c5735ad9c6da8c48fb24eeee0bb743d07c486a47d5db19bef13b5eaea24ad280'
WINDOWS = ((0x245f78,0x2461d8), (0x246768,0x2467b0),
           (0x2474b0,0x247878), (0x247ae0,0x247b20),
           (0x247bb8,0x247c00), (0x247f10,0x247f40),
           (0x24a6d0,0x24a720), (0x31c780,0x31c7a0),
           (0x2a3a50,0x2a3a90))
PINS = {
    0x245fc0:'cbnz w0, #0x2460e0', 0x245fd4:'mov w2, #0x900',
    0x245fec:'mov w2, #0x90c', 0x246004:'mov w2, #0x910',
    0x246020:'mov w2, #0x914', 0x24603c:'mov w2, #0x918',
    0x246050:'mov w2, #0x91c', 0x24606c:'mov w2, #0x904',
    0x24607c:'mov w4, #-0x80000000', 0x246084:'mov w2, #0x908',
    0x2460a0:'tbnz w0, #0x1f, #0x2460c8',
    0x2460ec:'lsl w21, w21, #9', 0x2460f4:'orr w21, w21, #0x300000',
    0x2460fc:'add w2, w21, #8', 0x246110:'add w2, w21, #0xc',
    0x246130:'add w2, w21, #0x10', 0x246150:'add w2, w21, #0x14',
    0x246164:'add w2, w21, #0x18', 0x246180:'mov w2, w21',
    0x24619c:'mov w4, #-0x80000000',
    0x2461bc:'tbnz w0, #0x1f, #0x2460c8',
    0x246770:'cbz x1, #0x246788', 0x24677c:'blr x1',
    0x24678c:'add x0, x0, #0x72c', 0x246790:'ldr w0, [x0]',
    0x246798:'mov w1, #0x10', 0x24679c:'movk w1, #0x2000, lsl #16',
    0x2467a0:'and w0, w0, w1', 0x2467a4:'cmp w0, #0x10',
    0x2474e0:'bl #0x246768', 0x2474e4:'cbz w0, #0x2474fc',
    0x247558:'bl #0x2474b0', 0x247588:'cmp w1, w0',
    0x24758c:'b.eq #0x247670', 0x2475ec:'ubfiz w21, w21, #0x13, #5',
    0x2475f4:'ubfiz w4, w22, #0x10, #3', 0x247604:'orr w4, w4, w0, lsl #24',
    0x24760c:'b.eq #0x247690', 0x247614:'mov w2, #5',
    0x247628:'mov w1, #1', 0x24762c:'bl #0x245f78',
    0x24763c:'bl #0x245dc8', 0x247680:'bl #0x246fa0',
    0x247690:'mov w2, #4', 0x247694:'ldr w5, [x20, #0x38]',
    0x247698:'ldp x3, x19, [x20, #0x28]',
    0x2476e8:'bl #0x2474b0', 0x247784:'ubfiz w21, w21, #0x13, #5',
    0x24778c:'ubfiz w4, w22, #0x10, #3', 0x24779c:'orr w4, w4, w0, lsl #24',
    0x2477a4:'b.eq #0x247858', 0x2477ac:'mov w2, #5',
    0x2477c0:'mov w1, #1', 0x2477c4:'bl #0x245f78',
    0x2477cc:'bl #0x24a6d0', 0x2477dc:'bl #0x245d90',
    0x247828:'bl #0x246f58', 0x24783c:'bl #0x24a6f8',
    0x247858:'mov w2, #4', 0x24785c:'ldr w5, [x20, #0x38]',
    0x247af4:'lsr x1, x1, #1', 0x247b08:'lsr x2, x2, #1',
    0x247bd0:'lsr x1, x1, #1', 0x247be4:'lsr x2, x2, #1',
    0x247f28:'mov x3, x20', 0x247f38:'bl #0x229060',
    0x24a6dc:'mov w2, #0x104', 0x24a6e8:'bl #0x245f20',
    0x24a700:'mov w2, #0x104', 0x24a718:'bl #0x245ea0',
    0x31c788:'adrp x1, #0x640000', 0x31c78c:'add x1, x1, #0xec8',
    0x31c790:'ldr w0, [x1, w0, sxtw #2]',
    0x2a3a64:'bl #0x31c780', 0x2a3a68:'cmp w0, #3',
    0x2a3a6c:'cset w1, eq', 0x2a3a7c:'b.eq #0x2a3a90',
}
PORTS = (('pcie_i',0xf7000000,0xdffc0000,0xf11c0000),
         ('pcie_m0',0xf6800000,0xc8010000,0xf1140000),
         ('pcie_m1',0xf6c00000,0xd0010000,0xf1180000),
         ('pcie_c',0xf7400000,0xe0000000,0xf1200000),
         ('pcie_n',0xf6400000,0xc0000000,0xf1100000))


def fdt_nodes(data):
    h=struct.unpack_from('>10I',data)
    assert h[0]==0xd00dfeed and h[1]==len(data)
    names=data[h[3]:h[3]+h[8]]
    position=h[2]; end=position+h[9]; stack=[]; nodes={}
    while position<end:
        token=struct.unpack_from('>I',data,position)[0]; position+=4
        if token==1:
            zero=data.index(0,position,end); stack.append(data[position:zero].decode('ascii'))
            position=(zero+4)&~3; nodes['/'.join(stack)]={}
        elif token==2:
            stack.pop()
        elif token==3:
            size,offset=struct.unpack_from('>II',data,position); position+=8
            assert stack and position+size<=end
            name=names[offset:names.index(0,offset)].decode('ascii')
            nodes['/'.join(stack)][name]=data[position:position+size]; position=(position+size+3)&~3
        elif token==4:
            pass
        elif token==9:
            assert not stack
            return nodes
        else:
            raise ValueError('Unknown FDT token')
    raise ValueError('Missing FDT end')


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--capture',action='store_true')
    args=parser.parse_args(); image=KERNEL.read_bytes(); dtb=DTB.read_bytes()
    assert len(image)==6610952 and hashlib.sha256(image).hexdigest()==KERNEL_SHA
    assert len(dtb)==16875 and hashlib.sha256(dtb).hexdigest()==DTB_SHA
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN); instructions={}; windows=[]
    for lo,hi in WINDOWS:
        raw=image[lo:hi]; ins=list(decoder.disasm(raw,lo)); assert sum(i.size for i in ins)==hi-lo
        instructions.update((i.address,i) for i in ins)
        windows.append({'start':hex(lo),'end':hex(hi),'sha256':hashlib.sha256(raw).hexdigest()})
    for offset,expected in PINS.items():
        i=instructions[offset]; assert (i.mnemonic+' '+i.op_str).rstrip()==expected,(hex(offset),i.op_str)
    assert struct.unpack_from('<5Q',image,0x628588)==(0,0,0,BASE+0x2476a8,BASE+0x247518)
    assert struct.unpack_from('<5I',image,0x640ec8)==(1,1,1,1,1)
    nodes=fdt_nodes(dtb); resources=[]
    for domain,(name,dbi,cfg,wrapper) in enumerate(PORTS):
        props=nodes['/soc/'+name]
        assert props['compatible']==b'snps,dw-pcie\0' and props['status']==b'disabled\0'
        assert props['reg-names']==b'ctrlreg\0config\0phy_reg\0'
        assert struct.unpack('>I',props['linux,pci-domain'])==(domain,)
        assert struct.unpack('>6Q',props['reg'])==(dbi,0x380000,cfg,0x20000,wrapper,0x40000)
        assert nodes['/soc/'+name+'_ep']['status']==b'disabled\0'
        assert struct.unpack_from('<3Q',image,0x62ed00+domain*0x13b0+0x1240)==(
            0xffffffff00000000|dbi,0xffffffff00000000|(dbi+0x380000),0xffffffff00000000|wrapper)
        resources.append({'domain':domain,'name':name,'dbi':hex(dbi),'type0_window':hex(cfg),
                          'type1_window':hex(cfg+0x10000),'wrapper':hex(wrapper),'status':'disabled'})
    assert ((1<<24)|(0<<19)|(0<<16))==0x01000000
    result={'kernel_sha256':KERNEL_SHA,'dtb_sha256':DTB_SHA,'windows':windows,
            'instruction_pins':len(PINS),'resources':resources,'initial_aspm_policy':[1]*5,
            'type0':4,'type1':5,'outbound_region':1,'runtime_verified':False}
    path=HERE/'enumeration-raw.json'
    if args.capture:path.write_text(json.dumps(result,indent=2)+'\n')
    else:assert json.loads(path.read_text())==result
    print(f'PASS original Image/DTB SHA, {len(PINS)} instruction pins, five DT/kernel resource tuples')
    print('PASS config read/write ops, Type0/1 region1, BDF target, link/error checks, initial ASPM policy/node status')
    print('STATIC ONLY: no current kernel PCI enumeration, downstream endpoint identity, role enable or CP proof')


if __name__=='__main__':main()
