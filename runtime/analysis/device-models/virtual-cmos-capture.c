/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "virtual-cmos-capture.h"
#include "../../../report/virtual-sensor/sensor-core.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* Firmware glibc 2.25 exports __fxstat rather than glibc 2.33's fstat symbol. */
static int vcmos_fstat(int fd, struct stat *st) {
#ifdef __aarch64__
    extern int __fxstat(int, int, struct stat *);
    return __fxstat(0, fd, st);
#else
    return fstat(fd, st);
#endif
}

static uint64_t vcmos_fnv64_step(uint64_t h, const uint8_t *p, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        h = (h ^ p[i]) * UINT64_C(1099511628211);
    }
    return h;
}

static uint64_t vcmos_fnv64(const uint8_t *p, size_t n) {
    return vcmos_fnv64_step(UINT64_C(14695981039346656037), p, n);
}

static int clamp_u8(int v) {
    return v < 0 ? 0 : (v > 255 ? 255 : v);
}

/* Exact orthonormal 8x8 DCT matrix scaled by 16384 (zero libm dependency). */
static const int16_t k_dct_cos[8][8] = {
    {  5793,   5793,   5793,   5793,   5793,   5793,   5793,   5793},
    {  8035,   6811,   4551,   1598,  -1598,  -4551,  -6811,  -8035},
    {  7568,   3135,  -3135,  -7568,  -7568,  -3135,   3135,   7568},
    {  6811,  -1598,  -8035,  -4551,   4551,   8035,   1598,  -6811},
    {  5793,  -5793,  -5793,   5793,   5793,  -5793,  -5793,   5793},
    {  4551,  -8035,   1598,   6811,  -6811,  -1598,   8035,  -4551},
    {  3135,  -7568,   7568,  -3135,  -3135,   7568,  -7568,   3135},
    {  1598,  -4551,   6811,  -8035,   8035,  -6811,   4551,  -1598},
};

/* Standard JPEG zigzag scan order (natural index for zigzag position k). */
static const uint8_t k_zigzag[64] = {
     0,  1,  8, 16,  9,  2,  3, 10,
    17, 24, 32, 25, 18, 11,  4,  5,
    12, 19, 26, 33, 40, 48, 41, 34,
    27, 20, 13,  6,  7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36,
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46,
    53, 60, 61, 54, 47, 55, 62, 63,
};

/* High-quality (approx Q88) quantization tables (natural order). */
static const uint8_t k_qtable_y[64] = {
     4,  3,  2,  4,  6, 10, 12, 15,
     3,  3,  3,  5,  6, 14, 14, 13,
     3,  3,  4,  6, 10, 14, 17, 13,
     3,  4,  5,  7, 12, 21, 19, 15,
     4,  5,  9, 13, 16, 26, 25, 18,
     6,  8, 13, 15, 19, 25, 27, 22,
    12, 15, 19, 21, 25, 29, 29, 24,
    17, 22, 23, 24, 27, 24, 25, 24,
};

static const uint8_t k_qtable_c[64] = {
     4,  4,  6, 11, 24, 24, 24, 24,
     4,  5,  6, 16, 24, 24, 24, 24,
     6,  6, 13, 24, 24, 24, 24, 24,
    11, 16, 24, 24, 24, 24, 24, 24,
    24, 24, 24, 24, 24, 24, 24, 24,
    24, 24, 24, 24, 24, 24, 24, 24,
    24, 24, 24, 24, 24, 24, 24, 24,
    24, 24, 24, 24, 24, 24, 24, 24,
};

/* Standard JPEG Annex K Huffman tables. */
static const uint8_t k_bits_dc_y[16] = {0,1,5,1,1,1,1,1,1,0,0,0,0,0,0,0};
static const uint8_t k_vals_dc_y[12] = {0,1,2,3,4,5,6,7,8,9,10,11};
static const uint8_t k_bits_dc_c[16] = {0,3,1,1,1,1,1,1,1,1,1,0,0,0,0,0};
static const uint8_t k_vals_dc_c[12] = {0,1,2,3,4,5,6,7,8,9,10,11};

static const uint8_t k_bits_ac_y[16] = {0,2,1,3,3,2,4,3,5,5,4,4,0,0,1,0x7d};
static const uint8_t k_vals_ac_y[162] = {
    0x01,0x02,0x03,0x00,0x04,0x11,0x05,0x12,0x21,0x31,0x41,0x06,0x13,0x51,0x61,0x07,
    0x22,0x71,0x14,0x32,0x81,0x91,0xa1,0x08,0x23,0x42,0xb1,0xc1,0x15,0x52,0xd1,0xf0,
    0x24,0x33,0x62,0x72,0x82,0x09,0x0a,0x16,0x17,0x18,0x19,0x1a,0x25,0x26,0x27,0x28,
    0x29,0x2a,0x34,0x35,0x36,0x37,0x38,0x39,0x3a,0x43,0x44,0x45,0x46,0x47,0x48,0x49,
    0x4a,0x53,0x54,0x55,0x56,0x57,0x58,0x59,0x5a,0x63,0x64,0x65,0x66,0x67,0x68,0x69,
    0x6a,0x73,0x74,0x75,0x76,0x77,0x78,0x79,0x7a,0x83,0x84,0x85,0x86,0x87,0x88,0x89,
    0x8a,0x92,0x93,0x94,0x95,0x96,0x97,0x98,0x99,0x9a,0xa2,0xa3,0xa4,0xa5,0xa6,0xa7,
    0xa8,0xa9,0xaa,0xb2,0xb3,0xb4,0xb5,0xb6,0xb7,0xb8,0xb9,0xba,0xc2,0xc3,0xc4,0xc5,
    0xc6,0xc7,0xc8,0xc9,0xca,0xd2,0xd3,0xd4,0xd5,0xd6,0xd7,0xd8,0xd9,0xda,0xe1,0xe2,
    0xe3,0xe4,0xe5,0xe6,0xe7,0xe8,0xe9,0xea,0xf1,0xf2,0xf3,0xf4,0xf5,0xf6,0xf7,0xf8,
    0xf9,0xfa
};

static const uint8_t k_bits_ac_c[16] = {0,2,1,2,4,4,3,4,7,5,4,4,0,1,2,0x77};
static const uint8_t k_vals_ac_c[162] = {
    0x00,0x01,0x02,0x03,0x11,0x04,0x05,0x21,0x31,0x06,0x12,0x41,0x51,0x07,0x61,0x71,
    0x13,0x22,0x32,0x81,0x08,0x14,0x42,0x91,0xa1,0xb1,0xc1,0x09,0x23,0x33,0x52,0xf0,
    0x15,0x62,0x72,0xd1,0x0a,0x16,0x24,0x34,0xe1,0x25,0xf1,0x17,0x18,0x19,0x1a,0x26,
    0x27,0x28,0x29,0x2a,0x35,0x36,0x37,0x38,0x39,0x3a,0x43,0x44,0x45,0x46,0x47,0x48,
    0x49,0x4a,0x53,0x54,0x55,0x56,0x57,0x58,0x59,0x5a,0x63,0x64,0x65,0x66,0x67,0x68,
    0x69,0x6a,0x73,0x74,0x75,0x76,0x77,0x78,0x79,0x7a,0x82,0x83,0x84,0x85,0x86,0x87,
    0x88,0x89,0x8a,0x92,0x93,0x94,0x95,0x96,0x97,0x98,0x99,0x9a,0xa2,0xa3,0xa4,0xa5,
    0xa6,0xa7,0xa8,0xa9,0xaa,0xb2,0xb3,0xb4,0xb5,0xb6,0xb7,0xb8,0xb9,0xba,0xc2,0xc3,
    0xc4,0xc5,0xc6,0xc7,0xc8,0xc9,0xca,0xd2,0xd3,0xd4,0xd5,0xd6,0xd7,0xd8,0xd9,0xda,
    0xe2,0xe3,0xe4,0xe5,0xe6,0xe7,0xe8,0xe9,0xea,0xf2,0xf3,0xf4,0xf5,0xf6,0xf7,0xf8,
    0xf9,0xfa
};

struct huff_enc_table {
    uint16_t code[256];
    uint8_t size[256];
};

static void build_huff_enc(const uint8_t bits[16], const uint8_t *vals, struct huff_enc_table *tbl) {
    memset(tbl, 0, sizeof *tbl);
    uint32_t code = 0;
    size_t k = 0;
    for (unsigned len = 1; len <= 16; ++len) {
        for (unsigned i = 0; i < bits[len - 1]; ++i) {
            uint8_t sym = vals[k++];
            tbl->code[sym] = (uint16_t)code;
            tbl->size[sym] = (uint8_t)len;
            ++code;
        }
        code <<= 1;
    }
}

struct byte_vec {
    uint8_t *data;
    size_t len;
    size_t cap;
    int error;
};

static void bv_reserve(struct byte_vec *v, size_t extra) {
    if (v->error) return;
    if (v->len + extra <= v->cap) return;
    size_t next = v->cap ? v->cap * 2 : 65536;
    while (next < v->len + extra) next *= 2;
    uint8_t *p = realloc(v->data, next);
    if (!p) { v->error = -ENOMEM; return; }
    v->data = p;
    v->cap = next;
}

static void bv_push(struct byte_vec *v, uint8_t b) {
    bv_reserve(v, 1);
    if (!v->error) v->data[v->len++] = b;
}

static void bv_write(struct byte_vec *v, const void *src, size_t n) {
    bv_reserve(v, n);
    if (!v->error && n) {
        memcpy(v->data + v->len, src, n);
        v->len += n;
    }
}

static void bv_be16(struct byte_vec *v, uint16_t x) {
    bv_push(v, (uint8_t)(x >> 8));
    bv_push(v, (uint8_t)(x & 0xffu));
}

