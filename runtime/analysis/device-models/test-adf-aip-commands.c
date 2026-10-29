/* SPDX-License-Identifier: MIT */
#include "adf-aip-commands.h"
#include "adf-aip-disable.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

static const unsigned char af[8] = {0xaf, 0, 0, 0, 8, 0, 0, 0};
static const unsigned char b0[16] = {0xb0, 0, 0, 0, 16, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};

enum {
    GOOD, FAIL_BEFORE, BAD_READBACK, REENTER_CONSUME, REENTER_ENQUEUE,
    CHANGE_GENERATION, CHANGE_SEQUENCE, CHANGE_KNOWN, CHANGE_S, CHANGE_CURSOR,
    CHANGE_COUNT, CHANGE_BUFFER, CHANGE_RESPONSE, CHANGE_AF, CHANGE_EVENTS,
    CHANGE_BUSY, CHANGE_FAULT, CHANGE_FLAG, CHANGE_EVENT
};
struct provider {
    struct full_adf_aip_commands *state;
    unsigned int bank[3], calls, writes, readbacks, mode;
};

/* A test-owned register bank, not the six original disable leaves. */
static int disable_bank(void *opaque)
{
    struct provider *p = opaque;
    struct full_adf_aip_commands *s = p->state;
    p->calls++;
    assert(s->busy == 1 && s->command_count == 1 && !s->response_pending);
    assert(!s->b0_applied && !s->stateflag);
    assert(s->response.opcode == (s->sequence ? 0xafu : 0u));
    if (p->mode == FAIL_BEFORE) return -7;
    unsigned int before0 = p->bank[0], before2 = p->bank[2];
    p->bank[0] &= ~0x80u;
    p->bank[1] = 0;
    p->bank[2] &= ~0x300u;
    p->writes += 3;
    if (p->mode == BAD_READBACK) p->bank[1] = 1;
    p->readbacks += 3;
    if (p->bank[0] != (before0 & ~0x80u) || p->bank[1] ||
        p->bank[2] != (before2 & ~0x300u)) return -8;
    switch (p->mode) {
    case REENTER_CONSUME:
        assert(full_adf_aip_commands_consume(s, 1, s->dispatch_event, disable_bank, p) == -1021);
        assert(s->busy == 1 && s->fault == 1);
        break;
    case REENTER_ENQUEUE:
        assert(full_adf_aip_commands_enqueue(s, b0, sizeof b0, 1) == -1021);
        assert(s->busy == 1 && s->fault == 1);
        break;
    case CHANGE_GENERATION: s->generation = 2; break;
    case CHANGE_SEQUENCE: s->sequence++; break;
    case CHANGE_KNOWN: s->known = 0; break;
    case CHANGE_S: s->interpreter_state = 8; break;
    case CHANGE_CURSOR: s->cursor++; break;
    case CHANGE_COUNT: s->command_count++; break;
    case CHANGE_BUFFER: s->buffer[sizeof s->buffer - 1] = 0xaa; break;
    case CHANGE_RESPONSE:
        s->response_pending = 1;
        s->response.opcode = 0xde;
        s->response.status = -33;
        break;
    case CHANGE_AF: s->af_applied ^= 1; break;
    case CHANGE_EVENTS: s->events++; break;
    case CHANGE_BUSY: s->busy = 0; break;
    case CHANGE_FAULT: s->fault = 1; break;
    case CHANGE_FLAG: s->stateflag = 1; break;
    case CHANGE_EVENT: s->dispatch_event++; break;
    default: break;
    }
    return 0;
}

static struct provider provider_for(struct full_adf_aip_commands *s)
{
    struct provider p = {0};
    p.state = s;
    p.bank[0] = 0xa5a5a5ff;
    p.bank[1] = 0x12345678;
    p.bank[2] = 0x876547ff;
    return p;
}

static void empty_buffer(const struct full_adf_aip_commands *s)
{
    for (unsigned int i = 0; i < sizeof s->buffer; i++) assert(!s->buffer[i]);
    assert(!s->command_count && !s->cursor && !s->response_pending && !s->busy);
}

static void retained(const struct full_adf_aip_commands *s,
                     const struct full_adf_aip_commands *before)
{
    assert(!memcmp(s->buffer, before->buffer, sizeof s->buffer));
    assert(s->command_count == before->command_count && s->cursor == before->cursor);
    assert(s->response_pending == before->response_pending);
    assert(!memcmp(&s->response, &before->response, sizeof s->response));
    assert(s->sequence == before->sequence && s->events == before->events);
    assert(s->af_applied == before->af_applied && s->b0_applied == before->b0_applied);
    assert(s->stateflag == before->stateflag && s->fault == 1);
}

static void after_af(struct full_adf_aip_commands *s)
{
    assert(!full_adf_aip_commands_init(s));
    assert(!full_adf_aip_commands_enqueue(s, af, sizeof af, 1));
    struct provider p = provider_for(s);
    assert(!full_adf_aip_commands_consume(s, 1, 1, disable_bank, &p));
}

static void queued(struct full_adf_aip_commands *s, unsigned int stage)
{
    if (stage) after_af(s);
    else assert(!full_adf_aip_commands_init(s));
    assert(!full_adf_aip_commands_enqueue(s, stage ? b0 : af, stage ? sizeof b0 : sizeof af, 1));
}

static void reject_enqueue(struct full_adf_aip_commands *s, const unsigned char *data,
                           unsigned int bytes, unsigned long long generation)
{
    struct full_adf_aip_commands before;
    memcpy(&before, s, sizeof before);
    assert(full_adf_aip_commands_enqueue(s, data, bytes, generation) == -1021);
    assert(!memcmp(s, &before, sizeof before));
}

static void test_success(void)
{
    struct full_adf_aip_commands s = {0};
    assert(!full_adf_aip_commands_init(&s));
    assert(s.known == 1 && !s.interpreter_state && !s.generation);
    struct provider p = provider_for(&s);
    for (unsigned int stage = 0; stage < 2; stage++) {
        unsigned int bytes = stage ? sizeof b0 : sizeof af;
        const unsigned char *data = stage ? b0 : af;
        assert(!full_adf_aip_commands_enqueue(&s, data, bytes, 1));
        assert(s.command_count == 1 && s.cursor == bytes / 4 && s.sequence == stage);
        assert(s.af_applied == stage && !s.b0_applied && !s.response_pending && !s.stateflag);
        assert(!memcmp(s.buffer, data, bytes));
        for (unsigned int i = bytes; i < sizeof s.buffer; i++) assert(!s.buffer[i]);
        assert(p.calls == stage && p.writes == 3 * stage && p.readbacks == 3 * stage);
        assert(!full_adf_aip_commands_consume(&s, 1, stage ? 4 : 1, disable_bank, &p));
        assert(p.calls == stage + 1 && p.writes == 3 * (stage + 1) && p.readbacks == p.writes);
        assert(p.bank[0] == (0xa5a5a5ffu & ~0x80u) && !p.bank[1]);
        assert(p.bank[2] == (0x876547ffu & ~0x300u));
        empty_buffer(&s);
        assert(!s.fault && s.generation == 1 && s.sequence == stage + 1 && s.events == stage + 1);
        assert(s.response.opcode == (stage ? 0xb0u : 0xafu) && !s.response.status);
        assert(s.response.sequence == stage + 1 && s.response.generation == 1);
        assert(s.response.event_sequence == (stage ? 4u : 1u));
        assert(s.af_applied == 1 && s.b0_applied == stage && s.stateflag == stage);
        assert(s.af_event == 1 && s.b0_event == (stage ? 4u : 0u));
        assert(s.dispatch_event == (stage ? 4u : 1u));
    }
}

static void test_init(void)
{
    assert(full_adf_aip_commands_init(0) == -1021);
    assert(full_adf_aip_commands_enqueue(0, af, sizeof af, 1) == -1021);
    assert(full_adf_aip_commands_consume(0, 1, 1, disable_bank, 0) == -1021);
    for (unsigned int i = 0; i < sizeof(struct full_adf_aip_commands); i++) {
        struct full_adf_aip_commands s = {0}, before;
        ((unsigned char *)&s)[i] = 1;
        memcpy(&before, &s, sizeof before);
        assert(full_adf_aip_commands_init(&s) == -1021);
        assert(!memcmp(&s, &before, sizeof s));
    }
    for (unsigned int stage = 0; stage < 2; stage++) {
        struct full_adf_aip_commands s = {0}, before;
        queued(&s, stage);
        memcpy(&before, &s, sizeof before);
        assert(full_adf_aip_commands_init(&s) == -1021 && !memcmp(&s, &before, sizeof s));
    }
}

