/* SPDX-License-Identifier: MIT
 * Virtual Glee control2 -> 218584 type0 -> 21d884, first bit3-on transaction.
 * Shadow/bitmap leaves and the generation2 same-mask NoOp; no PCM, MMIO,
 * original CP execution, frame clock or Idle reply. */
#include "adf-avio-output.h"
#include <string.h>

static void terminal(struct full_adf_avio_output *, unsigned int);
static void terminal_same(struct full_adf_avio_output *, unsigned int);
static int reject(struct full_adf_avio_output *s)
{
    if (s && (s->generation || s->queued)) s->fault = 1;
    return -1021;
}
static unsigned int get32(const unsigned char *p)
{
    return p[0] | (unsigned int)p[1] << 8 | (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24;
}
static void put32(unsigned char *p, unsigned int value)
{
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (8 * i));
}
static unsigned int field(struct full_adf_avio_snapshot *snapshot, unsigned int offset,
                           unsigned int mask, unsigned int value, unsigned int bitmap)
{
    unsigned int old = get32(snapshot->shadow + offset);
    unsigned int next = (old & ~mask) | (value & mask);
    put32(snapshot->shadow + offset, next);
    if (old != next) put32(snapshot->changed, get32(snapshot->changed) | bitmap);
    put32(snapshot->touched, get32(snapshot->touched) | bitmap);
    return old != next;
}
static unsigned int stage_work(struct full_adf_avio_snapshot *snapshot, unsigned int stage,
                                unsigned int source)
{
    unsigned int changed = 0;
    if (stage == 0) {
        changed += field(snapshot, 0x10, 1u << 27, 1u << 27, 0x00080000u);
        changed += field(snapshot, 0x10, 1u << 26, 0, 0x00080000u);
        changed += field(snapshot, 0x18, 1u << 30, 1u << 30, 0x08000000u);
        changed += field(snapshot, 0x18, 1u << 26, 1u << 26, 0x08000000u);
    } else if (stage == 2) {
        changed += field(snapshot, 0, 1u << 18, 1u << 18, 4);
        changed += field(snapshot, 0, 3u << 16, 2u << 16, 4);
        changed += field(snapshot, 0, 7u << 24, (source & 7u) << 24, 8);
    }
    return changed;
}
static int job_empty(const struct full_adf_avio_job *job)
{
    return !job->active && !job->type && !job->stage && !job->target && !job->change_mask &&
        !job->generation && !job->opaque_lease && !job->original_callback && !job->callback;
}
static int same_empty(const struct full_adf_avio_output *s)
{
    return !s->same.enqueued && !s->same.cache_stores && !s->same.cache_clears &&
        !s->same.cache_callback;
}
static int cold(const struct full_adf_avio_output *s)
{
    if (!s || s->known != 1 || s->fault || s->sync_flag || s->public_source != 1 ||
        s->source_cache != 0xff || s->generation || s->last_event || s->current_mask ||
        s->requested_mask || s->read_index || s->write_index || s->count || s->pending_events ||
        s->queued || s->consumed || s->vsync_events || s->shadow_writes || s->changed_writes ||
        s->touched_writes || s->callback_running || s->callback_calls || s->output_finished ||
        s->listener || s->context || !same_empty(s) ||
        memcmp(&s->initial, &s->snapshot, sizeof s->initial)) return 0;
    for (unsigned int i = 0; i < 3; i++) if (s->stage_counts[i]) return 0;
    for (unsigned int i = 0; i < FULL_ADF_AVIO_JOBS; i++) if (!job_empty(&s->jobs[i])) return 0;
    return 1;
}
int full_adf_avio_output_init(struct full_adf_avio_output *s,
                             const unsigned char shadow[FULL_ADF_AVIO_SHADOW_BYTES],
                             const unsigned char changed[FULL_ADF_AVIO_BITMAP_BYTES],
                             const unsigned char touched[FULL_ADF_AVIO_BITMAP_BYTES],
                             unsigned int public_source)
{
    if (!s || !shadow || !changed || !touched || public_source != 1) return -1021;
    const unsigned char *storage = (const unsigned char *)s;
    for (unsigned long i = 0; i < sizeof *s; i++) if (storage[i]) return -1021;
    struct full_adf_avio_output initial = {0};
    initial.known = 1;
    initial.public_source = public_source;
    initial.source_cache = 0xff;
    memcpy(initial.initial.shadow, shadow, sizeof initial.initial.shadow);
    memcpy(initial.initial.changed, changed, sizeof initial.initial.changed);
    memcpy(initial.initial.touched, touched, sizeof initial.initial.touched);
    initial.snapshot = initial.initial;
    *s = initial;
    return 0;
}
int full_adf_avio_output_enqueue(struct full_adf_avio_output *s, unsigned long long generation,
                                unsigned int target, full_adf_avio_listener listener, void *context)
{
    if (generation != 1 || target != 8 || !listener || !cold(s)) return reject(s);
    s->generation = generation;
    s->listener = listener;
    s->context = context;
    for (unsigned int i = 0; i < 3; i++) {
        s->jobs[i] = (struct full_adf_avio_job){.active = 1, .stage = i, .target = target,
            .change_mask = 8, .generation = generation, .callback = i == 2 ? terminal : 0};
    }
    s->requested_mask = target;
    s->write_index = s->count = s->queued = 3;
    return 0;
}
static int snapshot_valid(const struct full_adf_avio_output *s, unsigned int steps)
{
    struct full_adf_avio_snapshot expected = s->initial;
    unsigned int changes = 0, writes = 0;
    if (steps) { changes += stage_work(&expected, 0, 1); writes += 4; }
    if (steps == 3) { changes += stage_work(&expected, 2, 1); writes += 3; }
    return !memcmp(&expected, &s->snapshot, sizeof expected) && s->shadow_writes == writes &&
        s->changed_writes == changes && s->touched_writes == writes;
}
/* Includes every queue slot and all snapshot bytes, before any destructive dequeue. */
static int valid(const struct full_adf_avio_output *s, unsigned long long generation,
                  unsigned int in_flight, unsigned int callbacks)
{
    if (!s || !same_empty(s) || s->known != 1 || s->fault || generation != 1 || s->generation != generation ||
        s->sync_flag || s->public_source != 1 || s->queued != 3 || s->consumed > 3 ||
        s->consumed + in_flight > 3 || s->read_index != s->consumed || s->write_index != 3 ||
        s->count != 3 - s->consumed || s->requested_mask != 8 || s->pending_events != in_flight ||
        s->callback_calls != callbacks || s->output_finished != (s->consumed == 3)) return 0;
    unsigned int steps = s->consumed + in_flight;
    if (s->last_event != steps || s->vsync_events != steps ||
        s->source_cache != 0xff || s->current_mask != (steps == 3 ? 8u : 0u) ||
        s->callback_running != (in_flight && steps == 3) || (callbacks && steps != 3)) return 0;
    if (s->consumed == 3) {
        if (s->listener || s->context) return 0;
    } else if (!s->listener) return 0;
    for (unsigned int i = 0; i < 3; i++) if (s->stage_counts[i] != (steps > i)) return 0;
    for (unsigned int i = 0; i < FULL_ADF_AVIO_JOBS; i++) {
        const struct full_adf_avio_job *job = &s->jobs[i];
        if (i >= s->consumed && i < 3) {
            if (job->active != 1 || job->type || job->stage != i || job->target != 8 ||
                job->change_mask != 8 || job->generation != generation || job->opaque_lease ||
                job->original_callback || job->callback != (i == 2 ? terminal : 0)) return 0;
        } else if (!job_empty(job)) return 0;
    }
    return snapshot_valid(s, steps);
}
/* Counters are cumulative; stage_counts and all leaves remain generation1 history.
 * Slot3 remains a descriptor after POP, with active0 and no resource lease. */
