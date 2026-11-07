/* SPDX-License-Identifier: MIT */
#include "capture-output-memory.h"
#include "capture-notifications.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
static unsigned char *read_file(const char *name,size_t *size) {
    FILE *f=fopen(name,"rb");assert(f && !fseek(f,0,SEEK_END));long n=ftell(f);assert(n>0);rewind(f);
    unsigned char *p=malloc((size_t)n);assert(p);assert(fread(p,1,(size_t)n,f)==(size_t)n && !fclose(f));*size=(size_t)n;return p;
}
static void p16(unsigned char *p,unsigned value){p[0]=(unsigned char)value;p[1]=(unsigned char)(value>>8);}
static void p32(unsigned char *p,unsigned value){for(unsigned i=0;i<4;++i)p[i]=(unsigned char)(value>>(i*8));}
static uint32_t u32(const unsigned char *p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint64_t u64(const unsigned char *p){return u32(p)|(uint64_t)u32(p+4)<<32;}
static void request(unsigned char *q,unsigned op,unsigned handle,unsigned option) {
    memset(q,0,40);p16(q,op);p32(q+4,1);p32(q+8,handle);p16(q+22,option);
}
int main(int argc,char **argv) {
    assert(argc==4);size_t frame_size,main_size,thumb_size;
    unsigned char *frame=read_file(argv[1],&frame_size),*main=read_file(argv[2],&main_size),*thumb=read_file(argv[3],&thumb_size);
    unsigned char original[16]={5,0,0x38,0x40,0,0,0,0,2},param[128]={0};
    memcpy(original+4,frame+80,4);param[0x63]=8;
    struct capture_input *input=NULL;assert(!capture_input_create(frame,frame_size,original,param,&input));
    struct capture_output_memory *owner=NULL;assert(capture_output_memory_create(input,main,main_size,thumb,thumb_size,UINT64_MAX,&owner)==-ERANGE && !owner);
    struct capture_input_info before;assert(!capture_input_info(input,&before) && !before.owner_references);
    assert(!capture_output_memory_create(input,main,main_size,thumb,thumb_size,0,&owner));
    assert(capture_input_destroy(input)==-EBUSY);
    assert(capture_output_memory_create(input,main,main_size,thumb,thumb_size,0,&owner)==-EINVAL);
    struct capture_output_span spans[CAPTURE_OUT_COUNT];
    for(unsigned i=0;i<CAPTURE_OUT_COUNT;++i){assert(!capture_output_memory_span(owner,(enum capture_output_role)i,&spans[i]));assert(spans[i].cpu && !(spans[i].cpu&4095) && spans[i].capacity%4096==0 && !(spans[i].handle&0x8000));}
    assert(capture_output_memory_span(owner,(enum capture_output_role)-1,&spans[0])==-EINVAL);
    assert(!memcmp((void *)spans[CAPTURE_OUT_MAIN].cpu,main+2,main_size-2));
    assert(!memcmp((void *)spans[CAPTURE_OUT_THUMB].cpu,thumb,thumb_size));
    assert(spans[CAPTURE_OUT_MAIN].bytes==main_size-2 && spans[CAPTURE_OUT_THUMB].bytes==thumb_size);
    unsigned char q[40],r[40],unchanged[40];memset(unchanged,0xa5,40);memcpy(r,unchanged,40);
    request(q,0x2a,spans[1].handle^UINT32_C(0x01000000),0);assert(capture_output_memory_reply(owner,q,0,r)==-ESTALE && !memcmp(r,unchanged,40));
    request(q,0x2a,spans[1].handle,0);assert(capture_output_memory_reply(owner,q,1,r)==-EINVAL && !memcmp(r,unchanged,40));
    unsigned char overlap[80]={0};memcpy(overlap,q,40);assert(capture_output_memory_reply(owner,overlap,0,overlap+1)==-EINVAL);
    assert(!capture_output_memory_reply(owner,q,0,r));assert(u32(r+12)==spans[1].handle && u64(r+24)==spans[1].alias && u32(r+32)==spans[1].capacity);
    struct capture_output_info info;assert(!capture_output_memory_info(owner,&info) && !info.native_references);
    request(q,0x28,0x80d61,0);assert(!capture_output_memory_reply(owner,q,0,r) && u32(r+12)==spans[CAPTURE_OUT_HEADER].handle);
    request(q,0x28,0x27f,0);assert(!capture_output_memory_reply(owner,q,0,r) && u32(r+12)==spans[CAPTURE_OUT_AUX].handle);
    request(q,0x28,0xdead,0);assert(capture_output_memory_reply(owner,q,0,r)==-ENODATA);
    request(q,0x23,spans[1].handle,2);assert(capture_output_memory_reply(owner,q,0,r)==-EALREADY);
    request(q,0x21,spans[1].handle,1);
    for(unsigned i=0;i<255;++i)assert(!capture_output_memory_reply(owner,q,0,r));
    assert(capture_output_memory_reply(owner,q,0,r)==-EOVERFLOW && capture_output_memory_destroy(owner)==-EBUSY);
    request(q,0x23,spans[1].handle,2);
    for(unsigned i=0;i<255;++i)assert(!capture_output_memory_reply(owner,q,0,r));
    uint64_t tokens[9]={0};for(unsigned i=0;i<8;++i)assert(!capture_output_memory_hold(owner,&tokens[i]));
    assert(capture_output_memory_hold(owner,&tokens[8])==-ENOSPC && capture_output_memory_destroy(owner)==-EBUSY);
    for(unsigned i=0;i<8;++i)assert(!capture_output_memory_drop(owner,tokens[i]));
    assert(capture_output_memory_drop(owner,tokens[0])==-ESTALE);
    pid_t child=fork();assert(child>=0);
    if(!child){assert(capture_output_memory_info(owner,&info)==-ECHILD);assert(capture_output_memory_destroy(owner)==-ECHILD);_exit(0);}
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    struct capture_notifications notifications={0};
    unsigned char local_time[12]={0,0,0xe8,7,2,29,12,34,56,0,0,0},wrong[16];
    memcpy(wrong,original,16);wrong[4]^=1;
    assert(capture_notifications_build(owner,wrong,local_time,&notifications)==-EBADMSG && !notifications.owner);
    local_time[2]=0xe7;
    assert(capture_notifications_build(owner,original,local_time,&notifications)==-EINVAL && !notifications.owner);
    local_time[2]=0xe8;
    assert(!capture_notifications_build(owner,original,local_time,&notifications));
    assert(capture_notifications_build(owner,original,local_time,&notifications)==-EBUSY);
    assert(!memcmp(notifications.entry+0x14,local_time,12));
    assert(u32(notifications.info+0xc8)==spans[CAPTURE_OUT_METADATA].handle);
    assert(u32(notifications.info+0x158)==spans[CAPTURE_OUT_MAIN].handle);
    assert(u32(notifications.info+0x168)==spans[CAPTURE_OUT_THUMB].handle);
    assert(u32(notifications.info+0x170)==thumb_size);
    assert(!u32(notifications.info+0x218));
    assert(capture_output_memory_destroy(owner)==-EBUSY);
    uint64_t independent_export;assert(!capture_output_memory_hold(owner,&independent_export));
    assert(!capture_notifications_release(&notifications));
    assert(capture_notifications_release(&notifications)==-EINVAL);
    assert(capture_output_memory_destroy(owner)==-EBUSY);
    assert(!capture_output_memory_drop(owner,independent_export));
    uint32_t old_handle=spans[1].handle;uint64_t old_export=tokens[0];assert(!capture_output_memory_destroy(owner));owner=NULL;
    assert(!capture_input_info(input,&before) && !before.owner_references);
    assert(!capture_output_memory_create(input,main,main_size,thumb,thumb_size,0,&owner));
    request(q,0x2a,old_handle,0);assert(capture_output_memory_reply(owner,q,0,r)==-ESTALE);
    assert(capture_output_memory_drop(owner,old_export)==-ESTALE);
    assert(!capture_output_memory_destroy(owner));assert(!capture_input_destroy(input));
    free(frame);free(main);free(thumb);
    puts("PASS real-input output-owner page-capacity-native-refs-export-refs-stale-handle-fork");return 0;
}
