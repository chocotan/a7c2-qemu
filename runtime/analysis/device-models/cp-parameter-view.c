/* SPDX-License-Identifier: MIT */
#include "cp-parameter-view.h"
#include <string.h>
#include <unistd.h>

#define VIEW_MAGIC UINT32_C(0x43505653)

_Static_assert(CP_PARAMETER_VIEW_OVERRIDE_BYTES <= CP_PARAMETER_STATE_IMAGE_BYTES,
               "override span fits S");
_Static_assert(CP_PARAMETER_VIEW_CONFIG_SOURCE_VA ==
               CP_PARAMETER_VIEW_PUBLISHED_VA + 0x1144u,
               "config source is separate from d64 P copy");
_Static_assert(CP_PARAMETER_STATE_IMAGE_BYTES <= 0x1144u &&
               CP_PARAMETER_VIEW_CONFIG_WORD_OFFSET + 4 <= CP_PARAMETER_VIEW_CONFIG_BYTES,
               "config word fits independent config copy");
_Static_assert(CP_PARAMETER_VIEW_BANK3_VA == CP_PARAMETER_VIEW_PUBLISHED_VA + 0xe18u &&
               CP_PARAMETER_VIEW_BANK3_VA + 0x64cu ==
               CP_PARAMETER_VIEW_CONFIG_COPY_VA + CP_PARAMETER_VIEW_CONFIG_WORD_OFFSET,
               "bank3 getter aliases config copy word");

static int span_valid(const void *p, size_t n)
{
    return p != NULL && n != 0 && n <= UINTPTR_MAX - (uintptr_t)p;
}

static int overlaps(const void *a, size_t an, const void *b, size_t bn)
{
    return (uintptr_t)a < (uintptr_t)b + bn &&
           (uintptr_t)b < (uintptr_t)a + an;
}

static int owner_valid(const struct cp_parameter_view *v)
{
    if (!span_valid(v, sizeof(*v)) ||
        (uintptr_t)v % _Alignof(struct cp_parameter_view) != 0)
        return -EINVAL;
    if (v->magic != VIEW_MAGIC || v->copy_consumed > 1 ||
        v->bank0_bound > 1 || v->invalidated > 1 ||
        (v->bank0_bound && (!v->copy_consumed || v->invalidated)) ||
        v->config_source_known > 1 || v->config_word_known > 1 ||
        v->bank3_bound > 1 || v->bank3_invalidated > 1 ||
        v->flagb_known > 1 || v->flagb > 1 ||
        v->config_copy_event < CP_PARAMETER_VIEW_CONFIG_COPY_NONE ||
        v->config_copy_event > CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY ||
        v->config_copy_input < CP_PARAMETER_VIEW_CONFIG_INPUT_NONE ||
        v->config_copy_input > CP_PARAMETER_VIEW_CONFIG_INPUT_SPAN ||
        ((v->config_copy_event == CP_PARAMETER_VIEW_CONFIG_COPY_NONE) !=
         (v->config_copy_input == CP_PARAMETER_VIEW_CONFIG_INPUT_NONE)) ||
        (v->config_source_known && !v->config_copy_event && v->config_source_word != 2) ||
        (v->config_word_known && !v->config_copy_event) ||
        (v->bank3_bound && (!v->config_copy_event || v->bank3_invalidated)) ||
        (v->flagb_known && (!v->bank3_bound || !v->config_word_known ||
                           v->flagb != (v->config_word == 0))))
        return -EINVAL;
    if (v->owner_pid != (uint32_t)getpid())
        return -EXDEV;
    return 0;
}

static int guard_valid(const struct cp_parameter_view *v,
                       const struct cp_start_state_guard *g)
{
    int rc = owner_valid(v);
    if (rc != 0)
        return rc;
    if (!span_valid(g, sizeof(*g)) ||
        (uintptr_t)g % _Alignof(struct cp_start_state_guard) != 0 ||
        overlaps(v, sizeof(*v), g, sizeof(*g)))
        return -EINVAL;
    if (g->owner_pid != v->owner_pid)
        return -EXDEV;
    if (g->source_origin != CP_START_STATE_ORIGIN_VIRTUAL_SOURCE &&
        g->source_origin != CP_START_STATE_ORIGIN_HOST_TEST)
        return -EINVAL;
    if (v->source_origin != CP_START_STATE_ORIGIN_NONE &&
        g->source_origin != v->source_origin)
        return -EXDEV;
    if (g->quiescent != 1 || g->sequence_before != g->sequence_after ||
        (g->sequence_before & 1u) != 0)
        return -EAGAIN;
    if (g->sequence_before < v->source_sequence)
        return -ESTALE;
    return 0;
}

static void record_event(struct cp_parameter_view *v,
                         const struct cp_start_state_guard *g)
{
    v->source_sequence = g->sequence_before;
    v->source_origin = g->source_origin;
}

int cp_parameter_view_init(struct cp_parameter_view *v)
{
    if (!span_valid(v, sizeof(*v)) ||
        (uintptr_t)v % _Alignof(struct cp_parameter_view) != 0)
        return -EINVAL;
    memset(v, 0, sizeof(*v));
    v->owner_pid = (uint32_t)getpid();
    v->magic = VIEW_MAGIC;
    return 0;
}

