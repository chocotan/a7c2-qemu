/* SPDX-License-Identifier: MIT */
#include "infraimaging-format.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Public BB writer's arguments and first-entry layout, independently transcribed. */
static const unsigned char golden[80] = {
    0x53,0x53,0x59,0x4e,0,0,0,6,0,0,0,0,1,0,0,0,
    0x20,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0x45,0x54,0x52,0x59,0,0,0,0,1,0,0,0,0x40,0,0,0,
    0x10,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    1,0,0,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0
};

static const unsigned char forwarded[80] = {
    0x53,0x53,0x59,0x4e,0,0,0,1,0,0,0,0,1,0,0,0,
    0x20,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0x45,0x54,0x52,0x59,0,0,0,0,0,0,0,0,0x40,0,0,0,
    0x10,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    1,1,3,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0
};

static void put32(unsigned char *p, unsigned int value)
{
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (8 * i));
}

static void unchanged_reject(struct full_infraimaging_format *format,
                             const unsigned char *packet, unsigned int bytes)
{
    struct full_infraimaging_format before;
    memcpy(&before, format, sizeof before);
    assert(full_infraimaging_format_consume(format, packet, bytes) < 0);
    assert(!memcmp(format, &before, sizeof before));
}

static void fresh_init(void)
{
    struct full_infraimaging_format format, before;
    memset(&format, 0xa5, sizeof format);
    format.initialized = 0;
    assert(!full_infraimaging_format_init(&format));
    const unsigned int expected[5] = {1, 0, 0, 0, 0};
    assert(!memcmp(format.cache, expected, sizeof expected));
    assert(format.initialized == 1 && !format.consumed && !format.payload_fnv64);
    memcpy(&before, &format, sizeof before);
    assert(full_infraimaging_format_init(&format) < 0);
    assert(!memcmp(&format, &before, sizeof before));
    assert(full_infraimaging_format_init(NULL) < 0);
    format.initialized = UINT_MAX;
    memcpy(&before, &format, sizeof before);
    assert(full_infraimaging_format_init(&format) < 0);
    assert(!memcmp(&format, &before, sizeof before));
    puts("INFRAIMAGING_FORMAT_FRESH_EXPLICIT_FIVE_WORD_INIT_ONCE_PASS");
}

static void build_packet(void)
{
    unsigned char buffer[82], before[82];
    memset(buffer, 0xa5, sizeof buffer);
    memcpy(before, buffer, sizeof before);
    for (unsigned int bytes = 0; bytes <= 81; bytes++) {
        if (bytes == 80) continue;
        assert(full_infraimaging_format_build(buffer + 1, bytes) < 0);
        assert(!memcmp(buffer, before, sizeof buffer));
    }
    assert(full_infraimaging_format_build(buffer + 1, UINT_MAX) < 0);
    assert(!memcmp(buffer, before, sizeof buffer));
    assert(full_infraimaging_format_build(NULL, 80) < 0);
    assert(!full_infraimaging_format_build(buffer + 1, 80));
    assert(buffer[0] == 0xa5 && buffer[81] == 0xa5);
    assert(!memcmp(buffer + 1, golden, sizeof golden));
    printf("INFRAIMAGING_FORMAT_PACKET=");
    for (unsigned int i = 1; i <= 80; i++) printf("%02x", buffer[i]);
    puts("");
    puts("INFRAIMAGING_FORMAT_BUILD_CANONICAL_SSYN06_ETRY_TYPE1_80B_PASS");
}

static void consume_original(void)
{
    struct full_infraimaging_format format = {0}, before;
    assert(!full_infraimaging_format_init(&format));
    assert(!full_infraimaging_format_consume(&format, golden, sizeof golden));
    const unsigned int expected[5] = {0, 1, 1920, 1080, 0};
    assert(!memcmp(format.cache, expected, sizeof expected));
    assert(format.initialized == 1 && format.consumed == 1);
    assert(format.payload_fnv64 == 0x1a3c540ebc5023bdULL);
    printf("INFRAIMAGING_FORMAT_CACHE=%u,%u,%u,%u,%u\n", format.cache[0],
           format.cache[1], format.cache[2], format.cache[3], format.cache[4]);
    printf("INFRAIMAGING_FORMAT_PAYLOAD_FNV64=%016llx\n", format.payload_fnv64);
    memcpy(&before, &format, sizeof before);
    assert(full_infraimaging_format_init(&format) < 0);
    assert(!memcmp(&format, &before, sizeof before));
    puts("INFRAIMAGING_FORMAT_ORIGINAL_PAYLOAD_OUT1_CACHE_READBACK_FNV_PASS");
}

