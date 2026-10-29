/* SPDX-License-Identifier: MIT */
#include "optical-frame-owner.h"
#include "../virtual-jpeg-engine/jpeg-engine.h"
#include <assert.h>
#include <float.h>
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define REJECT(owner, expected, call) do { \
    unsigned char prior_[sizeof(owner)]; \
    memcpy(prior_, &(owner), sizeof(owner)); \
    assert((call) == (expected)); \
    assert(memcmp(prior_, &(owner), sizeof(owner)) == 0); \
} while (0)

enum { GUARD = 16 };
static const optical_frame_config standard = {{4, 1, 0.001, 100}, 3, 3, 11};

static void untouched(const unsigned char *p, size_t n)
{
    for (size_t i = 0; i < n; ++i) assert(p[i] == 0xa5);
}

static optical_frame_info snapshot(const optical_frame_owner *o)
{
    optical_frame_info info;
    assert(optical_frame_snapshot(o, &info) == OPTICAL_FRAME_OK);
    return info;
}

static void setup(optical_frame_owner *o, const optical_frame_config *c)
{
    assert(optical_frame_init(o) == OPTICAL_FRAME_OK);
    assert(optical_frame_configure(o, c) == OPTICAL_FRAME_OK);
}

static uint64_t hash(const unsigned char *p, size_t w, size_t h, size_t stride)
{
    uint64_t n = UINT64_C(14695981039346656037);
    for (size_t y = 0; y < h; ++y)
        for (size_t x = 0; x < w * 3; ++x)
            n = (n ^ p[y * stride + x]) * UINT64_C(1099511628211);
    return n;
}

static int inspect(const optical_frame_view *v, void *context)
{
    size_t *calls = context;
    assert(v->format == OPTICAL_FRAME_VIRTUAL_RGB888);
    assert(v->size == v->stride * v->height);
    assert(v->generation == v->metadata.frame_number);
    assert(hash(v->pixels, v->width, v->height, v->stride) == v->metadata.pixel_fnv1a);
    ++*calls;
    return 0;
}

static void lifecycle(void)
{
    optical_frame_owner o = {0}, other = {0};
    optical_frame_config c = standard;
    optical_frame_lease lease, stale, wrong;
    unsigned char a[64], b[64];
    memset(a, 0xa5, sizeof a);
    memset(b, 0xa5, sizeof b);
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_configure(&o, &c));
    assert(optical_frame_init(&o) == OPTICAL_FRAME_OK);
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_acquire(&o, a, sizeof a, &lease));
    assert(optical_frame_configure(&o, &c) == OPTICAL_FRAME_OK);
    assert(optical_frame_acquire(&o, a, sizeof a, &lease) == OPTICAL_FRAME_OK);
    stale = lease;
    optical_frame_info info = snapshot(&o);
    assert(info.state == OPTICAL_FRAME_STAGED && info.generation == 1);
    assert(info.counts.staged == 1 && !info.counts.rendered && !info.counts.read &&
           !info.counts.copied && !info.counts.retired);
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_init(&o));
    c.params.focus_m = 4;
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_configure(&o, &c));
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_autofocus(&o, NULL, NULL, 0, NULL));
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_acquire(&o, b, sizeof b, &wrong));
    size_t calls = 0;
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_consumer_read(&o, &lease, inspect, &calls));
    optical_frame_view v;
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_copy(&o, &lease, b, sizeof b, 11, &v));
    wrong = lease; ++wrong.generation;
    REJECT(o, OPTICAL_FRAME_STALE, optical_frame_render(&o, &wrong));
    wrong = lease; wrong.buffer = b;
    REJECT(o, OPTICAL_FRAME_STALE, optical_frame_retire(&o, &wrong));
    wrong = lease; --wrong.capacity;
    REJECT(o, OPTICAL_FRAME_STALE, optical_frame_retire(&o, &wrong));
    wrong = lease; wrong.owner = &other;
    REJECT(o, OPTICAL_FRAME_STALE, optical_frame_retire(&o, &wrong));
    assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_render(&o, &lease));
    assert(optical_frame_copy(&o, &lease, b, sizeof b, 13, &v) == OPTICAL_FRAME_OK);
    assert(v.pixels == b && v.stride == 13 && v.size == 39 && v.generation == 1);
    assert(v.metadata.pixel_fnv1a == hash(b, 3, 3, 13));
    assert(optical_frame_consumer_read(&o, &lease, inspect, &calls) == OPTICAL_FRAME_OK);
    assert(calls == 1);
    info = snapshot(&o);
    assert(info.counts.staged == 1 && info.counts.rendered == 1 &&
           info.counts.read == 2 && info.counts.copied == 1 && !info.counts.retired);
    assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
    info = snapshot(&o);
    assert(info.state == OPTICAL_FRAME_IDLE && info.counts.retired == 1 && !info.metadata.frame_number);
    REJECT(o, OPTICAL_FRAME_STALE, optical_frame_retire(&o, &lease));
    assert(optical_frame_configure(&o, &c) == OPTICAL_FRAME_OK);
    assert(optical_frame_acquire(&o, a, sizeof a, &lease) == OPTICAL_FRAME_OK);
    assert(lease.generation == stale.generation + 1 && lease.buffer == stale.buffer);
    REJECT(o, OPTICAL_FRAME_STALE, optical_frame_render(&o, &stale));
    REJECT(o, OPTICAL_FRAME_STALE, optical_frame_retire(&o, &stale));
    assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
    info = snapshot(&o);
    assert(info.counts.staged == 2 && info.counts.rendered == 1 &&
           info.counts.read == 2 && info.counts.copied == 1 && info.counts.retired == 2);
    optical_frame_af_request af_request = {1, 1, 2, 2, 0.1, INFINITY};
    optical_frame_af_result af_result = {0};
    REJECT(o, OPTICAL_FRAME_NO_CONTRAST,
           optical_frame_autofocus(&o, &af_request, b, sizeof b, &af_result));
    assert(!af_result.focus_m && !af_result.score && !af_result.coarse_samples &&
           !af_result.refinement_samples);
    setup(&other, &standard);
    assert(optical_frame_acquire(&other, a, sizeof a, &lease) == OPTICAL_FRAME_OK);
    REJECT(other, OPTICAL_FRAME_STALE, optical_frame_retire(&other, &stale));
    assert(optical_frame_retire(&other, &lease) == OPTICAL_FRAME_OK);
}

