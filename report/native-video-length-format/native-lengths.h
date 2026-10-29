#ifndef NATIVE_VIDEO_LENGTH_FORMAT_H
#define NATIVE_VIDEO_LENGTH_FORMAT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NLENGTH_AVC1 UINT32_C(0x61766331)
#define NLENGTH_HVC1 UINT32_C(0x68766331)

/* Validate the complete normal AU as repeated BE32(length)+NAL, returning
 * the actual NAL count only on success. container_type is the explicit
 * semantic avc1/hvc1 FOURCC above, NOT the unknown request codec+0x18.
 * The original configuration staging/serializer chain declares four-byte
 * lengths; it does not prove that the original encoder produced them.
 *
 * Reuses the real nau_resolve() with these exact raw arguments: exactly 96
 * immutable accessible descriptor bytes, an explicit known address_correction
 * (zero allowed), and the immutable contiguous WHOLE ES ring mapping. Normal
 * types remain {0,1,2,3,9}; type 4 is unsupported here. The internally resolved
 * one/two borrowed spans are consumed in order, including every body byte.
 * Length words and bodies may straddle the ring end. No external ready flag
 * or supplied struct nau is accepted as proof of a resolved view.
 *
 * AVC requires at least one header byte and forbidden_zero_bit == 0. HEVC
 * requires at least two, forbidden_zero_bit == 0, and temporal_id_plus1 != 0;
 * any layer ID is allowed. These are adapter checks, not original-parser
 * behavior. All NAL types, including reserved kinds, parameter sets, SEI and
 * AUD, are retained. No RBSP decoding, VCL filter, keyframe inference, SPS
 * dependency parsing, format detection, Annex-B conversion, NAL generation,
 * padding removal, allocation or concatenation. Exact whole-AU consumption
 * is required; a byte pattern valid as BE32 is judged by this explicit format.
 *
 * Caller guarantees accessibility and keeps the mapping/descriptor immutable
 * and their lease live throughout the call, externally serializing mutation
 * and retirement. Numerical checks cannot authenticate a lease or mapping.
 * out_count must be aligned for size_t and disjoint from the ENTIRE ES
 * capacity and all 96 descriptor bytes. Inputs may overlap each other.
 * Success writes only sizeof(size_t); EVERY error leaves output unchanged.
 * errno is unchanged on success and error. No global state, callback, ACK,
 * reply, PI/index push, lease acquisition/free, native publication or capture.
 * NVIDEO_NATIVE_GAPS remains 63; original encoder/lifecycle remain unclosed.
 *
 * Returns 0 or negative errno. EINVAL: null/alignment/alias, zero NAL length,
 * invalid adapter header, or invalid resolver argument. ENODATA: truncated
 * info, BE32 word or NAL body. ENOTSUP: unknown container or non-normal type.
 * EOVERFLOW: host/logical arithmetic wrap. ERANGE: AU outside the ES ring or
 * longer than its capacity. Resolver errors propagate unchanged. There is no
 * output capacity argument: the sole output object is one size_t.
 */
int nlength_validate(const uint8_t *info96, size_t info_size,
    uint64_t address_correction, uint64_t es_base,
    const uint8_t *es, size_t es_capacity, uint32_t container_type,
    size_t *out_count);

#ifdef __cplusplus
}
#endif
#endif
