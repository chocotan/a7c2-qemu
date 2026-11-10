/* SPDX-License-Identifier: MIT */
#ifndef FULL_SYSTEM_IMAGING_DEVICE_H
#define FULL_SYSTEM_IMAGING_DEVICE_H

#define FULL_IMAGING_CP 0x90040193u
#define FULL_IMAGING_AP 0x80020002u
#include <stddef.h>
#include <stdint.h>
#define FULL_IMAGING_POWER_ON_INHIBIT 0x04000000u
#define FULL_IMAGING_FUNCTIONAL_POLICY "actual-state128-virtual-optics-admission-v1"
#define FULL_IMAGING_LENS_POSITION_CP 0x90030001u
#define FULL_IMAGING_LENS_POSITION_POLICY "original-consumer-lens-position-unavailable-v1"
#define FULL_IMAGING_FOCUS_MAGNIFICATION_POLICY "original-consumer-focus-magnification-unavailable-v1"
#define FULL_IMAGING_FOCUS_RESET_POLICY "actual-optical-frame-focus-off-v1"
#define FULL_IMAGING_FOCUS_QUERY_POLICY "saved-full-frame-focus-checkpoint-state128-v1"
#define FULL_IMAGING_FELOCK_CP FULL_IMAGING_LENS_POSITION_CP
#define FULL_IMAGING_FELOCK_POLICY "original-consumer-flash-exposure-lock-unavailable-v1"

struct full_imaging_io {
    int (*allocate)(unsigned int, void **, unsigned int, unsigned int);
    int (*release)(unsigned int, void *);
    void (*set_source)(void *, unsigned int);
    int (*send)(unsigned int, void *);
    unsigned int (*size)(void *);
    unsigned int (*source)(void *);
    void (*record)(const char *, const char *);
};
struct full_imaging_focus_reset_receipt {
    uint64_t origin_fnv;
    unsigned char state[128], canonical[32], result[192];
};
typedef int (*full_imaging_focus_reset_backend)(const unsigned char[16],
                                               struct full_imaging_focus_reset_receipt *);
typedef int (*full_imaging_focus_query_backend)(const unsigned char[12], unsigned char[128]);
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
    int functional_owner_pid;
    unsigned int functional_enabled,functional_busy,live_replies;
    uint64_t functional_instance,functional_generation,functional_frame;
    unsigned long long focus_reset_requests,focus_reset_applied,focus_reset_failed;
    uint64_t focus_model_instance,focus_config_generation,focus_frame_generation,focus_result_fnv;
    unsigned long long focus_query_requests,focus_query_succeeded,focus_query_failed;
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
/* Explicit functional profile only. Strict capture_begin and requested cold bit
 * are unchanged. Real State128/caps/current identities govern the virtual
 * optics startup; original403d interlocks still use this same state owner. */
int full_imaging_functional_enable(void);
/* Binding is process-local setup without RPC; apply runs after exact reply
 * resource reservation, outside the private lock. Only raw validated actual
 * STATE128 -> RGB sink/retire -> class9/192 permits a successful (0,0) reset. */
int full_imaging_functional_bind_focus_reset(full_imaging_focus_reset_backend);
/* Only selector0x10f01 reads a previously RGB-consumed focus-off checkpoint.
 * Fresh same-instance STATE validates its live domain; missing state stays f001. */
int full_imaging_functional_bind_focus_query(full_imaging_focus_query_backend);
int full_imaging_capture_begin_functional(const uint8_t *,size_t,uint64_t expected_instance,uint64_t expected_generation);
/* Exact403d/4040 share this owner. Exact type5/414d8B on CP90030001 returns
 * 24B unavailable (f001); exact type5/403f16B on CP90040193 stays unavailable
 * unless body(0,0) completes the bound actual full-RGB-viewport transaction.
 * Exact type0/3020/12B on CP90030001, u32 input0/1, returns 12B FELock unavailable.
 * Exact type5/403e/12B selector0x10f01 returns16B from saved actual focus state,
 * after fresh STATE128; missing or invalid checkpoint remains unavailable.
 * No lens position, enabled magnification, flash lock, D012 or CP boot is synthesized. */
int full_imaging_functional_dispatch(unsigned,void *,const struct full_imaging_io *,int *);
void full_imaging_functional_observe_receive(unsigned,void *,unsigned source,unsigned bytes);
#ifdef FULL_IMAGING_TEST
void full_imaging_test_reset(unsigned int);
void full_imaging_test_still(unsigned int,unsigned int,unsigned int);
void full_imaging_test_arbitration(unsigned int,unsigned int,unsigned int,unsigned int,unsigned int);
void full_imaging_test_latches(unsigned int,unsigned int,unsigned int);
#endif
#endif
