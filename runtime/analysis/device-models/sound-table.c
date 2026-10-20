/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "sound-table.h"
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
static pthread_mutex_t backend_lock=PTHREAD_MUTEX_INITIALIZER;
static const volatile unsigned char *backing;
static const unsigned char *reference;
static unsigned long held_capacity,held_bytes;
static int metadata_valid(const char *text) {
    char expected[600];
    snprintf(expected,sizeof expected,"{\"ready\":true,\"physical\":\"0x%llx\",\"virtual_bus\":\"0x%llx\",\"audio_phys64\":\"0x%llx\",\"capacity\":%lu,\"bytes\":%lu,\"fnv64\":\"%016llx\",\"source_sha256\":\"%s\",\"lifetime\":\"vm\",\"audio_output_verified\":false}\n",
             SYSTEM_SOUND_PHYSICAL,SYSTEM_SOUND_BUS,SYSTEM_SOUND_AUDIO_PHYS64,
             SYSTEM_SOUND_CAPACITY,SYSTEM_SOUND_BYTES,SYSTEM_SOUND_FNV,SYSTEM_SOUND_SHA256);
    /* This private atomic file has one canonical producer; reject schema drift. */
    return text && !strcmp(text,expected);
}
#ifndef FULL_AUDIO_TEST
static int read_exact(const char *path,void *out,size_t bytes) {
    FILE *f=fopen(path,"rb");if (!f) return -1;
    size_t n=fread(out,1,bytes,f);int extra=fgetc(f),error=ferror(f);fclose(f);
    return n==bytes && extra==EOF && !error?0:-1;
}
static int attach(void) {
    char metadata[600]={0},command[8192]={0};
    FILE *f=fopen("/log/qemu/system-sound-owner.json","rb");if (!f) return -1;
    size_t n=fread(metadata,1,sizeof metadata-1,f);
    int extra=fgetc(f),error=ferror(f);fclose(f);
    if (!n || extra!=EOF || error || memchr(metadata,0,n) || !metadata_valid(metadata)) return -1;
    f=fopen("/proc/cmdline","rb");if (!f) return -1;
    n=fread(command,1,sizeof command-1,f);extra=fgetc(f);error=ferror(f);fclose(f);
    if (!n || extra!=EOF || error || memchr(command,0,n)) return -1;
    unsigned int reserved=0,enabled=0;char *save=0;
    for (char *p=strtok_r(command," \r\n\t",&save);p;p=strtok_r(0," \r\n\t",&save)) {
        if (!strcmp(p,SYSTEM_SOUND_RESERVATION)) reserved++;
        if (!strcmp(p,"fullsystem.sound-owner=1")) enabled++;
    }
    if (reserved!=1 || enabled!=1) return -1;
    unsigned char *source=malloc(SYSTEM_SOUND_BYTES);
    if (!source) return -1;
    if (read_exact("/cp/SysSound.bin",source,SYSTEM_SOUND_BYTES)) { free(source);return -1; }
    int fd=open("/dev/mem",O_RDONLY|O_SYNC);
    if (fd<0) { free(source);return -1; }
    const volatile unsigned char *memory=mmap(0,SYSTEM_SOUND_CAPACITY,PROT_READ,MAP_SHARED,fd,SYSTEM_SOUND_PHYSICAL);
    close(fd);
    if ((const void *)memory==MAP_FAILED) { free(source);return -1; }
    if (system_sound_verify(memory,SYSTEM_SOUND_CAPACITY,source,SYSTEM_SOUND_BYTES)) {
        munmap((void *)memory,SYSTEM_SOUND_CAPACITY);free(source);return -1;
    }
    /* Hold read-only mapping and original reference until process exit. */
    backing=memory;reference=source;held_capacity=SYSTEM_SOUND_CAPACITY;held_bytes=SYSTEM_SOUND_BYTES;
    return 0;
}
#endif
int full_sound_ready(void) {
    pthread_mutex_lock(&backend_lock);
#ifndef FULL_AUDIO_TEST
    if (!backing) (void)attach();
#endif
    int rc=system_sound_verify(backing,held_capacity,reference,held_bytes);
    pthread_mutex_unlock(&backend_lock);return rc;
}
static unsigned int u32(const unsigned char *p) {
    return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;
}
int full_sound_table(struct full_sound_slot *table,const unsigned char *in,unsigned int *status,int *index) {
    unsigned char desc[32];memcpy(desc,in+8,32);memset(desc+17,0,3);memset(desc+28,0,4);
    unsigned int kind=desc[12],regist=desc[14];*status=0;*index=-1;
    if (desc[15]>1 || desc[16]>1) return -1; /* Original assertion domain. */
    if (!kind) { *status=0xe002;return 0; }
    if (regist>1) { *status=0xe004;return 0; }
    int empty=-1,found=-1;
    for (int i=0;i<FULL_SOUND_SLOTS;i++) {
        if (table[i].descriptor[14]==1 && table[i].descriptor[12]==kind) found=i;
        if (!table[i].descriptor[14] && empty<0) empty=i;
    }
    if (!regist) {
        if (found>=0) { memset(&table[found],0,sizeof table[found]);*index=found; }
        return 0;
    }
    unsigned long long address=(unsigned long long)u32(desc)|(unsigned long long)u32(desc+4)<<32;
    unsigned long long offset=address-SYSTEM_SOUND_AUDIO_PHYS64;
    unsigned int bytes=u32(desc+8);
    /* +0x40 is conservative execution headroom; its original meaning is unknown. */
    if (address<SYSTEM_SOUND_AUDIO_PHYS64 || offset>=SYSTEM_SOUND_BYTES ||
        bytes>SYSTEM_SOUND_BYTES-offset || offset+bytes+0x40>SYSTEM_SOUND_CAPACITY) return -1;
    pthread_mutex_lock(&backend_lock);
    int bad=!backing || held_capacity!=SYSTEM_SOUND_CAPACITY || held_bytes!=SYSTEM_SOUND_BYTES;
    for (unsigned long i=0;!bad && i<(unsigned long)bytes+0x40;i++) {
        unsigned long pos=(unsigned long)offset+i;
        if (backing[pos]!=(pos<held_bytes?reference[pos]:0)) bad=1;
    }
    unsigned long long digest=bad?0:system_sound_digest(backing+(unsigned long)offset,bytes);
    pthread_mutex_unlock(&backend_lock);
    if (bad) return -1;
    if (found>=0) {
        *index=found;if (memcmp(table[found].descriptor,desc,32)) *status=0xe004;
        return 0;
    }
    if (empty<0) { *status=0xe004;return 0; }
    struct full_sound_slot *slot=&table[empty];memcpy(slot->descriptor,desc,32);
    slot->cpu=(unsigned int)(SYSTEM_SOUND_BUS+offset);slot->offset=(unsigned int)offset;
    slot->size=bytes;slot->digest=digest;*index=empty;return 0;
}
#ifdef FULL_AUDIO_TEST
int full_sound_test_bind(const volatile unsigned char *memory,unsigned long capacity,
                         const unsigned char *source,unsigned long bytes,const char *metadata) {
    pthread_mutex_lock(&backend_lock);int rc=-1;
    if (metadata_valid(metadata) && !system_sound_verify(memory,capacity,source,bytes)) {
        backing=memory;reference=source;held_capacity=capacity;held_bytes=bytes;rc=0;
    }
    pthread_mutex_unlock(&backend_lock);return rc;
}
void full_sound_test_reset(void) {
    pthread_mutex_lock(&backend_lock);backing=0;reference=0;held_capacity=held_bytes=0;
    pthread_mutex_unlock(&backend_lock);
}
#endif
