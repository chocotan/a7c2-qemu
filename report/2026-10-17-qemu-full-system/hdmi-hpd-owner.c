/* SPDX-License-Identifier: MIT */
#include "hdmi-hpd-owner.h"
#include <string.h>
#include <unistd.h>

static int lock_owner(struct hdmi_hpd_owner *o){
    if(!o || !o->state.initialized || o->pid!=(long)getpid())return -1;
    return pthread_mutex_lock(&o->mutex)?-1:0;
}
static int unlock_owner(struct hdmi_hpd_owner *o,int rc){pthread_mutex_unlock(&o->mutex);return rc;}
static int overlaps(const void *a,size_t alen,const void *b,size_t blen){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<=y ? y-x<alen : x-y<blen;
}
static int aliases_owner(const struct hdmi_hpd_owner *o,const void *p,size_t n){
    return overlaps(o,sizeof *o,p,n);
}
static struct hdmi_hpd_client *client_at(struct hdmi_hpd_owner *o,unsigned int id){
    if(!id || id>o->state.clients_ever_opened || !o->state.clients[id-1].open)return 0;
    return &o->state.clients[id-1];
}
static struct hdmi_hpd_event *event_at(struct hdmi_hpd_owner *o,unsigned int id,uint64_t lease){
    for(unsigned int i=0;i<HDMI_HPD_EVENTS;i++)
        if(o->events[i].live && o->events[i].client==id && o->events[i].lease==lease)return &o->events[i];
    return 0;
}
static struct hdmi_hpd_event *first_event(struct hdmi_hpd_owner *o,unsigned int id){
    struct hdmi_hpd_event *first=0;
    for(unsigned int i=0;i<HDMI_HPD_EVENTS;i++)
        if(o->events[i].live && o->events[i].client==id && (!first || o->events[i].lease<first->lease))first=&o->events[i];
    return first;
}
static void put32(unsigned char *p,unsigned int value){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(value>>(8*i));}
static int queue_event(struct hdmi_hpd_owner *o,unsigned int id,unsigned int index,unsigned int status,unsigned int data,uint64_t *lease){
    if(o->state.next_lease==UINT64_MAX)return -1;
    /* A submitted config owns one remaining lease credit. Another client's
     * HPD replay cannot consume its last possible completion identifier. */
    if(index!=7 && o->state.config.job_live && o->state.config.descriptor_live &&
       o->state.next_lease==UINT64_MAX-1)return -1;
    struct hdmi_hpd_event *e=0;
    for(unsigned int i=0;i<HDMI_HPD_EVENTS;i++)if(!o->events[i].live){e=&o->events[i];break;}
    if(!e)return -1;
    *e=(struct hdmi_hpd_event){.lease=++o->state.next_lease,.client=id,.live=1};
    put32(e->wire,index);put32(e->wire+4,status);put32(e->wire+8,data);
    o->state.live_events++;o->state.queued++;*lease=e->lease;return 0;
}
int hdmi_hpd_init_unplugged(struct hdmi_hpd_owner *o,int enabled){
    if(!o || enabled!=1 || o->state.initialized)return -1;
    if(pthread_mutex_init(&o->mutex,0))return -1;
    memset(&o->state,0,sizeof o->state);memset(o->events,0,sizeof o->events);
    o->pid=(long)getpid();o->state.initialized=1;o->state.hpd=0;return 0;
}
int hdmi_hpd_open(struct hdmi_hpd_owner *o,unsigned int sid,unsigned int *id){
    if(!o || !id || aliases_owner(o,id,sizeof *id) ||
       sid<0x909a07f6u || sid>0x909a07f8u || lock_owner(o))return -1;
    if(o->state.clients_ever_opened==HDMI_HPD_CLIENTS)return unlock_owner(o,-1);
    for(unsigned int i=0;i<o->state.clients_ever_opened;i++)
        if(o->state.clients[i].open && o->state.clients[i].sid==sid)return unlock_owner(o,-1);
    unsigned int slot=o->state.clients_ever_opened++;
    o->state.clients[slot]=(struct hdmi_hpd_client){.sid=sid,.open=1};
    o->state.open_clients++;*id=slot+1;return unlock_owner(o,0);
}
int hdmi_hpd_set_mask(struct hdmi_hpd_owner *o,unsigned int id,unsigned int mask){
    if((mask!=HDMI_HPD_MASK_ON && mask!=HDMI_HPD_MASK_OFF) || lock_owner(o))return -1;
    struct hdmi_hpd_client *c=client_at(o,id);if(!c)return unlock_owner(o,-1);
    c->mask=mask;return unlock_owner(o,0);
}
int hdmi_hpd_set_level(struct hdmi_hpd_owner *o,unsigned int level){
    if(level>1 || lock_owner(o))return -1;
    if(o->state.config.job_live || o->state.config.descriptor_live)return unlock_owner(o,-1);
    if(o->state.level_updates==UINT32_MAX)return unlock_owner(o,-1);
    o->state.hpd=level;o->state.level_updates++;return unlock_owner(o,0);
}
int hdmi_hpd_replay(struct hdmi_hpd_owner *o,unsigned int id,uint64_t *lease){
    if(!o || !lease || aliases_owner(o,lease,sizeof *lease) || lock_owner(o))return -1;
    struct hdmi_hpd_client *c=client_at(o,id);if(!c)return unlock_owner(o,-1);
    if(!(c->mask&2))return unlock_owner(o,1);
    /* CP 48898c invokes callback with {event_index, status, cached_value}. */
    int rc=queue_event(o,id,1,0,o->state.hpd,lease);return unlock_owner(o,rc);
}
int hdmi_hpd_read(struct hdmi_hpd_owner *o,unsigned int id,uint64_t lease,unsigned char out[12]){
    if(!o || !out || aliases_owner(o,out,HDMI_HPD_EVENT_BYTES) || lock_owner(o))return -1;
    struct hdmi_hpd_event *e=event_at(o,id,lease);
    if(!client_at(o,id) || !e || e!=first_event(o,id))return unlock_owner(o,-1);
    memcpy(out,e->wire,12);e->read=1;o->state.reads++;return unlock_owner(o,0);
}
int hdmi_hpd_consume(struct hdmi_hpd_owner *o,unsigned int id,uint64_t lease,const unsigned char received[12]){
    if(!received || lock_owner(o))return -1;
    struct hdmi_hpd_event *e=event_at(o,id,lease);
    if(!client_at(o,id) || !e || e!=first_event(o,id) || !e->read || memcmp(received,e->wire,12))return unlock_owner(o,-1);
    memset(e,0,sizeof *e);o->state.live_events--;o->state.consumed++;return unlock_owner(o,0);
}
int hdmi_hpd_dequeue(struct hdmi_hpd_owner *o,unsigned int id,unsigned char *out,
                     unsigned int capacity,uint64_t *lease){
    if(!o || !out || !lease || aliases_owner(o,out,HDMI_HPD_EVENT_BYTES) ||
       aliases_owner(o,lease,sizeof *lease) ||
       overlaps(out,HDMI_HPD_EVENT_BYTES,lease,sizeof *lease) || lock_owner(o))return -1;
    if(!client_at(o,id))return unlock_owner(o,-1);
    struct hdmi_hpd_event *e=first_event(o,id);
    if(!e)return unlock_owner(o,-11);
    if(capacity<HDMI_HPD_EVENT_BYTES)return unlock_owner(o,-90);
    memcpy(out,e->wire,HDMI_HPD_EVENT_BYTES);*lease=e->lease;
    memset(e,0,sizeof *e);o->state.live_events--;o->state.reads++;o->state.consumed++;
    return unlock_owner(o,0);
}
int hdmi_hpd_close(struct hdmi_hpd_owner *o,unsigned int id){
    if(lock_owner(o))return -1;
    struct hdmi_hpd_client *c=client_at(o,id);if(!c)return unlock_owner(o,-1);
    if(o->state.config.owner_client==id && (o->state.config.job_live || o->state.config.descriptor_live))return unlock_owner(o,-1);
    for(unsigned int i=0;i<HDMI_HPD_EVENTS;i++)
        if(o->events[i].live && o->events[i].client==id)return unlock_owner(o,-1);
    c->open=0;o->state.open_clients--;return unlock_owner(o,0);
}
int hdmi_hpd_snapshot(struct hdmi_hpd_owner *o,struct hdmi_hpd_snapshot *out){
    if(!o || !out || aliases_owner(o,out,sizeof *out) || lock_owner(o))return -1;
    *out=o->state;return unlock_owner(o,0);
}
static int config_cold(const struct hdmi_hpd_owner *o){
    const struct hdmi_cold_config *s=&o->state.config;
    return s->owner_client && s->current_mode==0 && s->target_mode==0 && !s->active && !s->dirty &&
           !o->state.hpd && !o->state.level_updates;
}
int hdmi_config_bind_fresh(struct hdmi_hpd_owner *o,unsigned int id){
    if(lock_owner(o))return -1;
    struct hdmi_cold_config *s=&o->state.config;
    if(id!=1 || !client_at(o,id) || s->owner_client || s->current_mode || s->target_mode || s->active || s->dirty ||
       s->initial_known || s->job_live || s->descriptor_live || o->state.queued || o->state.hpd || o->state.level_updates)
        return unlock_owner(o,-1);
    o->state.config.owner_client=id;return unlock_owner(o,0);
}
int hdmi_config_write_initial(struct hdmi_hpd_owner *o,unsigned int id,const unsigned char *bytes,unsigned int n){
    if(!o || !bytes || n!=18 || aliases_owner(o,bytes,n) || lock_owner(o))return -1;
    struct hdmi_cold_config *s=&o->state.config;
    if(!client_at(o,id) || s->owner_client!=id || !config_cold(o) || s->initial_known || (bytes[0]!=5 && bytes[0]!=6))
        return unlock_owner(o,-1);
    memcpy(s->initial,bytes,18);s->initial[17]=0;s->initial_known=1;return unlock_owner(o,18);
}
int hdmi_config_submit(struct hdmi_hpd_owner *o,unsigned int id,const unsigned char *bytes,unsigned int n,uint64_t *generation){
    if(!o || !bytes || !generation || n!=36 || aliases_owner(o,bytes,n) || aliases_owner(o,generation,sizeof *generation) ||
       overlaps(bytes,n,generation,sizeof *generation) || lock_owner(o))return -1;
    struct hdmi_cold_config *s=&o->state.config;
    if(!client_at(o,id) || s->owner_client!=id || !config_cold(o) || !s->initial_known || s->job_live || s->descriptor_live ||
       first_event(o,id) || s->generation==UINT64_MAX || o->state.next_lease==UINT64_MAX)return unlock_owner(o,-1);
    for(unsigned int i=0;i<8;i++)if(bytes[i])return unlock_owner(o,-1);
    memcpy(s->staged,bytes,36);s->has_config=1;s->job_live=1;s->job_applied=0;s->descriptor_live=1;s->completion_lease=0;
    s->generation++;s->submitted++;*generation=s->generation;return unlock_owner(o,0);
}
int hdmi_config_work_once(struct hdmi_hpd_owner *o,unsigned int id,uint64_t generation){
    if(lock_owner(o))return -1;
    struct hdmi_cold_config *s=&o->state.config;
    if(!client_at(o,id) || s->owner_client!=id || !config_cold(o) || !s->job_live || !s->descriptor_live || s->generation!=generation)
        return unlock_owner(o,-1);
    if(!s->job_applied){memcpy(s->applied,s->staged,36);s->applied_count++;s->job_applied=1;}
    /* Original fresh row0/slot4 policy byte is zero: consume the config and
     * publish a real same-client index7 event, without a hardware transaction. */
    if(first_event(o,id) || queue_event(o,id,7,0,0,&s->completion_lease))return unlock_owner(o,-2);
    s->job_live=0;s->descriptor_live=0;s->completed++;return unlock_owner(o,0);
}
