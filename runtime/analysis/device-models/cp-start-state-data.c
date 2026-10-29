/* SPDX-License-Identifier: MIT */
#include "cp-start-state-data.h"
#include <string.h>
#include <unistd.h>

#define OWNER_MAGIC UINT32_C(0x43503353)
#define K_PROFILE 1u
#define K_MODE 2u
#define K_CACHE 4u
#define K_KIND 8u
#define K_Q 16u

static int span_valid(const void *p, size_t n)
{
    return p != NULL && n != 0 && n <= UINTPTR_MAX - (uintptr_t)p;
}

static int overlaps(const void *a, size_t an, const void *b, size_t bn)
{
    return (uintptr_t)a < (uintptr_t)b + bn &&
           (uintptr_t)b < (uintptr_t)a + an;
}

static int owner_valid(const struct cp_start_state_data *d)
{
    if (!span_valid(d, sizeof(*d)) ||
        (uintptr_t)d % _Alignof(struct cp_start_state_data) != 0)
        return -EINVAL;
    if (d->magic != OWNER_MAGIC || (d->known_mask & ~15u) != 0 ||
        (d->predicate_known_mask & ~31u) != 0)
        return -EINVAL;
    if (d->owner_pid != (uint32_t)getpid())
        return -EXDEV;
    return 0;
}

static int guard_valid(const struct cp_start_state_data *d,
                       const struct cp_start_state_guard *g, int read_only)
{
    int rc = owner_valid(d);
    if (rc != 0)
        return rc;
    if (!span_valid(g, sizeof(*g)) ||
        (uintptr_t)g % _Alignof(struct cp_start_state_guard) != 0 ||
        overlaps(d, sizeof(*d), g, sizeof(*g)))
        return -EINVAL;
    if (g->owner_pid != d->owner_pid)
        return -EXDEV;
    if (g->source_origin != CP_START_STATE_ORIGIN_VIRTUAL_SOURCE &&
        g->source_origin != CP_START_STATE_ORIGIN_HOST_TEST)
        return -EINVAL;
    if (d->source_origin != CP_START_STATE_ORIGIN_NONE &&
        g->source_origin != d->source_origin)
        return -EXDEV;
    if (g->quiescent != 1 || g->sequence_before != g->sequence_after ||
        (g->sequence_before & 1u) != 0)
        return -EAGAIN;
    if (g->sequence_before < d->source_sequence ||
        (read_only && g->sequence_before != d->source_sequence))
        return -ESTALE;
    if (!read_only && d->revision == UINT64_MAX)
        return -EOVERFLOW;
    return 0;
}

static int input_valid(const struct cp_start_state_data *d,
                       const struct cp_start_state_span *s)
{
    size_t i;
    if (!span_valid(s, sizeof(*s)) ||
        (uintptr_t)s % _Alignof(struct cp_start_state_span) != 0 ||
        overlaps(d, sizeof(*d), s, sizeof(*s)))
        return -EINVAL;
    if (s->size == 0)
        return s->bytes == NULL && s->known == NULL && s->known_size == 0 ? 0 : -EINVAL;
    if (!span_valid(s->bytes, s->size) || !span_valid(s->known, s->known_size) ||
        s->known_size < s->size ||
        overlaps(d, sizeof(*d), s->bytes, s->size) ||
        overlaps(d, sizeof(*d), s->known, s->known_size))
        return -EINVAL;
    for (i = 0; i < s->size; ++i)
        if (s->known[i] > 1)
            return -EINVAL;
    return 0;
}

static int require_known(const struct cp_start_state_span *s, size_t off, size_t n)
{
    size_t i;
    if (off > s->size || n > s->size - off)
        return -EMSGSIZE;
    for (i = off; i < off + n; ++i)
        if (s->known[i] == 0)
            return -ENODATA;
    return 0;
}

