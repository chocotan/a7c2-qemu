/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_CAPTURE_MAPPER_H
#define FUNCTIONAL_CAPTURE_MAPPER_H
#include "capture-input.h"

struct capture_mapper_scope {
    struct capture_input *input;
    struct capture_input_info info;
    struct capture_input_mapping mapping;
    uint32_t objects;
    int error;
    uint8_t failed_metadata[1024];
};
/* Explicit setup on the owner process, before admitting capture requests.
 * Requires the caller to have full-file verified the original SDK; this also
 * checks loaded symbol addresses and exact original mapper/MakeInput bodies.
 * No constructor or profile is enabled implicitly. */
int capture_mapper_bind(const char *verified_original_sdk_sha256);
/* Externally serialized per thread; reserves the real metadata borrow before
 * the original void ctor can execute. The scope must remain live until end().
 * Only the exact original MakeInput callsite/alias/length/cache/caller can use
 * the real metadata. Other in-scope calls use private failure storage and set
 * an error, so a native adapter must refuse publication after end() fails.
 * No ACK/ready or original application success is emitted here. */
int capture_mapper_begin(struct capture_input *, struct capture_mapper_scope *);
/* EBUSY keeps scope/borrow live while any original object remains; original
 * destructor releases the object reference, never munmaps owner memory.
 * Other errors close the scope and report the failure for the outer adapter. */
int capture_mapper_end(struct capture_mapper_scope *);
#endif
