/* SPDX-License-Identifier: MIT */
#include "functional-capture-raw-blobs.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
static struct capture_input_info source={.token=11,.model_instance=12,.model_lifetime=13,
    .config_generation=14,.source_fnv1a64=15,.request_fnv1a64=16,.request_cookie=17,
    .request_trigger=18,.width=7008,.height=4672,.stride=21024,.pixel_bytes=98224128};
static struct capture_output_info owner={.generation=7,.frame_token=11,.model_instance=12,
    .model_lifetime=13,.config_generation=14,.source_RGB_fnv=15,.request_fnv1a64=16,
    .request_cookie=17,.request_trigger=18};
/* Actual SOF bytes, with SOI stripped as required by CAPTURE_OUT_MAIN. */
static uint8_t jpg[]={255,192,0,17,8,0x12,0x40,0x1b,0x60,3,1,0x21,0,2,0x11,1,3,0x11,1,255,217};
static struct capture_output_span span={.generation=7};
int capture_output_memory_info(struct capture_output_memory *m,struct capture_output_info *out){
    (void)m;*out=owner;return 0;
}
int capture_output_memory_span(struct capture_output_memory *m,enum capture_output_role role,struct capture_output_span *out){
    (void)m;assert(role==CAPTURE_OUT_MAIN);*out=span;return 0;
}
static uint32_t u32(const uint8_t *p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
int main(void){
    static struct functional_raw_blobs b;
    struct capture_output_raw_input raw={0};span.cpu=(uintptr_t)jpg;span.bytes=sizeof jpg;span.capacity=sizeof jpg;
    int rc=functional_raw_blobs_build(&b,&source,&owner,&span,"virtual-cmos-v1",&raw);
    if(rc)fprintf(stderr,"initial build rc=%d width=%u height=%u stride=%u bytes=%zu\n",rc,source.width,source.height,source.stride,source.pixel_bytes);
    assert(!rc);
    assert(raw.frame_token==source.token && raw.config_generation==source.config_generation);
    assert(!raw.pixels && !raw.preview && !raw.thumbnail);
    assert(u32(b.common+92)==source.width && u32(b.common+96)==source.height);
    assert(b.common[0]==1 && !b.common[1]);
    for(unsigned i=4;i<92;++i)assert(b.common[i]==255);
    for(unsigned i=108;i<512;++i)assert(b.common[i]==255);
    for(unsigned i=RAW_BLOBS_HEADER_OFFSET;i<sizeof b.common;++i)assert(!b.common[i]);
    for(unsigned i=0;i<21;++i){
        const struct capture_output_raw_area *a=&raw.areas[i];
        size_t limit=i<10?raw.common_bytes:raw.control_bytes;
        assert(a->offset<=limit && a->bytes<=limit-a->offset);
        if(i!=0 && i!=8 && i!=10 && i!=11 && i!=14 && i!=15 && i!=16 && i!=20)
            assert(!a->offset && !a->bytes);
    }
    assert(u32(b.control)==0x10000 && !u32(b.control+4));
    assert(u32(b.control)>=0x72 && u32(b.control)<RAW_BLOBS_HEADER_BYTES/2);
    assert(raw.areas[11].bytes==4 && !u32(b.control+20));
    assert(raw.areas[14].bytes==104 && u32(b.control+32)==7008 && u32(b.control+36)==4672);
    assert(u32(b.control+40)==14 && u32(b.control+44)==1 && u32(b.control+48)==32803);
    assert(u32(b.control+60)==UINT32_MAX && u32(b.control+64)==UINT32_MAX);
    assert(u32(b.control+128)==4672 && !memcmp(b.control+136,"\1\0\2\1",4));
    assert(u32(b.control+140)==7008 && u32(b.control+144)==4672);
    assert(u32(b.control+148)==2 && u32(b.control+152)==1);
    /* Replay the original type4 parser's length and count reads. */
    const uint8_t *dir=b.control+raw.areas[20].offset;uint32_t start=u32(dir+8);
    assert(start<=raw.areas[20].bytes-4 && u32(dir+start)==0);
    struct capture_output_raw_input saved=raw;
    assert(functional_raw_blobs_build(&b,&source,&owner,&span,"physical-camera",&raw)==-ENOTSUP);
    assert(!memcmp(&saved,&raw,sizeof raw));
    struct capture_input_info stale=source;++stale.request_cookie;
    assert(functional_raw_blobs_build(&b,&stale,&owner,&span,"virtual-cmos-v1",&raw)==-ESTALE);
    for(size_t n=0;n<19;++n){span.bytes=n;assert(functional_raw_blobs_build(&b,&source,&owner,&span,"virtual-cmos-v1",&raw)<0);}
    span.bytes=sizeof jpg;uint8_t old=jpg[8];jpg[8]=0;
    assert(functional_raw_blobs_build(&b,&source,&owner,&span,"virtual-cmos-v1",&raw)==-ERANGE);jpg[8]=old;
    old=jpg[11];jpg[11]=0;assert(functional_raw_blobs_build(&b,&source,&owner,&span,"virtual-cmos-v1",&raw)==-ENOTSUP);jpg[11]=old;
    assert(!functional_capture_raw_native_metadata((void *)1,&source,"virtual-cmos-v1",&raw));
    assert(functional_capture_raw_native_metadata(NULL,&source,"virtual-cmos-v1",&raw)==-EINVAL);
    puts("PASS virtual RAW blobs: bounds, same-job identity, empty native directory, CFA, dimensions, preview sampling, rejection paths");
    return 0;
}
