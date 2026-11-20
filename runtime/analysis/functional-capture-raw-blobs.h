/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_CAPTURE_RAW_BLOBS_H
#define FUNCTIONAL_CAPTURE_RAW_BLOBS_H
#include "../../report/functional-capture-output/capture-output-memory.h"
#define RAW_BLOBS_HEADER_OFFSET 4096u
#define RAW_BLOBS_HEADER_BYTES (256u*1024u)
struct functional_raw_blobs {
    uint8_t common[RAW_BLOBS_HEADER_OFFSET+RAW_BLOBS_HEADER_BYTES];
    uint8_t control[256];
};
/* Explicit virtual source only; source is the live input used to create owner.
 * Caller must copy the returned ranges before reusing this storage. */
int functional_raw_blobs_build(struct functional_raw_blobs *,
    const struct capture_input_info *,const struct capture_output_info *,
    const struct capture_output_span *,const char *profile,
    struct capture_output_raw_input *);
int functional_capture_raw_native_metadata(struct capture_output_memory *,
    const struct capture_input_info *,const char *profile,
    struct capture_output_raw_input *);
#endif
