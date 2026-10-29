/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_STARTUP_CONTROLS_DIAGNOSTIC_H
#define NATIVE_CP_STARTUP_CONTROLS_DIAGNOSTIC_H
#include "imaging-device.h"
#include <stdint.h>

#define NATIVE_CP_STARTUP_CONTROLS_SID UINT32_C(0x90030001)
#define FULL_CP_STARTUP_DIAGNOSTIC_PROFILE "diagnostic-cp-startup-controls-v1"
#define CP_STARTUP_CONTROLS_SOURCE_BLOCKED (-1022)
#define CP_STARTUP_CONTROLS_COMMANDS 3u
/* Storage capacity only: an opcode still needs its independently proved size. */
#define CP_STARTUP_CONTROLS_REQUEST_MAX 328u

/* Parent reserves its shared guard and verifies actual same-PID, original AP
 * free rc0/sender for402d,4063/40f9 and all13 predecessors, with no retained,
 * live or inflight work. These callbacks, and every IO callback, run unlocked.
 * Mock readiness in host tests is not evidence that business dependencies close.
 */
struct native_cp_startup_controls_diagnostic_guard {
    int (*reserve)(void);
    void (*release)(void);
    int (*predecessor_ready)(void);
};
struct native_cp_startup_controls_diagnostic_lease {
    unsigned int opcode, supported, source_byte1_known, request_bytes, source, request_destination, destination, cookie;
    uint32_t request_fnv1a32;
    unsigned int requests, busy, guard_held, faults, queued;
    unsigned int request_freed, reply_freed, clean_completion, ap_consumed;
    unsigned int reply_free_destination, reply_free_source, reply_free_bytes;
    int allocate_rc, send_rc, request_free_rc, reply_free_rc;
    long sender_tid, waiter_tid;
    unsigned char request_wire[CP_STARTUP_CONTROLS_REQUEST_MAX];
    unsigned char reply_wire[12], freed_reply_wire[12];
    void *retained_request, *live_reply, *retained_cleanup;
};
struct native_cp_startup_controls_diagnostic_snapshot {
    unsigned int initialized, diagnostic_only, virtual_padding;
    unsigned int business_applied, source_dependencies_closed, published, configured;
    unsigned int generation, native_cp, ee, frame, capture;
    unsigned int requests, completed, busy, guard_held, faults;
    int owner_pid;
    struct native_cp_startup_controls_diagnostic_lease leases[CP_STARTUP_CONTROLS_COMMANDS];
};
/* One-shot process-local constructor BEFORE inputs; no reset, importer, AP
 * state write or history override. The caller enables only the exact profile.
 * Unsupported/default-off/unrelated returns0 without ownership. A refusal
 * returns1/nonzero result with request caller-owned. Admission returns1/result0
 * even if transport subsequently fails; retained pointers and sticky faults
 * remain visible. Each proved opcode can be admitted once. Next admission needs
 * exact original AP reply free rc0 on original sender plus request free rc0.
 * Reply is a separate real12B type1/opcode/opaque cookie/f000 allocation, only
 * for contracts proved in the implementation. Byte1=0 is virtual padding.
 * Payload copy/hash and clean_completion/ap_consumed establish transport only;
 * all business/configuration/publication/generation/native/EE/capture flags stay0.
 */
int native_cp_startup_controls_diagnostic_owner_init(void);
int native_cp_startup_controls_diagnostic_dispatch(unsigned int, void *, const struct full_imaging_io *,
    const struct native_cp_startup_controls_diagnostic_guard *, int enabled, int *result);
int native_cp_startup_controls_diagnostic_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result);
void native_cp_startup_controls_diagnostic_snapshot(struct native_cp_startup_controls_diagnostic_snapshot *);
#ifdef NATIVE_CP_STARTUP_CONTROLS_DIAGNOSTIC_TEST
void native_cp_startup_controls_diagnostic_test_hold_lock(void);
void native_cp_startup_controls_diagnostic_test_drop_lock(void);
#endif
#endif
