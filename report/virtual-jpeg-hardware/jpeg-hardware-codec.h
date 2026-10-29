#ifndef VIRTUAL_JPEG_HARDWARE_CODEC_H
#define VIRTUAL_JPEG_HARDWARE_CODEC_H
#include "jpeg-hardware.h"
/* Internal bounded encoder: complete JPEG, validated against source controls. */
enum vjpeg_result vjpeg_encode(const struct vjpeg_frame *,
    const struct vjpeg_coding *, uint8_t *, size_t, size_t *, size_t *);
#endif