static void test_enqueue(void)
{
    for (unsigned int stage = 0; stage < 2; stage++) {
        struct full_adf_aip_commands s = {0};
        if (stage) after_af(&s);
        else assert(!full_adf_aip_commands_init(&s));
        unsigned int bytes = stage ? sizeof b0 : sizeof af;
        const unsigned char *data = stage ? b0 : af;
        reject_enqueue(&s, 0, bytes, 1);
        reject_enqueue(&s, stage ? af : b0, stage ? sizeof af : sizeof b0, 1);
        reject_enqueue(&s, data, bytes, 0);
        reject_enqueue(&s, data, bytes, 2);
        reject_enqueue(&s, data, bytes, ULLONG_MAX);
        unsigned int lengths[] = {0, 1, 7, 9, 15, 17, 0x514, UINT_MAX};
        for (unsigned int i = 0; i < sizeof lengths / sizeof lengths[0]; i++)
            reject_enqueue(&s, data, lengths[i], 1);
        for (unsigned int i = 0; i < bytes; i++) {
            unsigned char bad[16] = {0};
            memcpy(bad, data, bytes);
            bad[i] ^= 1;
            reject_enqueue(&s, bad, bytes, 1);
        }
        assert(!full_adf_aip_commands_enqueue(&s, data, bytes, 1));
        reject_enqueue(&s, data, bytes, 1);
        reject_enqueue(&s, stage ? af : b0, stage ? sizeof af : sizeof b0, 1);
    }
}

static void test_state(void)
{
    for (unsigned int stage = 0; stage < 2; stage++) {
        for (unsigned int kind = 0; kind < 27; kind++) {
            struct full_adf_aip_commands s = {0}, before;
            queued(&s, stage);
            switch (kind) {
            case 0: s.known = 0; break;
            case 1: s.interpreter_state = 8; break;
            case 2: s.command_count = 0; break;
            case 3: s.command_count = 0x4b; break;
            case 4: s.cursor = UINT_MAX; break;
            case 5: s.cursor = 0x144; break;
            case 6: s.sequence ^= 1; break;
            case 7: s.events ^= 1; break;
            case 8: s.af_applied ^= 1; break;
            case 9: s.b0_applied = 1; break;
            case 10: s.stateflag = 1; break;
            case 11: s.fault = 1; break;
            case 12: s.generation = 0; break;
            case 13: s.generation = 2; break;
            case 14: s.af_event ^= 1; break;
            case 15: s.b0_event = 4; break;
            case 16: s.dispatch_event ^= 1; break;
            case 17: s.response_pending = 1; break;
            case 18: s.response.opcode ^= 1; break;
            case 19: s.response.status = -1; break;
            case 20: s.response.sequence ^= 1; break;
            case 21: s.response.generation ^= 1; break;
            case 22: s.response.event_sequence ^= 1; break;
            case 23: s.busy = 1; break;
            case 24: s.command_count = UINT_MAX; break;
            case 25: s.cursor = 0; break;
            case 26: s.sequence = UINT_MAX; break;
            }
            memcpy(&before, &s, sizeof before);
            struct provider p = provider_for(&s);
            assert(full_adf_aip_commands_consume(&s, 1, stage ? 4 : 1, disable_bank, &p) == -1021);
            assert(!p.calls && s.fault == 1);
            before.fault = 1;
            assert(!memcmp(&s, &before, sizeof s));
        }
        for (unsigned int i = 0; i < 0x514; i++) {
            struct full_adf_aip_commands s = {0}, before;
            queued(&s, stage);
            s.buffer[i] ^= 1;
            memcpy(&before, &s, sizeof before);
            struct provider p = provider_for(&s);
            assert(full_adf_aip_commands_consume(&s, 1, stage ? 4 : 1, disable_bank, &p) == -1021);
            assert(!p.calls);
            retained(&s, &before);
        }
        struct full_adf_aip_commands s = {0};
        if (stage) after_af(&s);
        else assert(!full_adf_aip_commands_init(&s));
        s.buffer[sizeof s.buffer - 1] = 1;
        reject_enqueue(&s, stage ? b0 : af, stage ? sizeof b0 : sizeof af, 1);
    }
}

static void test_events(void)
{
    unsigned long long generations[] = {0, 2, ULLONG_MAX};
    for (unsigned int stage = 0; stage < 2; stage++) {
        for (unsigned int i = 0; i < 3; i++) {
            struct full_adf_aip_commands s = {0}, before;
            queued(&s, stage);
            memcpy(&before, &s, sizeof before);
            struct provider p = provider_for(&s);
            assert(full_adf_aip_commands_consume(&s, generations[i], stage ? 4 : 1, disable_bank, &p) == -1021);
            assert(!p.calls);
            retained(&s, &before);
        }
        unsigned long long events[] = {0, 1, 2, 3, 4, 5, ULLONG_MAX};
        for (unsigned int i = 0; i < sizeof events / sizeof events[0]; i++) {
            if (events[i] == (stage ? 4u : 1u)) continue;
            struct full_adf_aip_commands s = {0}, before;
            queued(&s, stage);
            memcpy(&before, &s, sizeof before);
            struct provider p = provider_for(&s);
            assert(full_adf_aip_commands_consume(&s, 1, events[i], disable_bank, &p) == -1021);
            assert(!p.calls);
            retained(&s, &before);
        }
    }
}

static void test_provider(void)
{
    for (unsigned int stage = 0; stage < 2; stage++) {
        for (unsigned int kind = 0; kind < 3; kind++) {
            struct full_adf_aip_commands s = {0}, before;
            queued(&s, stage);
            memcpy(&before, &s, sizeof before);
            struct provider p = provider_for(&s);
            p.mode = kind == 1 ? FAIL_BEFORE : BAD_READBACK;
            assert(full_adf_aip_commands_consume(&s, 1, stage ? 4 : 1,
                                                kind ? disable_bank : 0, &p) == -1021);
            assert(p.calls == (kind != 0) && !s.busy);
            assert(p.writes == (kind == 2 ? 3u : 0u));
            retained(&s, &before);
            assert(s.dispatch_event == (kind ? (stage ? 4u : 1u) : before.dispatch_event));
            unsigned int calls = p.calls;
            p.mode = GOOD;
            assert(full_adf_aip_commands_consume(&s, 1, stage ? 4 : 1, disable_bank, &p) == -1021);
            assert(p.calls == calls);
            reject_enqueue(&s, stage ? b0 : af, stage ? sizeof b0 : sizeof af, 1);
        }
    }
}

static void test_reentry(void)
{
    for (unsigned int stage = 0; stage < 2; stage++) {
        for (unsigned int mode = REENTER_CONSUME; mode <= REENTER_ENQUEUE; mode++) {
            struct full_adf_aip_commands s = {0}, before;
            queued(&s, stage);
            memcpy(&before, &s, sizeof before);
            struct provider p = provider_for(&s);
            p.mode = mode;
            assert(full_adf_aip_commands_consume(&s, 1, stage ? 4 : 1, disable_bank, &p) == -1021);
            assert(p.calls == 1 && !s.busy);
            retained(&s, &before);
        }
    }
}

