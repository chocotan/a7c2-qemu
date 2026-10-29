#define FIXED_IO_HOST_TEST
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "client.c"
static unsigned before,pages,calls,passed,resident;
static int rc,wrong;
int host_translate(u64 address,u64 *physical)
{
    assert(address==IO_VA || address==IO_VA+4096);
    unsigned i=(unsigned)((address-IO_VA)/4096);
    if (!((calls?pages:before)&(1U<<i))) return 0;
    *physical=IO_PHYSICAL+i*4096+(wrong?4096:0);
    return 1;
}
int ioremap_page_range(u64 start,u64 end,u64 physical,u64 protection)
{
    assert(start==IO_VA && end==IO_VA+8192 && physical==IO_PHYSICAL && protection==DEVICE_PROTECTION);
    calls++;return rc;
}
int printk(const char *format,...)
{
    if (strstr(format,"FIXED_PCIDMA_MAP_PASS:")) passed++;
    if (strstr(format,"FIXED_PCIDMA_RESIDENT_UNVERIFIED:")) resident++;
    return 0;
}
static void reset(void) { before=pages=calls=passed=resident=0;rc=wrong=0; }
int main(void)
{
    for (unsigned page=0;page<2;page++) {
        reset();before=1U<<page;assert(init_module()==-16 && !calls && !passed);
    }
    reset();pages=3;assert(!init_module() && calls==1 && passed==1 && !resident);
    reset();rc=-12;assert(init_module()==-12 && !pages && !passed && !resident);
    reset();rc=-12;pages=1;assert(!init_module() && resident && !passed); /* partial failure retains owner */
    reset();pages=1;assert(!init_module() && resident && !passed);
    reset();pages=3;wrong=1;assert(!init_module() && resident && !passed);
    reset();assert(!init_module() && resident && !passed);
    puts("PASS fixed PCI DMA mapping control: two pages/PA, existing/partial/wrong mapping cannot pass; host only");
}
