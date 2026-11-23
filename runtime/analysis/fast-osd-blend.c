/* SPDX-License-Identifier: MIT */
/* Host-side native x86_64 RGBA4444-over-RGB24 virtual CP display compositor.
 * Matches Sony AP RGBA4444 nibble order and rounding used in ramfb-viewer.c:
 *   v = le16(px): R = (v >> 12) * 17, G = ((v >> 8) & 15) * 17,
 *                 B = ((v >> 4) & 15) * 17, A = v & 15 (0..15).
 */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "../../report/virtual-sensor/sensor-core.h"

#define FAST_PIXELS (640U * 480U)
#define FAST_RGB_BYTES (FAST_PIXELS * 3U)

static uint8_t g_premul_rgb[65536][3];
static int g_table_ready;

static void ensure_table(void) {
    if (g_table_ready) return;
    for (unsigned v = 0; v < 65536U; ++v) {
        unsigned a = v & 15U;
        g_premul_rgb[v][0] = (uint8_t)(((v >> 12) * 17U * a + 7U) / 15U);
        g_premul_rgb[v][1] = (uint8_t)((((v >> 8) & 15U) * 17U * a + 7U) / 15U);
        g_premul_rgb[v][2] = (uint8_t)((((v >> 4) & 15U) * 17U * a + 7U) / 15U);
    }
    g_table_ready = 1;
}

void fast_blend_rgba4444_over_rgb24(const uint16_t *osd, const uint8_t *bg,
                                    uint8_t *out_rgb24, int has_bg) {
    ensure_table();
    if (!has_bg || !bg) {
        for (unsigned i = 0; i < FAST_PIXELS; ++i) {
            const uint8_t *rgb = g_premul_rgb[osd[i]];
            out_rgb24[3U * i + 0] = rgb[0];
            out_rgb24[3U * i + 1] = rgb[1];
            out_rgb24[3U * i + 2] = rgb[2];
        }
        return;
    }
    for (unsigned i = 0; i < FAST_PIXELS; ++i) {
        unsigned v = osd[i];
        unsigned a = v & 15U;
        uint8_t *dst = out_rgb24 + 3U * i;
        const uint8_t *src_bg = bg + 3U * i;
        if (a == 0U) {
            dst[0] = src_bg[0];
            dst[1] = src_bg[1];
            dst[2] = src_bg[2];
        } else if (a == 15U) {
            const uint8_t *rgb = g_premul_rgb[v];
            dst[0] = rgb[0];
            dst[1] = rgb[1];
            dst[2] = rgb[2];
        } else {
            unsigned inv = 15U - a;
            dst[0] = (uint8_t)((((v >> 12) * 17U * a) + src_bg[0] * inv + 7U) / 15U);
            dst[1] = (uint8_t)(((((v >> 8) & 15U) * 17U * a) + src_bg[1] * inv + 7U) / 15U);
            dst[2] = (uint8_t)(((((v >> 4) & 15U) * 17U * a) + src_bg[2] * inv + 7U) / 15U);
        }
    }
}

static void fast_hud_glyph(char ch, uint8_t rows[7]) {
    memset(rows, 0, 7);
    static const struct { char c; uint8_t r[7]; } k_glyphs[] = {
        {'0',{0x0e,0x11,0x13,0x15,0x19,0x11,0x0e}}, {'1',{0x04,0x0c,0x04,0x04,0x04,0x04,0x0e}},
        {'2',{0x0e,0x11,0x01,0x06,0x08,0x10,0x1f}}, {'3',{0x1f,0x02,0x04,0x02,0x01,0x11,0x0e}},
        {'4',{0x02,0x06,0x0a,0x12,0x1f,0x02,0x02}}, {'5',{0x1f,0x10,0x1e,0x01,0x01,0x11,0x0e}},
        {'6',{0x06,0x08,0x10,0x1e,0x11,0x11,0x0e}}, {'7',{0x1f,0x01,0x02,0x04,0x08,0x08,0x08}},
        {'8',{0x0e,0x11,0x11,0x0e,0x11,0x11,0x0e}}, {'9',{0x0e,0x11,0x11,0x0f,0x01,0x02,0x0c}},
        {'R',{0x1e,0x11,0x11,0x1e,0x14,0x12,0x11}}, {'E',{0x1f,0x10,0x10,0x1e,0x10,0x10,0x1f}},
        {'C',{0x0e,0x11,0x10,0x10,0x10,0x11,0x0e}}, {'S',{0x0f,0x10,0x10,0x0e,0x01,0x01,0x1e}},
        {'D',{0x1c,0x12,0x11,0x11,0x11,0x12,0x1c}}, {'W',{0x11,0x11,0x11,0x15,0x15,0x15,0x0a}},
        {'A',{0x0e,0x11,0x11,0x1f,0x11,0x11,0x11}}, {'V',{0x11,0x11,0x11,0x11,0x11,0x0a,0x04}},
        {'I',{0x0e,0x04,0x04,0x04,0x04,0x04,0x0e}}, {'N',{0x11,0x11,0x19,0x15,0x13,0x11,0x11}},
        {'G',{0x0e,0x11,0x10,0x17,0x11,0x11,0x0f}}, {':',{0x00,0x0c,0x0c,0x00,0x0c,0x0c,0x00}},
        {'.',{0x00,0x00,0x00,0x00,0x00,0x0c,0x0c}},
    };
    for (size_t i = 0; i < sizeof k_glyphs / sizeof k_glyphs[0]; ++i) {
        if (k_glyphs[i].c == ch) { memcpy(rows, k_glyphs[i].r, 7); return; }
    }
}

