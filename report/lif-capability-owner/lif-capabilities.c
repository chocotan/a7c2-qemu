/* SPDX-License-Identifier: MIT */
#include "lif-capabilities.h"
#include <errno.h>
#include <string.h>
#include <unistd.h>

/* f8f997: two actual source rows, not synthesized support defaults. */
static const unsigned char masks[2][32] = {
    {0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xef,0xff,0xff,0x07},
    {0x41,0x08,0x18}
};
/* 404e68: needed to prove partial support while Z is unknown. */
static const unsigned char z_mask[32] = {
    0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0x00,0x0c
};
static int span(const void *p, size_t n)
{ return p != NULL && n <= UINTPTR_MAX - (uintptr_t)p; }
static int overlap(const void *a, size_t an, const void *b, size_t bn)
{
    return an && bn && (uintptr_t)a < (uintptr_t)b + bn &&
           (uintptr_t)b < (uintptr_t)a + an;
}
static uint16_t le16(const unsigned char *p)
{ return (uint16_t)((uint16_t)p[0] | (uint16_t)((uint16_t)p[1] << 8)); }
static uint32_t le32(const unsigned char *p)
{ return (uint32_t)le16(p) | ((uint32_t)le16(p + 2) << 16); }
static int finish(int rc, int saved_errno)
{ errno = saved_errno; return rc; }
static int guard_valid(const struct cp_lif_bitmap_guard *g)
{
    if (!span(g, sizeof(*g)) ||
        (uintptr_t)g % _Alignof(struct cp_lif_bitmap_guard)) return -EINVAL;
    if (!g->owner_pid || g->origin == CP_LIF_ORIGIN_NONE) return -ENODATA;
    if (g->owner_pid != (uint32_t)getpid() ||
        (g->origin != CP_LIF_ORIGIN_VIRTUAL_SOURCE &&
         g->origin != CP_LIF_ORIGIN_HOST_TEST)) return -EXDEV;
    if (g->quiescent > 1) return -EINVAL;
    if (!g->quiescent || g->sequence_before != g->sequence_after ||
        (g->sequence_before & UINT64_C(1))) return -EAGAIN;
    return 0;
}
static int owner_guard(const struct lif_capabilities_owner *o,
                       const struct cp_lif_bitmap_guard *g, int reading)
{
    int rc;
    if (!span(o, sizeof(*o)) ||
        (uintptr_t)o % _Alignof(struct lif_capabilities_owner) ||
        !span(g, sizeof(*g)) ||
        (uintptr_t)g % _Alignof(struct cp_lif_bitmap_guard) ||
        overlap(o, sizeof(*o), g, sizeof(*g))) return -EINVAL;
    rc = guard_valid(g);
    if (rc) return rc;
    if (!o->revision) return -ENODATA;
    if (o->revision != LIF_CAPABILITIES_REVISION) return -ENOTSUP;
    if (o->value.owner_pid != (uint32_t)getpid() ||
        o->value.owner_pid != g->owner_pid || o->value.origin != g->origin)
        return -EXDEV;
    if (reading ? g->sequence_before != o->value.sequence :
                  g->sequence_before <= o->value.sequence) return -ESTALE;
    return 0;
}
static int output_valid(const struct lif_capabilities_owner *o,
    const struct cp_lif_bitmap_guard *g, void *out, size_t cap,
    size_t need, size_t alignment)
{
    if (!span(out, cap) || (uintptr_t)out % alignment ||
        overlap(out, cap, o, sizeof(*o)) ||
        overlap(out, cap, g, sizeof(*g))) return -EINVAL;
    return cap < need ? -EMSGSIZE : 0;
}
static int init(struct lif_capabilities_owner *o,
    const struct cp_property_stage *stage, const struct cp_start_state_guard *g,
    uint32_t selector)
{
    struct lif_capabilities_owner next;
    struct cp_property_stage_readback context;
    enum cp_lif_origin origin;
    size_t i;
    int rc;
    if (!span(o, sizeof(*o)) ||
        (uintptr_t)o % _Alignof(struct lif_capabilities_owner) ||
        !span(stage, sizeof(*stage)) ||
        (uintptr_t)stage % _Alignof(struct cp_property_stage) ||
        !span(g, sizeof(*g)) ||
        (uintptr_t)g % _Alignof(struct cp_start_state_guard) ||
        overlap(o, sizeof(*o), stage, sizeof(*stage)) ||
        overlap(o, sizeof(*o), g, sizeof(*g)) ||
        overlap(stage, sizeof(*stage), g, sizeof(*g))) return -EINVAL;
    for (i = 0; i < sizeof(*o); ++i)
        if (((const unsigned char *)o)[i]) return -EALREADY;
    /* Call the actual existing stage owner; no caller-supplied context bytes. */
    rc = cp_property_stage_snapshot(stage, g, &context);
    if (rc) return rc;
    if (!context.profile_known || !context.mode_property_known) return -ENODATA;
    if (context.source != CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE ||
        context.repository != CP_PROPERTY_STAGE_REPOSITORY_CP_PRIMARY ||
        context.cp_base != CP_PROPERTY_STAGE_BASE ||
        context.stage_fnv1a64 != CP_PROPERTY_STAGE_FNV1A64) return -ENODATA;
    /* Explicit mapping: the enums belong to different source contracts. */
    if (context.source_origin == CP_START_STATE_ORIGIN_VIRTUAL_SOURCE)
        origin = CP_LIF_ORIGIN_VIRTUAL_SOURCE;
    else if (context.source_origin == CP_START_STATE_ORIGIN_HOST_TEST)
        origin = CP_LIF_ORIGIN_HOST_TEST;
    else return -EXDEV;
    memset(&next, 0, sizeof(next));
    next.revision = LIF_CAPABILITIES_REVISION;
    next.value.owner_pid = context.owner_pid;
    next.value.origin = origin;
    next.value.sequence = g->sequence_before;
    next.value.reset_sequence = g->sequence_before;
    next.value.selector = selector;
    memcpy(&next.value.stage, &context, sizeof(context));
    /* Native constructor contents are unknown. Poison is not a P initializer. */
    memset(next.value.property, 0xa5, sizeof(next.value.property));
    /* Explicit a9073e event, not implicit BSS inference. */
    memset(next.value.support_known, 1, sizeof(next.value.support_known));
    next.value.support[1] = 1;
    next.value.mask_row = (unsigned char)(selector == 3);
    next.value.request[0] = 1;
    memcpy(next.value.request + 1, masks[next.value.mask_row], 32);
    next.value.request_configured = 1;
    next.value.diagnostic_only = next.value.owned_data_transport = 1;
    memcpy(o, &next, sizeof(next));
    return 0;
}
static void refresh(struct lif_capabilities_readback *v, uint64_t sequence)
{
    unsigned c;
    for (c = 0; c < LIF_CAPABILITIES_SUPPORT_BYTES; ++c) {
        unsigned offset = ((c - 1u) & 0xffu) >> 3;
        unsigned bit = 1u << ((c - 1u) & 7u);
        unsigned normal = masks[v->mask_row][offset] & bit;
        unsigned alternate = z_mask[offset] & bit;
        unsigned capability = v->property[offset + 1u] & bit;
        unsigned known = v->property_known[offset + 1u];
        v->support[c] = v->support_known[c] = 0;
        if (c == 1) {
            v->support[c] = v->support_known[c] = 1;
        } else if (c >= 0x41 && c <= 0x49 && !v->stage.context[0x20]) {
            v->support_known[c] = 1;
        } else if ((known && !capability) ||
                   (!normal && (v->z_known || !alternate))) {
            v->support_known[c] = 1;
        } else if (known && (v->z_known || normal == alternate)) {
            v->support_known[c] = 1;
            v->support[c] = (unsigned char)(capability && normal);
        }
        /* a9096c only reads unknown 1b1a7b1. False capability/mask is
         * decisive; a positive gated result still needs that actual byte. */
        if (c >= 0x41 && c <= 0x49 && v->stage.context[0x20] && v->support[c])
            v->support[c] = v->support_known[c] = 0;
    }
    v->support_refresh_sequence = sequence;
}
static void copy_property(struct lif_capabilities_readback *v, size_t at,
                          const unsigned char *body, size_t n)
{
    memcpy(v->property + at, body, n);
    memset(v->property_known + at, 1, n);
}
static void request_state(struct lif_capabilities_readback *v, unsigned requested,
                          uint64_t sequence)
{
    v->last_state_request = requested;
    v->last_state_request_known = 1;
    v->state_request_sequence = sequence;
    /* a908ea returns void: a refused request does not invalidate a copy. */
    if (requested <= 1 || (v->state_known &&
        (requested == 2 ? v->state <= 1 : v->state == requested - 1))) {
        v->state = requested;
        v->state_known = 1;
        v->state_commit_sequence = sequence;
    }
}
static void handshake9(struct lif_capabilities_readback *v,
                       const unsigned char *body, uint64_t sequence)
{
    unsigned kind = body[1] & 3u;
    if ((v->property[0x22] & 3u) == 2 && (kind == 1 || kind == 2)) {
        v->k = kind == 1 ? 5u : 2u;
        v->k_known = 1;
        v->k_store_sequence = sequence;
    }
    request_state(v, 3, sequence);
}
static int receive(struct lif_capabilities_owner *o, const unsigned char *rx,
                   size_t n, const struct cp_lif_bitmap_guard *g)
{
    struct lif_capabilities_owner next;
    unsigned char frame[CP_LIF_FRAME_MAX_RX_BYTES];
    const unsigned char *body = frame + 5;
    uint16_t length;
    uint32_t checksum = 0;
    size_t i, body_length;
    unsigned type, command, z = 0;
    int rc = owner_guard(o, g, 0);
    if (rc) return rc;
    if (!span(rx, n) || overlap(o, sizeof(*o), rx, n) ||
        overlap(g, sizeof(*g), rx, n)) return -EINVAL;
    if (n < 9 || n > sizeof(frame)) return -EMSGSIZE;
    memcpy(frame, rx, n);
    length = le16(frame + 1);
    if (length < 9 || length > CP_LIF_FRAME_MAX_BYTES ||
        (n != length && n != (size_t)length + 1)) return -EMSGSIZE;
    if (frame[0] != 0xf0 || frame[length - 1] != 0x55 ||
        (n != length && frame[length] != 0)) return -EBADMSG;
    for (i = 1; i < (size_t)length - 3; ++i) checksum += frame[i];
    if ((uint16_t)checksum != le16(frame + length - 3)) return -EBADMSG;
    type = frame[3] & 7u;
    if (type < 1 || type > 3) return -EBADMSG;
    if (type == 1) return -ENODATA;
    command = body[0];
    switch (command) {
    case 1: body_length = 33; break;
    case 7: body_length = 35; break;
    case 8: body_length = 202; break;
    case 9: body_length = LIF_CAPABILITIES_HANDSHAKE_BODY_BYTES; break;
    case 0x3d: body_length = 64; break;
    default: return -ENOTSUP;
    }
    /* The body includes its command byte: reject extra/duplicate commands. */
    if ((size_t)length != body_length + 8) return -EMSGSIZE;
    if (command == 7) {
        unsigned value = le16(body + 0x0a);
        unsigned context = o->value.stage.context[0x17];
        z = context == 1 || (context == 0 &&
            (value & 0xfffu) != 0xfffu && (value >> 14) >= 3);
        if (z) return -ENOTSUP;
    } else if (command != 1 && !o->value.z_known) return -ENODATA;
    if (command != 1 && command != 7 && o->value.z) return -ENOTSUP;
    if (command == 9 && (body[8] || body[9] ||
        !o->value.property_known[0x22] || !o->value.control_enabled_known))
        return -ENODATA;
    if (command == 0x3d && (le32(body + 0x25) & UINT32_C(0x20000000)))
        return -ENODATA;
    memcpy(&next, o, sizeof(next));
    if (command == 1) {
        copy_property(&next.value, 0, body, body_length);
        refresh(&next.value, g->sequence_before);
    } else if (command == 7) {
        /* a98fe8 precedes both copies; source does NOT refresh support here. */
        next.value.z = (unsigned char)z;
        next.value.z_known = 1;
        copy_property(&next.value, 0x21, body, body_length);
        copy_property(&next.value, 0x116, body, body_length);
    } else if (command == 8) {
        copy_property(&next.value, 0x44, body, body_length);
        /* Both a9556a branches call a90720 after the 40ad58 copy. */
        refresh(&next.value, g->sequence_before);
        request_state(&next.value, 2, g->sequence_before);
    } else if (command == 9) {
        if (next.value.control_enabled == 1) {
            handshake9(&next.value, body, g->sequence_before);
        } else {
            next.value.pending9 = next.value.pending9_known = 1;
            memcpy(next.value.pending9_body, body, body_length);
            next.value.pending9_body_known = 1;
            next.value.pending9_sequence = g->sequence_before;
        }
    } else {
        /* D bit29==0 makes either unproven 1b1ac73 flag path identical. */
        copy_property(&next.value, 0x139, body, body_length);
    }
    next.value.sequence = g->sequence_before;
    memset(&next.value.receipt, 0, sizeof(next.value.receipt));
    next.value.receipt.sequence = g->sequence_before;
    next.value.receipt.frame_length = length;
    next.value.receipt.rx_length = (uint16_t)n;
    next.value.receipt.body_length = (uint16_t)body_length;
    next.value.receipt.present = 1;
    next.value.receipt.command = (unsigned char)command;
    next.value.receipt.flags = frame[3];
    next.value.receipt.opaque = frame[4];
    next.value.receipt.extra_zero = (unsigned char)(n != length);
    memcpy(next.value.receipt.frame, frame, n);
    memcpy(o, &next, sizeof(next));
    return 0;
}
int lif_capabilities_init(struct lif_capabilities_owner *o,
    const struct cp_property_stage *stage, const struct cp_start_state_guard *g,
    uint32_t selector)
{
    int saved_errno = errno;
    return finish(init(o, stage, g, selector), saved_errno);
}
int lif_capabilities_receive(struct lif_capabilities_owner *o,
    const unsigned char *rx, size_t n, const struct cp_lif_bitmap_guard *g)
{
    int saved_errno = errno;
    return finish(receive(o, rx, n, g), saved_errno);
}
int lif_capabilities_consume_initial_kind_store(struct lif_capabilities_owner *o,
    const struct cp_lif_bitmap_guard *g)
{
    int saved_errno = errno;
    int rc = owner_guard(o, g, 0);
    unsigned type;
    if (rc) return finish(rc, saved_errno);
    if (!o->value.property_known[0x22]) return finish(-ENODATA, saved_errno);
    type = o->value.property[0x22] & 3u;
    if (type != 1 && type != 2) return finish(-ENOTSUP, saved_errno);
    o->value.k = type == 1 ? 4u : 1u;
    o->value.k_known = 1;
    o->value.k_store_sequence = o->value.sequence = g->sequence_before;
    return finish(0, saved_errno);
}
int lif_capabilities_consume_handshake_reset_store(struct lif_capabilities_owner *o,
    const struct cp_lif_bitmap_guard *g)
{
    int saved_errno = errno;
    int rc = owner_guard(o, g, 0);
    if (rc) return finish(rc, saved_errno);
    o->value.state = o->value.k = 0;
    o->value.state_known = o->value.k_known = 1;
    o->value.handshake_reset_sequence = o->value.state_commit_sequence = g->sequence_before;
    o->value.k_store_sequence = o->value.sequence = g->sequence_before;
    return finish(0, saved_errno);
}
int lif_capabilities_consume_control_flags_reset(struct lif_capabilities_owner *o,
    const struct cp_lif_bitmap_guard *g)
{
    int saved_errno = errno;
    int rc = owner_guard(o, g, 0);
    if (rc) return finish(rc, saved_errno);
    o->value.control_enabled = o->value.pending8 = o->value.pending9 = 0;
    o->value.flags_reset_known = o->value.control_enabled_known = 1;
    o->value.pending8_known = o->value.pending9_known = 1;
    o->value.control_flags_reset_sequence = o->value.sequence = g->sequence_before;
    return finish(0, saved_errno);
}
int lif_capabilities_consume_dispatch_event9_prefix(struct lif_capabilities_owner *o,
    const struct cp_lif_bitmap_guard *g)
{
    int saved_errno = errno;
    int rc = owner_guard(o, g, 0);
    if (rc) return finish(rc, saved_errno);
    if (!o->value.pending8_known || !o->value.pending9_known)
        return finish(-ENODATA, saved_errno);
    /* shortcut: no deferred8 producer; add its actual body consumer first. */
    if (o->value.pending8) return finish(-ENOTSUP, saved_errno);
    if (o->value.pending9 && (!o->value.pending9_body_known ||
        !o->value.property_known[0x22])) return finish(-ENODATA, saved_errno);
    o->value.control_enabled = o->value.control_enabled_known = 1;
    if (o->value.pending9)
        handshake9(&o->value, o->value.pending9_body, g->sequence_before);
    /* The source prefix does not clear pending flags after replay. */
    o->value.event9_sequence = o->value.sequence = g->sequence_before;
    return finish(0, saved_errno);
}
int lif_capabilities_receive_dynamic(struct lif_capabilities_owner *o,
    struct cp_lif_bitmap_owner *bitmap, const unsigned char *rx, size_t n,
    const struct cp_lif_bitmap_guard *g)
{
    struct cp_lif_bitmap_received received;
    unsigned i, present5 = 0, present6 = 0;
    int saved_errno = errno;
    int rc = owner_guard(o, g, 0);
    if (rc) return finish(rc, saved_errno);
    if (!span(bitmap, sizeof(*bitmap)) ||
        (uintptr_t)bitmap % _Alignof(struct cp_lif_bitmap_owner) || !span(rx, n) ||
        overlap(o, sizeof(*o), bitmap, sizeof(*bitmap)) ||
        overlap(bitmap, sizeof(*bitmap), g, sizeof(*g)) ||
        overlap(o, sizeof(*o), rx, n) || overlap(bitmap, sizeof(*bitmap), rx, n) ||
        overlap(g, sizeof(*g), rx, n)) return finish(-EINVAL, saved_errno);
    /* Call the live bitmap owner once; after success only infallible commits. */
    rc = cp_lif_bitmap_receive_decode(bitmap, rx, n, g, &received, sizeof(received));
    if (rc) return finish(rc, saved_errno);
    for (i = 0; i < received.decoded.command_count; ++i) {
        present5 |= received.decoded.commands[i].command == 5;
        present6 |= received.decoded.commands[i].command == 6;
    }
    if (present5) {
        o->value.received5_sequence = g->sequence_before;
        if (o->value.state_known && o->value.state == 3) {
            o->value.state = 4;
            o->value.state_commit_sequence = g->sequence_before;
        }
    }
    if (present6) {
        o->value.received6_sequence = g->sequence_before;
        if (o->value.state_known && o->value.state == 4) {
            o->value.state = 5;
            o->value.state_commit_sequence = g->sequence_before;
        }
    }
    memcpy(&o->value.last_dynamic, &received, sizeof(received));
    o->value.sequence = g->sequence_before;
    return finish(0, saved_errno);
}
int lif_capabilities_snapshot(const struct lif_capabilities_owner *o,
    const struct cp_lif_bitmap_guard *g, struct lif_capabilities_readback *out,
    size_t cap)
{
    int saved_errno = errno;
    int rc = owner_guard(o, g, 1);
    if (!rc) rc = output_valid(o, g, out, cap, sizeof(*out),
                               _Alignof(struct lif_capabilities_readback));
    if (!rc) memcpy(out, &o->value, sizeof(*out));
    return finish(rc, saved_errno);
}
int lif_capabilities_export_bitmap(const struct lif_capabilities_owner *o,
    const struct cp_lif_bitmap_guard *g, struct cp_lif_bitmap_inputs *out,
    size_t cap)
{
    struct cp_lif_bitmap_inputs result;
    int saved_errno = errno;
    int rc = owner_guard(o, g, 1);
    if (!rc) rc = output_valid(o, g, out, cap, sizeof(*out),
                               _Alignof(struct cp_lif_bitmap_inputs));
    if (rc) return finish(rc, saved_errno);
    memset(&result, 0, sizeof(result));
    memcpy(result.property, o->value.property, sizeof(result.property));
    memcpy(result.property_known, o->value.property_known, sizeof(result.property_known));
    /* Existing mode consumer writes the SAME 1107178 read by bitmap build.
     * This E-mode binding is separate from the data owner's M predicate. */
    result.mode = o->value.stage.mode;
    result.known = CP_LIF_BITMAP_MODE_KNOWN;
    if (o->value.k_known) {
        result.known |= CP_LIF_BITMAP_K_KNOWN;
        result.k = o->value.k;
    }
    if (o->value.z_known) {
        result.known |= CP_LIF_BITMAP_Z_KNOWN;
        result.z = o->value.z;
    }
    if (o->value.support_known[0x43]) {
        result.known |= CP_LIF_BITMAP_S43_KNOWN;
        result.s43 = o->value.support[0x43];
    }
    if (o->value.support_known[0x5a]) {
        result.known |= CP_LIF_BITMAP_S5A_KNOWN;
        result.s5a = o->value.support[0x5a];
    }
    memcpy(out, &result, sizeof(result));
    return finish(0, saved_errno);
}
