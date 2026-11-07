/* SPDX-License-Identifier: MIT */
#include "system-sound-owner.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc,char **argv) {
    assert(SYSTEM_SOUND_AUDIO_PHYS64-0x800000000ULL==SYSTEM_SOUND_BUS);
    assert(SYSTEM_SOUND_BYTES+0x40<=SYSTEM_SOUND_CAPACITY);
    assert(argc==2);
    FILE *f=fopen(argv[1],"rb");assert(f);
    unsigned char *source=malloc(SYSTEM_SOUND_BYTES),*memory=malloc(SYSTEM_SOUND_CAPACITY);
    assert(source && memory && fread(source,1,SYSTEM_SOUND_BYTES,f)==SYSTEM_SOUND_BYTES);
    assert(fgetc(f)==EOF);fclose(f);
    memset(memory,0xa5,SYSTEM_SOUND_CAPACITY);
    assert(system_sound_load(memory,SYSTEM_SOUND_CAPACITY,source,SYSTEM_SOUND_BYTES-1));
    assert(memory[0]==0xa5 && memory[SYSTEM_SOUND_CAPACITY-1]==0xa5);
    source[5]^=1;assert(system_sound_load(memory,SYSTEM_SOUND_CAPACITY,source,SYSTEM_SOUND_BYTES));
    assert(memory[0]==0xa5);source[5]^=1;
    assert(system_sound_load(memory,SYSTEM_SOUND_CAPACITY-1,source,SYSTEM_SOUND_BYTES));
    assert(memory[0]==0xa5);
    assert(!system_sound_load(memory,SYSTEM_SOUND_CAPACITY,source,SYSTEM_SOUND_BYTES));
    assert(!system_sound_verify(memory,SYSTEM_SOUND_CAPACITY,source,SYSTEM_SOUND_BYTES));
    memory[100]^=1;assert(system_sound_verify(memory,SYSTEM_SOUND_CAPACITY,source,SYSTEM_SOUND_BYTES));
    memory[100]^=1;memory[SYSTEM_SOUND_BYTES]=1;
    assert(system_sound_verify(memory,SYSTEM_SOUND_CAPACITY,source,SYSTEM_SOUND_BYTES));
    memory[SYSTEM_SOUND_BYTES]=0;
    assert(!system_sound_verify(memory,SYSTEM_SOUND_CAPACITY,source,SYSTEM_SOUND_BYTES));
    free(source);free(memory);puts("SYSTEM_SOUND_OWNER_CONTENT_HOST_PASS");return 0;
}
