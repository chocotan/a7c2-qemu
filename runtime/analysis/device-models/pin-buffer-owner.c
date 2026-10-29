/* SPDX-License-Identifier: MIT */
#include "pin-buffer-owner.h"
#include <pthread.h>
#include <stdatomic.h>
#include <string.h>
#include <unistd.h>
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static volatile unsigned char *backing;
static struct {unsigned int live,uses,handle,creator,creator_open,consumer,consumer_open;} slots[PIN_CONTROL_SLOTS];
static struct pin_control_snapshot state;
static int current_process(void){
    int pid=(int)getpid(),expected=0;
    atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    return atomic_load(&owner_pid)==pid;
}
static int slot_for(unsigned int handle){
    unsigned int slot=handle&0x3ff;
    if((handle&0xffff0000u) || !(handle&0x8000) || slot>=PIN_CONTROL_SLOTS ||
       !slots[slot].live || slots[slot].handle!=handle)return -1;
    return (int)slot;
}
static void describe(unsigned int index,struct pin_control_lease *out){
    unsigned int offset=index*PIN_CONTROL_SLOT_BYTES;
    *out=(struct pin_control_lease){slots[index].handle,PIN_CONTROL_UNIT,index,PIN_CONTROL_SLOT_BYTES,
        PIN_CONTROL_CP_VIRTUAL+offset,PIN_CONTROL_PHYSICAL+offset};
}
static void retire_if_unused(unsigned int index){
    if(slots[index].creator || slots[index].consumer)return;
    slots[index].live=0;state.live--;state.releases++;
    if(slots[index].uses==32)state.exhausted++;
    /* Ownership ends here; previously written bytes are not erased. */
}
int pin_control_bind_reserved(volatile unsigned char *memory,unsigned long capacity,unsigned long long physical){
    if(!memory || capacity!=PIN_CONTROL_CAPACITY || physical!=PIN_CONTROL_PHYSICAL)return -1;
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);
    if(state.bound){pthread_mutex_unlock(&mutex);return -2;}
    for(unsigned long i=0;i<capacity;i++)if(memory[i]){pthread_mutex_unlock(&mutex);return -3;}
    backing=memory;state.bound=1;pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_allocate(unsigned int unit,struct pin_control_lease *out){
    if(!out || unit!=PIN_CONTROL_UNIT)return -1;
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);
    if(!state.bound || state.faults){pthread_mutex_unlock(&mutex);return -2;}
    for(unsigned int i=0;i<PIN_CONTROL_SLOTS;i++)if(!slots[i].live && slots[i].uses<32){
        unsigned int handle=0x8000u|(slots[i].uses<<10)|i;
        slots[i].uses++;slots[i].live=1;slots[i].handle=handle;slots[i].creator=slots[i].creator_open=1;
        slots[i].consumer=slots[i].consumer_open=0;state.live++;state.allocations++;
        describe(i,out);
        pthread_mutex_unlock(&mutex);return 0;
    }
    pthread_mutex_unlock(&mutex);return -3;
}
int pin_control_write_ssyn(unsigned int handle,unsigned long long *digest){
    static const unsigned char header[32]={0x53,0x53,0x59,0x4e,0,0,0,1};
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || !slots[index].creator || !slots[index].creator_open || slots[index].consumer){pthread_mutex_unlock(&mutex);return -1;}
    volatile unsigned char *destination=backing+(unsigned int)index*PIN_CONTROL_SLOT_BYTES;
    for(unsigned int i=0;i<sizeof header;i++)destination[i]=header[i];
    unsigned long long hash=0xcbf29ce484222325ULL;
    for(unsigned int i=0;i<sizeof header;i++){
        unsigned char value=destination[i];
        if(value!=header[i]){state.faults++;pthread_mutex_unlock(&mutex);return -2;}
        hash=(hash^value)*0x100000001b3ULL;
    }
    state.header_writes++;if(digest)*digest=hash;pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_write_payload(unsigned int handle,const unsigned char *data,unsigned int bytes,unsigned long long *digest){
    if(!data || !bytes || bytes>PIN_CONTROL_SLOT_BYTES)return -1;
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || !slots[index].creator || !slots[index].creator_open || slots[index].consumer){pthread_mutex_unlock(&mutex);return -1;}
    volatile unsigned char *destination=backing+(unsigned int)index*PIN_CONTROL_SLOT_BYTES;
    for(unsigned int i=0;i<bytes;i++)destination[i]=data[i];
    unsigned long long hash=0xcbf29ce484222325ULL;
    for(unsigned int i=0;i<bytes;i++){
        unsigned char value=destination[i];
        if(value!=data[i]){state.faults++;pthread_mutex_unlock(&mutex);return -2;}
        hash=(hash^value)*0x100000001b3ULL;
    }
    state.payload_writes++;if(digest)*digest=hash;pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_close_creator(unsigned int handle){
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || !slots[index].creator || !slots[index].creator_open || slots[index].consumer || slots[index].consumer_open){pthread_mutex_unlock(&mutex);return -1;}
    slots[index].creator_open=0;state.creator_closes++;pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_transfer_creator(unsigned int handle,unsigned int unit){
    if(unit!=PIN_CONTROL_UNIT)return -1;
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || !slots[index].creator || slots[index].creator_open || slots[index].consumer || slots[index].consumer_open){pthread_mutex_unlock(&mutex);return -1;}
    slots[index].creator=0;slots[index].consumer=1;state.creator_transfers++;pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_share(unsigned int handle,unsigned int unit){
    if(unit!=PIN_CONTROL_UNIT)return -1;
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || !slots[index].creator || !slots[index].creator_open || slots[index].consumer){pthread_mutex_unlock(&mutex);return -1;}
    slots[index].consumer=1;state.shares++;pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_open_consumer(unsigned int handle,unsigned int unit,struct pin_control_lease *out){
    if(!out || unit!=PIN_CONTROL_UNIT)return -1;
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || !slots[index].consumer || slots[index].consumer_open){pthread_mutex_unlock(&mutex);return -1;}
    slots[index].consumer_open=1;state.consumer_opens++;describe((unsigned int)index,out);
    pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_read_consumer(unsigned int handle,unsigned int offset,unsigned char *out,unsigned int bytes){
    if(!out || !bytes || offset>PIN_CONTROL_SLOT_BYTES || bytes>PIN_CONTROL_SLOT_BYTES-offset)return -1;
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || !slots[index].consumer || !slots[index].consumer_open){pthread_mutex_unlock(&mutex);return -1;}
    volatile unsigned char *source=backing+(unsigned int)index*PIN_CONTROL_SLOT_BYTES+offset;
    for(unsigned int i=0;i<bytes;i++)out[i]=source[i];
    state.consumer_reads++;pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_close_consumer(unsigned int handle){
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || !slots[index].consumer || !slots[index].consumer_open){pthread_mutex_unlock(&mutex);return -1;}
    slots[index].consumer_open=0;state.consumer_closes++;pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_release_consumer(unsigned int handle){
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || !slots[index].consumer || !slots[index].consumer_open){pthread_mutex_unlock(&mutex);return -1;}
    slots[index].consumer_open=slots[index].consumer=0;state.consumer_closes++;state.consumer_releases++;
    retire_if_unused((unsigned int)index);pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_release_closed_consumer(unsigned int handle){
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || slots[index].creator || !slots[index].consumer || slots[index].consumer_open){pthread_mutex_unlock(&mutex);return -1;}
    slots[index].consumer=0;state.consumer_releases++;
    retire_if_unused((unsigned int)index);pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_references(unsigned int handle,struct pin_control_references *out){
    if(!out)return -1;
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults){pthread_mutex_unlock(&mutex);return -1;}
    *out=(struct pin_control_references){handle,slots[index].creator+slots[index].consumer,
        slots[index].creator_open+slots[index].consumer_open,slots[index].creator,slots[index].consumer,slots[index].consumer_open};
    pthread_mutex_unlock(&mutex);return 0;
}
int pin_control_release(unsigned int handle){
    if(!current_process())return -4;
    pthread_mutex_lock(&mutex);int index=slot_for(handle);
    if(index<0 || !state.bound || state.faults || !slots[index].creator){pthread_mutex_unlock(&mutex);return -1;}
    slots[index].creator=slots[index].creator_open=0;state.creator_releases++;retire_if_unused((unsigned int)index);
    pthread_mutex_unlock(&mutex);return 0;
}
void pin_control_snapshot(struct pin_control_snapshot *out){
    if(!out)return;
    if(!current_process()){*out=(struct pin_control_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);
}
#ifdef PIN_CONTROL_TEST
void pin_control_test_reset(void){
    pthread_mutex_lock(&mutex);state=(struct pin_control_snapshot){0};memset(slots,0,sizeof slots);backing=0;atomic_store(&owner_pid,(int)getpid());pthread_mutex_unlock(&mutex);
}
void pin_control_test_hold_lock(void){pthread_mutex_lock(&mutex);}
void pin_control_test_drop_lock(void){pthread_mutex_unlock(&mutex);}
#endif