static uint32_t le32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void put32(unsigned char *p, uint32_t value)
{
    unsigned int i;
    for (i = 0; i < 4; ++i)
        p[i] = (unsigned char)(value >> (8u * i));
}

static void commit(struct cp_start_state_data *d, struct cp_start_state_data *next,
                   const struct cp_start_state_guard *g)
{
    next->source_sequence = g->sequence_before;
    next->source_origin = g->source_origin;
    next->revision++;
    *d = *next;
}

/* An unknown old state/flags can select clear or retain, not a guessed zero. */
static void maybe_clear(struct cp_start_state_data *d, unsigned char *known)
{
    unsigned int i;
    for (i = 0; i < 2; ++i)
        if (d->data[i] != 0 || (*known & (1u << i)) == 0)
            *known &= (unsigned char)~(1u << i);
}

static void clear_pair(struct cp_start_state_data *d, unsigned char *known)
{
    d->data[0] = 0;
    d->data[1] = 0;
    *known |= 3u;
}

static void tuple_update(struct cp_start_state_data *d, unsigned char *known,
                         unsigned char state, unsigned char subcode, unsigned char kind)
{
    if (!d->previous_tuple_known) {
        if ((state | 2u) != 3u)
            maybe_clear(d, known);
    } else if ((d->previous_state != state || d->previous_subcode != subcode ||
                d->previous_kind != kind) && (state | 2u) != 3u &&
               (d->previous_state | 2u) == 3u) {
        clear_pair(d, known);
    }
    d->previous_state = state;
    d->previous_subcode = subcode;
    d->previous_kind = kind;
    d->previous_tuple_known = 1;
    if (state == 1) {
        if (kind == 0x60 || kind == 0x62) {
            d->data[0] = 1;
            *known |= 1u;
        }
        if (kind == 0x61 || kind == 0x62) {
            d->data[1] = 1;
            *known |= 2u;
        }
    }
}

static void action_update(struct cp_start_state_data *d, unsigned char *known,
                          unsigned char action)
{
    unsigned int x = (unsigned char)(action - 1u);
    d->effective_action = x <= 2u ? action : 0;
    d->data[2] = x <= 2u ? (unsigned char)(UINT32_C(0x10000) >> (8u * x)) : 0;
    *known |= 4u;
    if (action == 1 || action == 2) {
        d->data[action - 1u] = 1;
        *known |= (unsigned char)(1u << (action - 1u));
    }
}

static int fourth_read(struct cp_start_state_data *d)
{
    unsigned char computed;
    unsigned char known = d->predicate_known_mask;
    if ((known & K_MODE) == 0)
        return -ENODATA;
    if (d->mode == 1) {
        if ((known & K_CACHE) == 0)
            return -ENODATA;
        /* a9885e has no result-side effects before the full-u8 override. */
        d->data[3] = d->override_cache;
    } else {
        if ((known & K_PROFILE) == 0)
            return -ENODATA;
        if (d->profile == 2) {
            computed = 1;
        } else if (d->profile == 1) {
            if ((known & K_KIND) == 0)
                return -ENODATA;
            computed = d->predicate_kind >= 1 && d->predicate_kind <= 3;
        } else {
            if ((known & K_Q) == 0)
                return -ENODATA;
            computed = d->q[0] >= 1 && d->q[0] <= 3 && d->q[1] == 9 &&
                       (d->q[2] & 0xf0u) == 0x20 && d->q[3] == 0x13;
        }
        d->data[3] = computed;
        if (d->mode == 2) {
            d->override_cache = computed;
            d->predicate_known_mask |= K_CACHE;
        }
    }
    d->known_mask |= 8u;
    return 0;
}

int cp_start_state_data_init(struct cp_start_state_data *d)
{
    struct cp_start_state_data next;
    if (!span_valid(d, sizeof(*d)) ||
        (uintptr_t)d % _Alignof(struct cp_start_state_data) != 0)
        return -EINVAL;
    memset(&next, 0, sizeof(next));
    next.owner_pid = (uint32_t)getpid();
    next.magic = OWNER_MAGIC;
    next.image_initial = 1; /* Public file bytes 10e31c6..c8, not BSS/history. */
    *d = next;
    return 0;
}

