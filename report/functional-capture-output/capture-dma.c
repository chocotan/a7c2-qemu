/* SPDX-License-Identifier: MIT */
#include "capture-dma.h"
#include <errno.h>
#include <string.h>
static uint64_t hash(const void *data,size_t bytes){const unsigned char *p=data;uint64_t h=UINT64_C(14695981039346656037);for(size_t i=0;i<bytes;++i)h=(h^p[i])*UINT64_C(1099511628211);return h;}
int capture_dma_thumbnail(struct capture_output_memory *owner,uint64_t destination,uint64_t source,size_t bytes,uint64_t *readback){
    if(!owner || !readback)return -EINVAL;
    struct capture_output_info info;int rc=capture_output_memory_info(owner,&info);if(rc)return rc;
    struct capture_output_span spans[CAPTURE_OUT_COUNT+CAPTURE_RAW_COUNT]={0};
    for(unsigned i=0;i<CAPTURE_OUT_COUNT;++i){
        rc=capture_output_memory_span(owner,(enum capture_output_role)i,&spans[i]);if(rc)return rc;
    }
    for(unsigned i=0;i<CAPTURE_RAW_COUNT;++i){
        rc=capture_output_memory_raw_span(owner,(enum capture_output_raw_role)i,&spans[CAPTURE_OUT_COUNT+i]);
        if(rc && rc!=-ENODATA)return rc;
    }
    const struct capture_output_span *from=NULL,*to=NULL;
    for(unsigned i=0;i<CAPTURE_OUT_COUNT+CAPTURE_RAW_COUNT;++i){
        const struct capture_output_span *span=&spans[i];
        if(!span->handle || !span->cpu || !span->alias || !span->capacity)continue;
        if(source>=span->alias && source-span->alias<=span->capacity &&
           (!bytes || source-span->alias<span->capacity))from=span;
        if((i==CAPTURE_OUT_HEADER || i==CAPTURE_OUT_AUX) && destination>=span->alias &&
           destination-span->alias<=span->capacity && (!bytes || destination-span->alias<span->capacity))to=span;
    }
    if(!from || !to)return -ERANGE;
    if(from->generation!=info.generation || to->generation!=info.generation || !from->references || !to->references)return -ESTALE;
    size_t source_offset=(size_t)(source-from->alias),destination_offset=(size_t)(destination-to->alias);
    if(from->bytes>from->capacity || bytes>to->capacity-destination_offset ||
       (bytes && (source_offset>from->bytes || bytes>from->bytes-source_offset)))return -ERANGE;
    /* Native RAW metadata includes empty areas; validate their owners without touching memory. */
    if(!bytes){*readback=hash(NULL,0);return 0;}
    unsigned char *out=(void *)(to->cpu+destination_offset);const void *in=(const void *)(from->cpu+source_offset);
    uint64_t before=hash(in,bytes);memcpy(out,in,bytes);
    if(memcmp(out,in,bytes) || hash(out,bytes)!=before || hash(in,bytes)!=before)return -EIO;
    *readback=before;return 0;
}
