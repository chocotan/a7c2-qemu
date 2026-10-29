/* SPDX-License-Identifier: MIT */
#include "adf-source7-clock.h"
#include "adf-input-state.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void bound(struct full_adf_source7_clock *clock, uint32_t counter, unsigned int phase)
{
    memset(clock, 0, sizeof(*clock));
    assert(full_adf_source7_clock_init(clock, counter, phase) == 0);
    assert(full_adf_source7_clock_bind(clock, 1, 5, 7) == 0);
}

static void registered(struct full_adf_delay129 *delay, struct full_adf_source7_clock *clock)
{
    memset(delay, 0, sizeof(*delay));
    assert(full_adf_delay129_init(delay) == 0);
    assert(full_adf_delay129_register(delay, 1, clock) == 0);
    assert(delay->control_state == 1 && delay->registered && delay->priority == 2);
    assert(delay->pending_work && delay->pending && !delay->delay78);
}

static void only_clock_fault(const struct full_adf_source7_clock *actual,
                             struct full_adf_source7_clock before)
{
    before.fault = 1;
    assert(memcmp(actual, &before, sizeof(before)) == 0);
}

static void only_delay_fault(const struct full_adf_delay129 *actual,
                             struct full_adf_delay129 before)
{
    before.fault = 1;
    assert(memcmp(actual, &before, sizeof(before)) == 0);
}

static void event_matches(const struct full_adf_source7_event *event, uint64_t sequence,
                          uint32_t counter, unsigned int phase, uint64_t due, uint64_t observed)
{
    assert(event->generation == (sequence - 1) / FULL_ADF_SOURCE7_MAX_EVENTS + 1);
    assert(event->sequence == sequence);
    assert(event->hardware_source == 7 && event->software_source == 5);
    assert(event->deadline_ns == due && event->observed_ns == observed);
    assert(event->hardware.counter == counter && event->hardware.phase == phase);
    assert(event->hardware.epoch == sequence);
    assert(event->fb.counter == counter && event->fb.phase == phase && event->fb.epoch == sequence);
    assert(event->cache.counter == counter && event->cache.phase == phase);
    assert(event->cache.epoch == sequence);
}

static void construction(void)
{
    struct full_adf_source7_clock clock = {0}, before;
    struct full_adf_source7_snapshot snapshot, saved;
    struct full_adf_delay129 delay = {0}, delay_before;
    before = clock;
    assert(full_adf_source7_clock_init(NULL, 0, 0) == -1);
    assert(full_adf_source7_clock_init(&clock, 0x1000000, 0) == -1);
    assert(full_adf_source7_clock_init(&clock, 0, 0x10000) == -1);
    assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    assert(full_adf_source7_clock_init(&clock, 17, 0xffff) == 0);
    assert(clock.known && !clock.bound && !clock.cache_valid && !clock.events_delivered);
    assert(clock.hardware7.counter == 17 && clock.hardware7.phase == 0xffff);
    before = clock;
    memset(&snapshot, 0xa5, sizeof(snapshot));
    saved = snapshot;
    assert(full_adf_source7_clock_get(&clock, 1, 5, &snapshot) == -1);
    assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    assert(memcmp(&snapshot, &saved, sizeof(snapshot)) == 0);
    assert(full_adf_source7_clock_init(&clock, 0, 0) == -1);
    assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    assert(full_adf_source7_clock_bind(&clock, 1, 5, 7) == 0);
    assert(!clock.events_delivered && !clock.hardware7.epoch && !clock.cache5.epoch);
    assert(clock.cache5.counter == 17 && clock.cache5.phase == 0xffff);
    assert(full_adf_delay129_init(&delay) == 0);
    assert(delay.known && !delay.mode && !delay.processing_state);
    assert(delay.software_source == 5 && delay.hardware_source == 7);
    delay_before = delay;
    assert(full_adf_delay129_init(&delay) == -1);
    assert(memcmp(&delay, &delay_before, sizeof(delay)) == 0);
    assert(full_adf_delay129_init(NULL) == -1);
    puts("ADF_SOURCE7_CONSTRUCTION_BIND_EPOCH0_PASS");
}

static void progress(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_snapshot snapshot;
    struct full_adf_source7_event event, saved;
    struct full_adf_delay129 delay, delay_before;
    unsigned int i;
    uint64_t due;
    bound(&clock, 12, 0xa55a);
    registered(&delay, &clock);
    assert(delay.saved74 == 12 && delay.start7c == 12 && delay.registered_epoch == 0);
    delay_before = delay;
    before = clock;
    for (i = 0; i < 10; ++i) {
        assert(full_adf_source7_clock_get(&clock, 1, 5, &snapshot) == 0);
        assert(snapshot.counter == 12 && snapshot.phase == 0xa55a && !snapshot.epoch);
        assert(full_adf_delay129_poll(&delay, 1, &clock) == 1);
    }
    assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    assert(memcmp(&delay, &delay_before, sizeof(delay)) == 0);
    assert(full_adf_source7_clock_arm(&clock, 1, 100) == 0);
    due = 100 + FULL_ADF_SOURCE7_PERIOD_NS;
    assert(clock.deadline_ns == due && clock.armed && !clock.events_delivered);
    before = clock;
    memset(&event, 0xa5, sizeof(event));
    saved = event;
    assert(full_adf_source7_clock_expire(&clock, 1, due - 1, &event) == 1);
    assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    assert(memcmp(&event, &saved, sizeof(event)) == 0);
    assert(full_adf_delay129_poll(&delay, 1, &clock) == 1);
    assert(memcmp(&delay, &delay_before, sizeof(delay)) == 0);
    assert(full_adf_source7_clock_expire(&clock, 1, due, &event) == 0);
    event_matches(&event, 1, 13, 0xa55a, due, due);
    assert(clock.events_delivered == 1 && clock.events_delivered < FULL_ADF_SOURCE7_MAX_EVENTS && clock.armed);
    before = clock;
    assert(full_adf_source7_clock_get(&clock, 1, 5, &snapshot) == 0);
    assert(snapshot.counter == 13 && snapshot.epoch == 1);
    assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    assert(memcmp(&delay, &delay_before, sizeof(delay)) == 0);
    assert(full_adf_delay129_poll(&delay, 1, &clock) == 0);
    assert(delay.control_state == 2 && !delay.registered && !delay.priority);
    assert(!delay.pending_work && !delay.pending && !delay.saved74 && !delay.delay78 && !delay.start7c);
    assert(!delay.fault && memcmp(&clock, &before, sizeof(clock)) == 0);
    delay_before = delay;
    assert(full_adf_delay129_poll(&delay, 1, &clock) == -1);
    only_delay_fault(&delay, delay_before);
    puts("ADF_SOURCE7_READS_WAIT_REAL_EVENT_DELAY129_DRAIN_PASS");
}

