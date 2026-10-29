/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_START_STATE_DATA_H
#define NATIVE_CP_START_STATE_DATA_H
#include <errno.h>
#include <stddef.h>
#include <stdint.h>

#define CP_START_STATE_LIF_BYTES 0x129u
#define CP_START_STATE_OVERRIDE_BYTES 0x1c9u
#define CP_START_STATE_MERGE_BYTES 3u
#define CP_START_STATE_REPLY_BYTES 16u
#define CP_START_STATE_PROPERTY_ID UINT32_C(0x01250006)
#define CP_START_STATE_SOURCE_BLOCKED (-ENODATA)

enum cp_start_state_origin {
    CP_START_STATE_ORIGIN_NONE = 0,
    CP_START_STATE_ORIGIN_VIRTUAL_SOURCE = 1,
    CP_START_STATE_ORIGIN_HOST_TEST = 2
};
/* External serialization is required. Matching even sequence values describe
 * one immutable, quiescent source transaction, not a native CP observation. */
struct cp_start_state_guard {
    uint32_t owner_pid;
    uint64_t sequence_before, sequence_after;
    enum cp_start_state_origin source_origin;
    unsigned char quiescent;
};
struct cp_start_state_span {
    const unsigned char *bytes, *known;
    size_t size, known_size;
};
/* Caller-owned state. Do not alter fields directly; no pointers are retained.
 * Known bits refer to data consumed by this owner, never native initialization.
 * known_mask bits 0..3 are data[0..3]; predicate_known_mask bits 0..4 are
 * profile/M/C/kind/Q. Unknown storage bytes have no default-value semantics.
 * image_initial seeds only the source-file cache bytes 10e31c6/c7/c8. */
struct cp_start_state_data {
    uint32_t owner_pid, magic;
    uint64_t revision, source_sequence;
    enum cp_start_state_origin source_origin;
    unsigned char data[4], known_mask, image_initial;
    unsigned char previous_state, previous_subcode, previous_kind;
    unsigned char previous_tuple_known, previous_flags_known;
    uint32_t previous_flags;
    unsigned char raw_action, effective_kind, effective_state, effective_subcode;
    unsigned char effective_action, captured_live[4], captured_live_known;
    unsigned char profile, mode, override_cache, predicate_kind, q[4];
    unsigned char predicate_known_mask;
    unsigned char lif_consumed, property_consumed, adj_consumed, source_consumed;
};
/* Readback records bytes and provenance only. All publication/business fields
 * remain zero; a separate publisher must provide its own evidence and lease. */
struct cp_start_state_readback {
    uint32_t owner_pid;
    uint64_t revision, source_sequence;
    enum cp_start_state_origin source_origin;
    unsigned char data[4], known_mask, predicate_known_mask;
    unsigned char lif_consumed, property_consumed, adj_consumed, source_consumed;
    unsigned char effective_kind, effective_state, effective_subcode, effective_action;
    unsigned char captured_live[4], captured_live_known;
    unsigned char snapshot_copied, data_ready;
    unsigned char business_ready, configuration_ready, published, ap_applied;
    uint32_t publication_generation;
};
/* Source events below name actual storage/producer dependencies. They are not
 * ready bits. HISTORY is a bounded 7-byte LE record: previous state/subcode/kind
 * (1b1611a..1c), then previous flags (18b8ce4); it never seeds result bytes.
 * PREDICATE_KIND supplies the current a94b86 byte (1a040ac).
 * Q_COPY consumes 4 bytes from the actual a9171a source word 1a03ce0.
 * Q_CLEAR represents the actual a9170c clear event, and requires an empty span.
 * FOURTH_READ models the actual a499f4 getter (including M=2 cache writeback);
 * predicate input changes invalidate the fourth result until this event is
 * consumed. Native M/C initialization is unclosed: consume real ADJ writes. */
enum cp_start_state_event {
    CP_START_STATE_EVENT_HISTORY = 1,
    CP_START_STATE_EVENT_PREDICATE_KIND = 2,
    CP_START_STATE_EVENT_Q_COPY = 3,
    CP_START_STATE_EVENT_Q_CLEAR = 4,
    CP_START_STATE_EVENT_FOURTH_READ = 5
};
/* The caller supplies accessible, immutable buffers for every declared span;
 * pointer arithmetic wrap and typed-object alignment are checked. No pointer
 * mapping probe or internal thread synchronization is performed.
 * All calls return 0 or negative errno; state/output unchanged on error.
 * Unknown required source bytes return -ENODATA; unsupported packet aliases
 * return -ENOTSUP. Descriptors/masks/spans cannot overlap a mutable owner or an
 * output. Every mask byte in a logical span is 0/1; mask capacity is validated
 * for overlap but its tail is not scanned. Full u8 domains are preserved.
 * init binds getpid() and leaves every input mask and output-known bit empty.
 * A guarded event must come from the same process/origin and a nondecreasing
 * source sequence; forked owners and torn/unquiescent transactions fail closed.
 */
int cp_start_state_data_init(struct cp_start_state_data *);
/* Raw LIF 169dbb0: +81 kind,+82 state,+83 subcode,+84 LE32 flags,+128 action.
 * override_bank is the pointee of 165cfb0, +1c8 mode. For mode 1 only, merge is
 * 1b160ef..f1 (alternate kind at +0, subcode at +2). Span sizes must equal the
 * constants above; merge must be NULL for other modes. All six source fields,
 * plus both merge fields when selected, must be known before any mutation. */
int cp_start_state_data_consume_lif(struct cp_start_state_data *,
    const struct cp_start_state_guard *, const struct cp_start_state_span *lif,
    const struct cp_start_state_span *override_bank,
    const struct cp_start_state_span *merge);
/* Actual property payload copied by a48c08 to context 1211300. At least five
 * bytes are required and payload+4 must be known. No repository/prefetch default
 * is synthesized. Only property 01250006 is supported. */
int cp_start_state_data_consume_property(struct cp_start_state_data *,
    const struct cp_start_state_guard *, uint32_t property_id,
    const struct cp_start_state_span *payload);
/* Bounded actual 4b7730 packet: +26 ff, +28 LE16 0080/00b2, +2a 0a,
 * +2b 00, +2c LE32 length=1, +30 full u8 value. Exact size 31 hex;
 * multi-byte aliases and other packet forms are unsupported. */
int cp_start_state_data_consume_adj(struct cp_start_state_data *,
    const struct cp_start_state_guard *, const struct cp_start_state_span *packet);
int cp_start_state_data_consume_event(struct cp_start_state_data *,
    const struct cp_start_state_guard *, enum cp_start_state_event,
    const struct cp_start_state_span *source);
int cp_start_state_data_snapshot(const struct cp_start_state_data *,
    const struct cp_start_state_guard *, struct cp_start_state_readback *);
/* Builds only: type1, virtual reserved byte +1=0, command 3003 or 3000,
 * LE32 echo at +4, LE32 f000 at +8, four owned bytes at +12. Requires all four
 * bytes from this coherent owner state. No I/O/ACK/CP-current/publication.
 * out_size must be exactly 16 and overlap with owner/guard is rejected. */
int cp_start_state_data_build_reply(const struct cp_start_state_data *,
    const struct cp_start_state_guard *, uint16_t command, uint32_t echo,
    unsigned char *out, size_t out_size);
#endif
