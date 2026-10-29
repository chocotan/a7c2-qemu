#!/usr/bin/env python3
"""Pin the real SoC Root Port sysdata cast; do not admit the opaque prototype."""
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN

HERE=Path(__file__).resolve().parent
KERNEL=HERE.parents[2]/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
BASE=0xffffff8008080000
SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
PINS={
    0x2436f8:'ldr x1, [x0, #0x38]',0x2436fc:'cbz x1, #0x243710',
    0x243710:'ldr x1, [x0, #0x10]',0x243714:'cbnz x1, #0x243700',
    0x243720:'ldr x1, [x0, #0x120]',0x243724:'ldr x0, [x1, #0x238]',
    0x243728:'cbz x0, #0x243738',0x243738:'ldr x1, [x1]',
    0x24373c:'cbz x1, #0x243730',0x243740:'ldr x0, [x1, #0x238]',
    0x243798:'ldr x1, [x0, #0x360]',0x24379c:'cbz x1, #0x243848',
    0x243848:'mov x0, #0',0x24384c:'ret',0x2261c0:'ret',
    0x239db0:'add x19, x19, #0x18',0x239dbc:'ldp w1, w3, [x19, #4]',
    0x239dc0:'ldr w0, [x20, #0x44]',0x239dc4:'lsr w0, w0, w3',
    0x239dd4:'ldrh w0, [x19]',0x239dd8:'ldrh w1, [x20, #0x3c]',
    0x239de8:'ldrh w0, [x19, #2]',0x239dec:'ldrh w1, [x20, #0x3e]',
    0x239e04:'ldr x1, [x19, #0x10]',0x239e0c:'blr x1',
    0x249578:'ldrh w1, [x0, #0x52]',0x24957c:'ubfx x1, x1, #4, #4',
    0x249580:'cmp w1, #4',0x249584:'b.eq #0x249590',0x249588:'ret',
    0x2495b0:'ldr x0, [x0, #0x10]',0x2495b4:'ldr x22, [x0, #0xd0]',
    0x2495bc:'sub x20, x22, #0x20',0x2495c4:'bl #0x245d60',
    0x2495c8:'and w2, w0, #0xffffffbf',0x2495d8:'bl #0x245d78',
    0x2495dc:'ldur x1, [x22, #-0x18]',0x2495e8:'mov w2, #0x8bc',
    0x2495ec:'bl #0x245ea0',0x2495f0:'orr w4, w0, #1',
    0x249604:'bl #0x245f20',0x249614:'orr w21, w21, #0x100',
    0x249624:'strh w21, [x19, #0x52]',0x249684:'and w4, w0, #0xfffffffe',
    0x2496ac:'orr w2, w0, #0x40',0x2496c4:'bl #0x31deb0',
    0x2496dc:'bl #0x22d290',0x2312c8:'bl #0x27e2a8',
    0x231388:'bl #0x231288',0x231394:'ldr w2, [x1, #0xe4]',
    0x2313a0:'ldrb w1, [x1, #0xe0]',0x2313ac:'ldr w1, [x0, #0x38]',
}


def main():
    data=KERNEL.read_bytes();assert len(data)==6610952 and hashlib.sha256(data).hexdigest()==SHA
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    for offset,expected in PINS.items():
        i=list(decoder.disasm(data[offset:offset+4],offset))
        assert len(i)==1 and (i[0].mnemonic+' '+i[0].op_str).rstrip()==expected,hex(offset)
    vendor,device,cl,shift,hook=struct.unpack_from('<HHII4xQ',data,0x573fb8)
    assert (vendor,device,cl,shift,hook)==(0xffff,0xffff,0xffffffff,0,BASE+0x249578)
    jump=int.from_bytes(data[0x45f3d8:0x45f3d9],'little',signed=True)
    assert 0x239e78+jump*4==0x239e78
    assert 0x573cb8<=0x573fb8<0x573fd0 and (0x573fb8-0x573cb8)%24==0
    result={'kernel_sha256':SHA,'instruction_pins':len(PINS),
       'root_of_msi_null_node_subpaths_verified':True,
       'wildcard_early_fixup':'0x573fb8 -> 0x249578',
       'trigger_pcie_type':4,'reads_bus_sysdata':True,'ctrl_from_sysdata_delta':-32,
       'wrapper_pointer_offset_in_ctrl':0x160,'dbi_pointer_offset_in_ctrl':8,
       'opaque_adapter_gate':'BLOCKED: root port wildcard fixup needs actual compatible context/MMIO',
       'global_context_safety_verified':False,'runtime_verified':False}
    (HERE/'rootport-quirk-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(f'PASS original Image SHA, {len(PINS)} pins, wildcard early table and Root Port cast')
    print('OPAQUE ADAPTER BLOCKED: normal PCI core reaches SoC DW-context/MMIO fixup during scan')


if __name__=='__main__':main()
