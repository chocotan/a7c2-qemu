/* SPDX-License-Identifier: MIT */
/* HOSTTEST: actual extracted main hooks, real facade/DMM/registry, host IO only. */
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "functional-face-runtime.h"
#include "functional-face-ap-observer.h"
#include "device-models/functional-camera-control.h"
#include "dmm-service.h"

#define QUEUE UINT32_C(0x81cf1234)
#define OBJECT_BYTES 0x3553000u
/* Independent FINAL source-contract anchors and mode-zero request bytes. */
static const struct {unsigned int op;size_t ret;uint32_t bl;const char *hex;} goldens[] = {
 {0x20,0x35522a4,UINT32_C(0x9784320c),"20000000d901000000000000ffffffff000000000000000000000000000000000000000000000000"},
 {0x21,0x3552c60,UINT32_C(0x97842f9d),"21000000d90100000284000000000000000000000000000000000000000000000000000000000000"},
 {0x23,0x35524a8,UINT32_C(0x9784318b),"23000000000000000284000000000000000000003412000000000000000000000000000000000000"},
 {0x24,0x3552694,UINT32_C(0x97843110),"240000000000000002840000ffffffff000000000000000000000000000000000000000000000000"},
 {0x25,0x35528ac,UINT32_C(0x9784308a),"25000000000000000284000000000000000000000000000000000000000000000000000000000000"}
};
struct message {void *wire;unsigned int source,bytes,request;};
static struct message messages[128];
static void *queued[16];static unsigned int queue_ids[16],queue_count;
static unsigned char *object;static void *fixture_caller;static unsigned long appfw_base;
static int functional_camera_enabled=1,functional_camera_setup_error,cp_owned_state_enabled;
/* ACTUAL_FACE_DECLARATIONS */
static unsigned int allocations,request_frees,reply_frees,free_attempts,sends,receives,fallback_frees;
static unsigned int control_calls,dl_calls,open_calls,read_calls,close_calls,records,retained_logs;
static unsigned int callback_snapshots,model_busy_snapshots,source_logs,dmm_logs,legacy_calls;
static int reentry,in_snapshot,request_failure,reply_failure,send_failure,receive_result;
static int control_initialized=1,control_started=1,control_faults;
static int dl_result=1,wrong_base,null_base,null_name,open_failure,read_mode;
static const char *library_name="/system/lib/appFw.so";
static char last_prefix[96],last_text[4096],source_text[512],dmm_text[512];
static struct functional_face_runtime_snapshot diagnostic;
static int dmm_enabled;
static _Thread_local unsigned int native_receive_depth;
static unsigned int functional_mpr_codec_used,functional_vdf_path_used,functional_layout_stage_used;
static _Thread_local struct {void *pointer;unsigned int destination;uint64_t cycle;} functional_vdf_ticket;
static _Thread_local struct {void *pointer;unsigned int destination;uint64_t cycle;} functional_layout_stage_ticket;

