/* SPDX-License-Identifier: MIT */
/* Guest-only read diagnostic. No setting changes, CP task or ready response. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

typedef unsigned int (*size_fn)(unsigned int);
typedef unsigned int (*read_fn)(unsigned int,void *,int);
static int run(int argc,char **argv){
    if(argc!=2 || strcmp(argv[1],"--isolated-diagnostic"))return 2;
    void *module=dlopen("/usr/lib/libbackup.so",RTLD_NOW|RTLD_LOCAL);
    if(!module){puts("HDMI_BACKUP_PROBE_ERROR original-libbackup-unavailable");return 3;}
    size_fn size=(size_fn)dlsym(module,"Backup_get_datasize");
    read_fn nread=(read_fn)dlsym(module,"Backup_nread");
    if(!size || !nread){puts("HDMI_BACKUP_PROBE_ERROR original-symbol-unavailable");dlclose(module);return 4;}
    static const unsigned int keys[]={0x010d008d,0x003e0005,0x009a0001,0x010704fd,
                                      0x009a0009,0x009a000a,0x009a000b,0x009a000c};
    unsigned int readable=0;
    for(unsigned int i=0;i<8;i++){
        unsigned int before=size(keys[i]),after=before,rc=0xffffffffu;
        unsigned char bytes[256]={0};unsigned long long digest=0;
        int complete=0;
        if(before && before<=sizeof bytes){
            rc=nread(keys[i],bytes,(int)before);after=size(keys[i]);
            if(rc==before && after==before){
                complete=1;readable++;digest=0xcbf29ce484222325ull;
                for(unsigned int j=0;j<before;j++)digest=(digest^bytes[j])*0x100000001b3ull;
            }
        }
        printf("HDMI_BACKUP_PROBE_KEY key=%#x size_before=%#x original_nread=%#x size_after=%#x complete=%u fnv64=%016llx\n",
               keys[i],before,rc,after,complete,digest);fflush(stdout);
    }
    dlclose(module);
    printf("HDMI_BACKUP_PROBE_DONE keys=8 readable=%u original_cp_task=0 camera_startup_verified=0\n",readable);
    return 0; /* Diagnostic completeness is distinct from all keys being readable. */
}
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack){
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
