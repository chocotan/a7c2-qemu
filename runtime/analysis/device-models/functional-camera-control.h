/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_FUNCTIONAL_CAMERA_CONTROL_H
#define NATIVE_FUNCTIONAL_CAMERA_CONTROL_H
#include "cp-state-publication.h"
#include "../functional-camera-bridge.h"

#define FUNCTIONAL_CAMERA_CONTROL_SID NATIVE_CP_STATE_PUBLICATION_SID
#define FUNCTIONAL_CAMERA_CONTROL_AP NATIVE_CP_STATE_PUBLICATION_AP
#define FUNCTIONAL_CAMERA_CONTROL_LEASES CP_STATE_PUBLICATION_LEASES
#define FUNCTIONAL_CAMERA_CONTROL_BLOCKED (-ENODATA)

enum functional_camera_control_phase {
    FUNCTIONAL_CAMERA_CONTROL_UNKNOWN = 0,
    FUNCTIONAL_CAMERA_CONTROL_PROBING,
    FUNCTIONAL_CAMERA_CONTROL_INITIALIZED,
    FUNCTIONAL_CAMERA_CONTROL_START_QUEUED,
    FUNCTIONAL_CAMERA_CONTROL_START_CONSUMED,
    FUNCTIONAL_CAMERA_CONTROL_STATE_PROBING,
    FUNCTIONAL_CAMERA_CONTROL_PUBLICATION_COPIED,
    FUNCTIONAL_CAMERA_CONTROL_NOTICE_QUEUED,
    FUNCTIONAL_CAMERA_CONTROL_NOTICE_RECEIVED,
    FUNCTIONAL_CAMERA_CONTROL_NOTICE_CONSUMED,
    FUNCTIONAL_CAMERA_CONTROL_FAULT,
    FUNCTIONAL_CAMERA_CONTROL_MODE_ACK_CONSUMED
};
struct native_functional_camera_control_snapshot {
    int owner_pid;
    unsigned int initialized, busy, guard_held, faults, phase;
    unsigned int start_requests, start_complete, mode1_requests, mode1_complete;
    unsigned int model_initialized, business_ready, functional_model;
    unsigned int original_cp, physical_asic_verified, ee, frame, capture;
    unsigned int probe_attempts, probe_successes, probe_refusals;
    int bridge_rc, probe_rc;
    uint64_t probe_run_id, init_run_id, state_run_id;
    uint64_t model_instance, config_generation, rendered, frame_generation;
    struct fcam_native_origin last_origin;
    unsigned char model_state[FCAM_STATE_BYTES];
    unsigned int start_defined_mask, start_original_known_mask;
    unsigned int full_layout_copied, full_model_defined, full_original_source_known;
    unsigned int publication_copied, notification_queued;
    unsigned int notification_received, notification_ap_consumed;
    unsigned int shadow_generation, published_generation;
    unsigned int defined_blocks, projected_blocks, zero_policy_blocks;
    unsigned char block_defined[CP_FULL_STATE_SNAPSHOT_BLOCKS];
    unsigned char block_projected[CP_FULL_STATE_SNAPSHOT_BLOCKS];
    struct native_cp_state_publication_lease leases[FUNCTIONAL_CAMERA_CONTROL_LEASES];
    /* mode1_requests is lifetime selector1 acceptance; mode1_complete is its latest cycle.
     * notification_* and publication_* describe the last full publication,
     * including during an ACK-only cycle. No ACK-only publication is counted. */
    unsigned int notification_mode, mode1_ack_only, mode1_cycle_generation;
    unsigned int mode1_cycles_completed, mode1_ack_only_requests;
    unsigned int mode1_ack_only_completed, full_notifications_queued, full_notifications_consumed;
    uint64_t mode1_cycle_id, lease_cycle_id[FUNCTIONAL_CAMERA_CONTROL_LEASES];
    /* Latest full copy's one-frame-period software capability, not AP/flash completion. */
    unsigned int xsync_defined, xsync_source_fps, xsync_word, xsync_half;
    uint64_t xsync_source_generation;
    /* Opaque selectors share leases; mode1_* remains selector1-only history. */
    uint64_t mode_cycle_id;
    unsigned int mode_selector, mode_cycle_generation, mode_complete;
    unsigned int mode0_requests, mode0_complete, mode0_cycles_completed;
};
/* Local setup only: no broker/host operation, reset, readiness import or RPC.
 * Explicit functional profile only. Main still supplies its complete same-
 * process predecessor cohort (including the real 4072/earlier original frees).
 * Exact 3003/3000 start performs live INIT with the original request origin;
 * exact 4073 selector1 performs live STATE only after the original start ACK free.
 * Post-start selector0 is an explicit software state-refresh policy, not STOP,
 * poweroff or original CP mode-off. It requires a completed selector1 cycle and
 * all old leases retired, then real STATE and a newer-generation full notice.
 * Cold selector0 delegates to its finite boot owner; same-generation selector0
 * refuses without changing core generation/shadow. Selector2+ still delegates.
 * Both selectors save/read back the opaque selector in the owned request wire.
 * mode_cycle_id is the shared lease epoch; mode1_cycle_id/generation and all
 * mode1 counters/completion retain the most recent selector1 facts. mode0_*
 * tracks selector0 independently. mode_complete describes the current cycle.
 * Main consumers requiring current retirement must also check mode_complete;
 * a prior mode1_complete remains true while selector0's ACK is still live.
 * Repeat selector1 requires all previous leases retired. A newer actual generation
 * publishes a full notice; an already AP-consumed generation needs only ACK.
 * Missing/invalid model data returns handled=1/result<0, caller retains request.
 * After successful allocations, accepted requests are retained until real free;
 * result=0 then means owner takeover, never AP consumption or capture success.
 * Other modes/commands return0 for their existing owners. */
