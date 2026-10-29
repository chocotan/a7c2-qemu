/* SPDX-License-Identifier: MIT */
#include "mbp-mailbox.h"

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

_Static_assert(IMOLA_MBP_SOURCE_SPU0_BASE == UINT32_C(0xbf062000), "SPU0 source table");
_Static_assert(IMOLA_MBP_SOURCE_SPU1_BASE == UINT32_C(0xbf072000), "SPU1 source table");
_Static_assert(IMOLA_MBP_SOURCE_RAM1_BASE == UINT32_C(0xbe000000), "RAM1 source LUI");
_Static_assert(IMOLA_MBP_CHANNELS == 2 && IMOLA_MBP_ROLES == 2, "two logical pairs");
_Static_assert(IMOLA_MBP_VIRTUAL_DIRECTION_CAPACITY == 1, "explicit single-slot policy");

static void failed_write(imola_mbp *owner, unsigned channel, unsigned role,
                          uint32_t offset, uint32_t value, int error)
{
    imola_mbp before;
    memcpy(&before, owner, sizeof before);
    assert(imola_mbp_write(owner, channel, role, offset, value) == error);
    assert(memcmp(owner, &before, sizeof before) == 0);
}

static void failed_read(imola_mbp *owner, unsigned channel, unsigned role,
                         uint32_t offset, int error)
{
    imola_mbp before;
    imola_mbp_word out = {UINT32_C(0x12345678), UINT32_C(0x87654321)};
    const imola_mbp_word original = out;
    memcpy(&before, owner, sizeof before);
    assert(imola_mbp_read(owner, channel, role, offset, &out) == error);
    assert(memcmp(owner, &before, sizeof before) == 0);
    assert(memcmp(&out, &original, sizeof out) == 0);
}

static void expect_status(imola_mbp *owner, unsigned channel, unsigned role,
                           uint32_t bits)
{
    imola_mbp before;
    imola_mbp_word out;
    memcpy(&before, owner, sizeof before);
    assert(imola_mbp_read(owner, channel, role, IMOLA_MBP_STATUS_DOORBELL, &out) == 0);
    assert(out.known_bits == UINT32_C(0xa));
    assert((out.value & out.known_bits) == bits);
    assert((out.value & ~out.known_bits) ==
           (IMOLA_MBP_UNKNOWN_POISON & ~UINT32_C(0xa)));
    assert(memcmp(owner, &before, sizeof before) == 0);
}

static void stage(imola_mbp *owner, unsigned channel, unsigned role,
                   uint32_t command, uint32_t argument)
{
    assert(imola_mbp_write(owner, channel, role, IMOLA_MBP_TX_COMMAND, command) == 0);
    assert(imola_mbp_write(owner, channel, role, IMOLA_MBP_TX_ARGUMENT, argument) == 0);
}

static void send(imola_mbp *owner, unsigned channel, unsigned role,
                  uint32_t command, uint32_t argument)
{
    stage(owner, channel, role, command, argument);
    assert(imola_mbp_write(owner, channel, role,
                           IMOLA_MBP_STATUS_DOORBELL, IMOLA_MBP_SUBMIT) == 0);
}

static void read_word(imola_mbp *owner, unsigned channel, unsigned role,
                       uint32_t offset, uint32_t value)
{
    imola_mbp_word out;
    assert(imola_mbp_read(owner, channel, role, offset, &out) == 0);
    assert(out.value == value && out.known_bits == UINT32_MAX);
}

static void pair(imola_mbp *owner, unsigned channel, unsigned role,
                  uint32_t command, uint32_t argument)
{
    read_word(owner, channel, role, IMOLA_MBP_RX_COMMAND, command);
    read_word(owner, channel, role, IMOLA_MBP_RX_ARGUMENT, argument);
}

static void ack(imola_mbp *owner, unsigned channel, unsigned role)
{
    assert(imola_mbp_write(owner, channel, role,
                           IMOLA_MBP_STATUS_DOORBELL, IMOLA_MBP_ACK) == 0);
}

