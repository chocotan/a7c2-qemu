/* SPDX-License-Identifier: MIT */
#include "audio-capabilities.h"
#include <string.h>

void full_audio_capabilities_inputless(struct full_audio_capabilities *owner) {
    /* This owner has no audio input/processing devices. All three capability
     * sources exist and return saved values: P(word7)=0, A(0124)=0, Z(0205)=0.
     * No absent original configuration lookup is silently treated as zero. */
    *owner=(struct full_audio_capabilities){.profile=FULL_AUDIO_CAPS_INPUTLESS,.valid=7};
}
unsigned int full_audio_capabilities_read(struct full_audio_capabilities *owner,unsigned char out[16]) {
    memset(out,0,16);
    if (owner->error) return 0xefff;
    if (owner->profile!=FULL_AUDIO_CAPS_INPUTLESS || owner->valid!=7 || owner->input_devices ||
        owner->pro || owner->aip || owner->znr) {
        /* Original723b0 latches a source error;72128 returns efff and cleared
         * parameters. Unavailable capability flags cannot conceal failure. */
        owner->error=0xefff;return 0xefff;
    }
    unsigned int p=owner->pro,a=owner->aip,z=owner->znr;
    unsigned char flags[16];memset(flags,p?0:0x80,16);
    /* The sixteen original getter projections;81 is LowCut's special class,
     * not a generic supported/ready bit. The nine Pro/Shoe fields share P. */
    flags[8]=z==3?0x80:p?0:0x81;
    flags[9]=a?0:0x80;flags[10]=a==1?0:0x80;
    flags[11]=flags[12]=a==2?0:0x80;
    flags[13]=z==2 || z==3?0:0x80;flags[15]=z==3?0:0x80;
    memcpy(owner->flags,flags,16);memcpy(out,owner->flags,16);owner->queries++;
    return 0;
}
