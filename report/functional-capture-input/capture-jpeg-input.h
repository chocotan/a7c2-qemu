/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_CAPTURE_JPEG_INPUT_H
#define FUNCTIONAL_CAPTURE_JPEG_INPUT_H
#include "capture-input.h"
#define CAPTURE_JPEG_THUMB_MAX_QUALITY 75u
struct capture_jpeg_input {
    struct capture_input *owner;
    struct capture_input_mapping metadata, pixels;
    struct capture_input_info source;
    uint8_t model_request[32], image_size_info[72];
    uint64_t metadata_fnv1a64;
    int prepared;
};
/* Explicitly binds the original framework typed readers after full-file hash
 * verification by the caller; never loads a caller-chosen decoder/plugin. */
int capture_jpeg_input_bind(const char *verified_framework_sha256);
/* Input body is the actual original80B Main service payload after the outer
 * adapter validated its source/header/output SDS. Reads original SSYC through
 * original typed getters, then pins the exact same native RGB. Produces only
 * the model18 request; no encode/ACK/output write is synthesized here.
 * Quality is the explicit functional model percentage, not Sony's discrete code.
 * Thm selector1 caps it at75 for the original0x2ffc output area; this is software
 * policy only. The codec must still reject every actual result over capacity.
 * Output must start zeroed; an unreleased output is rejected. It owns any
 * acquired references, including on a later error; the
 * caller must release it. prepared1 is set only after complete input validation.
 * Externally serialize all operations on the same capture owner. */
int capture_jpeg_input_prepare(struct capture_input *, const uint8_t body[80],
    uint32_t selector, uint32_t quality, struct capture_jpeg_input *);
int capture_jpeg_input_release(struct capture_jpeg_input *);
#endif
