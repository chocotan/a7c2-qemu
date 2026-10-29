#!/usr/bin/env python3
"""Original pcidma submit path pins: transfer_async validation, start dequeue, dma_start engine writes."""
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
 # pcidma_transfer_async 2a20c8: request validation
 0x2a20e8:'ldrb w22, [x0]',0x2a20f0:'cmp w22, #4',0x2a20f4:'b.hi #0x2a220c',
 0x2a20f8:'ldrb w24, [x20, #1]',0x2a20fc:'cmp w24, #7',
 0x2a2104:'ldr x2, [x20, #0x18]',0x2a2108:'cbz x2, #0x2a220c',
 0x2a210c:'ldr w2, [x20, #4]',0x2a2110:'cbnz w2, #0x2a2120',
 0x2a2114:'ldr x2, [x20, #8]',0x2a2118:'tst x2, #7',0x2a211c:'b.ne #0x2a220c',
 0x2a2164:'strh wzr, [x20, #0x3a]',0x2a2168:'strh w0, [x20, #0x38]',
 0x2a21cc:'stp x19, x5, [x20, #0x28]',0x2a21f8:'bl #0x2a1ff0',
 # pcidma_start 2a1ff0: cur/state/ready gates, LIST_POISON dequeue, dir dispatch
 0x2a1ff0:'ldr x1, [x0, #0x30]',0x2a1ff4:'cbz x1, #0x2a2000',
 0x2a2000:'ldr w1, [x0, #0x14]',0x2a2004:'cbz w1, #0x2a1ff8',
 0x2a202c:'movk x6, #0xdead, lsl #48',0x2a2030:'movk x5, #0xdead, lsl #48',
 0x2a2034:'sub x2, x1, #0x28',0x2a2048:'str x2, [x0, #0x30]',0x2a2054:'str w1, [x0, #0x40]',
 0x2a2074:'ldrb w0, [x2, #2]',0x2a2078:'cmp w0, #1',
 0x2a2080:'add x1, x19, #0x1c0',0x2a2098:'add x1, x19, #0x1a8',
 0x2a2088:'bl #0x2a1e80',0x2a20a0:'bl #0x2a1e80',
 # dma_start 2a1e80: engine write sequence for direct mode
 0x2a1e88:'mov w0, #1',0x2a1e90:'ldr x3, [x1]',0x2a1e98:'str w0, [x3]',
 0x2a1ea4:'ldr w5, [x4, #4]',0x2a1ea8:'cbz w5, #0x2a1f50',
 0x2a1eb0:'ldr x0, [x1, #8]',0x2a1eb8:'add x6, x0, #8',0x2a1ebc:'str w5, [x6]',
 0x2a1ec0:'mov w5, #8',0x2a1ec4:'str w5, [x0]',
 0x2a1ecc:'ldr x5, [x4, #8]',0x2a1ed0:'str w5, [x6]',0x2a1ed4:'lsr x5, x5, #0x20',
 0x2a1ed8:'add x6, x0, #0x10',0x2a1edc:'str w5, [x6]',
 0x2a1ee0:'add x5, x0, #0x14',0x2a1ee4:'ldr x4, [x4, #0x10]',0x2a1ee8:'str w4, [x5]',
 0x2a1ef0:'add x0, x0, #0x18',0x2a1ef4:'str w4, [x0]',
 0x2a1efc:'ldr w0, [x2]',0x2a1f00:'ldr x1, [x1, #0x10]',0x2a1f04:'str w0, [x1]',
 0x2a1f40:'dmb oshst',
 # LL mode: LLP from src, CTRL1 = LLE|CCS = 0x300
 0x2a1f5c:'add x4, x5, #0x1c',0x2a1f60:'str w0, [x4]',
 0x2a1f68:'add x4, x5, #0x20',0x2a1f6c:'str w0, [x4]',
 0x2a1f70:'mov w0, #0x300',0x2a1f74:'str w0, [x5]',
}

def main():
 data=KERNEL.read_bytes();assert len(data)==6610952 and hashlib.sha256(data).hexdigest()==SHA
 decoder=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
 for offset,expected in PINS.items():
  ins=list(decoder.disasm(data[offset:offset+4],offset))
  assert len(ins)==1 and (ins[0].mnemonic+' '+ins[0].op_str).rstrip()==expected,hex(offset)
 review={'scope':'static original submit-path pins; no runtime transfer proof','kernel_sha256':SHA,'pins':len(PINS),
  'validation':{'controller_max':4,'channel_max':7,'callback_nonnull':True,'lli_src_8byte_aligned_when_len0':True,
   'metadata_written':'req+0x38/0x3a','driver_links':'req+0x28..0x37','returns':'0 accepted / -22 rejected'},
  'start_gates':{'cur_null_dequeues':True,'chan_state_required':True,'chan_ready_required_ER9001359142':True,
   'dequeue_writes_LIST_POISON':True,'queue_count_at_chan_record_0x40':True},
  'direct_engine_writes_in_order':['PWR(0x128+4ch)=1','SIZE=req.len','CTRL1=8(LIE)','SRC_L','SRC_H','DST_L','DST_H','doorbell(+0x10 wr / +0x30 rd)=channel_id'],
  'll_engine_writes':['LLP_L(ctl+0x1c)=src.low','LLP_H(ctl+0x20)=src.high','CTRL1=0x300(LLE|CCS)'],
  'channel_block':'engine+0x200+ch*0x200(+0x100 read dir)','runtime_verified':False}
 (HERE/'pcidma-submit-verification.json').write_text(json.dumps(review,indent=2)+'\n')
 print(f'MAIN_PASS {len(PINS)} original pins: transfer_async validation + start gates + dma_start engine writes; NO runtime claim')

if __name__=='__main__':main()
