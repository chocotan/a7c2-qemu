#include "jpeg-hardware.h"
#include "jpeg-hardware-codec.h"

#include <stdlib.h>
#include <string.h>

struct reg { uint32_t offset, value; };
struct vjpeg_hw {
    struct vjpeg_callbacks cb;
    void *opaque;
    struct vjpeg_job job;
    struct vjpeg_snapshot snapshot;
    int cancelled, callback;
    struct reg regs[38];
};
static const uint32_t offsets[38] = {
    0,8,0x10,0x14,0x18,0x30,0x38,0x40,0x44,0x4c,0x7c,0x80,0x84,
    0x800,0x804,0x808,0x80c,0x810,0x814,0x818,0x81c,0x820,0x824,
    0x1200,0x1218,0x1298,0x12a0,0x12a4,0x12a8,0x12ac,0x12b0,0x12b4,
    0x12b8,0x12bc,0x12c0,0x12c4,0x1c,0x90
};
static int range(uint64_t address, size_t size)
{
    return size != 0 && size <= UINT64_MAX - address;
}
static int overlaps(uint64_t a, size_t an, uint64_t b, size_t bn)
{
    return a < b + bn && b < a + an;
}
static enum vjpeg_result fault(struct vjpeg_hw *h, enum vjpeg_result r)
{
    h->snapshot.state = VJPEG_FAULT; h->snapshot.result = r;
    h->snapshot.output_length = 0; h->snapshot.fifo_count = 0;
    h->snapshot.events = r == VJPEG_CANCELLED ?
                         VJPEG_EVENT_CANCELLED : VJPEG_EVENT_FAULT;
    return r;
}
static void irq(struct vjpeg_hw *h, unsigned level)
{
    if (h->snapshot.irq_level == level) return;
    h->snapshot.irq_level = level;
    ++h->callback;
    h->cb.irq(h->opaque, VJPEG_DEVICE0_EXTERNAL_IRQ, (int)level);
    --h->callback;
}
struct vjpeg_hw *vjpeg_hw_create(const struct vjpeg_callbacks *cb, void *opaque)
{
    struct vjpeg_hw *h;
    if (cb == NULL || !cb->probe || !cb->read || !cb->write ||
        !cb->acquire || !cb->release || !cb->irq) return NULL;
    h = calloc(1, sizeof(*h));
    if (h == NULL) return NULL;
    h->cb = *cb; h->opaque = opaque;
    for (size_t i = 0; i < 38; ++i) h->regs[i].offset = offsets[i];
    return h;
}
void vjpeg_hw_destroy(struct vjpeg_hw *h)
{
    if (h == NULL || h->callback || h->snapshot.state == VJPEG_RUNNING) return;
    irq(h, 0); free(h);
}
struct vjpeg_snapshot vjpeg_hw_snapshot(const struct vjpeg_hw *h)
{
    if (h == NULL) {
        struct vjpeg_snapshot s = {VJPEG_FAULT, VJPEG_INVALID, 0, 0, 0, 0};
        return s;
    }
    return h->snapshot;
}
enum vjpeg_result vjpeg_hw_prepare(struct vjpeg_hw *h, const struct vjpeg_job *j)
{
    uint8_t prefix[VJPEG_PREFIX_SIZE];
    enum vjpeg_result r;
    if (h == NULL || j == NULL) return VJPEG_INVALID;
    if (h->callback || h->snapshot.state != VJPEG_IDLE ||
        h->snapshot.events || h->snapshot.fifo_count) return VJPEG_BUSY;
    if (j->pixels != VJPEG_RGB888) return fault(h, VJPEG_UNSUPPORTED);
    r = vjpeg_source_prefix(&j->coding, prefix);
    if (r != VJPEG_OK) return fault(h, r);
    if (!range(j->source_address, j->source_size) ||
        !range(j->destination_address, j->destination_capacity) ||
        j->destination_capacity > UINT32_MAX ||
        j->destination_capacity > SIZE_MAX - (VJPEG_PREFIX_SIZE + 16))
        return fault(h, VJPEG_BOUNDS);
    if (overlaps(j->source_address, j->source_size,
                 j->destination_address, j->destination_capacity))
        return fault(h, VJPEG_OVERLAP);
    h->job = *j;
    h->snapshot.state = VJPEG_ARMED; h->snapshot.result = VJPEG_OK;
    return VJPEG_OK;
}
enum vjpeg_result vjpeg_hw_cancel(struct vjpeg_hw *h)
{
    if (h == NULL) return VJPEG_INVALID;
    if (h->snapshot.state == VJPEG_RUNNING) {
        h->cancelled = 1; return VJPEG_OK;
    }
    if (h->callback) return VJPEG_BUSY;
    if (h->snapshot.state == VJPEG_ARMED) return fault(h, VJPEG_CANCELLED);
    return VJPEG_INVALID;
}
enum vjpeg_result vjpeg_hw_ack(struct vjpeg_hw *h, uint32_t events)
{
    if (h == NULL || (events & ~7u)) return VJPEG_INVALID;
    h->snapshot.events &= ~events;
    if (!(h->snapshot.events & VJPEG_EVENT_DONE)) irq(h, 0);
    if (h->snapshot.state != VJPEG_RUNNING &&
        h->snapshot.state != VJPEG_ARMED && !h->snapshot.events &&
        !h->snapshot.fifo_count) h->snapshot.state = VJPEG_IDLE;
    return VJPEG_OK;
}
static int probe(struct vjpeg_hw *h, uint64_t address, size_t size,
                 unsigned access, struct vjpeg_mapping *m)
{
    int result;
    ++h->callback;
    result = h->cb.probe(h->opaque, address, size, access, m);
    --h->callback;
    return result == 0 && m->object != 0 && range(m->offset, size);
}
static enum vjpeg_result frame_valid(const struct vjpeg_frame *f,
                                     const struct vjpeg_job *j)
{
    size_t row, extent;
    if (f->contract != VJPEG_RGB888) return VJPEG_UNSUPPORTED;
    if (f->rgb == NULL || f->width != j->coding.width ||
        f->height != j->coding.height || f->width > SIZE_MAX / 3)
        return VJPEG_INVALID;
    row = f->width * 3;
    if (f->stride < row || f->height - 1 > (SIZE_MAX - row) / f->stride)
        return VJPEG_BOUNDS;
    extent = (f->height - 1) * f->stride + row;
    if (extent > f->size || f->size > j->source_size ||
        f->size > UINTPTR_MAX - (uintptr_t)f->rgb) return VJPEG_BOUNDS;
    return VJPEG_OK;
}
enum vjpeg_result vjpeg_hw_execute(struct vjpeg_hw *h)
{
    struct vjpeg_frame f = {0};
    struct vjpeg_mapping src = {0}, dst = {0};
    enum vjpeg_result r = VJPEG_MEMORY;
    uint8_t check[256], *encoded = NULL;
    size_t offset = 0, length = 0, capacity;
    int acquired = 0, consumed = 0, transferred;
    if (h == NULL) return VJPEG_INVALID;
    if (h->callback || h->snapshot.state == VJPEG_RUNNING ||
        h->snapshot.events || h->snapshot.fifo_count) return VJPEG_BUSY;
    if (h->snapshot.state != VJPEG_ARMED) return fault(h, VJPEG_NEED_DATA);
    h->snapshot.state = VJPEG_RUNNING; h->cancelled = 0;
    if (!probe(h, h->job.source_address, h->job.source_size, VJPEG_READ, &src) ||
        h->cancelled) goto done;
    if (!probe(h, h->job.destination_address, h->job.destination_capacity,
               VJPEG_READ | VJPEG_WRITE, &dst) || h->cancelled) goto done;
    if (src.object == dst.object && overlaps(src.offset, h->job.source_size,
                                           dst.offset, h->job.destination_capacity)) {
        r = VJPEG_OVERLAP; goto done;
    }
    ++h->callback;
    transferred = h->cb.acquire(h->opaque, h->job.source_address,
                               h->job.source_size, &f);
    --h->callback;
    if (transferred != 0) { r = VJPEG_NEED_DATA; goto done; }
    acquired = 1;
    r = frame_valid(&f, &h->job);
    if (r != VJPEG_OK || h->cancelled) goto done;
    capacity = h->job.destination_capacity + VJPEG_PREFIX_SIZE + 16;
    encoded = malloc(capacity);
    if (encoded == NULL) { r = VJPEG_NO_MEMORY; goto done; }
    consumed = 1;
    r = vjpeg_encode(&f, &h->job.coding, encoded, capacity, &offset, &length);
    if (r != VJPEG_OK || h->cancelled) goto done;
    if (length > h->job.destination_capacity || length > UINT32_MAX) {
        r = VJPEG_BOUNDS; goto done;
    }
    ++h->callback;
    transferred = h->cb.write(h->opaque, h->job.destination_address,
                              encoded + offset, length);
    --h->callback;
    if (transferred != 0) { r = VJPEG_MEMORY; goto done; }
    if (h->cancelled) goto done;
    for (size_t i = 0; i < length; ) {
        size_t n = length - i < sizeof(check) ? length - i : sizeof(check);
        ++h->callback;
        transferred = h->cb.read(h->opaque, h->job.destination_address + i,
                                 check, n);
        --h->callback;
        if (transferred != 0) { r = VJPEG_MEMORY; goto done; }
        if (memcmp(check, encoded + offset + i, n)) { r = VJPEG_VERIFY; goto done; }
        if (h->cancelled) goto done;
        i += n;
    }
done:
    if (acquired) {
        ++h->callback; h->cb.release(h->opaque, f.lease, consumed); --h->callback;
    }
    free(encoded);
    if (h->cancelled) r = VJPEG_CANCELLED;
    if (r != VJPEG_OK) return fault(h, r);
    h->snapshot.state = VJPEG_COMPLETE; h->snapshot.result = VJPEG_OK;
    h->snapshot.events = VJPEG_EVENT_DONE;
    h->snapshot.output_length = (uint32_t)length; h->snapshot.fifo_count = 1;
    irq(h, 1);
    return VJPEG_OK;
}
static struct reg *reg_at(struct vjpeg_hw *h, uint32_t offset)
{
    for (size_t i = 0; i < 38; ++i)
        if (h->regs[i].offset == offset) return &h->regs[i];
    return NULL;
}
enum vjpeg_result vjpeg_hw_mmio_read(struct vjpeg_hw *h, uint32_t offset,
                                    unsigned size, uint32_t *value)
{
    struct reg *r;
    uint32_t word, base = offset & ~3u;
    if (h == NULL || value == NULL) return VJPEG_INVALID;
    *value = 0;
    if ((size != 1 && size != 2 && size != 4) || (offset & (size - 1)) ||
        (offset & 3u) + size > 4) return VJPEG_UNSUPPORTED;
    r = reg_at(h, base);
    if (r == NULL) return VJPEG_UNSUPPORTED;
    word = r->value;
    if (base == 8 || base == 0x14 || base == 0x40) word = 0;
    if (base == 0x44) word = h->snapshot.fifo_count;
    if (base == 0x4c) word = h->snapshot.output_length;
    word >>= (offset & 3u) * 8;
    *value = size == 4 ? word : word & ((1u << (size * 8)) - 1);
    return VJPEG_OK;
}
enum vjpeg_result vjpeg_hw_mmio_write(struct vjpeg_hw *h, uint32_t offset,
                                     unsigned size, uint32_t value)
{
    struct reg *r;
    if (h == NULL) return VJPEG_INVALID;
    if (size != 4 || (offset & 3u)) return VJPEG_UNSUPPORTED;
    r = reg_at(h, offset);
    if (r == NULL || offset == 0x10 || offset == 0x44 || offset == 0x4c)
        return VJPEG_UNSUPPORTED;
    if (offset == 0x14) {
        reg_at(h, 0x10)->value &= ~value;
        return VJPEG_OK;
    }
    if (h->callback || h->snapshot.state == VJPEG_RUNNING) return VJPEG_BUSY;
    if (offset == 8) {
        if (value & ~1u) return VJPEG_UNSUPPORTED;
        return value ? vjpeg_hw_execute(h) : VJPEG_OK;
    }
    if (offset == 0x40) {
        if (value != 1 || !h->snapshot.fifo_count) return VJPEG_INVALID;
        h->snapshot.fifo_count = 0; h->snapshot.output_length = 0;
        if (!h->snapshot.events) h->snapshot.state = VJPEG_IDLE;
        return VJPEG_OK;
    }
    if (h->snapshot.events || h->snapshot.fifo_count) return VJPEG_BUSY;
    r->value = value;
    return VJPEG_OK;
}

