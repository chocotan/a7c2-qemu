/* SPDX-License-Identifier: MIT */
#ifndef A7C2_VEF_PATH_DEVICE_H
#define A7C2_VEF_PATH_DEVICE_H
#include "imaging-device.h"
#define FULL_VEF_PATH_INPUT 0x92840747u
#define FULL_VEF_PATH_EMPTY 0xffffffffu
#define FULL_VEF_PATH_NOMEM 1u

/* Caller contract: reserve must hold the real common resource gate and verify tracked
 * native pools/pin work idle atomically. Nonzero means refused and NOT held.
 * Both callbacks must be present and must not reenter this module. */
struct full_vef_path_guard {
    int (*reserve)(void);
    void (*release)(void);
};
struct full_vef_path_snapshot {
    unsigned int configured, busy, faults, guard_held;
    unsigned int current_path, phase, state, generation, requested_path, inner_generation;
    /* S+0x22 is distinct from NoMem state; known only within this owned profile. */
    unsigned int runtime_status22, runtime_status22_known;
    unsigned int runtime_status22_writer_generation, runtime_status22_writes;
    unsigned int cached_handles[4], extra_resource, pending_context, work_pending;
    unsigned int selected_object, property, input_selection, stage0_done, stage1_done;
    unsigned int execution_status, outer_status, clean_completion, live_replies;
    unsigned int reply_owner, retained_request_owner, retained_cleanup_owner;
    unsigned long long requests, applications, queued, request_freed, reply_freed, cleanup_freed;
    void *live_reply, *retained_reply, *retained_request, *retained_cleanup_reply;
    int owner_pid, allocate_rc, send_rc, request_free_rc, reply_free_rc, cleanup_free_rc;
    unsigned char inner_request[20], inner_completion[12];
};
/* Own virtual NoMem cold state only; no CP RAM, frames, EE or global DMM claim.
 * Unknown CP writers/tables and original runtime RAM remain unverified.
 * Other commands/disabled return 0. A handled presend error retains the caller's
 * request. Valid path1 with refused resource reservation transfers the request
 * into faulted-pending ownership, returns OSAL0 and sends NO reply; the AP waits.
 * Other result=0 returns mean a separate reply was transferred; failed original
 * frees then remain owned here. Only one live transaction/reply.
 * Allocation runs outside the private mutex (recursive requests are refused).
 * Other transport/record callbacks must not reenter the module.
 * Constructor must bind the PID before fork; entries reject inherited child
 * ownership before callbacks or locks. Child snapshots have faults=1 and the
 * parent's owner_pid. */
int full_vef_path_owner_init(void);
int full_vef_path_dispatch(unsigned int, void *, const struct full_imaging_io *,
                           const struct full_vef_path_guard *, int, int *);
/* Recognizes queued replies, retained local cleanup and retained originals.
 * Failed frees retain pointer/owner; successful recovery never clears faults.
 * Only successfully freed queued replies increment reply_freed (AP consumption). */
int full_vef_path_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                              void (*)(const char *, const char *), int *);
void full_vef_path_snapshot(struct full_vef_path_snapshot *);
#ifdef FULL_VEF_PATH_TEST
void full_vef_path_test_reset(void);
void full_vef_path_test_resources(const unsigned int [4], unsigned int, unsigned int);
void full_vef_path_test_generation(unsigned int, int);
void full_vef_path_test_hold_lock(void);
void full_vef_path_test_drop_lock(void);
#endif
#endif
