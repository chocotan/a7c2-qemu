#define _GNU_SOURCE
#include "cp-background-device.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1); } } while(0)
struct message { unsigned bytes,source; unsigned char wire[24]; };
static _Atomic unsigned active,released,records;
static int fail_free,reenter;
static void *make(unsigned value) {
    struct message *m=calloc(1,sizeof *m);CHECK(m);
    m->bytes=12;m->source=0x80020002u;
    memset(m->wire,0xa5,24);m->wire[0]=5;m->wire[2]=0xb8;m->wire[3]=0x40;m->wire[8]=(unsigned char)value;
    atomic_fetch_add(&active,1);return m->wire;
}
static struct message *meta(void *p) { return (struct message *)((unsigned char *)p-8); }
static unsigned size(void *p) { return meta(p)->bytes; }
static unsigned source(void *p) { return meta(p)->source; }
static int release(unsigned,void *);
static void record(const char *tag,const char *line) {
    CHECK(tag && line);
    if(!strcmp(tag,"NATIVE_CP_BACKGROUND_PARAMETER_ACCEPT ")) {
        CHECK(strstr(line,"apply_pending=1 apply_completed=0") && strstr(line,"completion=0 original_CP=0"));
        atomic_fetch_add(&records,1);
    }
}
static const struct full_imaging_io io={.release=release,.size=size,.source=source,.record=record};
static int release(unsigned id,void *p) {
    CHECK(id==NATIVE_CP_BACKGROUND_SID && p);
    if(fail_free)return -17;
    if(reenter) {
        reenter=0;void *next=make(99);int rc=123;
        CHECK(native_cp_background_dispatch(id,next,&io,1,&rc)==1 && rc==-1021);
        CHECK(!release(id,next));
        struct native_cp_background_parameter_snapshot s;
        CHECK(!native_cp_background_parameter_snapshot(&s) && s.apply_pending && s.parameter170==7);
    }
    atomic_fetch_add(&released,1);atomic_fetch_sub(&active,1);free(meta(p));return 0;
}
static int dispatch(void *p) {
    int rc=123;CHECK(native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,1,&rc)==1);return rc;
}
static void check_value(unsigned value,unsigned generation) {
    struct native_cp_background_parameter_snapshot s;
    CHECK(!native_cp_background_parameter_snapshot(&s));
    CHECK(s.parameter170==value && s.parameter_valid && s.apply_pending && s.generation==generation);
    CHECK(s.wire[8]==value && s.wire[1]==0xa5 && s.wire[9]==0xa5 && s.wire[11]==0xa5);
}
static void *produce(void *unused) {
    unsigned value=(unsigned)(uintptr_t)unused;
    for(unsigned i=0;i<500;i++) {
        void *p=make(value);int rc=dispatch(p);
        if(rc==-1021) CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));
        else CHECK(rc==0);
    }
    return NULL;
}
int main(int argc,char **argv) {
    CHECK(argc==2);
    if(!strcmp(argv[1],"values")) {
        struct native_cp_background_parameter_snapshot s;
        CHECK(!native_cp_background_parameter_snapshot(&s) && !s.parameter_valid && !s.apply_pending && !s.generation);
        CHECK(native_cp_background_parameter_snapshot(NULL)==-1024);
        for(unsigned v=0;v<256;v++) { CHECK(!dispatch(make(v)));check_value(v,v+1); }
        CHECK(records==256 && released==256 && active==0);
    } else if(!strcmp(argv[1],"reject")) {
        for(unsigned n=0;n<8;n++) {
            unsigned char *p=make(7);
            switch(n) {
            case 0:meta(p)->bytes=8;break;
            case 1:meta(p)->bytes=24;break;
            case 2:meta(p)->source=0x810261c7;break;
            case 3:meta(p)->source=NATIVE_CP_BACKGROUND_SID;break;
            case 4:meta(p)->source=0;break;
            case 5:p[0]=1;break;
            case 6:p[2]=0xb9;break;
            default:p[2]=0xba;break;
            }
            int rc=123,handled=native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,1,&rc);
            if(n<5) CHECK(handled && rc==-1020);
            else CHECK(!handled && rc==123); /* original transport remains responsible and refuses unknown. */
            CHECK(active==1 && !records);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));
        }
        struct native_cp_background_parameter_snapshot s;
        CHECK(!native_cp_background_parameter_snapshot(&s) && !s.generation && !s.parameter_valid && !s.apply_pending);
        void *p=make(7);int rc=123;
        CHECK(!native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,0,&rc) && rc==123);
        CHECK(!native_cp_background_dispatch(1,p,&io,1,&rc) && rc==123);
        CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));
    } else if(!strcmp(argv[1],"free-failure")) {
        void *p=make(7);fail_free=1;CHECK(!dispatch(p));check_value(7,1);
        CHECK(active==1 && !released && records==1);
        void *next=make(8);CHECK(dispatch(next)==-1021);fail_free=0;CHECK(!release(NATIVE_CP_BACKGROUND_SID,next));
        int rc=123;CHECK(native_cp_background_release(NATIVE_CP_BACKGROUND_SID,p,release,record,&rc)==1 && !rc);
        CHECK(!active && released==2);check_value(7,1);
        next=make(8);CHECK(dispatch(next)==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,next));
    } else if(!strcmp(argv[1],"reentrant")) {
        reenter=1;CHECK(!dispatch(make(7)));check_value(7,1);CHECK(released==2 && !active && records==1);
    } else if(!strcmp(argv[1],"concurrent")) {
        pthread_t threads[4];
        for(unsigned i=0;i<4;i++)CHECK(!pthread_create(&threads[i],NULL,produce,(void *)(uintptr_t)i));
        for(unsigned i=0;i<4;i++)CHECK(!pthread_join(threads[i],NULL));
        struct native_cp_background_parameter_snapshot s;
        CHECK(!native_cp_background_parameter_snapshot(&s) && s.generation==records && s.parameter_valid && s.apply_pending);
        CHECK(records>0 && released==2000 && !active);
    } else if(!strcmp(argv[1],"fork")) {
        CHECK(!dispatch(make(7)));pid_t child=fork();CHECK(child>=0);
        if(!child) {
            alarm(3);struct native_cp_background_parameter_snapshot s,before;
            memset(&s,0x5a,sizeof s);before=s;
            CHECK(native_cp_background_parameter_snapshot(&s)==-1021 && !memcmp(&s,&before,sizeof s));
            void *p=make(8);CHECK(dispatch(p)==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));_exit(0);
        }
        int status;CHECK(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));check_value(7,1);
    } else CHECK(0);
    CHECK(!active);
    printf("{\"case\":\"%s\",\"released\":%u,\"accepted\":%u,\"active\":%u,\"apply_completed\":false}\n",argv[1],(unsigned)released,(unsigned)records,(unsigned)active);
    return 0;
}