static void configuration(void)
{
    optical_frame_owner o = {0};
    setup(&o, &standard);
    optical_frame_config c;
    const double invalid[] = {NAN, INFINITY, -INFINITY, 0, -1};
    for (size_t i = 0; i < sizeof invalid / sizeof invalid[0]; ++i) {
        c = standard; c.params.f_number = invalid[i];
        REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, &c));
        c = standard; c.params.shutter_s = invalid[i];
        REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, &c));
        c = standard; c.params.iso = invalid[i];
        REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, &c));
        if (invalid[i] != INFINITY) {
            c = standard; c.params.focus_m = invalid[i];
            REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, &c));
        }
    }
    c = standard; c.params.f_number = 5.6;
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, &c));
    c = standard; c.params.focus_m = 0.099;
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, &c));
    c = standard; c.params.shutter_s = DBL_MAX; c.params.iso = DBL_MAX;
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, &c));
    c = standard; c.params.focus_m = INFINITY;
    assert(optical_frame_configure(&o, &c) == OPTICAL_FRAME_OK);
    c.params.focus_m = 0.1; c.params.f_number = 16;
    assert(optical_frame_configure(&o, &c) == OPTICAL_FRAME_OK);
    c = standard;
    assert(optical_frame_configure(&o, &c) == OPTICAL_FRAME_OK);
    memset(&c, 0, sizeof c);
    unsigned char data[33], reference[33];
    optical_frame_lease lease;
    optics_metadata m;
    optics_stats stats = {0};
    memset(data, 0xa5, sizeof data); memset(reference, 0xa5, sizeof reference);
    assert(optical_frame_acquire(&o, data, sizeof data, &lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
    assert(optics_render(&standard.params, 3, 3, 11, reference, sizeof reference,
                         lease.generation, &m, &stats) == 0);
    assert(memcmp(data, reference, sizeof data) == 0);
    assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
}

static void bounds(void)
{
    optical_frame_owner o = {0};
    setup(&o, &standard);
    optical_frame_config c = standard;
    c.width = 0;
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, &c));
    c = standard; c.height = 0;
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, &c));
    c = standard; c.stride = 8;
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, &c));
    c = standard; c.width = SIZE_MAX / 3 + 1; c.stride = SIZE_MAX;
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_configure(&o, &c));
    c = standard; c.height = SIZE_MAX / 11 + 1;
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_configure(&o, &c));
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_configure(&o, NULL));
    REJECT(o, OPTICAL_FRAME_OVERLAP, optical_frame_configure(&o, &o.info.config));
    unsigned char guarded[33 + 2 * GUARD];
    memset(guarded, 0xa5, sizeof guarded);
    unsigned char *p = guarded + GUARD;
    optical_frame_lease lease, prior;
    memset(&lease, 0x5a, sizeof lease); memcpy(&prior, &lease, sizeof lease);
    REJECT(o, OPTICAL_FRAME_TOO_SMALL, optical_frame_acquire(&o, p, 32, &lease));
    REJECT(o, OPTICAL_FRAME_TOO_SMALL, optical_frame_acquire(&o, p, 0, &lease));
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_acquire(&o, NULL, 33, &lease));
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_acquire(&o, p, 33, NULL));
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_acquire(&o, p, SIZE_MAX, &lease));
    unsigned char *end = (unsigned char *)(uintptr_t)(UINTPTR_MAX - 1);
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_acquire(&o, end, 33, &lease));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_acquire(&o, (unsigned char *)&o, sizeof o, &lease));
    union { optical_frame_lease lease; unsigned char bytes[256]; } alias;
    memset(&alias, 0xa5, sizeof alias);
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_acquire(&o, alias.bytes, sizeof alias, &alias.lease));
    untouched(alias.bytes, sizeof alias);
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_acquire(&o, p, 33, (optical_frame_lease *)&o));
    assert(memcmp(&lease, &prior, sizeof lease) == 0);
    untouched(guarded, sizeof guarded);
    assert(optical_frame_acquire(&o, p, 33, &lease) == OPTICAL_FRAME_OK);
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_render(&o, NULL));
    REJECT(o, OPTICAL_FRAME_OVERLAP, optical_frame_render(&o, (optical_frame_lease *)&o));
    assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
    untouched(guarded, GUARD); untouched(p + 33, GUARD);
    for (size_t y = 0; y < 3; ++y) untouched(p + y * 11 + 9, 2);
    optical_frame_info info;
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_snapshot(&o, NULL));
    REJECT(o, OPTICAL_FRAME_OVERLAP, optical_frame_snapshot(&o, &o.info));
    assert(optical_frame_snapshot(&o, &info) == OPTICAL_FRAME_OK);
    assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_init(NULL) == OPTICAL_FRAME_INVALID);
    assert(optical_frame_snapshot(NULL, &info) == OPTICAL_FRAME_INVALID);
    assert(optical_frame_autofocus(NULL, NULL, NULL, 0, NULL) == OPTICAL_FRAME_INVALID);
}

