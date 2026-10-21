/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "sd-hotplug-runtime.h"
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

/* Guest glibc 2.25 has the original scanner, not the host's C23 redirect. */
extern int sd_legacy_sscanf(const char *,const char *,...) __asm__("sscanf");

#ifndef SD_HOTPLUG_DIRECTORY
#define SD_HOTPLUG_DIRECTORY "/tmp"
#endif

static struct {
    sd_core core;
    sd_backing backing;
    struct native_sd_hotplug_io io;
    pid_t pid;
    long worker;
    _Atomic unsigned enabled,port,lost,retired;
    _Atomic uint64_t generation;
    pthread_mutex_t mutex;
    sd_observation events[64];
    unsigned head,count;
    uint64_t seen_sequence,request_sequence;
    sd_result result;
    struct timespec deadline;
} hot={.port=2,.mutex=PTHREAD_MUTEX_INITIALIZER};

static bool guard(void *context)
{
    (void)context;
    return getpid()==hot.pid && hot.worker==syscall(SYS_gettid);
}
static bool backing_valid(void *context,const sd_backing *backing)
{ (void)context;return hot.io.backing_valid(hot.io.context,backing); }
static bool quiesce(void *context,uint64_t generation,uint32_t drive)
{ (void)context;return hot.io.flush(hot.io.context,generation,drive)==0; }
static sd_send_result notify(void *context,uint64_t generation,sd_operation op,const uint8_t p[7])
{
    (void)context;
    atomic_store(&hot.generation,generation);
    atomic_store(&hot.port,p[5]);
    return hot.io.notify(hot.io.context,generation,op,p);
}
static const char *state_name(void)
{
    if(!hot.core.bound)return "unavailable";
    if(atomic_load(&hot.lost))return "uncertain";
    switch(hot.core.state){
    case SD_PRESENT:return "present";
    case SD_ABSENT:return "absent";
    case SD_EJECTING:return "ejecting";
    case SD_INSERTING:return "inserting";
    default:return "uncertain";
    }
}
static void publish(void)
{
    sd_snapshot snapshot={0};
    if(hot.core.bound && sd_snapshot_read(&hot.core,&snapshot)!=SD_OK)return;
    if(hot.core.bound)atomic_store(&hot.port,snapshot.bytes[5]);
    atomic_store(&hot.retired,hot.core.bound && hot.core.state==SD_ABSENT && !atomic_load(&hot.lost));
    char data[360];
    int n=snprintf(data,sizeof data,
        "SD_HOTPLUG v=1 pid=%d sequence=%llu generation=%llu state=%s drive=%u result=%u port=%u lost=%u\n",
        hot.pid,(unsigned long long)hot.request_sequence,
        (unsigned long long)snapshot.generation,state_name(),snapshot.drive,
        (unsigned int)hot.result,atomic_load(&hot.port),atomic_load(&hot.lost));
    if(n<=0 || n>=(int)sizeof data)return;
    int fd=open(SD_HOTPLUG_DIRECTORY "/sd-hotplug.state.new",O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW|O_CLOEXEC,0600);
    int ok=fd>=0 && write(fd,data,(size_t)n)==n && fsync(fd)==0;
    if(fd>=0 && close(fd))ok=0;
    if(ok)rename(SD_HOTPLUG_DIRECTORY "/sd-hotplug.state.new",SD_HOTPLUG_DIRECTORY "/sd-hotplug.state");
}
int native_sd_hotplug_configure(const sd_backing *backing,const struct native_sd_hotplug_io *io)
{
    const char *enabled=getenv("A7C2_SD_HOTPLUG");
    if(!enabled || strcmp(enabled,"1"))return 0;
    if(hot.pid || !backing || !io || !io->context || !io->backing_valid || !io->flush || !io->notify ||
       backing->fd<0 || !backing->identity || !backing->size)return -1;
    hot.pid=getpid();hot.backing=*backing;hot.io=*io;hot.result=SD_UNBOUND;
    atomic_store(&hot.enabled,1);return 0;
}
int native_sd_hotplug_enabled(void)
{ return atomic_load(&hot.enabled) && getpid()==hot.pid; }
int native_sd_hotplug_retired(void)
{ return native_sd_hotplug_enabled() && atomic_load(&hot.retired) && !atomic_load(&hot.lost); }
uint64_t native_sd_hotplug_generation(void)
{ return native_sd_hotplug_enabled()?atomic_load(&hot.generation):0; }
unsigned int native_sd_hotplug_port(void)
{ return native_sd_hotplug_enabled()?atomic_load(&hot.port):2; }
static void enqueue(sd_observation event)
{
    if(!native_sd_hotplug_enabled())return;
    pthread_mutex_lock(&hot.mutex);
    if(hot.count==64){atomic_store(&hot.lost,1);atomic_store(&hot.retired,0);}
    else {hot.events[(hot.head+hot.count)%64]=event;hot.count++;}
    pthread_mutex_unlock(&hot.mutex);
}
void native_sd_hotplug_fsys(sd_observation_kind kind,unsigned int drive,int rc,bool path_validated,bool retired)
{ native_sd_hotplug_fsys_generation(native_sd_hotplug_generation(),kind,drive,rc,path_validated,retired); }
void native_sd_hotplug_fsys_generation(uint64_t generation,sd_observation_kind kind,unsigned int drive,int rc,bool path_validated,bool retired)
{
    if(kind!=SD_MOUNT && kind!=SD_UNMOUNT)return;
    /* A successful return alone is insufficient: require the same process's
     * original volume mask to confirm retirement or the newly mounted drive. */
    if(!rc && !retired)rc=-1021;
    enqueue((sd_observation){.generation=generation,.kind=kind,
        .drive=drive,.rc=rc,.genuine=true,.path_validated=path_validated,.owned=true});
}
void native_sd_hotplug_freed(uint64_t generation,int rc)
{
    if(generation)enqueue((sd_observation){.generation=generation,.kind=SD_NOTIFY_FREE,
        .rc=rc,.genuine=true,.owned=true});
}
static void process_event(sd_observation event)
{
    if(!hot.core.bound){
        if(event.kind!=SD_MOUNT || event.rc || !event.path_validated || !event.drive)return;
        event.generation=1;
        const sd_adapters adapters={.context=&hot,.guard=guard,.validate_backing=backing_valid,
            .validate_quiescence=quiesce,.notify=notify};
        hot.result=sd_bind(&hot.core,&adapters,&hot.backing,&event);
        if(hot.result==SD_OK)atomic_store(&hot.generation,hot.core.generation);
    }else{
        if(hot.core.state!=SD_EJECTING && hot.core.state!=SD_INSERTING)return;
        /* An error from another volume or operation is not this card's error.
         * Filter before sd_observe, whose rc handling intentionally fails closed. */
        if(event.kind==SD_UNMOUNT && (hot.core.state!=SD_EJECTING || event.drive!=hot.core.drive))return;
        if(event.kind==SD_MOUNT && (hot.core.state!=SD_INSERTING || !event.path_validated))return;
        sd_result rc=sd_observe(&hot.core,event);
        if(rc==SD_OK || rc==SD_UNCERTAIN)hot.result=rc;
    }
    publish();
}
static void request_pending(void)
{
    /* One operation is in flight. Never replace its sequence with a queued
     * opposite request and later label the first completion as the second. */
    if(hot.core.bound && (hot.core.state==SD_EJECTING || hot.core.state==SD_INSERTING))return;
    int fd=open(SD_HOTPLUG_DIRECTORY "/sd-hotplug.request",O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
    if(fd<0)return;
    struct stat info;char data[96];
    long n=syscall(SYS_fstat,fd,&info) || !S_ISREG(info.st_mode)?-1:read(fd,data,sizeof data-1);
    close(fd);if(n<=0)return;data[n]=0;
    unsigned version,operation;unsigned long long sequence;char extra;
    if(sd_legacy_sscanf(data,"%u %llu %u %c",&version,&sequence,&operation,&extra)!=3 || version!=1 ||
       !sequence || sequence>0x7fffffffffffffffULL || operation>1 || sequence<=hot.seen_sequence)return;
    hot.seen_sequence=sequence;hot.request_sequence=sequence;
    hot.result=atomic_load(&hot.lost)?SD_GUARD_FAILED:
        sd_request_apply(&hot.core,(sd_request){sequence,(sd_operation)operation});
    if(hot.result==SD_PENDING){clock_gettime(CLOCK_MONOTONIC,&hot.deadline);hot.deadline.tv_sec+=300;}
    publish();
}
void native_sd_hotplug_poll(void)
{
    if(!native_sd_hotplug_enabled())return;
    if(!hot.worker)hot.worker=syscall(SYS_gettid);
    if(!guard(&hot))return;
    for(;;){
        pthread_mutex_lock(&hot.mutex);
        int available=hot.count!=0;sd_observation event={0};
        if(available){event=hot.events[hot.head];hot.head=(hot.head+1)%64;hot.count--;}
        int bound=hot.core.bound,lost=atomic_load(&hot.lost);
        if(bound && lost){
            if(hot.core.state==SD_EJECTING || hot.core.state==SD_INSERTING)
                hot.result=sd_expire(&hot.core,(sd_timeout){hot.core.generation});
            publish();
        }else if(bound && available){
            /* Completion and sticky overflow share this mutex: an overrun
             * cannot appear between its check and the completion observation. */
            process_event(event);
        }
        pthread_mutex_unlock(&hot.mutex);
        if(!available)break;
        /* Initial bind validates the backing under the RM mutex, so it must
         * remain outside the event lock (free callbacks take the reverse path). */
        if(!bound && !lost)process_event(event);
    }
    if(hot.core.bound && (hot.core.state==SD_EJECTING || hot.core.state==SD_INSERTING)){
        struct timespec now;clock_gettime(CLOCK_MONOTONIC,&now);
        if(atomic_load(&hot.lost) || now.tv_sec>hot.deadline.tv_sec ||
           (now.tv_sec==hot.deadline.tv_sec && now.tv_nsec>=hot.deadline.tv_nsec)){
            hot.result=sd_expire(&hot.core,(sd_timeout){hot.core.generation});publish();
        }
    }
    request_pending();
}