struct bit_writer {
    struct byte_vec *out;
    uint32_t bitbuf;
    int bitcount;
};

static void bw_put(struct bit_writer *bw, uint32_t bits, int count) {
    bw->bitbuf = (bw->bitbuf << count) | (bits & ((1u << count) - 1u));
    bw->bitcount += count;
    while (bw->bitcount >= 8) {
        bw->bitcount -= 8;
        uint8_t b = (uint8_t)((bw->bitbuf >> bw->bitcount) & 0xffu);
        bv_push(bw->out, b);
        if (b == 0xffu) bv_push(bw->out, 0x00u);
    }
}

static void bw_flush(struct bit_writer *bw) {
    if (bw->bitcount > 0) {
        int pad = 8 - bw->bitcount;
        bw_put(bw, (1u << pad) - 1u, pad);
    }
}

static int bit_category(int val) {
    int a = val < 0 ? -val : val;
    int n = 0;
    while (a) { ++n; a >>= 1; }
    return n;
}

static void fdct8x8(const int16_t in[64], int32_t out[64]) {
    int64_t tmp[64];
    for (int r = 0; r < 8; ++r) {
        for (int c = 0; c < 8; ++c) {
            int64_t s = 0;
            for (int k = 0; k < 8; ++k) s += (int64_t)k_dct_cos[c][k] * in[r * 8 + k];
            tmp[r * 8 + c] = s;
        }
    }
    for (int u = 0; u < 8; ++u) {
        for (int v = 0; v < 8; ++v) {
            int64_t s = 0;
            for (int k = 0; k < 8; ++k) s += (int64_t)k_dct_cos[u][k] * tmp[k * 8 + v];
            /* Two scales of 16384 -> divide by 2^28 with rounding. */
            if (s >= 0) out[u * 8 + v] = (int32_t)((s + (INT64_C(1) << 27)) >> 28);
            else        out[u * 8 + v] = (int32_t)-(((-s) + (INT64_C(1) << 27)) >> 28);
        }
    }
}

static void idct8x8(const int32_t in[64], int16_t out[64]) {
    int64_t tmp[64];
    for (int r = 0; r < 8; ++r) {
        for (int c = 0; c < 8; ++c) {
            int64_t s = 0;
            for (int k = 0; k < 8; ++k) s += (int64_t)in[r * 8 + k] * k_dct_cos[k][c];
            tmp[r * 8 + c] = s;
        }
    }
    for (int y = 0; y < 8; ++y) {
        for (int x = 0; x < 8; ++x) {
            int64_t s = 0;
            for (int k = 0; k < 8; ++k) s += (int64_t)k_dct_cos[k][y] * tmp[k * 8 + x];
            int32_t v;
            if (s >= 0) v = (int32_t)((s + (INT64_C(1) << 27)) >> 28);
            else        v = (int32_t)-(((-s) + (INT64_C(1) << 27)) >> 28);
            out[y * 8 + x] = (int16_t)v;
        }
    }
}

static void encode_block(struct bit_writer *bw, const int16_t block[64],
                         const uint8_t qtbl[64],
                         const struct huff_enc_table *dc_tbl,
                         const struct huff_enc_table *ac_tbl,
                         int *prev_dc) {
    int32_t dct[64];
    int16_t zz[64];
    fdct8x8(block, dct);
    for (int k = 0; k < 64; ++k) {
        int idx = k_zigzag[k];
        int32_t q = qtbl[idx];
        int32_t v = dct[idx];
        zz[k] = (int16_t)(v >= 0 ? (v + q / 2) / q : -((-v + q / 2) / q));
    }
    int diff = zz[0] - *prev_dc;
    *prev_dc = zz[0];
    int cat = bit_category(diff);
    if (cat > 11) cat = 11;
    bw_put(bw, dc_tbl->code[cat], dc_tbl->size[cat]);
    if (cat) {
        uint32_t bits = diff >= 0 ? (uint32_t)diff : (uint32_t)(diff + (1 << cat) - 1);
        bw_put(bw, bits, cat);
    }
    int last = 63;
    while (last > 0 && zz[last] == 0) --last;
    int zeros = 0;
    for (int k = 1; k <= last; ++k) {
        int v = zz[k];
        if (v == 0) {
            ++zeros;
            continue;
        }
        while (zeros >= 16) {
            bw_put(bw, ac_tbl->code[0xf0], ac_tbl->size[0xf0]);
            zeros -= 16;
        }
        int acat = bit_category(v);
        if (acat > 10) acat = 10;
        uint8_t sym = (uint8_t)((zeros << 4) | acat);
        bw_put(bw, ac_tbl->code[sym], ac_tbl->size[sym]);
        uint32_t bits = v >= 0 ? (uint32_t)v : (uint32_t)(v + (1 << acat) - 1);
        bw_put(bw, bits, acat);
        zeros = 0;
    }
    if (last < 63) {
        bw_put(bw, ac_tbl->code[0x00], ac_tbl->size[0x00]);
    }
}

static void put_le16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)(v & 0xffu);
    p[1] = (uint8_t)(v >> 8);
}

static void put_le32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v & 0xffu);
    p[1] = (uint8_t)((v >> 8) & 0xffu);
    p[2] = (uint8_t)((v >> 16) & 0xffu);
    p[3] = (uint8_t)((v >> 24) & 0xffu);
}

static void write_exif_app1(struct byte_vec *out, unsigned width, unsigned height,
                            const struct virtual_lens_hud_state *hud) {
    uint8_t tiff[1024];
    memset(tiff, 0, sizeof tiff);
    /* Little-endian TIFF header ("II", 42, IFD0 offset = 8). */
    tiff[0] = 'I'; tiff[1] = 'I';
    put_le16(tiff + 2, 42);
    put_le32(tiff + 4, 8);

    const char *make = "SONY";
    const char *model = "ILCE-7CM2";
    const char *software = "ILCE-7CM2 v2.01 QEMU Virtual CMOS";
    const char *lens = (hud && hud->lens_name[0]) ? hud->lens_name : "Virtual 35mm F4.0";

    char dt[24];
    time_t now = time(NULL);
    struct tm tm_val;
    if (now > 946684800 && localtime_r(&now, &tm_val)) {
        snprintf(dt, sizeof dt, "%04d:%02d:%02d %02d:%02d:%02d",
                 tm_val.tm_year + 1900, tm_val.tm_mon + 1, tm_val.tm_mday,
                 tm_val.tm_hour, tm_val.tm_min, tm_val.tm_sec);
    } else {
        snprintf(dt, sizeof dt, "2026:11:22 12:00:00");
    }

    uint32_t sh_num = (hud && hud->shutter_num) ? hud->shutter_num : 1u;
    uint32_t sh_den = (hud && hud->shutter_den) ? hud->shutter_den : 125u;
    uint32_t f_num = (hud && hud->aperture_x100) ? hud->aperture_x100 : 400u;
    uint32_t f_den = 100u;
    uint16_t iso = (uint16_t)(hud ? virtual_lens_hud_iso_value(hud->iso_cp_byte) : 100u);

    /* IFD0 at offset 8: 6 entries -> 2 + 6*12 + 4 = 78 bytes (ends at 86). */
    size_t ifd0 = 8;
    size_t exif_ifd = 92; /* 9 entries -> 2 + 9*12 + 4 = 114 bytes (ends at 206). */
    size_t data_off = 212;

    size_t p = ifd0;
    put_le16(tiff + p, 6); p += 2;
    /* 0x010f Make */
    put_le16(tiff + p, 0x010f); put_le16(tiff + p + 2, 2); put_le32(tiff + p + 4, (uint32_t)strlen(make) + 1);
    put_le32(tiff + p + 8, (uint32_t)data_off);
    memcpy(tiff + data_off, make, strlen(make) + 1); data_off += strlen(make) + 1; p += 12;
    /* 0x0110 Model */
    put_le16(tiff + p, 0x0110); put_le16(tiff + p + 2, 2); put_le32(tiff + p + 4, (uint32_t)strlen(model) + 1);
    put_le32(tiff + p + 8, (uint32_t)data_off);
    memcpy(tiff + data_off, model, strlen(model) + 1); data_off += strlen(model) + 1; p += 12;
    /* 0x0112 Orientation = 1 */
    put_le16(tiff + p, 0x0112); put_le16(tiff + p + 2, 3); put_le32(tiff + p + 4, 1); put_le16(tiff + p + 8, 1); p += 12;
    /* 0x0131 Software */
    put_le16(tiff + p, 0x0131); put_le16(tiff + p + 2, 2); put_le32(tiff + p + 4, (uint32_t)strlen(software) + 1);
    put_le32(tiff + p + 8, (uint32_t)data_off);
    memcpy(tiff + data_off, software, strlen(software) + 1); data_off += strlen(software) + 1; p += 12;
    /* 0x0132 DateTime */
    put_le16(tiff + p, 0x0132); put_le16(tiff + p + 2, 2); put_le32(tiff + p + 4, 20);
    put_le32(tiff + p + 8, (uint32_t)data_off);
    memcpy(tiff + data_off, dt, 20); data_off += 20; p += 12;
    /* 0x8769 ExifIFDPointer */
    put_le16(tiff + p, 0x8769); put_le16(tiff + p + 2, 4); put_le32(tiff + p + 4, 1); put_le32(tiff + p + 8, (uint32_t)exif_ifd); p += 12;
    put_le32(tiff + p, 0); /* next IFD = 0 */

    /* ExifIFD: 9 entries (strictly sorted by tag). */
    p = exif_ifd;
    put_le16(tiff + p, 9); p += 2;
    /* 0x829a ExposureTime (RATIONAL) */
    data_off = (data_off + 3u) & ~3u;
    put_le16(tiff + p, 0x829a); put_le16(tiff + p + 2, 5); put_le32(tiff + p + 4, 1); put_le32(tiff + p + 8, (uint32_t)data_off);
    put_le32(tiff + data_off, sh_num); put_le32(tiff + data_off + 4, sh_den); data_off += 8; p += 12;
    /* 0x829d FNumber (RATIONAL) */
    put_le16(tiff + p, 0x829d); put_le16(tiff + p + 2, 5); put_le32(tiff + p + 4, 1); put_le32(tiff + p + 8, (uint32_t)data_off);
    put_le32(tiff + data_off, f_num); put_le32(tiff + data_off + 4, f_den); data_off += 8; p += 12;
    /* 0x8827 ISOSpeedRatings (SHORT) */
    put_le16(tiff + p, 0x8827); put_le16(tiff + p + 2, 3); put_le32(tiff + p + 4, 1); put_le16(tiff + p + 8, iso); p += 12;
    /* 0x9000 ExifVersion (UNDEFINED, 4 bytes inline) */
    put_le16(tiff + p, 0x9000); put_le16(tiff + p + 2, 7); put_le32(tiff + p + 4, 4);
    memcpy(tiff + p + 8, "0232", 4); p += 12;
    /* 0x9003 DateTimeOriginal (ASCII) */
    put_le16(tiff + p, 0x9003); put_le16(tiff + p + 2, 2); put_le32(tiff + p + 4, 20);
    put_le32(tiff + p + 8, (uint32_t)data_off);
    memcpy(tiff + data_off, dt, 20); data_off += 20; p += 12;
    /* 0x9004 DateTimeDigitized (ASCII) */
    put_le16(tiff + p, 0x9004); put_le16(tiff + p + 2, 2); put_le32(tiff + p + 4, 20);
    put_le32(tiff + p + 8, (uint32_t)data_off);
    memcpy(tiff + data_off, dt, 20); data_off += 20; p += 12;
    /* 0xa002 PixelXDimension (LONG) */
    put_le16(tiff + p, 0xa002); put_le16(tiff + p + 2, 4); put_le32(tiff + p + 4, 1); put_le32(tiff + p + 8, width); p += 12;
    /* 0xa003 PixelYDimension (LONG) */
    put_le16(tiff + p, 0xa003); put_le16(tiff + p + 2, 4); put_le32(tiff + p + 4, 1); put_le32(tiff + p + 8, height); p += 12;
    /* 0xa434 LensModel (ASCII) */
    size_t lens_len = strnlen(lens, 64) + 1;
    put_le16(tiff + p, 0xa434); put_le16(tiff + p + 2, 2); put_le32(tiff + p + 4, (uint32_t)lens_len); put_le32(tiff + p + 8, (uint32_t)data_off);
    memcpy(tiff + data_off, lens, lens_len - 1); tiff[data_off + lens_len - 1] = 0; data_off += lens_len; p += 12;
    put_le32(tiff + p, 0);

    bv_push(out, 0xff); bv_push(out, 0xe1);
    bv_be16(out, (uint16_t)(2 + 6 + data_off));
    bv_write(out, "Exif\0\0", 6);
    bv_write(out, tiff, data_off);
}

