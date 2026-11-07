/* SPDX-License-Identifier: MIT */
#define _XOPEN_SOURCE 700
#include "pin-buffer-owner.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
/* Host fixture only. The bytes are deliberately not an ETRY/format proof. */
static unsigned char memory[PIN_CONTROL_CAPACITY],payload[80];
static pthread_barrier_t barrier;
static unsigned int concurrent_handle;
static struct pin_control_snapshot snapshot(void){struct pin_control_snapshot s;pin_control_snapshot(&s);return s;}
static void references(unsigned int handle,unsigned int creator,unsigned int consumer,unsigned int open){
    struct pin_control_references s;assert(!pin_control_references(handle,&s));
    assert(s.handle==handle && s.creator==creator && s.consumer==consumer && s.consumer_open==open);
    assert(s.owners==creator+consumer && s.opens==creator+open);
}
static void reset(void){
    pin_control_test_reset();memset(memory,0,sizeof memory);
    assert(!pin_control_bind_reserved(memory,sizeof memory,PIN_CONTROL_PHYSICAL));
}
static void sync_threads(void){int rc=pthread_barrier_wait(&barrier);assert(!rc || rc==PTHREAD_BARRIER_SERIAL_THREAD);}
static void *creator_release(void *unused){
    (void)unused;sync_threads();assert(!pin_control_release(concurrent_handle));return 0;
}
static void *consumer_read_release(void *unused){
    (void)unused;unsigned char readback[sizeof payload];sync_threads();
    for(unsigned int i=0;i<12;i++){
        assert(!pin_control_read_consumer(concurrent_handle,0,readback,sizeof readback));
        assert(!memcmp(readback,payload,sizeof payload));
    }
    assert(!pin_control_release_consumer(concurrent_handle));return 0;
}
int main(void){
    for(unsigned int i=0;i<sizeof payload;i++)payload[i]=(unsigned char)(i*37+11);
    for(unsigned int consumer_first=0;consumer_first<2;consumer_first++){
        reset();struct pin_control_lease created,opened,other;unsigned char readback[sizeof payload],before[sizeof payload];
        assert(!pin_control_allocate(PIN_CONTROL_UNIT,&created));unsigned int handle=created.handle;
        references(handle,1,0,0);
        assert(pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&opened)<0);
        assert(pin_control_release_consumer(handle)<0);
        assert(!pin_control_write_payload(handle,payload,sizeof payload,0));memcpy(before,memory,sizeof before);
        assert(pin_control_share(handle,PIN_CONTROL_UNIT+1)<0);
        assert(!pin_control_share(handle,PIN_CONTROL_UNIT));references(handle,1,1,0);
        assert(pin_control_share(handle,PIN_CONTROL_UNIT)<0);
        assert(pin_control_read_consumer(handle,0,readback,sizeof readback)<0);
        assert(pin_control_write_payload(handle,payload,sizeof payload,0)<0 && pin_control_write_ssyn(handle,0)<0);
        assert(!memcmp(before,memory,sizeof before));
        assert(!pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&opened));references(handle,1,1,1);
        assert(created.handle==opened.handle && created.unit==opened.unit && created.slot==opened.slot &&
            created.bytes==opened.bytes && created.cp_virtual==opened.cp_virtual && created.physical==opened.physical);
        assert(pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&opened)<0);
        memset(readback,0xa5,sizeof readback);
        assert(pin_control_read_consumer(handle,0xffffffff,readback,2)<0 && readback[0]==0xa5);
        assert(pin_control_read_consumer(handle,PIN_CONTROL_SLOT_BYTES-1,readback,2)<0 && readback[0]==0xa5);
        assert(!pin_control_read_consumer(handle,0,readback,sizeof readback) && !memcmp(readback,payload,sizeof payload));
        if(consumer_first){
            assert(!pin_control_release_consumer(handle));references(handle,1,0,0);
            assert(pin_control_release_consumer(handle)<0);
        }else{
            assert(!pin_control_release(handle));references(handle,0,1,1);
            assert(pin_control_release(handle)<0);
            assert(!pin_control_read_consumer(handle,0,readback,sizeof readback) && !memcmp(readback,payload,sizeof payload));
        }
        assert(snapshot().live==1 && !snapshot().releases);
        assert(!pin_control_allocate(PIN_CONTROL_UNIT,&other) && other.slot==1);assert(!pin_control_release(other.handle));
        if(consumer_first)assert(!pin_control_release(handle));else assert(!pin_control_release_consumer(handle));
        assert(pin_control_references(handle,&(struct pin_control_references){0})<0);
        assert(pin_control_release(handle)<0 && pin_control_release_consumer(handle)<0 && !snapshot().live);
        assert(!pin_control_allocate(PIN_CONTROL_UNIT,&other) && other.slot==0 && other.handle!=handle);
        assert(pin_control_share(handle,PIN_CONTROL_UNIT)<0 && pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&opened)<0);
        assert(!pin_control_release(other.handle));
    }
    puts("CONTROL_SHARED_BACKING_TWO_RELEASE_ORDERS_DISTINCT_ROLE_DOUBLE_RELEASE_REFUSED_PASS");
    reset();struct pin_control_lease created,opened;
    assert(!pin_control_allocate(PIN_CONTROL_UNIT,&created));unsigned int handle=created.handle;
    assert(!pin_control_write_payload(handle,payload,sizeof payload,0));
    assert(!pin_control_share(handle,PIN_CONTROL_UNIT) && !pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&opened));
    assert(!pin_control_release(handle) && !pin_control_close_consumer(handle));references(handle,0,1,0);
    assert(snapshot().live==1 && !snapshot().releases && pin_control_close_consumer(handle)<0);
    unsigned char readback[80];assert(pin_control_read_consumer(handle,0,readback,sizeof readback)<0);
    assert(pin_control_release_consumer(handle)<0);
    assert(!pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&opened));
    assert(!pin_control_read_consumer(handle,0,readback,sizeof readback) && !memcmp(readback,payload,sizeof payload));
    assert(!pin_control_release_consumer(handle) && !snapshot().live);
    puts("CONTROL_CONSUMER_CLOSE_PRESERVES_SHARED_OWNER_REOPEN_REAL_BACKING_PASS");
    reset();assert(!pthread_barrier_init(&barrier,0,2));
    for(unsigned int i=0;i<64;i++){
        assert(!pin_control_allocate(PIN_CONTROL_UNIT,&created));concurrent_handle=created.handle;
        assert(!pin_control_write_payload(concurrent_handle,payload,sizeof payload,0));
        assert(!pin_control_share(concurrent_handle,PIN_CONTROL_UNIT) && !pin_control_open_consumer(concurrent_handle,PIN_CONTROL_UNIT,&opened));
        pthread_t a,b;assert(!pthread_create(&a,0,creator_release,0) && !pthread_create(&b,0,consumer_read_release,0));
        assert(!pthread_join(a,0) && !pthread_join(b,0));assert(!snapshot().live && !snapshot().faults);
    }
    assert(!pthread_barrier_destroy(&barrier));struct pin_control_snapshot s=snapshot();
    assert(s.allocations==64 && s.releases==64 && s.shares==64 && s.creator_releases==64 && s.consumer_releases==64 && s.consumer_reads==64*12);
    puts("CONTROL_CONCURRENT_CREATOR_RELEASE_CONSUMER_768_ACTUAL_READS_64_LEASES_PASS");return 0;
}
