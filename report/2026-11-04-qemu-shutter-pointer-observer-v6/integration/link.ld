/* SPDX-License-Identifier: MIT */
ENTRY(_start)
PHDRS {
    boot PT_LOAD FLAGS(5);
    dispatch PT_LOAD FLAGS(5);
    pointer_saved PT_LOAD FLAGS(5);
    pointer_generic PT_LOAD FLAGS(5);
    pointer_publish PT_LOAD FLAGS(5);
    pointer_stub PT_LOAD FLAGS(5);
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
    . = 0x4267b6d0;
    .text.pointer_generic : { *(.text.pointer_generic) } :pointer_generic
    . = 0x42767978;
    .text.writer : { *(.text.writer) } :writer
    . = 0x42767990;
    .text.descriptor : { *(.text.descriptor) } :descriptor
    . = 0x4285f1a8;
    .text.pointer_stub : { *(.text.pointer_stub) } :pointer_stub
    . = 0x428bb120;
    .text.table : { *(.text.table) } :table
    . = 0x42aa31d8;
    .text.pointer_saved : { *(.text.pointer_saved) } :pointer_saved
    . = 0x42aeffdc;
    .text.pointer_publish : { *(.text.pointer_publish) } :pointer_publish
    . = 0x45589390;
    .data.slot : { *(.data.slot) } :slot
    . = 0x47e43430;
    .bss.record (NOLOAD) : { *(.bss.record) } :recordcell
    . = 0x47e5d570;
    .bss.writer (NOLOAD) : { *(.bss.writer) } :cell
    /DISCARD/ : { *(.comment) *(.note*) }
}