static void budget(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_event event, saved;
    struct full_adf_source7_snapshot snapshot;
    uint64_t now = UINT64_C(1234567890123), due;
    unsigned int i;
    bound(&clock, 0, 321);
    assert(FULL_ADF_SOURCE7_MAX_EVENTS == 4);
    assert(!clock.events_delivered && clock.events_delivered < FULL_ADF_SOURCE7_MAX_EVENTS);
    assert(full_adf_source7_clock_arm(&clock, 1, 0) == 0);
    for (i = 1; i <= FULL_ADF_SOURCE7_MAX_EVENTS; ++i) {
        due = clock.deadline_ns;
        assert(full_adf_source7_clock_expire(&clock, 1, now, &event) == 0);
        event_matches(&event, i, i, 321, due, now);
        assert(clock.deadline_ns == now + FULL_ADF_SOURCE7_PERIOD_NS);
        assert(clock.events_delivered == i);
        if (i < FULL_ADF_SOURCE7_MAX_EVENTS) {
            assert(clock.armed && clock.events_delivered < FULL_ADF_SOURCE7_MAX_EVENTS);
            before = clock;
            saved = event;
            assert(full_adf_source7_clock_expire(&clock, 1, now, &event) == 1);
            assert(full_adf_source7_clock_expire(&clock, 1, clock.deadline_ns - 1, &event) == 1);
            assert(memcmp(&clock, &before, sizeof(clock)) == 0);
            assert(memcmp(&event, &saved, sizeof(event)) == 0);
        } else assert(!clock.armed);
        now = clock.deadline_ns + 7;
    }
    assert(full_adf_source7_clock_get(&clock, 1, 5, &snapshot) == 0);
    assert(snapshot.epoch == 4 && snapshot.counter == 4);
    before = clock;
    saved = event;
    assert(full_adf_source7_clock_expire(&clock, 1, now, &event) == -1);
    only_clock_fault(&clock, before);
    assert(memcmp(&event, &saved, sizeof(event)) == 0);
    assert(full_adf_source7_clock_arm(&clock, 1, now) == -1);
    only_clock_fault(&clock, before);
    puts("ADF_SOURCE7_FOUR_DISTINCT_DUE_EVENTS_NO_CATCHUP_PASS");
}

static void input_completed(void *context, unsigned int status)
{
    unsigned int *calls = context;
    assert(status == 0);
    ++*calls;
}

static void fourth_pass(void)
{
    struct full_adf_source7_clock clock, clock_before;
    struct full_adf_source7_event event, saved;
    struct full_adf_source7_snapshot snapshot;
    struct full_adf_delay129 delay, completed_delay;
    struct full_adf_input_state input, input_before;
    unsigned int variant, i, calls, phase;
    uint32_t reset;
    uint64_t due;
    for (variant = 0; variant < 2; ++variant) {
        reset = variant ? 0xffffff : 40;
        phase = variant ? 0xffff : 0xa55a;
        calls = 0;
        memset(&input, 0, sizeof(input));
        assert(full_adf_input_init(&input) == 0);
        input_before = input;
        bound(&clock, reset, phase);
        registered(&delay, &clock);
        assert(full_adf_source7_clock_arm(&clock, 1, 100) == 0);
        for (i = 1; i <= 3; ++i) {
            due = clock.deadline_ns;
            assert(full_adf_source7_clock_expire(&clock, 1, due, &event) == 0);
            event_matches(&event, i, (reset + i) & FULL_ADF_SOURCE7_COUNTER_MASK, phase, due, due);
            if (i == 1) {
                assert(full_adf_delay129_poll(&delay, 1, &clock) == 0);
                completed_delay = delay;
            }
            assert(delay.control_state == 2 && memcmp(&delay, &completed_delay, sizeof(delay)) == 0);
            assert(memcmp(&input, &input_before, sizeof(input)) == 0 && !calls);
        }
        assert(clock.events_delivered == 3 && clock.armed && clock.cache5.epoch == 3);
        /* Parent registers INPUT after output3 commit; no lower-priority rescan. */
        assert(full_adf_input_begin(&input, 1, input_completed, &calls) == 0);
        assert(input.jobs[0].active && input.jobs[0].priority == 2 && !input.complete);
        input_before = input;
        clock_before = clock;
        saved = event;
        assert(full_adf_source7_clock_expire(&clock, 1, event.observed_ns, &event) == 1);
        assert(full_adf_source7_clock_expire(&clock, 1, clock.deadline_ns - 1, &event) == 1);
        assert(full_adf_source7_clock_get(&clock, 1, 5, &snapshot) == 0 && snapshot.epoch == 3);
        assert(memcmp(&clock, &clock_before, sizeof(clock)) == 0);
        assert(memcmp(&event, &saved, sizeof(event)) == 0);
        assert(memcmp(&input, &input_before, sizeof(input)) == 0 && !calls && !input.complete);
        due = clock.deadline_ns;
        assert(full_adf_source7_clock_expire(&clock, 1, due, &event) == 0);
        event_matches(&event, 4, (reset + 4) & FULL_ADF_SOURCE7_COUNTER_MASK, phase, due, due);
        assert(clock.events_delivered == 4 && !clock.armed);
        assert(full_adf_source7_clock_get(&clock, 1, 5, &snapshot) == 0);
        assert(snapshot.epoch == 4 && snapshot.counter == event.hardware.counter);
        assert(memcmp(&input, &input_before, sizeof(input)) == 0 && !calls && !input.complete);
        assert(memcmp(&delay, &completed_delay, sizeof(delay)) == 0 && delay.control_state == 2);
        clock_before = clock;
        assert(full_adf_input_pump(&input, 1) == 0);
        assert(input.complete && calls == 1 && input.scheduler_consumed == 1 && !input.jobs[0].active);
        assert(memcmp(&clock, &clock_before, sizeof(clock)) == 0);
    }
    puts("ADF_SOURCE7_FOURTH_PASS_INPUT_REQUIRES_EXPLICIT_PUMP_PASS");
}

static void wrap(void)
{
    struct full_adf_source7_clock clock;
    struct full_adf_source7_event event;
    struct full_adf_delay129 delay, late, before;
    bound(&clock, 0xffffff, 0xffff);
    registered(&delay, &clock);
    assert(full_adf_source7_clock_arm(&clock, 1, 0) == 0);
    assert(full_adf_source7_clock_expire(&clock, 1, clock.deadline_ns, &event) == 0);
    event_matches(&event, 1, 0, 0xffff, FULL_ADF_SOURCE7_PERIOD_NS, FULL_ADF_SOURCE7_PERIOD_NS);
    assert(full_adf_delay129_poll(&delay, 1, &clock) == 0 && delay.control_state == 2);
    registered(&late, &clock);
    assert(late.saved74 == 0 && late.start7c == 0 && late.registered_epoch == 1);
    before = late;
    assert(full_adf_delay129_poll(&late, 1, &clock) == 1);
    assert(memcmp(&late, &before, sizeof(late)) == 0);
    assert(full_adf_source7_clock_expire(&clock, 1, clock.deadline_ns, &event) == 0);
    assert(event.hardware.counter == 1 && event.sequence == 2 && event.cache.phase == 0xffff);
    assert(full_adf_delay129_poll(&late, 1, &clock) == 0 && late.control_state == 2);
    puts("ADF_SOURCE7_24BIT_WRAP_PHASE_PRESERVED_PASS");
}