int cp_start_state_data_consume_lif(struct cp_start_state_data *d,
    const struct cp_start_state_guard *g, const struct cp_start_state_span *lif,
    const struct cp_start_state_span *bank, const struct cp_start_state_span *merge)
{
    struct cp_start_state_data next;
    unsigned char known, kind, state, subcode, action, mode;
    uint32_t flags;
    int rc = guard_valid(d, g, 0);
    if (rc != 0)
        return rc;
    rc = input_valid(d, lif);
    if (rc != 0)
        return rc;
    rc = input_valid(d, bank);
    if (rc != 0)
        return rc;
    if (lif->size != CP_START_STATE_LIF_BYTES || bank->size != CP_START_STATE_OVERRIDE_BYTES)
        return -EMSGSIZE;
    rc = require_known(lif, 0x81, 7);
    if (rc == 0)
        rc = require_known(lif, 0x128, 1);
    if (rc == 0)
        rc = require_known(bank, 0x1c8, 1);
    if (rc != 0)
        return rc;
    mode = bank->bytes[0x1c8];
    if (mode == 1) {
        rc = input_valid(d, merge);
        if (rc != 0)
            return rc;
        if (merge->size != CP_START_STATE_MERGE_BYTES)
            return -EMSGSIZE;
        rc = require_known(merge, 0, 1);
        if (rc == 0)
            rc = require_known(merge, 2, 1);
        if (rc != 0)
            return rc;
    } else if (merge != NULL) {
        return -EINVAL;
    }
    next = *d;
    known = next.image_initial ? 7u : (next.known_mask & 7u);
    kind = lif->bytes[0x81];
    state = lif->bytes[0x82];
    subcode = lif->bytes[0x83];
    action = lif->bytes[0x128];
    flags = le32(lif->bytes + 0x84);
    tuple_update(&next, &known, state, subcode, kind);
    if (flags == 0) {
        if (!next.previous_flags_known)
            maybe_clear(&next, &known);
        else if (next.previous_flags != 0)
            clear_pair(&next, &known);
    }
    next.previous_flags = flags;
    next.previous_flags_known = 1;
    if ((flags & 2u) != 0) {
        next.data[1] = 1;
        known |= 2u;
    }
    if ((flags & 0x20u) != 0) {
        next.data[0] = 1;
        known |= 1u;
    }
    action_update(&next, &known, action);
    if (mode == 2) {
        next.captured_live[0] = kind;
        next.captured_live[1] = state;
        next.captured_live[2] = subcode;
        next.captured_live[3] = action;
        next.captured_live_known = 1;
        tuple_update(&next, &known, state, subcode, kind);
    } else if (mode == 1) {
        unsigned char alternate_kind = merge->bytes[0];
        unsigned char alternate_subcode = merge->bytes[2];
        if (kind == 0x11 || alternate_kind == 0x11) {
            kind = 0x11; state = 3; subcode = 0x61; action = 2;
        } else if (kind == 0x10 || alternate_kind == 0x10) {
            kind = 0x10; state = 3; subcode = 0x61; action = 2;
        } else if (subcode == 0x61 || alternate_subcode == 0x61) {
            kind = 0; state = 3; subcode = 0x61; action = 2;
        } else if (kind == 0x62 || alternate_kind == 0x62) {
            kind = 0x62; state = 1; subcode = 0x32; action = 1;
        } else if (kind == 0x61 || alternate_kind == 0x61) {
            kind = 0x61; state = 1; subcode = 0x32; action = 1;
        } else if (kind == 0x60 || alternate_kind == 0x60) {
            kind = 0x60; state = 1; subcode = 0x32; action = 1;
        } else {
            kind = 0; state = 0; subcode = 0; action = 0;
        }
        tuple_update(&next, &known, state, subcode, kind);
        action_update(&next, &known, action);
    }
    if (known != 7u)
        return -ENODATA;
    next.raw_action = lif->bytes[0x128];
    next.effective_kind = kind;
    next.effective_state = state;
    next.effective_subcode = subcode;
    next.known_mask |= 7u;
    next.image_initial = 0;
    next.lif_consumed = 1;
    commit(d, &next, g);
    return 0;
}

