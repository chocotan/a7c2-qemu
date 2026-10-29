/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include "pin-buffer-owner.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
/* One host byte-array binding for all lifetimes below, never guest evidence. */
static unsigned char memory[PIN_CONTROL_CAPACITY];
static const unsigned char payload[80]={
    0x53,0x53,0x59,0x4e,0,0,0,1,0,0,0,0,1,0,0,0,
    0x20,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0x45,0x54,0x52,0x59,0,0,0,0,0,0,0,0,0x40,0,0,0,
    0x10,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0xc8,0xf4,0x1f,0,0,0,0,0,0,0x0f,0,0,0x70,8,0,0
};
static struct pin_control_snapshot snapshot(void){struct pin_control_snapshot out;pin_control_snapshot(&out);return out;}
static unsigned long long fnv(const unsigned char *data,unsigned int bytes){
    unsigned long long hash=0xcbf29ce484222325ULL;
    for(unsigned int i=0;i<bytes;i++)hash=(hash^data[i])*0x100000001b3ULL;
    return hash;
}
static void references(unsigned int handle,unsigned int owners,unsigned int opens,unsigned int creator,unsigned int consumer,unsigned int consumer_open){
    struct pin_control_references s;assert(!pin_control_references(handle,&s));
    assert(s.handle==handle && s.owners==owners && s.opens==opens && s.creator==creator &&
        s.consumer==consumer && s.consumer_open==consumer_open);
}
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
static void fork_rejected(unsigned int handle){
    struct pin_control_snapshot before=snapshot(),after;
    struct pin_control_references old_refs,new_refs;assert(!pin_control_references(handle,&old_refs));
    unsigned char old_memory[sizeof memory];memcpy(old_memory,memory,sizeof memory);
    pin_control_test_hold_lock();pid_t child=fork();assert(child>=0);
    if(!child){alarm(3);assert(pin_control_release_closed_consumer(handle)==-4);_exit(0);}
    int status=0;assert(waitpid(child,&status,0)==child);
    pin_control_test_drop_lock();assert(WIFEXITED(status) && !WEXITSTATUS(status));
    after=snapshot();assert(!memcmp(&before,&after,sizeof before) && !memcmp(old_memory,memory,sizeof memory));
    assert(!pin_control_references(handle,&new_refs) && !memcmp(&old_refs,&new_refs,sizeof old_refs));
}
int main(void){
    REJECT_UNCHANGED(pin_control_release_closed_consumer(0x8000),0x8000);
    assert(!pin_control_bind_reserved(memory,sizeof memory,PIN_CONTROL_PHYSICAL));
    struct pin_control_lease old,created,opened;
    assert(!pin_control_allocate(PIN_CONTROL_UNIT,&old) && old.handle==0x8000 && !old.slot);
    assert(!pin_control_write_ssyn(old.handle,0));
    assert(!pin_control_share(old.handle,PIN_CONTROL_UNIT));references(old.handle,2,1,1,1,0);
    REJECT_UNCHANGED(pin_control_release_closed_consumer(old.handle),old.handle);
    REJECT_UNCHANGED(pin_control_release_consumer(old.handle),old.handle);
    assert(!pin_control_open_consumer(old.handle,PIN_CONTROL_UNIT,&opened));references(old.handle,2,2,1,1,1);
    REJECT_UNCHANGED(pin_control_release_closed_consumer(old.handle),old.handle);
    assert(!pin_control_close_consumer(old.handle));references(old.handle,2,1,1,1,0);
    REJECT_UNCHANGED(pin_control_release_closed_consumer(old.handle),old.handle);
    REJECT_UNCHANGED(pin_control_release_consumer(old.handle),old.handle);
    assert(!pin_control_open_consumer(old.handle,PIN_CONTROL_UNIT,&opened));
    assert(!pin_control_release_consumer(old.handle));references(old.handle,1,1,1,0,0);
    assert(!pin_control_release(old.handle));
    struct pin_control_snapshot prior=snapshot();
    assert(prior.bound && !prior.live && !prior.faults && !prior.exhausted && prior.allocations==1 && prior.releases==1 &&
        prior.header_writes==1 && prior.shares==1 && prior.consumer_opens==2 && prior.consumer_closes==2 &&
        prior.creator_releases==1 && prior.consumer_releases==1 && !prior.payload_writes && !prior.consumer_reads &&
        !prior.creator_closes && !prior.creator_transfers);
    puts("CLOSED_CONSUMER_OLD_TWO_OWNER_CLOSE_REOPEN_AUTO_FREE_UNCHANGED_PASS");

    assert(!pin_control_allocate(PIN_CONTROL_UNIT,&created) && created.handle==0x8400 && created.slot==old.slot);
    assert(created.physical==old.physical && created.cp_virtual==old.cp_virtual && created.bytes==PIN_CONTROL_SLOT_BYTES);
    unsigned int handle=created.handle;references(handle,1,1,1,0,0);
    REJECT_UNCHANGED(pin_control_release_closed_consumer(handle),handle);
    unsigned char expected[sizeof memory];memcpy(expected,memory,sizeof expected);
    memcpy(expected+created.slot*PIN_CONTROL_SLOT_BYTES,payload,sizeof payload);
    unsigned long long digest=0;assert(!pin_control_write_payload(handle,payload,sizeof payload,&digest));
    assert(digest==fnv(payload,sizeof payload) && !memcmp(memory,expected,sizeof memory));
    assert(!pin_control_close_creator(handle));references(handle,1,0,1,0,0);
    REJECT_UNCHANGED(pin_control_release_closed_consumer(handle),handle);
    assert(!pin_control_transfer_creator(handle,PIN_CONTROL_UNIT));references(handle,1,0,0,1,0);
    REJECT_UNCHANGED(pin_control_close_consumer(handle),handle);
    REJECT_UNCHANGED(pin_control_release_consumer(handle),handle);
    unsigned int invalid[]={old.handle,handle^0x400u,handle|0x10000u,0,0x8010u,handle^0x8000u};
    for(unsigned int i=0;i<sizeof invalid/sizeof invalid[0];i++)
        REJECT_UNCHANGED(pin_control_release_closed_consumer(invalid[i]),handle);
    assert(!pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&opened));references(handle,1,1,0,1,1);
    assert(opened.handle==handle && opened.physical==created.physical && opened.cp_virtual==created.cp_virtual &&
        opened.unit==PIN_CONTROL_UNIT && opened.bytes==created.bytes && opened.slot==created.slot);
    REJECT_UNCHANGED(pin_control_release_closed_consumer(handle),handle);
    unsigned char readback[sizeof payload];
    assert(!pin_control_read_consumer(handle,0,readback,sizeof readback));
    assert(!memcmp(readback,payload,sizeof payload) && fnv(readback,sizeof readback)==digest);
    assert(!pin_control_close_consumer(handle));references(handle,1,0,0,1,0);
    REJECT_UNCHANGED(pin_control_close_consumer(handle),handle);
    REJECT_UNCHANGED(pin_control_release_consumer(handle),handle);
    memset(readback,0xa5,sizeof readback);
    REJECT_UNCHANGED(pin_control_read_consumer(handle,0,readback,sizeof readback),handle);
    for(unsigned int i=0;i<sizeof readback;i++)assert(readback[i]==0xa5);
    fork_rejected(handle);
    puts("CLOSED_CONSUMER_PID_GUARD_PRECEDES_INHERITED_LOCK_PASS");
    struct pin_control_snapshot closed=snapshot();
    assert(closed.live==1 && closed.releases==prior.releases && closed.consumer_closes==prior.consumer_closes+1);
    assert(!pin_control_release_closed_consumer(handle));
    struct pin_control_snapshot retired=snapshot(),want=prior;
    want.allocations++;want.releases++;want.payload_writes++;want.consumer_reads++;want.consumer_opens++;
    want.consumer_closes++;want.consumer_releases++;want.creator_closes++;want.creator_transfers++;
    assert(!memcmp(&retired,&want,sizeof want) && !memcmp(memory,expected,sizeof memory));
    assert(pin_control_references(handle,&(struct pin_control_references){0})<0);
    REJECT_UNCHANGED(pin_control_close_consumer(handle),handle);
    REJECT_UNCHANGED(pin_control_release_consumer(handle),handle);
    REJECT_UNCHANGED(pin_control_release_closed_consumer(handle),handle);
    puts("CLOSED_CONSUMER_SECOND_GENERATION_80B_SSYN_READ_CLOSE_FREE_NO_EXTRA_CLOSE_PASS");

    assert(!pin_control_allocate(PIN_CONTROL_UNIT,&created) && created.handle==0x8800 && created.slot==old.slot);
    REJECT_UNCHANGED(pin_control_release_closed_consumer(handle),created.handle);
    assert(!pin_control_close_creator(created.handle));
    assert(!pin_control_transfer_creator(created.handle,PIN_CONTROL_UNIT));references(created.handle,1,0,0,1,0);
    REJECT_UNCHANGED(pin_control_release_consumer(created.handle),created.handle);
    assert(!pin_control_release_closed_consumer(created.handle));
    struct pin_control_snapshot end=snapshot();want.allocations++;want.releases++;want.creator_closes++;
    want.creator_transfers++;want.consumer_releases++;
    assert(!memcmp(&end,&want,sizeof want) && !memcmp(memory,expected,sizeof memory));
    REJECT_UNCHANGED(pin_control_release_closed_consumer(created.handle),created.handle);
    puts("CLOSED_CONSUMER_NEVER_OPENED_OPTION0_FREE_PRESERVES_BYTES_AND_COUNTS_PASS");
    return 0;
}
