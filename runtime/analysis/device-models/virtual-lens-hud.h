/* SPDX-License-Identifier: MIT */
#ifndef VIRTUAL_LENS_HUD_H
#define VIRTUAL_LENS_HUD_H

#include <stddef.h>
#include <stdint.h>

/* Software virtual lens & exposure HUD wire encoders for AP queue 0x80020002.
 * All multi-byte fields are explicit little-endian matching appFw.so parsers:
 *   - 0x2044 (0xa0B): mounted virtual lens -> AP 0x351fdb8 (event 0x7a)
 *   - 0x201b (0x14B): aperture x100        -> AP 0x3531ba0 (event 0x99)
 *   - 0x200e (0x28B): shutter num/den      -> AP 0x35190c0 (event 0x26)
 *   - 0x2036 (0x0cB): ISO CP byte          -> AP 0x3521310 (event 0x25)
 * Software virtual model only; never claims physical CP ASIC or E-mount bus. */

#define VIRTUAL_LENS_HUD_CP_SOURCE 0x90030001u
#define VIRTUAL_LENS_HUD_AP_DEST   0x80020002u

#define VIRTUAL_LENS_HUD_2044_BYTES 0xa0u
#define VIRTUAL_LENS_HUD_201B_BYTES 0x14u
#define VIRTUAL_LENS_HUD_200E_BYTES 0x28u
#define VIRTUAL_LENS_HUD_2036_BYTES 0x0cu
#define VIRTUAL_LENS_HUD_NAME_MAX   0x40u

struct virtual_lens_hud_state {
    uint8_t lens_mounted;         /* 1 -> wire 1 (mounted), 0 -> wire 4 (detached) */
    uint32_t focal_min_x10;       /* e.g. 350 for 35.0mm */
    uint32_t focal_max_x10;       /* e.g. 350 for 35.0mm */
    uint16_t aperture_x100;       /* e.g. 400 for F4.0 */
    uint16_t aperture_min_x100;   /* e.g. 400 for F4.0 */
    uint16_t aperture_max_x100;   /* e.g. 1600 for F16 */
    uint16_t shutter_num;         /* e.g. 1 for 1/125s */
    uint32_t shutter_den;         /* e.g. 125 for 1/125s */
    uint16_t shutter_min_num;     /* e.g. 1 for 1/4000s */
    uint32_t shutter_min_den;     /* e.g. 4000 */
    uint16_t shutter_max_num;     /* e.g. 30 for 30s */
    uint32_t shutter_max_den;     /* e.g. 1 */
    uint8_t iso_cp_byte;          /* 0x0b -> AP enum 5 -> ISO 100 */
    uint8_t iso_auto;             /* 0 -> manual ISO byte */
    char lens_name[VIRTUAL_LENS_HUD_NAME_MAX + 1];
};

void virtual_lens_hud_init_defaults(struct virtual_lens_hud_state *state);
int virtual_lens_hud_encode_2044(const struct virtual_lens_hud_state *state,
                                 unsigned char *out, size_t capacity);
int virtual_lens_hud_encode_201b(const struct virtual_lens_hud_state *state,
                                 unsigned char *out, size_t capacity);
int virtual_lens_hud_encode_200e(const struct virtual_lens_hud_state *state,
                                 unsigned char *out, size_t capacity);
int virtual_lens_hud_encode_2036(const struct virtual_lens_hud_state *state,
                                 unsigned char *out, size_t capacity);
int virtual_lens_hud_step_aperture(struct virtual_lens_hud_state *state, int delta);
int virtual_lens_hud_step_shutter(struct virtual_lens_hud_state *state, int delta);
int virtual_lens_hud_step_iso(struct virtual_lens_hud_state *state, int delta);
int virtual_lens_hud_program_shift(struct virtual_lens_hud_state *state, int delta);
uint32_t virtual_lens_hud_iso_value(uint8_t iso_cp_byte);

#endif
