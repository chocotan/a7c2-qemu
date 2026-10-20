/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_COLD_CONTROL_H
#define NATIVE_CP_COLD_CONTROL_H
#include "cp-sync-resources.h"

/* Explicit finite mode3/cold control profile, not a sensor-ready service.
 * The caller owns the resource bank and must keep it alive. Only slot0's
 * parameter/idle contract is a completed backend. Other requests remain
 * pending: known policy/state publication is separately observable, never
 * used to claim all peripherals complete. No original RAM or reply is written.
 * The owner must quiesce callers before destruction. */
struct cp_cold_control;
struct cp_cold_snapshot {
    unsigned int generation, busy, current, target, group, path;
    unsigned int ended_command, pending_modules, parameter_valid;
    unsigned int requested[13], observed[13];
    unsigned char parameters[12];
    unsigned int state_record_generation, state_record_valid, state_record_value;
    unsigned int policy_flags_valid;
    unsigned char policy_flags[13];
    unsigned int model_mode, completion_event_pending, busy_mirror;
    unsigned int observer_a_state, observer_b_state, observer_a_index, observer_b_index;
    unsigned int observer_a_member[2], observer_b_member[2], observer_notifications;
    unsigned int exec_active, exec_last_event;
};
struct cp_cold_control *cp_cold_create(unsigned int model_mode, struct cp_sync_resources *);
int cp_cold_destroy(struct cp_cold_control *);
int cp_cold_begin(struct cp_cold_control *, unsigned int command);
/* One modeled periodic pass. Returns 1 only when the selected boundary/path
 * ends, 0 while waiting, negative on unsupported state. No CP success packet. */
int cp_cold_tick(struct cp_cold_control *);
/* Read-clear the ended command, analogous to the original internal completion
 * value. It is not an AP reply or hardware-ready notification. */
int cp_cold_take_end(struct cp_cold_control *, unsigned int *command);
/* The proved event304 dispatch effects, after read-clear. This updates owned
 * observer metadata/exec handle, never injects an event into original firmware. */
int cp_cold_observe_end(struct cp_cold_control *, unsigned int command);
int cp_cold_snapshot(struct cp_cold_control *, struct cp_cold_snapshot *);
#endif
