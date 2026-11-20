/* SPDX-License-Identifier: MIT */
#include "functional-camera-core.h"
#include "../../runtime/analysis/functional-still-format-abi.h"
#include "../functional-capture-input/capture-input.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t u32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24; }
static uint64_t u64(const uint8_t *p) { return u32(p) | (uint64_t)u32(p+4)<<32; }
static void p32(uint8_t *p,uint32_t v) { for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(v>>(8*i)); }
static void p64(uint8_t *p,uint64_t v) { for(unsigned i=0;i<8;++i)p[i]=(uint8_t)(v>>(8*i)); }
static uint64_t fnv(const uint8_t *p,size_t n) {
    uint64_t h=UINT64_C(14695981039346656037);
    for(size_t i=0;i<n;++i)h=(h^p[i])*UINT64_C(1099511628211);
    return h;
}
static void call(struct fcam_model *m,uint32_t op,const uint8_t *in,size_t n,uint8_t *out,size_t cap) {
    struct fcam_exec_result result={0};
    assert(!fcam_model_request(m,op,in,n,out,cap,&result));
    assert(!result.token && !result.total && !result.offset);
}
static uint8_t *collect(struct fcam_model *m,uint32_t op,const uint8_t *in,size_t n,size_t *bytes) {
    uint8_t chunk[65024];struct fcam_exec_result result={0};
    assert(!fcam_model_request(m,op,in,n,chunk,sizeof chunk,&result));
    assert(result.token && result.total && result.total<=128u*1024u*1024u);
    uint8_t *whole=malloc((size_t)result.total);assert(whole);
    const uint64_t token=result.token,total=result.total;
    size_t used=result.used;memcpy(whole,chunk,used);
    while(used<total) {
        uint8_t read[24]={0};p64(read,token);p64(read+8,used);p32(read+16,sizeof chunk);
        assert(!fcam_model_request(m,FCAM_OP_READ_RESULT,read,sizeof read,chunk,sizeof chunk,&result));
        assert(result.token==token && result.total==total && result.offset==used && result.used);
        memcpy(whole+used,chunk,result.used);used+=result.used;
    }
    uint8_t release[16]={0};p64(release,token);p64(release+8,fnv(whole,used));
    call(m,FCAM_OP_RELEASE_RESULT,release,sizeof release,NULL,0);
    *bytes=used;return whole;
}
int main(int argc,char **argv) {
    assert(argc==2);
    struct fcam_model *m=fcam_model_create(101);assert(m);
    uint8_t active[128],photo[128],query[16]={5,0,0x38,0x40};
    p32(query+4,29);query[8]=2;
    call(m,FCAM_OP_INIT,NULL,0,active,sizeof active);
    struct fcam_exec_result result={0};
    memset(photo,0xa5,sizeof photo);
    assert(fcam_model_request(m,FCAM_OP_CAPTURE_STATE,query,sizeof query,photo,sizeof photo,&result)==-ENODATA);
    for(size_t i=0;i<sizeof photo;++i)assert(photo[i]==0xa5);
    uint8_t route[16]={1,5,5},response[176];
    call(m,FCAM_OP_VDF_PATH,route,sizeof route,response,sizeof response);
    call(m,FCAM_OP_STILL_FORMAT,fcam_still_format_initial,16,response,sizeof response);
    call(m,FCAM_OP_STATE,NULL,0,active,sizeof active);
    call(m,FCAM_OP_CAPTURE_STATE,query,sizeof query,photo,sizeof photo);
    assert(u32(active+8)==640 && u32(active+12)==480);
    assert(u32(photo+8)==7008 && u32(photo+12)==4672);
    assert(!memcmp(active,photo,8) && !memcmp(active+16,photo+16,112));
    uint8_t after[128];call(m,FCAM_OP_STATE,NULL,0,after,sizeof after);
    assert(!memcmp(active,after,sizeof active));
    size_t bytes=0;uint8_t *frame=collect(m,FCAM_OP_FRAME_CAPTURE,query,sizeof query,&bytes);
    assert(bytes==96u+98224128u && u32(frame+48)==7008 && u32(frame+52)==4672 && u32(frame+56)==21024);
    assert(u64(frame+64)==98224128u && u64(frame+72)==fnv(frame+96,bytes-96));
    assert(u64(frame+32)==u64(photo+56) && u64(frame+88)==fnv(query,sizeof query));
    uint64_t token=u64(frame+8);
    uint8_t parameters[128]={0};parameters[0x63]=8;
    struct capture_input *input=NULL;struct capture_input_info info;
    assert(!capture_input_create(frame,bytes,query,parameters,&input));
    assert(!capture_input_info(input,&info) && info.width==7008 && info.height==4672 && info.pixel_bytes==98224128u);
    assert(!capture_input_destroy(input));free(frame);
    uint8_t encode[32]={0};p64(encode,token);p32(encode+16,1);p32(encode+20,7008);p32(encode+24,4672);p32(encode+28,90);
    uint8_t *jpeg=collect(m,FCAM_OP_FRAME_STILL,encode,sizeof encode,&bytes);
    assert(bytes>4 && jpeg[0]==255 && jpeg[1]==216 && jpeg[bytes-2]==255 && jpeg[bytes-1]==217);
    FILE *file=fopen(argv[1],"wb");assert(file);
    assert(fwrite(jpeg,1,bytes,file)==bytes && !fclose(file));free(jpeg);
    uint8_t release[16]={0};p64(release,token);p32(release+8,1);
    call(m,FCAM_OP_FRAME_RELEASE,release,sizeof release,NULL,0);
    call(m,FCAM_OP_STATE,NULL,0,after,sizeof after);
    assert(u32(after+8)==640 && u32(after+12)==480 && !u32(after+104));
    assert(fcam_model_request(m,FCAM_OP_CAPTURE_STATE,query,15,photo,sizeof photo,&result)==-EINVAL);
    fcam_model_destroy(m);
    puts("FULL_RESOLUTION_PHOTO_AND_DISPLAY_SEPARATION_PASS");return 0;
}