static void copies(void)
{
    optical_frame_owner o = {0};
    setup(&o, &standard);
    unsigned char *source = malloc(512), *dest = malloc(512);
    unsigned char saved[512], out_saved[sizeof(optical_frame_view)];
    assert(source && dest);
    memset(source, 0xa5, 512); memset(dest, 0xa5, 512);
    optical_frame_lease lease;
    assert(optical_frame_acquire(&o, source, 512, &lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
    memcpy(saved, source, 512);
    optical_frame_view out;
    memset(&out, 0x5a, sizeof out); memcpy(out_saved, &out, sizeof out);
    REJECT(o, OPTICAL_FRAME_TOO_SMALL, optical_frame_copy(&o, &lease, dest, 38, 13, &out));
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_copy(&o, &lease, dest, 512, 8, &out));
    REJECT(o, OPTICAL_FRAME_OVERFLOW,
           optical_frame_copy(&o, &lease, dest, 512, SIZE_MAX, &out));
    REJECT(o, OPTICAL_FRAME_OVERFLOW,
           optical_frame_copy(&o, &lease, dest, SIZE_MAX, 13, &out));
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_copy(&o, &lease, NULL, 39, 13, &out));
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_copy(&o, &lease, dest, 39, 13, NULL));
    REJECT(o, OPTICAL_FRAME_OVERLAP, optical_frame_copy(&o, &lease, source, 39, 13, &out));
    REJECT(o, OPTICAL_FRAME_OVERLAP, optical_frame_copy(&o, &lease, source + 100, 39, 13, &out));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_copy(&o, &lease, (unsigned char *)&o, sizeof o, 13, &out));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_copy(&o, &lease, (unsigned char *)&lease, sizeof lease, 9, &out));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_copy(&o, &lease, dest, 39, 13, (optical_frame_view *)source));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_copy(&o, &lease, dest, 39, 13, (optical_frame_view *)&o));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_copy(&o, &lease, dest, 39, 13, (optical_frame_view *)&lease));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_copy(&o, &lease, dest, 39, 13, (optical_frame_view *)dest));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_snapshot(&o, (optical_frame_info *)source));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_render(&o, (optical_frame_lease *)source));
    assert(memcmp(source, saved, 512) == 0);
    assert(memcmp(&out, out_saved, sizeof out) == 0);
    untouched(dest, 512);
    assert(optical_frame_copy(&o, &lease, dest + GUARD, 39, 13, &out) == OPTICAL_FRAME_OK);
    for (size_t y = 0; y < 3; ++y) {
        assert(memcmp(dest + GUARD + y * 13, source + y * 11, 9) == 0);
        untouched(dest + GUARD + y * 13 + 9, 4);
    }
    untouched(dest, GUARD); untouched(dest + GUARD + 39, 512 - GUARD - 39);
    assert(memcmp(source, saved, 512) == 0);
    assert(out.pixels == dest + GUARD && out.size == 39);
    assert(out.metadata.pixel_fnv1a == hash(out.pixels, 3, 3, 13));
    assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
    assert(memcmp(source, saved, 512) == 0);
    free(source); free(dest);
}

