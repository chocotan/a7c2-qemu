.section .gnu.linkonce.this_module,"aw",%progbits
.balign 64
.global __this_module
.type __this_module,%object
__this_module:
    .zero 0x18
    .asciz "sony_udate_distribution"
    .org __this_module + 0x158, 0
    .xword init_module
    .org __this_module + 0x300, 0
.size __this_module, . - __this_module
.section .modinfo,"a",%progbits
    .asciz "license=GPL"
    .asciz "depends=osal_uipc"
    .asciz "description=UDATE public endpoint with opt-in guarded Backup PCI fixture; not CP firmware"
    .asciz "vermagic=4.9.337-scel+ SMP preempt mod_unload aarch64"
.section .rodata,"a",%progbits
.global backup_param_name
backup_param_name:
    .asciz "backup_model"
.section __param,"a",%progbits
.balign 8
    .xword backup_param_name
    .xword __this_module
    .xword param_ops_bool
    .hword 0
    .byte -1
    .byte 0
    .word 0
    .xword backup_model
.section .note.GNU-stack,"",%progbits
