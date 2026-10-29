#include "jpeg-sos.h"

#include <string.h>

struct header {
    const uint8_t *bytes, *frame;
    size_t size, pos, start;
    unsigned quant, huffman;
    int restart;
};

static unsigned word(const uint8_t *p)
{
    return ((unsigned)p[0] << 8) | p[1];
}

static int controls(struct header *h, int marker, const uint8_t *p, size_t n)
{
    if (marker == 0xdb) {
        if (h->frame != NULL || n == 0) return 0;
        while (n != 0) {
            if (n < 65 || p[0] > 3 || (h->quant & (1u << p[0]))) return 0;
            for (size_t i = 1; i <= 64; ++i) if (p[i] == 0) return 0;
            h->quant |= 1u << p[0];
            p += 65;
            n -= 65;
        }
        return 1;
    }
    if (marker == 0xc0) {
        unsigned blocks = 0;
        if (h->frame != NULL || n != 15 || p[0] != 8 || p[5] != 3 ||
            word(p + 1) == 0 || word(p + 3) == 0) return 0;
        for (size_t i = 6; i < 15; i += 3) {
            unsigned x = p[i + 1] >> 4, y = p[i + 1] & 15;
            if (x == 0 || x > 4 || y == 0 || y > 4 || p[i + 2] > 3 ||
                !(h->quant & (1u << p[i + 2]))) return 0;
            for (size_t j = 6; j < i; j += 3) if (p[j] == p[i]) return 0;
            blocks += x * y;
        }
        h->frame = p;
        return blocks <= 10;
    }
    if (marker == 0xc4) {
        if (h->frame == NULL || h->restart >= 0 || n == 0) return 0;
        while (n != 0) {
            unsigned total = 0, bit;
            int slots = 1;
            uint8_t seen[256] = {0};
            if (n < 17 || (p[0] & 0xee) != 0) return 0;
            bit = 1u << ((p[0] >> 4) * 2 + (p[0] & 1));
            if (h->huffman & bit) return 0;
            for (size_t i = 1; i <= 16; ++i) {
                slots = slots * 2 - p[i];
                if (slots <= 0) return 0; /* No oversubscribed/all-ones code. */
                total += p[i];
            }
            if (total == 0 || total > ((p[0] & 16) ? 162u : 12u) ||
                total > n - 17) return 0;
            for (unsigned i = 0; i < total; ++i) {
                unsigned v = p[17 + i];
                if (seen[v]++) return 0;
                if (p[0] & 16) {
                    if ((v & 15) > 10 || ((v & 15) == 0 && v != 0 && v != 0xf0))
                        return 0;
                } else if (v > 11) return 0;
            }
            h->huffman |= bit;
            p += 17 + total;
            n -= 17 + total;
        }
        return 1;
    }
    if (marker == 0xdd) {
        if (n != 2 || h->huffman == 0 || h->restart >= 0) return 0;
        h->restart = (int)word(p);
        return 1;
    }
    if (marker == 0xda) {
        if (h->frame == NULL || n != 10 || p[0] != 3 ||
            p[7] != 0 || p[8] != 63 || p[9] != 0) return 0;
        for (size_t i = 0; i < 3; ++i) {
            unsigned t = p[2 + 2 * i];
            if (p[1 + 2 * i] != h->frame[6 + 3 * i] || (t & 0xee) != 0 ||
                !(h->huffman & (1u << (t >> 4))) ||
                !(h->huffman & (1u << (2 + (t & 1))))) return 0;
        }
        return 1;
    }
    return 0;
}

static int next(struct header *h)
{
    while (h->pos < h->size) {
        const uint8_t *p = h->bytes + h->pos;
        size_t length;
        int marker;
        if (h->size - h->pos < 4 || p[0] != 0xff) return -1;
        marker = p[1];
        length = word(p + 2);
        if (length < 2 || length > h->size - h->pos - 2) return -1;
        h->start = h->pos;
        h->pos += length + 2;
        if ((marker >= 0xe0 && marker <= 0xef) || marker == 0xfe) continue;
        return controls(h, marker, p + 4, length - 2) ? marker : -1;
    }
    return 0;
}

struct jpeg_sos_view jpeg_sos_suffix(
    const uint8_t *candidate, size_t candidate_size,
    const uint8_t *reference_prefix, size_t reference_size)
{
    const struct jpeg_sos_view rejected = {JPEG_SOS_REJECTED, NULL, 0, 0};
    struct header c = {candidate, NULL, candidate_size, 2, 0, 0, 0, -1};
    struct header r = {reference_prefix, NULL, reference_size, 2, 0, 0, 0, -1};
    size_t offset;
    int data = 0, restart = 0;
    if (candidate == NULL || reference_prefix == NULL ||
        candidate_size > UINTPTR_MAX - (uintptr_t)candidate ||
        reference_size > UINTPTR_MAX - (uintptr_t)reference_prefix ||
        candidate_size < 2 || reference_size < 2) return rejected;
    if (word(candidate) != 0xffd8 || word(reference_prefix) != 0xffd8)
        return rejected;
    /* shortcut: exact coding sequence only; extend on a real guest prefix. */
    for (;;) {
        int cm = next(&c), rm = next(&r);
        if (cm == 0xda) {
            if (rm != 0) return rejected;
            offset = c.start;
            break;
        }
        if (cm <= 0 || cm != rm || c.pos - c.start != r.pos - r.start ||
            memcmp(candidate + c.start, reference_prefix + r.start,
                   c.pos - c.start) != 0) return rejected;
    }
    /* Marker framing rules out extra scans; entropy itself is not decoded. */
    while (c.pos < c.size) {
        int marker = candidate[c.pos++];
        if (marker != 0xff) { data = 1; continue; }
        if (c.pos == c.size) return rejected;
        marker = candidate[c.pos++];
        if (marker == 0) { data = 1; continue; }
        if (marker == 0xd9 && c.pos == c.size && data) {
            return (struct jpeg_sos_view){JPEG_SOS_OK, candidate + offset,
                                         offset, candidate_size - offset};
        }
        if (marker != 0xd0 + restart || c.restart <= 0 || !data) return rejected;
        restart = (restart + 1) & 7;
        data = 0;
    }
    return rejected;
}