static void test_mutation(void)
{
    for (unsigned int stage = 0; stage < 2; stage++) {
        for (unsigned int mode = CHANGE_GENERATION; mode <= CHANGE_EVENT; mode++) {
            struct full_adf_aip_commands s = {0}, before;
            queued(&s, stage);
            memcpy(&before, &s, sizeof before);
            struct provider p = provider_for(&s);
            p.mode = mode;
            assert(full_adf_aip_commands_consume(&s, 1, stage ? 4 : 1, disable_bank, &p) == -1021);
            assert(p.calls == 1 && s.fault == 1 && !s.busy && !s.b0_applied);
            assert(!memcmp(s.buffer, before.buffer, stage ? sizeof b0 : sizeof af));
            assert(s.command_count >= 1 && s.cursor && !s.b0_event);
            if (mode != CHANGE_COUNT) assert(s.command_count == before.command_count);
            if (mode != CHANGE_CURSOR) assert(s.cursor == before.cursor);
            if (mode != CHANGE_SEQUENCE) assert(s.sequence == before.sequence);
            if (mode != CHANGE_EVENTS) assert(s.events == before.events);
            if (mode != CHANGE_FLAG) assert(!s.stateflag);
            if (mode == CHANGE_RESPONSE) {
                assert(s.response_pending == 1 && s.response.opcode == 0xde && s.response.status == -33);
            } else {
                assert(s.response_pending == before.response_pending);
                assert(!memcmp(&s.response, &before.response, sizeof s.response));
            }
            if (mode == CHANGE_BUFFER) assert(s.buffer[sizeof s.buffer - 1] == 0xaa);
            if (mode == CHANGE_GENERATION) assert(s.generation == 2);
            struct full_adf_aip_commands failed;
            memcpy(&failed, &s, sizeof failed);
            assert(full_adf_aip_commands_init(&s) == -1021 && !memcmp(&s, &failed, sizeof s));
            assert(full_adf_aip_commands_consume(&s, 1, stage ? 4 : 1, disable_bank, &p) == -1021);
            assert(p.calls == 1 && !memcmp(&s, &failed, sizeof s));
        }
    }
}

static void test_reuse(void)
{
    for (unsigned int stage = 0; stage < 2; stage++) {
        struct full_adf_aip_commands s = {0}, before;
        after_af(&s);
        struct provider p = provider_for(&s);
        if (stage) {
            assert(!full_adf_aip_commands_enqueue(&s, b0, sizeof b0, 1));
            assert(!full_adf_aip_commands_consume(&s, 1, 4, disable_bank, &p));
        }
        reject_enqueue(&s, af, sizeof af, 1);
        if (stage) reject_enqueue(&s, b0, sizeof b0, 1);
        memcpy(&before, &s, sizeof before);
        unsigned int calls = p.calls;
        assert(full_adf_aip_commands_consume(&s, 1, stage ? 4 : 1, disable_bank, &p) == -1021);
        assert(p.calls == calls);
        retained(&s, &before);
        empty_buffer(&s);
    }
}

static const unsigned int input_fixture[33] = {
    0xad, 8, 0xab, 12, 0, 0xae, 12, 0, 0xb8, 12, 0, 3, 12, 0,
    2, 44, 0x08080100, 0x20011ff7, 0x14141414, 0x14090814, 0x15141414,
    0x15141416, 0x14141416, 0, 0x43211121, 0x11, 8, 0xb6, 12, 0, 0xb7, 12, 0
};
static const unsigned int input_start[10] = {0, 2, 5, 8, 11, 14, 25, 27, 30, 33};

static unsigned int get32(const unsigned char *p)
{
    return (unsigned int)p[0] | (unsigned int)p[1] << 8 |
           (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24;
}

static void put32(unsigned char *p, unsigned int value)
{
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (8 * i));
}

static unsigned int input_packet(unsigned int index, unsigned char raw[44])
{
    unsigned int words = input_start[index + 1] - input_start[index];
    for (unsigned int i = 0; i < words; i++) put32(raw + 4 * i, input_fixture[input_start[index] + i]);
    return 4 * words;
}

static void legacy_complete(struct full_adf_aip_commands *s)
{
    after_af(s);
    struct provider p = provider_for(s);
    assert(!full_adf_aip_commands_enqueue(s, b0, sizeof b0, 1));
    assert(!full_adf_aip_commands_consume(s, 1, 4, disable_bank, &p));
}

static void input_ready(struct full_adf_aip_commands *s, unsigned int count)
{
    legacy_complete(s);
    assert(!full_adf_aip_commands_input_begin(s, 2));
    for (unsigned int i = 0; i < count; i++) {
        unsigned char raw[44];
        unsigned int bytes = input_packet(i, raw);
        assert(!full_adf_aip_commands_input_enqueue(s, raw, bytes, 2));
    }
}

enum {
    INPUT_GOOD, INPUT_FAIL, INPUT_STATUS, INPUT_NO_STATUS, INPUT_BUFFER,
    INPUT_RING, INPUT_HISTORY, INPUT_SNAPSHOT, INPUT_IDENTITY, INPUT_BUSY,
    INPUT_FAULT, INPUT_BEGIN_REENTRY, INPUT_ENQUEUE_REENTRY, INPUT_FLUSH_REENTRY,
    INPUT_LEGACY_ENQUEUE, INPUT_LEGACY_CONSUME, INPUT_INIT_REENTRY
};
struct input_provider {
    struct full_adf_aip_commands *state;
    unsigned int calls, mode, at, order[9], bank[9], readbacks;
};

/* This test bank proves actual provider invocations, not original MMIO or 0336 consumption. */
static int input_bank(void *opaque, const unsigned char *command, unsigned int bytes,
                       unsigned int *status)
{
    struct input_provider *p = opaque;
    struct full_adf_aip_commands *s = p->state;
    unsigned int index = p->calls++;
    unsigned char expected[44];
    assert(index < 9 && bytes == input_packet(index, expected));
    assert(!memcmp(command, expected, bytes));
    assert(command == s->buffer + 8 + 4 * input_start[index]);
    assert(s->busy == 1 && !s->fault && s->command_count == 9 && s->cursor == 35);
    assert(s->input.dispatches == 0 && s->input.last_event == 4);
    assert(s->input.ring_read == 0 && s->input.ring_write == index);
    assert(s->sequence == 2 && s->dispatch_event == 4 && s->response.opcode == 0xb0);
    p->order[index] = get32(command);
    if (p->mode == INPUT_FAIL && index == p->at) return -9;
    unsigned int checksum = 0x6e624eb7;
    for (unsigned int i = 0; i < bytes; i++) checksum = (checksum ^ command[i]) * 16777619u;
    p->bank[index] = checksum;
    assert(p->bank[index] == checksum);
    p->readbacks++;
    if (p->mode == INPUT_NO_STATUS && index == p->at) return 0;
    *status = index == 1;
    if (index != p->at) return 0;
    switch (p->mode) {
    case INPUT_STATUS: *status ^= 1; break;
    case INPUT_BUFFER: s->buffer[sizeof s->buffer - 1] = 0x55; break;
    case INPUT_RING: s->input.ring[75][11] = 0x55; break;
    case INPUT_HISTORY: s->response.opcode ^= 1; break;
    case INPUT_SNAPSHOT: s->input.snapshot[55] = 0x55; break;
    case INPUT_IDENTITY: s->input.owner = 0; break;
    case INPUT_BUSY: s->busy = 0; break;
    case INPUT_FAULT: s->fault = 1; break;
    case INPUT_BEGIN_REENTRY: assert(full_adf_aip_commands_input_begin(s, 2) == -1021); break;
    case INPUT_ENQUEUE_REENTRY:
        assert(full_adf_aip_commands_input_enqueue(s, command, bytes, 2) == -1021); break;
    case INPUT_FLUSH_REENTRY:
        assert(full_adf_aip_commands_input_flush(s, 2, 5, input_bank, p) == -1021); break;
    case INPUT_LEGACY_ENQUEUE:
        assert(full_adf_aip_commands_enqueue(s, af, sizeof af, 1) == -1021); break;
    case INPUT_LEGACY_CONSUME:
        assert(full_adf_aip_commands_consume(s, 1, 4, disable_bank, 0) == -1021); break;
    case INPUT_INIT_REENTRY: assert(full_adf_aip_commands_init(s) == -1021); break;
    default: break;
    }
    return 0;
}

static struct input_provider input_provider_for(struct full_adf_aip_commands *s)
{
    struct input_provider p = {0};
    p.state = s;
    return p;
}

