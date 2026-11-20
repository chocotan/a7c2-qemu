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
    struct capture_output_span raw_spans[CAPTURE_RAW_COUNT];
    struct capture_output_raw_area raw_areas[21];
    unsigned char *raw_memory;
    size_t raw_total;
    unsigned publication_mask;
    size_t total;
    unsigned char *memory;
    uint64_t next_export,exports[EXPORTS];
    unsigned allocated_prefixes,publication,publication_used;
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
    m->spans[CAPTURE_OUT_HEADER].unit_type=UINT32_C(0x80d61);
    m->spans[CAPTURE_OUT_AUX].unit_type=UINT32_C(0x27f);
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
static struct capture_output_span *owned_span(struct capture_output_memory *m,unsigned index) {
    return index<CAPTURE_OUT_COUNT?&m->spans[index]:&m->raw_spans[index-CAPTURE_OUT_COUNT];
}
static int raw_group(unsigned area) {
    switch(area) {
    case 0:case 3:case 4:case 5:case 6:case 8:return CAPTURE_RAW_COMMON;
    case 10:case 11:case 12:case 13:case 14:case 15:case 16:case 20:return CAPTURE_RAW_CONTROL;
    default:return -1;
    }
}
int capture_output_memory_add_raw(struct capture_output_memory *m,const struct capture_output_raw_input *raw) {
    int rc=source_live(m);if(rc)return rc;
    if(!raw)return -EINVAL;
    if(m->raw_memory || m->publication || m->info.native_references)return -EBUSY;
    if(raw->frame_token!=m->info.frame_token || raw->model_instance!=m->info.model_instance ||
       raw->model_lifetime!=m->info.model_lifetime || raw->config_generation!=m->info.config_generation ||
       raw->request_fnv1a64!=m->info.request_fnv1a64 || raw->request_cookie!=m->info.request_cookie ||
       raw->request_trigger!=m->info.request_trigger)return -ESTALE;
    if(!jpeg(raw->preview,raw->preview_bytes,MAX_MAIN) ||
       !jpeg(raw->thumbnail,raw->thumbnail_bytes,MAX_THUMB))return -EINVAL;
    const void *data[CAPTURE_RAW_COUNT]={raw->common,raw->control,raw->preview,raw->pixels,raw->thumbnail};
    const size_t source_bytes[CAPTURE_RAW_COUNT]={raw->common_bytes,raw->control_bytes,raw->preview_bytes,raw->pixel_bytes,raw->thumbnail_bytes};
    const size_t bytes[CAPTURE_RAW_COUNT]={raw->common_bytes,raw->control_bytes,
        CAPTURE_RAW_PREVIEW_PREFIX_BYTES+raw->preview_bytes,raw->pixel_bytes,raw->thumbnail_bytes};
    size_t capacities[CAPTURE_RAW_COUNT],total=0;
    for(unsigned i=0;i<CAPTURE_RAW_COUNT;++i) {
        if(!data[i] || !source_bytes[i] || bytes[i]>UINT32_MAX-(PAGE-1) ||
           source_bytes[i]>UINTPTR_MAX-(uintptr_t)data[i])return -EINVAL;
        capacities[i]=pages(bytes[i]);
        if(capacities[i]>UINT32_MAX-total)return -EOVERFLOW;
        total+=capacities[i];
    }
    for(unsigned i=0;i<21;++i) {
        int group=raw_group(i);struct capture_output_raw_area area=raw->areas[i];
        if(group<0){if(area.offset || area.bytes)return -EINVAL;continue;}
        if(area.offset>bytes[group] || area.bytes>bytes[group]-area.offset)return -ERANGE;
    }
    const unsigned required[]={0,8,10,14,15,16};
    for(unsigned i=0;i<sizeof required/sizeof *required;++i)
        if(!raw->areas[required[i]].bytes)return -ENODATA;
    if(raw->areas[14].bytes!=CAPTURE_RAW_PARAM_BYTES || raw->areas[15].bytes!=4)return -EINVAL;
    static const uint8_t grbg[4]={1,0,2,1};
    if(memcmp((const uint8_t *)raw->control+raw->areas[15].offset,grbg,4))return -ENOTSUP;
    const uint8_t *params=(const uint8_t *)raw->control+raw->areas[14].offset;
    struct capture_input_info source;rc=capture_input_info(m->input,&source);if(rc)return rc;
    uint32_t width=get32(params),height=get32(params+4);
    if(width!=source.width || height!=source.height || !width || !height ||
       (uint64_t)width*height>UINT32_MAX/2 || raw->pixel_bytes!=(uint64_t)width*height*2)return -ERANGE;
    if(get32(params+8)!=14 || get32(params+12)!=1 || get32(params+16)!=32803 ||
       get32(params+20)!=1 || get32(params+24)!=1 || get32(params+48)!=2 || get32(params+52)!=2 ||
       get32(params+96)!=height)return -ENOTSUP;
    const uint8_t *pixels=raw->pixels;
    for(size_t i=0;i<raw->pixel_bytes;i+=2)if(get16(pixels+i)>16383)return -ERANGE;
    struct capture_output_raw_area header=raw->areas[8];
    if(header.offset%PAGE || header.bytes%PAGE)return -EINVAL;
    /* Native ARW wraps source bytes after its4-byte prefix with a14-byte envelope. */
    size_t aux_capacity=pages((size_t)header.bytes+14u);
    if(aux_capacity>UINT32_MAX-total)return -EOVERFLOW;
    total+=aux_capacity;
    for(unsigned i=0;i<21;++i) {
        struct capture_output_raw_area area=raw->areas[i];
        if(i!=8 && raw_group(i)==CAPTURE_RAW_COMMON && area.bytes &&
           area.offset<header.offset+header.bytes && header.offset<area.offset+area.bytes)return -EINVAL;
    }
    unsigned char *memory=mmap(NULL,total,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if(memory==MAP_FAILED)return -errno;
    if((uintptr_t)memory<m->info.original_map_base || total>UINTPTR_MAX-(uintptr_t)memory){munmap(memory,total);return -ERANGE;}
    struct capture_output_span spans[CAPTURE_RAW_COUNT]={0};
    size_t offset=0;
    for(unsigned i=0;i<CAPTURE_RAW_COUNT;++i) {
        if(!capacities[i])continue;
        uintptr_t cpu=(uintptr_t)memory+offset;uint64_t alias=cpu-m->info.original_map_base;
        if(!alias || capacities[i]>UINT64_MAX-alias){munmap(memory,total);return -ERANGE;}
        spans[i]=(struct capture_output_span){.cpu=cpu,.alias=alias,.generation=m->info.generation,
            .bytes=bytes[i],.capacity=capacities[i],.unit_type=1,
            .handle=UINT32_C(0x69000000)+(uint32_t)m->info.generation*8u+i+1u};
        /* libarw+0x2690e0 writes SOI at +0xa2 and stores that offset in the preview IFD. */
        uintptr_t destination=cpu+(i==CAPTURE_RAW_PREVIEW?CAPTURE_RAW_PREVIEW_PREFIX_BYTES:0);
        memcpy((void *)destination,data[i],source_bytes[i]);
        if(memcmp((void *)destination,data[i],source_bytes[i])){munmap(memory,total);return -EIO;}
        offset+=capacities[i];
    }
    uintptr_t aux_cpu=(uintptr_t)memory+offset;uint64_t aux_alias=aux_cpu-m->info.original_map_base;
    if(!aux_alias || aux_capacity>UINT64_MAX-aux_alias){munmap(memory,total);return -ERANGE;}
    struct capture_output_span aux=m->spans[CAPTURE_OUT_AUX];
    aux.cpu=aux_cpu;aux.alias=aux_alias;aux.capacity=aux_capacity;
    memset((void *)(spans[CAPTURE_RAW_COMMON].cpu+header.offset),0,header.bytes);
    memcpy(m->raw_spans,spans,sizeof spans);memcpy(m->raw_areas,raw->areas,sizeof m->raw_areas);
    m->spans[CAPTURE_OUT_AUX]=aux;
    m->raw_memory=memory;m->raw_total=total;
    m->spans[CAPTURE_OUT_HEADER].unit_type=UINT32_C(0x80561);
    m->spans[CAPTURE_OUT_AUX].unit_type=UINT32_C(0x66e);
    return 0;
}
int capture_output_memory_raw_span(struct capture_output_memory *m,enum capture_output_raw_role role,struct capture_output_span *out) {
    int rc=source_live(m);if(rc)return rc;
    if(!out || (unsigned)role>=CAPTURE_RAW_COUNT)return -EINVAL;
    if(!m->raw_memory || !m->raw_spans[role].handle)return -ENODATA;
    *out=m->raw_spans[role];return 0;
}
int capture_output_memory_raw_info(struct capture_output_memory *m,uint8_t out[CAPTURE_RAW_INFO_BYTES]) {
    int rc=source_live(m);if(rc)return rc;if(!out)return -EINVAL;if(!m->raw_memory)return -ENODATA;
    uint8_t result[CAPTURE_RAW_INFO_BYTES]={0};
    for(unsigned i=0;i<21;++i) {
        int group=raw_group(i);struct capture_output_raw_area area=m->raw_areas[i];
        /* Native _check_error requires area9; area19 is a separate optional attachment. */
        if(i==9)group=CAPTURE_RAW_THUMB;
        if(i==17)group=CAPTURE_RAW_PREVIEW;
        if(i==18)group=CAPTURE_RAW_PIXELS;
        if(group<0)continue;
        struct capture_output_span *span=&m->raw_spans[group];
        if(i==9 || i==17 || i==18){area.offset=0;area.bytes=(uint32_t)span->bytes;}
        if(!area.bytes)continue;
        if(!span->handle || area.offset>span->capacity || area.bytes>span->capacity-area.offset)return -ERANGE;
        uint8_t *p=result+i*16;put32(p,span->handle);put32(p+4,area.offset);
        put32(p+8,area.bytes);put32(p+12,span->unit_type);
    }
    memcpy(out,result,sizeof result);return 0;
}
int capture_output_memory_info(struct capture_output_memory *m,struct capture_output_info *out) {
    int rc=source_live(m);if(rc)return rc;if(!out)return -EINVAL;*out=m->info;return 0;
}
int capture_output_memory_span(struct capture_output_memory *m,enum capture_output_role role,struct capture_output_span *out) {
    int rc=source_live(m);if(rc)return rc;if(!out || (unsigned)role>=CAPTURE_OUT_COUNT)return -EINVAL;
    *out=m->spans[role];return 0;
}
static int publish_begin(struct capture_output_memory *m,unsigned mask) {
    int rc=source_live(m);if(rc)return rc;
    if(m->publication)return -EALREADY;
    unsigned count=0;
    for(unsigned i=0;i<CAPTURE_OUT_COUNT+CAPTURE_RAW_COUNT;++i)if(mask&(1u<<i)) {
        if(!owned_span(m,i)->handle)return -ENODATA;
        if(owned_span(m,i)->references)return -EBUSY;
        ++count;
    }
    if(m->info.native_references>UINT32_MAX-count)return -EOVERFLOW;
    for(unsigned i=0;i<CAPTURE_OUT_COUNT+CAPTURE_RAW_COUNT;++i)if(mask&(1u<<i))++owned_span(m,i)->references;
    m->info.native_references+=count;m->publication_mask=mask;
    m->publication=1;m->publication_used=0;return 0;
}
int capture_output_memory_publish_begin(struct capture_output_memory *m) {
    return publish_begin(m,(1u<<CAPTURE_OUT_METADATA)|(1u<<CAPTURE_OUT_MAIN)|(1u<<CAPTURE_OUT_THUMB));
}
int capture_output_memory_publish_raw_begin(struct capture_output_memory *m,int include_jpeg) {
    int rc=source_live(m);if(rc)return rc;
    if(include_jpeg!=0 && include_jpeg!=1)return -EINVAL;
    if(!m->raw_memory)return -ENODATA;
    unsigned mask=include_jpeg?7u:0u;
    for(unsigned i=0;i<CAPTURE_RAW_COUNT;++i)if(m->raw_spans[i].handle)mask|=1u<<(CAPTURE_OUT_COUNT+i);
    return publish_begin(m,mask);
}
int capture_output_memory_publish_commit(struct capture_output_memory *m) {
    int rc=source_live(m);if(rc)return rc;if(m->publication!=1)return -EINVAL;
    m->publication=2;return 0;
}
int capture_output_memory_publish_cancel(struct capture_output_memory *m) {
    int rc=source_live(m);if(rc)return rc;
    if(m->publication!=1 || m->publication_used)return -EBUSY;
    for(unsigned i=0;i<CAPTURE_OUT_COUNT+CAPTURE_RAW_COUNT;++i)
        if((m->publication_mask&(1u<<i)) && owned_span(m,i)->references!=1)return -EBUSY;
    for(unsigned i=0;i<CAPTURE_OUT_COUNT+CAPTURE_RAW_COUNT;++i)if(m->publication_mask&(1u<<i)) {
        --owned_span(m,i)->references;--m->info.native_references;
    }
    m->publication_mask=0;m->publication=0;return 0;
}
int capture_output_memory_cancel_allocation(struct capture_output_memory *m,uint32_t handle) {
    int rc=source_live(m);if(rc)return rc;
    for(unsigned i=CAPTURE_OUT_HEADER;i<=CAPTURE_OUT_AUX;++i) {
        if(m->spans[i].handle!=handle)continue;
        if(!(m->allocated_prefixes&(1u<<i)) || m->spans[i].references!=1)return -EBUSY;
        --m->spans[i].references;--m->info.native_references;m->allocated_prefixes&=~(1u<<i);return 0;
    }
    return -ESTALE;
}
int capture_output_memory_reply(struct capture_output_memory *m,const uint8_t q[40],uint64_t mapbase,uint8_t out[40]) {
    int rc=source_live(m);if(rc)return rc;
    if(!q || !out || mapbase!=m->info.original_map_base)return -EINVAL;
    uintptr_t a=(uintptr_t)q,b=(uintptr_t)out;
    if(a>UINTPTR_MAX-40 || b>UINTPTR_MAX-40 || (a<b+40 && b<a+40))return -EINVAL;
    uint16_t op=get16(q),option=get16(q+22);
    uint32_t handle=get32(q+8);unsigned index=0;
    if(op==0x20) {
        uint32_t unit=get32(q+4);
        if(unit==m->spans[CAPTURE_OUT_HEADER].unit_type)index=CAPTURE_OUT_HEADER;
        else if(unit==m->spans[CAPTURE_OUT_AUX].unit_type)index=CAPTURE_OUT_AUX;
        else return -ENODATA;
        if(option!=1 || handle || get32(q+12)!=UINT32_MAX || get16(q+20))return -ENOTSUP;
        if(m->allocated_prefixes&(1u<<index))return -EBUSY;
        if(m->info.native_references==UINT32_MAX)return -EOVERFLOW;
    } else {
        for(;index<CAPTURE_OUT_COUNT+CAPTURE_RAW_COUNT && owned_span(m,index)->handle!=handle;++index){}
        if(!handle || index==CAPTURE_OUT_COUNT+CAPTURE_RAW_COUNT)return -ESTALE;
        if(index>=CAPTURE_OUT_HEADER && index<=CAPTURE_OUT_AUX && !(m->allocated_prefixes&(1u<<index)))return -ESTALE;
    }
    struct capture_output_span *span=owned_span(m,index);
    if(op==0x21) {
        if(option!=1 || get32(q+4)!=span->unit_type)return -ENOTSUP;
        if(span->references==255 || m->info.native_references==UINT32_MAX)return -EOVERFLOW;
    } else if(op==0x2a || op==0x28) { if(option)return -ENOTSUP; }
    else if(op==0x23) { if(option!=2)return -ENOTSUP;if(!span->references)return -EALREADY; }
    else if(op!=0x20)return -ENOTSUP;
    uint8_t reply[40]={0};put16(reply,(uint16_t)(op|0x8000));put32(reply+12,span->handle);
    if(op!=0x23) {
        put16(reply+8,1);put32(reply+16,span->unit_type);put64(reply+24,span->alias);put32(reply+32,(uint32_t)span->capacity);
    }
    if(op==0x20){m->allocated_prefixes|=1u<<index;++span->references;++m->info.native_references;}
    if(op==0x21){++span->references;++m->info.native_references;}
    if(op==0x23){--span->references;--m->info.native_references;}
    if((m->publication_mask&(1u<<index)) && m->publication==1)m->publication_used=1;
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
    if(m->raw_memory){
        if(munmap(m->raw_memory,m->raw_total))return -errno;
        m->raw_memory=NULL;memset(m->raw_spans,0,sizeof m->raw_spans);
    }
    if(m->memory){if(munmap(m->memory,m->total))return -errno;m->memory=NULL;}
    rc=capture_input_drop(m->input,&m->input_hold);if(rc)return rc;
    memset(m,0,sizeof *m);free(m);return 0;
}
