/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_MPR_CODEC_H
#define FUNCTIONAL_MPR_CODEC_H
#include <stddef.h>
#include <stdint.h>
#include "device-models/imaging-device.h"

#define FUNCTIONAL_MPR_CODEC_LIBRARY_SHA256 \
 "4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9"
#define FUNCTIONAL_MPR_CODEC_DESTINATION UINT32_C(0x8055001f)
#define FUNCTIONAL_MPR_CODEC_SOURCE UINT32_C(0x80c70047)

enum functional_mpr_codec_state {
    FMPR_CLOSED, FMPR_OPEN, FMPR_RECORDING, FMPR_DRAINED, FMPR_FAULT
};
struct functional_mpr_codec_snapshot {
    uint32_t state, pending, worker_live, physical_asic_verified, owned_replies;
    uint32_t original_cp_verified, capture_verified;
    int last_error, last_release_error;
    uint64_t epoch, model_instance, native_start_fnv;
    uint64_t accepted, backend_frames, backend_packet_bytes;
    uint64_t es_bytes_readback, pi_published, events_sent, events_received;
    uint64_t original_slots_returned, backpressure, failures;
    uint64_t es_capacity, es_used;
    uint64_t frames_published, memory_generation; /* Normal PI commits; current open generation. */
    uint32_t owned_memory_leases; /* Includes failed releases retained for retry. */
    int last_memory_release_error;
};

/* Called only by explicit virtual-functional-camera-v1 setup, never a
 * constructor. All entry points reject forked owners before taking locks. */
int functional_mpr_codec_owner_init(void);
/* base is dladdr-derived runtime libmpr load bias. hash must be the hash of
 * that actual mapped library. No file BSS defaults or foreign addresses. */
int functional_mpr_codec_bind(uintptr_t base, const char *sha256);
/* 0=delegate. Accepted work owns an immutable copy before releasing request.
 * FUNCTIONAL_MPR_REQUEST retains all 48 bytes, origin and open generation.
 * A handled validation error retains the request and returns negative errno
 * in result. Real replies use original queued MPR receiver transport. */
int functional_mpr_codec_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *, int enabled, int *result);
/* Observe immediately after original receive; does not consume the message.
 * First verified receive logs FUNCTIONAL_MPR_EVENT_RECEIVED with copied full
 * body, original request association and actual receiver PID/TID. PI_PUBLISH
 * receipts show producer commits; only validated original shared-read cursor
 * advances emit per-ticket PI_RETURN receipts. Neither proves Fsys completion. */
int functional_mpr_codec_observe_received(unsigned int destination, void *reply,
    const struct full_imaging_io *);
/* Hook original message free; 0=not ours, 1=handled, exact release rc in result.
 * io is the same original transport used by dispatch. Successful actual event
 * free logs FUNCTIONAL_MPR_EVENT_FREE; send success alone is not consumption. */
int functional_mpr_codec_release_if_owned(unsigned int destination, void *reply,
    const struct full_imaging_io *, int *result);
int functional_mpr_codec_snapshot(struct functional_mpr_codec_snapshot *);
/* Requires completed original Close (CLOSED, no pending/working command).
 * An active clip returns EBUSY without stop/cancel; this is never an original
 * Stop/mux/Fsys drain substitute. Parent also waits for Close receive/free and
 * original Fsys completion. Joins workers; no callback under adapter lock. */
int functional_mpr_codec_shutdown(void);
#endif