int cp_parameter_view_consume_initial_copy(struct cp_parameter_view *v,
    const struct cp_start_state_guard *g, const struct cp_parameter_state *source)
{
    unsigned char local;
    int rc = guard_valid(v, g);
    if (rc != 0)
        return rc;
    if (!span_valid(source, sizeof(*source)) ||
        overlaps(v, sizeof(*v), source, sizeof(*source)) ||
        overlaps(g, sizeof(*g), source, sizeof(*source)))
        return -EINVAL;
    /* The public read validates magic/PID/enabled even when override is unknown. */
    rc = cp_parameter_state_read(source, CP_PARAMETER_STATE_OVERRIDE_MODE_OFFSET,
                                 &local, sizeof(local));
    if (rc != 0 && rc != -ENODATA)
        return rc;
    if (v->copy_consumed)
        return -EBUSY;
    memcpy(v->bytes, source->bytes, sizeof(v->bytes));
    memcpy(v->known_mask, source->known_mask, sizeof(v->known_mask));
    v->copy_consumed = 1;
    v->copy_sequence = g->sequence_before;
    record_event(v, g);
    return 0;
}

int cp_parameter_view_consume_bank0_binding(struct cp_parameter_view *v,
    const struct cp_start_state_guard *g, uint32_t logical_root)
{
    int rc = guard_valid(v, g);
    if (rc != 0)
        return rc;
    if (!v->copy_consumed)
        return -ENODATA;
    if (logical_root != CP_PARAMETER_VIEW_PUBLISHED_VA) {
        v->bank0_bound = 0;
        v->invalidated = 1;
        record_event(v, g);
        return -ENOTSUP;
    }
    if (v->invalidated)
        return -ESTALE;
    if (v->bank0_bound)
        return -EBUSY;
    v->bank0_bound = 1;
    v->bank_sequence = g->sequence_before;
    record_event(v, g);
    return 0;
}

int cp_parameter_view_invalidate(struct cp_parameter_view *v,
    const struct cp_start_state_guard *g)
{
    int rc = guard_valid(v, g);
    if (rc != 0)
        return rc;
    if (!v->copy_consumed)
        return -ENODATA;
    v->bank0_bound = 0;
    v->invalidated = 1;
    record_event(v, g);
    return 0;
}

int cp_parameter_view_copy_override_span(const struct cp_parameter_view *v,
    const struct cp_start_state_guard *g, unsigned char *bytes, size_t capacity,
    unsigned char *known, size_t known_capacity)
{
    int rc = guard_valid(v, g);
    if (rc != 0)
        return rc;
    if (!span_valid(bytes, capacity) || !span_valid(known, known_capacity))
        return -EINVAL;
    if (capacity < CP_PARAMETER_VIEW_OVERRIDE_BYTES ||
        known_capacity < CP_PARAMETER_VIEW_OVERRIDE_BYTES)
        return -EMSGSIZE;
    if (overlaps(v, sizeof(*v), bytes, capacity) ||
        overlaps(v, sizeof(*v), known, known_capacity) ||
        overlaps(g, sizeof(*g), bytes, capacity) ||
        overlaps(g, sizeof(*g), known, known_capacity) ||
        overlaps(bytes, capacity, known, known_capacity))
        return -EINVAL;
    if (v->invalidated)
        return -ESTALE;
    if (!v->copy_consumed || !v->bank0_bound)
        return -ENODATA;
    memcpy(bytes, v->bytes, CP_PARAMETER_VIEW_OVERRIDE_BYTES);
    for (size_t i = 0; i < CP_PARAMETER_VIEW_OVERRIDE_BYTES; ++i)
        known[i] = (unsigned char)((v->known_mask[i / 8u] >> (i % 8u)) & 1u);
    return 0;
}

int cp_parameter_view_consume_config_constructor_store(struct cp_parameter_view *v,
    const struct cp_start_state_guard *g)
{
    int rc = guard_valid(v, g);
    if (rc != 0)
        return rc;
    if (v->config_source_known || v->config_copy_event)
        return -EBUSY;
    v->config_source_word = 2;
    v->config_source_known = 1;
    v->constructor_store_sequence = g->sequence_before;
    record_event(v, g);
    return 0;
}

static int config_span_valid(const struct cp_parameter_view *v,
    const struct cp_start_state_guard *g, const struct cp_start_state_span *s)
{
    if (!span_valid(s, sizeof(*s)) ||
        (uintptr_t)s % _Alignof(struct cp_start_state_span) != 0 ||
        overlaps(v, sizeof(*v), s, sizeof(*s)) ||
        overlaps(g, sizeof(*g), s, sizeof(*s)))
        return -EINVAL;
    if (s->size != CP_PARAMETER_VIEW_CONFIG_BYTES || s->known_size < s->size)
        return -EMSGSIZE;
    if (!span_valid(s->bytes, s->size) || !span_valid(s->known, s->known_size) ||
        overlaps(v, sizeof(*v), s->bytes, s->size) ||
        overlaps(v, sizeof(*v), s->known, s->known_size) ||
        overlaps(g, sizeof(*g), s->bytes, s->size) ||
        overlaps(g, sizeof(*g), s->known, s->known_size) ||
        overlaps(s, sizeof(*s), s->bytes, s->size) ||
        overlaps(s, sizeof(*s), s->known, s->known_size) ||
        overlaps(s->bytes, s->size, s->known, s->known_size))
        return -EINVAL;
    for (size_t i = 0; i < s->size; ++i)
        if (s->known[i] > 1)
            return -EINVAL;
    return 0;
}