enum vjpeg_result vjpeg_source_address(uint64_t base, uint32_t canvas_x,
    uint32_t valid_x, uint32_t valid_y, uint32_t target_x, uint32_t target_y,
    uint64_t *address)
{
    uint64_t x = (uint64_t)valid_x + target_x, y = (uint64_t)valid_y + target_y;
    uint64_t samples;
    if (address == NULL || canvas_x == 0) return VJPEG_INVALID;
    if (x > UINT32_MAX || y > UINT32_MAX || y > (UINT64_MAX - x) / canvas_x)
        return VJPEG_BOUNDS;
    samples = y * canvas_x + x;
    if (samples > (UINT64_MAX - base) / 2) return VJPEG_BOUNDS;
    *address = base + 2 * samples;
    return VJPEG_OK;
}
enum vjpeg_result vjpeg_phys_to_aif(uint64_t physical, struct vjpeg_aif *aif)
{
    uint64_t address;
    if (aif == NULL) return VJPEG_INVALID;
    if (physical < UINT64_C(0x200000000)) address = physical + UINT64_C(0x400000000);
    else if (physical >= UINT64_C(0x3fe000000) && physical < UINT64_C(0x3fe6c0000))
        address = physical - UINT64_C(0x300000000);
    else return VJPEG_UNSUPPORTED;
    aif->high = (uint32_t)((address >> 24) & UINT32_C(0xffffff00));
    aif->low = (uint32_t)address;
    return VJPEG_OK;
}
enum vjpeg_result vjpeg_aif_to_phys(struct vjpeg_aif aif, size_t span,
                                   uint64_t *physical)
{
    uint64_t a = ((uint64_t)aif.high << 24) | aif.low, p, end;
    if (physical == NULL) return VJPEG_INVALID;
    if ((aif.high & 255u) || !range(a, span)) return VJPEG_BOUNDS;
    end = a + span;
    if (a >= UINT64_C(0x400000000) && end <= UINT64_C(0x500000000))
        p = a - UINT64_C(0x400000000);
    else if (a >= UINT64_C(0x500000000) && end <= UINT64_C(0x600000000))
        p = a - UINT64_C(0x400000000);
    else if (a >= UINT64_C(0xfe000000) && end <= UINT64_C(0xfe6c0000))
        p = a + UINT64_C(0x300000000);
    else return VJPEG_UNSUPPORTED;
    *physical = p;
    return VJPEG_OK;
}
enum vjpeg_result vjpeg_output_layout(uint64_t base, uint32_t offset,
                                      uint32_t capacity, struct vjpeg_output *out)
{
    struct vjpeg_output v;
    uint64_t available, physical;
    enum vjpeg_result r;
    if (out == NULL) return VJPEG_INVALID;
    if (capacity <= VJPEG_NATIVE_HEADER_SIZE ||
        base > UINT64_MAX - offset - VJPEG_NATIVE_HEADER_SIZE)
        return VJPEG_BOUNDS;
    v.effective = base + offset + VJPEG_NATIVE_HEADER_SIZE;
    v.aligned = v.effective & ~UINT64_C(15);
    v.skip = (uint16_t)(v.effective - v.aligned);
    available = (uint64_t)capacity - VJPEG_NATIVE_HEADER_SIZE + v.skip;
    v.dma_capacity = (uint32_t)(available & ~UINT64_C(15));
    if (v.dma_capacity <= v.skip) return VJPEG_BOUNDS;
    v.threshold = capacity > 0x63du ? capacity - 0x63du : 0;
    r = vjpeg_phys_to_aif(v.aligned, &v.aif);
    if (r != VJPEG_OK) return r;
    r = vjpeg_aif_to_phys(v.aif, v.dma_capacity, &physical);
    if (r != VJPEG_OK || physical != v.aligned) return VJPEG_BOUNDS;
    *out = v;
    return VJPEG_OK;
}