static void full_payload_fields(void)
{
    struct full_infraimaging_format format = {0};
    unsigned char packet[80];
    assert(!full_infraimaging_format_init(&format));
    memcpy(packet, golden, sizeof packet);
    packet[0x40] = 0xff;
    packet[0x41] = 0x80;
    packet[0x42] = 0xcd;
    packet[0x43] = 0xab;
    put32(packet + 0x48, 0x89abcdefu);
    put32(packet + 0x4c, 0xfedcba98u);
    assert(!full_infraimaging_format_consume(&format, packet, sizeof packet));
    const unsigned int expected[5] = {0x80, 0xff, 0x89abcdefu, 0xfedcba98u, 0xabcd};
    assert(!memcmp(format.cache, expected, sizeof expected) && format.consumed == 1);
    memset(packet + 0x40, 0, 16);
    assert(!full_infraimaging_format_consume(&format, packet, sizeof packet));
    const unsigned int zero[5] = {0};
    assert(!memcmp(format.cache, zero, sizeof zero) && format.consumed == 2);
    packet[0x42] = packet[0x43] = 0xff;
    put32(packet + 0x48, UINT_MAX);
    put32(packet + 0x4c, UINT_MAX);
    assert(!full_infraimaging_format_consume(&format, packet, sizeof packet));
    assert(format.cache[4] == 0xffff && format.cache[2] == UINT_MAX &&
           format.cache[3] == UINT_MAX && format.consumed == 3);
    puts("INFRAIMAGING_FORMAT_FULL_BYTES_U16_FLAGS_AND_U32_DIMENSIONS_PASS");
}

static void unconsumed_word(void)
{
    struct full_infraimaging_format format = {0};
    unsigned char packet[80];
    assert(!full_infraimaging_format_init(&format));
    memcpy(packet, golden, sizeof packet);
    assert(!full_infraimaging_format_consume(&format, packet, sizeof packet));
    unsigned int cache[5];
    memcpy(cache, format.cache, sizeof cache);
    unsigned long long digest = format.payload_fnv64;
    memset(packet + 0x44, 0xa5, 4);
    assert(!full_infraimaging_format_consume(&format, packet, sizeof packet));
    assert(!memcmp(cache, format.cache, sizeof cache));
    assert(format.payload_fnv64 != digest && format.consumed == 2);
    digest = format.payload_fnv64;
    memset(packet + 0x44, 0xff, 4);
    assert(!full_infraimaging_format_consume(&format, packet, sizeof packet));
    assert(!memcmp(cache, format.cache, sizeof cache));
    assert(format.payload_fnv64 != digest && format.consumed == 3);
    puts("INFRAIMAGING_FORMAT_UNCONSUMED_WORD_ONLY_CHANGES_PAYLOAD_DIGEST_PASS");
}

static void invalid_framing(void)
{
    struct full_infraimaging_format format = {0};
    unsigned char packet[80];
    assert(!full_infraimaging_format_init(&format));
    assert(!full_infraimaging_format_consume(&format, golden, sizeof golden));
    for (unsigned int offset = 0; offset < 0x40; offset++) {
        memcpy(packet, golden, sizeof packet);
        packet[offset] ^= 1;
        unchanged_reject(&format, packet, sizeof packet);
    }
    static const unsigned int invalid[][2] = {
        {4, 0x01000000}, {0xc, 0}, {0xc, 2}, {0xc, UINT_MAX},
        {0x10, 0}, {0x10, 0x40}, {0x10, UINT_MAX},
        {0x24, 1}, {0x24, UINT_MAX}, {0x28, 0}, {0x28, 2},
        {0x2c, 0}, {0x2c, 0x3f}, {0x2c, 0x41}, {0x2c, UINT_MAX},
        {0x30, 0}, {0x30, 15}, {0x30, 17}, {0x30, UINT_MAX},
        {0x34, 0x20}, {0x34, 0x40}, {0x34, UINT_MAX}
    };
    for (unsigned int i = 0; i < sizeof invalid / sizeof invalid[0]; i++) {
        memcpy(packet, golden, sizeof packet);
        put32(packet + invalid[i][0], invalid[i][1]);
        unchanged_reject(&format, packet, sizeof packet);
    }
    memcpy(packet, golden, sizeof packet);
    put32(packet + 0xc, 2);
    put32(packet + 0x34, 0x20);
    unchanged_reject(&format, packet, sizeof packet);
    puts("INFRAIMAGING_FORMAT_BAD_SIGNATURE_KEY_TYPE_DUPLICATES_BOUNDS_RETAIN_PASS");
}

