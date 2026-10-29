/* SPDX-License-Identifier: MIT */
#include "bb-mode-work-queue.h"
#include <assert.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

typedef struct full_bb_mode_work_queue Queue;
static unsigned int cases;
struct context {
    Queue *owner;
    unsigned char live[1760], snapshot[1760], expected[1760];
    unsigned int copies, outer_calls, inner_calls, consumed, task;
    unsigned int action, attack_inner, bad_inner_argument;
    size_t tamper_offset;
    int provider_result;
    Queue observed;
};
static int outer_work(void *, uint32_t);
static int inner_work(void *, uint32_t);

static int invoke(Queue *s, struct context *ctx, unsigned int phase,
                    unsigned long long generation, uint32_t argument)
{
    if (!phase) return full_bb_mode_work_queue_enqueue_outer(s, generation, argument);
    if (phase == 1)
        return full_bb_mode_work_queue_dispatch_outer(s, generation, argument, outer_work, ctx);
    return full_bb_mode_work_queue_dispatch_inner(s, generation, argument, inner_work, ctx);
}

static void attack(struct context *ctx)
{
    Queue *s = ctx->owner;
    switch (ctx->action) {
    case 0: break;
    case 1:
        assert(full_bb_mode_work_queue_enqueue_outer(s, 1, 3) == FULL_BB_MODE_WORK_ERROR);
        break;
    case 2:
        assert(full_bb_mode_work_queue_dispatch_outer(s, 1, 30, outer_work, ctx) == FULL_BB_MODE_WORK_ERROR);
        break;
    case 3:
        assert(full_bb_mode_work_queue_dispatch_inner(s, 1, 31, inner_work, ctx) == FULL_BB_MODE_WORK_ERROR);
        break;
    case 4:
        assert(full_bb_mode_work_queue_init(s) == FULL_BB_MODE_WORK_ERROR);
        break;
    case 5:
        assert(full_bb_mode_work_queue_enqueue_inner(s, 1, FULL_BB_MODE_SNAPSHOT_TOKEN,
                 FULL_BB_MODE_INNER_WORK, ctx) == FULL_BB_MODE_WORK_ERROR);
        break;
    case 6:
        assert(ctx->tamper_offset < sizeof *s);
        ((unsigned char *)s)[ctx->tamper_offset] ^= 1;
        break;
    case 7:
        /* The unknown gap is not an integrity checksum or a zero predicate. */
        memset(s->outer.ring + 24, 0x39, 4);
        memset(s->outer.executing.bytes + 20, 0x91, 4);
        memset(s->inner.ring + 24, 0x47, 4);
        if (ctx->attack_inner) memset(s->inner.executing.bytes + 20, 0x82, 4);
        break;
    case 8: {
        uint32_t value = UINT32_C(0x12345678);
        const struct full_bb_mode_record *r = ctx->attack_inner ? &s->inner.executing : &s->outer.executing;
        assert(full_bb_mode_record_read32(r, 20, &value) == FULL_BB_MODE_WORK_ERROR);
        assert(value == UINT32_C(0x12345678) && !s->fault);
        break;
    }
    default: assert(0);
    }
}

