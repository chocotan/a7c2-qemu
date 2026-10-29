/* SPDX-License-Identifier: MIT */
#include "adf-avio-output.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

static unsigned char speech[1024 * 1024], speech_before[1024 * 1024];
static struct full_adf_avio_snapshot seed;
static unsigned int listener_calls, same_calls, rejected;
static unsigned int get32(const unsigned char *p)
{
    return p[0] | (unsigned int)p[1] << 8 | (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24;
}
static void put32(unsigned char *p, unsigned int value)
{
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (8 * i));
}
static void listener(void *context, unsigned int status)
{
    struct full_adf_avio_output *s = context;
    assert(!status && s && !s->fault && !s->output_finished);
    assert(s->consumed == 2 && s->count == 1 && s->read_index == 2);
    assert(s->last_event == 3 && s->vsync_events == 3 && s->pending_events == 1);
    assert(s->callback_running == 1 && s->callback_calls == 1);
    assert(s->current_mask == 8 && s->requested_mask == 8 && s->source_cache == 0xff);
    assert(s->shadow_writes == 7 && s->touched_writes == 7);
    assert((get32(s->snapshot.shadow) & 0x07070000u) == 0x01060000u);
    for (unsigned int i = 0; i < 3; i++) assert(s->stage_counts[i] == 1);
    listener_calls++;
}
static void cold(struct full_adf_avio_output *s)
{
    memset(s, 0, sizeof *s);
    assert(!full_adf_avio_output_init(s, seed.shadow, seed.changed, seed.touched, 1));
}
static void queued(struct full_adf_avio_output *s, full_adf_avio_listener callback)
{
    cold(s);
    assert(!full_adf_avio_output_enqueue(s, 1, 8, callback, s));
}
static void snapshot_equal(const struct full_adf_avio_snapshot *a,
                            const struct full_adf_avio_snapshot *b)
{
    assert(!memcmp(a, b, sizeof *a));
    assert(!memcmp(speech, speech_before, sizeof speech));
}
static void rejection_equal(const unsigned char *before, struct full_adf_avio_output *s)
{
    struct full_adf_avio_output expected;
    memcpy(&expected, before, sizeof expected);
    if (expected.generation || expected.queued) expected.fault = 1;
    assert(!memcmp(&expected, s, sizeof expected));
    assert(!memcmp(speech, speech_before, sizeof speech));
    rejected++;
}
static void reject_enqueue(struct full_adf_avio_output *s, unsigned long long generation,
                            unsigned int target, full_adf_avio_listener callback)
{
    unsigned char before[sizeof *s];
    memcpy(before, s, sizeof before);
    assert(full_adf_avio_output_enqueue(s, generation, target, callback, s) == -1021);
    rejection_equal(before, s);
}
static void reject_event(struct full_adf_avio_output *s, unsigned long long generation,
                          unsigned long long event)
{
    unsigned char before[sizeof *s];
    unsigned int calls = listener_calls + same_calls;
    memcpy(before, s, sizeof before);
    assert(full_adf_avio_output_consume_vsync(s, generation, event) == -1021);
    rejection_equal(before, s);
    assert(listener_calls + same_calls == calls);
}
static void check_init(void)
{
    struct full_adf_avio_output s;
    assert(full_adf_avio_output_init(0, seed.shadow, seed.changed, seed.touched, 1) == -1021);
    assert(full_adf_avio_output_enqueue(0, 1, 8, listener, 0) == -1021);
    assert(full_adf_avio_output_consume_vsync(0, 1, 1) == -1021);
    for (unsigned int kind = 0; kind < 9; kind++) {
        memset(&s, 0, sizeof s);
        if (kind == 7) s.jobs[59].opaque_lease = 0x8400;
        if (kind == 8) cold(&s);
        unsigned char before[sizeof s];
        memcpy(before, &s, sizeof before);
        assert(full_adf_avio_output_init(&s, kind == 0 ? 0 : seed.shadow,
            kind == 1 ? 0 : seed.changed, kind == 2 ? 0 : seed.touched,
            kind == 3 ? 0 : kind == 4 ? 2 : kind == 5 ? 0xff : kind == 6 ? UINT_MAX : 1) == -1021);
        assert(!memcmp(before, &s, sizeof before));
    }
}
static void check_success(unsigned int fields_already_set)
{
    struct full_adf_avio_output s;
    cold(&s);
    if (fields_already_set) {
        put32(s.initial.shadow + 0x10, (get32(s.initial.shadow + 0x10) | 0x08000000u) & ~0x04000000u);
        put32(s.initial.shadow + 0x18, get32(s.initial.shadow + 0x18) | 0x44000000u);
        put32(s.initial.shadow, (get32(s.initial.shadow) & ~0x07070000u) | 0x01060000u);
        s.snapshot = s.initial;
    }
    struct full_adf_avio_snapshot expected = s.snapshot;
    unsigned int callbacks_before = listener_calls;
    assert(!full_adf_avio_output_enqueue(&s, 1, 8, listener, &s));
    assert(s.count == 3 && s.queued == 3 && !s.consumed && !s.output_finished);
    assert(!s.current_mask && s.requested_mask == 8 && s.source_cache == 0xff);
    assert(!s.jobs[0].callback && !s.jobs[1].callback && s.jobs[2].callback);
    snapshot_equal(&expected, &s.snapshot);
    full_adf_avio_completion saved = s.jobs[2].callback;
    assert(!full_adf_avio_output_consume_vsync(&s, 1, 1));
    put32(expected.shadow + 0x10, (get32(expected.shadow + 0x10) | 0x08000000u) & ~0x04000000u);
    put32(expected.shadow + 0x18, get32(expected.shadow + 0x18) | 0x44000000u);
    put32(expected.changed, get32(expected.changed) | (fields_already_set ? 0 : 0x08080000u));
    put32(expected.touched, get32(expected.touched) | 0x08080000u);
    snapshot_equal(&expected, &s.snapshot);
    assert(s.consumed == 1 && s.count == 2 && s.stage_counts[0] == 1);
    assert(s.shadow_writes == 4 && s.touched_writes == 4 && !s.output_finished);
    assert(s.changed_writes == (fields_already_set ? 0u : 4u));
    assert(listener_calls == callbacks_before);
    unsigned int changes = s.changed_writes, writes = s.shadow_writes;
    assert(!full_adf_avio_output_consume_vsync(&s, 1, 2));
    snapshot_equal(&expected, &s.snapshot);
    assert(s.consumed == 2 && s.count == 1 && s.last_event == 2 && s.vsync_events == 2);
    assert(s.stage_counts[1] == 1 && s.changed_writes == changes && s.shadow_writes == writes);
    assert(!s.output_finished && !s.callback_calls && listener_calls == callbacks_before);
    assert(!full_adf_avio_output_consume_vsync(&s, 1, 3));
    put32(expected.shadow, (get32(expected.shadow) & ~0x07070000u) | 0x01060000u);
    put32(expected.changed, get32(expected.changed) | (fields_already_set ? 0 : 0xcu));
    put32(expected.touched, get32(expected.touched) | 0xcu);
    snapshot_equal(&expected, &s.snapshot);
    assert(s.output_finished == 1 && !s.fault && !s.count && s.consumed == 3);
    assert(s.callback_calls == 1 && listener_calls == callbacks_before + 1);
    assert(!s.callback_running && !s.pending_events && !s.listener && !s.context);
    assert(s.changed_writes == (fields_already_set ? 0u : 7u));
    for (unsigned int i = 0; i < FULL_ADF_AVIO_JOBS; i++) {
        const struct full_adf_avio_job zero = {0};
        assert(!memcmp(&s.jobs[i], &zero, sizeof zero));
    }
    reject_event(&s, 1, 3);
    reject_event(&s, 1, 4);
    reject_enqueue(&s, 1, 8, listener);
    saved(&s, 0);
    assert(s.callback_calls == 1 && listener_calls == callbacks_before + 1);
}
static void check_cold_rejections(void)
{
    struct full_adf_avio_output s;
    memset(&s, 0, sizeof s);
    reject_enqueue(&s, 1, 8, listener);
    for (unsigned int kind = 0; kind < 36; kind++) {
        cold(&s);
        switch (kind) {
        case 0: s.known = 0; break;
        case 1: s.known = 2; break;
        case 2: s.fault = 1; break;
        case 3: s.sync_flag = 1; break;
        case 4: s.public_source = 0; break;
        case 5: s.public_source = UINT_MAX; break;
        case 6: s.source_cache = 0; break;
        case 7: s.source_cache = 1; break;
        case 8: s.current_mask = 8; break;
        case 9: s.requested_mask = 8; break;
        case 10: s.read_index = 60; break;
        case 11: s.write_index = 60; break;
        case 12: s.count = 60; break;
        case 13: s.pending_events = 1; break;
        case 14: s.queued = 1; break;
        case 15: s.consumed = 1; break;
        case 16: s.vsync_events = 1; break;
        case 17: s.shadow_writes = 1; break;
        case 18: s.changed_writes = 1; break;
        case 19: s.touched_writes = 1; break;
        case 20: s.callback_running = 1; break;
        case 21: s.callback_calls = 1; break;
        case 22: s.output_finished = 1; break;
        case 23: s.generation = 1; break;
        case 24: s.last_event = 1; break;
        case 25: s.listener = listener; break;
        case 26: s.context = &s; break;
        case 27: s.snapshot.shadow[111] ^= 1; break;
        case 28: s.snapshot.changed[23] ^= 1; break;
        case 29: s.snapshot.touched[23] ^= 1; break;
        case 30: s.stage_counts[0] = 1; break;
        case 31: s.stage_counts[2] = 1; break;
        case 32: s.same.enqueued = 1; break;
        case 33: s.same.cache_stores = 1; break;
        case 34: s.same.cache_clears = 1; break;
        case 35: s.same.cache_callback = listener; break;
        }
        reject_enqueue(&s, 1, 8, listener);
    }
    const unsigned long long generations[] = {0, 2, ULLONG_MAX};
    for (unsigned int i = 0; i < 3; i++) { cold(&s); reject_enqueue(&s, generations[i], 8, listener); }
    const unsigned int targets[] = {0, 1, 9, UINT_MAX};
    for (unsigned int i = 0; i < 4; i++) { cold(&s); reject_enqueue(&s, 1, targets[i], listener); }
    cold(&s); reject_enqueue(&s, 1, 8, 0);
    cold(&s); reject_event(&s, 1, 1);
    for (unsigned int i = 0; i < FULL_ADF_AVIO_JOBS; i++) {
        cold(&s); s.jobs[i].opaque_lease = i & 1 ? 0x8400 : 0x8401;
        reject_enqueue(&s, 1, 8, listener);
    }
}
static void check_queued_rejections(void)
{
    struct full_adf_avio_output s;
    for (unsigned int step = 0; step < 3; step++) {
        const unsigned long long bad_events[] = {0, 4, ULLONG_MAX};
        for (unsigned int i = 0; i < 3; i++) {
            queued(&s, listener);
            for (unsigned int event = 1; event <= step; event++)
                assert(!full_adf_avio_output_consume_vsync(&s, 1, event));
            reject_event(&s, 1, bad_events[i]);
        }
        queued(&s, listener);
        for (unsigned int event = 1; event <= step; event++)
            assert(!full_adf_avio_output_consume_vsync(&s, 1, event));
        reject_event(&s, 1, step ? step : 2);
    }
    for (unsigned int kind = 0; kind < 29; kind++) {
        queued(&s, listener);
        switch (kind) {
        case 0: s.known = 0; break;
        case 1: s.sync_flag = 1; break;
        case 2: s.public_source = 2; break;
        case 3: s.source_cache = 1; break;
        case 4: s.current_mask = 8; break;
        case 5: s.requested_mask = 0; break;
        case 6: s.read_index = UINT_MAX; break;
        case 7: s.write_index = 60; break;
        case 8: s.count = 60; break;
        case 9: s.pending_events = 1; break;
        case 10: s.queued = 4; break;
        case 11: s.consumed = UINT_MAX; break;
        case 12: s.vsync_events = 1; break;
        case 13: s.stage_counts[0] = 1; break;
        case 14: s.shadow_writes = 1; break;
        case 15: s.changed_writes = 1; break;
        case 16: s.touched_writes = 1; break;
        case 17: s.callback_running = 1; break;
        case 18: s.callback_calls = 1; break;
        case 19: s.output_finished = 1; break;
        case 20: s.generation = 2; break;
        case 21: s.last_event = 1; break;
        case 22: s.listener = 0; break;
        case 23: s.snapshot.shadow[111] ^= 1; break;
        case 24: s.snapshot.changed[23] ^= 1; break;
        case 25: s.snapshot.touched[23] ^= 1; break;
        case 26: s.jobs[0].callback = s.jobs[2].callback; break;
        case 27: s.jobs[2].callback = 0; break;
        case 28: s.fault = 1; break;
        }
        reject_event(&s, 1, 1);
    }
    for (unsigned int index = 0; index < 3; index++)
        for (unsigned int kind = 0; kind < 7; kind++) {
            queued(&s, listener);
            switch (kind) {
            case 0: s.jobs[index].active = 0; break;
            case 1: s.jobs[index].type = 1; break;
            case 2: s.jobs[index].stage = 3; break;
            case 3: s.jobs[index].target = 0; break;
            case 4: s.jobs[index].change_mask = 0; break;
            case 5: s.jobs[index].generation = 2; break;
            case 6: s.jobs[index].opaque_lease = 0x8400; break;
            }
            reject_event(&s, 1, 1);
        }
    for (unsigned int index = 0; index < FULL_ADF_AVIO_JOBS; index++) {
        queued(&s, listener);
        s.jobs[index].opaque_lease = 0x8401;
        reject_event(&s, 1, 1);
    }
    queued(&s, listener); reject_enqueue(&s, 1, 8, listener);
    queued(&s, listener); reject_event(&s, 2, 1);
    queued(&s, listener); reject_event(&s, 0, 1);
    queued(&s, listener); reject_event(&s, ULLONG_MAX, 1);
}
static unsigned int attack;
static void adversarial_listener(void *context, unsigned int status)
{
    struct full_adf_avio_output *s = context;
    listener(context, status);
    switch (attack) {
    case 0: assert(full_adf_avio_output_consume_vsync(s, 1, 3) == -1021); break;
    case 1: assert(full_adf_avio_output_enqueue(s, 1, 8, listener, s) == -1021); break;
    case 2: s->jobs[2].callback(s, 0); break;
    case 3: s->generation = 2; break;
    case 4: s->generation = 0; break;
    case 5: s->pending_events = 0; break;
    case 6: s->listener = listener; break;
    case 7: s->jobs[59].opaque_lease = 0x8400; break;
    case 8: s->source_cache = 1; break;
    case 9: s->snapshot.shadow[111] ^= 1; break;
    }
}
static void check_callback_guards(void)
{
    struct full_adf_avio_output s;
    for (unsigned int step = 0; step < 3; step++) {
        queued(&s, listener);
        full_adf_avio_completion saved = s.jobs[2].callback;
        for (unsigned int event = 1; event <= step; event++)
            assert(!full_adf_avio_output_consume_vsync(&s, 1, event));
        unsigned char before[sizeof s];
        unsigned int calls = listener_calls;
        memcpy(before, &s, sizeof before);
        saved(&s, 0);
        rejection_equal(before, &s);
        assert(listener_calls == calls);
    }
    for (attack = 0; attack < 10; attack++) {
        queued(&s, adversarial_listener);
        full_adf_avio_completion saved = s.jobs[2].callback;
        unsigned int calls = listener_calls;
        assert(!full_adf_avio_output_consume_vsync(&s, 1, 1));
        assert(!full_adf_avio_output_consume_vsync(&s, 1, 2));
        assert(full_adf_avio_output_consume_vsync(&s, 1, 3) == -1021);
        assert(s.fault && !s.output_finished && listener_calls == calls + 1);
        assert(s.callback_calls == 1 && s.callback_running == 1);
        assert(s.count == 1 && s.read_index == 2 && s.consumed == 2);
        assert(s.jobs[2].callback == saved && s.jobs[2].active == 1 && s.jobs[2].generation == 1);
        assert(s.listener == (attack == 6 ? listener : adversarial_listener) && s.context == &s);
        if (attack == 7) assert(s.jobs[59].opaque_lease == 0x8400);
        saved(&s, 0);
        assert(listener_calls == calls + 1);
    }
    puts("ADF_AVIO_CALLBACK_EARLY_DUPLICATE_REENTRY_CROSS_GENERATION_PASS");
}
static struct full_adf_avio_snapshot same_before;
static void check_control3(const struct full_adf_avio_output *s)
{
    unsigned char before[sizeof *s];
    unsigned int mask = UINT_MAX, calls = listener_calls + same_calls;
    full_adf_avio_listener callback = listener;
    memcpy(before, s, sizeof before);
    assert(!full_adf_avio_output_control3(s, &mask, &callback));
    assert(mask == 8 && !callback);
    assert(!memcmp(before, s, sizeof before) && listener_calls + same_calls == calls);
}
static void reject_control3(const struct full_adf_avio_output *s)
{
    unsigned char before[sizeof *s];
    unsigned int mask = UINT_MAX;
    full_adf_avio_listener callback = listener;
    memcpy(before, s, sizeof before);
    assert(full_adf_avio_output_control3(s, &mask, &callback) == -1021);
    assert(mask == UINT_MAX && callback == listener && !memcmp(before, s, sizeof before));
}
static void same_listener(void *context, unsigned int status)
{
    struct full_adf_avio_output *s = context;
    assert(!status && s && !s->fault && !s->output_finished);
    assert(s->generation == 2 && s->read_index == 4 && s->write_index == 4 && !s->count);
    assert(s->consumed == 4 && s->queued == 4 && s->last_event == 9 && s->vsync_events == 4);
    assert(s->callback_running == 1 && s->pending_events == 1 && s->callback_calls == 2);
    assert(!s->jobs[3].active && s->jobs[3].callback && !s->jobs[3].opaque_lease);
    assert(s->same.cache_stores == 1 && s->same.cache_clears == 1);
    assert(s->current_mask == 8 && s->requested_mask == 8 && s->source_cache == 0xff);
    assert(s->public_source == 1 && s->shadow_writes == 7 && s->touched_writes == 7);
    for (unsigned int i = 0; i < 3; i++) assert(s->stage_counts[i] == 1);
    snapshot_equal(&same_before, &s->snapshot);
    check_control3(s);
    same_calls++;
}
static void completed(struct full_adf_avio_output *s)
{
    queued(s, listener);
    for (unsigned int event = 1; event <= 3; event++)
        assert(!full_adf_avio_output_consume_vsync(s, 1, event));
    assert(s->read_index == 3 && s->write_index == 3 && !s->count);
    check_control3(s);
    same_before = s->snapshot;
}
static void same_queued(struct full_adf_avio_output *s, full_adf_avio_listener callback)
{
    completed(s);
    assert(!full_adf_avio_output_enqueue_same(s, 2, 8, 0, 0, callback, s));
}
static void reject_same(struct full_adf_avio_output *s, unsigned long long generation,
                         unsigned int target, unsigned int power20, unsigned int power22,
                         full_adf_avio_listener callback)
{
    unsigned char before[sizeof *s];
    unsigned int calls = listener_calls + same_calls;
    memcpy(before, s, sizeof before);
    assert(full_adf_avio_output_enqueue_same(s, generation, target, power20, power22, callback, s) == -1021);
    rejection_equal(before, s);
    assert(listener_calls + same_calls == calls);
}
static void check_same_success(void)
{
    struct full_adf_avio_output s;
    const struct { unsigned int power20, power22; } power = {0, 0};
    completed(&s);
    struct full_adf_avio_snapshot initial = s.initial;
    unsigned int writes = s.shadow_writes, changes = s.changed_writes, calls = same_calls;
    assert(!full_adf_avio_output_enqueue_same(&s, 2, 8, power.power20, power.power22, same_listener, &s));
    assert(!power.power20 && !power.power22);
    assert(s.read_index == 3 && s.write_index == 4 && s.count == 1 && s.queued == 4 && s.consumed == 3);
    assert(!s.output_finished && !s.pending_events && !s.callback_running && same_calls == calls);
    assert(s.last_event == 3 && s.vsync_events == 3 && s.callback_calls == 1);
    check_control3(&s);
    const struct full_adf_avio_job job = s.jobs[3];
    assert(job.active == 1 && !job.type && !job.stage && job.target == 8 && !job.change_mask);
    assert(job.generation == 2 && !job.opaque_lease && job.callback && job.original_callback == 0x00666f61u);
    const unsigned char original[] = {0, 0, 8, 0, 0, 0, 0, 0, 0x61, 0x6f, 0x66, 0};
    unsigned char descriptor[12] = {0};
    descriptor[0] = (unsigned char)job.type; descriptor[1] = (unsigned char)job.stage;
    descriptor[2] = (unsigned char)job.target; descriptor[3] = (unsigned char)job.change_mask;
    put32(descriptor + 8, job.original_callback);
    assert(!memcmp(descriptor, original, sizeof original));
    snapshot_equal(&same_before, &s.snapshot);
    assert(!full_adf_avio_output_consume_vsync(&s, 2, 9));
    assert(s.output_finished == 1 && !s.fault && s.read_index == 4 && s.write_index == 4 && !s.count);
    assert(s.consumed == 4 && s.queued == 4 && s.callback_calls == 2 && same_calls == calls + 1);
    assert(!s.callback_running && !s.pending_events && !s.listener && !s.context);
    assert(s.shadow_writes == writes && s.changed_writes == changes && s.touched_writes == writes);
    assert(!memcmp(&initial, &s.initial, sizeof initial));
    snapshot_equal(&same_before, &s.snapshot);
    struct full_adf_avio_job stale = job;
    stale.active = 0;
    assert(!memcmp(&stale, &s.jobs[3], sizeof stale));
    check_control3(&s);
    unsigned char before[sizeof s];
    memcpy(before, &s, sizeof before);
    stale.callback(&s, 0);
    rejection_equal(before, &s);
    assert(same_calls == calls + 1 && !s.jobs[3].active && s.jobs[3].original_callback == 0x00666f61u);
    reject_event(&s, 2, 9);
    reject_same(&s, 2, 8, 0, 0, same_listener);
    puts("ADF_AVIO_SAME_OWNER_CONTROL3_POP_BEFORE_CALLBACK_NOOP_STALE_DESCRIPTOR_PASS");
}
static void check_same_rejections(void)
{
    struct full_adf_avio_output s;
    unsigned int mask = UINT_MAX;
    full_adf_avio_listener callback = listener;
    assert(full_adf_avio_output_control3(0, &mask, &callback) == -1021);
    assert(mask == UINT_MAX && callback == listener);
    assert(full_adf_avio_output_enqueue_same(0, 2, 8, 0, 0, same_listener, 0) == -1021);
    cold(&s); reject_control3(&s); reject_same(&s, 2, 8, 0, 0, same_listener);
    for (unsigned int step = 0; step < 3; step++) {
        queued(&s, listener);
        for (unsigned int event = 1; event <= step; event++)
            assert(!full_adf_avio_output_consume_vsync(&s, 1, event));
        reject_control3(&s);
        reject_same(&s, 2, 8, 0, 0, same_listener);
    }
    completed(&s);
    unsigned char before[sizeof s];
    memcpy(before, &s, sizeof before);
    assert(full_adf_avio_output_control3(&s, 0, &callback) == -1021);
    assert(full_adf_avio_output_control3(&s, &mask, 0) == -1021);
    assert(mask == UINT_MAX && callback == listener && !memcmp(before, &s, sizeof before));
    const unsigned long long generations[] = {0, 1, 3, ULLONG_MAX};
    for (unsigned int i = 0; i < 4; i++) {
        completed(&s); reject_same(&s, generations[i], 8, 0, 0, same_listener);
    }
    const unsigned int targets[] = {0, 1, 9, UINT_MAX};
    for (unsigned int i = 0; i < 4; i++) {
        completed(&s); reject_same(&s, 2, targets[i], 0, 0, same_listener);
    }
    completed(&s); reject_same(&s, 2, 8, 1, 0, same_listener);
    completed(&s); reject_same(&s, 2, 8, 0, 1, same_listener);
    completed(&s); reject_same(&s, 2, 8, UINT_MAX, UINT_MAX, same_listener);
    completed(&s); reject_same(&s, 2, 8, 0, 0, 0);
    for (unsigned int index = 0; index < FULL_ADF_AVIO_JOBS; index++) {
        completed(&s); s.jobs[index].opaque_lease = 0x8401;
        reject_control3(&s); reject_same(&s, 2, 8, 0, 0, same_listener);
    }
    for (unsigned int kind = 0; kind < 10; kind++) {
        completed(&s);
        switch (kind) {
        case 0: s.current_mask = 0; break;
        case 1: s.sync_flag = 1; break;
        case 2: s.generation = 2; break;
        case 3: s.count = 55; break;
        case 4: s.pending_events = 1; break;
        case 5: s.listener = same_listener; break;
        case 6: s.same.cache_callback = same_listener; break;
        case 7: s.same.enqueued = 1; break;
        case 8: s.same.cache_stores = 1; break;
        case 9: s.same.cache_clears = 1; break;
        }
        reject_control3(&s); reject_same(&s, 2, 8, 0, 0, same_listener);
    }
    const unsigned long long events[] = {0, 3, 4, 8, 10, ULLONG_MAX};
    for (unsigned int i = 0; i < 6; i++) {
        same_queued(&s, same_listener); reject_event(&s, 2, events[i]);
    }
    for (unsigned int i = 0; i < 4; i++) {
        same_queued(&s, same_listener); reject_event(&s, generations[i], 9);
    }
    for (unsigned int index = 0; index < FULL_ADF_AVIO_JOBS; index++) {
        same_queued(&s, same_listener); s.jobs[index].opaque_lease = 0x8400;
        reject_control3(&s); reject_event(&s, 2, 9);
    }
    for (unsigned int kind = 0; kind < 27; kind++) {
        same_queued(&s, same_listener);
        switch (kind) {
        case 0: s.known = 0; break;
        case 1: s.current_mask = 0; break;
        case 2: s.requested_mask = 0; break;
        case 3: s.sync_flag = 1; break;
        case 4: s.generation = 1; break;
        case 5: s.source_cache = 1; break;
        case 6: s.public_source = 0; break;
        case 7: s.same.cache_callback = same_listener; break;
        case 8: s.same.cache_clears = 0; break;
        case 9: s.same.cache_stores = 2; break;
        case 10: s.jobs[3].active = 0; break;
        case 11: s.jobs[3].type = 1; break;
        case 12: s.jobs[3].stage = 2; break;
        case 13: s.jobs[3].target = 0; break;
        case 14: s.jobs[3].change_mask = 8; break;
        case 15: s.jobs[3].generation = 1; break;
        case 16: s.jobs[3].original_callback ^= 1; break;
        case 17: s.jobs[3].callback = 0; break;
        case 18: s.snapshot.shadow[111] ^= 1; break;
        case 19: s.snapshot.changed[23] ^= 1; break;
        case 20: s.snapshot.touched[23] ^= 1; break;
        case 21: s.shadow_writes++; break;
        case 22: s.changed_writes++; break;
        case 23: s.touched_writes++; break;
        case 24: s.last_event = 8; break;
        case 25: s.stage_counts[0]++; break;
        case 26: s.count = 55; break;
        }
        reject_control3(&s); reject_event(&s, 2, 9);
    }
    same_queued(&s, same_listener); reject_same(&s, 2, 8, 0, 0, same_listener);
    same_queued(&s, same_listener);
    assert(!full_adf_avio_output_consume_vsync(&s, 2, 9));
    reject_event(&s, 2, 9);
    reject_control3(&s);
    same_queued(&s, same_listener);
    assert(!full_adf_avio_output_consume_vsync(&s, 2, 9));
    reject_same(&s, 2, 8, 0, 0, same_listener);
    puts("ADF_AVIO_SAME_MASK_POWER_SLOT_EVENT_METADATA_REJECTIONS_PRESERVED_PASS");
}
static void adversarial_same_listener(void *context, unsigned int status)
{
    struct full_adf_avio_output *s = context;
    same_listener(context, status);
    switch (attack) {
    case 0: assert(full_adf_avio_output_consume_vsync(s, 2, 9) == -1021); break;
    case 1: assert(full_adf_avio_output_enqueue_same(s, 2, 8, 0, 0, same_listener, s) == -1021); break;
    case 2: s->jobs[3].callback(s, 0); break;
    case 3: s->generation = 1; break;
    case 4: s->generation = 0; break;
    case 5: s->pending_events = 0; break;
    case 6: s->listener = same_listener; break;
    case 7: s->context = 0; break;
    case 8: s->jobs[59].opaque_lease = 0x8400; break;
    case 9: s->source_cache = 1; break;
    case 10: s->snapshot.shadow[111] ^= 1; break;
    case 11: s->jobs[3].original_callback ^= 1; break;
    case 12: s->same.cache_callback = same_listener; break;
    case 13: s->jobs[3].active = 1; break;
    case 14: s->initial.shadow[111] ^= 1; s->snapshot.shadow[111] ^= 1; break;
    }
}
static void check_same_callback_guards(void)
{
    struct full_adf_avio_output s;
    for (unsigned int status = 0; status < 2; status++) {
        same_queued(&s, same_listener);
        unsigned char before[sizeof s];
        memcpy(before, &s, sizeof before);
        s.jobs[3].callback(&s, status);
        rejection_equal(before, &s);
    }
    for (attack = 0; attack < 15; attack++) {
        same_queued(&s, adversarial_same_listener);
        full_adf_avio_completion saved = s.jobs[3].callback;
        unsigned int calls = same_calls;
        assert(full_adf_avio_output_consume_vsync(&s, 2, 9) == -1021);
        assert(s.fault && !s.output_finished && same_calls == calls + 1);
        assert(!s.count && s.read_index == 4 && s.write_index == 4 && s.consumed == 4);
        assert(s.callback_calls == 2 && s.callback_running == 1);
        assert(s.jobs[3].callback == saved && s.jobs[3].generation == 2);
        assert(s.jobs[3].active == (attack == 13));
        assert(s.listener == (attack == 6 ? same_listener : adversarial_same_listener));
        assert(s.context == (attack == 7 ? 0 : &s));
        if (attack == 8) assert(s.jobs[59].opaque_lease == 0x8400);
        saved(&s, 0);
        assert(same_calls == calls + 1);
    }
    puts("ADF_AVIO_SAME_POPPED_CALLBACK_REENTRY_TAMPER_FAILURE_EVIDENCE_PASS");
}
int main(void)
{
    for (unsigned int i = 0; i < sizeof seed.shadow; i++) seed.shadow[i] = (unsigned char)(i * 7u + 3u);
    for (unsigned int i = 0; i < sizeof seed.changed; i++) {
        seed.changed[i] = (unsigned char)(i * 11u + 5u);
        seed.touched[i] = (unsigned char)(i * 17u + 9u);
    }
    /* Force every target field to differ while retaining unrelated nonzero bits. */
    put32(seed.shadow + 0x10, (get32(seed.shadow + 0x10) | 0x04000000u) & ~0x08000000u);
    put32(seed.shadow + 0x18, get32(seed.shadow + 0x18) & ~0x44000000u);
    put32(seed.shadow, (get32(seed.shadow) & ~0x07070000u) | 0x02010000u);
    for (unsigned int i = 0; i < sizeof speech; i++) speech[i] = (unsigned char)(i * 19u + 0x84u);
    memcpy(speech_before, speech, sizeof speech);
    check_init();
    check_success(0);
    check_success(1);
    puts("ADF_AVIO_THREE_DISTINCT_EVENTS_RMW_CHANGED_TOUCHED_PRESERVATION_PASS");
    check_cold_rejections();
    check_queued_rejections();
    check_callback_guards();
    check_same_success();
    check_same_rejections();
    check_same_callback_guards();
    assert(!memcmp(speech, speech_before, sizeof speech));
    printf("ADF_AVIO_OUTPUT_PASS rejected_preserved=%u output_only=1 idle_complete=0 capture_verified=0\n", rejected);
    return 0;
}
