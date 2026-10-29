/* SPDX-License-Identifier: MIT */
#include "adf-aip-commands.h"
#include <string.h>

static const unsigned char af[8] = {0xaf, 0, 0, 0, 8, 0, 0, 0};
static const unsigned char b0[16] = {0xb0, 0, 0, 0, 16, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};

static int zero_bytes(const void *p, unsigned long bytes)
{
    const unsigned char *data = p;
    for (unsigned long i = 0; i < bytes; i++) if (data[i]) return 0;
    return 1;
}

static int response_matches(const struct full_adf_aip_command_response *r,
                            unsigned int opcode, unsigned int sequence,
                            unsigned long long generation, unsigned long long event)
{
    return r->opcode == opcode && r->status == 0 && r->sequence == sequence &&
           r->generation == generation && r->event_sequence == event;
}

static int valid_history(const struct full_adf_aip_commands *s)
{
    if (s->known != 1 || s->interpreter_state || s->busy || s->fault ||
        s->sequence > 2 || s->events != s->sequence ||
        s->response_pending || s->af_applied != (s->sequence >= 1) ||
        s->b0_applied != (s->sequence == 2) || s->stateflag != (s->sequence == 2) ||
        s->generation != ((s->sequence || s->command_count) ? 1u : 0u) ||
        s->af_event != (s->sequence >= 1 ? 1u : 0u) ||
        s->b0_event != (s->sequence == 2 ? 4u : 0u) ||
        s->dispatch_event != (s->sequence == 2 ? 4u : s->sequence)) return 0;
    if (!response_matches(&s->response, s->sequence == 2 ? 0xb0u : s->sequence ? 0xafu : 0u,
                          s->sequence, s->sequence ? 1u : 0u, s->dispatch_event)) return 0;
    return 1;
}

static int valid_state(const struct full_adf_aip_commands *s)
{
    if (!valid_history(s) || s->command_count > 1 ||
        !zero_bytes(&s->input, sizeof s->input) ||
        !zero_bytes(&s->output, sizeof s->output)) return 0;
    if (!s->command_count) return !s->cursor && zero_bytes(s->buffer, sizeof s->buffer);
    if (s->sequence == 2) return 0;
    unsigned int bytes = s->sequence ? sizeof b0 : sizeof af;
    return s->cursor == bytes / 4 && s->cursor < 0x144 &&
           !memcmp(s->buffer, s->sequence ? b0 : af, bytes) &&
           zero_bytes(s->buffer + bytes, sizeof s->buffer - bytes);
}

static int fault(struct full_adf_aip_commands *s)
{
    if (s) s->fault = 1;
    return -1021;
}

int full_adf_aip_commands_init(struct full_adf_aip_commands *s)
{
    if (s && s->busy && s->input.owner) return fault(s);
    if (!s || !zero_bytes(s, sizeof *s)) return -1021;
    s->known = 1;
    return 0;
}

int full_adf_aip_commands_enqueue(struct full_adf_aip_commands *s,
                                  const unsigned char *command, unsigned int bytes,
                                  unsigned long long generation)
{
    /* shortcut: single owned AF then source0 B0, cold S0/generation1 only; extend after lifecycle proof. */
    if (s && s->busy) return fault(s);
    if (!s || !command || generation != 1 || !valid_state(s) ||
        s->command_count || s->sequence == 2) return -1021;
    unsigned int expected = s->sequence ? sizeof b0 : sizeof af;
    if (bytes != expected || memcmp(command, s->sequence ? b0 : af, expected)) return -1021;
    memcpy(s->buffer, command, expected);
    s->command_count = 1;
    s->cursor = expected / 4;
    s->generation = generation;
    return 0;
}

static int take_response(struct full_adf_aip_commands *s, unsigned int opcode,
                         unsigned int sequence, unsigned long long generation,
                         unsigned long long event)
{
    if (s->response_pending != 1 ||
        !response_matches(&s->response, opcode, sequence, generation, event)) return -1021;
    s->response_pending = 0;
    return 0;
}

