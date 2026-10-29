/* SPDX-License-Identifier: MIT */
#include "adf-source7-clock.h"
#include <stddef.h>

static int zeroed(const void *storage, size_t bytes)
{
    const unsigned char *p = storage;
    size_t i;
    if (!p) return 0;
    for (i = 0; i < bytes; ++i) if (p[i]) return 0;
    return 1;
}

static int clock_fault(struct full_adf_source7_clock *clock)
{
    if (clock) clock->fault = 1;
    return FULL_ADF_SOURCE7_ERROR;
}

static int delay_fault(struct full_adf_delay129 *delay)
{
    if (delay) delay->fault = 1;
    return FULL_ADF_SOURCE7_ERROR;
}

static int snapshot_equal(const struct full_adf_source7_snapshot *a,
                          const struct full_adf_source7_snapshot *b)
{
    return a->counter == b->counter && a->phase == b->phase && a->epoch == b->epoch;
}

static int clock_ready(const struct full_adf_source7_clock *clock, uint64_t generation)
{
    uint32_t expected;
    unsigned int first, last;
    if (!clock || clock->known != 1 || clock->fault || clock->busy ||
        (generation != 1 && generation != 2 && generation != 3) || clock->generation != generation ||
        clock->bound != 1 || clock->cache_valid != 1 ||
        clock->reset_counter > FULL_ADF_SOURCE7_COUNTER_MASK ||
        clock->started > 1 || clock->armed > 1) return 0;
    first = (unsigned int)(generation - 1) * FULL_ADF_SOURCE7_MAX_EVENTS;
    last = first + (generation == 3 ? 1u : FULL_ADF_SOURCE7_MAX_EVENTS);
    if (clock->events_delivered < first || clock->events_delivered > last ||
        (generation != 1 && !clock->started)) return 0;
    if (!clock->started && (clock->armed || clock->events_delivered || clock->deadline_ns))
        return 0;
    if (clock->started && (clock->deadline_ns < FULL_ADF_SOURCE7_PERIOD_NS ||
        clock->armed != (clock->events_delivered < last))) return 0;
    expected = (clock->reset_counter + clock->events_delivered) & FULL_ADF_SOURCE7_COUNTER_MASK;
    return clock->hardware7.counter == expected &&
           clock->hardware7.phase == clock->reset_phase &&
           clock->hardware7.epoch == clock->events_delivered &&
           snapshot_equal(&clock->hardware7, &clock->published_fb) &&
           snapshot_equal(&clock->published_fb, &clock->cache5);
}

