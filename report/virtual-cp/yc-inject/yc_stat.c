/* Queue-depth probe for the YC injection experiment: reports whether av-cam's
 * VDT queue 0x827e073f still holds our injected 1000:0102 (unprocessed) or was
 * drained (consumed by the service thread). Read-only; no messages sent. */
typedef unsigned int u32;
extern int printk(const char *, ...);
extern long osal_stat_msgq(u32 qid, void *stat_out);

#define Q_VDT_IN 0x827e073fu

int __attribute__((section(".init.text"))) init_module(void)
{
    u32 w[16];
    long rc;
    int i;
    for (i = 0; i < 16; ++i) w[i] = 0xa5a5a5a5u;
    rc = osal_stat_msgq(Q_VDT_IN, w);
    printk("\0016YCSTAT: rc=%ld qid=%#x w=%08x %08x %08x %08x %08x %08x %08x %08x\n",
           rc, Q_VDT_IN, w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7]);
    return 0;
}

void __attribute__((section(".exit.text"))) cleanup_module(void)
{
    printk("\0016YCSTAT: exit\n");
}