static void invalid_lengths(void)
{
    struct full_infraimaging_format format = {0};
    assert(!full_infraimaging_format_init(&format));
    assert(!full_infraimaging_format_consume(&format, golden, sizeof golden));
    for (unsigned int bytes = 0; bytes < 80; bytes++) {
        unsigned char *packet = malloc(bytes ? bytes : 1);
        assert(packet);
        memcpy(packet, golden, bytes);
        unchanged_reject(&format, packet, bytes);
        free(packet);
    }
    unchanged_reject(&format, golden, 81);
    unchanged_reject(&format, golden, UINT_MAX);
    unchanged_reject(&format, NULL, 80);
    assert(full_infraimaging_format_consume(NULL, golden, 80) < 0);
    puts("INFRAIMAGING_FORMAT_TRUNCATED_OVERSIZE_NULL_RETAIN_PASS");
}

static void invalid_owner(void)
{
    struct full_infraimaging_format format = {0};
    unchanged_reject(&format, golden, sizeof golden);
    assert(!full_infraimaging_format_init(&format));
    assert(!full_infraimaging_format_consume(&format, golden, sizeof golden));
    format.initialized = 2;
    unchanged_reject(&format, golden, sizeof golden);
    format.initialized = 1;
    format.consumed = UINT_MAX;
    unchanged_reject(&format, golden, sizeof golden);
    puts("INFRAIMAGING_FORMAT_UNKNOWN_OWNER_AND_COUNTER_OVERFLOW_RETAIN_PASS");
}

static void independent_copy(void)
{
    struct full_infraimaging_format format = {0};
    unsigned char storage[81];
    assert(!full_infraimaging_format_init(&format));
    storage[0] = 0x5a;
    memcpy(storage + 1, golden, sizeof golden);
    assert(!full_infraimaging_format_consume(&format, storage + 1, 80));
    const unsigned int expected[5] = {0, 1, 1920, 1080, 0};
    memset(storage + 1, 0xa5, 80);
    assert(!memcmp(format.cache, expected, sizeof expected));
    assert(format.payload_fnv64 == 0x1a3c540ebc5023bdULL && format.consumed == 1);
    assert(storage[0] == 0x5a);
    puts("INFRAIMAGING_FORMAT_UNALIGNED_INPUT_16B_COPY_NO_ALIAS_PASS");
}

static void separate_owners(void)
{
    struct full_infraimaging_format left = {0}, right = {0}, before;
    assert(!full_infraimaging_format_init(&left));
    assert(!full_infraimaging_format_init(&right));
    memcpy(&before, &right, sizeof before);
    assert(!full_infraimaging_format_consume(&left, golden, sizeof golden));
    assert(!memcmp(&right, &before, sizeof before));
    assert(left.consumed == 1 && !right.consumed && right.cache[0] == 1);
    puts("INFRAIMAGING_FORMAT_DISTINCT_OWNERS_NO_SHARED_CACHE_PASS");
}