static int outer_work(void *opaque, uint32_t target)
{
    struct context *ctx = opaque;
    Queue *s = ctx->owner;
    ctx->outer_calls++;
    assert(ctx->outer_calls == 1 && target == 3);
    assert(s->identity == s && !s->fault && s->busy == 1 && s->pending == 1);
    assert(s->provider_phase == 1 && s->outer_provider == outer_work && s->provider_context == ctx);
    assert(s->outer.count == 0 && s->outer.free_bytes == FULL_BB_MODE_RING_BYTES);
    assert(s->outer.ring_read == 36 && s->outer.ring_write == 36 && s->outer.popped == 1);
    assert(s->outer.inflight == 1 && !s->outer.returned && s->outer.consumer_task == 30);
    assert(!s->inner.accepted && !full_bb_mode_work_queue_finished(s, 1));
    assert(!memcmp(s->outer.executing.bytes, s->outer.ring + 4, 32));
    assert(s->outer.executing.known == FULL_BB_MODE_RECORD_KNOWN);
    /* A real provider consumes the source->borrowed-snapshot copy before enqueue. */
    memcpy(ctx->snapshot, ctx->live, sizeof ctx->snapshot);
    memcpy(ctx->expected, ctx->live, sizeof ctx->expected);
    ctx->copies++;
    if (ctx->provider_result && !ctx->attack_inner && ctx->action == 9) {
        memcpy(&ctx->observed, s, sizeof *s);
        return ctx->provider_result;
    }
    if (ctx->action == 10 && !ctx->attack_inner) {
        memcpy(&ctx->observed, s, sizeof *s);
        return 0; /* A bare wrapper0 without child admission must fail. */
    }
    if (ctx->bad_inner_argument) {
        assert(full_bb_mode_work_queue_enqueue_inner(s, ctx->bad_inner_argument == 1 ? 2 : 1,
                 FULL_BB_MODE_SNAPSHOT_TOKEN ^ (ctx->bad_inner_argument == 2),
                 FULL_BB_MODE_INNER_WORK ^ (ctx->bad_inner_argument == 3),
                 ctx->bad_inner_argument == 4 ? (void *)s : ctx->bad_inner_argument == 5 ? 0 : ctx)
               == FULL_BB_MODE_WORK_ERROR);
        memcpy(&ctx->observed, s, sizeof *s);
        return 0;
    }
    assert(!full_bb_mode_work_queue_enqueue_inner(s, 1, FULL_BB_MODE_SNAPSHOT_TOKEN,
                                                  FULL_BB_MODE_INNER_WORK, ctx));
    assert(s->outer.inflight == 1 && !s->outer.returned && s->inner.count == 1);
    assert(!full_bb_mode_work_queue_finished(s, 1));
    if (!ctx->attack_inner && ctx->action < 9) attack(ctx);
    memcpy(&ctx->observed, s, sizeof *s);
    return ctx->attack_inner ? 0 : ctx->provider_result;
}

static int inner_work(void *opaque, uint32_t token)
{
    struct context *ctx = opaque;
    Queue *s = ctx->owner;
    ctx->inner_calls++;
    assert(ctx->inner_calls == 1 && token == FULL_BB_MODE_SNAPSHOT_TOKEN);
    assert(s->identity == s && !s->fault && s->busy == 1 && s->pending == 1);
    assert(s->provider_phase == 2 && s->inner_provider == inner_work && s->provider_context == ctx);
    assert(s->outer.returned == 1 && !s->outer.inflight);
    assert(!s->inner.count && s->inner.free_bytes == FULL_BB_MODE_RING_BYTES);
    assert(s->inner.ring_read == 36 && s->inner.ring_write == 36 && s->inner.popped == 1);
    assert(s->inner.inflight == 1 && !s->inner.returned && s->inner.consumer_task == ctx->task);
    assert(!full_bb_mode_work_queue_finished(s, 1));
    assert(!memcmp(s->inner.executing.bytes, s->inner.ring + 4, 32));
    assert(ctx->copies == 1 && !memcmp(ctx->snapshot, ctx->expected, sizeof ctx->snapshot));
    /* Conditional target3/op0 consumer: no hardware actions or original callbacks. */
    ctx->consumed++;
    if (ctx->attack_inner && ctx->action < 9) attack(ctx);
    memcpy(&ctx->observed, s, sizeof *s);
    return ctx->provider_result;
}

static void advance(Queue *s, struct context *ctx, unsigned int phase)
{
    memset(s, 0, sizeof *s);
    memset(ctx, 0, sizeof *ctx);
    ctx->owner = s;
    ctx->task = 31;
    for (size_t i = 0; i < sizeof ctx->live; i++) ctx->live[i] = (unsigned char)(i * 29 + i / 7);
    memset(ctx->snapshot, 0xcc, sizeof ctx->snapshot);
    assert(!full_bb_mode_work_queue_init(s));
    assert(s->known == 1 && s->identity == s && !s->generation && !s->fault && !s->pending && !s->busy);
    assert(s->outer.source_queue == 3 && s->inner.source_queue == 4);
    assert(s->outer.source_owner == FULL_BB_MODE_OUTER_OWNER && s->inner.source_owner == FULL_BB_MODE_INNER_OWNER);
    assert(s->outer.free_bytes == 10240 && s->inner.free_bytes == 10240);
    assert(!full_bb_mode_work_queue_finished(s, 1));
    for (unsigned int step = 0; step < phase; step++)
        assert(!invoke(s, ctx, step, 1, step == 0 ? 3 : step == 1 ? 30 : ctx->task));
}

