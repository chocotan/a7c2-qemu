/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_STARTUP_CONTROL_ABI_H
#define FUNCTIONAL_STARTUP_CONTROL_ABI_H
#include "functional-vdf-path-abi.h"

/* Independent software startup controls, not original CP capmode/queues,
 * overrides/history, physical modes, EE readiness or capture acceptance.
 * Canonical32: LEu16 command/body_bytes, body16 (unused bytes zero), reserved4
 * zero, LEu64 FNV1a64 of this instance's actual State128 bytes8..47. The caller
 * must first obtain STATE and hash those actual40 bytes; never hash Config48
 * or substitute a fixed fingerprint. validate_basic checks only the tuple.
 * 4014 saves an observed-mode descriptor constraining later RGB/codec domain
 * integrity; no physical enum or still/video restriction is inferred.
 * 4057/request0 copies/readbacks current virtual config40 into an independent
 * settings checkpoint. A later legal Configure may change current parameters;
 * checkpoint integrity remains enforced without requiring live equality.
 * Require prior INIT and active640x480 RGB888/stride1920. Every success/repeat
 * renders, copies/readbacks all921600 bytes to an independent sink, retires,
 * saves/readbacks a separate command bank32 and commits config/frame +1.
 * Result192 is VDF160/class9 plus the full independent bank32 readback;
 * proof consumer4/result192/FNV(actual192)/token0. No implicit INIT/route,
 * original_CP_business/source_dependencies_closed/physical/EE/capture claim. */
#define FCAM_STARTUP_CONTROL_INPUT_BYTES 32u
#define FCAM_STARTUP_CONTROL_RESULT_BYTES 192u
#define FCAM_STARTUP_CONTROL_R_CONFIG 160u
#define FCAM_STARTUP_CONTROL_CLASS 9u
#define FCAM_STARTUP_CONTROL_CMD_MODE 0x4014u
#define FCAM_STARTUP_CONTROL_CMD_SETTINGS 0x4057u
#define FCAM_STARTUP_CONTROL_I_COMMAND 0u
#define FCAM_STARTUP_CONTROL_I_BODY_BYTES 2u
#define FCAM_STARTUP_CONTROL_I_BODY 4u
#define FCAM_STARTUP_CONTROL_I_RESERVED 20u
#define FCAM_STARTUP_CONTROL_I_CONFIG_FNV 24u
#define FCAM_STARTUP_CONTROL_STATE_CONFIG_OFFSET 8u
#define FCAM_STARTUP_CONTROL_CONFIG_BYTES 40u

static const uint8_t fcam_startup_control_mode_body[16] = {
    0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0};

static inline int fcam_startup_control_validate_basic(
    const unsigned char input[FCAM_STARTUP_CONTROL_INPUT_BYTES])
{
    if (!input) return 0;
    const unsigned command = (unsigned)input[0] | (unsigned)input[1] << 8;
    const unsigned bytes = (unsigned)input[2] | (unsigned)input[3] << 8;
    if (!((command == FCAM_STARTUP_CONTROL_CMD_MODE && bytes == 16u) ||
          (command == FCAM_STARTUP_CONTROL_CMD_SETTINGS && bytes == 4u))) return 0;
    for (size_t i = 0; i < 16u; ++i)
        if (input[4u + i] != (command == FCAM_STARTUP_CONTROL_CMD_MODE ?
            fcam_startup_control_mode_body[i] : 0u)) return 0;
    for (size_t i = 20u; i < 24u; ++i) if (input[i]) return 0;
    return 1;
}
#endif
