/* SPDX-License-Identifier: MIT */
#include "pin-buffer-owner.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned char memory[PIN_CONTROL_CAPACITY];
static struct pin_control_snapshot snapshot(void){struct pin_control_snapshot out;pin_control_snapshot(&out);return out;}
static void reset(void){pin_control_test_reset();memset(memory,0,sizeof memory);}
static void *worker(void *unused){
    (void)unused;
    for(unsigned int i=0;i<20;i++){
        struct pin_control_lease lease;assert(!pin_control_allocate(PIN_CONTROL_UNIT,&lease));
        assert(!pin_control_write_ssyn(lease.handle,0));assert(!pin_control_release(lease.handle));
    }
    return 0;
}
int main(void){
    assert(pin_control_open_guest(0)==0);
    reset();struct pin_control_lease lease[PIN_CONTROL_SLOTS],replacement;
    assert(pin_control_allocate(PIN_CONTROL_UNIT,&replacement)<0);
    assert(pin_control_bind_reserved(memory,sizeof memory,PIN_CONTROL_PHYSICAL+4096)<0);
    memory[17]=0x89;assert(pin_control_bind_reserved(memory,sizeof memory,PIN_CONTROL_PHYSICAL)<0);assert(memory[17]==0x89);
    memory[17]=0;assert(!pin_control_bind_reserved(memory,sizeof memory,PIN_CONTROL_PHYSICAL));
    assert(pin_control_bind_reserved(memory,sizeof memory,PIN_CONTROL_PHYSICAL)<0);
    assert(pin_control_allocate(PIN_CONTROL_UNIT+1,&replacement)<0);
    for(unsigned int i=0;i<PIN_CONTROL_SLOTS;i++){
        assert(!pin_control_allocate(PIN_CONTROL_UNIT,&lease[i]));
        assert(lease[i].slot==i && lease[i].handle==(0x8000u|i) && lease[i].bytes==512);
        assert(lease[i].physical==PIN_CONTROL_PHYSICAL+i*512 && lease[i].cp_virtual==PIN_CONTROL_CP_VIRTUAL+i*512);
        unsigned long long digest=0;assert(!pin_control_write_ssyn(lease[i].handle,&digest) && digest);
        static const unsigned char expected[32]={0x53,0x53,0x59,0x4e,0,0,0,1};
        assert(!memcmp(memory+i*512,expected,32));
        for(unsigned int j=32;j<512;j++)assert(!memory[i*512+j]);
    }
    assert(snapshot().live==16 && pin_control_allocate(PIN_CONTROL_UNIT,&replacement)<0);
    unsigned int old=lease[3].handle;assert(!pin_control_release(old));assert(!pin_control_allocate(PIN_CONTROL_UNIT,&replacement));
    assert(replacement.slot==3 && replacement.handle!=old && pin_control_release(old)<0 && pin_control_write_ssyn(old,0)<0);
    assert(pin_control_release(replacement.handle|0x10000)<0 && snapshot().live==16);
    assert(!pin_control_release(replacement.handle));
    for(unsigned int i=0;i<PIN_CONTROL_SLOTS;i++)if(i!=3)assert(!pin_control_release(lease[i].handle));
    assert(!snapshot().live && snapshot().allocations==17 && snapshot().releases==17);
    puts("VIRTUAL_CONTROL_16X512_ACTUAL_HEADER_BACKING_STALE_LEASE_PASS");
    reset();assert(!pin_control_bind_reserved(memory,sizeof memory,PIN_CONTROL_PHYSICAL));
    for(unsigned int i=0;i<PIN_CONTROL_SLOTS*32;i++){
        assert(!pin_control_allocate(PIN_CONTROL_UNIT,&replacement));assert(!pin_control_release(replacement.handle));
    }
    assert(pin_control_allocate(PIN_CONTROL_UNIT,&replacement)<0 && snapshot().exhausted==16 && !snapshot().live);
    puts("VIRTUAL_CONTROL_5BIT_GENERATION_EXHAUSTION_WITHOUT_WRAP_PASS");
    reset();assert(!pin_control_bind_reserved(memory,sizeof memory,PIN_CONTROL_PHYSICAL));pthread_t threads[4];
    for(unsigned int i=0;i<4;i++)assert(!pthread_create(&threads[i],0,worker,0));
    for(unsigned int i=0;i<4;i++)assert(!pthread_join(threads[i],0));
    assert(!snapshot().live && !snapshot().faults && snapshot().allocations==80 && snapshot().header_writes==80);
    puts("VIRTUAL_CONTROL_CONCURRENT_ALLOC_WRITE_RELEASE_80_PASS");return 0;
}
