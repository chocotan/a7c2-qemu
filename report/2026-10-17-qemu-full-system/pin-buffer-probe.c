/* SPDX-License-Identifier: MIT */
/* Guest-only backing probe. This is not original PinMem/CP execution. */
#include "pin-buffer-owner.h"
#include <fcntl.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>
static int run(int argc,char **argv){
    (void)argv;if(argc!=1)return 2;
    if(pin_control_open_guest(1)!=1){puts("FULL_PIN_CONTROL_PROBE_FAILED stage=binding");return 3;}
    struct pin_control_lease lease;
    if(pin_control_allocate(PIN_CONTROL_UNIT,&lease)){puts("FULL_PIN_CONTROL_PROBE_FAILED stage=allocate");return 4;}
    unsigned long long header_digest=0;
    if(pin_control_write_ssyn(lease.handle,&header_digest)){puts("FULL_PIN_CONTROL_PROBE_FAILED stage=write-readback");return 5;}
    int fd=open("/dev/mem",O_RDONLY);
    if(fd<0)return 6;
    const volatile unsigned char *memory=mmap(0,PIN_CONTROL_CAPACITY,PROT_READ,MAP_SHARED,fd,PIN_CONTROL_PHYSICAL);close(fd);
    if((const void *)memory==MAP_FAILED)return 7;
    static const unsigned char header[32]={0x53,0x53,0x59,0x4e,0,0,0,1};
    unsigned long long digest=0xcbf29ce484222325ULL;int failed=0;
    for(unsigned int i=0;i<PIN_CONTROL_CAPACITY;i++){
        unsigned char value=memory[i];if(value!=(i<32?header[i]:0))failed=1;digest=(digest^value)*0x100000001b3ULL;
    }
    munmap((void *)memory,PIN_CONTROL_CAPACITY);
    if(failed){puts("FULL_PIN_CONTROL_PROBE_FAILED stage=independent-map");return 8;}
    if(pin_control_release(lease.handle)){puts("FULL_PIN_CONTROL_PROBE_FAILED stage=release");return 9;}
    struct pin_control_snapshot state;pin_control_snapshot(&state);
    if(state.live || state.faults || state.allocations!=1 || state.releases!=1 || state.header_writes!=1)return 10;
    printf("FULL_PIN_CONTROL_PROBE_PASS physical=%#llx cp_virtual=%#x capacity=%u unit=%#x handle=%#x bytes=%u header_fnv64=%016llx full_fnv64=%016llx live=0 releases=1 original_CP_task_running=0 pixels_consumed=0 camera_startup_verified=0\n",
           lease.physical,lease.cp_virtual,PIN_CONTROL_CAPACITY,lease.unit,lease.handle,lease.bytes,header_digest,digest);
    return 0;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack){
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
