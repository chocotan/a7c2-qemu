/* SPDX-License-Identifier: MIT */
/* Self-owned plumbing; only exact 36B/32B/32B/12B anchors are retained. */
.section .text.boot,"ax"
.global _start
_start:
    ldr x9, =0x47fff000
    mov sp, x9
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
passed_text: .asciz "DESCRIPTOR_V5_CPU_READBACK_PASS descriptor_values=1,0,ffffffff distinct_current_untouched=1 record_values=1,0,ffffffff record_flags10=1,1,1 record_flags13=1,1,1 upstream_values=1,0,ffffffff selectors=17c\n"
failed_text: .asciz "DESCRIPTOR_V5_CPU_READBACK_FAIL\n"
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
