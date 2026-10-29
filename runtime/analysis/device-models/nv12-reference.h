/* SPDX-License-Identifier: MIT */
#ifndef SONY_NV12_REFERENCE_H
#define SONY_NV12_REFERENCE_H
#include <stddef.h>
#include <stdint.h>
/* Explicit reference layout: Y0 Cb Y1 Cr; chroma averages adjacent rows,
 * rounding half up. This is not a recovered Sony SA program implementation. */
int nv12_reference_convert(const unsigned char *source,size_t source_capacity,
    uint32_t width,uint32_t height,uint32_t source_stride,
    unsigned char *destination,size_t destination_capacity);
#endif