int full_adf_source7_clock_init(struct full_adf_source7_clock *clock,
                               uint32_t reset_counter, unsigned int reset_phase)
{
    if (!zeroed(clock, sizeof(*clock)) || reset_counter > FULL_ADF_SOURCE7_COUNTER_MASK ||
        reset_phase > UINT16_MAX) return FULL_ADF_SOURCE7_ERROR;
    clock->known = 1;
    clock->reset_counter = clock->hardware7.counter = reset_counter;
    clock->reset_phase = clock->hardware7.phase = (uint16_t)reset_phase;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_source7_clock_bind(struct full_adf_source7_clock *clock, uint64_t generation,
                               unsigned int software_source, unsigned int hardware_source)
{
    const struct full_adf_source7_snapshot empty = {0};
    struct full_adf_source7_snapshot snapshot;
    if (!clock || clock->known != 1 || clock->fault || clock->busy || generation != 1 ||
        software_source != FULL_ADF_SOURCE7_SOFTWARE ||
        hardware_source != FULL_ADF_SOURCE7_HARDWARE || clock->bound || clock->cache_valid ||
        clock->generation || clock->started || clock->armed || clock->events_delivered ||
        clock->deadline_ns || clock->reset_counter > FULL_ADF_SOURCE7_COUNTER_MASK ||
        clock->hardware7.counter != clock->reset_counter ||
        clock->hardware7.phase != clock->reset_phase || clock->hardware7.epoch ||
        !snapshot_equal(&clock->published_fb, &empty) ||
        !snapshot_equal(&clock->cache5, &empty)) return clock_fault(clock);
    clock->busy = 1;
    snapshot = clock->hardware7;
    clock->published_fb = snapshot;
    clock->cache5 = clock->published_fb;
    clock->generation = generation;
    clock->bound = clock->cache_valid = 1;
    clock->busy = 0;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_source7_clock_get(const struct full_adf_source7_clock *clock,
                              uint64_t generation, unsigned int software_source,
                              struct full_adf_source7_snapshot *snapshot)
{
    if (!snapshot || software_source != FULL_ADF_SOURCE7_SOFTWARE ||
        !clock_ready(clock, generation)) return FULL_ADF_SOURCE7_ERROR;
    *snapshot = clock->cache5;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_source7_clock_arm(struct full_adf_source7_clock *clock, uint64_t generation,
                              uint64_t now_ns)
{
    if (generation != 1 || !clock_ready(clock, generation) || clock->started || clock->armed ||
        clock->events_delivered || now_ns > UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS)
        return clock_fault(clock);
    clock->busy = 1;
    clock->started = clock->armed = 1;
    clock->deadline_ns = now_ns + FULL_ADF_SOURCE7_PERIOD_NS;
    clock->busy = 0;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_source7_clock_continue(struct full_adf_source7_clock *clock, uint64_t now_ns)
{
    if (!clock_ready(clock, 1) || clock->started != 1 || clock->armed ||
        clock->events_delivered != FULL_ADF_SOURCE7_MAX_EVENTS ||
        now_ns < clock->deadline_ns - FULL_ADF_SOURCE7_PERIOD_NS ||
        now_ns > UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS) return clock_fault(clock);
    clock->busy = 1;
    clock->generation = 2;
    clock->armed = 1;
    clock->deadline_ns = now_ns + FULL_ADF_SOURCE7_PERIOD_NS;
    clock->busy = 0;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_source7_clock_continue_output(struct full_adf_source7_clock *clock, uint64_t now_ns)
{
    if (!clock_ready(clock, 2) || clock->started != 1 || clock->armed ||
        clock->events_delivered != 2u * FULL_ADF_SOURCE7_MAX_EVENTS ||
        now_ns < clock->deadline_ns - FULL_ADF_SOURCE7_PERIOD_NS ||
        now_ns > UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS) return clock_fault(clock);
    clock->busy = 1;
    clock->generation = 3;
    clock->armed = 1;
    clock->deadline_ns = now_ns + FULL_ADF_SOURCE7_PERIOD_NS;
    clock->busy = 0;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_source7_clock_expire(struct full_adf_source7_clock *clock, uint64_t generation,
                                 uint64_t now_ns, struct full_adf_source7_event *event_out)
{
    struct full_adf_source7_event event = {0};
    struct full_adf_source7_snapshot snapshot;
    unsigned int last = generation == 3 ? 9u : (unsigned int)generation * FULL_ADF_SOURCE7_MAX_EVENTS;
    if (!event_out || !clock_ready(clock, generation) || !clock->armed ||
        clock->events_delivered >= last) return clock_fault(clock);
    if (now_ns < clock->deadline_ns) return FULL_ADF_SOURCE7_PENDING;
    if (now_ns > UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS) return clock_fault(clock);
    clock->busy = 1;
    event.deadline_ns = clock->deadline_ns;
    ++clock->events_delivered;
    clock->hardware7.counter = (clock->hardware7.counter + 1) & FULL_ADF_SOURCE7_COUNTER_MASK;
    clock->hardware7.epoch = clock->events_delivered;
    snapshot = clock->hardware7;
    clock->published_fb = snapshot;
    clock->cache5 = clock->published_fb;
    clock->deadline_ns = now_ns + FULL_ADF_SOURCE7_PERIOD_NS;
    if (clock->events_delivered == last) clock->armed = 0;
    event.generation = generation;
    event.sequence = clock->events_delivered;
    event.observed_ns = now_ns;
    event.hardware_source = FULL_ADF_SOURCE7_HARDWARE;
    event.software_source = FULL_ADF_SOURCE7_SOFTWARE;
    event.hardware = snapshot;
    event.fb = clock->published_fb;
    event.cache = clock->cache5;
    clock->busy = 0;
    *event_out = event;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_source7_clock_cancel(struct full_adf_source7_clock *clock, uint64_t generation)
{
    if (!clock || clock->known != 1 || clock->busy ||
        (generation != 1 && generation != 2 && generation != 3) ||
        clock->generation != generation || clock->bound != 1 || clock->armed != 1)
        return clock_fault(clock);
    clock->fault = 1;
    clock->armed = 0;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_delay129_init(struct full_adf_delay129 *delay)
{
    if (!zeroed(delay, sizeof(*delay))) return FULL_ADF_SOURCE7_ERROR;
    delay->known = 1;
    delay->software_source = FULL_ADF_SOURCE7_SOFTWARE;
    delay->hardware_source = FULL_ADF_SOURCE7_HARDWARE;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_delay129_register(struct full_adf_delay129 *delay, uint64_t generation,
                              const struct full_adf_source7_clock *clock)
{
    struct full_adf_source7_snapshot snapshot;
    if (!delay || delay->known != 1 || delay->fault || delay->busy || generation != 1 ||
        delay->mode || delay->processing_state > 2 || delay->owner18 || delay->callback_pending ||
        delay->software_source != FULL_ADF_SOURCE7_SOFTWARE ||
        delay->hardware_source != FULL_ADF_SOURCE7_HARDWARE || delay->control_state ||
        delay->registered || delay->priority || delay->pending_work || delay->pending ||
        delay->generation || delay->clock || delay->registered_epoch ||
        delay->saved74 || delay->delay78 || delay->start7c ||
        full_adf_source7_clock_get(clock, generation, delay->software_source, &snapshot) ||
        clock->events_delivered >= FULL_ADF_SOURCE7_MAX_EVENTS) return delay_fault(delay);
    delay->busy = 1;
    delay->clock = clock;
    delay->generation = generation;
    delay->registered_epoch = snapshot.epoch;
    delay->saved74 = delay->start7c = snapshot.counter;
    delay->control_state = delay->registered = delay->pending_work = delay->pending = 1;
    delay->priority = 2;
    delay->busy = 0;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_delay129_poll(struct full_adf_delay129 *delay, uint64_t generation,
                          const struct full_adf_source7_clock *clock)
{
    struct full_adf_source7_snapshot snapshot;
    uint32_t delta;
    if (!delay || delay->known != 1 || delay->fault || delay->busy || generation != 1 ||
        delay->generation != generation || !clock || delay->clock != clock ||
        delay->software_source != FULL_ADF_SOURCE7_SOFTWARE ||
        delay->hardware_source != FULL_ADF_SOURCE7_HARDWARE || delay->control_state != 1 ||
        delay->registered != 1 || delay->priority != 2 || delay->pending_work != 1 ||
        delay->pending != 1 || delay->delay78 || delay->saved74 != delay->start7c ||
        full_adf_source7_clock_get(clock, generation, delay->software_source, &snapshot) ||
        delay->registered_epoch > snapshot.epoch ||
        delay->saved74 != ((clock->reset_counter + delay->registered_epoch) &
                           FULL_ADF_SOURCE7_COUNTER_MASK)) return delay_fault(delay);
    if (snapshot.counter == delay->saved74) return FULL_ADF_SOURCE7_PENDING;
    if (snapshot.epoch <= delay->registered_epoch || delay->mode ||
        delay->processing_state > 2 || delay->owner18 || delay->callback_pending)
        return delay_fault(delay);
    delta = (snapshot.counter - delay->start7c) & FULL_ADF_SOURCE7_COUNTER_MASK;
    if (delta < delay->delay78) return FULL_ADF_SOURCE7_PENDING;
    delay->busy = 1;
    delay->control_state = 2;
    delay->registered = delay->priority = delay->pending_work = delay->pending = 0;
    delay->saved74 = delay->delay78 = delay->start7c = 0;
    delay->busy = 0;
    return FULL_ADF_SOURCE7_OK;
}

int full_adf_delay129_cancel(struct full_adf_delay129 *delay, uint64_t generation)
{
    if (!delay || delay->known != 1 || delay->busy || generation != 1 ||
        delay->generation != generation || delay->control_state != 1 ||
        delay->registered != 1 || delay->pending_work != 1 || delay->pending != 1)
        return delay_fault(delay);
    delay->fault = 1;
    delay->registered = delay->priority = delay->pending_work = delay->pending = 0;
    return FULL_ADF_SOURCE7_OK;
}
