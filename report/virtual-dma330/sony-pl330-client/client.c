/* Single-request diagnostic of the ORIGINAL provider, not a DMA implementation.
 * Resident module owns its pages/request until this isolated VM exits. There
 * is no unload callback and a missing completion never permits reclamation.
 */
typedef unsigned long u64;
typedef unsigned int u32;
typedef int s32;
extern u64 __get_free_pages(u32 flags, unsigned order);
extern void free_pages(u64 address, unsigned order);
extern u64 arch_va_to_phys(const void *address);
extern void flush_dcache_all(void);
extern void msleep(unsigned milliseconds);
extern int printk(const char *, ...);

struct descriptor { u32 length, source, destination; };
struct request {
    u32 channel, count, descriptors, unused;
    u64 config;
    void (*callback)(s32, u64);
    u64 cookie;
    u64 internal[3];
};
_Static_assert(sizeof(u64) == 8 && sizeof(struct descriptor) == 12, "native ABI");
_Static_assert(sizeof(struct request) == 0x40, "original request writable extent");
extern int dma330_mem_transfer_async(struct request *request);
static struct request operation;
static u64 pages[3], physical[3];
static volatile u32 callbacks, cookie_valid;
static volatile s32 callback_status;
static const u64 cookie = 0x444d413330334f4bUL;

static void completed(s32 status, u64 received)
{
    callback_status = status;
    cookie_valid = received == cookie;
    callbacks++;
    /* IRQ callback: never sleep, allocate, free, or call the provider. */
}

int __attribute__((section(".init.text"))) init_module(void)
{
    unsigned i, wait;
    int submit;
    int bytes_ok = 1;
    struct descriptor *descriptor;
    /* __GFP_DMA is bit0. Nonblocking allocation with no reclaim flags; the
     * resulting actual address must still pass the original p32 domain below.
     * Only the first 4KiB of an order0 page is consumed (minimum A64 page size).
     */
    for (i = 0; i < 3; i++) {
        pages[i] = __get_free_pages(1, 0);
        if (!pages[i]) break;
        physical[i] = arch_va_to_phys((void *)pages[i]);
        if (physical[i] < 0x400000000UL || physical[i] > 0x4fdfff000UL
            || (physical[i] & 4095)) break;
    }
    if (i != 3 || physical[0] == physical[1] || physical[0] == physical[2]
        || physical[1] == physical[2]) {
        for (i = 0; i < 3; i++) if (pages[i]) free_pages(pages[i], 0);
        printk("\0013DMA_CLIENT_NOT_SUBMITTED: allocation/address refused\n");
        return -19;
    }
    for (i = 0; i < 4096; i++) {
        ((unsigned char *)pages[0])[i] = 0;
        ((unsigned char *)pages[1])[i] = 0x5a;
        ((unsigned char *)pages[2])[i] = 0xa5;
    }
    for (i = 0; i < 256; i++) ((unsigned char *)pages[1])[16+i] = (i*29+7)&255;
    descriptor = (struct descriptor *)pages[0];
    descriptor->length = 256;
    descriptor->source = (u32)(physical[1]+16);
    descriptor->destination = (u32)(physical[2]+16);
    operation.channel = 0;
    operation.count = 1;
    operation.descriptors = (u32)physical[0];
    operation.callback = completed;
    operation.cookie = cookie;
    flush_dcache_all();
    printk("\0016DMA_CLIENT_ADDRESSES desc=%lx source=%lx destination=%lx bytes=256\n",
           physical[0], physical[1], physical[2]);
    printk("\0016DMA_CLIENT_SUBMITTING\n");
    submit = dma330_mem_transfer_async(&operation);
    printk("\0016DMA_CLIENT_SUBMIT_RC=%d\n", submit);
    for (wait = 0; wait < 2000 && !callbacks; wait++) msleep(1);
    if (!callbacks) {
        printk("\0013DMA_CLIENT_PENDING: request/pages retained, do not unload or quit\n");
        return 0;
    }
    /* One-CPU test VM: the interrupted init task resumes after the original
     * IRQ handler returns. Callback never transfers ownership of our pages.
     */
    flush_dcache_all();
    for (i = 0; i < 4096; i++) {
        unsigned char source = (i >= 16 && i < 272) ? ((i-16)*29+7)&255 : 0x5a;
        unsigned char destination = (i >= 16 && i < 272) ? source : 0xa5;
        if (((unsigned char *)pages[1])[i] != source
            || ((unsigned char *)pages[2])[i] != destination) bytes_ok = 0;
    }
    printk("\0016DMA_CLIENT_SETTLED callbacks=%u status=%d cookie=%u submit=%d bytes=%d\n",
           callbacks, callback_status, cookie_valid, submit, bytes_ok);
    if (callbacks == 1 && !callback_status && cookie_valid && !submit && bytes_ok)
        printk("\0016DMA_CLIENT_PASS: original provider callback and 256 bytes; pages still owned\n");
    else
        printk("\0013DMA_CLIENT_FAIL: settled but not verified\n");
    return 0;
}
