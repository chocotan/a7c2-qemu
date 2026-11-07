/* SPDX-License-Identifier: MIT */
#ifndef CAPTURE_SAVE_H
#define CAPTURE_SAVE_H
#include "capture-output-memory.h"
#include "../../runtime/analysis/fsys-write-trace.h"
/* Observation stages emitted only by existing real Fsys passthrough wrappers.
 * Caller holds the capture owner's mutex. No API performs I/O, publishes a
 * successful capture or replaces original submit/callback/finished behavior. */
enum capture_save_event {
    CAPTURE_SAVE_SUBMIT=1,CAPTURE_SAVE_CALLBACK,CAPTURE_SAVE_CALLBACK_RETURN,
    CAPTURE_SAVE_FINISHED,CAPTURE_SAVE_READBACK,CAPTURE_SAVE_COVERAGE
};
struct capture_save;
struct capture_save_info {
    int owner_pid,first_error;
    unsigned token,submitted,callback_seen,callback_returned,finished,readback,coverage;
    unsigned write_readback_verified;
    uint64_t generation,frame_token,request_fnv1a64,main_fnv,bytes,file_fnv,cookie,path_fnv;
};
int capture_save_prepare(struct capture_output_memory *,uint64_t actual_callback_address,
    struct capture_save **out);
/* 0=foreign request (no matching actual Main address), 1=accepted same-job write,
 * negative=matching but invalid/stale/ambiguous. All contributing spans must be
 * within this output owner and include the complete unchanged Main exactly once
 * as the final contribution; unknown/copied buffers are never inferred equal. */
int capture_save_match(struct capture_save *,unsigned token,const struct fsys_write_layout *,
    const uint64_t actual_source_hashes[FSYS_WRITE_AREAS],const unsigned readable[FSYS_WRITE_AREAS]);
/* Token0 is reserved for whole-trace coverage, using bytes as actual record count.
 * Complete means actual full copied result/work input, EOF+close or coverage0,
 * as appropriate. No caller-supplied boolean alone creates a matching write. */
int capture_save_observe(struct capture_save *,unsigned token,enum capture_save_event,
    int actual_rc,unsigned complete,uint64_t bytes,uint64_t hash);
int capture_save_info(struct capture_save *,struct capture_save_info *out);
/* Normal close requires full original lifecycle/readback/coverage and no native
 * consumers. No implicit cancel, failed-write success or unmapping live data. */
int capture_save_close(struct capture_save *);
/* Optional strong hooks supplied by the production capture owner. The media
 * preload imports them weakly; absent capture owner preserves normal tracing. */
void functional_capture_fsys_begin(unsigned,const struct fsys_write_layout *,
    const uint64_t [FSYS_WRITE_AREAS],const unsigned [FSYS_WRITE_AREAS]);
void functional_capture_fsys_event(unsigned,enum capture_save_event,int,unsigned,uint64_t,uint64_t);
#endif
