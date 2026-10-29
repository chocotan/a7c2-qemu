/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include "pin-buffer-owner.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
static unsigned char memory[PIN_CONTROL_CAPACITY];
static struct pin_control_snapshot snapshot(void){struct pin_control_snapshot out;pin_control_snapshot(&out);return out;}
static void reset(void){pin_control_test_reset();memset(memory,0,sizeof memory);}
#define REJECT_UNCHANGED(call,handle) do { \
    struct pin_control_snapshot before=snapshot(),after; \
    struct pin_control_references old_refs,new_refs; \
    int old_rc=pin_control_references((handle),&old_refs); \
    unsigned char old_memory[sizeof memory];memcpy(old_memory,memory,sizeof memory); \
    assert((call)<0);after=snapshot();assert(!memcmp(&before,&after,sizeof before)); \
    assert(!memcmp(old_memory,memory,sizeof memory)); \
    assert(pin_control_references((handle),&new_refs)==old_rc); \
    if(!old_rc)assert(!memcmp(&old_refs,&new_refs,sizeof old_refs)); \
} while(0)
static void references(unsigned int handle,unsigned int owners,unsigned int opens,unsigned int creator,unsigned int consumer,unsigned int consumer_open){
    struct pin_control_references s;assert(!pin_control_references(handle,&s));
    assert(s.handle==handle && s.owners==owners && s.opens==opens && s.creator==creator &&
        s.consumer==consumer && s.consumer_open==consumer_open);
}
static void fork_rejected(unsigned int handle){
    struct pin_control_snapshot before=snapshot(),after;
    struct pin_control_references old_refs,new_refs;assert(!pin_control_references(handle,&old_refs));
    unsigned char old_memory[sizeof memory];memcpy(old_memory,memory,sizeof memory);
    pin_control_test_hold_lock();pid_t child=fork();assert(child>=0);
    if(!child){
        alarm(3);
        assert(pin_control_close_creator(handle)==-4);
        assert(pin_control_transfer_creator(handle,PIN_CONTROL_UNIT)==-4);
        _exit(0);
    }
    int status=0;assert(waitpid(child,&status,0)==child);
    pin_control_test_drop_lock();assert(WIFEXITED(status) && !WEXITSTATUS(status));
    after=snapshot();assert(!memcmp(&before,&after,sizeof before) && !memcmp(old_memory,memory,sizeof memory));
    assert(!pin_control_references(handle,&new_refs) && !memcmp(&old_refs,&new_refs,sizeof old_refs));
}
static void creator_handoff(void){
    /* Reuse this bound fixture after the old two-owner path, without resetting. */
    struct pin_control_snapshot before=snapshot();assert(before.bound && !before.live && !before.faults);
    struct pin_control_lease created,opened;
    assert(!pin_control_allocate(PIN_CONTROL_UNIT,&created));
    assert(!pin_control_write_ssyn(created.handle,0));
    assert(!pin_control_share(created.handle,PIN_CONTROL_UNIT));references(created.handle,2,1,1,1,0);
    REJECT_UNCHANGED(pin_control_close_creator(created.handle),created.handle);
    REJECT_UNCHANGED(pin_control_transfer_creator(created.handle,PIN_CONTROL_UNIT),created.handle);
    assert(!pin_control_open_consumer(created.handle,PIN_CONTROL_UNIT,&opened));references(created.handle,2,2,1,1,1);
    REJECT_UNCHANGED(pin_control_close_creator(created.handle),created.handle);
    REJECT_UNCHANGED(pin_control_transfer_creator(created.handle,PIN_CONTROL_UNIT),created.handle);
    unsigned char old_header[32];static const unsigned char expected_header[32]={0x53,0x53,0x59,0x4e,0,0,0,1};
    assert(!pin_control_read_consumer(created.handle,0,old_header,sizeof old_header) && !memcmp(old_header,expected_header,sizeof old_header));
    assert(!pin_control_release(created.handle));references(created.handle,1,1,0,1,1);
    assert(!pin_control_release_consumer(created.handle));
    struct pin_control_snapshot prior=snapshot();
    assert(!prior.live && !prior.faults && prior.allocations==before.allocations+1 && prior.releases==before.releases+1 &&
        prior.shares==before.shares+1 && prior.creator_releases==before.creator_releases+1 &&
        prior.consumer_releases==before.consumer_releases+1 && prior.creator_closes==before.creator_closes &&
        prior.creator_transfers==before.creator_transfers);
    puts("CONTROL_OLD_TWO_OWNER_REAL_SSYN_RELEASE_BEFORE_HANDOFF_WITHOUT_RESET_PASS");
    unsigned int stale=created.handle;
    assert(!pin_control_allocate(PIN_CONTROL_UNIT,&created) && created.handle!=stale);
    unsigned int handle=created.handle;references(handle,1,1,1,0,0);
    static const unsigned char packet[16]={0x53,0x53,0x59,0x4e,0,0,0,1,0,0,0,0,1,0,0,0};
    unsigned char expected[sizeof memory];memcpy(expected,memory,sizeof memory);
    memcpy(expected+created.slot*PIN_CONTROL_SLOT_BYTES,packet,sizeof packet);
    unsigned long long hash=0xcbf29ce484222325ULL,digest=0;
    for(unsigned int i=0;i<sizeof packet;i++)hash=(hash^packet[i])*0x100000001b3ULL;
    assert(!pin_control_write_payload(handle,packet,sizeof packet,&digest) && digest==hash && !memcmp(expected,memory,sizeof memory));
    REJECT_UNCHANGED(pin_control_transfer_creator(handle,PIN_CONTROL_UNIT),handle);
    REJECT_UNCHANGED(pin_control_transfer_creator(handle,PIN_CONTROL_UNIT+1),handle);
    unsigned int invalid[]={stale,handle|0x10000u,handle^0x400u,0,0x8010u};
    for(unsigned int i=0;i<sizeof invalid/sizeof invalid[0];i++){
        REJECT_UNCHANGED(pin_control_close_creator(invalid[i]),handle);
        REJECT_UNCHANGED(pin_control_transfer_creator(invalid[i],PIN_CONTROL_UNIT),handle);
    }
    fork_rejected(handle);
    assert(!pin_control_close_creator(handle));references(handle,1,0,1,0,0);
    struct pin_control_snapshot closed=snapshot();
    assert(closed.creator_closes==prior.creator_closes+1 && closed.creator_transfers==prior.creator_transfers &&
        closed.allocations==prior.allocations+1 && closed.releases==prior.releases && closed.live==1 &&
        closed.creator_releases==prior.creator_releases && closed.shares==prior.shares);
    REJECT_UNCHANGED(pin_control_close_creator(handle),handle);
    digest=0x12345678;
    REJECT_UNCHANGED(pin_control_write_payload(handle,packet,sizeof packet,&digest),handle);
    REJECT_UNCHANGED(pin_control_write_ssyn(handle,&digest),handle);assert(digest==0x12345678);
    REJECT_UNCHANGED(pin_control_share(handle,PIN_CONTROL_UNIT),handle);
    REJECT_UNCHANGED(pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&opened),handle);
    REJECT_UNCHANGED(pin_control_release_consumer(handle),handle);
    REJECT_UNCHANGED(pin_control_transfer_creator(handle,PIN_CONTROL_UNIT+1),handle);
    fork_rejected(handle);
    puts("CONTROL_CREATOR_CLOSE_PRESERVES_OWNER_FREEZES_WRITES_FORK_GUARD_BEFORE_MUTEX_PASS");
    assert(!pin_control_transfer_creator(handle,PIN_CONTROL_UNIT));references(handle,1,0,0,1,0);
    struct pin_control_snapshot transferred=snapshot();
    assert(transferred.creator_transfers==prior.creator_transfers+1 && transferred.creator_closes==closed.creator_closes &&
        transferred.live==1 && transferred.allocations==closed.allocations && transferred.releases==closed.releases &&
        transferred.shares==prior.shares && transferred.creator_releases==prior.creator_releases &&
        transferred.consumer_opens==prior.consumer_opens && transferred.consumer_releases==prior.consumer_releases);
    REJECT_UNCHANGED(pin_control_transfer_creator(handle,PIN_CONTROL_UNIT),handle);
    REJECT_UNCHANGED(pin_control_close_creator(handle),handle);
    REJECT_UNCHANGED(pin_control_release(handle),handle);
    REJECT_UNCHANGED(pin_control_release_consumer(handle),handle);
    REJECT_UNCHANGED(pin_control_share(handle,PIN_CONTROL_UNIT),handle);
    REJECT_UNCHANGED(pin_control_write_payload(handle,packet,sizeof packet,&digest),handle);
    REJECT_UNCHANGED(pin_control_write_ssyn(handle,&digest),handle);assert(digest==0x12345678);
    REJECT_UNCHANGED(pin_control_open_consumer(handle,PIN_CONTROL_UNIT+1,&opened),handle);
    unsigned char readback[sizeof packet];memset(readback,0xa5,sizeof readback);
    REJECT_UNCHANGED(pin_control_read_consumer(handle,0,readback,sizeof readback),handle);
    for(unsigned int i=0;i<sizeof readback;i++)assert(readback[i]==0xa5);
    assert(!pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&opened));references(handle,1,1,0,1,1);
    assert(opened.handle==handle && opened.slot==created.slot && opened.unit==PIN_CONTROL_UNIT &&
        opened.bytes==created.bytes && opened.physical==created.physical && opened.cp_virtual==created.cp_virtual);
    REJECT_UNCHANGED(pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&opened),handle);
    assert(!pin_control_read_consumer(handle,0,readback,sizeof readback) && !memcmp(readback,packet,sizeof packet));
    assert(!memcmp(expected,memory,sizeof memory));
    assert(!pin_control_release_consumer(handle));
    struct pin_control_snapshot retired=snapshot();
    assert(!retired.live && !retired.faults && retired.allocations==prior.allocations+1 && retired.releases==prior.releases+1 &&
        retired.payload_writes==prior.payload_writes+1 && retired.consumer_reads==prior.consumer_reads+1 &&
        retired.consumer_opens==prior.consumer_opens+1 && retired.consumer_closes==prior.consumer_closes+1 &&
        retired.consumer_releases==prior.consumer_releases+1 && retired.creator_closes==closed.creator_closes &&
        retired.creator_transfers==transferred.creator_transfers && retired.creator_releases==prior.creator_releases &&
        retired.shares==prior.shares && pin_control_references(handle,&(struct pin_control_references){0})<0);
    REJECT_UNCHANGED(pin_control_release_consumer(handle),handle);
    REJECT_UNCHANGED(pin_control_close_creator(handle),handle);
    REJECT_UNCHANGED(pin_control_transfer_creator(handle,PIN_CONTROL_UNIT),handle);
    puts("CONTROL_SAME_OWNER_HANDOFF_ACTUAL_16B_READ_FREE_MONOTONIC_NO_SHARE_OR_CREATOR_RELEASE_PASS");
    assert(!pin_control_allocate(PIN_CONTROL_UNIT,&opened) && opened.handle!=handle && opened.slot==created.slot);
    references(opened.handle,1,1,1,0,0);
    REJECT_UNCHANGED(pin_control_close_creator(handle),opened.handle);
    REJECT_UNCHANGED(pin_control_transfer_creator(handle,PIN_CONTROL_UNIT),opened.handle);
    assert(!pin_control_close_creator(opened.handle));references(opened.handle,1,0,1,0,0);
    assert(!pin_control_release(opened.handle));
    struct pin_control_snapshot end=snapshot();
    assert(!end.live && !end.faults && end.allocations==retired.allocations+1 && end.releases==retired.releases+1 &&
        end.creator_releases==retired.creator_releases+1 && end.creator_closes==retired.creator_closes+1 &&
        end.creator_transfers==retired.creator_transfers && !memcmp(expected,memory,sizeof memory));
    puts("CONTROL_CLOSED_CREATOR_RELEASE_AND_REUSED_SLOT_STALE_HANDOFF_NO_EFFECT_PASS");
}
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
    REJECT_UNCHANGED(pin_control_close_creator(0x8000),0x8000);
    REJECT_UNCHANGED(pin_control_transfer_creator(0x8000,PIN_CONTROL_UNIT),0x8000);
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
    puts("VIRTUAL_CONTROL_CONCURRENT_ALLOC_WRITE_RELEASE_80_PASS");
    creator_handoff();return 0;
}
