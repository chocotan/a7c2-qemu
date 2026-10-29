/* ABI facts from actual module metadata; all contents independently emitted. */
.section .gnu.linkonce.this_module,"aw",%progbits
.balign 64
.global __this_module
.type __this_module,%object
__this_module:
    .zero 0x18
    .asciz "dma330_abi_diag"
    .org __this_module + 0x158, 0
    .xword init_module
    .org __this_module + 0x2b8, 0
    .xword cleanup_module
    .org __this_module + 0x300, 0
.size __this_module, . - __this_module

.section .modinfo,"a",%progbits
    .asciz "license=GPL"
    .asciz "description=Independent marker-only local QEMU diagnostic"
    .asciz "depends="
    .asciz "vermagic=4.9.337-scel+ SMP preempt mod_unload aarch64"
.section .note.GNU-stack,"",%progbits