static void consume_forwarded(void)
{
    struct full_infraimaging_format format = {0};
    assert(!full_infraimaging_format_init(&format));
    assert(!full_infraimaging_format_consume(&format, golden, sizeof golden));
    assert(format.consumed == 1 && format.cache[0] == 0 && format.cache[4] == 0);
    assert(!full_infraimaging_format_consume(&format, forwarded, sizeof forwarded));
    const unsigned int expected[5] = {1, 1, 1920, 1080, 3};
    assert(!memcmp(format.cache, expected, sizeof expected));
    assert(format.initialized == 1 && format.consumed == 2);
    assert(format.payload_fnv64 == 0x37228cd728b41c0dULL);
    printf("INFRAIMAGING_FORMAT_FORWARDED_PACKET=");
    for (unsigned int i = 0; i < sizeof forwarded; i++) printf("%02x", forwarded[i]);
    puts("");
    printf("INFRAIMAGING_FORMAT_FORWARDED_CACHE=%u,%u,%u,%u,%u\n", format.cache[0],
           format.cache[1], format.cache[2], format.cache[3], format.cache[4]);
    printf("INFRAIMAGING_FORMAT_FORWARDED_PAYLOAD_FNV64=%016llx\n", format.payload_fnv64);
    puts("INFRAIMAGING_FORMAT_SSYN01_TYPE0_UPDATES_SAME_CACHE_CONSUMED_TWO_PASS");
}

static void forwarded_fields(void)
{
    struct full_infraimaging_format format = {0};
    unsigned char packet[80];
    assert(!full_infraimaging_format_init(&format));
    memcpy(packet, forwarded, sizeof packet);
    assert(!full_infraimaging_format_consume(&format, packet, sizeof packet));
    unsigned int cache[5];
    memcpy(cache, format.cache, sizeof cache);
    memset(packet + 0x44, 0xa5, 4);
    assert(!full_infraimaging_format_consume(&format, packet, sizeof packet));
    assert(!memcmp(cache, format.cache, sizeof cache));
    assert(format.payload_fnv64 != 0x37228cd728b41c0dULL && format.consumed == 2);
    packet[0x42] = 0xcd;
    packet[0x43] = 0xab;
    assert(!full_infraimaging_format_consume(&format, packet, sizeof packet));
    assert(format.cache[4] == 0xabcd && format.consumed == 3);
    assert(!memcmp(cache, format.cache, 4 * sizeof *cache));
    puts("INFRAIMAGING_FORMAT_SSYN01_UNCONSUMED_WORD_AND_FULL_U16_FLAGS_PASS");
}

static void forwarded_framing(void)
{
    struct full_infraimaging_format format = {0};
    unsigned char packet[80];
    assert(!full_infraimaging_format_init(&format));
    assert(!full_infraimaging_format_consume(&format, forwarded, sizeof forwarded));
    for (unsigned int offset = 0; offset < 0x40; offset++) {
        memcpy(packet, forwarded, sizeof packet);
        packet[offset] ^= 1;
        unchanged_reject(&format, packet, sizeof packet);
    }
    static const unsigned int pairs[][2] = {
        {0x01000000, 1}, {0x06000000, 0}, {0x02000000, 0}, {0x06000000, 2},
        {0, 0}, {UINT_MAX, 0}, {0x01000000, UINT_MAX}
    };
    for (unsigned int i = 0; i < sizeof pairs / sizeof *pairs; i++) {
        memcpy(packet, forwarded, sizeof packet);
        put32(packet + 4, pairs[i][0]);
        put32(packet + 0x28, pairs[i][1]);
        unchanged_reject(&format, packet, sizeof packet);
    }
    for (unsigned int bytes = 0; bytes < 80; bytes++) {
        unsigned char *short_packet = malloc(bytes ? bytes : 1);
        assert(short_packet);
        memcpy(short_packet, forwarded, bytes);
        unchanged_reject(&format, short_packet, bytes);
        free(short_packet);
    }
    unchanged_reject(&format, forwarded, 81);
    unchanged_reject(&format, forwarded, UINT_MAX);
    puts("INFRAIMAGING_FORMAT_SSYN_VARIANTS_REJECT_ASYMMETRIC_TYPES_AND_BOUNDS_PASS");
}

int main(void)
{
    fresh_init();
    build_packet();
    consume_original();
    full_payload_fields();
    unconsumed_word();
    invalid_framing();
    invalid_lengths();
    invalid_owner();
    independent_copy();
    separate_owners();
    consume_forwarded();
    forwarded_fields();
    forwarded_framing();
    puts("INFRAIMAGING_FORMAT_CASES=13");
    return 0;
}
