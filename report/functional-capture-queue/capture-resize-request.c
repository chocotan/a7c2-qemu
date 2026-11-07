/* SPDX-License-Identifier: MIT */
#include "capture-resize-request.h"
#include <errno.h>
#include <string.h>
static uint32_t get32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint16_t get16(const uint8_t *p){return (uint16_t)(p[0]|(uint16_t)p[1]<<8);}
static uint64_t fnv(const uint8_t *p,size_t n){uint64_t h=UINT64_C(14695981039346656037);for(size_t i=0;i<n;++i)h=(h^p[i])*UINT64_C(1099511628211);return h;}
static int overlap(uintptr_t a,size_t an,uintptr_t b,size_t bn){return a<=b?b-a<an:a-b<bn;}
int capture_resize_request_build(struct capture_input *input,const uint8_t request[16],
    uint8_t packet[CAPTURE_RESIZE_REQUEST_BYTES],struct capture_input_mapping *hold){
    if(!request || !packet || !hold || (uintptr_t)packet>UINTPTR_MAX-CAPTURE_RESIZE_REQUEST_BYTES ||
       (uintptr_t)hold>UINTPTR_MAX-sizeof *hold || overlap((uintptr_t)packet,CAPTURE_RESIZE_REQUEST_BYTES,(uintptr_t)hold,sizeof *hold) ||
       overlap((uintptr_t)packet,CAPTURE_RESIZE_REQUEST_BYTES,(uintptr_t)request,16) ||
       overlap((uintptr_t)hold,sizeof *hold,(uintptr_t)request,16))return -EINVAL;
    if(hold->token || hold->address || hold->bytes)return -EALREADY;
    struct capture_input_info info;int rc=capture_input_info(input,&info);if(rc)return rc;
    if(overlap((uintptr_t)packet,CAPTURE_RESIZE_REQUEST_BYTES,info.parameter_cpu,128) ||
       overlap((uintptr_t)hold,sizeof *hold,info.parameter_cpu,128) ||
       overlap((uintptr_t)packet,CAPTURE_RESIZE_REQUEST_BYTES,info.metadata_cpu,1024) ||
       overlap((uintptr_t)hold,sizeof *hold,info.metadata_cpu,1024) ||
       overlap((uintptr_t)packet,CAPTURE_RESIZE_REQUEST_BYTES,info.pixel_cpu,info.pixel_bytes) ||
       overlap((uintptr_t)hold,sizeof *hold,info.pixel_cpu,info.pixel_bytes))return -EINVAL;
    if(get32(request)!=UINT32_C(0x40380005) || request[9] || request[10] || request[11] ||
       get32(request+4)!=info.request_cookie || request[8]!=info.request_trigger ||
       fnv(request,16)!=info.request_fnv1a64)return -ESTALE;
    const uint8_t *p=(const void *)info.parameter_cpu;
    unsigned width=get16(p+0x68),height=get16(p+0x6a);
    if(p[0x63]!=8 || !width || !height || width>8192 || height>8192 ||
       get32(p+0x6c) || p[0x70]>3 || p[0x71] || p[0x72])return -ENOTSUP;
    struct capture_input_mapping acquired;
    rc=capture_input_hold(input,&acquired);if(rc)return rc;
    uint8_t q[CAPTURE_RESIZE_REQUEST_BYTES]={0};q[2]=2;q[0x10]=128;q[0x25]=0x15;
    for(unsigned i=0;i<8;++i)q[0x28+i]=(uint8_t)((uint64_t)info.parameter_cpu>>(8*i));
    memcpy(packet,q,sizeof q);*hold=acquired;return 0;
}
