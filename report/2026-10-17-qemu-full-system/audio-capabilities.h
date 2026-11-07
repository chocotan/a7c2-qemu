/* SPDX-License-Identifier: MIT */
#ifndef FULL_AUDIO_CAPABILITIES_H
#define FULL_AUDIO_CAPABILITIES_H
#define FULL_AUDIO_CAPS_INPUTLESS 1
struct full_audio_capabilities {
    unsigned int profile, valid, input_devices, pro, aip, znr, error;
    unsigned char flags[16];
    unsigned long long queries;
};
/* A new virtual owner, not a recovered original AVIO/Backup configuration. */
void full_audio_capabilities_inputless(struct full_audio_capabilities *);
unsigned int full_audio_capabilities_read(struct full_audio_capabilities *,unsigned char [16]);
#endif
