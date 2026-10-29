/* SPDX-License-Identifier: MIT */
#include "jpeg-without-pin-input.h"
#include <string.h>

static int span(const void *p, size_t n)
{
    return p && n && n <= UINTPTR_MAX - (uintptr_t)p;
}
static int overlaps(const void *a, size_t an, const void *b, size_t bn)
{
    uintptr_t x = (uintptr_t)a, y = (uintptr_t)b;
    return x <= y ? y - x < an : x - y < bn;
}
static uint32_t le32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static unsigned int le16(const unsigned char *p)
{
    return (unsigned int)p[0] | (unsigned int)p[1] << 8;
}
static int rectangle(const unsigned char *p, unsigned int w, unsigned int h)
{
    unsigned int x = le16(p), y = le16(p + 2);
    return x <= w && y <= h && le16(p + 4) && le16(p + 6) &&
           le16(p + 4) <= w - x && le16(p + 6) <= h - y;
}
static int binding(const struct jpeg_without_pin_sds *s,
                   const struct jpeg_without_pin_mapping *m)
{
    return s->lease && s->lease == m->lease && s->type == m->type &&
           s->handle == m->handle && span(m->data, m->bytes) && s->extent &&
           s->offset <= m->bytes && s->extent <= m->bytes - s->offset &&
           (!m->readable || span(m->readable, m->bytes));
}
static int known_image_byte(size_t i)
{
    return i < 0x26 || (i >= 0x2e && i < 0x44);
}

int jpeg_without_pin_validate(const struct jpeg_without_pin_input *in,
                              jpeg_without_pin_borrow borrow, void *context,
                              struct jpeg_without_pin_view *out)
{
    struct jpeg_without_pin_mapping pixel = {0}, metadata = {0};
    struct jpeg_without_pin_view result = {0};
    const unsigned char *base, *mask, *image, *state;
    static const unsigned char attributes[10] = {1, 0, 2, 0, 0, 0, 1, 1, 2, 0};
    static const unsigned char state_values[8] = {1, 0, 0, 1, 0, 4, 0, 0};
    static const unsigned int geometry[11] = {1920, 1088, 0, 0, 1280, 720,
                                             0, 0, 1280, 720, 0};
    size_t i, image_offset, state_offset;
    if (!span(in, sizeof *in) || !span(out, sizeof *out) || !borrow ||
        overlaps(in, sizeof *in, out, sizeof *out) || in->parameter1049 != 0x40 ||
        in->parameter1053.extent != JPEG_WITHOUT_PIN_METADATA_BYTES)
        return JPEG_WITHOUT_PIN_REJECT;
    if (borrow(context, in->parameter1054.type, in->parameter1054.handle, &pixel) ||
        borrow(context, in->parameter1053.type, in->parameter1053.handle, &metadata) ||
        !binding(&in->parameter1054, &pixel) || !binding(&in->parameter1053, &metadata) ||
        !metadata.readable)
        return JPEG_WITHOUT_PIN_REJECT;
    if (overlaps(out, sizeof *out, pixel.data, pixel.bytes) ||
        overlaps(out, sizeof *out, metadata.data, metadata.bytes) ||
        overlaps(out, sizeof *out, metadata.readable, metadata.bytes) ||
        (pixel.readable && overlaps(out, sizeof *out, pixel.readable, pixel.bytes)))
        return JPEG_WITHOUT_PIN_REJECT;
    base = metadata.data + in->parameter1053.offset;
    mask = metadata.readable + in->parameter1053.offset;
    result.borrowed_pixels = pixel.data + in->parameter1054.offset;
    result.pixel_extent = in->parameter1054.extent;
    if (overlaps(base, 1024, result.borrowed_pixels, result.pixel_extent) ||
        overlaps(metadata.data, metadata.bytes, metadata.readable, metadata.bytes))
        return JPEG_WITHOUT_PIN_REJECT;
    image_offset = in->image_size_offset;
    state_offset = in->yc_state_offset;
    if (image_offset > 1024 - 72 || state_offset > 1024 - 8)
        return JPEG_WITHOUT_PIN_REJECT;
    image = base + image_offset;
    state = base + state_offset;
    if (overlaps(image, 72, state, 8)) return JPEG_WITHOUT_PIN_REJECT;
    for (i = 0; i < 72; ++i) {
        if (!known_image_byte(i)) continue;
        if (mask[image_offset + i] != 0xff) return JPEG_WITHOUT_PIN_REJECT;
        result.image_readable[i] = result.image_consumed[i] = 0xff;
    }
    for (i = 0; i < 8; ++i) {
        if (mask[state_offset + i] != 0xff) return JPEG_WITHOUT_PIN_REJECT;
        result.state_readable[i] = result.state_consumed[i] = 0xff;
    }
    if (le32(image) != in->parameter1054.type ||
        le32(image + 4) != in->parameter1054.handle ||
        le32(image + 0x18) != in->parameter1054.offset)
        return JPEG_WITHOUT_PIN_REJECT;
    for (i = 8; i < 0x18; ++i)
        if (image[i]) return JPEG_WITHOUT_PIN_REJECT;
    if (!rectangle(image + 0x32, le16(image + 0x2e), le16(image + 0x30)) ||
        !rectangle(image + 0x3a, le16(image + 0x2e), le16(image + 0x30)) ||
        memcmp(image + 0x1c, attributes, sizeof attributes) ||
        memcmp(state, state_values, sizeof state_values))
        return JPEG_WITHOUT_PIN_REJECT;
    for (i = 0; i < 11; ++i)
        if (le16(image + 0x2e + i * 2) != geometry[i]) return JPEG_WITHOUT_PIN_REJECT;
    result.unsupported_fields = JPEG_WITHOUT_PIN_UNKNOWN_SSYC |
        JPEG_WITHOUT_PIN_UNKNOWN_IMAGE_HOLES | JPEG_WITHOUT_PIN_UNKNOWN_OUT_TIM |
        JPEG_WITHOUT_PIN_UNKNOWN_PIXEL_PACKING | JPEG_WITHOUT_PIN_UNKNOWN_REQUEST_HEADER;
    *out = result;
    return JPEG_WITHOUT_PIN_UNSUPPORTED;
}
