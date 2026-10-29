/* Independently emitted descriptor from the already established original ABI. */
.section .gnu.linkonce.this_module,"aw",%progbits
.balign 64
.global __this_module
.type __this_module,%object
__this_module:
    .zero 0x18
    .asciz "sony_dw_test_host"
    .org __this_module + 0x158, 0
    .xword init_module
    .org __this_module + 0x300, 0
.size __this_module, . - __this_module

.section .modinfo,"a",%progbits
    .asciz "license=GPL"
    .asciz "description=Owned DW-context host for explicit QEMU TEST peer"
    .asciz "depends="
    .asciz "vermagic=4.9.337-scel+ SMP preempt mod_unload aarch64"
.section .note.GNU-stack,"",%progbits
