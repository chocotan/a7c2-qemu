/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_STATE_SNAPSHOT_H
#define NATIVE_CP_STATE_SNAPSHOT_H
#include <stddef.h>
#include <stdint.h>

#define CP_STATE_SNAPSHOT_BYTES 0x6d4u
#define CP_STATE_SNAPSHOT_APERTURE_OFFSET 0x1c4u
#define CP_STATE_SNAPSHOT_APERTURE_BYTES 20u
#define CP_STATE_SNAPSHOT_LENS_OFFSET 0x2a8u
#define CP_STATE_SNAPSHOT_LENS_BYTES 0xa0u
#define CP_STATE_SNAPSHOT_NAME_BYTES 0x41u

enum cp_state_snapshot_provenance {
    CP_STATE_SNAPSHOT_UNPUBLISHED = 0,
    CP_STATE_SNAPSHOT_PUBLISHED_BYTES = 1
};
/* Caller describes the actual published source, not a command-completed bit.
 * Mutable may be ahead of published; all u32 values, including zero/wrap, exist.
 * The original generation is external to the wire: M+4 is zero. */
struct cp_state_snapshot_generation {
    enum cp_state_snapshot_provenance provenance;
    uint32_t mutable_generation, published_generation, shadow_generation;
};
struct cp_state_snapshot_input {
    const unsigned char *bytes, *known;
    size_t size, known_size;
    struct cp_state_snapshot_generation generation;
};
struct cp_state_snapshot {
    unsigned char bytes[CP_STATE_SNAPSHOT_BYTES];
    unsigned char known[CP_STATE_SNAPSHOT_BYTES];
    struct cp_state_snapshot_generation generation;
    uint16_t aperture_words[5]; /* 201b+8..10; full u16 domain, first=current. */
    uint8_t lens_wire_state;    /* 2044+8: raw 0/1/4, no attached/AF label. */
    uint32_t lens_values[2];    /* 2044+14/+1c, copied by AP without division. */
    unsigned char lens_name[CP_STATE_SNAPSHOT_NAME_BYTES + 1];
};
enum cp_state_snapshot_result { CP_STATE_SNAPSHOT_LAYOUT_COPIED = 0 };

/* Pure, unlinked layout/copy foundation; NOT a complete 76-getter validator,
 * publication, AP application, mode1 ACK, readiness or send authorization.
 * Source: report/lens-init-contract/README.md sections 4/5, E4/E6; public
 * CP353c18 generation != shadow; AP353277c..27f0 copies 6d4B to S+8;
 * AP3549330 consumes 201b at M+1c4 and 2044 at M+2a8 through AP351fdb8.
 * Caller supplies one immutable same-generation published packet and mask,
 * accessible for size / known_size respectively, with external quiescence.
 * size must be exactly 6d4; known_size is mask capacity (tail is not scanned).
 * Every logical mask byte must be 0/1. All bytes must be known except the
 * documented reserved +1 in the outer/201b/2044 headers. These three opaque
 * bytes and their masks are preserved verbatim, never synthesized or cleared.
 * Output must not overlap input descriptor, bytes, or ANY mask capacity byte;
 * input bytes/mask may overlap because both are read-only. No pointer retained.
 * Returns 0 only for checked layout plus copied views; negative errno:
 * EINVAL invalid span/mask/alias/provenance; ENODATA unknown required byte;
 * ENOTSUP unpublished source; ESTALE published==shadow; EPROTO header;
 * ERANGE closed lens enum outside source domain. Output unchanged on error.
 * No denominator/float checks are invented: these views perform no arithmetic,
 * and UI focal-length holder denominators/SDS are not bound to this packet.
 * Remaining getter semantics and an actual virtual settings provider must be
 * closed before a service offers this as a full snapshot to original AP. */
int cp_state_snapshot_copy(const struct cp_state_snapshot_input *, struct cp_state_snapshot *);
#endif