int full_adf_aip_commands_consume(struct full_adf_aip_commands *s,
                                  unsigned long long generation,
                                  unsigned long long event_sequence,
                                  int (*disable)(void *), void *context)
{
    if (s && !s->busy && !zero_bytes(&s->output, sizeof s->output)) return -1021;
    if (!s || !valid_state(s) || s->command_count != 1 || generation != 1 ||
        s->generation != generation || !disable ||
        event_sequence != (s->sequence ? 4u : 1u)) return fault(s);
    unsigned long long owned_generation = s->generation;
    unsigned int opcode = s->buffer[0];
    s->busy = 1;
    s->dispatch_event = event_sequence;
    struct full_adf_aip_commands before;
    memcpy(&before, s, sizeof before);
    int rc = disable(context); /* b6592c/b65948 -> b68094 must finish before responding. */
    if (rc || s->generation != owned_generation || memcmp(s, &before, sizeof before)) {
        s->fault = 1;
        s->busy = 0;
        return -1021;
    }
    if (opcode == 0xb0) s->stateflag = 1;
    s->response.opcode = opcode;
    s->response.status = 0;
    s->response.sequence = s->sequence + 1;
    s->response.generation = owned_generation;
    s->response.event_sequence = event_sequence;
    s->response_pending = 1;
    if (take_response(s, opcode, s->sequence + 1, owned_generation, event_sequence)) {
        s->fault = 1;
        s->busy = 0;
        return -1021;
    }
    memset(s->buffer, 0, sizeof s->buffer);
    s->command_count = 0;
    s->cursor = 0;
    s->sequence++;
    s->events++;
    if (opcode == 0xaf) {
        s->af_event = event_sequence;
        s->af_applied = 1;
    } else {
        s->b0_event = event_sequence;
        s->b0_applied = 1;
    }
    s->busy = 0;
    return 0;
}

/* 62de8: selector2 input batch, total 132 bytes; no general opcode admission. */
static const unsigned int input_words[33] = {
    0xad, 8, 0xab, 12, 0, 0xae, 12, 0, 0xb8, 12, 0, 3, 12, 0,
    2, 44, 0x08080100, 0x20011ff7, 0x14141414, 0x14090814, 0x15141414,
    0x15141416, 0x14141416, 0, 0x43211121, 0x11, 8, 0xb6, 12, 0, 0xb7, 12, 0
};
static const unsigned int input_offsets[10] = {0, 2, 5, 8, 11, 14, 25, 27, 30, 33};

static unsigned int read32(const unsigned char *p)
{
    return (unsigned int)p[0] | (unsigned int)p[1] << 8 |
           (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24;
}

static void write32(unsigned char *p, unsigned int value)
{
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (8 * i));
}

static int words_match(const unsigned char *p, unsigned int start, unsigned int end)
{
    for (unsigned int i = start; i < end; i++)
        if (read32(p + 4 * (i - start)) != input_words[i]) return 0;
    return 1;
}

/* Integrity guard only: old response statuses are never dispatched or task-inspected again. */
static int valid_input_failure(const struct full_adf_aip_input_commands *p)
{
    if (p->failure_opcode != 0xab || p->failure_status != 1 ||
        p->failure_task_status != FULL_ADF_AIP_TASK_ERROR ||
        read32(p->failure_snapshot) || read32(p->failure_snapshot + 4) != 9 ||
        read32(p->failure_snapshot + 116) != 0xff ||
        !zero_bytes(p->failure_snapshot + 120, sizeof p->failure_snapshot - 120)) return 0;
    for (unsigned int i = 0; i < 9; i++)
        if (read32(p->ring[i]) != input_words[input_offsets[i]] ||
            read32(p->ring[i] + 4) != 12 || read32(p->ring[i] + 8) != (i == 1) ||
            memcmp(p->failure_snapshot + 8 + 12 * i, p->ring[i], 12)) return 0;
    return 1;
}

