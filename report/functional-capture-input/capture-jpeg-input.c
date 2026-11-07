/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "capture-jpeg-input.h"
#include <dlfcn.h>
#include <errno.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>
#define FRAMEWORK_SHA "620e04a9cd51e65bd190ed1d5459b7235ff5a4109bc6498df342972621991d47"
static pid_t reader_owner;
struct typed_api {
    void (*yc_ctor)(void *,uint64_t,uint32_t,uint32_t),(*yc_dtor)(void *);
    void (*entry_ctor)(void *),(*entry_dtor)(void *),(*get_all)(void *,void *);
    uint32_t (*get_entry)(void *,void *);
};
static struct typed_api api;
static uint16_t u16(const uint8_t *p) { return (uint16_t)((uint16_t)p[0]|(uint16_t)p[1]<<8); }
static uint32_t u32(const uint8_t *p) { return (uint32_t)u16(p)|(uint32_t)u16(p+2)<<16; }
static uint64_t u64(const uint8_t *p) { return u32(p)|(uint64_t)u32(p+4)<<32; }
static void p32(uint8_t *p,uint32_t v) { for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(v>>(8*i)); }
static void p64(uint8_t *p,uint64_t v) { for(unsigned i=0;i<8;++i)p[i]=(uint8_t)(v>>(8*i)); }
static uint64_t digest(const uint8_t *p,size_t bytes) {
    uint64_t h=UINT64_C(14695981039346656037);
    for(size_t i=0;i<bytes;++i)h=(h^p[i])*UINT64_C(1099511628211);
    return h;
}
#define LOAD(field,name) do { void *symbol=dlsym(RTLD_NEXT,name);if(!symbol)return -ENOSYS; \
    _Static_assert(sizeof candidate.field==sizeof symbol,"POSIX function pointer ABI"); \
    memcpy(&candidate.field,&symbol,sizeof symbol); } while(0)
int capture_jpeg_input_bind(const char *sha) {
    if(reader_owner && reader_owner!=getpid())return -ECHILD;
    if(!sha || strcmp(sha,FRAMEWORK_SHA))return -ELIBBAD;
    struct typed_api candidate;
    LOAD(yc_ctor,"_ZN26C_DataflowInfra_StdData_YCC1Emjj");
    LOAD(yc_dtor,"_ZN26C_DataflowInfra_StdData_YCD1Ev");
    LOAD(entry_ctor,"_ZN35C_DataflowInfra_Entry_ImageSizeInfoC1Ev");
    LOAD(entry_dtor,"_ZN35C_DataflowInfra_Entry_ImageSizeInfoD1Ev");
    LOAD(get_entry,"_ZN26C_DataflowInfra_StdData_YC22GetEntry_ImageSizeInfoEP35C_DataflowInfra_Entry_ImageSizeInfo");
    LOAD(get_all,"_ZN35C_DataflowInfra_Entry_ImageSizeInfo11GetData_AllEPN19DataflowInfra_StdYc22PIN_YC_IMAGE_SIZE_INFOE");
    api=candidate;reader_owner=getpid();return 0;
}
#undef LOAD
int capture_jpeg_input_prepare(struct capture_input *owner,const uint8_t body[80],
    uint32_t selector,uint32_t quality,struct capture_jpeg_input *out) {
    if(!reader_owner)return -ENODEV;
    if(reader_owner!=getpid())return -ECHILD;
    if(!owner || !body || !out || selector>2 || !quality || quality>100)return -EINVAL;
    if(out->owner || out->metadata.token || out->pixels.token || out->prepared)return -EBUSY;
    const uint32_t width=u16(body+0x40),height=u16(body+0x42);
    if(u16(body+4)!=80 || u16(body+8)!=7 || u16(body+10) ||
        !width || width>8192 || !height || height>8192)return -EPROTO;
    struct capture_jpeg_input candidate={.owner=owner};
    int rc=capture_input_info(owner,&candidate.source);if(rc)return rc;
    if(u32(body+0x18) || u32(body+0x1c)!=candidate.source.metadata_unit || u32(body+0x20))return -ENODATA;
    rc=capture_input_metadata_read(owner,candidate.source.metadata_unit,0,1024,&candidate.metadata);
    if(rc)return rc;
    *out=candidate;
    _Alignas(16) uint8_t yc[512]={0},entry[512]={0},image[72]={0};
    api.yc_ctor(yc,candidate.metadata.address,1024,0);api.entry_ctor(entry);
    const uint64_t before=digest((const void *)candidate.metadata.address,1024);
    uint32_t code=api.get_entry(yc,entry);
    if(!code)api.get_all(entry,image);
    api.entry_dtor(entry);api.yc_dtor(yc);
    if(code)return -ENOTSUP;
    if(digest((const void *)candidate.metadata.address,1024)!=before)return -EBADMSG;
    const struct capture_input_info *s=&candidate.source;
    if(u32(image) || u32(image+4)!=s->pixel_unit || u64(image+8) || u64(image+16) ||
        u32(image+0x18) || image[0x1c]!=1 || image[0x1d] || image[0x1f] || image[0x20] ||
        image[0x21]!=8 || image[0x22]!=1 || image[0x23]!=1 || image[0x24]!=2 || image[0x25] ||
        u16(image+0x2a) || u16(image+0x2c) || u16(image+0x2e)!=s->width ||
        u16(image+0x30)!=s->height || u16(image+0x32) || u16(image+0x34) ||
        u16(image+0x36)!=s->width || u16(image+0x38)!=s->height || u16(image+0x3a) ||
        u16(image+0x3c) || u16(image+0x3e)!=s->width || u16(image+0x40)!=s->height ||
        u16(image+0x42))return -ENOTSUP;
    rc=capture_input_pixels(owner,s->pixel_unit,0,s->pixel_bytes,&out->pixels);
    if(rc)return rc;
    if(selector==1 && quality>CAPTURE_JPEG_THUMB_MAX_QUALITY)quality=CAPTURE_JPEG_THUMB_MAX_QUALITY;
    p64(out->model_request,s->token);p32(out->model_request+8,selector);
    p32(out->model_request+16,1);p32(out->model_request+20,width);
    p32(out->model_request+24,height);p32(out->model_request+28,quality);
    memcpy(out->image_size_info,image,sizeof image);
    out->metadata_fnv1a64=before;out->prepared=1;return 0;
}
int capture_jpeg_input_release(struct capture_jpeg_input *input) {
    if(!input || !input->owner)return -EINVAL;
    int rc=0;
    if(input->pixels.token) {
        int released=capture_input_release_pixels(input->owner,&input->pixels);
        if(released)rc=released;else memset(&input->pixels,0,sizeof input->pixels);
    }
    if(input->metadata.token) {
        int released=capture_input_release_metadata(input->owner,&input->metadata);
        if(released && !rc)rc=released;else if(!released)memset(&input->metadata,0,sizeof input->metadata);
    }
    if(!rc)memset(input,0,sizeof *input);
    return rc;
}
