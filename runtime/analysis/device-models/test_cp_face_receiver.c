/* SPDX-License-Identifier: MIT */
#include "cp-background-device.c"
#include <stdlib.h>
#include <sys/wait.h>
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"%s:%d: %s\n",__FILE__,__LINE__,#x);exit(1); } } while(0)
static unsigned char message[20];
static unsigned int bytes=12,source=0x80020002u,free_count,free_fail,reenter;
static unsigned int size_of(void *p) { CHECK(p==message);return bytes; }
static unsigned int source_of(void *p) { CHECK(p==message);return source; }
static struct full_imaging_io io;
static int release(unsigned int id,void *p) {
    CHECK(id==NATIVE_CP_FACE_SID && p==message);free_count++;
    struct native_cp_background_face_snapshot s;CHECK(!native_cp_background_face_snapshot(&s));
    CHECK(s.request==(uintptr_t)p && s.generation);
    if(reenter) {
        reenter=0;int rc=123;
        CHECK(native_cp_background_dispatch(id,p,&io,1,&rc)==1 && rc==-1021);
        CHECK(native_cp_background_release(id,p,release,NULL,&rc)==1 && rc==-1021);
    }
    return free_fail?-37:0;
}
static void make(unsigned int recipient,unsigned int mask) {
    memset(message,0xa5,sizeof message);message[0]=2;message[1]=7;
    put32(message+4,recipient);message[8]=(unsigned char)mask;message[9]=(unsigned char)(mask>>8);
}
static int dispatch(unsigned int dst,const struct full_imaging_io *ops) {
    int rc=123;CHECK(native_cp_background_dispatch(dst,message,ops,1,&rc)==1);return rc;
}
static struct native_cp_background_face_snapshot snapshot(void) {
    struct native_cp_background_face_snapshot s;CHECK(!native_cp_background_face_snapshot(&s));return s;
}
static void verify(unsigned int generation,unsigned int retired,unsigned int recipient,unsigned int mask) {
    struct native_cp_background_face_snapshot s=snapshot();
    CHECK(s.generation==generation && s.retired==retired && s.enabled==1 && s.recipient==recipient && s.mask==mask);
    CHECK(!memcmp(s.wire,message,12));
    unsigned int count=0;
    for(unsigned int i=0;i<16;i++) {
        unsigned int known=i==4 || (i>=6 && i<12);CHECK(s.shared_known[i]==known);count+=known;
        if(!known)CHECK(s.shared_value[i]==0);
    }
    CHECK(count==7 && s.shared_value[4]==1 && s.shared_value[6]==(mask&255) && s.shared_value[7]==(mask>>8));
    CHECK(u32(s.shared_value+8)==recipient);
}
int main(int argc,char **argv) {
    CHECK(argc==2);io=(struct full_imaging_io){.release=release,.size=size_of,.source=source_of};
    if(!strcmp(argv[1],"sequence")) {
        for(unsigned int m=0;m<65536;m++) {
            unsigned int r=0x80020002u^m;make(r,m);CHECK(!dispatch(NATIVE_CP_FACE_SID,&io));verify(m+1,m+1,r,m);
        }
        CHECK(free_count==65536 && !snapshot().request);
        struct native_cp_background_config_snapshot c,z={0};CHECK(!native_cp_background_config_snapshot(&c) && !memcmp(&c,&z,sizeof c));
    } else if(!strcmp(argv[1],"wire")) {
        const unsigned char w[]={2,7,0,0,2,0,2,128,16,0,0,0};memcpy(message,w,12);
        CHECK(!dispatch(NATIVE_CP_FACE_SID,&io));verify(1,1,0x80020002,16);
    } else if(!strcmp(argv[1],"reject")) {
        make(7,16);struct native_cp_background_face_snapshot zero={0},actual;
        for(unsigned int k=0;k<8;k++) {
            struct full_imaging_io bad=io;int rc=123,h;
            bytes=k==0?8:k==1?16:12;source=k==2?1:0x80020002u;
            if(k==3)bad.release=NULL;
            if(k==4)bad.source=NULL;
            if(k==5)bad.size=NULL;
            message[0]=k==6?5:2;message[1]=k==7?8:7;
            h=native_cp_background_dispatch(NATIVE_CP_FACE_SID,message,&bad,1,&rc);
            if(k<5)CHECK(h && rc==-1020);else if(k==5)CHECK(h && rc==-1021);else CHECK(!h && rc==123);
            actual=snapshot();CHECK(!memcmp(&actual,&zero,sizeof actual));
        }
        CHECK(!free_count);int rc=123;make(7,16);
        CHECK(!native_cp_background_dispatch(0,message,&io,1,&rc) && rc==123);
        CHECK(!native_cp_background_dispatch(NATIVE_CP_FACE_SID,message,&io,0,&rc) && rc==123);
        CHECK(!native_cp_background_dispatch(NATIVE_CP_FACE_SID,message,&io,1,NULL));
    } else if(!strcmp(argv[1],"reentrant")) {
        make(7,16);reenter=1;CHECK(!dispatch(NATIVE_CP_FACE_SID,&io));verify(1,1,7,16);CHECK(free_count==1);
    } else if(!strcmp(argv[1],"free-failure")) {
        make(7,16);free_fail=1;CHECK(!dispatch(NATIVE_CP_FACE_SID,&io));verify(1,0,7,16);
        CHECK(snapshot().request==(uintptr_t)message && atomic_load(&faults));
        CHECK(dispatch(NATIVE_CP_FACE_SID,&io)==-1021 && free_count==1);
        int rc=123;CHECK(native_cp_background_release(NATIVE_CP_BACKGROUND_SID,message,release,NULL,&rc)==1 && rc==-1021);
        free_fail=0;CHECK(native_cp_background_release(NATIVE_CP_FACE_SID,message,release,NULL,&rc)==1 && !rc);
        CHECK(!snapshot().request && snapshot().retired==1 && free_count==2);
        CHECK(dispatch(NATIVE_CP_FACE_SID,&io)==-1021);
    } else if(!strcmp(argv[1],"overflow")) {
        CHECK(claim_owner());face.generation=UINT32_MAX;make(7,16);CHECK(dispatch(NATIVE_CP_FACE_SID,&io)==-1021 && !free_count);
    } else if(!strcmp(argv[1],"fork")) {
        make(7,16);CHECK(!dispatch(NATIVE_CP_FACE_SID,&io));
        pthread_mutex_lock(&state_mutex);pid_t child=fork();CHECK(child>=0);
        if(!child) {
            alarm(3);struct native_cp_background_face_snapshot s,b;memset(&s,0xa5,sizeof s);b=s;
            CHECK(native_cp_background_face_snapshot(&s)==-1021 && !memcmp(&s,&b,sizeof s));
            CHECK(dispatch(NATIVE_CP_FACE_SID,&io)==-1021);_exit(0);
        }
        pthread_mutex_unlock(&state_mutex);int status;CHECK(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
        CHECK(native_cp_background_face_snapshot(NULL)==-1024);
    } else CHECK(0);
    return 0;
}
