/* SPDX-License-Identifier: MIT */
#include "functional-capture-raw-blobs.h"
#include <errno.h>
#include <string.h>
static void p32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(v>>(8*i));}
/* CAPTURE_OUT_MAIN omits SOI; parse only the bounded marker stream before SOS. */
static int preview_info(const struct capture_output_span *span,uint32_t *width,
    uint32_t *height,uint32_t *hs,uint32_t *vs){
    if(!span->cpu || span->bytes<4 || span->bytes>span->capacity ||
       span->bytes>UINTPTR_MAX-span->cpu)return -EINVAL;
    const uint8_t *p=(const uint8_t *)span->cpu;size_t at=0;
    while(at<span->bytes){
        if(p[at++]!=255)return -EBADMSG;
        while(at<span->bytes && p[at]==255)++at;
        if(at==span->bytes)return -EBADMSG;
        unsigned marker=p[at++];
        if(marker==0xda || marker==0xd9 || marker==0 || marker==0xd8)return -EBADMSG;
        if(marker==1 || (marker>=0xd0 && marker<=0xd7))continue;
        if(span->bytes-at<2)return -EBADMSG;
        size_t n=(size_t)p[at]*256+p[at+1];
        if(n<2 || n>span->bytes-at)return -EBADMSG;
        if(marker==0xc0 || marker==0xc1 || marker==0xc2){
            if(n!=17 || p[at+2]!=8 || p[at+7]!=3)return -ENOTSUP;
            unsigned y=p[at+9],cb=p[at+12],cr=p[at+15];
            unsigned yh=y>>4,yv=y&15,ch=cb>>4,cv=cb&15;
            if(cb!=cr || !yh || !yv || !ch || !cv || yh>4 || yv>4 ||
               ch>yh || cv>yv || yh%ch || yv%cv)return -ENOTSUP;
            *height=(uint32_t)p[at+3]*256+p[at+4];
            *width=(uint32_t)p[at+5]*256+p[at+6];*hs=yh/ch;*vs=yv/cv;
            return *width && *height?0:-EBADMSG;
        }
        at+=n;
    }
    return -EBADMSG;
}
int functional_raw_blobs_build(struct functional_raw_blobs *b,
    const struct capture_input_info *s,const struct capture_output_info *o,
    const struct capture_output_span *preview,const char *profile,
    struct capture_output_raw_input *raw){
    if(!b || !s || !o || !preview || !raw || !profile)return -EINVAL;
    if(strcmp(profile,"virtual-cmos-v1"))return -ENOTSUP;
    if(!s->token || !s->model_instance || !s->model_lifetime || !s->config_generation ||
       s->token!=o->frame_token || s->model_instance!=o->model_instance ||
       s->model_lifetime!=o->model_lifetime || s->config_generation!=o->config_generation ||
       s->source_fnv1a64!=o->source_RGB_fnv || s->request_fnv1a64!=o->request_fnv1a64 ||
       s->request_cookie!=o->request_cookie || s->request_trigger!=o->request_trigger ||
       preview->generation!=o->generation)return -ESTALE;
    if(s->width!=7008 || s->height!=4672 || s->stride!=s->width*3u ||
       s->pixel_bytes!=(size_t)s->width*s->height*3u)return -ENOTSUP;
    uint32_t pw,ph,hs,vs;int rc=preview_info(preview,&pw,&ph,&hs,&vs);if(rc)return rc;
    if(pw!=s->width || ph!=s->height)return -ERANGE;
    struct capture_output_raw_input out={0};
    memset(b,0,sizeof *b);
    /* Only this scalar EXIF block uses -1 omission; no count/offset/pointer does. */
    memset(b->common,255,512);b->common[0]=1;b->common[1]=0;
    p32(b->common+92,s->width);p32(b->common+96,s->height);
    p32(b->common+100,pw);p32(b->common+104,ph);
    out.common=b->common;out.common_bytes=sizeof b->common;
    out.control=b->control;out.control_bytes=sizeof b->control;
    out.areas[0]=(struct capture_output_raw_area){0,512};
    out.areas[8]=(struct capture_output_raw_area){RAW_BLOBS_HEADER_OFFSET,RAW_BLOBS_HEADER_BYTES};
    /* Native destination offset for the zero-length private byte segment.
     * The writer subtracts0x72 and pads up to this offset before RAW IFDs. */
    p32(b->control,0x10000);p32(b->control+4,0);
    out.areas[10]=(struct capture_output_raw_area){0,20};
    out.areas[11]=(struct capture_output_raw_area){20,4};
    uint8_t *params=b->control+32;memset(params,255,CAPTURE_RAW_PARAM_BYTES);
    p32(params,s->width);p32(params+4,s->height);p32(params+8,14);
    p32(params+12,1);p32(params+16,32803);p32(params+20,1);p32(params+24,1);
    p32(params+48,2);p32(params+52,2);
    /* Native setters do not support omission for these private scalar tags.
     * Explicit virtual values0, never real camera calibration claims. */
    p32(params+56,0);p32(params+60,0);p32(params+100,0);
    p32(params+96,s->height);
    out.areas[14]=(struct capture_output_raw_area){32,CAPTURE_RAW_PARAM_BYTES};
    static const uint8_t grbg[4]={1,0,2,1};memcpy(b->control+136,grbg,4);
    out.areas[15]=(struct capture_output_raw_area){136,4};
    p32(b->control+140,pw);p32(b->control+144,ph);
    p32(b->control+148,hs);p32(b->control+152,vs);
    out.areas[16]=(struct capture_output_raw_area){140,16};
    /* Original type4 parser: header+8=start12; a u32 count0 needs four bytes. */
    p32(b->control+168,12);
    out.areas[20]=(struct capture_output_raw_area){160,16};
    out.frame_token=s->token;out.model_instance=s->model_instance;
    out.model_lifetime=s->model_lifetime;out.config_generation=s->config_generation;
    out.request_fnv1a64=s->request_fnv1a64;out.request_cookie=s->request_cookie;
    out.request_trigger=s->request_trigger;*raw=out;return 0;
}
int functional_capture_raw_native_metadata(struct capture_output_memory *owner,
    const struct capture_input_info *source,const char *profile,
    struct capture_output_raw_input *raw){
    /* shortcut: capture jobs are serialized, replace TLS with per-job allocation if parallelized. */
    static _Thread_local struct functional_raw_blobs storage;
    if(!owner)return -EINVAL;
    struct capture_output_info info;int rc=capture_output_memory_info(owner,&info);if(rc)return rc;
    struct capture_output_span preview;
    rc=capture_output_memory_span(owner,CAPTURE_OUT_MAIN,&preview);if(rc)return rc;
    return functional_raw_blobs_build(&storage,source,&info,&preview,profile,raw);
}
