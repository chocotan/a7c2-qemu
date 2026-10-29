/* SPDX-License-Identifier: MIT */
#include "adf-set-input-cold-owners.h"
#include <string.h>

static int zero_storage(const void *storage, unsigned long size)
{
    const unsigned char *bytes = storage;
    for (unsigned long i = 0; i < size; i++) if (bytes[i]) return 0;
    return 1;
}
static int hotshoe_fault(struct full_adf_hotshoe_owner *s)
{
    if (s) s->fault = 1;
    return -1021;
}
static int glee_fault(struct full_adf_glee_input_owner *s)
{
    if (s) s->fault = 1;
    return -1021;
}
int full_adf_hotshoe_owner_init(struct full_adf_hotshoe_owner *s)
{
    if (!s || !zero_storage(s, sizeof *s)) return -1021;
    /* D53/f167 67c336: owner122f140 +4..1b and FIFO indices/table start empty. */
    s->identity = s;
    s->known = 1;
    return 0;
}
static int hotshoe_base(const struct full_adf_hotshoe_owner *s)
{
    return s && s->identity == s && s->known == 1 && !s->fault && !s->busy &&
        !s->field_8 && !s->field_c && !s->field_10 && !s->field_14 && !s->current_type;
}
static int hotshoe_slots_empty(const struct full_adf_hotshoe_owner *s, unsigned int start)
{
    for (unsigned int i = start; i < FULL_ADF_HOTSHOE_CALLBACK_CAPACITY; i++)
        if (s->fifo[i].callback || s->fifo[i].context || s->fifo[i].generation) return 0;
    return 1;
}
int full_adf_hotshoe_register(struct full_adf_hotshoe_owner *s, unsigned long long generation,
                             full_adf_hotshoe_callback callback, void *context)
{
    /* shortcut: first cold callback only; prove the other lifecycle paths before reuse. */
    if (generation != 1 || !callback || !hotshoe_base(s) || s->generation || s->request ||
        s->requested_type || s->callback_active || s->registered || s->popped ||
        s->callbacks_started || s->callbacks_returned || s->type_commits || s->complete ||
        s->fifo_read || s->fifo_write || s->fifo_count || !hotshoe_slots_empty(s, 0))
        return hotshoe_fault(s);
    s->generation = generation;
    s->request = 1;
    s->fifo[0] = (struct full_adf_hotshoe_callback_slot){callback, context, generation};
    s->fifo_write = 1;
    s->fifo_count = 1;
    s->registered = 1;
    return 0;
}
int full_adf_hotshoe_set_type(struct full_adf_hotshoe_owner *s, unsigned long long generation,
                             unsigned int type)
{
    if (generation != 1 || type || !hotshoe_base(s) || s->generation != generation ||
        s->request != 1 || s->requested_type || s->callback_active || s->registered != 1 ||
        s->popped || s->callbacks_started || s->callbacks_returned || s->type_commits ||
        s->complete || s->fifo_read || s->fifo_write != 1 || s->fifo_count != 1 ||
        !s->fifo[0].callback || s->fifo[0].generation != generation || !hotshoe_slots_empty(s, 1))
        return hotshoe_fault(s);
    /* 19a468 -> 19a5a0 -> 19a24c -> 19ad30: pop before callback, commit after. */
    s->busy = 1;
    struct full_adf_hotshoe_callback_slot slot = s->fifo[0];
    memset(&s->fifo[0], 0, sizeof s->fifo[0]);
    s->fifo_read = 1;
    s->fifo_count = 0;
    s->popped = 1;
    s->callback_active = 1;
    s->callbacks_started = 1;
    struct full_adf_hotshoe_owner expected;
    memcpy(&expected, s, sizeof expected);
    slot.callback(slot.context, 0);
    if (memcmp(s, &expected, sizeof expected)) return hotshoe_fault(s);
    s->callbacks_returned = 1;
    s->callback_active = 0;
    s->current_type = type;
    s->field_c = 0;
    s->field_10 = 0;
    s->field_14 = 0;
    s->busy = 0;
    s->request = 0;
    s->type_commits = 1;
    s->complete = 1;
    return 0;
}

