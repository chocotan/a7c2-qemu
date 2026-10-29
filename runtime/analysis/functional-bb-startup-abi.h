/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_BB_STARTUP_ABI_H
#define FUNCTIONAL_BB_STARTUP_ABI_H
#include "functional-vdf-path-abi.h"

/* Explicit virtual-functional-camera-v1 policy, not Sony CP/ASIC semantics.
 * All integers are LE. Both operations require an active route1/pins5,5 at
 * 640x480, idle frame owner, no active clip or pending result, and full reply
 * capacity before work. Success requires real CMOS render -> independent RGB
 * sink copy/readback -> retire -> saved config/result readback -> commit.
 * Base160 is the VDF receipt with the current route CONFIG16, real generations,
 * source/sink hashes, active bytes, instance and before-generation values.
 * CLASS is 5 or 6 below; host proof consumer_kind uses the same new values.
 * Neither operation uses the encoded-result token/cursor protocol. */
#define FCAM_BB_INPUT_BYTES 32u
#define FCAM_BB_RESULT_BYTES 192u
#define FCAM_BB_R_CONFIG 160u
#define FCAM_BB_CLASS 5u
#define FCAM_BB_PROOF_KIND 5u
#define FCAM_BB_FEATURES 5u
#define FCAM_BB_I_COMMAND 0u /* LEu16 original command */
#define FCAM_BB_I_BODY_BYTES 2u /* LEu16 original body length */
#define FCAM_BB_I_BODY 4u /* body28, unused tail must be virtual zero */
#define FCAM_BB_CMD_0111 0x0111u
#define FCAM_BB_CMD_0166 0x0166u
#define FCAM_BB_CMD_0167 0x0167u
#define FCAM_BB_CMD_015F 0x015fu
#define FCAM_BB_CMD_0128 0x0128u
/* Five independent saved/read-back canonical32 banks (and valid bits):
 * 0111/body28: 00 00 0f 02 followed by 24 zeros. Software SQ idle/off;
 *   sqMode@4, rate@8 and auxiliary fields must be zero. No deferred work.
 * 0166/body28: 00 01 followed by 26 zeros, or the exact observed initial
 *   tuple 00010000000000000000000008000000070000000100000001000000.
 *   Both select software RGB identity; preserve all six source words without
 *   Sony CreativeLook algorithm, address, coefficient or unit claims.
 * 0167/body2: LEu16 0 or 1. Two opaque software RGB identity domains;
 *   byte1 and all unused tail must be zero, no Sony gamut/matrix claim.
 * 015f/body4: LEu32 0 only. Keep the current software gain tag (initial 0),
 *   never clear it or assign an ISO value; Config48 ISO is unchanged.
 * 0128/body12: 00 01 00 00, LEu32 period in
 *   {60,50,40,30,20,10,9,8,7,6,5,4,3,2,1}, then four zeros.
 *   Scheduler disabled, no events; period is opaque pending-enable ticks,
 *   not Sony seconds/frames. Enabled/delay/nonneutral branches unsupported.
 * Every successful call advances config/frame generation by one. */
/* shortcut: these two complete look tokens select RGB identity; extend only with an explicit look model. */
static inline int fcam_bb_0166_identity(const uint32_t look[8])
{
    static const uint32_t initial[6] = {0, 0, 8, 7, 1, 1};
    int neutral = 1, observed = 1;
    if (look[0] || look[1] != 1) return 0;
    for (unsigned int i = 0; i < 6; ++i) {
        neutral = neutral && !look[i + 2];
        observed = observed && look[i + 2] == initial[i];
    }
    return neutral || observed;
}
static inline int fcam_bb_0166_body_valid(const unsigned char body[28])
{
    uint32_t look[8] = {body[0], body[1]};
    if (body[2] || body[3]) return 0;
    for (unsigned int i = 0; i < 6; ++i) {
        const unsigned char *p = body + 4 + i * 4;
        look[i + 2] = (uint32_t)p[0] | (uint32_t)p[1] << 8 |
                      (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
    }
    return fcam_bb_0166_identity(look);
}
#define FCAM_HIST_INPUT_BYTES 8u
#define FCAM_HIST_RESULT_BYTES 1192u
#define FCAM_HIST_R_CONFIG 160u
#define FCAM_HIST_R_BINS 168u
#define FCAM_HIST_BINS 1024u
#define FCAM_HIST_BINS_BYTES FCAM_HIST_BINS
#define FCAM_HIST_CHANNEL_BINS 256u
#define FCAM_HIST_CLASS 6u
#define FCAM_HIST_PROOF_KIND 6u
#define FCAM_HIST_COMMAND 0x0148u
/* Input8: LEu16 0148, LEu16 4, original body 01 01 00 00 only.
 * Result tail: independently saved/read-back canonical8, then four256B
 * software Y/R/G/B u8-height arrays calculated from the same sink RGB bytes.
 * Y=(77R+150G+29B+128)>>8; each channel has 256 bins and is independently
 * peak normalized: (count*255+peak/2)/peak. Nonempty frame required.
 * Config/frame generation advance once only after cache readback and retire.
 * This is one first-frame sample, not continuous histogram/UI acceptance.
 * Guest owns original210c header/logical1034B construction and AP ownership;
 * this receipt does not prove original CP work, RTOS/FIFO or physical bins,
 * notification delivery, MPR/Fsys acceptance or capture_verified. */
#endif