int native_functional_camera_control_owner_init(void);
int native_functional_camera_control_dispatch(unsigned int, void *,
    const struct full_imaging_io *, const struct native_cp_state_publication_guard *,
    int enabled, int *result);
/* Observe ONLY an actual original receive. Exact full pointer/source/bytes are
 * checked before its receiver may free a notice. The original imaging worker
 * may receive an ACK for a different requesting thread; ACKs must still be
 * freed by that original sender. Shadow advances only after the observed full
 * notification's real free on its receiving thread returns0. */
int native_functional_camera_control_observe_receive(unsigned int, void *, unsigned int, unsigned int);
int native_functional_camera_control_release(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result);
/* Repeated mode leases require the ticket captured for that actual transport
 * event, from lease_cycle_id in the snapshot. Never look up a fresh ticket for
 * an old event. Unqualified hooks accept only startup/first-mode leases; later
 * mode leases return -ESTALE without touching the owned pointer or real free. */
int native_functional_camera_control_observe_receive_cycle(unsigned int, void *, unsigned int, unsigned int, uint64_t);
int native_functional_camera_control_release_cycle(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result, uint64_t);
void native_functional_camera_control_snapshot(struct native_functional_camera_control_snapshot *);
/* Independent post-initialization functional bank. The original one-shot
 * parameter/P/S owners and every control snapshot field remain untouched. */
#define FUNCTIONAL_CAMERA_PARAMETER_POLICY "full-190-slot-bank-fps4151-v1"
struct native_functional_camera_parameter_snapshot {
    int owner_pid, model_rc, free_rc, error;
    unsigned int initialized, busy, guard_held, faults;
    unsigned int model_called, model_committed, verified, owned, releasing, request_freed;
    long sender_tid, free_tid;
    void *retained_request, *request_pointer;
    uint64_t transaction, commits, released, last_bank_generation;
    uint64_t model_instance, bank_generation, before_config_generation, config_generation;
    uint32_t fps;
    struct fcam_native_origin origin;
    struct fcam_bridge_result before_result, bank_result, after_result;
    unsigned char request[FCAM_CP_PARAMETER_BANK_BYTES];
    unsigned char before_state[FCAM_STATE_BYTES], after_state[FCAM_STATE_BYTES];
    unsigned char receipt[FCAM_CP_PARAMETER_BANK_RESULT_BYTES];
};
/* Local initialization only; Main selects this owner only after its first
 * strict batch has really staged/consumed/freed. Cold start delegates. Live
 * STATE -> complete OP20 bank/readback -> live STATE precede ownership/free.
 * Source, metadata, full bytes, same sender, all old leases and parent guard
 * are rechecked. Cookie is opaque data, never a replay/monotonicity ticket.
 * No ACK/notification/allocation, old model-state cache/shadow update, or
 * original Sony unknown-slot semantics are supplied by this software policy.
 * Pre-takeover failure returns a negative result with caller still owning
 * the request. Any uncertain/failed OP20 latches a fault and cannot be retried.
 * After takeover result0 means owner retention, including a failed real free. */
