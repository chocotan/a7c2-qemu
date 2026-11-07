/* SPDX-License-Identifier: MIT */
/* Original-library component only. The native router/ACK/Main/Comp execute;
 * OSAL/Dataflow delivery below is an explicit fixture; ParameterControl is native.
 * Model18 actually consumes their typed same-frame input in the parent process. */
#include "../functional-capture-input/capture-input.c"
#include "../functional-capture-input/capture-mapper.h"
#include "../functional-capture-input/capture-jpeg-input.h"
#include "capture-resize-request.h"
#include "../../runtime/analysis/functional-mpr-memory.h"
#include <stdbool.h>
#include <assert.h>
#include <dlfcn.h>
#include <stdio.h>
static struct capture_input *input_owner;
static struct capture_input_info input_info;
static uint8_t queue48[48],route64[64],parameter128[128],config_copy120[120],body80[80];
static uint8_t *native_config;
static _Alignas(16) uint8_t native_table[FUNCTIONAL_MPR_MEMORY_TABLE_BYTES];
static struct functional_mpr_memory_lease output_pins[2],config_pin;
static unsigned config_sent;
extern bool original_memory_alloc(int,uint32_t *,void *) __asm__("_ZN3mpr10DmmMemInfo14AllocDmmMemoryEiPjPNS0_11BufferTableE");
extern void original_memory_free(int) __asm__("_ZN3mpr10DmmMemInfo13FreeDmmMemoryEi");
unsigned fixture_config_send(const uint8_t *,void *) __asm__("_ZN3mpr5Codec14SendMsgToAvbbcEP10PayloadMprP12PayloadCodec");
unsigned fixture_config_send(const uint8_t *q,void *reply){
    assert(q && !reply && !config_sent && q[2]==1 && get32(q+0x10)==56 && get32(q+0x24)==0x1500);
    const uint8_t *payload=(const void *)(uintptr_t)get64(q+0x28);
    assert(payload && get64(payload)==(uintptr_t)native_config && get32(payload+8)==120);
    ++config_sent;return 1;
}
static uint8_t manager[32];
static _Alignas(16) uint8_t control[128];
static uint32_t (*control_get_pointer)(void *,uint32_t,void **);
static void *received_object;
static unsigned route_sent,ack_sent,parameter_copied,sdf_sent,aux_sent,selector,result_set;
static uint32_t native_result;
static uint64_t ordinal,route_order,ack_order,copy_order,done_order[2];
void capture_mapper_ctor1(void *,uint64_t,uint32_t,uint32_t,uint32_t) __asm__("_ZN12AvbbcPhycMemC1EmjNS_10CACHE_MODEEj");
void capture_mapper_dtor1(void *) __asm__("_ZN12AvbbcPhycMemD1Ev");
void quiet_debug_print(void *,void *) __asm__("_ZN26ExecCmd_SDF_EncodeJpegMain14PrintYcStdDataEP26C_DataflowInfra_StdData_YC");
void quiet_debug_print(void *object,void *data){(void)object;(void)data;}
uint32_t fixture_thread(void) __asm__("osal_thread_id");
uint32_t fixture_thread(void){return 0x555;}
int fixture_cpu(uint32_t id,uint32_t mask) __asm__("osal_set_cpu");
int fixture_cpu(uint32_t id,uint32_t mask){assert(id==0x555 && mask==15);return 0;}
uint32_t fixture_receive(void *,uint32_t,void *,uint32_t) __asm__("_ZN21DataflowInfraReceiver12ReceiveASyncEjP16DataflowInfraMsgj");
uint32_t fixture_receive(void *receiver,uint32_t source,void *message,uint32_t timeout){assert(receiver && source==CAPTURE_RESIZE_QUEUE && message && timeout==UINT32_MAX && !route_sent);received_object=message;return 0;}
void fixture_source(void *,uint32_t *) __asm__("_ZN16DataflowInfraMsg8GetSrcIdEPj");
void fixture_source(void *message,uint32_t *source){assert(message==received_object && source);*source=CAPTURE_RESIZE_SOURCE;}
uint32_t fixture_message(void *,void *,uint16_t) __asm__("_ZN16DataflowInfraMsg6GetMsgEPvt");
uint32_t fixture_message(void *message,void *out,uint16_t bytes){assert(message==received_object && out && bytes==48);memcpy(out,queue48,48);return 0;}
uint16_t fixture_cid(void *,uint16_t) __asm__("_ZN20InfraAvbbcMsgManager10ConvertCidEt");
uint16_t fixture_cid(void *object,uint16_t code){assert(object==manager && code==3);return 0x2000;}
uint16_t fixture_mid(void *,uint16_t,uint16_t) __asm__("_ZN20InfraAvbbcMsgManager13ConvertCmdMidEtt");
uint16_t fixture_mid(void *object,uint16_t category,uint16_t code){assert(object==manager);if(category==3){assert(code==0x304);return 4;}assert(category==4 && code==0x8405);return 0x8405;}
int fixture_send(void *,uint32_t,const uint8_t *,uint32_t) __asm__("_ZN20InfraAvbbcMsgManager10OsalSndMsgEjPKhj");
int fixture_send(void *object,uint32_t destination,const uint8_t *body,uint32_t bytes){
    assert(object==manager && body);
    if(destination==0x80550123){assert(bytes==64 && !route_sent);memcpy(route64,body,64);++route_sent;route_order=++ordinal;return 0;}
    if(destination==CAPTURE_RESIZE_SOURCE){assert(bytes==44 && !ack_sent && !parameter_copied);assert(body[2]==2 && body[3]==0x10 && get32(body+0x24)==0x4e0);++ack_sent;ack_order=++ordinal;return 0;}
    if(destination==0x8055068a){
        assert(bytes==40 && ack_sent && !parameter_copied && !aux_sent);void *copy=NULL;
        assert(!control_get_pointer(control,0x104a,&copy) && copy && copy!=(void *)input_info.parameter_cpu);
        assert(capture_input_destroy(input_owner)==-EBUSY && !memcmp(copy,(void *)input_info.parameter_cpu,128));
        memcpy(parameter128,copy,128);++parameter_copied;copy_order=++ordinal;++aux_sent;return 0;
    }
    assert(destination==0x82830752 && bytes==80 && parameter_copied && aux_sent && sdf_sent==selector);
    memcpy(body80,body,80);++sdf_sent;return 0;
}
static int route_running(void *object){assert(object);return !route_sent;}
#define SET_FUNCTION(table,offset,name) do {void (*binding)(void)=(void (*)(void))name;memcpy((table)+(offset),&binding,sizeof binding);} while(0)
#define LOAD(target,library,name) do {void *symbol=dlsym(library,name);assert(symbol);memcpy(&(target),&symbol,sizeof symbol);} while(0)
static void save_file(const char *name,const void *data,size_t bytes){FILE *f=fopen(name,"wb");assert(f && fwrite(data,1,bytes,f)==bytes && !fclose(f));}
static uint8_t *read_file(const char *name,size_t *size){FILE *f=fopen(name,"rb");assert(f && !fseek(f,0,SEEK_END));long n=ftell(f);assert(n>0);rewind(f);*size=(size_t)n;uint8_t *data=malloc(*size);assert(data && fread(data,1,*size,f)==*size && !fclose(f));return data;}
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc,char **argv){
    assert(argc==7);size_t frame_bytes;uint8_t *frame=read_file(argv[1],&frame_bytes);
    uint8_t request[16]={5,0,0x38,0x40,29,0,0,0,2},parameters[128]={0};parameters[0x63]=8;parameters[0x70]=2;
    put16(parameters+0x68,128);put16(parameters+0x6a,64);
    assert(!capture_input_create(frame,frame_bytes,request,parameters,&input_owner));assert(!capture_input_info(input_owner,&input_info));
    struct capture_input_mapping hold={0};assert(!capture_resize_request_build(input_owner,request,queue48,&hold));
    assert(get64(queue48+0x28)==input_info.parameter_cpu && capture_input_destroy(input_owner)==-EBUSY);
    void *osal=dlopen(argv[4],RTLD_NOW|RTLD_GLOBAL);if(!osal){fprintf(stderr,"OSAL dlopen: %s\n",dlerror());return 4;}
    void *crypto=dlopen(argv[6],RTLD_NOW|RTLD_GLOBAL);if(!crypto){fprintf(stderr,"crypto dlopen: %s\n",dlerror());return 5;}
    void *mpr=dlopen(argv[5],RTLD_LAZY|RTLD_GLOBAL);if(!mpr){fprintf(stderr,"MPR dlopen: %s\n",dlerror());return 6;}
    void *library=dlopen(argv[2],RTLD_LAZY|RTLD_GLOBAL);if(!library){fprintf(stderr,"Infra dlopen: %s\n",dlerror());return 2;}
    void *framework=dlopen(argv[3],RTLD_LAZY|RTLD_GLOBAL);if(!framework){fprintf(stderr,"framework dlopen: %s\n",dlerror());return 3;}
    assert(!capture_mapper_bind("676197567dbbefa54e08f528968efc6ca2aaffe8bee3ee3eae8164382ed5a7e5"));
    assert(!capture_jpeg_input_bind("620e04a9cd51e65bd190ed1d5459b7235ff5a4109bc6498df342972621991d47"));
    void (*router_main)(void *)=NULL;uint32_t (*resize_ack)(void *,const uint8_t *)=NULL;
    uint32_t (*main_exec)(void *,const uint8_t *)=NULL,(*main_ack)(void *,const uint8_t *,uint16_t)=NULL;
    uint32_t (*comp_exec)(void *,const uint8_t *)=NULL,(*comp_done)(void *,const uint8_t *,uint16_t)=NULL;
    LOAD(router_main,library,"_ZN12InfraAvbbcIf4MainEv");LOAD(resize_ack,library,"_ZN20ExecCmd_ResizeEncAck7ExecCmdEPKh");
    LOAD(main_exec,library,"_ZN26ExecCmd_SDF_EncodeJpegMain7ExecCmdEPKh");LOAD(main_ack,library,"_ZN26ExecCmd_SDF_EncodeJpegMain6ResCmdEPKht");
    LOAD(comp_exec,library,"_ZN30ExecCmd_SDF_EncodeJpegMainComp7ExecCmdEPKh");LOAD(comp_done,library,"_ZN30ExecCmd_SDF_EncodeJpegMainComp6ResCmdEPKht");
    void (*control_ctor)(void *,void *,uint32_t)=NULL,(*control_dtor)(void *)=NULL;
    void (*set_copy)(void *,uint32_t,void *,uint32_t)=NULL,(*set_pointer)(void *,uint32_t,void *)=NULL;
    void (*set_scalar)(void *,uint32_t,uint32_t)=NULL;
    uint32_t (*get_scalar)(void *,uint32_t,uint32_t *)=NULL;
    LOAD(control_ctor,library,"_ZN14AvbbcParamCtrl16ParameterControlC1EPN12ParamCtrlDef11PARAM_TABLEEj");
    LOAD(control_dtor,library,"_ZN14AvbbcParamCtrl16ParameterControlD1Ev");
    LOAD(control_get_pointer,library,"_ZN14AvbbcParamCtrl16ParameterControl8GetValueEjRPv");
    LOAD(set_copy,library,"_ZN14AvbbcParamCtrl16ParameterControl8SetValueEjPvj");
    LOAD(set_pointer,library,"_ZN14AvbbcParamCtrl16ParameterControl8SetValueEjPv");
    LOAD(set_scalar,library,"_ZN14AvbbcParamCtrl16ParameterControl8SetValueEjj");
    LOAD(get_scalar,library,"_ZN14AvbbcParamCtrl16ParameterControl8GetValueEjRj");
    void *constructor=NULL;memcpy(&constructor,&control_ctor,sizeof constructor);Dl_info control_location;
    assert(dladdr(constructor,&control_location) && control_location.dli_fbase);
    control_ctor(control,(uint8_t *)control_location.dli_fbase+0x1b7dc8,0x80550123);
    _Alignas(16) uint8_t router[48]={0},router_vtable[48]={0};
    put64(router,(uintptr_t)router_vtable);put64(router+0x20,(uintptr_t)manager);put32(manager+8,CAPTURE_RESIZE_QUEUE);
    SET_FUNCTION(router_vtable,0x28,route_running);router_main(router);
    assert(route_sent==1 && get32(route64)==CAPTURE_RESIZE_SOURCE);
    assert(route64[8]==0 && route64[9]==0x70 && route64[10]==0 && route64[11]==0x90 && route64[12]==0x38);
    assert(!memcmp(route64+16,queue48,48) && get64(route64+0x38)==input_info.parameter_cpu);
    _Alignas(16) uint8_t object[40]={0},comp[40]={0},trigger[40]={0},reply[16]={0};
    put64(object+0x10,(uintptr_t)manager);put64(object+0x18,(uintptr_t)control);put32(object+0x20,CAPTURE_RESIZE_SOURCE);
    save_file("actual-request16.bin",request,16);save_file("actual-queue48.bin",queue48,48);save_file("actual-route64.bin",route64,64);
    assert(!resize_ack(object,route64+8) && ack_sent==1 && parameter_copied==1 && aux_sent==1);
    assert(route_order<ack_order && ack_order<copy_order);
    assert(!memcmp(parameter128,(void *)hold.address,128));memset(queue48,0,48);memset(route64,0,64);
    assert(capture_input_destroy(input_owner)==-EBUSY);
    save_file("actual-parameter-copy128.bin",parameter128,128);
    memset(object,0,sizeof object);put64(object+0x10,(uintptr_t)manager);put64(object+0x18,(uintptr_t)control);
    memcpy(comp,object,sizeof comp);
    assert(!functional_mpr_memory_enable(NULL));uint32_t group=0;assert(original_memory_alloc(0x10,&group,native_table) && group);
    native_config=(void *)(uintptr_t)get64(native_table+0x2a0);
    assert(!functional_mpr_memory_acquire((uintptr_t)native_config,120,&config_pin));
    void *writer=dlsym(mpr,"_ZN3mpr10DmmMemInfo9SetMemTblEjiPNS0_11BufferTableE");Dl_info location;
    assert(writer && dladdr(writer,&location) && location.dli_fbase);
    void *entry=(uint8_t *)location.dli_fbase+0xcee2c;unsigned (*get_still)(void *)=NULL;memcpy(&get_still,&entry,sizeof get_still);
    assert(!get_still(native_table) && config_sent==1);memcpy(config_copy120,native_config,120);
    set_copy(control,0x1047,native_config,120);set_pointer(control,0x1048,native_config);
    void *native_copy=NULL,*native_pointer=NULL;
    assert(!control_get_pointer(control,0x1047,&native_copy) && native_copy && native_copy!=native_config);
    assert(!control_get_pointer(control,0x1048,&native_pointer) && native_pointer==native_config);
    assert(!memcmp(native_copy,native_config,120));
    for(unsigned i=0;i<2;++i){const uint8_t *slot=native_config+0x54+12*i;
        assert(!functional_mpr_memory_acquire_sds(0,get32(slot),get32(slot+4),get32(slot+8),&output_pins[i]));
        assert(output_pins[i].span.generation==config_pin.span.generation && output_pins[i].span.group==group);
    }
    assert(output_pins[0].address+output_pins[0].bytes<=output_pins[1].address || output_pins[1].address+output_pins[1].bytes<=output_pins[0].address);
    save_file("actual-buffer-table.bin",native_table,sizeof native_table);save_file("actual-config-before120.bin",config_copy120,120);
    for(selector=0;selector<2;++selector){
        object[0x20]=(uint8_t)selector;comp[0x20]=(uint8_t)selector;
        struct capture_mapper_scope scope;assert(!capture_mapper_begin(input_owner,&scope));
        assert(!main_exec(object,trigger));assert(sdf_sent==selector+1 && !scope.objects && !scope.error);assert(!capture_mapper_end(&scope));
        assert(body80[0]==0 && body80[1]==0x20 && body80[2]==4 && body80[3]==0 && body80[4]==80);
        assert(get32(body80+0x1c)==input_info.metadata_unit && body80[0x4b]==selector);
        const unsigned qualities[]={1,75,76,95,100};
        for(unsigned i=0;i<5;++i){struct capture_jpeg_input probe={0};
            assert(!capture_jpeg_input_prepare(input_owner,body80,selector,qualities[i],&probe));
            unsigned expected=selector && qualities[i]>75?75:qualities[i];assert(get32(probe.model_request+28)==expected);
            assert(!capture_jpeg_input_release(&probe));
        }
        struct capture_jpeg_input prepared={0};assert(!capture_jpeg_input_prepare(input_owner,body80,selector,95,&prepared));
        assert(prepared.source.token==input_info.token && prepared.pixels.address==input_info.pixel_cpu);
        save_file(selector?"actual-thumb80.bin":"actual-main80.bin",body80,80);
        save_file(selector?"actual-thumb32.bin":"actual-main32.bin",prepared.model_request,32);
        save_file(selector?"actual-thumb-ssyc1024.bin":"actual-main-ssyc1024.bin",(void *)input_info.metadata_cpu,1024);
        printf("MODEL18_ORIGINAL_MAIN_READY selector=%u native_input_references_held=1\n",selector);assert(!fflush(stdout));
        assert(fgetc(stdin)==1);size_t jpeg_bytes;uint8_t *jpeg=read_file(selector?"encoded-thumb.jpg":"encoded-main.jpg",&jpeg_bytes);
        assert(jpeg_bytes>2 && jpeg[0]==0xff && jpeg[1]==0xd8 && jpeg[jpeg_bytes-2]==0xff && jpeg[jpeg_bytes-1]==0xd9);
        size_t skip=selector?0:2;size_t native_bytes=jpeg_bytes-skip;
        assert(native_bytes<=output_pins[selector].bytes && !functional_mpr_memory_validate(&output_pins[selector]));
        assert(!functional_mpr_memory_write(&output_pins[selector],0,jpeg+skip,native_bytes));
        const uint8_t *output=(const void *)output_pins[selector].address;
        memset(reply,0,sizeof reply);reply[2]=0x10;reply[3]=0x83;assert(!main_ack(object,reply,0x8310));assert(!comp_exec(comp,reply));
        set_scalar(control,0x104c,UINT32_C(0xa5a55a5a));
        assert(!get_scalar(control,0x104c,&native_result) && native_result==UINT32_C(0xa5a55a5a));
        reply[2]=0x11;put32(reply+12,(uint32_t)native_bytes);assert(!comp_done(comp,reply,0x8311));
        assert(!get_scalar(control,0x104c,&native_result));++result_set;
        assert(result_set==selector+1 && !native_result && get32(native_config+0x5c+12*selector)==native_bytes && get32(config_copy120+0x5c+12*selector)==output_pins[selector].bytes);
        assert(!memcmp(native_copy,config_copy120,120));
        done_order[selector]=++ordinal;
        assert(fnv(output,native_bytes)==fnv(jpeg+skip,native_bytes));
        save_file(selector?"native-thumb.bin":"native-main-no-soi.bin",output,native_bytes);
        assert(capture_input_destroy(input_owner)==-EBUSY && !capture_jpeg_input_release(&prepared));free(jpeg);
    }
    uint8_t order[48];put64(order,route_order);put64(order+8,ack_order);put64(order+16,copy_order);
    put64(order+24,done_order[0]);put64(order+32,done_order[1]);put64(order+40,input_info.token);
    save_file("actual-order48.bin",order,48);save_file("actual-config120.bin",native_config,120);
    for(unsigned i=0;i<2;++i)assert(!functional_mpr_memory_release(output_pins[i].token));
    assert(!functional_mpr_memory_release(config_pin.token));original_memory_free(0x10);assert(!functional_mpr_memory_shutdown());
    control_dtor(control);assert(!capture_input_drop(input_owner,&hold));assert(!capture_input_destroy(input_owner));free(frame);
    puts("PASS original-router-ResizeEncAck-Main-MainComp same_frame=1 ACK_before_Pcopy=1 selectors=2 original_SetMemTbl=1 original_GetStillBufConfig=1 production_SDS=1 original_ParameterControl=1 IO_fixture=1 ParameterControl_fixture=0 original_AP=0 Fsys_saved=0 capture_verified=0");return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack){__libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();}
