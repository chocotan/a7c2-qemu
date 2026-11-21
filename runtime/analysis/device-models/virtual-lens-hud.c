/* SPDX-License-Identifier: MIT */
#include "virtual-lens-hud.h"

#include <errno.h>
#include <string.h>

static void put16(unsigned char *p, uint16_t v) {
    p[0] = (unsigned char)(v & 0xffu);
    p[1] = (unsigned char)((v >> 8) & 0xffu);
}

static void put32(unsigned char *p, uint32_t v) {
    p[0] = (unsigned char)(v & 0xffu);
    p[1] = (unsigned char)((v >> 8) & 0xffu);
    p[2] = (unsigned char)((v >> 16) & 0xffu);
    p[3] = (unsigned char)((v >> 24) & 0xffu);
}

static const uint16_t k_apertures_x100[] = {
    400, 450, 500, 560, 630, 710, 800, 900, 1000, 1100, 1300, 1400, 1600
};

struct shutter_entry {
    uint16_t num;
    uint32_t den;
};

static const struct shutter_entry k_shutters[] = {
    {30, 1}, {15, 1}, {8, 1}, {4, 1}, {2, 1}, {1, 1},
    {1, 2}, {1, 4}, {1, 8}, {1, 15}, {1, 30}, {1, 60},
    {1, 125}, {1, 250}, {1, 500}, {1, 1000}, {1, 2000}, {1, 4000}
};

/* CP 0x2036 ISO bytes accepted by appFw 0x3521310 (0x0b = ISO 100, 3 steps/EV). */
static const uint8_t k_iso_cp_bytes[] = {
    0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x10, 0x11, 0x12, 0x13,
    0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b, 0x1c,
    0x1d, 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23
};

void virtual_lens_hud_init_defaults(struct virtual_lens_hud_state *state) {
    static const char k_name[] = "Virtual 35mm F4.0";
    if (!state) return;
    memset(state, 0, sizeof *state);
    state->lens_mounted = 1;
    state->focal_min_x10 = 0x40u;   /* Matches validated 0x2044 focal tuple in functional-camera-control.c */
    state->focal_max_x10 = 0x160u;
    state->aperture_x100 = 400u;
    state->aperture_min_x100 = 400u;
    state->aperture_max_x100 = 1600u;
    state->shutter_num = 1u;
    state->shutter_den = 125u;
    state->shutter_min_num = 1u;
    state->shutter_min_den = 4000u;
    state->shutter_max_num = 30u;
    state->shutter_max_den = 1u;
    state->iso_cp_byte = 0x0bu;     /* ISO 100 */
    state->iso_auto = 0u;
    memcpy(state->lens_name, k_name, sizeof k_name);
}

int virtual_lens_hud_encode_2044(const struct virtual_lens_hud_state *state,
                                 unsigned char *out, size_t capacity) {
    if (!state || !out || capacity < VIRTUAL_LENS_HUD_2044_BYTES) return -EINVAL;
    memset(out, 0, VIRTUAL_LENS_HUD_2044_BYTES);
    out[0] = 6u;
    put16(out + 2, 0x2044u);
    out[8] = state->lens_mounted ? 1u : 4u;
    if (state->lens_mounted) {
        put32(out + 0x18, 10u);
        put32(out + 0x20, 10u);
        put32(out + 0x24, state->focal_min_x10 ? state->focal_min_x10 : 0x40u);
        put32(out + 0x28, 10u);
        put32(out + 0x2c, state->focal_max_x10 ? state->focal_max_x10 : 0x160u);
        put32(out + 0x30, 10u);
        size_t len = strnlen(state->lens_name, VIRTUAL_LENS_HUD_NAME_MAX);
        if (len) memcpy(out + 0x34, state->lens_name, len);
        out[0x34 + len] = 0;
    }
    return (int)VIRTUAL_LENS_HUD_2044_BYTES;
}

int virtual_lens_hud_encode_201b(const struct virtual_lens_hud_state *state,
                                 unsigned char *out, size_t capacity) {
    if (!state || !out || capacity < VIRTUAL_LENS_HUD_201B_BYTES) return -EINVAL;
    memset(out, 0, VIRTUAL_LENS_HUD_201B_BYTES);
    out[0] = 6u;
    put16(out + 2, 0x201bu);
    put16(out + 8, state->lens_mounted ? state->aperture_x100 : 0u);
    put16(out + 0x0e, state->lens_mounted ? state->aperture_min_x100 : 0u);
    put16(out + 0x10, state->lens_mounted ? state->aperture_max_x100 : 0u);
    return (int)VIRTUAL_LENS_HUD_201B_BYTES;
}

