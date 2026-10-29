/* SPDX-License-Identifier: MIT */
#ifndef RC_IDENTITY_H
#define RC_IDENTITY_H
#include <stddef.h>
#include <stdint.h>

/* Experimental RC format-0 byte-preserving subset, NOT a resize or DCD codec.
 * Callers must decode and validate the original device's register contract.
 * This kernel neither publishes completion nor raises interrupts.
 */
struct rc_identity_image {
    uint32_t width, height, stride;
    uint32_t format, phase, type;
    size_t capacity;
};
int rc_identity_copy(const struct rc_identity_image *input, const void *source,
                     const struct rc_identity_image *output, void *destination);
#endif
