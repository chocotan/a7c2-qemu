/* SPDX-License-Identifier: MIT */
#include "capture-output-memory.h"
#include "capture-dma.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t u32(const uint8_t *p) { return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static uint64_t u64(const uint8_t *p) { return u32(p)|(uint64_t)u32(p+4)<<32; }
static void p32(uint8_t *p,uint32_t x) { for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(x>>(8*i)); }
static uint8_t *read_file(const char *path,size_t *bytes) {
    FILE *f=fopen(path,"rb");assert(f && !fseek(f,0,SEEK_END));long n=ftell(f);assert(n>0);rewind(f);
    uint8_t *p=malloc((size_t)n);assert(p && fread(p,1,(size_t)n,f)==(size_t)n && !fclose(f));*bytes=(size_t)n;return p;
}
static void request(uint8_t q[40],unsigned op,uint32_t handle,unsigned option) {
    memset(q,0,40);q[0]=(uint8_t)op;p32(q+4,1);p32(q+8,handle);q[22]=(uint8_t)option;
}
int main(int argc,char **argv) {
    /* Same real frame/JPEG fixture arguments as test-output-memory.c.
     * Synthetic opaque metadata below tests ownership only, not native validity. */
    assert(argc==4);size_t nf,nm,nt;
    uint8_t *frame=read_file(argv[1],&nf),*main=read_file(argv[2],&nm),*thumb=read_file(argv[3],&nt);
    uint8_t original[16]={5,0,0x38,0x40,0,0,0,0,2},parameters[128]={0};
    memcpy(original+4,frame+80,4);parameters[0x63]=8;
    struct capture_input *input=NULL;assert(!capture_input_create(frame,nf,original,parameters,&input));
    struct capture_input_info in;assert(!capture_input_info(input,&in));
    struct capture_output_memory *owner=NULL;assert(!capture_output_memory_create(input,main,nm,thumb,nt,0,&owner));
    struct capture_output_info identity;assert(!capture_output_memory_info(owner,&identity));
    uint8_t descriptor[CAPTURE_RAW_INFO_BYTES],unchanged[CAPTURE_RAW_INFO_BYTES];memset(unchanged,0xa5,sizeof unchanged);
    memcpy(descriptor,unchanged,sizeof descriptor);
    assert(capture_output_memory_raw_info(owner,descriptor)==-ENODATA && !memcmp(descriptor,unchanged,sizeof descriptor));
    assert(capture_output_memory_publish_raw_begin(owner,0)==-ENODATA);
    uint8_t common[8192],control[512];memset(common,0xff,sizeof common);memset(control,0xff,sizeof control);
    size_t pixel_bytes=(size_t)in.width*in.height*2;uint8_t *pixels=calloc(1,pixel_bytes);assert(pixels);
    pixels[0]=0x34;pixels[1]=0x12;
    struct capture_output_raw_input raw={.common=common,.common_bytes=sizeof common,.control=control,.control_bytes=sizeof control,
        .pixels=pixels,.pixel_bytes=pixel_bytes,.preview=main,.preview_bytes=nm,.thumbnail=thumb,.thumbnail_bytes=nt,
        .frame_token=identity.frame_token,.model_instance=identity.model_instance,.model_lifetime=identity.model_lifetime,
        .config_generation=identity.config_generation,.request_fnv1a64=identity.request_fnv1a64,
        .request_cookie=identity.request_cookie,.request_trigger=identity.request_trigger};
    raw.areas[0]=(struct capture_output_raw_area){0,512};
    raw.areas[3]=(struct capture_output_raw_area){512,8};
    raw.areas[8]=(struct capture_output_raw_area){4096,4096};
    raw.areas[10]=(struct capture_output_raw_area){0,64};
    raw.areas[14]=(struct capture_output_raw_area){64,CAPTURE_RAW_PARAM_BYTES};
    raw.areas[15]=(struct capture_output_raw_area){168,4};
    raw.areas[16]=(struct capture_output_raw_area){176,CAPTURE_RAW_PARAM_BYTES};
    uint8_t *params=control+64;
    p32(params,in.width);p32(params+4,in.height);p32(params+8,14);p32(params+12,1);p32(params+16,32803);
    p32(params+20,1);p32(params+24,1);p32(params+48,2);p32(params+52,2);p32(params+96,in.height);
    const uint8_t cfa[4]={1,0,2,1};memcpy(control+168,cfa,4);
    ++raw.frame_token;assert(capture_output_memory_add_raw(owner,&raw)==-ESTALE);--raw.frame_token;
    raw.areas[14].bytes=0x67;assert(capture_output_memory_add_raw(owner,&raw)==-EINVAL);raw.areas[14].bytes=0x68;
    raw.areas[14].offset=sizeof control-1;assert(capture_output_memory_add_raw(owner,&raw)==-ERANGE);raw.areas[14].offset=64;
    raw.areas[9].bytes=1;assert(capture_output_memory_add_raw(owner,&raw)==-EINVAL);raw.areas[9].bytes=0;
    raw.areas[0].bytes=0;assert(capture_output_memory_add_raw(owner,&raw)==-ENODATA);raw.areas[0].bytes=512;
    raw.areas[8].offset=0;assert(capture_output_memory_add_raw(owner,&raw)==-EINVAL);raw.areas[8].offset=4096;
    control[168]=0;assert(capture_output_memory_add_raw(owner,&raw)==-ENOTSUP);control[168]=1;
    p32(params+12,32767);assert(capture_output_memory_add_raw(owner,&raw)==-ENOTSUP);p32(params+12,1);
    --raw.pixel_bytes;assert(capture_output_memory_add_raw(owner,&raw)==-ERANGE);++raw.pixel_bytes;
    pixels[1]=0x80;assert(capture_output_memory_add_raw(owner,&raw)==-ERANGE);pixels[1]=0x12;
    assert(!capture_output_memory_info(owner,&identity) && !identity.native_references);
    assert(!capture_output_memory_add_raw(owner,&raw));
    assert(capture_output_memory_add_raw(owner,&raw)==-EBUSY);
    assert(!capture_output_memory_raw_info(owner,descriptor));
    struct capture_output_span spans[CAPTURE_RAW_COUNT],jpeg_main;
    assert(!capture_output_memory_span(owner,CAPTURE_OUT_MAIN,&jpeg_main));
    for(unsigned i=0;i<CAPTURE_RAW_COUNT;++i) {
        assert(!capture_output_memory_raw_span(owner,(enum capture_output_raw_role)i,&spans[i]));
        assert(spans[i].handle && spans[i].unit_type==1 && !(spans[i].cpu%4096) && spans[i].capacity>=spans[i].bytes);
        assert(spans[i].handle!=jpeg_main.handle && spans[i].generation==identity.generation);
        for(unsigned j=0;j<i;++j)assert(spans[i].handle!=spans[j].handle);
    }
    assert(u32(descriptor)==spans[CAPTURE_RAW_COMMON].handle);
    assert(u32(descriptor+0x30)==u32(descriptor) && u32(descriptor+0x80)==u32(descriptor));
    assert(u32(descriptor+0xa0)==spans[CAPTURE_RAW_CONTROL].handle);
    assert(u32(descriptor+0xe0)==u32(descriptor+0xa0) && u32(descriptor+0xf0)==u32(descriptor+0xa0));
    assert(u32(descriptor+0x110)==spans[CAPTURE_RAW_PREVIEW].handle);
    assert(u32(descriptor+0x120)==spans[CAPTURE_RAW_PIXELS].handle && u32(descriptor+0x128)==pixel_bytes);
    assert(u32(descriptor+0x90)==spans[CAPTURE_RAW_THUMB].handle &&
           u32(descriptor+0x98)==nt && u32(descriptor+0x9c)==spans[CAPTURE_RAW_THUMB].unit_type);
    assert(u32(descriptor+0x130)==0);
    assert(!memcmp((void *)spans[CAPTURE_RAW_PIXELS].cpu,pixels,pixel_bytes));
    assert(spans[CAPTURE_RAW_PREVIEW].bytes==nm+CAPTURE_RAW_PREVIEW_PREFIX_BYTES);
    assert(u32(descriptor+0x118)==nm+CAPTURE_RAW_PREVIEW_PREFIX_BYTES);
    for(unsigned i=0;i<CAPTURE_RAW_PREVIEW_PREFIX_BYTES;++i)
        assert(!((uint8_t *)spans[CAPTURE_RAW_PREVIEW].cpu)[i]);
    assert(!memcmp((void *)(spans[CAPTURE_RAW_PREVIEW].cpu+CAPTURE_RAW_PREVIEW_PREFIX_BYTES),main,nm));
    assert(!memcmp((void *)spans[CAPTURE_RAW_THUMB].cpu,thumb,nt));
    assert(!memcmp((void *)jpeg_main.cpu,main+2,nm-2));
    for(unsigned i=0;i<4096;++i)assert(!((uint8_t *)spans[CAPTURE_RAW_COMMON].cpu)[4096+i] && common[4096+i]==255);
    /* Producer buffers are no longer owners. Native consumers may mutate preview/header only in the retained copies. */
    pixels[0]^=1;assert(((uint8_t *)spans[CAPTURE_RAW_PIXELS].cpu)[0]==0x34);pixels[0]^=1;
    uint8_t q[40],r[40],old[40];memset(old,0xa5,sizeof old);memcpy(r,old,sizeof r);
    request(q,0x21,spans[0].handle,1);p32(q+4,2);
    assert(capture_output_memory_reply(owner,q,0,r)==-ENOTSUP && !memcmp(r,old,40));
    request(q,0x20,0,1);p32(q+4,1);p32(q+12,UINT32_MAX);
    assert(capture_output_memory_reply(owner,q,0,r)==-ENODATA);
    assert(!capture_output_memory_publish_raw_begin(owner,0));
    assert(!capture_output_memory_info(owner,&identity) && identity.native_references==CAPTURE_RAW_COUNT);
    assert(!capture_output_memory_publish_cancel(owner));
    assert(!capture_output_memory_publish_raw_begin(owner,1));
    assert(!capture_output_memory_info(owner,&identity) && identity.native_references==CAPTURE_RAW_COUNT+3);
    assert(!capture_output_memory_publish_cancel(owner));
    assert(!capture_output_memory_info(owner,&identity) && !identity.native_references);
    for(unsigned role=CAPTURE_OUT_HEADER;role<=CAPTURE_OUT_AUX;++role){
        struct capture_output_span prefix;
        assert(!capture_output_memory_span(owner,(enum capture_output_role)role,&prefix));
        uint32_t unit=role==CAPTURE_OUT_HEADER?0x80561:0x66e;
        assert(prefix.unit_type==unit);
        if(role==CAPTURE_OUT_AUX)assert(prefix.capacity>=raw.areas[8].bytes+14u);
        request(q,0x20,0,1);p32(q+4,role==CAPTURE_OUT_HEADER?0x80d61:0x27f);p32(q+12,UINT32_MAX);
        assert(capture_output_memory_reply(owner,q,0,r)==-ENODATA);
        p32(q+4,unit);p32(q+12,0);
        assert(capture_output_memory_reply(owner,q,0,r)==-ENOTSUP);
        p32(q+12,UINT32_MAX);
        assert(!capture_output_memory_reply(owner,q,0,r));
        assert(u32(r+12)==prefix.handle && u32(r+16)==unit && u32(r+32)==prefix.capacity);
        assert(capture_output_memory_reply(owner,q,0,r)==-EBUSY);
        assert(!capture_output_memory_cancel_allocation(owner,prefix.handle));
    }
    /* RAW-only publishes no standalone JPEG references but keeps embedded JPEG. */
    assert(!capture_output_memory_publish_raw_begin(owner,0));
    assert(!capture_output_memory_span(owner,CAPTURE_OUT_MAIN,&jpeg_main) && !jpeg_main.references);
    request(q,0x2a,spans[0].handle,0);assert(!capture_output_memory_reply(owner,q,0,r));
    assert(u64(r+24)==spans[0].alias && u32(r+32)==spans[0].capacity);
    assert(capture_output_memory_publish_cancel(owner)==-EBUSY);
    assert(!capture_output_memory_publish_commit(owner));
    /* The original RAW envelope adds14 bytes after dropping a4-byte input prefix. */
    struct capture_output_span aux;
    assert(!capture_output_memory_span(owner,CAPTURE_OUT_AUX,&aux));
    request(q,0x20,0,1);p32(q+4,0x66e);p32(q+12,UINT32_MAX);
    assert(!capture_output_memory_reply(owner,q,0,r));
    uint8_t *extra=(uint8_t *)spans[CAPTURE_RAW_COMMON].cpu+raw.areas[8].offset;
    for(size_t i=0;i<raw.areas[8].bytes;++i)extra[i]=(uint8_t)(i*37u+3u);
    memset((void *)aux.cpu,0xb7,aux.capacity);
    uint64_t copied_hash=0;
    assert(!capture_dma_thumbnail(owner,aux.alias+14,spans[CAPTURE_RAW_COMMON].alias+raw.areas[8].offset+4,
        raw.areas[8].bytes-4,&copied_hash));
    assert(!memcmp((void *)(aux.cpu+14),extra+4,raw.areas[8].bytes-4));
    assert(((uint8_t *)aux.cpu)[13]==0xb7 && ((uint8_t *)aux.cpu)[raw.areas[8].bytes+10]==0xb7);
    request(q,0x23,aux.handle,2);assert(!capture_output_memory_reply(owner,q,0,r));
    uint64_t export_token;assert(!capture_output_memory_hold(owner,&export_token));
    assert(capture_output_memory_destroy(owner)==-EBUSY);
    for(unsigned i=0;i<CAPTURE_RAW_COUNT;++i) {
        request(q,0x21,spans[i].handle,1);assert(!capture_output_memory_reply(owner,q,0,r));
        request(q,0x23,spans[i].handle,2);assert(!capture_output_memory_reply(owner,q,0,r));
        assert(!capture_output_memory_reply(owner,q,0,r));
        assert(capture_output_memory_reply(owner,q,0,r)==-EALREADY);
    }
    assert(!capture_output_memory_info(owner,&identity) && !identity.native_references);
    assert(capture_output_memory_destroy(owner)==-EBUSY);
    assert(!capture_output_memory_drop(owner,export_token));assert(!capture_output_memory_destroy(owner));owner=NULL;
    assert(!capture_output_memory_create(input,main,nm,thumb,nt,0,&owner));
    request(q,0x2a,spans[0].handle,0);assert(capture_output_memory_reply(owner,q,0,r)==-ESTALE);
    raw.thumbnail=NULL;raw.thumbnail_bytes=0;
    assert(capture_output_memory_add_raw(owner,&raw)==-EINVAL);
    assert(capture_output_memory_raw_info(owner,descriptor)==-ENODATA);
    assert(capture_output_memory_raw_span(owner,CAPTURE_RAW_THUMB,&spans[0])==-ENODATA);
    assert(capture_output_memory_publish_raw_begin(owner,0)==-ENODATA);
    assert(!capture_output_memory_info(owner,&identity) && !identity.native_references);
    assert(!capture_output_memory_destroy(owner));assert(!capture_input_destroy(input));
    free(pixels);free(frame);free(main);free(thumb);
    puts("PASS RAW owner grouping, bounds, identity, GRBG, uncompressed14LE, preview, reserve/share/free, JPEG compatibility");
    return 0;
}
