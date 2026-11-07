/* SPDX-License-Identifier: MIT */
#include "vef-bb-post.h"
#include <string.h>
const unsigned char post_original_cold_cache[16]={1,0,0,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
static unsigned u32(const unsigned char *p){return p[0]|(unsigned)p[1]<<8|(unsigned)p[2]<<16|(unsigned)p[3]<<24;}
static unsigned long long fnv(const unsigned char *p,unsigned n){
    unsigned long long h=0xcbf29ce484222325ULL;
    for(unsigned i=0;i<n;i++)h=(h^p[i])*0x100000001b3ULL;
    return h;
}
static void begin(struct post_report *r){memset(r,0,sizeof *r);pin_control_snapshot(&r->before);}
static void lease_report(struct post_report *r,const struct pin_control_lease *l){
    r->actual_handle=l->handle;r->unit=l->unit;r->physical=l->physical;r->cp_virtual=l->cp_virtual;r->address_known=1;
}
static enum post_status finish(struct post_report *r,enum post_status s,int rc){
    r->status=s;r->operation_rc=rc;
    if(r->actual_handle){
        r->refs_rc=pin_control_references(r->actual_handle,&r->refs);
        if(!r->refs_rc)r->refs_state=POST_REFS_LIVE;
        else if(r->refs_state!=POST_REFS_RELEASED)r->refs_state=POST_REFS_UNKNOWN;
    }
    r->retained=r->refs_state==POST_REFS_UNKNOWN?POST_RETENTION_UNKNOWN:
        r->refs_state==POST_REFS_LIVE && r->refs.owners?POST_RETAINED:POST_NOT_RETAINED;
    pin_control_snapshot(&r->after);return s;
}
int post_bb_init(struct post_bb *bb,const unsigned char *cache,unsigned bytes){
    if(!bb || !cache || bytes!=16)return -1;
    memset(bb,0,sizeof *bb);memcpy(bb->cache,cache,16);bb->initializations=1;return 0;
}
enum post_status post_produce(unsigned peer,const struct post_trigger *t,struct post_message *m,struct post_report *r){
    unsigned char bytes[80];struct pin_control_lease l;int rc;
    if(!r)return POST_BAD_TRIGGER;
    begin(r);if(m)*m=(struct post_message){0};
    if(peer!=0x8100)return finish(r,POST_NOT_AFTER_PEER,-1);
    if(!t || !m || t->command!=0x2002 || t->subcommand!=0xf008 || t->extent!=0x1c || t->flags!=1 ||
       !t->record || t->record_bytes!=20 || u32(t->record)!=1)return finish(r,POST_BAD_TRIGGER,-1);
    rc=vef_bb_format_build(t->record,t->record_bytes,bytes,sizeof bytes);
    if(rc)return finish(r,POST_BAD_TRIGGER,rc);
    rc=pin_control_allocate(PIN_CONTROL_UNIT,&l);
    if(rc)return finish(r,POST_ALLOC_FAILED,rc);
    lease_report(r,&l);
    rc=pin_control_write_payload(l.handle,bytes,sizeof bytes,&r->fnv);
    if(rc){
        if(!pin_control_release(l.handle))r->refs_state=POST_REFS_RELEASED;
        return finish(r,POST_WRITE_FAILED,rc);
    }
    rc=pin_control_close_for_transfer(l.handle);
    if(rc)return finish(r,POST_CLOSE_FAILED,rc);
    *m=(struct post_message){u32(t->record),l.unit,l.handle,0};
    return finish(r,POST_READY,0);
}
enum post_status post_send_result(const struct post_message *m,int send_rc,struct post_report *r){
    if(!r)return POST_BAD_MESSAGE;
    begin(r);if(!m)return finish(r,POST_BAD_MESSAGE,-1);
    r->actual_handle=m->handle;r->unit=m->unit;
    return finish(r,send_rc?POST_SEND_FAILED:POST_READY,send_rc);
}
static enum post_status close_release(struct post_report *r,enum post_status status,int reason){
    int rc=pin_control_close_consumer(r->actual_handle);
    if(rc)return finish(r,POST_CLOSE_FAILED,rc);
    rc=pin_control_release_transferred_owner(r->actual_handle);
    if(rc)return finish(r,POST_RELEASE_FAILED,rc);
    r->refs_state=POST_REFS_RELEASED;return finish(r,status,reason);
}
enum post_status post_consume(struct post_bb *bb,const struct post_message *m,struct post_report *r){
    struct pin_control_lease l;struct pin_control_references refs;int rc;
    if(!r)return POST_BAD_MESSAGE;
    begin(r);if(m){r->actual_handle=m->handle;r->unit=m->unit;}
    if(!bb || bb->initializations!=1 || !m || m->pin_index!=1 || m->unit!=PIN_CONTROL_UNIT || m->offset)
        return finish(r,POST_BAD_MESSAGE,-1);
    memcpy(r->cache_before,bb->cache,16);memcpy(r->cache_after,bb->cache,16);
    r->cache_initializations=bb->initializations;r->cache_updates=bb->updates;
    rc=pin_control_references(m->handle,&refs);
    if(rc || refs.owners!=1 || refs.opens || !refs.creator || refs.consumer || !refs.transfer_pending || refs.transferred)
        return finish(r,POST_BAD_REFS,rc?rc:-1);
    rc=pin_control_open_transferred_owner(m->handle,m->unit,&l);
    if(rc)return finish(r,POST_OPEN_FAILED,rc);
    lease_report(r,&l);
    rc=pin_control_read_consumer(l.handle,0,r->consumed,sizeof r->consumed);
    if(rc)return close_release(r,POST_READ_FAILED,rc);
    r->consumed_bytes=sizeof r->consumed;r->fnv=fnv(r->consumed,r->consumed_bytes);
    rc=vef_bb_format_decode(r->consumed,r->consumed_bytes,&r->format);
    if(rc)return close_release(r,POST_BAD_FORMAT,rc);
    r->format_valid=1;
    r->cache_changed=memcmp(bb->cache,r->consumed+64,4)!=0 || memcmp(bb->cache+8,r->consumed+72,8)!=0;
    if(!r->cache_changed)return close_release(r,POST_RELEASED_SAME,0);
    memcpy(bb->cache,r->consumed+64,16);bb->updates++;
    memcpy(r->cache_after,bb->cache,16);r->cache_updates=bb->updates;
    if(bb->pin_states[1])return close_release(r,POST_RELEASED_CHANGED,0);
    rc=pin_control_close_consumer(l.handle);
    if(rc)return finish(r,POST_CLOSE_FAILED,rc);
    return finish(r,POST_RETAINED_UNSUPPORTED,0);
}
