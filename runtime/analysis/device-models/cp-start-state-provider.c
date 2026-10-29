/* SPDX-License-Identifier: MIT */
#include "cp-start-state-provider.h"
#include <string.h>
#include <unistd.h>

#define PROVIDER_MAGIC UINT32_C(0x43535031)
static uint16_t le16(const unsigned char *p)
{ return (uint16_t)(p[0] | (uint16_t)p[1] << 8); }
static uint32_t le32(const unsigned char *p)
{ return (uint32_t)le16(p) | (uint32_t)le16(p + 2) << 16; }
static int range(const void *p, size_t n)
{ return p && (uintptr_t)p <= UINTPTR_MAX - n; }
static int overlap(const void *a, size_t an, const void *b, size_t bn)
{ return an && bn && (uintptr_t)a < (uintptr_t)b + bn &&
                    (uintptr_t)b < (uintptr_t)a + an; }
static int valid(const struct cp_start_state_provider *p,
                 const struct cp_start_state_guard *g)
{
    if (!range(p, sizeof(*p)) ||
        (uintptr_t)p % _Alignof(struct cp_start_state_provider) ||
        !range(g, sizeof(*g)) ||
        (uintptr_t)g % _Alignof(struct cp_start_state_guard) ||
        overlap(p, sizeof(*p), g, sizeof(*g))) return -EINVAL;
    if (p->magic != PROVIDER_MAGIC) return -EINVAL;
    if (p->data.owner_pid != (uint32_t)getpid()) return -EXDEV;
    return 0;
}
/* 55df9c initializes the tables; be98c6 splits the SAME full property ID.
 * be995c/be9990 decode short/oversize/variable lengths and payload offset. */
