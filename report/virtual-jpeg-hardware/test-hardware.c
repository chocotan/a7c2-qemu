#include "jpeg-hardware.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SRC UINT64_C(0x1000)
#define DST UINT64_C(0x100000)
#define ALIAS UINT64_C(0x200000)
#define CAP 65536u
#define GUARD 16u

struct fixture {
    struct vjpeg_hw *hw;
    struct vjpeg_job job;
    uint8_t rgb[4096], output[CAP + 2 * GUARD];
    unsigned acquired, released, consumed, writes, reads, read_bytes, written_bytes;
    unsigned raised, lowered;
    int unmapped, acquire_fail, write_fail, read_fail, corrupt, bad_frame;
    int alias, cancel_at, early_ack, invert, varied_quant;
};
static void pending(struct fixture *f)
{
    struct vjpeg_snapshot s = vjpeg_hw_snapshot(f->hw);
    assert(s.state == VJPEG_RUNNING && !s.events && !s.irq_level);
    assert(!s.fifo_count && !s.output_length && !f->raised);
}
static void maybe_cancel(struct fixture *f, int stage)
{
    if (f->cancel_at == stage) assert(vjpeg_hw_cancel(f->hw) == VJPEG_OK);
}
static int memory_probe(void *opaque, uint64_t addr, size_t size,
                        unsigned access, struct vjpeg_mapping *m)
{
    struct fixture *f = opaque;
    pending(f);
    if (addr == SRC && size == f->job.source_size && access == VJPEG_READ) {
        m->object = 1; m->offset = 0; maybe_cancel(f, 1); return 0;
    }
    if (addr == f->job.destination_address && size == f->job.destination_capacity &&
        access == (VJPEG_READ | VJPEG_WRITE)) {
        if (f->unmapped) return -1;
        m->object = f->alias ? 1 : 2; m->offset = 0;
        maybe_cancel(f, 2); return 0;
    }
    return -1;
}
static int memory_read(void *opaque, uint64_t addr, void *out, size_t n)
{
    struct fixture *f = opaque;
    pending(f);
    assert(f->writes == 1 && addr >= f->job.destination_address);
    assert(addr - f->job.destination_address <= f->job.destination_capacity);
    assert(n <= f->job.destination_capacity - (addr - f->job.destination_address));
    if (f->read_fail) return -1;
    memcpy(out, f->output + GUARD + (addr - f->job.destination_address), n);
    if (f->corrupt) ((uint8_t *)out)[0] ^= 1;
    ++f->reads; f->read_bytes += (unsigned)n;
    maybe_cancel(f, 5);
    return 0;
}
static int memory_write(void *opaque, uint64_t addr, const void *in, size_t n)
{
    struct fixture *f = opaque;
    const uint8_t *bytes = in;
    pending(f);
    assert(f->acquired == 1 && !f->released && !f->writes && !f->reads);
    assert(addr == f->job.destination_address && n <= f->job.destination_capacity);
    assert(n >= 16 && bytes[0] == 0xff && bytes[1] == 0xda);
    assert(bytes[n - 2] == 0xff && bytes[n - 1] == 0xd9);
    if (f->early_ack) {
        assert(vjpeg_hw_ack(f->hw, VJPEG_EVENT_DONE) == VJPEG_OK);
        assert(vjpeg_hw_execute(f->hw) == VJPEG_BUSY);
        assert(vjpeg_hw_prepare(f->hw, &f->job) == VJPEG_BUSY);
    }
    if (f->write_fail) return -1;
    memcpy(f->output + GUARD, in, n); ++f->writes;
    f->written_bytes = (unsigned)n;
    maybe_cancel(f, 4);
    return 0;
}
static int frame_acquire(void *opaque, uint64_t addr, size_t n, struct vjpeg_frame *out)
{
    struct fixture *f = opaque;
    pending(f);
    assert(addr == SRC && n == f->job.source_size && !f->acquired);
    if (f->acquire_fail) return -1;
    ++f->acquired;
    out->contract = f->bad_frame == 1 ? VJPEG_PIXELS_UNKNOWN : VJPEG_RGB888;
    out->rgb = f->rgb; out->size = n;
    out->width = f->job.coding.width; out->height = f->job.coding.height;
    out->stride = f->bad_frame == 2 ? 1 : 104; out->lease = f;
    if (f->bad_frame == 3) out->size = 1;
    maybe_cancel(f, 3);
    return 0;
}
static void frame_release(void *opaque, void *lease, int consumed)
{
    struct fixture *f = opaque;
    pending(f);
    assert(lease == f && f->acquired == 1 && !f->released);
    ++f->released; f->consumed += (unsigned)consumed;
    maybe_cancel(f, 6);
}
static void emit_irq(void *opaque, unsigned input, int level)
{
    struct fixture *f = opaque;
    struct vjpeg_snapshot s = vjpeg_hw_snapshot(f->hw);
    assert(input == 29 && s.irq_level == (unsigned)level);
    if (level) {
        assert(f->writes == 1 && f->released == 1 && f->consumed == 1);
        assert(s.state == VJPEG_COMPLETE && s.events == VJPEG_EVENT_DONE);
        assert(s.fifo_count == 1 && s.output_length == f->read_bytes);
        ++f->raised;
    } else ++f->lowered;
}
static const struct vjpeg_callbacks callbacks = {
    memory_probe, memory_read, memory_write, frame_acquire, frame_release, emit_irq
};
static void init(struct fixture *f, int invert, int varied_quant)
{
    memset(f, 0, sizeof(*f));
    f->invert = invert; f->varied_quant = varied_quant;
    f->job.source_address = SRC; f->job.source_size = 20 * 104 + 33 * 3;
    f->job.destination_address = DST; f->job.destination_capacity = CAP;
    f->job.pixels = VJPEG_RGB888;
    f->job.coding.contract = VJPEG_SOURCE_HEADER_422;
    f->job.coding.width = 33; f->job.coding.height = 21;
    for (size_t t = 0; t < 2; ++t)
        for (size_t i = 0; i < 64; ++i)
            f->job.coding.quant_zigzag[t][i] = (uint8_t)(varied_quant ?
                1 + (i * 3 + t * 7) % 17 : 2);
    memset(f->output, 0xa5, sizeof(f->output));
    memset(f->rgb, 0xbc, sizeof(f->rgb));
    for (size_t y = 0; y < 21; ++y) for (size_t x = 0; x < 33; ++x) {
        uint8_t rgb[3] = {(uint8_t)(32 + 160 * x / 33),
            (uint8_t)(32 + 160 * y / 21), (uint8_t)(48 + 100 * (x + y) / 54)};
        for (size_t c = 0; c < 3; ++c)
            f->rgb[y * 104 + x * 3 + c] = invert ? (uint8_t)(255 - rgb[c]) : rgb[c];
    }
    f->hw = vjpeg_hw_create(&callbacks, f); assert(f->hw);
}
static void guards(const struct fixture *f)
{
    for (size_t i = 0; i < GUARD; ++i) assert(f->output[i] == 0xa5);
    for (size_t i = GUARD + f->written_bytes; i < sizeof(f->output); ++i)
        assert(f->output[i] == 0xa5);
    for (size_t i = GUARD + f->job.destination_capacity; i < sizeof(f->output); ++i)
        assert(f->output[i] == 0xa5);
}
static void destroy(struct fixture *f)
{
    guards(f); vjpeg_hw_destroy(f->hw);
}
static uint32_t reg_read(struct fixture *f, uint32_t offset, unsigned size)
{
    uint32_t value = UINT32_MAX;
    assert(vjpeg_hw_mmio_read(f->hw, offset, size, &value) == VJPEG_OK);
    return value;
}
static void arithmetic(void)
{
    uint64_t a = 0;
    struct vjpeg_aif af;
    struct vjpeg_output o;
    assert(vjpeg_source_address(0x1000,1920,3,4,5,6,&a) == VJPEG_OK);
    assert(a == 0x1000 + 2 * (10 * 1920 + 8));
    assert(vjpeg_source_address(0,1,UINT32_MAX,0,1,0,&a) == VJPEG_BOUNDS);
    assert(vjpeg_source_address(UINT64_MAX,1,1,0,0,0,&a) == VJPEG_BOUNDS);
    assert(vjpeg_source_address(0,UINT32_MAX,0,UINT32_MAX,0,0,&a) == VJPEG_BOUNDS);
    const uint64_t edges[] = {0,0xffffffff,0x100000000,0x1ffffffff,
                              0x3fe000000,0x3fe6bffff};
    for (size_t i = 0; i < sizeof(edges) / sizeof(edges[0]); ++i) {
        assert(vjpeg_phys_to_aif(edges[i],&af) == VJPEG_OK);
        assert(!(af.high & 255));
        assert(vjpeg_aif_to_phys(af,1,&a) == VJPEG_OK && a == edges[i]);
    }
    assert(vjpeg_phys_to_aif(0x200000000,&af) == VJPEG_UNSUPPORTED);
    assert(vjpeg_phys_to_aif(0x3fe6c0000,&af) == VJPEG_UNSUPPORTED);
    assert(vjpeg_phys_to_aif(0xffffffff,&af) == VJPEG_OK);
    assert(vjpeg_aif_to_phys(af,2,&a) == VJPEG_UNSUPPORTED);
    af.high |= 1;
    assert(vjpeg_aif_to_phys(af,1,&a) == VJPEG_BOUNDS);
    assert(vjpeg_output_layout(0x100000,7,0x4000,&o) == VJPEG_OK);
    assert(o.effective == 0x100244 && o.aligned == 0x100240 && o.skip == 4);
    assert(o.dma_capacity == 0x3dc0 && o.threshold == 0x39c3);
    assert(vjpeg_output_layout(UINT64_MAX,1,0x4000,&o) == VJPEG_BOUNDS);
    assert(vjpeg_output_layout(0,0,0x23d,&o) == VJPEG_BOUNDS);
    assert(vjpeg_output_layout(0x1fffffff0,0,0x4000,&o) == VJPEG_UNSUPPORTED);
}
static void success_and_fifo(void)
{
    struct fixture f;
    struct vjpeg_snapshot s;
    uint8_t prefix[VJPEG_PREFIX_SIZE];
    init(&f,0,1); f.early_ack = 1;
    assert(vjpeg_source_prefix(&f.job.coding,prefix) == VJPEG_OK);
    assert(prefix[0] == 0xff && prefix[1] == 0xd8);
    assert(prefix[2] == 0xff && prefix[3] == 0xdb);
    assert(prefix[136] == 0xff && prefix[137] == 0xc4);
    assert(prefix[556] == 0xff && prefix[557] == 0xc0 && prefix[567] == 0x21);
    assert(vjpeg_hw_prepare(f.hw,&f.job) == VJPEG_OK);
    assert(vjpeg_hw_mmio_write(f.hw,8,4,1) == VJPEG_OK);
    s = vjpeg_hw_snapshot(f.hw);
    assert(s.output_length > 16 && s.output_length <= CAP && f.raised == 1);
    assert(reg_read(&f,0x44,4) == 1 && reg_read(&f,0x4c,4) == s.output_length);
    assert(reg_read(&f,0x4c,1) == (s.output_length & 255));
    assert(reg_read(&f,0x4d,1) == ((s.output_length >> 8) & 255));
    assert(reg_read(&f,0x10,4) == 0);
    assert(vjpeg_hw_mmio_write(f.hw,0x14,4,UINT32_MAX) == VJPEG_OK);
    assert(vjpeg_hw_snapshot(f.hw).irq_level == 1);
    assert(vjpeg_hw_execute(f.hw) == VJPEG_BUSY);
    assert(vjpeg_hw_prepare(f.hw,&f.job) == VJPEG_BUSY);
    assert(vjpeg_hw_ack(f.hw,VJPEG_EVENT_FAULT) == VJPEG_OK);
    assert(vjpeg_hw_snapshot(f.hw).irq_level == 1);
    assert(vjpeg_hw_mmio_write(f.hw,0x40,4,1) == VJPEG_OK);
    assert(reg_read(&f,0x44,4) == 0 && reg_read(&f,0x4c,4) == 0);
    assert(vjpeg_hw_prepare(f.hw,&f.job) == VJPEG_BUSY);
    assert(vjpeg_hw_mmio_write(f.hw,0x40,4,1) == VJPEG_INVALID);
    assert(vjpeg_hw_ack(f.hw,VJPEG_EVENT_DONE) == VJPEG_OK);
    assert(vjpeg_hw_snapshot(f.hw).state == VJPEG_IDLE && f.lowered == 1);
    destroy(&f);
    init(&f,0,0);
    assert(vjpeg_hw_prepare(f.hw,&f.job) == VJPEG_OK);
    assert(vjpeg_hw_execute(f.hw) == VJPEG_OK);
    s = vjpeg_hw_snapshot(f.hw);
    assert(vjpeg_hw_ack(f.hw,VJPEG_EVENT_DONE) == VJPEG_OK);
    assert(!vjpeg_hw_snapshot(f.hw).irq_level && f.lowered == 1);
    assert(reg_read(&f,0x44,4) == 1 && reg_read(&f,0x4c,4) == s.output_length);
    assert(vjpeg_hw_prepare(f.hw,&f.job) == VJPEG_BUSY);
    assert(vjpeg_hw_mmio_write(f.hw,0x40,4,1) == VJPEG_OK);
    assert(vjpeg_hw_snapshot(f.hw).state == VJPEG_IDLE);
    destroy(&f);
}
static void failures(void)
{
    for (unsigned mode = 0; mode < 10; ++mode) {
        struct fixture f;
        enum vjpeg_result expected = VJPEG_MEMORY;
        init(&f,0,0);
        switch (mode) {
        case 0: f.unmapped = 1; break;
        case 1: f.acquire_fail = 1; expected = VJPEG_NEED_DATA; break;
        case 2: f.job.destination_capacity = 1; expected = VJPEG_BOUNDS; break;
        case 3: f.bad_frame = 1; expected = VJPEG_UNSUPPORTED; break;
        case 4: f.bad_frame = 2; expected = VJPEG_BOUNDS; break;
        case 5: f.bad_frame = 3; expected = VJPEG_BOUNDS; break;
        case 6: f.alias = 1; f.job.destination_address = ALIAS;
                expected = VJPEG_OVERLAP; break;
        case 7: f.write_fail = 1; break;
        case 8: f.read_fail = 1; break;
        case 9: f.corrupt = 1; expected = VJPEG_VERIFY; break;
        }
        assert(vjpeg_hw_prepare(f.hw,&f.job) == VJPEG_OK);
        assert(vjpeg_hw_execute(f.hw) == expected);
        struct vjpeg_snapshot s = vjpeg_hw_snapshot(f.hw);
        assert(s.state == VJPEG_FAULT && s.events == VJPEG_EVENT_FAULT);
        assert(!s.irq_level && !s.output_length && !s.fifo_count && !f.raised);
        assert(f.released == f.acquired);
        if (mode == 0 || mode == 1 || mode == 6) assert(!f.acquired);
        if (mode == 3 || mode == 4 || mode == 5) assert(!f.consumed);
        if (mode < 8) assert(!f.writes);
        assert(vjpeg_hw_mmio_write(f.hw,0x40,4,1) == VJPEG_INVALID);
        assert(vjpeg_hw_ack(f.hw,VJPEG_EVENT_DONE) == VJPEG_OK);
        assert(vjpeg_hw_snapshot(f.hw).state == VJPEG_FAULT);
        assert(vjpeg_hw_ack(f.hw,VJPEG_EVENT_FAULT) == VJPEG_OK);
        assert(vjpeg_hw_snapshot(f.hw).state == VJPEG_IDLE);
        destroy(&f);
    }
}
static void cancellations(void)
{
    for (int stage = 0; stage <= 6; ++stage) {
        struct fixture f;
        init(&f,0,0); f.cancel_at = stage;
        assert(vjpeg_hw_prepare(f.hw,&f.job) == VJPEG_OK);
        if (!stage) assert(vjpeg_hw_cancel(f.hw) == VJPEG_CANCELLED);
        else assert(vjpeg_hw_execute(f.hw) == VJPEG_CANCELLED);
        struct vjpeg_snapshot s = vjpeg_hw_snapshot(f.hw);
        assert(s.result == VJPEG_CANCELLED && s.events == VJPEG_EVENT_CANCELLED);
        assert(!s.output_length && !s.fifo_count && !s.irq_level && !f.raised);
        assert(f.acquired == f.released && f.consumed <= 1);
        if (stage <= 2) assert(!f.acquired);
        if (stage == 3) assert(!f.consumed);
        if (stage >= 4) assert(f.consumed == 1);
        destroy(&f);
    }
}
static void unsupported_and_bounds(void)
{
    struct fixture f;
    uint32_t value;
    init(&f,0,0);
    assert(vjpeg_hw_mmio_write(f.hw,8,4,1) == VJPEG_NEED_DATA);
    assert(!f.acquired && !f.writes && !f.raised);
    assert(vjpeg_hw_mmio_write(f.hw,0x14,4,7) == VJPEG_OK);
    assert(vjpeg_hw_snapshot(f.hw).events == VJPEG_EVENT_FAULT);
    assert(vjpeg_hw_ack(f.hw,VJPEG_EVENT_FAULT) == VJPEG_OK);
    assert(vjpeg_hw_mmio_write(f.hw,8,4,2) == VJPEG_UNSUPPORTED);
    assert(vjpeg_hw_mmio_write(f.hw,0x400,4,0) == VJPEG_UNSUPPORTED);
    assert(vjpeg_hw_mmio_write(f.hw,0x10,4,1) == VJPEG_UNSUPPORTED);
    assert(vjpeg_hw_mmio_write(f.hw,0x800,2,1) == VJPEG_UNSUPPORTED);
    assert(vjpeg_hw_mmio_read(f.hw,0x801,2,&value) == VJPEG_UNSUPPORTED);
    assert(vjpeg_hw_mmio_read(f.hw,UINT32_MAX,4,&value) == VJPEG_UNSUPPORTED);
    assert(vjpeg_hw_mmio_write(f.hw,0x1218,4,0x400) == VJPEG_OK);
    assert(reg_read(&f,0x1218,4) == 0x400);
    for (int mode = 0; mode < 5; ++mode) {
        struct vjpeg_job j = f.job;
        enum vjpeg_result r;
        if (mode == 0) { j.pixels = VJPEG_PIXELS_UNKNOWN; r = VJPEG_UNSUPPORTED; }
        else if (mode == 1) { j.coding.contract = VJPEG_CODING_UNKNOWN;
                             r = VJPEG_UNSUPPORTED; }
        else if (mode == 2) { j.destination_address = SRC; r = VJPEG_OVERLAP; }
        else if (mode == 3) { j.destination_address = UINT64_MAX;
                             r = VJPEG_BOUNDS; }
        else { j.coding.quant_zigzag[1][7] = 0; r = VJPEG_INVALID; }
        assert(vjpeg_hw_prepare(f.hw,&j) == r);
        assert(!f.acquired && !f.writes && !f.raised);
        assert(vjpeg_hw_ack(f.hw,VJPEG_EVENT_FAULT) == VJPEG_OK);
    }
    assert(vjpeg_hw_ack(f.hw,8) == VJPEG_INVALID);
    destroy(&f);
}
static void exact_capacity_and_padding(void)
{
    struct fixture first, f;
    init(&first,0,1);
    assert(vjpeg_hw_prepare(first.hw,&first.job) == VJPEG_OK);
    assert(vjpeg_hw_execute(first.hw) == VJPEG_OK);
    uint32_t n = vjpeg_hw_snapshot(first.hw).output_length;
    for (int delta = -1; delta <= 1; ++delta) {
        init(&f,0,1);
        f.job.destination_capacity = (size_t)((int)n + delta);
        for (size_t y = 0; y < 20; ++y) memset(f.rgb + y * 104 + 99,0x11,5);
        assert(vjpeg_hw_prepare(f.hw,&f.job) == VJPEG_OK);
        enum vjpeg_result r = vjpeg_hw_execute(f.hw);
        if (delta < 0) assert(r == VJPEG_BOUNDS && !f.writes && !f.raised);
        else {
            assert(r == VJPEG_OK && f.read_bytes == n);
            assert(!memcmp(f.output + GUARD, first.output + GUARD, n));
        }
        destroy(&f);
    }
    destroy(&first);
}
static int jpeg_stdout(int invert, int varied_quant)
{
    struct fixture f;
    uint8_t prefix[VJPEG_PREFIX_SIZE];
    init(&f,invert,varied_quant);
    assert(vjpeg_hw_prepare(f.hw,&f.job) == VJPEG_OK);
    assert(vjpeg_hw_execute(f.hw) == VJPEG_OK);
    assert(vjpeg_source_prefix(&f.job.coding,prefix) == VJPEG_OK);
    assert(fwrite(prefix,1,sizeof(prefix),stdout) == sizeof(prefix));
    assert(fwrite(f.output + GUARD,1,f.read_bytes,stdout) == f.read_bytes);
    destroy(&f);
    return 0;
}
int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1],"--jpeg")) return jpeg_stdout(0,0);
    if (argc == 2 && !strcmp(argv[1],"--jpeg-invert")) return jpeg_stdout(1,0);
    if (argc == 2 && !strcmp(argv[1],"--jpeg-tables")) return jpeg_stdout(0,1);
    assert(argc == 1);
    arithmetic(); success_and_fifo(); failures(); cancellations();
    unsupported_and_bounds(); exact_capacity_and_padding();
    puts("6 device self-test groups passed");
    return 0;
}
