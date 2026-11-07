/* SPDX-License-Identifier: MIT */
#ifndef FULL_SYSTEM_IMAGING_DEVICE_H
#define FULL_SYSTEM_IMAGING_DEVICE_H

#define FULL_IMAGING_CP 0x90040193u
#define FULL_IMAGING_AP 0x80020002u
#define FULL_IMAGING_POWER_ON_INHIBIT 0x04000000u

struct full_imaging_io {
    int (*allocate)(unsigned int, void **, unsigned int, unsigned int);
    int (*release)(unsigned int, void *);
    void (*set_source)(void *, unsigned int);
    int (*send)(unsigned int, void *);
    unsigned int (*size)(void *);
    unsigned int (*source)(void *);
    void (*record)(const char *, const char *);
};
struct full_imaging_snapshot {
    unsigned int requested, suppressed, effective, active_capture, faults;
    unsigned long long applied, queued, waiter_freed;
    unsigned int still_active[23], still_token[23];
    unsigned int af_selector, ae_selector, bw_selector, af_gate, arbiter_disabled;
    unsigned int focus_trigger[23], focus_af, focus_ae, focus_bw;
    unsigned int last_focus_message[6];
    unsigned long long still_unlocks, focus_controls;
    unsigned int control_latch, pending_still_13, focus_latch_09;
    unsigned int internal_counter_a, internal_counter_b;
};

/* Returns 0 for another destination. A handled error retains the caller's
 * request; accepted requests are consumed once, with a separate queued reply. */
int full_imaging_dispatch(unsigned int, void *, const struct full_imaging_io *, int *);
int full_imaging_release_reply(unsigned int, void *, int (*)(unsigned int,void *),
                               void (*)(const char *, const char *), int *);
void full_imaging_snapshot(struct full_imaging_snapshot *);
/* Future capture backends must enter through this same gate. No sensor or
 * capture backend currently clears the retained power-on inhibit. */
int full_imaging_capture_begin(void);
void full_imaging_capture_end(void);
#ifdef FULL_IMAGING_TEST
void full_imaging_test_reset(unsigned int);
void full_imaging_test_still(unsigned int,unsigned int,unsigned int);
void full_imaging_test_arbitration(unsigned int,unsigned int,unsigned int,unsigned int,unsigned int);
void full_imaging_test_latches(unsigned int,unsigned int,unsigned int);
#endif
#endif
