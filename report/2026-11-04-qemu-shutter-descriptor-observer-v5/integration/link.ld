/* SPDX-License-Identifier: MIT */
ENTRY(_start)
PHDRS {
    boot PT_LOAD FLAGS(5);
    dispatch PT_LOAD FLAGS(5);
    upstream PT_LOAD FLAGS(5);
    record PT_LOAD FLAGS(5);
    recordcell PT_LOAD FLAGS(6);
    writer PT_LOAD FLAGS(5);
    descriptor PT_LOAD FLAGS(5);
    table PT_LOAD FLAGS(5);
    slot PT_LOAD FLAGS(6);
    cell PT_LOAD FLAGS(6);
}
SECTIONS {
    . = 0x40200000;
    .text.boot : { *(.text.boot) } :boot
    . = 0x4247086c;
    .text.record : { *(.text.record) } :record
    . = 0x42506220;
    .text.dispatch : { *(.text.dispatch) } :dispatch
    . = 0x4250646c;
    .text.upstream : { *(.text.upstream) } :upstream
    . = 0x42767978;
    .text.writer : { *(.text.writer) } :writer
    . = 0x42767990;
    .text.descriptor : { *(.text.descriptor) } :descriptor
    . = 0x428bb120;
    .text.table : { *(.text.table) } :table
    . = 0x45589390;
    .data.slot : { *(.data.slot) } :slot
    . = 0x47e43430;
    .bss.record (NOLOAD) : { *(.bss.record) } :recordcell
    . = 0x47e5d570;
    .bss.writer (NOLOAD) : { *(.bss.writer) } :cell
    /DISCARD/ : { *(.comment) *(.note*) }
}
