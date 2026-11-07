/* SPDX-License-Identifier: MIT */
/* Actual original sender/receiver/ACK/callback/ParameterControl. Only OSAL
 * message backing and delivery are fixtures; no camera AP/Fsys execution. */
#define _GNU_SOURCE
#include "../functional-capture-input/capture-input.c"
#include "capture-resize-request.h"
#include <assert.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
static struct capture_input *input;
static struct capture_input_info input_info;
struct packet {uint32_t size,source;uint8_t data[48];};
static struct packet *request_packet;
static pthread_mutex_t bus=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t arrived=PTHREAD_COND_INITIALIZER;
static unsigned routed,source_copy,copied,sender_returned;
static _Atomic unsigned request_freed,reply_freed;
static uint8_t incoming48[48],route64[64],copied128[128],manager[32],control[128];
static void *received_object;
static uint64_t clock_order,ack_order,sender_order,copy_order;
static void (*callback)(void *,void *);
static uint32_t (*resize_ack)(void *,const uint8_t *);
static uint32_t (*control_get)(void *,uint32_t,void **);
static struct packet *allocation(void *p){return (struct packet *)((uint8_t *)p-sizeof(uint32_t)*2);}
int fixture_allocate(unsigned,void **,unsigned,unsigned) __asm__("osal_valloc_msg_wait");
int fixture_allocate(unsigned destination,void **out,unsigned bytes,unsigned alignment){
 if(out && alignment==0 && ((destination==0x008f013a && bytes==44) || (destination==0x008f0313 && bytes==32)))return -ENODEV;
 if(destination!=0x8055001f || !out || bytes!=48 || alignment!=1)fprintf(stderr,"ALLOCATION_MISMATCH destination=%#x out=%p bytes=%u mode=%u caller=%p\n",destination,(void *)out,bytes,alignment,__builtin_return_address(0));
 assert(destination==0x8055001f && out && bytes==48 && alignment==1);
 struct packet *p=calloc(1,sizeof *p);assert(p);p->size=bytes;*out=p->data;return 0;
}
void fixture_set_source(void *,unsigned) __asm__("osal_set_msg_src");
void fixture_set_source(void *message,unsigned source){assert(message && source==0x80c70047);allocation(message)->source=source;}
int fixture_free(unsigned,void *) __asm__("osal_free_msg");
int fixture_free(unsigned destination,void *message){
 assert(message);struct packet *p=allocation(message);assert(p->size==48);
 if(destination==0x8055001f){assert(p->source==0x80c70047);++request_freed;}
 else{assert(destination==0x80c70047 && p->source==0x8055001f);++reply_freed;}
 memset(p,0,sizeof *p);free(p);return 0;
}
int fixture_send(unsigned,void *) __asm__("osal_snd_msg");
int fixture_send(unsigned destination,void *message){
 assert(destination==0x8055001f && message);struct packet *p=allocation(message);
 assert(p->size==48 && p->source==0x80c70047);
 pthread_mutex_lock(&bus);assert(!request_packet);request_packet=p;pthread_cond_signal(&arrived);pthread_mutex_unlock(&bus);return 0;
}
uint32_t fixture_thread(void) __asm__("osal_thread_id");
uint32_t fixture_thread(void){return 0x555;}
int fixture_cpu(uint32_t,unsigned) __asm__("osal_set_cpu");
int fixture_cpu(uint32_t thread,unsigned cpu){assert(thread==0x555 && cpu==15);return 0;}
uint32_t fixture_receive(void *,uint32_t,void *,uint32_t) __asm__("_ZN21DataflowInfraReceiver12ReceiveASyncEjP16DataflowInfraMsgj");
uint32_t fixture_receive(void *receiver,uint32_t destination,void *message,uint32_t timeout){
 assert(receiver && destination==0x8055001f && message && timeout==UINT32_MAX);
 pthread_mutex_lock(&bus);while(!request_packet)pthread_cond_wait(&arrived,&bus);
 struct packet *p=request_packet;request_packet=NULL;memcpy(incoming48,p->data,48);source_copy=p->source;pthread_mutex_unlock(&bus);
 received_object=message;assert(!fixture_free(destination,p->data));return 0;
}
void fixture_source(void *,uint32_t *) __asm__("_ZN16DataflowInfraMsg8GetSrcIdEPj");
void fixture_source(void *message,uint32_t *source){assert(message==received_object && source);*source=source_copy;}
uint32_t fixture_message(void *,void *,uint16_t) __asm__("_ZN16DataflowInfraMsg6GetMsgEPvt");
uint32_t fixture_message(void *message,void *out,uint16_t bytes){assert(message==received_object && out && bytes==48);memcpy(out,incoming48,48);return 0;}
uint16_t fixture_mid(void *,uint16_t,uint16_t) __asm__("_ZN20InfraAvbbcMsgManager13ConvertCmdMidEtt");
uint16_t fixture_mid(void *object,uint16_t category,uint16_t code){assert(object==manager && category==4 && code==0x8405);return code;}
int fixture_manager_send(void *,uint32_t,const uint8_t *,uint32_t) __asm__("_ZN20InfraAvbbcMsgManager10OsalSndMsgEjPKhj");
int fixture_manager_send(void *object,uint32_t destination,const uint8_t *body,uint32_t bytes){
 assert(object==manager && body);
 if(destination==0x80550123){
  assert(bytes==64 && !routed);memcpy(route64,body,64);++routed;
  _Alignas(16) uint8_t ack_object[40]={0};put64(ack_object+0x10,(uintptr_t)manager);put64(ack_object+0x18,(uintptr_t)control);put32(ack_object+0x20,0x80c70047);
  assert(!resize_ack(ack_object,route64+8));return 0;
 }
 if(destination==0x80c70047){
  assert(bytes==44 && body[2]==2 && body[3]==0x10 && get32(body+0x24)==0x4e0 && !copied);
  struct packet *p=calloc(1,sizeof *p);assert(p);p->size=48;p->source=0x8055001f;memcpy(p->data,body,bytes);
  pthread_mutex_lock(&bus);ack_order=++clock_order;pthread_mutex_unlock(&bus);
  callback(p->data,NULL);assert(reply_freed==1);return 0;
 }
 assert(destination==0x8055068a && bytes==40);void *nativeP=NULL;
 assert(!control_get(control,0x104a,&nativeP) && nativeP && nativeP!=(void *)input_info.parameter_cpu);
 assert(!memcmp(nativeP,(void *)input_info.parameter_cpu,128));memcpy(copied128,nativeP,128);
 pthread_mutex_lock(&bus);++copied;copy_order=++clock_order;pthread_mutex_unlock(&bus);return 0;
}
static int running(void *object){assert(object);return !routed;}
static void (*router_main)(void *);
static uint8_t router[48];
static void *router_thread(void *unused){(void)unused;router_main(router);return NULL;}
#define LOAD(target,library,name) do {void *sym=dlsym(library,name);assert(sym);memcpy(&(target),&sym,sizeof sym);} while(0)
#define SET(table,offset,name) do {void (*f)(void)=(void (*)(void))name;memcpy(table+offset,&f,sizeof f);} while(0)
static uint8_t *read_file(const char *name,size_t *size){FILE *f=fopen(name,"rb");assert(f && !fseek(f,0,SEEK_END));long n=ftell(f);assert(n>0);rewind(f);*size=(size_t)n;uint8_t *raw=malloc(*size);assert(raw && fread(raw,1,*size,f)==*size && !fclose(f));return raw;}
static void save(const char *name,const void *p,size_t bytes){FILE *f=fopen(name,"wb");assert(f && fwrite(p,1,bytes,f)==bytes && !fclose(f));}
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc,char **argv){
 assert(argc==6);size_t frame_bytes;uint8_t *frame=read_file(argv[1],&frame_bytes);uint8_t request[16]={5,0,0x38,0x40,29,0,0,0,2},p128[128]={0},q48[48];p128[0x63]=8;put16(p128+0x68,128);put16(p128+0x6a,64);
 assert(!capture_input_create(frame,frame_bytes,request,p128,&input));assert(!capture_input_info(input,&input_info));struct capture_input_mapping hold={0};assert(!capture_resize_request_build(input,request,q48,&hold));
 void *osal=dlopen(argv[5],RTLD_NOW|RTLD_GLOBAL);assert(osal);void *crypto=dlopen(argv[4],RTLD_NOW|RTLD_GLOBAL);assert(crypto);void *mpr=dlopen(argv[2],RTLD_LAZY|RTLD_GLOBAL);assert(mpr);void *infra=dlopen(argv[3],RTLD_LAZY|RTLD_GLOBAL);assert(infra);
 unsigned (*send_original)(const uint8_t *,void *)=NULL;void (*expected)(uint32_t *,void **)=NULL;
 LOAD(send_original,mpr,"_ZN3mpr5Codec14SendMsgToAvbbcEP10PayloadMprP12PayloadCodec");
 LOAD(expected,mpr,"_ZN3mpr5Codec21GetExpectedCodecEventERNS0_9IntFactorEPP12PayloadCodec");
 void *writer=dlsym(mpr,"_ZN3mpr10DmmMemInfo9SetMemTblEjiPNS0_11BufferTableE");Dl_info location;assert(writer && dladdr(writer,&location) && location.dli_fbase);
 void *entry=(uint8_t *)location.dli_fbase+0x283e74;memcpy(&callback,&entry,sizeof callback);
 LOAD(router_main,infra,"_ZN12InfraAvbbcIf4MainEv");LOAD(resize_ack,infra,"_ZN20ExecCmd_ResizeEncAck7ExecCmdEPKh");
 _Alignas(16) uint8_t router_vtable[48]={0};SET(router_vtable,0x28,running);
 void (*control_ctor)(void *,void *,uint32_t)=NULL,(*control_dtor)(void *)=NULL;
 LOAD(control_ctor,infra,"_ZN14AvbbcParamCtrl16ParameterControlC1EPN12ParamCtrlDef11PARAM_TABLEEj");
 LOAD(control_dtor,infra,"_ZN14AvbbcParamCtrl16ParameterControlD1Ev");
 LOAD(control_get,infra,"_ZN14AvbbcParamCtrl16ParameterControl8GetValueEjRPv");
 void *ctor=NULL;memcpy(&ctor,&control_ctor,sizeof ctor);Dl_info control_location;assert(dladdr(ctor,&control_location) && control_location.dli_fbase);
 control_ctor(control,(uint8_t *)control_location.dli_fbase+0x1b7dc8,0x80550123);
 put64(router,(uintptr_t)router_vtable);put64(router+0x20,(uintptr_t)manager);put32(manager+8,0x8055001f);
 pthread_t worker;assert(!pthread_create(&worker,NULL,router_thread,NULL));
 assert(send_original(q48,NULL)==1);
 uint32_t factor=0;void *reply=(void *)1;expected(&factor,&reply);assert(factor==2 && !reply);
 pthread_mutex_lock(&bus);assert(request_freed==1 && ack_order && !sender_returned);
 assert(capture_input_destroy(input)==-EBUSY);sender_returned=1;sender_order=++clock_order;pthread_cond_signal(&arrived);pthread_mutex_unlock(&bus);
 assert(!pthread_join(worker,NULL));assert(copied==1 && request_freed==1 && reply_freed==1 && !memcmp(copied128,(void *)input_info.parameter_cpu,128));assert(ack_order<sender_order && ack_order<copy_order);
 save("actual-original-sender-Q48.bin",incoming48,48);save("actual-original-route-S64.bin",route64,64);save("actual-original-copy-P128.bin",copied128,128);
 uint8_t order[24];put64(order,ack_order);put64(order+8,sender_order);put64(order+16,copy_order);save("actual-original-order24.bin",order,24);
 control_dtor(control);assert(!capture_input_drop(input,&hold) && !capture_input_destroy(input));free(frame);
 puts("PASS actual-original-SendMsgToAvbbc-ResizeEncAck-CallbackFromAvbbc ACK1_wait_reset2 original_ParameterControl=1 deep_copy128=1 request_free=1 reply_free=1 input_hold=1 IO_fixture=1 ParameterControl_fixture=0 original_AP=0 capture_verified=0");return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack){__libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();}