static void first_group(struct full_adf_source7_clock *clock, uint32_t counter,
                        unsigned int phase)
{
    struct full_adf_source7_event event;
    unsigned int i;
    bound(clock, counter, phase);
    assert(full_adf_source7_clock_arm(clock, 1, 100) == 0);
    for (i = 1; i <= FULL_ADF_SOURCE7_MAX_EVENTS; ++i) {
        assert(full_adf_source7_clock_expire(clock, 1, clock->deadline_ns, &event) == 0);
        assert(event.generation == 1 && event.sequence == i);
    }
    assert(clock->started && !clock->armed && clock->events_delivered == 4);
}

static void continuation(void)
{
    struct full_adf_source7_clock clock, before, expected;
    struct full_adf_source7_snapshot snapshot, saved_snapshot;
    struct full_adf_source7_event event, saved;
    unsigned int variant, i, phase;
    uint32_t reset;
    uint64_t now, due;
    for (variant = 0; variant < 2; ++variant) {
        reset = variant ? FULL_ADF_SOURCE7_COUNTER_MASK - 4 : 0;
        phase = variant ? 0xffff : 321;
        first_group(&clock, reset, phase);
        now = clock.deadline_ns - FULL_ADF_SOURCE7_PERIOD_NS;
        if (variant) now += FULL_ADF_SOURCE7_PERIOD_NS + 17;
        expected = clock;
        expected.generation = 2;
        expected.armed = 1;
        expected.deadline_ns = now + FULL_ADF_SOURCE7_PERIOD_NS;
        assert(full_adf_source7_clock_continue(&clock, now) == 0);
        assert(memcmp(&clock, &expected, sizeof(clock)) == 0);
        before = clock;
        memset(&snapshot, 0xa5, sizeof(snapshot));
        saved_snapshot = snapshot;
        assert(full_adf_source7_clock_get(&clock, 1, 5, &snapshot) == -1);
        assert(memcmp(&snapshot, &saved_snapshot, sizeof(snapshot)) == 0);
        for (i = 0; i < 10; ++i) {
            assert(full_adf_source7_clock_get(&clock, 2, 5, &snapshot) == 0);
            assert(snapshot.counter == ((reset + 4) & FULL_ADF_SOURCE7_COUNTER_MASK));
            assert(snapshot.phase == phase && snapshot.epoch == 4);
        }
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        memset(&event, 0xa5, sizeof(event));
        for (i = 5; i <= 8; ++i) {
            before = clock;
            saved = event;
            due = clock.deadline_ns;
            assert(full_adf_source7_clock_expire(&clock, 2, due - 1, &event) == 1);
            assert(memcmp(&clock, &before, sizeof(clock)) == 0);
            assert(memcmp(&event, &saved, sizeof(event)) == 0);
            now = due + 7;
            assert(full_adf_source7_clock_expire(&clock, 2, now, &event) == 0);
            event_matches(&event, i, (reset + i) & FULL_ADF_SOURCE7_COUNTER_MASK,
                          phase, due, now);
            assert(clock.events_delivered == i && clock.started == 1);
            assert(clock.armed == (i < 8) && clock.deadline_ns == now + FULL_ADF_SOURCE7_PERIOD_NS);
            before = clock;
            assert(full_adf_source7_clock_get(&clock, 2, 5, &snapshot) == 0);
            assert(snapshot.epoch == i && snapshot.counter == event.hardware.counter);
            assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        }
        assert(!clock.armed && clock.hardware7.epoch == 8 && clock.cache5.epoch == 8);
        before = clock;
        saved = event;
        assert(full_adf_source7_clock_expire(&clock, 2, clock.deadline_ns, &event) == -1);
        only_clock_fault(&clock, before);
        assert(memcmp(&event, &saved, sizeof(event)) == 0);
    }
    puts("ADF_SOURCE7_CONTINUE_SAME_OWNER_EPOCH4_THROUGH8_WRAP_PASS");
}

static void continuation_rejections(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_event event;
    uint64_t now;
    unsigned int i, j;
    for (i = 0; i < 37; ++i) {
        first_group(&clock, 31, 42);
        now = clock.deadline_ns - FULL_ADF_SOURCE7_PERIOD_NS;
        switch (i) {
        case 0: memset(&clock, 0, sizeof(clock)); break;
        case 1:
            bound(&clock, 31, 42);
            break;
        case 2: case 3: case 4:
            bound(&clock, 31, 42);
            assert(full_adf_source7_clock_arm(&clock, 1, 100) == 0);
            for (j = 0; j < (i == 4 ? 3 : i - 2); ++j)
                assert(full_adf_source7_clock_expire(&clock, 1, clock.deadline_ns, &event) == 0);
            break;
        case 5: clock.known = 0; break;
        case 6: clock.fault = 1; break;
        case 7: clock.busy = 1; break;
        case 8: clock.bound = 0; break;
        case 9: clock.cache_valid = 0; break;
        case 10: clock.started = 0; break;
        case 11: clock.started = 2; break;
        case 12: clock.armed = 1; break;
        case 13: clock.armed = 2; break;
        case 14: clock.events_delivered = 5; break;
        case 15: clock.generation = 0; break;
        case 16: clock.generation = 2; break;
        case 17: clock.generation = 3; break;
        case 18: clock.reset_counter = FULL_ADF_SOURCE7_COUNTER_MASK + 1; break;
        case 19: ++clock.reset_counter; break;
        case 20: ++clock.reset_phase; break;
        case 21: ++clock.hardware7.counter; break;
        case 22: ++clock.hardware7.phase; break;
        case 23: ++clock.hardware7.epoch; break;
        case 24: ++clock.published_fb.counter; break;
        case 25: ++clock.published_fb.phase; break;
        case 26: ++clock.published_fb.epoch; break;
        case 27: ++clock.cache5.counter; break;
        case 28: ++clock.cache5.phase; break;
        case 29: ++clock.cache5.epoch; break;
        case 30: clock.deadline_ns = 0; break;
        case 31: clock.deadline_ns = FULL_ADF_SOURCE7_PERIOD_NS - 1; break;
        case 32: --now; break;
        case 33: now = UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS + 1; break;
        case 34: now = UINT64_MAX; break;
        case 35: case 36:
            assert(full_adf_source7_clock_continue(&clock, now) == 0);
            if (i == 36) {
                for (j = 0; j < FULL_ADF_SOURCE7_MAX_EVENTS; ++j)
                    assert(full_adf_source7_clock_expire(&clock, 2, clock.deadline_ns, &event) == 0);
                now = clock.deadline_ns;
            }
            break;
        }
        before = clock;
        assert(full_adf_source7_clock_continue(&clock, now) == -1);
        only_clock_fault(&clock, before);
    }
    assert(full_adf_source7_clock_continue(NULL, 0) == -1);
    puts("ADF_SOURCE7_CONTINUE_EARLY_CORRUPT_BACKWARD_OVERFLOW_REUSE_REJECTED");
}

