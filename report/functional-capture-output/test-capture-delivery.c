/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "capture-delivery.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
struct packet { unsigned source,size,index;unsigned char bytes[CAPTURE_NOTIFY_INFO_BYTES]; };
static struct capture_delivery *delivery;
static struct packet *packets[3];
static unsigned allocations,sends,frees,reserved,released;
static int inline_receive,send_error,allocate_error,allocated_on_error,free_error,ready,guard_error,bad_source;
static pthread_mutex_t sync_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition=PTHREAD_COND_INITIALIZER;
static int receiver_seen,receiver_release,release_inside,release_exit,hold_release;
static uint8_t request4038[16],job_time[12]={0,0,0xe8,7,2,29,12,34,56,0,0,0};
static struct packet *packet(void *p){return (struct packet *)((unsigned char *)p - offsetof(struct packet,bytes));}
static unsigned char *read_file(const char *path,size_t *bytes){FILE *f=fopen(path,"rb");assert(f && !fseek(f,0,SEEK_END));long n=ftell(f);assert(n>0);rewind(f);unsigned char *p=malloc((size_t)n);assert(p);assert(fread(p,1,(size_t)n,f)==(size_t)n && !fclose(f));*bytes=(size_t)n;return p;}
static unsigned u16(const unsigned char *p){return p[0]|(unsigned)p[1]<<8;}
static int reserve(void){++reserved;return guard_error;}
static void unreserve(void){++released;}
static int predecessor(void){return ready;}
static int allocate(unsigned destination,void **out,unsigned bytes,unsigned wait){
    assert(destination==NATIVE_CP_STATE_PUBLICATION_AP && out && wait==1 && allocations<3);
    unsigned index=allocations++;
    if(allocate_error && index==1 && !allocated_on_error)return -ENOMEM;
    struct packet *p=calloc(1,sizeof *p);assert(p);p->size=bytes;p->index=index;packets[index]=p;*out=p->bytes;
    return allocate_error && index==1?-ENOMEM:0;
}
static void source(void *p,unsigned value){packet(p)->source=bad_source?0:value;}
static unsigned get_size(void *p){return packet(p)->size;}
static unsigned get_source(void *p){return packet(p)->source;}
static int release(unsigned destination,void *p){
    assert(destination==NATIVE_CP_STATE_PUBLICATION_AP);struct packet *m=packet(p);assert(packets[m->index]==m);
    pthread_mutex_lock(&sync_mutex);
    if(hold_release){release_inside=1;pthread_cond_broadcast(&condition);while(!release_exit)pthread_cond_wait(&condition,&sync_mutex);}
    pthread_mutex_unlock(&sync_mutex);
    if(free_error)return -EIO;
    packets[m->index]=NULL;free(m);++frees;return 0;
}
static int send(unsigned destination,void *p){
    struct packet *m=packet(p);assert(destination==NATIVE_CP_STATE_PUBLICATION_AP && m->source==NATIVE_CP_STATE_PUBLICATION_SID);
    static const unsigned commands[]={0x1000,0x1017,0x1006};assert(sends==m->index && u16(m->bytes+2)==commands[sends]);++sends;
    assert(delivery && capture_delivery_close(delivery)==-EBUSY);
    if(inline_receive){assert(capture_delivery_observe(delivery,destination,p)==1);assert(capture_delivery_observe(delivery,destination,p)==-EALREADY);int rc=99;assert(capture_delivery_free(delivery,destination,p,&rc)==1 && rc==(free_error?-EIO:0));}
    return send_error && sends==2?-ENOSPC:0;
}
static const struct full_imaging_io io={allocate,release,source,send,get_size,get_source,NULL};
static const struct native_cp_state_publication_guard guard={reserve,unreserve,predecessor};
static void reset(void){
    assert(!delivery);for(unsigned i=0;i<3;++i)assert(!packets[i]);
    allocations=sends=frees=reserved=released=0;inline_receive=send_error=allocate_error=allocated_on_error=free_error=bad_source=guard_error=0;ready=1;
    receiver_seen=receiver_release=release_inside=release_exit=hold_release=0;
}
static void consume(unsigned index){
    void *p=packets[index]->bytes;assert(capture_delivery_observe(delivery,NATIVE_CP_STATE_PUBLICATION_AP,p)==1);
    int rc=123;assert(capture_delivery_free(delivery,NATIVE_CP_STATE_PUBLICATION_AP,p,&rc)==1 && !rc);
}
static void close_delivery(unsigned expected_consumed,int first_error){
    struct capture_delivery_info info;assert(!capture_delivery_info(delivery,&info));
    assert(info.wire_consumed==expected_consumed && info.first_error==first_error && !info.retained && info.guard_held);
    assert(!capture_delivery_close(delivery));delivery=NULL;assert(released==1);
}
static void *receiver(void *unused){
    (void)unused;void *p=packets[0]->bytes;assert(capture_delivery_observe(delivery,NATIVE_CP_STATE_PUBLICATION_AP,p)==1);
    pthread_mutex_lock(&sync_mutex);receiver_seen=1;pthread_cond_broadcast(&condition);while(!receiver_release)pthread_cond_wait(&condition,&sync_mutex);pthread_mutex_unlock(&sync_mutex);
    int rc=99;assert(capture_delivery_free(delivery,NATIVE_CP_STATE_PUBLICATION_AP,p,&rc)==1 && !rc);return NULL;
}
int main(int argc,char **argv){
    assert(argc==4);size_t nf,nm,nt;unsigned char *frame=read_file(argv[1],&nf),*main=read_file(argv[2],&nm),*thumb=read_file(argv[3],&nt);
    memcpy(request4038,(unsigned char[]){5,0,0x38,0x40,0,0,0,0,2,0,0,0,0,0,0,0},16);memcpy(request4038+4,frame+80,4);
    uint8_t parameters[128]={0};parameters[0x63]=8;struct capture_input *input=NULL;
    assert(!capture_input_create(frame,nf,request4038,parameters,&input));struct capture_output_memory *output=NULL;
    assert(!capture_output_memory_create(input,main,nm,thumb,nt,0,&output));uint64_t export;assert(!capture_output_memory_hold(output,&export));
    reset();ready=0;assert(capture_delivery_begin(output,request4038,job_time,&io,&guard,&delivery)==-ENODATA && !delivery && !allocations && released==1);
    reset();guard_error=-EBUSY;assert(capture_delivery_begin(output,request4038,job_time,&io,&guard,&delivery)==-EBUSY && !delivery && !released);
    reset();uint8_t wrong[16];memcpy(wrong,request4038,16);wrong[4]^=1;assert(capture_delivery_begin(output,wrong,job_time,&io,&guard,&delivery)==-EBADMSG && !delivery && released==1 && !allocations);
    reset();inline_receive=1;assert(!capture_delivery_begin(output,request4038,job_time,&io,&guard,&delivery));assert(allocations==3 && sends==3 && frees==3);close_delivery(3,0);assert(capture_output_memory_destroy(output)==-EBUSY);
    reset();assert(!capture_delivery_begin(output,request4038,job_time,&io,&guard,&delivery));assert(capture_delivery_close(delivery)==-EBUSY);
    int rc=99;assert(capture_delivery_free(delivery,NATIVE_CP_STATE_PUBLICATION_AP,packets[0]->bytes,&rc)==1 && rc==-EPROTO);assert(capture_delivery_observe(delivery,1,packets[0]->bytes)==0);
    packets[0]->bytes[4]^=1;assert(capture_delivery_observe(delivery,NATIVE_CP_STATE_PUBLICATION_AP,packets[0]->bytes)==-EBADMSG);packets[0]->bytes[4]^=1;
    pthread_t thread;assert(!pthread_create(&thread,NULL,receiver,NULL));pthread_mutex_lock(&sync_mutex);while(!receiver_seen)pthread_cond_wait(&condition,&sync_mutex);pthread_mutex_unlock(&sync_mutex);
    assert(capture_delivery_free(delivery,NATIVE_CP_STATE_PUBLICATION_AP,packets[0]->bytes,&rc)==1 && rc==-EPROTO);
    pthread_mutex_lock(&sync_mutex);hold_release=1;receiver_release=1;pthread_cond_broadcast(&condition);while(!release_inside)pthread_cond_wait(&condition,&sync_mutex);pthread_mutex_unlock(&sync_mutex);
    assert(capture_delivery_close(delivery)==-EBUSY && capture_delivery_cleanup(delivery)==-EBUSY);
    pthread_mutex_lock(&sync_mutex);release_exit=1;pthread_cond_broadcast(&condition);pthread_mutex_unlock(&sync_mutex);assert(!pthread_join(thread,NULL));hold_release=0;
    consume(1);consume(2);close_delivery(3,-EBADMSG);
    reset();send_error=1;assert(capture_delivery_begin(output,request4038,job_time,&io,&guard,&delivery)==-ENOSPC && sends==2);
    assert(!capture_delivery_cleanup(delivery) && frees==1 && packets[0] && !packets[1]);assert(capture_delivery_close(delivery)==-EBUSY);consume(0);close_delivery(1,-ENOSPC);
    reset();inline_receive=send_error=1;assert(capture_delivery_begin(output,request4038,job_time,&io,&guard,&delivery)==-ENOSPC && frees==2);close_delivery(1,-ENOSPC);
    for(unsigned allocated=0;allocated<2;++allocated){
        reset();allocate_error=1;allocated_on_error=(int)allocated;assert(capture_delivery_begin(output,request4038,job_time,&io,&guard,&delivery)==-ENOMEM);
        assert(!capture_delivery_cleanup(delivery));consume(0);close_delivery(1,-ENOMEM);
    }
    reset();inline_receive=free_error=1;assert(capture_delivery_begin(output,request4038,job_time,&io,&guard,&delivery)==-EIO && sends==1);free_error=0;
    assert(capture_delivery_free(delivery,NATIVE_CP_STATE_PUBLICATION_AP,packets[0]->bytes,&rc)==1 && !rc);close_delivery(1,-EIO);
    reset();bad_source=1;assert(capture_delivery_begin(output,request4038,job_time,&io,&guard,&delivery)==-EBADMSG && sends==0);assert(!capture_delivery_cleanup(delivery));close_delivery(0,-EBADMSG);
    reset();assert(!capture_delivery_begin(output,request4038,job_time,&io,&guard,&delivery));pid_t child=fork();assert(child>=0);
    if(!child){struct capture_delivery_info state;assert(capture_delivery_info(delivery,&state)==-ECHILD && capture_delivery_close(delivery)==-ECHILD);_exit(0);}
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));for(unsigned i=0;i<3;++i)consume(i);close_delivery(3,0);
    assert(!capture_output_memory_drop(output,export));assert(!capture_output_memory_destroy(output));assert(!capture_input_destroy(input));free(frame);free(main);free(thumb);
    puts("PASS original-consumer notification-transport inline-async-receiver-failed-send-cleanup-owned-output");return 0;
}