int native_functional_camera_parameter_owner_init(void);
int native_functional_camera_parameter_dispatch(unsigned int, void *,
    const struct full_imaging_io *, const struct native_cp_state_publication_guard *,
    int enabled, int *result);
void native_functional_camera_parameter_snapshot(struct native_functional_camera_parameter_snapshot *);
/* Cleanup only for an actual retained original request. Capture transaction
 * when the event is created; never look up a fresh ticket for a stale pointer.
 * The completed request identity rejects duplicate frees with a captured ticket;
 * Main invalidates that ticket on an actual new allocation reusing the pointer.
 * A successful cleanup after free failure does not clear the sticky fault. */
int native_functional_camera_parameter_release(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result, uint64_t transaction);
/* Independent post-bank finite mode0; no initial strict409d history is imported. */
#define FUNCTIONAL_CAMERA_CRANK_POLICY "active-config-crank-mode0-v1"
#define FUNCTIONAL_CAMERA_CRANK_REQUEST_BYTES 12u
#define FUNCTIONAL_CAMERA_CRANK_RESULT_BYTES 208u
#define FUNCTIONAL_CAMERA_CRANK_REPLY_BYTES 12u
/* Supplied only by an actual successful original receive, with the transaction
 * captured at the send/dispatch event. NULL in release means a real free. */
struct native_functional_camera_crank_receive {
    unsigned int source, bytes;
};
struct native_functional_camera_crank_snapshot {
    int owner_pid, before_rc, model_rc, after_rc, allocate_rc, send_rc;
    int request_free_rc, reply_free_rc, receive_rc, error;
    unsigned int initialized, busy, guard_held, faults;
    unsigned int model_called, model_committed, verified, owned, complete;
    unsigned int request_releasing, request_freed, reply_releasing, reply_inspecting;
    unsigned int reply_allocated, reply_valid, reply_alias, reply_send_started, send_inflight;
    unsigned int reply_queued, reply_received, reply_freed, reply_cleanup_freed, reply_consumed;
    long sender_tid, receiver_tid, request_free_tid, reply_free_tid;
    void *request_pointer, *reply_pointer, *allocation_pointer;
    void *retained_request, *retained_reply;
    uint64_t transaction, requests, commits, verified_commits, completions;
    uint64_t last_bank_generation, last_crank_generation;
    uint64_t model_instance, bank_generation, crank_generation;
    uint64_t before_config_generation, config_generation, frame_generation;
    uint64_t bank_transaction, bank_commits, bank_released;
    uint64_t reply_fnv1a64, receipt_fnv1a64;
    uint32_t mode, fps;
    struct fcam_native_origin origin, bank_origin;
    struct fcam_bridge_result before_result, crank_result, after_result;
    unsigned char request[FUNCTIONAL_CAMERA_CRANK_REQUEST_BYTES];
    unsigned char before_state[FCAM_STATE_BYTES];
    unsigned char receipt[FUNCTIONAL_CAMERA_CRANK_RESULT_BYTES];
    unsigned char after_state[FCAM_STATE_BYTES];
    unsigned char reply[FUNCTIONAL_CAMERA_CRANK_REPLY_BYTES];
};
/* Explicit functional profile only; local setup, no RPC/reset/history import.
 * Main supplies its all13/current-mode/strict409d/independent40f9 predecessors
 * under resource34 using the existing shared guard type. All callbacks run
 * outside owner locks. Initial409d delegates until a genuine bank is committed.
 * A current full bank receipt, actual original free and STATE128 binding precede
 * OP21; all208 readback bytes and afterSTATE are verified before reply creation.
 * Exactly mode0 is defined. No frame/render/codec/media or physical ASIC claim.
 * Nonzero result leaves the caller owning its request. After takeover result0
 * includes late allocation/send/free failures, with sticky faults/pointers. */
int native_functional_camera_crank_owner_init(void);
int native_functional_camera_crank_dispatch(unsigned int, void *,
    const struct full_imaging_io *, const struct native_cp_state_publication_guard *,
    int enabled, int *result);
