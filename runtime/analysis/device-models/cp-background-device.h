/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_BACKGROUND_DEVICE_H
#define NATIVE_CP_BACKGROUND_DEVICE_H
#include <stdint.h>
#include "imaging-device.h"
#include "cp-cold-control.h"
#define NATIVE_CP_BACKGROUND_SID 0x90030001u
#define NATIVE_CP_CAPTURE_SID 0x90040193u
#define NATIVE_CP_FACE_SID 0x90060197u
/* type2/index7: CP7e9e78 stores the result recipient and mask, then CP7ec468
 * overwrites 7 known bytes of shared key6000c. Unknown baseline bytes remain
 * unknown; no real shared-settings consumer, result or hardware apply is claimed. */
struct native_cp_background_face_snapshot {
    uintptr_t request;
    unsigned int generation, retired, enabled, recipient, mask;
    unsigned char wire[12], shared_value[16], shared_known[16];
};
int native_cp_background_face_snapshot(struct native_cp_background_face_snapshot *);
/* Opt-in virtual-mode3/cold endpoint: type0/24B/3007 and source80020002
 * type5 parameters and reusable zero-reply request slots (4023 keeps its central obligation).
 * Type5/40df/16B consumes five CP359bf8 stores and queues the original 12B
 * type1/40df/token/f000 ACK; config snapshots expose the stores and dirty flag.
 * ACK queue/free is distinct from the unmodeled periodic apply and from capture.
 * Capture SID supports 4036/4039/40a5/406a/40de ingress retirement; existing specialized receivers stay separate.
 * Success consumes the request or retains it on release failure. Neither
 * claims hardware apply, central history, an AP completion or capture. Unknown commands and
 * channels delegate untouched to the original transport. Malformed recognized
 * requests refuse. All state below shares the cold owner's mutex and PID. */
/* The pending flag never clears without a proved apply consumer. cp302c's
 * independent history observer remains fail-closed on common APPLY. */
struct native_cp_background_parameter_snapshot {
    unsigned int parameter170, parameter_valid, apply_pending, generation;
    unsigned char wire[12];
};
/* Returns -1021 in an inherited process, preserving output; -1024 for NULL. */
int native_cp_background_parameter_snapshot(struct native_cp_background_parameter_snapshot *);
#define NATIVE_CP_BACKGROUND_PARAMETER_BYTES 0xd1cu
#define NATIVE_CP_BACKGROUND_WIRE_BYTES 184u
struct native_cp_background_config_snapshot {
    unsigned int generation, last_opcode, wire_bytes, apply_pending;
    /* CPVA 0x165a720 + offset; known marks overwritten bytes only. */
    unsigned char value[NATIVE_CP_BACKGROUND_PARAMETER_BYTES];
    unsigned char known[NATIVE_CP_BACKGROUND_PARAMETER_BYTES];
    unsigned char wire[NATIVE_CP_BACKGROUND_WIRE_BYTES];
    /* Exact relative updates; the original CP baseline is not imported. */
    uint32_t delta2ec;
    unsigned char deltab52;
    /* CP 0x8daaa4 (0x4022) increments param 0x7a6; shadow count only. */
    unsigned char count7a6;
};
int native_cp_background_config_snapshot(struct native_cp_background_config_snapshot *);
/* 404e request retirement is distinct from FC/0901 work, which remains missing.
 * pending tracks a live request only. deferred_count counts unexecuted ingresses;
 * first/latest wires are diagnostics, not a replay queue. No completion is emitted. */
struct native_cp_background_async_snapshot {
    uintptr_t request;
    unsigned int source, opcode, bytes, generation, pending;
    unsigned char wire[8];
    unsigned int retired, deferred_count;
    unsigned char first_wire[8];
};
int native_cp_background_async_snapshot(struct native_cp_background_async_snapshot *);
/* 4070 requests retire individually. Original worker/bracketing/AP1010 remain
 * unexecuted and are counted by deferred_count; freeing is never completion.
 * pending is a live request, not the outstanding semantic work count. */
