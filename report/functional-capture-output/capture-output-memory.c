/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "capture-output-memory.h"
#include <errno.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define PAGE 4096u
#define MAX_MAIN (64u*1024u*1024u)
#define MAX_THUMB (16u*1024u*1024u)
#define PREFIX_CAP (256u*1024u)
#define EXPORTS 8u
struct capture_output_memory {
    struct capture_input *input;
    struct capture_input_mapping input_hold;
    struct capture_output_info info;
    struct capture_output_span spans[CAPTURE_OUT_COUNT];
    size_t total;
    unsigned char *memory;
    uint64_t next_export,exports[EXPORTS];
    pid_t pid;
};
static _Atomic uint32_t generations;
static uint16_t get16(const uint8_t *p) { return (uint16_t)(p[0]|(uint16_t)p[1]<<8); }
static uint32_t get32(const uint8_t *p) { return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static void put16(uint8_t *p,uint16_t v) { p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8); }
static void put32(uint8_t *p,uint32_t v) { for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(v>>(8*i)); }
static void put64(uint8_t *p,uint64_t v) { for(unsigned i=0;i<8;++i)p[i]=(uint8_t)(v>>(8*i)); }
static int guard(const struct capture_output_memory *m) { return !m?-EINVAL:m->pid!=getpid()?-ECHILD:0; }
static int jpeg(const void *data,size_t bytes,size_t limit) {
    if(!data || bytes<4 || bytes>limit || bytes>UINTPTR_MAX-(uintptr_t)data)return 0;
    const uint8_t *p=data;return p[0]==255 && p[1]==216 && p[bytes-2]==255 && p[bytes-1]==217;
}
static size_t pages(size_t n) { return (n+PAGE-1)&~(size_t)(PAGE-1); }
static int source_live(struct capture_output_memory *m) {
    int rc=guard(m);if(rc)return rc;if(!m->memory)return -ESTALE;
    struct capture_input_info now;
    rc=capture_input_info(m->input,&now);if(rc)return rc;
    return now.token==m->info.frame_token && now.model_instance==m->info.model_instance &&
        now.model_lifetime==m->info.model_lifetime && now.config_generation==m->info.config_generation &&
        now.source_fnv1a64==m->info.source_RGB_fnv && now.request_fnv1a64==m->info.request_fnv1a64 &&
        now.request_cookie==m->info.request_cookie && now.request_trigger==m->info.request_trigger?0:-ESTALE;
}
int capture_output_memory_create(struct capture_input *input,const void *main,size_t main_bytes,
    const void *thumb,size_t thumb_bytes,uint64_t mapbase,struct capture_output_memory **out) {
    if(!input || !out || *out || sysconf(_SC_PAGESIZE)!=PAGE ||
       !jpeg(main,main_bytes,MAX_MAIN) || !jpeg(thumb,thumb_bytes,MAX_THUMB))return -EINVAL;
    struct capture_input_info source;
    int rc=capture_input_info(input,&source);if(rc)return rc;
    struct capture_output_memory *m=calloc(1,sizeof *m);if(!m)return -ENOMEM;
    rc=capture_input_hold(input,&m->input_hold);if(rc){free(m);return rc;}
    const size_t capacities[CAPTURE_OUT_COUNT]={PAGE,pages(main_bytes-2),pages(thumb_bytes),PREFIX_CAP,PREFIX_CAP};
    for(unsigned i=0;i<CAPTURE_OUT_COUNT;++i)m->total+=capacities[i];
    m->memory=mmap(NULL,m->total,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if(m->memory==MAP_FAILED){rc=-errno;goto fail;}
    if((uintptr_t)m->memory<mapbase || m->total>UINTPTR_MAX-(uintptr_t)m->memory){rc=-ERANGE;goto fail;}
    uint32_t id=atomic_load(&generations);
    do {
        if(id==4095){rc=-EOVERFLOW;goto fail;}
    }while(!atomic_compare_exchange_weak(&generations,&id,id+1));
    ++id;
    m->input=input;m->pid=getpid();
    m->info=(struct capture_output_info){.generation=id,.frame_token=source.token,
        .model_instance=source.model_instance,.model_lifetime=source.model_lifetime,
        .config_generation=source.config_generation,.source_RGB_fnv=source.source_fnv1a64,.original_map_base=mapbase,
        .request_fnv1a64=source.request_fnv1a64,.request_cookie=source.request_cookie,.request_trigger=source.request_trigger};
    size_t offset=0;
    const size_t bytes[CAPTURE_OUT_COUNT]={512,main_bytes-2,thumb_bytes,0,0};
    for(unsigned i=0;i<CAPTURE_OUT_COUNT;++i) {
        uintptr_t cpu=(uintptr_t)m->memory+offset;uint64_t alias=cpu-mapbase;
        if(!alias || capacities[i]>UINT64_MAX-alias){rc=-ERANGE;goto fail;}
        m->spans[i]=(struct capture_output_span){.cpu=cpu,.alias=alias,.generation=id,
            .bytes=bytes[i],.capacity=capacities[i],.handle=UINT32_C(0x68000000)+id*8u+i+1u,.unit_type=1};
        offset+=capacities[i];
    }
    memset((void *)m->spans[CAPTURE_OUT_METADATA].cpu,255,512);
    memcpy((void *)m->spans[CAPTURE_OUT_MAIN].cpu,(const uint8_t *)main+2,main_bytes-2);
    memcpy((void *)m->spans[CAPTURE_OUT_THUMB].cpu,thumb,thumb_bytes);
    if(memcmp((void *)m->spans[CAPTURE_OUT_MAIN].cpu,(const uint8_t *)main+2,main_bytes-2) ||
       memcmp((void *)m->spans[CAPTURE_OUT_THUMB].cpu,thumb,thumb_bytes)){rc=-EIO;goto fail;}
    *out=m;return 0;
fail:
    if(m->memory && m->memory!=MAP_FAILED)munmap(m->memory,m->total);
    {int dropped=capture_input_drop(input,&m->input_hold);if(!rc)rc=dropped;}
    free(m);return rc;
}
int capture_output_memory_info(struct capture_output_memory *m,struct capture_output_info *out) {
    int rc=source_live(m);if(rc)return rc;if(!out)return -EINVAL;*out=m->info;return 0;
}
int capture_output_memory_span(struct capture_output_memory *m,enum capture_output_role role,struct capture_output_span *out) {
    int rc=source_live(m);if(rc)return rc;if(!out || (unsigned)role>=CAPTURE_OUT_COUNT)return -EINVAL;
    *out=m->spans[role];return 0;
}
int capture_output_memory_reply(struct capture_output_memory *m,const uint8_t q[40],uint64_t mapbase,uint8_t out[40]) {
    int rc=source_live(m);if(rc)return rc;
    if(!q || !out || mapbase!=m->info.original_map_base)return -EINVAL;
    uintptr_t a=(uintptr_t)q,b=(uintptr_t)out;
    if(a>UINTPTR_MAX-40 || b>UINTPTR_MAX-40 || (a<b+40 && b<a+40))return -EINVAL;
    uint16_t op=get16(q),option=get16(q+22);
    uint32_t handle=get32(q+8);unsigned index=0;
    if(op==0x28) {
        if(option)return -ENOTSUP;
        if(handle==UINT32_C(0x00080d61))index=CAPTURE_OUT_HEADER;
        else if(handle==UINT32_C(0x27f))index=CAPTURE_OUT_AUX;
        else return -ENODATA;
    } else {
        for(;index<CAPTURE_OUT_COUNT && m->spans[index].handle!=handle;++index){}
        if(index==CAPTURE_OUT_COUNT)return -ESTALE;
    }
    struct capture_output_span *span=&m->spans[index];
    if(op==0x21) {
        if(option!=1 || get32(q+4)!=span->unit_type)return -ENOTSUP;
        if(span->references==255 || m->info.native_references==UINT32_MAX)return -EOVERFLOW;
    } else if(op==0x2a) { if(option)return -ENOTSUP; }
    else if(op==0x23) { if(option!=2)return -ENOTSUP;if(!span->references)return -EALREADY; }
    else if(op!=0x28)return -ENOTSUP;
    uint8_t reply[40]={0};put16(reply,(uint16_t)(op|0x8000));put32(reply+12,span->handle);
    if(op!=0x23) {
        put16(reply+8,1);put32(reply+16,span->unit_type);put64(reply+24,span->alias);put32(reply+32,(uint32_t)span->capacity);
    }
    if(op==0x21){++span->references;++m->info.native_references;}
    if(op==0x23){--span->references;--m->info.native_references;}
    memcpy(out,reply,sizeof reply);return 0;
}
int capture_output_memory_hold(struct capture_output_memory *m,uint64_t *token) {
    int rc=source_live(m);if(rc)return rc;if(!token)return -EINVAL;
    if(m->next_export==UINT32_MAX)return -EOVERFLOW;
    unsigned index=0;for(;index<EXPORTS && m->exports[index];++index){}
    if(index==EXPORTS)return -ENOSPC;
    uint64_t value=(m->info.generation<<32)|++m->next_export;
    m->exports[index]=value;++m->info.export_references;*token=value;return 0;
}
int capture_output_memory_drop(struct capture_output_memory *m,uint64_t token) {
    int rc=guard(m);if(rc)return rc;
    for(unsigned i=0;i<EXPORTS;++i)if(token && m->exports[i]==token){m->exports[i]=0;--m->info.export_references;return 0;}
    return -ESTALE;
}
int capture_output_memory_destroy(struct capture_output_memory *m) {
    int rc=guard(m);if(rc)return rc;
    if(m->info.native_references || m->info.export_references)return -EBUSY;
    if(m->memory){if(munmap(m->memory,m->total))return -errno;m->memory=NULL;}
    rc=capture_input_drop(m->input,&m->input_hold);if(rc)return rc;
    memset(m,0,sizeof *m);free(m);return 0;
}
