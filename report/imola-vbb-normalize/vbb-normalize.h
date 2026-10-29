#ifndef IMOLA_VBB_NORMALIZE_H
#define IMOLA_VBB_NORMALIZE_H

#include <stddef.h>
#include <stdint.h>

#define NVBB_SUBRECORD_BYTES 0x4cu

/* Diagnostic transform of one owned byte buffer, never live CP/MCU memory.
 * The caller supplies the actual captured u32 context+0x18 and u8 context+0x1c,
 * context+0x1d values; there are no inferred defaults or pixel-format meanings.
 * Both full declared spans must be accessible, non-overlapping, non-wrapping;
 * src must remain immutable for the call. Mapping/accessibility is the caller's
 * responsibility. Unaligned byte buffers are supported.
 * Success copies exactly 0x4c bytes and normalizes only LE32 words +0/+4/+8;
 * bytes +0x0c..+0x4b remain opaque, and output-capacity tails remain untouched.
 * Returns 0, -EINVAL (null/overlap), -EOVERFLOW (span wrap), -EMSGSIZE (short),
 * or -ENOTSUP (unsupported consumed mode). On error the entire output is
 * unchanged; source and errno are preserved on every return. Auxiliary mode
 * is not consumed when the source word +8 is zero. Rejecting unknown modes
 * before output mutation is a conservative adapter policy, unlike the original
 * in-place writes preceding an assert. Zero means numeric bytes derived only:
 * no hardware configuration knowledge, ready state, or data consumption.
 */
int nvbb_normalize_subrecord(uint32_t base, uint8_t address_mode,
                             uint8_t auxiliary_mode, const unsigned char *src,
                             size_t src_bytes, unsigned char *out,
                             size_t out_bytes);

#endif
