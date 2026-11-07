/* SPDX-License-Identifier: MIT */
/* Component ABI check only: original MakeInputYcStdData/StdData encode/decode,
 * explicit software mapper; no original Main Exec, messages, ACK or camera app. */
#include "capture-input.c"
#include "capture-mapper.h"
#include "capture-jpeg-input.h"
#include <assert.h>
#include <dlfcn.h>
#include <stdio.h>

static struct capture_input *input_owner;
static struct capture_input_info input_info;
void capture_mapper_ctor1(void *,uint64_t,uint32_t,uint32_t,uint32_t)
    __asm__("_ZN12AvbbcPhycMemC1EmjNS_10CACHE_MODEEj");
void capture_mapper_dtor1(void *) __asm__("_ZN12AvbbcPhycMemD1Ev");
void quiet_debug_print(void *, void *)
    __asm__("_ZN26ExecCmd_SDF_EncodeJpegMain14PrintYcStdDataEP26C_DataflowInfra_StdData_YC");
void quiet_debug_print(void *object, void *data) { (void)object;(void)data; }
extern int __libc_start_main(int (*)(int,char **),int,char **,
    void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
#define LOAD(target,handle,name) do { void *symbol=dlsym(handle,name);assert(symbol);memcpy(&(target),&symbol,sizeof symbol); } while(0)
static int run(int argc, char **argv) {
    assert(argc==5);
    FILE *f=fopen(argv[1],"rb");assert(f);assert(!fseek(f,0,SEEK_END));
    long bytes=ftell(f);assert(bytes>96);rewind(f);
    uint8_t *frame=malloc((size_t)bytes);assert(frame);
    assert(fread(frame,1,(size_t)bytes,f)==(size_t)bytes);assert(!fclose(f));
    uint8_t request[16]={5,0,0x38,0x40,29,0,0,0,2},parameters[128]={0};parameters[0x63]=8;
    assert(capture_input_create(frame,(size_t)bytes,request,parameters,&input_owner)==0);
    assert(capture_input_info(input_owner,&input_info)==0);
    void *osal=dlopen(argv[4],RTLD_NOW|RTLD_GLOBAL);
    if(!osal) { fprintf(stderr,"OSAL dlopen: %s\n",dlerror());return 4; }
    void *library=dlopen(argv[2],RTLD_LAZY|RTLD_GLOBAL);
    if(!library) { fprintf(stderr,"dlopen: %s\n",dlerror());return 2; }
    void (*make)(void *,uint8_t *)=NULL;
    LOAD(make,library,"_ZN26ExecCmd_SDF_EncodeJpegMain18MakeInputYcStdDataEPN17StillEncoderParam23RESIZEENC_PARAM_PAYLOADE");
    assert(capture_mapper_bind("wrong")==-ELIBBAD);
    assert(capture_mapper_bind("676197567dbbefa54e08f528968efc6ca2aaffe8bee3ee3eae8164382ed5a7e5")==0);
    struct capture_mapper_scope scope;
    assert(capture_mapper_begin(input_owner,&scope)==0);
    assert(capture_mapper_begin(input_owner,&scope)==-EBUSY);
    _Alignas(16) uint8_t object[0x28]={0};
    make(object,(void *)input_info.parameter_cpu);
    assert(!scope.objects && !scope.error);
    assert(capture_input_info(input_owner,&input_info)==0 && input_info.mapping_references==1);
    assert(capture_input_destroy(input_owner)==-EBUSY);
    assert(capture_mapper_end(&scope)==0);
    assert(capture_input_info(input_owner,&input_info)==0 && !input_info.mapping_references && input_info.metadata_readonly);
    struct capture_input_mapping metadata_reader;
    assert(capture_input_metadata_read(input_owner,input_info.metadata_unit,0,1024,&metadata_reader)==0);
    assert(metadata_reader.address==input_info.metadata_cpu);
    assert(capture_mapper_begin(input_owner,&scope)==-EBUSY);
    assert(memcmp((void *)input_info.metadata_cpu,(uint8_t[32]){0},32));
    void *framework=dlopen(argv[3],RTLD_LAZY|RTLD_GLOBAL);
    if(!framework) { fprintf(stderr,"framework dlopen: %s\n",dlerror());return 3; }
    void (*yc_ctor)(void *,uint64_t,uint32_t,uint32_t)=NULL;
    void (*yc_dtor)(void *)=NULL;
    void (*size_ctor)(void *)=NULL,(*size_dtor)(void *)=NULL;
    void (*get_all)(void *,void *)=NULL;
    uint32_t (*get_size)(void *,void *)=NULL;
    LOAD(yc_ctor,framework,"_ZN26C_DataflowInfra_StdData_YCC1Emjj");
    LOAD(yc_dtor,framework,"_ZN26C_DataflowInfra_StdData_YCD1Ev");
    LOAD(size_ctor,framework,"_ZN35C_DataflowInfra_Entry_ImageSizeInfoC1Ev");
    LOAD(size_dtor,framework,"_ZN35C_DataflowInfra_Entry_ImageSizeInfoD1Ev");
    LOAD(get_size,framework,"_ZN26C_DataflowInfra_StdData_YC22GetEntry_ImageSizeInfoEP35C_DataflowInfra_Entry_ImageSizeInfo");
    LOAD(get_all,framework,"_ZN35C_DataflowInfra_Entry_ImageSizeInfo11GetData_AllEPN19DataflowInfra_StdYc22PIN_YC_IMAGE_SIZE_INFOE");
    _Alignas(16) uint8_t yc[512]={0},size_object[512]={0},values[128];memset(values,0xa5,sizeof values);
    yc_ctor(yc,input_info.metadata_cpu,1024,0);size_ctor(size_object);
    uint32_t code=get_size(yc,size_object);
    get_all(size_object,values);
    assert(get32(values)==0 && get32(values+4)==input_info.pixel_unit && !get32(values+0x18));
    assert(values[0x21]==8 && values[0x24]==2);
    assert((uint32_t)(values[0x2e]|(uint32_t)values[0x2f]<<8)==input_info.width);
    assert((uint32_t)(values[0x30]|(uint32_t)values[0x31]<<8)==input_info.height);
    for(unsigned i=72;i<sizeof values;++i)assert(values[i]==0xa5);
    size_dtor(size_object);yc_dtor(yc);
    assert(fnv((const void *)input_info.pixel_cpu,input_info.pixel_bytes)==input_info.source_fnv1a64);
    assert(capture_jpeg_input_bind("wrong")==-ELIBBAD);
    assert(capture_jpeg_input_bind("620e04a9cd51e65bd190ed1d5459b7235ff5a4109bc6498df342972621991d47")==0);
    uint8_t body[80]={0};put16(body+4,80);put16(body+8,7);
    put32(body+0x1c,input_info.metadata_unit);put16(body+0x40,input_info.width);put16(body+0x42,input_info.height);
    struct capture_jpeg_input prepared={0};
    body[0x1c]^=1;
    assert(capture_jpeg_input_prepare(input_owner,body,0,95,&prepared)==-ENODATA && !prepared.owner);
    body[0x1c]^=1;
    assert(capture_jpeg_input_prepare(input_owner,body,0,95,&prepared)==0 && prepared.prepared);
    assert(get64(prepared.model_request)==input_info.token && get32(prepared.model_request+16)==1);
    assert(prepared.pixels.address==input_info.pixel_cpu && prepared.pixels.bytes==input_info.pixel_bytes);
    assert(capture_jpeg_input_prepare(input_owner,body,0,95,&prepared)==-EBUSY);
    assert(capture_input_destroy(input_owner)==-EBUSY);
    const char *names[]={"actual-ssyc1024.bin","actual-parameter128.bin","actual-imagesize72.bin","actual-frame-still32.bin"};
    const void *data[]={(const void *)input_info.metadata_cpu,(const void *)input_info.parameter_cpu,values,prepared.model_request};
    const size_t lengths[]={1024,128,72,32};
    for(unsigned i=0;i<4;++i) {
        FILE *output=fopen(names[i],"wb");assert(output);
        assert(fwrite(data[i],1,lengths[i],output)==lengths[i]);assert(!fclose(output));
    }
    puts("MODEL18_INPUT_READY native_input_references_held=1");assert(!fflush(stdout));
    assert(fgetc(stdin)==1);
    assert(capture_jpeg_input_release(&prepared)==0 && !prepared.owner);
    const uint64_t metadata_hash=fnv((const void *)input_info.metadata_cpu,1024);
    assert(capture_input_release_metadata(input_owner,&metadata_reader)==0);
    assert(capture_mapper_begin(input_owner,&scope)==0);
    void (*set_all)(void *,void *)=NULL,(*set_entry)(void *,void *)=NULL;
    LOAD(set_all,framework,"_ZN35C_DataflowInfra_Entry_ImageSizeInfo11SetData_AllEPN19DataflowInfra_StdYc22PIN_YC_IMAGE_SIZE_INFOE");
    LOAD(set_entry,framework,"_ZN26C_DataflowInfra_StdData_YC22SetEntry_ImageSizeInfoEP35C_DataflowInfra_Entry_ImageSizeInfo");
    yc_ctor(yc,input_info.metadata_cpu,1024,0);size_ctor(size_object);
    assert(get_size(yc,size_object)==0);get_all(size_object,values);values[4]^=1;
    set_all(size_object,values);set_entry(yc,size_object);size_dtor(size_object);yc_dtor(yc);
    assert(capture_mapper_end(&scope)==0);
    assert(capture_jpeg_input_prepare(input_owner,body,0,95,&prepared)==-ENOTSUP &&
        prepared.owner==input_owner && prepared.metadata.token && !prepared.pixels.token && !prepared.prepared);
    assert(capture_input_destroy(input_owner)==-EBUSY);
    assert(capture_jpeg_input_release(&prepared)==0);
    assert(capture_mapper_begin(input_owner,&scope)==0);
    memset((void *)scope.mapping.address,0,1024);make(object,(void *)input_info.parameter_cpu);
    assert(capture_mapper_end(&scope)==0);
    assert(fnv((const void *)input_info.metadata_cpu,1024)==metadata_hash);
    assert(capture_mapper_begin(input_owner,&scope)==0);
    _Alignas(16) uint8_t bad_object[0x38]={0};
    capture_mapper_ctor1(bad_object,input_info.metadata_alias,1024,0,0x29);
    assert(scope.error==-EPROTO && scope.objects==1);
    assert(capture_mapper_end(&scope)==-EBUSY);
    assert(get64(bad_object+0x10)!=(uintptr_t)input_info.metadata_cpu);
    assert(fnv((const void *)input_info.metadata_cpu,1024)==metadata_hash);
    capture_mapper_dtor1(bad_object);
    assert(capture_mapper_end(&scope)==-EPROTO);
    assert(capture_input_destroy(input_owner)==0);free(frame);
    printf("PASS original-SSYC-serializer-and-typed-reader get_entry_rc=%u caller=0x29 original_main_exec=0 capture_verified=0\n",code);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
