/* SPDX-License-Identifier: MIT */
/* SOURCE_ONLY. All instructions, literals and replay execute in our own guest. */
#ifndef FIXTURE_STUB
#define FIXTURE_STUB 0
#endif
#ifndef FIXTURE_MUTATED
#define FIXTURE_MUTATED 0
#endif
#define RECORD_BYTES 408

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

/* x16 names the record: 31 GPRs, SP/NZCV/CPSR/tokens/source64, 14 stack words. */
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
    mrs x9, daif
    mrs x10, CurrentEL
    orr x9, x9, x10
    mrs x10, spsel
    orr x9, x9, x10
    mrs x10, nzcv
    orr x9, x9, x10
    str x9, [x16, #264]
    mrs x9, ttbr0_el1
    str x9, [x16, #272]
    mrs x9, tpidr_el0
    str x9, [x16, #280]
    ADDRESS x9, source_word
    ldr x9, [x9]
    str x9, [x16, #288]
    ADDRESS x9, __stack_top
    sub x9, x9, #96
    add x10, x16, #296
    mov x11, #14
.Lstack_\@:
    ldr x12, [x9], #8
    str x12, [x10], #8
    sub x11, x11, #1
    cbnz x11, .Lstack_\@
.endm
.macro RESTORE
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
    ldp x18, x19, [x16, #144]
    ldp x20, x21, [x16, #160]
    ldp x22, x23, [x16, #176]
    ldp x24, x25, [x16, #192]
    ldp x26, x27, [x16, #208]
    ldp x28, x29, [x16, #224]
    ldr x30, [x16, #240]
    ldp x16, x17, [x16, #128]
.endm
/* Comparisons run outside observed windows; the next RESTORE reinstates flags. */
.macro CHECK_RECORD actual, expected
    ADDRESS x9, \actual
    ADDRESS x10, \expected
    mov x11, #51
.Lcheck_\@:
    ldr x12, [x9], #8
    ldr x13, [x10], #8
    cmp x12, x13
    b.ne fixture_failure
    sub x11, x11, #1
    cbnz x11, .Lcheck_\@
.endm
.macro COPY_RECORD actual, expected
    ADDRESS x9, \actual
    ADDRESS x10, \expected
    mov x11, #51
.Lcopy_\@:
    ldr x12, [x9], #8
    str x12, [x10], #8
    sub x11, x11, #1
    cbnz x11, .Lcopy_\@
.endm

.section .text.boot, "ax", %progbits
.balign 4
.global _start
_start:
    msr daifset, #15
    msr spsel, #1
    ADDRESS x9, __stack_top
    mov sp, x9
    mrs x9, CurrentEL
    cmp x9, #4
    b.ne fixture_failure
    ADDRESS x9, fixture_vectors
    msr vbar_el1, x9
    isb
    mrs x9, sctlr_el1
    tbnz x9, #0, fixture_failure
    ADDRESS x9, fixture_l1
    movk x9, #1, lsl #48
    msr ttbr0_el1, x9
    mov x9, #0x44
    msr mair_el1, x9
    U64 x9, 0x80a03020
    msr tcr_el1, x9
    dsb sy
    tlbi vmalle1
    dsb sy
    isb
    mrs x9, sctlr_el1
    bic x9, x9, #2
    orr x9, x9, #1
    msr sctlr_el1, x9
    isb
    mrs x9, sctlr_el1
    and x9, x9, #3
    cmp x9, #1
    b.ne fixture_failure
    mrs x9, mair_el1
    cmp x9, #0x44
    b.ne fixture_failure
    mrs x9, tcr_el1
    U64 x10, 0x80a03020
    cmp x9, x10
    b.ne fixture_failure
    mrs x9, ttbr0_el1
    ADDRESS x10, fixture_l1
    movk x10, #1, lsl #48
    cmp x9, x10
    b.ne fixture_failure
    /* A=0 alone cannot permit unaligned data while MMU-off RAM is Device. */
    ADDRESS x9, __stack_bottom
    U64 x10, 0x0123456789abcdef
    U64 x11, 0xfedcba9876543210
    stp x10, x11, [x9]
    ldr x10, [x9, #4]
    U64 x11, 0x7654321001234567
    cmp x10, x11
    b.ne fixture_failure
    U64 x9, 0x89abcdef01234567
    msr tpidr_el0, x9
    /* Check all four windows against independent RO constants before execution. */
    ADDRESS x9, code_checks
    mov x14, #4
.Lcode_window:
    ldp x10, x11, [x9], #16
    ldr x12, [x9], #8
.Lcode_byte:
    ldrb w13, [x10], #1
    ldrb w15, [x11], #1
    cmp w13, w15
    b.ne fixture_failure
    sub x12, x12, #1
    cbnz x12, .Lcode_byte
    sub x14, x14, #1
    cbnz x14, .Lcode_window
    mov x0, #4
    ADDRESS x1, console_header
    hlt #0xf000

prepare:
    ADDRESS x9, __stack_top
    sub x9, x9, #96
    U64 x10, 0x6677889900000000
    mov x11, #14
.Lprime:
    str x10, [x9], #8
    add x10, x10, #1
    sub x11, x11, #1
    cbnz x11, .Lprime
    ADDRESS x9, round_number
    ldr x20, [x9]
    /* Round0 is an explicit gate-only warmup, before any measured entry. */
    mov w12, #1
    cbz x20, .Lsource_ready
    sub x9, x20, #1
    and x9, x9, #7
    ADDRESS x10, w0_inputs
    ldr w12, [x10, x9, lsl #2]
.Lsource_ready:
    U64 x10, 0x7abcdeff00000000
    orr x10, x10, x12
    ADDRESS x9, source_word
    str x10, [x9]
    U64 x0, 0xa0b0c0d0e0f00000
    orr x0, x0, x20
    U64 x1, 0x1122334400000000
    orr x1, x1, x20
    U64 x2, 0x2233445566770000
    orr x2, x2, x20
    U64 x3, 0x3344556677880000
    orr x3, x3, x20
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
    ADDRESS x16, entry_before
    mov x17, #17
    mov x18, #18
    U64 x19, 0x191a1b1c1d1e0000
    orr x19, x19, x20
    U64 x21, 0x2122232425260000
    orr x21, x21, x20
    U64 x22, 0x2223242526270000
    orr x22, x22, x20
    U64 x23, 0x2324252627280000
    orr x23, x23, x20
    U64 x24, 0x2425262728292a2b
    mov x25, #25
    mov x26, #26
    mov x27, sp
    mov x28, #28
    U64 x29, 0x292a2b2c2d2e2f30
    ADDRESS x30, entry_return
    and x9, x20, #3
    ADDRESS x10, nzcv_inputs
    ldr x9, [x10, x9, lsl #3]
    msr nzcv, x9
    mov x9, #9
    mov x10, #10
    SNAPSHOT
    COPY_RECORD entry_before, expected_entry_after
    ADDRESS x10, expected_entry_after
    ADDRESS x9, entry_after
    str x9, [x10, #128]
    ADDRESS x9, __stack_top
    sub x9, x9, #80
    str x9, [x10, #232]
    str x9, [x10, #248]
    str x20, [x10, #176]   /* MOV W22,W1 zero extends. */
    cbz x20, .Lentry_expected_ready
    ADDRESS x9, entry_before
    ldp x11, x12, [x9, #232]
    stp x11, x12, [x10, #312] /* frame [SP+0] and [SP+8] */
    ldp x11, x12, [x9, #168]
    stp x11, x12, [x10, #344] /* frame [SP+32] and [SP+40] */
.Lentry_expected_ready:
    RESTORE
    cbz x20, warmup_frame
    b synthetic_entry
warmup_frame:
    sub sp, sp, #80
    mov x29, sp
    mov w22, w1
    b after_entry
.global after_entry
after_entry:
    ADDRESS x16, entry_after
    SNAPSHOT
    CHECK_RECORD entry_after, expected_entry_after
    ADDRESS x16, entry_after
    RESTORE
    /* Harness setup is explicit and makes no claim about a Sony call path. */
    mov x23, x0
    ADDRESS x0, source_word
    ADDRESS x16, gate_before
    SNAPSHOT
    COPY_RECORD gate_before, expected_gate_after
    ADDRESS x10, expected_gate_after
    ADDRESS x9, gate_after
    str x9, [x10, #128]
    ldr x9, [x10, #152]
    str x9, [x10, #0]      /* Fallthrough MOV preserves the rich full64 X19. */
    ldr w9, [x10, #288]
    /* Mutation changes only CBNZ's Rt to W1; the harness follows that opcode. */
#if FIXTURE_MUTATED
    ldr w9, [x10, #8]
#endif
    cbz w9, .Lgate_zero
    ldr x9, [x10, #232]
    add x9, x9, #72
    str x9, [x10, #152]    /* Taken snippet ADD changes X19 before its MOV. */
    str x9, [x10, #0]
    b .Lgate_expected_ready
.Lgate_zero:
    ADDRESS x9, fallthrough_return
    str x9, [x10, #240]
.Lgate_expected_ready:
    ADDRESS x16, gate_before
    RESTORE
    b synthetic_gate
.global after_gate
after_gate:
    ADDRESS x16, gate_after
    SNAPSHOT
    CHECK_RECORD gate_after, expected_gate_after
    ADDRESS x2, entry_before
    mov x3, #(4 * RECORD_BYTES)
    bl dump_bytes
    add sp, sp, #80
    ADDRESS x9, round_number
    ldr x10, [x9]
    add x10, x10, #1
    str x10, [x9]
    cmp x10, #41
    b.ne prepare
    mov x0, #4
    ADDRESS x1, records_marker
    hlt #0xf000
    ADDRESS x2, __boot_start
    ADDRESS x3, __boot_end
    sub x3, x3, x2
    bl dump_bytes
    ADDRESS x2, __replay_start
    mov x3, #20
    bl dump_bytes
    ADDRESS x2, entry_return
    mov x3, #4
    bl dump_bytes
    ADDRESS x2, synthetic_entry
    mov x3, #20
    bl dump_bytes
    ADDRESS x2, successor_1724
    mov x3, #12
    bl dump_bytes
    ADDRESS x2, synthetic_gate
    mov x3, #20
    bl dump_bytes
    ADDRESS x2, owned_bl_sink
    mov x3, #4
    bl dump_bytes
    mov x0, #4
    ADDRESS x1, success_marker
    hlt #0xf000
    ADDRESS x1, exit_block
    mov x0, #0x20
    hlt #0xf000
.Lexit_returned:
    b .Lexit_returned
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
fixture_exception:
    ADDRESS x9, exception_record
    mrs x10, elr_el1
    str x10, [x9]
    mrs x10, esr_el1
    str x10, [x9, #8]
    mrs x10, far_el1
    str x10, [x9, #16]
    mrs x10, sctlr_el1
    str x10, [x9, #24]
    mov x0, #4
    ADDRESS x1, exception_marker
    hlt #0xf000
    ADDRESS x2, exception_record
    mov x3, #32
    bl dump_bytes
    ADDRESS x1, exit_block
    mov x9, #2
    str x9, [x1, #8]
    mov x0, #0x20
    hlt #0xf000
    b .Lexit_returned
/* Reuse the v3 binary semihosting dump: no plugin data enters the console. */
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
w0_inputs:
    .word 0, 1, 0, 0xffffffff, 0, 0x80000000, 0, 1
nzcv_inputs:
    .quad 0xa0000000, 0x60000000, 0x30000000, 0x90000000
code_checks:
    .quad synthetic_entry, expected_entry, 16
    .quad successor_1724, expected_1724, 8
    .quad synthetic_gate, expected_gate, 8
    .quad successor_1838, expected_1838, 8
expected_entry:
#if FIXTURE_STUB
    .word 0x58000050, 0xd61f0200
    .quad synthetic_replay
#else
    .word 0xa9bb7bfd, 0x910003fd, 0xa9025bf5, 0x2a0103f6
#endif
expected_1724:
    .word 0x910123b3, 0xaa1303e0
expected_gate:
    .word 0xb9400000
#if FIXTURE_MUTATED
    .word 0x35fff781
#else
    .word 0x35fff780
#endif
expected_1838:
    .word 0xaa1303e0, 0x9428b144
console_header:
    .asciz "SHUTTER_GATE_FIXTURE_V1\n"
records_marker:
    .asciz "\nSHUTTER_GATE_RECORDS_OK\n"
success_marker:
    .asciz "\nSHUTTER_GATE_FIXTURE_OK warmup=1 entries=40 gates=41\n"
failure_marker:
    .asciz "SHUTTER_GATE_SELF_CHECK_FAILED\n"
exception_marker:
    .asciz "SHUTTER_GATE_FIXTURE_EXCEPTION_ELR_ESR_FAR_SCTLR\n"

.section .rodata.mmu, "a", %progbits
.balign 4096
.global fixture_l1, fixture_l2, fixture_mmu_end
fixture_l1:
    .quad 0
    .quad fixture_l2 + 3
    .zero 510 * 8
fixture_l2:
    .set .Lfixture_pa, 0x40000000
    .rept 32
        .quad .Lfixture_pa + 0x701
        .set .Lfixture_pa, .Lfixture_pa + 0x200000
    .endr
    .zero 480 * 8
fixture_mmu_end:

.section .text.vectors, "ax", %progbits
.balign 2048
.global fixture_vectors, fixture_vectors_end
fixture_vectors:
    .rept 16
        b fixture_exception
        .space 124
    .endr
fixture_vectors_end:

.section .data.fixture, "aw", %progbits
.balign 16
.global entry_before, entry_after, gate_before, gate_after
entry_before: .space RECORD_BYTES
entry_after: .space RECORD_BYTES
gate_before: .space RECORD_BYTES
gate_after: .space RECORD_BYTES
expected_entry_after: .space RECORD_BYTES
expected_gate_after: .space RECORD_BYTES
round_number: .quad 0
console_byte: .byte 0
.balign 8
exception_record: .space 32
exit_block: .quad 0x20026, 0
.section .data.source, "aw", %progbits
.global source_word
source_word: .quad 0

/* This replay and the stub's literal are prebuilt owned guest code, never patches. */
.section .text.replay, "ax", %progbits
.global synthetic_replay
synthetic_replay:
    .inst 0xa9bb7bfd
    .inst 0x910003fd
    .inst 0xa9025bf5
    .inst 0x2a0103f6
    b entry_return
.section .text.resume, "ax", %progbits
.global entry_return
entry_return:
    b after_entry
.section .text.entry, "ax", %progbits
.global synthetic_entry
synthetic_entry:
#if FIXTURE_STUB
    .inst 0x58000050
    .inst 0xd61f0200
    .quad synthetic_replay
    nop
#else
    .inst 0xa9bb7bfd
    .inst 0x910003fd
    .inst 0xa9025bf5
    .inst 0x2a0103f6
    b entry_return
#endif
.section .text.target, "ax", %progbits
.global successor_1724
successor_1724:
    .inst 0x910123b3
    .inst 0xaa1303e0
    b after_gate
.section .text.gate, "ax", %progbits
.global synthetic_gate, successor_1838, fallthrough_return
synthetic_gate:
    .inst 0xb9400000
#if FIXTURE_MUTATED
    .inst 0x35fff781
#else
    .inst 0x35fff780
#endif
successor_1838:
    .inst 0xaa1303e0
    .inst 0x9428b144
fallthrough_return:
    b fixture_failure
.section .text.sink, "ax", %progbits
.global owned_bl_sink
owned_bl_sink:
    b after_gate
.section .note.GNU-stack, "", %progbits