static void legacy_history(const struct full_adf_aip_commands *s)
{
    assert(s->known == 1 && !s->interpreter_state && s->generation == 1);
    assert(s->sequence == 2 && s->events == 2 && s->stateflag == 1);
    assert(s->af_applied == 1 && s->b0_applied == 1 && s->af_event == 1 && s->b0_event == 4);
    assert(s->dispatch_event == 4 && !s->response_pending);
    assert(s->response.opcode == 0xb0 && !s->response.status && s->response.sequence == 2);
    assert(s->response.generation == 1 && s->response.event_sequence == 4);
}

static void input_failure_retained(const struct full_adf_aip_commands *s,
                                    struct full_adf_aip_commands *before)
{
    before->fault = 1;
    assert(!memcmp(s, before, sizeof *s));
}

static void test_input_success(void)
{
    struct full_adf_aip_commands s = {0};
    input_ready(&s, 3);
    /* The parent's synchronous Glee callback can queue its private metadata here. */
    unsigned int private_completion_queued = 1;
    assert(s.command_count == 3 && s.input.enqueued == 3 && s.cursor == 10);
    assert(get32(s.buffer) == 0 && get32(s.buffer + 4) == 3);
    assert(!s.input.dispatches && s.input.last_event == 4 && !s.input.ring_write);
    for (unsigned int i = 3; i < 9; i++) {
        unsigned char raw[44];
        unsigned int bytes = input_packet(i, raw);
        assert(!full_adf_aip_commands_input_enqueue(&s, raw, bytes, 2));
    }
    assert(private_completion_queued && s.command_count == 9 && s.cursor == 35);
    assert(get32(s.buffer) == 0 && get32(s.buffer + 4) == 9);
    struct input_provider p = input_provider_for(&s);
    assert(!full_adf_aip_commands_input_flush(&s, 2, 5, input_bank, &p));
    assert(p.calls == 9 && p.readbacks == 9 && !s.fault);
    empty_buffer(&s);
    legacy_history(&s);
    assert(s.input.owner == &s && s.input.generation == 2 && s.input.enqueued == 9);
    assert(s.input.dispatches == 1 && s.input.last_event == 5);
    assert(s.input.ring_read == 9 && s.input.ring_write == 9);
    assert(s.input.snapshot_count == 9 && s.input.checked == 2 && s.input.local_cursor == 6);
    assert(s.input.task_status == FULL_ADF_AIP_TASK_ERROR && s.input.uninspected == 7);
    assert(s.input.failure_opcode == 0xab && s.input.failure_status == 1 && s.input.failure_task_status == FULL_ADF_AIP_TASK_ERROR);
    assert(!memcmp(s.input.snapshot, s.input.failure_snapshot, sizeof s.input.snapshot));
    assert(get32(s.input.snapshot) == 0 && get32(s.input.snapshot + 4) == 9);
    for (unsigned int i = 0; i < 9; i++) {
        unsigned int opcode = input_fixture[input_start[i]];
        assert(p.order[i] == opcode && p.bank[i]);
        assert(get32(s.input.ring[i]) == opcode && get32(s.input.ring[i] + 4) == 12);
        assert(get32(s.input.ring[i] + 8) == (i == 1));
        assert(!memcmp(s.input.snapshot + 8 + 12 * i, s.input.ring[i], 12));
    }
    assert(get32(s.input.snapshot + 116) == 0xff);
    unsigned char failure[FULL_ADF_AIP_SNAPSHOT_BYTES];
    memcpy(failure, s.input.failure_snapshot, sizeof failure);
    for (unsigned int event = 6; event <= 8; event++) {
        assert(!full_adf_aip_commands_input_flush(&s, 2, event, input_bank, &p));
        assert(!s.fault && p.calls == 9 && p.readbacks == 9);
        assert(s.input.dispatches == event - 4 && s.input.last_event == event);
        assert(s.input.ring_read == 9 && s.input.ring_write == 9);
        assert(!s.input.snapshot_count && !s.input.checked && !s.input.local_cursor);
        assert(!s.input.task_status && !s.input.uninspected);
        assert(!get32(s.input.snapshot) && !get32(s.input.snapshot + 4));
        assert(get32(s.input.snapshot + 8) == 0xff);
        assert(!memcmp(s.input.snapshot + 12, failure + 12, sizeof failure - 12));
        assert(!memcmp(s.input.failure_snapshot, failure, sizeof failure));
        for (unsigned int i = 2; i < 9; i++)
            assert(!memcmp(s.input.snapshot + 8 + 12 * i, s.input.ring[i], 12));
        assert(s.input.failure_opcode == 0xab && s.input.failure_status == 1 && s.input.failure_task_status == FULL_ADF_AIP_TASK_ERROR);
        empty_buffer(&s);
        legacy_history(&s);
    }
    struct full_adf_aip_commands before;
    memcpy(&before, &s, sizeof before);
    assert(full_adf_aip_commands_input_begin(&s, 2) == -1021);
    assert(!memcmp(&s, &before, sizeof s));
    assert(full_adf_aip_commands_input_flush(&s, 2, 9, input_bank, &p) == -1021);
    input_failure_retained(&s, &before);
    assert(p.calls == 9);
}

static void test_input_begin(void)
{
    assert(full_adf_aip_commands_input_begin(0, 2) == -1021);
    for (unsigned int stage = 0; stage < 5; stage++) {
        struct full_adf_aip_commands s = {0}, before;
        if (stage < 2) {
            assert(!full_adf_aip_commands_init(&s));
            if (stage) assert(!full_adf_aip_commands_enqueue(&s, af, sizeof af, 1));
        } else if (stage < 4) {
            after_af(&s);
            if (stage == 3) assert(!full_adf_aip_commands_enqueue(&s, b0, sizeof b0, 1));
        } else {
            legacy_complete(&s);
            s.buffer[sizeof s.buffer - 1] = 0x55;
        }
        memcpy(&before, &s, sizeof before);
        assert(full_adf_aip_commands_input_begin(&s, 2) == -1021);
        assert(!memcmp(&s, &before, sizeof s));
    }
    unsigned long long generations[] = {0, 1, 3, ULLONG_MAX};
    for (unsigned int i = 0; i < 4; i++) {
        struct full_adf_aip_commands s = {0}, before;
        legacy_complete(&s);
        memcpy(&before, &s, sizeof before);
        assert(full_adf_aip_commands_input_begin(&s, generations[i]) == -1021);
        assert(!memcmp(&s, &before, sizeof s));
    }
    struct full_adf_aip_commands s = {0}, before;
    input_ready(&s, 3);
    memcpy(&before, &s, sizeof before);
    assert(full_adf_aip_commands_init(&s) == -1021);
    assert(full_adf_aip_commands_input_begin(&s, 2) == -1021);
    assert(!memcmp(&s, &before, sizeof s));
}

static void input_reject_packet(struct full_adf_aip_commands *s, const unsigned char *raw,
                                 unsigned int bytes, unsigned long long generation)
{
    struct full_adf_aip_commands before;
    memcpy(&before, s, sizeof before);
    assert(full_adf_aip_commands_input_enqueue(s, raw, bytes, generation) == -1021);
    assert(!memcmp(s, &before, sizeof *s));
}

static void test_input_packets(void)
{
    for (unsigned int index = 0; index < 9; index++) {
        struct full_adf_aip_commands s = {0};
        input_ready(&s, index);
        unsigned char raw[44], other[44];
        unsigned int bytes = input_packet(index, raw);
        input_reject_packet(&s, 0, bytes, 2);
        input_reject_packet(&s, raw, bytes, 0);
        input_reject_packet(&s, raw, bytes, 1);
        input_reject_packet(&s, raw, bytes, 3);
        input_reject_packet(&s, raw, bytes, ULLONG_MAX);
        input_reject_packet(&s, other, input_packet((index + 1) % 9, other), 2);
        unsigned int sizes[] = {0, 1, 7, 9, 11, 13, 16, 43, 45, 0x514, UINT_MAX};
        for (unsigned int i = 0; i < sizeof sizes / sizeof sizes[0]; i++)
            input_reject_packet(&s, raw, sizes[i], 2);
        for (unsigned int i = 0; i < bytes; i++) {
            memcpy(other, raw, bytes);
            other[i] ^= 1;
            input_reject_packet(&s, other, bytes, 2);
        }
        assert(!full_adf_aip_commands_input_enqueue(&s, raw, bytes, 2));
        input_reject_packet(&s, raw, bytes, 2);
    }
}

