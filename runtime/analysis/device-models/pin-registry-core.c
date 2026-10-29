/* SPDX-License-Identifier: MIT */
/* Shared Get-only transport. Each explicit owner has independent state/leases. */
#define _GNU_SOURCE
#include "pin-registry-core.h"
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
/* Both pin owners share the allocator's address space. Serialize real free
 * and new lease publication across owners, not only within one registry. */
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put32(unsigned char *p,unsigned int value){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(value>>(8*i));}
static void hex(char *out,const unsigned char *p,unsigned int n){
    for(unsigned int i=0;i<n;i++)snprintf(out+2*i,3,"%02x",p[i]);
    out[2*n]=0;
}
static void event(struct pin_registry_owner *owner,const struct full_imaging_io *io,const char *kind,const char *text){
    if(io && io->record){char tag[64];snprintf(tag,sizeof tag,"FULL_%s_%s",owner->name,kind);io->record(tag,text);}
}
static int reject(struct pin_registry_owner *owner,const struct full_imaging_io *io,int *result,const char *reason){
    event(owner,io,"UNSUPPORTED ",reason);*result=-1021;return 1;
}
static void initialize(struct pin_registry_owner *owner,const struct full_imaging_io *io){
    struct full_vef_snapshot *state=&owner->state;
    if(state->initialized)return;
    for(unsigned int i=0;i<owner->count;i++){
        struct full_vef_pin *pin=&state->pins[i];
        memcpy(pin->self,owner->keys[i],3*sizeof(unsigned int));pin->self[3]=owner->source;
        pin->peer[0]=pin->peer[1]=0xff;pin->state=1;
        char line[200];snprintf(line,sizeof line,"slot=%u type=%u dir=%u index=%u owner=%#x state=%u peer_type=%u peer_dir=%u peer_index=%u peer_owner=%u ",
            i,pin->self[0],pin->self[1],pin->self[2],pin->self[3],pin->state,pin->peer[0],pin->peer[1],pin->peer[2],pin->peer[3]);
        event(owner,io,"PIN_CREATED ",line);
    }
    state->initialized=1;state->registry_objects=owner->count;state->owner_sid=owner->source;
}
static int cleanup(struct pin_registry_owner *owner,const struct full_imaging_io *io,unsigned int dst,void *p){
    int rc=io->release(dst,p);if(rc){owner->state.faults++;owner->state.retained_reply=p;}
    char line[160];snprintf(line,sizeof line,"tid=%ld destination=%#x pointer=%p rc=%d",syscall(SYS_gettid),dst,p,rc);
    event(owner,io,rc?"FAULT ":"CLEANUP_FREE ",line);return rc;
}
int pin_registry_dispatch(struct pin_registry_owner *owner,unsigned int destination,void *request,
                          const struct full_imaging_io *io,int enabled,int *result){
    if(destination!=owner->source || enabled!=1 || !io || !result)return 0;
    if(owner->count>FULL_PIN_REGISTRY_CAPACITY)return reject(owner,io,result,"registry-capacity");
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->set_source || !io->send)
        return reject(owner,io,result,"missing-transport");
    const unsigned char *in=request;unsigned int bytes=io->size(request);
    if(bytes!=48 || u32(in+4)!=0xa0a0a0a0 || u16(in+8)!=1 || u16(in+10)!=48 ||
       u32(in+12)!=24 || u32(in+16)!=48 || u16(in+24)!=0x1000 || u16(in+26)!=0 ||
       u16(in+28)!=24 || u16(in+30)!=2)
        return reject(owner,io,result,"only-48B-PinGet-supported-no-Connect");
    unsigned int dst=u32(in),source=io->source(request),keys[3]={u32(in+32),u32(in+36),u32(in+40)};
    if((source>>28)!=8 || !(source&0x0fffffff) || (dst>>28)!=8 || !(dst&0x0fffffff))
        return reject(owner,io,result,"nonlocal-or-zero-reply-subset");
    char raw[113],line[640];hex(raw,in,48);
    snprintf(line,sizeof line,"tid=%ld destination=%#x source=%#x reply_destination=%#x bytes=48 raw=%s",
             syscall(SYS_gettid),destination,source,dst,raw);event(owner,io,"REQUEST ",line);
    pthread_mutex_lock(&mutex);initialize(owner,io);struct full_vef_snapshot *state=&owner->state;
    int index=-1;
    unsigned int mask=(owner->full_key_match || owner->type_only)?0xffffffffU:255U;
    for(unsigned int i=0;i<owner->count;i++)if(state->pins[i].self[0]==(keys[0]&mask) &&
        (owner->type_only || (state->pins[i].self[1]==(keys[1]&mask) && state->pins[i].self[2]==(keys[2]&mask)))){index=(int)i;break;}
    if(state->faults || state->pending || index<0){
        pthread_mutex_unlock(&mutex);return reject(owner,io,result,index<0?"missing-pin-outside-supported-subset":"fault-or-concurrent-call");
    }
    state->pending=1;pthread_mutex_unlock(&mutex);
    void *reply=0;int rc=io->allocate(dst,&reply,56,1);
    pthread_mutex_lock(&mutex);struct pin_registry_lease *slot=0;int duplicate=reply && reply==request;
    for(unsigned int i=0;i<8;i++){
        if(reply && owner->replies[i].pointer==reply)duplicate=1;
        if(!owner->replies[i].pointer && !slot)slot=&owner->replies[i];
    }
    if(duplicate){state->faults++;state->pending=0;event(owner,io,"FAULT ","allocator-returned-live-message");
        pthread_mutex_unlock(&mutex);return reject(owner,io,result,"duplicate-ownership");}
    if(rc || !reply || !slot || state->faults){
        if(reply)cleanup(owner,io,dst,reply);
        state->pending=0;pthread_mutex_unlock(&mutex);*result=rc?rc:-1021;return 1;
    }
    struct full_vef_snapshot before=*state;
    const struct full_vef_pin *pin=&state->pins[index];unsigned int pin_state=pin->state,pin_owner=pin->self[3];state->queries++;
    unsigned char *out=reply;memset(out,0,56);put32(out,owner->reply_sid);put32(out+4,0xa0a0a0a0);
    out[8]=1;out[10]=56;put32(out+12,24);put32(out+16,56);
    out[25]=0x10;out[27]=0x80;out[28]=32;out[30]=2;
    for(unsigned int i=0;i<3;i++)put32(out+32+4*i,owner->type_only?pin->self[i]:keys[i]);
    put32(out+44,pin_state);put32(out+48,pin_owner);put32(out+52,0);
    io->set_source(reply,owner->source);unsigned long long serial=++state->next_lease;
    /* Legacy masked lookups echo aliases; only canonical returned keys prove a pin. */
    unsigned int pin_index=FULL_PIN_REGISTRY_CAPACITY;
    if(u32(out+32)==pin->self[0] && u32(out+36)==pin->self[1] && u32(out+40)==pin->self[2] && u32(out+48)==pin->self[3])pin_index=(unsigned int)index;
    *slot=(struct pin_registry_lease){reply,dst,serial,syscall(SYS_gettid),pin_index};state->live_replies++;
    rc=io->send(dst,reply);
    if(rc){*state=before;state->pending=0;memset(slot,0,sizeof *slot);cleanup(owner,io,dst,reply);
        event(owner,io,"TRANSPORT_FAILURE ","send-failed-caller-owned-rollback");
        pthread_mutex_unlock(&mutex);*result=rc;return 1;}
    state->queued++;hex(raw,out,56);
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x reply=%p lease=%llu bytes=56 raw=%s",
             syscall(SYS_gettid),owner->source,dst,reply,serial,raw);event(owner,io,"REPLY_QUEUED ",line);
    int freed=io->release(owner->source,request);
    if(freed){state->faults++;state->retained_request=request;}else state->request_freed++;
    state->pending=0;
    snprintf(line,sizeof line,"tid=%ld slot=%d type=%u dir=%u index=%u pin_state=%u owner=%#x status=0 queries=%llu reply=%p lease=%llu request_free_rc=%d connect_performed=0 pixels_consumed=0 camera_startup_verified=0",
             syscall(SYS_gettid),index,keys[0],keys[1],keys[2],pin_state,pin_owner,state->queries,reply,serial,freed);
    event(owner,io,freed?"FAULT ":"COMMIT ",line);pthread_mutex_unlock(&mutex);*result=0;return 1;
}
int pin_registry_release(struct pin_registry_owner *owner,unsigned int destination,void *reply,
                          int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *result){
    if(!reply || !release || !result)return 0;
    pthread_mutex_lock(&mutex);struct pin_registry_lease found={0};struct full_vef_snapshot *state=&owner->state;
    for(unsigned int i=0;i<8;i++)if(owner->replies[i].pointer==reply){
        found=owner->replies[i];*result=destination==found.destination?release(destination,reply):-1021;
        if(*result)state->faults++;
        else{memset(&owner->replies[i],0,sizeof owner->replies[i]);state->live_replies--;state->native_freed++;
            if(found.sender==syscall(SYS_gettid)){
                state->waiter_freed++;
                if(found.pin_index<owner->count && found.pin_index<FULL_PIN_REGISTRY_CAPACITY)owner->retired_get[found.pin_index]=1;
            }}
        break;
    }
    if(found.pointer && record){char tag[64],line[320];long tid=syscall(SYS_gettid);
        snprintf(line,sizeof line,"tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p lease=%llu bytes=56 rc=%d",
                 tid,found.sender,tid==found.sender,destination,found.destination,reply,found.serial,*result);
        snprintf(tag,sizeof tag,"FULL_%s_%s",owner->name,*result?"FAULT ":"NATIVE_REPLY_FREE ");record(tag,line);}
    pthread_mutex_unlock(&mutex);return found.pointer!=0;
}
void pin_registry_snapshot(struct pin_registry_owner *owner,struct full_vef_snapshot *out){
    pthread_mutex_lock(&mutex);*out=owner->state;pthread_mutex_unlock(&mutex);
}
int pin_registry_key_get_retired(struct pin_registry_owner *owner,const unsigned int key[4]){
    if(!owner || !key)return 0;
    pthread_mutex_lock(&mutex);int retired=0;
    if(owner->count<=FULL_PIN_REGISTRY_CAPACITY && owner->state.initialized && !owner->state.faults &&
       owner->state.owner_sid==owner->source && owner->state.registry_objects==owner->count && key[3]==owner->source){
        for(unsigned int i=0;i<owner->count;i++)if(!memcmp(owner->state.pins[i].self,key,4*sizeof *key)){
            retired=owner->retired_get[i]!=0;break;
        }
    }
    pthread_mutex_unlock(&mutex);return retired;
}
static struct full_vef_pin *existing_pin(struct pin_registry_owner *owner,const unsigned int *key){
    if(!owner->state.initialized || owner->state.faults || key[3]!=owner->source)return 0;
    for(unsigned int i=0;i<owner->count;i++)if(!memcmp(owner->state.pins[i].self,key,4*sizeof *key))return &owner->state.pins[i];
    return 0;
}
int pin_registry_connect_step(struct pin_registry_owner *source,struct pin_registry_owner *peer,
                              const unsigned int *s,const unsigned int *p,unsigned int step){
    if(!source || !peer || !s || !p || source==peer)return -1;
    pthread_mutex_lock(&mutex);struct full_vef_pin *a=existing_pin(source,s),*b=existing_pin(peer,p);int rc=-1;
    if(a && b){
        if(step==1 && a->state==1 && b->state==1 && !source->state.pending && !peer->state.pending &&
           s[0]==p[0] && ((s[1]==2 && p[1]==1) ||
            (s[0]==1 && s[1]==3 && s[2]==0 && s[3]==0x90590818u &&
             p[1]==3 && p[2]==0 && p[3]==0x9080003bu))){
            memcpy(a->peer,p,4*sizeof *p);a->state=2;source->state.pending=1;rc=0;
        }else if(step==2 && a->state==2 && b->state==1 && source->state.pending && !memcmp(a->peer,p,4*sizeof *p)){
            memcpy(b->peer,s,4*sizeof *s);b->state=0;rc=0;
        }else if(step==3 && a->state==2 && b->state==0 && source->state.pending &&
                 !memcmp(a->peer,p,4*sizeof *p) && !memcmp(b->peer,s,4*sizeof *s)){
            a->state=0;rc=0;
        }else if(step==4 && a->state==0 && b->state==0 && source->state.pending &&
                 !memcmp(a->peer,p,4*sizeof *p) && !memcmp(b->peer,s,4*sizeof *s)){
            source->state.pending=0;rc=0;
        }
    }
    pthread_mutex_unlock(&mutex);return rc;
}
void pin_registry_connect_fault(struct pin_registry_owner *source,struct pin_registry_owner *peer){
    pthread_mutex_lock(&mutex);source->state.faults++;peer->state.faults++;pthread_mutex_unlock(&mutex);
}
#ifdef FULL_VEF_TEST
void pin_registry_test_reset(struct pin_registry_owner *owner){
    pthread_mutex_lock(&mutex);owner->state=(struct full_vef_snapshot){0};memset(owner->replies,0,sizeof owner->replies);
    memset(owner->retired_get,0,sizeof owner->retired_get);pthread_mutex_unlock(&mutex);
}
void pin_registry_test_set_state(struct pin_registry_owner *owner,unsigned int i,unsigned int value){
    pthread_mutex_lock(&mutex);initialize(owner,0);if(i<owner->count)owner->state.pins[i].state=value;pthread_mutex_unlock(&mutex);
}
#endif