static void continuation_ownership(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_snapshot snapshot, saved_snapshot;
    struct full_adf_source7_event event, saved;
    struct full_adf_delay129 delay, delay_before;
    unsigned int i;
    int result;
    for (i = 0; i < 7; ++i) {
        first_group(&clock, 0, 0);
        assert(full_adf_source7_clock_continue(&clock, clock.deadline_ns) == 0);
        before = clock;
        memset(&event, 0xa5, sizeof(event));
        saved = event;
        if (i == 0) result = full_adf_source7_clock_init(&clock, 0, 0);
        else if (i == 1) result = full_adf_source7_clock_bind(&clock, 1, 5, 7);
        else if (i == 2) result = full_adf_source7_clock_arm(&clock, 1, clock.deadline_ns);
        else if (i == 3) result = full_adf_source7_clock_arm(&clock, 2, clock.deadline_ns);
        else result = full_adf_source7_clock_expire(&clock, i == 4 ? 1 : i == 5 ? 3 : 0,
                                                    clock.deadline_ns, &event);
        assert(result == -1);
        if (i == 0) assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        else only_clock_fault(&clock, before);
        assert(memcmp(&event, &saved, sizeof(event)) == 0);
    }
    first_group(&clock, 0, 0);
    assert(full_adf_source7_clock_continue(&clock, clock.deadline_ns) == 0);
    for (i = 0; i < 11; ++i) {
        before = clock;
        memset(&snapshot, 0xa5, sizeof(snapshot));
        saved_snapshot = snapshot;
        switch (i) {
        case 3: clock.events_delivered = 3; break;
        case 4: clock.events_delivered = 9; break;
        case 5: clock.started = 0; break;
        case 6: clock.armed = 0; break;
        case 7: clock.cache5.epoch = 0; break;
        case 8: clock.published_fb.counter = 0; break;
        case 9: clock.busy = 1; break;
        case 10: clock.fault = 1; break;
        }
        {
            struct full_adf_source7_clock rejected = clock;
            assert(full_adf_source7_clock_get(&clock, i < 3 ? i == 0 ? 0 : i == 1 ? 1 : 3 : 2,
                                              5, &snapshot) == -1);
            assert(memcmp(&clock, &rejected, sizeof(clock)) == 0);
        }
        assert(memcmp(&snapshot, &saved_snapshot, sizeof(snapshot)) == 0);
        clock = before;
    }
    for (i = 1; i <= 2; ++i) {
        memset(&delay, 0, sizeof(delay));
        assert(full_adf_delay129_init(&delay) == 0);
        delay_before = delay;
        before = clock;
        assert(full_adf_delay129_register(&delay, i, &clock) == -1);
        only_delay_fault(&delay, delay_before);
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    }
    bound(&clock, 0, 0);
    registered(&delay, &clock);
    assert(full_adf_source7_clock_arm(&clock, 1, 100) == 0);
    for (i = 0; i < FULL_ADF_SOURCE7_MAX_EVENTS; ++i)
        assert(full_adf_source7_clock_expire(&clock, 1, clock.deadline_ns, &event) == 0);
    saved = event;
    assert(full_adf_source7_clock_continue(&clock, clock.deadline_ns) == 0);
    delay_before = delay;
    before = clock;
    assert(full_adf_delay129_poll(&delay, 1, &clock) == -1);
    only_delay_fault(&delay, delay_before);
    assert(delay.pending_work && delay.control_state == 1);
    assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    assert(full_adf_source7_clock_expire(&clock, saved.generation, saved.observed_ns, &event) == -1);
    only_clock_fault(&clock, before);
    assert(memcmp(&event, &saved, sizeof(event)) == 0);
    puts("ADF_SOURCE7_CONTINUE_OLD_GENERATION_GET_EVENT_DELAY_REJECTED");
}

static void continuation_cancellation(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_event event, saved;
    struct full_adf_source7_snapshot snapshot, saved_snapshot;
    unsigned int i, j;
    for (i = 0; i < FULL_ADF_SOURCE7_MAX_EVENTS; ++i) {
        first_group(&clock, 11, 12);
        assert(full_adf_source7_clock_continue(&clock, clock.deadline_ns) == 0);
        for (j = 0; j < i; ++j)
            assert(full_adf_source7_clock_expire(&clock, 2, clock.deadline_ns, &event) == 0);
        before = clock;
        assert(full_adf_source7_clock_cancel(&clock, 1) == -1);
        only_clock_fault(&clock, before);
        assert(full_adf_source7_clock_cancel(&clock, 2) == 0);
        before.fault = 1;
        before.armed = 0;
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        memset(&snapshot, 0xa5, sizeof(snapshot));
        saved_snapshot = snapshot;
        memset(&event, 0xa5, sizeof(event));
        saved = event;
        assert(full_adf_source7_clock_get(&clock, 2, 5, &snapshot) == -1);
        assert(memcmp(&snapshot, &saved_snapshot, sizeof(snapshot)) == 0);
        assert(full_adf_source7_clock_expire(&clock, 2, clock.deadline_ns, &event) == -1);
        assert(full_adf_source7_clock_continue(&clock, clock.deadline_ns) == -1);
        assert(full_adf_source7_clock_cancel(&clock, 2) == -1);
        assert(memcmp(&event, &saved, sizeof(event)) == 0);
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        assert(clock.events_delivered == 4 + i && clock.events_delivered < 8);
    }
    first_group(&clock, 0, 0);
    assert(full_adf_source7_clock_continue(&clock, clock.deadline_ns) == 0);
    for (i = 0; i < FULL_ADF_SOURCE7_MAX_EVENTS; ++i)
        assert(full_adf_source7_clock_expire(&clock, 2, clock.deadline_ns, &event) == 0);
    before = clock;
    assert(full_adf_source7_clock_cancel(&clock, 2) == -1);
    only_clock_fault(&clock, before);
    puts("ADF_SOURCE7_CONTINUE_CANCEL_CURRENT_GENERATION_FAULT_PRESERVES_TOTAL_PASS");
}

static void continuation_overflow(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_event event, saved;
    first_group(&clock, 0, 0);
    assert(full_adf_source7_clock_continue(&clock, UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS) == 0);
    assert(clock.deadline_ns == UINT64_MAX && clock.events_delivered == 4 && clock.armed);
    before = clock;
    memset(&event, 0xa5, sizeof(event));
    saved = event;
    assert(full_adf_source7_clock_expire(&clock, 2, UINT64_MAX - 1, &event) == 1);
    assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    assert(memcmp(&event, &saved, sizeof(event)) == 0);
    assert(full_adf_source7_clock_expire(&clock, 2, UINT64_MAX, &event) == -1);
    only_clock_fault(&clock, before);
    assert(memcmp(&event, &saved, sizeof(event)) == 0);
    assert(full_adf_source7_clock_cancel(&clock, 2) == 0);
    assert(clock.fault && !clock.armed && clock.events_delivered == 4);
    puts("ADF_SOURCE7_CONTINUE_MAX_DEADLINE_NO_OVERFLOW_EVENT_PASS");
}

