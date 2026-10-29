/* SPDX-License-Identifier: MIT */
#include "cp-lif-frame.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const unsigned char lengths5[] = {
    8, 1, 8, 3, 10, 28, 2, 6, 1, 2, 8, 6, 6, 6,
    1, 6, 3, 3, 4, 4, 4, 8, 36, 40, 8, 4, 6, 3
};
static const unsigned char lengths6[] = {2, 11, 9, 4, 6, 7, 45, 4, 8, 8, 24};

static struct cp_lif_frame_context context(void)
{
    struct cp_lif_frame_context c;
    memset(&c, 0, sizeof(c));
    c.sequence_before = c.sequence_after = 8;
    c.origin = CP_LIF_ORIGIN_HOST_TEST;
    c.bitmap_event = CP_LIF_BITMAP_A923D0_SNAPSHOT;
    c.quiescent = c.type1_source_known = c.type1_source_byte = 1;
    memset(c.bitmap_known, 1, sizeof(c.bitmap_known));
    return c;
}

static void finish(unsigned char *frame, size_t length)
{
    size_t i;
    unsigned sum = 0;
    frame[0] = 0xf0;
    frame[1] = (unsigned char)length;
    frame[2] = (unsigned char)(length >> 8);
    for (i = 1; i < length - 3; ++i)
        sum += frame[i];
    frame[length - 3] = (unsigned char)sum;
    frame[length - 2] = (unsigned char)(sum >> 8);
    frame[length - 1] = 0x55;
}

/* Synthetic host input, not a recorded native source event. */
static size_t make_frame(unsigned char *frame, const struct cp_lif_frame_context *c,
    unsigned first, unsigned second)
{
    unsigned commands[2] = {first, second};
    size_t pos = 5, k, j;
    memset(frame, 0, CP_LIF_FRAME_MAX_RX_BYTES);
    frame[3] = 0xf9;
    frame[4] = 0xa7;
    for (k = 0; k < 2 && commands[k]; ++k) {
        unsigned cmd = commands[k], base = cmd == 5 ? 0 : 0x40;
        size_t count = cmd == 5 ? sizeof(lengths5) : sizeof(lengths6);
        const unsigned char *lengths = cmd == 5 ? lengths5 : lengths6;
        frame[pos++] = (unsigned char)cmd;
        for (j = 0; j < count; ++j) {
            unsigned id = base + (unsigned)j, n;
            if (!(c->bitmap[id / 8] & (1u << (id % 8))))
                continue;
            for (n = 0; n < lengths[j]; ++n)
                frame[pos++] = (unsigned char)(id + n + 0x39u);
        }
    }
    finish(frame, pos + 3);
    return pos + 3;
}

static void check_views(const struct cp_lif_decoded_frame *out,
    const struct cp_lif_frame_context *c, const unsigned char *frame, size_t n)
{
    size_t k, j, pos = 5, fields = 0;
    assert(out->transport_decoded == 1 && out->source_sequence == 8);
    assert(out->origin == c->origin && out->bitmap_event == c->bitmap_event);
    assert(out->frame_length == n && out->rx_length == n && !out->extra_zero);
    assert(out->flags == frame[3] && out->opaque == frame[4]);
    assert(memcmp(frame, out->frame, n) == 0);
    for (k = 0; k < out->command_count; ++k) {
        const struct cp_lif_command_view *command = &out->commands[k];
        unsigned cmd = frame[pos++], base = cmd == 5 ? 0 : 0x40;
        const unsigned char *lengths = cmd == 5 ? lengths5 : lengths6;
        size_t count = cmd == 5 ? sizeof(lengths5) : sizeof(lengths6);
        size_t start = pos - 1, first_field = fields;
        assert(command->command == cmd && command->offset == start);
        assert(command->metadata == 0 && command->first_field == fields);
        for (j = 0; j < count; ++j) {
            unsigned id = base + (unsigned)j;
            const struct cp_lif_field_view *field;
            if (!(c->bitmap[id / 8] & (1u << (id % 8))))
                continue;
            field = &out->fields[fields++];
            assert(field->command == cmd && field->id == id);
            assert(field->length == lengths[j] && field->offset == pos);
            assert(field->offset >= 6 && pos + field->length <= n - 3);
            assert(memcmp(out->frame + field->offset, frame + pos, field->length) == 0);
            pos += field->length;
        }
        assert(command->length == pos - start);
        assert(command->field_count == fields - first_field);
    }
    assert(fields == out->field_count && pos == n - 3);
}

