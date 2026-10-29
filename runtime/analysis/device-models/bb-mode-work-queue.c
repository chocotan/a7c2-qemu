/* SPDX-License-Identifier: MIT */
#include "bb-mode-work-queue.h"
#include <stddef.h>
#include <string.h>

static int zero_bytes(const void *data, size_t bytes)
{
    const unsigned char *p = data;
    for (size_t i = 0; i < bytes; i++) if (p[i]) return 0;
    return 1;
}

static uint32_t read32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void write32(unsigned char *p, uint32_t value)
{
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (8 * i));
}

int full_bb_mode_record_read32(const struct full_bb_mode_record *r, uint32_t offset,
                                uint32_t *value)
{
    if (!r || !value || offset > FULL_BB_MODE_RECORD_BYTES - 4 || offset % 4 ||
        (r->known & ~FULL_BB_MODE_RECORD_KNOWN) ||
        (r->known & (UINT32_C(15) << offset)) != (UINT32_C(15) << offset))
        return FULL_BB_MODE_WORK_ERROR;
    *value = read32(r->bytes + offset);
    return 0;
}

static int record_valid(const struct full_bb_mode_record *r, int inner)
{
    static const uint32_t offsets[] = {0, 4, 8, 12, 16, 24, 28};
    const uint32_t expected[] = {
        inner ? FULL_BB_MODE_INNER_PMF : FULL_BB_MODE_OUTER_PMF, 0,
        inner ? FULL_BB_MODE_INNER_WORK : FULL_BB_MODE_OUTER_WORK, 0, 0,
        inner ? FULL_BB_MODE_SNAPSHOT_TOKEN : 3u, 0
    };
    if (r->known != FULL_BB_MODE_RECORD_KNOWN) return 0;
    for (unsigned int i = 0; i < sizeof offsets / sizeof offsets[0]; i++) {
        uint32_t value;
        if (full_bb_mode_record_read32(r, offsets[i], &value) || value != expected[i]) return 0;
    }
    return 1;
}

/* stage0: unused; stage1: queued; stage2: executing; stage3: work returned. */
static int queue_valid(const struct full_bb_mode_queue *q, int inner, unsigned int stage)
{
    if (q->source_owner != (inner ? FULL_BB_MODE_INNER_OWNER : FULL_BB_MODE_OUTER_OWNER) ||
        q->source_queue != (inner ? 4u : 3u) || q->accepted != (stage != 0) ||
        q->popped != (stage >= 2) || q->inflight != (stage == 2) ||
        q->returned != (stage == 3) || q->count != (stage == 1) ||
        q->ring_read != (stage >= 2 ? FULL_BB_MODE_RECORD_STRIDE : 0u) ||
        q->ring_write != (stage ? FULL_BB_MODE_RECORD_STRIDE : 0u) ||
        q->free_bytes != FULL_BB_MODE_RING_BYTES - (stage == 1 ? FULL_BB_MODE_RECORD_STRIDE : 0u))
        return 0;
    if (stage < 2) {
        if (q->consumer_task || !zero_bytes(&q->executing, sizeof q->executing)) return 0;
    } else if ((!inner && q->consumer_task != 30) ||
               (inner && q->consumer_task != 28 && q->consumer_task != 29 && q->consumer_task != 31) ||
               !record_valid(&q->executing, inner)) return 0;
    if (!stage) return !q->ring_known && zero_bytes(q->ring, sizeof q->ring);
    struct full_bb_mode_record record;
    memcpy(record.bytes, q->ring + 4, sizeof record.bytes);
    record.known = q->ring_known;
    return read32(q->ring) == FULL_BB_MODE_RECORD_BYTES && record_valid(&record, inner);
}

static int inactive_provider(const struct full_bb_mode_work_queue *s)
{
    return !s->provider_phase && !s->outer_provider && !s->inner_provider && !s->provider_context;
}

