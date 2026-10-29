/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_PARAMETER_VIEW_H
#define NATIVE_CP_PARAMETER_VIEW_H
#include "cp-parameter-state.h"
#include "cp-start-state-data.h"

#define CP_PARAMETER_VIEW_PUBLISHED_VA UINT32_C(0x0172fe50)
#define CP_PARAMETER_VIEW_OVERRIDE_BYTES CP_START_STATE_OVERRIDE_BYTES
#define CP_PARAMETER_VIEW_CONFIG_BYTES 304u
#define CP_PARAMETER_VIEW_CONFIG_WORD_OFFSET 0x1cu
#define CP_PARAMETER_VIEW_CONFIG_SOURCE_VA UINT32_C(0x01730f94)
#define CP_PARAMETER_VIEW_CONFIG_COPY_VA UINT32_C(0x01731298)
#define CP_PARAMETER_VIEW_BANK3_VA UINT32_C(0x01730c68)
#define CP_PARAMETER_VIEW_FLAGB_VA UINT32_C(0x0169e018)

enum cp_parameter_view_config_copy_event {
    CP_PARAMETER_VIEW_CONFIG_COPY_NONE = 0,
    CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL = 1, /* CPb2e686 */
    CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY = 2   /* CPb2ee12 */
};
enum cp_parameter_view_config_copy_input {
    CP_PARAMETER_VIEW_CONFIG_INPUT_NONE = 0,
    CP_PARAMETER_VIEW_CONFIG_INPUT_CONSTRUCTOR = 1,
    CP_PARAMETER_VIEW_CONFIG_INPUT_SPAN = 2
};

/* Caller-owned virtual S: an immutable d64-byte copy of P and its bit mask,
 * plus the separate mutable config word consumed through bank3 (not in P).
 * No source/input/output pointer is retained. Do not modify fields directly.
 * copy_consumed and bank0_bound name separate local data-flow events; neither
 * proves native boot, ready, generation, ACK, AP application or capture.
 * source_sequence is the last consumed event; copy_sequence and bank_sequence
 * retain their own event sequences. Later mutations of P never refresh the
 * d64 copy. config_source_* describe the last consumed source observation,
 * initially the constructor store; a caller-span copy refreshes them too. */
struct cp_parameter_view {
    uint32_t owner_pid, magic;
    uint64_t source_sequence, copy_sequence, bank_sequence;
    enum cp_start_state_origin source_origin;
    unsigned char copy_consumed, bank0_bound, invalidated;
    unsigned char bytes[CP_PARAMETER_STATE_IMAGE_BYTES];
    unsigned char known_mask[CP_PARAMETER_STATE_KNOWN_BYTES];
    uint64_t constructor_store_sequence, config_copy_sequence;
    uint64_t bank3_sequence, flagb_store_sequence;
    uint32_t config_source_word, config_word;
    enum cp_parameter_view_config_copy_event config_copy_event;
    enum cp_parameter_view_config_copy_input config_copy_input;
    unsigned char config_source_known, config_word_known;
    unsigned char bank3_bound, bank3_invalidated, flagb, flagb_known;
};

/* Success-only FLAGB readback: copy provenance remains distinct from the
 * getter/STRB event. No whole-config knownness or native history is asserted. */
struct cp_parameter_view_flagb_readback {
    uint32_t owner_pid, config_word;
    uint64_t source_sequence, constructor_store_sequence, config_copy_sequence;
    uint64_t bank3_sequence, flagb_store_sequence;
    enum cp_start_state_origin source_origin;
    enum cp_parameter_view_config_copy_event config_copy_event;
    enum cp_parameter_view_config_copy_input config_copy_input;
    unsigned char flagb;
};

/* External serialization is mandatory, including source init/writes. Guards
 * must be accessible, aligned, disjoint from owners and outputs, same PID and
 * origin, quiescent=1, matching even sequences, and nondecreasing. A later
 * sequence may read the immutable copy; it does not imply a new source copy.
 * Callers guarantee the declared spans are accessible and immutable until
 * return. Full output capacities are checked for wrap/overlap, tails untouched.
 * No internal locks or pointer-mapping probes. Errors preserve owners/outputs
 * except a valid guarded wrong-root binding invalidates only that bank.
 * init leaves all config and FLAGB known bits false; it runs no constructor. */
