/* SPDX-License-Identifier: MIT */
#ifndef REPORT_LIF_CACHE_H
#define REPORT_LIF_CACHE_H
#include "lif-capabilities.h"

#define LIF_CACHE_REVISION 1u
#define LIF_CACHE_RECORDS 64u
#define LIF_CACHE_RESERVE_BYTES 0x220u

struct lif_cache_handle {
    uint64_t incarnation;
    unsigned char slot;
};
/* known+!present is an observed empty slot, not an unknown history. */
struct lif_cache_history_ref {
    struct lif_cache_handle handle;
    unsigned char known, present;
};
struct lif_cache_epoch {
    uint64_t sequence;
    unsigned char known, token;
    struct lif_cache_history_ref command[2]; /* command 5, command 6 */
};
/* Actual ingress entry +2/+4/+10, supplied under the transport lock. The
 * token is independent of frame[4] opaque; all three values are mandatory. */
struct lif_cache_ingress {
    unsigned char token;
    uint32_t metadata8, metadata10;
};
struct lif_cache_command_ref {
    uint16_t offset, length, metadata;
    unsigned char command, field_count;
};
struct lif_cache_record {
    uint64_t incarnation, source_sequence;
    size_t pool_offset;
    uint32_t metadata8, metadata10;
    uint16_t rx_length, frame_length;
    unsigned char live, admitted_owned_frame, verdict;
    unsigned char ingress_token, flags, opaque, extra_zero;
    unsigned char command_count, last_top_index;
    unsigned char field_table_known, field_table_command;
    unsigned char field_count, last_dynamic_index;
    /* Offsets are relative to this record's copied RX, including command byte.
     * These are shared-table fields from ONLY the last NONEMPTY command. */
    struct lif_cache_command_ref commands[2];
    struct cp_lif_field_view fields[CP_LIF_MAX_FIELDS];
};
struct lif_cache_readback {
    uint32_t owner_pid;
    enum cp_lif_origin origin;
    uint64_t sequence, reset_sequence, next_incarnation;
    size_t pool_capacity, write_offset, last_rx_size;
    unsigned char source_primed, next_slot;
    unsigned char diagnostic_only, owned_virtual_policy;
    unsigned char original_cache_executed, worker_published, ack, ready;
    struct lif_cache_history_ref global_last[2];
    struct lif_cache_epoch current, previous;
    struct lif_cache_record records[LIF_CACHE_RECORDS];
};
/* Fixed lifecycle: every byte must initially be zero, then treat all members
 * as private. Caller owns accessible pool bytes for this owner's entire life.
 * One external lock serializes cache, backing, capability and bitmap owners.
 * Never copy/reinitialize an owner to reuse incarnation tokens. */
struct lif_cache_owner {
    uint32_t revision;
    unsigned char *pool;
    struct lif_cache_readback value;
};
struct lif_cache_result {
    struct lif_cache_handle handle;
    uint64_t source_sequence;
    size_t size;
    unsigned char ingress_token, opaque, diagnostic_only;
    unsigned char bytes[LIF_CACHE_RESERVE_BYTES];
};
/* All APIs return 0 or -errno, preserve errno and change nothing on error.
 * Immutable accessible inputs, typed alignment and nonwrapping spans required.
 * Full output capacity (including unused tail) must be disjoint from inputs,
 * owner and the FULL backing pool. Only sizeof(*out) is written on success. */
int lif_cache_init(struct lif_cache_owner *, unsigned char *pool, size_t capacity,
    const struct cp_lif_bitmap_guard *);
/* Explicit a9570a..a95732 reset/prime event; metadata/history only, no pool
 * writes. Preserves monotonic next_incarnation; epoch remains unknown. */
int lif_cache_consume_reset_and_prime(struct lif_cache_owner *,
    const struct cp_lif_bitmap_guard *);
/* Explicit a476a4 roll, using exactly one immutable actual source token byte
 * (a96cea/a90ec2). Copies current to previous; starts known-empty current refs.
 * An equal received token never calls this event implicitly. */
int lif_cache_consume_cycle_roll(struct lif_cache_owner *,
    const unsigned char *actual_token, size_t, const struct cp_lif_bitmap_guard *);
/* Exact cap_guard is passed to lif_capabilities_snapshot; mutation guard must
 * be newer than cache, capabilities and live bitmap, with matching PID/origin.
 * Requires BOTH 5/6 support known true and known Z=0, a conservative subset.
 * Entire RX (optional zero included) <=0x220. Plans reserve/evictions first,
 * invokes cp_lif_bitmap_receive_decode EXACTLY ONCE, then copies/commits only.
 * Capability owner is read-only; no handshake state or source publication. */
int lif_cache_receive(struct lif_cache_owner *,
    const struct lif_capabilities_owner *, const struct cp_lif_bitmap_guard *cap_guard,
    struct cp_lif_bitmap_owner *, const unsigned char *rx, size_t,
    const struct lif_cache_ingress *, const struct cp_lif_bitmap_guard *mutation_guard,
    struct lif_cache_handle *out, size_t out_capacity);
/* Same admission prechecks and exact-current cap_guard as lif_cache_receive.
 * ONE external lock covers all THREE owners, backing and immutable inputs.
 * Calls lif_capabilities_receive_dynamic ONCE (one real bitmap decode), then
 * copies that same call's owned last_dynamic and commits cache infallibly.
 * Success gives all three owners mutation_guard's sequence and conditionally
 * applies known state 3->4/4->5; unknown state stays unknown. Errors preserve
 * all three owners, backing and output. No original CP/event/ready claim. */
int lif_cache_receive_with_handshake(struct lif_cache_owner *,
    struct lif_capabilities_owner *, const struct cp_lif_bitmap_guard *cap_guard,
    struct cp_lif_bitmap_owner *, const unsigned char *rx, size_t,
    const struct lif_cache_ingress *, const struct cp_lif_bitmap_guard *mutation_guard,
    struct lif_cache_handle *out, size_t out_capacity);
int lif_cache_snapshot(const struct lif_cache_owner *,
    const struct cp_lif_bitmap_guard *, struct lif_cache_readback *, size_t);
/* Copy full top-command body (including command byte), or exact shared-table
 * field bytes. Handles reject both metadata reuse and byte-overlap eviction. */
int lif_cache_lookup_command(const struct lif_cache_owner *, struct lif_cache_handle,
    unsigned command, const struct cp_lif_bitmap_guard *, struct lif_cache_result *, size_t);
int lif_cache_lookup_field(const struct lif_cache_owner *, struct lif_cache_handle,
    unsigned field_id, const struct cp_lif_bitmap_guard *, struct lif_cache_result *, size_t);
/* Requires the current matching-token history handle AND record.opaque ==
 * current.token for BOTH commands. The command6 opaque equality is a stronger
 * local freshness policy than its source worker prefix. No implicit roll. */
int lif_cache_lookup_current_field(const struct lif_cache_owner *, unsigned command,
    unsigned field_id, const struct cp_lif_bitmap_guard *, struct lif_cache_result *, size_t);
#endif
