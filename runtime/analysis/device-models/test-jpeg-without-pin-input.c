/* SPDX-License-Identifier: MIT */
#include "jpeg-without-pin-input.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct {
    unsigned char pixels[128], metadata[1040], mask[1040];
    struct jpeg_without_pin_mapping pixel, meta;
    struct jpeg_without_pin_input input;
    int live, calls;
} f;
static unsigned int checks;
static void put32(unsigned char *p, uint32_t v)
{
    size_t i;
    for (i = 0; i < 4; ++i) p[i] = (unsigned char)(v >> (i * 8));
}
static void put16(unsigned char *p, unsigned int v)
{
    p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8);
}
static int known(size_t i) { return i < 0x26 || (i >= 0x2e && i < 0x44); }
static int borrow(void *context, uint32_t type, uint32_t handle,
                  struct jpeg_without_pin_mapping *out)
{
    assert(context == &f); ++f.calls;
    if (!f.live) return -1;
    if (type == 0x42 && handle == 0xa0) *out = f.pixel;
    else if (type == 0x43 && handle == 0xb0) *out = f.meta;
    else return -1;
    return 0;
}
static void init(void)
{
    unsigned char *p;
    size_t i;
    const unsigned int geometry[] = {1920, 1088, 0, 0, 1280, 720, 0, 0, 1280, 720, 0};
    const unsigned char attributes[] = {1, 0, 2, 0, 0, 0, 1, 1, 2, 0};
    const unsigned char state[] = {1, 0, 0, 1, 0, 4, 0, 0};
    memset(&f, 0, sizeof f);
    memset(f.pixels, 0xd3, sizeof f.pixels);
    memset(f.metadata, 0xa5, sizeof f.metadata);
    f.pixel = (struct jpeg_without_pin_mapping){f.pixels, NULL, sizeof f.pixels, 0x42, 0xa0, 17};
    f.meta = (struct jpeg_without_pin_mapping){f.metadata, f.mask, sizeof f.metadata, 0x43, 0xb0, 23};
    f.input = (struct jpeg_without_pin_input){0x40, {0x42, 0xa0, 7, 57, 17},
                                            {0x43, 0xb0, 16, 1024, 23}, 32, 128};
    p = f.metadata + 16 + 32;
    put32(p, 0x42); put32(p + 4, 0xa0);
    memset(p + 8, 0, 16); put32(p + 0x18, 7);
    memcpy(p + 0x1c, attributes, sizeof attributes);
    for (i = 0; i < 11; ++i) put16(p + 0x2e + 2 * i, geometry[i]);
    for (i = 0; i < 72; ++i) f.mask[48 + i] = known(i) ? 0xff : 0;
    memcpy(f.metadata + 144, state, sizeof state);
    memset(f.mask + 144, 0xff, 8);
    f.live = 1;
}
static void accepted(void)
{
    struct jpeg_without_pin_view view;
    unsigned char before[sizeof f.metadata], pixels[sizeof f.pixels];
    size_t i;
    memcpy(before, f.metadata, sizeof before); memcpy(pixels, f.pixels, sizeof pixels);
    assert(jpeg_without_pin_validate(&f.input, borrow, &f, &view) == JPEG_WITHOUT_PIN_UNSUPPORTED);
    assert(view.unsupported_fields == 31 && view.borrowed_pixels == f.pixels + 7);
    assert(view.pixel_extent == f.input.parameter1054.extent);
    for (i = 0; i < 72; ++i) {
        assert(view.image_readable[i] == (known(i) ? 0xff : 0));
        assert(view.image_consumed[i] == view.image_readable[i]);
    }
    for (i = 0; i < 8; ++i) assert(view.state_readable[i] == 0xff && view.state_consumed[i] == 0xff);
    assert(!memcmp(before, f.metadata, sizeof before) && !memcmp(pixels, f.pixels, sizeof pixels));
    ++checks;
}
static void rejected(void)
{
    struct jpeg_without_pin_view view, before;
    memset(&view, 0x5a, sizeof view); memcpy(&before, &view, sizeof view);
    assert(jpeg_without_pin_validate(&f.input, borrow, &f, &view) == JPEG_WITHOUT_PIN_REJECT);
    assert(!memcmp(&before, &view, sizeof view)); ++checks;
}
#define BAD(change) do { init(); change; rejected(); } while (0)
int main(void)
{
    size_t i;
    struct jpeg_without_pin_view view;
    init(); accepted(); assert(f.calls == 2);
    init(); f.input.parameter1054.extent = sizeof f.pixels - 7; accepted();
    init();
    for (i = 0; i < 72; ++i) if (!known(i)) {
        f.metadata[48 + i] ^= 0xff; f.mask[48 + i] = 0xff;
    }
    accepted();
    init();
    memmove(f.metadata + 968, f.metadata + 48, 72);
    memmove(f.mask + 968, f.mask + 48, 72);
    f.input.image_size_offset = 952; accepted();
    for (i = 0; i < 72; ++i) if (known(i)) {
        BAD(f.metadata[48 + i] ^= 1);
        BAD(f.mask[48 + i] = 0);
        BAD(f.mask[48 + i] = 0x7f);
    }
    for (i = 0; i < 8; ++i) {
        BAD(f.metadata[144 + i] ^= 1);
        BAD(f.mask[144 + i] = 0);
    }
    BAD(f.input.parameter1049 = 5); assert(f.calls == 0);
    BAD(f.live = 0);
    BAD(f.input.parameter1054.handle++);
    BAD(f.pixel.handle++);
    BAD(f.meta.type++);
    BAD(f.input.parameter1054.lease++);
    BAD(f.input.parameter1053.lease++);
    BAD(f.input.parameter1054.lease = 0; f.pixel.lease = 0);
    BAD(f.input.parameter1053.extent = 1023);
    BAD(f.meta.bytes--);
    BAD(f.pixel.bytes = 63);
    BAD(f.input.parameter1054.extent = 0);
    BAD(f.input.parameter1054.extent = SIZE_MAX);
    BAD(f.input.parameter1054.offset = UINT32_MAX);
    BAD(f.input.parameter1053.offset = UINT32_MAX);
    BAD(f.pixel.bytes = SIZE_MAX);
    BAD(f.meta.data = (const unsigned char *)(UINTPTR_MAX - 7));
    BAD(f.meta.readable = NULL);
    BAD(f.meta.readable = (const unsigned char *)(UINTPTR_MAX - 7));
    BAD(f.input.image_size_offset = SIZE_MAX);
    BAD(f.input.image_size_offset = 953);
    BAD(f.input.yc_state_offset = 1017);
    BAD(f.input.yc_state_offset = 32);
    BAD(f.pixel.data = f.metadata);
    BAD(f.meta.readable = f.metadata);
    BAD(put16(f.metadata + 48 + 0x32, 65535));
    BAD(put16(f.metadata + 48 + 0x36, 0));
    BAD(put16(f.metadata + 48 + 0x30, 0));
    BAD(memset(f.metadata + 48, 0, 72));
    BAD(memset(f.mask, 0, sizeof f.mask));
    init();
    assert(jpeg_without_pin_validate(NULL, borrow, &f, &view) == JPEG_WITHOUT_PIN_REJECT);
    assert(jpeg_without_pin_validate(&f.input, NULL, &f, &view) == JPEG_WITHOUT_PIN_REJECT);
    assert(jpeg_without_pin_validate(&f.input, borrow, &f, NULL) == JPEG_WITHOUT_PIN_REJECT);
    assert(jpeg_without_pin_validate(&f.input, borrow, &f,
        (struct jpeg_without_pin_view *)&f.input) == JPEG_WITHOUT_PIN_REJECT);
    assert(jpeg_without_pin_validate(&f.input, borrow, &f,
        (struct jpeg_without_pin_view *)f.metadata) == JPEG_WITHOUT_PIN_REJECT);
    assert(jpeg_without_pin_validate(&f.input, borrow, &f,
        (struct jpeg_without_pin_view *)f.mask) == JPEG_WITHOUT_PIN_REJECT);
    assert(jpeg_without_pin_validate(&f.input, borrow, &f,
        (struct jpeg_without_pin_view *)f.pixels) == JPEG_WITHOUT_PIN_REJECT);
    checks += 7;
    printf("PASS: %u metadata contract cases; unknown fields remain unsupported\n", checks);
    return 0;
}