static int valid_same(const struct full_adf_avio_output *s, unsigned long long generation,
                       unsigned int in_flight, unsigned int callbacks)
{
    if (!s || s->known != 1 || s->fault || generation != 2 || s->generation != generation ||
        s->sync_flag || s->public_source != 1 || s->source_cache != 0xff ||
        s->same.enqueued != 1 || s->same.cache_stores != 1 || s->same.cache_clears != 1 ||
        s->same.cache_callback || s->current_mask != 8 || s->requested_mask != 8 ||
        s->queued != 4 || (s->consumed != 3 && s->consumed != 4) ||
        s->read_index != s->consumed || s->write_index != 4 || s->count != 4 - s->consumed ||
        s->pending_events != in_flight || s->callback_running != in_flight ||
        s->callback_calls != callbacks) return 0;
    if (s->consumed == 3) {
        if (in_flight || callbacks != 1 || s->last_event != 3 || s->vsync_events != 3 ||
            s->output_finished || !s->listener) return 0;
    } else {
        if (s->last_event != 9 || s->vsync_events != 4 || in_flight > 1 ||
            (callbacks != 1 && callbacks != 2)) return 0;
        if (in_flight) {
            if (s->output_finished || !s->listener) return 0;
        } else if (callbacks != 2 || s->output_finished != 1 || s->listener || s->context) return 0;
    }
    for (unsigned int i = 0; i < 3; i++) if (s->stage_counts[i] != 1) return 0;
    for (unsigned int i = 0; i < FULL_ADF_AVIO_JOBS; i++) {
        const struct full_adf_avio_job *job = &s->jobs[i];
        if (i == 3) {
            if (job->active != (s->consumed == 3) || job->type || job->stage || job->target != 8 ||
                job->change_mask || job->generation != 2 || job->opaque_lease ||
                job->original_callback != 0x00666f61u || job->callback != terminal_same) return 0;
        } else if (!job_empty(job)) return 0;
    }
    return snapshot_valid(s, 3);
}
int full_adf_avio_output_control3(const struct full_adf_avio_output *s, unsigned int *mask,
                                  full_adf_avio_listener *cache_callback)
{
    if (!mask || !cache_callback || !s ||
        !((valid(s, 1, 0, 1) && s->consumed == 3) ||
          valid_same(s, 2, s->pending_events, s->callback_calls))) return -1021;
    *mask = s->current_mask;
    *cache_callback = s->same.cache_callback;
    return 0;
}
int full_adf_avio_output_enqueue_same(struct full_adf_avio_output *s, unsigned long long generation,
                                     unsigned int target, unsigned int power20, unsigned int power22,
                                     full_adf_avio_listener listener, void *context)
{
    if (generation != 2 || target != 8 || power20 || power22 || !listener ||
        !valid(s, 1, 0, 1) || s->consumed != 3 || FULL_ADF_AVIO_JOBS - s->count <= 5)
        return reject(s);
    s->generation = generation;
    s->listener = listener;
    s->context = context;
    s->same.enqueued = 1;
    s->same.cache_callback = listener;
    s->same.cache_stores++;
    s->same.cache_callback = 0;
    s->same.cache_clears++;
    s->jobs[s->write_index] = (struct full_adf_avio_job){.active = 1, .target = target,
        .generation = generation, .original_callback = 0x00666f61u, .callback = terminal_same};
    s->write_index++;
    s->count++;
    s->queued++;
    s->output_finished = 0;
    return valid_same(s, generation, 0, 1) ? 0 : reject(s);
}
static void terminal_same(struct full_adf_avio_output *s, unsigned int status)
{
    if (status || !valid_same(s, 2, 1, 1)) { reject(s); return; }
    full_adf_avio_listener listener = s->listener;
    void *context = s->context;
    const struct full_adf_avio_snapshot initial = s->initial;
    s->callback_calls++;
    listener(context, 0);
    if (!valid_same(s, 2, 1, 2) || s->listener != listener || s->context != context ||
        memcmp(&initial, &s->initial, sizeof initial)) reject(s);
}
static int consume_same(struct full_adf_avio_output *s, unsigned long long generation,
                         unsigned long long event_sequence)
{
    if (!valid_same(s, generation, 0, 1) || s->consumed != 3 || event_sequence != 9)
        return reject(s);
    const struct full_adf_avio_job job = s->jobs[s->read_index];
    s->jobs[s->read_index].active = 0;
    s->read_index++;
    s->consumed++;
    s->count--;
    s->pending_events = 1;
    s->last_event = event_sequence;
    s->vsync_events++;
    s->callback_running = 1;
    if (!valid_same(s, generation, 1, 1)) return reject(s);
    job.callback(s, 0);
    if (!valid_same(s, generation, 1, 2)) return reject(s);
    s->pending_events = 0;
    s->callback_running = 0;
    s->listener = 0;
    s->context = 0;
    s->output_finished = 1;
    return valid_same(s, generation, 0, 2) ? 0 : reject(s);
}
static void terminal(struct full_adf_avio_output *s, unsigned int status)
{
    if (status || !valid(s, 1, 1, 0) || s->consumed != 2) { reject(s); return; }
    const unsigned long long generation = s->generation;
    full_adf_avio_listener listener = s->listener;
    void *context = s->context;
    s->callback_calls++;
    listener(context, 0);
    /* Reentry, duplicate delivery or a changed generation retains the live slot and listener. */
    if (!valid(s, generation, 1, 1) || s->listener != listener || s->context != context) reject(s);
}
int full_adf_avio_output_consume_vsync(struct full_adf_avio_output *s,
                                      unsigned long long generation,
                                      unsigned long long event_sequence)
{
    if (generation == 2 || (s && s->same.enqueued)) return consume_same(s, generation, event_sequence);
    if (!valid(s, generation, 0, 0) || s->consumed >= 3 || event_sequence != s->consumed + 1u)
        return reject(s);
    struct full_adf_avio_job job = s->jobs[s->read_index];
    s->pending_events = 1;
    s->last_event = event_sequence;
    s->vsync_events++;
    s->changed_writes += stage_work(&s->snapshot, job.stage, s->public_source);
    s->shadow_writes += job.stage == 0 ? 4 : job.stage == 2 ? 3 : 0;
    s->touched_writes = s->shadow_writes;
    s->stage_counts[job.stage]++;
    if (job.stage == 2) {
        s->current_mask = job.target;
        s->callback_running = 1;
    }
    if (!valid(s, generation, 1, 0)) return reject(s);
    if (job.callback) {
        job.callback(s, 0);
        if (!valid(s, generation, 1, 1)) return reject(s);
    }
    /* Generation and all foreign-slot checks precede clearing the consumed job. */
    memset(&s->jobs[s->read_index], 0, sizeof s->jobs[0]);
    s->read_index++;
    s->consumed++;
    s->count--;
    s->pending_events = 0;
    s->callback_running = 0;
    if (job.callback) {
        s->listener = 0;
        s->context = 0;
        s->output_finished = 1;
    }
    return valid(s, generation, 0, job.callback ? 1 : 0) ? 0 : reject(s);
}
