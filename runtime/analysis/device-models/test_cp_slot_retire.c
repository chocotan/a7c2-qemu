#define _GNU_SOURCE
#ifdef SLOT_RETIRE_EMBEDDED
#include "cp-background-device.c"
#else
#include "cp-background-device.h"
#endif
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1); } } while (0)
struct contract { unsigned dst,op,n; };
static const struct contract contracts[]={
    {NATIVE_CP_BACKGROUND_SID,0x4023,12},{NATIVE_CP_BACKGROUND_SID,0x4077,12},
    {NATIVE_CP_CAPTURE_SID,0x4039,16},{NATIVE_CP_CAPTURE_SID,0x40a5,12},
    {NATIVE_CP_BACKGROUND_SID,0x404e,8},{NATIVE_CP_BACKGROUND_SID,0x4070,12},
    {NATIVE_CP_CAPTURE_SID,0x406a,12},{NATIVE_CP_CAPTURE_SID,0x4036,16},
    {NATIVE_CP_CAPTURE_SID,0x40de,12},{NATIVE_CP_BACKGROUND_SID,0x301a,12}
};
#define CONTRACT_COUNT (sizeof contracts/sizeof contracts[0])
struct message { unsigned n,source;unsigned char wire[64]; };
static _Atomic unsigned active,frees,sends,allocations,logs,accepted;
static unsigned current;static int free_failure,release_probe,record_probe,pending_probe;
static void *recycled;
static struct message *header(void *p) { return (void *)((unsigned char *)p-8); }
static unsigned size(void *p) { return header(p)->n; }
static unsigned source(void *p) { return header(p)->source; }
static void *make(unsigned index,unsigned token) {
    const struct contract *c=&contracts[index];struct message *m=calloc(1,sizeof *m);CHECK(m);
    m->n=c->n;m->source=0x80020002;m->wire[0]=5;m->wire[2]=(unsigned char)c->op;m->wire[3]=(unsigned char)(c->op>>8);
    for(unsigned i=0;i<4;i++)m->wire[4+i]=(unsigned char)(token>>(8*i));
    m->wire[8]=0x80;m->wire[9]=7;m->wire[10]=0xff;m->wire[11]=0x80;m->wire[12]=0x34;m->wire[13]=0x12;
    if(index==8)m->wire[8]=2;
    if(index==9)m->wire[0]=0;
    atomic_fetch_add(&active,1);return m->wire;
}
static int release(unsigned,void *);
static void record(const char *,const char *);
static int allocate(unsigned a,void **b,unsigned c,unsigned d) { (void)a;(void)b;(void)c;(void)d;atomic_fetch_add(&allocations,1);return -17; }
static int send(unsigned a,void *b) { (void)a;(void)b;atomic_fetch_add(&sends,1);return -17; }
static const struct full_imaging_io io={.size=size,.source=source,.release=release,.record=record,.allocate=allocate,.send=send};
static int dispatch(unsigned k,void *p,const struct full_imaging_io *ops) {
    int rc=123;CHECK(native_cp_background_dispatch(contracts[k].dst,p,ops,1,&rc)==1);return rc;
}
static struct native_cp_background_remainder_snapshot snapshot(unsigned k) {
    struct native_cp_background_remainder_snapshot s;CHECK(!native_cp_background_remainder_snapshot(contracts[k].dst,contracts[k].op,&s));return s;
}
static void alias_probe(void *p) {
    unsigned char saved[64];memcpy(saved,p,64);unsigned original=size(p);
    for(unsigned k=0;k<CONTRACT_COUNT;k++) {
        ((unsigned char *)p)[0]=contracts[k].op==0x301a?0:5;
        ((unsigned char *)p)[2]=(unsigned char)contracts[k].op;((unsigned char *)p)[3]=(unsigned char)(contracts[k].op>>8);header(p)->n=contracts[k].n;
        CHECK(dispatch(k,p,&io)==-1021);
    }
    memcpy(p,saved,64);header(p)->n=original;
}
static int release(unsigned id,void *p) {
    CHECK(p && (id==NATIVE_CP_BACKGROUND_SID || id==NATIVE_CP_CAPTURE_SID));
    if(release_probe) {
        release_probe=0;struct native_cp_background_remainder_snapshot s=snapshot(current);
        CHECK(s.pending && s.request==(uintptr_t)p && !s.retired);
        for(unsigned j=0;j<3;j++) { int rc=123;unsigned owner=j==0?id:j==1?0:0x80020002;
            CHECK(native_cp_background_release(owner,p,release,record,&rc)==1 && rc==-1021); }
        alias_probe(p);void *q=make(current,2);CHECK(dispatch(current,q,&io)==-1021);CHECK(!release(id,q));
    }
    if(free_failure)return -17;
    atomic_fetch_sub(&active,1);atomic_fetch_add(&frees,1);if(p!=recycled)free(header(p));return 0;
}
static void record(const char *tag,const char *text) {
    if(!strcmp(tag,"NATIVE_CP_BACKGROUND_ASYNC_PENDING ") || !strcmp(tag,"NATIVE_CP_BACKGROUND_4070_PENDING ")) {
        CHECK(strstr(text,"internal0901_delivered=0") && strstr(text,"internal1010_delivered=0") && strstr(text,"bracketing_updated=0"));
        if(pending_probe) { pending_probe=0;struct native_cp_background_remainder_snapshot s=snapshot(current);
            CHECK(s.pending && s.request);alias_probe((void *)s.request); }
    }
    if(!strcmp(tag,"NATIVE_CP_BACKGROUND_STILL_LOCK_PENDING ")) {
        CHECK(strstr(text,"receiver_recorded=1 kind_state_updated=0") && strstr(text,"lock_start_notified=0 lock_complete_notified=0"));
        CHECK(strstr(text,"handler_executed=0 completion=0 original_CP=0 capture_verified=0"));
    }
    if(!strcmp(tag,"NATIVE_CP_BACKGROUND_RELEASE_KEY_PENDING ")) {
        CHECK(strstr(text,"receiver_recorded=1 key_state_updated=0") && strstr(text,"internal4036_delivered=0 internal4038_delivered=0"));
        CHECK(strstr(text,"handler_executed=0 completion=0 original_CP=0 capture_verified=0"));
    }
    if(!strcmp(tag,"NATIVE_CP_BACKGROUND_PREVIEW_PENDING ")) {
        CHECK(strstr(text,"receiver_recorded=1 internal8102_delivered=0 preview_mode_applied=0 ap_reply=none"));
        CHECK(strstr(text,"internal_event=0x8102") && strstr(text,"handler_executed=0 completion=0 original_CP=0 capture_verified=0"));
    }
    if(strcmp(tag,"NATIVE_CP_BACKGROUND_SLOT_RETIRE "))return;
    CHECK(strstr(text,"handler_executed=0") && strstr(text,"apply_completed=0 completion=0") && strstr(text,"original_CP=0 capture_verified=0"));
    atomic_fetch_add(&logs,1);
    if(record_probe) { record_probe=0;CHECK(snapshot(current).retired==1);CHECK(!dispatch(current,make(current,2),&io)); }
}
static void unchanged(void) {
    struct native_cp_background_config_snapshot s,zero={0};CHECK(!native_cp_background_config_snapshot(&s));CHECK(!memcmp(&s,&zero,sizeof s));
}
static void verify(unsigned k,unsigned n) {
    struct native_cp_background_remainder_snapshot s=snapshot(k);
    CHECK(s.generation==n && s.retired==n && s.deferred_count==n && !s.pending && !s.request);
    CHECK(s.opcode==contracts[k].op && s.bytes==contracts[k].n && s.source==0x80020002 && s.destination==contracts[k].dst);
    CHECK(!sends && !allocations);
    if(k==4) { struct native_cp_background_async_snapshot a;CHECK(!native_cp_background_async_snapshot(&a));
        CHECK(a.generation==n && a.retired==n && a.deferred_count==n && !a.pending && !a.request);
        CHECK(!memcmp(a.wire,s.wire,8) && !memcmp(a.first_wire,s.first_wire,8)); }
    if(k==5) { struct native_cp_background_4070_snapshot w;CHECK(!native_cp_background_4070_snapshot(&w));
        CHECK(w.generation==n && w.retired==n && w.deferred_count==n && !w.pending && !w.request);
        CHECK(!memcmp(w.wire,s.wire,12) && !memcmp(w.first_wire,s.first_wire,12)); }
    unchanged();
}
static void *produce(void *unused) {
    (void)unused;for(unsigned i=0;i<100;i++) { void *p=make(current,i);int rc=dispatch(current,p,&io);CHECK(!rc || rc==-1021);
        if(rc)CHECK(!release(contracts[current].dst,p));else atomic_fetch_add(&accepted,1); }return NULL;
}
int main(int argc,char **argv) {
    CHECK(argc>=2 && argc<=3);
#ifdef SLOT_INDEX
    current=SLOT_INDEX;
#else
    current=argc==3?(unsigned)strtoul(argv[2],NULL,0):2;
#endif
    CHECK(current<CONTRACT_COUNT && current!=0);alarm(25);const struct contract *c=&contracts[current];const char *test=argv[1];
    if(!strcmp(test,"normal") || !strcmp(test,"sequence") || !strcmp(test,"reuse") || !strcmp(test,"minimal") || !strcmp(test,"minimal-transport") || !strcmp(test,"deferred")) {
        unsigned n=!strcmp(test,"reuse")?10000:3;struct full_imaging_io minimal={.size=size,.source=source,.release=release};
        for(unsigned i=0;i<n;i++)CHECK(!dispatch(current,make(current,i+1),strstr(test,"minimal")?&minimal:&io));
        verify(current,n);struct native_cp_background_remainder_snapshot s=snapshot(current);
        CHECK(s.first_wire[4]==1 && s.wire[4]==(unsigned char)n);for(unsigned i=c->n;i<32;i++)CHECK(!s.wire[i] && !s.first_wire[i]);
    } else if(!strcmp(test,"preview-wire")) {
        CHECK(current==9 && c->dst==NATIVE_CP_BACKGROUND_SID);
        const unsigned char wire[12]={0,0,0x1a,0x30,0x67,0,0,0x80,0,0,0,0};
        for(unsigned value=0;value<256;value++) {
            unsigned char *p=make(current,0);memcpy(p,wire,12);p[8]=(unsigned char)value;
            p[1]=(unsigned char)(255-value);p[9]=0xfa;p[10]=0xfb;p[11]=0xfc;
            CHECK(!dispatch(current,p,&io));struct native_cp_background_remainder_snapshot s=snapshot(current);
            CHECK(s.mode==value && s.wire[8]==value && s.wire[1]==255-value);
        }
        verify(current,256);struct native_cp_background_remainder_snapshot s=snapshot(current);
        CHECK(!memcmp(s.first_wire+2,wire+2,6) && s.first_wire[8]==0 && s.wire[8]==255);
    } else if(!strcmp(test,"key-clear-wire")) {
        CHECK(current==6 && contracts[current].dst==0x90040193u);
        const unsigned char wire[12]={5,0,0x6a,0x40,0x26,0,0,0x80,0,0,0,0};
        for(unsigned n=0;n<2;n++) { void *p=make(current,0);memcpy(p,wire,12);CHECK(!dispatch(current,p,&io)); }
        verify(current,2);struct native_cp_background_remainder_snapshot s=snapshot(current);
        CHECK(!memcmp(s.first_wire,wire,12) && !memcmp(s.wire,wire,12));
    } else if(!strcmp(test,"release-key-wire")) {
        CHECK(current==8 && contracts[current].dst==0x90040193u);
        const unsigned char wire[12]={5,0,0xde,0x40,0x6c,0,0,0x80,2,0,0,0};
        for(unsigned n=0;n<2;n++) { void *p=make(current,0);memcpy(p,wire,12);CHECK(!dispatch(current,p,&io)); }
        verify(current,2);struct native_cp_background_remainder_snapshot s=snapshot(current);
        CHECK(!memcmp(s.first_wire,wire,12) && !memcmp(s.wire,wire,12));
        for(unsigned key=6;key<256;key++) { unsigned char *p=make(current,0);p[8]=(unsigned char)key;CHECK(dispatch(current,p,&io)==-1021);CHECK(!release(c->dst,p)); }
        verify(current,2);
    } else if(!strcmp(test,"still-lock-wire")) {
        CHECK(current==7 && contracts[current].dst==0x90040193u);
        const unsigned char wire[16]={5,0,0x36,0x40,0x42,0,0,0x80,4,0,0,0,0xff,0xff,0xff,0xff};
        for(unsigned n=0;n<2;n++) { void *p=make(current,0);memcpy(p,wire,16);CHECK(!dispatch(current,p,&io)); }
        verify(current,2);struct native_cp_background_remainder_snapshot s=snapshot(current);
        CHECK(!memcmp(s.first_wire,wire,16) && !memcmp(s.wire,wire,16));
    } else if(!strcmp(test,"reuse-address")) {
        void *p=make(current,17);recycled=p;
        for(unsigned i=0;i<1000;i++) { if(i)atomic_fetch_add(&active,1);CHECK(!dispatch(current,p,&io)); }
        verify(current,1000);recycled=NULL;free(header(p));
    } else if(!strcmp(test,"same-value")) {
        for(unsigned i=0;i<1000;i++)CHECK(!dispatch(current,make(current,17),&io));
        verify(current,1000);
        struct native_cp_background_remainder_snapshot s=snapshot(current);CHECK(!memcmp(s.first_wire,s.wire,c->n));
    } else if(!strcmp(test,"reentrant") || !strcmp(test,"busy") || !strcmp(test,"protected-free") || !strcmp(test,"alias") || !strcmp(test,"reverse-alias") || !strcmp(test,"alias-reverse") || !strcmp(test,"sending")) {
        release_probe=1;pending_probe=1;record_probe=!strcmp(test,"reentrant");
        CHECK(!dispatch(current,make(current,1),&io));verify(current,!strcmp(test,"reentrant")?2:1);
    } else if(!strcmp(test,"reject")) {
        for(unsigned n=0;n<=40;n++)if(n!=c->n) {
            void *p=make(current,1);header(p)->n=n;int rc=123,h=native_cp_background_dispatch(c->dst,p,&io,1,&rc);
            CHECK(n<4?(!h && rc==123):(h && rc==-1020));CHECK(!release(c->dst,p)); }
        for(unsigned k=0;k<12;k++) {
            unsigned char *p=make(current,1);struct full_imaging_io bad=io;int rc=123;unsigned dst=c->dst;
            switch(k) {
            case 0:header(p)->source=0;break;case 1:header(p)->source=c->dst;break;case 2:bad.source=NULL;break;
            case 3:bad.release=NULL;break;case 4:bad.size=NULL;break;case 5:p[0]=current==9?5:0;break;case 6:p[0]=13;break;
            case 7:dst=c->dst==NATIVE_CP_CAPTURE_SID?NATIVE_CP_BACKGROUND_SID:NATIVE_CP_CAPTURE_SID;break;default:break; }
            int h=native_cp_background_dispatch(dst,p,&bad,k!=8,k==9?NULL:&rc);
            if(k<4)CHECK(h && rc==-1020);else if(k==4 && c->dst==NATIVE_CP_BACKGROUND_SID)CHECK(h && rc==-1021);
            else if(k>=10)CHECK(h && !rc);else CHECK(!h && rc==123);
            if(k<10)CHECK(!release(c->dst,p));
        }
        verify(current,2);
    } else if(!strcmp(test,"fault") || !strcmp(test,"free-failure")) {
        void *p=make(current,1);free_failure=1;CHECK(!dispatch(current,p,&io));free_failure=0;
        struct native_cp_background_remainder_snapshot s=snapshot(current);CHECK(s.pending && s.request==(uintptr_t)p && s.generation==1 && !s.retired && s.deferred_count==1);
        void *q=make(current,2);CHECK(dispatch(current,q,&io)==-1021);CHECK(!release(c->dst,q));int rc=123;
        CHECK(native_cp_background_release(0,p,release,record,&rc)==1 && rc==-1021);
        release_probe=1;
        CHECK(native_cp_background_release(c->dst,p,release,record,&rc)==1 && !rc);verify(current,1);
        q=make(current,2);CHECK(dispatch(current,q,&io)==-1021);CHECK(!release(c->dst,q));
    } else if(!strcmp(test,"fork")) {
        CHECK(!dispatch(current,make(current,1),&io));pid_t child=fork();CHECK(child>=0);
        if(!child) { alarm(3);struct native_cp_background_remainder_snapshot s,b;memset(&s,0xa5,sizeof s);b=s;
            CHECK(native_cp_background_remainder_snapshot(c->dst,c->op,&s)==-1021 && !memcmp(&s,&b,sizeof s));
            void *p=make(current,2);CHECK(dispatch(current,p,&io)==-1021);CHECK(!release(c->dst,p));_exit(0); }
        int status;CHECK(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));verify(current,1);
    } else if(!strcmp(test,"concurrent")) {
        pthread_t threads[8];for(unsigned i=0;i<8;i++)CHECK(!pthread_create(&threads[i],NULL,produce,NULL));
        for(unsigned i=0;i<8;i++)CHECK(!pthread_join(threads[i],NULL));
        CHECK(accepted>0 && accepted<=800);verify(current,accepted);CHECK(frees==800);
    } else if(!strcmp(test,"all-slots") || !strcmp(test,"two-slots") || !strcmp(test,"reverse-slots")) {
        for(unsigned i=0;i<CONTRACT_COUNT;i++)if(i!=0)for(unsigned j=0;j<4;j++)CHECK(!dispatch(i,make(i,j+1),&io));
        for(unsigned i=0;i<CONTRACT_COUNT;i++)if(i!=0)verify(i,4);
    } else if(!strcmp(test,"capture-census")) {
        for(unsigned op=0;op<65536;op++) { unsigned k=op==0x40de?8:op==0x4036?7:op==0x4039?2:3;void *p=make(k,1);
            ((unsigned char *)p)[2]=(unsigned char)op;((unsigned char *)p)[3]=(unsigned char)(op>>8);int rc=123;
            int h=native_cp_background_dispatch(NATIVE_CP_CAPTURE_SID,p,&io,1,&rc);
            if(op==0x4036 || op==0x4039 || op==0x40a5 || op==0x406a || op==0x40de)CHECK(h && !rc);else {CHECK(!h && rc==123);CHECK(!release(NATIVE_CP_CAPTURE_SID,p));} }
        verify(2,1);verify(3,1);verify(6,1);verify(7,1);verify(8,1);
    } else if(!strcmp(test,"snapshot-errors")) {
        struct native_cp_background_remainder_snapshot s,b;memset(&s,0xa5,sizeof s);b=s;
        CHECK(native_cp_background_remainder_snapshot(c->dst,c->op,NULL)==-1024);
        CHECK(native_cp_background_remainder_snapshot(1,c->op,&s)==-1024 && !memcmp(&s,&b,sizeof s));
        CHECK(native_cp_background_remainder_snapshot(c->dst,0xffff,&s)==-1024 && !memcmp(&s,&b,sizeof s));
        CHECK(native_cp_background_async_snapshot(NULL)==-1024 && native_cp_background_4070_snapshot(NULL)==-1024);
#ifdef SLOT_RETIRE_EMBEDDED
    } else if(!strcmp(test,"overflow")) {
        remainder_pending[current].generation=UINT32_MAX;void *p=make(current,1);
        CHECK(dispatch(current,p,&io)==-1021);CHECK(!release(c->dst,p));CHECK(!snapshot(current).retired);
#endif
    } else CHECK(0);
    CHECK(!active && !sends && !allocations);
    printf("{\"case\":\"%s\",\"opcode\":%u,\"frees\":%u,\"logs\":%u,\"completion\":false}\n",test,c->op,(unsigned)frees,(unsigned)logs);return 0;
}