static void constructor(void)
{
    imola_mbp owner = {0}, before;
    imola_mbp_info out, original;
    memset(&out, 0x3c, sizeof out);
    memcpy(&original, &out, sizeof out);
    failed_read(&owner, 0, 0, IMOLA_MBP_STATUS_DOORBELL, -EINVAL);
    failed_write(&owner, 0, 0, 0, 1, -EINVAL);
    assert(imola_mbp_snapshot(&owner, &out) == -EINVAL);
    assert(memcmp(&out, &original, sizeof out) == 0);
    assert(imola_mbp_init(&owner) == 0);
    memcpy(&before, &owner, sizeof owner);
    assert(imola_mbp_init(&owner) == -EALREADY);
    assert(memcmp(&owner, &before, sizeof owner) == 0);
    assert(imola_mbp_snapshot(&owner, &out) == 0);
    assert(out.diagnostic_only == 1 && out.owned_data_transport == 1);
    assert(out.original_mcu_executed == 0 && out.channels == 2);
    assert(out.direction_capacity == 1);
    for (unsigned c = 0; c < 2; ++c)
        for (unsigned r = 0; r < 2; ++r) {
            expect_status(&owner, c, r, IMOLA_MBP_TX_CAPACITY);
            assert(out.endpoints[c][r].pending == 0);
            assert(out.endpoints[c][r].staged_words == 0);
            assert(out.endpoints[c][r].read_words == 0);
            failed_read(&owner, c, r, IMOLA_MBP_RX_COMMAND, -ENODATA);
            failed_read(&owner, c, r, IMOLA_MBP_RX_ARGUMENT, -ENODATA);
        }
}

static void round_trip(unsigned channel, unsigned role)
{
    const uint32_t commands[2][2] = {{UINT32_C(0x20), UINT32_C(0x40a)},
                                    {0, UINT32_MAX}};
    const uint32_t arguments[2][2] = {{UINT32_C(0xdeadbeef), UINT32_C(0x12345678)},
                                     {UINT32_MAX, 0}};
    imola_mbp owner = {0};
    unsigned peer = role ^ 1u;
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, channel, role, commands[channel][role], arguments[channel][role]);
    expect_status(&owner, channel, role, 0);
    expect_status(&owner, channel, peer, IMOLA_MBP_TX_CAPACITY | IMOLA_MBP_RX_PENDING);
    pair(&owner, channel, peer, commands[channel][role], arguments[channel][role]);
    expect_status(&owner, channel, role, 0);
    ack(&owner, channel, peer);
    expect_status(&owner, channel, role, IMOLA_MBP_TX_CAPACITY);
    expect_status(&owner, channel, peer, IMOLA_MBP_TX_CAPACITY);
    failed_read(&owner, channel, peer, IMOLA_MBP_RX_COMMAND, -ENODATA);
}

static void full_duplex(void)
{
    imola_mbp owner = {0};
    assert(imola_mbp_init(&owner) == 0);
    for (unsigned c = 0; c < 2; ++c) {
        send(&owner, c, IMOLA_MBP_SPU, UINT32_C(0x20) + c, UINT32_C(0xa0000000) + c);
        send(&owner, c, IMOLA_MBP_MBP, UINT32_C(0x40a) + c, UINT32_C(0xb0000000) + c);
    }
    for (unsigned c = 0; c < 2; ++c) {
        expect_status(&owner, c, IMOLA_MBP_SPU, IMOLA_MBP_RX_PENDING);
        expect_status(&owner, c, IMOLA_MBP_MBP, IMOLA_MBP_RX_PENDING);
        pair(&owner, c, IMOLA_MBP_SPU, UINT32_C(0x40a) + c, UINT32_C(0xb0000000) + c);
        pair(&owner, c, IMOLA_MBP_MBP, UINT32_C(0x20) + c, UINT32_C(0xa0000000) + c);
        ack(&owner, c, IMOLA_MBP_SPU);
        expect_status(&owner, c, IMOLA_MBP_MBP,
                       IMOLA_MBP_TX_CAPACITY | IMOLA_MBP_RX_PENDING);
        ack(&owner, c, IMOLA_MBP_MBP);
    }
}

static void independent_channels(void)
{
    imola_mbp owner = {0};
    imola_mbp_endpoint before[2];
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, 1, 0, 11, 12);
    memcpy(before, owner.endpoints[1], sizeof before);
    send(&owner, 0, 0, 21, 22);
    send(&owner, 0, 1, 31, 32);
    pair(&owner, 0, 1, 21, 22);
    ack(&owner, 0, 1);
    assert(memcmp(before, owner.endpoints[1], sizeof before) == 0);
    pair(&owner, 1, 1, 11, 12);
}

