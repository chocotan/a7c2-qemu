/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_SET_INPUT_COLD_OWNERS_H
#define FULL_ADF_SET_INPUT_COLD_OWNERS_H

#define FULL_ADF_HOTSHOE_CALLBACK_CAPACITY 10u
#define FULL_ADF_GLEE_INPUT_CAPACITY 50u

typedef void (*full_adf_hotshoe_callback)(void *, unsigned int);
typedef void (*full_adf_glee_input_callback)(void *, unsigned int);
struct full_adf_hotshoe_callback_slot {
    full_adf_hotshoe_callback callback;
    void *context;
    unsigned long long generation;
};
/* Owned projections, never original CP addresses or packed wire structures. */
struct full_adf_hotshoe_owner {
    const struct full_adf_hotshoe_owner *identity;
    unsigned int known, fault;
    unsigned int busy, field_8, field_c, field_10, field_14, current_type;
    unsigned int fifo_read, fifo_write, fifo_count;
    struct full_adf_hotshoe_callback_slot fifo[FULL_ADF_HOTSHOE_CALLBACK_CAPACITY];
    unsigned long long generation;
    unsigned int request, requested_type, callback_active;
    unsigned int registered, popped, callbacks_started, callbacks_returned, type_commits, complete;
};
struct full_adf_glee_power_owner {
    unsigned int field_c, field_10, field_14;
    unsigned int flag_20, flag_21, flag_22;
    unsigned int queue_read, queue_write, queue_count;
};
struct full_adf_glee_input_owner {
    const struct full_adf_glee_input_owner *identity;
    unsigned int known, fault;
    unsigned int input_type, input_source, input_callback_field;
    unsigned int driver_parameter;
    full_adf_glee_input_callback driver_callback;
    unsigned int driver_sentinel, ring_read, ring_write, ring_count;
    unsigned int ring[FULL_ADF_GLEE_INPUT_CAPACITY][6];
    unsigned int kind_cache;
    struct full_adf_glee_power_owner power;
    unsigned long long control30_generation, generation;
    unsigned int control30_notes, control30_complete;
    unsigned int request, callback_active, requested_kind, requested_type, requested_source;
    full_adf_glee_input_callback submitted;
    void *context;
    unsigned int callbacks_started, callbacks_returned, complete;
};
/* Construction only, on zero storage before Proc0323; never reset at SetInput0336.
 * The caller serializes these owners and retains the transport request on failure.
 * identity rejects copied/foreign owners; direct external updates are unsupported. */
int full_adf_hotshoe_owner_init(struct full_adf_hotshoe_owner *);
int full_adf_hotshoe_register(struct full_adf_hotshoe_owner *, unsigned long long,
                             full_adf_hotshoe_callback, void *);
int full_adf_hotshoe_set_type(struct full_adf_hotshoe_owner *, unsigned long long, unsigned int);
int full_adf_glee_input_owner_init(struct full_adf_glee_input_owner *);
/* Record the actual Proc control30 readback and completion, once, after its callback
 * drained. Proc dependency/ownership must be validated by the caller, not inferred
 * from this note. Only the driver +14/+18 projection is written. */
int full_adf_glee_input_note_control30(struct full_adf_glee_input_owner *, unsigned long long,
                                      unsigned int, full_adf_glee_input_callback, unsigned int);
/* Original control0 words [kind=0,type=0,source=1,callback@173289].
 * callback is the real local C continuation, not the original CP address. */
int full_adf_glee_input_control0(struct full_adf_glee_input_owner *, unsigned long long,
                                unsigned int, unsigned int, unsigned int,
                                full_adf_glee_input_callback, void *);
int full_adf_glee_input_control1(const struct full_adf_glee_input_owner *,
                                unsigned int *, unsigned int *, unsigned int *);
#endif
