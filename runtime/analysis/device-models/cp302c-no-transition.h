/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP302C_NO_TRANSITION_H
#define NATIVE_CP302C_NO_TRANSITION_H
#include "imaging-device.h"
#define NATIVE_CP302C_SID 0x90030001u
#define FULL_CP302C_NO_TRANSITION_PROFILE "virtual-cp302c-current0-no-transition-v1"
#define FULL_CP302C_DIAGNOSTIC_PROFILE "diagnostic-cp302c-reply-only-v1"

/* reserve/release are the parent's shared resource reservation. While held,
 * predecessor_ready must inspect the actual all13 source owner's clean,
 * same-PID, original-AP-free snapshot, including its live/retained/work fields.
 * No caller-supplied readiness/state flags are accepted. All callbacks run
 * outside this owner's mutex and may read its snapshot. */
struct native_cp302c_guard {
    int (*reserve)(void);
    void (*release)(void);
    int (*predecessor_ready)(void);
};
struct native_cp302c_snapshot {
    unsigned int initialized, history_valid, current_known, current, central_busy;
    unsigned int diagnostic, diagnostic_inputs, diagnostic_transport;
    unsigned int observer_a, observer_b, executor_active, executor_last_event;
    unsigned int predecessor_seen, predecessor_completed, predecessor_cookie, predecessor_source;
    unsigned int generation, requests, busy, guard_held, faults;
    unsigned int queued, request_freed, reply_freed, clean_completion, ap_consumed;
    unsigned int no_transition, mode_transition, module_complete, module_effects, capture;
    unsigned int source_byte1_known, virtual_padding, cookie, destination;
    unsigned long long history_seq;
    int owner_pid, allocate_rc, send_rc, request_free_rc, reply_free_rc;
    long predecessor_sender_tid, sender_tid, waiter_tid;
    unsigned char predecessor_wire[24], request_wire[24], reply_wire[12];
    void *retained_request, *live_reply, *retained_cleanup;
};

/* Call exactly once from the process constructor, BEFORE ANY central input.
 * This applies the source-proved virtual initializer and actor constructors;
 * it neither reads original CP RAM nor accepts an arbitrary initial current.
 * Forked children reject before touching an inherited mutex or any callback. */
int native_cp302c_owner_init(void);
/* Alternative constructor ONLY, before any input. No CP state is established:
 * all current/actor storage remains unknown, and only transport is admitted
 * after the actual original 3007 waiter free and the unchanged all13 guard.
 * Neither initializer can reset an owner, change its mode, or clear faults. */
int native_cp302c_diagnostic_owner_init(void);
/* Observe every full central input before service/dispatch early returns.
 * Canonical rejected 302c probes do not execute a central event. Strict mode
 * invalidates history on untracked input. Diagnostic mode audits unmodeled
 * input without establishing history/config consumption; malformed/repeated
 * pre-admission 3007 evidence still faults. entry names the diagnostic producer. */
int native_cp302c_observe_input(unsigned int dst, const void *message,
                               unsigned int source, unsigned int bytes, const char *entry);
/* Source-proved strict prefix only; diagnostic auditing never expands it. */
int native_cp302c_parameter_prefix_supported(unsigned int command);
/* Parent calls ONLY from the actual original 3007 reply release hook, using
 * the complete wire copied BEFORE free and its recorded queue/send identity.
 * source is the reply's source SID; destination is its actual queue owner.
 * The sender must match the observed request's actual tid; freeing_tid is
 * checked against syscall(SYS_gettid), never used as a substitute for it. */
int native_cp302c_observe_3007_reply_freed(unsigned int source, unsigned int destination,
                                        const void *wire, unsigned int bytes,
                                        int queue_rc, int free_rc,
                                        long sender_tid, long freeing_tid);
/* Default off. 0 delegates unrelated messages; 1 with a nonzero result refuses
 * without transferring the original request. Allocation failure is before
 * admission. Once admitted, the request is consumed/retained by this owner and
 * result is 0 even on send failure; snapshots/logs retain every failure. No retry/reset after
 * an admitted request. Place BEFORE the legacy phase/perform/observer gate. */
int native_cp302c_dispatch(unsigned int, void *, const struct full_imaging_io *,
                          const struct native_cp302c_guard *, int enabled, int *result);
int native_cp302c_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                               void (*)(const char *, const char *), int *result);
void native_cp302c_snapshot(struct native_cp302c_snapshot *);
#ifdef NATIVE_CP302C_TEST
void native_cp302c_test_hold_lock(void);
void native_cp302c_test_drop_lock(void);
#endif
#endif