static int valid_empty_snapshot(const struct full_adf_aip_input_commands *p)
{
    return !read32(p->snapshot) && !read32(p->snapshot + 4) &&
           read32(p->snapshot + 8) == 0xff &&
           !memcmp(p->snapshot + 12, p->failure_snapshot + 12, sizeof p->snapshot - 12);
}

static int valid_input(const struct full_adf_aip_commands *s)
{
    const struct full_adf_aip_input_commands *p = &s->input;
    /* command_count belongs to the shared buffer, not the legacy history. */
    if (!valid_history(s) || s->sequence != 2 ||
        !zero_bytes(&s->output, sizeof s->output) ||
        p->owner != s || p->generation != 2 || p->dispatches > 4 ||
        p->last_event != 4u + p->dispatches || p->enqueued > 9) return 0;
    if (!p->dispatches) {
        unsigned int words = input_offsets[p->enqueued];
        return s->command_count == p->enqueued && s->cursor == 2 + words &&
               !read32(s->buffer) && read32(s->buffer + 4) == p->enqueued &&
               words_match(s->buffer + 8, 0, words) &&
               zero_bytes(s->buffer + 8 + 4 * words, sizeof s->buffer - 8 - 4 * words) &&
               !p->ring_read && !p->ring_write && zero_bytes(p->ring, sizeof p->ring) &&
               zero_bytes(p->snapshot, sizeof p->snapshot) &&
               zero_bytes(p->failure_snapshot, sizeof p->failure_snapshot) &&
               !p->snapshot_count && !p->checked && !p->local_cursor && !p->task_status &&
               !p->uninspected && !p->failure_opcode && !p->failure_status && !p->failure_task_status;
    }
    if (p->enqueued != 9 || s->command_count || s->cursor ||
        !zero_bytes(s->buffer, sizeof s->buffer) || p->ring_read != 9 || p->ring_write != 9 ||
        !valid_input_failure(p)) return 0;
    for (unsigned int i = 9; i < FULL_ADF_AIP_RESPONSE_SLOTS; i++)
        if (!zero_bytes(p->ring[i], 12)) return 0;
    if (p->dispatches == 1)
        return p->snapshot_count == 9 && p->checked == 2 && p->local_cursor == 6 &&
               p->task_status == FULL_ADF_AIP_TASK_ERROR && p->uninspected == 7 &&
               !memcmp(p->snapshot, p->failure_snapshot, sizeof p->snapshot);
    return !p->snapshot_count && !p->checked && !p->local_cursor && !p->task_status &&
           !p->uninspected && valid_empty_snapshot(p);
}

int full_adf_aip_commands_input_begin(struct full_adf_aip_commands *s,
                                      unsigned long long generation)
{
    if (s && s->busy) return fault(s);
    if (!s || generation != 2 || !valid_state(s) || s->sequence != 2) return -1021;
    s->input.owner = s;
    s->input.generation = generation;
    s->input.last_event = 4;
    s->cursor = 2; /* The buffer was proved empty; its two header words are policy0/count0. */
    return 0;
}

int full_adf_aip_commands_input_enqueue(struct full_adf_aip_commands *s,
                                        const unsigned char *command, unsigned int bytes,
                                        unsigned long long generation)
{
    if (s && s->busy) return fault(s);
    if (!s || !command || generation != 2 || !valid_input(s) ||
        s->input.dispatches || s->input.enqueued == 9) return -1021;
    unsigned int index = s->input.enqueued;
    unsigned int first = input_offsets[index], end = input_offsets[index + 1];
    if (bytes != 4 * (end - first) || !words_match(command, first, end)) return -1021;
    memcpy(s->buffer + 4 * s->cursor, command, bytes);
    s->cursor += bytes / 4;
    s->command_count = ++s->input.enqueued;
    write32(s->buffer + 4, s->command_count);
    return 0;
}

