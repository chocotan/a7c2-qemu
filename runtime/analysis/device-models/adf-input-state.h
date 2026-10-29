/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_INPUT_STATE_H
#define FULL_ADF_INPUT_STATE_H

struct full_adf_input_state;
typedef void (*full_adf_input_listener)(void *, unsigned int);
typedef void (*full_adf_input_completion)(struct full_adf_input_state *, unsigned int);
struct full_adf_input_job {
    unsigned int priority, active;
    unsigned long long generation;
};
struct full_adf_input_listener_slot {
    full_adf_input_listener callback;
    void *context;
    unsigned long long generation;
};
/* Virtual ownership only; these fields are never addresses in the original CP. */
struct full_adf_input_state {
    unsigned int known, fault, request, pending, parameter, input_state;
    full_adf_input_completion registered, submitted;
    struct full_adf_input_job jobs[32];
    struct full_adf_input_listener_slot listeners[5];
    unsigned int driver_parameter;
    full_adf_input_completion driver_callback;
    unsigned int callback_pending, callback_submitted, callback_driver_empty;
    unsigned int scheduler_registered, scheduler_consumed, controls, readbacks;
    unsigned int callbacks, listeners_called, listeners_removed, complete;
    unsigned long long generation;
};
/* Construction only: nonzero storage is rejected unchanged, never reset active work. */
int full_adf_input_init(struct full_adf_input_state *);
int full_adf_input_begin(struct full_adf_input_state *, unsigned long long,
                         full_adf_input_listener, void *);
int full_adf_input_pump(struct full_adf_input_state *, unsigned long long);
int full_adf_input_readback(const struct full_adf_input_state *, unsigned int *,
                            full_adf_input_completion *);
#endif
