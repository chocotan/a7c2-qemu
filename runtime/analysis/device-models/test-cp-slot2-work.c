/* SPDX-License-Identifier: MIT */
#include "cp-slot2-work.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

/* Explicit HOST fixture, not an implementation of the unknown CP consumer.
 * Fault/pending cases intentionally retain a reachable instance/lease to exit. */
static struct fixture {
    struct cp_slot2_work *s;
    struct cp_slot2_io io;
    struct cp_slot2_input in;
    unsigned char n[200],expected[200],known[200],record[20],root[16],extra;
    unsigned char banks[2*CP_SLOT2_BANK_BYTES],bank_known[2*CP_SLOT2_BANK_BYTES];
    uint64_t lease_generation;
    unsigned int selector,executions,completions,live;
    int enqueue_result,execute_result,complete_result,unknown_root,bad_bank,block;
    char order[8];size_t events;
    pthread_mutex_t mutex;
    pthread_cond_t cond;
    int entered,proceed;
} f;
static const unsigned char done[20]={0x75,0x70,0x63,0,0,0,0,0,0x91,0xe1,0x4d,0,0,0,0,0,0,0,0};
static const unsigned char queued[20]={0x7b,0xca,0x74,0,0,0,0,0,0x87,0x6d,0x8c,0,0,0,0,0,0,0,0,0};
static uint32_t get32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static void put32(unsigned char *p,uint32_t n) {
    for (size_t i=0;i<4;i++) p[i]=(unsigned char)(n>>(i*8));
}
static uint32_t hash(const unsigned char *p) {
    uint32_t h=UINT32_C(2166136261);
    for (size_t i=0;i<200;i++) h=(h^p[i])*UINT32_C(16777619);
    return h;
}
static struct cp_slot2_view snap(void) {
    struct cp_slot2_view v;assert(!cp_slot2_snapshot(f.s,&v));
    assert(!v.original_worker_verified && !v.original_schedule_verified);
    assert(!v.completion_publish_verified && !v.observed_known && !v.observed && !v.completion_mask);
    return v;
}
static void reenter(unsigned int stage) {
    struct cp_slot2_view v=snap();assert(v.busy && v.stage==stage && f.live);
    assert(cp_slot2_destroy(f.s)==-EBUSY);
    assert(cp_slot2_bind(f.s,&f.io,&f)==-EBUSY);
    assert(cp_slot2_begin(f.s,&f.in)==-EBUSY);
    assert(cp_slot2_tick(f.s)==-EBUSY);
}
static int valid(void *arg,const struct cp_slot2_borrowed *b) {
    assert(arg==&f && b->context==&f);
    assert(snap().busy);
    if (!f.live || b->generation!=f.lease_generation) return -ESTALE;
    return b->mode==7?0:-ENOTSUP; /* Supplied fixture mode, not a CP mode claim. */
}
static int read_cp32(void *arg,const struct cp_slot2_borrowed *b,uint32_t address,
    unsigned char *bytes,unsigned char *known,size_t size) {
    int rc=valid(arg,b);if (rc) return rc;
    if (address==UINT32_C(0x172fe56) && size==2) {
        memcpy(bytes,f.root+6,2);memset(known,f.unknown_root?0:1,2);return 0;
    }
    if (address==UINT32_C(0x1730bb8) && size==1) {
        *bytes=f.extra;*known=1;return 0;
    }
    return -EFAULT; /* No zero-filled unknown CP span or normal G+10 mapping. */
}
static int enqueue(void *arg,uint32_t queue,const unsigned char *record,const unsigned char *work) {
    assert(arg==&f && queue==CP_SLOT2_QUEUE_TOKEN);
    assert(!memcmp(record,queued,20) && get32(work)==2);
    assert(!memcmp(work+4,f.expected,200) && !memcmp(work+0xcc,done,20));
    reenter(CP_SLOT2_VALIDATING);f.order[f.events++]='q';return f.enqueue_result;
}
static int execute(void *arg,const struct cp_slot2_pointer_view *n,
    const struct cp_slot2_borrowed *b,struct cp_slot2_bank *bank) {
    assert(arg==&f && n->size==200 && n->known_size==200);
    assert(!memcmp(n->bytes,f.expected,200) && n->source_fnv==hash(f.expected));
    for (size_t i=0;i<200;i++) assert(n->known[i]==1);
    assert(get32(n->bytes)==UINT32_C(0x172fe50));
    unsigned char borrowed=0xa5,known=0;
    assert(!read_cp32(arg,b,get32(n->bytes+4),&borrowed,&known,1) && known==1);
    assert(bank->token==CP_SLOT2_BANK_BASE+(f.selector^1)*0x920u);
    reenter(CP_SLOT2_EXECUTING);assert(snap().selector==f.selector);
    f.order[f.events++]='x';f.executions++;
    if (f.block) {
        assert(!pthread_mutex_lock(&f.mutex));f.entered=1;
        assert(!pthread_cond_signal(&f.cond));
        while (!f.proceed) assert(!pthread_cond_wait(&f.cond,&f.mutex));
        assert(!pthread_mutex_unlock(&f.mutex));
    }
    for (size_t i=0;i<CP_SLOT2_BANK_BYTES;i++) {
        if (f.bad_bank==1 && i>=4) continue; /* Fixture branch consumes/writes only four bytes. */
        bank->bytes[i]=(unsigned char)(borrowed+0x40u+i*3u);bank->known[i]=1;
    }
    bank->fully_consumed=1;
    if (f.bad_bank==2) bank->known_size--;
    if (f.bad_bank==3) bank->fully_consumed=0;
    if (f.bad_bank==4) bank->token++;
    if (f.bad_bank==5) bank->known[1]=2;
    if (f.bad_bank==6) f.lease_generation++;
    return f.execute_result;
}
static int complete(void *arg,const struct cp_slot2_borrowed *b,const unsigned char *record,uint32_t module) {
    assert(arg==&f && module==2 && !memcmp(record,done,20));
    assert(!valid(arg,b));reenter(CP_SLOT2_COMPLETING);
    struct cp_slot2_view v=snap();
    if (f.executions) {
        assert(v.selector==(f.selector^1) && v.publications==1);
        assert(v.bank_generation[v.selector]==v.generation && !v.completed_generation);
        for (size_t i=0;i<CP_SLOT2_BANK_BYTES;i++) {
            int opaque=f.bad_bank==1 && i>=4;
            assert(v.banks[v.selector*CP_SLOT2_BANK_BYTES+i]==
                   (opaque?0xa5:(unsigned char)(f.extra+0x40u+i*3u)));
            assert(v.bank_known[v.selector*CP_SLOT2_BANK_BYTES+i]==(opaque?0:1));
        }
    } else {
        assert(v.selector==f.selector && !v.publications && !v.completed_generation);
        assert(!memcmp(v.banks,f.banks,sizeof f.banks));
    }
    assert(!v.callbacks);f.order[f.events++]='c';f.completions++;
    return f.complete_result;
}
static void init(unsigned int selector,unsigned int command) {
    memset(&f,0,sizeof f);f.live=1;f.selector=selector;f.extra=0x21;
    f.lease_generation=19;f.enqueue_result=1;
    for (size_t i=0;i<200;i++) f.n[i]=(unsigned char)(i*7u+3u);
    put32(f.n,UINT32_C(0x172fe50));put32(f.n+4,UINT32_C(0x1730bb8));
    memcpy(f.expected,f.n,200);memset(f.known,1,200);memcpy(f.record,done,20);
    f.root[6]=(unsigned char)command;f.root[7]=(unsigned char)(command>>8);
    memset(f.banks,0xa7,sizeof f.banks);memset(f.bank_known,1,sizeof f.bank_known);
    f.io=(struct cp_slot2_io){valid,read_cp32,enqueue,execute,complete};
    f.in=(struct cp_slot2_input){f.n,f.known,f.record,200,200,20,2,command,1,1,{&f,19,7}};
    f.s=cp_slot2_create(selector,f.banks,f.bank_known,sizeof f.banks);assert(f.s);
    assert(!cp_slot2_bind(f.s,&f.io,&f));
}
static void retained(int error,unsigned int executions,unsigned int publications) {
    struct cp_slot2_view v=snap();
    assert(v.busy && v.stage==CP_SLOT2_FAULT && v.fault==error);
    assert(v.publications==publications && f.executions==executions);
    assert(v.selector==(publications?(f.selector^1):f.selector));
    assert(!v.callbacks && !v.completed_generation && f.live);
    assert(cp_slot2_destroy(f.s)==-EBUSY && cp_slot2_tick(f.s)==error);
    assert(cp_slot2_bind(f.s,&f.io,&f)==-EBUSY && cp_slot2_begin(f.s,&f.in)==-EBUSY);
}
static void normal(void) {
    const unsigned int commands[]={0x323,0x32c,0x302};
    for (size_t j=0;j<3;j++) {
        init((unsigned int)(j&1),commands[j]);assert(!cp_slot2_begin(f.s,&f.in));
        struct cp_slot2_view v=snap();
        assert(v.stage==CP_SLOT2_QUEUED && v.busy && !v.callbacks && !v.publications);
        assert(v.source_fnv==hash(f.expected) && v.borrowed_generation==19);
        memset(f.n,0x55,200);memset(f.known,0,200);memset(f.record,0x66,20);
        f.io.execute_8c736a=NULL;f.extra=0x51; /* Borrowed data stays shallow/live. */
        assert(!cp_slot2_tick(f.s));v=snap();
        assert(!v.busy && v.stage==CP_SLOT2_IDLE && v.callbacks==1 && v.publications==1);
        assert(v.requested==commands[j] && v.completed_generation==1 && !strcmp(f.order,"qxc"));
        assert(!memcmp(v.owned_work+4,f.expected,200) && !memcmp(v.owned_work+0xcc,done,20));
        assert(v.banks[v.selector*CP_SLOT2_BANK_BYTES]!= (unsigned char)commands[j]);
        assert(!memcmp(v.banks+f.selector*CP_SLOT2_BANK_BYTES,f.banks,CP_SLOT2_BANK_BYTES));
        f.live=0;assert(cp_slot2_tick(f.s)==-ENOENT);assert(!cp_slot2_destroy(f.s));f.s=NULL;
    }
}
static void invalid(void) {
    init(0,0x323);
    assert(!cp_slot2_create(2,f.banks,f.bank_known,sizeof f.banks));
    assert(!cp_slot2_create(0,NULL,f.bank_known,sizeof f.banks));
    assert(!cp_slot2_create(0,f.banks,f.bank_known,1));
    f.bank_known[0]=2;assert(!cp_slot2_create(0,f.banks,f.bank_known,sizeof f.banks));
    assert(cp_slot2_snapshot(NULL,NULL)==-EINVAL && cp_slot2_snapshot(f.s,NULL)==-EINVAL);
    assert(cp_slot2_begin(f.s,NULL)==-EINVAL && cp_slot2_bind(f.s,NULL,NULL)==-EINVAL);
    struct cp_slot2_input in=f.in;
    f.in.known_size=199;assert(cp_slot2_begin(f.s,&f.in)==-EINVAL);f.in=in;
    f.in.view_size=199;assert(cp_slot2_begin(f.s,&f.in)==-EINVAL);f.in=in;
    f.in.record_size=19;assert(cp_slot2_begin(f.s,&f.in)==-EINVAL);f.in=in;
    f.known[199]=0;assert(cp_slot2_begin(f.s,&f.in)==-EAGAIN);
    f.known[199]=2;assert(cp_slot2_begin(f.s,&f.in)==-EAGAIN);f.known[199]=1;
    f.in.module=1;assert(cp_slot2_begin(f.s,&f.in)==-ENOTSUP);f.in=in;
    f.in.requested_known=0;assert(cp_slot2_begin(f.s,&f.in)==-ENOTSUP);f.in=in;
    f.in.mode_known=0;assert(cp_slot2_begin(f.s,&f.in)==-ENOTSUP);f.in=in;
    f.in.requested=0x201;assert(cp_slot2_begin(f.s,&f.in)==-ENOTSUP);f.in=in;
    f.in.borrowed.generation=0;assert(cp_slot2_begin(f.s,&f.in)==-ENOTSUP);f.in=in;
    for (size_t i=0;i<20;i++) {
        f.record[i]^=1;assert(cp_slot2_begin(f.s,&f.in)==-ENOTSUP);f.record[i]^=1;
    }
    assert(!snap().generation && !snap().busy && !f.events);
    assert(!cp_slot2_destroy(f.s));f.s=NULL;
}
static void *worker(void *arg) { (void)arg;assert(!cp_slot2_tick(f.s));return NULL; }
static void concurrent(void) {
    init(1,0x302);f.block=1;
    assert(!pthread_mutex_init(&f.mutex,NULL) && !pthread_cond_init(&f.cond,NULL));
    assert(!cp_slot2_begin(f.s,&f.in));pthread_t thread;
    assert(!pthread_create(&thread,NULL,worker,NULL));
    assert(!pthread_mutex_lock(&f.mutex));
    while (!f.entered) assert(!pthread_cond_wait(&f.cond,&f.mutex));
    reenter(CP_SLOT2_EXECUTING);assert(!snap().publications);
    f.proceed=1;assert(!pthread_cond_signal(&f.cond));assert(!pthread_mutex_unlock(&f.mutex));
    assert(!pthread_join(thread,NULL));assert(!snap().busy);
    assert(!cp_slot2_destroy(f.s));f.s=NULL;
    assert(!pthread_cond_destroy(&f.cond) && !pthread_mutex_destroy(&f.mutex));
}
static void forked(void) {
    init(0,0x323);assert(!cp_slot2_begin(f.s,&f.in));pid_t pid=fork();assert(pid>=0);
    if (!pid) {
        struct cp_slot2_view v;
        assert(cp_slot2_snapshot(f.s,&v)==-ECHILD && cp_slot2_tick(f.s)==-ECHILD);
        assert(cp_slot2_destroy(f.s)==-ECHILD && cp_slot2_begin(f.s,&f.in)==-ECHILD);
        assert(cp_slot2_bind(f.s,&f.io,&f)==-ECHILD);_exit(0);
    }
    int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(!cp_slot2_tick(f.s) && !cp_slot2_destroy(f.s));f.s=NULL;
}
int main(int argc,char **argv) {
    assert(argc==2);const char *name=argv[1];
    if (!strcmp(name,"normal")) normal();
    else if (!strcmp(name,"invalid")) invalid();
    else if (!strcmp(name,"fork")) forked();
    else if (!strcmp(name,"concurrent")) concurrent();
    else {
        init(0,0x323);
        if (!strcmp(name,"no-executor")) {
            f.io.execute_8c736a=NULL;assert(!cp_slot2_bind(f.s,&f.io,&f));
            assert(!cp_slot2_begin(f.s,&f.in) && cp_slot2_tick(f.s)==-ENOSYS);
            struct cp_slot2_view v=snap();assert(v.busy && v.stage==CP_SLOT2_QUEUED);
            assert(!v.publications && !v.callbacks && !memcmp(v.banks,f.banks,sizeof f.banks));
            assert(cp_slot2_destroy(f.s)==-EBUSY && f.live);
        } else if (!strcmp(name,"enqueue-zero")) {
            f.enqueue_result=0;assert(!cp_slot2_begin(f.s,&f.in));
            struct cp_slot2_view v=snap();assert(!v.busy && v.callbacks==1 && !v.publications);
            assert(!v.completed_generation && !f.executions && !strcmp(f.order,"qc"));
            assert(!cp_slot2_destroy(f.s));f.s=NULL;
        } else if (!strcmp(name,"sparse-bank")) {
            f.bad_bank=1;assert(!cp_slot2_destroy(f.s));
            memset(f.banks,0xa5,sizeof f.banks);memset(f.bank_known,0,sizeof f.bank_known);
            f.s=cp_slot2_create(0,f.banks,f.bank_known,sizeof f.banks);assert(f.s);
            assert(!cp_slot2_bind(f.s,&f.io,&f));
            assert(!cp_slot2_begin(f.s,&f.in) && !cp_slot2_tick(f.s));
            struct cp_slot2_view v=snap();assert(v.selector==1 && !v.busy && v.callbacks==1);
            assert(v.banks[CP_SLOT2_BANK_BYTES+4]==0xa5 && !v.bank_known[CP_SLOT2_BANK_BYTES+4]);
            assert(v.publications==1 && v.completed_generation==1);
            assert(!cp_slot2_destroy(f.s));f.s=NULL;
        } else if (!strcmp(name,"enqueue-error")) {
            f.enqueue_result=-EPIPE;assert(cp_slot2_begin(f.s,&f.in)==-EPIPE);retained(-EPIPE,0,0);
        } else if (!strcmp(name,"unknown-root")) {
            f.unknown_root=1;assert(cp_slot2_begin(f.s,&f.in)==-EAGAIN);retained(-EAGAIN,0,0);assert(!f.events);
        } else if (!strcmp(name,"root-mismatch")) {
            f.root[6]++;assert(cp_slot2_begin(f.s,&f.in)==-ESTALE);retained(-ESTALE,0,0);
        } else if (!strcmp(name,"root-span")) {
            put32(f.n,UINT32_MAX-3);assert(cp_slot2_begin(f.s,&f.in)==-EFAULT);retained(-EFAULT,0,0);
        } else if (!strcmp(name,"mode")) {
            f.in.borrowed.mode=9;assert(cp_slot2_begin(f.s,&f.in)==-ENOTSUP);retained(-ENOTSUP,0,0);
        } else {
            if (!strcmp(name,"execute-error")) f.execute_result=-EIO;
            else if (!strcmp(name,"short-mask")) f.bad_bank=2;
            else if (!strcmp(name,"unconsumed")) f.bad_bank=3;
            else if (!strcmp(name,"wrong-bank")) f.bad_bank=4;
            else if (!strcmp(name,"invalid-mask")) f.bad_bank=5;
            else if (!strcmp(name,"lost-during-execute")) f.bad_bank=6;
            else if (!strcmp(name,"complete-error")) f.complete_result=1;
            else if (!strcmp(name,"failure-callback-error")) { f.enqueue_result=0;f.complete_result=-EIO; }
            else assert(!strcmp(name,"lost-generation"));
            if (!strcmp(name,"failure-callback-error")) {
                assert(cp_slot2_begin(f.s,&f.in)==-EIO);retained(-EIO,0,0);
            } else {
                assert(!cp_slot2_begin(f.s,&f.in));
                int lost=!strcmp(name,"lost-generation");if (lost) f.lease_generation++;
                int error=(lost || f.bad_bank==6)?-ESTALE:
                    (f.execute_result || f.complete_result)?-EIO:-EAGAIN;
                assert(cp_slot2_tick(f.s)==error);retained(error,lost?0:1,f.complete_result?1:0);
                if (!lost) assert(snap().banks[CP_SLOT2_BANK_BYTES]==(unsigned char)(f.extra+0x40));
                assert(f.completions==(f.complete_result?1u:0u));
            }
        }
    }
    puts("host scaffold only; original_worker=0 schedule_verified=0 completion_publish=0 capture=0");
    return 0;
}
