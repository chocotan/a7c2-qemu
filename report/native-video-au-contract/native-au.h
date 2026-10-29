#ifndef NATIVE_VIDEO_AU_CONTRACT_H
#define NATIVE_VIDEO_AU_CONTRACT_H

#include "../native-video-binding/native-video.h"

#ifdef __cplusplus
extern "C" {
#endif

struct nau_span {
    const uint8_t *data;
    size_t length;
    uint64_t logical_address;
    size_t es_offset;
};

struct nau {
    struct nvideo_info info; /* Existing typed fields; address is raw LE64(V+8). */
    uint8_t raw_info[NVIDEO_INFO_BYTES]; /* All 96 bytes, including opaque bits. */
    uint64_t address_correction, corrected_address, es_base;
    size_t es_capacity;
    struct nau_span spans[2]; /* End part first, then ring base if needed. */
    size_t span_count, total_length;
};

/* Resolve one immutable, accessible 96-byte normal VideoInfo entry. Accepts
 * exactly the existing nvideo_parse_info types {0,1,2,3,9}; type 4 belongs to
 * the separate parameter-set parser. corrected_address = LE64(info+8) plus
 * the explicitly supplied original context+0x40 address_correction.
 * LE32(info+0x10) is the entire opaque AU length. No prefix, padding, unit,
 * NAL, byte-order, Annex-B or container transformation is applied to ES.
 *
 * es is a caller-owned immutable contiguous mapping of the WHOLE ES ring
 * [es_base,es_base+es_capacity). A nonempty AU must fit within one traversal.
 * spans borrow only this mapping; consume them in order while the caller
 * keeps the entire mapping and its lease live. logical_address is the ring
 * address of each span, so the second span starts at es_base. Unused span
 * fields are zero. No allocation, linearization, ES copy, callback, lease
 * acquisition/retirement, ACK, index advance, native publication or capture.
 *
 * Reuses nvideo_parse_info on the snapshot's abstract [raw_address,
 * raw_address+length) extent for metadata/type validation ONLY. That extent
 * is not presented as a real mapping or lease; this function independently
 * validates the actual corrected ring mapping. Raw/corrected AU exclusive
 * ends and the ring's exclusive end must all fit in u64, even for wrapping
 * physical spans. Zero correction is accepted when explicitly known.
 *
 * info96 and es may overlap. The ENTIRE out_capacity must be disjoint from
 * both; out must be aligned for struct nau. Caller guarantees accessibility;
 * arithmetic checks cannot prove host memory is mapped or a lease exists.
 * On success only sizeof(*out) bytes are written. On every error all output
 * bytes, including any capacity tail, stay unchanged. No global state;
 * caller serializes mutation/retirement. errno is never modified.
 *
 * Returns 0 or negative errno:
 * EINVAL: null/empty mapping, wrong oversized info, zero AU, alignment/alias;
 * ENODATA: fewer than 96 info bytes; ENOSPC: output capacity too small;
 * ENOTSUP: non-sample type (including 4); EOVERFLOW: host/u64 arithmetic wrap;
 * ERANGE: corrected start outside the ring or AU longer than its capacity.
 * nvideo statuses map OK->0, INVALID->-EINVAL, UNSUPPORTED->-ENOTSUP,
 * RANGE->-ERANGE; explicit arithmetic checks above return -EOVERFLOW first.
 */
int nau_resolve(const uint8_t *info96, size_t info_size,
    uint64_t address_correction, uint64_t es_base,
    const uint8_t *es, size_t es_capacity,
    struct nau *out, size_t out_capacity);

#ifdef __cplusplus
}
#endif
#endif