static void second_group(struct full_adf_source7_clock *clock, uint32_t counter,
                         unsigned int phase)
{
    struct full_adf_source7_event event;
    unsigned int i;
    first_group(clock, counter, phase);
    assert(full_adf_source7_clock_continue(clock, clock->deadline_ns) == 0);
    for (i = 5; i <= 8; ++i) {
        assert(full_adf_source7_clock_expire(clock, 2, clock->deadline_ns, &event) == 0);
        assert(event.generation == 2 && event.sequence == i);
    }
    assert(clock->started && !clock->armed && clock->events_delivered == 8);
}

static void output_continuation(void)
{
    struct full_adf_source7_clock clock, before, expected;
    struct full_adf_source7_snapshot snapshot, saved_snapshot;
    struct full_adf_source7_event event, saved;
    unsigned int variant, i, phase;
    uint32_t reset;
    uint64_t now, due;
    for (variant = 0; variant < 2; ++variant) {
        reset = variant ? FULL_ADF_SOURCE7_COUNTER_MASK - 8 : 0;
        phase = variant ? 0xffff : 321;
        second_group(&clock, reset, phase);
        now = clock.deadline_ns - FULL_ADF_SOURCE7_PERIOD_NS;
        if (variant) now += FULL_ADF_SOURCE7_PERIOD_NS + 17;
        expected = clock;
        expected.generation = 3;
        expected.armed = 1;
        expected.deadline_ns = now + FULL_ADF_SOURCE7_PERIOD_NS;
        assert(full_adf_source7_clock_continue_output(&clock, now) == 0);
        assert(memcmp(&clock, &expected, sizeof(clock)) == 0);
        before = clock;
        memset(&snapshot, 0xa5, sizeof(snapshot));
        saved_snapshot = snapshot;
        for (i = 0; i <= 4; ++i) {
            if (i == 3) continue;
            assert(full_adf_source7_clock_get(&clock, i, 5, &snapshot) == -1);
            assert(memcmp(&snapshot, &saved_snapshot, sizeof(snapshot)) == 0);
        }
        for (i = 0; i < 10; ++i) {
            assert(full_adf_source7_clock_get(&clock, 3, 5, &snapshot) == 0);
            assert(snapshot.counter == ((reset + 8) & FULL_ADF_SOURCE7_COUNTER_MASK));
            assert(snapshot.phase == phase && snapshot.epoch == 8);
        }
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        memset(&event, 0xa5, sizeof(event));
        saved = event;
        due = clock.deadline_ns;
        assert(full_adf_source7_clock_expire(&clock, 3, now, &event) == 1);
        assert(full_adf_source7_clock_expire(&clock, 3, due - 1, &event) == 1);
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        assert(memcmp(&event, &saved, sizeof(event)) == 0);
        now = variant ? due + UINT64_C(1000000000) : due;
        assert(full_adf_source7_clock_expire(&clock, 3, now, &event) == 0);
        event_matches(&event, 9, (reset + 9) & FULL_ADF_SOURCE7_COUNTER_MASK, phase, due, now);
        assert(clock.generation == 3 && clock.events_delivered == 9 && clock.started && !clock.armed);
        assert(clock.deadline_ns == now + FULL_ADF_SOURCE7_PERIOD_NS);
        before = clock;
        assert(full_adf_source7_clock_get(&clock, 3, 5, &snapshot) == 0);
        assert(snapshot.counter == event.cache.counter && snapshot.epoch == 9 && snapshot.phase == phase);
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        saved = event;
        assert(full_adf_source7_clock_expire(&clock, 3, clock.deadline_ns, &event) == -1);
        only_clock_fault(&clock, before);
        assert(memcmp(&event, &saved, sizeof(event)) == 0);
        assert(clock.events_delivered == 9);
    }
    puts("ADF_SOURCE7_OUTPUT_CONTINUE_EPOCH8_SINGLE_EVENT9_WRAP_PHASE_PASS");
}

static void output_rejections(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_event event;
    uint64_t now;
    unsigned int i, j;
    for (i = 0; i < 45; ++i) {
        second_group(&clock, 31, 42);
        now = clock.deadline_ns - FULL_ADF_SOURCE7_PERIOD_NS;
        switch (i) {
        case 0: memset(&clock, 0, sizeof(clock)); break;
        case 1: bound(&clock, 31, 42); break;
        case 2: first_group(&clock, 31, 42); break;
        case 3: case 4: case 5: case 6:
            first_group(&clock, 31, 42);
            assert(full_adf_source7_clock_continue(&clock, clock.deadline_ns) == 0);
            for (j = 0; j < i - 3; ++j)
                assert(full_adf_source7_clock_expire(&clock, 2, clock.deadline_ns, &event) == 0);
            break;
        case 7: clock.known = 0; break;
        case 8: clock.known = 2; break;
        case 9: clock.fault = 1; break;
        case 10: clock.busy = 1; break;
        case 11: clock.bound = 0; break;
        case 12: clock.cache_valid = 0; break;
        case 13: clock.started = 0; break;
        case 14: clock.started = 2; break;
        case 15: clock.armed = 1; break;
        case 16: clock.armed = 2; break;
        case 17: clock.events_delivered = 7; break;
        case 18: clock.events_delivered = 9; break;
        case 19: clock.generation = 0; break;
        case 20: clock.generation = 1; break;
        case 21: clock.generation = 3; break;
        case 22: clock.generation = 4; break;
        case 23: clock.generation = UINT64_MAX; break;
        case 24: clock.reset_counter = FULL_ADF_SOURCE7_COUNTER_MASK + 1; break;
        case 25: ++clock.reset_counter; break;
        case 26: ++clock.reset_phase; break;
        case 27: ++clock.hardware7.counter; break;
        case 28: ++clock.hardware7.phase; break;
        case 29: ++clock.hardware7.epoch; break;
        case 30: ++clock.published_fb.counter; break;
        case 31: ++clock.published_fb.phase; break;
        case 32: ++clock.published_fb.epoch; break;
        case 33: ++clock.cache5.counter; break;
        case 34: ++clock.cache5.phase; break;
        case 35: ++clock.cache5.epoch; break;
        case 36: clock.deadline_ns = 0; break;
        case 37: clock.deadline_ns = FULL_ADF_SOURCE7_PERIOD_NS - 1; break;
        case 38: --now; break;
        case 39: now = UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS + 1; break;
        case 40: now = UINT64_MAX; break;
        case 41: case 42:
            assert(full_adf_source7_clock_continue_output(&clock, now) == 0);
            if (i == 42) {
                assert(full_adf_source7_clock_expire(&clock, 3, clock.deadline_ns, &event) == 0);
                now = clock.deadline_ns;
            }
            break;
        case 43: clock.bound = 2; break;
        case 44: clock.cache_valid = 2; break;
        }
        before = clock;
        assert(full_adf_source7_clock_continue_output(&clock, now) == -1);
        only_clock_fault(&clock, before);
    }
    assert(full_adf_source7_clock_continue_output(NULL, 0) == -1);
    puts("ADF_SOURCE7_OUTPUT_EARLY_CORRUPT_BACKWARD_OVERFLOW_DUPLICATE_REJECTED");
}

