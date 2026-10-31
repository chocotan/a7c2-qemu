/* SPDX-License-Identifier: MIT */
/* Synthetic bare-metal program; the marked anchors are inherited byte patterns. */
#ifndef FIXTURE_PRODUCER
#define FIXTURE_PRODUCER 0
#endif
#ifndef FIXTURE_PRODUCER_MUTATED
#define FIXTURE_PRODUCER_MUTATED 0
#endif
#if FIXTURE_PRODUCER
#define FIXTURE_RECORD_BYTES 432
#else
#define FIXTURE_RECORD_BYTES 408
#endif
#ifndef FIXTURE_MUTATED
#define FIXTURE_MUTATED 0
#endif
#ifndef FIXTURE_WRONG_LR_ONLY
#define FIXTURE_WRONG_LR_ONLY 0
#endif

.macro ADDRESS reg, symbol
    adrp \reg, \symbol
    add \reg, \reg, :lo12:\symbol
.endm

.macro U64 reg, value
    movz \reg, #(\value & 0xffff)
    movk \reg, #((\value >> 16) & 0xffff), lsl #16
    movk \reg, #((\value >> 32) & 0xffff), lsl #32
    movk \reg, #((\value >> 48) & 0xffff), lsl #48
.endm

/* x16 always points to actual_record; capture before using scratch registers. */
.macro SNAPSHOT
    stp x0, x1, [x16, #0]
    stp x2, x3, [x16, #16]
    stp x4, x5, [x16, #32]
    stp x6, x7, [x16, #48]
    stp x8, x9, [x16, #64]
    stp x10, x11, [x16, #80]
    stp x12, x13, [x16, #96]
    stp x14, x15, [x16, #112]
    stp x16, x17, [x16, #128]
    stp x18, x19, [x16, #144]
    stp x20, x21, [x16, #160]
    stp x22, x23, [x16, #176]
    stp x24, x25, [x16, #192]
    stp x26, x27, [x16, #208]
    stp x28, x29, [x16, #224]
    str x30, [x16, #240]
    mov x9, sp
    str x9, [x16, #248]
    mrs x9, nzcv
    str x9, [x16, #256]
    sub x9, sp, #128
    add x10, x16, #264
    mov x11, #18
.Lsnapshot_stack_\@:
    ldr x12, [x9], #8
    str x12, [x10], #8
    sub x11, x11, #1
    cbnz x11, .Lsnapshot_stack_\@
.endm

.macro RESTORE_INPUT
    ldr x9, [x16, #256]
    msr nzcv, x9
    ldp x0, x1, [x16, #0]
    ldp x2, x3, [x16, #16]
    ldp x4, x5, [x16, #32]
    ldp x6, x7, [x16, #48]
    ldp x8, x9, [x16, #64]
    ldp x10, x11, [x16, #80]
    ldp x12, x13, [x16, #96]
    ldp x14, x15, [x16, #112]
    ldp x16, x17, [x16, #128]
    ldp x18, x19, [x16, #144]
    ldp x20, x21, [x16, #160]
    ldp x22, x23, [x16, #176]
    ldp x24, x25, [x16, #192]
    ldp x26, x27, [x16, #208]
    ldp x28, x29, [x16, #224]
    ldr x30, [x16, #240]
.endm

#if FIXTURE_PRODUCER
/* The A35's unchanged EL1h PSTATE is sampled without changing exception level. */
.macro PRODUCER_SNAPSHOT
    SNAPSHOT
    mrs x9, daif
    mrs x10, CurrentEL
    orr x9, x9, x10
    mrs x10, spsel
    orr x9, x9, x10
    mrs x10, nzcv
    orr x9, x9, x10
    str x9, [x16, #408]
    mrs x9, ttbr0_el1
    str x9, [x16, #416]
    mrs x9, tpidr_el0
    str x9, [x16, #424]
.endm
#endif

.section .text.boot, "ax", %progbits
.balign 4
.global _start
.type _start, %function
_start:
    msr daifset, #15
    msr spsel, #1
    ADDRESS x9, __stack_top
    mov sp, x9
    mrs x9, CurrentEL
    cmp x9, #4
    b.ne fixture_failure
    mrs x9, sctlr_el1
    tbnz x9, #0, fixture_failure
    mov x0, #4
    ADDRESS x1, console_header
    hlt #0xf000
#if FIXTURE_PRODUCER
    b producer_prepare
#endif

prepare_call:
    /* Prime the entire 112-byte future frame plus 16-byte guards on each side. */
    sub x9, sp, #128
    U64 x10, 0x6677889900000000
    mov x11, #18
.Lprime:
    str x10, [x9], #8
    add x10, x10, #1
    sub x11, x11, #1
    cbnz x11, .Lprime
    ADDRESS x9, round_number
    ldr x22, [x9]
    ADDRESS x9, phase_number
    ldr x9, [x9]
    ADDRESS x10, lane_order
    ldr x25, [x10, x9, lsl #3]
    ADDRESS x10, lr_table
    ldr x28, [x10, x25, lsl #3]
    U64 x0, 0xa0b0c0d0e0f00000
    orr x0, x0, x22, lsl #8
    orr x0, x0, x25
    U64 x1, 0x0102030405060708
    mov x2, #2
    mov x3, #3
    mov x4, #4
    mov x5, #5
    mov x6, #6
    mov x7, #7
    mov x8, #8
    mov x9, #9
    mov x10, #10
    mov x11, #11
    mov x12, #12
    mov x13, #13
    mov x14, #14
    mov x15, #15
    ADDRESS x16, actual_record
    mov x17, #17
    mov x18, #18
    U64 x19, 0x191a1b1c1d1e0000
    orr x19, x19, x22
    U64 x20, 0x2021222324250000
    orr x20, x20, x25
    U64 x21, 0x2122232425260000
    orr x21, x21, x22, lsl #8
    orr x21, x21, x25
    U64 x23, 0x1122334455667700
    add x23, x23, x22
    U64 x24, 0x2425262728292a2b
    mov x26, #26
    mov x27, sp
    U64 x29, 0x292a2b2c2d2e2f30
    U64 x30, 0x3031323334353637
    /* Set flags with scratch x9, then return x9 to its declared input value. */
    ADDRESS x9, nzcv_table
    ldr x9, [x9, x25, lsl #3]
    msr nzcv, x9
    mov x9, #9
    SNAPSHOT

    /* Derive the expected result from the actual input and defined BL/prefix effects. */
    ADDRESS x9, actual_record
    ADDRESS x10, expected_record
    mov x11, #51
.Lexpected_copy:
    ldr x12, [x9], #8
    str x12, [x10], #8
    sub x11, x11, #1
    cbnz x11, .Lexpected_copy
    ADDRESS x10, expected_record
    U64 x9, (0x488385f8 + FIXTURE_MUTATED)
    str x9, [x10, #8]       /* ADRP/ADD replaces x1, without dereferencing it. */
    ldr x9, [x10, #224]     /* BL writes the lane's LR, not the initial x30. */
    str x9, [x10, #240]
    str x9, [x10, #288]     /* [SP-112+8] receives LR. */
    ldr x9, [x10, #232]
    str x9, [x10, #280]     /* [SP-112] receives caller FP. */
    ldr x9, [x10, #184]
    str x9, [x10, #328]     /* [SP-112+48] receives caller x23. */
    ldr x9, [x10, #192]
    str x9, [x10, #336]     /* [SP-112+56] receives caller x24. */
    RESTORE_INPUT
    /* Fixed BL sites are ~32 MiB away; only the unconditional B can reach. */
    cbnz x25, .Ltry_lane1
    b callsite0
.Ltry_lane1:
    tbnz x25, #1, .Ltry_wrong_lane
    b callsite1
.Ltry_wrong_lane:
    b wrong_callsite

.global after_call
.type after_call, %function
after_call:
    SNAPSHOT
    ADDRESS x9, actual_record
    ADDRESS x10, expected_record
    mov x11, #51
.Lselfcheck:
    ldr x12, [x9], #8
    ldr x13, [x10], #8
    cmp x12, x13
    b.ne fixture_failure
    sub x11, x11, #1
    cbnz x11, .Lselfcheck
    ADDRESS x2, actual_record
    mov x3, #408
    bl dump_bytes
    ADDRESS x9, phase_number
    ldr x10, [x9]
    add x10, x10, #1
#if FIXTURE_WRONG_LR_ONLY
    cmp x10, #1
#else
    cmp x10, #3
#endif
    b.eq .Lnext_round
    str x10, [x9]
    b prepare_call
.Lnext_round:
    str xzr, [x9]
    ADDRESS x9, round_number
    ldr x10, [x9]
    add x10, x10, #1
    str x10, [x9]
    cmp x10, #18
    b.ne prepare_call
#if FIXTURE_PRODUCER
    b producer_prepare
#endif
fixture_dump_code:
    mov x0, #4
    ADDRESS x1, records_marker
    hlt #0xf000
    ADDRESS x2, __boot_start
    ADDRESS x3, __boot_end
    sub x3, x3, x2
    bl dump_bytes
    ADDRESS x2, __callers_start
    ADDRESS x3, __callers_end
    sub x3, x3, x2
    bl dump_bytes
    ADDRESS x2, __wrong_start
    ADDRESS x3, __wrong_end
    sub x3, x3, x2
    bl dump_bytes
    ADDRESS x2, __observed_start
    ADDRESS x3, __observed_end
    sub x3, x3, x2
    bl dump_bytes
#if FIXTURE_PRODUCER
    ADDRESS x2, __producer_start
    ADDRESS x3, __producer_end
    sub x3, x3, x2
    bl dump_bytes
#endif
    mov x0, #4
    ADDRESS x1, success_marker
    hlt #0xf000
    ADDRESS x1, exit_block
    mov x0, #0x20
    hlt #0xf000
.Lexit_returned:
    b .Lexit_returned

#if FIXTURE_PRODUCER
/* One early invocation, the existing scope sequence, then sixteen late calls. */
producer_prepare:
    sub x9, sp, #128
    U64 x10, 0x6677889900000000
    mov x11, #18
.Lproducer_prime_stack:
    str x10, [x9], #8
    add x10, x10, #1
    sub x11, x11, #1
    cbnz x11, .Lproducer_prime_stack
    ADDRESS x9, producer_store_seed
    ADDRESS x10, producer_targets
    ADDRESS x11, producer_store_before
    ADDRESS x12, producer_expected_stores
    ldp x13, x14, [x9]
    stp x13, x14, [x10]
    stp x13, x14, [x11]
    stp x13, x14, [x12]
    ldp x13, x14, [x9, #16]
    stp x13, x14, [x10, #16]
    stp x13, x14, [x11, #16]
    stp x13, x14, [x12, #16]
    ADDRESS x9, producer_round
    ldr x22, [x9]
    /* Pointer-shaped, unmapped x0 is still only the original STR's u32 value. */
    U64 x0, 0xffff0001dead0000
    orr x0, x0, x22
    U64 x1, 0x0102030405060708
    mov x2, #2
    mov x3, #3
    mov x4, #4
    mov x5, #5
    mov x6, #6
    mov x7, #7
    mov x8, #8
    mov x9, #9
    mov x10, #10
    mov x11, #11
    mov x12, #12
    mov x13, #13
    mov x14, #14
    mov x15, #15
    ADDRESS x16, actual_record
    mov x17, #17
    mov x18, #18
    U64 x19, 0x191a1b1c1d1e0000
    orr x19, x19, x22
    U64 x20, 0x2021222324250000
    U64 x21, 0x2122232425260000
    orr x21, x21, x22, lsl #8
    U64 x23, 0x1122334455667700
    add x23, x23, x22
    U64 x24, 0x2425262728292a2b
    mov x25, #0
    mov x26, #26
    mov x27, sp
    ADDRESS x28, producer_return
    U64 x29, 0x292a2b2c2d2e2f30
    ADDRESS x30, producer_return
    U64 x9, 0x90000000
    msr nzcv, x9
    mov x9, #9
    PRODUCER_SNAPSHOT
    ADDRESS x9, actual_record
    ADDRESS x10, producer_before
    ADDRESS x11, expected_record
    mov x12, #54
.Lproducer_copy_input:
    ldr x13, [x9], #8
    str x13, [x10], #8
    str x13, [x11], #8
    sub x12, x12, #1
    cbnz x12, .Lproducer_copy_input
    ADDRESS x10, expected_record
    U64 x9, (0x47e6a4d8 + 4 * FIXTURE_PRODUCER_MUTATED)
    str x9, [x10, #8]
    ADDRESS x10, producer_expected_stores
    ldr w9, [x16]
    str w9, [x10, #(8 + 4 * FIXTURE_PRODUCER_MUTATED)]
    str w9, [x10, #(16 + 4 * FIXTURE_PRODUCER_MUTATED)]
    RESTORE_INPUT
.global producer_callsite, producer_return
producer_callsite:
    bl synthetic_producer
producer_return:
    PRODUCER_SNAPSHOT
    ADDRESS x9, actual_record
    ADDRESS x10, expected_record
    mov x11, #54
.Lproducer_selfcheck:
    ldr x12, [x9], #8
    ldr x13, [x10], #8
    cmp x12, x13
    b.ne fixture_failure
    sub x11, x11, #1
    cbnz x11, .Lproducer_selfcheck
    ADDRESS x9, producer_targets
    ADDRESS x10, producer_expected_stores
    mov x11, #4
.Lproducer_store_selfcheck:
    ldr x12, [x9], #8
    ldr x13, [x10], #8
    cmp x12, x13
    b.ne fixture_failure
    sub x11, x11, #1
    cbnz x11, .Lproducer_store_selfcheck
    ADDRESS x2, producer_before
    mov x3, #432
    bl dump_bytes
    ADDRESS x2, actual_record
    mov x3, #432
    bl dump_bytes
    ADDRESS x2, producer_store_before
    mov x3, #32
    bl dump_bytes
    ADDRESS x2, producer_targets
    mov x3, #32
    bl dump_bytes
    ADDRESS x9, producer_round
    ldr x10, [x9]
    add x11, x10, #1
    str x11, [x9]
    cmp x10, #1
    b.eq prepare_call
    cmp x10, #17
    b.ne producer_prepare
    b fixture_dump_code
#endif

fixture_failure:
    mov x0, #4
    ADDRESS x1, failure_marker
    hlt #0xf000
    ADDRESS x1, exit_block
    mov x9, #1
    str x9, [x1, #8]
    mov x0, #0x20
    hlt #0xf000
    b .Lexit_returned

/* SYS_WRITEC preserves binary bytes and keeps guest output off plugin/stderr. */
dump_bytes:
    ADDRESS x1, console_byte
.Ldump:
    cbz x3, .Ldump_end
    ldrb w4, [x2], #1
    strb w4, [x1]
    mov x0, #3
    hlt #0xf000
    sub x3, x3, #1
    b .Ldump
.Ldump_end:
    ret

.section .rodata.fixture, "a", %progbits
.balign 8
lane_order:
#if FIXTURE_WRONG_LR_ONLY
    .quad 2
#else
    .quad 0, 2, 1
#endif
lr_table:
    .quad lane0_return, lane1_return, wrong_return
nzcv_table:
    .quad 0xa0000000, 0x60000000, 0x30000000
console_header:
#if FIXTURE_PRODUCER
    .asciz "SCOPE_FIXTURE_V2_PRODUCER\n"
#else
    .asciz "SCOPE_FIXTURE_V1\n"
#endif
records_marker:
    .asciz "\nSCOPE_FIXTURE_RECORDS_OK\n"
success_marker:
#if FIXTURE_PRODUCER
    .asciz "\nSCOPE_FIXTURE_OK calls=51 lanes=17,17,17 producer_calls=17\n"
#elif FIXTURE_WRONG_LR_ONLY
    .asciz "\nSCOPE_FIXTURE_OK calls=17 lanes=0,0,17\n"
#else
    .asciz "\nSCOPE_FIXTURE_OK calls=51 lanes=17,17,17\n"
#endif
failure_marker:
    .asciz "SCOPE_FIXTURE_SELF_CHECK_FAILED\n"

.section .data.fixture, "aw", %progbits
.balign 16
.global actual_record
actual_record:
    .space FIXTURE_RECORD_BYTES
.balign 16
expected_record:
    .space FIXTURE_RECORD_BYTES
#if FIXTURE_PRODUCER
.balign 16
producer_before:
    .space 432
producer_store_before:
    .space 32
producer_expected_stores:
    .space 32
producer_store_seed:
    .quad 0x1122334455667788, 0x99aabbcc13572468
    .quad 0x0123456789abcdef, 0xfedcba9876543210
producer_round:
    .quad 1
#endif
.balign 8
round_number:
    .quad 1
phase_number:
    .quad 0
console_byte:
    .byte 0
.balign 8
exit_block:
    .quad 0x20026, 0

.section .text.callers, "ax", %progbits
.balign 4
.global callsite0, lane0_return, callsite1, lane1_return
callsite0:
    bl synthetic_entry
lane0_return:
    b after_call
callsite1:
    bl synthetic_entry
lane1_return:
    b after_call

.section .text.wrong, "ax", %progbits
.balign 4
.global wrong_callsite, wrong_return
wrong_callsite:
    bl synthetic_entry
wrong_return:
    b after_call

.section .text.observed, "ax", %progbits
.balign 4
.global synthetic_entry, anchor_end
.type synthetic_entry, %function
synthetic_entry:
    /* Known 24-byte signature, followed only by independently authored code. */
    .inst 0xa9b97bfd          /* stp x29,x30,[sp,#-112]! */
    .inst 0xd002d181          /* adrp x1, ... */
#if FIXTURE_MUTATED
    .inst 0x9117e421          /* One-byte change: add x1,x1,#0x5f9. */
#else
    .inst 0x9117e021          /* add x1,x1,#0x5f8 */
#endif
    .inst 0x910003fd          /* mov x29,sp */
    .inst 0xa90363f7          /* stp x23,x24,[sp,#48] */
    .inst 0x910183b7          /* add x23,x29,#96 */
anchor_end:
    ldp x23, x24, [sp, #48]
    ldp x29, x30, [sp], #112
    ret
.size synthetic_entry, .-synthetic_entry

#if FIXTURE_PRODUCER
.section .text.producer, "ax", %progbits
.balign 4
.global synthetic_producer, producer_anchor_end
.type synthetic_producer, %function
synthetic_producer:
    /* Exact inherited 24B, at the same offset in this self-owned mapping. */
    .inst 0xd002b701
#if FIXTURE_PRODUCER_MUTATED
    .inst 0x91137021          /* Ordinary corrupt candidate: add #0x4dc. */
#else
    .inst 0x91136021
#endif
    .inst 0x91406821
    .inst 0xb902f020
    .inst 0xb902f820
    .inst 0xd65f03c0
producer_anchor_end:
.size synthetic_producer, .-synthetic_producer

.section .data.producer_targets, "aw", %progbits
.balign 8
.global producer_targets
producer_targets:
    .space 32
#endif

.section .note.GNU-stack, "", %progbits