static void rejected(Queue *s, struct context *ctx, unsigned int operation,
                       unsigned long long generation, uint32_t argument)
{
    Queue expected;
    memcpy(&expected, s, sizeof expected);
    expected.fault = expected.pending = 1;
    unsigned int calls = ctx->outer_calls + ctx->inner_calls;
    assert(invoke(s, ctx, operation, generation, argument) == FULL_BB_MODE_WORK_ERROR);
    assert(!memcmp(s, &expected, sizeof expected));
    assert(calls == ctx->outer_calls + ctx->inner_calls && !full_bb_mode_work_queue_finished(s, 1));
    assert(full_bb_mode_work_queue_init(s) == FULL_BB_MODE_WORK_ERROR);
    assert(!memcmp(s, &expected, sizeof expected));
    cases++;
}

static void test_real_two_level_work_and_opaque_gap(void)
{
    static const uint32_t tasks[] = {28, 29, 31};
    static const unsigned char gaps[] = {0, 0xa5, 0xff};
    const unsigned char inner_pmf[] = {0x05, 0x54, 0x69, 0};
    const unsigned char inner_work_bytes[] = {0xed, 0x37, 0x1b, 0};
    for (unsigned int t = 0; t < 3; t++) for (unsigned int g = 0; g < 3; g++) {
        Queue s, before;
        struct context ctx;
        unsigned char outer_ring[36], inner_ring[36];
        advance(&s, &ctx, 1);
        assert(s.generation == 1 && s.pending == 1 && !s.busy);
        assert(s.outer.count == 1 && s.outer.ring_read == 0 && s.outer.ring_write == 36);
        assert(s.outer.free_bytes == 10204 && !s.outer.inflight && !s.outer.returned);
        memset(s.outer.ring + 24, gaps[g], 4);
        memcpy(outer_ring, s.outer.ring, sizeof outer_ring);
        assert(!full_bb_mode_work_queue_dispatch_outer(&s, 1, 30, outer_work, &ctx));
        assert(s.outer.returned == 1 && !s.outer.inflight && !s.busy && s.pending == 1);
        assert(s.inner.accepted == 1 && s.inner.count == 1 && !s.inner.inflight);
        assert(!memcmp(s.outer.ring, outer_ring, sizeof outer_ring));
        assert(!memcmp(s.outer.executing.bytes, outer_ring + 4, 32));
        assert(!memcmp(s.inner.ring + 4, inner_pmf, sizeof inner_pmf));
        assert(!memcmp(s.inner.ring + 12, inner_work_bytes, sizeof inner_work_bytes));
        for (unsigned int i = 24; i < 28; i++) assert(s.inner.ring[i] == 0xa5);
        assert(!full_bb_mode_work_queue_finished(&s, 1));
        memset(s.inner.ring + 24, gaps[g], 4);
        memcpy(inner_ring, s.inner.ring, sizeof inner_ring);
        ctx.task = tasks[t];
        memset(ctx.live, 0x55, sizeof ctx.live); /* Snapshot is stable after outer returns. */
        assert(!full_bb_mode_work_queue_dispatch_inner(&s, 1, tasks[t], inner_work, &ctx));
        assert(s.outer.returned == 1 && s.inner.returned == 1 && !s.outer.inflight && !s.inner.inflight);
        assert(!s.busy && !s.pending && !s.fault && !s.provider_phase && !s.provider_context);
        assert(!s.outer_provider && !s.inner_provider && ctx.copies == 1 && ctx.consumed == 1);
        assert(ctx.outer_calls == 1 && ctx.inner_calls == 1 && s.inner.consumer_task == tasks[t]);
        assert(!memcmp(s.outer.ring, outer_ring, sizeof outer_ring));
        assert(!memcmp(s.outer.executing.bytes, outer_ring + 4, 32));
        assert(!memcmp(s.inner.ring, inner_ring, sizeof inner_ring));
        assert(!memcmp(s.inner.executing.bytes, inner_ring + 4, 32));
        assert(s.outer.free_bytes == 10240 && s.inner.free_bytes == 10240);
        assert(full_bb_mode_work_queue_finished(&s, 1));
        assert(!full_bb_mode_work_queue_finished(&s, 0) && !full_bb_mode_work_queue_finished(&s, 2));
        memcpy(&before, &s, sizeof before);
        assert(full_bb_mode_work_queue_init(&s) == FULL_BB_MODE_WORK_ERROR && !memcmp(&s, &before, sizeof s));
        rejected(&s, &ctx, 0, 1, 3); /* No implicit second transaction/reply retirement. */
    }
    assert(FULL_BB_MODE_SOURCE_CAPACITY == FULL_BB_MODE_RING_BYTES / FULL_BB_MODE_RECORD_STRIDE);
    puts("BB_MODE_WORK_QUEUE_REAL_COPY_TWO_RETURNS_SHARED_TASKS_OPAQUE_GAP_PASS");
}

