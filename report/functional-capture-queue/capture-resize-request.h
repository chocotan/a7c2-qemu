/* SPDX-License-Identifier: MIT */
#ifndef CAPTURE_RESIZE_REQUEST_H
#define CAPTURE_RESIZE_REQUEST_H
#include "../functional-capture-input/capture-input.h"
#define CAPTURE_RESIZE_REQUEST_POLICY "original-consumer-virtual-cp-resize-request-v1"
#define CAPTURE_RESIZE_REQUEST_BYTES 48u
#define CAPTURE_RESIZE_QUEUE UINT32_C(0x8055001f)
#define CAPTURE_RESIZE_SOURCE UINT32_C(0x80c70047)
/* Explicit functional-profile producer, not a recovered Sony CP writer.
 * Q48 references the owner's real native P128 CPU address, never an alias or
 * physical address. Fields the original1500/2 consumer does not use are zero
 * by this software policy. Only Main/Thm single JPEG is supported.
 * Caller serializes this with all input-owner operations. On success keep hold
 * through actual original P copy and Main/Thm completion; packet free/ACK1002
 * cannot drop it because original ACK is sent BEFORE the P128 copy.
 * This builds bytes only: no messages, implicit encode, ACK or release.
 * hold must be all zero on entry. Failure leaves both outputs unchanged;
 * neither output may overlap the request, input storage or the other output.
 */
int capture_resize_request_build(struct capture_input *,const uint8_t original4038[16],
    uint8_t packet[CAPTURE_RESIZE_REQUEST_BYTES],struct capture_input_mapping *hold);
#endif
