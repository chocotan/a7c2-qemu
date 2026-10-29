/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_IRIS_STATUS_H
#define NATIVE_CP_IRIS_STATUS_H
#include <stddef.h>
#include <stdint.h>

#define CP_IRIS_BANK_BYTES 0x520u
#define CP_IRIS_BANK_COUNT 3u
#define CP_IRIS_BANK_BASE UINT32_C(0x01717510)
#define CP_IRIS_INIT_COMPLETE_OFFSET 2u
/* CPVA df2938: {name f78208, size 1, reserved 0, address 1717512} names
 * uc_IrisInitComp; H+3 is IrisInitEMG. Tokens are evidence, never host/RAM
 * pointers. H0/H1/H2 are 1717510/1717a30/1717f50, stride 0x520 = 1312.
 * a75d40 returns ROM df27f8 {2,0,0,2}; a7abc4 stores its pointer at 19f9250.
 * a76188 dereferences that profile; only profile 2 uses index byte 1b1a0a3,
 * without source bounds wrapping. All other known profiles select H0.
 * Source pins use public CP SHA256
 * f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428.
 * This models bank dataflow only. The O+6 field writer / physical iris
 * producer remains missing; no GPIO, lens, completion, or capture emulation. */
struct cp_iris_status;
struct cp_iris_status_view {
    uint64_t generation, index_publications, copies, source_copy_count;
    uint64_t sequence, last_index_publication_sequence, last_copy_sequence;
    uint32_t profile;
    unsigned int profile_known, current_index;
    unsigned int constructor_zero_writes, constructor_copy_bytes;
    unsigned int original_producer_verified, source_runtime_verified;
    unsigned int original_atomicity_verified, capture_verified;
    size_t known_bytes[CP_IRIS_BANK_COUNT];
    unsigned char banks[CP_IRIS_BANK_COUNT][CP_IRIS_BANK_BYTES];
    unsigned char known[CP_IRIS_BANK_COUNT][CP_IRIS_BANK_BYTES];
};
/* Explicit known profile (known=1); unknown (0) fails ENODATA, other masks
 * fail EINVAL. Prior H0 data/mask are exact 0x520-byte immutable spans through
 * return. Masks are exactly 0/1. a75d8e zeros ONLY H0[0:8], marks those eight
 * bytes known, then copies all H0 bytes/masks to H1/H2 and publishes index 0.
 * All other H0 bytes, including unknown opaque values, are preserved.
 * Returns NULL with errno on error; functions below return negative errno.
 * Caller supplies accessible declared storage; no storage is borrowed after
 * return, no leases, external callbacks, or private bank pointers escape. */
struct cp_iris_status *cp_iris_status_create(uint32_t profile, unsigned int profile_known,
    const unsigned char *h0, size_t size, const unsigned char *known, size_t known_size);
/* a76494: profile 2 -> (index+1)%3, otherwise 0. No state mutation. */
int cp_iris_next_bank(struct cp_iris_status *, unsigned int *index);
/* a76506: profile 2 copies current to next; other profiles do nothing. */
int cp_iris_copy_current_to_next(struct cp_iris_status *);
/* a7655a: profile 2 FIRST publishes next index, THEN copies new current to
 * following bank. Other profiles do nothing. Carries old data/knownness;
 * copying or publication never establishes a new completion producer. */
int cp_iris_publish_next(struct cp_iris_status *);
/* a780e6: FIRST publish index 0, THEN copy this actual full source[0:0x520]
 * and mask to H0, preserving H1/H2. Source is the caller's consumed O+4
 * buffer (a7ce70 / O=10e8a88); its upstream producer is not proved here.
 * Unknown source bytes are allowed and preserved, including H+2; sampling
 * requires that byte known. No boolean setter or synthetic field writer.
 * shortcut: one initialization-source consumption per instance (EALREADY on
 * repeat), extend only when another source-consumption path is defined.
 * Caller must supply the real consumed source in a future runtime binding;
 * a host fixture value 1 proves only that these bytes were copied. */
int cp_iris_publish_initial_source(struct cp_iris_status *, const unsigned char *source,
    size_t size, const unsigned char *known, size_t known_size);
/* Actual a76188-selected H+2 byte only; unknown -> ENODATA, output unchanged.
 * No working-buffer mutation; cp_slot2_normal_word_032x remains separate.
 * Values are not normalized to bool and do not attest freshness/completion. */
int cp_iris_sample_init_complete(struct cp_iris_status *, unsigned char *value);
int cp_iris_status_snapshot(struct cp_iris_status *, struct cp_iris_status_view *);
/* PID checked before lock, including after fork. Private operations/snapshots
 * serialize; this is not a claim about original CP copy atomicity. Destroy
 * requires caller quiescence. Output spans must not overlap the private owner.
 * Counters/sequence/generation are HOST audit only, never original generations.
 * Constructor: generation=1, copies=2, index_publications=1, sequence=3
 * (copy, copy, index). Each mutating call increments generation once; no-op
 * non-2 calls and reads leave it unchanged. Sequence counts copy/index events.
 * Overflow fails before any mutation. Verification flags always remain zero. */
int cp_iris_status_destroy(struct cp_iris_status *);
#endif