static void test_masked_read(void)
{
    Queue s;
    struct context ctx;
    advance(&s, &ctx, 2);
    struct full_bb_mode_record r;
    memcpy(r.bytes, s.inner.ring + 4, sizeof r.bytes);
    r.known = s.inner.ring_known;
    static const uint32_t offsets[] = {0, 4, 8, 12, 16, 24, 28};
    for (unsigned int i = 0; i < sizeof offsets / sizeof offsets[0]; i++) {
        uint32_t value = UINT32_MAX;
        assert(!full_bb_mode_record_read32(&r, offsets[i], &value));
        for (unsigned int byte = 0; byte < 4; byte++) {
            struct full_bb_mode_record missing = r;
            missing.known &= ~(UINT32_C(1) << (offsets[i] + byte));
            value = UINT32_MAX;
            assert(full_bb_mode_record_read32(&missing, offsets[i], &value) == FULL_BB_MODE_WORK_ERROR);
            assert(value == UINT32_MAX);
            cases++;
        }
    }
    for (uint32_t offset = 0; offset < 36; offset++) {
        if (offset < 32 && offset % 4 == 0 && offset != 20) continue;
        uint32_t value = UINT32_MAX;
        assert(full_bb_mode_record_read32(&r, offset, &value) == FULL_BB_MODE_WORK_ERROR);
        assert(value == UINT32_MAX);
        cases++;
    }
    uint32_t value = UINT32_MAX;
    r.known = UINT32_MAX; /* Making up validity cannot turn the gap into a field. */
    assert(full_bb_mode_record_read32(&r, 20, &value) == FULL_BB_MODE_WORK_ERROR && value == UINT32_MAX);
    assert(full_bb_mode_record_read32(&r, UINT32_MAX, &value) == FULL_BB_MODE_WORK_ERROR && value == UINT32_MAX);
    assert(full_bb_mode_record_read32(0, 0, &value) == FULL_BB_MODE_WORK_ERROR && value == UINT32_MAX);
    assert(full_bb_mode_record_read32(&r, 0, 0) == FULL_BB_MODE_WORK_ERROR);
    puts("BB_MODE_WORK_QUEUE_MASKED_READ_UNKNOWN_GAP_REJECT_PASS");
}