static void output_ownership(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_event event, saved;
    struct full_adf_source7_snapshot snapshot, saved_snapshot;
    struct full_adf_delay129 delay, delay_before;
    unsigned int i;
    int result;
    for (i = 0; i < 13; ++i) {
        second_group(&clock, 0, 0);
        assert(full_adf_source7_clock_continue_output(&clock, clock.deadline_ns) == 0);
        before = clock;
        memset(&event, 0xa5, sizeof(event));
        saved = event;
        if (i == 0) result = full_adf_source7_clock_init(&clock, 0, 0);
        else if (i <= 2) result = full_adf_source7_clock_bind(&clock, i == 1 ? 1 : 3, 5, 7);
        else if (i <= 5) result = full_adf_source7_clock_arm(&clock, i - 2, clock.deadline_ns);
        else if (i == 6) result = full_adf_source7_clock_continue(&clock, clock.deadline_ns);
        else result = full_adf_source7_clock_expire(&clock,
            i < 10 ? i - 7 : i == 10 ? 4 : i == 11 ? UINT64_MAX : 3,
            clock.deadline_ns, i == 12 ? NULL : &event);
        assert(result == -1);
        if (i == 0) assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        else only_clock_fault(&clock, before);
        assert(memcmp(&event, &saved, sizeof(event)) == 0);
    }
    second_group(&clock, 0, 0);
    assert(full_adf_source7_clock_continue_output(&clock, clock.deadline_ns) == 0);
    for (i = 0; i < 14; ++i) {
        before = clock;
        switch (i) {
        case 0: clock.events_delivered = 7; break;
        case 1: clock.events_delivered = 10; break;
        case 2: clock.started = 0; break;
        case 3: clock.armed = 0; break;
        case 4: clock.cache5.epoch = 0; break;
        case 5: ++clock.published_fb.counter; break;
        case 6: clock.busy = 1; break;
        case 7: clock.fault = 1; break;
        case 8: ++clock.hardware7.phase; break;
        case 9: clock.generation = 4; break;
        case 10: clock.bound = 0; break;
        case 11: clock.cache_valid = 0; break;
        case 12: clock.events_delivered = 9; break;
        case 13: clock.deadline_ns = FULL_ADF_SOURCE7_PERIOD_NS - 1; break;
        }
        memset(&snapshot, 0xa5, sizeof(snapshot));
        saved_snapshot = snapshot;
        {
            struct full_adf_source7_clock rejected = clock;
            assert(full_adf_source7_clock_get(&clock, 3, 5, &snapshot) == -1);
            assert(memcmp(&clock, &rejected, sizeof(clock)) == 0);
            memset(&event, 0xa5, sizeof(event));
            saved = event;
            assert(full_adf_source7_clock_expire(&clock, 3, clock.deadline_ns, &event) == -1);
            only_clock_fault(&clock, rejected);
            assert(memcmp(&event, &saved, sizeof(event)) == 0);
        }
        assert(memcmp(&snapshot, &saved_snapshot, sizeof(snapshot)) == 0);
        clock = before;
    }
    for (i = 1; i <= 3; ++i) {
        memset(&delay, 0, sizeof(delay));
        assert(full_adf_delay129_init(&delay) == 0);
        delay_before = delay;
        before = clock;
        assert(full_adf_delay129_register(&delay, i, &clock) == -1);
        only_delay_fault(&delay, delay_before);
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    }
    /* Even a consistent fabricated generation4 cannot extend this lifetime. */
    clock.generation = 4;
    clock.events_delivered = 12;
    clock.hardware7.counter = clock.published_fb.counter = clock.cache5.counter = 12;
    clock.hardware7.epoch = clock.published_fb.epoch = clock.cache5.epoch = 12;
    before = clock;
    memset(&snapshot, 0xa5, sizeof(snapshot));
    saved_snapshot = snapshot;
    assert(full_adf_source7_clock_get(&clock, 4, 5, &snapshot) == -1);
    assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    assert(memcmp(&snapshot, &saved_snapshot, sizeof(snapshot)) == 0);
    memset(&event, 0xa5, sizeof(event));
    saved = event;
    assert(full_adf_source7_clock_expire(&clock, 4, clock.deadline_ns, &event) == -1);
    only_clock_fault(&clock, before);
    assert(memcmp(&event, &saved, sizeof(event)) == 0);
    puts("ADF_SOURCE7_OUTPUT_NO_RESET_REBIND_REARM_OLD_EVENT_DELAY_OR_GEN4_PASS");
}

static void output_cancellation(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_event event, saved;
    struct full_adf_source7_snapshot snapshot, saved_snapshot;
    unsigned int i;
    for (i = 0; i <= 4; ++i) {
        second_group(&clock, 11, 12);
        assert(full_adf_source7_clock_continue_output(&clock, clock.deadline_ns) == 0);
        before = clock;
        if (i != 3) {
            assert(full_adf_source7_clock_cancel(&clock, i) == -1);
            only_clock_fault(&clock, before);
        }
        assert(full_adf_source7_clock_cancel(&clock, 3) == 0);
        before.fault = 1;
        before.armed = 0;
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        memset(&snapshot, 0xa5, sizeof(snapshot));
        saved_snapshot = snapshot;
        memset(&event, 0xa5, sizeof(event));
        saved = event;
        assert(full_adf_source7_clock_get(&clock, 3, 5, &snapshot) == -1);
        assert(memcmp(&snapshot, &saved_snapshot, sizeof(snapshot)) == 0);
        assert(full_adf_source7_clock_expire(&clock, 3, clock.deadline_ns, &event) == -1);
        assert(full_adf_source7_clock_continue_output(&clock, clock.deadline_ns) == -1);
        assert(full_adf_source7_clock_cancel(&clock, 3) == -1);
        assert(memcmp(&event, &saved, sizeof(event)) == 0);
        assert(memcmp(&clock, &before, sizeof(clock)) == 0 && clock.events_delivered == 8);
    }
    second_group(&clock, 0, 0);
    assert(full_adf_source7_clock_continue_output(&clock, clock.deadline_ns) == 0);
    assert(full_adf_source7_clock_expire(&clock, 3, clock.deadline_ns, &event) == 0);
    before = clock;
    assert(full_adf_source7_clock_cancel(&clock, 3) == -1);
    only_clock_fault(&clock, before);
    puts("ADF_SOURCE7_OUTPUT_CANCEL_CURRENT_FAULT_PRESERVES_EVENT8_PASS");
}

