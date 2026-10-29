#include "native-paramsets.h"

#include <errno.h>
#include <string.h>

static uint16_t le16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | (uint16_t)((uint16_t)p[1] << 8));
}

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
        (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint64_t le64(const uint8_t *p)
{
    return (uint64_t)le32(p) | (uint64_t)le32(p + 4) << 32;
}

static uint32_t be32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
        (uint32_t)p[2] << 8 | (uint32_t)p[3];
}

static int wraps(const void *p, size_t n)
{
    return n > UINTPTR_MAX - (uintptr_t)p;
}

/* Only called after checking both complete numerical address ranges. */
static int overlaps(const void *a, size_t an, const void *b, size_t bn)
{
    return an && bn && (uintptr_t)a < (uintptr_t)b + bn &&
        (uintptr_t)b < (uintptr_t)a + an;
}

static void metadata(struct nparamsets_group *g, const uint8_t *p,
    uint8_t flags, unsigned bit)
{
    g->span = le16(p);
    g->count = p[2];
    g->source_id = p[3];
    g->changed = (uint8_t)((flags >> bit) & 1u);
}

static int mandatory(const struct nparamsets_group *g)
{
    /* shortcut: single NAL per group, extend only with a proved consumer. */
    if (g->count > 1) return -ENOTSUP;
    if (!g->count || !g->span) return -ENODATA;
    return 0;
}

static int nal_group(struct nparamsets_group *g, const uint8_t *es,
    uint32_t container_type, unsigned kind)
{
    const uint8_t *p;
    uint32_t n;
    if (g->span < 4) return -ENODATA;
    p = es + g->es_offset;
    n = be32(p);
    if (!n || n > (uint32_t)g->span - 4u) return -ENODATA;
    if (n != (uint32_t)g->span - 4u) return -EINVAL;
    p += 4;
    if (p[0] & 0x80u) return -EINVAL;
    if (container_type == NPARAMSETS_AVC1) {
        if ((p[0] & 0x1fu) != kind) return -EINVAL;
    } else {
        if (n < 2) return -ENODATA;
        if (((p[0] >> 1) & 0x3fu) != kind || !(p[1] & 7u))
            return -EINVAL;
    }
    g->nal = p;
    g->nal_size = n;
    return 0;
}

int nparamsets_parse(const uint8_t *info, size_t info_size,
    uint32_t container_type, uint64_t address_correction,
    uint64_t es_base, const uint8_t *es, size_t es_capacity,
    struct nparamsets *out, size_t out_capacity)
{
    struct nparamsets r;
    uint64_t offset;
    int rc;
    if (!info || !es || !out) return -EINVAL;
    if (wraps(info, info_size) || wraps(es, es_capacity) ||
        wraps(out, out_capacity)) return -EOVERFLOW;
    if ((uintptr_t)out % _Alignof(struct nparamsets)) return -EINVAL;
    if (out_capacity < sizeof(*out)) return -ENOSPC;
    if (overlaps(out, out_capacity, info, info_size) ||
        overlaps(out, out_capacity, es, es_capacity)) return -EINVAL;
    if (info_size < NPARAMSETS_INFO_BYTES) return -ENODATA;
    if (info_size != NPARAMSETS_INFO_BYTES) return -EINVAL;
    if (info[0] != 4 || (container_type != NPARAMSETS_AVC1 &&
        container_type != NPARAMSETS_HVC1)) return -ENOTSUP;
    if (!es_capacity) return -ENODATA;
    if (es_capacity > UINT64_MAX - es_base) return -EOVERFLOW;

    memset(&r, 0, sizeof(r));
    r.info_type = info[0];
    r.change_flags = info[1];
    r.container_type = container_type;
    r.declared_length = le32(info + 0x10);
    r.wire_address = le64(info + 8);
    r.address_correction = address_correction;
    r.es_base = es_base;
    r.es_capacity = es_capacity;
    metadata(&r.vps, info + 0x28, r.change_flags, 0);
    metadata(&r.sps, info + 0x2c, r.change_flags, 1);
    metadata(&r.pps, info + 0x30, r.change_flags, 2);
    if (container_type == NPARAMSETS_AVC1) {
        if (r.vps.span || r.vps.count) return -ENOTSUP;
    } else {
        rc = mandatory(&r.vps);
        if (rc) return rc;
    }
    rc = mandatory(&r.sps);
    if (rc) return rc;
    rc = mandatory(&r.pps);
    if (rc) return rc;
    r.group_bytes = (size_t)r.vps.span + r.sps.span + r.pps.span;
    if (r.wire_address > UINT64_MAX - address_correction) return -EOVERFLOW;
    r.corrected_address = r.wire_address + address_correction;
    if (r.group_bytes > UINT64_MAX - r.corrected_address) return -EOVERFLOW;
    if (r.corrected_address < es_base) return -ERANGE;
    offset = r.corrected_address - es_base;
    if (offset > es_capacity || r.group_bytes > es_capacity - (size_t)offset)
        return -ERANGE;
    r.vps.es_offset = (size_t)offset;
    r.sps.es_offset = r.vps.es_offset + r.vps.span;
    r.pps.es_offset = r.sps.es_offset + r.sps.span;
    if (container_type == NPARAMSETS_HVC1) {
        rc = nal_group(&r.vps, es, container_type, 32);
        if (rc) return rc;
    }
    rc = nal_group(&r.sps, es, container_type,
        container_type == NPARAMSETS_AVC1 ? 7u : 33u);
    if (rc) return rc;
    rc = nal_group(&r.pps, es, container_type,
        container_type == NPARAMSETS_AVC1 ? 8u : 34u);
    if (rc) return rc;
    memcpy(out, &r, sizeof(r));
    return 0;
}
