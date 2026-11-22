/* SPDX-License-Identifier: MIT */
/* Host-side native x86_64 RGBA4444-over-RGB24 virtual CP display compositor.
 * Matches Sony AP RGBA4444 nibble order and rounding used in ramfb-viewer.c:
 *   v = le16(px): R = (v >> 12) * 17, G = ((v >> 8) & 15) * 17,
 *                 B = ((v >> 4) & 15) * 17, A = v & 15 (0..15).
 */
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
