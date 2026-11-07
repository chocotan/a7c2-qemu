/* SPDX-License-Identifier: MIT */
/* Component only: actual original Exif writer and real encoded thumbnail.
 * DMA aliases here are explicit software domains, never physical ASIC addresses. */
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <errno.h>
#include "capture-output-memory.h"
#include "capture-notifications.h"
static struct capture_output_memory *output_owner;

#define HEADER_CAP 131072u
static uintptr_t mpr_base;
static unsigned char *prefix, *thumbnail;
static size_t thumbnail_bytes;
static unsigned copies;
static uint64_t copied_fnv;
static uint64_t fnv(const void *p,size_t n) {
    const unsigned char *b=p;uint64_t h=UINT64_C(14695981039346656037);
    for(size_t i=0;i<n;++i)h=(h^b[i])*UINT64_C(1099511628211);
    return h;
}
static void put32(void *p,uint32_t value) { memcpy(p,&value,4); }
static void put64(void *p,uint64_t value) { memcpy(p,&value,8); }
static uint64_t get64(const void *p) { uint64_t v;memcpy(&v,p,8);return v; }
#include "owned-dmm-boundary.h"
#include "capture-dma.h"
int software_dma_copy(void *,void *,uint32_t)
    __asm__("_ZN3mpr4dmac16memcpyThreadSafeEPvS1_j");