void native_functional_camera_crank_snapshot(struct native_functional_camera_crank_snapshot *);
/* event==NULL: free the retained request/reply using the actual original free.
 * event!=NULL: observe actual original receive; release may be NULL and is not
 * called. Receive retains its actual transport TID, which may differ from the
 * original sender; only request/reply free must run on this transaction's sender.
 * Actual receive and its pointer/source/bytes/envelope/ticket are never inferred
 * from free. Ticket0 can pass through only an unowned/completed pointer after Main has
 * invalidated its old ticket on a genuine successful allocation reuse. Never
 * fetch a fresh transaction at free. Nonzero stale/foreign tickets are handled
 * errors. Failed/dirty unqueued nonalias allocations may be explicitly freed by
 * the sender; that is cleanup, never AP consumption, and faults stay sticky. */
int native_functional_camera_crank_release(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result, uint64_t transaction,
    const struct native_functional_camera_crank_receive *event);
/* Independent late type5/4000; no strict4000 or strict409d history import. */
#define FUNCTIONAL_CAMERA_MOVIE_FORMAT_POLICY "active-config-movie-format5-rate1-0-v1"
#define FUNCTIONAL_CAMERA_MOVIE_FORMAT_REQUEST_BYTES 20u
#define FUNCTIONAL_CAMERA_MOVIE_FORMAT_RESULT_BYTES 240u
#define FUNCTIONAL_CAMERA_MOVIE_FORMAT_REPLY_BYTES 12u
struct native_functional_camera_movie_format_context {
    uint64_t model_instance, bank_generation, crank_generation;
};
struct native_functional_camera_movie_format_receive {
    unsigned int source, bytes;
};
struct native_functional_camera_movie_format_snapshot {
    int owner_pid, before_rc, model_rc, after_rc, validation_rc, allocate_rc, send_rc;
    int request_free_rc, reply_free_rc, receive_rc, error;
    unsigned int initialized, busy, guard_held, faults;
    unsigned int model_called, model_committed, verified, owned, complete;
    unsigned int request_releasing, request_freed, reply_releasing, reply_inspecting;
    unsigned int reply_allocated, reply_valid, reply_alias, reply_send_started, send_inflight;
    unsigned int reply_queued, reply_received, reply_freed, reply_cleanup_freed, reply_consumed;
    long sender_tid, receiver_tid, request_free_tid, reply_free_tid;
    void *request_pointer, *reply_pointer, *allocation_pointer;
    void *retained_request, *retained_reply;
    uint64_t transaction, requests, commits, verified_commits, completions;
    uint64_t last_bank_generation, last_crank_generation, last_movie_generation;
    uint64_t model_instance, bank_generation, crank_generation, movie_generation;
    uint64_t before_config_generation, config_generation, frame_generation;
    uint64_t bank_transaction, bank_commits, bank_released, crank_transaction, crank_completions;
    uint64_t reply_fnv1a64, receipt_fnv1a64;
    uint32_t software_format, software_rate_index, fps, software_codec;
    struct fcam_native_origin origin, bank_origin, crank_origin;
    struct fcam_bridge_result before_result, movie_result, after_result;
    unsigned char request[FUNCTIONAL_CAMERA_MOVIE_FORMAT_REQUEST_BYTES];
    unsigned char before_state[FCAM_STATE_BYTES];
    unsigned char receipt[FUNCTIONAL_CAMERA_MOVIE_FORMAT_RESULT_BYTES];
    unsigned char after_state[FCAM_STATE_BYTES];
    unsigned char reply[FUNCTIONAL_CAMERA_MOVIE_FORMAT_REPLY_BYTES];
};
/* Local setup in explicit functional profile only. Main supplies resource35's
 * real same-process current bank/crank and strict4000-clean predecessor guard.
 * Context is copied, then checked against full retired native bank/crank state;
 * generation validation uses this captured operation binding. A live STATE is
 * used, never a historical bank receipt as today's config. OP22's full240 and
 * afterSTATE must prove config+1 and every frame/codec counter unchanged before
 * independent OSAL allocation/send12 and real request free. model_rc records the
 * actual bridge return; model_committed/commits survive later validation errors.
 * Cold calls delegate; pre-takeover failure leaves request caller-owned. After
 * takeover result0 includes retained/faulted real transport/free failures. */
int native_functional_camera_movie_format_owner_init(void);
int native_functional_camera_movie_format_dispatch(unsigned int, void *,
    const struct full_imaging_io *, const struct native_cp_state_publication_guard *,
    const struct native_functional_camera_movie_format_context *, int enabled, int *result);
