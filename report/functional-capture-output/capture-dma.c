/* SPDX-License-Identifier: MIT */
#include "capture-dma.h"
#include <errno.h>
#include <string.h>
static uint64_t hash(const void *data,size_t bytes){const unsigned char *p=data;uint64_t h=UINT64_C(14695981039346656037);for(size_t i=0;i<bytes;++i)h=(h^p[i])*UINT64_C(1099511628211);return h;}
int capture_dma_thumbnail(struct capture_output_memory *owner,uint64_t destination,uint64_t source,size_t bytes,uint64_t *readback){
    if(!owner || !readback)return -EINVAL;
    struct capture_output_info info;int rc=capture_output_memory_info(owner,&info);if(rc)return rc;
    struct capture_output_span header,thumb;
    rc=capture_output_memory_span(owner,CAPTURE_OUT_HEADER,&header);if(rc)return rc;
    rc=capture_output_memory_span(owner,CAPTURE_OUT_THUMB,&thumb);if(rc)return rc;
    if(header.generation!=info.generation || thumb.generation!=info.generation || !header.references || !thumb.references)return -ESTALE;
    if(source!=thumb.alias || !bytes || bytes!=thumb.bytes || bytes>thumb.capacity ||
       destination<header.alias || destination-header.alias>=header.capacity || bytes>header.capacity-(destination-header.alias))return -ERANGE;
    unsigned char *out=(void *)(header.cpu+(uintptr_t)(destination-header.alias));const void *in=(const void *)thumb.cpu;
    uint64_t before=hash(in,bytes);memcpy(out,in,bytes);
    if(memcmp(out,in,bytes) || hash(out,bytes)!=before || hash(in,bytes)!=before)return -EIO;
    *readback=before;return 0;
}