static void test_order_and_arguments(void)
{
    static const unsigned long long generations[] = {0, 2, ULLONG_MAX};
    static const uint32_t bad_targets[] = {0, 1, 2, 4, 5, 6, 7, UINT32_MAX};
    static const uint32_t bad_tasks[] = {0, 27, 32, 381, 1037, UINT32_MAX};
    Queue s, before;
    struct context ctx;
    for (unsigned int phase = 0; phase < 3; phase++) {
        for (unsigned int i = 0; i < 3; i++) {
            advance(&s, &ctx, phase);
            rejected(&s, &ctx, phase, generations[i], phase == 0 ? 3 : phase == 1 ? 30 : 31);
        }
        for (unsigned int i = 0; i < sizeof bad_tasks / sizeof bad_tasks[0]; i++) {
            advance(&s, &ctx, phase);
            rejected(&s, &ctx, phase, 1, bad_tasks[i]);
        }
        assert(invoke(0, &ctx, phase, 1, phase == 0 ? 3 : phase == 1 ? 30 : 31) == FULL_BB_MODE_WORK_ERROR);
    }
    for (unsigned int i = 0; i < sizeof bad_targets / sizeof bad_targets[0]; i++) {
        advance(&s, &ctx, 0);
        rejected(&s, &ctx, 0, 1, bad_targets[i]);
    }
    for (unsigned int phase = 0; phase < 3; phase++)
        for (unsigned int operation = 0; operation < 3; operation++) {
            if (phase == operation) continue;
            advance(&s, &ctx, phase);
            rejected(&s, &ctx, operation, 1, operation == 0 ? 3 : operation == 1 ? 30 : 31);
        }
    /* queue3 has one consumer; queue4 really accepts all three, but never task30. */
    for (uint32_t task = 28; task <= 31; task++) {
        if (task == 30) continue;
        advance(&s, &ctx, 1);
        rejected(&s, &ctx, 1, 1, task);
    }
    advance(&s, &ctx, 2);
    rejected(&s, &ctx, 2, 1, 30);
    for (unsigned int phase = 1; phase <= 2; phase++) for (unsigned int missing = 0; missing < 2; missing++) {
        advance(&s, &ctx, phase);
        memcpy(&before, &s, sizeof before);
        before.fault = before.pending = 1;
        int rc = phase == 1 ? full_bb_mode_work_queue_dispatch_outer(&s, 1, 30,
                     missing ? outer_work : 0, missing ? 0 : &ctx) :
                 full_bb_mode_work_queue_dispatch_inner(&s, 1, 31,
                     missing ? inner_work : 0, missing ? 0 : &ctx);
        assert(rc == FULL_BB_MODE_WORK_ERROR && !memcmp(&s, &before, sizeof s));
        assert(ctx.outer_calls == (phase == 2) && !ctx.inner_calls);
        cases++;
    }
    advance(&s, &ctx, 0);
    assert(full_bb_mode_work_queue_enqueue_inner(&s, 1, FULL_BB_MODE_SNAPSHOT_TOKEN,
             FULL_BB_MODE_INNER_WORK, &ctx) == FULL_BB_MODE_WORK_ERROR);
    assert(s.fault && s.pending && !s.inner.accepted);
    puts("BB_MODE_WORK_QUEUE_ORDER_GENERATION_TARGET_TASK_ADMISSION_REJECT_PASS");
}

#define OFF(field) offsetof(Queue, field)
#define QOFF(which, field) (OFF(which) + offsetof(struct full_bb_mode_queue, field))
static const size_t owned_offsets[] = {
    OFF(identity), OFF(known), OFF(fault), OFF(busy), OFF(pending), OFF(generation),
    OFF(provider_phase), OFF(outer_provider), OFF(inner_provider), OFF(provider_context),
    QOFF(outer, source_owner), QOFF(outer, source_queue), QOFF(outer, ring_known),
    QOFF(outer, ring_read), QOFF(outer, ring_write), QOFF(outer, free_bytes), QOFF(outer, count),
    QOFF(outer, accepted), QOFF(outer, popped), QOFF(outer, inflight), QOFF(outer, returned), QOFF(outer, consumer_task),
    QOFF(inner, source_owner), QOFF(inner, source_queue), QOFF(inner, ring_known),
    QOFF(inner, ring_read), QOFF(inner, ring_write), QOFF(inner, free_bytes), QOFF(inner, count),
    QOFF(inner, accepted), QOFF(inner, popped), QOFF(inner, inflight), QOFF(inner, returned), QOFF(inner, consumer_task),
    QOFF(outer, executing) + offsetof(struct full_bb_mode_record, known),
    QOFF(inner, executing) + offsetof(struct full_bb_mode_record, known)
};

