/* Host mocks test diagnostic lifecycle only, never hardware/provider success. */
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "client.c"
static int allocations, frees, mode, sleeps, flushes;
static int observed_pass, observed_pending, observed_unsubmitted;
static u64 originals[3];
u64 __get_free_pages(u32 flags, unsigned order)
{
    assert(flags == 1 && order == 0);
    if (mode == 4 && allocations == 1) return 0;
    void *page = aligned_alloc(4096, 4096); assert(page);
    originals[allocations++] = (u64)page;
    return (u64)page;
}
void free_pages(u64 address, unsigned order) { assert(!order); free((void *)address); frees++; }
u64 arch_va_to_phys(const void *address)
{
    unsigned i;
    if (mode == 5) return 0x510000000UL;
    for (i = 0; i < 3; i++) if ((u64)address == originals[i]) return 0x410000000UL+i*0x1000;
    assert(0); return 0;
}
void flush_dcache_all(void) { flushes++; }
void msleep(unsigned milliseconds) { assert(milliseconds == 1); sleeps++; }
int printk(const char *format, ...)
{
    if (strstr(format, "DMA_CLIENT_PASS:")) observed_pass++;
    if (strstr(format, "DMA_CLIENT_PENDING:")) observed_pending++;
    if (strstr(format, "DMA_CLIENT_NOT_SUBMITTED:")) observed_unsubmitted++;
    return 0;
}
int dma330_mem_transfer_async(struct request *request)
{
    struct descriptor *descriptor = (struct descriptor *)originals[0];
    assert(request == &operation && request->count == 1 && request->channel == 0);
    assert(request->descriptors == 0x10000000 && descriptor->source == 0x10001010
           && descriptor->destination == 0x10002010 && descriptor->length == 256);
    assert(flushes == 1);
    if (mode == 1) return 0; /* Return0 without callback must remain pending. */
    if (mode != 3) memcpy((void *)(originals[2]+16), (void *)(originals[1]+16), 256);
    request->callback(mode == 2 ? -5 : 0, request->cookie);
    return 0;
}
static void reset_case(int value)
{
    memset(pages, 0, sizeof pages); memset(physical, 0, sizeof physical);
    memset(originals, 0, sizeof originals); memset(&operation, 0, sizeof operation);
    callbacks = cookie_valid = 0; callback_status = 0;
    allocations = frees = sleeps = flushes = 0;
    observed_pass = observed_pending = observed_unsubmitted = 0; mode = value;
}
int main(void)
{
    int value, i;
    for (value = 0; value < 6; value++) {
        reset_case(value);
        int rc = init_module();
        if (!value) assert(!rc && observed_pass == 1 && callbacks == 1 && !frees);
        if (value == 1) assert(!rc && observed_pending == 1 && sleeps == 2000 && !frees && !observed_pass);
        if (value == 2 || value == 3) assert(!rc && callbacks == 1 && !observed_pass && !frees);
        if (value == 4 || value == 5) assert(rc == -19 && observed_unsubmitted && frees == allocations);
        if (!frees) for (i = 0; i < allocations; i++) free((void *)originals[i]);
    }
    puts("PASS host-client-only: completion/data required; return0 timeout retains owner; error/corruption fail; allocation/address rejected");
}
