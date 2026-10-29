.section .gnu.linkonce.this_module,"aw",%progbits
.balign 64
.global __this_module
.type __this_module,%object
__this_module:
    .zero 0x18
    .asciz "yc_inject"
    .org __this_module + 0x158, 0
    .xword init_module
    .org __this_module + 0x2b8, 0
    .xword 0
    .org __this_module + 0x300, 0
.size __this_module, . - __this_module
.section .modinfo,"a",%progbits
    .asciz "license=GPL"
    .asciz "depends=osal_uipc"
    .asciz "description=YC IN1 synthetic-frame injection diagnostic (not a real CMOS)"
    .asciz "vermagic=4.9.337-scel+ SMP preempt mod_unload aarch64"
.section .note.GNU-stack,"",%progbits
