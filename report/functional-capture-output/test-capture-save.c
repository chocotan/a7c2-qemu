/* SPDX-License-Identifier: MIT */
/* Host OSAL/Fsys fixture. Real model17/model18 bytes come from Python; no
 * original AP/Fsys or saved-camera claim is made by this test. */
#define _GNU_SOURCE
#include "capture-save.c"
#include "capture-dma.h"
#include <assert.h>
#include <stdio.h>
#include <sys/wait.h>
static struct capture_save *save_owner;
static unsigned hooks,stages;
static unsigned char *file_bytes;
static size_t file_size,file_position;
static int read_error,close_error;
static const char *expected_path="A:/DCIM/100MSDCF/DSC00001.JPG";
static void p32(void *p,uint32_t v){unsigned char *b=p;for(unsigned i=0;i<4;++i)b[i]=(unsigned char)(v>>(8*i));}
static void p64(void *p,uint64_t v){unsigned char *b=p;for(unsigned i=0;i<8;++i)b[i]=(unsigned char)(v>>(8*i));}
static unsigned char *load(const char *path,size_t *bytes){FILE *f=fopen(path,"rb");assert(f && !fseek(f,0,SEEK_END));long n=ftell(f);assert(n>0);rewind(f);unsigned char *p=malloc((size_t)n);assert(p && fread(p,1,(size_t)n,f)==(size_t)n && !fclose(f));*bytes=(size_t)n;return p;}
void functional_capture_fsys_begin(unsigned token,const struct fsys_write_layout *l,const uint64_t hashes[FSYS_WRITE_AREAS],const unsigned readable[FSYS_WRITE_AREAS]){
    ++hooks;int rc=capture_save_match(save_owner,token,l,hashes,readable);assert(rc==1 || rc<0);errno=E2BIG;
}
void functional_capture_fsys_event(unsigned token,enum capture_save_event event,int rc,unsigned complete,uint64_t bytes,uint64_t fnv){
    ++stages;(void)capture_save_observe(save_owner,token,event,rc,complete,bytes,fnv);errno=EDOM;
}
static int file_open(const char *path,unsigned long long *handle,unsigned flags){assert(!strcmp(path,expected_path) && flags==1);*handle=73;file_position=0;return 0;}
static int file_read(unsigned long long handle,void *out,int n){assert(handle==73 && n>0);if(read_error)return -EIO;if(file_position==file_size)return 0;size_t count=file_size-file_position;if(count>(size_t)n)count=(size_t)n;if(count>137)count=137;memcpy(out,file_bytes+file_position,count);file_position+=count;return (int)count;}
static int file_close(unsigned long long handle){assert(handle==73);return close_error;}
int main(int argc,char **argv){
    assert(argc==5);int mode=atoi(argv[4]);size_t nf,nm,nt;unsigned char *frame=load(argv[1],&nf),*main=load(argv[2],&nm),*thumb=load(argv[3],&nt);
    unsigned char request[16]={5,0,0x38,0x40,29,0,0,0,2},parameters[128]={0};parameters[0x63]=8;
    struct capture_input *input=NULL;assert(!capture_input_create(frame,nf,request,parameters,&input));struct capture_output_memory *owner=NULL;
    assert(!capture_output_memory_create(input,main,nm,thumb,nt,0,&owner));assert(!capture_save_prepare(owner,0x4321,&save_owner));
    struct capture_output_span header,body;assert(!capture_output_memory_span(owner,CAPTURE_OUT_HEADER,&header));assert(!capture_output_memory_span(owner,CAPTURE_OUT_MAIN,&body));
    memset((void *)header.cpu,0,4096);((unsigned char *)header.cpu)[0]=255;((unsigned char *)header.cpu)[1]=216;
    if(mode>=27){
        struct capture_output_span thumbnail;assert(!capture_output_memory_span(owner,CAPTURE_OUT_THUMB,&thumbnail));
        uint8_t query[40]={0},response[40];
        if(mode!=31){
            query[0]=0x21;p32(query+4,1);query[22]=1;p32(query+8,header.handle);assert(!capture_output_memory_reply(owner,query,0,response));
            p32(query+8,thumbnail.handle);assert(!capture_output_memory_reply(owner,query,0,response));
        }
        uint64_t digest=0;int rc=capture_dma_thumbnail(owner,mode==29?header.alias+header.capacity:header.alias+16,
            mode==28?thumbnail.alias+1:thumbnail.alias,mode==30?thumbnail.bytes-1:thumbnail.bytes,&digest);
        assert(rc==(mode==27?0:mode==31?-ESTALE:-ERANGE));
        if(!rc)assert(digest==hash((const void *)thumbnail.cpu,thumbnail.bytes) && !memcmp((void *)(header.cpu+16),(void *)thumbnail.cpu,thumbnail.bytes));
        if(mode!=31){query[0]=0x23;query[22]=2;p32(query+8,header.handle);assert(!capture_output_memory_reply(owner,query,0,response));p32(query+8,thumbnail.handle);assert(!capture_output_memory_reply(owner,query,0,response));}
    }
    file_size=4096+body.bytes;file_bytes=calloc(1,file_size+1);assert(file_bytes);memcpy(file_bytes,(void *)header.cpu,4096);memcpy(file_bytes+4096,(void *)body.cpu,body.bytes);
    unsigned char q[FSYS_WRITE_REQUEST_BYTES]={0};strcpy((char *)q,"A:/DCIM/100MSDCF/DSC00001.JPG");p32(q+0x42c,(uint32_t)file_size);p64(q+0x438,header.cpu);p64(q+0x440,4096);p64(q+0x450,body.cpu);p64(q+0x458,body.capacity);p32(q+0x4f0,2);p64(q+0x4f8,0x4321);p64(q+0x500,0x1234);
    if(mode==2)p64(q+0x4f8,0x4322);
    if(mode==3)p64(q+0x500,0);
    if(mode==4){p32(q+0x42c,(uint32_t)file_size-1);}
    if(mode==5){expected_path="A:/MISC/FILE.DAT";strcpy((char *)q,expected_path);}
    if(mode==6)((unsigned char *)header.cpu)[0]=0;
    if(mode==7)((unsigned char *)body.cpu)[0]^=1;
    if(mode==8)p64(q+0x438,(uintptr_t)file_bytes);
    if(mode==9)p64(q+0x440,4095);
    assert(!setenv("A7C2_FSYS_ASYNC_OBSERVE","1",1));errno=EINTR;unsigned token=fsys_write_trace_begin(q);assert(token==1 && hooks==1 && errno==EINTR);
    unsigned char result[FSYS_WRITE_RESULT_BYTES]={0},work[24]={0};p64(work,0x1234);
    if(mode==10)p32(work+8,(uint32_t)-EIO);
    if(mode==11)read_error=1;
    if(mode==12)close_error=-EIO;
    if(mode==13)file_bytes[file_size-1]^=1;
    if(mode==14)++file_size;
    if(mode==1)fsys_write_trace_submit(token,0);
    if(mode==15){assert(fsys_write_trace_callback((void *)0x1234,0,result,0x4321)==1);fsys_write_trace_callback((void *)0x1234,0,result,0x4321);}
    else if(mode!=16){unsigned callback=fsys_write_trace_callback((void *)0x1234,mode==17?-EIO:0,result,0x4321);
        if(mode!=18)fsys_write_trace_finished_return(fsys_write_trace_finished_begin(work));
        if(mode!=19)fsys_write_trace_callback_return(callback);
    }
    if(mode!=1)fsys_write_trace_submit(token,mode==20?-EIO:0);
    if(mode==21)fsys_write_trace_submit(token,0);
    if(mode==22)fsys_write_trace_unobserved();
    if(mode==23){pid_t child=fork();assert(child>=0);if(!child){struct capture_save_info info;_exit(capture_save_info(save_owner,&info)==-ECHILD && capture_save_close(save_owner)==-ECHILD?0:1);}int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));}
    if(mode==24){struct fsys_write_layout layout;assert(!fsys_write_decode(q,sizeof q,&layout));uint64_t hashes[8]={0};unsigned readable[8]={0};assert(capture_save_match(save_owner,2,&layout,hashes,readable)==-EALREADY);}
    if(mode==25){struct fsys_write_layout layout;assert(!fsys_write_decode(q,sizeof q,&layout));layout.area[1].address=0x12345000;uint64_t hashes[8]={0};unsigned readable[8]={0};assert(!capture_save_match(save_owner,2,&layout,hashes,readable));}
    struct capture_save_info info;assert(!capture_save_info(save_owner,&info));assert(!info.write_readback_verified && capture_save_close(save_owner)!=0);
    struct fsys_native_read_ops ops={file_open,file_read,file_close};errno=EINTR;int readback=fsys_write_trace_readback(&ops);assert(errno==EINTR && stages>0);
    if(mode==26){assert(!readback);readback=fsys_write_trace_readback(&ops);assert(!readback && errno==EINTR);}
    assert(!capture_save_info(save_owner,&info));int positive=mode==0 || mode==1 || mode==23 || mode==25 || mode==26 || mode>=27;
    if(positive){assert(!readback && info.write_readback_verified && !info.first_error && info.token==1 && info.bytes==4096+body.bytes);assert(!capture_save_close(save_owner));}
    else{assert(!info.write_readback_verified && (info.first_error || !info.token));assert(capture_save_close(save_owner)!=0);
        /* Fixture-only disposal after proving all mock consumers have returned;
         * production has no failed-write close or success conversion API. */
        assert(!capture_output_memory_drop(owner,save_owner->lease));free(save_owner);
    }
    assert(!capture_output_memory_destroy(owner) && !capture_input_destroy(input));free(file_bytes);free(frame);free(main);free(thumb);
    puts("PASS HOST_ONLY actual-source-owner real-trace-hooks callback-finished-readback-coverage capture_verified=0 original_AP=0 original_Fsys=0");return 0;
}