typedef struct {
    optical_frame_owner *owner;
    const optical_frame_lease *lease;
    int result, mutate;
    size_t calls;
} read_context;

static int reentrant(const optical_frame_view *v, void *context)
{
    read_context *c = context;
    optical_frame_owner *o = c->owner;
    optical_frame_info info = snapshot(o);
    assert(info.state == OPTICAL_FRAME_READING);
    inspect(v, &c->calls);
    unsigned char dest[64];
    optical_frame_view out;
    optical_frame_lease next;
    REJECT(*o, OPTICAL_FRAME_STATE, optical_frame_configure(o, &standard));
    REJECT(*o, OPTICAL_FRAME_STATE, optical_frame_acquire(o, dest, sizeof dest, &next));
    REJECT(*o, OPTICAL_FRAME_STATE, optical_frame_render(o, c->lease));
    REJECT(*o, OPTICAL_FRAME_STATE, optical_frame_retire(o, c->lease));
    REJECT(*o, OPTICAL_FRAME_STATE, optical_frame_init(o));
    REJECT(*o, OPTICAL_FRAME_STATE, optical_frame_autofocus(o, NULL, NULL, 0, NULL));
    REJECT(*o, OPTICAL_FRAME_STATE,
           optical_frame_consumer_read(o, c->lease, reentrant, c));
    REJECT(*o, OPTICAL_FRAME_STATE,
           optical_frame_copy(o, c->lease, dest, sizeof dest, 11, &out));
    if (c->mutate) ((unsigned char *)v->pixels)[0] ^= 1; /* Deliberate contract violation. */
    return c->result;
}

static void consumers(void)
{
    optical_frame_owner o = {0};
    setup(&o, &standard);
    unsigned char source[33], dest[33];
    memset(source, 0xa5, sizeof source); memset(dest, 0xa5, sizeof dest);
    optical_frame_lease lease;
    assert(optical_frame_acquire(&o, source, sizeof source, &lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
    read_context context = {&o, &lease, 0, 0, 0};
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_consumer_read(&o, &lease, NULL, NULL));
    assert(optical_frame_consumer_read(&o, &lease, reentrant, &context) == OPTICAL_FRAME_OK);
    assert(context.calls == 1 && snapshot(&o).counts.read == 1 && !snapshot(&o).counts.copied);
    context.result = 7;
    assert(optical_frame_consumer_read(&o, &lease, reentrant, &context) == OPTICAL_FRAME_CONSUMER_FAILED);
    assert(context.calls == 2 && snapshot(&o).counts.read == 2);
    context.mutate = 1;
    assert(optical_frame_consumer_read(&o, &lease, reentrant, &context) == OPTICAL_FRAME_CHANGED);
    assert(context.calls == 3 && snapshot(&o).counts.read == 3);
    assert(snapshot(&o).state == OPTICAL_FRAME_RENDERED);
    optical_frame_view out;
    REJECT(o, OPTICAL_FRAME_CHANGED, optical_frame_copy(&o, &lease, dest, sizeof dest, 11, &out));
    REJECT(o, OPTICAL_FRAME_CHANGED, optical_frame_consumer_read(&o, &lease, reentrant, &context));
    untouched(dest, sizeof dest);
    assert(context.calls == 3);
    assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
}

static void exhaustion(void)
{
    optical_frame_owner o = {0};
    setup(&o, &standard);
    unsigned char source[33], dest[33];
    optical_frame_lease lease;
    optical_frame_view out;
    memset(source, 0xa5, sizeof source); memset(dest, 0xa5, sizeof dest);
    /* Fault injection only: production callers must never edit private state. */
    o.info.counts.staged = UINT64_MAX;
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_acquire(&o, source, sizeof source, &lease));
    o.info.counts.staged = 0;
    o.info.generation = UINT64_MAX - 1;
    assert(optical_frame_acquire(&o, source, sizeof source, &lease) == OPTICAL_FRAME_OK);
    assert(lease.generation == UINT64_MAX);
    o.info.counts.rendered = UINT64_MAX;
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_render(&o, &lease));
    untouched(source, sizeof source);
    o.info.counts.rendered = 0;
    assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
    size_t calls = 0;
    o.info.counts.read = UINT64_MAX;
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_consumer_read(&o, &lease, inspect, &calls));
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_copy(&o, &lease, dest, sizeof dest, 11, &out));
    assert(!calls);
    o.info.counts.read = 0; o.info.counts.copied = UINT64_MAX;
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_copy(&o, &lease, dest, sizeof dest, 11, &out));
    untouched(dest, sizeof dest);
    o.info.counts.copied = 0; o.info.counts.retired = UINT64_MAX;
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_retire(&o, &lease));
    o.info.counts.retired = 0;
    assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_configure(&o, &standard) == OPTICAL_FRAME_OK);
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_acquire(&o, source, sizeof source, &lease));
    assert(snapshot(&o).generation == UINT64_MAX);
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_init(&o));
}