void fast_draw_rec_hud(uint8_t *rgb24, int rec_active, int rec_saving, uint32_t elapsed_ms) {
    if (!rgb24 || (!rec_active && !rec_saving)) return;
    char label[24];
    if (rec_saving) {
        snprintf(label, sizeof label, "SD SAVING...");
    } else {
        unsigned sec = elapsed_ms / 1000U;
        unsigned mins = (sec / 60U) % 100U;
        unsigned rem = sec % 60U;
        snprintf(label, sizeof label, "REC %02u:%02u", mins, rem);
    }
    const unsigned x0 = 14U, y0 = 10U, scale = 2U;
    const unsigned nchars = (unsigned)strlen(label);
    const unsigned box_w = 24U + nchars * 6U * scale + 10U;
    const unsigned box_h = 22U;
    for (unsigned y = y0; y < y0 + box_h && y < 480U; ++y) {
        uint8_t *row = rgb24 + (size_t)y * 640U * 3U;
        for (unsigned x = x0; x < x0 + box_w && x < 640U; ++x) {
            uint8_t *p = row + (size_t)x * 3U;
            p[0] = (uint8_t)(p[0] >> 2);
            p[1] = (uint8_t)(p[1] >> 2);
            p[2] = (uint8_t)(p[2] >> 2);
        }
    }
    /* Solid dot: crimson while recording, amber while saving */
    const unsigned cx = x0 + 11U, cy = y0 + 11U, r2 = 30U;
    const uint8_t dr = rec_saving ? 255U : 235U;
    const uint8_t dg = rec_saving ? 185U : 45U;
    const uint8_t db = 45U;
    for (int dy = -6; dy <= 6; ++dy) {
        for (int dx = -6; dx <= 6; ++dx) {
            if ((unsigned)(dx * dx + dy * dy) <= r2) {
                unsigned px = cx + (unsigned)dx, py = cy + (unsigned)dy;
                if (px < 640U && py < 480U) {
                    uint8_t *p = rgb24 + ((size_t)py * 640U + px) * 3U;
                    p[0] = dr; p[1] = dg; p[2] = db;
                }
            }
        }
    }
    unsigned tx = x0 + 24U, ty = y0 + 4U;
    for (unsigned i = 0; i < nchars; ++i) {
        uint8_t rows[7];
        fast_hud_glyph(label[i], rows);
        for (unsigned ry = 0; ry < 7U; ++ry) {
            for (unsigned rx = 0; rx < 5U; ++rx) {
                if (rows[ry] & (1U << (4U - rx))) {
                    for (unsigned sy = 0; sy < scale; ++sy) {
                        for (unsigned sx = 0; sx < scale; ++sx) {
                            unsigned px = tx + rx * scale + sx;
                            unsigned py = ty + ry * scale + sy;
                            if (px < 640U && py < 480U) {
                                uint8_t *p = rgb24 + ((size_t)py * 640U + px) * 3U;
                                p[0] = 255U; p[1] = 255U; p[2] = 255U;
                            }
                        }
                    }
                }
            }
        }
        tx += 6U * scale;
    }
}

int fast_default_chart_rgb24(uint8_t *out_rgb24) {
    if (!out_rgb24) return -1;
    sensor_config cfg = sensor_config_default();
    uint8_t *rgb = sensor_frame_rgb(&cfg, sensor_token_next(&cfg, 0));
    if (!rgb) return -1;
    memcpy(out_rgb24, rgb, FAST_RGB_BYTES);
    free(rgb);
    return 0;
}

uint32_t fast_atomic_load_u32(const uint32_t *ptr) {
    return __atomic_load_n(ptr, __ATOMIC_ACQUIRE);
}

void fast_atomic_store_u32(uint32_t *ptr, uint32_t val) {
    __atomic_store_n(ptr, val, __ATOMIC_RELEASE);
}

uint64_t fast_atomic_load_u64(const uint64_t *ptr) {
    return __atomic_load_n(ptr, __ATOMIC_ACQUIRE);
}

void fast_atomic_store_u64(uint64_t *ptr, uint64_t val) {
    __atomic_store_n(ptr, val, __ATOMIC_RELEASE);
}
