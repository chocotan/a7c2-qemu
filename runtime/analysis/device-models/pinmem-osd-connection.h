/* SPDX-License-Identifier: MIT */
#ifndef FULL_PINMEM_OSD_CONNECTION_H
#define FULL_PINMEM_OSD_CONNECTION_H
#include "scalar-connection.h"
#include "osd-pin-format.h"
#define FULL_PINMEM_OSD_CONNECTION_PROFILE "virtual-pinmem-osd0-osdpin-if0-ssos-v1"
/* Closed metadata connection only. E1700 is a separate, explicitly virtual
 * 16x256-byte pool. All creator/consumer references persist after Connect;
 * Disconnect, active rows, graphics/GPE, CP page attributes and frames are
 * unsupported. No original CP task or allocator-capacity claim is made. */
struct full_pinmem_osd_resource {
    unsigned int handle, tag, used, known_bytes, creator_side, owners, opens;
    struct full_osd_mapping mapping;
    unsigned long long bytes_fnv, known_fnv;
};
struct full_pinmem_osd_connection_snapshot {
    int owner_pid;
    unsigned int initialized, started, busy, native_guarded, guard_held, faults;
    unsigned int requests, unadmitted_count, connections, queued, clean_completion, ap_consumed;
    unsigned int request_freed, reply_freed, releasing_reply, reply_destination, retained_messages;
    unsigned int native_reply_frees, waiter_frees, source_state, peer_state;
    unsigned int context_kind, phase, wait_primary, wait_secondary, keep_pending;
    unsigned int pending_event6, event6_enqueued, event6_consumed, event6_inflight;
    unsigned int event6_token, event6_token_verified, event6_peer_verified;
    unsigned int dmm_requests, dmm_replies, allocations, shares, opens, reference_readbacks;
    unsigned int peer_notifications, source_notifications, notifications_consumed, consumer_reads;
    unsigned int canonical_references, history_preserved, metadata_ready, readiness_post_checks;
    unsigned int source_post_updated, selected_tag100, selected_backing_count, selected_cached_count;
    unsigned int diagnostics_optional_skipped, gpe_ready, frames_verified, capture_verified;
    unsigned int original_CP_executed, original_CP_pages_verified, original_allocator_capacity_verified;
    unsigned char saved_request[64], event6_parameter[12];
    unsigned long long saved_request_fnv, event6_parameter_fnv;
    void *event6_answer, *event6_body, *live_reply, *retained_request, *retained_cleanup;
    /* Banks key0, tag101, tag100, tag102; these store readback evidence only.
     * Buffer bytes and reference counts remain authoritative in osd-buffer-owner. */
    struct full_pinmem_osd_resource resources[4][4];
    struct full_osd_format_plane source_outputs[4];
    unsigned short local_pairs[8][2];
    unsigned char source_row_enabled[5], source_row_known[5];
    struct full_osd_format_state format;
    struct full_osd_pool_snapshot pool;
};
int full_pinmem_osd_connection_owner_init(void);
int full_pinmem_osd_connection_native_dispatch(unsigned int, void *, const struct full_imaging_io *, const struct full_adf_proc_guard *, int, int *);
int full_pinmem_osd_connection_dispatch(unsigned int, void *, const struct full_imaging_io *, int, int *);
int full_pinmem_osd_connection_release(unsigned int, void *, int (*)(unsigned int, void *), void (*)(const char *, const char *), int *);
void full_pinmem_osd_connection_snapshot(struct full_pinmem_osd_connection_snapshot *);
#if defined(FULL_PIN_CONNECTION_TEST) || defined(FULL_VEF_TEST)
void full_pinmem_osd_connection_test_event_corrupt(unsigned int);
void full_pinmem_osd_connection_test_row(unsigned int, unsigned int, unsigned int);
#endif
#endif