static void renderer_identity(void)
{
    const size_t widths[] = {1, 3, 17, 1024, 1025};
    for (size_t i = 0; i < sizeof widths / sizeof widths[0]; ++i) {
        optical_frame_owner o = {0};
        optical_frame_config c = {{4, 1, 0.001, 100}, widths[i], 65, widths[i] * 3 + 13};
        setup(&o, &c);
        const size_t n = c.stride * c.height;
        unsigned char *a = malloc(n + 2 * GUARD), *b = malloc(n + 2 * GUARD);
        assert(a && b);
        memset(a, 0xa5, n + 2 * GUARD); memset(b, 0xa5, n + 2 * GUARD);
        optical_frame_lease lease;
        optics_metadata metadata;
        optics_stats stats = {0};
        assert(optical_frame_acquire(&o, a + GUARD, n, &lease) == OPTICAL_FRAME_OK);
        assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
        assert(optics_render(&c.params, c.width, c.height, c.stride, b + GUARD,
                             n, 999, &metadata, &stats) == 0);
        assert(memcmp(a, b, n + 2 * GUARD) == 0);
        assert(snapshot(&o).metadata.pixel_fnv1a == metadata.pixel_fnv1a);
        assert(snapshot(&o).metadata.frame_number != metadata.frame_number);
        assert(memcmp(a + GUARD, a + GUARD + 8 * c.stride, c.width * 3) == 0);
        for (size_t y = 0; y < c.height; ++y)
            untouched(a + GUARD + y * c.stride + c.width * 3, 13);
        assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
        assert(optical_frame_acquire(&o, a + GUARD, n, &lease) == OPTICAL_FRAME_OK);
        assert(lease.generation == 2);
        assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
        assert(memcmp(a, b, n + 2 * GUARD) == 0);
        assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
        untouched(a, GUARD); untouched(a + GUARD + n, GUARD);
        free(a); free(b);
    }
}

enum { AF_W = 1024, AF_H = 16, AF_STRIDE = AF_W * 3 + 13, AF_BYTES = AF_STRIDE * AF_H };
static const optical_frame_config af_config = {{4, 0.1, 0.001, 100}, AF_W, AF_H, AF_STRIDE};

static double roi_gradient(const unsigned char *pixels, size_t stride,
                           const optical_frame_af_request *r)
{
    double sum = 0;
    for (size_t y = r->y; y < r->y + r->height - 1; ++y)
        for (size_t x = r->x; x < r->x + r->width - 1; ++x) {
            size_t i = y * stride + x * 3;
            sum += abs((int)pixels[i + 3] - pixels[i]);
            sum += abs((int)pixels[i + stride] - pixels[i]);
        }
    return sum / (2.0 * (double)(r->width - 1) * (double)(r->height - 1));
}

static void autofocus(void)
{
    optical_frame_owner o = {0};
    setup(&o, &af_config);
    unsigned char *pixels = malloc(AF_BYTES), *saved = malloc(AF_BYTES);
    unsigned char *scratch = malloc(AF_BYTES + 7 + 2 * GUARD);
    assert(pixels && saved && scratch);
    for (size_t layer = 0; layer < 2; ++layer) {
        optical_frame_config c = af_config, input = c;
        optical_frame_af_request r = {layer * AF_W / 2 + 16, 4, AF_W / 2 - 32, 8,
                                      0.1, INFINITY}, original = r;
        assert(optical_frame_configure(&o, &c) == OPTICAL_FRAME_OK);
        memset(pixels, 0xa5, AF_BYTES);
        optical_frame_lease lease;
        assert(optical_frame_acquire(&o, pixels, AF_BYTES, &lease) == OPTICAL_FRAME_OK);
        assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
        double before = roi_gradient(pixels, AF_STRIDE, &r);
        assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
        memcpy(saved, pixels, AF_BYTES);
        optical_frame_owner expected = o;
        struct { unsigned char front[GUARD]; optical_frame_af_result result;
                 unsigned char back[GUARD]; } output;
        memset(&output, 0xa5, sizeof output);
        memset(scratch, 0xa5, AF_BYTES + 7 + 2 * GUARD);
        assert(optical_frame_autofocus(&o, &r, scratch + GUARD, AF_BYTES + 7,
                                       &output.result) == OPTICAL_FRAME_OK);
        optical_frame_af_result result = output.result;
        assert(fabs(result.focus_m - (layer ? 4.0 : 1.0)) < (layer ? 0.2 : 0.08));
        assert(result.focus_m >= r.near_m && result.focus_m <= r.far_m);
        assert(result.score > 0 && isfinite(result.score));
        assert(result.coarse_samples == 17 && result.refinement_samples > 0 &&
               result.refinement_samples <= 12);
        expected.info.config.params.focus_m = result.focus_m;
        assert(memcmp(&expected, &o, sizeof o) == 0);
        assert(memcmp(&c, &input, sizeof c) == 0 && memcmp(&r, &original, sizeof r) == 0);
        assert(memcmp(pixels, saved, AF_BYTES) == 0);
        untouched(output.front, GUARD); untouched(output.back, GUARD);
        untouched(scratch, GUARD); untouched(scratch + GUARD + AF_BYTES, 7 + GUARD);
        for (size_t y = 0; y < AF_H; ++y)
            untouched(scratch + GUARD + y * AF_STRIDE + AF_W * 3, 13);
        assert(optical_frame_acquire(&o, pixels, AF_BYTES, &lease) == OPTICAL_FRAME_OK);
        assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
        double after = roi_gradient(pixels, AF_STRIDE, &r);
        assert(after > 5 * before && after > 5);
        optical_frame_af_request other = r;
        other.x = (1 - layer) * AF_W / 2 + 16;
        assert(after > 2 * roi_gradient(pixels, AF_STRIDE, &other));
        assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
    }
    /* A restricted range must choose its actual best endpoint, not a scene oracle. */
    optical_frame_af_request r = {16, 4, AF_W / 2 - 32, 8, 2, 8};
    optical_frame_af_result result;
    assert(optical_frame_autofocus(&o, &r, scratch + GUARD, AF_BYTES, &result)
           == OPTICAL_FRAME_OK);
    assert(result.focus_m == 2 && result.coarse_samples == 17);
    free(pixels); free(saved); free(scratch);
}