static void input_snapshot(struct full_adf_aip_commands *s)
{
    struct full_adf_aip_input_commands *p = &s->input;
    unsigned int saved_write = p->ring_write, cursor = p->ring_read, count = 0;
    write32(p->snapshot, 0); /* Explicit owned virtual batch header policy. */
    while (cursor != saved_write) {
        memcpy(p->snapshot + 8 + 12 * count++, p->ring[cursor], 12);
        cursor = (cursor + 1) % FULL_ADF_AIP_RESPONSE_SLOTS;
    }
    write32(p->snapshot + 4, count);
    write32(p->snapshot + 8 + 12 * count, 0xff);
    p->ring_read = saved_write; /* b6aad6 drains the whole ring before local inspection. */
    p->snapshot_count = count;
    p->checked = p->local_cursor = p->task_status = p->uninspected = 0;
    for (unsigned int i = 0; i < count; i++) {
        const unsigned char *response = p->snapshot + 8 + 12 * i;
        p->checked++;
        p->local_cursor += 3;
        if (read32(response + 8)) {
            p->task_status = FULL_ADF_AIP_TASK_ERROR;
            p->uninspected = count - p->checked;
            memcpy(p->failure_snapshot, p->snapshot, sizeof p->snapshot);
            p->failure_opcode = read32(response);
            p->failure_status = read32(response + 8);
            p->failure_task_status = p->task_status;
            break;
        }
    }
}

int full_adf_aip_commands_input_flush(struct full_adf_aip_commands *s,
                                      unsigned long long generation,
                                      unsigned long long global_event,
                                      int (*provider)(void *, const unsigned char *,
                                                      unsigned int, unsigned int *),
                                      void *context)
{
    if (s && !s->busy && !zero_bytes(&s->output, sizeof s->output)) return -1021;
    if (!s || generation != 2 || !valid_input(s) || s->input.enqueued != 9 ||
        s->input.dispatches == 4 || global_event != s->input.last_event + 1 || !provider)
        return fault(s);
    struct full_adf_aip_input_commands *p = &s->input;
    s->busy = 1;
    for (unsigned int i = 0; i < s->command_count; i++) {
        unsigned int first = input_offsets[i], bytes = 4 * (input_offsets[i + 1] - first);
        struct full_adf_aip_commands before;
        memcpy(&before, s, sizeof before);
        unsigned int status = ~0u;
        int rc = provider(context, s->buffer + 8 + 4 * first, bytes, &status);
        if (rc || memcmp(s, &before, sizeof before)) goto failed;
        unsigned int next = (p->ring_write + 1) % FULL_ADF_AIP_RESPONSE_SLOTS;
        if (next == p->ring_read) goto failed; /* 76 slots retain one empty: capacity75. */
        write32(p->ring[p->ring_write], input_words[first]);
        write32(p->ring[p->ring_write] + 4, 12);
        write32(p->ring[p->ring_write] + 8, status);
        p->ring_write = next;
        if (status != (i == 1)) goto failed;
    }
    input_snapshot(s);
    memset(s->buffer, 0, sizeof s->buffer);
    s->command_count = s->cursor = 0; /* b6f864 clears only after this dispatch finishes. */
    p->dispatches++;
    p->last_event = global_event;
    s->busy = 0;
    return 0;
failed:
    s->fault = 1;
    s->busy = 0;
    return -1021;
}

