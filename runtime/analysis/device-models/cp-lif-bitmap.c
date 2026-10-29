/* SPDX-License-Identifier: MIT */
#include "cp-lif-bitmap.h"
#include <errno.h>
#include <string.h>
#include <unistd.h>

static int span(const void *p, size_t n)
{
    return p != NULL && n <= UINTPTR_MAX - (uintptr_t)p;
}
static int overlap(const void *a, size_t an, const void *b, size_t bn)
{
    return (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static int output(const void *out, size_t n, size_t need, size_t align,
                  const void *a, size_t an, const void *b, size_t bn)
{
    if (!span(out, n) || (uintptr_t)out % align ||
        overlap(out, n, a, an) || overlap(out, n, b, bn)) return -EINVAL;
    return n < need ? -EMSGSIZE : 0;
}
static int guard_valid(const struct cp_lif_bitmap_guard *g)
{
    if (!span(g, sizeof(*g)) || (uintptr_t)g % _Alignof(struct cp_lif_bitmap_guard)) return -EINVAL;
    if (!g->owner_pid || g->origin == CP_LIF_ORIGIN_NONE) return -ENODATA;
    if (g->owner_pid != (uint32_t)getpid() ||
        (g->origin != CP_LIF_ORIGIN_HOST_TEST && g->origin != CP_LIF_ORIGIN_VIRTUAL_SOURCE)) return -EXDEV;
    if (g->quiescent > 1) return -EINVAL;
    if (!g->quiescent || g->sequence_before != g->sequence_after || (g->sequence_before & 1u)) return -EAGAIN;
    return 0;
}
static int owner_guard(const struct cp_lif_bitmap_owner *o, const struct cp_lif_bitmap_guard *g)
{
    int rc = guard_valid(g);
    if (rc) return rc;
    if (!span(o, sizeof(*o)) || (uintptr_t)o % _Alignof(struct cp_lif_bitmap_owner) ||
        overlap(o, sizeof(*o), g, sizeof(*g))) return -EINVAL;
    if (!o->revision) return -ENODATA;
    if (o->revision != CP_LIF_BITMAP_OWNER_REVISION) return -ENOTSUP;
    if (o->owner_pid != (uint32_t)getpid() || o->owner_pid != g->owner_pid || o->origin != g->origin) return -EXDEV;
    if (g->sequence_before <= o->sequence) return -ESTALE;
    return 0;
}
static int property(const struct cp_lif_bitmap_inputs *s, size_t at, size_t n)
{
    size_t i;
    for (i = at; i < at + n; ++i) {
        if (s->property_known[i] > 1) return -EINVAL;
        if (!s->property_known[i]) return -ENODATA;
    }
    return 0;
}
static uint32_t le32(const unsigned char *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
int cp_lif_bitmap_build(const struct cp_lif_bitmap_inputs *s,
    const struct cp_lif_bitmap_guard *g, struct cp_lif_bitmap_product *out, size_t cap)
{
    struct cp_lif_bitmap_product r;
    unsigned char *b = r.bitmap;
    uint32_t a, d, checksum = 0x25;
    size_t i;
    int rc = guard_valid(g);
    if (rc) return rc;
    if (!span(s, sizeof(*s)) || (uintptr_t)s % _Alignof(struct cp_lif_bitmap_inputs)) return -EINVAL;
    rc = output(out, cap, sizeof(*out), _Alignof(struct cp_lif_bitmap_product), s, sizeof(*s), g, sizeof(*g));
    if (rc) return rc;
    if (s->known & ~31u) return -EINVAL;
    if (!(s->known & CP_LIF_BITMAP_K_KNOWN)) return -ENODATA;
    memset(&r, 0, sizeof(r));
    r.gate = 1;
    if (s->k == 1 || s->k == 2) {
        b[0] = 0x40;
    } else if (s->k == 4 || s->k == 5) {
        uint32_t required = CP_LIF_BITMAP_MODE_KNOWN | CP_LIF_BITMAP_Z_KNOWN | CP_LIF_BITMAP_S43_KNOWN;
        if ((s->known & required) != required) return -ENODATA;
        rc = property(s, 0x161, 1);
        if (rc) return rc;
        b[0] = 0xdf; b[1] = 0x79; b[8] = 0x2f;
        if (s->property[0x161] & 0x20) { b[2] = 0x80; b[3] |= 6; }
        else b[0] |= 0x20;
        if (s->mode == 1) {
            rc = property(s, 0x52, 1);
            if (rc) return rc;
            if ((s->property[0x52] & 0x60) == 0x60) {
                b[2] |= 3;
                if (s->property[0x161] & 0x20) b[3] |= 8;
                else b[1] |= 0x80;
            }
        }
        if (!s->s43) b[1] |= 6;
        rc = property(s, 0x15a, 4);
        if (rc) return rc;
        a = le32(s->property + 0x15a);
        if (!s->z) {
            rc = property(s, 0x15e, 4);
            if (rc) return rc;
            d = le32(s->property + 0x15e);
            if (a & UINT32_C(0x1000)) b[2] |= 4;
            if (a & UINT32_C(0x8000)) b[2] |= 8;
            if (a & UINT32_C(0x200000)) b[2] |= 0x10;
            if (d & UINT32_C(0x40000000)) b[3] |= 1;
        }
        if (a & UINT32_C(0x80000000)) b[2] |= 0x40;
        if (s->k == 5 || !s->s43) b[8] |= 0x10;
        if (s->k == 4) {
            rc = property(s, 0x51, 1);
            if (rc) return rc;
            if (s->property[0x51] & 0x20) b[8] |= 0x80;
        }
        if (!s->z) {
            if (s->k == 5) {
                if (!(s->known & CP_LIF_BITMAP_S5A_KNOWN)) return -ENODATA;
                if (s->s5a) b[9] |= 1;
            }
            if (a & UINT32_C(0x10000000)) b[9] |= 2;
            if (a & UINT32_C(0x20000000)) b[9] |= 4;
        }
    } else {
        r.gate = 0; /* Actual a91e96 event: this is known all-off, not a default. */
    }
    r.command[0] = 0x0a;
    memcpy(r.command + 1, b, CP_LIF_BITMAP_BYTES);
    r.wire[0] = 0xf0; r.wire[1] = 0x19; r.wire[3] = 2;
    memcpy(r.wire + 5, r.command, sizeof(r.command));
    for (i = 0; i < CP_LIF_BITMAP_BYTES; ++i) checksum += b[i];
    r.wire[22] = (unsigned char)checksum; r.wire[23] = (unsigned char)(checksum >> 8); r.wire[24] = 0x55;
    r.logical_bytes = CP_LIF_BITMAP_WIRE_BYTES; r.dma_span = CP_LIF_BITMAP_DMA_SPAN;
    r.dma_known_bytes = CP_LIF_BITMAP_WIRE_BYTES; r.owned_virtual_data = 1;
    memcpy(out, &r, sizeof(r));
    return 0;
}
int cp_lif_bitmap_owner_init(struct cp_lif_bitmap_owner *o, const struct cp_lif_bitmap_guard *g)
{
    struct cp_lif_bitmap_owner r;
    int rc = guard_valid(g);
    if (rc) return rc;
    if (!span(o, sizeof(*o)) || (uintptr_t)o % _Alignof(struct cp_lif_bitmap_owner) || overlap(o, sizeof(*o), g, sizeof(*g))) return -EINVAL;
    if (o->revision || o->owner_pid) return -EALREADY;
    memset(&r, 0, sizeof(r));
    r.revision = CP_LIF_BITMAP_OWNER_REVISION; r.owner_pid = g->owner_pid; r.origin = g->origin;
    r.sequence = g->sequence_before;
    memcpy(o, &r, sizeof(r));
    return 0;
}
int cp_lif_bitmap_request(struct cp_lif_bitmap_owner *o, unsigned selector,
    const struct cp_lif_bitmap_inputs *s, const struct cp_lif_bitmap_guard *g,
    struct cp_lif_bitmap_lease *out, size_t cap)
{
    struct cp_lif_bitmap_owner r;
    struct cp_lif_bitmap_lease lease;
    struct cp_lif_bitmap_product p;
    int rc = owner_guard(o, g);
    if (rc) return rc;
    rc = output(out, cap, sizeof(*out), _Alignof(struct cp_lif_bitmap_lease), o, sizeof(*o), g, sizeof(*g));
    if (rc) return rc;
    if (selector == 2) return -ENOTSUP;
    if (o->configured_generation == UINT64_MAX) return -EOVERFLOW;
    if (selector == 1) {
        if (!span(s, sizeof(*s)) || overlap(o, sizeof(*o), s, sizeof(*s)) || overlap(out, cap, s, sizeof(*s))) return -EINVAL;
        rc = cp_lif_bitmap_build(s, g, &p, sizeof(p));
        if (rc) return rc;
        if (!o->pending && o->next_token == UINT64_MAX) return -EOVERFLOW;
    }
    memcpy(&r, o, sizeof(r));
    memset(&lease, 0, sizeof(lease));
    ++r.configured_generation; r.configured_known = 1; r.sequence = g->sequence_before;
    r.data_producer_sequence = g->sequence_before;
    if (selector == 1) {
        memcpy(r.configured, p.bitmap, sizeof(r.configured)); r.gate = p.gate;
        /* shortcut: one pending lease; newer configuration commits without a new lease. */
        if (!r.pending) {
            lease.token = ++r.next_token; lease.configured_generation = r.configured_generation;
            lease.producer_sequence = r.data_producer_sequence; lease.owner_pid = r.owner_pid; lease.origin = r.origin;
            memcpy(lease.wire, p.wire, sizeof(lease.wire)); lease.logical_bytes = p.logical_bytes;
            lease.dma_span = p.dma_span; lease.dma_known_bytes = p.dma_known_bytes; lease.owned_virtual_data = 1;
            memcpy(&r.lease, &lease, sizeof(lease)); r.pending = 1;
        }
    } else {
        memset(r.configured, 0, sizeof(r.configured)); r.gate = 0;
    }
    memcpy(o, &r, sizeof(r)); memcpy(out, &lease, sizeof(lease));
    return 0;
}
int cp_lif_bitmap_gate_clear(struct cp_lif_bitmap_owner *o, const struct cp_lif_bitmap_guard *g)
{
    int rc = owner_guard(o, g);
    if (rc) return rc;
    if (!o->configured_known) return -ENODATA;
    o->gate = 0; o->sequence = g->sequence_before;
    return 0;
}
int cp_lif_bitmap_observe_transport_consumed(struct cp_lif_bitmap_owner *o,
    const struct cp_lif_bitmap_lease *lease, const unsigned char *actual, size_t n,
    const struct cp_lif_bitmap_guard *g)
{
    int rc = owner_guard(o, g);
    if (rc) return rc;
    if (!span(lease, sizeof(*lease)) || (uintptr_t)lease % _Alignof(struct cp_lif_bitmap_lease) || !span(actual, n) ||
        overlap(o, sizeof(*o), actual, n) || overlap(o, sizeof(*o), lease, sizeof(*lease))) return -EINVAL;
    if (n != CP_LIF_BITMAP_WIRE_BYTES) return -EMSGSIZE;
    if (!o->pending) return -ENODATA;
    if (!lease->token || lease->token != o->lease.token || lease->configured_generation != o->lease.configured_generation ||
        lease->producer_sequence != o->lease.producer_sequence || lease->owner_pid != o->owner_pid || lease->origin != o->origin) return -ESTALE;
    if (lease->logical_bytes != CP_LIF_BITMAP_WIRE_BYTES || lease->dma_span != CP_LIF_BITMAP_DMA_SPAN ||
        lease->dma_known_bytes != CP_LIF_BITMAP_WIRE_BYTES || lease->owned_virtual_data != 1) return -EINVAL;
    if (memcmp(lease->wire, o->lease.wire, n) || memcmp(actual, o->lease.wire, n)) return -EBADMSG;
    o->consumed_generation = o->lease.configured_generation;
    o->consumed_producer_sequence = o->lease.producer_sequence;
    o->owned_transport_consumed = 1; o->pending = 0; o->sequence = g->sequence_before;
    return 0;
}
int cp_lif_bitmap_receive_decode(struct cp_lif_bitmap_owner *o,
    const unsigned char *rx, size_t n, const struct cp_lif_bitmap_guard *g,
    struct cp_lif_bitmap_received *out, size_t cap)
{
    struct cp_lif_bitmap_received r;
    int rc = owner_guard(o, g);
    if (rc) return rc;
    if (!span(rx, n) || overlap(o, sizeof(*o), rx, n)) return -EINVAL;
    rc = output(out, cap, sizeof(*out), _Alignof(struct cp_lif_bitmap_received), o, sizeof(*o), g, sizeof(*g));
    if (rc) return rc;
    if (overlap(out, cap, rx, n)) return -EINVAL;
    if (!o->configured_known || !o->owned_transport_consumed) return -ENODATA;
    if (o->configured_generation != o->consumed_generation || o->data_producer_sequence != o->consumed_producer_sequence) return -EAGAIN;
    memset(&r, 0, sizeof(r));
    r.configured_generation = o->configured_generation; r.consumed_generation = o->consumed_generation;
    r.data_producer_sequence = o->data_producer_sequence; r.configured_matches_consumed = 1; r.owned_virtual_data = 1;
    r.context.sequence_before = g->sequence_before; r.context.sequence_after = g->sequence_after;
    r.context.origin = g->origin; r.context.quiescent = 1;
    r.context.bitmap_event = CP_LIF_BITMAP_A923D0_SNAPSHOT;
    memcpy(r.context.bitmap, o->configured, sizeof(r.context.bitmap));
    memset(r.context.bitmap_known, 1, sizeof(r.context.bitmap_known));
    r.context.type1_source_byte = o->gate; r.context.type1_source_known = 1;
    rc = cp_lif_frame_decode(rx, n, &r.context, &r.decoded, sizeof(r.decoded));
    if (rc) return rc;
    o->sequence = g->sequence_before;
    memcpy(out, &r, sizeof(r));
    return 0;
}