static void test_input_events(void)
{
    assert(full_adf_aip_commands_input_flush(0, 2, 5, input_bank, 0) == -1021);
    assert(full_adf_aip_commands_input_enqueue(0, af, sizeof af, 2) == -1021);
    for (unsigned int count = 0; count < 9; count++) {
        struct full_adf_aip_commands s = {0}, before;
        input_ready(&s, count);
        memcpy(&before, &s, sizeof before);
        struct input_provider p = input_provider_for(&s);
        assert(full_adf_aip_commands_input_flush(&s, 2, 5, input_bank, &p) == -1021);
        assert(!p.calls);
        input_failure_retained(&s, &before);
    }
    for (unsigned int passes = 0; passes < 4; passes++) {
        for (unsigned int event = 0; event < 11; event++) {
            if (event == 5 + passes) continue;
            struct full_adf_aip_commands s = {0}, before;
            input_ready(&s, 9);
            struct input_provider p = input_provider_for(&s);
            for (unsigned int i = 0; i < passes; i++)
                assert(!full_adf_aip_commands_input_flush(&s, 2, 5 + i, input_bank, &p));
            memcpy(&before, &s, sizeof before);
            unsigned int calls = p.calls;
            assert(full_adf_aip_commands_input_flush(&s, 2, event, input_bank, &p) == -1021);
            assert(p.calls == calls);
            input_failure_retained(&s, &before);
        }
    }
    unsigned long long generations[] = {0, 1, 3, ULLONG_MAX};
    for (unsigned int i = 0; i < 4; i++) {
        struct full_adf_aip_commands s = {0}, before;
        input_ready(&s, 9);
        struct input_provider p = input_provider_for(&s);
        memcpy(&before, &s, sizeof before);
        assert(full_adf_aip_commands_input_flush(&s, generations[i], 5, input_bank, &p) == -1021);
        input_failure_retained(&s, &before);
        assert(!p.calls);
    }
}

static void test_input_provider(void)
{
    for (unsigned int index = 0; index < 9; index++) {
        for (unsigned int mode = INPUT_FAIL; mode <= INPUT_NO_STATUS; mode++) {
            struct full_adf_aip_commands s = {0};
            input_ready(&s, 9);
            unsigned char buffer[sizeof s.buffer];
            memcpy(buffer, s.buffer, sizeof buffer);
            struct input_provider p = input_provider_for(&s);
            p.mode = mode; p.at = index;
            assert(full_adf_aip_commands_input_flush(&s, 2, 5, input_bank, &p) == -1021);
            assert(p.calls == index + 1 && s.fault == 1 && !s.busy);
            assert(!memcmp(s.buffer, buffer, sizeof buffer) && s.command_count == 9 && s.cursor == 35);
            assert(!s.input.dispatches && s.input.last_event == 4 && !s.input.ring_read);
            assert(s.input.ring_write == index + (mode != INPUT_FAIL));
            if (mode != INPUT_FAIL)
                assert(get32(s.input.ring[index] + 8) == (mode == INPUT_STATUS ? ((index == 1) ^ 1u) : UINT_MAX));
            assert(!s.input.snapshot_count && !s.input.checked && !s.input.task_status && !s.input.failure_opcode);
            legacy_history(&s);
            struct full_adf_aip_commands before;
            memcpy(&before, &s, sizeof before);
            p.mode = INPUT_GOOD;
            assert(full_adf_aip_commands_input_flush(&s, 2, 5, input_bank, &p) == -1021);
            assert(full_adf_aip_commands_input_begin(&s, 2) == -1021);
            assert(full_adf_aip_commands_init(&s) == -1021);
            assert(!memcmp(&s, &before, sizeof s) && p.calls == index + 1);
        }
    }
    struct full_adf_aip_commands s = {0}, before;
    input_ready(&s, 9);
    memcpy(&before, &s, sizeof before);
    assert(full_adf_aip_commands_input_flush(&s, 2, 5, 0, 0) == -1021);
    input_failure_retained(&s, &before);
}

static void test_input_mutation(void)
{
    for (unsigned int mode = INPUT_BUFFER; mode <= INPUT_INIT_REENTRY; mode++) {
        struct full_adf_aip_commands s = {0};
        input_ready(&s, 9);
        struct input_provider p = input_provider_for(&s);
        p.mode = mode; p.at = 4;
        assert(full_adf_aip_commands_input_flush(&s, 2, 5, input_bank, &p) == -1021);
        assert(p.calls == 5 && s.fault == 1 && !s.busy);
        assert(s.command_count == 9 && s.cursor == 35 && s.input.enqueued == 9);
        assert(!s.input.dispatches && s.input.last_event == 4);
        assert(s.input.ring_read == 0 && s.input.ring_write == 4);
        if (mode == INPUT_BUFFER) assert(s.buffer[sizeof s.buffer - 1] == 0x55);
        if (mode == INPUT_RING) assert(s.input.ring[75][11] == 0x55);
        if (mode == INPUT_HISTORY) assert(s.response.opcode == (0xb0 ^ 1));
        if (mode == INPUT_SNAPSHOT) assert(s.input.snapshot[55] == 0x55);
        if (mode == INPUT_IDENTITY) assert(!s.input.owner);
    }
}

static void test_input_state(void)
{
    for (unsigned int pass = 0; pass < 2; pass++) {
        for (unsigned int kind = 0; kind < 33; kind++) {
            struct full_adf_aip_commands s = {0}, before;
            input_ready(&s, 9);
            struct input_provider p = input_provider_for(&s);
            if (pass) assert(!full_adf_aip_commands_input_flush(&s, 2, 5, input_bank, &p));
            switch (kind) {
            case 0: s.known = 0; break;
            case 1: s.interpreter_state = 1; break;
            case 2: s.sequence = 1; break;
            case 3: s.events = 1; break;
            case 4: s.stateflag = 0; break;
            case 5: s.af_applied = 0; break;
            case 6: s.b0_applied = 0; break;
            case 7: s.response_pending = 1; break;
            case 8: s.generation = 2; break;
            case 9: s.af_event = 2; break;
            case 10: s.b0_event = 5; break;
            case 11: s.dispatch_event = 5; break;
            case 12: s.response.status = 1; break;
            case 13: s.command_count++; break;
            case 14: s.cursor++; break;
            case 15: s.input.owner = 0; break;
            case 16: s.input.generation = 1; break;
            case 17: s.input.enqueued++; break;
            case 18: s.input.dispatches++; break;
            case 19: s.input.last_event++; break;
            case 20: s.input.ring_read++; break;
            case 21: s.input.ring_write++; break;
            case 22: s.input.ring[75][0] = 1; break;
            case 23: s.input.snapshot_count++; break;
            case 24: s.input.checked++; break;
            case 25: s.input.local_cursor++; break;
            case 26: s.input.task_status++; break;
            case 27: s.input.uninspected++; break;
            case 28: s.input.failure_opcode++; break;
            case 29: s.input.failure_status++; break;
            case 30: s.input.failure_task_status++; break;
            case 31: s.input.snapshot[sizeof s.input.snapshot - 1] ^= 1; break;
            case 32: s.input.failure_snapshot[sizeof s.input.failure_snapshot - 1] ^= 1; break;
            }
            memcpy(&before, &s, sizeof before);
            unsigned int calls = p.calls;
            assert(full_adf_aip_commands_input_flush(&s, 2, 5 + pass, input_bank, &p) == -1021);
            assert(p.calls == calls);
            input_failure_retained(&s, &before);
        }
        unsigned int storage_bytes = sizeof(((struct full_adf_aip_commands *)0)->buffer) +
            sizeof(((struct full_adf_aip_input_commands *)0)->ring) +
            2 * FULL_ADF_AIP_SNAPSHOT_BYTES;
        for (unsigned int i = 0; i < storage_bytes; i++) {
            /* Every byte of shared command storage and all three response arrays is guarded. */
            struct full_adf_aip_commands s = {0}, before;
            unsigned char *byte;
            if (i < sizeof s.buffer) byte = s.buffer + i;
            else {
                unsigned int offset = i - sizeof s.buffer;
                if (offset < sizeof s.input.ring) byte = (unsigned char *)s.input.ring + offset;
                else if (offset - sizeof s.input.ring < sizeof s.input.snapshot)
                    byte = s.input.snapshot + offset - sizeof s.input.ring;
                else byte = s.input.failure_snapshot + offset - sizeof s.input.ring - sizeof s.input.snapshot;
            }
            input_ready(&s, 9);
            struct input_provider p = input_provider_for(&s);
            if (pass) assert(!full_adf_aip_commands_input_flush(&s, 2, 5, input_bank, &p));
            *byte ^= 1;
            memcpy(&before, &s, sizeof before);
            unsigned int calls = p.calls;
            assert(full_adf_aip_commands_input_flush(&s, 2, 5 + pass, input_bank, &p) == -1021);
            assert(p.calls == calls);
            input_failure_retained(&s, &before);
        }
    }
}

