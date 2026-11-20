/* SPDX-License-Identifier: MIT */
/* Standalone owner-registry fixture: compile this file with capture-dma.c. */
#include "capture-dma.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
struct capture_output_memory {
    struct capture_output_info info;
    struct capture_output_span jpeg[CAPTURE_OUT_COUNT],raw[CAPTURE_RAW_COUNT];
};
int capture_output_memory_info(struct capture_output_memory *owner,struct capture_output_info *out){*out=owner->info;return 0;}
int capture_output_memory_span(struct capture_output_memory *owner,enum capture_output_role role,struct capture_output_span *out){*out=owner->jpeg[role];return 0;}
int capture_output_memory_raw_span(struct capture_output_memory *owner,enum capture_output_raw_role role,struct capture_output_span *out){
    if(!owner->raw[role].handle)return -ENODATA;
    *out=owner->raw[role];return 0;
}
int main(void){
    unsigned char header[16384],aux[512],thumb[3169],jpeg[64],control[0x11000];
    memset(header,0xa5,sizeof header);memset(aux,0x5a,sizeof aux);memset(control,0xcc,sizeof control);
    for(size_t i=0;i<sizeof thumb;++i)thumb[i]=(unsigned char)(i*37u);
    memset(jpeg,0x77,sizeof jpeg);
    struct capture_output_memory owner={.info={.generation=7}};
    owner.jpeg[CAPTURE_OUT_HEADER]=(struct capture_output_span){.cpu=(uintptr_t)header,.alias=0x100000,.generation=7,.capacity=sizeof header,.handle=1,.references=1};
    owner.jpeg[CAPTURE_OUT_AUX]=(struct capture_output_span){.cpu=(uintptr_t)aux,.alias=0x200000,.generation=7,.capacity=sizeof aux,.handle=2,.references=1};
    owner.jpeg[CAPTURE_OUT_THUMB]=(struct capture_output_span){.cpu=(uintptr_t)jpeg,.alias=0x300000,.generation=7,.bytes=sizeof jpeg,.capacity=sizeof jpeg,.handle=3,.references=1};
    owner.raw[CAPTURE_RAW_THUMB]=(struct capture_output_span){.cpu=(uintptr_t)thumb,.alias=0x3ffc53000,.generation=7,.bytes=sizeof thumb,.capacity=4096,.handle=4,.references=1};
    owner.raw[CAPTURE_RAW_CONTROL]=(struct capture_output_span){.cpu=(uintptr_t)control,.alias=0x40000000,.generation=7,.bytes=16,.capacity=sizeof control,.handle=5,.references=1};
    uint64_t hash=0;const uint64_t dest=owner.jpeg[CAPTURE_OUT_HEADER].alias+0x1488;
    assert(!capture_dma_thumbnail(&owner,dest,owner.raw[CAPTURE_RAW_THUMB].alias,sizeof thumb,&hash));
    assert(hash && !memcmp(header+0x1488,thumb,sizeof thumb));
    assert(header[0x1487]==0xa5 && header[0x1488+sizeof thumb]==0xa5);
    assert(!capture_dma_thumbnail(&owner,owner.jpeg[CAPTURE_OUT_AUX].alias+7,owner.raw[CAPTURE_RAW_THUMB].alias+17,31,&hash));
    assert(!memcmp(aux+7,thumb+17,31));
    assert(!capture_dma_thumbnail(&owner,dest,owner.raw[CAPTURE_RAW_CONTROL].alias+0x10000,0,&hash));
    assert(hash==UINT64_C(14695981039346656037) && control[0x10000]==0xcc && header[0x1488]==thumb[0]);
    assert(!capture_dma_thumbnail(&owner,dest,owner.jpeg[CAPTURE_OUT_THUMB].alias,sizeof jpeg,&hash));
    assert(!memcmp(header+0x1488,jpeg,sizeof jpeg));
    hash=123;
    assert(capture_dma_thumbnail(&owner,dest,owner.raw[CAPTURE_RAW_THUMB].alias+1,sizeof thumb,&hash)==-ERANGE && hash==123);
    assert(capture_dma_thumbnail(&owner,owner.jpeg[CAPTURE_OUT_HEADER].alias+sizeof header-1,owner.raw[CAPTURE_RAW_THUMB].alias,2,&hash)==-ERANGE);
    assert(capture_dma_thumbnail(&owner,dest,0xdeadbeef,0,&hash)==-ERANGE);
    assert(capture_dma_thumbnail(&owner,0xdeadbeef,owner.raw[CAPTURE_RAW_CONTROL].alias,0,&hash)==-ERANGE);
    assert(capture_dma_thumbnail(&owner,owner.raw[CAPTURE_RAW_CONTROL].alias,owner.jpeg[CAPTURE_OUT_THUMB].alias,1,&hash)==-ERANGE);
    assert(capture_dma_thumbnail(&owner,dest,owner.raw[CAPTURE_RAW_CONTROL].alias+sizeof control+1,0,&hash)==-ERANGE);
    owner.raw[CAPTURE_RAW_THUMB].references=0;
    assert(capture_dma_thumbnail(&owner,dest,owner.raw[CAPTURE_RAW_THUMB].alias,1,&hash)==-ESTALE);
    owner.raw[CAPTURE_RAW_THUMB].references=1;owner.raw[CAPTURE_RAW_THUMB].generation=6;
    assert(capture_dma_thumbnail(&owner,dest,owner.raw[CAPTURE_RAW_THUMB].alias,1,&hash)==-ESTALE);
    owner.raw[CAPTURE_RAW_THUMB].generation=7;owner.jpeg[CAPTURE_OUT_HEADER].references=0;
    assert(capture_dma_thumbnail(&owner,dest,owner.raw[CAPTURE_RAW_THUMB].alias,1,&hash)==-ESTALE);
    owner.jpeg[CAPTURE_OUT_HEADER].references=1;owner.raw[CAPTURE_RAW_CONTROL].references=0;
    assert(capture_dma_thumbnail(&owner,dest,owner.raw[CAPTURE_RAW_CONTROL].alias+0x10000,0,&hash)==-ESTALE);
    puts("PASS owner-bound RAW thumbnail, partial copy, empty metadata, JPEG, bounds and live references");
    return 0;
}
