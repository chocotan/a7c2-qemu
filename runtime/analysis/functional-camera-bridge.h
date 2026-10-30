/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_CAMERA_BRIDGE_H
#define FUNCTIONAL_CAMERA_BRIDGE_H
#include "functional-camera-abi.h"
#include "functional-bb-startup-abi.h"
#include "functional-vdf-bit-width-abi.h"
#include "functional-face-source-snapshot-abi.h"

/* Facts supplied by the actual original-request adapter, not host-created
 * firmware events. The adapter retains its original request until call ends. */
struct fcam_native_origin {
    uint32_t source, destination, command, bytes;
    uint64_t wire_fnv1a64;
};
struct fcam_bridge_result {
    size_t used, required;
    uint64_t model_instance, result_token;
};
/* Process-local explicit profile setup only: allocate/pin a dedicated mailbox,
 * export actual PFNs, never probe or wait for the host in a constructor.
 * Callback records metadata only. Main installs it before original requests. */
int fcam_bridge_init(void (*record)(const char *, const char *));
/* Sends one real operation; drains its result into caller-owned output and
 * verifies actual destination bytes before RELEASE_RESULT. No host file I/O,
 * arbitrary physical writes, original firmware memory patches or fake ACK.
 * Caller owns accessible immutable input and mutable output for the call.
 * Serialized internally; forked owners fail before inherited locks.
 * Returns 0 or negative errno. Validation errors leave outputs unchanged;
 * a failed live transfer may leave partial output, never reported complete.
 * OP11 accepts BASE360 + exact CP/SDK page counts and API40 handle origin;
 * its retained stream must equal source bytes, with flag1 on READ/RELEASE/
 * CANCEL. OP12 takes Input8/returns BitWidth168 under legacy flag0, with
 * original015e native10-byte origin. Full class7/config/sink/generation/tail
 * validation and caller destination readback precede success; token must be
 * zero. Selector0 is only the explicit software RGB888 bus policy; physical
 * depth is unknown. Other operations retain legacy flag0. This API supplies no error-
 * stage receipt: an errno alone cannot prove a remote result was cancelled. */
int fcam_bridge_call(const struct fcam_native_origin *, uint32_t opcode,
    const void *input, size_t input_bytes, void *output, size_t output_capacity,
    struct fcam_bridge_result *);
/* Typed noncodec results retain the actual original request origin. */
int fcam_bridge_bb_startup_config(const struct fcam_native_origin *,
    const unsigned char[FCAM_BB_INPUT_BYTES], unsigned char[FCAM_BB_RESULT_BYTES],
    struct fcam_bridge_result *);
int fcam_bridge_histogram(const struct fcam_native_origin *,
    const unsigned char[FCAM_HIST_INPUT_BYTES], unsigned char[FCAM_HIST_RESULT_BYTES],
    struct fcam_bridge_result *);
int fcam_bridge_close(void);
#endif