static void partial_stage(void)
{
    imola_mbp owner = {0};
    assert(imola_mbp_init(&owner) == 0);
    failed_write(&owner, 0, 0, 0x10, 1, -ENODATA);
    assert(imola_mbp_write(&owner, 0, 0, 0, 99) == 0);
    failed_write(&owner, 0, 0, 0x10, 1, -ENODATA);
    assert(imola_mbp_write(&owner, 0, 0, 4, 100) == 0);
    assert(imola_mbp_write(&owner, 0, 0, 0x10, 1) == 0);
    pair(&owner, 0, 1, 99, 100);
    assert(imola_mbp_write(&owner, 1, 1, 4, 200) == 0);
    failed_write(&owner, 1, 1, 0x10, 1, -ENODATA);
    assert(imola_mbp_write(&owner, 1, 1, 0, 199) == 0);
    assert(imola_mbp_write(&owner, 1, 1, 0x10, 1) == 0);
    pair(&owner, 1, 0, 199, 200);
}

static void fresh_stage(void)
{
    imola_mbp owner = {0};
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, 0, 0, 10, 11);
    pair(&owner, 0, 1, 10, 11);
    ack(&owner, 0, 1);
    failed_write(&owner, 0, 0, 0x10, 1, -ENODATA);
    assert(imola_mbp_write(&owner, 0, 0, 0, 20) == 0);
    failed_write(&owner, 0, 0, 0x10, 1, -ENODATA);
    assert(imola_mbp_write(&owner, 0, 0, 4, 21) == 0);
    assert(imola_mbp_write(&owner, 0, 0, 0x10, 1) == 0);
    pair(&owner, 0, 1, 20, 21);
}

static void busy_retention(void)
{
    imola_mbp owner = {0};
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, 0, 0, 10, 11);
    stage(&owner, 0, 0, 20, 21);
    failed_write(&owner, 0, 0, 0x10, 1, -EBUSY);
    pair(&owner, 0, 1, 10, 11);
    failed_write(&owner, 0, 0, 0x10, 1, -EBUSY);
    ack(&owner, 0, 1);
    assert(imola_mbp_write(&owner, 0, 0, 0x10, 1) == 0);
    pair(&owner, 0, 1, 20, 21);
}

static void ack_empty(void)
{
    imola_mbp owner = {0};
    assert(imola_mbp_init(&owner) == 0);
    for (unsigned c = 0; c < 2; ++c)
        for (unsigned r = 0; r < 2; ++r)
            failed_write(&owner, c, r, 0x10, 4, -ENOENT);
}

static void ack_unread(void)
{
    imola_mbp owner = {0};
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, 0, 0, 0, UINT32_MAX);
    failed_write(&owner, 0, 1, 0x10, 4, -ENODATA);
    expect_status(&owner, 0, 0, 0);
}

static void ack_one_word(void)
{
    imola_mbp owner = {0};
    assert(imola_mbp_init(&owner) == 0);
    for (unsigned first = 0; first < 2; ++first) {
        send(&owner, first, 0, 17, 18);
        read_word(&owner, first, 1, 8 + first * 4u, 17 + first);
        failed_write(&owner, first, 1, 0x10, 4, -ENODATA);
        read_word(&owner, first, 1, 8 + (first ^ 1u) * 4u, 17 + (first ^ 1u));
        ack(&owner, first, 1);
        failed_write(&owner, first, 1, 0x10, 4, -ENOENT);
    }
}

static void repeat_peek(void)
{
    imola_mbp owner = {0};
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, 0, 0, UINT32_MAX, 0);
    read_word(&owner, 0, 1, 8, UINT32_MAX);
    read_word(&owner, 0, 1, 8, UINT32_MAX);
    failed_write(&owner, 0, 1, 0x10, 4, -ENODATA);
    read_word(&owner, 0, 1, 0xc, 0);
    pair(&owner, 0, 1, UINT32_MAX, 0);
    expect_status(&owner, 0, 0, 0);
    expect_status(&owner, 0, 1, IMOLA_MBP_TX_CAPACITY | IMOLA_MBP_RX_PENDING);
    ack(&owner, 0, 1);
    failed_read(&owner, 0, 1, 8, -ENODATA);
}