static void test_input_clone_and_legacy(void)
{
    for (unsigned int pass = 0; pass < 2; pass++) {
        struct full_adf_aip_commands s = {0}, clone, before;
        input_ready(&s, 9);
        struct input_provider p = input_provider_for(&s);
        if (pass) assert(!full_adf_aip_commands_input_flush(&s, 2, 5, input_bank, &p));
        memcpy(&before, &s, sizeof before);
        memcpy(&clone, &s, sizeof clone);
        unsigned char raw[44];
        unsigned int bytes = input_packet(0, raw);
        assert(full_adf_aip_commands_input_begin(&clone, 2) == -1021);
        input_reject_packet(&clone, raw, bytes, 2);
        struct input_provider other = input_provider_for(&clone);
        assert(full_adf_aip_commands_input_flush(&clone, 2, 5 + pass, input_bank, &other) == -1021);
        assert(!other.calls && clone.fault == 1);
        assert(!memcmp(&s, &before, sizeof s));
        reject_enqueue(&s, af, sizeof af, 1);
        reject_enqueue(&s, b0, sizeof b0, 1);
        assert(full_adf_aip_commands_init(&s) == -1021 && !memcmp(&s, &before, sizeof s));
        struct provider old = provider_for(&s);
        assert(full_adf_aip_commands_consume(&s, 1, 4, disable_bank, &old) == -1021);
        assert(!old.calls);
        input_failure_retained(&s, &before);
    }
}

static int real_disable(void *context)
{
    return full_adf_aip_disable_apply(context, 0);
}

static void output_ready(struct full_adf_aip_commands *s, struct full_adf_aip_disable *bank)
{
    const struct full_adf_aip_disable_registers initial = {0xa5a5a5a4, 1, 2, 3, 4, 5, 6, 7};
    assert(!full_adf_aip_disable_init(bank, &initial, 1));
    assert(!full_adf_aip_commands_init(s));
    assert(!full_adf_aip_commands_enqueue(s, af, sizeof af, 1));
    assert(!full_adf_aip_commands_consume(s, 1, 1, real_disable, bank));
    assert(!full_adf_aip_commands_enqueue(s, b0, sizeof b0, 1));
    assert(!full_adf_aip_commands_consume(s, 1, 4, real_disable, bank));
    assert(bank->calls == 2 && bank->writes == 14 && bank->readbacks == 14);
    assert(!full_adf_aip_commands_input_begin(s, 2));
    for (unsigned int i = 0; i < 9; i++) {
        unsigned char raw[44];
        unsigned int bytes = input_packet(i, raw);
        assert(!full_adf_aip_commands_input_enqueue(s, raw, bytes, 2));
    }
    struct input_provider p = input_provider_for(s);
    for (unsigned int event = 5; event <= 8; event++)
        assert(!full_adf_aip_commands_input_flush(s, 2, event, input_bank, &p));
    assert(p.calls == 9 && s->input.dispatches == 4 && s->input.last_event == 8);
    assert(s->input.ring_read == 9 && s->input.ring_write == 9 && !s->input.task_status);
}

static void output_queued(struct full_adf_aip_commands *s, struct full_adf_aip_disable *bank)
{
    output_ready(s, bank);
    assert(!full_adf_aip_commands_output_begin(s, 3));
    assert(!full_adf_aip_commands_output_enqueue(s, b0, sizeof b0, 3));
}

static void output_history(const struct full_adf_aip_commands *s,
                             const struct full_adf_aip_commands *before)
{
    legacy_history(s);
    const struct full_adf_aip_input_commands *p = &s->input, *old = &before->input;
    assert(p->owner == s && p->generation == 2 && p->enqueued == 9);
    assert(p->dispatches == 4 && p->last_event == 8);
    assert(!p->snapshot_count && !p->checked && !p->local_cursor && !p->task_status && !p->uninspected);
    assert(p->failure_opcode == 0xab && p->failure_status == 1 && p->failure_task_status == 0x1004);
    assert(!memcmp(p->failure_snapshot, old->failure_snapshot, sizeof p->failure_snapshot));
    assert(!memcmp(p->ring, old->ring, 9 * 12));
    for (unsigned int i = 2; i < 9; i++)
        assert(!memcmp(p->failure_snapshot + 8 + 12 * i, p->ring[i], 12));
}

static void test_output_success(void)
{
    struct full_adf_aip_commands s = {0}, history;
    struct full_adf_aip_disable bank = {0};
    output_ready(&s, &bank);
    memcpy(&history, &s, sizeof history);
    unsigned char *physical_buffer = s.buffer, *physical_ring = s.input.ring[0], *physical_snapshot = s.input.snapshot;
    assert(!full_adf_aip_commands_output_begin(&s, 3));
    assert(s.output.owner == &s && s.output.generation == 3 && s.output.last_event == 8);
    assert(!s.command_count && s.cursor == 2);
    assert(!full_adf_aip_commands_output_enqueue(&s, b0, 16, 3));
    assert(s.command_count == 1 && s.cursor == 6 && s.output.enqueued == 1);
    assert(!get32(s.buffer) && get32(s.buffer + 4) == 1 && !memcmp(s.buffer + 8, b0, 16));
    assert(!s.output.dispatches && s.input.ring_read == 9 && s.input.ring_write == 9);
    assert(bank.calls == 2 && bank.readbacks == 14);
    assert(!full_adf_aip_commands_output_flush(&s, 3, 9, real_disable, &bank));
    assert(bank.calls == 3 && bank.writes == 21 && bank.readbacks == 21);
    assert(bank.registers.active0400 == 0xa5a5a5a4);
    assert(!bank.registers.route8828 && !bank.registers.route882c && !bank.registers.route8830);
    assert(!bank.registers.route8928 && !bank.registers.route892c && !bank.registers.route8930 && !bank.registers.controla000);
    assert(s.buffer == physical_buffer && s.input.ring[0] == physical_ring && s.input.snapshot == physical_snapshot);
    assert(s.input.ring_read == 10 && s.input.ring_write == 10);
    assert(get32(s.input.ring[9]) == 0xb0 && get32(s.input.ring[9] + 4) == 12 && !get32(s.input.ring[9] + 8));
    assert(!get32(s.input.snapshot) && get32(s.input.snapshot + 4) == 1);
    assert(!memcmp(s.input.snapshot + 8, s.input.ring[9], 12) && get32(s.input.snapshot + 20) == 0xff);
    assert(!memcmp(s.input.snapshot + 24, history.input.snapshot + 24, sizeof s.input.snapshot - 24));
    assert(s.output.enqueued == 1 && s.output.dispatches == 1 && s.output.last_event == 9);
    assert(s.output.snapshot_count == 1 && s.output.checked == 1 && s.output.local_cursor == 3);
    assert(!s.output.task_status && !s.output.uninspected && !s.fault);
    empty_buffer(&s);
    output_history(&s, &history);
    struct full_adf_aip_disable bank_before = bank;
    assert(full_adf_aip_disable_apply(&bank, 0) == -1021 && !memcmp(&bank, &bank_before, sizeof bank));
    struct full_adf_aip_commands before;
    memcpy(&before, &s, sizeof before);
    assert(full_adf_aip_commands_output_begin(&s, 3) == -1021);
    assert(full_adf_aip_commands_output_enqueue(&s, b0, 16, 3) == -1021);
    assert(!memcmp(&s, &before, sizeof s));
    assert(full_adf_aip_commands_output_flush(&s, 3, 9, real_disable, &bank) == -1021);
    input_failure_retained(&s, &before);
    assert(!memcmp(&bank, &bank_before, sizeof bank));
}

