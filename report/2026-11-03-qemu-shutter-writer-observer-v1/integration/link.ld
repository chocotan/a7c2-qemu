/* SPDX-License-Identifier: MIT */
ENTRY(_start)
PHDRS {
    boot PT_LOAD FLAGS(5);
    writer PT_LOAD FLAGS(5);
    cell PT_LOAD FLAGS(6);
}
SECTIONS {
    . = 0x40200000;
    .text.boot : { *(.text.boot) } :boot
    . = 0x42767978;
    .text.writer : { *(.text.writer) } :writer
    . = 0x47e5d570;
    .bss.writer (NOLOAD) : { *(.bss.writer) } :cell
    /DISCARD/ : { *(.comment) *(.note*) }
}