int full_adf_glee_input_owner_init(struct full_adf_glee_input_owner *s)
{
    if (!s || !zero_storage(s, sizeof *s)) return -1021;
    /* 70b2c8..70b300 and 70baa8: source1, sentinelff, Power +14=2 must survive. */
    s->identity = s;
    s->known = 1;
    s->input_source = 1;
    s->driver_sentinel = 0xff;
    s->power.field_14 = 2;
    return 0;
}
static int glee_base(const struct full_adf_glee_input_owner *s)
{
    if (!s || s->identity != s || s->known != 1 || s->fault || s->input_type ||
        s->input_source != 1 || s->input_callback_field || s->driver_parameter ||
        s->driver_callback || s->driver_sentinel != 0xff || s->ring_read || s->ring_write ||
        s->ring_count || s->kind_cache || s->power.field_c || s->power.field_10 ||
        s->power.field_14 != 2 || s->power.flag_20 || s->power.flag_21 || s->power.flag_22 ||
        s->power.queue_read || s->power.queue_write || s->power.queue_count) return 0;
    for (unsigned int i = 0; i < FULL_ADF_GLEE_INPUT_CAPACITY; i++)
        for (unsigned int j = 0; j < 6; j++) if (s->ring[i][j]) return 0;
    return 1;
}
static int glee_unrequested(const struct full_adf_glee_input_owner *s)
{
    return !s->generation && !s->request && !s->callback_active && !s->requested_kind &&
        !s->requested_type && !s->requested_source && !s->submitted && !s->context &&
        !s->callbacks_started && !s->callbacks_returned && !s->complete;
}
int full_adf_glee_input_note_control30(struct full_adf_glee_input_owner *s,
                                      unsigned long long generation, unsigned int parameter,
                                      full_adf_glee_input_callback callback, unsigned int complete)
{
    if (generation != 1 || parameter || callback || complete != 1 || !glee_base(s) ||
        !glee_unrequested(s) || s->control30_generation || s->control30_notes || s->control30_complete)
        return glee_fault(s);
    s->driver_parameter = parameter;
    s->driver_callback = callback;
    s->control30_generation = generation;
    s->control30_notes = 1;
    s->control30_complete = complete;
    return 0;
}
static int glee_control30_consumed(const struct full_adf_glee_input_owner *s)
{
    return s->control30_generation == 1 && s->control30_notes == 1 && s->control30_complete == 1;
}
int full_adf_glee_input_control0(struct full_adf_glee_input_owner *s, unsigned long long generation,
                                unsigned int kind, unsigned int type, unsigned int source,
                                full_adf_glee_input_callback callback, void *context)
{
    /* shortcut: first type0/source1, unchanged kind0 and Power cold branch only. */
    if (generation != 1 || kind || type || source != 1 || !callback || !glee_base(s) ||
        !glee_control30_consumed(s) || !glee_unrequested(s)) return glee_fault(s);
    s->generation = generation;
    s->request = 1;
    s->requested_kind = kind;
    s->requested_type = type;
    s->requested_source = source;
    s->submitted = callback;
    s->context = context;
    s->callback_active = 1;
    s->callbacks_started = 1;
    struct full_adf_glee_input_owner expected;
    memcpy(&expected, s, sizeof expected);
    /* 217c2e -> 217d5e: no ring jobs, Power/cache writes or driver30 replay. */
    callback(context, 0);
    if (memcmp(s, &expected, sizeof expected)) return glee_fault(s);
    s->callbacks_returned = 1;
    s->callback_active = 0;
    s->submitted = 0;
    s->context = 0;
    s->request = 0;
    s->complete = 1;
    return 0;
}
int full_adf_glee_input_control1(const struct full_adf_glee_input_owner *s,
                                unsigned int *type, unsigned int *source, unsigned int *callback)
{
    if (!type || !source || !callback || !glee_base(s) || !glee_control30_consumed(s) ||
        s->generation != 1 || s->requested_kind || s->requested_type || s->requested_source != 1 ||
        s->callbacks_started != 1) return -1021;
    if (!((s->request == 1 && s->callback_active == 1 && s->submitted &&
           !s->callbacks_returned && !s->complete) ||
          (!s->request && !s->callback_active && !s->submitted && !s->context &&
           s->callbacks_returned == 1 && s->complete == 1))) return -1021;
    *type = s->input_type;
    *source = s->input_source;
    *callback = s->input_callback_field;
    return 0;
}
