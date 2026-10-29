/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_EE_CONTROLS_DIAGNOSTIC_H
#define NATIVE_CP_EE_CONTROLS_DIAGNOSTIC_H
#include "imaging-device.h"
#include <stdint.h>

#define NATIVE_CP_EE_CONTROLS_SID UINT32_C(0x90030001)
#define FULL_CP_EE_DIAGNOSTIC_PROFILE "diagnostic-cp-ee-controls-v1"
#define CP_EE_CONTROLS_SOURCE_BLOCKED (-1023)
#define CP_EE_CONTROLS_COMMANDS 3u
#define CP_EE_CONTROLS_REQUEST_MAX 24u

/* Parent reserves the existing shared guard, then checks SAME PID and actual
 * earlier 302c/4073/402d/4014/4057 original request/reply free rc0 pairs and all13
 * predecessors, with no retained/live/inflight work. Each pair needs its OWN
 * sender/waiter TID match; current 409d sender need NOT match earlier senders.
 * All callbacks run outside this owner's mutex. Readiness is native evidence,
 * never remote input or a claim that source business dependencies have closed.
 */
struct native_cp_ee_controls_diagnostic_guard {
    int (*reserve)(void);
    void (*release)(void);
    int (*predecessor_ready)(void);
};
struct native_cp_ee_controls_diagnostic_lease {
    unsigned int opcode, supported, oneway, source_byte1_known, request_bytes;
    unsigned int source, request_destination, destination, cookie;
    uint32_t request_fnv1a32;
    unsigned int attempts, requests, busy, guard_held, faults, queued;
    unsigned int request_freed, reply_freed, clean_completion, ap_consumed, oneway_consumed;
    unsigned int virtual_field_mask, virtual_fields_readback, virtual_fields_consumed;
    uint32_t virtual_fields[4], virtual_readback[4];
    unsigned int reply_free_destination, reply_free_source, reply_free_bytes;
    int allocate_rc, send_rc, request_free_rc, reply_free_rc;
    long sender_tid, waiter_tid;
    unsigned char request_wire[CP_EE_CONTROLS_REQUEST_MAX];
    unsigned char reply_wire[12], freed_reply_wire[12];
    void *retained_request, *live_reply, *retained_cleanup;
};
struct native_cp_ee_controls_diagnostic_snapshot {
    unsigned int initialized, diagnostic_only, virtual_padding;
    unsigned int business_applied, source_dependencies_closed, published, configured;
    unsigned int generation, native_cp, ee, frame, capture;
    unsigned int attempts, requests, completed, busy, guard_held, faults;
    int owner_pid;
    struct native_cp_ee_controls_diagnostic_lease leases[CP_EE_CONTROLS_COMMANDS];
};
/* One process-local construction BEFORE inputs; no reset/import/history writes.
 * Parent enables ONLY the exact existing capture-format profile value above.
 * Unrelated/default-off/3003 returns0 untouched. Refusal returns1/nonzero result
 * with request caller-owned; accepted ownership returns1/result0 even on later
 * transport failure. One attempt per command after native guard admission;
 * failures are permanent and retained pointers remain visible for cleanup.
 * Required order: 409d clean original reply/request free, 4072 real request free,
 * then 3012. 409d/3012 own separate exact12B type1/opcode/+4 cookie/f000 replies;
 * byte1 is UNKNOWN in source and explicitly virtual0 here. Their original AP
 * free must run on that command's OWN sender TID. 4072 NEVER allocates/sends an
 * ACK and never sets reply_freed/ap_consumed: oneway_consumed requires real
 * request free rc0. Four 409d bytes and two 4072 bytes are zero-extended into
 * virtual DIAGNOSTIC audit/readback only; masks0xf/0x3 prove that copy only.
 * 3003's16B reply contains four SOURCE DATA bytes+12..15, NOT padding; unknown
 * values must never be replaced by zero or acknowledged here. All source
 * business/configuration/publication/generation/native/EE/frame/capture stay0.
 */
int native_cp_ee_controls_diagnostic_owner_init(void);
int native_cp_ee_controls_diagnostic_dispatch(unsigned int, void *, const struct full_imaging_io *,
    const struct native_cp_ee_controls_diagnostic_guard *, int enabled, int *result);
/* Also recognizes retained request/failed-allocation cleanup for real freeing. */
int native_cp_ee_controls_diagnostic_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result);
void native_cp_ee_controls_diagnostic_snapshot(struct native_cp_ee_controls_diagnostic_snapshot *);
#ifdef NATIVE_CP_EE_CONTROLS_DIAGNOSTIC_TEST
void native_cp_ee_controls_diagnostic_test_hold_lock(void);
void native_cp_ee_controls_diagnostic_test_drop_lock(void);
#endif
#endif
