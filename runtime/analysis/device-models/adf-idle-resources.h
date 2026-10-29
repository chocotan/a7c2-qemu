/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_IDLE_RESOURCES_H
#define FULL_ADF_IDLE_RESOURCES_H

#define FULL_ADF_IDLE_CONTROLLERS 2u
#define FULL_ADF_IDLE_STOCKERS 5u
#define FULL_ADF_IDLE_PINS 3u
#define FULL_ADF_IDLE_STOCK_CAPACITY 20u

enum full_adf_idle_controller_kind {
    FULL_ADF_IDLE_AUDIO = 0,
    FULL_ADF_IDLE_YC = 1
};
enum full_adf_idle_stocker_kind {
    FULL_ADF_IDLE_AUDIO0 = 0,
    FULL_ADF_IDLE_AUDIO1,
    FULL_ADF_IDLE_AC3,
    FULL_ADF_IDLE_EXT_CODEC,
    FULL_ADF_IDLE_YC0
};

struct full_adf_idle_controller {
    unsigned int known, selector, mode, registered, busy, flags, events;
    unsigned int mode_writes, flag_writes;
};
struct full_adf_idle_stocker {
    unsigned int known, read_index, write_index, count, policy;
    unsigned long long opaque_tokens[FULL_ADF_IDLE_STOCK_CAPACITY];
    unsigned long long resource_uses;
    unsigned int clear_calls;
    int clear_result;
};
struct full_adf_idle_pin {
    unsigned int known, type, current_path, requested_path;
    unsigned int phase1_path, phase2_path, phase, pending, done_mask;
    unsigned long long opaque_lease, lease_uses;
    unsigned int registrations, phase1_calls, phase2_calls;
};
/* Owned virtual cold metadata only; no original CP RAM or external DMM access.
 * Caller serializes access. These actions do not complete ADF Idle or input work. */
struct full_adf_idle_resources {
    unsigned int known, preparations;
    unsigned long long generation;
    struct full_adf_idle_controller controllers[FULL_ADF_IDLE_CONTROLLERS];
    struct full_adf_idle_stocker stockers[FULL_ADF_IDLE_STOCKERS];
    /* WrAudioPin(type2), Write(type1), Read(type0). */
    struct full_adf_idle_pin pins[FULL_ADF_IDLE_PINS];
};
/* Zero the storage once before init; nonzero storage is rejected unchanged. */
int full_adf_idle_resources_init(struct full_adf_idle_resources *);
/* Admission is for the unused cold generation; prepared state is not reusable. */
int full_adf_idle_resources_admissible(const struct full_adf_idle_resources *);
/* 0 = prepared and read back, -1021 = rejected with all metadata unchanged.
 * shortcut: only cold generation 1, extend after later lifecycle contracts exist. */
int full_adf_idle_resources_prepare(struct full_adf_idle_resources *, unsigned long long generation);

#endif