static void output_overflow(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_event event, saved;
    second_group(&clock, 0, 0);
    assert(full_adf_source7_clock_continue_output(&clock, UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS) == 0);
    assert(clock.deadline_ns == UINT64_MAX && clock.events_delivered == 8 && clock.armed);
    before = clock;
    memset(&event, 0xa5, sizeof(event));
    saved = event;
    assert(full_adf_source7_clock_expire(&clock, 3, UINT64_MAX - 1, &event) == 1);
    assert(memcmp(&clock, &before, sizeof(clock)) == 0);
    assert(memcmp(&event, &saved, sizeof(event)) == 0);
    assert(full_adf_source7_clock_expire(&clock, 3, UINT64_MAX, &event) == -1);
    only_clock_fault(&clock, before);
    assert(memcmp(&event, &saved, sizeof(event)) == 0);
    assert(full_adf_source7_clock_cancel(&clock, 3) == 0);
    assert(clock.fault && !clock.armed && clock.events_delivered == 8);
    second_group(&clock, 0, 0);
    assert(full_adf_source7_clock_continue_output(&clock,
        UINT64_MAX - 2u * FULL_ADF_SOURCE7_PERIOD_NS) == 0);
    assert(full_adf_source7_clock_expire(&clock, 3,
        UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS, &event) == 0);
    assert(clock.deadline_ns == UINT64_MAX && !clock.armed && !clock.fault);
    assert(clock.events_delivered == 9 && clock.cache5.counter == 9 && clock.cache5.epoch == 9);
    puts("ADF_SOURCE7_OUTPUT_MAX_DEADLINE_NO_OVERFLOW_EVENT_PASS");
}

static void clock_rejections(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_snapshot snapshot, snapshot_before;
    struct full_adf_source7_event event, saved;
    unsigned int i;
    int result;
    for (i = 0; i < 6; ++i) {
        memset(&clock, 0, sizeof(clock));
        assert(full_adf_source7_clock_init(&clock, 3, 4) == 0);
        before = clock;
        result = full_adf_source7_clock_bind(&clock, i < 2 ? i * 2 : 1,
                                              i == 2 ? 7 : i == 3 ? 0 : 5,
                                              i == 4 ? 5 : i == 5 ? 8 : 7);
        assert(result == -1);
        only_clock_fault(&clock, before);
    }
    for (i = 0; i < 7; ++i) {
        bound(&clock, 3, 4);
        memset(&snapshot, 0xa5, sizeof(snapshot));
        snapshot_before = snapshot;
        if (i == 3) clock.cache_valid = 0;
        if (i == 4) clock.cache5.epoch = 1;
        if (i == 5) clock.published_fb.counter = 7;
        if (i == 6) clock.busy = 1;
        before = clock;
        assert(full_adf_source7_clock_get(&clock, i < 2 ? i * 2 : 1,
                                          i == 2 ? 7 : 5, &snapshot) == -1);
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        assert(memcmp(&snapshot, &snapshot_before, sizeof(snapshot)) == 0);
    }
    for (i = 0; i < 11; ++i) {
        bound(&clock, 3, 4);
        if (i >= 2) assert(full_adf_source7_clock_arm(&clock, 1, 0) == 0);
        if (i == 5) clock.busy = 1;
        if (i == 6) clock.known = 0;
        if (i == 7) clock.hardware7.counter = 0x1000000;
        if (i == 8) clock.hardware7.phase = 5;
        if (i == 9) clock.cache5.counter = 2;
        if (i == 10) clock.events_delivered = FULL_ADF_SOURCE7_MAX_EVENTS + 1;
        before = clock;
        memset(&event, 0xa5, sizeof(event));
        saved = event;
        if (i == 0) result = full_adf_source7_clock_bind(&clock, 1, 5, 7);
        else if (i == 2) result = full_adf_source7_clock_arm(&clock, 1, 0);
        else result = full_adf_source7_clock_expire(&clock, i == 3 ? 2 : 1,
                                                    FULL_ADF_SOURCE7_PERIOD_NS,
                                                    i == 4 ? NULL : &event);
        assert(result == -1);
        only_clock_fault(&clock, before);
        assert(memcmp(&event, &saved, sizeof(event)) == 0);
    }
    memset(&clock, 0, sizeof(clock));
    before = clock;
    assert(full_adf_source7_clock_arm(&clock, 1, 0) == -1);
    only_clock_fault(&clock, before);
    memset(&clock, 0, sizeof(clock));
    assert(full_adf_source7_clock_init(&clock, 0, 0) == 0);
    before = clock;
    assert(full_adf_source7_clock_expire(&clock, 1, 1, &event) == -1);
    only_clock_fault(&clock, before);
    assert(full_adf_source7_clock_expire(NULL, 1, 1, &event) == -1);
    bound(&clock, 0, 0);
    assert(full_adf_source7_clock_arm(&clock, 1, 0) == 0);
    for (i = 0; i < 3; ++i)
        assert(full_adf_source7_clock_expire(&clock, 1, clock.deadline_ns, &event) == 0);
    assert(clock.events_delivered == 3 && clock.armed);
    before = clock;
    saved = event;
    assert(full_adf_source7_clock_expire(&clock, 2, clock.deadline_ns, &event) == -1);
    only_clock_fault(&clock, before);
    assert(memcmp(&event, &saved, sizeof(event)) == 0);
    puts("ADF_SOURCE7_UNKNOWN_ALIAS_GENERATION_REENTRY_STALE_REJECTED");
}

static void delay_rejections(void)
{
    struct full_adf_source7_clock clock, clock_before, other;
    struct full_adf_source7_event event;
    struct full_adf_delay129 delay, before;
    unsigned int i;
    for (i = 0; i < 12; ++i) {
        bound(&clock, 5, 6);
        memset(&delay, 0, sizeof(delay));
        assert(full_adf_delay129_init(&delay) == 0);
        if (i == 1) delay.mode = 1;
        if (i == 2) delay.processing_state = 3;
        if (i == 3) delay.owner18 = 1;
        if (i == 4) delay.callback_pending = 1;
        if (i == 5) delay.pending_work = 1;
        if (i == 6) delay.software_source = 7;
        if (i == 7) delay.hardware_source = 5;
        if (i == 8) delay.busy = 1;
        if (i == 9) delay.known = 0;
        if (i == 10) assert(full_adf_delay129_register(&delay, 1, &clock) == 0);
        if (i == 11) clock.bound = 0;
        before = delay;
        clock_before = clock;
        assert(full_adf_delay129_register(&delay, i == 0 ? 2 : 1, &clock) == -1);
        only_delay_fault(&delay, before);
        assert(delay.control_state != 2);
        assert(memcmp(&clock, &clock_before, sizeof(clock)) == 0);
    }
    for (i = 0; i < 19; ++i) {
        bound(&clock, 5, 6);
        registered(&delay, &clock);
        assert(full_adf_source7_clock_arm(&clock, 1, 0) == 0);
        assert(full_adf_source7_clock_expire(&clock, 1, clock.deadline_ns, &event) == 0);
        other = clock;
        if (i == 2) delay.mode = 1;
        if (i == 3) delay.processing_state = 3;
        if (i == 4) delay.owner18 = 1;
        if (i == 5) delay.callback_pending = 1;
        if (i == 6) delay.delay78 = 1;
        if (i == 7) delay.start7c = 4;
        if (i == 8) delay.saved74 = delay.start7c = 6;
        if (i == 9) delay.registered_epoch = 2;
        if (i == 10) delay.pending_work = 0;
        if (i == 11) delay.priority = 3;
        if (i == 12) delay.software_source = 7;
        if (i == 13) delay.hardware_source = 5;
        if (i == 14) clock.cache5.epoch = 0;
        if (i == 15) clock.fault = 1;
        if (i == 16) delay.busy = 1;
        if (i == 17) delay.known = 0;
        if (i == 18) delay.pending = 0;
        before = delay;
        clock_before = clock;
        assert(full_adf_delay129_poll(&delay, i == 0 ? 2 : 1, i == 1 ? &other : &clock) == -1);
        only_delay_fault(&delay, before);
        assert(delay.control_state == 1);
        assert(memcmp(&clock, &clock_before, sizeof(clock)) == 0);
    }
    for (i = 0; i <= 2; ++i) {
        bound(&clock, 0, 0);
        registered(&delay, &clock);
        delay.processing_state = i;
        assert(full_adf_delay129_poll(&delay, 1, &clock) == 1);
        assert(full_adf_source7_clock_arm(&clock, 1, 0) == 0);
        assert(full_adf_source7_clock_expire(&clock, 1, clock.deadline_ns, &event) == 0);
        assert(full_adf_delay129_poll(&delay, 1, &clock) == 0);
        assert(delay.control_state == 2 && !delay.fault);
        before = delay;
        assert(full_adf_delay129_register(&delay, 1, &clock) == -1);
        only_delay_fault(&delay, before);
    }
    memset(&delay, 0, sizeof(delay));
    before = delay;
    assert(full_adf_delay129_poll(&delay, 1, &clock) == -1);
    only_delay_fault(&delay, before);
    assert(full_adf_delay129_register(NULL, 1, &clock) == -1);
    puts("ADF_SOURCE7_DELAY129_OWNERSHIP_DUPLICATE_INVALID_PROCESSING_REJECTED");
}