int cp_start_state_data_consume_property(struct cp_start_state_data *d,
    const struct cp_start_state_guard *g, uint32_t property_id,
    const struct cp_start_state_span *payload)
{
    struct cp_start_state_data next;
    int rc = guard_valid(d, g, 0);
    if (rc != 0)
        return rc;
    rc = input_valid(d, payload);
    if (rc != 0)
        return rc;
    if (property_id != CP_START_STATE_PROPERTY_ID)
        return -ENOTSUP;
    rc = require_known(payload, 4, 1);
    if (rc != 0)
        return rc;
    next = *d;
    next.profile = payload->bytes[4];
    next.predicate_known_mask |= K_PROFILE;
    next.known_mask &= 7u;
    next.property_consumed = 1;
    commit(d, &next, g);
    return 0;
}

int cp_start_state_data_consume_adj(struct cp_start_state_data *d,
    const struct cp_start_state_guard *g, const struct cp_start_state_span *packet)
{
    struct cp_start_state_data next;
    unsigned int index;
    int rc = guard_valid(d, g, 0);
    if (rc != 0)
        return rc;
    rc = input_valid(d, packet);
    if (rc != 0)
        return rc;
    if (packet->size != 0x31u)
        return -ENOTSUP;
    rc = require_known(packet, 0x26, 1);
    if (rc == 0)
        rc = require_known(packet, 0x28, 9);
    if (rc != 0)
        return rc;
    index = packet->bytes[0x28] | (unsigned int)packet->bytes[0x29] << 8;
    if (packet->bytes[0x26] != 0xff || packet->bytes[0x2a] != 0x0a ||
        packet->bytes[0x2b] != 0 || le32(packet->bytes + 0x2c) != 1 ||
        (index != 0x80 && index != 0xb2))
        return -ENOTSUP;
    next = *d;
    if (index == 0x80) {
        next.mode = packet->bytes[0x30];
        next.predicate_known_mask |= K_MODE;
    } else {
        next.override_cache = packet->bytes[0x30];
        next.predicate_known_mask |= K_CACHE;
    }
    next.known_mask &= 7u;
    next.adj_consumed = 1;
    commit(d, &next, g);
    return 0;
}

int cp_start_state_data_consume_event(struct cp_start_state_data *d,
    const struct cp_start_state_guard *g, enum cp_start_state_event event,
    const struct cp_start_state_span *source)
{
    struct cp_start_state_data next;
    size_t needed;
    int rc = guard_valid(d, g, 0);
    if (rc != 0)
        return rc;
    rc = input_valid(d, source);
    if (rc != 0)
        return rc;
    switch (event) {
    case CP_START_STATE_EVENT_HISTORY: needed = 7; break;
    case CP_START_STATE_EVENT_PREDICATE_KIND: needed = 1; break;
    case CP_START_STATE_EVENT_Q_COPY: needed = 4; break;
    case CP_START_STATE_EVENT_Q_CLEAR: needed = 0; break;
    case CP_START_STATE_EVENT_FOURTH_READ: needed = 0; break;
    default: return -ENOTSUP;
    }
    if (source->size != needed)
        return -EMSGSIZE;
    rc = require_known(source, 0, needed);
    if (rc != 0)
        return rc;
    next = *d;
    switch (event) {
    case CP_START_STATE_EVENT_HISTORY:
        next.previous_state = source->bytes[0];
        next.previous_subcode = source->bytes[1];
        next.previous_kind = source->bytes[2];
        next.previous_tuple_known = 1;
        next.previous_flags = le32(source->bytes + 3);
        next.previous_flags_known = 1;
        break;
    case CP_START_STATE_EVENT_PREDICATE_KIND:
        next.predicate_kind = source->bytes[0];
        next.predicate_known_mask |= K_KIND;
        next.known_mask &= 7u;
        break;
    case CP_START_STATE_EVENT_Q_COPY:
        memcpy(next.q, source->bytes, 4);
        next.predicate_known_mask |= K_Q;
        next.known_mask &= 7u;
        break;
    case CP_START_STATE_EVENT_Q_CLEAR:
        memset(next.q, 0, 4);
        next.predicate_known_mask |= K_Q;
        next.known_mask &= 7u;
        break;
    case CP_START_STATE_EVENT_FOURTH_READ:
        rc = fourth_read(&next);
        if (rc != 0)
            return rc;
        break;
    default: return -ENOTSUP;
    }
    next.source_consumed = 1;
    commit(d, &next, g);
    return 0;
}