static int valid(const struct full_bb_mode_work_queue *s)
{
    if (!s || s->identity != s || s->known != 1 || s->fault) return 0;
    if (!s->generation)
        return !s->busy && !s->pending && inactive_provider(s) &&
               queue_valid(&s->outer, 0, 0) && queue_valid(&s->inner, 1, 0);
    if (s->generation != 1) return 0;
    if (!s->outer.returned) {
        if (!s->outer.inflight)
            return !s->busy && s->pending == 1 && inactive_provider(s) &&
                   queue_valid(&s->outer, 0, 1) && queue_valid(&s->inner, 1, 0);
        return s->busy == 1 && s->pending == 1 && s->provider_phase == 1 &&
               s->outer_provider && !s->inner_provider && s->provider_context &&
               queue_valid(&s->outer, 0, 2) &&
               (queue_valid(&s->inner, 1, 0) || queue_valid(&s->inner, 1, 1));
    }
    if (!queue_valid(&s->outer, 0, 3)) return 0;
    if (s->inner.returned)
        return !s->busy && !s->pending && inactive_provider(s) && queue_valid(&s->inner, 1, 3);
    if (!s->inner.inflight)
        return !s->busy && s->pending == 1 && inactive_provider(s) && queue_valid(&s->inner, 1, 1);
    return s->busy == 1 && s->pending == 1 && s->provider_phase == 2 &&
           !s->outer_provider && s->inner_provider && s->provider_context &&
           queue_valid(&s->inner, 1, 2);
}

static int fault(struct full_bb_mode_work_queue *s)
{
    if (s) {
        s->fault = 1;
        s->pending = 1; /* Unknown work retains ownership, including an executing provider. */
    }
    return FULL_BB_MODE_WORK_ERROR;
}

int full_bb_mode_work_queue_init(struct full_bb_mode_work_queue *s)
{
    if (s && s->identity == s && s->known == 1 && s->busy) return fault(s);
    if (!s || !zero_bytes(s, sizeof *s)) return FULL_BB_MODE_WORK_ERROR;
    s->identity = s;
    s->known = 1;
    s->outer.source_owner = FULL_BB_MODE_OUTER_OWNER;
    s->outer.source_queue = 3;
    s->inner.source_owner = FULL_BB_MODE_INNER_OWNER;
    s->inner.source_queue = 4;
    s->outer.free_bytes = s->inner.free_bytes = FULL_BB_MODE_RING_BYTES;
    return 0;
}

static void enqueue(struct full_bb_mode_queue *q, int inner)
{
    write32(q->ring, FULL_BB_MODE_RECORD_BYTES);
    memset(q->ring + 4, 0xa5, FULL_BB_MODE_RECORD_BYTES);
    write32(q->ring + 4, inner ? FULL_BB_MODE_INNER_PMF : FULL_BB_MODE_OUTER_PMF);
    write32(q->ring + 8, 0); /* ARM PMF this adjustment, not a callback context. */
    write32(q->ring + 12, inner ? FULL_BB_MODE_INNER_WORK : FULL_BB_MODE_OUTER_WORK);
    write32(q->ring + 16, 0);
    write32(q->ring + 20, 0);
    write32(q->ring + 28, inner ? FULL_BB_MODE_SNAPSHOT_TOKEN : 3u);
    write32(q->ring + 32, 0);
    q->ring_known = FULL_BB_MODE_RECORD_KNOWN;
    q->ring_write = FULL_BB_MODE_RECORD_STRIDE;
    q->free_bytes -= FULL_BB_MODE_RECORD_STRIDE;
    q->count = q->accepted = 1;
}

int full_bb_mode_work_queue_enqueue_outer(struct full_bb_mode_work_queue *s,
                                          unsigned long long generation, uint32_t target)
{
    if (!valid(s) || s->busy || s->generation || generation != 1 || target != 3) return fault(s);
    enqueue(&s->outer, 0);
    s->generation = generation;
    s->pending = 1;
    return 0;
}