static void write_dqt(struct byte_vec *out, uint8_t id, const uint8_t qtbl[64]) {
    bv_push(out, 0xff); bv_push(out, 0xdb);
    bv_be16(out, 67);
    bv_push(out, id);
    for (int k = 0; k < 64; ++k) bv_push(out, qtbl[k_zigzag[k]]);
}

static void write_dht(struct byte_vec *out, uint8_t tc_th, const uint8_t bits[16], const uint8_t *vals, size_t nvals) {
    bv_push(out, 0xff); bv_push(out, 0xc4);
    bv_be16(out, (uint16_t)(2 + 1 + 16 + nvals));
    bv_push(out, tc_th);
    bv_write(out, bits, 16);
    bv_write(out, vals, nvals);
}

int virtual_cmos_encode_jpeg(const uint8_t *rgb, unsigned width, unsigned height,
                             const struct virtual_lens_hud_state *hud,
                             uint8_t **out_buf, size_t *out_len) {
    if (!rgb || !width || !height || width > 4096 || height > 4096 || !out_buf || !out_len)
        return -EINVAL;
    *out_buf = NULL;
    *out_len = 0;

    struct huff_enc_table dc_y, ac_y, dc_c, ac_c;
    build_huff_enc(k_bits_dc_y, k_vals_dc_y, &dc_y);
    build_huff_enc(k_bits_ac_y, k_vals_ac_y, &ac_y);
    build_huff_enc(k_bits_dc_c, k_vals_dc_c, &dc_c);
    build_huff_enc(k_bits_ac_c, k_vals_ac_c, &ac_c);

    struct byte_vec out = {0};
    bv_push(&out, 0xff); bv_push(&out, 0xd8); /* SOI */
    write_exif_app1(&out, width, height, hud);
    write_dqt(&out, 0, k_qtable_y);
    write_dqt(&out, 1, k_qtable_c);

    /* SOF0: 8-bit Baseline DCT, 3 components (4:2:0 subsampling). */
    bv_push(&out, 0xff); bv_push(&out, 0xc0);
    bv_be16(&out, 17);
    bv_push(&out, 8);
    bv_be16(&out, (uint16_t)height);
    bv_be16(&out, (uint16_t)width);
    bv_push(&out, 3);
    bv_push(&out, 1); bv_push(&out, 0x22); bv_push(&out, 0); /* Y: 2x2, q=0 */
    bv_push(&out, 2); bv_push(&out, 0x11); bv_push(&out, 1); /* Cb: 1x1, q=1 */
    bv_push(&out, 3); bv_push(&out, 0x11); bv_push(&out, 1); /* Cr: 1x1, q=1 */

    write_dht(&out, 0x00, k_bits_dc_y, k_vals_dc_y, sizeof k_vals_dc_y);
    write_dht(&out, 0x10, k_bits_ac_y, k_vals_ac_y, sizeof k_vals_ac_y);
    write_dht(&out, 0x01, k_bits_dc_c, k_vals_dc_c, sizeof k_vals_dc_c);
    write_dht(&out, 0x11, k_bits_ac_c, k_vals_ac_c, sizeof k_vals_ac_c);

    /* SOS */
    bv_push(&out, 0xff); bv_push(&out, 0xda);
    bv_be16(&out, 12);
    bv_push(&out, 3);
    bv_push(&out, 1); bv_push(&out, 0x00);
    bv_push(&out, 2); bv_push(&out, 0x11);
    bv_push(&out, 3); bv_push(&out, 0x11);
    bv_push(&out, 0); bv_push(&out, 63); bv_push(&out, 0);

    struct bit_writer bw = {&out, 0, 0};
    int prev_y = 0, prev_cb = 0, prev_cr = 0;

    for (unsigned my = 0; my < height; my += 16) {
        for (unsigned mx = 0; mx < width; mx += 16) {
            int16_t yb[4][64];
            int16_t cbb[64];
            int16_t crb[64];
            for (unsigned dy = 0; dy < 16; ++dy) {
                unsigned sy = my + dy < height ? my + dy : height - 1;
                for (unsigned dx = 0; dx < 16; ++dx) {
                    unsigned sx = mx + dx < width ? mx + dx : width - 1;
                    const uint8_t *px = rgb + ((size_t)sy * width + sx) * 3u;
                    int r = px[0], g = px[1], b = px[2];
                    int y  = (( 19595 * r + 38470 * g +  7471 * b + 32768) >> 16) - 128;
                    unsigned bi = ((dy >> 3) << 1) | (dx >> 3);
                    yb[bi][(dy & 7) * 8 + (dx & 7)] = (int16_t)y;
                }
            }
            for (unsigned cy = 0; cy < 8; ++cy) {
                for (unsigned cx = 0; cx < 8; ++cx) {
                    int rs = 0, gs = 0, bs = 0;
                    for (unsigned sy2 = 0; sy2 < 2; ++sy2) {
                        unsigned sy = my + cy * 2 + sy2;
                        if (sy >= height) sy = height - 1;
                        for (unsigned sx2 = 0; sx2 < 2; ++sx2) {
                            unsigned sx = mx + cx * 2 + sx2;
                            if (sx >= width) sx = width - 1;
                            const uint8_t *px = rgb + ((size_t)sy * width + sx) * 3u;
                            rs += px[0]; gs += px[1]; bs += px[2];
                        }
                    }
                    int r = (rs + 2) >> 2, g = (gs + 2) >> 2, b = (bs + 2) >> 2;
                    int cb = (-11056 * r - 21712 * g + 32768 * b + 32768) >> 16;
                    int cr = ( 32768 * r - 27440 * g -  5328 * b + 32768) >> 16;
                    cbb[cy * 8 + cx] = (int16_t)cb;
                    crb[cy * 8 + cx] = (int16_t)cr;
                }
            }
            for (int bi = 0; bi < 4; ++bi) encode_block(&bw, yb[bi], k_qtable_y, &dc_y, &ac_y, &prev_y);
            encode_block(&bw, cbb, k_qtable_c, &dc_c, &ac_c, &prev_cb);
            encode_block(&bw, crb, k_qtable_c, &dc_c, &ac_c, &prev_cr);
        }
    }
    bw_flush(&bw);
    bv_push(&out, 0xff); bv_push(&out, 0xd9); /* EOI */
    if (out.error) {
        free(out.data);
        return out.error;
    }
    *out_buf = out.data;
    *out_len = out.len;
    return 0;
}

/* --- Minimal Baseline DCT JPEG Decoder + Exif summary parser --- */

