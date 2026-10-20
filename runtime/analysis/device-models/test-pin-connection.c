/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "pin-connection.h"
#include "vef-device.h"
#include "pinmem-device.h"
#include "pin-buffer-owner.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct message {unsigned int owner,source,bytes;unsigned char data[];};
static void *live[64],*queued,*alias;
static unsigned int allocation_count,fail_allocation,send_failure,fail_release;
static unsigned int alias_peer_reply,bad_size,fail_peer_free,fail_request_free;
static void *last64;
static unsigned int peer_request_events,peer_reply_events,dmm_request_events,dmm_reply_events,blocked_events;
static unsigned int format_injection;
static unsigned char backing[PIN_CONTROL_CAPACITY];
static const char *host_fixture;
static unsigned int D=0x81da02a4;
static struct message *header(void *p){return (struct message *)((char *)p - offsetof(struct message,data));}
static void put16(unsigned char *p,unsigned int n){p[0]=(unsigned char)n;p[1]=(unsigned char)(n>>8);}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static int allocate(unsigned int id,void **out,unsigned int n,unsigned int wait){
    assert(wait==1);allocation_count++;
    if(allocation_count==fail_allocation){*out=0;return -88;}
    if(alias){*out=alias;alias=0;return 0;}
    if(alias_peer_reply && n==72){alias_peer_reply=0;*out=last64;return 0;}
    struct message *m=calloc(1,sizeof *m+n);assert(m);m->owner=id;m->bytes=n;*out=m->data;
    if(n==64)last64=*out;
    if(bad_size==n)m->bytes=n-1;
    for(unsigned int i=0;i<64;i++)if(!live[i]){live[i]=*out;return 0;}
    abort();
}
static int release(unsigned int id,void *p){
    assert(p && header(p)->owner==id);
    if(fail_release){fail_release=0;return -89;}
    for(unsigned int i=0;i<64;i++)if(live[i]==p){live[i]=0;memset(p,0xde,header(p)->bytes);free(header(p));return 0;}
    abort();
}
static unsigned int size(void *p){return header(p)->bytes;}
static unsigned int source(void *p){return header(p)->source;}
static void set_source(void *p,unsigned int id){header(p)->source=id;}
static int send(unsigned int id,void *p){assert(header(p)->owner==id && !queued);if(send_failure)return -77;queued=p;return 0;}
static void record(const char *kind,const char *line){
    assert(line);peer_request_events+=!strcmp(kind,"FULL_PIN_CONNECT_PEER_REQUEST ");peer_reply_events+=!strcmp(kind,"FULL_PIN_CONNECT_PEER_REPLY ");
    if(host_fixture)printf("OBS %s%s\n",kind,line);
    dmm_request_events+=!strcmp(kind,"FULL_PIN_CONNECT_DMM_REQUEST ");dmm_reply_events+=!strcmp(kind,"FULL_PIN_CONNECT_DMM_REPLY ");
    blocked_events+=!strcmp(kind,"FULL_PIN_CONNECT_FORMAT_BLOCKED_REQUEST ");
    if(fail_peer_free && !strcmp(kind,"FULL_PIN_CONNECT_PEER_REPLY ")){fail_peer_free=0;fail_release=1;}
    if(fail_request_free && !strcmp(kind,"FULL_PIN_CONNECT_REPLY_QUEUED ")){fail_request_free=0;fail_release=1;}
    if(format_injection && !strcmp(kind,"FULL_PIN_CONNECT_FORMAT_NOTIFY_QUEUED ")){
        if(format_injection==1)backing[0]=0;
        else if(format_injection==2){for(unsigned int i=0;i<64;i++)if(live[i] && size(live[i])==80)put32((unsigned char *)live[i]+64,0x405);}
        else{for(unsigned int i=0;i<64;i++)if(live[i] && size(live[i])==80)alias=live[i];}
        format_injection=0;
    }
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static unsigned char *request(unsigned int owner,unsigned int bytes,unsigned int command,unsigned int dir,unsigned int index){
    void *p=0;assert(!allocate(owner,&p,bytes,1));unsigned char *out=p;set_source(p,D);
    if(bytes>=24){put32(out,D);put32(out+4,0xa0a0a0a0);put16(out+8,1);put16(out+10,bytes);put32(out+12,24);put32(out+16,bytes);}
    if(bytes>=48){put16(out+24,0x1000);put16(out+26,command);put16(out+28,bytes-24);put16(out+30,2);put32(out+36,dir);put32(out+40,index);}
    if(bytes==64){put32(out+44,FULL_VEF_CP);put32(out+52,1);put32(out+56,1);put32(out+60,FULL_PINMEM_CP);}
    return out;
}
static void seed(void){
    int rc=123;void *r=request(FULL_VEF_CP,48,0,2,3);
    assert(full_vef_dispatch(FULL_VEF_CP,r,&io,1,&rc) && !rc);assert(full_vef_release_reply(D,queued,release,record,&rc) && !rc);queued=0;
    r=request(FULL_PINMEM_CP,48,0,1,1);
    assert(full_pinmem_dispatch(FULL_PINMEM_CP,r,&io,1,&rc) && !rc);assert(full_pinmem_release_reply(D,queued,release,record,&rc) && !rc);queued=0;
}
static void reset(void){
    full_pin_connection_test_reset();full_vef_test_reset();full_pinmem_test_reset();pin_control_test_reset();
    for(unsigned int i=0;i<64;i++)if(live[i]){free(header(live[i]));live[i]=0;}
    queued=alias=0;allocation_count=fail_allocation=send_failure=fail_release=0;
    alias_peer_reply=bad_size=fail_peer_free=fail_request_free=0;last64=0;
    peer_request_events=peer_reply_events=dmm_request_events=dmm_reply_events=blocked_events=0;
    format_injection=0;
    memset(backing,0,sizeof backing);
}
static struct pin_connection_snapshot snapshot(void){struct pin_connection_snapshot s;full_pin_connection_snapshot(&s);return s;}
static void format_test(void){
    reset();seed();assert(!pin_control_bind_reserved(backing,sizeof backing,PIN_CONTROL_PHYSICAL));
    int rc=123;void *r=request(FULL_VEF_CP,64,1,2,3);
    assert(full_pin_connection_dispatch(FULL_VEF_CP,r,&io,2,&rc) && !rc && queued);
    struct pin_connection_snapshot s=snapshot();struct pin_control_snapshot pool;pin_control_snapshot(&pool);
    assert(!s.faults && s.format_mode && s.format_consumed && !s.format_pending && s.buffer_released && !s.virtual_vef_status);
    assert(s.format_current.pin_index==2 && s.format_current.ordinal==1 && s.format_current.code==1 &&
        !s.format_current.component && !s.format_current.encoded_flags && s.format_current.width==1920 && s.format_current.height==1080);
    assert(!pool.live && pool.releases==1 && pool.shares==1 && pool.consumer_opens==1 && pool.consumer_reads==1 && pool.creator_releases==1 && pool.consumer_releases==1);
    static const unsigned char expected[80]={
        0x53,0x53,0x59,0x4e,0,0,0,1,0,0,0,0,1,0,0,0,0x20,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0x45,0x54,0x52,0x59,0,0,0,0,0,0,0,0,0x40,0,0,0,0x10,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        1,0,0,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
    assert(!memcmp(backing,expected,sizeof expected));for(unsigned int i=80;i<sizeof backing;i++)assert(!backing[i]);
    assert(full_pin_connection_release(D,queued,release,record,&rc) && !rc);queued=0;
    r=request(FULL_PINMEM_CP,48,0,2,1);
    assert(!full_pin_connection_dispatch(FULL_PINMEM_CP,r,&io,2,&rc));
    assert(full_pinmem_dispatch(FULL_PINMEM_CP,r,&io,1,&rc) && !rc && queued && !blocked_events);
    assert(size(queued)==56 && u32((unsigned char *)queued+40)==1 && u32((unsigned char *)queued+44)==1 && u32((unsigned char *)queued+48)==FULL_PINMEM_CP);
    assert(full_pinmem_release_reply(D,queued,release,record,&rc) && !rc);queued=0;
    assert(!snapshot().blocked_requests);
    puts("PIN_FORMAT_REAL_80B_SHARE_NOTIFY_OPEN_DECODE_CACHE_LAST_RELEASE_AND_NEXT_GET_PASS");
}
int main(void){
    const char *format_fixture=getenv("PIN_CONNECTION_FORMAT_FIXTURE");
    if(format_fixture){
        host_fixture=format_fixture;puts("HOST_FIXTURE_ONLY_NO_VM");format_test();
        FILE *file=fopen(format_fixture,"wb");assert(file && fwrite(backing,1,sizeof backing,file)==sizeof backing && !fclose(file));reset();return 0;
    }
    host_fixture=getenv("PIN_CONNECTION_HOST_FIXTURE");if(host_fixture)puts("HOST_FIXTURE_ONLY_NO_VM");
    reset();seed();int rc=123;void *r=request(FULL_VEF_CP,64,1,2,3);
    assert(!full_pin_connection_dispatch(FULL_VEF_CP,r,&io,0,&rc));
    assert(full_pin_connection_dispatch(FULL_VEF_CP,r,&io,1,&rc) && rc && !snapshot().started);assert(!release(FULL_VEF_CP,r));
    assert(!pin_control_bind_reserved(backing,sizeof backing,PIN_CONTROL_PHYSICAL));
    r=request(FULL_VEF_CP,1,0,0,0);assert(full_pin_connection_dispatch(FULL_VEF_CP,r,&io,1,&rc) && rc);assert(!release(FULL_VEF_CP,r));
    r=request(FULL_VEF_CP,64,1,2,3);assert(full_pin_connection_dispatch(FULL_VEF_CP,r,&io,1,&rc) && !rc && queued);
    struct pin_connection_snapshot s=snapshot();assert(!s.faults && s.connections==1 && s.peer_requests_consumed==1 && s.peer_replies_consumed==1 && s.format_pending);
    assert(peer_request_events==1 && peer_reply_events==1 && dmm_request_events==1 && dmm_reply_events==1);
    struct full_vef_snapshot a,b;full_vef_snapshot(&a);full_pinmem_snapshot(&b);
    assert(a.pins[10].state==0 && a.pins[10].peer[3]==FULL_PINMEM_CP && b.pins[1].state==0 && b.pins[1].peer[3]==FULL_VEF_CP && !a.pending);
    assert(size(queued)==56 && source(queued)==FULL_VEF_CP && u16((unsigned char *)queued+26)==0x8001 && u32((unsigned char *)queued+44)==FULL_VEF_CP && !u32((unsigned char *)queued+48));
    static const unsigned char expected[32]={0x53,0x53,0x59,0x4e,0,0,0,1};assert(!memcmp(backing,expected,32));
    assert(s.buffer_physical==PIN_CONTROL_PHYSICAL && s.buffer_bytes==512);
    assert(full_pin_connection_release(D,queued,release,record,&rc) && !rc);queued=0;assert(snapshot().waiter_frees==1);
    r=request(FULL_PINMEM_CP,48,0,2,1);assert(full_pin_connection_dispatch(FULL_PINMEM_CP,r,&io,1,&rc) && !rc && !queued && blocked_events==1 && snapshot().blocked_requests==1);
    struct pin_control_snapshot pool;pin_control_snapshot(&pool);assert(pool.live==1 && !pool.releases);
    puts("PIN_CONNECTION_ACTUAL_64_64_72_56_CONSUMPTION_BUFFER_AND_FORMAT_BLOCK_PASS");
    if(host_fixture){
        FILE *file=fopen(host_fixture,"wb");assert(file && fwrite(backing,1,sizeof backing,file)==sizeof backing && !fclose(file));
        reset();return 0;
    }
    /* Explicit host VM teardown, not a fabricated production format/free. */
    reset();seed();assert(!pin_control_bind_reserved(backing,sizeof backing,PIN_CONTROL_PHYSICAL));
    r=request(FULL_VEF_CP,64,1,2,3);fail_allocation=allocation_count+1;
    assert(full_pin_connection_dispatch(FULL_VEF_CP,r,&io,1,&rc) && rc && snapshot().faults && !queued);assert(!release(FULL_VEF_CP,r));
    reset();seed();assert(!pin_control_bind_reserved(backing,sizeof backing,PIN_CONTROL_PHYSICAL));
    r=request(FULL_VEF_CP,64,1,2,3);alias=r;
    assert(full_pin_connection_dispatch(FULL_VEF_CP,r,&io,1,&rc) && rc && snapshot().faults && !queued);assert(!release(FULL_VEF_CP,r));
    reset();seed();assert(!pin_control_bind_reserved(backing,sizeof backing,PIN_CONTROL_PHYSICAL));
    r=request(FULL_VEF_CP,64,1,2,3);send_failure=1;
    assert(full_pin_connection_dispatch(FULL_VEF_CP,r,&io,1,&rc) && rc && snapshot().faults && !queued);assert(!release(FULL_VEF_CP,r));
    puts("PIN_CONNECTION_DISABLED_MALFORMED_ALLOCATION_ALIAS_SEND_FAILURE_PASS");
    for(unsigned int mode=0;mode<3;mode++){
        reset();seed();assert(!pin_control_bind_reserved(backing,sizeof backing,PIN_CONTROL_PHYSICAL));
        r=request(FULL_VEF_CP,64,1,2,3);
        if(mode==0)alias_peer_reply=1;else if(mode==1)bad_size=72;else fail_peer_free=1;
        assert(full_pin_connection_dispatch(FULL_VEF_CP,r,&io,1,&rc) && rc && snapshot().faults && !queued);
        assert(!release(FULL_VEF_CP,r));
    }
    puts("PIN_CONNECTION_LIVE_64_TO_72_ALIAS_SIZE_AND_INTERNAL_FREE_FAILURE_PASS");
    reset();seed();assert(!pin_control_bind_reserved(backing,sizeof backing,PIN_CONTROL_PHYSICAL));
    r=request(FULL_VEF_CP,64,1,2,3);fail_request_free=1;
    assert(full_pin_connection_dispatch(FULL_VEF_CP,r,&io,1,&rc) && !rc && snapshot().faults && queued);
    assert(full_pin_connection_release(D+1,queued,release,record,&rc) && rc);
    assert(full_pin_connection_release(D,queued,release,record,&rc) && !rc);queued=0;
    puts("PIN_CONNECTION_POST_SEND_REQUEST_FAILURE_AND_OWNED_REPLY_RELEASE_PASS");
    format_test();
    for(unsigned int injection=1;injection<=3;injection++){
        reset();seed();assert(!pin_control_bind_reserved(backing,sizeof backing,PIN_CONTROL_PHYSICAL));
        r=request(FULL_VEF_CP,64,1,2,3);format_injection=injection;
        assert(full_pin_connection_dispatch(FULL_VEF_CP,r,&io,2,&rc) && !rc && queued && snapshot().faults && !snapshot().format_consumed && !snapshot().buffer_released);
        pin_control_snapshot(&pool);assert(pool.live==1);
        assert(full_pin_connection_release(D,queued,release,record,&rc) && !rc);queued=0;
    }
    puts("PIN_FORMAT_BAD_BACKING_NOTIFY_UNIT_AND_LIVE_NOTIFY_DMM_ALIAS_REFUSED_PASS");
    reset();return 0;
}
