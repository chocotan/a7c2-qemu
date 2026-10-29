/* Exact Backup-sized PCI -> AP transport; synthetic bytes, no firmware/CP proof. */
#include "registers.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

#define BASE UINT64_C(0x403fffff0)
#define SOURCE UINT64_C(0x404000000)
#define DEST UINT64_C(0x4040ed000)
#define BYTES 0x15a8f8U
#define CAPACITY 0x250020U
#define DEST_OFFSET (16U + 0xed000U)

static struct memory {
    unsigned char ap[CAPACITY], pci[CAPACITY];
    size_t pci_limit;
    unsigned writes;
} memory;

static unsigned char *lookup(enum sony_edma_domain domain, uint64_t address, size_t count)
{
    size_t limit = domain == SONY_EDMA_LOCAL ? CAPACITY : memory.pci_limit;
    if (address < BASE || count > limit || address - BASE > limit - count) return NULL;
    return (domain == SONY_EDMA_LOCAL ? memory.ap : memory.pci) + (address - BASE);
}
static int read_bytes(void *opaque, enum sony_edma_domain domain, uint64_t address,
                      void *out, size_t count)
{
    (void)opaque;
    unsigned char *p = lookup(domain, address, count);
    if (!p) return -1;
    memcpy(out, p, count);
    return 0;
}
static int write_bytes(void *opaque, enum sony_edma_domain domain, uint64_t address,
                       const void *in, size_t count)
{
    (void)opaque;
    unsigned char *p = lookup(domain, address, count);
    if (!p) return -1;
    memcpy(p, in, count);
    memory.writes++;
    return 0;
}
static void set(struct sony_edma_registers *r, const struct sony_edma_bus *bus,
                uint32_t offset, uint32_t value)
{
    assert(sony_edma_register(r, bus, offset, &value, 1) == 0);
}
static void set_address(struct sony_edma_registers *r, const struct sony_edma_bus *bus,
                        uint32_t offset, uint64_t address)
{
    set(r, bus, offset, (uint32_t)address);
    set(r, bus, offset + 4, (uint32_t)(address >> 32));
}
static unsigned char pattern(size_t index)
{
    return (unsigned char)(index * 37U + (index >> 8) * 11U + (index >> 16));
}
static void run(uint64_t budget, uint64_t source, size_t available,
                enum sony_edma_result result, size_t copied)
{
    struct sony_edma_registers r;
    struct sony_edma_bus bus = {NULL, read_bytes, write_bytes};
    memset(memory.ap, 0xa5, sizeof memory.ap);
    memset(memory.pci, 0x6b, sizeof memory.pci);
    for (size_t i = 0; i < BYTES; i++) memory.pci[16 + i] = pattern(i);
    memory.pci_limit = available;
    memory.writes = 0;
    sony_edma_reset(&r, 64, budget);
    set(&r, &bus, 0x2c, 1);
    set(&r, &bus, 0x168, 1);
    set(&r, &bus, 0x300, 8);
    set(&r, &bus, 0x308, BYTES);
    set_address(&r, &bus, 0x30c, source);
    set_address(&r, &bus, 0x314, DEST);
    assert(r.status[1] == 0 && !sony_edma_irq(&r));
    set(&r, &bus, 0x30, 0);
    assert(r.last[1][0].result == result && r.last[1][0].bytes == copied);
    assert(r.status[0] == 0);
    assert(r.status[1] == (result == SONY_EDMA_PAUSED ? 1U : 0x10000U));
    assert(!sony_edma_irq(&r));
    assert(memory.writes == (copied + 255) / 256);
    for (size_t i = 0; i < CAPACITY; i++) {
        unsigned char ap_expected = i >= DEST_OFFSET && i - DEST_OFFSET < copied
            ? pattern(i - DEST_OFFSET) : 0xa5;
        unsigned char pci_expected = i >= 16 && i - 16 < BYTES ? pattern(i - 16) : 0x6b;
        assert(memory.ap[i] == ap_expected);
        assert(memory.pci[i] == pci_expected);
    }
    set(&r, &bus, 0xa8, 0);
    assert(sony_edma_irq(&r));
    set(&r, &bus, 0xac, r.status[1]);
    assert(!r.status[1] && !sony_edma_irq(&r));
}
int main(void)
{
    run(0x100000, SOURCE, CAPACITY, SONY_EDMA_BUDGET, 0);
    run(0x200000, SOURCE, CAPACITY, SONY_EDMA_PAUSED, BYTES);
    run(0x200000, UINT64_C(0x804000000), CAPACITY, SONY_EDMA_FAULT, 0);
    run(0x200000, SOURCE, 16 + BYTES - 1, SONY_EDMA_FAULT, BYTES / 256 * 256);
    puts("PASS Backup-sized eDMA: 1419512 bytes, independent same-address domains, AP root/guards/source intact, 1MiB budget rejection, high-address rejection, partial-tail failure abort, IRQ/W1C; NO guest/CP proof");
    return 0;
}