static uint16_t rd_be16(const uint8_t *p) { return (uint16_t)((uint16_t)p[0] << 8 | p[1]); }
static uint16_t rd_le16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }
static uint32_t rd_le32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint32_t rd_be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static void parse_exif_summary(const uint8_t *payload, size_t len, char *out, size_t cap) {
    if (!out || !cap || len < 14 || memcmp(payload, "Exif\0\0", 6) != 0) return;
    const uint8_t *t = payload + 6;
    size_t tlen = len - 6;
    int le;
    if (t[0] == 'I' && t[1] == 'I') le = 1;
    else if (t[0] == 'M' && t[1] == 'M') le = 0;
    else return;
    uint32_t ifd0 = le ? rd_le32(t + 4) : rd_be32(t + 4);
    if (ifd0 + 2 > tlen) return;
    uint16_t n0 = le ? rd_le16(t + ifd0) : rd_be16(t + ifd0);
    uint32_t exif_off = 0;
    for (uint16_t i = 0; i < n0; ++i) {
        size_t e = ifd0 + 2 + (size_t)i * 12;
        if (e + 12 > tlen) break;
        uint16_t tag = le ? rd_le16(t + e) : rd_be16(t + e);
        if (tag == 0x8769) {
            exif_off = le ? rd_le32(t + e + 8) : rd_be32(t + e + 8);
            break;
        }
    }
    if (!exif_off || exif_off + 2 > tlen) return;
    uint16_t ne = le ? rd_le16(t + exif_off) : rd_be16(t + exif_off);
    uint32_t sh_num = 0, sh_den = 0, f_num = 0, f_den = 0, iso = 0;
    for (uint16_t i = 0; i < ne; ++i) {
        size_t e = exif_off + 2 + (size_t)i * 12;
        if (e + 12 > tlen) break;
        uint16_t tag = le ? rd_le16(t + e) : rd_be16(t + e);
        uint32_t val = le ? rd_le32(t + e + 8) : rd_be32(t + e + 8);
        if (tag == 0x829a && val + 8 <= tlen) {
            sh_num = le ? rd_le32(t + val) : rd_be32(t + val);
            sh_den = le ? rd_le32(t + val + 4) : rd_be32(t + val + 4);
        } else if (tag == 0x829d && val + 8 <= tlen) {
            f_num = le ? rd_le32(t + val) : rd_be32(t + val);
            f_den = le ? rd_le32(t + val + 4) : rd_be32(t + val + 4);
        } else if (tag == 0x8827) {
            iso = le ? rd_le16(t + e + 8) : rd_be16(t + e + 8);
        }
    }
    char ss[24] = "", ap[24] = "", isos[24] = "";
    if (sh_num && sh_den) {
        if (sh_den == 1) snprintf(ss, sizeof ss, "%u\"", sh_num);
        else snprintf(ss, sizeof ss, "%u/%u", sh_num, sh_den);
    }
    if (f_num && f_den) {
        unsigned fx10 = (f_num * 10u + f_den / 2u) / f_den;
        snprintf(ap, sizeof ap, "F%u.%u", fx10 / 10u, fx10 % 10u);
    }
    if (iso) snprintf(isos, sizeof isos, "ISO %u", iso);
    if (ss[0] || ap[0] || isos[0]) {
        snprintf(out, cap, "%s  %s  %s", ss[0] ? ss : "--", ap[0] ? ap : "F--", isos[0] ? isos : "ISO --");
    }
}

struct huff_dec_table {
    int present;
    uint16_t mincode[17];
    int32_t maxcode[17];
    int32_t valptr[17];
    uint8_t vals[256];
};

struct bit_reader {
    const uint8_t *data;
    size_t len;
    size_t pos;
    uint32_t bitbuf;
    int bitcount;
    int error;
};

static int br_next_byte(struct bit_reader *br) {
    if (br->pos >= br->len) { br->error = -EPROTO; return 0; }
    uint8_t b = br->data[br->pos++];
    if (b == 0xffu) {
        if (br->pos >= br->len) { br->error = -EPROTO; return 0; }
        uint8_t next = br->data[br->pos++];
        if (next != 0x00u) {
            /* Hit a marker prematurely; rewind so caller sees end of scan. */
            br->pos -= 2;
            br->error = -EPROTO;
            return 0;
        }
    }
    return b;
}

static int br_get_bits(struct bit_reader *br, int n) {
    if (!n) return 0;
    while (br->bitcount < n) {
        int b = br_next_byte(br);
        if (br->error) return 0;
        br->bitbuf = (br->bitbuf << 8) | (uint32_t)b;
        br->bitcount += 8;
    }
    br->bitcount -= n;
    return (int)((br->bitbuf >> br->bitcount) & ((1u << n) - 1u));
}

static int br_decode_huff(struct bit_reader *br, const struct huff_dec_table *tbl) {
    if (!tbl->present) { br->error = -EPROTO; return 0; }
    int32_t code = 0;
    for (int len = 1; len <= 16; ++len) {
        code = (code << 1) | br_get_bits(br, 1);
        if (br->error) return 0;
        if (code <= tbl->maxcode[len]) {
            int idx = tbl->valptr[len] + (code - tbl->mincode[len]);
            if (idx < 0 || idx >= 256) { br->error = -EPROTO; return 0; }
            return tbl->vals[idx];
        }
    }
    br->error = -EPROTO;
    return 0;
}

static int br_extend(int v, int n) {
    if (n <= 0) return 0;
    int vt = 1 << (n - 1);
    return v < vt ? v - (1 << n) + 1 : v;
}

struct jpg_comp {
    uint8_t id, h, v, qid, dc_id, ac_id;
    int prev_dc;
};

