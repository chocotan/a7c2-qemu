#include "atu_core.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static unsigned char endpoint[4096];
static int calls;
static const uint64_t pci_base = 0x10004000000UL;
static int access_peer(void *opaque, uint64_t target, void *bytes, size_t size, int write)
{
    assert(opaque == endpoint);
    if (target < pci_base || target-pci_base > sizeof endpoint
        || size > sizeof endpoint-(target-pci_base)) return -1;
    calls++;
    if (write) memcpy(endpoint+(target-pci_base), bytes, size);
    else memcpy(bytes, endpoint+(target-pci_base), size);
    return 0;
}
static void reg(struct sony_atu *atu, unsigned offset, uint32_t value)
{
    assert(!sony_atu_register(atu, offset, &value, 1));
}
static void map(struct sony_atu *atu, unsigned slot, uint64_t target)
{
    unsigned base = slot*512;
    reg(atu, base+0x14, target); reg(atu, base+0x18, target >> 32);
    reg(atu, base+8, 0xc0000000); reg(atu, base+0xc, 0);
    reg(atu, base+0x10, 0xc00fffff); reg(atu, base+0x20, 0);
    reg(atu, base+4, 0x80000000U);
}
int main(void)
{
    struct sony_atu state;
    unsigned char input[256], output[256];
    uint64_t target = 0x1234; unsigned slot = 99, i;
    sony_atu_reset(&state);
    assert(sony_atu_translate(&state, 0xc0000000, 1, &target, &slot) && target == 0x1234);
    map(&state, 7, pci_base);
    for (i = 0; i < sizeof input; i++) input[i] = (i*31+3)&255;
    assert(!sony_atu_transfer(&state, 0xc0000010, input, sizeof input, 1, access_peer, endpoint));
    assert(!sony_atu_transfer(&state, 0xc0000010, output, sizeof output, 0, access_peer, endpoint));
    assert(!memcmp(input, output, sizeof input) && calls == 2);
    assert(!endpoint[15] && !endpoint[272]);
    assert(sony_atu_translate(&state, 0xc00fffff, 2, &target, &slot));
    assert(sony_atu_transfer(&state, 0xc0001000, output, 1, 0, access_peer, endpoint));
    map(&state, 0, pci_base); assert(sony_atu_translate(&state, 0xc0000010, 1, &target, &slot));
    reg(&state, 4, 0); reg(&state, 7*512+4, 0);
    assert(sony_atu_transfer(&state, 0xc0000010, output, 1, 0, access_peer, endpoint) && calls == 2);
    map(&state, 2, UINT64_MAX-7); assert(sony_atu_translate(&state, 0xc0000010, 1, &target, &slot));
    assert(sony_atu_translate(&state, 0xdfffffff, 2, &target, &slot));
    puts("PASS virtualATUcore: enabled slot7,64bit target,real owned backing read/write,guards,unmap/cross/overflow/ambiguous reject");
}
