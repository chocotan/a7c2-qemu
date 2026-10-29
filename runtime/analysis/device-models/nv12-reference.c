/* SPDX-License-Identifier: MIT */
#include "nv12-reference.h"
#include <stdint.h>

int nv12_reference_convert(const unsigned char *source,size_t source_capacity,
    uint32_t width,uint32_t height,uint32_t source_stride,
    unsigned char *destination,size_t destination_capacity)
{
    if (!source || !destination || !width || !height || width>8192 || height>8192 ||
        (width&1) || (height&1) || source_stride<width*2u) return -1;
    uint64_t input_bytes=(uint64_t)(height-1)*source_stride+width*2u;
    uint64_t pixels=(uint64_t)width*height,output_bytes=pixels+pixels/2;
    uintptr_t src=(uintptr_t)source,dst=(uintptr_t)destination;
    if (input_bytes>source_capacity || output_bytes>destination_capacity ||
        input_bytes>UINTPTR_MAX-src || output_bytes>UINTPTR_MAX-dst ||
        (src<dst+output_bytes && dst<src+input_bytes)) return -1;
    for (uint32_t row=0;row<height;row++) {
        const unsigned char *input=source+(size_t)row*source_stride;
        unsigned char *y=destination+(size_t)row*width;
        for (uint32_t column=0;column<width;column++) y[column]=input[column*2u];
    }
    for (uint32_t row=0;row<height;row+=2) {
        const unsigned char *upper=source+(size_t)row*source_stride;
        const unsigned char *lower=upper+source_stride;
        unsigned char *uv=destination+(size_t)pixels+(size_t)(row/2)*width;
        for (uint32_t column=0;column<width;column+=2) {
            uv[column]=(upper[column*2u+1]+lower[column*2u+1]+1u)/2u;
            uv[column+1]=(upper[column*2u+3]+lower[column*2u+3]+1u)/2u;
        }
    }
    return 0;
}