int cp_parameter_view_init(struct cp_parameter_view *);
/* CPb2e150..164: getter P, memcpy(S,P,d64), with no ready/generation gate.
 * cp_parameter_state_read validates the actual source owner; -ENODATA is valid
 * for this opaque copy. Source unknown bits remain unknown. One copy per init;
 * a repeated copy returns -EBUSY. Source, destination and guard must not alias. */
int cp_parameter_view_consume_initial_copy(struct cp_parameter_view *,
    const struct cp_start_state_guard *, const struct cp_parameter_state *);
/* CPb2ebce -> T[0]=S -> 99affc/99b00c pointer-table copy. logical_root must be
 * CP_PARAMETER_VIEW_PUBLISHED_VA (a logical identity, never dereferenced).
 * A wrong root returns -ENOTSUP and permanently invalidates this copy's bank0.
 * Rebinding the same root returns -EBUSY. Reinit is required after invalidation. */
int cp_parameter_view_consume_bank0_binding(struct cp_parameter_view *,
    const struct cp_start_state_guard *, uint32_t logical_root);
/* Explicitly revoke bank0, retaining owned bytes, mask and copy/bank diagnostics.
 * No source pointer is required. This copy cannot subsequently be rebound. */
int cp_parameter_view_invalidate(struct cp_parameter_view *,
    const struct cp_start_state_guard *);
/* Copy [0,1c9) and expand every bit to a strict 0/1 known byte. Requires copy
 * and matching, non-invalidated bank0 binding. Unknown bytes copy opaquely;
 * success does not assert any field known. Buffers/capacities must be disjoint
 * from each other, owner and guard. No internal borrowed pointer escapes.
 * Feed caller-owned outputs to cp_start_state_data_consume_lif only when its
 * real LIF dependencies are known, with the same PID/origin/sequence guard. */
int cp_parameter_view_copy_override_span(const struct cp_parameter_view *,
    const struct cp_start_state_guard *, unsigned char *bytes, size_t capacity,
    unsigned char *known, size_t known_capacity);

/* Fixed b2a82a -> b2a540 source store: S+1144+1c = LE32 2. Explicit once
 * before any config copy; neither copies the word nor stores FLAGB. */
int cp_parameter_view_consume_config_constructor_store(struct cp_parameter_view *,
    const struct cp_start_state_guard *);
/* Consume the actual 304-byte initial b2e686 or later b2ee12 memcpy to 1731298.
 * source must have size=304, known_size>=304, strict 0/1 mask bytes. Only the
 * four bytes at +1c are retained, known iff all four are known. Other 300 bytes
 * acquire no owned knownness. Source and destination word knownness follow
 * the consumed span. A valid unknown copy succeeds and revokes FLAGB.
 * NULL source is allowed only for INITIAL after the owned constructor store;
 * RECOPY always requires a current caller span, never a replayed constructor.
 * INITIAL is once per init; RECOPY requires INITIAL. Every successful copy
 * revokes FLAGB knownness, including equal words/sequences. Input descriptor,
 * full buffers, owner and guard must be disjoint; no input pointer is kept. */
int cp_parameter_view_consume_config_copy(struct cp_parameter_view *,
    const struct cp_start_state_guard *, enum cp_parameter_view_config_copy_event,
    const struct cp_start_state_span *source);
/* Independent T[3]=S+e18 identity, never dereferenced. Requires a config copy.
 * Wrong root returns -ENOTSUP, revoking only bank3/FLAGB until reinit; bank0
 * and its d64 bytes/mask remain intact. Repeated correct binding is -EBUSY. */
int cp_parameter_view_consume_bank3_binding(struct cp_parameter_view *,
    const struct cp_start_state_guard *, uint32_t logical_root);
/* Explicit 3a9d48 -> 99b86e getter then a4dfc6 STRB to 169e018. Requires the
 * actual copied word known and bank3 bound; stores FLAGB=(word==0), recording
 * its own event sequence. No copy/binding implicitly executes this event. */
int cp_parameter_view_consume_flagb_store(struct cp_parameter_view *,
    const struct cp_start_state_guard *);
/* Read only an actual, still-current FLAGB store, with provenance. Unknown
 * returns -ENODATA; invalidated bank3 or a guard differing from the last owned
 * event returns -ESTALE. Output must be aligned and disjoint from owner/guard.
 * Errors leave output untouched, including a caller's older successful result;
 * callers must honor the return code and consume every intervening recopy. */
int cp_parameter_view_copy_flagb(const struct cp_parameter_view *,
    const struct cp_start_state_guard *, struct cp_parameter_view_flagb_readback *);
#endif
