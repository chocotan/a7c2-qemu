/* SPDX-License-Identifier: MIT */
#include "frame-rle.h"

#include <assert.h>
#include <stdlib.h>

int main(void)
{
    const uint8_t rgb[] = {1, 2, 3, 1, 2, 3, 1, 2, 3, 4, 5, 6, 7, 8, 9};
    const uint8_t expected[] = {2, 0x80, 1, 2, 3, 1, 0, 4, 5, 6, 7, 8, 9};
    uint8_t packed[32], decoded[sizeof rgb];
    size_t bytes = fcam_rgb_pack(rgb, 5, packed, sizeof packed);
    assert(bytes == sizeof expected && !memcmp(packed, expected, bytes));
    assert(!fcam_rgb_unpack(packed, bytes, decoded, 5));
    assert(!memcmp(rgb, decoded, sizeof rgb));
    assert(!fcam_rgb_pack(rgb, 5, packed, bytes - 1u));
    assert(fcam_rgb_unpack(expected, sizeof expected - 1u, decoded, 5) == -EBADMSG);
    assert(fcam_rgb_unpack(expected, sizeof expected, decoded, 4) == -EBADMSG);
    assert(fcam_rgb_unpack(expected, sizeof expected, decoded, 6) == -EBADMSG);
    assert(fcam_rgb_unpack(expected, 1, decoded, 5) == -EBADMSG);
    assert(fcam_rgb_unpack(expected, 0, decoded, 5) == -EBADMSG);
    memcpy(packed, expected, sizeof expected);
    packed[sizeof expected] = 0;
    assert(fcam_rgb_unpack(packed, sizeof expected + 1u, decoded, 5) == -EBADMSG);
    assert(!fcam_rgb_pack(NULL, 5, packed, sizeof packed));
    assert(!fcam_rgb_pack(rgb, 0, packed, sizeof packed));
    assert(!fcam_rgb_pack(rgb, SIZE_MAX, packed, sizeof packed));
    assert(fcam_rgb_unpack(NULL, 0, decoded, 5) == -EINVAL);
    assert(fcam_rgb_unpack(rgb, sizeof rgb, decoded, SIZE_MAX) == -EINVAL);

    const size_t pixels = 32770u, length = pixels * 3u;
    uint8_t *source = malloc(length), *wire = malloc(length + 6u), *out = malloc(length);
    assert(source && wire && out);
    memset(source, 0x73, length);
    bytes = fcam_rgb_pack(source, pixels, wire, length + 6u);
    assert(bytes == 13u && wire[0] == 0xff && wire[1] == 0xff);
    assert(wire[5] == 1 && wire[6] == 0); /* Two remaining pixels are literal. */
    assert(!fcam_rgb_unpack(wire, bytes, out, pixels) && !memcmp(source, out, length));

    /* Incompressible input exercises maximum literal records and lossless fallback. */
    for (size_t i = 0; i < length; ++i) source[i] = (uint8_t)i;
    bytes = fcam_rgb_pack(source, pixels, wire, length + 6u);
    assert(bytes == length + 4u && wire[0] == 0xff && wire[1] == 0x7f);
    assert(!fcam_rgb_unpack(wire, bytes, out, pixels) && !memcmp(source, out, length));
    assert(!fcam_rgb_pack(source, pixels, wire, length - 1u));

    /* Deterministic mixed literal/run inputs cover chunk and run transitions. */
    uint32_t random = 1;
    for (size_t pass = 1; pass <= 64u; ++pass) {
        const size_t count = pass * 509u;
        for (size_t i = 0; i < count; ++i) {
            random = random * 1664525u + 1013904223u;
            if (i && (random & 7u) < 6u) memcpy(source + i * 3u, source + (i - 1u) * 3u, 3u);
            else {
                source[i * 3u] = (uint8_t)random;
                source[i * 3u + 1u] = (uint8_t)(random >> 8);
                source[i * 3u + 2u] = (uint8_t)(random >> 16);
            }
        }
        bytes = fcam_rgb_pack(source, count, wire, length + 6u);
        assert(bytes && !fcam_rgb_unpack(wire, bytes, out, count));
        assert(!memcmp(source, out, count * 3u));
    }
    free(out);
    free(wire);
    free(source);
    return 0;
}