static void unsupported_access(void)
{
    const uint32_t bad_read[] = {0, 4, 0x14, 0x100, UINT32_C(0xfffffffc)};
    const uint32_t bad_write[] = {8, 0xc, 0x14, 0x100, UINT32_C(0xfffffffc)};
    const uint32_t bad_doorbell[] = {0, 2, 3, 5, UINT32_MAX};
    imola_mbp owner = {0};
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, 0, 0, 1, 2);
    stage(&owner, 0, 0, 3, 4);
    for (size_t i = 0; i < sizeof bad_read / sizeof *bad_read; ++i)
        failed_read(&owner, 0, 1, bad_read[i], -ENOTSUP);
    for (size_t i = 0; i < sizeof bad_write / sizeof *bad_write; ++i)
        failed_write(&owner, 0, 1, bad_write[i], 9, -ENOTSUP);
    for (size_t i = 0; i < sizeof bad_doorbell / sizeof *bad_doorbell; ++i)
        failed_write(&owner, 0, 1, 0x10, bad_doorbell[i], -ENOTSUP);
}

static void invalid_addressing(void)
{
    const unsigned bad[] = {2, 0x100, 0x101, UINT_MAX};
    imola_mbp owner = {0};
    assert(imola_mbp_init(&owner) == 0);
    for (size_t i = 0; i < sizeof bad / sizeof *bad; ++i) {
        failed_read(&owner, bad[i], 0, 0x10, -EINVAL);
        failed_write(&owner, bad[i], 0, 0, 1, -EINVAL);
        failed_read(&owner, 0, bad[i], 0x10, -EINVAL);
        failed_write(&owner, 0, bad[i], 0, 1, -EINVAL);
    }
    for (uint32_t offset = 1; offset < 0x14; ++offset)
        if (offset & 3u) {
            failed_read(&owner, 0, 0, offset, -EINVAL);
            failed_write(&owner, 0, 0, offset, 1, -EINVAL);
        }
}

static void null_pointers(void)
{
    imola_mbp owner = {0}, before;
    imola_mbp_word word = {17, 19};
    imola_mbp_info info, original;
    memset(&info, 0x3c, sizeof info);
    memcpy(&original, &info, sizeof info);
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, 0, 0, 1, 2);
    memcpy(&before, &owner, sizeof owner);
    assert(imola_mbp_init(NULL) == -EINVAL);
    assert(imola_mbp_read(NULL, 0, 0, 0x10, &word) == -EINVAL);
    assert(word.value == 17 && word.known_bits == 19);
    assert(imola_mbp_write(NULL, 0, 0, 0, 0) == -EINVAL);
    assert(imola_mbp_snapshot(NULL, &info) == -EINVAL);
    assert(memcmp(&info, &original, sizeof info) == 0);
    assert(imola_mbp_read(&owner, 0, 1, 8, NULL) == -EINVAL);
    assert(imola_mbp_snapshot(&owner, NULL) == -EINVAL);
    assert(memcmp(&owner, &before, sizeof owner) == 0);
}

static void owner_output_alias(void)
{
    imola_mbp owner = {0}, before;
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, 0, 0, 1, 2);
    memcpy(&before, &owner, sizeof owner);
    assert(imola_mbp_read(&owner, 0, 1, 8, (imola_mbp_word *)(void *)&owner) == -EINVAL);
    assert(imola_mbp_read(&owner, 0, 1, 8,
           (imola_mbp_word *)(void *)((unsigned char *)&owner + sizeof owner - 4)) == -EINVAL);
    assert(imola_mbp_snapshot(&owner, (imola_mbp_info *)(void *)&owner) == -EINVAL);
    assert(memcmp(&owner, &before, sizeof owner) == 0);
}

