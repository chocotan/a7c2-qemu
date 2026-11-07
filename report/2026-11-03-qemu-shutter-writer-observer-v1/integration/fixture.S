/* SPDX-License-Identifier: MIT */
/* Self-owned API fixture; three retained instructions are a bounded test anchor. */
.section .text.boot,"ax"
.global _start
_start:
    ldr x9, =0x47fff000
    mov sp, x9
    mov x0, #1
    ldr x16, =writer
    blr x16
    ldr x9, =writer_cell
    ldr w10, [x9]
    cmp w10, #1
    b.ne failed
    mov x0, #0
    blr x16
    ldr w10, [x9]
    cbnz w10, failed
    mov w0, #-1
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
passed_text: .asciz "WRITER_CPU_READBACK_PASS values=1,0,ffffffff\n"
failed_text: .asciz "WRITER_CPU_READBACK_FAIL\n"
.ltorg

.section .text.writer,"ax"
.global writer
writer:
    .inst 0xd002b7a1
    .inst 0xb9057020
    .inst 0xd65f03c0

.section .bss.writer,"aw",%nobits
.balign 4
.global writer_cell
writer_cell:
    .skip 4
