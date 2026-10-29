/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_PROPERTY_STAGE_FILE_H
#define NATIVE_CP_PROPERTY_STAGE_FILE_H
#include "cp-property-stage.h"
#include "cp-parameter-import.h"
/* Caller opens only the host-SHA-verified public /seed-backup.bin. Read-only,
 * exact size, complete bytes and original whole-seed FNV are checked here.
 * Only the explicit CP_INITIAL_STAGE projection is consumed; no fallback.
 * FD, owners and source serialization remain with the caller; errno preserved.
 * Failure leaves the stage owner and import decision unchanged. This does not
 * deliver profile or execute defaults; both reads bind the SAME stage bytes. */
int cp_property_stage_load_public_file(struct cp_property_stage *,
    const struct cp_start_state_guard *, int fd, struct cp_parameter_import *);
#endif
