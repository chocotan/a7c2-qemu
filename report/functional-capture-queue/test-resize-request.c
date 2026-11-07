/* SPDX-License-Identifier: MIT */
#include "../functional-capture-input/capture-input.c"
#include "capture-resize-request.h"
#include <assert.h>
#include <stdio.h>
#include <sys/wait.h>
static void load_frame(const char *name,uint8_t **out,size_t *size){FILE *f=fopen(name,"rb");assert(f);assert(!fseek(f,0,SEEK_END));long n=ftell(f);assert(n>96);rewind(f);*size=(size_t)n;*out=malloc(*size);assert(*out && fread(*out,1,*size,f)==*size);assert(!fclose(f));}
int main(int argc,char **argv){
    assert(argc==2);uint8_t *frame;size_t size;load_frame(argv[1],&frame,&size);
    uint8_t request[16]={5,0,0x38,0x40,29,0,0,0,2},p[128]={0},q[48],before[48],saved[16];
    p[0x63]=8;put16(p+0x68,128);put16(p+0x6a,64);p[0x70]=2;
    struct capture_input *input=NULL;assert(!capture_input_create(frame,size,request,p,&input));
    struct capture_input_info info;assert(!capture_input_info(input,&info));
    struct capture_input_mapping hold={0};memset(q,0xa5,sizeof q);memcpy(before,q,sizeof q);memcpy(saved,request,16);
    uint8_t wrong[16];memcpy(wrong,request,16);wrong[4]^=1;
    assert(capture_resize_request_build(input,wrong,q,&hold)==-ESTALE && !hold.token && !memcmp(q,before,48));
    for(unsigned i=0;i<16;++i){memcpy(wrong,request,16);wrong[i]^=1;assert(capture_resize_request_build(input,wrong,q,&hold)==-ESTALE && !hold.token && !memcmp(q,before,48));}
    assert(capture_resize_request_build(input,request,(void *)info.parameter_cpu,&hold)==-EINVAL);
    assert(capture_resize_request_build(input,request,(void *)info.metadata_cpu,&hold)==-EINVAL);
    assert(capture_resize_request_build(input,request,(void *)info.pixel_cpu,&hold)==-EINVAL);
    assert(capture_resize_request_build(input,request,q,(void *)(q+8))==-EINVAL);
    assert(capture_resize_request_build(input,q,q,&hold)==-EINVAL);
    assert(!capture_resize_request_build(input,request,q,&hold));
    assert(hold.token && hold.address==info.parameter_cpu && hold.bytes==128 && !memcmp(request,saved,16));
    assert(q[2]==2 && get32(q+0x10)==128 && get32(q+0x24)==0x1500 && get64(q+0x28)==info.parameter_cpu);
    for(unsigned i=0;i<48;++i)if(i!=2 && i!=0x10 && i!=0x25 && i<0x28)assert(!q[i]);
    assert(get64(q+0x28)!=info.metadata_alias && get64(q+0x28)!=info.pixel_alias);
    memcpy(before,q,48);assert(capture_resize_request_build(input,request,q,&hold)==-EALREADY && !memcmp(q,before,48));
    assert(capture_input_destroy(input)==-EBUSY);
    uint8_t copied[128];memcpy(copied,(void *)(uintptr_t)get64(q+0x28),128);memset(q,0,48);
    assert(!memcmp(copied,(void *)hold.address,128) && capture_input_destroy(input)==-EBUSY);
    pid_t child=fork();assert(child>=0);if(!child){struct capture_input_mapping empty={0};assert(capture_resize_request_build(input,request,q,&empty)==-ECHILD);_exit(0);}int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(!capture_input_drop(input,&hold));assert(capture_input_drop(input,&hold)==-ESTALE);assert(!capture_input_destroy(input));
    for(unsigned i=0;i<7;++i){memset(p,0,sizeof p);p[0x63]=8;put16(p+0x68,128);put16(p+0x6a,64);p[0x70]=2;
        if(i==0)put16(p+0x68,0);
        if(i==1)put16(p+0x6a,8193);
        if(i==2)p[0x70]=4;
        if(i==3)p[0x71]=1;
        if(i==4)p[0x72]=1;
        if(i==5)put16(p+0x6c,160);
        if(i==6)put16(p+0x6e,120);
        input=NULL;assert(!capture_input_create(frame,size,request,p,&input));hold=(struct capture_input_mapping){0};memset(q,0xa5,48);memcpy(before,q,48);
        assert(capture_resize_request_build(input,request,q,&hold)==-ENOTSUP && !hold.token && !memcmp(q,before,48));assert(!capture_input_destroy(input));
    }
    free(frame);puts("PASS functional-Q48-real-P128-request-identity-and-hold no-send no-ACK capture_verified=0");return 0;
}
