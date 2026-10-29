/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_FULL_STATE_SNAPSHOT_H
#define NATIVE_CP_FULL_STATE_SNAPSHOT_H
#include "cp-state-snapshot.h"

#define CP_FULL_STATE_SNAPSHOT_BLOCKS 76u
struct cp_full_state_snapshot_block {
    uint16_t command, offset, bytes;
};
extern const struct cp_full_state_snapshot_block
    cp_full_state_snapshot_blocks[CP_FULL_STATE_SNAPSHOT_BLOCKS];
enum cp_full_state_snapshot_result { CP_FULL_STATE_SNAPSHOT_LAYOUT_ASSEMBLED = 0 };

/* Pure nominal-success CP353c18/D93660 layout only; no field providers,
 * publication, shadow update, AP application, ACK, readiness or send permission.
 * See report/cp-full-state-snapshot/{README.md,source-pins.json}.
 *
 * copy checks all 76 headers (6, command, u32+4 == 0), then delegates masks,
 * domains, provenance and freshness to the unchanged cp_state_snapshot_copy.
 * assemble requires exactly 76 successful getter fragments in table order,
 * using cp_state_snapshot_input for each fragment's actual bytes, mask capacity
 * and generation. Each size must equal the nominal successful return length;
 * zero/missing/short/long/refused providers cannot be filled or skipped.
 * All four generation fields must equal *generation; mutable may be ahead of
 * published, zero/wrap is valid, and published must differ from shadow.
 * The outer +1 is explicitly VIRTUAL reserved zero with known=0; fragment +1
 * bytes/masks are preserved. Only the existing outer/201b/2044 +1 exceptions
 * permit unknown bytes; every logical mask byte must be 0/1.
 *
 * Caller owns accessible, immutable, quiescent spans for the call. Output may
 * not overlap ANY input descriptor, generation, bytes, or entire mask capacity;
 * read-only input spans may overlap one another. No pointer is retained.
 * Output and all inputs are unchanged on error. Negative errno follows the
 * existing helper; EINVAL also covers count/width/span/alias, EPROTO any full
 * header, ESTALE any mixed generation metadata. A successful result means
 * LAYOUT_ASSEMBLED only; all remaining provider semantics stay caller work. */
int cp_full_state_snapshot_copy(const struct cp_state_snapshot_input *,
                                struct cp_state_snapshot *);
int cp_full_state_snapshot_assemble(const struct cp_state_snapshot_input *fragments,
                                    size_t count,
                                    const struct cp_state_snapshot_generation *generation,
                                    struct cp_state_snapshot *);
#endif
