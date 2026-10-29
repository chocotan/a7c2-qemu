#!/usr/bin/env python3
"""Original installed platform link callback and bounded post-upload controls; no READY producer claim."""
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
 0x2497d0:'adrp x22, #0x45f000',0x2497d8:'add x28, x22, #0xeb8',
 0x2497e0:'add x1, x28, #0x18',0x2497e8:'str x1, [x24, #0x158]',
 0x246768:'ldr x1, [x0, #0x158]',0x24676c:'ldr x1, [x1, #0x18]',
 0x246770:'cbz x1, #0x246788',0x24677c:'blr x1',
 0x246788:'ldr x0, [x0, #8]',0x24678c:'add x0, x0, #0x72c',
 0x249334:'mov w1, #0x1b8',0x249338:'movk w1, #2, lsl #16',
 0x249340:'bl #0x245d60',0x249344:'ubfx x0, x0, #1, #1',
 0x249c08:'mov w1, #0x18',0x249c0c:'movk w1, #2, lsl #16',
 0x249c18:'tbz w2, #0x1d, #0x249c3c',0x249c1c:'and w2, w0, #0xdfffffff',
 0x249c50:'tbz w2, #4, #0x249c68',0x249c54:'and w2, w0, #0xffffffef',
 0x249c98:'orr w2, w0, #2',
 0x248118:'mov w1, #0x78ffff',0x248134:'bl #0x246a20',
 0x248140:'mov w1, #0x4000000',0x248144:'bl #0x246a88',
 0x246a2c:'mov w1, #0x274',0x246a34:'movk w1, #2, lsl #16',
 0x246a4c:'bic w0, w0, w3',0x246a54:'str w0, [x1]',0x246a58:'cbz w2, #0x246a7c',
 0x246a64:'bl #0x245d60',0x246a70:'orr w3, w3, w0',0x246a78:'str w3, [x4]',
 0x246a94:'mov w1, #0x278',0x246a9c:'movk w1, #2, lsl #16',
 0x246ab4:'bic w0, w0, w3',0x246abc:'str w0, [x1]',0x246ac0:'cbz w2, #0x246ae4',
 0x246acc:'bl #0x245d60',0x246ad8:'orr w3, w3, w0',0x246ae0:'str w3, [x4]',
 0x246888:'mov w2, #0x710',0x246894:'and w0, w0, #0xffc0ffff',
 0x2468cc:'add x3, x3, #0xda0',0x2468d4:'adr x3, #0x2468e0',
 0x246938:'orr w4, w0, #0x70000',
 0x246904:'mov w2, #0x80c',0x24690c:'and w4, w0, #0xffffe0ff',
 0x246924:'add x0, x0, #0xda8',0x24692c:'adr x1, #0x246938',
 0x2469a8:'orr w4, w4, #0x400',0x246974:'mov w2, #0x890',0x24697c:'and w4, w0, #0xfffffffe',
 0x2484f0:'mov w4, #1',0x2484f8:'mov w2, #0xb40',0x2484fc:'bl #0x245f20',
 0x248534:'and w3, w3, #0xfffdffff',0x248538:'bl #0x246fa0',
 0x24854c:'orr w3, w3, #0x20000',0x248550:'bl #0x246fa0',
 0x246b68:'mov w1, #0x1ac',0x246b70:'movk w1, #2, lsl #16',
 0x246b80:'and w0, w0, #0xffffff0f',0x246b8c:'orr w0, w0, w2, lsl #4',
 0x246b98:'str w0, [x1]',
 0x249da4:'mov w1, #0x380',0x249db0:'and w2, w0, #0xffffffbf',
 0x249dd0:'mov w2, #0x8bc',0x249dd4:'bl #0x245ea0',0x249dd8:'orr w4, w0, #1',
 0x249df4:'mov w4, #0x104d',0x249df8:'mov x3, #2',0x249dfc:'mov w2, #0',
 0x249e14:'mov w2, w3',0x249e18:'mov w4, #0x911d',
 0x249e30:'mov w2, #0x8bc',0x249e40:'and w4, w0, #0xfffffffe',
 0x249e68:'orr w2, w0, #0x40',
 0x249e80:'bl #0x31ded8',0x249e84:'cmp w0, #0x1ff',
 0x2a2568:'ldr w2, [x0, #4]',0x2a2570:'ldr x1, [x0, #0x1248]',
 0x2a2574:'orr w2, w2, #2',0x2a2578:'add x4, x1, #0xc',0x2a2580:'str w3, [x4]',
 0x2a2584:'mov w2, #-1',0x2a258c:'str w2, [x4]',0x2a2594:'str w3, [x4]',
 0x2a25a8:'mov w1, #0xff0000',0x2a25b0:'str w1, [x2]',0x2a25b8:'str w1, [x2]',
 0x2a25c0:'str wzr, [x1]',0x2a25c8:'str wzr, [x0]',
}
RANGES=((0x249330,0x249350,'20478385e9e67234adad1e74140ca6919f72ada997d48c54ef401d2170ecaa82'),
 (0x246768,0x2467b0,'01040ac1f3803dc20b55b287d840846e094d88d4e1a3e955c0704b822891b412'),
 (0x246a20,0x246a84,'81ff7ae57a7c1ecb98afcdc92af322002e77f892d672860d86c5568cc6165d35'),
 (0x246a88,0x246aec,'4b7f0e0a056e6d22befbe3f6a81fdddad7ca519fee56f911a51d6c1a0e85c311'),
 (0x246b60,0x246bc4,'0de5ef9173a2178b50a2609a1f0e0ffa3884d8a56b6890fa70b2e2a27a67c313'),
 (0x249da0,0x249e90,'6bf737b9ca89f3acbb8dfcf1ef00c6b1854190e02636281829ea6c90f5ea5e5a'))

