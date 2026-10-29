/* SPDX-License-Identifier: MIT */
#include "cp-parameter-import.h"
#include <string.h>

static uint16_t u16(const unsigned char *p) { return (uint16_t)(p[0]|(uint16_t)p[1]<<8); }
static uint32_t u32(const unsigned char *p) { return (uint32_t)u16(p)|(uint32_t)u16(p+2)<<16; }
static int span(const void *p,size_t n) { return p && n<=UINTPTR_MAX-(uintptr_t)p; }
static int overlap(const void *a,size_t an,const void *b,size_t bn) {
    return (uintptr_t)a<(uintptr_t)b+bn && (uintptr_t)b<(uintptr_t)a+an;
}
static int property(const unsigned char *b,size_t n,uint32_t key,unsigned attr,
                    size_t length,uint32_t *first_word) {
    uint32_t sections=u32(b+16),properties=u32(b+20),data=u32(b+24);
    size_t table=0x100+(size_t)sections*6,entry,offset,bytes,capacity;
    if(sections>(n-0x100)/6 || data<table || data>n || properties>(data-table)/6)return -EINVAL;
    if((key>>16)>=sections)return -ENODATA;
    entry=0x100+(size_t)(key>>16)*6;
    uint32_t first=u32(b+entry+2);uint16_t count=u16(b+entry);
    if(first>properties || count>properties-first)return -EINVAL;
    if((key&0xffff)>=count)return -ENODATA;
    entry=table+((size_t)first+(key&0xffff))*6;
    if(u16(b+entry)!=attr)return -ENOTSUP;
    uint32_t packed=u32(b+entry+2);
    if(packed==UINT32_MAX)return -ENODATA;
    offset=packed&0xffffff;bytes=capacity=packed>>24;
    if(offset<data || offset>=n)return -EINVAL;
    if(bytes==255 || bytes==0) {
        size_t prefix=bytes?2:4;
        if(prefix>n-offset)return -EINVAL;
        capacity=bytes?u16(b+offset):u16(b+offset+2);bytes=u16(b+offset);offset+=prefix;
    }
    if(bytes!=length || bytes>capacity || capacity>n-offset)return -EMSGSIZE;
    *first_word=u32(b+offset);return 0;
}
int cp_parameter_import_inspect(const struct cp_property_stage *owner,
    const struct cp_start_state_guard *guard,const unsigned char *stage,size_t size,
    struct cp_parameter_import *out) {
    struct cp_property_stage_readback binding;
    struct cp_parameter_import result={0};
    if(!span(out,sizeof(*out)) || (uintptr_t)out%_Alignof(struct cp_parameter_import) ||
       !span(stage,size) || !span(owner,sizeof(*owner)) || !span(guard,sizeof(*guard)) ||
       overlap(out,sizeof(*out),stage,size) || overlap(out,sizeof(*out),owner,sizeof(*owner)) ||
       overlap(out,sizeof(*out),guard,sizeof(*guard)) || overlap(stage,size,owner,sizeof(*owner)) ||
       overlap(stage,size,guard,sizeof(*guard)))return -EINVAL;
    int rc=cp_property_stage_snapshot(owner,guard,&binding);if(rc)return rc;
    if(!binding.profile_known || !binding.mode_property_known ||
       binding.source!=CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE ||
       binding.repository!=CP_PROPERTY_STAGE_REPOSITORY_CP_PRIMARY)return -ENODATA;
    if(size!=CP_PROPERTY_STAGE_BYTES)return -EMSGSIZE;
    uint64_t hash=UINT64_C(14695981039346656037);
    for(size_t i=0;i<size;++i)hash=(hash^stage[i])*UINT64_C(1099511628211);
    if(hash!=binding.stage_fnv1a64 || hash!=CP_PROPERTY_STAGE_FNV1A64)return -EILSEQ;
    rc=property(stage,size,UINT32_C(0x00030160),0,4096,&result.header);if(rc)return rc;
    rc=property(stage,size,UINT32_C(0x0092001c),10,4,&result.flags);if(rc)return rc;
    result.source_sequence=binding.source_sequence;result.stage_fnv1a64=hash;result.origin=binding.source_origin;
    result.properties_consumed=1;
    result.import_selected=(unsigned char)(result.header==0xd68 && (result.flags&4));
    result.defaults_selected=(unsigned char)!result.import_selected;
    memcpy(out,&result,sizeof(result));return 0;
}
