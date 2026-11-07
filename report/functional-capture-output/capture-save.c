/* SPDX-License-Identifier: MIT */
#include "capture-save.h"
#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
struct capture_save {
    struct capture_output_memory *owner;
    struct capture_save_info info;
    struct capture_output_span main;
    uint64_t callback,lease;
};
static uint64_t hash_bytes(uint64_t h,const void *p,size_t n){const unsigned char *b=p;for(size_t i=0;i<n;++i)h=(h^b[i])*UINT64_C(1099511628211);return h;}
static uint64_t hash(const void *p,size_t n){return hash_bytes(UINT64_C(14695981039346656037),p,n);}
static int guard(const struct capture_save *s){return !s?-EINVAL:s->info.owner_pid!=getpid()?-ECHILD:0;}
static int fault(struct capture_save *s,int rc){if(!s->info.first_error)s->info.first_error=rc?rc:-EIO;return rc?rc:-EIO;}
static int current(struct capture_save *s){
    int rc=guard(s);if(rc)return rc;
    struct capture_output_info info;rc=capture_output_memory_info(s->owner,&info);if(rc)return rc;
    return info.generation==s->info.generation && info.frame_token==s->info.frame_token &&
        info.request_fnv1a64==s->info.request_fnv1a64?0:-ESTALE;
}
int capture_save_prepare(struct capture_output_memory *owner,uint64_t callback,struct capture_save **out){
    if(!owner || !callback || !out || *out)return -EINVAL;
    struct capture_output_info info;int rc=capture_output_memory_info(owner,&info);if(rc)return rc;
    struct capture_output_span main;rc=capture_output_memory_span(owner,CAPTURE_OUT_MAIN,&main);if(rc)return rc;
    if(!main.bytes || main.bytes>main.capacity || main.generation!=info.generation)return -ESTALE;
    struct capture_save *s=calloc(1,sizeof *s);if(!s)return -ENOMEM;
    rc=capture_output_memory_hold(owner,&s->lease);if(rc){free(s);return rc;}
    s->owner=owner;s->callback=callback;s->main=main;
    s->info=(struct capture_save_info){.owner_pid=getpid(),.generation=info.generation,
        .frame_token=info.frame_token,.request_fnv1a64=info.request_fnv1a64,.main_fnv=hash((const void *)main.cpu,main.bytes)};
    *out=s;return 0;
}
static int jpeg_path(const char *path,size_t length){
    if(length<7 || path[0]<'A' || path[0]>'Z' || path[1]!=':' || path[2]!='/')return 0;
    const char *suffix=path+length-4;return suffix[0]=='.' && (suffix[1]=='j' || suffix[1]=='J') &&
        (suffix[2]=='p' || suffix[2]=='P') && (suffix[3]=='g' || suffix[3]=='G');
}
int capture_save_match(struct capture_save *s,unsigned token,const struct fsys_write_layout *layout,
    const uint64_t hashes[FSYS_WRITE_AREAS],const unsigned readable[FSYS_WRITE_AREAS]){
    int rc=guard(s);if(rc)return rc;
    if(!layout || !hashes || !readable)return -EINVAL;
    if(!layout->count || layout->count>FSYS_WRITE_AREAS)return 0;
    unsigned main_count=0;
    for(unsigned i=0;i<layout->count;++i)main_count+=layout->area[i].address==s->main.cpu;
    if(!main_count)return 0;
    if(s->info.first_error)return s->info.first_error;
    rc=current(s);if(rc)return fault(s,rc);
    if(!token || s->info.token || main_count!=1)return fault(s,-EALREADY);
    const char *end=memchr(layout->path,0,sizeof layout->path);
    if(!end || !jpeg_path(layout->path,(size_t)(end-layout->path)) || layout->callback!=s->callback ||
       !layout->cookie || layout->address_mode!=1 || layout->payload_bytes!=layout->expected_bytes ||
       layout->expected_bytes<=s->main.bytes || layout->expected_bytes>FSYS_WRITE_OBSERVATION_LIMIT)return fault(s,-EBADMSG);
    if(hash((const void *)s->main.cpu,s->main.bytes)!=s->info.main_fnv)return fault(s,-ESTALE);
    struct capture_output_span spans[CAPTURE_OUT_COUNT];
    for(unsigned i=0;i<CAPTURE_OUT_COUNT;++i){rc=capture_output_memory_span(s->owner,(enum capture_output_role)i,&spans[i]);if(rc)return fault(s,rc);}
    uint64_t submitted=0,payload=0,combined=UINT64_C(14695981039346656037);unsigned main_seen=0,first=1;
    for(unsigned i=0;i<layout->count;++i){
        const struct fsys_write_area *a=&layout->area[i];
        if(a->offset!=submitted || a->submitted_bytes>UINT64_MAX-submitted ||
           !a->address || a->address>UINTPTR_MAX || (a->address&4095) || (a->submitted_bytes&4095))return fault(s,-EBADMSG);
        submitted+=a->submitted_bytes;
        uint64_t expected=a->offset<layout->expected_bytes?layout->expected_bytes-a->offset:0;
        if(expected>a->submitted_bytes)expected=a->submitted_bytes;
        if(a->bytes!=expected || !readable[i])return fault(s,-EBADMSG);
        unsigned role=0;
        for(;role<CAPTURE_OUT_COUNT;++role){
            const struct capture_output_span *p=&spans[role];
            if(a->address>=p->cpu && a->address-p->cpu<p->capacity &&
               a->submitted_bytes<=p->capacity-(a->address-p->cpu))break;
        }
        if(role==CAPTURE_OUT_COUNT)return fault(s,-EXDEV);
        if(a->bytes){
            if(main_seen)return fault(s,-EBADMSG);
            const unsigned char *p=(const void *)(uintptr_t)a->address;
            if(first){if(a->bytes<2 || p[0]!=255 || p[1]!=216)return fault(s,-EBADMSG);first=0;}
            if(role==CAPTURE_OUT_MAIN){if(a->address!=s->main.cpu || a->bytes!=s->main.bytes)return fault(s,-EBADMSG);main_seen=1;}
            if(hash(p,(size_t)a->bytes)!=hashes[i])return fault(s,-ESTALE);
            combined=hash_bytes(combined,p,(size_t)a->bytes);payload+=a->bytes;
        }else if(hashes[i]!=UINT64_C(14695981039346656037))return fault(s,-EBADMSG);
    }
    if(!main_seen || payload!=layout->expected_bytes || layout->expected_bytes>submitted)return fault(s,-EBADMSG);
    s->info.token=token;s->info.cookie=layout->cookie;s->info.bytes=payload;s->info.file_fnv=combined;
    s->info.path_fnv=hash(layout->path,(size_t)(end-layout->path));return 1;
}
int capture_save_observe(struct capture_save *s,unsigned token,enum capture_save_event event,
    int rc,unsigned complete,uint64_t bytes,uint64_t content_hash){
    int checked=guard(s);if(checked)return checked;
    if(!s->info.token || (event!=CAPTURE_SAVE_COVERAGE && token!=s->info.token))return 0;
    if(s->info.first_error)return s->info.first_error;
    checked=current(s);if(checked)return fault(s,checked);
    if(complete!=1 || rc)return fault(s,rc?rc:-ENODATA);
    switch(event){
    case CAPTURE_SAVE_SUBMIT:
        if(s->info.submitted)return fault(s,-EALREADY);
        s->info.submitted=1;break;
    case CAPTURE_SAVE_CALLBACK:
        if(s->info.callback_seen)return fault(s,-EALREADY);
        s->info.callback_seen=1;break;
    case CAPTURE_SAVE_CALLBACK_RETURN:
        if(!s->info.callback_seen || s->info.callback_returned)return fault(s,-EPROTO);
        s->info.callback_returned=1;break;
    case CAPTURE_SAVE_FINISHED:
        if(!s->info.callback_seen || s->info.finished)return fault(s,-EPROTO);
        s->info.finished=1;break;
    case CAPTURE_SAVE_READBACK:
        if(!s->info.submitted || !s->info.callback_returned || !s->info.finished ||
           bytes!=s->info.bytes || content_hash!=s->info.file_fnv)return fault(s,-EBADMSG);
        s->info.readback=1;break;
    case CAPTURE_SAVE_COVERAGE:
        if(token || !s->info.readback || bytes<s->info.token)return fault(s,-EBADMSG);
        s->info.coverage=1;break;
    default:return fault(s,-EINVAL);
    }
    s->info.write_readback_verified=s->info.submitted && s->info.callback_seen && s->info.callback_returned &&
        s->info.finished && s->info.readback && s->info.coverage;
    return 1;
}
int capture_save_info(struct capture_save *s,struct capture_save_info *out){int rc=guard(s);if(rc)return rc;if(!out)return -EINVAL;*out=s->info;return 0;}
int capture_save_close(struct capture_save *s){
    int rc=current(s);if(rc)return rc;
    if(s->info.first_error)return s->info.first_error;
    if(!s->info.write_readback_verified)return -EBUSY;
    struct capture_output_info info;rc=capture_output_memory_info(s->owner,&info);if(rc)return rc;
    if(info.native_references)return -EBUSY;
    rc=capture_output_memory_drop(s->owner,s->lease);if(rc)return rc;
    memset(s,0,sizeof *s);free(s);return 0;
}
