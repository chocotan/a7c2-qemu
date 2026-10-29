#include "native-jpeg.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void wr(struct njpeg_binding *h, uint32_t o, uint32_t v)
{
    assert(njpeg_mmio_write(h,o,4,v) == VJPEG_OK);
}
static uint32_t rd(struct njpeg_binding *h, uint32_t o)
{
    uint32_t v = UINT32_MAX;
    assert(njpeg_mmio_read(h,o,4,&v) == VJPEG_OK);
    return v;
}
static struct njpeg_binding *configured(unsigned omit, unsigned custom)
{
    static const uint16_t zero[] = {
        0,0x30,0x38,0x7c,0xa4,0xac,0x1008,0x1200,0x808,0x814,0x818,0x820,0x824,
        0x12a8,0x12ac,0x12b8,0x12bc,0x12c0,0x12c4
    };
    static const struct { uint16_t mmio, prefix, size; } slices[] = {
        {0x600,141,16},{0x610,157,12},{0x620,170,16},{0x630,186,162},
        {0x700,349,16},{0x710,365,12},{0x720,378,16},{0x730,394,162}
    };
    struct njpeg_binding *h = njpeg_create();
    struct vjpeg_coding c = {0};
    struct vjpeg_aif src;
    struct vjpeg_output dst;
    uint8_t prefix[VJPEG_PREFIX_SIZE];
    assert(h);
    for (size_t i = 0; i < sizeof(zero) / sizeof(zero[0]); ++i) wr(h,zero[i],0);
    assert(vjpeg_phys_to_aif(0x1000,&src) == VJPEG_OK);
    assert(vjpeg_output_layout(0x2000,0,65536,&dst) == VJPEG_OK);
    wr(h,0x18,0x01100005); wr(h,0x80,16); wr(h,0x84,32);
    wr(h,0x90,dst.threshold); wr(h,0xa0,1); wr(h,0xb0,1);
    wr(h,0xb4,16); wr(h,0xb8,16); wr(h,0x400,dst.skip);
    wr(h,0x4c0,1); wr(h,0x500,0x3c); wr(h,0x870,1);
    wr(h,0x1218,src.high); wr(h,0x800,src.low); wr(h,0x804,256);
    wr(h,0x80c,7); wr(h,0x810,0u-7u*256u); wr(h,0x81c,1);
    wr(h,0x1298,dst.aif.high); wr(h,0x12a0,dst.aif.low);
    wr(h,0x12a4,dst.dma_capacity); wr(h,0x12b0,0u-dst.dma_capacity);
    wr(h,0x12b4,0xffff);
    for (unsigned t = 0; t < 2; ++t) {
        unsigned base = t ? 0x280 : 0x200;
        for (unsigned i = 0; i < 64; i += 4) {
            uint32_t word = 0;
            for (unsigned j = 0; j < 4; ++j) {
                unsigned q = custom ? 4u + ((i+j)*3u+t)%9u : 2u+(i+j+t)%3u;
                word |= q << (8*j);
            }
            if (base + i != omit) wr(h,base+i,word);
        }
    }
    c.contract = VJPEG_SOURCE_HEADER_422; c.width = 32; c.height = 16;
    memset(c.quant_zigzag,1,sizeof(c.quant_zigzag));
    assert(vjpeg_source_prefix(&c,prefix) == VJPEG_OK);
    for (unsigned t = 0; t < sizeof(slices) / sizeof(slices[0]); ++t)
        for (unsigned i = 0; i < slices[t].size; i += 4) {
            uint32_t word = 0;
            for (unsigned j = 0; j < 4 && i+j < slices[t].size; ++j)
                word |= (uint32_t)prefix[slices[t].prefix+i+j] << (8*j);
            if (slices[t].mmio+i != omit) wr(h,slices[t].mmio+i,word);
        }
    return h;
}
static void configuration_tests(void)
{
    struct njpeg_binding *h = configured(0,0);
    struct njpeg_configuration c;
    uint32_t v;
    assert(njpeg_resolve(h,&c) == VJPEG_OK);
    assert(c.coding.width == 32 && c.coding.height == 16);
    assert(c.coding.quant_zigzag[0][0] == 2 && c.coding.quant_zigzag[0][2] == 4);
    assert(c.source_address == 0x1000 && c.source_dma_span == 4096);
    assert(c.source_stride == 256 && c.source_access_width == 128);
    assert(c.destination_address == 0x223d && c.destination_aligned == 0x2230);
    assert(c.destination_skip == 13 && c.destination_capacity == 64963);
    assert(c.gaps == 7);
    assert(njpeg_mmio_write(h,8,4,1) == VJPEG_NEED_DATA);
    assert(njpeg_last_result(h) == VJPEG_NEED_DATA);
    assert(njpeg_mmio_write(h,8,4,1) == VJPEG_NEED_DATA);
    assert(rd(h,0x10) == 0 && rd(h,0x44) == 0 && rd(h,0x4c) == 0);
    assert(njpeg_mmio_write(h,0x40,4,1) == VJPEG_INVALID);
    assert(njpeg_mmio_write(h,0x14,4,UINT32_MAX) == VJPEG_OK);
    assert(njpeg_mmio_write(h,0x10,4,1) == VJPEG_UNSUPPORTED);
    assert(njpeg_mmio_write(h,4,4,1) == VJPEG_UNSUPPORTED);
    assert(njpeg_mmio_write(h,0x61c,4,1) == VJPEG_UNSUPPORTED);
    assert(njpeg_mmio_write(h,8,4,2) == VJPEG_UNSUPPORTED);
    assert(njpeg_mmio_write(h,0x200,1,1) == VJPEG_UNSUPPORTED);
    assert(njpeg_mmio_read(h,0x201,1,&v) == VJPEG_OK && v == 3);
    assert(njpeg_mmio_read(h,0x202,2,&v) == VJPEG_OK && v == 0x0204);
    assert(njpeg_mmio_read(h,0x201,2,&v) == VJPEG_UNSUPPORTED);
    assert(njpeg_mmio_read(h,0x200,0,&v) == VJPEG_UNSUPPORTED);
    assert(njpeg_mmio_read(h,0x244c,4,&v) == VJPEG_UNSUPPORTED);
    wr(h,0x200,0); assert(njpeg_resolve(h,&c) == VJPEG_INVALID);
    assert(c.gaps == 0 && c.source_address == 0);
    njpeg_destroy(h);
    h = configured(0x23c,0);
    assert(njpeg_resolve(h,&c) == VJPEG_NEED_DATA); njpeg_destroy(h);
    h = configured(0x7d0,0);
    assert(njpeg_resolve(h,&c) == VJPEG_NEED_DATA); njpeg_destroy(h);
    h = configured(0,0); wr(h,0x7d0,0xfffffaf9);
    assert(njpeg_resolve(h,&c) == VJPEG_UNSUPPORTED); njpeg_destroy(h);
    h = configured(0,0); wr(h,0xac,0); wr(h,0x200,0x02040302);
    assert(njpeg_resolve(h,&c) == VJPEG_NEED_DATA); njpeg_destroy(h);
    h = configured(0,0); v = rd(h,0x600); wr(h,0x4c0,1); wr(h,0x600,v);
    assert(njpeg_resolve(h,&c) == VJPEG_NEED_DATA); njpeg_destroy(h);
    h = configured(0,0); wr(h,0xb4,8);
    assert(njpeg_resolve(h,&c) == VJPEG_UNSUPPORTED); njpeg_destroy(h);
    h = configured(0,0); wr(h,0x1200,0x800);
    assert(njpeg_resolve(h,&c) == VJPEG_UNSUPPORTED); njpeg_destroy(h);
    h = configured(0,0); wr(h,0x1008,0x10);
    assert(njpeg_resolve(h,&c) == VJPEG_NEED_DATA);
    wr(h,0x1200,0x2000); assert(njpeg_resolve(h,&c) == VJPEG_NEED_DATA);
    wr(h,0x1280,3); assert(njpeg_resolve(h,&c) == VJPEG_OK && c.gaps == 7);
    assert(njpeg_mmio_write(h,8,4,1) == VJPEG_NEED_DATA);
    assert(rd(h,0x10) == 0 && rd(h,0x44) == 0 && rd(h,0x4c) == 0);
    njpeg_destroy(h);
    h = configured(0,0); wr(h,0x84,31);
    assert(njpeg_resolve(h,&c) == VJPEG_BOUNDS); njpeg_destroy(h);
    h = configured(0,0); wr(h,0x1218,0x401);
    assert(njpeg_resolve(h,&c) == VJPEG_BOUNDS); njpeg_destroy(h);
    h = configured(0,0); wr(h,0x800,0xfffffff0);
    assert(njpeg_resolve(h,&c) == VJPEG_UNSUPPORTED); njpeg_destroy(h);
    h = configured(0,0); wr(h,0x12a4,0xffff);
    assert(njpeg_resolve(h,&c) == VJPEG_BOUNDS); njpeg_destroy(h);
    h = configured(0,0); wr(h,0x12a0,0x1000);
    assert(njpeg_resolve(h,&c) == VJPEG_OVERLAP); njpeg_destroy(h);
    h = configured(0,0); wr(h,0x808,UINT32_MAX);
    assert(njpeg_resolve(h,&c) == VJPEG_UNSUPPORTED); njpeg_destroy(h);
    h = njpeg_create(); assert(h);
    assert(njpeg_mmio_write(h,8,4,1) == VJPEG_NEED_DATA); njpeg_destroy(h);
    assert(njpeg_resolve(NULL,&c) == VJPEG_INVALID);
}
static void parameter_geometry_tests(void)
{
    struct njpeg_binding *h = configured(0,0);
    struct njpeg_configuration c, zero = {0};
    uint8_t p[0x30] = {0}, before[0x30], prefix[VJPEG_PREFIX_SIZE];
    for (unsigned width = 17; width <= 32; ++width) {
        for (unsigned height = 9; height <= 16; ++height) {
            p[0x28] = (uint8_t)width; p[0x2c] = (uint8_t)height;
            memcpy(before,p,sizeof p);
            assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_OK);
            assert(!memcmp(p,before,sizeof p));
            assert(c.logical_width == width && c.logical_height == height);
            assert(c.coding.width == 32 && c.coding.height == 16 && c.source_dma_span == 4096);
            assert(c.gaps == (NJPEG_GAP_PIXEL_LAYOUT|NJPEG_GAP_SCAN_RESTART));
            struct vjpeg_coding header = c.coding;
            header.width = c.logical_width; header.height = c.logical_height;
            assert(vjpeg_source_prefix(&header,prefix) == VJPEG_OK);
            assert(prefix[560] == 8 && prefix[561] == 0 && prefix[562] == height);
            assert(prefix[563] == 0 && prefix[564] == width);
        }
    }
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p-1,&c) == VJPEG_NEED_DATA);
    assert(!memcmp(&c,&zero,sizeof c));
    p[0x28] = 0;
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_BOUNDS);
    assert(!memcmp(&c,&zero,sizeof c));
    p[0x28] = 16;
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_BOUNDS);
    p[0x28] = 33;
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_BOUNDS);
    p[0x28] = 31; p[0x2a] = 1; /* Do not silently use the low16 of original u32. */
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_BOUNDS);
    p[0x2a] = 0; p[0x2c] = 8;
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_BOUNDS);
    p[0x2c] = 15;
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_OK);
    wr(h,0x84,48);
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_BOUNDS);
    wr(h,0x84,32);
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_OK);
    struct njpeg_configuration saved = c;
    assert(njpeg_resolve_parameter_geometry(h,&c,sizeof c,&c) == VJPEG_INVALID);
    assert(!memcmp(&c,&saved,sizeof c));
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,(struct njpeg_configuration *)(void *)h) == VJPEG_INVALID);
    assert(njpeg_resolve(h,&c) == VJPEG_OK && c.gaps == 7 && !c.logical_width && !c.logical_height);
    assert(njpeg_resolve_parameter_geometry(h,(const void *)(UINTPTR_MAX-1),0x30,&c) == VJPEG_INVALID);
    assert(njpeg_resolve_parameter_geometry(h,NULL,0,&c) == VJPEG_INVALID);
    assert(njpeg_resolve_parameter_geometry(NULL,p,sizeof p,&c) == VJPEG_INVALID);
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,NULL) == VJPEG_INVALID);
    assert(njpeg_mmio_write(h,8,4,1) == VJPEG_NEED_DATA);
    assert(rd(h,0x10) == 0 && rd(h,0x44) == 0 && rd(h,0x4c) == 0);
    njpeg_destroy(h);
    h = configured(0,0);
    wr(h,0x84,304); wr(h,0x80,24); wr(h,0x808,512); wr(h,0x814,2);
    wr(h,0x810,0u-7u*768u); wr(h,0x81c,2); wr(h,0x12a0,0x10000);
    p[0x28] = 0x21; p[0x29] = 1; p[0x2c] = 17;
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_OK);
    assert(c.logical_width == 289 && c.logical_height == 17);
    assert(c.coding.width == 304 && c.coding.height == 24 && c.source_dma_span == 18432);
    struct vjpeg_coding header = c.coding;
    header.width = c.logical_width; header.height = c.logical_height;
    assert(vjpeg_source_prefix(&header,prefix) == VJPEG_OK);
    assert(prefix[563] == 1 && prefix[564] == 0x21);
    njpeg_destroy(h);
    h = configured(0x23c,0);
    assert(njpeg_resolve_parameter_geometry(h,p,sizeof p,&c) == VJPEG_NEED_DATA);
    assert(!memcmp(&c,&zero,sizeof c));
    njpeg_destroy(h);
}
struct memory {
    struct njpeg_configuration config;
    uint8_t rgb[32*16*3], destination[65536];
    size_t written, read;
    unsigned acquired, released, consumed, irq_high;
    int fail_write, bad_read;
};
static int probe(void *opaque, uint64_t a, size_t n, unsigned access,
                  struct vjpeg_mapping *mapping)
{
    struct memory *m = opaque;
    if (a == 0x1000 && n == sizeof(m->rgb) && access == VJPEG_READ) {
        mapping->object = 1; mapping->offset = 0; return 0;
    }
    if (a == m->config.destination_address && n <= sizeof(m->destination) &&
        access == (VJPEG_READ|VJPEG_WRITE)) {
        mapping->object = 2; mapping->offset = 0; return 0;
    }
    return -1;
}
static int read_memory(void *opaque, uint64_t a, void *out, size_t n)
{
    struct memory *m = opaque;
    uint64_t offset = a - m->config.destination_address;
    assert(a >= m->config.destination_address && offset <= m->written);
    assert(n <= m->written-offset);
    memcpy(out,m->destination+offset,n); m->read += n;
    if (m->bad_read && n) ((uint8_t *)out)[0] ^= 1;
    return 0;
}
static int write_memory(void *opaque, uint64_t a, const void *in, size_t n)
{
    struct memory *m = opaque;
    assert(a == m->config.destination_address && n <= sizeof(m->destination));
    assert(!m->released && !m->irq_high);
    if (m->fail_write) return -1;
    memcpy(m->destination,in,n); m->written = n;
    return 0;
}
static int acquire(void *opaque, uint64_t a, size_t n, struct vjpeg_frame *f)
{
    struct memory *m = opaque;
    assert(a == 0x1000 && n == sizeof(m->rgb));
    ++m->acquired;
    f->contract = VJPEG_RGB888; f->rgb = m->rgb; f->size = sizeof(m->rgb);
    f->width = 32; f->height = 16; f->stride = 32*3; f->lease = m;
    return 0;
}
static void release(void *opaque, void *lease, int consumed)
{
    struct memory *m = opaque;
    assert(lease == m && !m->released); ++m->released;
    m->consumed = (unsigned)consumed;
}
static void irq(void *opaque, unsigned external, int level)
{
    struct memory *m = opaque;
    assert(external == 29);
    if (level) {
        assert(m->released == 1 && m->written && m->written == m->read);
        ++m->irq_high;
    }
}
static struct vjpeg_hw *core_for(struct memory *m, struct njpeg_binding *h,
                                  unsigned inverse)
{
    const struct vjpeg_callbacks cb = {probe,read_memory,write_memory,acquire,release,irq};
    struct vjpeg_job j = {0};
    struct vjpeg_hw *core;
    memset(m,0,sizeof(*m));
    assert(njpeg_resolve(h,&m->config) == VJPEG_OK);
    for (unsigned y = 0; y < 16; ++y)
        for (unsigned x = 0; x < 32; ++x) {
            unsigned i = 3*(y*32+x);
            m->rgb[i] = (uint8_t)(30+4*x);
            m->rgb[i+1] = (uint8_t)(50+5*y);
            m->rgb[i+2] = (uint8_t)(40+2*x+2*y);
            if (inverse) for (unsigned k=0;k<3;++k) m->rgb[i+k] ^= 255;
        }
    memset(m->destination,0xa5,sizeof(m->destination));
    core = vjpeg_hw_create(&cb,m); assert(core);
    /* Independent host fixture: registers supply coding, not YC interpretation.
     * Native DMA span is deliberately NOT relabeled as RGB or passed to core. */
    j.source_address = 0x1000; j.source_size = sizeof(m->rgb);
    j.destination_address = m->config.destination_address;
    j.destination_capacity = m->config.destination_capacity;
    j.pixels = VJPEG_RGB888; j.coding = m->config.coding;
    assert(vjpeg_hw_prepare(core,&j) == VJPEG_OK);
    return core;
}
static void completion_tests(void)
{
    struct njpeg_binding *h = configured(0,0);
    struct memory m;
    struct vjpeg_hw *core = core_for(&m,h,0);
    struct njpeg_completion c = {0};
    uint32_t v;
    assert(njpeg_completion_import(&c,core) == VJPEG_NEED_DATA);
    assert(njpeg_completion_write(&c,0x14,4,1) == VJPEG_OK);
    assert(vjpeg_hw_execute(core) == VJPEG_OK);
    assert(m.acquired == 1 && m.released == 1 && m.consumed == 1 && m.irq_high == 1);
    assert(m.destination[0] == 255 && m.destination[1] == 218);
    assert(m.destination[m.written-2] == 255 && m.destination[m.written-1] == 217);
    assert(m.destination[m.written] == 0xa5);
    assert(njpeg_completion_import(&c,core) == VJPEG_OK);
    assert(c.status == 1 && c.fifo_count == 1 && !c.irq_level);
    assert(njpeg_completion_write(&c,0x18,4,0x01100005) == VJPEG_OK && c.irq_level);
    assert(njpeg_interrupt_code(c.status) == 1);
    assert(njpeg_completion_read(&c,0x10,1,&v) == VJPEG_OK && v == 1);
    assert(njpeg_completion_read(&c,0x4c,4,&v) == VJPEG_OK && v == m.written);
    assert(njpeg_completion_read(&c,0x44,4,&v) == VJPEG_OK && v == 1);
    assert(njpeg_completion_read(&c,0x44,4,&v) == VJPEG_OK && v == 1);
    assert(njpeg_completion_write(&c,0x40,4,0) == VJPEG_INVALID);
    assert(njpeg_completion_import(&c,core) == VJPEG_BUSY);
    assert(njpeg_completion_write(&c,0x14,4,4) == VJPEG_OK && c.status == 1);
    assert(njpeg_completion_write(&c,0x14,4,1) == VJPEG_OK);
    assert(!c.status && !c.irq_level && c.fifo_count == 1);
    assert(njpeg_completion_import(&c,core) == VJPEG_BUSY);
    assert(njpeg_completion_write(&c,0x40,4,1) == VJPEG_OK);
    assert(!c.owner && !c.length && !c.fifo_count);
    assert(vjpeg_hw_snapshot(core).state == VJPEG_IDLE);
    assert(njpeg_completion_import(&c,core) == VJPEG_NEED_DATA);
    assert(njpeg_completion_write(&c,0x40,4,1) == VJPEG_INVALID);
    assert(njpeg_completion_write(&c,0x10,4,1) == VJPEG_UNSUPPORTED);
    assert(njpeg_completion_read(&c,0x11,2,&v) == VJPEG_UNSUPPORTED);
    /* Real host output never unblocks the unrelated, unproved native source. */
    assert(njpeg_mmio_write(h,8,4,1) == VJPEG_NEED_DATA);
    assert(rd(h,0x10) == 0 && rd(h,0x44) == 0);
    vjpeg_hw_destroy(core);
    core = core_for(&m,h,0);
    assert(vjpeg_hw_execute(core) == VJPEG_OK);
    assert(njpeg_completion_import(&c,core) == VJPEG_OK && c.irq_level);
    assert(njpeg_completion_write(&c,0x40,4,1) == VJPEG_OK);
    assert(c.status == 1 && c.irq_level);
    assert(njpeg_completion_write(&c,0x14,4,UINT32_MAX) == VJPEG_OK);
    assert(!c.owner && vjpeg_hw_snapshot(core).state == VJPEG_IDLE);
    vjpeg_hw_destroy(core);
    for (unsigned fail = 1; fail <= 2; ++fail) {
        core = core_for(&m,h,0);
        m.fail_write = fail == 1; m.bad_read = fail == 2;
        assert(vjpeg_hw_execute(core) == (fail == 1 ? VJPEG_MEMORY : VJPEG_VERIFY));
        assert(m.released == 1 && m.consumed == 1 && m.irq_high == 0);
        assert(njpeg_completion_import(&c,core) == VJPEG_NEED_DATA);
        assert(!c.status && !c.fifo_count && !c.irq_level);
        assert(vjpeg_hw_ack(core,VJPEG_EVENT_FAULT) == VJPEG_OK);
        vjpeg_hw_destroy(core);
    }
    njpeg_destroy(h);
}
static void interrupt_tests(void)
{
    static const uint32_t masks[] = {
        0x1000000,1,0x10000,4,0x10,0x20,0x40,0x20000,0x40000,0x80000,0x100000
    };
    static const unsigned codes[] = {10,1,2,3,4,5,6,7,8,9,13};
    struct njpeg_completion error = {0};
    uint32_t value;
    /* A source-defined rejection latch is not synthesized from host faults. */
    error.status = NJPEG_ENCODE_REJECTED; error.interrupt_mask = 4; error.irq_level = 1;
    assert(njpeg_completion_read(&error,0x10,4,&value) == VJPEG_OK && value == 4);
    assert(njpeg_interrupt_code(value) == 3);
    assert(njpeg_completion_write(&error,0x14,4,1) == VJPEG_OK && error.status == 4);
    assert(njpeg_completion_write(&error,0x14,4,4) == VJPEG_OK);
    assert(!error.status && !error.irq_level && !error.fifo_count);
    assert(njpeg_interrupt_code(0) == 0 && njpeg_interrupt_code(0x80000000) == 0);
    for (unsigned i = 0; i < sizeof(codes) / sizeof(codes[0]); ++i) {
        uint32_t combined = 0;
        for (unsigned j = i; j < sizeof(codes) / sizeof(codes[0]); ++j)
            combined |= masks[j];
        assert(njpeg_interrupt_code(masks[i]) == codes[i]);
        assert(njpeg_interrupt_code(combined) == codes[i]);
    }
}
int main(int argc, char **argv)
{
    if (argc > 1 && (strcmp(argv[1],"--emit") == 0 || strcmp(argv[1],"--emit-geometry") == 0)) {
        unsigned inverse = argc > 2 ? (unsigned)atoi(argv[2]) : 0;
        unsigned custom = argc > 3 ? (unsigned)atoi(argv[3]) : 0;
        struct njpeg_binding *h = configured(0,custom);
        struct memory m;
        struct vjpeg_hw *core = core_for(&m,h,inverse);
        struct njpeg_completion c = {0};
        uint8_t prefix[VJPEG_PREFIX_SIZE];
        assert(vjpeg_hw_execute(core) == VJPEG_OK);
        assert(njpeg_completion_import(&c,core) == VJPEG_OK);
        struct vjpeg_coding header = m.config.coding;
        if (!strcmp(argv[1],"--emit-geometry")) {
            assert(argc == 6);
            uint8_t parameter[0x30] = {0};
            unsigned width = (unsigned)atoi(argv[4]), height = (unsigned)atoi(argv[5]);
            for (unsigned i = 0; i < 4; ++i) {
                parameter[0x28+i] = (uint8_t)(width >> (8*i));
                parameter[0x2c+i] = (uint8_t)(height >> (8*i));
            }
            struct njpeg_configuration resolved;
            assert(njpeg_resolve_parameter_geometry(h,parameter,sizeof parameter,&resolved) == VJPEG_OK);
            header.width = resolved.logical_width; header.height = resolved.logical_height;
        }
        assert(vjpeg_source_prefix(&header,prefix) == VJPEG_OK);
        assert(fwrite(prefix,1,sizeof(prefix),stdout) == sizeof(prefix));
        assert(fwrite(m.destination,1,m.written,stdout) == m.written);
        assert(njpeg_completion_write(&c,0x14,4,1) == VJPEG_OK);
        assert(njpeg_completion_write(&c,0x40,4,1) == VJPEG_OK);
        vjpeg_hw_destroy(core); njpeg_destroy(h);
        return 0;
    }
    configuration_tests(); parameter_geometry_tests(); interrupt_tests(); completion_tests();
    puts("native configuration, fail-closed start, and verified completion checks passed");
    return 0;
}
