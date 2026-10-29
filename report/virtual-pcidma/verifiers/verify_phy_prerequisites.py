#!/usr/bin/env python3
"""Original PHY-name tables and bounded status/control predicates; no PHY emulation claim."""
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN

HERE=Path(__file__).resolve().parent
KERNEL=HERE.parents[2]/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
BASE=0xffffff8008080000
SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
RESETS=('rst_pwrup','rst_button','rst_pe','rst_apb','rst_axi2avb_pci','rst_axi2avb_pci_i0')
CLOCKS=('apb_pclk','dbi_aclk','slv_aclk','mstr_aclk','aux_clk','axi2avb_pcie0','axi2avb_pcie1')
PINS={
    0x245d60:'ldr x0, [x0, #0x160]',0x245d64:'add x0, x0, w1, uxtw',
    0x245d68:'ldr w0, [x0]',0x245d6c:'dsb ld',
    0x248638:'mov w1, #0x380',0x248640:'movk w1, #2, lsl #16',
    0x248644:'bl #0x245d60',0x248648:'and w0, w0, #0xfffffffe',
    0x24864c:'cmp w20, #0',0x248650:'orr w2, w0, #1',
    0x248654:'csel w2, w2, w0, eq',0x248664:'bl #0x245d78',
    0x2469c4:'mov w1, #0x1ac',0x2469cc:'movk w1, #2, lsl #16',
    0x2469e4:'and w0, w0, #0xfffffffb',0x2469f0:'cbz w4, #0x246a14',
    0x246a08:'orr w0, w0, #4',0x246a10:'str w0, [x2]',
    0x246ccc:'mov w1, #0x380',0x246cd4:'movk w1, #2, lsl #16',
    0x246ce4:'orr w0, w0, #0x1f0000',0x246cf0:'str w0, [x1]',
    0x246cf4:'mov w1, #0x38c',0x246cfc:'movk w1, #2, lsl #16',
    0x246d00:'bl #0x245d60',0x246d04:'cmp w3, #2',
    0x246d08:'b.eq #0x246d60',0x246d0c:'cmp w3, #4',
    0x246d10:'b.eq #0x246d30',0x246d14:'cmp w3, #1',
    0x246d18:'and w0, w0, #1',0x246d1c:'b.eq #0x246d34',
    0x246d20:'mov w0, #-0x16',0x246d30:'and w0, w0, #0xf',
    0x246d34:'cbnz w0, #0x246d50',0x246d38:'mov w1, #1',
    0x246d44:'str w1, [x2]',0x246d54:'str wzr, [x2]',
    0x246d60:'and w0, w0, #3',
    0x249b44:'mov w19, #0xc8',0x249b54:'b.eq #0x24a170',
    0x249b5c:'bl #0x1efb88',0x249b68:'bl #0x245d60',
    0x249b6c:'tbz w0, #2, #0x249b50',0x249b70:'mov x0, #-0x10',
    0x249b7c:'mov w28, #0x18000',0x249b80:'add x27, x0, w27, uxtw #4',
    0x249ba8:'add w28, w28, #4',0x249bac:'ldrh w2, [x0, w27, sxtw #1]',
    0x249bb8:'bl #0x245d78',0x249be8:'orr w2, w0, #2',
    0x249c1c:'and w2, w0, #0xdfffffff',0x249c54:'and w2, w0, #0xffffffef',
    0x249d30:'mov w19, #0xc8',0x249d34:'bl #0x7b850',
    0x249d44:'bl #0x246cc0',0x249d50:'bl #0x7b850',
    0x249d60:'bl #0x246cc0',0x249d64:'subs w19, w19, #1',
    0x249d68:'b.eq #0x24a0fc',0x249d74:'cbz w1, #0x249d50',
    0x24a0fc:'ldr w0, [x29, #0x6c]',0x24a100:'cbnz w0, #0x249d78',
}


def main():
    data=KERNEL.read_bytes();assert len(data)==6610952 and hashlib.sha256(data).hexdigest()==SHA
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    for offset,expected in PINS.items():
        ins=list(decoder.disasm(data[offset:offset+4],offset))
        assert len(ins)==1 and (ins[0].mnemonic+' '+ins[0].op_str).rstrip()==expected,hex(offset)
    for start,expected in ((0x45ff00,RESETS),(0x45ff30,CLOCKS)):
        actual=[]
        for i in range(len(expected)):
            ptr=struct.unpack_from('<Q',data,start+8*i)[0]-BASE
            assert 0<=ptr<len(data)
            actual.append(data[ptr:data.index(0,ptr)].decode('ascii'))
        assert tuple(actual)==expected
    result={'scope':'original static names/control/status subset, not complete PHY or runtime initialization',
            'kernel_sha256':SHA,'pins':len(PINS),'reset_table':list(RESETS),'clock_table':list(CLOCKS),
            'ready_helper':'0x246cc0','status_offset':'0x2038c',
            'input_masks':{'1':1,'2':3,'4':15},'output_one_iff_masked_status_zero':True,
            'invalid_input_returns':-22,'probe_checks_final_ready_after_counter_exhaustion':True,
            'full_reset_clock_order_verified':False,'runtime_verified':False}
    (HERE/'phy-prerequisites-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(f'PASS original SHA, {len(PINS)} instruction pins, six reset/seven clock table names')
    print('PASS bounded wrapper controls, SRAM loop/upload, PHY status-zero predicate and final-probe recheck')
    print('PARTIAL CONTRACT: full PHY/clock/reset/timing and runtime remain UNVERIFIED')


if __name__=='__main__':main()