static void wrapped_unaligned_pointers(void)
{
    imola_mbp owner = {0}, before;
    imola_mbp_word word = {17, 19};
    imola_mbp_info info, original;
    uintptr_t high = UINTPTR_MAX - 3u;
    _Alignas(imola_mbp) unsigned char unaligned[sizeof(imola_mbp) + 8];
    memset(&info, 0x3c, sizeof info);
    memcpy(&original, &info, sizeof info);
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, 0, 0, 1, 2);
    memcpy(&before, &owner, sizeof owner);
    assert(imola_mbp_init((imola_mbp *)high) == -EOVERFLOW);
    assert(imola_mbp_read((imola_mbp *)high, 0, 1, 8, &word) == -EOVERFLOW);
    assert(word.value == 17 && word.known_bits == 19);
    assert(imola_mbp_write((imola_mbp *)high, 0, 0, 0, 0) == -EOVERFLOW);
    assert(imola_mbp_snapshot((imola_mbp *)high, &info) == -EOVERFLOW);
    assert(memcmp(&info, &original, sizeof info) == 0);
    assert(imola_mbp_read(&owner, 0, 1, 8, (imola_mbp_word *)high) == -EOVERFLOW);
    assert(imola_mbp_snapshot(&owner, (imola_mbp_info *)high) == -EOVERFLOW);
    assert(imola_mbp_init((imola_mbp *)(void *)(unaligned + 1)) == -EINVAL);
    assert(imola_mbp_write((imola_mbp *)(void *)(unaligned + 1), 0, 0, 0, 1) == -EINVAL);
    assert(imola_mbp_read((imola_mbp *)(void *)(unaligned + 1), 0, 0, 0x10, &word) == -EINVAL);
    assert(imola_mbp_snapshot((imola_mbp *)(void *)(unaligned + 1), &info) == -EINVAL);
    assert(imola_mbp_read(&owner, 0, 1, 8,
                          (imola_mbp_word *)(void *)(unaligned + 1)) == -EINVAL);
    assert(imola_mbp_snapshot(&owner,
                              (imola_mbp_info *)(void *)(unaligned + 1)) == -EINVAL);
    assert(memcmp(&owner, &before, sizeof owner) == 0);
}

static void snapshot_passive(void)
{
    imola_mbp owner = {0}, before;
    imola_mbp_info info;
    assert(imola_mbp_init(&owner) == 0);
    send(&owner, 0, 0, 10, 11);
    stage(&owner, 0, 0, 20, 21);
    read_word(&owner, 0, 1, 0xc, 11);
    memcpy(&before, &owner, sizeof owner);
    assert(imola_mbp_snapshot(&owner, &info) == 0);
    assert(memcmp(&owner, &before, sizeof owner) == 0);
    assert(info.endpoints[0][0].staged_words == 3);
    assert(info.endpoints[0][1].pending == 1);
    assert(info.endpoints[0][1].read_words == 2);
    assert(info.endpoints[0][0].status.known_bits == 0xa);
    failed_write(&owner, 0, 1, 0x10, 4, -ENODATA);
    pair(&owner, 0, 1, 10, 11);
}

int main(int argc, char **argv)
{
    static const char *const names[] = {
        "constructor", "spu0-to-mbp", "mbp0-to-spu", "spu1-to-mbp", "mbp1-to-spu",
        "full-duplex", "channel-independence", "partial-stage", "fresh-stage",
        "busy-retention", "ack-empty", "ack-unread", "ack-one-word", "repeat-peek",
        "unsupported-access", "invalid-addressing", "null-pointers",
        "owner-output-alias", "wrapped-unaligned-pointers", "snapshot-passive"
    };
    static void (*const tests[])(void) = {
        constructor, NULL, NULL, NULL, NULL, full_duplex, independent_channels,
        partial_stage, fresh_stage, busy_retention, ack_empty, ack_unread,
        ack_one_word, repeat_peek, unsupported_access, invalid_addressing,
        null_pointers, owner_output_alias, wrapped_unaligned_pointers, snapshot_passive
    };
    assert(sizeof tests / sizeof *tests == sizeof names / sizeof *names);
    if (argc != 2) return 2;
    for (unsigned i = 0; i < sizeof names / sizeof *names; ++i)
        if (strcmp(argv[1], names[i]) == 0) {
            if (i >= 1 && i <= 4) round_trip((i - 1) / 2, (i - 1) % 2);
            else tests[i]();
            puts("HOST_TEST diagnostic_only=1 original_mcu_executed=0");
            return 0;
        }
    return 2;
}
