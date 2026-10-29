/* SPDX-License-Identifier: MIT */
#include "cp-upm-hcrn.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

/* Host fixtures only: no original CP worker, AP kernel, or native 302c proof. */
static const unsigned char request[16]={0x62,0x01,0x92,0};
static int fail_create;
void *__real_calloc(size_t,size_t);
int __real_pthread_mutex_init(pthread_mutex_t *,const pthread_mutexattr_t *);
void *__wrap_calloc(size_t n,size_t size) {
    if (fail_create==1) { errno=ENOMEM;return NULL; }
    return __real_calloc(n,size);
}
int __wrap_pthread_mutex_init(pthread_mutex_t *mutex,const pthread_mutexattr_t *attr) {
    return fail_create==2?ENOMEM:__real_pthread_mutex_init(mutex,attr);
}
static uint32_t get32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static void put32(unsigned char *p,uint32_t word) {
    for (size_t i=0;i<4;i++) p[i]=(unsigned char)(word>>(8*i));
}
static uint32_t hash(const unsigned char *p,size_t n) {
    uint32_t h=UINT32_C(2166136261);
    for (size_t i=0;i<n;i++) h=(h^p[i])*UINT32_C(16777619);
    return h;
}
static void all(const unsigned char *p,size_t n,unsigned char value) {
    for (size_t i=0;i<n;i++) assert(p[i]==value);
}
static struct cp_upm_hcrn_view snap(struct cp_upm_hcrn *s) {
    struct cp_upm_hcrn_view v={0};assert(!cp_upm_hcrn_snapshot(s,&v));
    assert(v.virtual_registered==1 && !v.original_registration_verified);
    assert(!v.publication_source_runtime_verified && !v.ap_current_value_verified);
    assert(!v.source_atomic_snapshot_verified && !v.publication_history_runtime_complete);
    assert(v.initialized_cache_only==(v.publications_consumed==0));
    assert(v.generation==v.publications_consumed && v.queries==v.callbacks);
    assert(v.serial==v.publications_consumed+v.queries);
    assert(v.cache_fnv==hash(v.cache,16));all(v.cache_known,16,1);return v;
}
static void unchanged(struct cp_upm_hcrn *s,const struct cp_upm_hcrn_view *before) {
    struct cp_upm_hcrn_view after=snap(s);assert(!memcmp(&after,before,sizeof after));
}
static void packet(unsigned char p[20],uint32_t n) {
    put32(p,CP_UPM_HCRN_PUBLICATION);put32(p+4,UINT32_C(0x12340000)|n);
    put32(p+8,~n);put32(p+12,n*7+19);put32(p+16,n^UINT32_C(0xa5a55a5a));
}
static void tuple(const unsigned char body[16]) {
    if (!get32(body)) { all(body,16,0);return; }
    unsigned char expected[20];uint32_t n=get32(body)&UINT32_C(0xffff);
    assert(n && n<=100);packet(expected,n);assert(!memcmp(body,expected+4,16));
}
static void query(struct cp_upm_hcrn *s,unsigned char body[16]) {
    unsigned char known[16];memcpy(body,request,16);memset(known,1,16);
    assert(!cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,body,16,known,16));
    all(known,16,1);
}
static void normal(void) {
    struct cp_upm_hcrn *s=cp_upm_hcrn_create();assert(s);
    struct cp_upm_hcrn_view v=snap(s);unsigned char body[16];
    all(v.cache,16,0);all(v.last_readback,16,0);
    assert(!v.serial && !v.callbacks && !v.publication_fnv && !v.request_fnv && !v.readback_fnv);
    assert(!v.requested && !v.last_query_generation);
    const uint32_t ap_initial[4]={0,6,26,31};
    for (size_t i=1;i<4;i++) assert(get32(v.cache+4*i)!=ap_initial[i]);
    v.cache[0]=0xff;v.virtual_registered=0;v.ap_current_value_verified=1;
    all(snap(s).cache,16,0);query(s,body);all(body,16,0);
    v=snap(s);assert(v.initialized_cache_only && v.callbacks==1 && !v.generation);
    assert(v.readback_fnv==v.cache_fnv && v.request_fnv==hash(request,16));
    assert(v.requested==CP_UPM_HCRN_QUERY && !memcmp(v.last_readback,body,16));
    for (uint32_t n=1;n<=2;n++) {
        unsigned char p[20],known[20],original[20],old_readback[16];
        packet(p,n);memcpy(original,p,20);memset(known,1,20);
        memcpy(old_readback,v.last_readback,16);
        assert(!cp_upm_hcrn_consume_publication(s,CP_UPM_HCRN_DESTINATION,p,20,known,20));
        assert(!memcmp(p,original,20));all(known,20,1);
        v=snap(s);assert(v.generation==n && v.callbacks==n);
        assert(v.publication_fnv==hash(original,20) && !memcmp(v.cache,original+4,16));
        assert(!memcmp(v.last_readback,old_readback,16));
        memset(p,0xee,20);memset(known,0,20); /* Actor copied, never borrowed the spans. */
        query(s,body);assert(!memcmp(body,original+4,16));
        v=snap(s);assert(v.last_query_generation==n && v.queries==n+1);
        assert(v.readback_fnv==v.cache_fnv && !memcmp(v.last_readback,body,16));
        assert(get32(body)!=CP_UPM_HCRN_QUERY && get32(body)!=UINT32_C(0xf000));
    }
    assert(!cp_upm_hcrn_destroy(s));
    s=cp_upm_hcrn_create();assert(s);all(snap(s).cache,16,0);
    assert(!snap(s).publications_consumed && !snap(s).callbacks);
    assert(!cp_upm_hcrn_destroy(s));
}
static void invalid(void) {
    struct cp_upm_hcrn *s=cp_upm_hcrn_create();assert(s);
    unsigned char p[20],pk[20],body[16],known[16],original[20];
    packet(p,7);memcpy(original,p,20);memset(pk,1,20);
    memcpy(body,request,16);memset(known,1,16);
    assert(!cp_upm_hcrn_consume_publication(s,CP_UPM_HCRN_DESTINATION,p,20,pk,20));
    struct cp_upm_hcrn_view before=snap(s);
    assert(cp_upm_hcrn_snapshot(NULL,&before)==-EINVAL);
    assert(cp_upm_hcrn_snapshot(s,NULL)==-EINVAL && cp_upm_hcrn_destroy(NULL)==-EINVAL);
    assert(cp_upm_hcrn_consume_publication(NULL,0,NULL,0,NULL,0)==-EINVAL);
    assert(cp_upm_hcrn_query_in_place(NULL,0,NULL,0,NULL,0)==-EINVAL);
    assert(cp_upm_hcrn_consume_publication(s,CP_UPM_HCRN_DESTINATION,NULL,20,pk,20)==-EINVAL);
    assert(cp_upm_hcrn_consume_publication(s,CP_UPM_HCRN_DESTINATION,p,20,NULL,20)==-EINVAL);
    assert(cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,NULL,16,known,16)==-EINVAL);
    assert(cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,body,16,NULL,16)==-EINVAL);
    const size_t bad_pub[]={0,19,21,SIZE_MAX},bad_query[]={0,15,17,SIZE_MAX};
    for (size_t i=0;i<4;i++) {
        assert(cp_upm_hcrn_consume_publication(s,CP_UPM_HCRN_DESTINATION,p,bad_pub[i],pk,20)==-EINVAL);
        assert(cp_upm_hcrn_consume_publication(s,CP_UPM_HCRN_DESTINATION,p,20,pk,bad_pub[i])==-EINVAL);
        assert(cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,body,bad_query[i],known,16)==-EINVAL);
        assert(cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,body,16,known,bad_query[i])==-EINVAL);
    }
    const uint32_t bad_sid[]={0,0x80920022,0x80920021,0x90030001,0x92a20844};
    for (size_t i=0;i<sizeof bad_sid/sizeof *bad_sid;i++) {
        assert(cp_upm_hcrn_consume_publication(s,bad_sid[i],p,20,pk,20)==-ENOTSUP);
        assert(cp_upm_hcrn_query_in_place(s,bad_sid[i],body,16,known,16)==-ENOTSUP);
    }
    const unsigned char bad_mask[]={0,2,255};
    for (size_t j=0;j<sizeof bad_mask;j++) {
        for (size_t i=0;i<20;i++) {
            pk[i]=bad_mask[j];
            assert(cp_upm_hcrn_consume_publication(s,CP_UPM_HCRN_DESTINATION,p,20,pk,20)==-EAGAIN);
            assert(pk[i]==bad_mask[j]);pk[i]=1;
        }
        for (size_t i=0;i<16;i++) {
            known[i]=bad_mask[j];
            assert(cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,body,16,known,16)==-EAGAIN);
            assert(!memcmp(body,request,16) && known[i]==bad_mask[j]);known[i]=1;
        }
    }
    for (size_t i=0;i<4;i++) {
        p[i]^=1;
        assert(cp_upm_hcrn_consume_publication(s,CP_UPM_HCRN_DESTINATION,p,20,pk,20)==-ENOTSUP);
        assert(p[i]==(unsigned char)(original[i]^1));p[i]^=1;
    }
    for (size_t i=0;i<16;i++) {
        body[i]^=1;
        assert(cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,body,16,known,16)==-ENOTSUP);
        assert(body[i]==(unsigned char)(request[i]^1));body[i]^=1;
    }
    unchanged(s,&before);assert(!memcmp(p,original,20) && !memcmp(body,request,16));
    all(pk,20,1);all(known,16,1);assert(!cp_upm_hcrn_destroy(s));
}
static void aliases(void) {
    struct cp_upm_hcrn *s=cp_upm_hcrn_create();assert(s);
    struct cp_upm_hcrn_view before=snap(s);
    for (size_t offset=0;offset<16;offset++) {
        for (unsigned int reverse=0;reverse<2;reverse++) {
            unsigned char buf[64],saved[64];memset(buf,1,sizeof buf);
            unsigned char *body=buf+4+(reverse?offset:0),*known=buf+4+(reverse?0:offset);
            memcpy(body,request,16);memcpy(saved,buf,sizeof buf);
            assert(cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,body,16,known,16)==-EINVAL);
            assert(!memcmp(buf,saved,sizeof buf));unchanged(s,&before);
        }
    }
    unsigned char body[16],known[16];memcpy(body,request,16);memset(known,1,16);
    unsigned char *wrapped=(unsigned char *)(uintptr_t)(UINTPTR_MAX-7);
    assert(cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,wrapped,16,known,16)==-EINVAL);
    assert(cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,body,16,wrapped,16)==-EINVAL);
    unchanged(s,&before);assert(!memcmp(body,request,16));all(known,16,1);
    for (unsigned int reverse=0;reverse<2;reverse++) {
        unsigned char buf[40];memset(buf,0xa5,sizeof buf);
        unsigned char *b=buf+4+(reverse?16:0),*k=buf+4+(reverse?0:16);
        memcpy(b,request,16);memset(k,1,16);
        assert(!cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,b,16,k,16));
        all(b,16,0);all(k,16,1);all(buf,4,0xa5);all(buf+36,4,0xa5);
    }
    assert(!cp_upm_hcrn_destroy(s));
}
struct threads {
    struct cp_upm_hcrn *s;
    pthread_mutex_t mutex;
    pthread_cond_t cond;
    unsigned int waiting,go;
};
static void start(struct threads *t) {
    assert(!pthread_mutex_lock(&t->mutex));t->waiting++;
    assert(!pthread_cond_broadcast(&t->cond));
    while (!t->go) assert(!pthread_cond_wait(&t->cond,&t->mutex));
    assert(!pthread_mutex_unlock(&t->mutex));
}
static void *reader(void *arg) {
    struct threads *t=arg;start(t);
    for (size_t i=0;i<100;i++) {
        unsigned char body[16];query(t->s,body);tuple(body);
        struct cp_upm_hcrn_view v=snap(t->s);tuple(v.cache);tuple(v.last_readback);
        assert(v.last_query_generation<=v.generation && v.readback_fnv==hash(v.last_readback,16));
    }
    return NULL;
}
static void *publisher(void *arg) {
    struct threads *t=arg;start(t);
    for (uint32_t n=1;n<=100;n++) {
        unsigned char p[20],known[20],saved[20];packet(p,n);
        memcpy(saved,p,20);memset(known,1,20);
        assert(!cp_upm_hcrn_consume_publication(t->s,CP_UPM_HCRN_DESTINATION,p,20,known,20));
        assert(!memcmp(saved,p,20));all(known,20,1);
    }
    return NULL;
}
static void concurrent(void) {
    struct threads t={0};t.s=cp_upm_hcrn_create();assert(t.s);
    assert(!pthread_mutex_init(&t.mutex,NULL) && !pthread_cond_init(&t.cond,NULL));
    pthread_t threads[25];
    for (size_t i=0;i<25;i++) assert(!pthread_create(threads+i,NULL,i==24?publisher:reader,&t));
    assert(!pthread_mutex_lock(&t.mutex));
    while (t.waiting!=25) assert(!pthread_cond_wait(&t.cond,&t.mutex));
    t.go=1;assert(!pthread_cond_broadcast(&t.cond));assert(!pthread_mutex_unlock(&t.mutex));
    for (size_t i=0;i<25;i++) assert(!pthread_join(threads[i],NULL));
    struct cp_upm_hcrn_view v=snap(t.s);
    assert(v.queries==2400 && v.publications_consumed==100 && v.serial==2500);
    unsigned char final[20];packet(final,100);assert(!memcmp(v.cache,final+4,16));
    assert(!cp_upm_hcrn_destroy(t.s));
    assert(!pthread_cond_destroy(&t.cond) && !pthread_mutex_destroy(&t.mutex));
}
static void forked(void) {
    struct cp_upm_hcrn *s=cp_upm_hcrn_create();assert(s);
    struct cp_upm_hcrn_view before=snap(s);pid_t pid=fork();assert(pid>=0);
    if (!pid) {
        unsigned char p[20],known[20],body[16];packet(p,9);memset(known,1,20);
        memcpy(body,request,16);struct cp_upm_hcrn_view out,saved;
        memset(&out,0xa5,sizeof out);memcpy(&saved,&out,sizeof out);
        assert(cp_upm_hcrn_snapshot(s,&out)==-ECHILD && !memcmp(&out,&saved,sizeof out));
        assert(cp_upm_hcrn_consume_publication(s,CP_UPM_HCRN_DESTINATION,p,20,known,20)==-ECHILD);
        assert(cp_upm_hcrn_query_in_place(s,CP_UPM_HCRN_HANDLE,body,16,known,16)==-ECHILD);
        assert(!memcmp(body,request,16));all(known,20,1);
        assert(cp_upm_hcrn_destroy(s)==-ECHILD);
        struct cp_upm_hcrn *own=cp_upm_hcrn_create();assert(own);query(own,body);all(body,16,0);
        assert(!cp_upm_hcrn_destroy(own));_exit(0);
    }
    int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));
    unchanged(s,&before);assert(!cp_upm_hcrn_destroy(s));
}
static void failures(void) {
    for (int i=1;i<=2;i++) {
        fail_create=i;errno=0;assert(!cp_upm_hcrn_create() && errno==ENOMEM);
    }
    fail_create=0;struct cp_upm_hcrn *s=cp_upm_hcrn_create();assert(s);
    assert(snap(s).virtual_registered==1);assert(!cp_upm_hcrn_destroy(s));
}
int main(int argc,char **argv) {
    assert(argc==2);
    if (!strcmp(argv[1],"normal")) normal();
    else if (!strcmp(argv[1],"invalid")) invalid();
    else if (!strcmp(argv[1],"aliases")) aliases();
    else if (!strcmp(argv[1],"concurrent")) concurrent();
    else if (!strcmp(argv[1],"fork")) forked();
    else if (!strcmp(argv[1],"create-failures")) failures();
    else assert(0);
    puts("host_test=1 original_registration=0 publication_runtime=0 AP_current=0 source_atomic=0 history_complete=0 native302c=0");
    return 0;
}
