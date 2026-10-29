/* SPDX-License-Identifier: MIT */
#include "lif-cache.h"
#include <errno.h>
#include <string.h>
#include <unistd.h>

struct region { const void *p; size_t n; };
static int span(const void *p, size_t n)
{ return p != NULL && n <= UINTPTR_MAX - (uintptr_t)p; }
static int overlap(const void *a, size_t an, const void *b, size_t bn)
{
    return an && bn && (uintptr_t)a < (uintptr_t)b + bn &&
           (uintptr_t)b < (uintptr_t)a + an;
}
static int disjoint(const struct region *r, size_t count)
{
    size_t i, j;
    for (i = 0; i < count; ++i) {
        if (!span(r[i].p, r[i].n)) return -EINVAL;
        for (j = 0; j < i; ++j)
            if (overlap(r[i].p, r[i].n, r[j].p, r[j].n)) return -EINVAL;
    }
    return 0;
}
static int finish(int rc, int saved) { errno = saved; return rc; }
static int guard_valid(const struct cp_lif_bitmap_guard *g)
{
    if (!span(g, sizeof(*g)) ||
        (uintptr_t)g % _Alignof(struct cp_lif_bitmap_guard)) return -EINVAL;
    if (!g->owner_pid || g->origin == CP_LIF_ORIGIN_NONE) return -ENODATA;
    if (g->owner_pid != (uint32_t)getpid() ||
        (g->origin != CP_LIF_ORIGIN_HOST_TEST &&
         g->origin != CP_LIF_ORIGIN_VIRTUAL_SOURCE)) return -EXDEV;
    if (g->quiescent > 1) return -EINVAL;
    if (!g->quiescent || g->sequence_before != g->sequence_after ||
        (g->sequence_before & UINT64_C(1))) return -EAGAIN;
    return 0;
}
static int owner_guard(const struct lif_cache_owner *o,
    const struct cp_lif_bitmap_guard *g, int reading)
{
    int rc;
    if (!span(o, sizeof(*o)) || (uintptr_t)o % _Alignof(struct lif_cache_owner) ||
        !span(g, sizeof(*g)) || overlap(o, sizeof(*o), g, sizeof(*g))) return -EINVAL;
    rc = guard_valid(g);
    if (rc) return rc;
    if (!o->revision) return -ENODATA;
    if (o->revision != LIF_CACHE_REVISION) return -ENOTSUP;
    if (!span(o->pool, o->value.pool_capacity) ||
        o->value.pool_capacity < LIF_CACHE_RESERVE_BYTES ||
        overlap(o, sizeof(*o), o->pool, o->value.pool_capacity) ||
        overlap(g, sizeof(*g), o->pool, o->value.pool_capacity)) return -EINVAL;
    if (o->value.owner_pid != (uint32_t)getpid() ||
        o->value.owner_pid != g->owner_pid || o->value.origin != g->origin) return -EXDEV;
    if (reading ? g->sequence_before != o->value.sequence :
                  g->sequence_before <= o->value.sequence) return -ESTALE;
    return 0;
}
static int output_valid(const struct lif_cache_owner *o,
    const struct cp_lif_bitmap_guard *g, void *out, size_t cap, size_t need, size_t alignment)
{
    if (!span(out, cap) || (uintptr_t)out % alignment ||
        overlap(out, cap, o, sizeof(*o)) || overlap(out, cap, g, sizeof(*g)) ||
        overlap(out, cap, o->pool, o->value.pool_capacity)) return -EINVAL;
    return cap < need ? -EMSGSIZE : 0;
}
static struct lif_cache_history_ref empty_ref(void)
{
    struct lif_cache_history_ref r;
    memset(&r, 0, sizeof(r));
    r.known = 1; r.handle.slot = 0xff;
    return r;
}
int lif_cache_init(struct lif_cache_owner *o, unsigned char *pool, size_t capacity,
    const struct cp_lif_bitmap_guard *g)
{
    struct lif_cache_owner next;
    const struct region r[] = {{o, sizeof(*o)}, {pool, capacity}, {g, sizeof(*g)}};
    size_t i;
    int saved = errno, rc = disjoint(r, 3);
    if (!rc && (uintptr_t)o % _Alignof(struct lif_cache_owner)) rc = -EINVAL;
    if (!rc) rc = guard_valid(g);
    if (!rc && capacity < LIF_CACHE_RESERVE_BYTES) rc = -ENOSPC;
    if (rc) return finish(rc, saved);
    for (i = 0; i < sizeof(*o); ++i)
        if (((const unsigned char *)o)[i]) return finish(-EALREADY, saved);
    memset(&next, 0, sizeof(next));
    next.revision = LIF_CACHE_REVISION; next.pool = pool;
    next.value.owner_pid = g->owner_pid; next.value.origin = g->origin;
    next.value.sequence = g->sequence_before; next.value.pool_capacity = capacity;
    next.value.diagnostic_only = next.value.owned_virtual_policy = 1;
    memcpy(o, &next, sizeof(next));
    return finish(0, saved);
}
int lif_cache_consume_reset_and_prime(struct lif_cache_owner *o,
    const struct cp_lif_bitmap_guard *g)
{
    int saved = errno, rc = owner_guard(o, g, 0);
    if (rc) return finish(rc, saved);
    memset(o->value.records, 0, sizeof(o->value.records));
    memset(&o->value.current, 0, sizeof(o->value.current));
    memset(&o->value.previous, 0, sizeof(o->value.previous));
    o->value.global_last[0] = o->value.global_last[1] = empty_ref();
    o->value.write_offset = o->value.last_rx_size = 0;
    o->value.next_slot = 0; o->value.source_primed = 1;
    o->value.reset_sequence = o->value.sequence = g->sequence_before;
    return finish(0, saved);
}
int lif_cache_consume_cycle_roll(struct lif_cache_owner *o,
    const unsigned char *actual, size_t n, const struct cp_lif_bitmap_guard *g)
{
    int saved = errno, rc = owner_guard(o, g, 0);
    if (rc) return finish(rc, saved);
    if (!span(actual, n) || overlap(actual, n, o, sizeof(*o)) ||
        overlap(actual, n, g, sizeof(*g)) ||
        overlap(actual, n, o->pool, o->value.pool_capacity)) return finish(-EINVAL, saved);
    if (n != 1) return finish(-EMSGSIZE, saved);
    memcpy(&o->value.previous, &o->value.current, sizeof(o->value.previous));
    memset(&o->value.current, 0, sizeof(o->value.current));
    o->value.current.known = 1; o->value.current.token = actual[0];
    o->value.current.command[0] = o->value.current.command[1] = empty_ref();
    o->value.current.sequence = o->value.sequence = g->sequence_before;
    return finish(0, saved);
}
static int reserve_offset(const struct lif_cache_owner *o, size_t *offset)
{
    size_t end;
    uintptr_t aligned, base = (uintptr_t)o->pool;
    if (o->value.next_slot >= LIF_CACHE_RECORDS ||
        o->value.write_offset > o->value.pool_capacity ||
        o->value.last_rx_size > o->value.pool_capacity - o->value.write_offset) return -EINVAL;
    *offset = 0;
    if (!o->value.last_rx_size) return 0;
    end = o->value.write_offset + o->value.last_rx_size;
    if (base + end > UINTPTR_MAX - 15u) return -EOVERFLOW;
    aligned = (base + end + 15u) & ~(uintptr_t)15u;
    if (aligned - base <= o->value.pool_capacity &&
        LIF_CACHE_RESERVE_BYTES <= o->value.pool_capacity - (size_t)(aligned - base))
        *offset = (size_t)(aligned - base);
    return 0;
}
static int receive(struct lif_cache_owner *o, const struct lif_capabilities_owner *cap_owner,
    struct lif_capabilities_owner *mutable_cap, const struct cp_lif_bitmap_guard *cg,
    struct cp_lif_bitmap_owner *bm,
    const unsigned char *rx, size_t n, const struct lif_cache_ingress *ingress,
    const struct cp_lif_bitmap_guard *g, struct lif_cache_handle *out, size_t out_cap)
{
    struct lif_capabilities_readback capabilities;
    struct cp_lif_bitmap_received received;
    struct lif_cache_record record;
    struct lif_cache_history_ref ref;
    size_t offset, i;
    const struct cp_lif_command_view *last_nonempty = NULL;
    int rc = owner_guard(o, g, 0);
    if (rc) return rc;
    {
        const struct region r[] = {{o, sizeof(*o)}, {o->pool, o->value.pool_capacity},
            {cap_owner, sizeof(*cap_owner)}, {cg, sizeof(*cg)}, {bm, sizeof(*bm)},
            {rx, n}, {ingress, sizeof(*ingress)}, {g, sizeof(*g)}, {out, out_cap}};
        rc = disjoint(r, sizeof(r) / sizeof(r[0]));
    }
    if (rc || (uintptr_t)cap_owner % _Alignof(struct lif_capabilities_owner) ||
        (uintptr_t)cg % _Alignof(struct cp_lif_bitmap_guard) ||
        (uintptr_t)bm % _Alignof(struct cp_lif_bitmap_owner) ||
        (uintptr_t)ingress % _Alignof(struct lif_cache_ingress) ||
        (uintptr_t)out % _Alignof(struct lif_cache_handle)) return -EINVAL;
    if (out_cap < sizeof(*out) || n < 9 || n > LIF_CACHE_RESERVE_BYTES) return -EMSGSIZE;
    if (!o->value.source_primed) return -ENODATA;
    if (o->value.next_incarnation == UINT64_MAX) return -EOVERFLOW;
    rc = reserve_offset(o, &offset);
    if (rc) return rc;
    /* Use the actual capability API and its exact read guard for admission. */
    rc = lif_capabilities_snapshot(cap_owner, cg, &capabilities, sizeof(capabilities));
    if (rc) return rc;
    if (capabilities.owner_pid != g->owner_pid || capabilities.origin != g->origin) return -EXDEV;
    if (g->sequence_before <= capabilities.sequence) return -ESTALE;
    if (!capabilities.z_known || !capabilities.support_known[5] ||
        !capabilities.support_known[6]) return -ENODATA;
    if (capabilities.z) return -ENOTSUP;
    if (!capabilities.support[5] || !capabilities.support[6]) return -EACCES;
    /* After this one live decode succeeds, all remaining work is infallible. */
    if (mutable_cap) {
        rc = lif_capabilities_receive_dynamic(mutable_cap, bm, rx, n, g);
        if (rc) return rc;
        /* Owned result of this same call, never a caller-supplied decode. */
        memcpy(&received, &mutable_cap->value.last_dynamic, sizeof(received));
    } else {
        rc = cp_lif_bitmap_receive_decode(bm, rx, n, g, &received, sizeof(received));
        if (rc) return rc;
    }
    memset(&record, 0, sizeof(record)); memset(&ref, 0, sizeof(ref));
    record.incarnation = o->value.next_incarnation + 1;
    record.source_sequence = received.decoded.source_sequence;
    record.pool_offset = offset; record.rx_length = received.decoded.rx_length;
    record.frame_length = received.decoded.frame_length;
    record.ingress_token = ingress->token;
    record.metadata8 = ingress->metadata8; record.metadata10 = ingress->metadata10;
    record.flags = received.decoded.flags; record.opaque = received.decoded.opaque;
    record.extra_zero = received.decoded.extra_zero;
    record.command_count = received.decoded.command_count;
    record.last_top_index = (unsigned char)(record.command_count - 1u);
    record.last_dynamic_index = 0xff;
    for (i = 0; i < record.command_count; ++i) {
        const struct cp_lif_command_view *c = &received.decoded.commands[i];
        record.commands[i].command = c->command;
        record.commands[i].offset = c->offset;
        record.commands[i].length = c->length;
        record.commands[i].metadata = c->metadata;
        record.commands[i].field_count = c->field_count;
        if (c->field_count) last_nonempty = c;
    }
    if (last_nonempty) {
        record.field_table_known = 1; record.field_table_command = last_nonempty->command;
        record.field_count = last_nonempty->field_count;
        record.last_dynamic_index = (unsigned char)(last_nonempty->field_count - 1u);
        memcpy(record.fields, received.decoded.fields + last_nonempty->first_field,
               last_nonempty->field_count * sizeof(record.fields[0]));
    }
    /* Conservative virtual policy: invalidate intersecting SPANS, not just starts. */
    for (i = 0; i < LIF_CACHE_RECORDS; ++i) {
        struct lif_cache_record *old = &o->value.records[i];
        if (i == o->value.next_slot || (old->live && old->pool_offset < offset + LIF_CACHE_RESERVE_BYTES &&
            offset < old->pool_offset + old->rx_length)) old->live = 0;
    }
    memcpy(o->pool + offset, received.decoded.frame, n);
    record.live = record.admitted_owned_frame = 1;
    ref.known = ref.present = 1;
    ref.handle.slot = o->value.next_slot; ref.handle.incarnation = record.incarnation;
    memcpy(&o->value.records[o->value.next_slot], &record, sizeof(record));
    for (i = 0; i < record.command_count; ++i) {
        unsigned index = record.commands[i].command - 5u;
        o->value.global_last[index] = ref;
        if (o->value.current.known && ingress->token == o->value.current.token)
            o->value.current.command[index] = ref;
    }
    o->value.write_offset = offset; o->value.last_rx_size = n;
    o->value.next_incarnation = record.incarnation;
    o->value.next_slot = (unsigned char)((o->value.next_slot + 1u) % LIF_CACHE_RECORDS);
    o->value.sequence = g->sequence_before;
    memcpy(out, &ref.handle, sizeof(*out));
    return 0;
}
int lif_cache_receive(struct lif_cache_owner *o, const struct lif_capabilities_owner *cap_owner,
    const struct cp_lif_bitmap_guard *cg, struct cp_lif_bitmap_owner *bm,
    const unsigned char *rx, size_t n, const struct lif_cache_ingress *ingress,
    const struct cp_lif_bitmap_guard *g, struct lif_cache_handle *out, size_t capacity)
{
    int saved = errno;
    return finish(receive(o, cap_owner, NULL, cg, bm, rx, n, ingress, g, out, capacity), saved);
}
int lif_cache_receive_with_handshake(struct lif_cache_owner *o,
    struct lif_capabilities_owner *cap_owner, const struct cp_lif_bitmap_guard *cg,
    struct cp_lif_bitmap_owner *bm, const unsigned char *rx, size_t n,
    const struct lif_cache_ingress *ingress, const struct cp_lif_bitmap_guard *g,
    struct lif_cache_handle *out, size_t capacity)
{
    int saved = errno;
    return finish(receive(o, cap_owner, cap_owner, cg, bm, rx, n, ingress, g, out, capacity), saved);
}
int lif_cache_snapshot(const struct lif_cache_owner *o, const struct cp_lif_bitmap_guard *g,
    struct lif_cache_readback *out, size_t capacity)
{
    int saved = errno, rc = owner_guard(o, g, 1);
    if (!rc) rc = output_valid(o, g, out, capacity, sizeof(*out), _Alignof(struct lif_cache_readback));
    if (!rc) memcpy(out, &o->value, sizeof(*out));
    return finish(rc, saved);
}
static int resolve(const struct lif_cache_owner *o, struct lif_cache_handle h,
    const struct lif_cache_record **record)
{
    if (h.slot >= LIF_CACHE_RECORDS || !h.incarnation) return -ESTALE;
    *record = &o->value.records[h.slot];
    if (!(*record)->live || (*record)->incarnation != h.incarnation) return -ESTALE;
    return 0;
}
static int copy_result(const struct lif_cache_owner *o, struct lif_cache_handle h,
    const struct lif_cache_record *r, size_t offset, size_t size, struct lif_cache_result *out)
{
    struct lif_cache_result result;
    if (r->pool_offset > o->value.pool_capacity ||
        r->rx_length > o->value.pool_capacity - r->pool_offset ||
        offset > r->rx_length || size > (size_t)r->rx_length - offset ||
        size > sizeof(result.bytes)) return -EINVAL;
    memset(&result, 0, sizeof(result));
    result.handle = h; result.source_sequence = r->source_sequence;
    result.size = size; result.ingress_token = r->ingress_token;
    result.opaque = r->opaque; result.diagnostic_only = 1;
    memcpy(result.bytes, o->pool + r->pool_offset + offset, size);
    memcpy(out, &result, sizeof(result));
    return 0;
}
static int field(const struct lif_cache_owner *o, struct lif_cache_handle h,
    const struct lif_cache_record *r, unsigned id, struct lif_cache_result *out)
{
    size_t i;
    if (!r->field_table_known) return -ENODATA;
    for (i = 0; i < r->field_count; ++i)
        if (r->fields[i].id == id)
            return copy_result(o, h, r, r->fields[i].offset, r->fields[i].length, out);
    return -ENOENT;
}
int lif_cache_lookup_command(const struct lif_cache_owner *o, struct lif_cache_handle h,
    unsigned command, const struct cp_lif_bitmap_guard *g, struct lif_cache_result *out, size_t cap)
{
    const struct lif_cache_record *r;
    size_t i;
    int saved = errno, rc = owner_guard(o, g, 1);
    if (!rc) rc = output_valid(o, g, out, cap, sizeof(*out), _Alignof(struct lif_cache_result));
    if (!rc) rc = resolve(o, h, &r);
    if (!rc) {
        rc = -ENOENT;
        for (i = 0; i < r->command_count; ++i)
            if (r->commands[i].command == command) {
                rc = copy_result(o, h, r, r->commands[i].offset, r->commands[i].length, out);
                break;
            }
    }
    return finish(rc, saved);
}
int lif_cache_lookup_field(const struct lif_cache_owner *o, struct lif_cache_handle h,
    unsigned id, const struct cp_lif_bitmap_guard *g, struct lif_cache_result *out, size_t cap)
{
    const struct lif_cache_record *r;
    int saved = errno, rc = owner_guard(o, g, 1);
    if (!rc) rc = output_valid(o, g, out, cap, sizeof(*out), _Alignof(struct lif_cache_result));
    if (!rc) rc = resolve(o, h, &r);
    if (!rc) rc = field(o, h, r, id, out);
    return finish(rc, saved);
}
int lif_cache_lookup_current_field(const struct lif_cache_owner *o, unsigned command,
    unsigned id, const struct cp_lif_bitmap_guard *g, struct lif_cache_result *out, size_t cap)
{
    const struct lif_cache_record *r;
    const struct lif_cache_history_ref *ref;
    int saved = errno, rc = owner_guard(o, g, 1);
    if (!rc) rc = output_valid(o, g, out, cap, sizeof(*out), _Alignof(struct lif_cache_result));
    if (rc) return finish(rc, saved);
    if (command != 5 && command != 6) return finish(-ENOTSUP, saved);
    if (!o->value.current.known) return finish(-ENODATA, saved);
    ref = &o->value.current.command[command - 5u];
    if (!ref->known) return finish(-ENODATA, saved);
    if (!ref->present) return finish(-ENOENT, saved);
    rc = resolve(o, ref->handle, &r);
    if (!rc && r->opaque != o->value.current.token) rc = -ESTALE;
    if (!rc && (!r->field_table_known || r->field_table_command != command))
        rc = r->field_table_known ? -ENOENT : -ENODATA;
    if (!rc) rc = field(o, ref->handle, r, id, out);
    return finish(rc, saved);
}
