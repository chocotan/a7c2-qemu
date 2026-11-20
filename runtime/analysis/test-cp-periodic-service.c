/* SPDX-License-Identifier: MIT */
#include "cp-periodic-service.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
struct packet {unsigned int bytes;int alive;unsigned char data[8];};
static int release_result;
static unsigned long long release_calls;
static unsigned int packet_size(void *p){return ((struct packet *)p)->bytes;}
static int release_packet(unsigned int destination,void *p){
    if(destination!=NATIVE_CP_PERIODIC_START && destination!=NATIVE_CP_PERIODIC_STOP)return -90;
    struct packet *packet=p;
    if(!packet->alive)return -91;
    release_calls++;
    if(!release_result)packet->alive=0;
    return release_result;
}
static void check(int ok,const char *why){if(!ok){fprintf(stderr,"FAIL %s\n",why);exit(1);}}
static struct packet packet(unsigned int bytes,unsigned first,unsigned second){
    struct packet p={.bytes=bytes,.alive=1};
    p.data[0]=first;p.data[1]=first>>8;p.data[2]=second;p.data[3]=second>>8;return p;
}
/* The native IO points at the payload, so bridge mock metadata via container. */
static unsigned int size(void *p){return packet_size((unsigned char *)p-__builtin_offsetof(struct packet,data));}
static int release(unsigned int d,void *p){return release_packet(d,(unsigned char *)p-__builtin_offsetof(struct packet,data));}
static const struct full_imaging_io io={.release=release,.size=size};
static void replay(unsigned first,unsigned second,unsigned period,unsigned count,unsigned phase){
    struct packet p=packet(4,first,second);int rc=123;
    check(native_cp_periodic_dispatch(NATIVE_CP_PERIODIC_START,p.data,&io,1,&rc)==1 && rc==0 && !p.alive,"start consumed");
    struct native_cp_periodic_state s;native_cp_periodic_snapshot(&s);
    check(s.period==period && s.count==count && s.phase==phase && s.requested_active,"CP register decoding");
}
static void *worker(void *unused){
    (void)unused;
    for(unsigned i=0;i<4096;i++){
        struct packet p=packet(4,0x8064,5);int rc=123;
        check(native_cp_periodic_dispatch(NATIVE_CP_PERIODIC_START,p.data,&io,1,&rc)==1 && !rc && !p.alive,"concurrent release");
    }return NULL;
}
int main(void){
    struct packet p=packet(4,0x8064,5);int rc=123;
    check(!native_cp_periodic_dispatch(NATIVE_CP_PERIODIC_START,p.data,&io,0,&rc) && rc==123 && p.alive,"disabled untouched");
    check(!native_cp_periodic_dispatch(0x91170318,p.data,&io,1,&rc) && rc==123 && p.alive,"other SID untouched");
    check(!native_cp_periodic_dispatch(NATIVE_CP_PERIODIC_START,p.data,&io,1,NULL) && p.alive,"missing return slot");
    struct full_imaging_io missing=io;missing.release=NULL;
    check(native_cp_periodic_dispatch(NATIVE_CP_PERIODIC_START,p.data,&missing,1,&rc) && rc==-1021 && p.alive,"missing callback");
    check(native_cp_periodic_dispatch(NATIVE_CP_PERIODIC_START,NULL,&io,1,&rc) && rc==-1021,"null payload");
    for(unsigned n=0;n<=8;n++)if(n!=4){p=packet(n,0x8064,5);check(native_cp_periodic_dispatch(NATIVE_CP_PERIODIC_START,p.data,&io,1,&rc) && rc==-1021 && p.alive,"start malformed size");}
    p=packet(4,0x8064,5);
    struct native_cp_periodic_state before,after;native_cp_periodic_snapshot(&before);
    release_result=-55;
    check(native_cp_periodic_dispatch(NATIVE_CP_PERIODIC_START,p.data,&io,1,&rc) && rc==-55 && p.alive,"failed release retains caller");
    native_cp_periodic_snapshot(&after);check(!memcmp(&before,&after,sizeof before),"failed release no commit");release_result=0;
    replay(0x8064,5,100,5,0);
    replay(0x8064,0x0105,100,5,1);
    replay(100,500,100,5,255);
    replay(100,5,100,0,255);
    replay(0,0,100,5,0);
    replay(0,5,100,0,255);
    replay(0x8000,0x0105,100,5,1);
    replay(0xffff,0xffff,32767,255,255);
    replay(1,0xffff,1,65535,255);
    p=packet(4,0,0);check(native_cp_periodic_dispatch(NATIVE_CP_PERIODIC_STOP,p.data,&io,1,&rc) && rc==-1021 && p.alive,"stop malformed size");
    p=packet(0,0,0);check(native_cp_periodic_dispatch(NATIVE_CP_PERIODIC_STOP,p.data,&io,1,&rc) && !rc && !p.alive,"stop zero bytes released");
    native_cp_periodic_snapshot(&after);check(!after.requested_active && after.stops==1 && after.released==10,"stop state");
    pthread_t workers[2];
    for(unsigned i=0;i<2;i++)check(!pthread_create(&workers[i],NULL,worker,NULL),"thread start");
    for(unsigned i=0;i<2;i++)check(!pthread_join(workers[i],NULL),"thread join");
    native_cp_periodic_snapshot(&after);
    check(after.starts==8201 && after.stops==1 && after.released==8202 && release_calls==8203,"exactly one retirement per request");
    puts("PASS cp-periodic: 9 decode cases, 8 invalid sizes, ownership/failure/disabled/stop, 8192 concurrent requests; no timers/samples claimed");return 0;
}