int virtual_cmos_decode_jpeg(const uint8_t *jpeg, size_t jpeg_len,
                             uint8_t *rgb640x480,
                             unsigned *src_width, unsigned *src_height,
                             char *exif_summary, size_t exif_cap) {
    if (!jpeg || jpeg_len < 4 || !rgb640x480) return -EINVAL;
    if (jpeg[0] != 0xff || jpeg[1] != 0xd8) return -EPROTO;
    if (exif_summary && exif_cap) exif_summary[0] = 0;

    uint16_t qtables[4][64];
    int qpresent[4] = {0, 0, 0, 0};
    struct huff_dec_table dc_tbl[4];
    struct huff_dec_table ac_tbl[4];
    memset(dc_tbl, 0, sizeof dc_tbl);
    memset(ac_tbl, 0, sizeof ac_tbl);

    unsigned width = 0, height = 0, ncomp = 0;
    struct jpg_comp comps[3];
    memset(comps, 0, sizeof comps);
    unsigned restart_interval = 0;
    size_t pos = 2;
    size_t scan_start = 0;

    while (pos + 2 <= jpeg_len) {
        if (jpeg[pos] != 0xff) return -EPROTO;
        while (pos < jpeg_len && jpeg[pos] == 0xff) ++pos;
        if (pos >= jpeg_len) break;
        uint8_t marker = jpeg[pos++];
        if (marker == 0xd9) break;
        if (marker == 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
        if (pos + 2 > jpeg_len) return -EPROTO;
        uint16_t seg_len = rd_be16(jpeg + pos);
        if (seg_len < 2 || pos + seg_len > jpeg_len) return -EPROTO;
        const uint8_t *seg = jpeg + pos + 2;
        size_t slen = seg_len - 2;
        pos += seg_len;

        if (marker == 0xe1 && exif_summary && exif_cap) {
            parse_exif_summary(seg, slen, exif_summary, exif_cap);
        } else if (marker == 0xdb) { /* DQT */
            size_t o = 0;
            while (o < slen) {
                uint8_t pq_tq = seg[o++];
                uint8_t pq = pq_tq >> 4, tq = pq_tq & 15;
                if (tq >= 4 || pq > 1) return -ENOTSUP;
                size_t need = pq ? 128 : 64;
                if (o + need > slen) return -EPROTO;
                for (int k = 0; k < 64; ++k) {
                    qtables[tq][k_zigzag[k]] = pq ? rd_be16(seg + o + 2 * k) : seg[o + k];
                }
                qpresent[tq] = 1;
                o += need;
            }
        } else if (marker == 0xc4) { /* DHT */
            size_t o = 0;
            while (o < slen) {
                if (o + 17 > slen) return -EPROTO;
                uint8_t tc_th = seg[o++];
                uint8_t tc = tc_th >> 4, th = tc_th & 15;
                if (tc > 1 || th >= 4) return -ENOTSUP;
                struct huff_dec_table *tbl = tc ? &ac_tbl[th] : &dc_tbl[th];
                const uint8_t *counts = seg + o;
                o += 16;
                unsigned total = 0;
                for (int i = 0; i < 16; ++i) total += counts[i];
                if (total > 256 || o + total > slen) return -EPROTO;
                memcpy(tbl->vals, seg + o, total);
                o += total;
                int32_t code = 0;
                int val_i = 0;
                for (int len = 1; len <= 16; ++len) {
                    if (counts[len - 1] == 0) {
                        tbl->maxcode[len] = -1;
                        tbl->mincode[len] = 0;
                        tbl->valptr[len] = 0;
                    } else {
                        tbl->valptr[len] = val_i;
                        tbl->mincode[len] = (uint16_t)code;
                        val_i += counts[len - 1];
                        code += counts[len - 1];
                        tbl->maxcode[len] = code - 1;
                    }
                    code <<= 1;
                }
                tbl->present = 1;
            }
        } else if (marker == 0xc0) { /* SOF0 Baseline */
            if (slen < 6 || seg[0] != 8) return -ENOTSUP;
            height = rd_be16(seg + 1);
            width = rd_be16(seg + 3);
            ncomp = seg[5];
            if (!width || !height || width > 4096 || height > 4096 || (ncomp != 1 && ncomp != 3))
                return -ENOTSUP;
            if (slen < 6 + ncomp * 3) return -EPROTO;
            for (unsigned c = 0; c < ncomp; ++c) {
                comps[c].id = seg[6 + c * 3];
                comps[c].h = seg[6 + c * 3 + 1] >> 4;
                comps[c].v = seg[6 + c * 3 + 1] & 15;
                comps[c].qid = seg[6 + c * 3 + 2];
                if (comps[c].h < 1 || comps[c].h > 2 || comps[c].v < 1 || comps[c].v > 2 || comps[c].qid >= 4)
                    return -ENOTSUP;
            }
        } else if (marker == 0xdd) { /* DRI */
            if (slen >= 2) restart_interval = rd_be16(seg);
        } else if (marker == 0xda) { /* SOS */
            if (!width || !height || !ncomp || slen < 1 + ncomp * 2 + 3) return -EPROTO;
            if (seg[0] != ncomp) return -ENOTSUP;
            for (unsigned c = 0; c < ncomp; ++c) {
                uint8_t cid = seg[1 + c * 2];
                uint8_t td_ta = seg[1 + c * 2 + 1];
                int found = 0;
                for (unsigned j = 0; j < ncomp; ++j) {
                    if (comps[j].id == cid) {
                        comps[j].dc_id = td_ta >> 4;
                        comps[j].ac_id = td_ta & 15;
                        if (comps[j].dc_id >= 4 || comps[j].ac_id >= 4) return -EPROTO;
                        found = 1;
                        break;
                    }
                }
                if (!found) return -EPROTO;
            }
            scan_start = pos;
            break;
        }
    }

    if (!scan_start || !width || !height || !ncomp) return -EPROTO;
    for (unsigned c = 0; c < ncomp; ++c) {
        if (!qpresent[comps[c].qid] || !dc_tbl[comps[c].dc_id].present || !ac_tbl[comps[c].ac_id].present)
            return -EPROTO;
    }

    unsigned max_h = 1, max_v = 1;
    for (unsigned c = 0; c < ncomp; ++c) {
        if (comps[c].h > max_h) max_h = comps[c].h;
        if (comps[c].v > max_v) max_v = comps[c].v;
    }
    unsigned mcu_w = max_h * 8, mcu_h = max_v * 8;
    unsigned mcus_x = (width + mcu_w - 1) / mcu_w;
    unsigned mcus_y = (height + mcu_h - 1) / mcu_h;

    uint8_t *full_rgb = (width == VIRTUAL_CMOS_W && height == VIRTUAL_CMOS_H)
        ? rgb640x480
        : malloc((size_t)width * height * 3u);
    if (!full_rgb) return -ENOMEM;

    struct bit_reader br = {jpeg, jpeg_len, scan_start, 0, 0, 0};
    unsigned mcu_count = 0;

    for (unsigned my = 0; my < mcus_y && !br.error; ++my) {
        for (unsigned mx = 0; mx < mcus_x && !br.error; ++mx) {
            if (restart_interval && mcu_count && (mcu_count % restart_interval) == 0) {
                br.bitbuf = 0;
                br.bitcount = 0;
                while (br.pos + 1 < br.len && jpeg[br.pos] == 0xff && jpeg[br.pos + 1] == 0xff) ++br.pos;
                if (br.pos + 1 < br.len && jpeg[br.pos] == 0xff &&
                    jpeg[br.pos + 1] >= 0xd0 && jpeg[br.pos + 1] <= 0xd7) {
                    br.pos += 2;
                }
                for (unsigned c = 0; c < ncomp; ++c) comps[c].prev_dc = 0;
            }
            ++mcu_count;

            int16_t comp_buf[3][256]; /* up to 16x16 per component */
            for (unsigned c = 0; c < ncomp && !br.error; ++c) {
                const uint16_t *qt = qtables[comps[c].qid];
                const struct huff_dec_table *dt = &dc_tbl[comps[c].dc_id];
                const struct huff_dec_table *at = &ac_tbl[comps[c].ac_id];
                for (unsigned bv = 0; bv < comps[c].v && !br.error; ++bv) {
                    for (unsigned bh = 0; bh < comps[c].h && !br.error; ++bh) {
                        int32_t coeff[64];
                        memset(coeff, 0, sizeof coeff);
                        int dc_cat = br_decode_huff(&br, dt);
                        if (br.error) break;
                        int dc_diff = br_extend(br_get_bits(&br, dc_cat), dc_cat);
                        comps[c].prev_dc += dc_diff;
                        coeff[0] = comps[c].prev_dc * (int32_t)qt[0];
                        for (int k = 1; k < 64; ) {
                            int rs = br_decode_huff(&br, at);
                            if (br.error) break;
                            if (rs == 0) break;
                            int run = rs >> 4;
                            int size = rs & 15;
                            if (rs == 0xf0) { k += 16; continue; }
                            k += run;
                            if (k >= 64) { br.error = -EPROTO; break; }
                            int val = br_extend(br_get_bits(&br, size), size);
                            int nat = k_zigzag[k];
                            coeff[nat] = val * (int32_t)qt[nat];
                            ++k;
                        }
                        if (br.error) break;
                        int16_t spatial[64];
                        idct8x8(coeff, spatial);
                        unsigned stride = comps[c].h * 8;
                        for (unsigned y = 0; y < 8; ++y) {
                            for (unsigned x = 0; x < 8; ++x) {
                                comp_buf[c][(bv * 8 + y) * stride + (bh * 8 + x)] = spatial[y * 8 + x];
                            }
                        }
                    }
                }
            }
            if (br.error) break;

            for (unsigned dy = 0; dy < mcu_h; ++dy) {
                unsigned py = my * mcu_h + dy;
                if (py >= height) break;
                for (unsigned dx = 0; dx < mcu_w; ++dx) {
                    unsigned px = mx * mcu_w + dx;
                    if (px >= width) break;
                    unsigned y_x = (dx * comps[0].h) / max_h;
                    unsigned y_y = (dy * comps[0].v) / max_v;
                    int yv = comp_buf[0][y_y * (comps[0].h * 8) + y_x] + 128;
                    int r, g, b;
                    if (ncomp == 1) {
                        r = g = b = clamp_u8(yv);
                    } else {
                        unsigned cb_x = (dx * comps[1].h) / max_h;
                        unsigned cb_y = (dy * comps[1].v) / max_v;
                        unsigned cr_x = (dx * comps[2].h) / max_h;
                        unsigned cr_y = (dy * comps[2].v) / max_v;
                        int cb = comp_buf[1][cb_y * (comps[1].h * 8) + cb_x];
                        int cr = comp_buf[2][cr_y * (comps[2].h * 8) + cr_x];
                        r = clamp_u8(yv + ((91881 * cr + 32768) >> 16));
                        g = clamp_u8(yv - ((22554 * cb + 46802 * cr + 32768) >> 16));
                        b = clamp_u8(yv + ((116130 * cb + 32768) >> 16));
                    }
                    uint8_t *dst = full_rgb + ((size_t)py * width + px) * 3u;
                    dst[0] = (uint8_t)r; dst[1] = (uint8_t)g; dst[2] = (uint8_t)b;
                }
            }
        }
    }

    if (br.error) {
        if (full_rgb != rgb640x480) free(full_rgb);
        return br.error;
    }

    if (full_rgb != rgb640x480) {
        /* Aspect-preserving fit onto 640x480 black canvas. */
        memset(rgb640x480, 0, VIRTUAL_CMOS_RGB_BYTES);
        unsigned dw = VIRTUAL_CMOS_W, dh = VIRTUAL_CMOS_H;
        if (width * VIRTUAL_CMOS_H >= height * VIRTUAL_CMOS_W) {
            dh = (height * VIRTUAL_CMOS_W) / width;
            if (!dh) dh = 1;
        } else {
            dw = (width * VIRTUAL_CMOS_H) / height;
            if (!dw) dw = 1;
        }
        unsigned ox = (VIRTUAL_CMOS_W - dw) / 2;
        unsigned oy = (VIRTUAL_CMOS_H - dh) / 2;
        for (unsigned y = 0; y < dh; ++y) {
            unsigned sy = (y * height) / dh;
            for (unsigned x = 0; x < dw; ++x) {
                unsigned sx = (x * width) / dw;
                memcpy(rgb640x480 + ((size_t)(oy + y) * VIRTUAL_CMOS_W + (ox + x)) * 3u,
                       full_rgb + ((size_t)sy * width + sx) * 3u, 3u);
            }
        }
        free(full_rgb);
    }
    if (src_width) *src_width = width;
    if (src_height) *src_height = height;
    return 0;
}

/* --- Active CMOS frame loader --- */

static int read_all_fd(int fd, uint8_t *buf, size_t n) {
    while (n) {
        ssize_t got = read(fd, buf, n);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) return -1;
        buf += got;
        n -= (size_t)got;
    }
    return 0;
}

static int (*g_custom_rgb_provider)(uint8_t *rgb_out);

void virtual_cmos_set_custom_rgb_provider(int (*provider)(uint8_t *rgb_out)) {
    g_custom_rgb_provider = provider;
}