static void test_constructor_copies_and_tamper(void)
{
    Queue s, copy;
    struct context ctx;
    assert(full_bb_mode_work_queue_init(0) == FULL_BB_MODE_WORK_ERROR);
    assert(!full_bb_mode_work_queue_finished(0, 1));
    for (size_t byte = 0; byte < sizeof s; byte++) {
        memset(&s, 0, sizeof s);
        ((unsigned char *)&s)[byte] = 0xa5;
        memcpy(&copy, &s, sizeof copy);
        assert(full_bb_mode_work_queue_init(&s) == FULL_BB_MODE_WORK_ERROR);
        assert(!memcmp(&copy, &s, sizeof s));
        cases++;
    }
    for (unsigned int phase = 0; phase <= 3; phase++) {
        advance(&s, &ctx, phase);
        memcpy(&copy, &s, sizeof copy);
        assert(!full_bb_mode_work_queue_finished(&copy, 1));
        assert(full_bb_mode_work_queue_init(&copy) == FULL_BB_MODE_WORK_ERROR);
        rejected(&copy, &ctx, phase < 3 ? phase : 0, 1, phase == 1 ? 30 : phase == 2 ? 31 : 3);
        assert(!s.fault && s.identity == &s && (phase != 3 || full_bb_mode_work_queue_finished(&s, 1)));
        for (unsigned int i = 0; i < sizeof owned_offsets / sizeof owned_offsets[0]; i++) {
            advance(&s, &ctx, phase);
            ((unsigned char *)&s)[owned_offsets[i]] ^= 1;
            assert(!full_bb_mode_work_queue_finished(&s, 1));
            rejected(&s, &ctx, phase < 3 ? phase : 0, 1, phase == 1 ? 30 : phase == 2 ? 31 : 3);
        }
        for (unsigned int inner = 0; inner < 2; inner++) for (unsigned int byte = 0; byte < 36; byte++) {
            if (byte >= 24 && byte < 28) continue;
            advance(&s, &ctx, phase);
            struct full_bb_mode_queue *q = inner ? &s.inner : &s.outer;
            q->ring[byte] ^= 1;
            assert(!full_bb_mode_work_queue_finished(&s, 1));
            rejected(&s, &ctx, phase < 3 ? phase : 0, 1, phase == 1 ? 30 : phase == 2 ? 31 : 3);
        }
    }
    puts("BB_MODE_WORK_QUEUE_CTOR_ZERO_ONLY_COPY_IDENTITY_TAMPER_REJECT_PASS");
}

static void check_provider_failure(Queue *s, struct context *ctx, unsigned int inner)
{
    ctx->observed.fault = ctx->observed.pending = ctx->observed.busy = 1;
    assert(!memcmp(s, &ctx->observed, sizeof *s));
    assert(s->fault == 1 && s->pending == 1 && s->busy == 1);
    if (ctx->action != 6) assert(inner ? !s->inner.returned : !s->outer.returned);
    assert(!full_bb_mode_work_queue_finished(s, 1));
    Queue before;
    memcpy(&before, s, sizeof before);
    assert(full_bb_mode_work_queue_init(s) == FULL_BB_MODE_WORK_ERROR && !memcmp(s, &before, sizeof before));
    unsigned int calls = ctx->outer_calls + ctx->inner_calls;
    assert(invoke(s, ctx, inner ? 2 : 1, 1, inner ? 31 : 30) == FULL_BB_MODE_WORK_ERROR);
    assert(!memcmp(s, &before, sizeof before) && calls == ctx->outer_calls + ctx->inner_calls);
    cases++;
}