static int property(const unsigned char *b, size_t n, unsigned char *context)
{
    uint32_t sections, properties, data, data_size, sum = 0, encoded;
    size_t table, entry, offset, bytes, capacity;
    uint16_t count;
    uint32_t first;
    if (n < 0x100 || n > UINT32_MAX) return -EMSGSIZE;
    if (memcmp(b + 12, "BK4\0", 4)) return -EPROTO;
    sections = le32(b + 16); properties = le32(b + 20);
    data = le32(b + 24); data_size = le32(b + 28);
    if (data > n || data_size != n - data ||
        sections > (n - 0x100) / 6) return -EINVAL;
    table = 0x100 + (size_t)sections * 6;
    if (data < table || properties > (data - table) / 6) return -EINVAL;
    for (size_t i = 0; i < n; ++i)
        if (i < 0x20 || i >= 0x24) sum += b[i];
    if (sum != le32(b + 0x20)) return -EILSEQ;
    if (sections <= (CP_START_STATE_PROPERTY_ID >> 16)) return -ENOENT;
    entry = 0x100 + (size_t)(CP_START_STATE_PROPERTY_ID >> 16) * 6;
    count = le16(b + entry); first = le32(b + entry + 2);
    if (first > properties || count > properties - first) return -EINVAL;
    if ((CP_START_STATE_PROPERTY_ID & 0xffffu) >= count) return -ENOENT;
    entry = table + ((size_t)first + (CP_START_STATE_PROPERTY_ID & 0xffffu)) * 6;
    encoded = le32(b + entry + 2);
    if (encoded == UINT32_MAX) return -ENOENT;
    bytes = capacity = encoded >> 24; offset = encoded & UINT32_C(0xffffff);
    if (offset < data || offset > n) return -EINVAL;
    if (bytes == 0xff || bytes == 0) {
        size_t header = bytes ? 2u : 4u;
        if (header > n - offset) return -EINVAL;
        capacity = bytes ? le16(b + offset) : le16(b + offset + 2);
        bytes = le16(b + offset); offset += header;
    }
    if (bytes > capacity || capacity > n - offset) return -EINVAL;
    if (bytes != CP_START_STATE_PROPERTY_CONTEXT_BYTES) return -ENOTSUP;
    memcpy(context, b + offset, bytes);
    return (int)bytes;
}
int cp_start_state_provider_init(struct cp_start_state_provider *p)
{
    struct cp_start_state_provider next;
    int rc;
    if (!range(p, sizeof(*p)) ||
        (uintptr_t)p % _Alignof(struct cp_start_state_provider)) return -EINVAL;
    memset(&next, 0, sizeof(next));
    rc = cp_start_state_data_init(&next.data);
    if (rc) return rc;
    next.magic = PROVIDER_MAGIC;
    memcpy(p, &next, sizeof(next));
    return 0;
}
int cp_start_state_provider_bootstrap_property(struct cp_start_state_provider *p,
    const struct cp_start_state_guard *g, enum cp_start_state_repository repository,
    const unsigned char *bank, size_t n)
{
    struct cp_start_state_provider next;
    unsigned char known[CP_START_STATE_PROPERTY_CONTEXT_BYTES];
    struct cp_start_state_span payload;
    int rc = valid(p, g);
    if (rc) return rc;
    if (!range(bank, n) || overlap(p, sizeof(*p), bank, n)) return -EINVAL;
    if (repository != CP_START_STATE_REPOSITORY_PRIMARY &&
        repository != CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL) return -ENOTSUP;
    if (p->property_bootstrapped || p->property_delivered) return -EALREADY;
    next = *p;
    rc = property(bank, n, next.context);
    if (rc == -ENOENT) return -ENODATA;
    if (rc < 0) return rc;
    next.prefetch_result = rc;
    next.repository = repository;
    memset(known, 1, sizeof(known));
    payload = (struct cp_start_state_span){next.context, known,
        sizeof(next.context), sizeof(known)};
    rc = cp_start_state_data_consume_property(&next.data, g,
        CP_START_STATE_PROPERTY_ID, &payload);
    if (rc) return rc;
    next.property_bootstrapped = 1;
    memcpy(p, &next, sizeof(next));
    return 0;
}
int cp_start_state_provider_deliver_property(struct cp_start_state_provider *p,
    const struct cp_start_state_guard *g, uint32_t id,
    const struct cp_start_state_span *payload)
{
    struct cp_start_state_provider next;
    int rc = valid(p, g), missing = 0;
    if (rc) return rc;
    if (!range(payload, sizeof(*payload)) ||
        (uintptr_t)payload % _Alignof(struct cp_start_state_span) ||
        overlap(p, sizeof(*p), payload, sizeof(*payload))) return -EINVAL;
    if (id != CP_START_STATE_PROPERTY_ID) return -ENOTSUP;
    if (payload->size != CP_START_STATE_PROPERTY_CONTEXT_BYTES ||
        payload->known_size < payload->size) return -EMSGSIZE;
    if (!range(payload->bytes, payload->size) ||
        !range(payload->known, payload->known_size) ||
        overlap(p, sizeof(*p), payload->bytes, payload->size) ||
        overlap(p, sizeof(*p), payload->known, payload->known_size)) return -EINVAL;
    for (size_t i = 0; i < payload->size; ++i) {
        if (payload->known[i] > 1) return -EINVAL;
        if (!payload->known[i]) missing = 1;
    }
    if (missing) return -ENODATA;
    next = *p;
    rc = cp_start_state_data_consume_property(&next.data, g, id, payload);
    if (rc) return rc;
    memcpy(next.context, payload->bytes, sizeof(next.context));
    next.property_delivered = 1;
    memcpy(p, &next, sizeof(next));
    return 0;
}
int cp_start_state_provider_snapshot(const struct cp_start_state_provider *p,
    const struct cp_start_state_guard *g, struct cp_start_state_provider_readback *out)
{
    struct cp_start_state_provider_readback next;
    int rc = valid(p, g);
    if (rc) return rc;
    if (!range(out, sizeof(*out)) ||
        (uintptr_t)out % _Alignof(struct cp_start_state_provider_readback) ||
        overlap(p, sizeof(*p), out, sizeof(*out)) ||
        overlap(g, sizeof(*g), out, sizeof(*out))) return -EINVAL;
    memset(&next, 0, sizeof(next));
    rc = cp_start_state_data_snapshot(&p->data, g, &next.data);
    if (rc) return rc;
    next.prefetch_result = p->prefetch_result;
    next.repository = p->repository;
    memcpy(next.context, p->context, sizeof(next.context));
    next.property_bootstrapped = p->property_bootstrapped;
    next.property_delivered = p->property_delivered;
    memcpy(out, &next, sizeof(next));
    return 0;
}
