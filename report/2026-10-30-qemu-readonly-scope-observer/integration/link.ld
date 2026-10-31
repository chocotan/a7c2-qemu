/* SPDX-License-Identifier: MIT */
OUTPUT_FORMAT(elf64-littleaarch64)
OUTPUT_ARCH(aarch64)
ENTRY(_start)

/* Independent LOAD segments keep the file small despite separated VMAs. */
PHDRS
{
    boot     PT_LOAD FLAGS(5);
    data     PT_LOAD FLAGS(6);
    stack    PT_LOAD FLAGS(6);
    callers  PT_LOAD FLAGS(5);
    wrong    PT_LOAD FLAGS(5);
    observed PT_LOAD FLAGS(5);
    producer PT_LOAD FLAGS(5);
    targets  PT_LOAD FLAGS(6);
}

B = 0x40000000;
SECTIONS
{
    .boot B + 0x80000 :
    {
        __boot_start = .;
        KEEP(*(.text.boot))
        KEEP(*(.rodata.fixture))
        . = ALIGN(4);
        __boot_end = .;
    } :boot

    .fixturedata B + 0x100000 :
    {
        KEEP(*(.data.fixture))
    } :data

    .stack B + 0x1fc000 (NOLOAD) :
    {
        __stack_bottom = .;
        . += 0x4000;
        __stack_top = .;
        . += 0x10;
    } :stack

    .callers B + 0x209ee7c :
    {
        __callers_start = .;
        KEEP(*(.text.callers))
        __callers_end = .;
    } :callers

    .wrongcaller B + 0x209eea0 :
    {
        __wrong_start = .;
        KEEP(*(.text.wrong))
        __wrong_end = .;
    } :wrong

    .producer B + 0x276e710 :
    {
        __producer_start = .;
        KEEP(*(.text.producer))
        __producer_end = .;
    } :producer

    .observed B + 0x2e068cc :
    {
        __observed_start = .;
        KEEP(*(.text.observed))
        __observed_end = .;
    } :observed

    .producertargets B + 0x7e6a7c0 :
    {
        __producer_targets_start = .;
        KEEP(*(.data.producer_targets))
        __producer_targets_end = .;
    } :targets

    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}

ASSERT(_start == B + 0x80000, "unexpected entry")
ASSERT(__boot_end < B + 0x100000, "boot overlaps data")
ASSERT(actual_record == B + 0x100000, "unexpected snapshot address")
ASSERT(__stack_top == B + 0x200000, "unexpected SP")
ASSERT(callsite0 == B + 0x209ee7c, "lane 0 BL moved")
ASSERT(lane0_return == B + 0x209ee80, "lane 0 LR moved")
ASSERT(callsite1 == B + 0x209ee84, "lane 1 BL moved")
ASSERT(lane1_return == B + 0x209ee88, "lane 1 LR moved")
ASSERT(wrong_return == B + 0x209eea4, "negative LR moved")
ASSERT(SIZEOF(.callers) == 16, "unexpected callers")
ASSERT(SIZEOF(.wrongcaller) == 8, "unexpected wrong-LR caller")
ASSERT(synthetic_entry == B + 0x2e068cc, "synthetic entry moved")
ASSERT(anchor_end - synthetic_entry == 24, "anchor must be exactly six words")
ASSERT(SIZEOF(.observed) == 36, "only the anchor plus the own epilogue is allowed")
ASSERT(SIZEOF(.producer) == 0 || SIZEOF(.producer) == 24, "producer must be absent or six complete words")
ASSERT(SIZEOF(.producertargets) == 0 || SIZEOF(.producertargets) == 32, "unexpected self-owned target guards")
ASSERT(__producer_end <= B + 0x276f000, "producer anchor must not cross a guest page")
ASSERT(__producer_targets_end <= B + 0x8000000, "producer targets exceed private 128 MiB RAM")