static void autofocus_flat(void)
{
    optical_frame_owner o = {0};
    setup(&o, &af_config);
    unsigned char *scratch = malloc(AF_BYTES + 2 * GUARD);
    assert(scratch);
    optical_frame_af_request original = {16, 4, AF_W / 2 - 32, 8, 0.1, INFINITY};
    for (size_t i = 0; i < 4; ++i) {
        optical_frame_config c = af_config;
        optical_frame_af_request r = original;
        if (i == 0) c.params.shutter_s = 100; /* Saturated texture. */
        if (i == 1) { c.params.iso = DBL_MIN; c.params.shutter_s = DBL_MIN; }
        if (i == 2) { r.x = 1; r.y = 1; r.width = 2; r.height = 2; }
        if (i == 3) { r.near_m = 1e100; r.far_m = 1e101; } /* Positive but flat response. */
        optical_frame_af_request saved_request = r;
        assert(optical_frame_configure(&o, &c) == OPTICAL_FRAME_OK);
        optical_frame_af_result out;
        unsigned char prior[sizeof out];
        memset(&out, 0x5a, sizeof out); memcpy(prior, &out, sizeof out);
        memset(scratch, 0xa5, AF_BYTES + 2 * GUARD);
        REJECT(o, OPTICAL_FRAME_NO_CONTRAST,
               optical_frame_autofocus(&o, &r, scratch + GUARD, AF_BYTES, &out));
        assert(memcmp(prior, &out, sizeof out) == 0);
        assert(memcmp(&r, &saved_request, sizeof r) == 0);
        untouched(scratch, GUARD); untouched(scratch + GUARD + AF_BYTES, GUARD);
        for (size_t y = 0; y < AF_H; ++y)
            untouched(scratch + GUARD + y * AF_STRIDE + AF_W * 3, 13);
        assert(roi_gradient(scratch + GUARD, AF_STRIDE, &r) == 0 || i == 3);
        if (i == 3) assert(roi_gradient(scratch + GUARD, AF_STRIDE, &r) > 0);
    }
    free(scratch);
}

