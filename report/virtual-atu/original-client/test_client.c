/* Control/error tests only. A shared host page exercises diagnostic branches;
 * it does not model an ATU, PCI transactions, or original-provider execution.
 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
static unsigned long control_base;
#define ATU_CTRL_BASE control_base
#include "client.c"

enum scenario {
    GOOD, MAP_NEGATIVE, BAD_SLOT, BAD_PHYSICAL, AP_NULL, AP_PARTIAL,
    AP_MISMATCH, AP_UNALIGNED, PEER_NULL, PEER_PARTIAL, PEER_MISMATCH,
    INITIAL_PAYLOAD, INITIAL_GUARD_FIRST, INITIAL_GUARD_LAST,
    CHANGED_PAYLOAD, CHANGED_GUARD_FIRST, CHANGED_GUARD_LAST,
    NO_ALIAS, UNMAP_NEGATIVE, UNMAP_POSITIVE, ENABLE_STUCK
};
static enum scenario scenario;
static s32 map_result, unmap_result;
static u64 map_physical;
static unsigned char *page, *other_page;
static u32 controls[8][128], before_controls[8][128];
static unsigned maps, unmaps, iomaps, iounmaps, initialized, initial_pass;
static unsigned written, data_pass, passed, uncertain, released, not_mapped, failures;
static unsigned ctrl_logs;

s32 pciatu_map(u64 pci, u64 *physical, u32 size, const struct atu_option *option)
{
    assert(++maps == 1 && pci == 0x04000000UL && size == MAP_BYTES && !option);
    assert(physical && *physical == 0);
    if (map_result >= 0) *physical = map_physical;
    return map_result;
}

s32 pciatu_unmap(u32 slot)
{
    assert(++unmaps == 1 && slot == (u32)map_result && slot < 8);
    if (!unmap_result && scenario != ENABLE_STUCK) controls[slot][1] &= 0x7fffffffU;
    if (unmap_result) control_base = 0; /* Any forbidden ctrl read after error faults. */
    /* No CPU access to either alias is permitted after this point in this test. */
    assert(mprotect(page, PAGE_BYTES, PROT_NONE) == 0);
    assert(mprotect(other_page, PAGE_BYTES, PROT_NONE) == 0);
    return unmap_result;
}

void *udif_ioremap(void *object)
{
    struct iomem *resource = object;
    iomaps++;
    assert(resource->size == PAGE_BYTES && resource->flags == 0 && !resource->virtual);
    if (resource == &aperture) {
        assert(iomaps == 1 && resource->physical == map_physical);
        assert(!memcmp(resource->name, "atu-ap\0\0", 8));
        if (scenario == AP_NULL) return 0;
        resource->virtual = (u64)(scenario == NO_ALIAS ? other_page : page);
        if (scenario == AP_PARTIAL) return 0;
        if (scenario == AP_MISMATCH) return other_page;
        if (scenario == AP_UNALIGNED) resource->virtual++;
    } else {
        assert(resource == &peer && iomaps == 2 && resource->physical == 0x600000000UL);
        assert(!memcmp(resource->name, "atupeer\0", 8));
        if (scenario == PEER_NULL) return 0;
        resource->virtual = (u64)page;
        if (scenario == PEER_PARTIAL) return 0;
        if (scenario == PEER_MISMATCH) return other_page;
    }
    return (void *)resource->virtual;
}

void udif_iounmap(void *object)
{
    struct iomem *resource = object;
    assert(!initialized && !unmaps && resource->virtual);
    iounmaps++;
    resource->virtual = 0;
}

int printk(const char *format, ...)
{
    if (strstr(format, "ATU_CLIENT_PEER_INITIALIZED:")) {
        initialized++;
        if (scenario == INITIAL_PAYLOAD) page[PAYLOAD_START + 31] ^= 1;
        if (scenario == INITIAL_GUARD_FIRST) page[0] ^= 1;
        if (scenario == INITIAL_GUARD_LAST) page[PAGE_BYTES - 1] ^= 1;
    }
    if (strstr(format, "ATU_CLIENT_APERTURE_READ_PASS:")) initial_pass++;
    if (strstr(format, "ATU_CLIENT_APERTURE_WRITTEN:")) {
        written++;
        if (scenario == CHANGED_PAYLOAD) page[PAYLOAD_START + 127] ^= 1;
        if (scenario == CHANGED_GUARD_FIRST) page[0] ^= 1;
        if (scenario == CHANGED_GUARD_LAST) page[PAGE_BYTES - 1] ^= 1;
    }
    if (strstr(format, "ATU_CLIENT_DATA_PASS:")) data_pass++;
    if (strstr(format, "ATU_CLIENT_PASS:")) passed++;
    if (strstr(format, "ATU_CLIENT_OWNER_UNCERTAIN:")) uncertain++;
    if (strstr(format, "ATU_CLIENT_OWNER_RELEASED:")) released++;
    if (strstr(format, "ATU_CLIENT_NOT_MAPPED:")) not_mapped++;
    if (strstr(format, "ATU_CLIENT_FAIL:")) failures++;
    if (strstr(format, "ATU_CLIENT_CTRL_AFTER_UNMAP=")) ctrl_logs++;
    return 0;
}

