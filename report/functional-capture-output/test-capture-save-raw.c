/* SPDX-License-Identifier: MIT */
/* Host-only source ownership checks; never original libarw/Fsys acceptance. */
#define _GNU_SOURCE
#include "capture-save.c"
#include <assert.h>
struct capture_output_memory { struct capture_output_info info;struct capture_output_span raw[CAPTURE_RAW_COUNT]; };
int capture_output_memory_info(struct capture_output_memory *m,struct capture_output_info *out){*out=m->info;return 0;}
int capture_output_memory_raw_span(struct capture_output_memory *m,enum capture_output_raw_role role,struct capture_output_span *out){*out=m->raw[role];return out->handle?0:-ENODATA;}
int capture_output_memory_span(struct capture_output_memory *m,enum capture_output_role role,struct capture_output_span *out){(void)m;(void)role;memset(out,0,sizeof *out);return 0;}
int capture_output_memory_hold(struct capture_output_memory *m,uint64_t *token){(void)m;*token=7;return 0;}
int capture_output_memory_drop(struct capture_output_memory *m,uint64_t token){(void)m;return token==7?0:-ESTALE;}
int main(void){
    unsigned char *header=NULL,*pixels=NULL;
    assert(!posix_memalign((void **)&header,4096,4*4096));pixels=header+3*4096;
    memset(header,0,4096);memcpy(header,"II\052\000\010\000\000\000",8);memset(pixels,3,4096);
    struct capture_output_memory owner={.info={.generation=1,.frame_token=2,.request_fnv1a64=3}};
    owner.raw[CAPTURE_RAW_COMMON]=(struct capture_output_span){.cpu=(uintptr_t)header,.capacity=4096,.bytes=4096,.generation=1,.handle=0x69000009,.unit_type=1};
    owner.raw[CAPTURE_RAW_CONTROL]=(struct capture_output_span){.cpu=(uintptr_t)header+4096,.capacity=4096,.bytes=4096,.generation=1,.handle=0x6900000a,.unit_type=1};
    owner.raw[CAPTURE_RAW_PREVIEW]=(struct capture_output_span){.cpu=(uintptr_t)header+8192,.capacity=4096,.bytes=4096,.generation=1,.handle=0x6900000b,.unit_type=1};
    owner.raw[CAPTURE_RAW_PIXELS]=(struct capture_output_span){.cpu=(uintptr_t)pixels,.capacity=4096,.bytes=4096,.generation=1,.handle=0x6900000c,.unit_type=1};
    struct capture_save *s=NULL;assert(!capture_save_prepare(&owner,0x1234,&s));assert(s->info.raw);
    struct fsys_write_layout layout={.count=2,.callback=0x1234,.cookie=9,.address_mode=1,.payload_bytes=8192,.expected_bytes=8192};
    strcpy(layout.path,"A:/DCIM/100MSDCF/DSC00001.ARW");
    layout.area[0]=(struct fsys_write_area){.address=(uintptr_t)header,.offset=0,.bytes=4096,.submitted_bytes=4096};
    layout.area[1]=(struct fsys_write_area){.address=(uintptr_t)pixels,.offset=4096,.bytes=4096,.submitted_bytes=4096};
    uint64_t hashes[FSYS_WRITE_AREAS]={hash(header,4096),hash(pixels,4096)};unsigned readable[FSYS_WRITE_AREAS]={1,1};
    assert(capture_save_match(s,1,&layout,hashes,readable)==1);
    s->info.token=0;strcpy(layout.path,"A:/DCIM/100MSDCF/DSC00001.JPG");
    assert(capture_save_match(s,1,&layout,hashes,readable)==-EBADMSG);
    s->info.first_error=0;strcpy(layout.path,"A:/DCIM/100MSDCF/DSC00001.ARW");pixels[0]^=1;
    assert(capture_save_match(s,1,&layout,hashes,readable)==-ESTALE);pixels[0]^=1;s->info.first_error=0;
    layout.area[0].address=4096;
    assert(capture_save_match(s,1,&layout,hashes,readable)==-EXDEV);
    assert(!capture_output_memory_drop(&owner,s->lease));free(s);free(header);return 0;
}