static void autofocus_bounds(void)
{
    optical_frame_owner o = {0};
    optical_frame_af_request valid = {0, 0, 3, 3, 0.1, INFINITY}, r = valid;
    optical_frame_af_result out;
    unsigned char prior[sizeof out], pixels[64], scratch[64];
    memset(&out, 0x5a, sizeof out); memcpy(prior, &out, sizeof out);
    memset(pixels, 0xa5, sizeof pixels); memset(scratch, 0xa5, sizeof scratch);
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_autofocus(&o, &r, scratch, 64, &out));
    assert(optical_frame_init(&o) == OPTICAL_FRAME_OK);
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_autofocus(&o, &r, scratch, 64, &out));
    assert(optical_frame_configure(&o, &standard) == OPTICAL_FRAME_OK);
    for (size_t i = 0; i < 10; ++i) {
        r = valid;
        if (i == 0) r.width = 0;
        if (i == 1) r.width = 1;
        if (i == 2) r.height = 1;
        if (i == 3) r.x = 1;
        if (i == 4) r.y = 1;
        if (i == 5) r.width = SIZE_MAX;
        if (i == 6) r.height = SIZE_MAX;
        if (i == 7) r.x = SIZE_MAX;
        if (i == 8) r.y = SIZE_MAX;
        if (i == 9) r.height = 0;
        REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_autofocus(&o, &r, scratch, 64, &out));
    }
    const double bad[] = {NAN, -INFINITY, INFINITY, 0, -1, 0.099};
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; ++i) {
        r = valid; r.near_m = bad[i];
        REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_autofocus(&o, &r, scratch, 64, &out));
        if (bad[i] != INFINITY) {
            r = valid; r.far_m = bad[i];
            REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_autofocus(&o, &r, scratch, 64, &out));
        }
    }
    r = valid; r.far_m = r.near_m;
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_autofocus(&o, &r, scratch, 64, &out));
    r.near_m = 4; r.far_m = 1;
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_autofocus(&o, &r, scratch, 64, &out));
    r.near_m = 1; r.far_m = nextafter(1, 2);
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_autofocus(&o, &r, scratch, 64, &out));
    r = valid;
    REJECT(o, OPTICAL_FRAME_TOO_SMALL, optical_frame_autofocus(&o, &r, scratch, 32, &out));
    REJECT(o, OPTICAL_FRAME_TOO_SMALL, optical_frame_autofocus(&o, &r, scratch, 0, &out));
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_autofocus(&o, NULL, scratch, 64, &out));
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_autofocus(&o, &r, NULL, 64, &out));
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_autofocus(&o, &r, scratch, 64, NULL));
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_autofocus(&o, &r, scratch, SIZE_MAX, &out));
    unsigned char *end = (unsigned char *)(uintptr_t)(UINTPTR_MAX - 1);
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_autofocus(&o, &r, end, 64, &out));
    REJECT(o, OPTICAL_FRAME_OVERFLOW,
           optical_frame_autofocus(&o, (optical_frame_af_request *)end, scratch, 64, &out));
    REJECT(o, OPTICAL_FRAME_OVERFLOW,
           optical_frame_autofocus(&o, &r, scratch, 64, (optical_frame_af_result *)end));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_autofocus(&o, (optical_frame_af_request *)&o, scratch, 64, &out));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_autofocus(&o, &r, (unsigned char *)&o, sizeof o, &out));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_autofocus(&o, &r, scratch, 64, (optical_frame_af_result *)&o));
    union { optical_frame_af_request request; optical_frame_af_result result;
            unsigned char bytes[256]; } alias;
    memset(&alias, 0xa5, sizeof alias);
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_autofocus(&o, &alias.request, alias.bytes, sizeof alias, &out));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_autofocus(&o, &r, alias.bytes, sizeof alias, &alias.result));
    REJECT(o, OPTICAL_FRAME_OVERLAP,
           optical_frame_autofocus(&o, &alias.request, scratch, 64, &alias.result));
    untouched(alias.bytes, sizeof alias);
    /* Fault injection: callers cannot normally bypass configure's stride checks. */
    o.info.config.stride = 8;
    REJECT(o, OPTICAL_FRAME_INVALID, optical_frame_autofocus(&o, &r, scratch, 64, &out));
    o.info.config.stride = SIZE_MAX;
    REJECT(o, OPTICAL_FRAME_OVERFLOW, optical_frame_autofocus(&o, &r, scratch, 64, &out));
    o.info.config = standard;
    optical_frame_lease lease;
    assert(optical_frame_acquire(&o, pixels, sizeof pixels, &lease) == OPTICAL_FRAME_OK);
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_autofocus(&o, &r, pixels, 64, &out));
    untouched(pixels, sizeof pixels);
    assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
    unsigned char saved[sizeof pixels]; memcpy(saved, pixels, sizeof pixels);
    REJECT(o, OPTICAL_FRAME_STATE, optical_frame_autofocus(&o, &r, pixels, 64, &out));
    assert(memcmp(saved, pixels, sizeof pixels) == 0);
    assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
    assert(memcmp(prior, &out, sizeof out) == 0);
    untouched(scratch, sizeof scratch);
}

typedef struct {
    unsigned char *output;
    size_t capacity;
    struct jpeg_engine_result result;
} encoder_context;

static int encode(const optical_frame_view *v, void *context)
{
    encoder_context *c = context;
    assert(v->format == OPTICAL_FRAME_VIRTUAL_RGB888);
    c->result = jpeg_engine_encode_rgb888(v->pixels, v->size, v->width, v->height,
                                         v->stride, 95, c->output, c->capacity);
    return c->result.status != JPEG_ENGINE_OK;
}