int software_dma_copy(void *destination,void *source,uint32_t bytes) {
    const uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    const uintptr_t dst=(uintptr_t)destination,src=(uintptr_t)source;
    assert(mpr_base && caller==mpr_base+0x275ad4);
    assert(src==thumb_alias && bytes==thumbnail_bytes && bytes && copies==0);
    assert(dst>=header_alias && dst-header_alias<HEADER_CAP && bytes<=HEADER_CAP-(dst-header_alias));
    const uint64_t before=fnv(thumbnail,thumbnail_bytes);
    assert(!capture_dma_thumbnail(output_owner,dst,src,bytes,&copied_fnv));
    assert(!memcmp(prefix+(dst-header_alias),thumbnail,bytes));
    assert(fnv(thumbnail,thumbnail_bytes)==before && copied_fnv==before);
    ++copies;return 0;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,
    void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static void pin(uintptr_t offset,size_t bytes,uint64_t expected) {
    assert(fnv((const void *)(mpr_base+offset),bytes)==expected);
}
static int run(int argc,char **argv) {
    assert(argc==7);
    FILE *f=fopen(argv[1],"rb");assert(f && !fseek(f,0,SEEK_END));
    long length=ftell(f);assert(length>4 && length<60000);rewind(f);
    thumbnail_bytes=(size_t)length;thumbnail=malloc(thumbnail_bytes);assert(thumbnail);
    assert(fread(thumbnail,1,thumbnail_bytes,f)==thumbnail_bytes && !fclose(f));
    assert(thumbnail[0]==255 && thumbnail[1]==216 && thumbnail[thumbnail_bytes-2]==255 && thumbnail[thumbnail_bytes-1]==217);
    void *osal=dlopen(argv[3],RTLD_LAZY|RTLD_GLOBAL);
    if(!osal){fprintf(stderr,"osal: %s\n",dlerror());return 4;}
    void *crypto=dlopen(argv[4],RTLD_LAZY|RTLD_GLOBAL);
    if(!crypto){fprintf(stderr,"crypto: %s\n",dlerror());return 6;}
    void *mpr=dlopen(argv[2],RTLD_LAZY|RTLD_GLOBAL);
    if(!mpr){fprintf(stderr,"mpr: %s\n",dlerror());return 5;}
    void *symbol=dlsym(mpr,"_ZN7libjpeg3getEPN5still8get_if_tEN3mpr10StillImageE");assert(symbol);
    Dl_info identity;assert(dladdr(symbol,&identity) && identity.dli_fbase);
    mpr_base=(uintptr_t)identity.dli_fbase;assert((uintptr_t)symbol==mpr_base+0x26d540);
    pin(0x271b88,64,UINT64_C(0xe5b5a0c74c0f7527));
    pin(0x27963c,116,UINT64_C(0x94be58237395e6ad));
    pin(0x276520,176,UINT64_C(0x98a475ca28a2f2ef));
    pin(0x275a4c,168,UINT64_C(0x17b4c982c2b69cc2));
    assert(get64((const void *)(mpr_base+0x2fd820))==mpr_base+0x2fba50);
    assert(get64((const void *)(mpr_base+0x2fbaa8))==mpr_base+0x276520);
    assert(get64((const void *)(mpr_base+0x2fbad0))==mpr_base+0x275a4c);
    unsigned char *add_if=calloc(1,0x870),*metadata=malloc(512);
    prefix=mmap(NULL,HEADER_CAP,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(add_if && metadata && prefix!=MAP_FAILED && !((uintptr_t)prefix&4095));
    /* Explicit synthetic metadata: unsupported camera fields use original -1 sentinel. */
    memset(metadata,255,512);put64(add_if,(uintptr_t)metadata);
    prefix[0]=255;prefix[1]=216;
    FILE *main_file=fopen(argv[5],"rb");assert(main_file && !fseek(main_file,0,SEEK_END));
    long main_length=ftell(main_file);assert(main_length>4 && main_length<1000000);rewind(main_file);
    size_t body_bytes=(size_t)main_length-2,body_capacity=(body_bytes+4095)&~(size_t)4095;
    unsigned char *main_data=mmap(NULL,body_capacity+4096,PROT_READ|PROT_WRITE,
        MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(main_data!=MAP_FAILED && !((uintptr_t)main_data&4095));
    assert(fgetc(main_file)==255 && fgetc(main_file)==216);
    assert(fread(main_data,1,body_bytes,main_file)==body_bytes && !fclose(main_file));
    memset(main_data+body_bytes,0xa5,body_capacity+4096-body_bytes);
    unsigned char *fin_if=calloc(1,0x180);assert(fin_if);
    pin(0x2b1d78,1104,UINT64_C(0x0fcd96d8b2336546));
    pin(0x2b2258,24,UINT64_C(0x79f5134f9d2895d2));
    pin(0x2b2270,616,UINT64_C(0xbe2d485414c20136));
    assert(get64((const void *)(mpr_base+0x2fdce8))==mpr_base+0x3d82a0);
    actual_map_base=get64((void *)(mpr_base+0x3d82a0));
    FILE *frame_file=fopen(argv[6],"rb");assert(frame_file && !fseek(frame_file,0,SEEK_END));
    long frame_bytes=ftell(frame_file);assert(frame_bytes>96);rewind(frame_file);
    unsigned char *frame=malloc((size_t)frame_bytes);assert(frame);
    assert(fread(frame,1,(size_t)frame_bytes,frame_file)==(size_t)frame_bytes && !fclose(frame_file));
    unsigned char capture_request[16]={5,0,0x38,0x40,0,0,0,0,2},parameters[128]={0};
    memcpy(capture_request+4,frame+80,4);parameters[0x63]=8;
    struct capture_input *captured=NULL;
    assert(capture_input_create(frame,(size_t)frame_bytes,capture_request,parameters,&captured)==0);free(frame);
    unsigned char *full_main=malloc((size_t)main_length);assert(full_main);full_main[0]=255;full_main[1]=216;
    memcpy(full_main+2,main_data,body_bytes);
    assert(capture_output_memory_create(captured,full_main,(size_t)main_length,thumbnail,thumbnail_bytes,actual_map_base,&output_owner)==0);
    free(full_main);assert(capture_input_destroy(captured)==-EBUSY);
    assert(munmap(prefix,HEADER_CAP)==0 && munmap(main_data,body_capacity+4096)==0);
    struct capture_output_span header_span,main_span,thumb_span,meta_span;
    assert(capture_output_memory_span(output_owner,CAPTURE_OUT_METADATA,&meta_span)==0);
    assert(capture_output_memory_span(output_owner,CAPTURE_OUT_HEADER,&header_span)==0);
    assert(capture_output_memory_span(output_owner,CAPTURE_OUT_MAIN,&main_span)==0);
    assert(capture_output_memory_span(output_owner,CAPTURE_OUT_THUMB,&thumb_span)==0);
    prefix=(void *)header_span.cpu;main_data=(void *)main_span.cpu;
    free(thumbnail);thumbnail=(void *)thumb_span.cpu;
    uint64_t export_token=0;assert(capture_output_memory_hold(output_owner,&export_token)==0);
    register_owned_span(0,header_span.handle,prefix,header_span.capacity);
    register_owned_span(1,main_span.handle,main_data,main_span.capacity);
    register_owned_span(2,thumb_span.handle,thumbnail,thumb_span.capacity);
    register_owned_span(3,meta_span.handle,(void *)meta_span.cpu,meta_span.capacity);
    header_alias=header_span.alias;thumb_alias=thumb_span.alias;
    struct capture_notifications notifications={0};
    const unsigned char job_time[12]={0,0,0xea,7,11,3,12,34,56,0,0,0};
    assert(capture_notifications_build(output_owner,capture_request,job_time,&notifications)==0);
    const char *packet_names[]={"notification-start.bin","notification-entry.bin","notification-info.bin"};
    const void *packet_bytes[]={notifications.start,notifications.entry,notifications.info};
    const size_t packet_lengths[]={sizeof notifications.start,sizeof notifications.entry,sizeof notifications.info};
    for(unsigned i=0;i<3;++i){FILE *packet=fopen(packet_names[i],"wb");assert(packet);
        assert(fwrite(packet_bytes[i],1,packet_lengths[i],packet)==packet_lengths[i] && !fclose(packet));}
    unsigned char metadata_area[48]={0};const unsigned char *jpg=notifications.info+0xc8;
    actual_original_area_from_wire(jpg,metadata_area);
    free(metadata);put64(add_if,get64(metadata_area+0x10));
    actual_original_area_from_wire(jpg+0x90,add_if+0x148);
    actual_original_area_from_wire(jpg+0xa0,add_if+0x178);
    actual_original_area(0,fin_if,HEADER_CAP);
    void *(*factory)(uint32_t)=NULL;int (*add)(void *,void *)=NULL,(*finish)(void *,void *)=NULL;
    pin(0x270b2c,664,UINT64_C(0xbb1cfced3ce29d7f));
    pin(0x270f9c,336,UINT64_C(0x4aa82ae05182229d));
    pin(0xc4de0,140,UINT64_C(0xb481dcd0cc056e8a));
    void *factory_symbol=dlsym(mpr,"_ZN9stillutil7createrEN3mpr9StillTypeE");assert(factory_symbol);
    memcpy(&factory,&factory_symbol,sizeof factory_symbol);
    uintptr_t address=mpr_base+0x270b2c;memcpy(&add,&address,sizeof address);
    address=mpr_base+0x270f9c;memcpy(&finish,&address,sizeof address);
    unsigned char *jpeg=factory(1);assert(jpeg && get64(jpeg)==mpr_base+0x2fb800);
    int add_rc=add(jpeg,add_if);assert(add_rc==0);
    assert(*(uint32_t *)(jpeg+0x13e4)==1);
    const uint64_t main_before=fnv(main_data,body_bytes),thumb_before=fnv(thumbnail,thumbnail_bytes);
    int finish_rc=finish(jpeg,fin_if);assert(finish_rc==0 && copies==1);
    assert(copied_fnv==thumb_before);
    assert(*(uint32_t *)(jpeg+0x13e4)==3);
    unsigned count=*(uint32_t *)(jpeg+0x11f0);assert(count>0 && count<=8);
    f=fopen("original-jpeg-output-list.bin","wb");assert(f);
    FILE *records=fopen("original-output-records.bin","wb");assert(records);
    size_t total=0;
    for(unsigned i=0;i<count;++i) {
        unsigned char *record=jpeg+0x11f8+i*0x30;
        uint32_t bytes=*(uint32_t *)(record+8);uintptr_t cpu=(uintptr_t)get64(record+0x10);
        assert(bytes && !(cpu&4095) && ((cpu==(uintptr_t)prefix && bytes<=HEADER_CAP) ||
            (cpu==(uintptr_t)main_data && bytes<=body_capacity)));
        assert(fwrite(record,1,0x30,records)==0x30);
        assert(fwrite((void *)cpu,1,bytes,f)==bytes);total+=bytes;
    }
    assert(!fclose(records) && !fclose(f));
    assert(fnv(main_data,body_bytes)==main_before && fnv(thumbnail,thumbnail_bytes)==thumb_before);
    actual_original_release_spans();
    assert(capture_output_memory_destroy(output_owner)==-EBUSY);
    assert(capture_notifications_release(&notifications)==0);
    assert(capture_output_memory_destroy(output_owner)==-EBUSY);
    assert(capture_output_memory_drop(output_owner,export_token)==0);
    assert(capture_output_memory_destroy(output_owner)==0);output_owner=NULL;
    assert(capture_input_destroy(captured)==0);
    assert(get64((void *)(mpr_base+0x3d82a0))==actual_map_base);
    printf("PASS original-libjpeg-add-finish-output-list records=%u total_bytes=%zu software_DMA_copies=%u original_DMM_helper=1 software_owned_registry=1 production_output_owner=1 exports_checked=1 notification_lease_checked=1 notifications_sent=0 native_shares=%u native_queries=%u native_frees=%u actual_mapping_base=%#llx original_AP=0 native_DMM_registered=0 Fsys_saved=0 capture_verified=0\n",count,total,copies,native_shares,native_queries,native_frees,(unsigned long long)actual_map_base);
    /* Process owns the original marker allocations until exit; no camera/DMM owner is retired here. */
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
