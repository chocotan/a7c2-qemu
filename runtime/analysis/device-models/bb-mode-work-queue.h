/* SPDX-License-Identifier: MIT */
#ifndef FULL_BB_MODE_WORK_QUEUE_H
#define FULL_BB_MODE_WORK_QUEUE_H

#include <stdint.h>

#define FULL_BB_MODE_RECORD_BYTES 32u
#define FULL_BB_MODE_RING_BYTES 0x2800u
#define FULL_BB_MODE_RECORD_STRIDE 36u
#define FULL_BB_MODE_SOURCE_CAPACITY 284u
#define FULL_BB_MODE_RECORD_KNOWN UINT32_C(0xff0fffff)
#define FULL_BB_MODE_OUTER_OWNER UINT32_C(0x01788ef4)
#define FULL_BB_MODE_INNER_OWNER UINT32_C(0x01788f14)
#define FULL_BB_MODE_OUTER_PMF UINT32_C(0x0069dea3)
#define FULL_BB_MODE_INNER_PMF UINT32_C(0x00695405)
#define FULL_BB_MODE_OUTER_WORK UINT32_C(0x001aaddd)
#define FULL_BB_MODE_INNER_WORK UINT32_C(0x001b37ed)
#define FULL_BB_MODE_SNAPSHOT_TOKEN UINT32_C(0x01ff2cc8)
#define FULL_BB_MODE_WORK_ERROR (-1021)

struct full_bb_mode_record {
    unsigned char bytes[FULL_BB_MODE_RECORD_BYTES];
    uint32_t known; /* One bit per byte; +0x14..+0x17 are never semantically read. */
};

/* This stores one admitted record, not a full source ring. Source queues have
 * 10240 bytes, 284 records plus a separately executing item. Byte indices and
 * free_bytes below describe the first 36-byte record's real push/pop semantics.
 * ring and executing retain their stale bytes after pop/work return. */
struct full_bb_mode_queue {
    uint32_t source_owner, source_queue;
    unsigned char ring[FULL_BB_MODE_RECORD_STRIDE];
    uint32_t ring_known;
    struct full_bb_mode_record executing;
    uint32_t ring_read, ring_write, free_bytes, count;
    uint32_t accepted, popped, inflight, returned, consumer_task;
};

typedef int (*full_bb_mode_outer_provider)(void *context, uint32_t target);
typedef int (*full_bb_mode_inner_provider)(void *context, uint32_t snapshot_token);

struct full_bb_mode_work_queue {
    const struct full_bb_mode_work_queue *identity;
    uint32_t known, fault, busy, pending;
    unsigned long long generation; /* Owned first-transaction policy, no original epoch. */
    struct full_bb_mode_queue outer, inner;
    uint32_t provider_phase; /* 1: outer work executing, 2: inner work executing. */
    full_bb_mode_outer_provider outer_provider;
    full_bb_mode_inner_provider inner_provider;
    void *provider_context;
};

/* Entirely zero owned storage only; never copies, resets, or fault recovery.
 * Serial caller holds its parent guard for all access, including providers.
 * No mutex, scheduler, transport, original callback, or original status lives here.
 * Runtime failure latches fault/pending, retains records and executing ownership,
 * and cannot be retried or reset. Providers may only call enqueue_inner from the
 * outer work; other reentry fails even if its error is ignored by the provider.
 * Caller owns reply lifetime and must prove it independently; a later mode
 * transaction requires additional lifecycle proof, not another init/enqueue. */
int full_bb_mode_work_queue_init(struct full_bb_mode_work_queue *);
/* Return 0 proves admission. Original 69de28's unconditional wrapper0 does not.
 * shortcut: first generation1/target3 job only; extend after later lifecycle proof. */
int full_bb_mode_work_queue_enqueue_outer(struct full_bb_mode_work_queue *,
                                          unsigned long long generation, uint32_t target);
/* RTOS task30/queue3 only; these task IDs are never Linux TIDs.
 * Provider returns 0 only after consuming the 1760B live->snapshot copy and
 * calling enqueue_inner on this same owner, during this call, with context as
 * proof_context. A success with no inner admission is a retained failure.
 * This provider return is a local consumption contract, not an original status. */
int full_bb_mode_work_queue_dispatch_outer(struct full_bb_mode_work_queue *,
                                           unsigned long long generation, uint32_t task_id,
                                           full_bb_mode_outer_provider, void *context);
/* Only the active outer provider may enqueue; code/adjustment/work are metadata,
 * never host executable pointers. The parent owns snapshot bytes/validity and
 * their borrow lifetime through inner return; this token is semantic provenance. */
int full_bb_mode_work_queue_enqueue_inner(struct full_bb_mode_work_queue *,
                                          unsigned long long generation,
                                          uint32_t snapshot_token, uint32_t work,
                                          void *proof_context);
/* queue4 is shared by owner1788f34/task28, owner1788f54/task29 and
 * owner1788f14/task31, not exclusive to task31. source_owner records the producer.
 * Only after outer work returns. The parent must prove target3/operationMode0
 * before dispatch, and the C provider must consume that conditional child path.
 * rc0 marks work returned; the parent separately generates the second completion.
 * No generic ACK provider can establish these parent-owned facts. */
int full_bb_mode_work_queue_dispatch_inner(struct full_bb_mode_work_queue *,
                                           unsigned long long generation, uint32_t task_id,
                                           full_bb_mode_inner_provider, void *context);
/* Pure masked read; rejection leaves output unchanged, including for unknown gap. */
int full_bb_mode_record_read32(const struct full_bb_mode_record *, uint32_t offset,
                                uint32_t *value);
/* Pure boolean for BOTH work returns, not AP reply consumption or mode completion.
 * Empty rings while a provider is executing never satisfy it. */
int full_bb_mode_work_queue_finished(const struct full_bb_mode_work_queue *,
                                     unsigned long long generation);
#endif