int cp_parameter_view_consume_config_copy(struct cp_parameter_view *v,
    const struct cp_start_state_guard *g, enum cp_parameter_view_config_copy_event event,
    const struct cp_start_state_span *source)
{
    uint32_t word = 0;
    unsigned char known = 1;
    int rc = guard_valid(v, g);
    if (rc != 0)
        return rc;
    if (event != CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL &&
        event != CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY)
        return -ENOTSUP;
    if (source != NULL) {
        rc = config_span_valid(v, g, source);
        if (rc != 0)
            return rc;
        for (size_t i = 0; i < 4; ++i)
            known &= source->known[CP_PARAMETER_VIEW_CONFIG_WORD_OFFSET + i];
        if (known)
            for (size_t i = 0; i < 4; ++i)
                word |= (uint32_t)source->bytes[CP_PARAMETER_VIEW_CONFIG_WORD_OFFSET + i]
                        << (8u * i);
    } else {
        if (event != CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL)
            return -EINVAL;
        if (!v->config_source_known)
            return -ENODATA;
        word = v->config_source_word;
    }
    if (event == CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL && v->config_copy_event)
        return -EBUSY;
    if (event == CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY && !v->config_copy_event)
        return -ENODATA;
    v->config_source_word = word;
    v->config_source_known = known;
    v->config_word = word;
    v->config_word_known = known;
    v->config_copy_event = event;
    v->config_copy_input = source == NULL ? CP_PARAMETER_VIEW_CONFIG_INPUT_CONSTRUCTOR :
                                          CP_PARAMETER_VIEW_CONFIG_INPUT_SPAN;
    v->config_copy_sequence = g->sequence_before;
    v->flagb_known = 0;
    record_event(v, g);
    return 0;
}

int cp_parameter_view_consume_bank3_binding(struct cp_parameter_view *v,
    const struct cp_start_state_guard *g, uint32_t logical_root)
{
    int rc = guard_valid(v, g);
    if (rc != 0)
        return rc;
    if (!v->config_copy_event)
        return -ENODATA;
    if (logical_root != CP_PARAMETER_VIEW_BANK3_VA) {
        v->bank3_bound = 0;
        v->bank3_invalidated = 1;
        v->flagb_known = 0;
        record_event(v, g);
        return -ENOTSUP;
    }
    if (v->bank3_invalidated)
        return -ESTALE;
    if (v->bank3_bound)
        return -EBUSY;
    v->bank3_bound = 1;
    v->bank3_sequence = g->sequence_before;
    record_event(v, g);
    return 0;
}

int cp_parameter_view_consume_flagb_store(struct cp_parameter_view *v,
    const struct cp_start_state_guard *g)
{
    int rc = guard_valid(v, g);
    if (rc != 0)
        return rc;
    if (v->bank3_invalidated)
        return -ESTALE;
    if (!v->bank3_bound || !v->config_word_known)
        return -ENODATA;
    v->flagb = (unsigned char)(v->config_word == 0);
    v->flagb_known = 1;
    v->flagb_store_sequence = g->sequence_before;
    record_event(v, g);
    return 0;
}

int cp_parameter_view_copy_flagb(const struct cp_parameter_view *v,
    const struct cp_start_state_guard *g, struct cp_parameter_view_flagb_readback *out)
{
    struct cp_parameter_view_flagb_readback next;
    int rc = guard_valid(v, g);
    if (rc != 0)
        return rc;
    if (!span_valid(out, sizeof(*out)) ||
        (uintptr_t)out % _Alignof(struct cp_parameter_view_flagb_readback) != 0 ||
        overlaps(v, sizeof(*v), out, sizeof(*out)) ||
        overlaps(g, sizeof(*g), out, sizeof(*out)))
        return -EINVAL;
    if (v->bank3_invalidated)
        return -ESTALE;
    if (!v->flagb_known)
        return -ENODATA;
    if (g->sequence_before != v->source_sequence)
        return -ESTALE;
    memset(&next, 0, sizeof(next));
    next.owner_pid = v->owner_pid;
    next.config_word = v->config_word;
    next.source_sequence = v->source_sequence;
    next.constructor_store_sequence = v->constructor_store_sequence;
    next.config_copy_sequence = v->config_copy_sequence;
    next.bank3_sequence = v->bank3_sequence;
    next.flagb_store_sequence = v->flagb_store_sequence;
    next.source_origin = v->source_origin;
    next.config_copy_event = v->config_copy_event;
    next.config_copy_input = v->config_copy_input;
    next.flagb = v->flagb;
    *out = next;
    return 0;
}
