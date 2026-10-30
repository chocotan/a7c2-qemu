/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_VDF_BIT_WIDTH_ABI_H
#define FUNCTIONAL_VDF_BIT_WIDTH_ABI_H
#include "functional-vdf-path-abi.h"

/* virtual-functional-camera-v1 software display-bus policy only:
 * selector0 means RGB888 with eight-bit R/G/B components in this model.
 * Original015e selector0's physical bit depth is UNKNOWN. No Sony ASIC/CP
 * compatibility or original capture acceptance is established by this policy.
 * Input8: selector:u8 followed by seven reserved zero bytes. Selectors1..3
 * (and all other selectors) remain unsupported; no physical depth is guessed.
 * Require an initialized active route1/pins5,5 at 640x480. Success consumes
 * one actual leased RGB frame, copies/reads back an independent packed sink,
 * retires it, then commits/readbacks a separate saved Input8 bank. Repeats
 * perform the same real transaction and advance config/frame generation once.
 * Result168: VDF base160 with class7, INPUT_FNV over all8 input bytes and
 * current route CONFIG16, then the actual independent saved Input8 readback.
 * No encoded result token, implicit INIT, route change, or CP completion. */
#define FCAM_BIT_WIDTH_INPUT_BYTES 8u
#define FCAM_BIT_WIDTH_RESULT_BYTES 168u
#define FCAM_BIT_WIDTH_R_CONFIG 160u
#define FCAM_BIT_WIDTH_CLASS 7u
#define FCAM_BIT_WIDTH_SOFTWARE_RGB888_SELECTOR 0u

static inline int fcam_bit_width_input_valid(const unsigned char input[FCAM_BIT_WIDTH_INPUT_BYTES])
{
    if (!input || input[0] != FCAM_BIT_WIDTH_SOFTWARE_RGB888_SELECTOR) return 0;
    for (size_t i = 1; i < FCAM_BIT_WIDTH_INPUT_BYTES; ++i) if (input[i]) return 0;
    return 1;
}
#endif