struct native_cp_background_4070_snapshot {
    uintptr_t request;
    unsigned int source, opcode, bytes, generation, pending;
    unsigned char wire[12];
    unsigned int retired, deferred_count;
    unsigned char first_wire[12];
};
int native_cp_background_4070_snapshot(struct native_cp_background_4070_snapshot *);
/* Exact first/latest wire and monotonic request generation/retired counters.
 * Each accepted request is released; failure preserves its pointer and sticky fault.
 * Except 4023's proved stores, this is diagnostic retirement, not a CP handler.
 * deferred_count counts missing semantic executions, never a runnable event queue.
 * Type0/301a/12B records preview_mode=request[8] and the missing central8102
 * obligation; no AP reply, mode application or internal event delivery is claimed.
 * All accepted wires are also logged when record is provided. 4023's separate
 * central obligation below remains fail-closed. Other capture opcodes delegate. */
struct native_cp_background_remainder_snapshot {
    uintptr_t request;
    unsigned int destination, source, opcode, bytes, generation, pending;
    unsigned char wire[32];
    unsigned int retired, deferred_count;
    unsigned char first_wire[32];
    /* 4028 decoded latest input only; gate/CP baseline are unbound, no updates. */
    int signed_delta;
    unsigned int mode, parameter2e4, parameter2e6;
};
/* -1024 for NULL/unknown destination+opcode; -1021 in an inherited process. */
int native_cp_background_remainder_snapshot(unsigned int destination,unsigned int opcode,
                                           struct native_cp_background_remainder_snapshot *);
/* 4023: consume proved P688/P720 stores and common dirty, retire each request.
 * One independent copied central8306 obligation survives request release:
 * central_pending=1 conditional on saved unknown inputs; =2 proved required;
 * =0 no obligation. No central actor, config+2db input or apply consumer is bound.
 * Another request that might create a central event refuses while this slot is
 * occupied. Same-value reissues cannot emit8306 and may retire normally.
 * central_wire is a 32B template: b1fe10's unbound word@8 is zero storage,
 * NOT a valid dispatch prefix; never deliver this template as an executable event.
 * counter_delta counts only proved 0<->1 changes modulo256; unknown initial
 * crossing is retained separately, never converted to a zero CP baseline.
 * No FC CancelTracking/0901, AP ACK, timeout completion or claim of full handler.
 * Only actual release rc0 increments retired. Snapshot is read-only, PID guarded. */
struct native_cp_background_4023_snapshot {
    unsigned int generation, retired, parameter688, parameter720, parameter_valid;
    unsigned int central_pending, central_generation;
    unsigned int central_old688, central_old688_known;
    unsigned int central_p134, central_p134_known, central_p198, central_p198_known;
    unsigned int clear2ba_pending, initial_transition_unknown;
    unsigned char counter_delta, wire[12], central_request[12], central_wire[32];
};
int native_cp_background_4023_snapshot(struct native_cp_background_4023_snapshot *);
int native_cp_background_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int native_cp_background_release(unsigned int,void *,int (*)(unsigned int,void *),
                                 void (*)(const char *,const char *),int *);
/* Optional constructor-time observer of this owner's actual 3007 reply free.
 * Other synchronous ACKs (40df) must not advance/invalidate the 3007 lifecycle.
 * Invoked outside both model locks only after send returned successfully and
 * real free returned 0. Inline frees while send is unresolved are not promoted.
 * wire is the saved 12B payload, never a dereference after release. */
typedef void (*native_cp_background_free_observer)(unsigned int destination,
    const unsigned char wire[12]);
int native_cp_background_bind_free_observer(native_cp_background_free_observer);
/* Shared real backing for future finite image consumers; VM/process lifetime.
 * Never substitute an independent empty bank when a consumer has allocations. */
struct cp_sync_resources *native_cp_background_resources(void);
#endif
