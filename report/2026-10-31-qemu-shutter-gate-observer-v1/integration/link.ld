/* SPDX-License-Identifier: MIT */
OUTPUT_FORMAT(elf64-littleaarch64)
OUTPUT_ARCH(aarch64)
ENTRY(_start)
/* Reuse the v3 sparse LOAD layout; every mapping is private virt-machine RAM. */
PHDRS
{
    boot PT_LOAD FLAGS(5);
    replay PT_LOAD FLAGS(5);
    resume PT_LOAD FLAGS(5);
    data PT_LOAD FLAGS(6);
    source PT_LOAD FLAGS(6);
    stack PT_LOAD FLAGS(6);
    entry PT_LOAD FLAGS(5);
    target PT_LOAD FLAGS(5);
    gate PT_LOAD FLAGS(5);
    sink PT_LOAD FLAGS(5);
}
B = 0x40000000;
SECTIONS
{
    .boot B + 0x80000 :
    {
        __boot_start = .;
        KEEP(*(.text.boot))
        KEEP(*(.rodata.fixture))
        . = ALIGN(4096);
        KEEP(*(.rodata.mmu))
        . = ALIGN(2048);
        KEEP(*(.text.vectors))
        . = ALIGN(4);
        __boot_end = .;
    } :boot
    .replay B + 0x90000 :
    {
        __replay_start = .;
        KEEP(*(.text.replay))
    } :replay
    .resume B + 0x90100 : { KEEP(*(.text.resume)) } :resume
    .fixturedata B + 0x100000 : { KEEP(*(.data.fixture)) } :data
    .source B + 0x102000 : { KEEP(*(.data.source)) } :source
    .stack B + 0x1fc000 (NOLOAD) :
    {
        __stack_bottom = .;
        . += 0x4000;
        __stack_top = .;
        . += 0x10;
    } :stack
    .entry B + 0x1af16dc : { KEEP(*(.text.entry)) } :entry
    .target B + 0x1af1724 : { KEEP(*(.text.target)) } :target
    .gate B + 0x1af1830 : { KEEP(*(.text.gate)) } :gate
    .sink B + 0x251dd4c : { KEEP(*(.text.sink)) } :sink
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
ASSERT(_start == B + 0x80000, "boot entry moved")
ASSERT(__boot_end < B + 0x90000, "boot overlaps replay")
ASSERT(fixture_l1 == B + 0x81000, "owned L1 moved")
ASSERT(fixture_l2 == B + 0x82000, "owned L2 moved")
ASSERT(fixture_mmu_end == B + 0x83000, "owned table size changed")
ASSERT(fixture_vectors == B + 0x83000 && fixture_vectors_end == B + 0x83800, "owned vectors moved")
ASSERT(synthetic_replay == B + 0x90000 && SIZEOF(.replay) == 20, "owned replay moved")
ASSERT(entry_return == B + 0x90100 && SIZEOF(.resume) == 4, "entry continuation moved")
ASSERT(entry_before == B + 0x100000, "snapshot array moved")
ASSERT(entry_after - entry_before == 408, "entry snapshot size changed")
ASSERT(gate_before - entry_before == 816, "gate input snapshot moved")
ASSERT(gate_after - entry_before == 1224, "gate result snapshot moved")
ASSERT(SIZEOF(.fixturedata) < 0x2000, "records overlap source word")
ASSERT(source_word == B + 0x102000 && SIZEOF(.source) == 8, "source/guard moved")
ASSERT(__stack_top == B + 0x200000, "stack top moved")
ASSERT(synthetic_entry == B + 0x1af16dc && SIZEOF(.entry) == 20, "entry window moved")
ASSERT(successor_1724 == B + 0x1af1724 && SIZEOF(.target) == 12, "target window moved")
ASSERT(synthetic_gate == B + 0x1af1830 && SIZEOF(.gate) == 20, "gate window moved")
ASSERT(successor_1838 == B + 0x1af1838, "fallthrough window moved")
ASSERT(fallthrough_return == B + 0x1af1840, "owned BL return moved")
ASSERT(owned_bl_sink == B + 0x251dd4c && SIZEOF(.sink) == 4, "owned BL sink moved")
ASSERT(owned_bl_sink + SIZEOF(.sink) < B + 0x4000000, "guest exceeds private 64 MiB RAM")
