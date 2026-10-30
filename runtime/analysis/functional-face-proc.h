#ifndef FUNCTIONAL_FACE_PROC_H
#define FUNCTIONAL_FACE_PROC_H

#include <stddef.h>
#include <stdint.h>

struct functional_face_proc_unit {
    uint32_t handle, unit, state, owners, opens, shares, generation, relation;
    uint32_t extent_id, segments;
    uint64_t address;
    size_t bytes;
    size_t row_offset, row_bytes;
};

/*
 * Parse a complete original /proc/udm/dmm_units ASCII document.
 * The caller must establish EOF and exclude competing proc readers; this API
 * cannot establish read completeness, atomicity, writer exclusion or birth.
 * raw_bytes excludes any C-string terminator; embedded NUL is rejected.
 * unit is 0x1d9..0x1dc; full_handle is the exact original saved Birth handle.
 * Returns 0, or a negative errno; every failure leaves *out unchanged.
 * ENODATA: no matching handle. ESTALE: wrong unit or handle generation.
 * ENOTSUP: target has multiple segments. EPROTO: malformed/unsafe metadata.
 * EINVAL: invalid arguments. E2BIG: document/line exceeds fixed bounds.
 * row_offset/row_bytes select the original target row, including ancestors
 * and excluding LF. Compare semantic fields, not whole structs: offsets vary.
 * Numeric relation/extent IDs and address are diagnostic values, not pointers,
 * native identities, pin receipts, sourceReady or capture evidence.
 */
int functional_face_proc_unit_parse(const void *raw, size_t raw_bytes,
                                   uint32_t unit, uint32_t full_handle,
                                   struct functional_face_proc_unit *out);

#endif
