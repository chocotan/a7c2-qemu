/* SPDX-License-Identifier: MIT */
#ifndef A7C2_AUDIO_DEVICE_H
#define A7C2_AUDIO_DEVICE_H
#include "imaging-device.h"
#include "sound-table.h"
#include "audio-capabilities.h"
#define FULL_AUDIO_INPUT 0x92840747u
#define FULL_AUDIO_VOLUME 1
#define FULL_AUDIO_BOOT 2
struct full_audio_snapshot {
    unsigned int known, wire_volume, driver_level, faults, live_replies;
    unsigned char driver_control[64];
    unsigned long long applied, driver_consumed, queued, request_freed, waiter_freed, native_freed, next_lease;
    void *retained_reply, *retained_request;
    unsigned long long queries, table_applied;
    struct full_sound_slot table[FULL_SOUND_SLOTS];
    unsigned char system_volume[FULL_SOUND_SLOTS];
    unsigned long long system_volume_applied;
    struct full_audio_capabilities capabilities;
    unsigned int system_path, path_register, path_control_argument;
    unsigned long long path_applied, path_control_consumed;
};
int full_audio_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_audio_dispatch_capabilities(unsigned int,void *,const struct full_imaging_io *,int,int,int *);
int full_audio_release_reply(unsigned int,void *,int (*)(unsigned int,void *),
                             void (*)(const char *,const char *),int *);
void full_audio_snapshot(struct full_audio_snapshot *);
int full_audio_replay_config(unsigned int *);
#ifdef FULL_AUDIO_TEST
void full_audio_test_reset(void);
void full_audio_test_capabilities_bind(const struct full_audio_capabilities *);
#endif
#endif
