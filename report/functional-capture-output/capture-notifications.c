/* SPDX-License-Identifier: MIT */
#include "capture-notifications.h"
#include <errno.h>
#include <limits.h>
#include <string.h>
static uint16_t u16(const uint8_t *p){return (uint16_t)(p[0]|(uint16_t)p[1]<<8);}
static uint32_t u32(const uint8_t *p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void p16(uint8_t *p,uint16_t value){p[0]=(uint8_t)value;p[1]=(uint8_t)(value>>8);}
static void p32(uint8_t *p,uint32_t value){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(value>>(8*i));}
static uint64_t fnv(const void *pointer,size_t n){const uint8_t *p=pointer;uint64_t h=UINT64_C(14695981039346656037);for(size_t i=0;i<n;++i)h=(h^p[i])*UINT64_C(1099511628211);return h;}
static int time_valid(const uint8_t *p){
    int offset=(int16_t)u16(p);unsigned year=u16(p+2),month=p[4],day=p[5];
    if(offset<-840 || offset>840 || year<1970 || year>9999 || month<1 || month>12 ||
       p[6]>23 || p[7]>59 || p[8]>59 || p[9] || u16(p+10))return 0;
    static const unsigned days[]={31,28,31,30,31,30,31,31,30,31,30,31};
    unsigned max=days[month-1]+(month==2 && year%4==0 && (year%100!=0 || year%400==0));
    return day>=1 && day<=max;
}
static int area(uint8_t *wire,const struct capture_output_span *span){
    if(!span->handle || span->unit_type!=1 || !span->cpu || !span->alias || !span->bytes ||
       span->bytes>span->capacity || span->bytes>UINT32_MAX || span->capacity>UINT32_MAX)return -ENODATA;
    p32(wire,span->handle);p32(wire+4,0);p32(wire+8,(uint32_t)span->bytes);p32(wire+12,span->unit_type);return 0;
}
static void header(uint8_t *p,unsigned command,uint32_t cookie){p[0]=4;p16(p+2,(uint16_t)command);p32(p+4,cookie);}
int capture_notifications_build(struct capture_output_memory *owner,const uint8_t request[16],
    const uint8_t job_time[12],struct capture_notifications *out){
    if(!owner || !request || !job_time || !out)return -EINVAL;
    if(out->owner || out->lease_token)return -EBUSY;
    struct capture_output_info source;int rc=capture_output_memory_info(owner,&source);if(rc)return rc;
    if(u32(request)!=UINT32_C(0x40380005) || request[9] || request[10] || request[11] ||
       !(request[8]==2 || request[8]==10 || request[8]==12 || request[8]==8 || request[8]==9 || request[8]==3) ||
       fnv(request,16)!=source.request_fnv1a64 || u32(request+4)!=source.request_cookie ||
       request[8]!=source.request_trigger)return -EBADMSG;
    if(!time_valid(job_time))return -EINVAL;
    if(!source.generation || source.generation>UINT32_MAX || !source.frame_token)return -ESTALE;
    struct capture_output_span meta,main,thumb;
    if((rc=capture_output_memory_span(owner,CAPTURE_OUT_METADATA,&meta)) ||
       (rc=capture_output_memory_span(owner,CAPTURE_OUT_MAIN,&main)) ||
       (rc=capture_output_memory_span(owner,CAPTURE_OUT_THUMB,&thumb)))return rc;
    if(meta.generation!=source.generation || main.generation!=source.generation || thumb.generation!=source.generation)return -ESTALE;
    struct capture_notifications next={.owner=owner,.frame_token=source.frame_token,
        .request_fnv1a64=source.request_fnv1a64,.job_scalar=(uint32_t)source.generation};
    header(next.start,0x1000,source.request_cookie);p32(next.start+8,0xf000);
    /* Software normal-single-JPEG class: value1 at+10 maps to original class0. */
    next.start[0x10]=1;p32(next.start+0x14,next.job_scalar);
    header(next.entry,0x1017,source.request_cookie);p32(next.entry+8,next.job_scalar);
    memcpy(next.entry+0x14,job_time,12);
    /* Functional1006 fixed envelope; unused/padding fields explicitly reserved0. */
    header(next.info,0x1006,source.request_cookie);p32(next.info+0x0c,next.job_scalar);
    p32(next.info+0xb8,1);p32(next.info+0xc4,next.job_scalar);
    uint8_t *jpg=next.info+0xc8;
    if((rc=area(jpg,&meta)) || (rc=area(jpg+0x90,&main)) || (rc=area(jpg+0xa0,&thumb)))return rc;
    p32(next.info+0x218,0);
    rc=capture_output_memory_hold(owner,&next.lease_token);if(rc)return rc;
    *out=next;return 0;
}
int capture_notifications_release(struct capture_notifications *n){
    if(!n || !n->owner || !n->lease_token)return -EINVAL;
    int rc=capture_output_memory_drop(n->owner,n->lease_token);
    if(!rc)memset(n,0,sizeof *n);
    return rc;
}
