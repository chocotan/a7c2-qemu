/* SPDX-License-Identifier: MIT */
#include "cp-property-stage.h"
#include <string.h>
#include <unistd.h>

#define STAGE_MAGIC UINT32_C(0x43504953)
static uint16_t le16(const unsigned char *p)
{ return (uint16_t)(p[0] | (uint16_t)p[1] << 8); }
static uint32_t le32(const unsigned char *p)
{ return (uint32_t)le16(p) | (uint32_t)le16(p + 2) << 16; }
static int range(const void *p, size_t n)
{ return p && n <= UINTPTR_MAX - (uintptr_t)p; }
static int overlap(const void *a, size_t an, const void *b, size_t bn)
{ return an && bn && (uintptr_t)a < (uintptr_t)b + bn &&
                    (uintptr_t)b < (uintptr_t)a + an; }
static int valid(const struct cp_property_stage *p,
                 const struct cp_start_state_guard *g, int reading)
{
    if (!range(p, sizeof(*p)) ||
        (uintptr_t)p % _Alignof(struct cp_property_stage) ||
        !range(g, sizeof(*g)) ||
        (uintptr_t)g % _Alignof(struct cp_start_state_guard) ||
        overlap(p, sizeof(*p), g, sizeof(*g))) return -EINVAL;
    if (p->magic != STAGE_MAGIC) return -EINVAL;
    if (p->value.owner_pid != (uint32_t)getpid() ||
        g->owner_pid != p->value.owner_pid) return -EXDEV;
    if (g->source_origin != CP_START_STATE_ORIGIN_VIRTUAL_SOURCE &&
        g->source_origin != CP_START_STATE_ORIGIN_HOST_TEST) return -EINVAL;
    if (p->value.source_origin != CP_START_STATE_ORIGIN_NONE &&
        p->value.source_origin != g->source_origin) return -EXDEV;
    if (g->quiescent != 1 || g->sequence_before != g->sequence_after ||
        (g->sequence_before & 1u)) return -EAGAIN;
    if (g->sequence_before < p->value.source_sequence ||
        (reading && g->sequence_before != p->value.source_sequence)) return -ESTALE;
    return 0;
}
/* Same be98c6/be995c/be9990 decoding as the provider's private parser.
 * shortcut: only these three pinned properties, extract a shared parser if that
 * provider exposes one; never relabel CP_INITIAL_STAGE as SECONDARY_VIRTUAL. */