static void encoded_frames(void)
{
    optical_frame_owner o = {0};
    assert(optical_frame_init(&o) == OPTICAL_FRAME_OK);
    const char *names[] = {"base", "stopped", "far", "shutter", "iso", "odd",
                           "defocused", "af-near", "af-far"};
    for (size_t i = 0; i < sizeof names / sizeof names[0]; ++i) {
        optical_frame_config c = {{4, 1, 0.001, 100}, i == 5 ? 1025 : 1024,
                                   i == 5 ? 65 : 64, 0};
        c.stride = c.width * 3 + 13;
        if (i == 1) c.params.f_number = 8;
        if (i == 2) c.params.focus_m = 4;
        if (i == 3) c.params.shutter_s *= 2;
        if (i == 4) c.params.iso *= 2;
        if (i >= 6) c.params.focus_m = 0.1;
        const size_t n = c.stride * c.height, capacity = n + 4096;
        unsigned char *raw = malloc(n + 2 * GUARD), *saved = malloc(n + 2 * GUARD);
        unsigned char *output = malloc(capacity + 2 * GUARD);
        assert(raw && saved && output);
        memset(raw, 0xa5, n + 2 * GUARD); memset(output, 0xa5, capacity + 2 * GUARD);
        assert(optical_frame_configure(&o, &c) == OPTICAL_FRAME_OK);
        if (i >= 7) {
            optical_frame_af_request request = {i == 7 ? 20 : c.width / 2 + 20,
                16, c.width / 2 - 40, c.height - 32, 0.1, INFINITY};
            optical_frame_af_result result;
            assert(optical_frame_autofocus(&o, &request, raw + GUARD, n, &result)
                   == OPTICAL_FRAME_OK);
            assert(fabs(result.focus_m - (i == 7 ? 1.0 : 4.0)) < 0.12);
            assert(result.score > 0 && result.coarse_samples == 17 &&
                   result.refinement_samples > 0 && result.refinement_samples <= 12);
        }
        optical_frame_lease lease;
        assert(optical_frame_acquire(&o, raw + GUARD, n, &lease) == OPTICAL_FRAME_OK);
        assert(optical_frame_render(&o, &lease) == OPTICAL_FRAME_OK);
        memcpy(saved, raw, n + 2 * GUARD);
        encoder_context encoder = {output + GUARD, capacity, {JPEG_ENGINE_OK, 0}};
        assert(optical_frame_consumer_read(&o, &lease, encode, &encoder) == OPTICAL_FRAME_OK);
        assert(encoder.result.status == JPEG_ENGINE_OK && encoder.result.used > 32);
        assert(encoder.result.used <= capacity && memcmp(raw, saved, n + 2 * GUARD) == 0);
        untouched(output, GUARD);
        untouched(output + GUARD + encoder.result.used, capacity - encoder.result.used + GUARD);
        optical_frame_info info = snapshot(&o);
        assert(info.counts.read == i + 1 && !info.counts.copied && info.counts.retired == i);
        assert(printf("FRAME %s %zu %zu %zu %" PRIu64 " %" PRIu64 " %zu\n",
                      names[i], c.width, c.height, c.stride, lease.generation,
                      info.metadata.pixel_fnv1a, encoder.result.used) > 0);
        assert(fwrite(raw + GUARD, 1, n, stdout) == n);
        assert(fwrite(output + GUARD, 1, encoder.result.used, stdout) == encoder.result.used);
        assert(fflush(stdout) == 0);
        /* Pillow must decode and verify the bytes before this test retires. */
        char reply[128], extra;
        uint64_t generation, digest;
        assert(fgets(reply, sizeof reply, stdin));
        assert(sscanf(reply, "decoded %" SCNu64 " %" SCNu64 " %c",
                      &generation, &digest, &extra) == 2);
        assert(generation == lease.generation && digest == info.metadata.pixel_fnv1a);
        assert(snapshot(&o).state == OPTICAL_FRAME_RENDERED);
        assert(optical_frame_retire(&o, &lease) == OPTICAL_FRAME_OK);
        assert(snapshot(&o).counts.retired == i + 1);
        assert(memcmp(raw, saved, n + 2 * GUARD) == 0);
        free(raw); free(saved); free(output);
    }
    assert(puts("PASS decoded-before-retire 9") >= 0);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "lifecycle")) lifecycle();
    else if (!strcmp(argv[1], "configuration")) configuration();
    else if (!strcmp(argv[1], "bounds")) bounds();
    else if (!strcmp(argv[1], "copies")) copies();
    else if (!strcmp(argv[1], "consumers")) consumers();
    else if (!strcmp(argv[1], "exhaustion")) exhaustion();
    else if (!strcmp(argv[1], "renderer-identity")) renderer_identity();
    else if (!strcmp(argv[1], "autofocus")) autofocus();
    else if (!strcmp(argv[1], "autofocus-flat")) autofocus_flat();
    else if (!strcmp(argv[1], "autofocus-bounds")) autofocus_bounds();
    else if (!strcmp(argv[1], "encode")) { encoded_frames(); return 0; }
    else assert(0);
    assert(printf("PASS %s\n", argv[1]) > 0);
    return 0;
}
