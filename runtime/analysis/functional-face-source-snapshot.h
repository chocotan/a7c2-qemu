/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_FACE_SOURCE_SNAPSHOT_H
#define FUNCTIONAL_FACE_SOURCE_SNAPSHOT_H
#include "functional-face-transfer.h"
#include "functional-face-ap-observer.h"
#include "functional-face-proc.h"
#include "functional-face-source-snapshot-abi.h"
#include "functional-camera-bridge.h"

#define FUNCTIONAL_FACE_SOURCE_SNAPSHOT_MODEL "paused-source-snapshot-v1"
/* Trusted parent supplies facts saved at original birth and authenticates the
 * live original API40 caller/frame. No epoch or native kernel pointer is minted
 * here. This provider implements the explicit functional image-bus model only. */
struct functional_face_source_snapshot_config {
    struct functional_face_ap_span saved_source;
    struct functional_face_ap_birth birth;
    const struct functional_face_ap_observer *observer;
    uint32_t relation, generation, extent_id;
    struct functional_face_proc_unit born;
    /* Must read actual current proc metadata twice under the parent's proc
     * reader lock. No fallback from a cached birth/current raw handle. */
    int (*read_current_metadata)(void *, unsigned int unit, unsigned int full_handle,
        struct functional_face_proc_unit *);
    void *metadata_context;
    struct functional_face_dmm_descriptor destination;
    uint64_t producer_owner;
    int owner_pid;
    int64_t owner_tid;
    uintptr_t frame, api_pointer;
    unsigned char raw_api40[40], ap_descriptor[8], cp_descriptor[8];
    int original_caller_verified;
    int (*original_command)(void *, unsigned int op, unsigned int unit, unsigned int handle,
        struct functional_face_ap_observer *);
    void *command_context;
#ifdef FCAM_HOST_TEST
    /* Synthetic entries and owned-buffer copies are HOST TEST evidence only. */
    long (*read_pagemap)(void *, uintptr_t page, uint64_t *raw_entry);
    int (*bridge_call)(void *, const struct fcam_native_origin *, uint32_t,
        const void *, size_t, void *, size_t, struct fcam_bridge_result *);
    void *test_context;
#endif
};
/* Zero initialized, caller owned, same PID/TID, one attempt. Keep the complete
 * context, original frame and IO context after a retained fault. Page arrays
 * are observations, not native pin capabilities or forever-pinned mappings. */
struct functional_face_source_snapshot {
    _Atomic unsigned int busy;
    uint32_t initialized, attempted, claimed, faulted, uncertain, provider_may_retain;
    uint32_t owner_live, open_live, snapshot_live, close_attempted, free_attempted, baseline_opens;
    uint32_t cp_count, sdk_count, host_disjoint_verified, bridge_complete;
    /* These claims stay false throughout this functional provider. */
    uint32_t original_global_writer_verified, kernel_atomic_snapshot_verified, physical_asic_verified;
    int last_error, cleanup_error, pagemap_error, pagemap_close_error;
    uint64_t last_sequence, physical, snapshot_digest;
    size_t bytes_read;
    unsigned char *owned_snapshot;
    struct functional_face_source_snapshot_config config;
    struct functional_face_ap_observer operations[4]; /* actual 21,24,25,23 */
    struct functional_face_proc_unit metadata[6]; /* pre21,post21,post24,pre-cleanup,post25,post23 */
    uint32_t metadata_calls;
    struct functional_face_ap_borrow token;
    struct fcam_bridge_result bridge_result;
    uint64_t cp_pages[FCAM_FACE_SNAPSHOT_MAX_CP_PAGES], sdk_pages[FCAM_FACE_SNAPSHOT_MAX_SDK_PAGES];
    unsigned char packet[FCAM_FACE_SNAPSHOT_MAX_INPUT_BYTES];
    size_t packet_bytes;
};
/* No IO/default activation. Failure leaves ctx and out unchanged. acquire
 * failure returns no caller token; claimed/uncertain/may_retain describe the
 * provider's retained original resources. Never fallback or retry a claim. */
int functional_face_source_snapshot_init(struct functional_face_source_snapshot *,
    const struct functional_face_source_snapshot_config *, struct functional_face_ap_provider *);
#endif