static void fails(const unsigned char *frame, size_t n,
    const struct cp_lif_frame_context *c, int expected)
{
    struct cp_lif_decoded_frame out, before;
    memset(&out, 0xa5, sizeof(out));
    memcpy(&before, &out, sizeof(before));
    assert(cp_lif_frame_decode(frame, n, c, &out, sizeof(out)) == expected);
    assert(memcmp(&before, &out, sizeof(out)) == 0);
}

static void schemas_and_copy(void)
{
    struct cp_lif_frame_context c = context(), saved;
    struct cp_lif_decoded_frame out;
    unsigned char frame[CP_LIF_FRAME_MAX_RX_BYTES], original[sizeof(frame)];
    unsigned bit, first;
    size_t n;
    for (bit = 0; bit < 128; ++bit) {
        memset(c.bitmap, 0, sizeof(c.bitmap));
        c.bitmap[bit / 8] = (unsigned char)(1u << (bit % 8));
        for (first = 5; first <= 6; ++first) {
            n = make_frame(frame, &c, first, 0);
            assert(cp_lif_frame_decode(frame, n, &c, &out, sizeof(out)) == 0);
            check_views(&out, &c, frame, n);
            assert(out.field_count == ((first == 5 && bit < 28) ||
                   (first == 6 && bit >= 64 && bit < 75)));
        }
    }
    memset(c.bitmap, 0xff, sizeof(c.bitmap));
    for (first = 5; first <= 6; ++first) {
        n = make_frame(frame, &c, first, 11 - first);
        memcpy(original, frame, sizeof(frame));
        memcpy(&saved, &c, sizeof(c));
        assert(cp_lif_frame_decode(frame, n, &c, &out, sizeof(out)) == 0);
        check_views(&out, &c, frame, n);
        assert(out.command_count == 2 && out.field_count == 39 && n == 363);
        assert(memcmp(original, frame, sizeof(frame)) == 0);
        assert(memcmp(&saved, &c, sizeof(c)) == 0);
    }
    {
        unsigned char *allocated = malloc(n);
        assert(allocated);
        memcpy(allocated, frame, n);
        assert(cp_lif_frame_decode(allocated, n, &c, &out, sizeof(out)) == 0);
        memset(allocated, 0x11, n);
        free(allocated);
        check_views(&out, &c, original, n);
    }
    c.origin = CP_LIF_ORIGIN_VIRTUAL_SOURCE;
    assert(cp_lif_frame_decode(frame, n, &c, &out, sizeof(out)) == 0);
    assert(out.origin == CP_LIF_ORIGIN_VIRTUAL_SOURCE);
}