static int lookup(const unsigned char *b, size_t n, uint32_t id,
                  uint16_t attr, size_t expected, unsigned char *out)
{
    uint32_t sections = le32(b + 0x10), properties = le32(b + 0x14);
    uint32_t data = le32(b + 0x18), encoded, first;
    size_t table = 0x100 + (size_t)sections * 6, entry, offset, bytes, capacity;
    uint16_t count;
    if ((id >> 16) >= sections) return -ENODATA;
    entry = 0x100 + (size_t)(id >> 16) * 6;
    count = le16(b + entry); first = le32(b + entry + 2);
    if (first > properties || count > properties - first) return -EINVAL;
    if ((id & 0xffffu) >= count) return -ENODATA;
    entry = table + ((size_t)first + (id & 0xffffu)) * 6;
    encoded = le32(b + entry + 2);
    if (encoded == UINT32_MAX) return -ENODATA;
    if (le16(b + entry) != attr) return -ENOTSUP;
    bytes = capacity = encoded >> 24; offset = encoded & UINT32_C(0xffffff);
    if (offset < data || offset > n) return -EINVAL;
    if (bytes == 0xff || bytes == 0) {
        size_t header = bytes ? 2u : 4u;
        if (header > n - offset) return -EINVAL;
        capacity = bytes ? le16(b + offset) : le16(b + offset + 2);
        bytes = le16(b + offset); offset += header;
    }
    if (bytes > capacity || capacity > n - offset) return -EINVAL;
    if (bytes != expected) return -EMSGSIZE;
    memcpy(out, b + offset, bytes);
    return 0;
}
static int decode(const unsigned char *b, size_t n,
                  struct cp_property_stage_readback *out)
{
    uint32_t sections, properties, data, sum = 0;
    uint64_t fnv = UINT64_C(14695981039346656037);
    size_t table;
    int rc;
    if (n != CP_PROPERTY_STAGE_BYTES) return -EMSGSIZE;
    if (b[9] != 0) return -EILSEQ;
    if (memcmp(b + 0xc, "BK4\0", 4)) return -EPROTO;
    sections = le32(b + 0x10); properties = le32(b + 0x14);
    data = le32(b + 0x18);
    if (data > n || le32(b + 0x1c) != n - data ||
        sections > (n - 0x100) / 6) return -EINVAL;
    table = 0x100 + (size_t)sections * 6;
    if (data < table || properties > (data - table) / 6) return -EINVAL;
    for (size_t i = 0; i < n; ++i) {
        if (i < 0x20 || i >= 0x24) sum += b[i];
        fnv = (fnv ^ b[i]) * UINT64_C(1099511628211);
    }
    if (sum != le32(b + 0x20)) return -EILSEQ;
    rc = lookup(b, n, CP_PROPERTY_STAGE_MODE_ID, 0, 1, &out->mode_property);
    if (rc) return rc;
    rc = lookup(b, n, CP_START_STATE_PROPERTY_ID, 8, sizeof(out->context), out->context);
    if (rc) return rc;
    rc = lookup(b, n, CP_PROPERTY_STAGE_ALH_ID, 8, sizeof(out->ALH_context), out->ALH_context);
    if (rc) return rc;
    if (fnv != CP_PROPERTY_STAGE_FNV1A64) return -EILSEQ;
    if (out->mode_property == 1 || out->mode_property == 2)
        out->mode = out->mode_property;
    out->stage_fnv1a64 = fnv;
    out->mode_property_known = out->profile_known = out->alh_property_known = 1;
    return 0;
}
int cp_property_stage_init(struct cp_property_stage *p)
{
    struct cp_property_stage next;
    if (!range(p, sizeof(*p)) ||
        (uintptr_t)p % _Alignof(struct cp_property_stage)) return -EINVAL;
    memset(&next, 0, sizeof(next));
    next.magic = STAGE_MAGIC;
    next.value.owner_pid = (uint32_t)getpid();
    next.value.mode = 3; /* eb5650: source-file initializer, not BSS inference. */
    memcpy(p, &next, sizeof(next));
    return 0;
}
int cp_property_stage_consume(struct cp_property_stage *p,
    const struct cp_start_state_guard *g, enum cp_property_stage_source source,
    const unsigned char *b, size_t n)
{
    struct cp_property_stage next;
    int rc = valid(p, g, 0);
    if (rc) return rc;
    if (source != CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE) return -ENOTSUP;
    if (!range(b, n) || overlap(p, sizeof(*p), b, n) ||
        overlap(g, sizeof(*g), b, n)) return -EINVAL;
    next = *p;
    rc = decode(b, n, &next.value);
    if (rc) return rc;
    if (p->value.profile_known) return -EALREADY;
    next.value.source = source;
    next.value.repository = CP_PROPERTY_STAGE_REPOSITORY_CP_PRIMARY;
    next.value.cp_base = CP_PROPERTY_STAGE_BASE;
    next.value.source_sequence = g->sequence_before;
    next.value.source_origin = g->source_origin;
    memcpy(p, &next, sizeof(next));
    return 0;
}
int cp_property_stage_snapshot(const struct cp_property_stage *p,
    const struct cp_start_state_guard *g, struct cp_property_stage_readback *out)
{
    int rc = valid(p, g, 1);
    if (rc) return rc;
    if (!range(out, sizeof(*out)) ||
        (uintptr_t)out % _Alignof(struct cp_property_stage_readback) ||
        overlap(p, sizeof(*p), out, sizeof(*out)) ||
        overlap(g, sizeof(*g), out, sizeof(*out))) return -EINVAL;
    memcpy(out, &p->value, sizeof(*out));
    return 0;
}
int cp_property_stage_deliver_profile(const struct cp_property_stage *p,
    const struct cp_start_state_guard *g, struct cp_start_state_provider *provider)
{
    unsigned char known[CP_START_STATE_PROPERTY_CONTEXT_BYTES];
    struct cp_start_state_span payload;
    int rc = valid(p, g, 1);
    if (rc) return rc;
    if (!range(provider, sizeof(*provider)) ||
        (uintptr_t)provider % _Alignof(struct cp_start_state_provider) ||
        overlap(p, sizeof(*p), provider, sizeof(*provider)) ||
        overlap(g, sizeof(*g), provider, sizeof(*provider))) return -EINVAL;
    if (!p->value.profile_known) return -ENODATA;
    memset(known, 1, sizeof(known));
    payload = (struct cp_start_state_span){p->value.context, known,
        sizeof(p->value.context), sizeof(known)};
    return cp_start_state_provider_deliver_property(provider, g,
        CP_START_STATE_PROPERTY_ID, &payload);
}
