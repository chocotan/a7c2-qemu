/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_STILL_FORMAT_ABI_H
#define FUNCTIONAL_STILL_FORMAT_ABI_H
#include "functional-vdf-path-abi.h"

/* Explicit software policy for the second original402d tuple only. L means
 * the currently configured full RGB888 frame; FINE preserves Config48 and
 * explicit per-job JPEG quality/geometry. Both slots' auxiliary/raw fields
 * are saved and checked; no RAW/HIF output or physical tag2/CP selector,
 * size lookup, publication or native file-format equivalence is claimed.
 * Input16 is canonical (original wire's opaque final2 bytes become zero in
 * the caller's translation). Require prior INIT and active640x480 route.
 * Each success/repeat renders, copies/readbacks an independent packed sink,
 * retires, then saves/readbacks this separate config16 before committing one
 * config/frame generation. Saved state constrains later RGB/codec consumers.
 * Result176 is VDF160/class8 followed by the independent config16 readback;
 * INPUT_FNV covers all16 bytes; proof consumer4/result176/FNV/token0.
 * No implicit INIT/route, media writes, CP/EE ready or native completion. */
#define FCAM_STILL_FORMAT_INPUT_BYTES 16u
#define FCAM_STILL_FORMAT_RESULT_BYTES 176u
#define FCAM_STILL_FORMAT_R_CONFIG 160u
#define FCAM_STILL_FORMAT_CLASS 8u

static const uint8_t fcam_still_format_initial[FCAM_STILL_FORMAT_INPUT_BYTES] = {
    2, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0};

static inline int fcam_still_format_input_valid(const unsigned char input[FCAM_STILL_FORMAT_INPUT_BYTES])
{
    if (!input) return 0;
    for (size_t i = 0; i < FCAM_STILL_FORMAT_INPUT_BYTES; ++i)
        if (input[i] != fcam_still_format_initial[i]) return 0;
    return 1;
}
#endif