int virtual_cmos_load_active_rgb(const char *custom_rgb_path,
                                 uint8_t *rgb_out,
                                 char *source_out, size_t source_cap) {
    if (!rgb_out) return -EINVAL;
    if (g_custom_rgb_provider && g_custom_rgb_provider(rgb_out) == 1) {
        if (source_out && source_cap) snprintf(source_out, source_cap, "custom");
        return 0;
    }
    if (custom_rgb_path && custom_rgb_path[0]) {
        int fd = open(custom_rgb_path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
        if (fd >= 0) {
            struct stat st;
            int ok = !vcmos_fstat(fd, &st) && S_ISREG(st.st_mode) &&
                     (size_t)st.st_size == VIRTUAL_CMOS_RGB_BYTES &&
                     read_all_fd(fd, rgb_out, VIRTUAL_CMOS_RGB_BYTES) == 0;
            close(fd);
            if (ok) {
                if (source_out && source_cap) snprintf(source_out, source_cap, "custom");
                return 0;
            }
        }
    }
    sensor_config cfg = sensor_config_default();
    uint8_t *chart = sensor_frame_rgb(&cfg, sensor_token_next(&cfg, 0));
    if (!chart) return -ENOMEM;
    memcpy(rgb_out, chart, VIRTUAL_CMOS_RGB_BYTES);
    free(chart);
    if (source_out && source_cap) snprintf(source_out, source_cap, "chart");
    return 0;
}

/* --- Virtual SD Fsys capture writer --- */

static unsigned char first_mounted_drive(const struct virtual_cmos_fsys_ops *ops) {
    if (!ops || !ops->get_mount_drives) return 0;
    unsigned int mask = ops->get_mount_drives();
    for (unsigned i = 0; i < 26; ++i) {
        if (mask & (1u << i)) return (unsigned char)('A' + i);
    }
    return 0;
}

static int file_exists_fsys(const struct virtual_cmos_fsys_ops *ops, const char *path) {
    uint64_t handle = 0;
    if (ops->open_fn(path, &handle, 1u) != 0) return 0;
    ops->close_fn(handle);
    return 1;
}

static int vcmos_fsys_write_all(const struct virtual_cmos_fsys_ops *ops, uint64_t handle,
                                const uint8_t *buf, size_t len) {
    size_t written = 0u;
    while (written < len) {
        size_t chunk = len - written;
        if (chunk > 65536u) chunk = 65536u;
        int got = ops->write_fn(handle, buf + written, (int)chunk);
        if (got <= 0) return -EIO;
        written += (size_t)got;
    }
    return 0;
}

static int vcmos_pick_numbered_path(const struct virtual_cmos_fsys_ops *ops,
                                    unsigned char drive, const char *fmt,
                                    uint32_t last_num, uint32_t *chosen_out,
                                    char *path_out, size_t path_cap) {
    uint32_t start = last_num ? last_num + 1u : 1u;
    if (start > 9999u) start = 1u;
    for (uint32_t n = start; n <= 9999u; ++n) {
        snprintf(path_out, path_cap, fmt, drive, n);
        if (!file_exists_fsys(ops, path_out)) { *chosen_out = n; return 0; }
    }
    for (uint32_t n = 1u; n < start; ++n) {
        snprintf(path_out, path_cap, fmt, drive, n);
        if (!file_exists_fsys(ops, path_out)) { *chosen_out = n; return 0; }
    }
    return -ENOSPC;
}

static uint32_t g_last_capture_num;
static uint32_t g_last_movie_num;

int virtual_cmos_capture_to_sd(const struct virtual_cmos_fsys_ops *ops,
                               const char *custom_rgb_path,
                               const struct virtual_lens_hud_state *hud,
                               struct virtual_cmos_capture_result *result) {
    if (!ops || !ops->get_mount_drives || !ops->mkdir_fn || !ops->open_fn ||
        !ops->write_fn || !ops->read_fn || !ops->flush_fn || !ops->close_fn ||
        !ops->flush_volume_fn || !result)
        return -EINVAL;
    memset(result, 0, sizeof *result);

    unsigned char drive = first_mounted_drive(ops);
    if (!drive) return -ENODEV;

    uint8_t *rgb = malloc(VIRTUAL_CMOS_RGB_BYTES);
    if (!rgb) return -ENOMEM;
    int rc = virtual_cmos_load_active_rgb(custom_rgb_path, rgb, result->source, sizeof result->source);
    if (rc) { free(rgb); return rc; }

    uint8_t *jpeg = NULL;
    size_t jpeg_len = 0;
    rc = virtual_cmos_encode_jpeg(rgb, VIRTUAL_CMOS_W, VIRTUAL_CMOS_H, hud, &jpeg, &jpeg_len);
    free(rgb);
    if (rc) return rc;

    char dir_dcim[32], dir_dcf[48];
    snprintf(dir_dcim, sizeof dir_dcim, "%c:/DCIM", drive);
    snprintf(dir_dcf, sizeof dir_dcf, "%c:/DCIM/100MSDCF", drive);
    (void)ops->mkdir_fn(dir_dcim);
    (void)ops->mkdir_fn(dir_dcf);

    uint32_t chosen = 0;
    char path[64];
    if (vcmos_pick_numbered_path(ops, drive, "%c:/DCIM/100MSDCF/DSC%05u.JPG",
                                 g_last_capture_num, &chosen, path, sizeof path) != 0) {
        free(jpeg);
        return -ENOSPC;
    }

    uint64_t handle = 0;
    if (ops->open_fn(path, &handle, 0xfu) != 0) { free(jpeg); return -EIO; }

    if (vcmos_fsys_write_all(ops, handle, jpeg, jpeg_len) != 0) {
        ops->close_fn(handle);
        free(jpeg);
        return -EIO;
    }
    int frc = ops->flush_fn(handle);
    int crc = ops->close_fn(handle);
    if (frc || crc) { free(jpeg); return -EIO; }

    uint64_t expected_hash = vcmos_fnv64(jpeg, jpeg_len);
    uint8_t *rb = malloc(jpeg_len);
    int verified = 0;
    if (rb) {
        uint64_t rh = 0;
        if (ops->open_fn(path, &rh, 1u) == 0) {
            size_t total = 0;
            while (total < jpeg_len) {
                size_t chunk = jpeg_len - total;
                if (chunk > 65536u) chunk = 65536u;
                int got = ops->read_fn(rh, rb + total, (int)chunk);
                if (got <= 0) break;
                total += (size_t)got;
            }
            ops->close_fn(rh);
            if (total == jpeg_len && memcmp(rb, jpeg, jpeg_len) == 0 &&
                vcmos_fnv64(rb, total) == expected_hash) {
                verified = 1;
            }
        }
        free(rb);
    }
    free(jpeg);
    if (!verified) return -EIO;
    if (ops->flush_volume_fn(drive) != 0) return -EIO;

    g_last_capture_num = chosen;
    snprintf(result->path, sizeof result->path, "%s", path);
    result->bytes = jpeg_len;
    result->fnv1a64 = expected_hash;
    result->file_number = chosen;
    result->readback_verified = 1;
    return 0;
}

void virtual_cmos_movie_abort(struct virtual_cmos_movie_writer *w,
                              const struct virtual_cmos_fsys_ops *ops) {
    if (!w) return;
    if (w->active && ops && w->handle && ops->close_fn) {
        (void)ops->close_fn(w->handle);
    }
    if (w->path[0] && ops && ops->remove_fn) {
        (void)ops->remove_fn(w->path);
    }
    memset(w, 0, sizeof *w);
}

int virtual_cmos_movie_begin(struct virtual_cmos_movie_writer *w,
                             const struct virtual_cmos_fsys_ops *ops) {
    if (!w || !ops || !ops->get_mount_drives || !ops->mkdir_fn || !ops->open_fn ||
        !ops->write_fn || !ops->read_fn || !ops->flush_fn || !ops->close_fn ||
        !ops->flush_volume_fn)
        return -EINVAL;
    if (w->active) virtual_cmos_movie_abort(w, ops);
    memset(w, 0, sizeof *w);

    unsigned char drive = first_mounted_drive(ops);
    if (!drive) return -ENODEV;

    char dir_priv[32], dir_m4[48], dir_clip[56];
    snprintf(dir_priv, sizeof dir_priv, "%c:/PRIVATE", drive);
    snprintf(dir_m4, sizeof dir_m4, "%c:/PRIVATE/M4ROOT", drive);
    snprintf(dir_clip, sizeof dir_clip, "%c:/PRIVATE/M4ROOT/CLIP", drive);
    (void)ops->mkdir_fn(dir_priv);
    (void)ops->mkdir_fn(dir_m4);
    (void)ops->mkdir_fn(dir_clip);

    uint32_t chosen = 0;
    char path[64];
    if (vcmos_pick_numbered_path(ops, drive, "%c:/PRIVATE/M4ROOT/CLIP/C%04u.MP4",
                                 g_last_movie_num, &chosen, path, sizeof path) != 0)
        return -ENOSPC;

    uint64_t handle = 0;
    if (ops->open_fn(path, &handle, 0xfu) != 0) return -EIO;

    w->active = 1;
    w->drive = drive;
    w->handle = handle;
    w->file_number = chosen;
    w->bytes_written = 0u;
    w->running_fnv1a64 = UINT64_C(14695981039346656037);
    snprintf(w->path, sizeof w->path, "%s", path);
    return 0;
}

int virtual_cmos_movie_write_chunk(struct virtual_cmos_movie_writer *w,
                                   const struct virtual_cmos_fsys_ops *ops,
                                   const uint8_t *data, size_t len) {
    if (!w || !ops || !ops->write_fn || !w->active) return -EINVAL;
    if (len == 0u) return 0;
    if (!data) return -EINVAL;
    if (vcmos_fsys_write_all(ops, w->handle, data, len) != 0) return -EIO;
    w->bytes_written += len;
    w->running_fnv1a64 = vcmos_fnv64_step(w->running_fnv1a64, data, len);
    return 0;
}

int virtual_cmos_movie_commit(struct virtual_cmos_movie_writer *w,
                              const struct virtual_cmos_fsys_ops *ops,
                              size_t expected_bytes,
                              uint64_t expected_fnv1a64,
                              struct virtual_cmos_capture_result *result) {
    if (!w || !ops || !ops->flush_fn || !ops->close_fn || !ops->open_fn ||
        !ops->read_fn || !ops->flush_volume_fn || !w->active || !result)
        return -EINVAL;
    memset(result, 0, sizeof *result);

    int frc = ops->flush_fn(w->handle);
    int crc = ops->close_fn(w->handle);
    w->handle = 0u;
    w->active = 0;
    if (frc || crc) {
        if (ops->remove_fn) (void)ops->remove_fn(w->path);
        return -EIO;
    }
    if (w->bytes_written != expected_bytes || w->running_fnv1a64 != expected_fnv1a64 ||
        expected_bytes == 0u) {
        if (ops->remove_fn) (void)ops->remove_fn(w->path);
        return -EIO;
    }

    uint8_t *rb = malloc(65536u);
    if (!rb) return -ENOMEM;
    uint64_t rh = 0u;
    int verified = 0;
    uint64_t rb_hash = UINT64_C(14695981039346656037);
    size_t total = 0u;
    if (ops->open_fn(w->path, &rh, 1u) == 0) {
        while (total < expected_bytes) {
            size_t want = expected_bytes - total;
            if (want > 65536u) want = 65536u;
            int got = ops->read_fn(rh, rb, (int)want);
            if (got <= 0) break;
            rb_hash = vcmos_fnv64_step(rb_hash, rb, (size_t)got);
            total += (size_t)got;
        }
        /* Confirm no trailing bytes exist beyond expected_bytes. */
        if (total == expected_bytes && ops->read_fn(rh, rb, 1) <= 0 &&
            rb_hash == expected_fnv1a64) {
            verified = 1;
        }
        ops->close_fn(rh);
    }
    free(rb);
    if (!verified) {
        if (ops->remove_fn) (void)ops->remove_fn(w->path);
        return -EIO;
    }
    if (ops->flush_volume_fn(w->drive) != 0) return -EIO;

    g_last_movie_num = w->file_number;
    snprintf(result->path, sizeof result->path, "%s", w->path);
    snprintf(result->source, sizeof result->source, "video");
    result->bytes = total;
    result->fnv1a64 = rb_hash;
    result->file_number = w->file_number;
    result->readback_verified = 1;
    return 0;
}

/* --- Minimal 5x7 ASCII bitmap font for Playback HUD overlay --- */

static void glyph5x7(char ch, uint8_t rows[7]) {
    if (ch >= 'a' && ch <= 'z') ch = (char)(ch - 'a' + 'A');
    memset(rows, 0, 7);
    static const struct { char c; uint8_t r[7]; } k_font[] = {
        {'0',{0x0e,0x11,0x13,0x15,0x19,0x11,0x0e}}, {'1',{0x04,0x0c,0x04,0x04,0x04,0x04,0x0e}},
        {'2',{0x0e,0x11,0x01,0x06,0x08,0x10,0x1f}}, {'3',{0x1f,0x02,0x04,0x02,0x01,0x11,0x0e}},
        {'4',{0x02,0x06,0x0a,0x12,0x1f,0x02,0x02}}, {'5',{0x1f,0x10,0x1e,0x01,0x01,0x11,0x0e}},
        {'6',{0x06,0x08,0x10,0x1e,0x11,0x11,0x0e}}, {'7',{0x1f,0x01,0x02,0x04,0x08,0x08,0x08}},
        {'8',{0x0e,0x11,0x11,0x0e,0x11,0x11,0x0e}}, {'9',{0x0e,0x11,0x11,0x0f,0x01,0x02,0x0c}},
        {'A',{0x0e,0x11,0x11,0x1f,0x11,0x11,0x11}}, {'B',{0x1e,0x11,0x11,0x1e,0x11,0x11,0x1e}},
        {'C',{0x0e,0x11,0x10,0x10,0x10,0x11,0x0e}}, {'D',{0x1c,0x12,0x11,0x11,0x11,0x12,0x1c}},
        {'E',{0x1f,0x10,0x10,0x1e,0x10,0x10,0x1f}}, {'F',{0x1f,0x10,0x10,0x1e,0x10,0x10,0x10}},
        {'G',{0x0e,0x11,0x10,0x17,0x11,0x11,0x0f}}, {'H',{0x11,0x11,0x11,0x1f,0x11,0x11,0x11}},
        {'I',{0x0e,0x04,0x04,0x04,0x04,0x04,0x0e}}, {'J',{0x07,0x02,0x02,0x02,0x02,0x12,0x0c}},
        {'K',{0x11,0x12,0x14,0x18,0x14,0x12,0x11}}, {'L',{0x10,0x10,0x10,0x10,0x10,0x10,0x1f}},
        {'M',{0x11,0x1b,0x15,0x15,0x11,0x11,0x11}}, {'N',{0x11,0x11,0x19,0x15,0x13,0x11,0x11}},
        {'O',{0x0e,0x11,0x11,0x11,0x11,0x11,0x0e}}, {'P',{0x1e,0x11,0x11,0x1e,0x10,0x10,0x10}},
        {'Q',{0x0e,0x11,0x11,0x11,0x15,0x12,0x0d}}, {'R',{0x1e,0x11,0x11,0x1e,0x14,0x12,0x11}},
        {'S',{0x0f,0x10,0x10,0x0e,0x01,0x01,0x1e}}, {'T',{0x1f,0x04,0x04,0x04,0x04,0x04,0x04}},
        {'U',{0x11,0x11,0x11,0x11,0x11,0x11,0x0e}}, {'V',{0x11,0x11,0x11,0x11,0x11,0x0a,0x04}},
        {'W',{0x11,0x11,0x11,0x15,0x15,0x15,0x0a}}, {'X',{0x11,0x11,0x0a,0x04,0x0a,0x11,0x11}},
        {'Y',{0x11,0x11,0x0a,0x04,0x04,0x04,0x04}}, {'Z',{0x1f,0x01,0x02,0x04,0x08,0x10,0x1f}},
        {'/',{0x01,0x02,0x02,0x04,0x08,0x08,0x10}}, {'-',{0x00,0x00,0x00,0x1f,0x00,0x00,0x00}},
        {'.',{0x00,0x00,0x00,0x00,0x00,0x0c,0x0c}}, {':',{0x00,0x0c,0x0c,0x00,0x0c,0x0c,0x00}},
        {'[',{0x0e,0x08,0x08,0x08,0x08,0x08,0x0e}}, {']',{0x0e,0x02,0x02,0x02,0x02,0x02,0x0e}},
        {'(',{0x02,0x04,0x08,0x08,0x08,0x04,0x02}}, {')',{0x08,0x04,0x02,0x02,0x02,0x04,0x08}},
        {'<',{0x02,0x04,0x08,0x10,0x08,0x04,0x02}}, {'>',{0x08,0x04,0x02,0x01,0x02,0x04,0x08}},
        {'|',{0x04,0x04,0x04,0x04,0x04,0x04,0x04}}, {'"',{0x0a,0x0a,0x00,0x00,0x00,0x00,0x00}},
        {'_',{0x00,0x00,0x00,0x00,0x00,0x00,0x1f}}, {'+',{0x00,0x04,0x04,0x1f,0x04,0x04,0x00}},
    };
    for (size_t i = 0; i < sizeof k_font / sizeof k_font[0]; ++i) {
        if (k_font[i].c == ch) { memcpy(rows, k_font[i].r, 7); return; }
    }
}

static void draw_bar(uint8_t *rgb, unsigned y0, unsigned y1) {
    for (unsigned y = y0; y < y1 && y < VIRTUAL_CMOS_H; ++y) {
        uint8_t *row = rgb + (size_t)y * VIRTUAL_CMOS_W * 3u;
        for (unsigned x = 0; x < VIRTUAL_CMOS_W * 3u; ++x) {
            row[x] = (uint8_t)(row[x] >> 2); /* 75% dark translucent band */
        }
    }
}

static void draw_text(uint8_t *rgb, unsigned x, unsigned y, const char *text,
                      unsigned scale, uint8_t r, uint8_t g, uint8_t b) {
    for (; *text; ++text) {
        uint8_t rows[7];
        glyph5x7(*text, rows);
        for (unsigned ry = 0; ry < 7; ++ry) {
            for (unsigned rx = 0; rx < 5; ++rx) {
                if (!(rows[ry] & (1u << (4 - rx)))) continue;
                for (unsigned sy = 0; sy < scale; ++sy) {
                    unsigned py = y + ry * scale + sy;
                    if (py >= VIRTUAL_CMOS_H) continue;
                    for (unsigned sx = 0; sx < scale; ++sx) {
                        unsigned px = x + rx * scale + sx;
                        if (px >= VIRTUAL_CMOS_W) continue;
                        uint8_t *p = rgb + ((size_t)py * VIRTUAL_CMOS_W + px) * 3u;
                        p[0] = r; p[1] = g; p[2] = b;
                    }
                }
            }
        }
        x += 6 * scale;
        if (x + 6 * scale >= VIRTUAL_CMOS_W) break;
    }
}

static int write_rgb_frame_with_magic(const char *frame_path, const char magic[8], uint32_t seq, const uint8_t *rgb) {
    if (!frame_path || !magic || !rgb) return -EINVAL;
    char tmp[512];
    int n = snprintf(tmp, sizeof tmp, "%s.tmp", frame_path);
    if (n <= 0 || n >= (int)sizeof tmp) return -ENAMETOOLONG;
    int fd = open(tmp, O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW, 0600);
    if (fd < 0) return -errno;
    uint8_t hdr[VIRTUAL_PLAYBACK_HEADER_BYTES];
    memcpy(hdr, magic, 8);
    put_le32(hdr + 8, seq);
    put_le16(hdr + 12, (uint16_t)VIRTUAL_CMOS_W);
    put_le16(hdr + 14, (uint16_t)VIRTUAL_CMOS_H);
    int ok = write(fd, hdr, sizeof hdr) == (ssize_t)sizeof hdr;
    size_t off = 0;
    while (ok && off < VIRTUAL_CMOS_RGB_BYTES) {
        ssize_t w = write(fd, rgb + off, VIRTUAL_CMOS_RGB_BYTES - off);
        if (w < 0 && errno == EINTR) continue;
        if (w <= 0) { ok = 0; break; }
        off += (size_t)w;
    }
    if (close(fd) != 0) ok = 0;
    if (!ok || rename(tmp, frame_path) != 0) {
        unlink(tmp);
        return -EIO;
    }
    return 0;
}

static int write_playback_frame(const char *frame_path, uint32_t seq, const uint8_t *rgb) {
    return write_rgb_frame_with_magic(frame_path, VIRTUAL_PLAYBACK_MAGIC, seq, rgb);
}

static void scan_sd_photos(struct virtual_cmos_playback_state *pb,
                           const struct virtual_cmos_fsys_ops *ops) {
    pb->count = 0;
    pb->drive = first_mounted_drive(ops);
    if (!pb->drive) return;
    /* Scan 1..max(64, g_last_capture_num + 16) capped at 512 to find existing photos fast. */
    uint32_t limit = g_last_capture_num + 32u;
    if (limit < 64u) limit = 64u;
    if (limit > 512u) limit = 512u;
    char path[64];
    for (uint32_t n = 1u; n <= limit && pb->count < 256u; ++n) {
        snprintf(path, sizeof path, "%c:/DCIM/100MSDCF/DSC%05u.JPG", pb->drive, n);
        if (file_exists_fsys(ops, path)) pb->files[pb->count++] = n;
    }
}

static int render_current_playback(struct virtual_cmos_playback_state *pb,
                                   const struct virtual_cmos_fsys_ops *ops,
                                   const char *frame_path) {
    uint8_t *rgb = calloc(1, VIRTUAL_CMOS_RGB_BYTES);
    if (!rgb) return -ENOMEM;

    if (!pb->drive || pb->count == 0) {
        draw_bar(rgb, 0, 34);
        draw_text(rgb, 16, 10, "PLAYBACK  SD VIRTUAL", 2, 235, 160, 78);
        draw_text(rgb, 110, 210, pb->drive ? "NO IMAGES ON VIRTUAL SD" : "NO VIRTUAL SD MOUNTED",
                  2, 240, 244, 242);
        draw_text(rgb, 118, 252, "PRESS SHUTTER TO CAPTURE   PLAY TO EXIT", 1, 165, 175, 170);
        int rc = write_playback_frame(frame_path, ++pb->frame_seq, rgb);
        free(rgb);
        return rc;
    }

    if (pb->index >= pb->count) pb->index = pb->count - 1u;
    uint32_t fnum = pb->files[pb->index];
    char path[64];
    snprintf(path, sizeof path, "%c:/DCIM/100MSDCF/DSC%05u.JPG", pb->drive, fnum);

    size_t cap = 512u * 1024u;
    uint8_t *buf = malloc(cap);
    size_t total = 0;
    int read_ok = 0;
    if (buf) {
        uint64_t h = 0;
        if (ops->open_fn(path, &h, 1u) == 0) {
            for (;;) {
                if (total + 65536u > cap) {
                    if (cap >= 4u * 1024u * 1024u) break;
                    size_t next = cap * 2u;
                    uint8_t *nb = realloc(buf, next);
                    if (!nb) break;
                    buf = nb;
                    cap = next;
                }
                int got = ops->read_fn(h, buf + total, 65536);
                if (got <= 0) break;
                total += (size_t)got;
            }
            ops->close_fn(h);
            read_ok = total >= 4;
        }
    }

    unsigned sw = 0, sh = 0;
    char exif[96] = "";
    int decoded = 0;
    if (read_ok) {
        decoded = virtual_cmos_decode_jpeg(buf, total, rgb, &sw, &sh, exif, sizeof exif) == 0;
    }
    free(buf);

    if (!decoded) {
        memset(rgb, 24, VIRTUAL_CMOS_RGB_BYTES);
        draw_text(rgb, 140, 218, "UNABLE TO DECODE JPEG", 2, 239, 125, 117);
    }

    draw_bar(rgb, 0, 34);
    draw_bar(rgb, 434, 480);

    char top_left[96], top_right[48], bot_left[128];
    snprintf(top_left, sizeof top_left, "PLAYBACK  100-%04u  DSC%05u.JPG", fnum % 10000u, fnum);
    snprintf(top_right, sizeof top_right, "%u/%u  %uKB", pb->index + 1u, pb->count, (unsigned)((total + 1023u) / 1024u));
    draw_text(rgb, 14, 10, top_left, 2, 240, 244, 242);
    draw_text(rgb, 466, 10, top_right, 2, 235, 160, 78);

    if (exif[0]) snprintf(bot_left, sizeof bot_left, "%s   %ux%u", exif, sw, sh);
    else         snprintf(bot_left, sizeof bot_left, "VIRTUAL CMOS JPEG   %ux%u", sw, sh);
    draw_text(rgb, 14, 442, bot_left, 2, 240, 244, 242);
    draw_text(rgb, 14, 464, "< > PREV/NEXT    DEL ERASE    PLAY/HALF EXIT", 1, 170, 185, 180);

    int rc = write_playback_frame(frame_path, ++pb->frame_seq, rgb);
    free(rgb);
    return rc;
}

int virtual_cmos_playback_enter(struct virtual_cmos_playback_state *pb,
                                const struct virtual_cmos_fsys_ops *ops,
                                const char *frame_path) {
    if (!pb || !ops || !frame_path) return -EINVAL;
    scan_sd_photos(pb, ops);
    pb->active = 1;
    pb->index = pb->count ? pb->count - 1u : 0u; /* newest photo first, like Sony cameras */
    return render_current_playback(pb, ops, frame_path);
}

int virtual_cmos_playback_step(struct virtual_cmos_playback_state *pb,
                               const struct virtual_cmos_fsys_ops *ops,
                               const char *frame_path, int delta) {
    if (!pb || !ops || !frame_path || !pb->active) return -EINVAL;
    if (pb->count > 1u) {
        int next = ((int)pb->index + delta) % (int)pb->count;
        if (next < 0) next += (int)pb->count;
        pb->index = (unsigned int)next;
    }
    return render_current_playback(pb, ops, frame_path);
}

int virtual_cmos_playback_delete(struct virtual_cmos_playback_state *pb,
                                 const struct virtual_cmos_fsys_ops *ops,
                                 const char *frame_path) {
    if (!pb || !ops || !ops->remove_fn || !ops->flush_volume_fn || !frame_path || !pb->active)
        return -EINVAL;
    if (!pb->drive || pb->count == 0) return 0;
    if (pb->index >= pb->count) pb->index = pb->count - 1u;
    char path[64];
    snprintf(path, sizeof path, "%c:/DCIM/100MSDCF/DSC%05u.JPG", pb->drive, pb->files[pb->index]);
    if (ops->remove_fn(path) != 0) return -EIO;
    (void)ops->flush_volume_fn(pb->drive);
    for (unsigned i = pb->index + 1u; i < pb->count; ++i) pb->files[i - 1u] = pb->files[i];
    --pb->count;
    if (pb->index >= pb->count && pb->count > 0) pb->index = pb->count - 1u;
    return render_current_playback(pb, ops, frame_path);
}

void virtual_cmos_playback_exit(struct virtual_cmos_playback_state *pb,
                                const char *frame_path) {
    if (pb) pb->active = 0;
    if (frame_path) unlink(frame_path);
}

int virtual_cmos_decode_playback_rgb(const struct virtual_cmos_fsys_ops *ops,
                                     const char *jpeg_path,
                                     uint8_t *rgb_out) {
    if (!ops || !ops->open_fn || !ops->read_fn || !ops->close_fn ||
        !jpeg_path || !jpeg_path[0] || !rgb_out)
        return -EINVAL;
    size_t cap = 512u * 1024u;
    uint8_t *buf = malloc(cap);
    if (!buf) return -ENOMEM;
    size_t total = 0;
    uint64_t h = 0;
    if (ops->open_fn(jpeg_path, &h, 1u) != 0) {
        free(buf);
        return -ENOENT;
    }
    for (;;) {
        if (total + 65536u > cap) {
            if (cap >= 4u * 1024u * 1024u) break;
            size_t next = cap * 2u;
            uint8_t *nb = realloc(buf, next);
            if (!nb) break;
            buf = nb;
            cap = next;
        }
        int got = ops->read_fn(h, buf + total, 65536);
        if (got <= 0) break;
        total += (size_t)got;
    }
    ops->close_fn(h);
    if (total < 4u) {
        free(buf);
        return -EIO;
    }
    memset(rgb_out, 0, VIRTUAL_CMOS_RGB_BYTES);
    unsigned sw = 0, sh = 0;
    int rc = virtual_cmos_decode_jpeg(buf, total, rgb_out, &sw, &sh, NULL, 0);
    free(buf);
    return rc;
}

int virtual_cmos_render_playback_bg(const struct virtual_cmos_fsys_ops *ops,
                                    const char *jpeg_path,
                                    const char *bg_path,
                                    uint32_t seq) {
    if (!bg_path || !bg_path[0]) return -EINVAL;
    uint8_t *rgb = calloc(1, VIRTUAL_CMOS_RGB_BYTES);
    if (!rgb) return -ENOMEM;
    int rc = virtual_cmos_decode_playback_rgb(ops, jpeg_path, rgb);
    if (rc == 0) {
        rc = write_rgb_frame_with_magic(bg_path, VIRTUAL_PLAYBACK_BG_MAGIC, seq, rgb);
    }
    free(rgb);
    return rc;
}