static int output_valid(const struct cp_start_state_data *d,
                        const struct cp_start_state_guard *g, void *out, size_t n)
{
    return span_valid(out, n) && !overlaps(d, sizeof(*d), out, n) &&
           !overlaps(g, sizeof(*g), out, n) ? 0 : -EINVAL;
}

int cp_start_state_data_snapshot(const struct cp_start_state_data *d,
    const struct cp_start_state_guard *g, struct cp_start_state_readback *out)
{
    struct cp_start_state_readback next;
    int rc = guard_valid(d, g, 1);
    if (rc != 0)
        return rc;
    rc = output_valid(d, g, out, sizeof(*out));
    if (rc != 0)
        return rc;
    if ((uintptr_t)out % _Alignof(struct cp_start_state_readback) != 0)
        return -EINVAL;
    memset(&next, 0, sizeof(next));
    next.owner_pid = d->owner_pid;
    next.revision = d->revision;
    next.source_sequence = d->source_sequence;
    next.source_origin = d->source_origin;
    memcpy(next.data, d->data, sizeof(next.data));
    next.known_mask = d->known_mask;
    next.predicate_known_mask = d->predicate_known_mask;
    next.lif_consumed = d->lif_consumed;
    next.property_consumed = d->property_consumed;
    next.adj_consumed = d->adj_consumed;
    next.source_consumed = d->source_consumed;
    next.effective_kind = d->effective_kind;
    next.effective_state = d->effective_state;
    next.effective_subcode = d->effective_subcode;
    next.effective_action = d->effective_action;
    memcpy(next.captured_live, d->captured_live, sizeof(next.captured_live));
    next.captured_live_known = d->captured_live_known;
    next.snapshot_copied = 1;
    next.data_ready = d->known_mask == 15u;
    *out = next;
    return 0;
}

int cp_start_state_data_build_reply(const struct cp_start_state_data *d,
    const struct cp_start_state_guard *g, uint16_t command, uint32_t echo,
    unsigned char *out, size_t out_size)
{
    unsigned char next[CP_START_STATE_REPLY_BYTES] = {0};
    int rc = guard_valid(d, g, 1);
    if (rc != 0)
        return rc;
    if (out_size != sizeof(next))
        return -EMSGSIZE;
    rc = output_valid(d, g, out, out_size);
    if (rc != 0)
        return rc;
    if (command != 0x3003 && command != 0x3000)
        return -ENOTSUP;
    if (d->known_mask != 15u || !d->lif_consumed)
        return -ENODATA;
    next[0] = 1;
    next[2] = (unsigned char)command;
    next[3] = (unsigned char)(command >> 8);
    put32(next + 4, echo);
    put32(next + 8, 0xf000);
    memcpy(next + 12, d->data, 4);
    memcpy(out, next, sizeof(next));
    return 0;
}
