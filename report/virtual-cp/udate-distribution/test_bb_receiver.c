/* Host ownership/concurrency tests; original kernel IRQ behavior is checked separately. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
#include <stdarg.h>
#include <semaphore.h>
#include <time.h>
#define BACKUP_ENDPOINT_TEST
#include "client.c"
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL %s:%d: %s\n",__FILE__,__LINE__,#c); exit(1); } } while (0)
struct fixture { u32 size, source; u8 body[32]; };
static _Atomic unsigned active, allocated, freed, replies, failed_free;
static unsigned free_failure, reg_failure, create_failure, starts, cancels, sleeps, stop_checks;
static int (*thread_fn)(void *);
static unsigned dummy_task, recycle_once, concurrent_mode;
static long recycle_rc;
static void *recycle_address;
static char last_log[1024];
static pthread_mutex_t queue_mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic unsigned lock_waiters, completed_senders, done, holder_ready, holder_release;
static unsigned defer_once;
static pthread_t holder;
static sem_t permits;
static struct fixture *meta(void *m) { return (struct fixture *)((u8 *)m-8); }
static void init_message(struct fixture *m,u16 command,u16 value)
{
    memset(m,0,sizeof(*m));m->size=command==0x118?22:10;m->source=0x81cf61c3;
    put16(m->body,0x200d);put16(m->body+2,command);
    put16(m->body+4,(u16)m->size);put16(m->body+6,0x8001);put16(m->body+8,value);
    atomic_fetch_add(&active,1);atomic_fetch_add(&allocated,1);
}
static void *new_message(u16 command,u16 value)
{
    struct fixture *m=malloc(sizeof(*m));CHECK(m!=NULL);init_message(m,command,value);return m->body;
}
static void wait_flag(_Atomic unsigned *flag)
{
    struct timespec begin,now;CHECK(!clock_gettime(CLOCK_MONOTONIC,&begin));
    while(!atomic_load(flag)) {
        sched_yield();CHECK(!clock_gettime(CLOCK_MONOTONIC,&now));CHECK(now.tv_sec-begin.tv_sec<5);
    }
}
unsigned long _raw_spin_lock_irqsave(u32 *lock)
{
    CHECK(lock==&bb_lock);atomic_fetch_add(&lock_waiters,1);
    CHECK(!pthread_mutex_lock(&queue_mutex));atomic_fetch_sub(&lock_waiters,1);return 0xabc;
}
void _raw_spin_unlock_irqrestore(u32 *lock,unsigned long flags)
{ CHECK(lock==&bb_lock && flags==0xabc);CHECK(!pthread_mutex_unlock(&queue_mutex)); }
static void *hold_lock(void *unused)
{
    unsigned long flags;(void)unused;flags=_raw_spin_lock_irqsave(&bb_lock);
    atomic_store(&holder_ready,1);wait_flag(&holder_release);_raw_spin_unlock_irqrestore(&bb_lock,flags);return NULL;
}
int printk(const char *fmt,...)
{
    va_list args;va_start(args,fmt);(void)vsnprintf(last_log,sizeof(last_log),fmt,args);va_end(args);return 0;
}
long osal_reg_public(long slot) { CHECK(*(void **)slot!=NULL);return reg_failure?-19:0; }
long osal_free_msg(u32 q,void *m)
{
    CHECK(q==BB_TARGET && m!=NULL);
    if(free_failure) { atomic_fetch_add(&failed_free,1);return -17; }
    atomic_fetch_sub(&active,1);atomic_fetch_add(&freed,1);
    if(recycle_once) {
        recycle_once=0;recycle_address=m;
        /* Deterministic allocator reuse, before the old free call returns to the worker. */
        init_message(meta(m),0x142,1);recycle_rc=udate_sender(BB_TARGET,m);return 0;
    }
    free(meta(m));
    if(concurrent_mode) CHECK(!sem_post(&permits));
    if(defer_once) { defer_once=0;CHECK(!pthread_create(&holder,NULL,hold_lock,NULL));wait_flag(&holder_ready); }
    return 0;
}
u32 osal_get_msg_src(void *m) { return meta(m)->source; }
void osal_set_msg_src(void *m,u32 source) { meta(m)->source=source; }
long osal_valloc_msg_wait(u32 q,void **m,u32 n,u32 wait)
{ (void)q;(void)m;(void)n;(void)wait;atomic_fetch_add(&replies,1);return -99; }
long osal_snd_msg(u32 q,void *m) { (void)q;(void)m;atomic_fetch_add(&replies,1);return -99; }
long osal_dynamic_id(u32 a,u32 b,unsigned long c) { (void)a;(void)b;(void)c;atomic_fetch_add(&replies,1);return -99; }
long osal_rcv_msg_tmo(u32 q,void **m,long t) { (void)q;(void)m;(void)t;atomic_fetch_add(&replies,1);return -99; }
long osal_snd_sync_direct(u32 q,void *m) { (void)q;(void)m;atomic_fetch_add(&replies,1);return -99; }
struct task_struct *kthread_create_on_node(int (*fn)(void *),void *p,int node,const char *name,...)
{ CHECK(p==NULL && node==-1 && !strcmp(name,"a7c2-bb-rx"));thread_fn=fn;return create_failure?(struct task_struct *)(intptr_t)-12:(struct task_struct *)&dummy_task; }
int wake_up_process(struct task_struct *t) { CHECK(t==(struct task_struct *)&dummy_task);++starts;return 1; }
int kthread_stop(struct task_struct *t) { CHECK(t==(struct task_struct *)&dummy_task);++cancels;return 0; }
int kthread_should_stop(void) { return ++stop_checks>BB_DEPTH+3; }
void msleep(unsigned int ms) { CHECK(ms==10);++sleeps; }
static void drain(void) { while(bb_worker_step()) {} }
static void verify_pool(void)
{ CHECK(!active && allocated==freed && !replies && !bb_count && !bb_fault && !bb_inflight.message); }
static void reject(void *m,long expected)
{ CHECK(udate_sender(BB_TARGET,m)==expected);CHECK(!osal_free_msg(BB_TARGET,m)); }
static void lifecycle(void)
{
    static const u16 commands[]={0x142,0x15a,0x160,0x500,0x33b};
    for(unsigned round=0;round<15000;round++) {
        for(unsigned n=0;n<5;n++) CHECK(!udate_sender(BB_TARGET,new_message(commands[n],n==4?0x5500:round%2)));
        CHECK(active==5);drain();verify_pool();
        for(unsigned n=0;n<5;n++) CHECK(bb_values[n]==(n==4?0x5500:round%2));
    }
    CHECK(bb_accepted==75000 && bb_consumed==75000);
    for(unsigned n=0;n<5;n++) CHECK(bb_generation[n]==15000);
}
static void edges(void)
{
    void *m=new_message(0x500,1);
    CHECK(!udate_sender(BB_TARGET,m));CHECK(udate_sender(BB_TARGET,m)==-1021);
    CHECK(strstr(last_log,"BB_K_REJECT") && strstr(last_log,"existing_owner=receiver"));
    drain();verify_pool();CHECK(udate_sender(BB_TARGET,NULL)==-1024);
    CHECK(udate_sender(0x92a208fc,(void *)(uintptr_t)1)==-1020);
    for(unsigned i=0;i<10;i++) {
        m=new_message(0x500,1);
        switch(i) {
        case 0:meta(m)->size=0;break;
        case 1:meta(m)->size=9;break;
        case 2:put16(m,0x2001);break;
        case 3:put16((u8 *)m+4,12);break;
        case 4:put16((u8 *)m+6,1);break;
        case 5:put16((u8 *)m+8,2);break;
        case 6:meta(m)->source=0x92840747;break;
        case 7:meta(m)->source=0x80000000;break;
        case 8:put16((u8 *)m+2,0x118);break;
        default:put16((u8 *)m+2,0x33b);put16((u8 *)m+8,0x101);break;
        }
        reject(m,-1020);
    }
    m=new_message(0x500,1);bb_ready=0;reject(m,-1021);bb_ready=1;
    for(unsigned i=0;i<BB_DEPTH;i++) CHECK(!udate_sender(BB_TARGET,new_message(0x142,1)));
    reject(new_message(0x142,1),-1021);drain();verify_pool();
}
static void fault(void)
{
    void *m=new_message(0x500,1);CHECK(!udate_sender(BB_TARGET,m));
    free_failure=1;CHECK(!bb_worker_step());CHECK(bb_fault && !bb_count && active==1 && failed_free==1);
    CHECK(!bb_worker_step() && failed_free==1 && !bb_generation[3]);
    free_failure=0;reject(new_message(0x500,1),-1021);
    /* Teardown only, after the worker has stopped. The product retains this allocation. */
    CHECK(bb_inflight.message==m);CHECK(!osal_free_msg(BB_TARGET,m));bb_inflight.message=NULL;
    CHECK(!active && !replies);
}
static void *one_step(void *unused) { (void)unused;CHECK(bb_worker_step());return NULL; }
static void defer(void)
{
    pthread_t worker;CHECK(!udate_sender(BB_TARGET,new_message(0x500,1)));
    defer_once=1;CHECK(!pthread_create(&worker,NULL,one_step,NULL));wait_flag(&holder_ready);wait_flag(&lock_waiters);
    CHECK(!active && !bb_count && freed==1);
    atomic_store(&holder_release,1);CHECK(!pthread_join(holder,NULL));CHECK(!pthread_join(worker,NULL));
    CHECK(!bb_worker_step() && freed==1);verify_pool();
}
static void reuse(void)
{
    void *m=new_message(0x500,1);CHECK(!udate_sender(BB_TARGET,m));recycle_once=1;
    CHECK(bb_worker_step());CHECK(recycle_address==m && recycle_rc==0);
    CHECK(active==1 && allocated==2 && freed==1 && bb_count==1 && !bb_inflight.message);
    CHECK(bb_worker_step());CHECK(bb_values[0]==1 && bb_generation[0]==1);
    CHECK(bb_accepted==2 && bb_consumed==2);verify_pool();
}
static void *send_once(void *message)
{ CHECK(!udate_sender(BB_TARGET,message));atomic_fetch_add(&completed_senders,1);return NULL; }
static void contention(void)
{
    pthread_t p;void *m=new_message(0x500,1);unsigned long flags=_raw_spin_lock_irqsave(&bb_lock);
    CHECK(!pthread_create(&p,NULL,send_once,m));wait_flag(&lock_waiters);CHECK(!completed_senders);
    _raw_spin_unlock_irqrestore(&bb_lock,flags);CHECK(!pthread_join(p,NULL));CHECK(completed_senders==1);
    drain();CHECK(!bb_rejected);verify_pool();
}
static void *producer(void *unused)
{
    (void)unused;
    for(unsigned i=0;i<2500;i++) {
        CHECK(!sem_wait(&permits));
        /* Reserve fixture capacity before allocation; original caller submits exactly once. */
        CHECK(udate_sender(BB_TARGET,new_message(0x500,i%2))==0);
    }
    atomic_fetch_add(&done,1);return NULL;
}
static void concurrent(void)
{
    pthread_t p[4];concurrent_mode=1;CHECK(!sem_init(&permits,0,BB_DEPTH/2));
    for(unsigned i=0;i<4;i++) CHECK(!pthread_create(&p[i],NULL,producer,NULL));
    while(atomic_load(&done)!=4) { bb_worker_step();sched_yield(); }
    for(unsigned i=0;i<4;i++) CHECK(!pthread_join(p[i],NULL));
    drain();verify_pool();CHECK(bb_consumed==10000 && !bb_rejected);CHECK(!sem_destroy(&permits));
}
static void panel_record(void)
{
    void *m=new_message(0x118,3);u8 requested[14];
    for(unsigned i=0;i<14;i++) ((u8 *)m)[8+i]=(u8)(i+1);
    memcpy(requested,(u8 *)m+8,14);CHECK(!udate_sender(BB_TARGET,m));
    CHECK(bb_panel_busy && bb_count==1);reject(new_message(0x118,3),-1021);
    CHECK(bb_worker_step());CHECK(!bb_count && bb_panel_pending.message==m);
    struct bb_entry pending=bb_panel_pending;
    CHECK(pending.source==0x81cf61c3 && !memcmp(pending.panel,requested,14));
    CHECK(bb_panel_generation==1 && bb_panel_pending_mask==3 && active==1 && !replies && bb_consumed==0);
    CHECK(strstr(last_log,"BB_K_PANEL_PENDING") && strstr(last_log,"completion=0") && strstr(last_log,"backend_missing=1"));
    CHECK(!bb_worker_step() && !bb_worker_step());CHECK(active==1 && !replies);
    CHECK(!udate_sender(BB_TARGET,new_message(0x142,1)));drain();CHECK(active==1 && bb_values[0]==1);
    /* Resident pending request is released by the fixture only after shutdown. */
    CHECK(!osal_free_msg(BB_TARGET,m));bb_panel_pending.message=NULL;bb_panel_busy=0;verify_pool();
}
static void reject_log(void)
{
    for(unsigned i=0;i<33;i++) {
        void *m=new_message(0x32f,1);memset(last_log,0,sizeof(last_log));
        CHECK(udate_sender(BB_TARGET,m)==-1020);
        if(i<32) CHECK(strstr(last_log,"command=0x32f rc=-1020") && strstr(last_log,"raw=0d202f030a0001800100"));
        else CHECK(!last_log[0]);
        CHECK(!osal_free_msg(BB_TARGET,m));
    }
    CHECK(bb_rejected==33);verify_pool();
}
int main(int argc,char **argv)
{
    CHECK(argc==2);
    if(!strcmp(argv[1],"create-failure")) { create_failure=1;CHECK(init_module()==-12 && !starts && !cancels && !bb_ready); }
    else if(!strcmp(argv[1],"register-failure")) { reg_failure=1;CHECK(init_module()==-19 && !starts && cancels==1 && !bb_ready); }
    else {
        CHECK(!init_module() && starts==1 && !cancels && bb_ready);
        if(!strcmp(argv[1],"lifecycle")) lifecycle();
        else if(!strcmp(argv[1],"edges")) edges();
        else if(!strcmp(argv[1],"free-failure")) fault();
        else if(!strcmp(argv[1],"deferred-retirement")) defer();
        else if(!strcmp(argv[1],"concurrent")) concurrent();
        else if(!strcmp(argv[1],"lock-contention")) contention();
        else if(!strcmp(argv[1],"address-reuse")) reuse();
        else if(!strcmp(argv[1],"panel-record")) panel_record();
        else if(!strcmp(argv[1],"reject-log")) reject_log();
        else { CHECK(!strcmp(argv[1],"thread-loop"));CHECK(!udate_sender(BB_TARGET,new_message(0x500,1)));CHECK(!thread_fn(NULL) && sleeps);verify_pool(); }
    }
    printf("{\"case\":\"%s\",\"accepted\":%u,\"consumed\":%u,\"outstanding\":%u,\"replies\":%u,\"rejected\":%u}\n",argv[1],bb_accepted,bb_consumed,active,replies,bb_rejected);
    return 0;
}
