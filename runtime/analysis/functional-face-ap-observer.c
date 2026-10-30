/* SPDX-License-Identifier: MIT */
#include "functional-face-ap-observer.h"
#include <errno.h>
#ifdef FULL_IMAGING_GUEST
extern int getpid(void);
#else
#include <unistd.h>
#endif
static uint32_t face_ap_word(const unsigned char *p, size_t n) {
    uint32_t v=0;
    for(size_t i=0;i<n;i++)v|=(uint32_t)p[i]<<(8*i);
    return v;
}
static int face_ap_same_thread(const struct functional_face_ap_observer *s, int64_t tid) {
    return s && s->owner_pid==getpid() && s->sender_tid==tid && s->active;
}
int functional_face_ap_begin(struct functional_face_ap_observer *s, int enabled, int verified,
    int64_t tid, uint32_t destination, uint32_t source, const void *request, size_t bytes,
    functional_face_ap_record record) {
    if(!s || enabled!=1 || verified!=1 || destination!=FUNCTIONAL_FACE_AP_DMM || !source ||
        source==FUNCTIONAL_FACE_AP_DMM || source==UINT32_MAX || !request || bytes!=40 || tid<=0)return 0;
    if(s->owner_pid && (s->owner_pid!=getpid() || s->sender_tid!=tid))return -ECHILD;
    const unsigned char *p=request;
    uint32_t op=face_ap_word(p,2),unit=face_ap_word(p+4,4),handle=face_ap_word(p+8,4);
    if(op==0x20 || op==0x21) { if(unit<0x1d9 || unit>0x1dc)return 0; }
    else if(op!=0x23 && op!=0x24 && op!=0x25)return 0;
    if(op!=0x20 && (!handle || handle>0x7fff || !((handle>>10)&31u)))return 0;
    if(s->active) { ++s->dropped;if(record)record(FACE_AP_RETAINED,s);return -EBUSY; }
    if(s->sequence==UINT64_MAX)return -EOVERFLOW;
    uint64_t sequence=s->sequence+1,dropped=s->dropped;
    struct functional_face_ap_birth births[4];
    for(size_t i=0;i<4;i++)births[i]=s->births[i];
    *s=(struct functional_face_ap_observer){.owner_pid=getpid(),.sender_tid=tid,.sequence=sequence,
        .dropped=dropped,.active=1,.source=source,.op=op,.unit=unit,.handle=handle,.request=(uintptr_t)request};
    for(size_t i=0;i<4;i++)s->births[i]=births[i];
    for(size_t i=0;i<40;i++)s->request_wire[i]=p[i];
    if(record)record(FACE_AP_SUBMIT,s);
    return 1;
}
void functional_face_ap_sent(struct functional_face_ap_observer *s, int64_t tid, int result,
    functional_face_ap_record record) {
    if(!face_ap_same_thread(s,tid) || s->send_seen)return;
    s->send_seen=1;s->send_result=result;
    if(result)s->active=0;
    if(record)record(FACE_AP_SEND_RETURN,s);
}
void functional_face_ap_received(struct functional_face_ap_observer *s, int64_t tid, uint32_t queue,
    uint32_t source, void *reply, size_t bytes, int result, functional_face_ap_record record) {
    if(!face_ap_same_thread(s,tid) || result || !s->send_seen || s->send_result || queue!=s->source ||
        !reply || bytes<40 || s->received)return;
    const unsigned char *p=reply;
    if(face_ap_word(p,2)!=(s->op|0x8000u))return;
    s->reply=(uintptr_t)reply;s->reply_source=source;s->reply_bytes=bytes>UINT32_MAX?UINT32_MAX:(uint32_t)bytes;s->received=1;
    for(size_t i=0;i<40;i++)s->reply_wire[i]=p[i];
    if(record)record(FACE_AP_RECEIVE,s);
}
void functional_face_ap_freed(struct functional_face_ap_observer *s, int64_t tid, uint32_t queue,
    void *reply, int result, functional_face_ap_record record) {
    if(!face_ap_same_thread(s,tid) || !s->received || queue!=s->source || s->reply!=(uintptr_t)reply)return;
    ++s->free_attempts;s->free_result=result;
    if(!result) {
        s->active=0;
        if(s->send_seen && !s->send_result && s->reply_source==FUNCTIONAL_FACE_AP_DMM &&
           !face_ap_word(s->reply_wire+2,2)) {
            if(s->op==0x20 && s->unit>=0x1d9 && s->unit<=0x1dc) {
                uint32_t h=face_ap_word(s->reply_wire+12,4);
                struct functional_face_ap_birth *b=&s->births[s->unit-0x1d9];
                if(b->observations) { b->ambiguous=1;if(b->observations!=UINT32_MAX)++b->observations; }
                else *b=(struct functional_face_ap_birth){.unit=s->unit,.handle=h,.observations=1,
                    .ambiguous=!(h && h<=0x7fff && (h&0x3ffu)!=0x3ffu && ((h>>10)&31u)),
                    .reply_source=s->reply_source,.observation_sequence=s->sequence};
            }
        }
        if(s->send_seen && !s->send_result && s->op==0x23) {
            for(size_t i=0;i<4;i++)if(s->births[i].observations && s->births[i].handle==s->handle)
                s->births[i].any_free_observed=1;
        }
    }
    if(record)record(FACE_AP_FREE_RETURN,s);
}
int functional_face_ap_observed_birth(const struct functional_face_ap_observer *s,int64_t tid,
    uint32_t unit,uint32_t handle,struct functional_face_ap_birth *out) {
    if(!s || !out || unit<0x1d9 || unit>0x1dc)return -EINVAL;
    if(s->owner_pid!=getpid() || s->sender_tid!=tid)return -ECHILD;
    const struct functional_face_ap_birth *b=&s->births[unit-0x1d9];
    if(b->observations!=1 || b->ambiguous || b->handle!=handle || b->reply_source!=FUNCTIONAL_FACE_AP_DMM)
        return -ESTALE;
    *out=*b;return 0;
}
