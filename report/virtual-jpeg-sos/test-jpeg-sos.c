#include "jpeg-sos.h"
#include "jpeg-engine.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void rejected(struct jpeg_sos_view view)
{
    assert(view.status == JPEG_SOS_REJECTED);
    assert(view.data == NULL && view.offset == 0 && view.length == 0);
}

static void bounded(struct jpeg_sos_view view, const uint8_t *p, size_t n)
{
    if (view.status == JPEG_SOS_OK) {
        assert(view.offset < n && view.length == n - view.offset);
        assert(view.data == p + view.offset && view.length >= 4);
        assert(view.data[0] == 0xff && view.data[1] == 0xda);
        assert(view.data[view.length - 2] == 0xff);
        assert(view.data[view.length - 1] == 0xd9);
    } else {
        rejected(view);
    }
}

int main(void)
{
    uint8_t pixels[17 * 19 * 3], jpeg[8192], original[8192], prefix[8192];
    size_t offset = 2, n;
    struct jpeg_engine_result encoded;
    struct jpeg_sos_view view;
    for (size_t i = 0; i < sizeof(pixels); ++i) pixels[i] = (uint8_t)(i * 13);
    encoded = jpeg_engine_encode_rgb888(pixels, sizeof(pixels), 17, 19, 51,
                                       95, jpeg, sizeof(jpeg));
    assert(encoded.status == JPEG_ENGINE_OK);
    n = encoded.used;
    memcpy(original, jpeg, n);
    while (jpeg[offset + 1] != 0xda) {
        size_t length;
        assert(n - offset >= 4 && jpeg[offset] == 0xff);
        length = ((size_t)jpeg[offset + 2] << 8) | jpeg[offset + 3];
        assert(length >= 2 && length <= n - offset - 2);
        offset += length + 2;
    }
    memcpy(prefix, jpeg, offset);
    view = jpeg_sos_suffix(jpeg, n, prefix, offset);
    bounded(view, jpeg, n);
    assert(view.status == JPEG_SOS_OK && view.offset == offset);
    assert(memcmp(jpeg, original, n) == 0 && memcmp(prefix, jpeg, offset) == 0);
    view = jpeg_sos_suffix(jpeg, n, jpeg, offset);
    assert(view.status == JPEG_SOS_OK && view.data == jpeg + offset);

    rejected(jpeg_sos_suffix(NULL, n, prefix, offset));
    rejected(jpeg_sos_suffix(jpeg, n, NULL, offset));
    rejected(jpeg_sos_suffix(jpeg, SIZE_MAX, prefix, offset));
    rejected(jpeg_sos_suffix(jpeg, n, prefix, SIZE_MAX));
    rejected(jpeg_sos_suffix((const uint8_t *)(uintptr_t)(UINTPTR_MAX - 1),
                             3, prefix, offset));
    rejected(jpeg_sos_suffix(jpeg, n,
                             (const uint8_t *)(uintptr_t)(UINTPTR_MAX - 1), 3));
    for (size_t length = 0; length < n; ++length) {
        rejected(jpeg_sos_suffix(jpeg, length, prefix, offset));
    }
    for (size_t length = 0; length <= n; ++length) {
        view = jpeg_sos_suffix(jpeg, n, jpeg, length);
        if (length == offset) assert(view.status == JPEG_SOS_OK);
        else rejected(view);
    }

    /* Exercise every byte without presuming entropy mutations are decoded. */
    for (size_t i = 0; i < n; ++i) {
        for (unsigned mask = 1; mask <= 128; mask <<= 1) {
            jpeg[i] ^= (uint8_t)mask;
            bounded(jpeg_sos_suffix(jpeg, n, prefix, offset), jpeg, n);
            jpeg[i] ^= (uint8_t)mask;
        }
    }
    for (size_t i = 0; i < offset; ++i) {
        prefix[i] ^= 0xff;
        bounded(jpeg_sos_suffix(jpeg, n, prefix, offset), jpeg, n);
        prefix[i] ^= 0xff;
    }
    assert(memcmp(jpeg, original, n) == 0 && memcmp(prefix, jpeg, offset) == 0);
    puts("jpeg-sos: 4 C self-check groups passed (host memory only)");
    return 0;
}
