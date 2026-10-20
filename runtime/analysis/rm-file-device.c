/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "rm-file-device.h"
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#define MIN_IMAGE_BYTES 0x400000U
#define BAD_ARG 0x80000001U
#define UNSUPPORTED 0x80000002U
#define SYSTEM_ERROR 0x80000004U
#define NO_MEDIA 0x80010002U
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t queue_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t queue_condition=PTHREAD_COND_INITIALIZER;
static void *pending[16];
static unsigned int queue_head,queue_count,stopping;
static pthread_t worker_thread;
static int worker_live;
static struct {
    struct full_imaging_io io;
    int fd,started,attempted,faults;
    pid_t pid;
    struct stat identity;
    char path[256];
    void *receiver;
    unsigned int subscriber;
    unsigned int image_bytes;
    unsigned int slot;
    unsigned long long hash,serial,queries,types,subscriptions,notifications;
} state={.fd=-1,.slot=1};
static struct {void *p;unsigned int owner,destination,bytes;unsigned long long serial;long sender;} leases[16];
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|(unsigned int)u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int n){p[0]=n;p[1]=n>>8;}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=n>>(8*i);}
static void event(const char *kind,const char *text){
    if(state.io.record){char tag[80];snprintf(tag,sizeof tag,"FULL_RM_FILE_%s",kind);state.io.record(tag,text);}
}
static int local_queue(unsigned int q){return q && (q&0x7fff) && !(q&0x70000000U) && q!=NATIVE_RM_FILE_SID;}
static int backing(void){
    struct stat now,path;unsigned char boot[512];
    if(getpid()!=state.pid || syscall(SYS_fstat,state.fd,&now) ||
       syscall(SYS_newfstatat,AT_FDCWD,state.path,&path,AT_SYMLINK_NOFOLLOW) || !S_ISREG(path.st_mode) ||
       now.st_dev!=state.identity.st_dev || now.st_ino!=state.identity.st_ino ||
       path.st_dev!=now.st_dev || path.st_ino!=now.st_ino || now.st_size!=state.image_bytes ||
       pread(state.fd,boot,sizeof boot,0)!=sizeof boot)return -1;
    unsigned int sectors=u16(boot+19);if(!sectors)sectors=u32(boot+32);
    return boot[510]==0x55 && boot[511]==0xaa && u16(boot+11)==512 &&
           sectors==state.image_bytes/512 && boot[13] && !(boot[13]&(boot[13]-1))?0:-1;
}
static int emit(unsigned int owner,unsigned int dst,unsigned int source,const unsigned char *data,unsigned int n,void *request,const char *kind){
    void *p=0;int rc=state.io.allocate(owner,&p,n,1);
    pthread_mutex_lock(&mutex);int slot=-1,alias=p && p==request;
    for(unsigned int i=0;i<16;i++){if(p && leases[i].p==p)alias=1;if(!leases[i].p && slot<0)slot=i;}
    if(rc || !p || slot<0 || alias || state.io.size(p)!=n){
        state.faults++;pthread_mutex_unlock(&mutex);
        if(p && !alias)state.io.release(owner,p);
        event("FAULT ","reply allocation/size/lease unavailable");return -1;
    }
    memcpy(p,data,n);state.io.set_source(p,source);
    unsigned long long serial=++state.serial;long tid=syscall(SYS_gettid);
    leases[slot].p=p;leases[slot].owner=owner;leases[slot].destination=dst;
    leases[slot].bytes=n;leases[slot].serial=serial;leases[slot].sender=tid;
    char raw[273],line[520];for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",data[i]);
    if(owner==dst)
        snprintf(line,sizeof line,"tid=%ld destination=%#x reply=%p lease=%llu bytes=%u raw=%s",tid,dst,p,serial,n,raw);
    else
        snprintf(line,sizeof line,"tid=%ld destination=%#x allocation_owner=%#x reply=%p lease=%llu bytes=%u raw=%s",tid,dst,owner,p,serial,n,raw);
    event(kind,line);pthread_mutex_unlock(&mutex);
    rc=state.io.send(dst,p);
    if(rc){
        pthread_mutex_lock(&mutex);int retained=leases[slot].p==p && leases[slot].serial==serial;
        if(retained)memset(&leases[slot],0,sizeof leases[slot]);
        state.faults++;pthread_mutex_unlock(&mutex);
        if(retained)state.io.release(owner,p);
        event("FAULT ","reply send failed");return -1;
    }
    return 0;
}
#ifdef NATIVE_RM_FILE_TEST
/* Host-only transport test; no unsolicited guest notification or card change. */
int native_rm_file_test_emit(unsigned int owner,unsigned int dst,const unsigned char *data,unsigned int n){
    return emit(owner,dst,owner,data,n,0,"TEST_OWNER_SEPARATION ");
}
#endif
static void dispatch(void *request,unsigned long arg){
    (void)arg;if(!request)return;
    unsigned int n=state.io.size(request),opcode=0,dst=0,payload=0,result=BAD_ARG,outbytes=0,notify=0;
    unsigned char reply[136]={0};const unsigned char *in=request;
    if(n>=24){
        memcpy(reply,in,24);opcode=u32(in);dst=u32(in+8);payload=u16(in+6);
        result=UNSUPPORTED;
        if(getpid()!=state.pid || backing())result=NO_MEDIA;
        else if(u16(in+4)!=1 || n!=24+payload)result=BAD_ARG;
        else if(opcode==9 && payload==112){
            memset(reply+24,0,112);put32(reply+24,1);
            for(unsigned int i=0;i<3;i++)put32(reply+28+i*36,i);
            /* The virtual card is one physical slot. Which logical RM carries it
               is a device-topology choice, not a capacity value: slot 1 = RM2 by
               default, slot 0 = RM1 when MENU_RM_FILE_SLOT=0. Media fields are
               reported on exactly one record either way. */
            unsigned char *r=reply+28+state.slot*36;put32(r+4,1);put32(r+8,2);put32(r+16,0x20);
            result=0;outbytes=112;state.queries++;
        } else if(opcode==2 && payload==8 && u32(in+24)==0x102){
            memcpy(reply+24,in+24,8);put32(reply+28,3);result=0;outbytes=8;state.types++;
        } else if(opcode==3 && payload==4 && (!u32(in+24) || local_queue(u32(in+24)))){
            state.subscriber=u32(in+24);memcpy(reply+24,in+24,4);result=0;outbytes=4;
            notify=state.subscriber;state.subscriptions++;
        }
        pthread_mutex_lock(&mutex);if(state.faults){result=SYSTEM_ERROR;outbytes=0;notify=0;}pthread_mutex_unlock(&mutex);
        put16(reply+6,outbytes);put32(reply+12,result);
        char line[320];snprintf(line,sizeof line,"tid=%ld request=%p bytes=%u opcode=%u payload=%u reply_queue=%#x result=%#x backing_bytes=%u queries=%llu types=%llu subscriptions=%llu",
            syscall(SYS_gettid),request,n,opcode,payload,dst,result,state.image_bytes,state.queries,state.types,state.subscriptions);
        event("REQUEST ",line);
        if(local_queue(dst) && !emit(dst,dst,NATIVE_RM_FILE_SID,reply,24+outbytes,request,"REPLY_QUEUED ") && notify){
            unsigned char initial[7]={2,0,0,2,0,2,0};
            if(!backing() && !emit(notify,notify,notify,initial,7,request,"INITIAL_QUEUED "))state.notifications++;
        }
    }
    unsigned long identity=(unsigned long)request;int freed=state.io.release(NATIVE_RM_FILE_SID,request);
    pthread_mutex_lock(&mutex);if(freed)state.faults++;pthread_mutex_unlock(&mutex);
    char line[200];snprintf(line,sizeof line,"tid=%ld request=%#lx opcode=%u result=%#x free_rc=%d notifications=%llu",syscall(SYS_gettid),identity,opcode,result,freed,state.notifications);
    event(freed?"FAULT ":"REQUEST_FREE ",line);
}
static void *worker(void *unused){
    (void)unused;
    for(;;){
        pthread_mutex_lock(&queue_mutex);
        while(!queue_count && !stopping)pthread_cond_wait(&queue_condition,&queue_mutex);
        if(!queue_count && stopping){pthread_mutex_unlock(&queue_mutex);return 0;}
        void *p=pending[queue_head];queue_head=(queue_head+1)%16;queue_count--;
        pthread_mutex_unlock(&queue_mutex);dispatch(p,0);
    }
}
static void receive(void *request,unsigned long arg){
    (void)arg;if(!request)return;
    pthread_mutex_lock(&queue_mutex);
    if(!stopping && queue_count<16){
        pending[(queue_head+queue_count)%16]=request;queue_count++;
        pthread_cond_signal(&queue_condition);pthread_mutex_unlock(&queue_mutex);return;
    }
    pthread_mutex_unlock(&queue_mutex);
    int rc=state.io.release(NATIVE_RM_FILE_SID,request);
    pthread_mutex_lock(&mutex);state.faults++;pthread_mutex_unlock(&mutex);
    char line[100];snprintf(line,sizeof line,"worker queue unavailable request_free_rc=%d",rc);event("FAULT ",line);
}
static void stop_worker(void){
    if(!worker_live)return;
    pthread_mutex_lock(&queue_mutex);stopping=1;pthread_cond_signal(&queue_condition);pthread_mutex_unlock(&queue_mutex);
    pthread_join(worker_thread,0);worker_live=0;
}
int native_rm_file_start(const char *path,const char *claim,const struct full_imaging_io *io,
                        int (*reg)(unsigned int,void **,void *,unsigned long),
                        int (*unreg)(unsigned int,void *),int (*statq)(unsigned int,void *)){
    pid_t pid=getpid(),owner=__atomic_load_n(&state.pid,__ATOMIC_ACQUIRE);
    if(!owner){pid_t empty=0;__atomic_compare_exchange_n(&state.pid,&empty,pid,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);owner=__atomic_load_n(&state.pid,__ATOMIC_ACQUIRE);}
    if(owner!=pid)return -1;
    pthread_mutex_lock(&mutex);
    if(state.attempted){int rc=state.started?0:-1;pthread_mutex_unlock(&mutex);return rc;}
    state.attempted=1;if(io)state.io=*io;pthread_mutex_unlock(&mutex);
    const char *image_env=getenv("MENU_RM_FILE_IMAGE"),*claim_env=getenv("MENU_RM_FILE_CLAIM");
    const char *slot_env=getenv("MENU_RM_FILE_SLOT");
    state.slot=1;
    if(slot_env){
        if(!strcmp(slot_env,"0"))state.slot=0;
        else if(!strcmp(slot_env,"1"))state.slot=1;
        else return -1;
    }
    if(image_env)path=image_env;
    if(claim_env)claim=claim_env;
    if(!path || !claim || strlen(path)>=sizeof state.path || !io || !io->size || !io->allocate ||
       !io->release || !io->send || !io->set_source || !reg || !unreg || !statq)return -1;
    strcpy(state.path,path);
    unsigned int stats[4]={0};int claimfd=open(claim,O_CREAT|O_EXCL|O_NOFOLLOW|O_WRONLY,0600);
    if(claimfd<0){event("FAILED ","exclusive claim unavailable");return -1;}close(claimfd);
    if(statq(NATIVE_RM_FILE_SID,stats) || stats[0] || stats[1] || stats[2] || stats[3]){
        event("FAILED ","existing RM queue owner or pending data");return -1;
    }
    state.fd=open(path,O_RDWR|O_NOFOLLOW);
    if(state.fd<0 || syscall(SYS_fstat,state.fd,&state.identity) || !S_ISREG(state.identity.st_mode) ||
       state.identity.st_size<MIN_IMAGE_BYTES || state.identity.st_size>0x80000000LL || state.identity.st_size%4096)goto fail;
    state.image_bytes=(unsigned int)state.identity.st_size;
    if(backing())goto fail;
    unsigned char bytes[4096];state.hash=0xcbf29ce484222325ULL;
    for(unsigned int offset=0;offset<state.image_bytes;offset+=sizeof bytes){
        if(pread(state.fd,bytes,sizeof bytes,offset)!=sizeof bytes)goto fail;
        for(unsigned int i=0;i<sizeof bytes;i++)state.hash=(state.hash^bytes[i])*0x100000001b3ULL;
    }
    if(backing())goto fail;
    if(pthread_create(&worker_thread,0,worker,0)){event("FAILED ","worker creation failed");goto fail;}
    worker_live=1;
    int rc=reg(NATIVE_RM_FILE_SID,&state.receiver,(void *)receive,0);
    if(rc){event("FAILED ","original callback registration failed");goto fail;}
    memset(stats,0,sizeof stats);
    if(statq(NATIVE_RM_FILE_SID,stats) || stats[1]!=1 || stats[2] || stats[3]){
        int undone=unreg(NATIVE_RM_FILE_SID,state.receiver);char cleanup[180];
        snprintf(cleanup,sizeof cleanup,"unregister_rc=%d receiver=%p worker_retained=%u backing_retained=%u",undone,state.receiver,undone!=0,undone!=0);
        event(undone?"CLEANUP_REQUIRED ":"ROLLBACK ",cleanup);
        if(undone){pthread_mutex_lock(&mutex);state.faults++;pthread_mutex_unlock(&mutex);return -1;}
        event("FAILED ","real callback stat verification failed");goto fail;
    }
    pthread_mutex_lock(&mutex);state.started=1;pthread_mutex_unlock(&mutex);char line[260];
    snprintf(line,sizeof line,"pid=%ld receiver=%p callback_count=%u image_bytes=%u initial_fnv64=%016llx virtual_rm=2 virtual_mmc_selector=0x20 global_dummy_nand_unsupported=1 original_cp_task=0",
             (long)state.pid,state.receiver,stats[1],state.image_bytes,state.hash);event("STARTED ",line);return 0;
fail:
    stop_worker();
    if(state.fd>=0){close(state.fd);state.fd=-1;}event("FAILED ","backing or original queue startup validation failed");return -1;
}
int native_rm_file_release(unsigned int dst,void *p,int (*release)(unsigned int,void *),
                           void (*record)(const char *,const char *),int *rc){
    if(!p || !release || !rc)return 0;
    if(state.pid && getpid()!=state.pid){*rc=-1021;return 1;}
    pthread_mutex_lock(&mutex);
    for(unsigned int i=0;i<16;i++)if(leases[i].p==p){
        unsigned int expected=leases[i].owner,bytes=leases[i].bytes;unsigned long long serial=leases[i].serial;long sender=leases[i].sender;
        *rc=dst==expected?release(dst,p):-1021;
        if(!*rc)memset(&leases[i],0,sizeof leases[i]);else state.faults++;
        char line[260];snprintf(line,sizeof line,"tid=%ld sender=%ld destination=%#x expected=%#x reply=%p lease=%llu bytes=%u rc=%d",
                               syscall(SYS_gettid),sender,dst,expected,p,serial,bytes,*rc);
        if(record)record(*rc?"FULL_RM_FILE_FAULT ":"FULL_RM_FILE_NATIVE_REPLY_FREE ",line);
        pthread_mutex_unlock(&mutex);return 1;
    }
    pthread_mutex_unlock(&mutex);return 0;
}