static void golden_vectors_and_checksum_wrap(void)
{
    static const unsigned char five[] = {0xf0, 0x0a, 0, 0xe2, 0x7c, 5, 0xa6, 0x13, 2, 0x55};
    static const unsigned char six[] = {0xf0, 0x0b, 0, 3, 0x91, 6, 0x12, 0x34, 0xeb, 0, 0x55};
    static const unsigned char both[] = {
        0xf0, 0x0d, 0, 1, 0x7f, 5, 0xa6, 6, 0x12, 0x34, 0x84, 1, 0x55
    };
    struct cp_lif_frame_context c = context();
    struct cp_lif_decoded_frame out;
    unsigned char frame[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t n, i, j;
    unsigned sum = 0;
    c.bitmap[0] = 2;
    c.type1_source_known = 0;
    assert(cp_lif_frame_decode(five, sizeof(five), &c, &out, sizeof(out)) == 0);
    check_views(&out, &c, five, sizeof(five));
    assert(out.fields[0].id == 1 && out.fields[0].offset == 6);
    c.bitmap[0] = 0;
    c.bitmap[8] = 1;
    assert(cp_lif_frame_decode(six, sizeof(six), &c, &out, sizeof(out)) == 0);
    check_views(&out, &c, six, sizeof(six));
    assert(out.fields[0].id == 0x40 && out.fields[0].length == 2);
    c.bitmap[0] = 2;
    c.type1_source_known = 1;
    assert(cp_lif_frame_decode(both, sizeof(both), &c, &out, sizeof(out)) == 0);
    check_views(&out, &c, both, sizeof(both));
    assert(out.commands[1].offset == 7 && out.fields[1].offset == 8);
    memset(c.bitmap, 0xff, sizeof(c.bitmap));
    n = make_frame(frame, &c, 5, 6);
    assert(cp_lif_frame_decode(frame, n, &c, &out, sizeof(out)) == 0);
    for (i = 0; i < out.field_count; ++i)
        for (j = 0; j < out.fields[i].length; ++j)
            frame[out.fields[i].offset + j] = 0xff;
    finish(frame, n);
    for (i = 1; i < n - 3; ++i)
        sum += frame[i];
    assert(sum > 65535);
    assert(cp_lif_frame_decode(frame, n, &c, &out, sizeof(out)) == 0);
    check_views(&out, &c, frame, n);
}

static void guards_and_header(void)
{
    struct cp_lif_frame_context c = context(), bad;
    struct cp_lif_decoded_frame out;
    unsigned char frame[CP_LIF_FRAME_MAX_RX_BYTES];
    unsigned i, type;
    size_t n = make_frame(frame, &c, 5, 0);
    for (i = 0; i < 16; ++i) {
        bad = c;
        bad.bitmap_known[i] = 0;
        fails(frame, n, &bad, -ENODATA);
        bad.bitmap_known[i] = 2;
        fails(frame, n, &bad, -EINVAL);
        bad.bitmap_known[i] = 0xff;
        fails(frame, n, &bad, -EINVAL);
    }
    memset(&bad, 0, sizeof(bad));
    fails(frame, n, &bad, -ENODATA);
    bad.origin = c.origin;
    bad.quiescent = 1;
    fails(frame, n, &bad, -ENODATA);
    bad = c;
    bad.bitmap_event = CP_LIF_BITMAP_UNKNOWN;
    fails(frame, n, &bad, -ENODATA);
    bad.bitmap_event = (enum cp_lif_bitmap_event)99;
    fails(frame, n, &bad, -ENOTSUP);
    bad = c;
    bad.origin = (enum cp_lif_origin)99;
    fails(frame, n, &bad, -EXDEV);
    bad = c;
    bad.sequence_after = 10;
    fails(frame, n, &bad, -EAGAIN);
    bad.sequence_before = bad.sequence_after = 9;
    fails(frame, n, &bad, -EAGAIN);
    bad = c;
    bad.quiescent = 0;
    fails(frame, n, &bad, -EAGAIN);
    bad.quiescent = 2;
    fails(frame, n, &bad, -EINVAL);
    bad = c;
    bad.type1_source_known = 2;
    fails(frame, n, &bad, -EINVAL);
    bad.type1_source_known = 0;
    fails(frame, n, &bad, -ENODATA);
    bad.type1_source_known = 1;
    bad.type1_source_byte = 0;
    fails(frame, n, &bad, -EACCES);
    for (i = 1; i < 256; ++i) {
        bad.type1_source_byte = (unsigned char)i;
        assert(cp_lif_frame_decode(frame, n, &bad, &out, sizeof(out)) == 0);
    }
    for (type = 0; type < 8; ++type) {
        for (i = 0; i < 256; i += 8) {
            frame[3] = (unsigned char)(i | type);
            frame[4] = (unsigned char)(255 - i);
            finish(frame, n);
            bad = c;
            bad.type1_source_known = (unsigned char)(type == 1);
            if (type < 1 || type > 3) {
                fails(frame, n, &bad, -EBADMSG);
            } else {
                assert(cp_lif_frame_decode(frame, n, &bad, &out, sizeof(out)) == 0);
                check_views(&out, &bad, frame, n);
            }
        }
    }
}

static void corrupt_and_subset(void)
{
    struct cp_lif_frame_context c = context();
    struct cp_lif_decoded_frame out;
    unsigned char frame[CP_LIF_FRAME_MAX_RX_BYTES + 1], bad[sizeof(frame)];
    size_t n = make_frame(frame, &c, 5, 0), i;
    frame[n] = 0;
    assert(cp_lif_frame_decode(frame, n + 1, &c, &out, sizeof(out)) == 0);
    assert(out.extra_zero == 1 && out.rx_length == n + 1 && out.frame_length == n);
    assert(out.frame[n] == 0 && memcmp(out.frame, frame, n + 1) == 0);
    frame[n] = 1;
    fails(frame, n + 1, &c, -EBADMSG);
    fails(frame, n + 2, &c, -EMSGSIZE);
    for (i = 0; i < n; ++i) {
        memcpy(bad, frame, n);
        bad[i] ^= 1;
        fails(bad, n, &c, (i == 1 || i == 2) ? -EMSGSIZE : -EBADMSG);
    }
    for (i = 0; i < n; ++i)
        fails(frame, i, &c, -EMSGSIZE);
    memcpy(bad, frame, n);
    bad[1] = 8;
    fails(bad, n, &c, -EMSGSIZE);
    memset(bad, 0, sizeof(bad));
    bad[3] = 1;
    bad[5] = 0x7e;
    finish(bad, CP_LIF_FRAME_MAX_BYTES);
    fails(bad, CP_LIF_FRAME_MAX_BYTES, &c, -ENOTSUP);
    bad[CP_LIF_FRAME_MAX_BYTES] = 0;
    fails(bad, CP_LIF_FRAME_MAX_RX_BYTES, &c, -ENOTSUP);
    finish(bad, CP_LIF_FRAME_MAX_RX_BYTES);
    fails(bad, CP_LIF_FRAME_MAX_RX_BYTES, &c, -EMSGSIZE);
    fails(bad, sizeof(bad), &c, -EMSGSIZE);
    for (i = 0; i < 256; ++i) {
        if (i == 5 || i == 6)
            continue;
        n = make_frame(frame, &c, 5, 0);
        frame[5] = (unsigned char)i;
        finish(frame, n);
        fails(frame, n, &c, -ENOTSUP);
    }
    n = make_frame(frame, &c, 5, 5);
    fails(frame, n, &c, -ENOTSUP);
    n = make_frame(frame, &c, 6, 6);
    fails(frame, n, &c, -ENOTSUP);
    memset(c.bitmap, 0xff, sizeof(c.bitmap));
    n = make_frame(frame, &c, 5, 6);
    frame[n - 3] = 9;
    finish(frame, n + 1);
    fails(frame, n + 1, &c, -ENOTSUP);
    n = make_frame(frame, &c, 5, 0);
    finish(frame, n - 1);
    fails(frame, n - 1, &c, -EMSGSIZE);
}

static void alias_and_sizes(void)
{
    struct cp_lif_frame_context c = context();
    struct cp_lif_decoded_frame out;
    unsigned char frame[CP_LIF_FRAME_MAX_RX_BYTES];
    union {
        struct cp_lif_decoded_frame align;
        unsigned char bytes[sizeof(struct cp_lif_decoded_frame) +
                            sizeof(struct cp_lif_frame_context) + 128];
    } storage, before;
    size_t n = make_frame(frame, &c, 5, 0), cap = sizeof(out);
    struct cp_lif_decoded_frame *target = (void *)storage.bytes;
    struct cp_lif_frame_context *tail_context = (void *)(storage.bytes + cap);
    assert(cp_lif_frame_decode(NULL, n, &c, &out, cap) == -EINVAL);
    assert(cp_lif_frame_decode(frame, n, NULL, &out, cap) == -EINVAL);
    assert(cp_lif_frame_decode(frame, n, &c, NULL, cap) == -EINVAL);
    assert(cp_lif_frame_decode(frame, n, &c, &out, cap - 1) == -EMSGSIZE);
    assert(cp_lif_frame_decode(frame, SIZE_MAX, &c, &out, cap) == -EINVAL);
    assert(cp_lif_frame_decode(frame, n, &c, &out, SIZE_MAX) == -EINVAL);
    assert(cp_lif_frame_decode((const void *)(UINTPTR_MAX - 3), n,
                              &c, &out, cap) == -EINVAL);
    assert(cp_lif_frame_decode(frame, n, (const void *)(UINTPTR_MAX - 3),
                              &out, cap) == -EINVAL);
    assert(cp_lif_frame_decode(frame, n, &c,
                              (void *)(UINTPTR_MAX - 3), cap) == -EINVAL);
    assert(cp_lif_frame_decode(frame, n, (const void *)((unsigned char *)&c + 1),
                              &out, cap) == -EINVAL);
    assert(cp_lif_frame_decode(frame, n, &c,
                              (void *)((unsigned char *)&out + 1), cap) == -EINVAL);
    memset(&storage, 0x37, sizeof(storage));
    memcpy(storage.bytes + cap, frame, n);
    memcpy(&before, &storage, sizeof(storage));
    assert(cp_lif_frame_decode(storage.bytes + cap, n, &c, target, cap + n) == -EINVAL);
    assert(memcmp(&before, &storage, sizeof(storage)) == 0);
    assert(cp_lif_frame_decode(storage.bytes + cap, n, &c, target, cap) == 0);
    assert(memcmp(storage.bytes + cap, frame, n) == 0);
    memcpy(storage.bytes, frame, n);
    memcpy(&before, &storage, sizeof(storage));
    assert(cp_lif_frame_decode(storage.bytes, n, &c, target, cap) == -EINVAL);
    assert(memcmp(&before, &storage, sizeof(storage)) == 0);
    memcpy(tail_context, &c, sizeof(c));
    memcpy(&before, &storage, sizeof(storage));
    assert(cp_lif_frame_decode(frame, n, tail_context, target,
                              cap + sizeof(c)) == -EINVAL);
    assert(memcmp(&before, &storage, sizeof(storage)) == 0);
    assert(cp_lif_frame_decode(frame, n, tail_context, target, cap) == 0);
    assert(memcmp(tail_context, &c, sizeof(c)) == 0);
    memcpy(storage.bytes, &c, sizeof(c));
    memcpy(&before, &storage, sizeof(storage));
    assert(cp_lif_frame_decode(frame, n, (const void *)storage.bytes,
                              target, cap) == -EINVAL);
    assert(memcmp(&before, &storage, sizeof(storage)) == 0);
    memset(&storage, 0x37, sizeof(storage));
    assert(cp_lif_frame_decode(frame, n, &c, target, sizeof(storage)) == 0);
    for (n = cap; n < sizeof(storage); ++n)
        assert(storage.bytes[n] == 0x37);
}

int main(void)
{
    schemas_and_copy();
    golden_vectors_and_checksum_wrap();
    guards_and_header();
    corrupt_and_subset();
    alias_and_sizes();
    puts("host_fixture_transport_decoded=1 native_receive=0 semantic_applied=0 published=0 ack=0");
    return 0;
}
