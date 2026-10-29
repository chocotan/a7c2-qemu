/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_CAPTURE_FORMAT_H
#define NATIVE_CP_CAPTURE_FORMAT_H
#include "imaging-device.h"
#include <stddef.h>
#include <stdint.h>

#define NATIVE_CP_CAPTURE_FORMAT_SID UINT32_C(0x90030001)
/* Reserved integration name; no successful consumer implements this profile. */
#define FULL_CP_CAPTURE_FORMAT_PROFILE "virtual-cp-capture-format-v1"
#define FULL_CP_CAPTURE_FORMAT_DIAGNOSTIC_PROFILE "diagnostic-cp402d-reply-only-v1"
#define CP_CAPTURE_FORMAT_BYTES 24u
#define CP_CAPTURE_FORMAT_SOURCE_BLOCKED (-1021)
#define CP_CAPTURE_FORMAT_FIRST_MISSING UINT32_C(0x353eac)

/* Public CP f5a477...a1428, raw base108000, Thumb:
 * table10faec0, index41, 20B: 402d/3561cd/0/0/35f4b1.
 * 3561cc: wire+8 -> P+e0(u32), +9 -> P+f8(u32), six LE16 at
 * +10,+12,+14,+16,+18,+20 -> P+104,+106,+108,+114,+116,+118.
 * +1 and +22..23 are not consumed; +4 is an opaque reply cookie.
 * 35f4b0 compares these values only if its second argument is1, logging
 * mismatches. It neither validates enum ranges nor rejects the request.
 *
 * FIRST MISSING: mandatory 353ea4 reads P+100 at353eac, then P+110 at353ed2.
 * Those selectors choose/merge the pair fields and are absent from402d.
 * No selector state importer exists here. In particular,4063's190-slot
 * staging copy is NOT semantic application and supplies no such state.
 * 353fec additionally needs P+138/P+2a0/P+b40 for4a82f4 dimension lookup.
 * b0de20 calls476e18 then b0e99e before the reply. b0e99e builds a20B
 * common record at1720280, compares via b0eb2c against current/global state,
 * and can enter b0eb80/b0ebbe wait/publish paths. A format-payload copy
 * cannot substitute for these operations or justify a generation advance.
 * Only after that call returns does3562ae construct type1/402d/echo/f000.
 * Byte1 of that12B reply is unassigned, not a source-proven zero.
 *
 * The strict inspector/dispatch below remain fail-closed, not a virtual config
 * consumer. They never allocate, send, release, publish or own a request.
 * No success status, generation, pending completion, CP, EE, frame or capture
 * is established. A future implementation must close the missing dependency
 * before enabling the reserved profile; inventing selectors is insufficient
 * to close the downstream common publication branch.
 */
struct cp_capture_format_audit {
    unsigned char request_wire[CP_CAPTURE_FORMAT_BYTES];
    uint32_t source, destination, cookie, request_fnv1a32;
    uint32_t p_e0, p_f8;
    uint16_t p_104, p_106, p_108, p_114, p_116, p_118;
    uint32_t first_missing_address;
};

/* Exact AP/type5/402d/24B only. Returns SOURCE_BLOCKED after decoding into
 * caller-owned out; this negative result MUST NOT cause an ACK. Other negative
 * errno results leave out unchanged. All request bytes, including opaque ones,
 * are copied before decoding. FNV is a diagnostic hash of this copy, not a
 * semantic-consumption/readback claim. Input must remain readable/stable until
 * return and must not overlap any out storage. No shared state or borrowed view.
 */
int cp_capture_format_inspect(struct cp_capture_format_audit *out, uint32_t source,
                              uint32_t destination, const void *wire, size_t bytes);

/* House dispatch convention:0 delegates unrelated/default-off;1 refuses a
 * matching request with nonzero *result, leaving it wholly with the caller.
 * No reserve/release/predecessor guard is taken because admission is impossible.
 * Even a valid predecessor, inline free, send failure or fork cannot produce
 * a reply: no ownership/transport callbacks except size/source/record run.
 */
int native_cp_capture_format_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *io, int enabled, int *result);

/* Explicit diagnostic transport ONLY. Parent must enable the exact diagnostic
 * profile AND reserve its shared guard. predecessor_ready must inspect actual
 * same-PID original AP free rc0/sender identity for4073 and diagnostic302c, plus
 * unchanged clean all13 AND actual190-slot4063 staging request free rc0, with
 * no live/retained/inflight work.4063 staging remains semantically unverified.
 * No supplied ready flag, profile presence, or constructor alone closes this gate. All callbacks
 * run outside this owner's private mutex. No D018 is sent by this owner. */
struct native_cp_capture_format_diagnostic_guard {
    int (*reserve)(void);
    void (*release)(void);
    int (*predecessor_ready)(void);
};
struct native_cp_capture_format_diagnostic_snapshot {
    unsigned int initialized, diagnostic_only, no_publication, virtual_padding;
    unsigned int source_business_applied, current_known, source_dependency_closed;
    unsigned int generation, pending_complete, native_verified, native_cp, ee, frame, capture;
    unsigned int source_byte1_known, requests, busy, guard_held, faults;
    unsigned int queued, request_freed, reply_freed, clean_completion, ap_consumed;
    unsigned int destination, cookie, reply_free_destination, reply_free_source, reply_free_bytes;
    int owner_pid, allocate_rc, send_rc, request_free_rc, reply_free_rc;
    long sender_tid, waiter_tid;
    struct cp_capture_format_audit audit;
    unsigned char reply_wire[12], freed_reply_wire[12];
    void *retained_request, *live_reply, *retained_cleanup;
};
/* One-shot process-local constructor before inputs, no reset or state importer.
 * Copies inspector data into an owned audit before transport; SOURCE_BLOCKED
 * remains the inspector result. Reply is12B type1/402d/actual cookie/f000 with
 * explicit virtual byte1=0. Source constructs this status only AFTER mandatory
 * work: this diagnostic omits that work and claims no equivalent format success.
 * clean_completion/ap_consumed mean ONLY queued reply, exact original AP free
 * readback rc0 on sender thread, and original request free rc0. All source
 * business/current/dependency/generation/pending/native/EE/frame/capture stay0.
 * Refusal:1/nonzero result, original stays caller-owned. Admission:1/result0,
 * even on send/free failure, with retained pointers and sticky faults visible.
 * Allocation failure with no pointer is retryable; no broad opcode ACK exists. */
int native_cp_capture_format_diagnostic_owner_init(void);
int native_cp_capture_format_diagnostic_dispatch(unsigned int, void *, const struct full_imaging_io *,
    const struct native_cp_capture_format_diagnostic_guard *, int enabled, int *result);
int native_cp_capture_format_diagnostic_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result);
void native_cp_capture_format_diagnostic_snapshot(struct native_cp_capture_format_diagnostic_snapshot *);
#ifdef NATIVE_CP_CAPTURE_FORMAT_TEST
void native_cp_capture_format_diagnostic_test_hold_lock(void);
void native_cp_capture_format_diagnostic_test_drop_lock(void);
#endif
#endif