static void run_case(enum scenario value, s32 slot, u64 physical)
{
    unsigned i, j;
    scenario = value; map_result = slot; map_physical = physical;
    unmap_result = value == UNMAP_NEGATIVE ? -1 : value == UNMAP_POSITIVE ? 1 : 0;
    maps = unmaps = iomaps = iounmaps = initialized = initial_pass = 0;
    written = data_pass = passed = uncertain = released = not_mapped = failures = ctrl_logs = 0;
    aperture.physical = aperture.virtual = peer.virtual = 0;
    page = mmap(0, PAGE_BYTES, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    other_page = mmap(0, PAGE_BYTES, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(page != MAP_FAILED && other_page != MAP_FAILED);
    memset(page, 0x69, PAGE_BYTES); memset(other_page, 0x37, PAGE_BYTES);
    for (i = 0; i < 8; i++) for (j = 0; j < 128; j++)
        controls[i][j] = 0x89abcdefU ^ (i * 0x1000U + j);
    memcpy(before_controls, controls, sizeof controls);
    control_base = (u64)controls;
    assert(init_module() == 0 && maps == 1);
    if (value == MAP_NEGATIVE) {
        assert(not_mapped == 1 && !unmaps && !iomaps && !uncertain && !passed);
    } else if (value == BAD_SLOT) {
        assert(uncertain == 1 && !unmaps && !iomaps && !passed && !ctrl_logs);
    } else {
        assert(unmaps == 1);
        assert(!passed || (data_pass && initial_pass && written && released));
        if (value == UNMAP_NEGATIVE || value == UNMAP_POSITIVE || value == ENABLE_STUCK) {
            assert(uncertain == 1 && !released && !passed && data_pass == 1);
            assert(ctrl_logs == (value == ENABLE_STUCK));
        } else {
            assert(!uncertain && released == 1 && ctrl_logs == 1);
        }
        if (value == GOOD) {
            assert(passed == 1 && data_pass == 1 && !iounmaps && !failures);
            assert(aperture.virtual && peer.virtual); /* Established resources retained. */
        }
        if (value == BAD_PHYSICAL) assert(!iomaps && !initialized && !passed && failures == 1);
        if (value >= AP_NULL && value <= PEER_MISMATCH) {
            unsigned expected_rollback = value == AP_NULL ? 0 :
                (value == PEER_PARTIAL || value == PEER_MISMATCH) ? 2 : 1;
            assert(iounmaps == expected_rollback && !initialized && !passed && failures == 1);
            assert(!aperture.virtual && !peer.virtual);
            assert(iomaps == (value >= PEER_NULL ? 2U : 1U));
        }
        if ((value >= INITIAL_PAYLOAD && value <= INITIAL_GUARD_LAST) || value == NO_ALIAS)
            assert(initialized == 1 && !initial_pass && !written && !data_pass && !passed && !iounmaps);
        if (value >= CHANGED_PAYLOAD && value <= CHANGED_GUARD_LAST)
            assert(initial_pass == 1 && written == 1 && !data_pass && !passed && !iounmaps);
        assert(mprotect(page, PAGE_BYTES, PROT_READ | PROT_WRITE) == 0);
        assert(mprotect(other_page, PAGE_BYTES, PROT_READ | PROT_WRITE) == 0);
        if (value == GOOD) {
            for (i = 0; i < PAGE_BYTES; i++) {
                assert(page[i] == expected(i, 1));
                assert(other_page[i] == 0x37);
            }
        }
    }
    for (i = 0; i < 8; i++) for (j = 0; j < 128; j++) {
        u32 want = before_controls[i][j];
        if (unmaps && !unmap_result && value != ENABLE_STUCK && i == (u32)slot && j == 1)
            want &= 0x7fffffffU;
        assert(controls[i][j] == want);
    }
    assert(munmap(page, PAGE_BYTES) == 0 && munmap(other_page, PAGE_BYTES) == 0);
}

int main(void)
{
    unsigned cases = 0, i;
    s32 negative;
    const u64 rejected[] = {0, 0xbff00000UL, 0xe0000000UL, 0xdff00001UL,
                             0xc0001000UL, ~0UL};
    for (i = 0; i < 8; i++) { run_case(GOOD, (s32)i, i & 1 ? 0xdff00000UL : 0xc0000000UL); cases++; }
    for (negative = -1; negative >= -5; negative--) { run_case(MAP_NEGATIVE, negative, 0); cases++; }
    run_case(BAD_SLOT, 8, 0xc0000000UL); cases++;
    run_case(BAD_SLOT, 0x7fffffff, 0xc0000000UL); cases++;
    for (i = 0; i < sizeof rejected / sizeof rejected[0]; i++) {
        run_case(BAD_PHYSICAL, 3, rejected[i]); cases++;
    }
    for (i = AP_NULL; i <= ENABLE_STUCK; i++) {
        run_case((enum scenario)i, 5, 0xc0000000UL); cases++;
    }
    printf("PASS_HOST_CONTROL_ONLY: %u cases, ASan/UBSan; no hardware/provider proof\n", cases);
    puts("Checked: slot/window bounds, NULL/no-wait ABI, own 4KiB IOMEM, setup rollback,");
    puts("guard/payload failures, absent alias, release errors/stuck enable, retained owner,");
    puts("all 8 slots/untouched neighbors, no CPU access after unmap (PROT_NONE).\n");
    return 0;
}
