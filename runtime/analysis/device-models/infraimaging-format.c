/* SPDX-License-Identifier: MIT */
#include "infraimaging-format.h"
#include <limits.h>
#include <string.h>

_Static_assert(CHAR_BIT == 8 && sizeof(unsigned int) == 4 &&
               sizeof(unsigned long long) == 8, "Sony field widths");

static unsigned int u16(const unsigned char *p)
{
    return p[0] | (unsigned int)p[1] << 8;
}

static unsigned int u32(const unsigned char *p)
{
    return u16(p) | u16(p + 2) << 16;
}

int full_infraimaging_format_init(struct full_infraimaging_format *format)
{
    if (!format || format->initialized) return -1;
    /* Public CP raw fe1070, table e74294[1]; cache is not a zero-BSS guess. */
    *format = (struct full_infraimaging_format){
        .cache = {1, 0, 0, 0, 0}, .initialized = 1,
        .consumed = 0, .payload_fnv64 = 0
    };
    return 0;
}

int full_infraimaging_format_build(unsigned char *out, unsigned int bytes)
{
    /* Raw ced98..cedbc supplies SSYN06 and ETRY type1, not VEF's SSYN01/type0. */
    static const unsigned char packet[FULL_INFRAIMAGING_FORMAT_BYTES] = {
        [0] = 0x53, [1] = 0x53, [2] = 0x59, [3] = 0x4e, [7] = 6,
        [0xc] = 1, [0x10] = 0x20,
        [0x20] = 0x45, [0x21] = 0x54, [0x22] = 0x52, [0x23] = 0x59,
        [0x28] = 1, [0x2c] = 0x40, [0x30] = 0x10,
        [0x40] = 1, [0x48] = 0x80, [0x49] = 7, [0x4c] = 0x38, [0x4d] = 4
    };
    if (!out || bytes != sizeof packet) return -1;
    memcpy(out, packet, sizeof packet);
    return 0;
}

int full_infraimaging_format_consume(struct full_infraimaging_format *format,
                                   const unsigned char *packet, unsigned int bytes)
{
    if (!format || format->initialized != 1 || format->consumed == UINT_MAX ||
        !packet || bytes != FULL_INFRAIMAGING_FORMAT_BYTES) return -1;
    /* shortcut: only audited SSYN06/type1 and forwarded SSYN01/type0, not general SSYN. */
    unsigned int version=u32(packet + 4), type=u32(packet + 0x28);
    if (u32(packet) != 0x4e595353 ||
        !((version == 0x06000000 && type == 1) || (version == 0x01000000 && type == 0)) ||
        u32(packet + 8) || u32(packet + 0xc) != 1 || u32(packet + 0x10) != 0x20 ||
        u32(packet + 0x14) || u32(packet + 0x18) || u32(packet + 0x1c) ||
        u32(packet + 0x20) != 0x59525445 || u32(packet + 0x24) ||
        u32(packet + 0x2c) != 0x40 ||
        u32(packet + 0x30) != 16 || u32(packet + 0x34) ||
        u32(packet + 0x38) || u32(packet + 0x3c)) return -1;

    unsigned char payload[16];
    memcpy(payload, packet + 0x40, sizeof payload);
    /* CP 46f52c..46f54c stores these five words; payload+4 is unconsumed. */
    const unsigned int cache[5] = {
        payload[1], payload[0], u32(payload + 8), u32(payload + 12), u16(payload + 2)
    };
    unsigned long long fnv = 0xcbf29ce484222325ULL;
    for (unsigned int i = 0; i < sizeof payload; i++)
        fnv = (fnv ^ payload[i]) * 0x100000001b3ULL;
    memcpy(format->cache, cache, sizeof cache);
    format->payload_fnv64 = fnv;
    format->consumed++;
    return 0;
}
