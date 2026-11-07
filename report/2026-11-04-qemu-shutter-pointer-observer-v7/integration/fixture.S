/* SPDX-License-Identifier: MIT */
/* Self-owned plumbing; only exact 36B/32B/32B/12B anchors are retained. */
.section .text.boot,"ax"
.global _start
_start:
    ldr x9, =0x47fff000
    mov sp, x9
    adrp x13, descriptor_cell
    add x13, x13, :lo12:descriptor_cell
    adrp x14, pointer_descriptor
    add x14, x14, :lo12:pointer_descriptor
    str x13, [x14, #8]
    adrp x14, pointer_txn
    add x14, x14, :lo12:pointer_txn
    adrp x12, pointer_descriptor
    add x12, x12, :lo12:pointer_descriptor
    str x12, [x14, #8]
    str x12, [x14, #0x58]
    adrp x12, writer_cell
    add x12, x12, :lo12:writer_cell
    str x12, [x14]
    str x12, [x14, #0x50]
    mov w0, #1
    bl pointer_saved_wrapper
    ldr w10, [x13]
    cmp w10, #1
    b.ne failed
    mov w0, #0
    bl pointer_saved_wrapper
    ldr w10, [x13]
    cbnz w10, failed
    mov w0, #-1
    bl pointer_saved_wrapper
    ldr w10, [x13]
    cmn w10, #1
    b.ne failed
    mov w0, #1
    bl pointer_generic_wrapper
    ldr w10, [x13]
    cmp w10, #1
    b.ne failed
    mov w0, #0
    bl pointer_generic_wrapper
    ldr w10, [x13]
    cbnz w10, failed
    mov w0, #-1
    bl pointer_generic_wrapper
    ldr w10, [x13]
    cmn w10, #1
    b.ne failed
    mov w0, #1
    bl pointer_publish_wrapper
    ldr w10, [x13]
    cmp w10, #1
    b.ne failed
    mov w0, #0
    bl pointer_publish_wrapper
    ldr w10, [x13]
    cbnz w10, failed
    mov w0, #-1
    bl pointer_publish_wrapper
    ldr w10, [x13]
    cmn w10, #1
    b.ne failed
    adrp x14, writer_cell
    add x14, x14, :lo12:writer_cell
    str wzr, [x14]
    adrp x16, descriptor_writer
    add x16, x16, :lo12:descriptor_writer
    adrp x13, descriptor_cell
    add x13, x13, :lo12:descriptor_cell
    mov w0, #1
    blr x16
    ldr w10, [x13]
    cmp w10, #1
    b.ne failed
    mov w0, #0
    blr x16
    ldr w10, [x13]
    cbnz w10, failed
    mov w0, #-1
    blr x16
    ldr w10, [x13]
    cmn w10, #1
    b.ne failed
    adrp x13, writer_cell
    add x13, x13, :lo12:writer_cell
    ldr w10, [x13]
    cbnz w10, failed
    adrp x16, record_update
    add x16, x16, :lo12:record_update
    mov x19, #0xa24
    mov x20, #0x1234
    mov x21, #0x89ab
    mov w0, #1
    blr x16
    adrp x13, record_cell
    add x13, x13, :lo12:record_cell
    ldr w10, [x13, #4]
    cmp w10, #1
    b.ne failed
    ldrb w10, [x13, #0x10]
    cmp w10, #1
    b.ne failed
    ldrb w10, [x13, #0x13]
    cmp w10, #1
    b.ne failed
    strb wzr, [x13, #0x10]
    strb wzr, [x13, #0x13]
    mov x21, #0x89ac
    mov w0, #0
    blr x16
    ldr w10, [x13, #4]
    cbnz w10, failed
    ldrb w10, [x13, #0x10]
    cmp w10, #1
    b.ne failed
    ldrb w10, [x13, #0x13]
    cmp w10, #1
    b.ne failed
    strb wzr, [x13, #0x10]
    strb wzr, [x13, #0x13]
    mov x21, #0x89ad
    mov w0, #-1
    blr x16
    ldr w10, [x13, #4]
    cmn w10, #1
    b.ne failed
    ldrb w10, [x13, #0x10]
    cmp w10, #1
    b.ne failed
    ldrb w10, [x13, #0x13]
    cmp w10, #1
    b.ne failed
    ldr x16, =upstream
    mov w0, #0x99
    mov w1, #0x17c
    mov w2, #1
    mov w3, #0
    mov w4, #10
    mov x5, #0
    blr x16
    ldr x9, =writer_cell
    ldr w10, [x9]
    cmp w10, #1
    b.ne failed
    ldr x13, =path_cell
    ldr w10, [x13]
    cbnz w10, failed
    mov w0, #0x9a
    mov w1, #0x17c
    mov w2, #0
    mov w3, #1
    mov w4, #11
    mov x5, #0
    blr x16
    ldr w10, [x9]
    cbnz w10, failed
    ldr w10, [x13]
    cmp w10, #1
    b.ne failed
    mov w0, #0x9b
    mov w1, #0x17c
    mov w2, #-1
    mov w3, #0
    mov w4, #12
    mov x5, #0
    blr x16
    ldr w10, [x9]
    cmn w10, #1
    b.ne failed
    ldr w10, [x13]
    cbnz w10, failed
    ldr x0, =passed_text
    bl puts
    mov x0, #0x20
    ldr x1, =exit_ok
    hlt #0xf000
failed:
    ldr x0, =failed_text
    bl puts
    mov x0, #0x20
    ldr x1, =exit_bad
    hlt #0xf000
1:  wfe
    b 1b
puts:
    ldr x11, =0x09000000
2:  ldrb w10, [x0], #1
    cbz w10, 4f
3:  ldr w12, [x11, #0x18]
    tbnz w12, #5, 3b
    str w10, [x11]
    b 2b
4:  ret
.balign 8
exit_ok: .quad 0x20026, 0
exit_bad: .quad 0x20026, 1
passed_text: .asciz "POINTER_V7_CPU_READBACK_PASS pointer_values=1,0,ffffffff pointer_sites=3 descriptor_values=1,0,ffffffff distinct_current_untouched=1 record_values=1,0,ffffffff record_flags10=1,1,1 record_flags13=1,1,1 upstream_values=1,0,ffffffff selectors=17c\n"
failed_text: .asciz "POINTER_V7_CPU_READBACK_FAIL\n"

pointer_saved_wrapper:
    adrp x19, pointer_saved_input
    add x19, x19, :lo12:pointer_saved_input
    str w0, [x19, #0xa0]
    mov x0, x13
    mov x15, x30
    adrp x16, pointer_saved_anchor
    add x16, x16, :lo12:pointer_saved_anchor
    br x16
pointer_duplicate_wrapper:
    stp x29, x30, [sp, #-0x30]!
    mov x29, sp
    stp x19, x20, [sp, #0x10]
    mov w20, w0
    adrp x19, pointer_txn
    add x19, x19, :lo12:pointer_txn
    adrp x16, pointer_generic_duplicate
    add x16, x16, :lo12:pointer_generic_duplicate
    br x16
pointer_generic_wrapper:
    stp x29, x30, [sp, #-0x30]!
    mov x29, sp
    stp x19, x20, [sp, #0x10]
    mov w20, w0
    adrp x19, pointer_txn
    add x19, x19, :lo12:pointer_txn
    adrp x16, pointer_generic_anchor
    add x16, x16, :lo12:pointer_generic_anchor
    br x16
pointer_publish_wrapper:
    mov x15, x30
    mov w19, w0
    adrp x29, pointer_txn
    add x29, x29, :lo12:pointer_txn
    adrp x16, pointer_publish_anchor
    add x16, x16, :lo12:pointer_publish_anchor
    br x16
.balign 8
pointer_saved_input: .skip 168
pointer_descriptor: .skip 24
pointer_txn: .skip 128

.ltorg

.section .text.dispatch,"ax"
.global dispatch
dispatch:
    .inst 0xa9bc7bfd
    .inst 0x910003fd
    .inst 0xa90153f3
    .inst 0x2a0003f3
    .inst 0xa9025bf5
    .inst 0x2a0103f4
    .inst 0xf9001bf7
    .inst 0xaa0503f5
    .inst 0x35000222
    b self_owned_dispatch
    .org 0x64
    b self_owned_dispatch
self_owned_dispatch:
    mov w0, w19
    mov w1, w20
    bl table_setter
    ldr x23, [sp, #0x30]
    ldp x19, x20, [sp, #0x10]
    ldp x21, x22, [sp, #0x20]
    ldp x29, x30, [sp], #0x40
    ret

.section .text.upstream,"ax"
.global upstream
upstream:
    .inst 0xa9bb7bfd
    .inst 0x72001c7f
    .inst 0x910003fd
    .inst 0xa9025bf5
    .inst 0x2a0103f5
    .inst 0xa90153f3
    .inst 0x2a0203e1
    .inst 0x54000300
    b self_owned_upstream
    .org 0x7c
    b self_owned_upstream
self_owned_upstream:
    mov w0, w21
    tst w3, #0xff
    cset w2, ne
    adrp x10, path_cell
    add x10, x10, :lo12:path_cell
    str w2, [x10]
    mov x5, x4
    bl dispatch
    ldp x19, x20, [sp, #0x10]
    ldp x21, x22, [sp, #0x20]
    ldp x29, x30, [sp], #0x50
    ret

.section .text.table,"ax"
.global table_setter
table_setter:
    .inst 0x93407c00
    .inst 0xd2800603
    .inst 0xb0016642
    .inst 0x9130e042
    .inst 0x9b030800
    .inst 0xf9400c02
    .inst 0x2a0103e0
    .inst 0xd61f0040

.section .text.writer,"ax"
.global writer
writer:
    .inst 0xd002b7a1
    .inst 0xb9057020
    .inst 0xd65f03c0

.section .data.slot,"aw"
.global self_owned_slot
self_owned_slot: .quad writer

.section .bss.writer,"aw",%nobits
.balign 4
.global writer_cell
writer_cell: .skip 4
.global path_cell
path_cell: .skip 4
.global descriptor_cell
descriptor_cell: .skip 4

.section .text.record,"ax"
.global record_return
record_return:
    ret
    .org 0x20
.global record_update
record_update:
    .inst 0xd2800302
    .inst 0x9002ce21
    .inst 0x91034021
    .inst 0x9b020661
    .inst 0xb9000420
    .inst 0x52800020
    .inst 0x39004020
    .inst 0x39004c20
    .inst 0x17fffff0

.section .bss.record,"aw",%nobits
.global record_cell
record_cell: .skip 24

.section .text.descriptor,"ax"
.global descriptor_writer
descriptor_writer:
    .inst 0xd002b7a1
    .inst 0xb9057820
    .inst 0xd65f03c0

.section .text.pointer_saved,"ax"
.global pointer_saved_anchor
pointer_saved_anchor:
    .inst 0xb940a261
    .inst 0xb9000001
    .inst 0x97f6eff2
    mov x30, x15
    ret
.section .text.pointer_stub,"ax"
    ret

.section .text.pointer_generic,"ax"
.global pointer_generic_anchor
pointer_generic_anchor:
    .inst 0x94401e77
    .inst 0xf9400660
    .inst 0xf9400400
    .inst 0xb9000014
    .inst 0x52800020
    .inst 0x39005660
    .inst 0xf9400260
    .inst 0xb9000014
    .inst 0x52800020
    .inst 0x39005260
    .inst 0xaa1303e0
    .inst 0xa94153f3
    .inst 0xa8c37bfd
    .inst 0xd65f03c0

.section .text.pointer_publish,"ax"
.global pointer_publish_anchor
pointer_publish_anchor:
    .inst 0x942e4c34
    .inst 0xf9402fa0
    .inst 0xf9400400
    .inst 0xb9000013
    .inst 0x52800020
    .inst 0x390197a0
    .inst 0xf9402ba0
    .inst 0xb9000013
    .inst 0x52800020
    .inst 0x390193a0
    .inst 0x910143a0
    .inst 0x97e9a9b7
    mov x30, x15
    ret

.section .text.pointer_generic_stub,"ax"
    ret
.section .text.pointer_publish_stub,"ax"
    ret
.section .text.pointer_generic_duplicate,"ax"
.global pointer_generic_duplicate
pointer_generic_duplicate:
    .inst 0xf9400660
    .inst 0xf9400400
    .inst 0xb9000014
    .inst 0x52800020
    .inst 0x39005660
    .inst 0xf9400260
    .inst 0xb9000014
    .inst 0x52800020
    .inst 0x39005260
    .inst 0xaa1303e0
    .inst 0xa94153f3
    .inst 0xa8c37bfd
    .inst 0xd65f03c0
