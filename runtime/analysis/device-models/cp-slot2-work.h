/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_SLOT2_WORK_H
#define NATIVE_CP_SLOT2_WORK_H
#include <stddef.h>
#include <stdint.h>

#define CP_SLOT2_VIEW_BYTES 200u
#define CP_SLOT2_RECORD_BYTES 20u
#define CP_SLOT2_WORK_BYTES 224u
#define CP_SLOT2_BANK_BYTES 0x920u
#define CP_SLOT2_BANK_BASE UINT32_C(0x203f4f8)
#define CP_SLOT2_WORK_TOKEN UINT32_C(0x186ec58)
#define CP_SLOT2_QUEUE_TOKEN UINT32_C(0x186ed38)
/* Source: report/cp302c-module-{frontier.md,source-pins.json}. Public CP SHA256:
 * f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428.
 * CPVA/raw: 8c9846/7c1846 (4B), 8c6d02/7bed02 (220B),
 * 351620/249620 (40B), 8c6e64/7bee64 (136B), 4dab4a/3d2b4a (28B).
 * 8c6d96 bytes 4ff41262 encode #0x920. Tokens below are CP32, never host
 * pointers; CPVA-minus-raw=108000 applies to file windows, NOT CP RAM.
 * Owned layout: module u32 +0, shallow N[200] +4, all record[20] +cc.
 * Selector CP32=1ad46a9; normal G+10=P+2950 is distinct from G+40. */
struct cp_slot2_work;
enum cp_slot2_stage {
    CP_SLOT2_IDLE, CP_SLOT2_VALIDATING, CP_SLOT2_QUEUED,
    CP_SLOT2_EXECUTING, CP_SLOT2_COMPLETING, CP_SLOT2_FAULT
};
struct cp_slot2_borrowed { void *context; uint64_t generation; uint32_t mode; };
struct cp_slot2_pointer_view {
    const unsigned char *bytes, *known;
    size_t size, known_size;
    uint32_t source_fnv;
};
struct cp_slot2_bank {
    uint32_t token;
    unsigned char bytes[CP_SLOT2_BANK_BYTES], known[CP_SLOT2_BANK_BYTES];
    size_t known_size;
    unsigned int fully_consumed;
};
/* All callbacks run outside the private lock. IO/code/context outlive the
 * instance. valid establishes the supplied mode, generation and borrowed
 * prerequisites; read resolves CP32 spans with byte masks (0 unknown/1 known).
 * Unknown spans must fail, never be filled with fabricated zero bytes.
 * The caller pins the lease through successful complete, including its return;
 * no cancellation/release API can retire an outstanding or faulted lease.
 * enqueue: positive=queued, zero=source failure, negative=unknown/error.
 * The bound internal execute callback must consume every source-required field
 * of its supported business branch and supply actual bank bytes plus a full
 * mask array (0/1) and fully_consumed=1. Opaque bytes may remain unknown; the
 * queue cannot infer business field coverage. This attestation is never accepted
 * from a wire caller. There is NO default executor or normal-view refresh.
 * complete invokes an explicitly bound host callback for the immutable source
 * record/module; the CP function tokens are evidence, never called addresses.
 * Callback errors retain work/lease; failed execution is never retried. No
 * callback may retain temporary descriptors or destroy the instance. */
struct cp_slot2_io {
    int (*valid)(void *, const struct cp_slot2_borrowed *);
    int (*read)(void *, const struct cp_slot2_borrowed *, uint32_t,
                unsigned char *, unsigned char *, size_t);
    int (*enqueue)(void *, uint32_t, const unsigned char *, const unsigned char *);
    int (*execute_8c736a)(void *, const struct cp_slot2_pointer_view *,
                         const struct cp_slot2_borrowed *, struct cp_slot2_bank *);
    int (*complete)(void *, const struct cp_slot2_borrowed *, const unsigned char *, uint32_t);
};
struct cp_slot2_input {
    const unsigned char *view, *known, *completion_record;
    size_t view_size, known_size, record_size;
    uint32_t module, requested;
    unsigned int requested_known, mode_known;
    struct cp_slot2_borrowed borrowed;
};
struct cp_slot2_view {
    uint64_t generation, borrowed_generation, bank_generation[2], completed_generation;
    uint32_t source_fnv, requested, mode;
    unsigned int busy, stage, selector, publications, callbacks, completion_attempts;
    int fault;
    unsigned int original_worker_verified, original_schedule_verified;
    unsigned int completion_publish_verified, observed_known, observed, completion_mask;
    unsigned char owned_work[CP_SLOT2_WORK_BYTES], view_known[CP_SLOT2_VIEW_BYTES];
    unsigned char queue_record[CP_SLOT2_RECORD_BYTES];
    unsigned char banks[2 * CP_SLOT2_BANK_BYTES], bank_known[2 * CP_SLOT2_BANK_BYTES];
};
/* Initial selector/bank bytes/masks are explicit inputs, not presumed cold RAM.
 * Masks are one byte per byte, exactly 0 or 1. Counters are host audit only.
 * One writer per instance; destroy requires caller quiescence and !busy. */
struct cp_slot2_work *cp_slot2_create(unsigned int, const unsigned char *,
                                    const unsigned char *, size_t);
int cp_slot2_bind(struct cp_slot2_work *, const struct cp_slot2_io *, void *);
/* This finite admission requires all 200 N bytes known, the exact source20B
 * completion record/module2, explicit requested 0323/032c/0302 and a known mode.
 * valid must verify that mode; read must verify actual u16 at CP32 (*N)+6.
 * Unknown pointed-to bytes are checked only when used, never filled in here. */
int cp_slot2_begin(struct cp_slot2_work *, const struct cp_slot2_input *);
int cp_slot2_tick(struct cp_slot2_work *);
int cp_slot2_snapshot(struct cp_slot2_work *, struct cp_slot2_view *);
int cp_slot2_destroy(struct cp_slot2_work *);
#endif
