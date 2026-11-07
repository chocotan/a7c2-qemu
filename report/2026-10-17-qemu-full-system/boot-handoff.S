/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Generic-virt GIC routing contract before the unmodified Sony kernel.
 * x0..x3 are preserved. No stack, kernel patch, IPC or application state change.
 */
.text
.global _start
_start:
    movz x16, #0x0800, lsl #16
    ldr w17, [x16, #4]       /* GICD_TYPER interrupt count */
    and w17, w17, #31
    add w17, w17, #1
    lsl w17, w17, #5
    sub w17, w17, #32
    add x16, x16, #0x820     /* ITARGETSR: first SPI (32) */
    mov w18, #1              /* Generic board peripherals to CPU0 */
    cbz w17, 2f
1:
    strb w18, [x16], #1
    subs w17, w17, #1
    b.ne 1b
2:
    movz x16, #0x0800, lsl #16
    add x16, x16, #0x8e8     /* Sony hwtimer0..3: IRQ232..235 */
    movz w17, #0x0201
    movk w17, #0x0804, lsl #16
    str w17, [x16]           /* Channel i uses CPU i */
    dsb sy
    isb
    ldr x16, 3f
    br x16
.balign 8
3:
    .quad 0x400080000        /* Original Image entry, unchanged */
