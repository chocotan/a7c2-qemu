/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "system-sound-owner.h"
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

unsigned long long system_sound_digest(const volatile unsigned char *p,unsigned long n) {
    unsigned long long h=0xcbf29ce484222325ULL;
    for (unsigned long i=0;i<n;i++) h=(h^p[i])*0x100000001b3ULL;
    return h;
}
static int source_valid(const unsigned char *source,unsigned long bytes) {
    return source && bytes==SYSTEM_SOUND_BYTES &&
           system_sound_digest(source,bytes)==SYSTEM_SOUND_FNV;
}
int system_sound_verify(const volatile unsigned char *memory,unsigned long capacity,
                        const unsigned char *source,unsigned long bytes) {
    if (!memory || capacity!=SYSTEM_SOUND_CAPACITY || !source_valid(source,bytes)) return -1;
    for (unsigned long i=0;i<bytes;i++) if (memory[i]!=source[i]) return -2;
    for (unsigned long i=bytes;i<capacity;i++) if (memory[i]) return -3;
    return system_sound_digest(memory,bytes)==SYSTEM_SOUND_FNV?0:-4;
}
int system_sound_load(volatile unsigned char *memory,unsigned long capacity,
                      const unsigned char *source,unsigned long bytes) {
    if (!memory || capacity!=SYSTEM_SOUND_CAPACITY || !source_valid(source,bytes)) return -1;
    for (unsigned long i=0;i<bytes;i++) memory[i]=source[i];
    for (unsigned long i=bytes;i<capacity;i++) memory[i]=0;
    return system_sound_verify(memory,capacity,source,bytes);
}

#if !defined(SYSTEM_SOUND_OWNER_TEST) && !defined(SYSTEM_SOUND_OWNER_LIBRARY)
static const char *ready="/log/qemu/system-sound-owner.json";
static int reservation_present(void) {
    char command[8192];FILE *f=fopen("/proc/cmdline","r");
    if (!f) return 0;
    size_t n=fread(command,1,sizeof command-1,f);
    int extra=fgetc(f);fclose(f);
    if (extra!=EOF) return 0;
    command[n]=0;unsigned int count=0;char *save=0;
    for (char *word=strtok_r(command," \r\n\t",&save);word;word=strtok_r(0," \r\n\t",&save))
        if (!strcmp(word,SYSTEM_SOUND_RESERVATION)) count++;
    return count==1;
}
static int run(int argc,char **argv) {
    int verify_only=argc==2 && !strcmp(argv[1],"--verify");
    if (argc!=1 && !verify_only) return 2;
    unlink(ready);unlink("/log/qemu/system-sound-owner.json.new");
    if (!reservation_present()) { puts("FULL_SOUND_OWNER_FAILED reservation");return 3; }
    unsigned char *source=malloc(SYSTEM_SOUND_BYTES);
    FILE *f=fopen("/cp/SysSound.bin","rb");
    if (!source || !f) { if (f) fclose(f);free(source);return 4; }
    size_t bytes=fread(source,1,SYSTEM_SOUND_BYTES,f);
    int extra=fgetc(f),error=ferror(f);fclose(f);
    if (extra!=EOF || error || !source_valid(source,bytes)) {
        puts("FULL_SOUND_OWNER_FAILED source-size-or-digest");free(source);return 5;
    }
    int fd=open("/dev/mem",O_RDWR|O_SYNC);
    if (fd<0) { free(source);return 6; }
    volatile unsigned char *memory=mmap(0,SYSTEM_SOUND_CAPACITY,PROT_READ|PROT_WRITE,
                                       MAP_SHARED,fd,SYSTEM_SOUND_PHYSICAL);
    close(fd);
    if ((void *)memory==MAP_FAILED) { free(source);return 7; }
    int rc=verify_only?system_sound_verify(memory,SYSTEM_SOUND_CAPACITY,source,bytes):
                       system_sound_load(memory,SYSTEM_SOUND_CAPACITY,source,bytes);
    unsigned long long digest=system_sound_digest(memory,SYSTEM_SOUND_BYTES);
    munmap((void *)memory,SYSTEM_SOUND_CAPACITY);free(source);
    if (rc) { printf("FULL_SOUND_OWNER_FAILED readback=%d\n",rc);return 8; }
    f=fopen("/log/qemu/system-sound-owner.json.new","w");
    if (!f) return 9;
    int failed=fprintf(f,"{\"ready\":true,\"physical\":\"0x%llx\",\"virtual_bus\":\"0x%llx\",\"audio_phys64\":\"0x%llx\",\"capacity\":%lu,\"bytes\":%lu,\"fnv64\":\"%016llx\",\"source_sha256\":\"%s\",\"lifetime\":\"vm\",\"audio_output_verified\":false}\n",
                      SYSTEM_SOUND_PHYSICAL,SYSTEM_SOUND_BUS,SYSTEM_SOUND_AUDIO_PHYS64,SYSTEM_SOUND_CAPACITY,
                      SYSTEM_SOUND_BYTES,digest,SYSTEM_SOUND_SHA256)<0;
    if (fflush(f) || fsync(fileno(f))) failed=1;
    if (fclose(f)) failed=1;
    if (failed || rename("/log/qemu/system-sound-owner.json.new",ready)) return 10;
    printf("FULL_SOUND_OWNER_READY physical=%#llx virtual_bus=%#llx audio_phys64=%#llx capacity=%lu bytes=%lu fnv64=%016llx mode=%s audio_output_verified=0\n",
           SYSTEM_SOUND_PHYSICAL,SYSTEM_SOUND_BUS,SYSTEM_SOUND_AUDIO_PHYS64,SYSTEM_SOUND_CAPACITY,SYSTEM_SOUND_BYTES,
           digest,verify_only?"verify":"loaded");
    return 0;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,
                            void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
#endif