static void cancellation(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_event event, saved;
    struct full_adf_delay129 delay, delay_before;
    unsigned int i, j;
    for (i = 0; i < FULL_ADF_SOURCE7_MAX_EVENTS; ++i) {
        bound(&clock, 20, 30);
        registered(&delay, &clock);
        assert(full_adf_source7_clock_arm(&clock, 1, 10) == 0);
        for (j = 0; j < i; ++j)
            assert(full_adf_source7_clock_expire(&clock, 1, clock.deadline_ns, &event) == 0);
        assert(clock.events_delivered == i && clock.armed);
        before = clock;
        assert(full_adf_source7_clock_cancel(&clock, 2) == -1);
        only_clock_fault(&clock, before);
        assert(full_adf_source7_clock_cancel(&clock, 1) == 0);
        before.fault = 1;
        before.armed = 0;
        assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        delay_before = delay;
        assert(full_adf_delay129_poll(&delay, 1, &clock) == -1);
        only_delay_fault(&delay, delay_before);
        assert(full_adf_delay129_cancel(&delay, 1) == 0);
        delay_before.fault = 1;
        delay_before.registered = delay_before.priority = delay_before.pending_work = delay_before.pending = 0;
        assert(memcmp(&delay, &delay_before, sizeof(delay)) == 0);
        assert(delay.control_state == 1 && delay.fault && !delay.pending_work);
        before = clock;
        memset(&event, 0xa5, sizeof(event));
        saved = event;
        assert(full_adf_source7_clock_expire(&clock, 1, UINT64_C(1000000000), &event) == -1);
        only_clock_fault(&clock, before);
        assert(memcmp(&event, &saved, sizeof(event)) == 0);
        assert(full_adf_delay129_poll(&delay, 1, &clock) == -1);
        assert(delay.control_state == 1 && !delay.pending);
        assert(full_adf_source7_clock_cancel(&clock, 1) == -1);
        assert(full_adf_delay129_cancel(&delay, 1) == -1);
    }
    bound(&clock, 20, 30);
    registered(&delay, &clock);
    delay_before = delay;
    assert(full_adf_delay129_cancel(&delay, 2) == -1);
    only_delay_fault(&delay, delay_before);
    assert(delay.control_state == 1 && delay.pending_work);
    assert(full_adf_delay129_cancel(&delay, 1) == 0);
    assert(delay.fault && delay.control_state == 1 && !delay.pending_work);
    before = clock;
    assert(full_adf_source7_clock_cancel(&clock, 1) == -1);
    only_clock_fault(&clock, before);
    puts("ADF_SOURCE7_CANCELLATION_NEVER_NORMAL_COMPLETION_PASS");
}

static void overflow(void)
{
    struct full_adf_source7_clock clock, before;
    struct full_adf_source7_event event, saved;
    unsigned int i;
    bound(&clock, 0, 0);
    before = clock;
    assert(full_adf_source7_clock_arm(&clock, 1, UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS + 1) == -1);
    only_clock_fault(&clock, before);
    assert(!clock.armed && !clock.events_delivered);
    for (i = 0; i < 2; ++i) {
        bound(&clock, 0, 0);
        assert(full_adf_source7_clock_arm(&clock, 1,
                                         i ? UINT64_MAX - FULL_ADF_SOURCE7_PERIOD_NS : 0) == 0);
        memset(&event, 0xa5, sizeof(event));
        saved = event;
        before = clock;
        if (i) {
            assert(clock.deadline_ns == UINT64_MAX);
            assert(full_adf_source7_clock_expire(&clock, 1, UINT64_MAX - 1, &event) == 1);
            assert(memcmp(&clock, &before, sizeof(clock)) == 0);
        }
        assert(full_adf_source7_clock_expire(&clock, 1, UINT64_MAX, &event) == -1);
        only_clock_fault(&clock, before);
        assert(!clock.events_delivered && memcmp(&event, &saved, sizeof(event)) == 0);
        assert(full_adf_source7_clock_cancel(&clock, 1) == 0);
        assert(!clock.armed && clock.fault);
    }
    puts("ADF_SOURCE7_DEADLINE_OVERFLOW_NO_EVENT_PASS");
}

int main(int argc, char **argv)
{
    static const struct { const char *name; void (*run)(void); } cases[] = {
        {"construction", construction}, {"progress", progress}, {"budget", budget},
        {"fourth_pass", fourth_pass}, {"wrap", wrap},
        {"continuation", continuation}, {"continuation_rejections", continuation_rejections},
        {"continuation_ownership", continuation_ownership},
        {"continuation_cancellation", continuation_cancellation},
        {"continuation_overflow", continuation_overflow},
        {"output_continuation", output_continuation}, {"output_rejections", output_rejections},
        {"output_ownership", output_ownership}, {"output_cancellation", output_cancellation},
        {"output_overflow", output_overflow},
        {"clock_rejections", clock_rejections},
        {"delay_rejections", delay_rejections}, {"cancellation", cancellation}, {"overflow", overflow}
    };
    size_t i;
    int matched = 0;
    assert(argc == 1 || argc == 2);
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        if (argc == 1 || strcmp(argv[1], cases[i].name) == 0) {
            cases[i].run();
            matched = 1;
        }
    }
    assert(matched);
    return 0;
}
