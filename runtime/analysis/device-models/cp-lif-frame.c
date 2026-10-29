/* SPDX-License-Identifier: MIT */
#include "cp-lif-frame.h"
#include <errno.h>
#include <string.h>

/* 1107034/38 -> 1206dfd/1206e7f; 80 00 terminates each schema. */
static const unsigned char schema5[] = {
    8, 1, 8, 3, 10, 28, 2, 6, 1, 2, 8, 6, 6, 6,
    1, 6, 3, 3, 4, 4, 4, 8, 36, 40, 8, 4, 6, 3
};
static const unsigned char schema6[] = {2, 11, 9, 4, 6, 7, 45, 4, 8, 8, 24};

static int span_valid(const void *p, size_t n)
{
    return p != NULL && n <= UINTPTR_MAX - (uintptr_t)p;
}

static int overlaps(const void *a, size_t an, const void *b, size_t bn)
{
    return (uintptr_t)a < (uintptr_t)b + bn &&
           (uintptr_t)b < (uintptr_t)a + an;
}

static uint16_t le16(const unsigned char *p)
{
    return (uint16_t)((uint16_t)p[0] | (uint16_t)((uint16_t)p[1] << 8));
}

static int context_valid(const struct cp_lif_frame_context *c, unsigned type)
{
    size_t i;
    if (c->origin == CP_LIF_ORIGIN_NONE)
        return -ENODATA;
    if (c->origin != CP_LIF_ORIGIN_VIRTUAL_SOURCE &&
        c->origin != CP_LIF_ORIGIN_HOST_TEST)
        return -EXDEV;
    if (c->quiescent > 1 || c->type1_source_known > 1)
        return -EINVAL;
    if (!c->quiescent || c->sequence_before != c->sequence_after ||
        (c->sequence_before & UINT64_C(1)))
        return -EAGAIN;
    for (i = 0; i < CP_LIF_BITMAP_BYTES; ++i)
        if (c->bitmap_known[i] > 1)
            return -EINVAL;
    if (c->bitmap_event == CP_LIF_BITMAP_UNKNOWN)
        return -ENODATA;
    if (c->bitmap_event != CP_LIF_BITMAP_A923D0_SNAPSHOT)
        return -ENOTSUP;
    for (i = 0; i < CP_LIF_BITMAP_BYTES; ++i)
        if (!c->bitmap_known[i])
            return -ENODATA;
    if (type == 1) {
        if (!c->type1_source_known)
            return -ENODATA;
        /* a92580 -> 405590/4055c6 -> 404d18: original source byte != 0. */
        if (!c->type1_source_byte)
            return -EACCES;
    }
    return 0;
}

int cp_lif_frame_decode(const unsigned char *rx, size_t rx_size,
    const struct cp_lif_frame_context *context, struct cp_lif_decoded_frame *out,
    size_t out_capacity)
{
    struct cp_lif_decoded_frame result;
    struct cp_lif_frame_context c;
    unsigned char *frame = result.frame;
    uint16_t length;
    unsigned type, seen = 0;
    size_t end, pos, i;
    uint32_t checksum = 0;
    int rc;

    if (!span_valid(rx, rx_size) || !span_valid(context, sizeof(*context)) ||
        !span_valid(out, out_capacity) ||
        (uintptr_t)context % _Alignof(struct cp_lif_frame_context) ||
        (uintptr_t)out % _Alignof(struct cp_lif_decoded_frame))
        return -EINVAL;
    if (overlaps(out, out_capacity, rx, rx_size) ||
        overlaps(out, out_capacity, context, sizeof(*context)))
        return -EINVAL;
    if (out_capacity < sizeof(*out) || rx_size < 9 ||
        rx_size > CP_LIF_FRAME_MAX_RX_BYTES)
        return -EMSGSIZE;
    memset(&result, 0, sizeof(result));
    memcpy(frame, rx, rx_size);
    memcpy(&c, context, sizeof(c));
    length = le16(frame + 1);
    if (length < 9 || length > CP_LIF_FRAME_MAX_BYTES ||
        (rx_size != length && rx_size != (size_t)length + 1))
        return -EMSGSIZE;
    if (frame[0] != 0xf0 || frame[length - 1] != 0x55 ||
        (rx_size != length && frame[length] != 0))
        return -EBADMSG;
    end = (size_t)length - 3;
    for (i = 1; i < end; ++i)
        checksum += frame[i];
    if ((uint16_t)checksum != le16(frame + end))
        return -EBADMSG;
    type = frame[3] & 7u;
    if (type < 1 || type > 3)
        return -EBADMSG;
    rc = context_valid(&c, type);
    if (rc)
        return rc;

    /* shortcut: finite 5/6 subset, add other commands only after closing schemas. */
    for (pos = 5; pos < end;) {
        struct cp_lif_command_view *command;
        const unsigned char *schema;
        unsigned id_base, count, cmd = frame[pos], bit;
        size_t start = pos++;
        if (cmd == 5) {
            schema = schema5;
            count = sizeof(schema5);
            id_base = 0;
            bit = 1;
        } else if (cmd == 6) {
            schema = schema6;
            count = sizeof(schema6);
            id_base = 0x40;
            bit = 2;
        } else {
            return -ENOTSUP;
        }
        if (seen & bit)
            return -ENOTSUP;
        seen |= bit;
        command = &result.commands[result.command_count++];
        command->command = (unsigned char)cmd;
        command->offset = (uint16_t)start;
        command->first_field = result.field_count;
        /* metadata is zero in both source table rows; no 'support' claim. */
        for (i = 0; i < count; ++i) {
            unsigned id = id_base + (unsigned)i;
            if (c.bitmap[(id >> 3) & 15u] & (1u << (id & 7u))) {
                struct cp_lif_field_view *field;
                if (schema[i] > end - pos)
                    return -EMSGSIZE;
                field = &result.fields[result.field_count++];
                field->command = (unsigned char)cmd;
                field->id = (unsigned char)id;
                field->offset = (uint16_t)pos;
                field->length = schema[i];
                ++command->field_count;
                pos += schema[i];
            }
        }
        command->length = (uint16_t)(pos - start);
    }
    result.source_sequence = c.sequence_before;
    result.origin = c.origin;
    result.bitmap_event = c.bitmap_event;
    result.frame_length = length;
    result.rx_length = (uint16_t)rx_size;
    result.flags = frame[3];
    result.opaque = frame[4];
    result.extra_zero = (unsigned char)(rx_size != length);
    result.transport_decoded = 1;
    memcpy(out, &result, sizeof(result));
    return 0;
}
