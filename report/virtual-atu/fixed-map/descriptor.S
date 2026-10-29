.section .gnu.linkonce.this_module,"aw",%progbits
.balign 64
.global __this_module
.type __this_module,%object
__this_module:
    .zero 0x18
#ifdef FIXED_ATU_PROFILE
    .asciz "sony_atu_map"
#else
    .asciz "sony_fixed_io"
#endif
    .org __this_module + 0x158, 0
    .xword init_module
    .org __this_module + 0x300, 0
.size __this_module, . - __this_module
.section .modinfo,"a",%progbits
    .asciz "license=GPL"
    .asciz "description=Isolated virt fixed board IO mapping diagnostic"
    .asciz "depends="
    .asciz "vermagic=4.9.337-scel+ SMP preempt mod_unload aarch64"
.section .note.GNU-stack,"",%progbits
