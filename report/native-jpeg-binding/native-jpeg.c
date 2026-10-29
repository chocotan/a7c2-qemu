#include "native-jpeg.h"

#include <stdlib.h>
#include <string.h>

#define WORDS (0x2454u / 4u)
struct njpeg_binding {
    uint32_t word[WORDS];
    uint8_t written[WORDS];
    enum vjpeg_result result;
};
static const uint16_t scalar[] = {
    0,4,8,0x10,0x14,0x18,0x1c,0x30,0x38,0x40,0x44,0x4c,
    0x7c,0x80,0x84,0x90,0xa0,0xa4,0xac,0xb0,0xb4,0xb8,
    0x400,0x4c0,0x500,0x870,0x1000,0x1008,0x1010,0x1018,
    0x1200,0x1208,0x1218,0x1280,0x1288,0x1298,0x2450
};
static const uint8_t zigzag[64] = {
    0,1,8,16,9,2,3,10,17,24,32,25,18,11,4,5,
    12,19,26,33,40,48,41,34,27,20,13,6,7,14,21,28,
    35,42,49,56,57,50,43,36,29,22,15,23,30,37,44,51,
    58,59,52,45,38,31,39,46,53,60,61,54,47,55,62,63
};
struct table_slice { uint16_t mmio, prefix, size; };
/* K2aaa8c -> K2a43a4: no table-info byte is transferred to the ASIC. */
static const struct table_slice huffman[] = {
    {0x600,141,16},{0x610,157,12},{0x620,170,16},{0x630,186,162},
    {0x700,349,16},{0x710,365,12},{0x720,378,16},{0x730,394,162}
};
static int between(uint32_t x, uint32_t lo, uint32_t hi)
{
    return x >= lo && x <= hi;
}
static int known(uint32_t o)
{
    if (o & 3u) return 0;
    for (size_t i = 0; i < sizeof(scalar) / sizeof(scalar[0]); ++i)
        if (o == scalar[i]) return 1;
    return between(o,0x200,0x23c) || between(o,0x280,0x2bc) ||
           between(o,0x600,0x618) || between(o,0x620,0x6d0) ||
           between(o,0x700,0x718) || between(o,0x720,0x7d0) ||
           between(o,0x800,0x824) || between(o,0x12a0,0x12c4) ||
           between(o,0x2400,0x2408) || between(o,0x2410,0x2418) ||
           between(o,0x2420,0x2428) || between(o,0x2430,0x2438) ||
           between(o,0x2440,0x2448);
}
static enum vjpeg_result lane(uint32_t o, unsigned size, uint32_t word,
                               uint32_t *value)
{
    if (value == NULL) return VJPEG_INVALID;
    *value = 0;
    if ((size != 1 && size != 2 && size != 4) ||
        (o & (size - 1u)) || (o & 3u) + size > 4)
        return VJPEG_UNSUPPORTED;
    word >>= 8u * (o & 3u);
    *value = size == 4 ? word : word & ((1u << (size * 8u)) - 1u);
    return VJPEG_OK;
}
static uint32_t at(const struct njpeg_binding *h, uint32_t o)
{
    return h->word[o / 4];
}
struct njpeg_binding *njpeg_create(void)
{
    return calloc(1, sizeof(struct njpeg_binding));
}
void njpeg_destroy(struct njpeg_binding *h) { free(h); }
enum vjpeg_result njpeg_last_result(const struct njpeg_binding *h)
{
    return h == NULL ? VJPEG_INVALID : h->result;
}
enum vjpeg_result njpeg_mmio_read(const struct njpeg_binding *h, uint32_t o,
                                  unsigned size, uint32_t *value)
{
    uint32_t word;
    if (h == NULL || value == NULL) return VJPEG_INVALID;
    *value = 0;
    if (!known(o & ~3u)) return VJPEG_UNSUPPORTED;
    word = at(h, o & ~3u);
    /* No unproved operation can publish native status, length or IRQ. */
    if (between(o & ~3u,4,0x14) || (o & ~3u) == 0x40 ||
        (o & ~3u) == 0x44 || (o & ~3u) == 0x4c) word = 0;
    return lane(o, size, word, value);
}
enum vjpeg_result njpeg_mmio_write(struct njpeg_binding *h, uint32_t o,
                                   unsigned size, uint32_t value)
{
    struct njpeg_configuration c;
    enum vjpeg_result r;
    if (h == NULL) return VJPEG_INVALID;
    if (size != 4 || !known(o)) return VJPEG_UNSUPPORTED;
    if (o == 0x10 || o == 0x44 || o == 0x4c || o == 4)
        return VJPEG_UNSUPPORTED;
    if (o == 0x14) return VJPEG_OK; /* W1C of an empty native latch. */
    if (o == 0x40) return VJPEG_INVALID; /* No native FIFO entry exists. */
    if (o == 8) {
        if (value & ~1u) return VJPEG_UNSUPPORTED;
        if (!value) return VJPEG_OK;
        r = njpeg_resolve(h, &c);
        if (r == VJPEG_OK && c.gaps) r = VJPEG_NEED_DATA;
        /* shortcut: native packing/scan and a coherent logical-size snapshot
         * remain required; connect the codec only with source and lease evidence. */
        h->result = r == VJPEG_OK ? VJPEG_UNSUPPORTED : r;
        return h->result;
    }
    /* Require complete uploads after the original driver's control writes;
     * stale words from an earlier snapshot cannot complete a partial upload. */
    if (o == 0xac && value == 0)
        for (unsigned i = 0; i < 64; i += 4) {
            h->written[(0x200 + i) / 4] = 0;
            h->written[(0x280 + i) / 4] = 0;
        }
    if (o == 0x4c0 && value == 1)
        for (size_t t = 0; t < sizeof(huffman) / sizeof(huffman[0]); ++t)
            for (unsigned i = 0; i < huffman[t].size; i += 4)
                h->written[(huffman[t].mmio + i) / 4] = 0;
    h->word[o / 4] = value; h->written[o / 4] = 1;
    return VJPEG_OK;
}
static enum vjpeg_result tables(const struct njpeg_binding *h,
                                struct vjpeg_coding *c)
{
    uint8_t prefix[VJPEG_PREFIX_SIZE];
    for (unsigned t = 0; t < 2; ++t) {
        uint32_t base = t ? 0x280u : 0x200u;
        for (unsigned z = 0; z < 64; ++z) {
            unsigned i = zigzag[z];
            if (!h->written[(base + (i & ~3u)) / 4]) return VJPEG_NEED_DATA;
            c->quant_zigzag[t][z] = (uint8_t)(at(h,base + (i & ~3u)) >>
                                                         (8u * (i & 3u)));
            if (!c->quant_zigzag[t][z]) return VJPEG_INVALID;
        }
    }
    if (vjpeg_source_prefix(c, prefix) != VJPEG_OK) return VJPEG_INVALID;
    for (size_t t = 0; t < sizeof(huffman) / sizeof(huffman[0]); ++t) {
        const struct table_slice *s = &huffman[t];
        for (unsigned i = 0; i < s->size; i += 4) {
            uint32_t expected = 0;
            if (!h->written[(s->mmio + i) / 4]) return VJPEG_NEED_DATA;
            for (unsigned j = 0; j < 4 && i + j < s->size; ++j)
                expected |= (uint32_t)prefix[s->prefix + i + j] << (8u * j);
            if (at(h,s->mmio + i) != expected) return VJPEG_UNSUPPORTED;
        }
    }
    return VJPEG_OK;
}
enum vjpeg_result njpeg_resolve(const struct njpeg_binding *h,
                                struct njpeg_configuration *out)
{
    static const uint16_t required[] = {
        0,0x18,0x30,0x38,0x7c,0x80,0x84,0x90,0xa0,0xa4,0xac,0xb0,
        0xb4,0xb8,0x400,0x4c0,0x500,0x870,0x1008,0x1200,0x1218,0x1298,
        0x800,0x804,0x808,0x80c,0x810,0x814,0x818,0x81c,0x820,0x824,
        0x12a0,0x12a4,0x12a8,0x12ac,0x12b0,0x12b4,0x12b8,0x12bc,
        0x12c0,0x12c4
    };
    struct njpeg_configuration c = {0};
    struct vjpeg_aif aif;
    enum vjpeg_result r;
    uint64_t stride, access, span;
    if (h == NULL || out == NULL) return VJPEG_INVALID;
    memset(out, 0, sizeof(*out));
    for (size_t i = 0; i < sizeof(required) / sizeof(required[0]); ++i)
        if (!h->written[required[i] / 4]) return VJPEG_NEED_DATA;
    if (at(h,0) || at(h,0x30) || at(h,0x38) || at(h,0x7c) ||
        at(h,0xa0) != 1 || at(h,0xa4) || at(h,0xac) || at(h,0xb0) != 1 ||
        at(h,0xb4) != 16 || at(h,0xb8) != 16 || at(h,0x4c0) != 1 ||
        at(h,0x500) != 0x3c || at(h,0x870) != 1 ||
        (at(h,0x1008) & ~0x10u) || (at(h,0x1200) & ~0x2000u) ||
        (at(h,0x1280) != 0 && at(h,0x1280) != 3))
        return VJPEG_UNSUPPORTED;
    /* K2a5404 writes these three gates in order before B+8. */
    if (at(h,0x1008) || at(h,0x1200) || at(h,0x1280)) {
        if (!h->written[0x1280 / 4] || at(h,0x1008) != 0x10 ||
            at(h,0x1200) != 0x2000 || at(h,0x1280) != 3)
            return VJPEG_NEED_DATA;
    }
    c.coding.contract = VJPEG_SOURCE_HEADER_422;
    c.coding.width = at(h,0x84); c.coding.height = at(h,0x80);
    if (!c.coding.width || !c.coding.height || c.coding.width > 65500 ||
        c.coding.height > 65500 || (c.coding.width & 15u) ||
        (c.coding.height & 7u)) return VJPEG_BOUNDS;
    r = tables(h,&c.coding);
    if (r != VJPEG_OK) return r;
    stride = (uint64_t)at(h,0x808) + 256u;
    access = ((uint64_t)at(h,0x814) + 1u) * 128u;
    if (stride > UINT32_MAX || access > UINT32_MAX / 2u ||
        (stride & 255u) || access < c.coding.width || 2u * access > stride ||
        at(h,0x804) != 256 || at(h,0x80c) != 7 ||
        at(h,0x810) != (uint32_t)(0u - 7u * stride) ||
        at(h,0x818) != stride - 2u * access ||
        at(h,0x81c) != c.coding.height / 8u - 1u ||
        at(h,0x820) || at(h,0x824)) return VJPEG_UNSUPPORTED;
    span = (c.coding.height - 1u) * stride + 2u * access;
    if (span > SIZE_MAX) return VJPEG_BOUNDS;
    aif.high = at(h,0x1218); aif.low = at(h,0x800);
    r = vjpeg_aif_to_phys(aif,(size_t)span,&c.source_address);
    if (r != VJPEG_OK) return r;
    if (c.source_address & 15u) return VJPEG_BOUNDS;
    c.source_dma_span = span; c.source_stride = (uint32_t)stride;
    c.source_access_width = (uint32_t)access;
    c.destination_dma_capacity = at(h,0x12a4);
    if ((c.destination_dma_capacity & 15u) ||
        at(h,0x400) > 15 || c.destination_dma_capacity <= at(h,0x400) ||
        (at(h,0x12a0) & 15u)) return VJPEG_BOUNDS;
    if (at(h,0x12a8) || at(h,0x12ac) ||
        at(h,0x12b0) != 0u - c.destination_dma_capacity ||
        at(h,0x12b4) != 0xffff || at(h,0x12b8) || at(h,0x12bc) ||
        at(h,0x12c0) || at(h,0x12c4)) return VJPEG_UNSUPPORTED;
    aif.high = at(h,0x1298); aif.low = at(h,0x12a0);
    r = vjpeg_aif_to_phys(aif,c.destination_dma_capacity,&c.destination_aligned);
    if (r != VJPEG_OK) return r;
    c.destination_skip = (uint16_t)at(h,0x400);
    c.destination_address = c.destination_aligned + c.destination_skip;
    c.destination_capacity = c.destination_dma_capacity - c.destination_skip;
    if (c.source_address < c.destination_aligned + c.destination_dma_capacity &&
        c.destination_aligned < c.source_address + span) return VJPEG_OVERLAP;
    c.threshold = at(h,0x90); c.interrupt_mask = at(h,0x18);
    c.gaps = NJPEG_GAP_PIXEL_LAYOUT | NJPEG_GAP_SCAN_RESTART |
             NJPEG_GAP_LOGICAL_GEOMETRY;
    *out = c;
    return VJPEG_OK;
}
enum vjpeg_result njpeg_resolve_parameter_geometry(const struct njpeg_binding *h,
    const void *parameter, size_t bytes, struct njpeg_configuration *out)
{
    const uint8_t *p = parameter;
    uint32_t width, height;
    enum vjpeg_result r;
    uintptr_t source = (uintptr_t)parameter, target = (uintptr_t)out;
    if (out == NULL) return VJPEG_INVALID;
    if (h != NULL && ((uintptr_t)h > UINTPTR_MAX - sizeof(*h) ||
        target > UINTPTR_MAX - sizeof(*out) ||
        ((uintptr_t)h < target + sizeof(*out) && target < (uintptr_t)h + sizeof(*h))))
        return VJPEG_INVALID;
    /* Overlap would mutate the immutable submission snapshot on failure. */
    if (parameter != NULL && (bytes > UINTPTR_MAX - source ||
        sizeof(*out) > UINTPTR_MAX - target ||
        (source < target + sizeof(*out) && target < source + bytes)))
        return VJPEG_INVALID;
    memset(out, 0, sizeof(*out));
    if (h == NULL || p == NULL) return VJPEG_INVALID;
    if (bytes < 0x30) return VJPEG_NEED_DATA;
    width = (uint32_t)p[0x28] | (uint32_t)p[0x29] << 8 |
            (uint32_t)p[0x2a] << 16 | (uint32_t)p[0x2b] << 24;
    height = (uint32_t)p[0x2c] | (uint32_t)p[0x2d] << 8 |
             (uint32_t)p[0x2e] << 16 | (uint32_t)p[0x2f] << 24;
    r = njpeg_resolve(h, out);
    if (r != VJPEG_OK) return r;
    if (!width || !height || width > 65500 || height > 65500 ||
        ((width + 15u) & ~15u) != out->coding.width ||
        ((height + 7u) & ~7u) != out->coding.height) {
        memset(out, 0, sizeof(*out));
        return VJPEG_BOUNDS;
    }
    out->logical_width = width; out->logical_height = height;
    out->gaps &= ~(unsigned)NJPEG_GAP_LOGICAL_GEOMETRY;
    return VJPEG_OK;
}
unsigned njpeg_interrupt_code(uint32_t status)
{
    static const struct { uint32_t mask; unsigned code; } priority[] = {
        {0x1000000,10},{1,1},{0x10000,2},{4,3},{0x10,4},{0x20,5},
        {0x40,6},{0x20000,7},{0x40000,8},{0x80000,9},{0x100000,13}
    };
    for (size_t i = 0; i < sizeof(priority) / sizeof(priority[0]); ++i)
        if (status & priority[i].mask) return priority[i].code;
    return 0;
}
enum vjpeg_result njpeg_completion_import(struct njpeg_completion *c,
                                          struct vjpeg_hw *core)
{
    struct vjpeg_snapshot s;
    if (c == NULL || core == NULL) return VJPEG_INVALID;
    if (c->owner || c->status || c->fifo_count || c->irq_level)
        return VJPEG_BUSY;
    s = vjpeg_hw_snapshot(core);
    if (s.state != VJPEG_COMPLETE || s.result != VJPEG_OK ||
        s.events != VJPEG_EVENT_DONE || s.fifo_count != 1 ||
        !s.output_length || s.irq_level != 1) return VJPEG_NEED_DATA;
    c->status = NJPEG_ENCODE_DONE; c->length = s.output_length;
    c->fifo_count = 1; c->owner = core;
    c->irq_level = (c->status & c->interrupt_mask) != 0;
    return VJPEG_OK;
}
enum vjpeg_result njpeg_completion_read(const struct njpeg_completion *c,
    uint32_t o, unsigned size, uint32_t *value)
{
    uint32_t word = 0;
    if (c == NULL || value == NULL) return VJPEG_INVALID;
    *value = 0;
    switch (o & ~3u) {
    case 0x10: word = c->status; break;
    case 0x18: word = c->interrupt_mask; break;
    case 0x44: word = c->fifo_count; break;
    case 0x4c: word = c->length; break;
    case 0x14: case 0x40: break;
    default: return VJPEG_UNSUPPORTED;
    }
    return lane(o,size,word,value);
}
enum vjpeg_result njpeg_completion_write(struct njpeg_completion *c,
    uint32_t o, unsigned size, uint32_t value)
{
    enum vjpeg_result r;
    if (c == NULL) return VJPEG_INVALID;
    if (size != 4 || (o & 3u)) return VJPEG_UNSUPPORTED;
    switch (o) {
    case 0x14:
        if (c->owner && (c->status & value & NJPEG_ENCODE_DONE)) {
            r = vjpeg_hw_ack(c->owner,VJPEG_EVENT_DONE);
            if (r != VJPEG_OK) return r;
        }
        c->status &= ~value;
        break;
    case 0x18: c->interrupt_mask = value; break;
    case 0x40:
        if (value != 1 || !c->fifo_count || !c->owner) return VJPEG_INVALID;
        r = vjpeg_hw_mmio_write(c->owner,0x40,4,1);
        if (r != VJPEG_OK) return r;
        c->fifo_count = 0; c->length = 0;
        break;
    default: return VJPEG_UNSUPPORTED;
    }
    c->irq_level = (c->status & c->interrupt_mask) != 0;
    if (!c->status && !c->fifo_count) c->owner = NULL;
    return VJPEG_OK;
}
