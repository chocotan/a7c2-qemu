/* SPDX-License-Identifier: MIT */
#ifndef A7C2_SOUND_TABLE_H
#define A7C2_SOUND_TABLE_H
#include "system-sound-owner.h"
#define FULL_SOUND_SLOTS 30
struct full_sound_slot {
    unsigned char descriptor[32];
    unsigned int cpu, offset, size;
    unsigned long long digest;
};
/* The caller serializes table transactions, including rollback on send failure. */
int full_sound_ready(void);
int full_sound_table(struct full_sound_slot *,const unsigned char *,unsigned int *,int *);
#ifdef FULL_AUDIO_TEST
/* Borrowed buffers: tests retain ownership, production never uses host /dev/mem. */
int full_sound_test_bind(const volatile unsigned char *,unsigned long,
                         const unsigned char *,unsigned long,const char *);
void full_sound_test_reset(void);
#endif
#endif