static void test_output_begin(void)
{
    assert(full_adf_aip_commands_output_begin(0, 3) == -1021);
    for (unsigned int stage = 0; stage < 8; stage++) {
        struct full_adf_aip_commands s = {0}, before;
        if (!stage) assert(!full_adf_aip_commands_init(&s));
        else if (stage == 1) after_af(&s);
        else if (stage == 2) legacy_complete(&s);
        else {
            input_ready(&s, stage == 3 ? 8 : 9);
            struct input_provider p = input_provider_for(&s);
            unsigned int passes = stage >= 4 ? stage - 4 : 0;
            for (unsigned int event = 5; event < 5 + passes; event++)
                assert(!full_adf_aip_commands_input_flush(&s, 2, event, input_bank, &p));
        }
        memcpy(&before, &s, sizeof before);
        assert(full_adf_aip_commands_output_begin(&s, 3) == -1021);
        assert(!memcmp(&s, &before, sizeof s));
    }
    const unsigned long long generations[] = {0, 1, 2, 4, ULLONG_MAX};
    struct full_adf_aip_commands s = {0}, before;
    struct full_adf_aip_disable bank = {0};
    output_ready(&s, &bank);
    memcpy(&before, &s, sizeof before);
    for (unsigned int i = 0; i < sizeof generations / sizeof generations[0]; i++) {
        assert(full_adf_aip_commands_output_begin(&s, generations[i]) == -1021);
        assert(!memcmp(&s, &before, sizeof s));
    }
    assert(!full_adf_aip_commands_output_begin(&s, 3));
    memcpy(&before, &s, sizeof before);
    assert(full_adf_aip_commands_output_begin(&s, 3) == -1021 && !memcmp(&s, &before, sizeof s));
}

static void output_reject_packet(struct full_adf_aip_commands *s, const unsigned char *raw,
                                  unsigned int bytes, unsigned long long generation)
{
    struct full_adf_aip_commands before;
    memcpy(&before, s, sizeof before);
    assert(full_adf_aip_commands_output_enqueue(s, raw, bytes, generation) == -1021);
    assert(!memcmp(s, &before, sizeof *s));
}

static void test_output_packets(void)
{
    assert(full_adf_aip_commands_output_enqueue(0, b0, 16, 3) == -1021);
    struct full_adf_aip_commands s = {0};
    struct full_adf_aip_disable bank = {0};
    output_ready(&s, &bank);
    output_reject_packet(&s, b0, 16, 3);
    assert(!full_adf_aip_commands_output_begin(&s, 3));
    output_reject_packet(&s, 0, 16, 3);
    output_reject_packet(&s, af, 8, 3);
    const unsigned int sizes[] = {0, 1, 8, 15, 17, 24, 0x514, UINT_MAX};
    for (unsigned int i = 0; i < sizeof sizes / sizeof sizes[0]; i++)
        output_reject_packet(&s, b0, sizes[i], 3);
    const unsigned long long generations[] = {0, 1, 2, 4, ULLONG_MAX};
    for (unsigned int i = 0; i < sizeof generations / sizeof generations[0]; i++)
        output_reject_packet(&s, b0, 16, generations[i]);
    for (unsigned int i = 0; i < 16; i++) {
        unsigned char raw[16];
        memcpy(raw, b0, 16); raw[i] ^= 1; /* Includes source0 -> source1. */
        output_reject_packet(&s, raw, 16, 3);
    }
    assert(!full_adf_aip_commands_output_enqueue(&s, b0, 16, 3));
    output_reject_packet(&s, b0, 16, 3);
}

static void test_output_events(void)
{
    assert(full_adf_aip_commands_output_flush(0, 3, 9, real_disable, 0) == -1021);
    for (unsigned int kind = 0; kind < 4; kind++) {
        unsigned int count = kind == 0 ? 5 : kind == 1 ? 12 : 1;
        for (unsigned int i = 0; i < count; i++) {
            if (kind == 1 && i == 9) continue;
            struct full_adf_aip_commands s = {0}, before;
            struct full_adf_aip_disable bank = {0};
            if (kind == 2) {
                output_ready(&s, &bank);
                assert(!full_adf_aip_commands_output_begin(&s, 3));
            } else output_queued(&s, &bank);
            const unsigned long long generations[] = {0, 1, 2, 4, ULLONG_MAX};
            unsigned long long gen = kind ? 3 : generations[i];
            unsigned long long event = kind == 1 ? (i == 11 ? ULLONG_MAX : i) : 9;
            memcpy(&before, &s, sizeof before);
            struct full_adf_aip_disable bank_before = bank;
            assert(full_adf_aip_commands_output_flush(&s, gen, event, kind == 3 ? 0 : real_disable, &bank) == -1021);
            input_failure_retained(&s, &before);
            assert(!memcmp(&bank, &bank_before, sizeof bank));
        }
    }
}

static void damage_output(struct full_adf_aip_commands *s, unsigned int kind)
{
    switch (kind) {
    case 0: s->known = 0; break;
    case 1: s->interpreter_state = 1; break;
    case 2: s->generation = 2; break;
    case 3: s->sequence++; break;
    case 4: s->events++; break;
    case 5: s->stateflag = 0; break;
    case 6: s->af_applied = 0; break;
    case 7: s->b0_applied = 0; break;
    case 8: s->af_event++; break;
    case 9: s->b0_event++; break;
    case 10: s->dispatch_event++; break;
    case 11: s->response_pending = 1; break;
    case 12: s->response.opcode++; break;
    case 13: s->response.status++; break;
    case 14: s->response.sequence++; break;
    case 15: s->response.generation++; break;
    case 16: s->response.event_sequence++; break;
    case 17: s->input.owner = 0; break;
    case 18: s->input.generation++; break;
    case 19: s->input.enqueued++; break;
    case 20: s->input.dispatches--; break;
    case 21: s->input.last_event++; break;
    case 22: s->input.ring_read++; break;
    case 23: s->input.ring_write++; break;
    case 24: s->input.snapshot_count++; break;
    case 25: s->input.checked++; break;
    case 26: s->input.local_cursor++; break;
    case 27: s->input.task_status++; break;
    case 28: s->input.uninspected++; break;
    case 29: s->input.failure_opcode++; break;
    case 30: s->input.failure_status++; break;
    case 31: s->input.failure_task_status++; break;
    case 32: s->command_count++; break;
    case 33: s->cursor++; break;
    case 34: s->fault = 1; break;
    case 35: s->busy = 1; break;
    case 36: s->output.owner = 0; break;
    case 37: s->output.generation++; break;
    case 38: s->output.last_event++; break;
    case 39: s->output.enqueued++; break;
    case 40: s->output.dispatches++; break;
    case 41: s->output.snapshot_count++; break;
    case 42: s->output.checked++; break;
    case 43: s->output.local_cursor++; break;
    case 44: s->output.task_status++; break;
    case 45: s->output.uninspected++; break;
    default: assert(0);
    }
}

