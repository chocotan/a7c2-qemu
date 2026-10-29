/* SPDX-License-Identifier: MIT */
#ifndef SONY_RC_REFERENCE_H
#define SONY_RC_REFERENCE_H
#include "rc-identity.h"
struct rc_reference_request {
    struct rc_identity_image input, output;
    uint64_t source, destination;
};
/* Experimental lane-preserving backend, not a silicon packing/filter oracle. */
int rc_reference_decode(const uint32_t rc[32], const uint32_t input[32],
                        const uint32_t output[32], const uint32_t input_pack[4],
                        const uint32_t output_pack[4], struct rc_reference_request *request);
#endif
