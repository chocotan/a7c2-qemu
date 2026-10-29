#ifndef NATIVE_VIDEO_PARAMSETS_H
#define NATIVE_VIDEO_PARAMSETS_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NPARAMSETS_INFO_BYTES 96u
#define NPARAMSETS_AVC1 UINT32_C(0x61766331)
#define NPARAMSETS_HVC1 UINT32_C(0x68766331)

/* Borrowed pure NAL; no BE length word or Annex-B prefix. es_offset locates
 * the group's BE length word in the caller's ES mapping, including for a
 * zero-span AVC VPS. source_id is opaque metadata, never a parsed RBSP ID.
 */
struct nparamsets_group {
    const uint8_t *nal;
    size_t nal_size, es_offset;
    uint16_t span;
    uint8_t count, source_id, changed;
};

struct nparamsets {
    uint32_t container_type, declared_length;
    uint64_t wire_address, address_correction, corrected_address, es_base;
    size_t es_capacity, group_bytes;
    uint8_t info_type, change_flags; /* Preserve the complete source bytes. */
    struct nparamsets_group vps, sps, pps;
};

/* Read one original MPRVideoInfo type-4 entry from exactly 96 accessible,
 * immutable bytes. container_type is the semantic avc1/hvc1 FOURCC above,
 * NOT PayloadMpr+0x18. address_correction is the known original context+0x40
 * u64 value; the caller must supply it explicitly (zero is allowed if known).
 * Corrected address = LE64(info+8) + address_correction, checked for overflow.
 * es is one caller-resolved contiguous mapping of [es_base,es_base+capacity).
 * Its real capacity, not info+0x10's informational declared_length, bounds
 * every access. No guessed host pointer, SDS lookup or ring linearization.
 *
 * Supports AVC with zero VPS span/count, one SPS and one PPS, and HEVC with
 * one VPS/SPS/PPS. Each nonempty group must be exactly BE32(nal_size)+NAL.
 * All groups are validated and returned even when their change bit is clear;
 * unchanged bytes must not be automatically applied to a container/cache.
 * Header kind/forbidden-bit/HEVC temporal-id checks are adapter validation,
 * not an assertion that the original consumer checked or decoded RBSPs.
 *
 * Caller owns the mapping lease and must keep it immutable and live until
 * the last borrowed slice consumer finishes. No allocation, free, callback,
 * completion, read-index push, ACK, cache deduplication or native capture.
 * info and es may overlap each other; the ENTIRE out_capacity must be disjoint
 * from both. out must be aligned for struct nparamsets. Caller guarantees
 * accessible storage; numerical pointer checks cannot prove accessibility.
 * On success write sizeof(*out) bytes only; on every failure leave all output
 * bytes unchanged. No global state; caller serializes mutation/retirement.
 *
 * Returns 0 or a negative errno, without modifying errno:
 * EINVAL: bad arguments, alignment, overlap, NAL header or trailing bytes;
 * ENOSPC: output capacity too small; ENOTSUP: type/codec/multi-NAL form;
 * ENODATA: missing mandatory group or truncated info/length-word/NAL;
 * EOVERFLOW: host/logical address arithmetic wraps; ERANGE: outside mapping.
 */
int nparamsets_parse(const uint8_t *info, size_t info_size,
    uint32_t container_type, uint64_t address_correction,
    uint64_t es_base, const uint8_t *es, size_t es_capacity,
    struct nparamsets *out, size_t out_capacity);

#ifdef __cplusplus
}
#endif
#endif
