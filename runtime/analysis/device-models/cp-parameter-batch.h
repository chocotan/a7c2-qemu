/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_PARAMETER_BATCH_H
#define NATIVE_CP_PARAMETER_BATCH_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

#define CP_PARAMETER_BATCH_BYTES 0xa04u
#define CP_PARAMETER_BATCH_SLOTS 190u
#define CP_PARAMETER_BATCH_SOURCE UINT32_C(0x80020002)
#define CP_PARAMETER_BATCH_TARGET UINT32_C(0x90030001)
#define CP_PARAMETER_BATCH_MASK_WORDS 3u

/* Offsets include the outer eight-byte header; size includes each slot header.
 * These are fixed CP dispatcher arguments, never wire lengths or a TLV count. */
struct cp_parameter_batch_slot {
    uint16_t opcode, offset, size;
};
extern const struct cp_parameter_batch_slot
    cp_parameter_batch_slots[CP_PARAMETER_BATCH_SLOTS];

/* One explicit virtual settings owner, containing its own complete wire copy.
 * semantic_consumed bit i means business handler i actually consumed its value;
 * this implementation has no business handlers, so all bits remain zero.
 * Reserved bytes, opaque words and uninterpreted payloads retain their input
 * values. No generation, published state, hardware result, ACK or callback. */
struct cp_parameter_batch {
    pid_t owner_pid;
    bool enabled, staged, semantic_applied;
    uint64_t semantic_consumed[CP_PARAMETER_BATCH_MASK_WORDS];
    unsigned char bytes[CP_PARAMETER_BATCH_BYTES];
};
enum cp_parameter_batch_result { CP_PARAMETER_BATCH_STAGED = 1 };

/* Initialize before use; enabled=false (including a zero-initialized owner)
 * rejects staging. Reinitialization explicitly discards a previous stage.
 * Caller must quiesce access during init/stage, and keep owner storage alive
 * while reading it; views into bytes expire on init or owner destruction.
 * After fork the child must initialize its own owner before staging. */
int cp_parameter_batch_init(struct cp_parameter_batch *, bool enabled);

/* Exact AP type5/4063/a04B envelope only. Every fixed slot must contain type5
 * and its predetermined opcode; no assumptions about its other header bytes
 * or payload. All validation precedes writes; errors leave owner unchanged.
 * Input must be readable for size bytes and must not overlap ANY owner storage.
 * The caller owns envelope provenance and synchronization of input until return.
 * One-shot: a second stage returns -EBUSY until explicit reinitialization.
 * Returns STAGED only, or negative errno. Copy/decode does not apply CP settings
 * and MUST NOT cause a caller to advance generation or publish a snapshot. */
int cp_parameter_batch_stage(struct cp_parameter_batch *, uint32_t source,
                             uint32_t target, const void *input, size_t size);
#endif
