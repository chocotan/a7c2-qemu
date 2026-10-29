/* SPDX-License-Identifier: MIT */
#include "cp-parameter-state.h"
#include <errno.h>
#include <string.h>
#include <unistd.h>

#define STATE_MAGIC UINT32_C(0x43503436)

/* BEGIN GENERATED SOURCE TABLE: report/cp-parameter-state/generate.py */
enum field_mode { COPY, SIGN, CONST, BOOL, EQ, ORBOOL };
struct field { uint16_t wire, image; uint8_t width, source_width, mode, condition_zero; uint32_t argument; };
struct slot_model { uint16_t first, count; bool semantic; };
static const struct field fields[] = {
    {0x8,0x690,4,1,COPY,0,UINT32_C(0x0)}, /* slot 0 */
    {0x8,0x934,4,1,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x9,0x938,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 1 */
    {0xa,0x939,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 1 */
    {0xc,0x93a,2,2,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0xe,0x93c,2,2,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x10,0x940,1,1,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x11,0x941,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 1 */
    {0x12,0x942,1,1,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x14,0x944,4,4,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x18,0x948,4,4,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x1c,0x94c,4,4,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x20,0x950,4,4,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x24,0x954,4,4,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x28,0x958,4,4,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x2c,0x95c,4,4,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x30,0x960,4,4,COPY,0,UINT32_C(0x0)}, /* slot 1 */
    {0x8,0x93e,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 2 */
    {0x9,0x93f,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 2 */
    {0x8,0x124,4,1,COPY,0,UINT32_C(0x0)}, /* slot 3 */
    {0x9,0x128,4,1,COPY,0,UINT32_C(0x0)}, /* slot 3 */
    {0xc,0x120,4,4,COPY,0,UINT32_C(0x0)}, /* slot 3 */
    {0x8,0xb2c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 4 */
    {0x8,0xb30,4,1,COPY,0,UINT32_C(0x0)}, /* slot 5 */
    {0x8,0xb34,4,1,COPY,0,UINT32_C(0x0)}, /* slot 6 */
    {0x8,0xb38,4,1,COPY,0,UINT32_C(0x0)}, /* slot 7 */
    {0x8,0xb3c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 8 */
    {0x8,0xb10,4,1,COPY,0,UINT32_C(0x0)}, /* slot 9 */
    {0x9,0xb14,1,1,COPY,0,UINT32_C(0x0)}, /* slot 9 */
    {0xa,0xb15,1,1,COPY,0,UINT32_C(0x0)}, /* slot 9 */
    {0x8,0x2a8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 10 */
    {0x8,0xd2c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 11 */
    {0x8,0xcb8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 12 */
    {0x8,0xcbc,4,1,COPY,0,UINT32_C(0x0)}, /* slot 13 */
    {0x8,0x140,4,1,COPY,0,UINT32_C(0x0)}, /* slot 14 */
    {0x9,0x144,4,1,COPY,0,UINT32_C(0x0)}, /* slot 14 */
    {0xa,0x148,1,1,COPY,0,UINT32_C(0x0)}, /* slot 14 */
    {0xb,0x14c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 14 */
    {0xc,0x150,4,1,COPY,0,UINT32_C(0x0)}, /* slot 14 */
    {0xd,0x154,1,1,COPY,0,UINT32_C(0x0)}, /* slot 14 */
    {0xe,0x158,4,1,COPY,0,UINT32_C(0x0)}, /* slot 14 */
    {0x10,0x15c,4,4,COPY,0,UINT32_C(0x0)}, /* slot 14 */
    {0x8,0xcf8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 16 */
    {0x8,0xd24,4,1,COPY,0,UINT32_C(0x0)}, /* slot 17 */
    {0x8,0x56c,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 19 */
    {0x9,0x570,4,1,COPY,0,UINT32_C(0x0)}, /* slot 19 */
    {0x8,0x568,4,1,COPY,0,UINT32_C(0x0)}, /* slot 20 */
    {0x8,0x6c4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 21 */
    {0x8,0x574,1,1,BOOL,0,UINT32_C(0x0)}, /* slot 24 */
    {0x8,0x575,1,1,BOOL,0,UINT32_C(0x0)}, /* slot 25 */
    {0x8,0x578,4,1,COPY,0,UINT32_C(0x0)}, /* slot 26 */
    {0x8,0x304,4,1,COPY,0,UINT32_C(0x0)}, /* slot 27 */
    {0x9,0x308,4,1,COPY,0,UINT32_C(0x0)}, /* slot 27 */
    {0xa,0x30c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 27 */
    {0xb,0x310,4,1,COPY,0,UINT32_C(0x0)}, /* slot 27 */
    {0xc,0x314,4,1,COPY,0,UINT32_C(0x0)}, /* slot 27 */
    {0xd,0x318,4,1,COPY,0,UINT32_C(0x0)}, /* slot 27 */
    {0xe,0x454,4,1,COPY,0,UINT32_C(0x0)}, /* slot 27 */
    {0xf,0x31c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 27 */
    {0x8,0x160,4,1,COPY,0,UINT32_C(0x0)}, /* slot 28 */
    {0x8,0x324,4,1,COPY,0,UINT32_C(0x0)}, /* slot 29 */
    {0x9,0x328,4,1,COPY,0,UINT32_C(0x0)}, /* slot 29 */
    {0xa,0x32c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 29 */
    {0x8,0x964,4,1,COPY,0,UINT32_C(0x0)}, /* slot 30 */
    {0x8,0x968,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 31 */
    {0x8,0x96c,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 32 */
    {0x8,0xcd2,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 33 */
    {0x8,0x96d,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 34 */
    {0x8,0x96e,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 35 */
    {0x8,0x2c8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 36 */
    {0x8,0x970,4,1,COPY,0,UINT32_C(0x0)}, /* slot 37 */
    {0x8,0x974,4,1,COPY,0,UINT32_C(0x0)}, /* slot 38 */
    {0x8,0x6ec,4,1,COPY,0,UINT32_C(0x0)}, /* slot 39 */
    {0x8,0x2c0,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 40 */
    {0x9,0x2c4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 40 */
    {0xa,0x2bf,1,1,COPY,0,UINT32_C(0x0)}, /* slot 40 */
    {0x8,0xcc4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 41 */
    {0x8,0xd30,4,1,COPY,0,UINT32_C(0x0)}, /* slot 42 */
    {0x9,0xd34,4,1,COPY,0,UINT32_C(0x0)}, /* slot 42 */
    {0x8,0x6f0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 43 */
    {0x8,0x335,1,1,COPY,0,UINT32_C(0x0)}, /* slot 44 */
    {0x8,0x336,1,1,COPY,0,UINT32_C(0x0)}, /* slot 45 */
    {0x8,0x978,4,1,COPY,0,UINT32_C(0x0)}, /* slot 46 */
    {0x8,0xd18,4,1,COPY,0,UINT32_C(0x0)}, /* slot 47 */
    {0x8,0xd20,4,1,COPY,0,UINT32_C(0x0)}, /* slot 48 */
    {0x8,0x250,4,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x9,0x254,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0xa,0x255,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0xb,0x256,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0xc,0x257,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0xd,0x258,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0xe,0x25c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0xf,0x260,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x10,0x261,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x11,0x262,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x12,0x263,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x13,0x264,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x14,0x265,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x15,0x266,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x16,0x267,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 49 */
    {0x17,0x268,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 49 */
    {0x18,0x26c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x19,0x270,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 49 */
    {0x1a,0x271,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x1b,0x272,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x1c,0x273,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x1d,0x274,4,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x1e,0x278,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x1f,0x279,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 49 */
    {0x20,0x27a,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x21,0x27b,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 49 */
    {0x22,0x27c,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 49 */
    {0x23,0x27d,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x24,0x27e,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x25,0x27f,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x26,0x280,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 49 */
    {0x27,0x284,4,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x28,0x288,4,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x2a,0x28c,2,2,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x2c,0x28e,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x2d,0x28f,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x2e,0x290,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x2f,0x291,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x30,0x292,2,2,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x32,0x294,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x33,0x295,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x34,0x296,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x35,0x297,1,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x36,0x24c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 49 */
    {0x8,0x2d4,1,1,COPY,0,UINT32_C(0x0)}, /* slot 51 */
    {0x8,0x2e8,1,1,COPY,0,UINT32_C(0x0)}, /* slot 52 */
    {0x8,0x2cc,1,1,COPY,0,UINT32_C(0x0)}, /* slot 53 */
    {0x8,0xd00,4,1,COPY,0,UINT32_C(0x0)}, /* slot 54 */
    {0x8,0xd04,4,1,COPY,0,UINT32_C(0x0)}, /* slot 55 */
    {0x8,0xd1c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 56 */
    {0x8,0xd28,4,1,COPY,0,UINT32_C(0x0)}, /* slot 57 */
    {0x8,0x33c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 58 */
    {0x8,0x6f8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 59 */
    {0x9,0x6fc,4,1,COPY,0,UINT32_C(0x0)}, /* slot 59 */
    {0x8,0x700,4,1,COPY,0,UINT32_C(0x0)}, /* slot 60 */
    {0x8,0x58c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 61 */
    {0x8,0x704,4,1,COPY,0,UINT32_C(0x0)}, /* slot 62 */
    {0x8,0x590,4,1,COPY,0,UINT32_C(0x0)}, /* slot 63 */
    {0x8,0x34c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 64 */
    {0x9,0x350,4,1,COPY,0,UINT32_C(0x0)}, /* slot 64 */
    {0x8,0x354,4,1,COPY,0,UINT32_C(0x0)}, /* slot 65 */
    {0x8,0xbb8,1,1,EQ,0,UINT32_C(0x1)}, /* slot 67 */
    {0x8,0xb48,4,1,COPY,0,UINT32_C(0x0)}, /* slot 68 */
    {0x8,0x204,4,1,COPY,0,UINT32_C(0x0)}, /* slot 69 */
    {0x8,0x20c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 70 */
    {0x8,0x1fc,4,1,COPY,0,UINT32_C(0x0)}, /* slot 71 */
    {0x8,0x5ac,4,1,COPY,0,UINT32_C(0x0)}, /* slot 72 */
    {0x8,0x337,1,1,COPY,0,UINT32_C(0x0)}, /* slot 74 */
    {0x8,0x358,1,1,COPY,0,UINT32_C(0x0)}, /* slot 75 */
    {0x8,0x1b0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 76 */
    {0x8,0x1e4,1,1,BOOL,0,UINT32_C(0x0)}, /* slot 77 */
    {0x8,0xbd2,1,1,EQ,0,UINT32_C(0x1)}, /* slot 78 */
    {0x8,0x2d0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 79 */
    {0x8,0x35c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 80 */
    {0x8,0xb51,1,1,COPY,0,UINT32_C(0x0)}, /* slot 81 */
    {0x8,0x74c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 82 */
    {0x8,0x750,4,1,COPY,0,UINT32_C(0x0)}, /* slot 83 */
    {0x8,0x364,4,1,COPY,0,UINT32_C(0x0)}, /* slot 85 */
    {0x8,0x758,4,1,COPY,0,UINT32_C(0x0)}, /* slot 86 */
    {0x8,0x75c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 87 */
    {0x8,0x368,4,1,COPY,0,UINT32_C(0x0)}, /* slot 88 */
    {0x8,0x764,4,1,COPY,0,UINT32_C(0x0)}, /* slot 89 */
    {0x8,0x768,4,1,COPY,0,UINT32_C(0x0)}, /* slot 90 */
    {0xc,0x76c,4,4,COPY,0,UINT32_C(0x0)}, /* slot 90 */
    {0x10,0x770,4,4,COPY,0,UINT32_C(0x0)}, /* slot 90 */
    {0x8,0xb40,4,1,COPY,0,UINT32_C(0x0)}, /* slot 91 */
    {0x8,0x5b0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 92 */
    {0x8,0x370,2,2,COPY,0,UINT32_C(0x0)}, /* slot 93 */
    {0xa,0x374,4,1,COPY,0,UINT32_C(0x0)}, /* slot 93 */
    {0xb,0x378,4,1,COPY,0,UINT32_C(0x0)}, /* slot 93 */
    {0x8,0x164,4,1,COPY,0,UINT32_C(0x0)}, /* slot 94 */
    {0x8,0x37c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 95 */
    {0x8,0x380,4,1,COPY,0,UINT32_C(0x0)}, /* slot 96 */
    {0x8,0x724,4,1,COPY,0,UINT32_C(0x0)}, /* slot 97 */
    {0x8,0x754,4,1,COPY,0,UINT32_C(0x0)}, /* slot 98 */
    {0x8,0x77c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 99 */
    {0x8,0x6c0,1,1,BOOL,0,UINT32_C(0x0)}, /* slot 100 */
    {0x8,0x780,4,1,COPY,0,UINT32_C(0x0)}, /* slot 101 */
    {0x8,0xd0c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 102 */
    {0x8,0xb53,1,1,COPY,0,UINT32_C(0x0)}, /* slot 103 */
    {0x8,0x3a0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 104 */
    {0x8,0x3a4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 105 */
    {0x8,0xb54,4,1,COPY,0,UINT32_C(0x0)}, /* slot 106 */
    {0x8,0x788,4,1,COPY,0,UINT32_C(0x0)}, /* slot 107 */
    {0x8,0xb64,4,1,COPY,0,UINT32_C(0x0)}, /* slot 108 */
    {0x8,0xb58,4,1,COPY,0,UINT32_C(0x0)}, /* slot 108 */
    {0x9,0xb68,4,1,COPY,0,UINT32_C(0x0)}, /* slot 108 */
    {0x9,0xb5c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 108 */
    {0xa,0xb6c,2,2,COPY,0,UINT32_C(0x0)}, /* slot 108 */
    {0xa,0xb60,2,2,COPY,0,UINT32_C(0x0)}, /* slot 108 */
    {0x8,0xb70,4,1,COPY,0,UINT32_C(0x0)}, /* slot 109 */
    {0x8,0xb58,4,1,COPY,0,UINT32_C(0x0)}, /* slot 109 */
    {0x9,0xb74,4,1,COPY,0,UINT32_C(0x0)}, /* slot 109 */
    {0x9,0xb5c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 109 */
    {0xa,0xb78,2,2,COPY,0,UINT32_C(0x0)}, /* slot 109 */
    {0xa,0xb60,2,2,COPY,0,UINT32_C(0x0)}, /* slot 109 */
    {0x8,0xd44,4,1,COPY,0,UINT32_C(0x0)}, /* slot 110 */
    {0x8,0x3b4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 111 */
    {0xc,0x3b8,4,4,COPY,0,UINT32_C(0x0)}, /* slot 111 */
    {0x10,0x3bc,2,2,COPY,0,UINT32_C(0x0)}, /* slot 111 */
    {0x8,0x384,4,1,COPY,0,UINT32_C(0x0)}, /* slot 112 */
    {0x8,0xce8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 113 */
    {0x8,0xb24,4,1,COPY,0,UINT32_C(0x0)}, /* slot 114 */
    {0x8,0x168,4,1,COPY,0,UINT32_C(0x0)}, /* slot 115 */
    {0x8,0xb7c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 116 */
    {0x8,0xb80,1,1,COPY,0,UINT32_C(0x0)}, /* slot 117 */
    {0x8,0x78c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 118 */
    {0x8,0xd48,4,1,COPY,0,UINT32_C(0x0)}, /* slot 119 */
    {0x8,0x3be,1,1,COPY,0,UINT32_C(0x0)}, /* slot 121 */
    {0x9,0x3bf,1,1,COPY,0,UINT32_C(0x0)}, /* slot 121 */
    {0xa,0x3c0,1,1,COPY,0,UINT32_C(0x0)}, /* slot 121 */
    {0xb,0x3c1,1,1,COPY,0,UINT32_C(0x0)}, /* slot 121 */
    {0xc,0x3c2,1,1,COPY,0,UINT32_C(0x0)}, /* slot 121 */
    {0xd,0x3c3,1,1,COPY,0,UINT32_C(0x0)}, /* slot 121 */
    {0x8,0x3c4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 122 */
    {0x8,0x790,4,1,COPY,0,UINT32_C(0x0)}, /* slot 123 */
    {0x8,0x1b4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 124 */
    {0x8,0x3d4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 125 */
    {0x8,0x1b8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 126 */
    {0x8,0xba9,1,1,BOOL,0,UINT32_C(0x0)}, /* slot 128 */
    {0x8,0xbac,4,1,BOOL,0,UINT32_C(0x0)}, /* slot 129 */
    {0x8,0xbf8,4,1,BOOL,0,UINT32_C(0x0)}, /* slot 129 */
    {0x8,0xbb0,1,1,BOOL,0,UINT32_C(0x0)}, /* slot 130 */
    {0x8,0xbb1,1,1,BOOL,0,UINT32_C(0x0)}, /* slot 131 */
    {0x8,0xa04,4,1,COPY,0,UINT32_C(0x0)}, /* slot 132 */
    {0x8,0x96a,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 133 */
    {0x8,0x969,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 134 */
    {0x8,0x96b,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 135 */
    {0x8,0xcd3,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 136 */
    {0x8,0xcd4,1,1,SIGN,0,UINT32_C(0x0)}, /* slot 137 */
    {0x8,0xaf0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 139 */
    {0x8,0xaf4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 140 */
    {0x8,0xbe8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 141 */
    {0x8,0xbf0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 142 */
    {0x8,0x7b4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 143 */
    {0x8,0x3d8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 144 */
    {0x8,0x7b8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 147 */
    {0x8,0xcec,4,1,COPY,0,UINT32_C(0x0)}, /* slot 148 */
    {0x8,0x558,1,1,COPY,0,UINT32_C(0x0)}, /* slot 149 */
    {0x8,0x36c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 150 */
    {0x8,0x48,4,1,COPY,0,UINT32_C(0x0)}, /* slot 151 */
    {0x9,0x4c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 151 */
    {0xa,0x50,4,1,COPY,0,UINT32_C(0x0)}, /* slot 151 */
    {0x8,0x54,4,1,COPY,0,UINT32_C(0x0)}, /* slot 152 */
    {0x8,0x58,4,1,COPY,0,UINT32_C(0x0)}, /* slot 153 */
    {0x8,0x5b4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 154 */
    {0x8,0x2f8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 155 */
    {0x0,0x2f4,4,0,CONST,1,UINT32_C(0x0)}, /* slot 155 */
    {0x8,0xfc,4,1,COPY,0,UINT32_C(0x0)}, /* slot 156 */
    {0x8,0x300,4,1,COPY,0,UINT32_C(0x0)}, /* slot 157 */
    {0x8,0x3dc,4,1,COPY,0,UINT32_C(0x0)}, /* slot 159 */
    {0x8,0x3e0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 160 */
    {0x8,0x1f8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 161 */
    {0x8,0x3e4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 162 */
    {0x8,0x7bc,4,1,COPY,0,UINT32_C(0x0)}, /* slot 163 */
    {0x8,0x7c0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 164 */
    {0x8,0x820,1,1,EQ,0,UINT32_C(0x1)}, /* slot 165 */
    {0x8,0x3e8,4,4,COPY,0,UINT32_C(0x0)}, /* slot 166 */
    {0xc,0x3ec,2,2,COPY,0,UINT32_C(0x0)}, /* slot 166 */
    {0xe,0x3f0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 166 */
    {0x10,0x3f4,4,4,COPY,0,UINT32_C(0x0)}, /* slot 166 */
    {0x14,0x3f8,2,2,COPY,0,UINT32_C(0x0)}, /* slot 166 */
    {0x16,0x3fc,4,1,COPY,0,UINT32_C(0x0)}, /* slot 166 */
    {0x17,0x400,4,1,COPY,0,UINT32_C(0x0)}, /* slot 166 */
    {0x8,0x64,1,1,BOOL,0,UINT32_C(0x0)}, /* slot 167 */
    {0x9,0x65,1,1,BOOL,0,UINT32_C(0x0)}, /* slot 167 */
    {0xb,0x66,1,1,ORBOOL,0,UINT32_C(0xa)}, /* slot 167 */
    {0xc,0x67,1,1,ORBOOL,0,UINT32_C(0xa)}, /* slot 167 */
    {0x8,0xc8,1,1,BOOL,0,UINT32_C(0x0)}, /* slot 169 */
    {0x8,0x42c,4,4,COPY,0,UINT32_C(0x0)}, /* slot 171 */
    {0xc,0x430,4,4,COPY,0,UINT32_C(0x0)}, /* slot 171 */
    {0x8,0x1bc,4,1,COPY,0,UINT32_C(0x0)}, /* slot 172 */
    {0xa,0x1c0,2,2,COPY,0,UINT32_C(0x0)}, /* slot 172 */
    {0x8,0x821,1,1,EQ,0,UINT32_C(0x1)}, /* slot 173 */
    {0x8,0x409,1,1,COPY,0,UINT32_C(0x0)}, /* slot 175 */
    {0x8,0x40c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 176 */
    {0x9,0x410,1,1,COPY,0,UINT32_C(0x0)}, /* slot 176 */
    {0x8,0xb0c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 177 */
    {0x8,0xb84,4,1,COPY,0,UINT32_C(0x0)}, /* slot 179 */
    {0x9,0xb88,4,1,COPY,0,UINT32_C(0x0)}, /* slot 179 */
    {0xa,0xb8c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 179 */
    {0xb,0xb90,4,1,COPY,0,UINT32_C(0x0)}, /* slot 179 */
    {0xc,0xb94,4,1,COPY,0,UINT32_C(0x0)}, /* slot 179 */
    {0xd,0xb98,4,1,COPY,0,UINT32_C(0x0)}, /* slot 179 */
    {0xe,0xb9c,4,1,COPY,0,UINT32_C(0x0)}, /* slot 179 */
    {0x8,0xd4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 180 */
    {0x8,0xcfc,4,1,COPY,0,UINT32_C(0x0)}, /* slot 181 */
    {0x8,0x414,4,1,COPY,0,UINT32_C(0x0)}, /* slot 182 */
    {0x8,0xba0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 183 */
    {0x8,0x131,1,1,COPY,0,UINT32_C(0x0)}, /* slot 184 */
    {0x8,0xba4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 187 */
    {0x8,0xca0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 188 */
    {0x9,0xca4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 188 */
    {0xa,0xca8,4,1,COPY,0,UINT32_C(0x0)}, /* slot 188 */
    {0xb,0xcac,4,1,COPY,0,UINT32_C(0x0)}, /* slot 188 */
    {0xc,0xcb0,4,1,COPY,0,UINT32_C(0x0)}, /* slot 188 */
    {0xd,0xcb4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 188 */
    {0x8,0x1c4,4,1,COPY,0,UINT32_C(0x0)}, /* slot 189 */
};
static const struct slot_model models[CP_PARAMETER_BATCH_SLOTS] = {
    {0,1,true}, /* 0: 4002 -> 8dad14 */
    {1,16,true}, /* 1: 4006 -> 354900 */
    {17,2,true}, /* 2: 4007 -> 354a04 */
    {19,3,false}, /* 3: 4008 -> 354a5c */
    {22,1,true}, /* 4: 400a -> 354bf0 */
    {23,1,true}, /* 5: 400b -> 354c38 */
    {24,1,true}, /* 6: 400c -> 354c80 */
    {25,1,true}, /* 7: 400d -> 354cc8 */
    {26,1,true}, /* 8: 400e -> 354d0c */
    {27,3,true}, /* 9: 400f -> 354d50 */
    {30,1,true}, /* 10: 4010 -> 354dac */
    {31,1,true}, /* 11: 4011 -> 354df4 */
    {32,1,true}, /* 12: 4012 -> 3555c0 */
    {33,1,true}, /* 13: 4013 -> 355608 */
    {34,8,true}, /* 14: 4015 -> 355848 */
    {42,0,false}, /* 15: 4016 -> 354e44 */
    {42,1,true}, /* 16: 4017 -> 354ebc */
    {43,1,true}, /* 17: 4019 -> 8dadca */
    {44,0,false}, /* 18: 401a -> 354f04 */
    {44,2,true}, /* 19: 401d -> 3550fc */
    {46,1,true}, /* 20: 401e -> 355154 */
    {47,1,true}, /* 21: 4021 -> 355e34 */
    {48,0,false}, /* 22: 4022 -> 8daaa4 */
    {48,0,false}, /* 23: 4023 -> 355edc */
    {48,1,true}, /* 24: 4024 -> 3559e0 */
    {49,1,true}, /* 25: 4025 -> 355a44 */
    {50,1,true}, /* 26: 4026 -> 355aa0 */
    {51,8,true}, /* 27: 4029 -> 355c20 */
    {59,1,true}, /* 28: 402a -> 355994 */
    {60,3,true}, /* 29: 402e -> 356388 */
    {63,1,true}, /* 30: 402f -> 356484 */
    {64,1,true}, /* 31: 4030 -> 3564cc */
    {65,1,true}, /* 32: 4031 -> 356518 */
    {66,1,true}, /* 33: 4032 -> 356564 */
    {67,1,true}, /* 34: 4033 -> 356720 */
    {68,1,true}, /* 35: 4034 -> 35676c */
    {69,1,true}, /* 36: 403a -> 355208 */
    {70,1,true}, /* 37: 4041 -> 3563e4 */
    {71,1,true}, /* 38: 4044 -> 356434 */
    {72,1,true}, /* 39: 4047 -> 3567b4 */
    {73,3,true}, /* 40: 4048 -> 3551a8 */
    {76,1,true}, /* 41: 4049 -> 35690c */
    {77,2,true}, /* 42: 404a -> 356954 */
    {79,1,true}, /* 43: 404c -> 356a1c */
    {80,1,true}, /* 44: 404d -> 35524c */
    {81,1,true}, /* 45: 404f -> 35529c */
    {82,1,true}, /* 46: 4050 -> 356b14 */
    {83,1,true}, /* 47: 4051 -> 356bb0 */
    {84,1,true}, /* 48: 4052 -> 356c00 */
    {85,44,true}, /* 49: 4056 -> 8dae36 */
    {129,0,false}, /* 50: 4059 -> 35535c */
    {129,1,true}, /* 51: 405a -> 3553c0 */
    {130,1,true}, /* 52: 405b -> 35540c */
    {131,1,true}, /* 53: 405c -> 355458 */
    {132,1,true}, /* 54: 405d -> 356a6c */
    {133,1,true}, /* 55: 405e -> 356ac0 */
    {134,1,true}, /* 56: 405f -> 356c50 */
    {135,1,true}, /* 57: 4060 -> 8dae00 */
    {136,1,true}, /* 58: 4061 -> 356cf8 */
    {137,2,true}, /* 59: 4062 -> 356ca0 */
    {139,1,true}, /* 60: 4064 -> 356d40 */
    {140,1,true}, /* 61: 4066 -> 356e80 */
    {141,1,true}, /* 62: 4067 -> 356ed0 */
    {142,1,true}, /* 63: 406e -> 356f68 */
    {143,2,true}, /* 64: 4078 -> 35793c */
    {145,1,true}, /* 65: 4079 -> 357998 */
    {146,0,false}, /* 66: 407a -> 3579e4 */
    {146,1,true}, /* 67: 407c -> 3547d4 */
    {147,1,true}, /* 68: 407d -> 357ad8 */
    {148,1,false}, /* 69: 407e -> 357b28 */
    {149,1,false}, /* 70: 407f -> 357b7c */
    {150,1,false}, /* 71: 4080 -> 357bd4 */
    {151,1,true}, /* 72: 4082 -> 357c2c */
    {152,0,false}, /* 73: 4083 -> 35482c */
    {152,1,true}, /* 74: 4084 -> 357c7c */
    {153,1,true}, /* 75: 4086 -> 357db8 */
    {154,1,true}, /* 76: 4088 -> 357e58 */
    {155,1,true}, /* 77: 4089 -> 354710 */
    {156,1,true}, /* 78: 408c -> 357f38 */
    {157,1,true}, /* 79: 408d -> 355bd8 */
    {158,1,true}, /* 80: 4093 -> 357fe8 */
    {159,1,false}, /* 81: 4097 -> 8db234 */
    {160,1,true}, /* 82: 409a -> 358278 */
    {161,1,true}, /* 83: 40a1 -> 8db332 */
    {162,0,false}, /* 84: 40a2 -> 35858c */
    {162,1,true}, /* 85: 40a4 -> 356d84 */
    {163,1,true}, /* 86: 40a6 -> 358644 */
    {164,1,true}, /* 87: 40a7 -> 35869c */
    {165,1,true}, /* 88: 40a9 -> 356dcc */
    {166,1,true}, /* 89: 40aa -> 3582c4 */
    {167,3,true}, /* 90: 40ab -> 358310 */
    {170,1,false}, /* 91: 40ac -> 358818 */
    {171,1,true}, /* 92: 40ad -> 358864 */
    {172,3,true}, /* 93: 40ae -> 358c00 */
    {175,1,true}, /* 94: 40af -> 3588b8 */
    {176,1,true}, /* 95: 40b0 -> 358a78 */
    {177,1,true}, /* 96: 40b1 -> 358ac4 */
    {178,1,true}, /* 97: 40b2 -> 8db368 */
    {179,1,true}, /* 98: 40b3 -> 8db39e */
    {180,1,true}, /* 99: 40b4 -> 358b14 */
    {181,1,true}, /* 100: 40b5 -> 358b54 */
    {182,1,true}, /* 101: 40b6 -> 358bac */
    {183,1,true}, /* 102: 40c2 -> 3593f0 */
    {184,1,true}, /* 103: 40c3 -> 35943c */
    {185,1,true}, /* 104: 40c4 -> 358f80 */
    {186,1,true}, /* 105: 40c5 -> 358fd4 */
    {187,1,true}, /* 106: 40c6 -> 359488 */
    {188,1,true}, /* 107: 40c7 -> 3594d8 */
    {189,6,true}, /* 108: 40ca -> 359528 */
    {195,6,true}, /* 109: 40cb -> 3595a0 */
    {201,1,true}, /* 110: 40cc -> 359618 */
    {202,3,true}, /* 111: 40cd -> 359664 */
    {205,1,true}, /* 112: 40ce -> 3596cc */
    {206,1,true}, /* 113: 40d2 -> 3597b4 */
    {207,1,true}, /* 114: 40d3 -> 3597fc */
    {208,1,true}, /* 115: 40d4 -> 358910 */
    {209,1,true}, /* 116: 40d5 -> 359850 */
    {210,1,true}, /* 117: 40d6 -> 3598a4 */
    {211,1,true}, /* 118: 40d7 -> 8db3d4 */
    {212,1,true}, /* 119: 40d8 -> 3598f4 */
    {213,0,false}, /* 120: 40d9 -> 359944 */
    {213,6,true}, /* 121: 40db -> 359a00 */
    {219,1,true}, /* 122: 40dc -> 359b40 */
    {220,1,true}, /* 123: 40e3 -> 359e40 */
    {221,1,true}, /* 124: 40e4 -> 359d44 */
    {222,1,true}, /* 125: 40e6 -> 359da0 */
    {223,1,true}, /* 126: 40e7 -> 359df0 */
    {224,0,false}, /* 127: 40e8 -> 35907c */
    {224,1,true}, /* 128: 40e9 -> 359164 */
    {225,2,true}, /* 129: 40ea -> 3591c0 */
    {227,1,true}, /* 130: 40eb -> 359218 */
    {228,1,true}, /* 131: 40ec -> 35927c */
    {229,1,true}, /* 132: 40f1 -> 35a7e0 */
    {230,1,true}, /* 133: 40f3 -> 3565b0 */
    {231,1,true}, /* 134: 40f4 -> 3565fc */
    {232,1,true}, /* 135: 40f5 -> 356644 */
    {233,1,true}, /* 136: 40f6 -> 35668c */
    {234,1,true}, /* 137: 40f7 -> 3566d8 */
    {235,0,false}, /* 138: 40f8 -> 359f3c */
    {235,1,true}, /* 139: 40fb -> 359f9c */
    {236,1,true}, /* 140: 40fc -> 359fe8 */
    {237,1,true}, /* 141: 40fd -> 35a03c */
    {238,1,true}, /* 142: 40ff -> 35a0d8 */
    {239,1,true}, /* 143: 4100 -> 35a244 */
    {240,1,true}, /* 144: 4101 -> 35a29c */
    {241,0,false}, /* 145: 4103 -> 35a2f4 */
    {241,0,true}, /* 146: 4104 -> 35a4b4 */
    {241,1,true}, /* 147: 4105 -> 35a508 */
    {242,1,true}, /* 148: 4137 -> 35ba7c */
    {243,1,true}, /* 149: 4138 -> 35a788 */
    {244,1,true}, /* 150: 413a -> 35a8a0 */
    {245,3,true}, /* 151: 413b -> 35a944 */
    {248,1,true}, /* 152: 413c -> 35a8f0 */
    {249,1,true}, /* 153: 413d -> 8db48c */
    {250,1,true}, /* 154: 413e -> 35a838 */
    {251,2,true}, /* 155: 413f -> 35aa04 */
    {253,1,true}, /* 156: 4141 -> 356340 */
    {254,1,true}, /* 157: 4142 -> 35aabc */
    {255,0,false}, /* 158: 4143 -> 35bd80 */
    {255,1,true}, /* 159: 4145 -> 35becc */
    {256,1,true}, /* 160: 4146 -> 35bf20 */
    {257,1,true}, /* 161: 4148 -> 35bf74 */
    {258,1,true}, /* 162: 4149 -> 35c314 */
    {259,1,true}, /* 163: 414b -> 35bfc0 */
    {260,1,true}, /* 164: 414c -> 35c00c */
    {261,1,true}, /* 165: 4150 -> 35c060 */
    {262,7,true}, /* 166: 4151 -> 8db508 */
    {269,4,true}, /* 167: 4154 -> 35c4a4 */
    {273,0,false}, /* 168: 4155 -> 35c54c */
    {273,1,true}, /* 169: 4156 -> 35c6a8 */
    {274,0,false}, /* 170: 4157 -> 8db56e */
    {274,2,true}, /* 171: 4158 -> 355d08 */
    {276,2,true}, /* 172: 4159 -> 35c824 */
    {278,1,true}, /* 173: 415b -> 35c7c0 */
    {279,0,false}, /* 174: 415f -> 35a358 */
    {279,1,true}, /* 175: 4161 -> 35c924 */
    {280,2,true}, /* 176: 4162 -> 35c97c */
    {282,1,true}, /* 177: 4163 -> 35c9e4 */
    {283,0,true}, /* 178: 4164 -> 8db5d4 */
    {283,7,true}, /* 179: 4165 -> 8db5d8 */
    {290,1,true}, /* 180: 4166 -> 35ca88 */
    {291,1,true}, /* 181: 4167 -> 35cad0 */
    {292,1,true}, /* 182: 4169 -> 35cbe4 */
    {293,1,true}, /* 183: 416c -> 35cc40 */
    {294,1,true}, /* 184: 4170 -> 35594c */
    {295,0,true}, /* 185: 4172 -> 8daa9c */
    {295,0,true}, /* 186: 4173 -> 8daaa0 */
    {295,1,true}, /* 187: 4174 -> 35ca3c */
    {296,6,true}, /* 188: 4176 -> 35cd38 */
    {302,1,true}, /* 189: 4177 -> 35cdc8 */
};
/* END GENERATED SOURCE TABLE */

/* Public CP354768, independent of CP8da08c's fixed 190 slots. */
static const struct field zoom_fields[] = {
    {0x9,0x698,1,1,COPY,0,UINT32_C(0x0)}, /* zoom_speed */
    {0x8,0x69c,4,1,COPY,0,UINT32_C(0x0)}, /* zoom_drive */
    {0xa,0x6a0,4,1,COPY,0,UINT32_C(0x0)}, /* zoom_trigger */
    {0xb,0x6a4,1,1,COPY,0,UINT32_C(0x0)}, /* zoom_speed_movie_rec */
};

#include "cp-parameter-common-init.inc"
#include "cp-parameter-default-init.inc"
_Static_assert(sizeof(default_init_values)==CP_PARAMETER_STATE_DEFAULT_LOCAL_BYTES,
               "default initializer source coverage");
_Static_assert(sizeof(common_init_values)==CP_PARAMETER_STATE_COMMON_LOCAL_BYTES,
               "common initializer source coverage");

static bool span_valid(const void *p, size_t n) {
    return p && (uintptr_t)p <= UINTPTR_MAX - n;
}

static bool overlaps(const void *a, size_t na, const void *b, size_t nb) {
    return (uintptr_t)a < (uintptr_t)b + nb &&
           (uintptr_t)b < (uintptr_t)a + na;
}

static bool owner_valid(const struct cp_parameter_state *s) {
    return span_valid(s, sizeof(*s)) &&
           (uintptr_t)s % _Alignof(struct cp_parameter_state) == 0;
}

static uint32_t decode(const unsigned char *p, const struct field *f) {
    uint32_t value = 0;
    if (f->mode == CONST) return f->argument;
    for (unsigned i = 0; i < f->source_width; i++)
        value |= (uint32_t)p[f->wire + i] << (i * 8u);
    if (f->mode == SIGN && f->source_width < 4u &&
        (value & (UINT32_C(1) << (f->source_width * 8u - 1u))))
        value |= UINT32_MAX << (f->source_width * 8u);
    if (f->mode == BOOL) value = value != 0;
    if (f->mode == EQ) value = value == f->argument;
    if (f->mode == ORBOOL) value = value != 0 || p[f->argument] != 0;
    return value;
}

static void apply_fields(struct cp_parameter_state *s, const unsigned char *p,
                         const struct field *table, size_t count) {
    for (size_t j = 0; j < count; j++) {
        const struct field *f = &table[j];
        if (f->condition_zero && p[8] != 0) continue;
        uint32_t value = decode(p, f);
        for (unsigned k = 0; k < f->width; k++) {
            size_t offset = (size_t)f->image + k;
            s->bytes[offset] = (unsigned char)(value >> (k * 8u));
            s->known_mask[offset / 8u] |= (unsigned char)(1u << (offset % 8u));
        }
    }
}

int cp_parameter_state_init(struct cp_parameter_state *s, bool enabled) {
    if (!owner_valid(s)) return -EINVAL;
    memset(s, 0, sizeof(*s));
    s->magic = STATE_MAGIC;
    return cp_parameter_batch_init(&s->batch, enabled);
}

int cp_parameter_state_consume_reset_store(struct cp_parameter_state *s) {
    const size_t offset = CP_PARAMETER_STATE_OVERRIDE_MODE_OFFSET;
    if (!owner_valid(s) || s->magic != STATE_MAGIC) return -EINVAL;
    if (s->batch.owner_pid != getpid()) return -ECHILD;
    if (!s->batch.enabled) return -EACCES;
    _Static_assert(CP_PARAMETER_STATE_OVERRIDE_MODE_OFFSET % 8u == 0, "STRD mask byte");
    if (s->batch.staged || s->known_mask[offset / 8u]) return -EBUSY;
    /* CP8db6aa/ac/d6: r4=P, r5=0, STRD r5,r5,[r4,#1c8]. */
    memset(s->bytes + offset, 0, 8);
    s->known_mask[offset / 8u] = 0xff;
    return 0;
}

int cp_parameter_state_consume_common_stores(struct cp_parameter_state *s) {
    if (!owner_valid(s) || s->magic != STATE_MAGIC) return -EINVAL;
    if (s->batch.owner_pid != getpid()) return -ECHILD;
    if (!s->batch.enabled) return -EACCES;
    if (s->batch.staged) return -EBUSY;
    for (size_t i=0; i<sizeof(s->known_mask); ++i)
        if (s->known_mask[i]) return -EBUSY;
    for (size_t i=0; i<sizeof(common_init_ranges)/sizeof(common_init_ranges[0]); ++i) {
        const struct common_init_range *r=&common_init_ranges[i];
        memcpy(s->bytes+r->offset,common_init_values+r->data,r->bytes);
        for (size_t j=r->offset; j<(size_t)r->offset+r->bytes; ++j)
            s->known_mask[j/8u] |= (unsigned char)(1u<<(j%8u));
    }
    s->common_stores_consumed = 1;
    return 0;
}

int cp_parameter_state_consume_default_stores(struct cp_parameter_state *s,
    const struct cp_parameter_import *decision) {
    unsigned char expected[CP_PARAMETER_STATE_KNOWN_BYTES]={0};
    if(!owner_valid(s) || s->magic!=STATE_MAGIC || !span_valid(decision,sizeof(*decision)) ||
       (uintptr_t)decision%_Alignof(struct cp_parameter_import) ||
       overlaps(s,sizeof(*s),decision,sizeof(*decision)))return -EINVAL;
    if(s->batch.owner_pid!=getpid())return -ECHILD;
    if(!s->batch.enabled)return -EACCES;
    if(s->batch.staged)return -EBUSY;
    if(decision->properties_consumed!=1 || decision->defaults_selected!=1 || decision->import_selected!=0 ||
       decision->stage_fnv1a64!=CP_PROPERTY_STAGE_FNV1A64 || (decision->source_sequence&1u) ||
       (decision->origin!=CP_START_STATE_ORIGIN_VIRTUAL_SOURCE && decision->origin!=CP_START_STATE_ORIGIN_HOST_TEST) ||
       decision->header!=0 || decision->flags!=0)return -ENODATA;
    for(size_t i=0;i<sizeof(common_init_ranges)/sizeof(common_init_ranges[0]);++i) {
        const struct common_init_range *r=&common_init_ranges[i];
        if(memcmp(s->bytes+r->offset,common_init_values+r->data,r->bytes))return -EBUSY;
        for(size_t j=r->offset;j<(size_t)r->offset+r->bytes;++j)
            expected[j/8u]|=(unsigned char)(1u<<(j%8u));
    }
    if(memcmp(expected,s->known_mask,sizeof(expected)))return -EBUSY;
    for(size_t i=0;i<sizeof(default_init_ranges)/sizeof(default_init_ranges[0]);++i) {
        const struct default_init_range *r=&default_init_ranges[i];
        memcpy(s->bytes+r->offset,default_init_values+r->data,r->bytes);
        for(size_t j=r->offset;j<(size_t)r->offset+r->bytes;++j)
            s->known_mask[j/8u]|=(unsigned char)(1u<<(j%8u));
    }
    s->default_stores_consumed = 1;
    return 0;
}

int cp_parameter_state_consume(struct cp_parameter_state *s, uint32_t source,
    uint32_t target, const void *input, size_t size) {
    struct cp_parameter_state next;
    int rc;
    bool complete = true;
    if (!owner_valid(s) || !span_valid(input, size)) return -EINVAL;
    if (s->magic != STATE_MAGIC) return -EINVAL;
    if (overlaps(input, size, s, sizeof(*s))) return -EINVAL;
    memcpy(&next, s, sizeof(next));
    rc = cp_parameter_batch_stage(&next.batch, source, target, input, size);
    if (rc < 0) return rc;
    /* shortcut: unclosed handlers leave their entire local write set unknown;
     * extend the pinned offline table when their old-state/callee logic closes. */
    for (size_t slot = 0; slot < CP_PARAMETER_BATCH_SLOTS; slot++) {
        const struct slot_model *m = &models[slot];
        const unsigned char *p = next.batch.bytes + cp_parameter_batch_slots[slot].offset;
        uint64_t bit = UINT64_C(1) << (slot % 64u);
        apply_fields(&next, p, fields + m->first, m->count);
        if (m->count) next.config_consumed[slot / 64u] |= bit;
        if (m->semantic) next.semantic_complete[slot / 64u] |= bit;
        else complete = false;
    }
    memcpy(next.batch.semantic_consumed, next.semantic_complete,
           sizeof(next.batch.semantic_consumed));
    next.batch.semantic_applied = complete;
    memcpy(s, &next, sizeof(*s));
    return complete ? CP_PARAMETER_STATE_COMPLETE : CP_PARAMETER_STATE_PARTIAL;
}

static int zoom_guard_valid(const struct cp_parameter_state *s,
    const struct cp_start_state_guard *g, const struct cp_parameter_zoom_readback *out) {
    if (!owner_valid(s) || s->magic != STATE_MAGIC || !span_valid(g, sizeof(*g)) ||
        (uintptr_t)g % _Alignof(struct cp_start_state_guard) || !span_valid(out, sizeof(*out)) ||
        (uintptr_t)out % _Alignof(struct cp_parameter_zoom_readback) ||
        overlaps(s, sizeof(*s), g, sizeof(*g)) || overlaps(s, sizeof(*s), out, sizeof(*out)) ||
        overlaps(g, sizeof(*g), out, sizeof(*out))) return -EINVAL;
    if (s->batch.owner_pid != getpid() || g->owner_pid != (uint32_t)getpid()) return -ECHILD;
    if (!s->batch.enabled) return -EACCES;
    if (g->source_origin != CP_START_STATE_ORIGIN_VIRTUAL_SOURCE &&
        g->source_origin != CP_START_STATE_ORIGIN_HOST_TEST) return -EINVAL;
    if (g->quiescent != 1 || g->sequence_before != g->sequence_after ||
        (g->sequence_before & 1u)) return -EAGAIN;
    if (s->zoom.count && g->source_origin != s->zoom.source_origin) return -EXDEV;
    if (s->zoom.count && g->sequence_before < s->zoom.source_sequence) return -ESTALE;
    if (s->common_stores_consumed != 1 || s->default_stores_consumed != 1 || !s->batch.staged)
        return -ENODATA;
    return 0;
}

static int zoom_read_fields(const struct cp_parameter_state *s, struct cp_parameter_zoom_readback *out) {
    static const size_t offsets[] = {0x69c, 0x698, 0x6a0, 0x6a4};
    static const size_t widths[] = {4, 1, 4, 1};
    size_t at = 0;
    out->known_mask = 0;
    for (size_t i = 0; i < 4; i++) {
        int rc = cp_parameter_state_read(s, offsets[i], out->fields + at, widths[i]);
        if (rc) return rc;
        for (size_t j = 0; j < widths[i]; j++) out->known_mask |= (uint16_t)(1u << (at + j));
        at += widths[i];
    }
    return 0;
}

int cp_parameter_state_consume_zoom(struct cp_parameter_state *s, const struct cp_start_state_guard *g,
    uint32_t metadata_source, uint32_t target, const void *input, size_t size,
    struct cp_parameter_zoom_readback *out) {
    int rc = zoom_guard_valid(s, g, out);
    if (rc) return rc;
    if (!span_valid(input, size) || overlaps(s, sizeof(*s), input, size) ||
        overlaps(g, sizeof(*g), input, size) || overlaps(out, sizeof(*out), input, size)) return -EINVAL;
    if (metadata_source != CP_PARAMETER_BATCH_SOURCE || target != CP_PARAMETER_BATCH_TARGET) return -EPERM;
    if (size != CP_PARAMETER_ZOOM_BYTES) return -EMSGSIZE;
    const unsigned char *p = input;
    if (p[0] != 5 || p[2] != 1 || p[3] != 0x40) return -EPROTO;
    uint32_t caller = p[4] | (uint32_t)p[5] << 8 | (uint32_t)p[6] << 16 | (uint32_t)p[7] << 24;
    if (!caller) return -EPROTO;
    if (s->zoom.count && g->sequence_before == s->zoom.source_sequence) return -EALREADY;
    if (s->zoom.count == UINT64_MAX) return -EOVERFLOW;
    struct cp_parameter_state next = *s;
    apply_fields(&next, p, zoom_fields, sizeof(zoom_fields) / sizeof(zoom_fields[0]));
    struct cp_parameter_zoom_readback readback = {0};
    readback.count = s->zoom.count + 1;
    readback.source_sequence = g->sequence_before; readback.source_origin = g->source_origin;
    readback.metadata_source = metadata_source; readback.target = target; readback.caller = caller;
    memcpy(readback.wire, p, size);
    rc = zoom_read_fields(&next, &readback);
    if (rc) return rc;
    const unsigned char expected[10] = {p[8], 0, 0, 0, p[9], p[10], 0, 0, 0, p[11]};
    if (readback.known_mask != CP_PARAMETER_ZOOM_KNOWN_MASK ||
        memcmp(readback.fields, expected, sizeof(expected))) return -EIO;
    readback.config_consumed = 1; next.zoom = readback;
    memcpy(s, &next, sizeof(*s)); *out = readback;
    return 0;
}

int cp_parameter_state_read_zoom(const struct cp_parameter_state *s, const struct cp_start_state_guard *g,
    struct cp_parameter_zoom_readback *out) {
    int rc = zoom_guard_valid(s, g, out);
    if (rc) return rc;
    if (!s->zoom.count || s->zoom.config_consumed != 1) return -ENODATA;
    struct cp_parameter_zoom_readback readback = s->zoom;
    rc = zoom_read_fields(s, &readback);
    if (rc) return rc;
    if (memcmp(readback.fields, s->zoom.fields, sizeof(readback.fields)) ||
        readback.known_mask != CP_PARAMETER_ZOOM_KNOWN_MASK) return -ESTALE;
    *out = readback;
    return 0;
}

int cp_parameter_state_read(const struct cp_parameter_state *s, size_t offset,
    void *output, size_t size) {
    if (!owner_valid(s) || !span_valid(output, size) || !size ||
        offset >= CP_PARAMETER_STATE_IMAGE_BYTES ||
        size > CP_PARAMETER_STATE_IMAGE_BYTES - offset) return -EINVAL;
    if (s->magic != STATE_MAGIC) return -EINVAL;
    if (s->batch.owner_pid != getpid()) return -ECHILD;
    if (!s->batch.enabled) return -EACCES;
    if (overlaps(output, size, s, sizeof(*s))) return -EINVAL;
    for (size_t i = offset; i < offset + size; i++)
        if (!(s->known_mask[i / 8u] & (1u << (i % 8u)))) return -ENODATA;
    memcpy(output, s->bytes + offset, size);
    return 0;
}