int virtual_lens_hud_encode_200e(const struct virtual_lens_hud_state *state,
                                 unsigned char *out, size_t capacity) {
    if (!state || !out || capacity < VIRTUAL_LENS_HUD_200E_BYTES) return -EINVAL;
    if (!state->shutter_num || !state->shutter_den) return -ERANGE;
    memset(out, 0, VIRTUAL_LENS_HUD_200E_BYTES);
    out[0] = 6u;
    put16(out + 2, 0x200eu);
    put16(out + 8, state->shutter_num);
    put32(out + 0x0c, state->shutter_den);
    put16(out + 0x10, state->shutter_min_num ? state->shutter_min_num : 1u);
    put32(out + 0x14, state->shutter_min_den ? state->shutter_min_den : 4000u);
    put16(out + 0x18, state->shutter_max_num ? state->shutter_max_num : 30u);
    put32(out + 0x1c, state->shutter_max_den ? state->shutter_max_den : 1u);
    out[0x24] = 0u;
    out[0x25] = 0u;
    return (int)VIRTUAL_LENS_HUD_200E_BYTES;
}

int virtual_lens_hud_encode_2036(const struct virtual_lens_hud_state *state,
                                 unsigned char *out, size_t capacity) {
    if (!state || !out || capacity < VIRTUAL_LENS_HUD_2036_BYTES) return -EINVAL;
    if (state->iso_cp_byte < 0x07u || state->iso_cp_byte > 0x2fu) return -ERANGE;
    memset(out, 0, VIRTUAL_LENS_HUD_2036_BYTES);
    out[0] = 6u;
    put16(out + 2, 0x2036u);
    out[8] = state->iso_cp_byte;
    out[9] = state->iso_auto ? 1u : 0u;
    return (int)VIRTUAL_LENS_HUD_2036_BYTES;
}

int virtual_lens_hud_step_aperture(struct virtual_lens_hud_state *state, int delta) {
    if (!state || !state->lens_mounted) return -ENODEV;
    const int n = (int)(sizeof k_apertures_x100 / sizeof k_apertures_x100[0]);
    int idx = 0;
    for (int i = 0; i < n; i++) {
        if (k_apertures_x100[i] >= state->aperture_x100) { idx = i; break; }
        idx = i;
    }
    int next = idx + delta;
    if (next < 0) next = 0;
    if (next >= n) next = n - 1;
    state->aperture_x100 = k_apertures_x100[next];
    return 0;
}

int virtual_lens_hud_step_shutter(struct virtual_lens_hud_state *state, int delta) {
    if (!state) return -EINVAL;
    const int n = (int)(sizeof k_shutters / sizeof k_shutters[0]);
    int idx = 12; /* default 1/125 */
    for (int i = 0; i < n; i++) {
        if (k_shutters[i].num == state->shutter_num && k_shutters[i].den == state->shutter_den) {
            idx = i;
            break;
        }
    }
    int next = idx + delta;
    if (next < 0) next = 0;
    if (next >= n) next = n - 1;
    state->shutter_num = k_shutters[next].num;
    state->shutter_den = k_shutters[next].den;
    return 0;
}

int virtual_lens_hud_step_iso(struct virtual_lens_hud_state *state, int delta) {
    if (!state) return -EINVAL;
    const int n = (int)(sizeof k_iso_cp_bytes / sizeof k_iso_cp_bytes[0]);
    int idx = 0;
    for (int i = 0; i < n; i++) {
        if (k_iso_cp_bytes[i] >= state->iso_cp_byte) { idx = i; break; }
        idx = i;
    }
    int next = idx + delta;
    if (next < 0) next = 0;
    if (next >= n) next = n - 1;
    state->iso_cp_byte = k_iso_cp_bytes[next];
    state->iso_auto = 0u;
    return 0;
}

int virtual_lens_hud_program_shift(struct virtual_lens_hud_state *state, int delta) {
    if (!state || !state->lens_mounted) return -ENODEV;
    if (!delta) return 0;
    uint16_t old_ap = state->aperture_x100;
    uint16_t old_num = state->shutter_num;
    uint32_t old_den = state->shutter_den;
    int rc_ap = virtual_lens_hud_step_aperture(state, -delta);
    int rc_ss = virtual_lens_hud_step_shutter(state, delta);
    if (rc_ap || rc_ss || state->aperture_x100 == old_ap ||
        (state->shutter_num == old_num && state->shutter_den == old_den)) {
        state->aperture_x100 = old_ap;
        state->shutter_num = old_num;
        state->shutter_den = old_den;
    }
    return 0;
}

uint32_t virtual_lens_hud_iso_value(uint8_t iso_cp_byte) {
    static const uint32_t k_iso_values[] = {
        100, 125, 160, 200, 250, 320, 400, 500, 640, 800,
        1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000, 6400, 8000,
        10000, 12800, 16000, 20000, 25600
    };
    if (iso_cp_byte < 0x0bu) return 100u;
    size_t idx = (size_t)(iso_cp_byte - 0x0bu);
    size_t n = sizeof k_iso_values / sizeof k_iso_values[0];
    return idx < n ? k_iso_values[idx] : k_iso_values[n - 1];
}