static uint64_t hash(const void *p,size_t n){
 const unsigned char *s=p;uint64_t h=UINT64_C(14695981039346656037);
 for(size_t i=0;i<n;i++)h=(h^s[i])*UINT64_C(1099511628211);
 return h;
}
static void put(void *p,uint64_t v,unsigned int n){
 unsigned char *s=p;for(unsigned int i=0;i<n;i++)s[i]=(unsigned char)(v>>(8*i));
}
static struct message *metadata(void *p){
 for(unsigned int i=0;i<128;i++)if(messages[i].wire==p && p)return &messages[i];
 assert(!"message must have real live transport metadata");return NULL;
}
static struct message *new_message(unsigned int bytes,unsigned int source,unsigned int request){
 for(unsigned int i=0;i<128;i++)if(!messages[i].wire){
  messages[i]=(struct message){malloc(bytes),source,bytes,request};assert(messages[i].wire);
  memset(messages[i].wire,0,bytes);return &messages[i];
 }
 abort();
}
static void destroy(struct message *m){assert(m && m->wire);free(m->wire);memset(m,0,sizeof *m);}
static void callback_snapshot(void){
 if(!reentry || in_snapshot)return;
 in_snapshot=1;struct functional_face_runtime_snapshot *s=malloc(sizeof *s);assert(s);
 assert(!functional_face_runtime_snapshot(s));callback_snapshots++;
 assert(s->model_snapshot_result==0 || s->model_snapshot_result==-EBUSY);
 if(s->model_snapshot_result==-EBUSY)model_busy_snapshots++;
 free(s);in_snapshot=0;
}
static void record(const char *prefix,const char *text){
 assert(prefix && text && strlen(prefix)<sizeof last_prefix && strlen(text)<sizeof last_text);
 assert(strlen(prefix)>0 && prefix[strlen(prefix)-1]==' ');
 strcpy(last_prefix,prefix);strcpy(last_text,text);records++;
 if(!strcmp(prefix,"FUNCTIONAL_FACE_DMM_SOURCE_BOUND ")){
  assert(strlen(text)<sizeof source_text);strcpy(source_text,text);source_logs++;
  assert(strstr(text,"producer=process-local-software-owner") && strstr(text,"original_cp_verified=0"));
 }else if(!strcmp(prefix,"DMM_REQUEST ")){
  assert(strlen(text)<sizeof dmm_text);strcpy(dmm_text,text);dmm_logs++;
 }else if(!strcmp(prefix,"FUNCTIONAL_FACE_DMM_TICKET_RETAINED ")){
  assert(strstr(text,"no_refresh=1"));retained_logs++;
 }else{
  assert(!strncmp(prefix,"FUNCTIONAL_FACE_DMM_",20));
  assert(strstr(text,"physical_verified=0") && strstr(text,"capture_verified=0"));
 }
 callback_snapshot();errno=ERANGE;
}
static int allocate_api(unsigned int queue,void **out,unsigned int bytes,unsigned int wait){
 assert(queue==QUEUE && out && bytes==40 && wait==1);callback_snapshot();allocations++;
 *out=new_message(bytes,0,0)->wire;errno=EDOM;return 0;
}
static int free_api(unsigned int id,void *p){
 struct message *m=metadata(p);callback_snapshot();free_attempts++;
 assert(id==(m->request?FUNCTIONAL_FACE_DMM_CP:m->source==FUNCTIONAL_FACE_DMM_CP?QUEUE:id));
 if(m->request && request_failure)return -73;
 if(!m->request && reply_failure)return -74;
 if(m->request)request_frees++;else reply_frees++;
 destroy(m);errno=EINTR;return 0;
}
static void source_set_api(void *p,unsigned int source){callback_snapshot();metadata(p)->source=source;errno=EDOM;}
static unsigned int source_api(void *p){callback_snapshot();errno=EDOM;return metadata(p)->source;}
static unsigned int size_api(void *p){callback_snapshot();errno=EDOM;return metadata(p)->bytes;}
static int send_api(unsigned int id,void *p){
 callback_snapshot();assert(id==QUEUE && metadata(p)->source==FUNCTIONAL_FACE_DMM_CP);sends++;
 if(send_failure)return -77;
 assert(queue_count<16);queued[queue_count]=p;queue_ids[queue_count++]=id;errno=E2BIG;return 0;
}
static int (*real_allocate_msg)(unsigned int,void **,unsigned int,unsigned int)=allocate_api;
static int (*real_free_msg)(unsigned int,void *)=free_api;
static void (*real_set_source)(void *,unsigned int)=source_set_api;
static int (*real_send_msg)(unsigned int,void *)=send_api;
static unsigned int (*real_msg_size)(void *)=size_api,(*real_get_source)(void *)=source_api;
static long fixture_syscall(long n){assert(n==178);return syscall(SYS_gettid);}
#define syscall fixture_syscall
static int memory_open(const char *path,int flags){
 assert(!strcmp(path,"/proc/self/mem") && !flags);open_calls++;
 if(open_failure){errno=EACCES;return -1;}
 int fd=open(path,flags);assert(fd>=0);errno=EDOM;return fd;
}
static ssize_t memory_read(int fd,void *out,size_t bytes,off_t offset){
 assert(bytes==4 && (uintptr_t)offset==(uintptr_t)fixture_caller-4);read_calls++;
 ssize_t rc=pread(fd,out,bytes,offset);assert(rc==4);
 /* A real source byte mutation occurs between the two original reads. */
 if(read_mode==2 && (read_calls&1u))((unsigned char *)fixture_caller)[-4]^=1;
 if(read_mode==3 && (read_calls&1u))return 3;
 if(read_mode==4 && !(read_calls&1u))return 3;
 if(read_mode==5)return -1;
 errno=EIO;return rc;
}
static int memory_close(int fd){close_calls++;int rc=close(fd);assert(!rc);errno=EBADF;return rc;}
#define open memory_open
#define pread memory_read
#define close memory_close
static int dladdr_api(const void *p,Dl_info *info){
 assert(p==fixture_caller && info);dl_calls++;info->dli_fbase=null_base?NULL:object+wrong_base;
 info->dli_fname=null_name?NULL:library_name;errno=EDOM;return dl_result;
}
static int (*real_dladdr)(const void *,Dl_info *)=dladdr_api;
void native_functional_camera_control_snapshot(struct native_functional_camera_control_snapshot *s){
 assert(s);control_calls++;s->model_initialized=(unsigned int)control_initialized;
 s->start_complete=(unsigned int)control_started;s->faults=(unsigned int)control_faults;errno=EDOM;
}
/* Unrelated owners are inert; the actual original receive gate is retained. */
static void native_background_start_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;}
static void native_histogram_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;}
static int functional_vdf_layout_stage_observe_receive_cycle(unsigned int id,void *p,unsigned int source,unsigned int bytes,uint64_t *ticket){
 (void)id;(void)p;(void)source;(void)bytes;(void)ticket;assert(0);return 0;
}
static int functional_vdf_path_observe_receive_cycle(unsigned int id,void *p,unsigned int source,unsigned int bytes,uint64_t *ticket){
 (void)id;(void)p;(void)source;(void)bytes;(void)ticket;assert(0);return 0;
}
static int functional_camera_events_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;return 0;}
static int functional_jpeg_codec_observe_received(unsigned int id,void *p,const struct full_imaging_io *io){(void)id;(void)p;(void)io;return 0;}
static int functional_mpr_codec_observe_received(unsigned int id,void *p,const struct full_imaging_io *io){(void)id;(void)p;(void)io;assert(0);return 0;}
int native_cp_state_publication_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;return 0;}
static void native_hdmi_video_received(unsigned int id,void **p,int rc){(void)id;(void)p;(void)rc;}
static int receive_api(unsigned int id,void **out,long timeout){
 assert(id==QUEUE && timeout==27 && native_receive_depth && out && queue_count);receives++;
 assert(queue_ids[0]==id);*out=queued[0];errno=ERANGE;
 if(receive_result)return receive_result;
 for(unsigned int i=1;i<queue_count;i++){queued[i-1]=queued[i];queue_ids[i-1]=queue_ids[i];}
 queue_count--;return 0;
}
static int (*real_u_rcv_msg_tmo)(unsigned int,void **,long)=receive_api;
static int trace_media_mount_completion(const char *prefix,unsigned int id,void *p){
 assert(!strcmp(prefix,"FULL_MEDIA_MOUNT_FREE_ENTER "));(void)id;(void)p;return 0;
}
static int dmm_send(void *p,unsigned long caller,unsigned long frame){
 assert(p && caller==(unsigned long)fixture_caller && !frame);legacy_calls++;return 123;
}
static int ap_send_result;
static int ap_send_api(unsigned int id,void *message){
 assert(id==FUNCTIONAL_FACE_AP_DMM && metadata(message)->bytes==40);sends++;errno=EINTR;return ap_send_result;
}
static int gui_model_service_send(unsigned int id,void *message,int *result){
 (void)message;(void)result;assert(id==FUNCTIONAL_FACE_AP_DMM);return 0;
}
static void functional_face_native_birth_observe(const struct functional_face_ap_observer *s) { assert(s); }
/* ACTUAL_AP_RECORD */
/* ACTUAL_FACE_HELPERS */
/* ACTUAL_CP_RECEIVE */
/* ACTUAL_FACE_FREE */
static int actual_send(unsigned int id,void *message){
/* ACTUAL_DMM_DISPATCH */
 return -999;
}
static int actual_ap_send(unsigned int id,void *message){
/* ACTUAL_AP_SEND */
 return result;
}
static int actual_ap_free(unsigned int id,void *message){
/* ACTUAL_AP_FREE */
 *__errno_location()=saved_errno;return result;
}
static void origin(unsigned int op){
 for(unsigned int i=0;i<sizeof goldens/sizeof *goldens;i++)if(goldens[i].op==op){
  fixture_caller=object+goldens[i].ret;memcpy((unsigned char *)fixture_caller-4,&goldens[i].bl,4);return;
 }
 assert(0);
}
static struct message *request(unsigned int op,unsigned int unit,unsigned int handle){
 struct message *m=new_message(40,QUEUE,1);
 for(unsigned int k=0;k<sizeof goldens/sizeof *goldens;k++)if(goldens[k].op==op){
  assert(strlen(goldens[k].hex)==80);
  for(unsigned int j=0;j<40;j++){
   unsigned int byte;assert(sscanf(goldens[k].hex+2*j,"%2x",&byte)==1);((unsigned char *)m->wire)[j]=(unsigned char)byte;
  }
  if(op==0x20 || op==0x21)put((unsigned char *)m->wire+4,unit,4);
  if(op!=0x20)put((unsigned char *)m->wire+8,handle,4);
  if(op==0x23)put((unsigned char *)m->wire+0x14,QUEUE&0xffffu,2);
  origin(op);return m;
 }
 abort();
}
static void snapshot(void){
 assert(!functional_face_runtime_snapshot(&diagnostic));assert(!diagnostic.model_snapshot_result);
 assert(!diagnostic.physical_verified && !diagnostic.original_cp_verified && !diagnostic.native_capture_verified);
}
static struct functional_face_dmm_descriptor lookup(unsigned int unit){
 struct functional_face_dmm_descriptor d;assert(!functional_face_runtime_lookup_creator(functional_face_producer_owner(),unit,&d));return d;
}
static void reject_main(struct message *m,unsigned int id,int expected,int direct){
 unsigned char before[40];memcpy(before,m->wire,40);struct message meta=*m;
 unsigned int old_alloc=allocations,old_free=free_attempts,old_send=sends;
 int result=91;errno=EAGAIN;
 if(direct){int claimed=native_functional_face_send(id,m->wire,fixture_caller,&result);assert(claimed==!!expected);if(!claimed)assert(result==91);else assert(result==expected);}
 else assert(actual_send(id,m->wire)==expected);
 assert(!memcmp(before,m->wire,40) && !memcmp(&meta,m,sizeof meta));
 assert(allocations==old_alloc && free_attempts==old_free && sends==old_send);destroy(m);
}
static void queue_request(unsigned int op,unsigned int unit,unsigned int handle){
 struct message *m=request(op,unit,handle);unsigned int frees=request_frees,reads=read_calls;
 assert(!actual_send(FUNCTIONAL_FACE_DMM_CP,m->wire));
 assert(request_frees==frees+1 && read_calls==reads+2 && queue_count);
}
static void *receive_success(void){
 void *p=NULL;errno=EAGAIN;assert(!u_osal_rcv_msg_tmo(QUEUE,&p,27) && p && errno==ERANGE);
 assert(functional_face_ticket.actual.reply==(uintptr_t)p && functional_face_ticket.actual.destination==QUEUE);
 return p;
}
static struct functional_face_runtime_ticket complete(int status){
 void *p=receive_success();struct functional_face_runtime_ticket t=functional_face_ticket;
 assert(t.transaction && t.actual.nonce && t.producer_owner==functional_face_producer_owner());
 assert(!memcmp(t.actual.wire,p,40));assert((int16_t)((unsigned int)t.actual.wire[2]|(unsigned int)t.actual.wire[3]<<8)==status);
 unsigned int attempts=free_attempts,fallback=fallback_frees;errno=EDOM;
 assert(!osal_free_msg(QUEUE,p) && errno==EDOM && free_attempts==attempts+1 && fallback_frees==fallback);
 assert(!functional_face_ticket.actual.reply);return t;
}
static struct functional_face_runtime_ticket operation(unsigned int op,unsigned int unit,unsigned int handle,int status){
 queue_request(op,unit,handle);return complete(status);
}
static struct functional_face_dmm_descriptor create(unsigned int unit){
 queue_request(0x20,unit,0);struct functional_face_dmm_descriptor d,untouched;
 memset(&d,0xa5,sizeof d);untouched=d;
 assert(functional_face_runtime_lookup_creator(functional_face_producer_owner(),unit,&d)==-ENODATA);
 assert(!memcmp(&d,&untouched,sizeof d));snapshot();
 assert(diagnostic.model.units[unit-0x1d9].allocated && !diagnostic.units[unit-0x1d9].live_creator);
 uint64_t commits=diagnostic.ledger_commit;void *p=receive_success();
 struct functional_face_runtime_ticket ticket=functional_face_ticket;
 assert(functional_face_runtime_lookup_creator(functional_face_producer_owner(),unit,&d)==-ENODATA);
 snapshot();assert(diagnostic.ledger_commit==commits);
 native_functional_face_received(QUEUE,p);assert(!memcmp(&ticket,&functional_face_ticket,sizeof ticket));
 unsigned int attempts=free_attempts;assert(!osal_free_msg(QUEUE,p) && free_attempts==attempts+1 && !fallback_frees);
 d=lookup(unit);assert(!memcmp(&d,&ticket.actual.span,sizeof d));return d;
}
static void units_test(void){
 struct dmm_service speech={.physical=DMM_TEST_PHYSICAL};speech.memory=malloc(DMM_TEST_SIZE);assert(speech.memory);
 unsigned char q[40]={0x20},r[40];put(q+4,0x63a,4);put(q+22,1,2);
 for(unsigned int i=0;i<2;i++){assert(!dmm_service_reply(&speech,q,40,r));speech.slots[i].creator_kind=DMM_CREATOR_SPEECH_INITIAL;assert(speech.slots[i].handle==0x8400u+i);}
 for(size_t i=0;i<DMM_TEST_SIZE;i++)speech.memory[i]=(unsigned char)(i^(i>>9)^0x95);
 struct dmm_service speech_before;memcpy(&speech_before,&speech,sizeof speech);
 unsigned char *speech_bytes=malloc(DMM_TEST_SIZE);assert(speech_bytes);memcpy(speech_bytes,speech.memory,DMM_TEST_SIZE);
 uint64_t written=0,read=0;
 for(unsigned int i=0;i<3;i++){
  struct functional_face_dmm_descriptor d=create(0x1d9+i);
  assert(d.domain==1 && d.unit==0x1d9+i && d.handle==0x8402+i && d.epoch==i+1 && !d.reference);
  assert(d.owner==functional_face_producer_owner() && d.host_view && d.registration);
  assert(d.bytes==(i==0?409600u:i==1?51200u:53504u));
  assert(d.logical==FUNCTIONAL_FACE_REGISTRY_IOVA+i*FUNCTIONAL_FACE_REGISTRY_WINDOW);
  struct functional_face_runtime_ticket opened=operation(0x24,d.unit,d.handle,0);
  (void)operation(0x23,d.unit,d.handle,-1);
  (void)operation(0x25,d.unit,d.handle,0);
  struct functional_face_runtime_ticket shared=operation(0x21,d.unit,d.handle,0);
  assert(opened.actual.span.reference && shared.actual.span.reference && opened.actual.span.reference!=shared.actual.span.reference);
  (void)operation(0x25,d.unit,d.handle,0);
  unsigned char *pattern=malloc(d.bytes),*copy=malloc(d.bytes);assert(pattern && copy);
  for(size_t j=0;j<d.bytes;j++)pattern[j]=(unsigned char)((j*29+i*97+23)^(j>>7));
  struct functional_face_dmm_borrow b;struct functional_face_dmm_readback rb;
  assert(!functional_face_runtime_borrow_destination(functional_face_producer_owner(),d.unit,d.handle,&d,0,d.bytes,FUNCTIONAL_FACE_DMM_WRITE|FUNCTIONAL_FACE_DMM_TRANSFER,&b));
  assert(!functional_face_dmm_write(&b,0,pattern,d.bytes,&rb));
  assert(rb.verified_bytes==d.bytes && rb.after_digest==hash(pattern,d.bytes));
  assert(!functional_face_dmm_release_borrow(&b,&rb) && rb.verified_bytes==d.bytes);
  assert(!functional_face_runtime_borrow_destination(functional_face_producer_owner(),d.unit,d.handle,&d,0,d.bytes,FUNCTIONAL_FACE_DMM_READ,&b));
  assert(!functional_face_dmm_read(&b,0,copy,d.bytes,&rb));assert(rb.verified_bytes==d.bytes && !memcmp(pattern,copy,d.bytes));
  (void)operation(0x23,d.unit,d.handle,-1);snapshot();assert(diagnostic.units[i].live_creator && diagnostic.model.units[i].borrows==1);
  assert(!functional_face_dmm_release_borrow(&b,&rb));snapshot();
  written+=diagnostic.model.units[i].verified_write_bytes;read+=diagnostic.model.units[i].verified_read_bytes;
  printf("BYTES unit=%x bytes=%zu digest=%016" PRIx64 "\n",d.unit,d.bytes,hash(copy,d.bytes));
  (void)operation(0x23,d.unit,d.handle,0);snapshot();
  assert(diagnostic.units[i].retired && !diagnostic.units[i].live_creator && !diagnostic.model.units[i].allocated);
  free(copy);free(pattern);
 }
 snapshot();assert(written==514304 && read==514304 && diagnostic.ledger_commit==18);
 assert(!diagnostic.live_creators && !diagnostic.opens && !diagnostic.shares && !diagnostic.tickets && !diagnostic.faults && !diagnostic.retained);
 assert(diagnostic.actual_receive==24 && diagnostic.actual_request_free==24 && diagnostic.actual_reply_free==24);
 assert(request_frees==24 && reply_frees==24 && allocations==24 && sends==24 && receives==24);
 assert(!memcmp(&speech,&speech_before,sizeof speech) && !memcmp(speech.memory,speech_bytes,DMM_TEST_SIZE));
 assert(!functional_face_dmm_shutdown());free(speech_bytes);free(speech.memory);
 puts("COUNTS units=3 write=514304 read=514304 request_free=24 reply_free=24 ledger_commit=18 speech_unchanged=1");
}
static void caller_test(void){
 for(unsigned int i=0;i<sizeof goldens/sizeof *goldens;i++){
  origin(goldens[i].op);errno=EAGAIN;
  assert(!functional_face_original_caller(goldens[i].op,fixture_caller,QUEUE) && errno==EAGAIN);
  assert(read_calls==(i+1)*2 && open_calls==i+1 && close_calls==i+1 && source_logs==i+1);
  char anchor[48];snprintf(anchor,sizeof anchor,"caller_va=%#lx",(unsigned long)goldens[i].ret);
  assert(strstr(source_text,anchor) && strstr(source_text,"reads=4/4"));
 }
 assert(!allocations && !control_calls);
 puts("CALLER anchors=5 actual_pread=10 physical_verified=0 original_cp_verified=0");
}
static void negative_test(const char *mode){
 struct message *m=request(0x20,0x1d9,0);int expected=-ELIBBAD,claimed=1;
 unsigned int id=FUNCTIONAL_FACE_DMM_CP;
 if(!strcmp(mode,"disabled") || !strcmp(mode,"strict")){functional_camera_enabled=0;claimed=0;}
 else if(!strcmp(mode,"non-cp")){id=0x0061003c;claimed=0;}
 else if(!strcmp(mode,"null")){
  int result=91;assert(!native_functional_face_send(id,NULL,fixture_caller,&result) && result==91);
  assert(!allocations && !source_logs && !control_calls);destroy(m);return;
 }else if(!strcmp(mode,"size39")){m->bytes=39;claimed=0;}
 else if(!strcmp(mode,"size41")){m->bytes=41;claimed=0;}
 else if(!strcmp(mode,"other-unit")){put((unsigned char *)m->wire+4,0x1dc,4);claimed=0;}
 else if(!strcmp(mode,"op2a")){put(m->wire,0x2a,2);claimed=0;}
 else if(!strcmp(mode,"speech0") || !strcmp(mode,"speech1") || !strcmp(mode,"share-speech")){
  unsigned int op=!strcmp(mode,"share-speech")?0x21:0x24;destroy(m);m=request(op,0x63a,0x8400u+!strcmp(mode,"speech1"));claimed=0;
 }else if(!strcmp(mode,"no-size")){real_msg_size=NULL;claimed=0;}
 else if(!strcmp(mode,"no-source"))real_get_source=NULL;
 else if(!strcmp(mode,"bad-library-base"))wrong_base=4;
 else if(!strcmp(mode,"bad-appfw-base"))appfw_base+=4;
 else if(!strcmp(mode,"bad-suffix"))library_name="/system/lib/appFw.so.bad";
 else if(!strcmp(mode,"bad-prefix"))library_name="/system/lib/notappFw.so";
 else if(!strcmp(mode,"bad-va"))fixture_caller=(unsigned char *)fixture_caller+4;
 else if(!strcmp(mode,"null-caller"))fixture_caller=NULL;
 else if(!strcmp(mode,"dladdr-failed"))dl_result=0;
 else if(!strcmp(mode,"null-library"))null_name=1;
 else if(!strcmp(mode,"null-base"))null_base=1;
 else if(!strcmp(mode,"no-dladdr"))real_dladdr=NULL;
 else if(!strcmp(mode,"first-bl"))((unsigned char *)fixture_caller)[-4]^=1;
 else if(!strcmp(mode,"second-bl"))read_mode=2;
 else if(!strcmp(mode,"short-first"))read_mode=3;
 else if(!strcmp(mode,"short-second"))read_mode=4;
 else if(!strcmp(mode,"read-error"))read_mode=5;
 else if(!strcmp(mode,"open-failed"))open_failure=1;
 else if(!strcmp(mode,"source0"))m->source=0;
 else if(!strcmp(mode,"source-cp"))m->source=FUNCTIONAL_FACE_DMM_CP;
 else if(!strcmp(mode,"source-max"))m->source=UINT32_MAX;
 else if(!strcmp(mode,"source-domain")){m->source=0x02821234;expected=-EPROTO;}
 else if(!strcmp(mode,"control-uninit")){control_initialized=0;expected=-ENODATA;}
 else if(!strcmp(mode,"control-not-started")){control_started=0;expected=-ENODATA;}
 else if(!strcmp(mode,"control-fault")){control_faults=1;expected=-ENODATA;}
 else if(!strcmp(mode,"setup-error")){functional_camera_setup_error=-71;expected=-71;}
 else abort();
 reject_main(m,id,claimed?expected:0,1);
 if(!claimed)assert(!source_logs && !control_calls && !dl_calls && !open_calls && !read_calls);
 if(read_mode || !strcmp(mode,"first-bl"))assert(read_calls==2 && open_calls==1 && close_calls==1);
 if(!strcmp(mode,"open-failed"))assert(open_calls==1 && !read_calls && !close_calls);
 if(expected==-ELIBBAD)assert(!control_calls);
}
static void canonical_test(void){
 struct functional_face_dmm_descriptor d=create(0x1d9);unsigned int mutations=0;
 for(unsigned int k=0;k<sizeof goldens/sizeof *goldens;k++)for(unsigned int byte=2;byte<40;byte++){
  if(byte>=4 && byte<12)continue;
  struct message *m=request(goldens[k].op,d.unit,d.handle);((unsigned char *)m->wire)[byte]^=1;
  reject_main(m,FUNCTIONAL_FACE_DMM_CP,-EPROTO,1);mutations++;
 }
 assert(mutations==150);(void)operation(0x23,d.unit,d.handle,0);
 puts("CANONICAL rejected_mutations=150 transport_callbacks=0");
}
static void saved_identity_test(void){
 struct functional_face_dmm_descriptor d=create(0x1d9),bad;
 struct functional_face_dmm_borrow b,before;memset(&b,0xa5,sizeof b);before=b;
#define BAD(field,value) do {bad=d;bad.field=(value);assert(functional_face_runtime_borrow_destination(functional_face_producer_owner(),d.unit,d.handle,&bad,0,1,FUNCTIONAL_FACE_DMM_READ,&b)==-ESTALE);assert(!memcmp(&b,&before,sizeof b));} while(0)
 BAD(unit,d.unit+1);BAD(handle,d.handle^1);BAD(domain,d.domain+1);BAD(epoch,d.epoch+1);BAD(owner,d.owner+1);
 BAD(reference,1);BAD(logical,d.logical+4096);BAD(registration,d.registration+1);BAD(host_view,d.host_view+1);
#undef BAD
 assert(functional_face_runtime_borrow_destination(functional_face_producer_owner()+1,d.unit,d.handle,&d,0,1,1,&b)==-EPERM);
 assert(functional_face_runtime_borrow_destination(functional_face_producer_owner(),d.unit,d.handle^1,&d,0,1,1,&b)==-ESTALE);
 assert(functional_face_runtime_borrow_destination(functional_face_producer_owner(),d.unit+1,d.handle,&d,0,1,1,&b)==-ENODATA);
 assert(!memcmp(&b,&before,sizeof b));(void)operation(0x23,d.unit,d.handle,0);
}
static void queued_test(void){
 queue_request(0x20,0x1d9,0);snapshot();assert(!diagnostic.ledger_commit && !diagnostic.actual_receive && diagnostic.actual_request_free==1);
 reject_main(request(0x24,0x1d9,0x8402),FUNCTIONAL_FACE_DMM_CP,-ESTALE,1);
 snapshot();assert(!diagnostic.ledger_commit && diagnostic.model.units[0].allocated);
 (void)complete(0);struct functional_face_dmm_descriptor d=lookup(0x1d9);(void)operation(0x23,d.unit,d.handle,0);
}
static void dispatch_test(void){
 struct functional_face_dmm_descriptor d=create(0x1d9);
 (void)operation(0x24,d.unit,d.handle,0);(void)operation(0x25,d.unit,d.handle,0);
 assert(!legacy_calls && dmm_logs==3 && strstr(dmm_text,"op=0x25") && strstr(dmm_text,"sampled=40 raw="));
 struct message *m=request(0x24,0x63a,0x8400);assert(actual_send(FUNCTIONAL_FACE_DMM_CP,m->wire)==-999);destroy(m);
 m=request(0x25,0x63a,0x8400);assert(actual_send(FUNCTIONAL_FACE_DMM_CP,m->wire)==-999);destroy(m);
 functional_camera_enabled=0;dmm_enabled=1;
 m=request(0x24,d.unit,d.handle);assert(actual_send(FUNCTIONAL_FACE_DMM_CP,m->wire)==-999);destroy(m);
 m=request(0x25,d.unit,d.handle);assert(actual_send(FUNCTIONAL_FACE_DMM_CP,m->wire)==-999);destroy(m);
 m=request(0x20,0x63a,0);assert(actual_send(FUNCTIONAL_FACE_DMM_CP,m->wire)==123);destroy(m);
 m=request(0x21,0x63a,0x8400);assert(actual_send(FUNCTIONAL_FACE_DMM_CP,m->wire)==123);destroy(m);
 m=request(0x20,d.unit,0);put(m->wire,0x2a,2);assert(actual_send(FUNCTIONAL_FACE_DMM_CP,m->wire)==123);destroy(m);
 assert(legacy_calls==3);dmm_enabled=0;
 m=request(0x20,0x63a,0);assert(actual_send(FUNCTIONAL_FACE_DMM_CP,m->wire)==-999);destroy(m);
 functional_camera_enabled=1;(void)operation(0x23,d.unit,d.handle,0);
}
static void free_no_ticket(void *p,int expected){
 unsigned int attempts=free_attempts,fallback=fallback_frees;int result=91;errno=EAGAIN;
 assert(native_functional_face_release(QUEUE,p,&result)==1 && result==expected && errno==EAGAIN);
 assert(free_attempts==attempts && fallback_frees==fallback);
}
static void receive_gate_test(const char *mode){
 queue_request(0x20,0x1d9,0);void *p=queued[0];
 if(!strcmp(mode,"receive-failure")){
  receive_result=-91;void *actual=NULL;
  assert(u_osal_rcv_msg_tmo(QUEUE,&actual,27)==-91 && actual==p && !functional_face_ticket.actual.reply);
  snapshot();assert(!diagnostic.actual_receive && !diagnostic.ledger_commit);receive_result=0;
 }else if(!strcmp(mode,"receive-gates")){
  native_cp_state_received(QUEUE,NULL,0);void *empty=NULL;native_cp_state_received(QUEUE,&empty,0);
  native_cp_state_received(QUEUE,&p,-91);functional_camera_enabled=0;native_cp_state_received(QUEUE,&p,0);
  functional_camera_enabled=1;real_msg_size=NULL;native_cp_state_received(QUEUE,&p,0);real_msg_size=size_api;
  real_get_source=NULL;native_cp_state_received(QUEUE,&p,0);real_get_source=source_api;
  assert(!functional_face_ticket.actual.reply);snapshot();assert(!diagnostic.actual_receive);
 }
 free_no_ticket(p,-ESTALE);snapshot();assert(!diagnostic.actual_receive && !diagnostic.ledger_commit);
 (void)complete(0);struct functional_face_dmm_descriptor d=lookup(0x1d9);(void)operation(0x23,d.unit,d.handle,0);
}
static void ticket_test(const char *mode){
 queue_request(0x20,0x1d9,0);void *p=receive_success();struct functional_face_runtime_ticket t=functional_face_ticket;
 unsigned int before=free_attempts;
 if(!strcmp(mode,"wrong-queue")){
  int result=91;assert(native_functional_face_release(QUEUE+1,p,&result)==1 && result==-ESTALE);
 }else if(!strcmp(mode,"old-ticket")){
  functional_face_ticket.actual.nonce++;free_no_ticket(p,-ESTALE);functional_face_ticket=t;
 }else if(!strcmp(mode,"failed-free")){
  reply_failure=1;assert(osal_free_msg(QUEUE,p)==-74 && free_attempts==before+1);
  assert(!memcmp(&t,&functional_face_ticket,sizeof t));reply_failure=0;free_no_ticket(p,-EIO);
  assert(osal_free_msg(QUEUE,p)==-EIO && free_attempts==before+1 && !fallback_frees);
  snapshot();assert(diagnostic.retained==1 && diagnostic.faults && !diagnostic.ledger_commit);return;
 }else if(!strcmp(mode,"ticket-retained")){
  queue_request(0x20,0x1da,0);void *second=NULL;
  assert(!u_osal_rcv_msg_tmo(QUEUE,&second,27) && second && second!=p);
  assert(!memcmp(&t,&functional_face_ticket,sizeof t));snapshot();assert(diagnostic.actual_receive==1);
  free_no_ticket(second,-ESTALE);assert(!osal_free_msg(QUEUE,p));
  native_cp_state_received(QUEUE,&second,0);assert(functional_face_ticket.actual.reply==(uintptr_t)second);
  assert(!osal_free_msg(QUEUE,second));struct functional_face_dmm_descriptor d=lookup(0x1da);
  (void)operation(0x23,d.unit,d.handle,0);d=lookup(0x1d9);(void)operation(0x23,d.unit,d.handle,0);return;
 }else abort();
 assert(free_attempts==before && !memcmp(&t,&functional_face_ticket,sizeof t));
 assert(!osal_free_msg(QUEUE,p));struct functional_face_dmm_descriptor d=lookup(0x1d9);(void)operation(0x23,d.unit,d.handle,0);
}
struct thread_ticket {void *pointer;struct functional_face_runtime_ticket ticket;};
static void *wrong_thread(void *arg){
 struct thread_ticket *in=arg;void *p=in->pointer;
 assert(!functional_face_ticket.actual.reply);native_functional_face_received(QUEUE,p);
 assert(!functional_face_ticket.actual.reply);
 if(in->ticket.actual.reply)functional_face_ticket=in->ticket;
 free_no_ticket(p,-ESTALE);
 assert(!memcmp(&in->ticket,&functional_face_ticket,sizeof in->ticket));return NULL;
}
static void wrong_tid_test(void){
 queue_request(0x20,0x1d9,0);pthread_t thread;struct thread_ticket in={queued[0],{0}};
 assert(!pthread_create(&thread,NULL,wrong_thread,&in) && !pthread_join(thread,NULL));
 void *p=receive_success();struct functional_face_runtime_ticket saved=functional_face_ticket;
 in.ticket=saved;
 assert(!pthread_create(&thread,NULL,wrong_thread,&in) && !pthread_join(thread,NULL));
 assert(!memcmp(&saved,&functional_face_ticket,sizeof saved));assert(!osal_free_msg(QUEUE,p));
 struct functional_face_dmm_descriptor d=lookup(0x1d9);(void)operation(0x23,d.unit,d.handle,0);
}
static void failure_test(const char *mode){
 request_failure=!strcmp(mode,"request-free-failure");send_failure=!strcmp(mode,"send-failure");
 struct message *m=request(0x20,0x1d9,0);
 assert(actual_send(FUNCTIONAL_FACE_DMM_CP,m->wire)==(send_failure?-77:-EIO));
 snapshot();assert(!diagnostic.ledger_commit && !diagnostic.live_creators && !request_frees);
 if(request_failure){
  assert(diagnostic.retained==1 && diagnostic.faults);unsigned int attempts=free_attempts;
  request_failure=0;assert(osal_free_msg(FUNCTIONAL_FACE_DMM_CP,m->wire)==-EIO && free_attempts==attempts && !fallback_frees);
 }else{
  assert(!queue_count && reply_frees==1 && !diagnostic.retained && !diagnostic.model.units[0].span.host_view);
  destroy(m);send_failure=0;struct functional_face_dmm_descriptor d=create(0x1d9);(void)operation(0x23,d.unit,d.handle,0);
 }
}
static void fork_test(void){
 queue_request(0x20,0x1d9,0);void *p=receive_success();struct functional_face_runtime_ticket saved=functional_face_ticket;
 pid_t pid=fork();assert(pid>=0);
 if(!pid){
  unsigned int attempts=free_attempts;int result=91;errno=EAGAIN;
  native_functional_face_received(QUEUE,p);assert(!memcmp(&saved,&functional_face_ticket,sizeof saved));
  assert(native_functional_face_release(QUEUE,p,&result)==1 && result==-EXDEV && free_attempts==attempts && errno==EAGAIN);
  assert(osal_free_msg(QUEUE,p)==-EXDEV && free_attempts==attempts && !fallback_frees);
  _exit(0);
 }
 int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));
 assert(!osal_free_msg(QUEUE,p));struct functional_face_dmm_descriptor d=lookup(0x1d9);(void)operation(0x23,d.unit,d.handle,0);
}
static void pointer_test(void){
 queue_request(0x20,0x1d9,0);void *p=receive_success();uintptr_t retired=(uintptr_t)p;
 assert(!osal_free_msg(QUEUE,p));struct message *fresh=new_message(40,0x81234567,0);
 assert((uintptr_t)fresh->wire==retired);memset(fresh->wire,0xa5,40);
 native_functional_face_received(QUEUE,fresh->wire);assert(!functional_face_ticket.actual.reply);
 unsigned int before=free_attempts;assert(!osal_free_msg(QUEUE,fresh->wire));
 assert(free_attempts==before+1 && fallback_frees==1);
 puts("POINTER real_malloc_reuse=1 fallback_free_once=1");
 struct functional_face_dmm_descriptor d=lookup(0x1d9);(void)operation(0x23,d.unit,d.handle,0);
}
static void ambiguous_test(void){
 struct functional_face_dmm_descriptor d=create(0x1d9);
 (void)operation(0x24,d.unit,d.handle,0);(void)operation(0x21,d.unit,d.handle,0);
 reject_main(request(0x25,d.unit,d.handle),FUNCTIONAL_FACE_DMM_CP,-ENODATA,1);
 snapshot();assert(diagnostic.opens==1 && diagnostic.shares==1 && diagnostic.model.units[0].opens==1 && diagnostic.model.units[0].shares==1);
}
static void ap_observer_test(const char *mode){
 origin(0x20);struct message *q=request(0x20,0x1d9,0);q->request=0;
 unsigned char before[40];memcpy(before,q->wire,40);real_send_msg=ap_send_api;
 if(!strcmp(mode,"ap-observer-send-failure"))ap_send_result=-77;
 if(!strcmp(mode,"ap-observer-untrusted"))read_mode=2;
 int result=actual_ap_send(FUNCTIONAL_FACE_AP_DMM,q->wire);
 assert(result==ap_send_result && sends==1 && !allocations && !request_frees && !reply_frees && !control_calls);
 assert(!memcmp(before,q->wire,40) && !functional_face_used && !functional_face_ticket.actual.reply);
 if(ap_send_result){assert(!functional_face_ap_state.active && functional_face_ap_state.send_result==-77);return;}
 int traced=strcmp(mode,"ap-observer-untrusted")!=0;
 assert(functional_face_ap_state.active==(unsigned int)traced);
 struct message *reply=new_message(40,0x8061003c,0);put(reply->wire,0x8020,2);put((char *)reply->wire+12,0x409,4);
 put((char *)reply->wire+24,0x12345000,8);put((char *)reply->wire+32,0x64000,4);
 assert(!queue_count);queued[0]=reply->wire;queue_ids[0]=QUEUE;queue_count=1;
 void *received=NULL;assert(!u_osal_rcv_msg_tmo(QUEUE,&received,27) && received==reply->wire);
 assert(functional_face_ap_state.received==(unsigned int)traced && !functional_face_ticket.actual.reply);
 assert(!actual_ap_free(QUEUE,received) && reply_frees==1 && !functional_face_ap_state.active);
 if(traced){assert(functional_face_ap_state.free_attempts==1 && functional_face_ap_state.reply_source==0x8061003c);
  assert(strstr(last_text,"observation_only=1") && strstr(last_text,"allocation_pin_verified=0") && strstr(last_text,"native_byte_access_verified=0"));}
 assert(!allocations && !request_frees && !control_calls && !functional_face_used);
 puts("AP_MAIN original_send_once=1 metadata_unchanged=1 original_free_once=1 observation_only=1 native_pin=0");
}
int main(int argc,char **argv){
 assert(argc==2);const char *mode=argv[1];object=calloc(1,OBJECT_BYTES);assert(object);appfw_base=(unsigned long)object;
 if(!strncmp(mode,"ap-observer",11))ap_observer_test(mode);
 else if(!strcmp(mode,"units"))units_test();
 else if(!strcmp(mode,"caller-goldens"))caller_test();
 else if(!strcmp(mode,"queued") || !strcmp(mode,"no-snapshot-epoch"))queued_test();
 else if(!strcmp(mode,"canonical"))canonical_test();
 else if(!strcmp(mode,"saved-identity"))saved_identity_test();
 else if(!strcmp(mode,"dispatch"))dispatch_test();
 else if(!strcmp(mode,"receive-failure") || !strcmp(mode,"receive-gates") || !strcmp(mode,"no-free-observe"))receive_gate_test(mode);
 else if(!strcmp(mode,"ticket-retained") || !strcmp(mode,"wrong-queue") || !strcmp(mode,"old-ticket") || !strcmp(mode,"failed-free"))ticket_test(mode);
 else if(!strcmp(mode,"wrong-tid"))wrong_tid_test();
 else if(!strcmp(mode,"request-free-failure") || !strcmp(mode,"send-failure"))failure_test(mode);
 else if(!strcmp(mode,"fork"))fork_test();
 else if(!strcmp(mode,"pointer"))pointer_test();
 else if(!strcmp(mode,"ambiguous-close"))ambiguous_test();
 else if(!strcmp(mode,"reentry")){
  reentry=1;struct functional_face_dmm_descriptor d=create(0x1d9);(void)operation(0x23,d.unit,d.handle,0);
  assert(callback_snapshots>10 && model_busy_snapshots>10 && records>7);
  printf("REENTRY callback_snapshots=%u model_busy=%u\n",callback_snapshots,model_busy_snapshots);
 }else negative_test(mode);
 /* Fault tests retain model leases until process teardown; reclaim only host transport here. */
 for(unsigned int i=0;i<128;i++)if(messages[i].wire)destroy(&messages[i]);
 free(object);printf("FACE_WIRING_HOSTTEST_PASS mode=%s\n",mode);return 0;
}
