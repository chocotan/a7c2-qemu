/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_H
#define NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_H
#include "imaging-device.h"
#include <stdint.h>

#define NATIVE_CP_MOVIE_FORMAT_SID UINT32_C(0x90030001)
#define FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE "diagnostic-cp-movie-format-v1"
#define CP_MOVIE_FORMAT_SOURCE_BLOCKED (-1024)
#define CP_MOVIE_FORMAT_REQUEST_BYTES 20u
#define CP_MOVIE_FORMAT_KNOWN_MASK 0x7fu

/* Parent reserves the shared guard, then requires SAME PID and clean all13,
 * 302c/4073/402d/4014/4057 and actual409d original AP/request free rc0 pairs,
 * each pair on its own sender. Current4000 sender MUST equal409d sender.
 * No retained/live/inflight work may exist. Parent gates subsequent4072/3012
 * on this owner's actual original AP free, without changing the EE owner.
 * All guard and IO callbacks run outside this owner's private mutex.
 * Host guard stubs test transport only, never native readiness/business state. */
struct native_cp_movie_format_diagnostic_guard {
    int (*reserve)(void);
    void (*release)(void);
    int (*predecessor_ready)(void);
};
struct native_cp_movie_format_diagnostic_snapshot {
    unsigned int initialized, diagnostic_only, no_publication, virtual_padding;
    unsigned int source_business_applied, current_known, source_dependency_closed;
    unsigned int business_applied, source_dependencies_closed, published, configured;
    unsigned int generation, pending_complete, native_verified, native_cp, ee, frame, capture;
    unsigned int opcode, supported, source_byte1_known, request_bytes;
    unsigned int attempts, requests, busy, guard_held, faults;
    unsigned int queued, request_freed, reply_freed, clean_completion, ap_consumed;
    unsigned int source, request_destination, destination, cookie;
    uint32_t request_fnv1a32;
    /* Audit-only indices: format@8, raw_rate_a@9, raw_rate_b@10,
     * LE32 conditional_state@12, byte16, byte17, byte18. NOT seven adjacent
     * bytes. No converted-rate or conditional-state application is claimed.
     * known_mask/field_mask=0x7f prove only these diagnostic copies/readback. */
    unsigned int known_field_mask, virtual_field_mask, virtual_fields_readback, virtual_fields_consumed;
    uint32_t virtual_fields[7], virtual_readback[7];
    unsigned int reply_free_destination, reply_free_source, reply_free_bytes;
    int owner_pid, allocate_rc, send_rc, request_free_rc, reply_free_rc;
    long sender_tid, waiter_tid;
    unsigned char request_wire[CP_MOVIE_FORMAT_REQUEST_BYTES];
    unsigned char reply_wire[12], freed_reply_wire[12];
    void *retained_request, *live_reply, *retained_cleanup;
};
/* Construct once BEFORE inputs/profile admission; no reset/import/history writes.
 * Exact type5/byte1=0/opcode4000/20B/AP source and body+8..19
 * 050100000000000000000100 ONLY; any opaque cookie+4 is echoed unchanged.
 * Default-off/unrelated returns0 untouched. Recognizable4000 with wrong type,
 * size/source/body returns1/BLOCKED with request caller-owned. One attempt after
 * reserve+predecessor admission; failures are sticky even for null allocation.
 * Admission returns1/result0 despite later send/free failure, retaining owned
 * pointers for real cleanup. Separate12B type1/4000/cookie/f000, source CP,
 * byte1 UNKNOWN in source (explicit virtual0). Completion means ONLY queued,
 * exact original AP free rc0 on original sender, and original request free rc0.
 * All business/dependency/configured/published/generation/native/EE/frame/capture
 * flags stay0;3003/3000/3030 data replies and4072 are never acknowledged here. */
int native_cp_movie_format_diagnostic_owner_init(void);
int native_cp_movie_format_diagnostic_dispatch(unsigned int, void *, const struct full_imaging_io *,
    const struct native_cp_movie_format_diagnostic_guard *, int enabled, int *result);
int native_cp_movie_format_diagnostic_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result);
void native_cp_movie_format_diagnostic_snapshot(struct native_cp_movie_format_diagnostic_snapshot *);
#ifdef NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_TEST
void native_cp_movie_format_diagnostic_test_hold_lock(void);
void native_cp_movie_format_diagnostic_test_drop_lock(void);
#endif
#endif
