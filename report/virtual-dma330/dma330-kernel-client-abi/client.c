/* Independent marker-only diagnostic client; no kernel headers are included. */
extern int printk(const char *format, ...);

int __attribute__((section(".init.text"))) init_module(void)
{
    printk("\0016dma330_abi_diag: marker-only init\n");
    return 0;
}

void __attribute__((section(".exit.text"))) cleanup_module(void)
{
}