def main():
 data=KERNEL.read_bytes();assert len(data)==6610952 and hashlib.sha256(data).hexdigest()==SHA
 decoder=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
 for offset,expected in PINS.items():
  ins=list(decoder.disasm(data[offset:offset+4],offset));assert len(ins)==1 and (ins[0].mnemonic+' '+ins[0].op_str).rstrip()==expected,hex(offset)
 for start,end,sha in RANGES:assert hashlib.sha256(data[start:end]).hexdigest()==sha
 assert struct.unpack_from('<Q',data,0x45fed0+0x18)[0]==BASE+0x249330
 assert data[0x45fda0+3]==0x16 and 0x2468e0+0x16*4==0x246938
 assert data[0x45fda8+3]==0x1c and 0x246938+0x1c*4==0x2469a8
 review={'scope':'static post-upload control/link selection only','kernel_sha256':SHA,'pins':len(PINS),'complete_ranges':len(RANGES),
  'original_ops':'0x45fed0','installed_link_callback':'0x249330','platform_link_predicate':'W+201b8 bit1',
  'dbi72c_only_if_link_callback_null':True,'sideband_enables_clear_then_reread_set':{'W+20274':'0x78ffff','W+20278':'0x04000000'},
  'four_lane_control':{'D+710':'(old&~0x3f0000)|0x70000','D+80c':'(old&~0x1f00)|0x400'},
  'core_control_write_contract':'W+201ac (old&~0xf0)|(mode<<4); allowed field bits 0xf0 plus 0x400/0x4',
  'ro_wr_en_sequence':'wrapper W+20380 bit6 clear, then DBI+8bc |=1 (4B RMW); dis: DBI+8bc &=~1 then wrapper bit6 set',
  'vid_did_writes':{'D+0':'0x104d (16-bit)','D+2':'0x911d (16-bit)','helper_245f20_size_arg':'x3=2'},
  'axi_timeout_hook':'weak default -1, cmp 0x1ff skips DBI+8d4 write',
  'notify_callback_2a2538':'domain<=4 gate; record+4 flags|=2; engine writes in order: +c=1,+58=0xffffffff,+2c=1,+ac=0xffffffff,+90=0xff0000,+c4=0xff0000,+54=0,+a8=0; engines ENABLED-but-idle after notify, not zero',
  'sram_init_or_lane_or_link_producer_verified':False,'native_host_or_runtime_verified':False}
 (HERE/'soc0-post-upload-verification.json').write_text(json.dumps(review,indent=2)+'\n')
 print(f'MAIN_PASS {len(PINS)} original pins/{len(RANGES)} ranges/installed ops link callback and four-lane jumps; NO status producer/runtime')

if __name__=='__main__':main()
