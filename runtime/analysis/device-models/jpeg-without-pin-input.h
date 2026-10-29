/* SPDX-License-Identifier: MIT */
#ifndef JPEG_WITHOUT_PIN_INPUT_H
#define JPEG_WITHOUT_PIN_INPUT_H
#include <stddef.h>
#include <stdint.h>

#define JPEG_WITHOUT_PIN_METADATA_BYTES 1024u
#define JPEG_WITHOUT_PIN_IMAGE_BYTES 72u
#define JPEG_WITHOUT_PIN_STATE_BYTES 8u
#define JPEG_WITHOUT_PIN_REJECT (-1)
#define JPEG_WITHOUT_PIN_UNSUPPORTED 1
#define JPEG_WITHOUT_PIN_UNKNOWN_SSYC 1u
#define JPEG_WITHOUT_PIN_UNKNOWN_IMAGE_HOLES 2u
#define JPEG_WITHOUT_PIN_UNKNOWN_OUT_TIM 4u
#define JPEG_WITHOUT_PIN_UNKNOWN_PIXEL_PACKING 8u
#define JPEG_WITHOUT_PIN_UNKNOWN_REQUEST_HEADER 16u

struct jpeg_without_pin_sds {
    uint32_t type, handle, offset;
    size_t extent;
    uint64_t lease;
};
struct jpeg_without_pin_mapping {
    const unsigned char *data, *readable;
    size_t bytes;
    uint32_t type, handle;
    uint64_t lease;
};
/* Resolve the CURRENT open lease from the caller's owner, not from the request.
 * Keep its mapping and lease locked/live throughout validation and any later
 * use of the borrowed pointer. Return zero on a live binding, nonzero otherwise.
 * readable is a byte mask (0xff = readable); pixels need no mask or read. */
typedef int (*jpeg_without_pin_borrow)(void *, uint32_t, uint32_t,
                                     struct jpeg_without_pin_mapping *);
struct jpeg_without_pin_input {
    unsigned char parameter1049;
    struct jpeg_without_pin_sds parameter1054, parameter1053;
    /* Payload offsets relative to metadata SDS, supplied by a trusted locator.
     * This partial API does not locate or authenticate SSYC entries/headers. */
    size_t image_size_offset, yc_state_offset;
};
struct jpeg_without_pin_view {
    const unsigned char *borrowed_pixels;
    size_t pixel_extent;
    unsigned int unsupported_fields;
    unsigned char image_readable[72], image_consumed[72];
    unsigned char state_readable[8], state_consumed[8];
};
/* Explicit Without_Pin/0x1049==0x40 only. Source: report/jpeg-without-pin,
 * I: ctor 11ac38, MakeInputYcStdData 11b388, makeParam 11b18c, ExecCmd 11b654.
 * Checks source-closed ImageSizeInfo/YcStateInfo payload fields only; no SSYC or
 * request is serialized. Unknown image holes have zero output masks regardless
 * of their opaque input bytes. Consumption means metadata comparisons only.
 * DataContent=2 does not identify packing; no pixel bytes are consumed and the
 * bounded extent cannot be proven sufficient for an image without that packing.
 * Returns UNSUPPORTED with a partial view, or REJECT with output unchanged.
 * A positive return NEVER permits submitting an original encoding request:
 * ImageOutTimInfo, container/command headers, holes and packing remain unknown;
 * original JPEG hardware/completion is also required. No lease is acquired,
 * released or invented, and no ACK, frame or readiness state is produced. */
int jpeg_without_pin_validate(const struct jpeg_without_pin_input *,
                              jpeg_without_pin_borrow, void *,
                              struct jpeg_without_pin_view *);
#endif