static void test_output_state(void)
{
    for (unsigned int phase = 0; phase < 2; phase++) {
        for (unsigned int kind = 0; kind < (phase ? 46u : 35u); kind++) {
            struct full_adf_aip_commands s = {0}, before;
            struct full_adf_aip_disable bank = {0};
            if (phase) output_queued(&s, &bank);
            else output_ready(&s, &bank);
            damage_output(&s, kind);
            memcpy(&before, &s, sizeof before);
            if (phase) {
                assert(full_adf_aip_commands_output_flush(&s, 3, 9, real_disable, &bank) == -1021);
                input_failure_retained(&s, &before);
            } else {
                assert(full_adf_aip_commands_output_begin(&s, 3) == -1021);
                assert(!memcmp(&s, &before, sizeof s));
            }
            assert(bank.calls == 2 && bank.readbacks == 14);
        }
        const unsigned int storage_bytes = sizeof(((struct full_adf_aip_commands *)0)->buffer) +
            sizeof(((struct full_adf_aip_input_commands *)0)->ring) + 2 * FULL_ADF_AIP_SNAPSHOT_BYTES;
        for (unsigned int i = 0; i < storage_bytes; i++) {
            struct full_adf_aip_commands s = {0}, before;
            struct full_adf_aip_disable bank = {0};
            if (phase) output_queued(&s, &bank);
            else output_ready(&s, &bank);
            unsigned char *byte;
            if (i < sizeof s.buffer) byte = s.buffer + i;
            else {
                unsigned int offset = i - sizeof s.buffer;
                if (offset < sizeof s.input.ring) byte = (unsigned char *)s.input.ring + offset;
                else if (offset - sizeof s.input.ring < sizeof s.input.snapshot)
                    byte = s.input.snapshot + offset - sizeof s.input.ring;
                else byte = s.input.failure_snapshot + offset - sizeof s.input.ring - sizeof s.input.snapshot;
            }
            *byte ^= 1;
            memcpy(&before, &s, sizeof before);
            if (phase) {
                assert(full_adf_aip_commands_output_flush(&s, 3, 9, real_disable, &bank) == -1021);
                input_failure_retained(&s, &before);
            } else {
                assert(full_adf_aip_commands_output_begin(&s, 3) == -1021);
                assert(!memcmp(&s, &before, sizeof s));
            }
            assert(bank.calls == 2 && bank.writes == 14 && bank.readbacks == 14);
        }
    }
}

struct output_provider {
    struct full_adf_aip_commands *state;
    struct full_adf_aip_disable *bank;
    unsigned int mode, calls;
};

static int output_disable(void *context)
{
    struct output_provider *p = context;
    struct full_adf_aip_commands *s = p->state;
    p->calls++;
    assert(p->calls == 1 && s->busy == 1 && s->output.dispatches == 0);
    assert(s->command_count == 1 && s->cursor == 6 && s->input.ring_write == 9);
    if (!p->mode) return -7;
    assert(!real_disable(p->bank));
    switch (p->mode) {
    case 1: assert(full_adf_aip_commands_output_begin(s, 3) == -1021); break;
    case 2: assert(full_adf_aip_commands_output_enqueue(s, b0, 16, 3) == -1021); break;
    case 3: assert(full_adf_aip_commands_output_flush(s, 3, 9, output_disable, p) == -1021); break;
    case 4: assert(full_adf_aip_commands_input_begin(s, 2) == -1021); break;
    case 5: assert(full_adf_aip_commands_input_enqueue(s, af, 8, 2) == -1021); break;
    case 6: assert(full_adf_aip_commands_input_flush(s, 2, 9, 0, 0) == -1021); break;
    case 7: assert(full_adf_aip_commands_enqueue(s, b0, 16, 1) == -1021); break;
    case 8: assert(full_adf_aip_commands_consume(s, 1, 4, real_disable, p->bank) == -1021); break;
    case 9: assert(full_adf_aip_commands_init(s) == -1021); break;
    case 45: s->busy = 0; break;
    default: damage_output(s, p->mode - 10); break;
    }
    return 0;
}

static void test_output_provider(void)
{
    for (unsigned int mode = 0; mode < 56; mode++) {
        struct full_adf_aip_commands s = {0}, before;
        struct full_adf_aip_disable bank = {0};
        output_queued(&s, &bank);
        memcpy(&before, &s, sizeof before);
        struct output_provider p = {&s, &bank, mode, 0};
        assert(full_adf_aip_commands_output_flush(&s, 3, 9, output_disable, &p) == -1021);
        assert(p.calls == 1 && s.fault == 1 && !s.busy);
        assert(bank.calls == (mode ? 3u : 2u) && bank.readbacks == 7 * bank.calls);
        if (mode < 10) input_failure_retained(&s, &before);
        assert(!memcmp(s.buffer, before.buffer, sizeof s.buffer));
        assert(!memcmp(s.input.ring, before.input.ring, sizeof s.input.ring));
        assert(!memcmp(s.input.failure_snapshot, before.input.failure_snapshot, sizeof s.input.failure_snapshot));
        unsigned int calls = bank.calls;
        assert(full_adf_aip_commands_output_flush(&s, 3, 9, real_disable, &bank) == -1021);
        assert(bank.calls == calls);
    }
    struct full_adf_aip_commands s = {0}, before;
    struct full_adf_aip_disable bank = {0};
    output_queued(&s, &bank);
    bank.registers.active0400 |= 1;
    memcpy(&before, &s, sizeof before);
    struct full_adf_aip_disable bank_before = bank;
    assert(full_adf_aip_commands_output_flush(&s, 3, 9, real_disable, &bank) == -1021);
    input_failure_retained(&s, &before);
    assert(!memcmp(&bank, &bank_before, sizeof bank));
}

static void test_output_clone_and_legacy(void)
{
    for (unsigned int phase = 0; phase < 3; phase++) {
        struct full_adf_aip_commands s = {0}, clone, before;
        struct full_adf_aip_disable bank = {0};
        output_ready(&s, &bank);
        assert(!full_adf_aip_commands_output_begin(&s, 3));
        if (phase) assert(!full_adf_aip_commands_output_enqueue(&s, b0, 16, 3));
        if (phase == 2) assert(!full_adf_aip_commands_output_flush(&s, 3, 9, real_disable, &bank));
        memcpy(&before, &s, sizeof before);
        memcpy(&clone, &s, sizeof clone);
        assert(full_adf_aip_commands_output_begin(&clone, 3) == -1021);
        output_reject_packet(&clone, b0, 16, 3);
        struct full_adf_aip_disable bank_before = bank;
        assert(full_adf_aip_commands_output_flush(&clone, 3, 9, real_disable, &bank) == -1021);
        assert(!memcmp(&bank, &bank_before, sizeof bank));
        assert(!memcmp(&s, &before, sizeof s));
        assert(full_adf_aip_commands_init(&s) == -1021);
        reject_enqueue(&s, af, 8, 1);
        assert(full_adf_aip_commands_consume(&s, 1, 4, real_disable, &bank) == -1021);
        assert(full_adf_aip_commands_input_begin(&s, 2) == -1021);
        input_reject_packet(&s, af, 8, 2);
        assert(full_adf_aip_commands_input_flush(&s, 2, 9, 0, 0) == -1021);
        assert(!memcmp(&s, &before, sizeof s) && !memcmp(&bank, &bank_before, sizeof bank));
    }
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "success")) test_success();
    else if (!strcmp(argv[1], "init")) test_init();
    else if (!strcmp(argv[1], "enqueue")) test_enqueue();
    else if (!strcmp(argv[1], "state")) test_state();
    else if (!strcmp(argv[1], "events")) test_events();
    else if (!strcmp(argv[1], "provider")) test_provider();
    else if (!strcmp(argv[1], "reentry")) test_reentry();
    else if (!strcmp(argv[1], "mutation")) test_mutation();
    else if (!strcmp(argv[1], "reuse")) test_reuse();
    else if (!strcmp(argv[1], "input-success")) test_input_success();
    else if (!strcmp(argv[1], "input-begin")) test_input_begin();
    else if (!strcmp(argv[1], "input-packets")) test_input_packets();
    else if (!strcmp(argv[1], "input-events")) test_input_events();
    else if (!strcmp(argv[1], "input-provider")) test_input_provider();
    else if (!strcmp(argv[1], "input-mutation")) test_input_mutation();
    else if (!strcmp(argv[1], "input-state")) test_input_state();
    else if (!strcmp(argv[1], "input-clone-legacy")) test_input_clone_and_legacy();
    else if (!strcmp(argv[1], "output-success")) test_output_success();
    else if (!strcmp(argv[1], "output-begin")) test_output_begin();
    else if (!strcmp(argv[1], "output-packets")) test_output_packets();
    else if (!strcmp(argv[1], "output-events")) test_output_events();
    else if (!strcmp(argv[1], "output-state")) test_output_state();
    else if (!strcmp(argv[1], "output-provider")) test_output_provider();
    else if (!strcmp(argv[1], "output-clone-legacy")) test_output_clone_and_legacy();
    else assert(0);
    puts("ADF_AIP_OWNED_AF_B0_CONSUMPTION_PASS");
    return 0;
}
