/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_PARAMETER_IMPORT_H
#define NATIVE_CP_PARAMETER_IMPORT_H
#include "cp-property-stage.h"
struct cp_parameter_import {
    uint32_t header, flags;
    uint64_t source_sequence, stage_fnv1a64;
    enum cp_start_state_origin origin;
    unsigned char properties_consumed, import_selected, defaults_selected;
};
/* Source CP353d48: header d68 AND flags bit2 selects import; otherwise flag0
 * defaults. Requires an already consumed explicit CP initial-stage owner at
 * this exact transaction and immutable matching bytes. No image is applied,
 * pointer retained, property repaired or runtime/import flag fabricated. */
int cp_parameter_import_inspect(const struct cp_property_stage *,
    const struct cp_start_state_guard *, const unsigned char *stage, size_t,
    struct cp_parameter_import *);
#endif
