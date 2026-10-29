#define FIXED_IO_HOST_TEST
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "client.c"
static int initially_present, mapped, map_failure, bad_pid, calls, passed;
int host_present(u64 address)
{
    assert(address == IO_VA || address == IO_VA+4095);
    return initially_present || mapped;
}
u32 host_pid(void) { assert(mapped); return bad_pid ? 0 : 0x30; }
int ioremap_page_range(u64 start, u64 end, u64 physical, u64 protection)
{
    assert(start == IO_VA && end == IO_VA+4096 && physical == IO_PHYSICAL);
    assert(protection == DEVICE_PROTECTION); calls++;
    if (map_failure) return -12;
    mapped = 1; return 0;
}
int printk(const char *format, ...)
{
    if (strstr(format, "FIXED_IO_PASS:") || strstr(format, "FIXED_ATU_MAP_PASS:")) passed++;
    return 0;
}
int main(void)
{
    assert(!init_module() && mapped && calls == 1 && passed == 1);
    mapped = calls = passed = 0; initially_present = 1;
    assert(init_module() == -16 && !calls && !passed);
    initially_present = 0; map_failure = 1;
    assert(init_module() == -12 && !mapped && !passed);
    calls = 0; map_failure = 0; bad_pid = 1;
#ifdef FIXED_ATU_PROFILE
    assert(!init_module() && mapped && passed); /* mapping-only, no PID claim */
#else
    assert(!init_module() && mapped && !passed); /* resident, not accepted */
#endif
    puts("PASS host mapping control only: existing rejected; real mapper failure propagated; no falsePID success");
}