static int valid_output(const struct full_adf_aip_commands *s)
{
    const struct full_adf_aip_input_commands *p = &s->input;
    const struct full_adf_aip_output_commands *q = &s->output;
    if (!valid_history(s) || s->sequence != 2 ||
        p->owner != s || p->generation != 2 || p->enqueued != 9 ||
        p->dispatches != 4 || p->last_event != 8 || p->snapshot_count || p->checked ||
        p->local_cursor || p->task_status || p->uninspected || !valid_input_failure(p) ||
        q->owner != s || q->generation != 3 || q->enqueued > 1 || q->dispatches > 1 ||
        q->last_event != 8u + q->dispatches || q->task_status || q->uninspected ||
        p->ring_read != 9u + q->dispatches || p->ring_write != p->ring_read) return 0;
    for (unsigned int i = 9u + q->dispatches; i < FULL_ADF_AIP_RESPONSE_SLOTS; i++)
        if (!zero_bytes(p->ring[i], 12)) return 0;
    if (!q->dispatches) {
        unsigned int bytes = q->enqueued ? sizeof b0 : 0u;
        return !q->snapshot_count && !q->checked && !q->local_cursor &&
               valid_empty_snapshot(p) && s->command_count == q->enqueued &&
               s->cursor == 2 + bytes / 4 && !read32(s->buffer) &&
               read32(s->buffer + 4) == q->enqueued &&
               !memcmp(s->buffer + 8, b0, bytes) &&
               zero_bytes(s->buffer + 8 + bytes, sizeof s->buffer - 8 - bytes);
    }
    return q->enqueued == 1 && q->snapshot_count == 1 && q->checked == 1 &&
           q->local_cursor == 3 && !s->command_count && !s->cursor &&
           zero_bytes(s->buffer, sizeof s->buffer) &&
           read32(p->ring[9]) == 0xb0 && read32(p->ring[9] + 4) == 12 &&
           !read32(p->ring[9] + 8) && !read32(p->snapshot) &&
           read32(p->snapshot + 4) == 1 && !memcmp(p->snapshot + 8, p->ring[9], 12) &&
           read32(p->snapshot + 20) == 0xff &&
           !memcmp(p->snapshot + 24, p->failure_snapshot + 24, sizeof p->snapshot - 24);
}

int full_adf_aip_commands_output_begin(struct full_adf_aip_commands *s,
                                       unsigned long long generation)
{
    if (s && s->busy) return fault(s);
    if (!s || generation != 3 || !valid_input(s) || s->input.dispatches != 4) return -1021;
    s->output.owner = s;
    s->output.generation = generation;
    s->output.last_event = 8;
    s->cursor = 2;
    return 0;
}

int full_adf_aip_commands_output_enqueue(struct full_adf_aip_commands *s,
                                         const unsigned char *command, unsigned int bytes,
                                         unsigned long long generation)
{
    if (s && s->busy) return fault(s);
    if (!s || !command || generation != 3 || !valid_output(s) ||
        s->output.enqueued || bytes != sizeof b0 || memcmp(command, b0, sizeof b0)) return -1021;
    memcpy(s->buffer + 8, command, sizeof b0);
    write32(s->buffer + 4, 1);
    s->command_count = s->output.enqueued = 1;
    s->cursor = 6; /* Whole batch is policy0/count1 plus the 16-byte command. */
    return 0;
}

int full_adf_aip_commands_output_flush(struct full_adf_aip_commands *s,
                                       unsigned long long generation,
                                       unsigned long long global_event,
                                       int (*disable)(void *), void *context)
{
    if (!s || generation != 3 || global_event != 9 || !valid_output(s) ||
        s->output.enqueued != 1 || s->output.dispatches || !disable) return fault(s);
    s->busy = 1;
    struct full_adf_aip_commands before;
    memcpy(&before, s, sizeof before);
    int rc = disable(context); /* 51ffb4 -> b6fb60 -> S0 B0 -> the same seven disable leaves. */
    if (rc || memcmp(s, &before, sizeof before)) {
        s->fault = 1;
        s->busy = 0;
        return -1021;
    }
    struct full_adf_aip_input_commands *p = &s->input;
    struct full_adf_aip_output_commands *q = &s->output;
    write32(p->ring[9], 0xb0);
    write32(p->ring[9] + 4, 12);
    write32(p->ring[9] + 8, 0);
    p->ring_write = 10;
    write32(p->snapshot, 0);
    write32(p->snapshot + 4, 1);
    memcpy(p->snapshot + 8, p->ring[9], 12);
    write32(p->snapshot + 20, 0xff);
    p->ring_read = p->ring_write; /* Whole current ring contains only this new response. */
    q->snapshot_count = q->checked = q->dispatches = 1;
    q->local_cursor = 3;
    q->last_event = global_event;
    memset(s->buffer, 0, sizeof s->buffer);
    s->command_count = s->cursor = 0;
    s->busy = 0;
    return 0;
}
