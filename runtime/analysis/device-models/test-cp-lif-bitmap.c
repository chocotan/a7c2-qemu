/* SPDX-License-Identifier: MIT */
#include "cp-lif-bitmap.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static struct cp_lif_bitmap_guard guard(uint64_t n)
{
    struct cp_lif_bitmap_guard g = {0};
    g.owner_pid = (uint32_t)getpid(); g.sequence_before = n; g.sequence_after = n;
    g.origin = CP_LIF_ORIGIN_HOST_TEST; g.quiescent = 1;
    return g;
}
static struct cp_lif_bitmap_inputs inputs(uint32_t k)
{
    struct cp_lif_bitmap_inputs s;
    memset(&s, 0, sizeof(s)); s.known = 31; s.k = k; s.z = 1; s.s43 = 1;
    memset(s.property_known, 1, sizeof(s.property_known));
    return s;
}
static void word(unsigned char *p, uint32_t n)
{
    size_t i;
    for (i = 0; i < 4; ++i) p[i] = (unsigned char)(n >> (8 * i));
}
static void wire_check(const struct cp_lif_bitmap_product *p)
{
    unsigned sum = 0x25;
    size_t i;
    assert(p->command[0] == 10 && !memcmp(p->command + 1, p->bitmap, 16));
    assert(!memcmp(p->wire, "\xf0\x19\x00\x02\x00\x0a", 6));
    assert(!memcmp(p->wire + 6, p->bitmap, 16));
    for (i = 0; i < 16; ++i) sum += p->bitmap[i];
    assert(p->wire[22] == (sum & 255) && p->wire[23] == (sum >> 8) && p->wire[24] == 0x55);
    assert(p->logical_bytes == 25 && p->dma_span == 32 && p->dma_known_bytes == 25 && p->owned_virtual_data == 1);
}
static void branch_matrix(void)
{
    static const uint32_t bits[] = {0x1000, 0x8000, 0x200000, 0x80000000, 0x10000000, 0x20000000};
    const unsigned char literal[25] = {0xf0,0x19,0,2,0,10,0x40,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0x65,0,0x55};
    struct cp_lif_bitmap_guard g = guard(2);
    struct cp_lif_bitmap_product p;
    struct cp_lif_bitmap_inputs s = inputs(1);
    unsigned k, flags, control, i;
    assert(!cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) && !memcmp(p.wire, literal, 25));
    for (k = 0; k < 8; ++k) for (flags = 0; flags < 256; ++flags) for (control = 0; control < 64; ++control) {
        unsigned char expected[16] = {0};
        uint32_t a = 0;
        unsigned special = flags >> 7, f;
        s = inputs(k);
        for (i = 0; i < 6; ++i) if (flags & (1u << i)) a |= bits[i];
        word(s.property + 0x15a, a);
        word(s.property + 0x15e, (flags & 64) ? 0x40000000 : 0);
        s.property[0x161] |= special ? 0x20 : 0;
        s.mode = (control & 1) ? 1 : 0;
        s.property[0x52] = (control & 2) ? 0x60 : 0x20;
        s.s43 = (control & 4) ? 0xff : 0;
        s.z = (control & 8) ? 0xff : 0;
        s.property[0x51] = (control & 16) ? 0x20 : 0;
        s.s5a = (control & 32) ? 0x80 : 0;
        f = (control & 3) == 3;
        if (k == 1 || k == 2) expected[0] = 0x40;
        if (k == 4 || k == 5) {
            expected[0] = special ? 0xdf : 0xff;
            expected[1] = (unsigned char)(0x79 | (s.s43 ? 0 : 6) | (f && !special ? 0x80 : 0));
            expected[2] = (unsigned char)((special ? 0x80 : 0) | (f ? 3 : 0) | ((flags & 8) ? 0x40 : 0));
            expected[3] = (unsigned char)((special ? 6 : 0) | (f && special ? 8 : 0));
            expected[8] = (unsigned char)(0x2f | (k == 5 || !s.s43 ? 0x10 : 0) | (k == 4 && (control & 16) ? 0x80 : 0));
            if (!s.z) {
                expected[2] |= (unsigned char)(((flags & 1) ? 4 : 0) | ((flags & 2) ? 8 : 0) | ((flags & 4) ? 0x10 : 0));
                expected[3] |= (flags & 64) ? 1 : 0;
                expected[9] = (unsigned char)((k == 5 && s.s5a ? 1 : 0) | ((flags & 16) ? 2 : 0) | ((flags & 32) ? 4 : 0));
            }
        }
        assert(!cp_lif_bitmap_build(&s, &g, &p, sizeof(p)));
        assert(!memcmp(p.bitmap, expected, 16));
        assert(p.gate == (k == 1 || k == 2 || k == 4 || k == 5));
        assert(!(p.bitmap[8] & 0x40)); /* field 46 is never selected by the builder. */
        wire_check(&p);
    }
    s = inputs(UINT32_MAX); s.known = CP_LIF_BITMAP_K_KNOWN;
    memset(s.property_known, 0xff, sizeof(s.property_known));
    assert(!cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) && !p.gate);
}
static void required_inputs_and_errors(void)
{
    struct cp_lif_bitmap_guard g = guard(2), bad;
    struct cp_lif_bitmap_product p, before;
    struct cp_lif_bitmap_inputs s = inputs(5);
    union { struct cp_lif_bitmap_inputs s; struct cp_lif_bitmap_product p; } alias;
    size_t i;
    s.known &= ~CP_LIF_BITMAP_S5A_KNOWN;
    s.property_known[0x51] = s.property_known[0x52] = 0;
    memset(s.property_known + 0x15e, 0, 3);
    assert(!cp_lif_bitmap_build(&s, &g, &p, sizeof(p)));
    s.z = 0;
    assert(cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) == -ENODATA);
    memset(s.property_known + 0x15e, 1, 3);
    assert(cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) == -ENODATA);
    s.known |= CP_LIF_BITMAP_S5A_KNOWN;
    assert(!cp_lif_bitmap_build(&s, &g, &p, sizeof(p)));
    s.k = 4;
    assert(cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) == -ENODATA);
    s.property_known[0x51] = 1; s.mode = 1;
    assert(cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) == -ENODATA);
    s.property_known[0x52] = 1;
    assert(!cp_lif_bitmap_build(&s, &g, &p, sizeof(p)));
    for (i = 0; i < 5; ++i) {
        s = inputs(5); s.z = 0; s.known &= ~(1u << i);
        assert(cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) == -ENODATA);
    }
    for (i = 0x15a; i < 0x162; ++i) {
        s = inputs(5); s.z = 0; s.property_known[i] = 0;
        assert(cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) == -ENODATA);
    }
    s = inputs(1); s.known = 1; memset(s.property_known, 0xff, sizeof(s.property_known));
    assert(!cp_lif_bitmap_build(&s, &g, &p, sizeof(p)));
    memset(&p, 0xa5, sizeof(p)); before = p;
    s.known = 0;
    assert(cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) == -ENODATA && !memcmp(&p, &before, sizeof(p)));
    s = inputs(4); s.property_known[0x161] = 2;
    assert(cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) == -EINVAL);
    s = inputs(1); s.known |= 32;
    assert(cp_lif_bitmap_build(&s, &g, &p, sizeof(p)) == -EINVAL);
    s = inputs(1);
    assert(cp_lif_bitmap_build(&s, &g, &p, sizeof(p) - 1) == -EMSGSIZE);
    assert(!memcmp(&p, &before, sizeof(p)));
    alias.s = s;
    assert(cp_lif_bitmap_build(&alias.s, &g, &alias.p, sizeof(alias.p)) == -EINVAL);
    assert(cp_lif_bitmap_build(&s, &g, (void *)(uintptr_t)(UINTPTR_MAX - 4), sizeof(p)) == -EINVAL);
    assert(cp_lif_bitmap_build((void *)((unsigned char *)&s + 1), &g, &p, sizeof(p)) == -EINVAL);
    bad = g; bad.origin = CP_LIF_ORIGIN_NONE;
    assert(cp_lif_bitmap_build(&s, &bad, &p, sizeof(p)) == -ENODATA);
    bad = g; bad.origin = (enum cp_lif_origin)99;
    assert(cp_lif_bitmap_build(&s, &bad, &p, sizeof(p)) == -EXDEV);
    bad = g; ++bad.owner_pid;
    assert(cp_lif_bitmap_build(&s, &bad, &p, sizeof(p)) == -EXDEV);
    bad = g; bad.quiescent = 2;
    assert(cp_lif_bitmap_build(&s, &bad, &p, sizeof(p)) == -EINVAL);
    bad = g; bad.quiescent = 0;
    assert(cp_lif_bitmap_build(&s, &bad, &p, sizeof(p)) == -EAGAIN);
    bad = g; ++bad.sequence_after;
    assert(cp_lif_bitmap_build(&s, &bad, &p, sizeof(p)) == -EAGAIN);
    bad = guard(3);
    assert(cp_lif_bitmap_build(&s, &bad, &p, sizeof(p)) == -EAGAIN);
}
static size_t receive6(unsigned char *rx, unsigned type)
{
    size_t i;
    unsigned sum = 0;
    memset(rx, 0, 42); rx[0] = 0xf0; rx[1] = 42; rx[3] = (unsigned char)type; rx[5] = 6;
    for (i = 6; i < 39; ++i) rx[i] = (unsigned char)(0x80 + i);
    for (i = 1; i < 39; ++i) sum += rx[i];
    rx[39] = (unsigned char)sum; rx[40] = (unsigned char)(sum >> 8); rx[41] = 0x55;
    return 42;
}
static void owner_and_receive(void)
{
    struct cp_lif_bitmap_owner o = {0}, before;
    struct cp_lif_bitmap_guard g = guard(2);
    struct cp_lif_bitmap_inputs s = inputs(4);
    struct cp_lif_bitmap_lease lease, wrong, suppressed;
    struct cp_lif_bitmap_received received, prior;
    struct { struct cp_lif_bitmap_received value; unsigned char tail[24]; } extended;
    unsigned char *rx = malloc(42), actual[25];
    static const unsigned ids[] = {0x40,0x41,0x42,0x43,0x45}, lens[] = {2,11,9,4,7};
    size_t n, i, offset;
    pid_t child;
    int status;
    assert(rx); n = receive6(rx, 2);
    assert(cp_lif_bitmap_request(&o, 1, &s, &g, &lease, sizeof(lease)) == -ENODATA);
    assert(!cp_lif_bitmap_owner_init(&o, &g) && !o.configured_known && !o.pending);
    assert(cp_lif_bitmap_owner_init(&o, &g) == -EALREADY);
    g = guard(4);
    assert(cp_lif_bitmap_receive_decode(&o, rx, n, &g, &received, sizeof(received)) == -ENODATA);
    before = o;
    assert(cp_lif_bitmap_request(&o, 2, &s, &g, &lease, sizeof(lease)) == -ENOTSUP);
    assert(!memcmp(&before, &o, sizeof(o)));
    assert(!cp_lif_bitmap_request(&o, 1, &s, &g, &lease, sizeof(lease)));
    assert(o.configured_known && o.gate == 1 && o.pending && !o.owned_transport_consumed);
    assert(lease.token == 1 && lease.configured_generation == 1 && lease.producer_sequence == 4);
    g = guard(6); before = o;
    assert(cp_lif_bitmap_receive_decode(&o, rx, n, &g, &received, sizeof(received)) == -ENODATA);
    memcpy(actual, lease.wire, 25);
    for (i = 0; i < 25; ++i) {
        actual[i] ^= 1;
        assert(cp_lif_bitmap_observe_transport_consumed(&o, &lease, actual, 25, &g) == -EBADMSG);
        assert(!memcmp(&before, &o, sizeof(o))); actual[i] ^= 1;
    }
    assert(cp_lif_bitmap_observe_transport_consumed(&o, &lease, actual, 24, &g) == -EMSGSIZE);
    wrong = lease; ++wrong.token;
    assert(cp_lif_bitmap_observe_transport_consumed(&o, &wrong, actual, 25, &g) == -ESTALE);
    wrong = lease; ++wrong.producer_sequence;
    assert(cp_lif_bitmap_observe_transport_consumed(&o, &wrong, actual, 25, &g) == -ESTALE);
    assert(!cp_lif_bitmap_observe_transport_consumed(&o, &lease, actual, 25, &g));
    assert(o.owned_transport_consumed && !o.pending && o.consumed_generation == 1);
    g = guard(8);
    assert(cp_lif_bitmap_observe_transport_consumed(&o, &lease, actual, 25, &g) == -ENODATA);
    memset(&extended, 0x5a, sizeof(extended));
    assert(!cp_lif_bitmap_receive_decode(&o, rx, n, &g, &extended.value, sizeof(extended)));
    received = extended.value;
    for (i = 0; i < sizeof(extended.tail); ++i) assert(extended.tail[i] == 0x5a);
    assert(received.owned_virtual_data && received.configured_matches_consumed);
    assert(received.context.bitmap_event == CP_LIF_BITMAP_A923D0_SNAPSHOT);
    assert(received.context.type1_source_known && received.context.type1_source_byte == 1);
    assert(received.decoded.transport_decoded && received.decoded.command_count == 1 && received.decoded.field_count == 5);
    assert(received.decoded.source_sequence == 8 && received.decoded.frame_length == 42);
    for (i = 0, offset = 6; i < 5; ++i) {
        assert(received.decoded.fields[i].id == ids[i] && received.decoded.fields[i].length == lens[i]);
        assert(received.decoded.fields[i].offset == offset); offset += lens[i];
    }
    assert(offset == 39 && received.decoded.fields[0].id == 0x40 && !(received.context.bitmap[8] & 0x40));
    memset(rx, 0, n); free(rx); rx = NULL;
    assert(received.decoded.frame[6] == 0x86);
    g = guard(10); before = o; prior = received;
    assert(cp_lif_bitmap_receive_decode(&o, received.decoded.frame, 42, &g, &received, sizeof(received)) == -EINVAL);
    assert(!memcmp(&received, &prior, sizeof(received)) && !memcmp(&o, &before, sizeof(o)));
    assert(cp_lif_bitmap_request(&o, 1, &s, &g, (void *)&o, sizeof(o)) == -EINVAL);
    g = guard(8);
    assert(cp_lif_bitmap_gate_clear(&o, &g) == -ESTALE);
    g = guard(10);
    assert(!cp_lif_bitmap_gate_clear(&o, &g) && !o.gate && o.configured_generation == 1);
    {
        unsigned char frame[42];
        n = receive6(frame, 1); g = guard(12); before = o;
        assert(cp_lif_bitmap_receive_decode(&o, frame, n, &g, &received, sizeof(received)) == -EACCES);
        assert(!memcmp(&o, &before, sizeof(o)));
        n = receive6(frame, 2);
        assert(!cp_lif_bitmap_receive_decode(&o, frame, n, &g, &received, sizeof(received)) && !received.context.type1_source_byte);
    }
    g = guard(14); assert(!cp_lif_bitmap_request(&o, 1, &s, &g, &lease, sizeof(lease)));
    g = guard(16); s.k = 1;
    assert(!cp_lif_bitmap_request(&o, 1, &s, &g, &suppressed, sizeof(suppressed)) && !suppressed.token);
    assert(o.configured_generation == 3 && o.pending && !memcmp(o.lease.wire, lease.wire, 25));
    g = guard(18);
    assert(!cp_lif_bitmap_observe_transport_consumed(&o, &lease, lease.wire, 25, &g));
    g = guard(20); before = o;
    assert(cp_lif_bitmap_receive_decode(&o, received.decoded.frame, received.decoded.rx_length, &g, &prior, sizeof(prior)) == -EAGAIN);
    assert(!memcmp(&before, &o, sizeof(o)) && o.configured_generation != o.consumed_generation);
    assert(!cp_lif_bitmap_request(&o, 1, &s, &g, &lease, sizeof(lease)));
    g = guard(22);
    assert(!cp_lif_bitmap_request(&o, 0, NULL, &g, &suppressed, sizeof(suppressed)));
    assert(!o.gate && o.configured_known && !suppressed.token && o.configured_generation == 5);
    for (i = 0; i < 16; ++i) assert(!o.configured[i]);
    g = guard(24);
    assert(!cp_lif_bitmap_observe_transport_consumed(&o, &lease, lease.wire, 25, &g));
    g = guard(26);
    assert(cp_lif_bitmap_receive_decode(&o, received.decoded.frame, 42, &g, &prior, sizeof(prior)) == -EAGAIN);
    child = fork(); assert(child >= 0);
    if (!child) {
        struct cp_lif_bitmap_guard inherited = g;
        assert(cp_lif_bitmap_gate_clear(&o, &inherited) == -EXDEV);
        inherited.owner_pid = (uint32_t)getpid();
        assert(cp_lif_bitmap_gate_clear(&o, &inherited) == -EXDEV);
        _exit(0);
    }
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    o.configured_generation = UINT64_MAX; before = o;
    assert(cp_lif_bitmap_request(&o, 0, NULL, &g, &suppressed, sizeof(suppressed)) == -EOVERFLOW);
    assert(!memcmp(&before, &o, sizeof(o)));
}
int main(void)
{
    branch_matrix(); required_inputs_and_errors(); owner_and_receive();
    puts("owned_virtual_data=1 source_build_consumed=1 owned_transport_consumed=1 receive_snapshot_decoded=1 native_delivery=0 cp_state=0 ready=0 ack=0");
    return 0;
}
