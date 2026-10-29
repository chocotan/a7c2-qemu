/* SPDX-License-Identifier: MIT */
#include "cp-background-device.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#define SOURCE 0x810261c7u
struct message { unsigned int owner,source,bytes,live; unsigned char body[64]; };
static struct message messages[80];
static unsigned int allocations,releases,sends,accepts,unhandled,free_observations;
static int observer_bound;
static int fail_allocate,fail_send,fast_free,reuse_address;
static void *fail_free;
static void *last_reply;
static unsigned char captured[12];
static unsigned int captured_source;
static _Atomic int initialization_window;
static int window_ready[2],window_release[2];
int __real_pthread_mutex_lock(pthread_mutex_t *);
int __wrap_pthread_mutex_lock(pthread_mutex_t *mutex) {
    int rc=__real_pthread_mutex_lock(mutex);
    if (!rc && atomic_exchange(&initialization_window,0)) {
        char byte='x';assert(write(window_ready[1],&byte,1)==1);
        assert(read(window_release[0],&byte,1)==1);
    }
    return rc;
}
static void *initialize_thread(void *unused) {
    (void)unused;return native_cp_background_resources();
}

static struct message *lookup(void *p) {
    for (unsigned int i=0;i<80;i++) if (messages[i].body==p) return &messages[i];
    abort();
}
static void *make(unsigned int owner,unsigned int size,unsigned int source) {
    for (unsigned int i=0;i<80;i++) if (!messages[i].live) {
        struct message *m=&messages[i];memset(m,0,sizeof *m);
        m->owner=owner;m->bytes=size;m->source=source;m->live=1;return m->body;
    }
    abort();
}
static int allocate(unsigned int owner,void **p,unsigned int size,unsigned int count) {
    assert(owner==SOURCE && size==12 && count==1);allocations++;
    if (fail_allocate) return -12;
    *p=make(owner,size,0);return 0;
}
static int release(unsigned int owner,void *p) {
    struct message *m=lookup(p);assert(m->live && m->owner==owner);
    if (p==fail_free) return -9;
    releases++;m->live=0;return 0;
}
static void set_source(void *p,unsigned int source) { assert(lookup(p)->live);lookup(p)->source=source; }
static unsigned int source(void *p) { assert(lookup(p)->live);return lookup(p)->source; }
static unsigned int size(void *p) { assert(lookup(p)->live);return lookup(p)->bytes; }
static char unhandled_text[220];
static void record(const char *tag,const char *text) {
    assert(tag && text);
    if (!strcmp(tag,"NATIVE_CP_BACKGROUND_ACCEPT ")) accepts++;
    if (!strcmp(tag,"NATIVE_CP_BACKGROUND_UNHANDLED ")) {
        unhandled++;assert(strlen(text)<sizeof unhandled_text);strcpy(unhandled_text,text);
    }
}
static int send(unsigned int destination,void *p) {
    struct message *m=lookup(p);assert(m->live && destination==SOURCE);
    sends++;last_reply=p;memcpy(captured,p,12);captured_source=m->source;
    if (fail_send) return -7;
    if (fast_free) {
        int rc=99;assert(native_cp_background_release(destination,p,release,record,&rc)==1 && !rc);
        if (reuse_address) {
            void *next=make(SOURCE,8,123);assert(next==p);
            rc=99;assert(!native_cp_background_release(SOURCE,next,release,record,&rc));
            assert(!release(SOURCE,next));
        }
    }
    return 0;
}
static void observe_free(unsigned int destination,const unsigned char wire[12]) {
    assert(destination==SOURCE && wire[0]==1 && wire[2]==7 && wire[3]==0x30);
    assert(wire[8]==0 && wire[9]==0xf0 && wire[10]==0 && wire[11]==0);
    struct cp_sync_resources *r=native_cp_background_resources();assert(r);
    struct cp_sync_snapshot view;assert(!cp_sync_snapshot(r,&view));
    free_observations++;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static void *request(void) {
    unsigned char *p=make(NATIVE_CP_BACKGROUND_SID,24,SOURCE);
    p[2]=7;p[3]=0x30;p[4]=0x12;p[5]=0x34;p[6]=0x56;p[7]=0x78;return p;
}
static int dispatch(void *p) {
    int rc=123;assert(native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,1,&rc)==1);return rc;
}
static void free_reply(void *p) {
    int rc=123;assert(native_cp_background_release(SOURCE,p,release,record,&rc)==1 && !rc);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if (!strcmp(argv[1],"fork-initialization")) {
        assert(!pipe(window_ready) && !pipe(window_release));
        atomic_store(&initialization_window,1);
        pthread_t thread;assert(!pthread_create(&thread,NULL,initialize_thread,NULL));
        char byte;assert(read(window_ready[0],&byte,1)==1);
        pid_t child=fork();assert(child>=0);
        if (!child) { alarm(2);_exit(native_cp_background_resources()==NULL?0:1); }
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
        assert(write(window_release[1],&byte,1)==1);
        void *value=NULL;assert(!pthread_join(thread,&value) && value);
        assert(!close(window_ready[0]) && !close(window_ready[1]) &&
               !close(window_release[0]) && !close(window_release[1]));
        return 0;
    }
    if(!strcmp(argv[1],"observe-normal") || !strcmp(argv[1],"observe-fast-free") ||
       !strcmp(argv[1],"observe-sendfail") || !strcmp(argv[1],"observe-reply-fail")) {
        assert(!native_cp_background_bind_free_observer(observe_free));observer_bound=1;
    }
    void *p=request();int rc=123;
    if (!strcmp(argv[1],"normal") || !strcmp(argv[1],"observe-normal")) {
        assert(!dispatch(p));assert(!lookup(p)->live && accepts==1);
        assert(sends==1 && captured_source==NATIVE_CP_BACKGROUND_SID);
        assert(captured[0]==1 && captured[1]==0 && captured[2]==7 && captured[3]==0x30);
        assert(!memcmp(captured+4,(unsigned char[]){0x12,0x34,0x56,0x78,0,0xf0,0,0},8));
        pid_t child=fork();assert(child>=0);
        if (!child) {
            int result=0;
            _exit(native_cp_background_release(SOURCE,last_reply,release,record,&result)==1 && result==-1021?0:1);
        }
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
        free_reply(last_reply);
        assert(releases==2);
    } else if (!strcmp(argv[1],"unused-bytes")) {
        /* Exact passive capture from run-4d24ai94: not zero-filled padding. */
        const unsigned char wire[24]={0x00,0xc1,0x07,0x30,0x7f,0,0,0,
            0x20,0x1e,0x17,0x2e,0x7f,0,0,0,0xc3,0x61,0x91,0x80,0,0,0,0};
        memcpy(p,wire,sizeof wire);assert(!dispatch(p) && accepts==1);
        assert(!memcmp(captured+4,(unsigned char[]){0x7f,0,0,0},4));free_reply(last_reply);
    } else if (!strcmp(argv[1],"observe-unhandled")) {
        /* A 4000-series batch must be delegated, logged, and never answered. */
        unsigned char *batch=make(NATIVE_CP_BACKGROUND_SID,16,SOURCE);
        batch[0]=5;batch[2]=0x63;batch[3]=0x40;
        int result=123;
        assert(!native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,batch,&io,1,&result));
        assert(unhandled==1 && strstr(unhandled_text,"opcode=0x4063") &&
               strstr(unhandled_text,"delegated=1"));
        assert(!allocations && !sends && !releases && !accepts && result==123);
        assert(lookup(batch)->live);
        unsigned char *shortp=make(NATIVE_CP_BACKGROUND_SID,2,SOURCE);
        assert(!native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,shortp,&io,1,&result));
        assert(unhandled==2 && !allocations && !sends);
        /* Delegation never consumes the request: the caller keeps ownership. */
        assert(!release(NATIVE_CP_BACKGROUND_SID,shortp));
        assert(!release(NATIVE_CP_BACKGROUND_SID,batch));
        assert(!release(NATIVE_CP_BACKGROUND_SID,p));
    } else if (!strcmp(argv[1],"bad-command") || !strcmp(argv[1],"bad-type") ||
               !strcmp(argv[1],"legacy-40b8")) {
        if (!strcmp(argv[1],"bad-command")) ((unsigned char *)p)[2]=0x73;
        else if (!strcmp(argv[1],"legacy-40b8")) {
            lookup(p)->bytes=12;lookup(p)->source=0x80020002;
            ((unsigned char *)p)[0]=5;((unsigned char *)p)[2]=0xb8;((unsigned char *)p)[3]=0x40;
        } else ((unsigned char *)p)[0]=2;
        assert(!native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,1,&rc));
        assert(rc==123 && lookup(p)->live && !allocations && !sends && !releases);
        assert(!release(NATIVE_CP_BACKGROUND_SID,p));
    } else if (!strcmp(argv[1],"fast-free") || !strcmp(argv[1],"fast-reuse") || !strcmp(argv[1],"observe-fast-free")) {
        fast_free=1;reuse_address=!strcmp(argv[1],"fast-reuse");
        assert(!dispatch(p) && accepts==1 && releases==(reuse_address?3u:2u));
    } else if (!strcmp(argv[1],"allocfail")) {
        fail_allocate=1;assert(dispatch(p)==-12 && lookup(p)->live && !sends && !releases);
        fail_allocate=0;assert(!dispatch(p));free_reply(last_reply);
    } else if (!strcmp(argv[1],"sendfail") || !strcmp(argv[1],"observe-sendfail")) {
        fail_send=1;assert(dispatch(p)==-7 && lookup(p)->live && releases==1 && !accepts);
        assert(dispatch(p)==-1021 && allocations==1);assert(!release(NATIVE_CP_BACKGROUND_SID,p));
    } else if (!strcmp(argv[1],"request-free-fail")) {
        fail_free=p;assert(!dispatch(p) && lookup(p)->live && accepts==1);
        free_reply(last_reply);fail_free=NULL;
        assert(dispatch(p)==-1021);
        assert(native_cp_background_release(SOURCE,p,release,record,&rc)==1 && rc==-1021);
        assert(native_cp_background_release(NATIVE_CP_BACKGROUND_SID,p,release,record,&rc)==1 && !rc);
    } else if (!strcmp(argv[1],"wrong-free")) {
        assert(!dispatch(p));
        assert(native_cp_background_release(SOURCE+1,last_reply,release,record,&rc)==1 && rc==-1021);
        assert(lookup(last_reply)->live);free_reply(last_reply);
    } else if (!strcmp(argv[1],"reply-free-fail") || !strcmp(argv[1],"observe-reply-fail")) {
        assert(!dispatch(p));fail_free=last_reply;
        assert(native_cp_background_release(SOURCE,last_reply,release,record,&rc)==1 && rc==-9);
        assert(lookup(last_reply)->live);fail_free=NULL;free_reply(last_reply);
    } else if (!strcmp(argv[1],"leases-full")) {
        void *queued[8];
        for (unsigned int i=0;i<8;i++) { assert(!dispatch(p));queued[i]=last_reply;p=request(); }
        assert(dispatch(p)==-1021 && lookup(p)->live && allocations==8 && sends==8);
        for (unsigned int i=0;i<8;i++) free_reply(queued[i]);
        assert(!dispatch(p));free_reply(last_reply);
    } else if (!strcmp(argv[1],"real-backing-busy")) {
        struct cp_sync_resources *r=native_cp_background_resources();assert(r);uint64_t lease;
        assert(!cp_sync_allocate(r,6,128,&lease));
        assert(dispatch(p)==-1021 && !sends && lookup(p)->live && releases==1);
        struct cp_sync_snapshot v;assert(!cp_sync_snapshot(r,&v) && !v.idle && v.bytes==128);
        assert(!cp_sync_release(r,lease) && !cp_sync_free(r,6,lease));
        assert(!release(NATIVE_CP_BACKGROUND_SID,p));
    } else {
        assert(!native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,0,&rc));
        assert(!native_cp_background_dispatch(1,p,&io,1,&rc));
        if (!strcmp(argv[1],"bad-size")) lookup(p)->bytes=8;
        else if (!strcmp(argv[1],"bad-source")) lookup(p)->source=0;
        else abort();
        assert(dispatch(p)==-1021 && lookup(p)->live && !allocations && !sends);
        assert(!release(NATIVE_CP_BACKGROUND_SID,p));
    }
    if(observer_bound)assert(free_observations==(!strcmp(argv[1],"observe-normal")?1u:0u));
    else assert(!free_observations);
    for (unsigned int i=0;i<80;i++) assert(!messages[i].live);
    return 0;
}
