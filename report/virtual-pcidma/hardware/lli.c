#include "lli.h"
#include <limits.h>

static uint32_t le32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static uint64_t le64(const unsigned char *p) { return le32(p) | (uint64_t)le32(p+4)<<32; }
static int span(uint64_t address, uint64_t size)
{
    return size && address <= UINT64_MAX-(size-1);
}

struct sony_edma_outcome sony_edma_copy(const struct sony_edma_bus *bus,
    uint64_t source, uint64_t target, uint32_t length, unsigned write_direction,
    uint64_t max_bytes)
{
    struct sony_edma_outcome out = { .result=SONY_EDMA_BAD_INPUT };
    unsigned char bytes[256];
    if (!bus || !bus->read || !bus->write || write_direction>1 || !max_bytes) return out;
    out.result = SONY_EDMA_FAULT;
    if (!span(source,length) || !span(target,length)) return out;
    if (length>max_bytes) { out.result=SONY_EDMA_BUDGET; return out; }
    enum sony_edma_domain src = write_direction ? SONY_EDMA_LOCAL : SONY_EDMA_PCI;
    enum sony_edma_domain dst = write_direction ? SONY_EDMA_PCI : SONY_EDMA_LOCAL;
    for (uint32_t offset=0; offset<length;) {
        size_t size = length-offset < sizeof bytes ? length-offset : sizeof bytes;
        if (bus->read(bus->opaque,src,source+offset,bytes,size)) return out;
        if (bus->write(bus->opaque,dst,target+offset,bytes,size)) {
            out.write_fault=1;
            return out;
        }
        out.bytes += size;
        offset += size;
    }
    out.result=SONY_EDMA_PAUSED;
    return out;
}

struct sony_edma_outcome sony_edma_consume(const struct sony_edma_bus *bus,
    uint64_t list, unsigned phase, unsigned write_direction, unsigned max_steps,
    uint64_t max_bytes)
{
    struct sony_edma_outcome out = { .result=SONY_EDMA_BAD_INPUT, .next=list, .phase=phase };
    unsigned interrupt = 0;
    if (!bus || !bus->read || !bus->write || phase>1 || write_direction>1 || !max_steps || !max_bytes)
        return out;
    for (unsigned step=0; step<max_steps; step++) {
        unsigned char record[24];
        out.result = SONY_EDMA_FAULT;
        if (!span(out.next, 4) || bus->read(bus->opaque, SONY_EDMA_LOCAL, out.next, record, 4)) return out;
        uint32_t control = le32(record);
        if ((control&1) != out.phase) {
            out.result = SONY_EDMA_PAUSED;
            out.local_interrupt = interrupt;
            return out;
        }
        /* Only the original local-IRQ subset is implemented. RIE needs real
         * remote interrupt writes and is not silently accepted as local LIE.
         */
        if (control&~15U || ((control&2) && !(control&4)) || ((control&4) && (control&8))) {
            out.result = SONY_EDMA_UNSUPPORTED;
            return out;
        }
        if (control&4) {
            if (!span(out.next, 16) || bus->read(bus->opaque, SONY_EDMA_LOCAL, out.next+4, record+4, 12)) return out;
            if (control&2) out.phase ^= 1;
            out.next = le64(record+8);
            out.entries++;
            continue;
        }
        if (!span(out.next, 24) || bus->read(bus->opaque, SONY_EDMA_LOCAL, out.next+4, record+4, 20)) return out;
        uint32_t length = le32(record+4);
        uint64_t source = le64(record+8), target = le64(record+16);
        if (!span(source, length) || !span(target, length)) return out;
        if (length>max_bytes-out.bytes) { out.result=SONY_EDMA_BUDGET; return out; }
        struct sony_edma_outcome copied = sony_edma_copy(bus,source,target,length,write_direction,max_bytes-out.bytes);
        out.bytes += copied.bytes;
        if (copied.result != SONY_EDMA_PAUSED) {
            out.result=copied.result; out.write_fault=copied.write_fault; return out;
        }
        interrupt |= !!(control&8);
        out.entries++;
        if (out.next>UINT64_MAX-24) return out;
        out.next += 24;
    }
    out.result = SONY_EDMA_BUDGET;
    return out;
}