void native_functional_camera_movie_format_snapshot(struct native_functional_camera_movie_format_snapshot *);
/* Immutable Main ticket is captured at the actual event, never fetched at free.
 * event!=NULL observes only a real successful receive; its positive receiver TID
 * may differ from sender. event==NULL frees only on this transaction's sender,
 * after actual receive for a queued reply. Failed unqueued nonalias allocation
 * cleanup is distinct from consumption and never clears the sticky fault. */
int native_functional_camera_movie_format_release(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result, uint64_t transaction,
    const struct native_functional_camera_movie_format_receive *event);
/* Independent late type5/4072 one-way configure; no strict history mutation. */
#define FUNCTIONAL_CAMERA_OU_CRANK_POLICY "active-config-ou-crank-mode0-v1"
#define FUNCTIONAL_CAMERA_OU_CRANK_RESOURCE 36u
#define FUNCTIONAL_CAMERA_OU_CRANK_REQUEST_BYTES 12u
#define FUNCTIONAL_CAMERA_OU_CRANK_RESULT_BYTES 224u
struct native_functional_camera_ou_crank_context {
    uint64_t model_instance, bank_generation, crank_generation, movie_generation;
};
struct native_functional_camera_ou_crank_snapshot {
    int owner_pid, before_rc, model_rc, after_rc, validation_rc, free_rc, error;
    unsigned int initialized, busy, guard_held, guard_fault, faults;
    unsigned int model_called, model_committed, verified, owned, complete;
    unsigned int releasing, request_freed;
    long sender_tid, free_tid;
    void *request_pointer, *retained_request;
    uint64_t transaction, requests, commits, verified_commits, completions, released;
    uint64_t model_instance, bank_generation, crank_generation, movie_generation, ou_generation;
    uint64_t last_bank_generation, last_crank_generation, last_movie_generation, last_ou_generation;
    uint64_t before_config_generation, config_generation, frame_generation, receipt_fnv1a64;
    uint64_t bank_transaction, bank_commits, bank_released, crank_transaction, crank_completions;
    uint64_t movie_transaction, movie_completions, startup_cycle, startup_config_generation;
    uint64_t startup_frame_generation, startup_lease_generation, startup_result_fnv1a64, startup_config40_fnv1a64;
    unsigned int startup_completed_cycles;
    uint32_t mode, fps;
    struct fcam_native_origin origin, bank_origin, crank_origin, movie_origin, startup_origin;
    struct fcam_bridge_result before_result, ou_result, after_result;
    unsigned char request[FUNCTIONAL_CAMERA_OU_CRANK_REQUEST_BYTES];
    unsigned char before_state[FCAM_STATE_BYTES];
    unsigned char receipt[FUNCTIONAL_CAMERA_OU_CRANK_RESULT_BYTES];
    unsigned char after_state[FCAM_STATE_BYTES];
};
/* Context is copied before callbacks. Resource36 must guard all13/current mode,
 * TTS144, both DMM, PIN/VEF idle and consumed strict4072 history. After reserve,
 * full Native bank/crank/movie and functional4057 snapshots are re-read and
 * verified, including actual retirement, seals and current live generation.
 * STATE -> generic bridge OP23(original12) -> STATE must prove all224 bytes and
 * config+1 only before ownership. No allocate/set_source/send/receive or ACK.
 * Pre-takeover failure remains caller-owned; actual C0 and postvalidation errors
 * remain distinct. Post-takeover result0 includes retained free/guard failures.
 * Every callback runs outside this private mutex; only actual sender/free0 can
 * complete. Main snapshots verified/owned/retained/current transaction in its
 * io.release wrapper before original free, and retains that immutable ticket. */
int native_functional_camera_ou_crank_owner_init(void);
int native_functional_camera_ou_crank_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *io, const struct native_cp_state_publication_guard *guard,
    const struct native_functional_camera_ou_crank_context *context, int enabled, int *result);
void native_functional_camera_ou_crank_snapshot(struct native_functional_camera_ou_crank_snapshot *out);
/* Only retained requests are recoverable; sticky faults never become success.
 * Old/wrong/duplicate tickets are refused before any request metadata or bytes
 * are read. Ticket0 passes only an unowned retired address after Main invalidates
 * the old event on genuine successful single-allocation reuse. */
int native_functional_camera_ou_crank_release(unsigned int destination, void *pointer,
    int (*release)(unsigned int, void *), void (*logger)(const char *, const char *),
    int *result, uint64_t transaction);
#ifdef HOST_TEST
void native_functional_camera_control_test_hold_lock(void);
void native_functional_camera_control_test_drop_lock(void);
#endif
#endif
