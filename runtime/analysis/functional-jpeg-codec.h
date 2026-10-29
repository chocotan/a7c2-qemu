/* SPDX-License-Identifier: MIT */
/* Implementation: gpt-6.1-sol, thinking=max; 2026-10-28 functional profile. */
#ifndef FUNCTIONAL_JPEG_CODEC_H
#define FUNCTIONAL_JPEG_CODEC_H
#include <stddef.h>
#include <stdint.h>
#include "device-models/imaging-device.h"
#include "functional-mpr-memory.h"

#define FUNCTIONAL_JPEG_CODEC_LIBRARY_SHA256 \
 "676197567dbbefa54e08f528968efc6ca2aaffe8bee3ee3eae8164382ed5a7e5"
#define FUNCTIONAL_JPEG_CODEC_SID UINT32_C(0x82830752)
#define FUNCTIONAL_JPEG_CODEC_EXEC_SYMBOL \
 "_ZN34ExecCmd_SDF_EncodeJpeg_Without_Pin7ExecCmdEPKh"
#define FUNCTIONAL_JPEG_CODEC_RES_SYMBOL \
 "_ZN34ExecCmd_SDF_EncodeJpeg_Without_Pin6ResCmdEPKht"

#define FUNCTIONAL_JPEG_CODEC_MAIN_EXEC_SYMBOL \
 "_ZN26ExecCmd_SDF_EncodeJpegMain7ExecCmdEPKh"
#define FUNCTIONAL_JPEG_CODEC_MAIN_RES_SYMBOL \
 "_ZN26ExecCmd_SDF_EncodeJpegMain6ResCmdEPKht"
#define FUNCTIONAL_JPEG_CODEC_COMP_EXEC_SYMBOL \
 "_ZN30ExecCmd_SDF_EncodeJpegMainComp7ExecCmdEPKh"
#define FUNCTIONAL_JPEG_CODEC_COMP_RES_SYMBOL \
 "_ZN30ExecCmd_SDF_EncodeJpegMainComp6ResCmdEPKht"

struct functional_jpeg_codec_snapshot {
    uint32_t enabled, pending, working, worker_live;
    uint32_t physical_asic_compatible, capture_verified;
    int last_error, last_release_error;
    uint64_t sequence, model_instance, accepted, encoded, bytes_readback;
    uint64_t queued, received, native_ack, native_done, rejected;
    uintptr_t original_base, original_exec;
};

/* Explicit virtual-functional-camera-v1 local setup only. The bridge must be
 * initialized before the first original encode request; setup binds the SDK
 * and waits without calling the model. Needs a current owned SDS resolver.
 * No constructor, key/timer trigger, media
 * writer, business-ready store, guest patch, or physical-ASIC claim. Callback
 * receives bounded byte/lease receipts outside adapter locks; it may query
 * snapshot(). Original 104-byte requests and 16-byte responses are copied;
 * media bodies are identified by actual leased readback ranges/FNV, never hex. */
int functional_jpeg_codec_enable(void (*record)(const char *, const char *));
/* Parent calls from the real OSAL send interception, before legacy emulation.
 * Only an actual original Without_Pin or Main ExecCmd on this thread can claim a
 * request. Main selectors 0/1/2 share this worker; Main ACK is nonterminal and
 * only its associated original MainComp Exec/Res can consume DONE. Receipts add
 * kind=without-pin|main, selector and comp_object without changing snapshot ABI.
 * 0=delegate exactly. 1=handled, exact transport result in *result.
 * Accepted requests are copied and released once via original OSAL. Rejected
 * requests remain the original sender's responsibility. */
int functional_jpeg_codec_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *, int *result);
/* Call immediately after a successful original OSAL receive and before the
 * original SDK decodes/frees its packet. Checks source/destination and the exact
 * source-defined 16-byte body. Observation never consumes or modifies it. */
int functional_jpeg_codec_observe_received(unsigned int destination, void *reply,
    const struct full_imaging_io *);
/* Call only after the real OSAL free, with its unchanged result. Never reads or
 * frees pointer. 1=matched success, negative=matched failure/owner error,
 * 0=unclaimed (including duplicate/stale calls). Failed frees are sticky and keep
 * the output lease owned. Preserves caller errno; PID guard precedes all locks. */
int functional_jpeg_codec_observe_freed(unsigned int destination, void *pointer, int actual_rc);
int functional_jpeg_codec_snapshot(struct functional_jpeg_codec_snapshot *);
/* Refuses live requests/replies/leases. Parent drains the original receiver and
 * MPR/Fsys first; a failed queued send remains pending and is never called clean.
 * All APIs fail with -ECHILD before locks in a fork of the enabled owner. */
int functional_jpeg_codec_shutdown(void);

/* Integration dependency owned by functional-mpr-memory. The C implementation
 * keeps its weak import for unavailable-provider refusal; the current provider
 * supplies a strong definition. Resolve the CURRENT original
 * SDS, not a pointer cast or an unregistered handle. Offset includes the native
 * stream-position field. Return a real acquired lease covering exactly bytes;
 * unknown/stale handles, overflow, foreign aliases and retired generations fail.
 * Existing memory_write()/validate()/release() govern serialized output through
 * native ResCmd. Failed releases stay owned and block shutdown/reuse.
 * This declaration does not implement an SDS binding. */
int functional_mpr_memory_acquire_sds(uint32_t type, uint32_t handle,
    uint32_t offset, size_t bytes, struct functional_mpr_memory_lease *);
#endif
