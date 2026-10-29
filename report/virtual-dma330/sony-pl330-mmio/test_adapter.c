#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include "adapter.c"
unsigned char udif_devices[0x300] __attribute__((aligned(8)));
static unsigned char records[18*0x98] __attribute__((aligned(8)));
static unsigned char io[2][0x1000] __attribute__((aligned(8)));
static int map_calls, unmap_calls, fail_map, fail_pid;
int printk(const char *format, ...) { (void)format; return 0; }
void *udif_ioremap(void *opaque)
{
    struct iomem *mapping = opaque;
    int index = map_calls++;
    if (fail_map == index) return 0;
    mapping->virtual = (u64)io[index];
    mapping->flags = 0x80000000U;
    *(u32 *)(io[index]+0xfe0) = fail_pid == index ? 0 : 0x30;
    return io[index];
}
void udif_iounmap(void *opaque)
{
    struct iomem *mapping = opaque;
    assert(mapping->virtual);
    unmap_calls++;
    mapping->virtual = 0;
}
static void setup(void)
{
    unsigned i;
    memset(udif_devices, 0, sizeof udif_devices);
    memset(records, 0, sizeof records); memset(mappings, 0, sizeof mappings);
    *field(udif_devices+0x240, 0) = 0x302d64303333UL;
    *(u32 *)(udif_devices+0x240+0x18) = 18;
    *field(udif_devices+0x240, 0x20) = (u64)records;
    for (i = 0; i < 16; i++) {
        u64 physical = i < 8 ? 0xf1056000UL : 0xf1057000UL;
        *field(records+i*0x98, 8) = physical;
        *field(records+i*0x98, 0x10) = 0x1000;
        *field(records+i*0x98, 0x18) = 0xffffffff00000000UL | physical;
    }
    map_calls = unmap_calls = 0; fail_map = fail_pid = -1;
}
int main(void)
{
    unsigned i;
    unsigned char before[sizeof records];
    setup(); memcpy(before, records, sizeof records);
    assert(init_module() == 0 && map_calls == 2);
    for (i = 0; i < 16; i++) *field(before+i*0x98, 0x18) = (u64)io[i/8];
    assert(!memcmp(before, records, sizeof records));
    setup(); *field(records, 0x40) = 1; assert(init_module() == -16 && !map_calls);
    setup(); *field(records, 8) = 0; assert(init_module() == -22 && !map_calls);
    setup(); *(u32 *)(udif_devices+0x258) = 17; assert(init_module() == -22 && !map_calls);
    setup(); memcpy(before, records, sizeof records); fail_map = 1;
    assert(init_module() == -19 && unmap_calls == 1 && !memcmp(before, records, sizeof records));
    setup(); memcpy(before, records, sizeof records); fail_pid = 1;
    assert(init_module() == -19 && unmap_calls == 2 && !memcmp(before, records, sizeof records));
    puts("PASS: only virtual resource fields changed; late-driver/geometry/count rejected; failed mapping/PID unpublished and rolled back");
}
