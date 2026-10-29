/* SPDX-License-Identifier: MIT */
#ifndef REPORT_LIF_CAPABILITIES_H
#define REPORT_LIF_CAPABILITIES_H
#include "cp-lif-bitmap.h"
#include "cp-property-stage.h"

#define LIF_CAPABILITIES_REVISION 1u
#define LIF_CAPABILITIES_PROPERTY_BYTES 1088u
#define LIF_CAPABILITIES_SUPPORT_BYTES 100u
#define LIF_CAPABILITIES_REQUEST_BYTES 33u
#define LIF_CAPABILITIES_HANDSHAKE_BODY_BYTES 12u

struct lif_capabilities_receipt {
    uint64_t sequence;
    uint16_t frame_length, rx_length, body_length;
    unsigned char present, command, flags, opaque, extra_zero;
    unsigned char frame[CP_LIF_FRAME_MAX_RX_BYTES];
};
struct lif_capabilities_readback {
    uint32_t owner_pid, selector, k;
    enum cp_lif_origin origin;
    uint64_t sequence, reset_sequence, support_refresh_sequence, k_store_sequence;
    /* Independent immutable stage transaction, not the receive sequence. */
    struct cp_property_stage_readback stage;
    unsigned char property[LIF_CAPABILITIES_PROPERTY_BYTES];
    unsigned char property_known[LIF_CAPABILITIES_PROPERTY_BYTES];
    unsigned char support[LIF_CAPABILITIES_SUPPORT_BYTES];
    unsigned char support_known[LIF_CAPABILITIES_SUPPORT_BYTES];
    unsigned char z, z_known, mask_row, k_known;
    unsigned char request[LIF_CAPABILITIES_REQUEST_BYTES];
    unsigned char request_configured;
    unsigned char diagnostic_only, owned_data_transport;
    unsigned char original_cache_admission, original_CP;
    /* Explicit local store history, never original CP state or readiness. */
    uint32_t state, last_state_request;
    uint64_t handshake_reset_sequence, state_request_sequence, state_commit_sequence;
    uint64_t control_flags_reset_sequence, pending9_sequence, event9_sequence;
    uint64_t received5_sequence, received6_sequence;
    unsigned char state_known, last_state_request_known, flags_reset_known;
    unsigned char control_enabled, control_enabled_known, pending8, pending8_known;
    unsigned char pending9, pending9_known, pending9_body_known;
    unsigned char pending9_body[LIF_CAPABILITIES_HANDSHAKE_BODY_BYTES];
    unsigned char original_handler_executed, original_event_delivery;
    struct cp_lif_bitmap_received last_dynamic;
    struct lif_capabilities_receipt receipt;
};
/* Fixed caller-owned storage. Initialize every byte to zero; then treat members
 * as private. External serialization and accessible immutable inputs required.
 * No retained pointers, heap, process-global mutable state or native CP state. */
struct lif_capabilities_owner {
    uint32_t revision;
    struct lif_capabilities_readback value;
};
/* Import context by calling cp_property_stage_snapshot with the actual guard.
 * The separate selector is NOT the CP mode. Runs modeled a9073e reset and
 * configures command 1's actual mask bytes; no enqueue/send/lease occurs.
 * Context[0x20] != 0 keeps gated positive support results unknown until the
 * actual a9096c state byte is supplied by a future source event. */
int lif_capabilities_init(struct lif_capabilities_owner *,
    const struct cp_property_stage *, const struct cp_start_state_guard *,
    uint32_t selector);
/* One actual immutable frame, one fixed command 01/07/08/09/3d only. Type 2/3;
 * type 1 is -ENODATA. Mutation requires a strictly newer even sequence.
 * Copies the entire received frame including the optional exact zero.
 * shortcut: Z=0 only; upgrade after closing all three complete normalizers.
 * Command 7 producing Z=1 is -ENOTSUP; required unknown Z and command 3d's
 * D bit 29 set are -ENODATA. Command 9 requires known P+22/control enabled
 * and body[8..9]==0 (header-independent source subset). Disabled control
 * defers all 12 bytes; enabled control applies only a955da K/state stores.
 * Command 8 refreshes support and requests state 2, committing only when
 * the old state is known 0/1. Rejected state requests do not reject a copy.
 * Neither failure consumes bytes or sequence. */
int lif_capabilities_receive(struct lif_capabilities_owner *,
    const unsigned char *rx, size_t rx_size, const struct cp_lif_bitmap_guard *);
/* Execute only the source a95856 initial-kind store: known P+22 low bits
 * 1 -> K=4; 2 -> K=1; other values unsupported. Requires a newer guard.
 * This explicit local step does not execute its later calls/queue or claim
 * original handler invocation. Receiving command 7 never invokes it. */
int lif_capabilities_consume_initial_kind_store(struct lif_capabilities_owner *,
    const struct cp_lif_bitmap_guard *);
/* Consume ONLY a913d2's explicit state=0/K=0 stores. Does not reset P,
 * support, flags, receipts or other buffers; init never executes this event. */
int lif_capabilities_consume_handshake_reset_store(struct lif_capabilities_owner *,
    const struct cp_lif_bitmap_guard *);
/* Consume ONLY a948a8..a9491a enabled/pending8/pending9 zero stores.
 * Pending body contents/knownness and all other source fields are preserved. */
int lif_capabilities_consume_control_flags_reset(struct lif_capabilities_owner *,
    const struct cp_lif_bitmap_guard *);
/* Explicit 408d58 event9 LOCAL prefix: enabled=1, then pending8 before
 * pending9. No deferred8 producer exists: unknown/nonzero pending8 refuses.
 * Replays the retained body without clearing original pending9. This call
 * certifies no original event delivery, queue, timer or complete handler. */
int lif_capabilities_consume_dispatch_event9_prefix(struct lif_capabilities_owner *,
    const struct cp_lif_bitmap_guard *);
/* Under ONE external lock for BOTH owners, validate actual dynamic RX once
 * with cp_lif_bitmap_receive_decode. Same PID/origin and a newer guard for
 * BOTH are required. Retains its owned decode separately from fixed receipt;
 * actual command5 then command6 presence conditionally writes state 4/5.
 * Errors leave BOTH owners unchanged; no original cache/publication claim. */
int lif_capabilities_receive_dynamic(struct lif_capabilities_owner *,
    struct cp_lif_bitmap_owner *, const unsigned char *rx, size_t rx_size,
    const struct cp_lif_bitmap_guard *);
/* Read APIs require the exact CURRENT owner sequence. Full declared output
 * capacity, including unused tail, must be disjoint from owner and guard.
 * Every API returns 0 or -errno, preserves errno, and changes nothing on error. */
int lif_capabilities_snapshot(const struct lif_capabilities_owner *,
    const struct cp_lif_bitmap_guard *, struct lif_capabilities_readback *, size_t);
/* Copies P[0..0x161]/known, Z/known, CACHED S43/S5a/known and validated
 * stage E-mode (same source 1107178). K is known only after an explicit
 * handshake reset, initial-kind store, or applicable command9 K store;
 * stage E-mode is not the data owner's M predicate. */
int lif_capabilities_export_bitmap(const struct lif_capabilities_owner *,
    const struct cp_lif_bitmap_guard *, struct cp_lif_bitmap_inputs *, size_t);
#endif
