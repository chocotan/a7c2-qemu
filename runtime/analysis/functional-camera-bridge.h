/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_CAMERA_BRIDGE_H
#define FUNCTIONAL_CAMERA_BRIDGE_H
#include "functional-camera-abi.h"
#include "functional-bb-startup-abi.h"
#include "functional-vdf-bit-width-abi.h"
#include "functional-still-format-abi.h"
#include "functional-startup-control-abi.h"
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
 * depth is unknown. OP13 takes canonical16/returns StillFormat176/class8;
 * requires flag0/native402d/24B/source80020002/destination90030001. Exact
 * tuple, complete sink/route/generation/config16 and caller readback precede
 * success with token0; physical format/CP selectors remain unknown.
 * OP14 takes canonical32/returns StartupControl192/class9 under flag0 with
 * native4014/24B or4057/12B, source80020002/destination90030001. First obtain
 * actual STATE from this bridge instance and hash its bytes8..47. Full32 tail,
 * current config40 fingerprint, route/frame/sink/generation and caller readback
 * are checked, including before-generations against the actual State128.
 * A successful OP14 advances that cache; other non-State128 operations
 * invalidate it until a new State128 is returned. There is no old176/class5/
 * class8 fallback or native ACK.
 * Other operations retain legacy flag0. This API supplies no error-
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
