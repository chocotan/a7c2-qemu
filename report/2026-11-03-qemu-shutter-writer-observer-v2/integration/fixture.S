/* SPDX-License-Identifier: MIT */
/* Self-owned plumbing; only the 36B/32B/12B instruction anchors are retained. */
.section .text.boot,"ax"
.global _start
_start:
    ldr x9, =0x47fff000
    mov sp, x9
    ldr x16, =dispatch
    mov w0, #0x17c
    mov w1, #1
    mov w2, #0
    mov w3, #3
    mov w4, #10
    mov x5, #0
    blr x16
    ldr x9, =writer_cell
    ldr w10, [x9]
    cmp w10, #1
    b.ne failed
    mov w0, #0x17c
    mov w1, #0
    mov w2, #1
    mov w3, #4
    mov w4, #11
    mov x5, #0
    blr x16
    ldr w10, [x9]
    cbnz w10, failed
    mov w0, #0x17c
    mov w1, #-1
    mov w2, #0
    mov w3, #5
    mov w4, #12
    mov x5, #0
    blr x16
    ldr w10, [x9]
    cmn w10, #1
    b.ne failed
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
passed_text: .asciz "ORIGIN_V2_CPU_READBACK_PASS values=1,0,ffffffff flags=0,1,0\n"
failed_text: .asciz "ORIGIN_V2_CPU_READBACK_FAIL\n"
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