static void test_provider_failure_reentry_and_mutation(void)
{
    static const int failures[] = {-5, 1, 0x1004, FULL_BB_MODE_WORK_ERROR};
    Queue s;
    struct context ctx;
    for (unsigned int inner = 0; inner < 2; inner++) {
        for (unsigned int i = 0; i < sizeof failures / sizeof failures[0]; i++) {
            advance(&s, &ctx, inner ? 2 : 1);
            ctx.attack_inner = inner;
            ctx.provider_result = failures[i];
            assert(invoke(&s, &ctx, inner ? 2 : 1, 1, inner ? 31 : 30) == FULL_BB_MODE_WORK_ERROR);
            check_provider_failure(&s, &ctx, inner);
            assert(s.outer.free_bytes == 10240 && (inner ? s.inner.free_bytes == 10240 : s.inner.count == 1));
        }
        for (unsigned int action = 1; action <= 8; action++) {
            if (action == 6) continue;
            advance(&s, &ctx, inner ? 2 : 1);
            ctx.attack_inner = inner;
            ctx.action = action;
            int rc = invoke(&s, &ctx, inner ? 2 : 1, 1, inner ? 31 : 30);
            if (action == 7 || action == 8) {
                assert(!rc && !s.fault && !s.busy && s.pending == !inner);
                cases++;
            } else {
                assert(rc == FULL_BB_MODE_WORK_ERROR);
                check_provider_failure(&s, &ctx, inner);
            }
        }
        for (unsigned int i = 0; i < sizeof owned_offsets / sizeof owned_offsets[0]; i++) {
            advance(&s, &ctx, inner ? 2 : 1);
            ctx.attack_inner = inner;
            ctx.action = 6;
            ctx.tamper_offset = owned_offsets[i];
            assert(invoke(&s, &ctx, inner ? 2 : 1, 1, inner ? 31 : 30) == FULL_BB_MODE_WORK_ERROR);
            check_provider_failure(&s, &ctx, inner);
        }
        for (unsigned int which = 0; which < 2; which++) for (unsigned int byte = 0; byte < 32; byte++) {
            if (byte >= 20 && byte < 24) continue;
            advance(&s, &ctx, inner ? 2 : 1);
            ctx.attack_inner = inner;
            ctx.action = 6;
            ctx.tamper_offset = (which ? QOFF(inner, executing) : QOFF(outer, executing)) + byte;
            assert(invoke(&s, &ctx, inner ? 2 : 1, 1, inner ? 31 : 30) == FULL_BB_MODE_WORK_ERROR);
            check_provider_failure(&s, &ctx, inner);
        }
    }
    for (unsigned int i = 0; i < 2; i++) {
        advance(&s, &ctx, 2);
        ctx.task = i ? 29 : 28;
        ctx.attack_inner = 1;
        ctx.action = 6;
        ctx.tamper_offset = QOFF(inner, consumer_task);
        assert(full_bb_mode_work_queue_dispatch_inner(&s, 1, ctx.task, inner_work, &ctx)
               == FULL_BB_MODE_WORK_ERROR);
        check_provider_failure(&s, &ctx, 1);
    }
    for (unsigned int bad = 1; bad <= 5; bad++) {
        advance(&s, &ctx, 1);
        ctx.bad_inner_argument = bad;
        assert(full_bb_mode_work_queue_dispatch_outer(&s, 1, 30, outer_work, &ctx) == FULL_BB_MODE_WORK_ERROR);
        assert(!s.inner.accepted && s.outer.inflight == 1);
        check_provider_failure(&s, &ctx, 0);
    }
    for (unsigned int action = 9; action <= 10; action++) {
        advance(&s, &ctx, 1);
        ctx.action = action;
        ctx.provider_result = action == 9 ? -5 : 0;
        assert(full_bb_mode_work_queue_dispatch_outer(&s, 1, 30, outer_work, &ctx) == FULL_BB_MODE_WORK_ERROR);
        assert(!s.inner.accepted && s.outer.inflight == 1);
        check_provider_failure(&s, &ctx, 0);
    }
    puts("BB_MODE_WORK_QUEUE_PROVIDER_FAILURE_REENTRY_TAMPER_RETAINED_PASS");
    puts("BB_MODE_WORK_QUEUE_EMPTY_INFLIGHT_OR_WRAPPER0_NEVER_FINISHED_PASS");
}

int main(void)
{
    test_real_two_level_work_and_opaque_gap();
    test_masked_read();
    test_order_and_arguments();
    test_constructor_copies_and_tamper();
    test_provider_failure_reentry_and_mutation();
    printf("BB_MODE_WORK_QUEUE_CASES=%u\n", cases);
    return 0;
}