static void pop(struct full_bb_mode_queue *q, uint32_t task_id)
{
    memcpy(q->executing.bytes, q->ring + 4, sizeof q->executing.bytes);
    q->executing.known = q->ring_known;
    q->ring_read = FULL_BB_MODE_RECORD_STRIDE;
    q->free_bytes += FULL_BB_MODE_RECORD_STRIDE; /* Source 1db198 returns ring space before work. */
    q->count = 0;
    q->popped = q->inflight = 1;
    q->consumer_task = task_id;
}

int full_bb_mode_work_queue_enqueue_inner(struct full_bb_mode_work_queue *s,
                                          unsigned long long generation,
                                          uint32_t snapshot_token, uint32_t work,
                                          void *proof_context)
{
    if (!valid(s) || generation != 1 || s->generation != generation ||
        s->provider_phase != 1 || !s->busy || !s->outer.inflight || s->inner.accepted ||
        !proof_context || proof_context != s->provider_context ||
        snapshot_token != FULL_BB_MODE_SNAPSHOT_TOKEN || work != FULL_BB_MODE_INNER_WORK)
        return fault(s);
    enqueue(&s->inner, 1);
    return 0;
}

int full_bb_mode_work_queue_dispatch_outer(struct full_bb_mode_work_queue *s,
                                           unsigned long long generation, uint32_t task_id,
                                           full_bb_mode_outer_provider provider, void *context)
{
    if (!valid(s) || generation != 1 || s->generation != generation || task_id != 30 ||
        s->busy || s->outer.count != 1 || !provider || !context) return fault(s);
    s->busy = 1;
    s->provider_phase = 1;
    s->outer_provider = provider;
    s->provider_context = context;
    pop(&s->outer, task_id);
    uint32_t target;
    if (full_bb_mode_record_read32(&s->outer.executing, 24, &target)) return fault(s);
    int rc = provider(context, target);
    /* Validate allowed inner enqueue, not a whole-owner memcmp which would reject it. */
    if (rc || !valid(s) || s->provider_phase != 1 || s->outer_provider != provider ||
        s->provider_context != context || s->inner.accepted != 1) {
        s->busy = 1;
        return fault(s);
    }
    s->outer.inflight = 0;
    s->outer.returned = 1;
    s->busy = s->provider_phase = 0;
    s->outer_provider = 0;
    s->provider_context = 0;
    return 0;
}

int full_bb_mode_work_queue_dispatch_inner(struct full_bb_mode_work_queue *s,
                                           unsigned long long generation, uint32_t task_id,
                                           full_bb_mode_inner_provider provider, void *context)
{
    if (!valid(s) || generation != 1 || s->generation != generation ||
        (task_id != 28 && task_id != 29 && task_id != 31) || s->busy ||
        s->outer.returned != 1 || s->inner.count != 1 || !provider || !context) return fault(s);
    s->busy = 1;
    s->provider_phase = 2;
    s->inner_provider = provider;
    s->provider_context = context;
    pop(&s->inner, task_id);
    uint32_t snapshot_token;
    if (full_bb_mode_record_read32(&s->inner.executing, 24, &snapshot_token)) return fault(s);
    int rc = provider(context, snapshot_token);
    if (rc || !valid(s) || s->provider_phase != 2 || s->inner_provider != provider ||
        s->provider_context != context || s->inner.consumer_task != task_id) {
        s->busy = 1;
        return fault(s);
    }
    s->inner.inflight = 0;
    s->inner.returned = 1;
    s->busy = s->pending = s->provider_phase = 0;
    s->inner_provider = 0;
    s->provider_context = 0;
    return 0;
}

int full_bb_mode_work_queue_finished(const struct full_bb_mode_work_queue *s,
                                     unsigned long long generation)
{
    return generation == 1 && valid(s) && s->generation == generation &&
           s->outer.returned == 1 && s->inner.returned == 1;
}
