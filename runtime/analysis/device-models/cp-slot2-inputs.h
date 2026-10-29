/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_SLOT2_INPUTS_H
#define NATIVE_CP_SLOT2_INPUTS_H
#include <stddef.h>
#include <stdint.h>

#define CP_SLOT2_INPUT_N_BYTES 200u
#define CP_SLOT2_INPUT_ROOT_BYTES 0x930u
#define CP_SLOT2_INPUT_WORKING_BYTES 0xf3au
#define CP_SLOT2_INPUT_ACTION_BYTES 0x3ccu
#define CP_SLOT2_INPUT_T178_BYTES 3u
#define CP_SLOT2_INPUT_WORKING_TOKEN UINT32_C(0x02012a58)
#define CP_SLOT2_INPUT_ACTION_TOKEN UINT32_C(0x0186bf24)
#define CP_SLOT2_INPUT_T178_TOKEN UINT32_C(0x01656d98)

/* CP32 tokens bind actual caller buffers; they are never cast to host pointers.
 * size is the logical byte span, known_size its mask capacity. All masks inside
 * size must be 0/1; only consumed bytes must be known. Backing outside size is
 * untouched. The caller supplies accessible storage for every declared span. */
struct cp_slot2_input_span {
    unsigned char *bytes, *known;
    size_t size, known_size;
    uint32_t token;
};
struct cp_slot2_inputs {
    struct cp_slot2_input_span n, root, working, action, t178;
    unsigned char mode_b, mode_b_known;
};
enum cp_slot2_inputs_result {
    CP_SLOT2_INPUTS_STAGED = 0,
    CP_SLOT2_NORMAL_WORD_STAGED = 0
};

/* Public CP SHA256 f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428.
 * CPVA 8a3bd8..8a3c5c, raw 79bbd8, 134B, CPVA = raw + 108000.
 * Called at 32880e..328822. This contract first SAVES the known A+32d byte
 * and CLEARS it, matching the CALLER'S pre-call write, then stages 8a3bd8.
 * N is exactly 200B; le32(N+0) must equal root.token. C/A/T tokens are fixed
 * above. mode_b is the actual known u8 from b08868 / CP32 1b1dea5.
 * The caller must supply the actual prior state: 32870c's 1350B copy from
 * 02018df8 to C, 178B from 01656f10 to T, and restoration are OUTSIDE this API.
 * No initialization or zero filling of unknown bytes is performed here.
 * Validate every span, mask, required read and output before any write.
 * Mutable spans must not overlap other storage or CP32 spans; saved_marker
 * must not alias any input storage. Read-only spans may overlap each other.
 * Returns INPUTS_STAGED only, or negative errno (EINVAL/ENODATA).
 * Caller quiescence, lifetime and generation checks are external: this pure
 * helper does not reproduce original atomicity or attest command completion.
 * No queue, timer, semaphore, callback, publication, observed, ready or event. */
int cp_slot2_inputs_stage(const struct cp_slot2_inputs *, unsigned char *saved_marker);

/* Finite 0323/032c TEMP2B candidate only: known le16(C+0), actual status byte
 * C+10aa copied from H+2, and le16(C+6) only when status != 1. C must cover
 * 10ab bytes. Returns NORMAL_WORD_STAGED and writes candidate[2] in LE order;
 * unsupported commands (including 0302) return -ENOTSUP. Unknown reads fail
 * without changing candidate. No C mutation, G+10/P+2950 write, or claim of
 * complete 8c8eea. Candidate must not alias C, its mask or its descriptor. */
int cp_slot2_normal_word_032x(const struct cp_slot2_input_span *, unsigned char candidate[2]);
#endif
