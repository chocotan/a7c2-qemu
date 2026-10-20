/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "dmm-unit-config.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static struct {unsigned int loaded,unit,extent,bytes,faults;unsigned long long queries,serial;} state;
static struct lease {void *p;unsigned int dst;long tid;unsigned long long serial;} leases[8];
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|(unsigned int)u16(p+2)<<16;}
static void put32(unsigned char *p,unsigned int x){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(x>>(8*i));}
static int config_bind(const unsigned char *p,unsigned int n){
    if(!p || n!=43508)return -1;
    unsigned long long digest=0xcbf29ce484222325ULL;
    for(unsigned int i=0;i<n;i++)digest=(digest^p[i])*0x100000001b3ULL;
    if(digest!=0xb17ed6044f6bf2deULL || u32(p+0x96a0)!=0x50b58 || u32(p+0x96a4) ||
       u32(p+0x96ac)!=0xffffffff || u32(p+0x96a8)!=u32(p+0x5774) || !u32(p+0x5778))return -1;
    state.unit=u32(p+0x96a0);state.extent=u32(p+0x96a8);state.bytes=u32(p+0x5778);state.loaded=1;return 0;
}
int native_dmm_unit_bind(const unsigned char *p,unsigned int n){
    pthread_mutex_lock(&mutex);int rc=config_bind(p,n);pthread_mutex_unlock(&mutex);return rc;
}
static int load(void){
    if(state.loaded)return 0;
    static unsigned char data[43508];FILE *f=fopen("/cp/DmmCfg.bin","rb");if(!f)return -1;
    unsigned int n=(unsigned int)fread(data,1,sizeof data,f);int extra=fgetc(f),error=ferror(f);fclose(f);
    return extra==EOF && !error?config_bind(data,n):-1;
}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[80];snprintf(tag,sizeof tag,"FULL_DMM_UNIT_%s",kind);io->record(tag,text);}
}
int native_dmm_unit_dispatch(unsigned int id,void *request,const struct full_imaging_io *io,int enabled,int *rc){
    if(enabled!=1 || id!=NATIVE_DMM_UNIT_SID || !request || !io || !io->size || !rc)return 0;
    unsigned int n=io->size(request);const unsigned char *in=request;
    if(n<2 || u16(in)!=0x18)return 0;
    if(n!=40 || u16(in+2) || u32(in+4)!=0x50b58 || !io->source || !io->allocate ||
       !io->release || !io->send || !io->set_source){*rc=-1021;return 1;}
    for(unsigned int i=8;i<40;i++)if(i!=20 && i!=21 && in[i]){*rc=-1021;return 1;}
    unsigned int dst=io->source(request),token=u16(in+20);
    if(dst>>28!=8 || !(dst&0xfffffff)){*rc=-1021;return 1;}
    pthread_mutex_lock(&mutex);int valid=!state.faults && !load();pthread_mutex_unlock(&mutex);
    if(!valid){event(io,"UNSUPPORTED ","original-config-identity-or-table-not-available");*rc=-1021;return 1;}
    void *reply=0;*rc=io->allocate(dst,&reply,40,1);
    pthread_mutex_lock(&mutex);struct lease *slot=0;int alias=reply && reply==request;
    for(unsigned int i=0;i<8;i++){
        if(reply && leases[i].p==reply)alias=1;
        if(!leases[i].p && !slot)slot=&leases[i];
    }
    if(alias){state.faults++;event(io,"FAULT ","allocator-live-alias");pthread_mutex_unlock(&mutex);*rc=-1021;return 1;}
    if(*rc || !reply || !slot || state.faults || io->size(reply)!=40){
        if(reply && io->release(dst,reply)){state.faults++;event(io,"FAULT ","failed-allocation-cleanup");}
        if(!*rc)*rc=-1021;
        pthread_mutex_unlock(&mutex);return 1;
    }
    long tid=syscall(SYS_gettid);char raw[81],line[560];
    for(unsigned int i=0;i<40;i++)snprintf(raw+2*i,3,"%02x",in[i]);
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x bytes=40 raw=%s",tid,dst,id,raw);event(io,"REQUEST ",line);
    memset(reply,0,40);unsigned char *out=reply;out[0]=0x18;out[1]=0x80;out[6]=(unsigned char)token;out[7]=(unsigned char)(token>>8);put32(out+16,state.bytes);
    io->set_source(reply,NATIVE_DMM_UNIT_SID);unsigned long long serial=++state.serial;
    *slot=(struct lease){reply,dst,tid,serial};*rc=io->send(dst,reply);
    if(*rc){memset(slot,0,sizeof *slot);if(io->release(dst,reply)){state.faults++;event(io,"FAULT ","failed-send-cleanup");}pthread_mutex_unlock(&mutex);return 1;}
    state.queries++;
    for(unsigned int i=0;i<40;i++)snprintf(raw+2*i,3,"%02x",out[i]);
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x reply=%p lease=%llu bytes=40 raw=%s",tid,id,dst,reply,serial,raw);event(io,"REPLY_QUEUED ",line);
    int freed=io->release(id,request);if(freed)state.faults++;
    snprintf(line,sizeof line,"tid=%ld unit=%#x extent=%#x size=%#x config_bytes=43508 config_fnv64=b17ed6044f6bf2de unit_record=0x96a0 extent_record=0x576c queries=%llu reply=%p lease=%llu request_free_rc=%d allocated_bytes=0 camera_startup_verified=0 pixels_consumed=0",tid,state.unit,state.extent,state.bytes,state.queries,reply,serial,freed);
    event(io,freed?"FAULT ":"COMMIT ",line);pthread_mutex_unlock(&mutex);*rc=0;return 1;
}
int native_dmm_unit_release(unsigned int dst,void *p,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *rc){
    if(!p || !release || !rc)return 0;
    pthread_mutex_lock(&mutex);int found=0;
    for(unsigned int i=0;i<8;i++)if(leases[i].p==p){
        struct lease lease=leases[i];found=1;*rc=dst==lease.dst?release(dst,p):-1021;
        if(*rc)state.faults++;else memset(&leases[i],0,sizeof leases[i]);
        if(record){char line[300];snprintf(line,sizeof line,"tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p lease=%llu bytes=40 rc=%d",syscall(SYS_gettid),lease.tid,syscall(SYS_gettid)==lease.tid,dst,lease.dst,p,lease.serial,*rc);record(*rc?"FULL_DMM_UNIT_FAULT ":"FULL_DMM_UNIT_NATIVE_REPLY_FREE ",line);}
        break;
    }
    pthread_mutex_unlock(&mutex);return found;
}
