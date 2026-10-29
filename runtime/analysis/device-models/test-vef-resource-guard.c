/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "vef-resource-guard.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static unsigned char fixture[DMM_TEST_SIZE], backing_before[DMM_TEST_SIZE];
static struct full_vef_resource_snapshot empty_fixture(void)
{
    /* Host-only metadata fixture, never a guest resource observation. */
    struct full_vef_resource_snapshot s={0};
    s.dmm_enabled=1;s.dmm.memory=fixture;s.dmm.physical=DMM_TEST_PHYSICAL;
    s.control.bound=1;s.control.allocations=s.control.releases=1;
    s.connection.started=1;s.connection.connections=1;s.connection.format_consumed=1;
    s.connection.buffer_released=1;s.connection.native_reply_frees=1;
    s.vef.initialized=s.pinmem.initialized=1;
    s.vef.registry_objects=16;s.pinmem.registry_objects=21;
    s.vef.owner_sid=FULL_VEF_CP;s.pinmem.owner_sid=FULL_PINMEM_CP;
    /* A connected pin is legitimate; resource idle does not clear its state. */
    s.vef.pins[10].state=0;s.vef.pins[10].peer[3]=FULL_PINMEM_CP;
    return s;
}
static void put_le(unsigned char *p,unsigned long long value,unsigned int bytes)
{
    for (unsigned int i=0;i<bytes;i++) p[i]=(unsigned char)(value>>(8*i));
}
static struct full_vef_resource_snapshot speech_fixture(void)
{
    struct full_vef_resource_snapshot s=empty_fixture();
    s.dmm.allocations=2;s.appfw_base=0x7f2645e000UL;
    s.speech_address=s.appfw_base+0x5f66b08UL;
    s.speech_read_before=s.speech_read_after=0x90;
    for (unsigned int i=0;i<2;i++) {
        struct dmm_slot *slot=&s.dmm.slots[i];
        slot->allocated=slot->open_count=slot->generation=1;
        slot->handle=0x8400U|i;slot->allocation_epoch=i+1;
        slot->creator_kind=DMM_CREATOR_SPEECH_INITIAL;
        unsigned char *entry=s.speech_before+i*0x48;
        put_le(entry,0x1a+i,4);put_le(entry+0x18,slot->handle,4);
        put_le(entry+0x1c,0x80000,4);put_le(entry+0x20,0x1e000000ULL+i*0x80000ULL,8);
    }
    memcpy(s.speech_after,s.speech_before,sizeof s.speech_after);
    return s;
}
static void check_classification(const struct full_vef_resource_snapshot *s,
                                 enum full_vef_dmm_domain domain,int admitted)
{
    unsigned char before[sizeof *s];
    if (s) memcpy(before,s,sizeof *s);
    memcpy(backing_before,fixture,sizeof fixture);
    assert(full_vef_resource_dmm_domain(s)==domain);
    assert(full_vef_resources_admissible(s)==admitted);
    if (s) assert(!memcmp(before,s,sizeof *s));
    assert(!memcmp(backing_before,fixture,sizeof fixture));
}
static void check_predicate(void)
{
    struct full_vef_resource_snapshot s=empty_fixture();
    check_classification(&s,FULL_VEF_DMM_EMPTY,1);
    check_classification(0,FULL_VEF_DMM_UNKNOWN,0);
    for (unsigned int speech=0;speech<2;speech++) {
        for (unsigned int kind=0;kind<19;kind++) {
            s=speech?speech_fixture():empty_fixture();
            switch(kind) {
            case 0:s.dmm_enabled=0;break;
            case 1:s.dmm.memory=0;break;
            case 2:s.dmm.physical++;break;
            case 3:s.dmm.slots[0].allocated=speech?0:1;break;
            case 4:s.dmm.slots[1].open_count=speech?0:1;break;
            case 5:s.control.bound=0;break;
            case 6:s.control.live=1;break;
            case 7:s.control.faults=1;break;
            case 8:s.control.releases=0;break;
            case 9:s.control.allocations=s.control.releases=0;break;
            case 10:s.connection.started=0;break;
            case 11:s.connection.connections=2;break;
            case 12:s.connection.faults=1;break;
            case 13:s.connection.format_pending=1;break;
            case 14:s.connection.blocked_requests=1;break;
            case 15:s.connection.format_consumed=0;break;
            case 16:s.connection.buffer_released=0;break;
            case 17:s.connection.native_reply_frees=0;break;
            case 18:s.connection.connections=0;break;
            }
            check_classification(&s,kind<5?FULL_VEF_DMM_UNKNOWN:
                                 speech?FULL_VEF_DMM_SPEECH_INITIAL:FULL_VEF_DMM_EMPTY,0);
        }
        for (unsigned int index=0;index<2;index++) for (unsigned int kind=0;kind<8;kind++) {
            s=speech?speech_fixture():empty_fixture();struct full_vef_snapshot *r=index?&s.pinmem:&s.vef;
            switch(kind) {
            case 0:r->initialized=0;break;
            case 1:r->registry_objects=0;break;
            case 2:r->owner_sid=0;break;
            case 3:r->faults=1;break;
            case 4:r->pending=1;break;
            case 5:r->live_replies=1;break;
            case 6:r->retained_request=&fixture;break;
            case 7:r->retained_reply=&fixture;break;
            }
            check_classification(&s,speech?FULL_VEF_DMM_SPEECH_INITIAL:FULL_VEF_DMM_EMPTY,0);
        }
    }
    s=empty_fixture();s.dmm.slots[0].handle=0x9400;s.dmm.slots[0].generation=5;
    s.dmm.allocations=33;s.dmm.lifecycle_changed=1;s.speech_read_before=-1;
    check_classification(&s,FULL_VEF_DMM_EMPTY,1); /* retired handles retain generation */
}
static void check_speech_domain(void)
{
    struct full_vef_resource_snapshot s=speech_fixture();
    check_classification(&s,FULL_VEF_DMM_SPEECH_INITIAL,1);
    for (unsigned int kind=0;kind<19;kind++) {
        s=speech_fixture();
        switch(kind) {
        case 0:s.dmm.allocations=0;break;
        case 1:s.dmm.allocations=1;break;
        case 2:s.dmm.allocations=3;break;
        case 3:s.dmm.lifecycle_changed=1;break;
        case 4:s.dmm.lifecycle_changed=2;break;
        case 5:s.appfw_base=0;break;
        case 6:s.appfw_base=0xffff;s.speech_address=s.appfw_base+0x5f66b08UL;break;
        case 7:s.appfw_base=0x7ff0000000UL;s.speech_address=s.appfw_base+0x5f66b08UL;break;
        case 8:s.speech_address++;break;
        case 9:s.speech_read_before=-1;break;
        case 10:s.speech_read_before=0x8f;break;
        case 11:s.speech_read_before=0x91;break;
        case 12:s.speech_read_after=-1;break;
        case 13:s.speech_read_after=0x8f;break;
        case 14:s.speech_read_after=0x91;break;
        case 15:s.speech_after[0x2f]^=1;break;
        case 16:memset(s.speech_before,0,sizeof s.speech_before);break;
        case 17:memset(s.speech_after,0,sizeof s.speech_after);break;
        case 18:memset(s.speech_before,0,sizeof s.speech_before);
                memset(s.speech_after,0,sizeof s.speech_after);break;
        }
        check_classification(&s,FULL_VEF_DMM_UNKNOWN,0);
    }
    for (unsigned int index=0;index<2;index++) for (unsigned int kind=0;kind<17;kind++) {
        s=speech_fixture();struct dmm_slot *slot=&s.dmm.slots[index];
        switch(kind) {
        case 0:slot->allocated=0;break;
        case 1:slot->allocated=2;break;
        case 2:slot->allocated=-1;break;
        case 3:slot->open_count=0;break;
        case 4:slot->open_count=2;break;
        case 5:slot->generation=0;break;
        case 6:slot->generation=2;break;
        case 7:slot->allocation_epoch=0;break;
        case 8:slot->allocation_epoch=33+index;break;
        case 9:slot->allocation_epoch=2-index;break;
        case 10:slot->creator_kind=DMM_CREATOR_UNKNOWN;break;
        case 11:slot->creator_kind=2;break;
        case 12:slot->handle&=~0x8000U;break;
        case 13:slot->handle|=0x10000U;break;
        case 14:slot->handle^=1;break;
        case 15:slot->handle^=0xc00;break;
        case 16:slot->handle=0;break;
        }
        check_classification(&s,FULL_VEF_DMM_UNKNOWN,0);
    }
    for (unsigned int index=0;index<2;index++) for (unsigned int kind=0;kind<12;kind++) {
        s=speech_fixture();unsigned char *entry=s.speech_before+index*0x48;
        switch(kind) {
        case 0:put_le(entry,0,4);break;
        case 1:put_le(entry,0x1a+(1-index),4);break;
        case 2:put_le(entry+0x18,0x8400U|(1-index),4);break;
        case 3:put_le(entry+0x18,0x400U|index,4);break;
        case 4:put_le(entry+0x18,0x18400U|index,4);break;
        case 5:put_le(entry+0x1c,0x80001,4);break;
        case 6:put_le(entry+0x1c,0,4);break;
        case 7:put_le(entry+0x1c,0x7ffff,4);break;
        case 8:put_le(entry+0x20,0x1e000001ULL+index*0x80000ULL,8);break;
        case 9:put_le(entry+0x20,0x1e000000ULL+(1-index)*0x80000ULL,8);break;
        case 10:put_le(entry+0x20,DMM_TEST_PHYSICAL+index*0x80000ULL,8);break;
        case 11:put_le(entry+0x20,0x11e000000ULL+index*0x80000ULL,8);break;
        }
        memcpy(s.speech_after,s.speech_before,sizeof s.speech_after);
        check_classification(&s,FULL_VEF_DMM_UNKNOWN,0);
    }
    for (unsigned int boundary=0;boundary<2;boundary++) {
        s=speech_fixture();s.appfw_base=boundary?0x7fefffffffUL:0x10000UL;
        s.speech_address=s.appfw_base+0x5f66b08UL;
        check_classification(&s,FULL_VEF_DMM_SPEECH_INITIAL,1);
    }
    s=speech_fixture();
    for (unsigned int index=0;index<2;index++) {
        /* AP locals and mapping pointers are not mapping or admission proof. */
        put_le(s.speech_before+index*0x48+4,index?0xffffffffU:0,4);
        put_le(s.speech_before+index*0x48+0x28,index?~0ULL:0,8);
    }
    memcpy(s.speech_after,s.speech_before,sizeof s.speech_after);
    check_classification(&s,FULL_VEF_DMM_SPEECH_INITIAL,1);
    puts("VEF_DMM_DOMAIN_PASS empty and initial Speech only; metadata and backing unchanged");
}
static void dmm_operation(struct dmm_service *s,unsigned int op,unsigned int handle,unsigned int option)
{
    unsigned char request[40]={0},reply[40];
    put_le(request,op,2);put_le(request+4,0x63a,4);
    put_le(request+8,handle,4);put_le(request+22,option,2);
    assert(!dmm_service_reply(s,request,sizeof request,reply));
    assert(!reply[2] && !reply[3]);
}
static void check_speech_lifecycle(void)
{
    for (unsigned int index=0;index<2;index++) {
        struct full_vef_resource_snapshot s=speech_fixture();
        unsigned int handle=s.dmm.slots[index].handle;
        dmm_operation(&s.dmm,0x21,handle,0);
        assert(s.dmm.slots[index].open_count==2);
        check_classification(&s,FULL_VEF_DMM_UNKNOWN,0);
        dmm_operation(&s.dmm,0x22,handle,0);
        assert(s.dmm.slots[index].open_count==1 && s.dmm.lifecycle_changed);
        check_classification(&s,FULL_VEF_DMM_UNKNOWN,0);
        s=speech_fixture();dmm_operation(&s.dmm,0x23,handle,2);
        check_classification(&s,FULL_VEF_DMM_UNKNOWN,0);
        dmm_operation(&s.dmm,0x20,0,1);
        assert(s.dmm.slots[index].creator_kind==DMM_CREATOR_UNKNOWN);
        check_classification(&s,FULL_VEF_DMM_UNKNOWN,0);
    }
    struct full_vef_resource_snapshot s=speech_fixture();
    for (unsigned int cycle=0;cycle<31;cycle++) {
        dmm_operation(&s.dmm,0x23,s.dmm.slots[0].handle,2);
        dmm_operation(&s.dmm,0x20,0,1);
    }
    assert(s.dmm.slots[0].handle==0x8400 && s.dmm.slots[0].generation==1 &&
           s.dmm.slots[0].open_count==1 && s.dmm.slots[0].allocation_epoch==33);
    check_classification(&s,FULL_VEF_DMM_UNKNOWN,0);
    /* Isolate epoch rejection even if other history metadata were forged. */
    s.dmm.slots[0].creator_kind=DMM_CREATOR_SPEECH_INITIAL;
    s.dmm.allocations=2;s.dmm.lifecycle_changed=0;
    check_classification(&s,FULL_VEF_DMM_UNKNOWN,0);
    puts("VEF_DMM_LIFECYCLE_PASS real reference roundtrip and generation reuse rejected");
}
static int sender_exit(unsigned int destination,int value)
{
    int held __attribute__((cleanup(full_vef_resource_send_leave)))=
        full_vef_resource_send_enter(destination,1);
    if (held<0) return held;
    if (value<0) return value;
    return value+1;
}
static pthread_mutex_t observation=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed=PTHREAD_COND_INITIALIZER;
static int attempting,acquired;
static void *mutator(void *arg)
{
    unsigned int destination=*(unsigned int *)arg;
    pthread_mutex_lock(&observation);attempting=1;pthread_cond_broadcast(&changed);pthread_mutex_unlock(&observation);
    int held=full_vef_resource_send_enter(destination,1);assert(held==1);
    pthread_mutex_lock(&observation);acquired=1;pthread_cond_broadcast(&changed);pthread_mutex_unlock(&observation);
    full_vef_resource_send_leave(&held);assert(!held);return 0;
}
static void check_gate(void)
{
    const unsigned int destinations[]={FULL_VEF_CP,FULL_PINMEM_CP,0x9061003c};
    assert(!full_vef_resources_owner_init());
    for (unsigned int index=0;index<3;index++) {
        unsigned int destination=destinations[index];
        assert(!full_vef_resource_send_enter(destination,0));
        assert(sender_exit(destination,-7)==-7 && sender_exit(destination,4)==5);
        assert(!full_vef_resources_test_trylock());full_vef_resources_unlock();
        assert(!full_vef_resources_lock());
        assert(!full_vef_resource_send_enter(0x81cf61c9,1)); /* unrelated IPC stays unblocked */
        attempting=acquired=0;pthread_t thread;assert(!pthread_create(&thread,0,mutator,&destination));
        pthread_mutex_lock(&observation);
        while (!attempting) pthread_cond_wait(&changed,&observation);
        struct timespec deadline;assert(!clock_gettime(CLOCK_REALTIME,&deadline));
        deadline.tv_nsec+=100000000;if(deadline.tv_nsec>=1000000000){deadline.tv_sec++;deadline.tv_nsec-=1000000000;}
        int rc=0;while (!acquired && !rc) rc=pthread_cond_timedwait(&changed,&observation,&deadline);
        assert(rc==ETIMEDOUT && !acquired);
        pthread_mutex_unlock(&observation);
        full_vef_resources_unlock();assert(!pthread_join(thread,0));assert(acquired);
    }
    assert(!full_vef_resources_lock());
    pid_t child=fork();assert(child>=0);
    if (!child) {
        alarm(2);
        for (unsigned int i=0;i<3;i++) assert(full_vef_resource_send_enter(destinations[i],1)==-1021);
        assert(full_vef_resources_lock()==-1021 && full_vef_resources_owner_init()==-1021);
        _exit(0);
    }
    int status=0;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
    full_vef_resources_unlock();
    assert(!full_vef_resources_test_trylock());full_vef_resources_unlock();
}
int main(void)
{
    memset(fixture,0xa5,sizeof fixture);
    check_predicate();check_speech_domain();check_speech_lifecycle();check_gate();
    puts("VEF_RESOURCE_GUARD_PASS known tracked resources only; atomic sender/reservation gate, early returns, inherited PID rejected");
    return 0;
}
