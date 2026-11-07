/* SPDX-License-Identifier: MIT */
/* Real model STATE bytes provided by fixture, explicit host OSAL transport. */
#define _GNU_SOURCE
#include "imaging-device.c"
#include <assert.h>
#include <stdlib.h>
#include <sys/wait.h>
struct block {unsigned size,source,pool;uint8_t bytes[32];};
static void *reply;
static int inline_receive,send_error,free_error,allocate_error;
static unsigned sends,frees,allocs;
static int reply_size_delta,allocate_after_error,null_reply;
static void *alias_reply;
static unsigned verified_unwritten,felock_unavailable,felock_received,felock_freed;
static unsigned focus_applied_logs,focus_received_logs,focus_free_logs,focus_backend_calls;
static int focus_mode;
static struct full_imaging_focus_reset_receipt actual_focus_receipt;
static unsigned char actual_query_state[128];
static unsigned query_backend_calls,query_logs,query_received,query_freed;
static int query_mode;
static int apply_query(const unsigned char original[12],unsigned char out[128]){
 ++query_backend_calls;assert(u16(original+2)==0x403e && u32(original+8)==0x10f01u);
 if(query_mode==151)assert(full_imaging_functional_bind_focus_query(apply_query)==-EBUSY);
 if(query_mode==132)return -ENODATA;
 memcpy(out,actual_query_state,128);
 if(query_mode==133)out[48]^=1;
 if(query_mode==134)put32(out+56,0);
 if(query_mode==135)put32(out+112,0);
 if(query_mode==136)out[0]^=1;
 if(query_mode==137)put32(out+104,1);
 if(query_mode==138)put32(out+108,1);
 if(query_mode==139)out[120]=1;
 if(query_mode==150)((unsigned char *)original)[11]=1;
 if(query_mode==159)memset(out,0,128);
 return 0;
}
static int other_query(const unsigned char original[12],unsigned char out[128]){
 (void)original;(void)out;return -ENOSYS;
}
_Static_assert(sizeof(struct full_imaging_focus_reset_receipt)==360,"raw focus receipt layout");
static int apply_focus(const unsigned char original[16],struct full_imaging_focus_reset_receipt *out){
 ++focus_backend_calls;
 if(focus_mode==123){struct full_imaging_snapshot s;full_imaging_snapshot(&s);assert(s.functional_busy);
  assert(full_imaging_functional_bind_focus_reset(apply_focus)==-EBUSY);}
 if(focus_mode==103)return -ENODATA;
 *out=actual_focus_receipt;
 if(focus_mode==104)out->state[0]^=1;
 if(focus_mode==105)out->canonical[4]^=1;
 if(focus_mode==106)out->result[96]=8;
 if(focus_mode==107)out->result[16]^=1;
 if(focus_mode==108)out->result[56]^=1;
 if(focus_mode==109)out->result[116]=0;
 if(focus_mode==110)out->result[191]^=1;
 if(focus_mode==121)((unsigned char *)original)[8]=1;
 if(focus_mode==122)out->origin_fnv^=1;
 if(focus_mode==125)out->state[48]^=1;
 if(focus_mode==126)out->result[72]^=1;
 return 0;
}
static int other_focus(const unsigned char original[16],struct full_imaging_focus_reset_receipt *out){
 (void)original;(void)out;return -ENOSYS;
}
static void observed_record(const char *tag,const char *text){
 assert(tag && text);
 if(strstr(tag,"FUNCTIONAL_CAMERA_FELOCK_")){
  assert(strstr(text,"cmd=0x3020") && strstr(text,"status=0xf001") && strstr(text,"flash_lock_available=0") && strstr(text,"capture_verified=0"));
  assert(!strstr(text,"position_available="));
  if(strstr(tag,"UNAVAILABLE")){assert(strstr(text,FULL_IMAGING_FELOCK_POLICY));++felock_unavailable;}
  if(strstr(tag,"REPLY_RECEIVED"))++felock_received;
  if(strstr(tag,"REPLY_FREE"))++felock_freed;
 }else if(strstr(tag,"FUNCTIONAL_CAMERA_FOCUS_QUERY")){
  assert(strstr(text,"cmd=0x403e") && strstr(text,"bytes=16") && strstr(text,"capture_verified=0"));
  if(!strcmp(tag,"FUNCTIONAL_CAMERA_FOCUS_QUERY ")){assert(strstr(text,FULL_IMAGING_FOCUS_QUERY_POLICY) && strstr(text,"state=") && strstr(text,"checkpoint_fnv="));++query_logs;}
  if(strstr(tag,"REPLY_RECEIVED"))++query_received;
  if(strstr(tag,"REPLY_FREE"))++query_freed;
 }else if(strstr(tag,"FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_RESET_REQUEST ")){
  assert(strstr(text,"cmd=0x403f") && strstr(text,"request_bytes=16") && strstr(text,"raw=05003f40") && strstr(text,FULL_IMAGING_FOCUS_RESET_POLICY));
 }else if(strstr(tag,"FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_BACKEND ")){
  assert(strstr(text,"cmd=0x403f") && strstr(text,"backend_rc=") && strstr(text,"capture_verified=0"));
 }else if(strstr(tag,"FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_APPLIED")){
  assert(strstr(text,"cmd=0x403f") && strstr(text,"status=0xf000") && strstr(text,"magnification_disabled=1") && strstr(text,"capture_verified=0"));
  if(strstr(tag,"APPLIED ")){assert(strstr(text,FULL_IMAGING_FOCUS_RESET_POLICY));++focus_applied_logs;}
  if(strstr(tag,"REPLY_RECEIVED"))++focus_received_logs;
  if(strstr(tag,"REPLY_FREE"))++focus_free_logs;
 }else if(strstr(tag,"FUNCTIONAL_CAMERA_LENS_POSITION_") || strstr(tag,"FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_")){
  assert(strstr(text,"position_available=0") && !strstr(text,"flash_lock_available="));
 }
}
static struct block *block(void *p){return (void *)((uint8_t *)p-3*sizeof(unsigned));}
static int allocate(unsigned pool,void **out,unsigned size,unsigned mode){
 assert(mode==1 && size<=32);++allocs;if(allocate_error)return allocate_error;
 if(pool==FULL_IMAGING_AP){if(alias_reply){*out=alias_reply;return allocate_after_error;}if(null_reply){*out=NULL;return 0;}}
 struct block *p=calloc(1,sizeof *p);assert(p);p->size=size+(pool==FULL_IMAGING_AP?reply_size_delta:0);p->pool=pool;*out=p->bytes;
 if(pool==FULL_IMAGING_AP)return allocate_after_error;
 return 0;
}
static int release(unsigned pool,void *p){
 assert(p && block(p)->pool==pool);
 if(pool==FULL_IMAGING_AP && (reply_size_delta || allocate_after_error)){for(unsigned i=0;i<32;++i)assert(!((uint8_t *)p)[i]);++verified_unwritten;}
 if(pool==FULL_IMAGING_AP && free_error)return free_error;
 ++frees;free(block(p));return 0;
}
static void set_source(void *p,unsigned source){block(p)->source=source;}
static unsigned get_source(void *p){return block(p)->source;}
static unsigned get_size(void *p){return block(p)->size;}
static int send(unsigned pool,void *p){assert(pool==FULL_IMAGING_AP);++sends;if(send_error)return send_error;reply=p;
 if(inline_receive){full_imaging_functional_observe_receive(pool,p,get_source(p),get_size(p));int rc=99;assert(full_imaging_release_reply(pool,p,release,observed_record,&rc)==1 && !rc);reply=NULL;}
 return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,get_size,get_source,observed_record};
static void *request(unsigned command,unsigned mask,unsigned lock){void *p=NULL;unsigned size=command==0x414d?8:command==0x403d || command==0x403f?16:12;unsigned pool=command==0x414d || command==0x3020?FULL_IMAGING_LENS_POSITION_CP:FULL_IMAGING_CP;assert(!allocate(pool,&p,size,1));memset(p,0,size);uint8_t *b=p;b[0]=command==0x3020?0:5;b[2]=(uint8_t)command;b[3]=(uint8_t)(command>>8);put32(b+4,0x1234);if(size>=12)put32(b+8,mask);if(size==16)b[12]=(uint8_t)lock;set_source(p,FULL_IMAGING_AP);return p;}
static void drain(void){assert(reply);full_imaging_functional_observe_receive(FULL_IMAGING_AP,reply,get_source(reply),get_size(reply));int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,observed_record,&rc)==1 && !rc);reply=NULL;}
static void *receive_on_other_thread(void *unused){
 (void)unused;assert(reply);full_imaging_functional_observe_receive(FULL_IMAGING_AP,reply,get_source(reply),get_size(reply));return NULL;
}
int main(int argc,char **argv){
 assert(argc==3 || argc==4);int mode=atoi(argv[2]);assert(argc==(mode>=97?4:3));uint8_t state128[128];FILE *f=fopen(argv[1],"rb");assert(f && fread(state128,1,128,f)==128 && fgetc(f)==EOF && !fclose(f));
 uint64_t instance=u64(state128+48),generation=u64(state128+56);assert(instance && generation);
 if(mode==0){assert(full_imaging_capture_begin_functional(state128,128,instance,generation)==-ENODEV);return 0;}
 assert(!full_imaging_functional_enable());assert(full_imaging_functional_enable()==-EALREADY);
 assert(full_imaging_capture_begin()==-16);
 if(mode>=2 && mode<=17){
  const unsigned at[]={0,4,8,12,16,20,48,56,64,104,108,112,120,124,8,12};unsigned p=at[mode-2];
  if(mode<8 || mode==16 || mode==17)put32(state128+p,mode==16 || mode==17?8193:0);
  else if(mode==11 || mode==12 || mode==14 || mode==15)put32(state128+p,1);
  else memset(state128+p,0,8);
  assert(full_imaging_capture_begin_functional(state128,128,instance,generation)!=0);
 }else if(mode==18){assert(full_imaging_capture_begin_functional(state128,127,instance,generation)==-EINVAL);
 }else if(mode==19){assert(full_imaging_capture_begin_functional(state128,128,instance+1,generation)!=0);
 }else if(mode==20){assert(full_imaging_capture_begin_functional(state128,128,instance,generation+1)!=0);
 }else if(mode>=21 && mode<=28){
  unsigned mask=(mode==22 || mode==24)?0x200000:0x8000;int result=1;void *p=request(0x403d,mask,1);
  if(mode==23)inline_receive=1;
  if(mode==25)send_error=-ENOSPC;
  if(mode==26)allocate_error=-ENOMEM;
  if(mode==27){assert(!full_imaging_capture_begin_functional(state128,128,instance,generation));}
  int handled=full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,&result);assert(handled==1);
  if(mode>=25 && mode<=27){assert(result==(mode==25?-ENOSPC:mode==26?-ENOMEM:-EBUSY));assert(!release(FULL_IMAGING_CP,p));if(mode==27)full_imaging_capture_end();}
  else{
   assert(!result);if(reply){if(mode==28){int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,NULL,&rc)==1 && rc==-EPROTO);}drain();}
   assert(full_imaging_capture_begin_functional(state128,128,instance,generation)==-EBUSY);
   p=request(0x403d,mask,0);assert(full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,&result)==1 && !result);if(reply)drain();
  }
  struct full_imaging_snapshot s;full_imaging_snapshot(&s);assert(s.requested==FULL_IMAGING_POWER_ON_INHIBIT && !s.faults && !s.live_replies);
  assert(!full_imaging_capture_begin_functional(state128,128,instance,generation));full_imaging_capture_end();
 }else if(mode==29){
  void *p=request(0x403d,FULL_IMAGING_POWER_ON_INHIBIT,0);int result=1;assert(full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,&result)==1 && result==-ENOTSUP);assert(!release(FULL_IMAGING_CP,p));
 }else if(mode==30){
  void *p=request(0x4040,FULL_IMAGING_POWER_ON_INHIBIT,0);int result=1;assert(full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,&result)==1 && !result && reply && get_size(reply)==16);assert(u32((uint8_t *)reply+8)==0xf001 && u32((uint8_t *)reply+12)==FULL_IMAGING_POWER_ON_INHIBIT);drain();
 }else if(mode==31){
  pthread_mutex_lock(&mutex);pid_t child=fork();assert(child>=0);if(!child)_exit(full_imaging_capture_begin_functional(state128,128,instance,generation)==-ECHILD?0:1);int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));pthread_mutex_unlock(&mutex);
 }else if(mode>=33 && mode<=40){
  if(mode==37){void *first=request(0x4040,FULL_IMAGING_POWER_ON_INHIBIT,0);int result=1;
   assert(full_imaging_functional_dispatch(FULL_IMAGING_CP,first,&io,&result)==1 && !result && reply);}
  void *p=request(0x403d,0x8000,1);uint8_t request_before[16],reply_before[16];memcpy(request_before,p,16);
  if(mode==33 || mode==39)reply_size_delta=-1;
  if(mode==34)reply_size_delta=1;
  if(mode==35)alias_reply=p;
  if(mode==36)alias_reply=(uint8_t *)p+1;
  if(mode==37){alias_reply=reply;memcpy(reply_before,reply,16);}
  if(mode==38)allocate_after_error=-ENOSPC;
  if(mode==39)free_error=-EIO;
  if(mode==40)null_reply=1;
  unsigned sent_before=sends,freed_before=frees;int result=1;
  int expected=mode==38?-ENOSPC:mode==40?-ENOMEM:mode>=35 && mode<=37?-EINVAL:-EMSGSIZE;
  assert(full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,&result)==1 && result==expected);
  assert(sends==sent_before && !memcmp(p,request_before,16));
  if(mode==37)assert(!memcmp(reply,reply_before,16));
  assert(verified_unwritten==((mode==33 || mode==34 || mode==38 || mode==39)?1u:0u));
  struct full_imaging_snapshot s;full_imaging_snapshot(&s);
  assert(s.requested==FULL_IMAGING_POWER_ON_INHIBIT && !s.functional_busy && s.faults==(mode==39));
  assert(s.live_replies==((mode==37 || mode==39)?1u:0u));
  assert(frees-freed_before==((mode==33 || mode==34 || mode==38)?1u:0u));
  alias_reply=NULL;assert(!release(FULL_IMAGING_CP,p));if(mode==37)drain();
 }else if(mode>=41 && mode<=96){
  int original_mode=mode,magnification=(mode>=57 && mode<=72) || mode==74,felock=mode>=75;
  if(mode>=57 && mode<=72)mode-=16;
  else if(mode>=75 && mode<=90)mode-=34;
  else if(mode>=91)mode=original_mode==95?50:41;
  else if(mode>=73)mode=41;
  unsigned command=felock?0x3020:magnification?0x403f:0x414d,request_bytes=felock?12:magnification?16:8,reply_bytes=felock || magnification?12:24;
  unsigned expected_source=magnification?FULL_IMAGING_CP:FULL_IMAGING_LENS_POSITION_CP;
  void *p=request(command,original_mode==92?1:0,0);uint8_t saved[16];unsigned destination=expected_source;int result=1;
  if(mode==42)inline_receive=1;
  if(mode==43)set_source(p,0x80020003);
  if(mode==44)((uint8_t *)p)[0]=felock?5:0;
  if(mode==45)((uint8_t *)p)[1]=1;
  if(mode==46)block(p)->size=7;
  if(mode==47)destination=magnification?FULL_IMAGING_LENS_POSITION_CP:FULL_IMAGING_CP;
  if(original_mode==93 || original_mode==94)put32((uint8_t *)p+8,original_mode==93?2:0x100);
  if(mode==48)send_error=-ENOSPC;
  if(mode==49)allocate_error=-ENOMEM;
  if(mode==50)reply_size_delta=original_mode==95?1:-1;
  if(mode==51)alias_reply=p;
  if(mode==52)alias_reply=(uint8_t *)p+1;
  if(mode==53)block(p)->size=9;
  memcpy(saved,p,request_bytes);unsigned sent_before=sends,freed_before=frees;
  if(mode==54){assert(full_imaging_dispatch(destination,p,&io,&result)==magnification);if(magnification)assert(result==-1021);assert(sends==sent_before);assert(!release(expected_source,p));}
  else{
   int handled=full_imaging_functional_dispatch(destination,p,&io,&result);
   if((mode>=43 && mode<=53) || original_mode==93 || original_mode==94){
    assert(handled==(mode!=47));
    if(mode!=47)assert(result==(mode==48?-ENOSPC:mode==49?-ENOMEM:mode==50?-EMSGSIZE:mode==51 || mode==52?-EINVAL:-ENOTSUP));
    assert(sends-sent_before==(mode==48));assert(!memcmp(p,saved,request_bytes));
    assert(frees-freed_before==((mode==48 || mode==50)?1u:0u));alias_reply=NULL;
    assert(!release(expected_source,p));
   }else{
    assert(handled==1 && !result);
    if(mode==42)assert(!reply && frees-freed_before==2);
    else{
     uint8_t expected[24]={1,0,0x4d,0x41,0x34,0x12,0,0,1,0xf0,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
     expected[2]=(uint8_t)command;expected[3]=(uint8_t)(command>>8);
     assert(reply && get_size(reply)==reply_bytes && get_source(reply)==expected_source && !memcmp(reply,expected,reply_bytes));
     assert(u32((uint8_t *)reply+8)!=0xf000); /* Original query takes its error exit. */
     if(mode==55){int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,NULL,&rc)==1 && rc==-EPROTO);}
     if(mode==56){full_imaging_functional_observe_receive(FULL_IMAGING_AP,reply,get_source(reply),get_size(reply));((uint8_t *)reply)[reply_bytes-4]^=1;int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,observed_record,&rc)==1 && rc==-EBADMSG);((uint8_t *)reply)[reply_bytes-4]^=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,observed_record,&rc)==1 && !rc);reply=NULL;}
     else if(original_mode==73 || original_mode==74 || original_mode==91){pthread_t receiver;assert(!pthread_create(&receiver,NULL,receive_on_other_thread,NULL) && !pthread_join(receiver,NULL));int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,observed_record,&rc)==1 && !rc);reply=NULL;}
     else{if(original_mode==96){full_imaging_functional_observe_receive(FULL_IMAGING_AP,reply,0,get_size(reply));int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,NULL,&rc)==1 && rc==-EPROTO);}drain();}
    }
   }
  }
  struct full_imaging_snapshot s;full_imaging_snapshot(&s);
  assert(!s.live_replies && !s.functional_busy && !s.active_capture && !s.applied);
  assert(s.faults==(mode==56 || original_mode==96));
  if(felock && (mode==41 || mode==42 || mode==55 || mode==56) && original_mode!=93 && original_mode!=94){
   assert(felock_unavailable==1 && felock_received>=1 && felock_freed>=1);
  }
 }else if(mode>=97 && mode<=126){
  focus_mode=mode;FILE *input=fopen(argv[3],"rb");assert(input);
  assert(fread(&actual_focus_receipt,1,sizeof actual_focus_receipt,input)==sizeof actual_focus_receipt && fgetc(input)==EOF && !fclose(input));
  if(mode!=100){assert(!full_imaging_functional_bind_focus_reset(apply_focus));assert(!full_imaging_functional_bind_focus_reset(apply_focus));}
  if(mode==118)assert(full_imaging_functional_bind_focus_reset(other_focus)==-EALREADY);
  if(mode==119){assert(full_imaging_functional_bind_focus_reset(NULL)==-EINVAL);pthread_mutex_lock(&mutex);
   pid_t child=fork();assert(child>=0);if(!child)_exit(full_imaging_functional_bind_focus_reset(apply_focus)==-ECHILD?0:1);
   int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));pthread_mutex_unlock(&mutex);}
  void *p=request(0x403f,mode==101?1:0,mode==102?1:0);int result=1;
  if(mode==98)inline_receive=1;
  if(mode==111)reply_size_delta=-1;
  if(mode==112)alias_reply=p;
  if(mode==113)allocate_error=-ENOMEM;
  if(mode==114)send_error=-ENOSPC;
  if(mode==117)((unsigned char *)p)[0]=0;
  if(mode==120)reply_size_delta=1;
  if(mode==124)set_source(p,0x80020003);
  assert(full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,&result)==1);
  int pre_error=mode==111 || mode==112 || mode==113 || mode==117 || mode==120 || mode==124;
  int model_error=(mode>=103 && mode<=110) || mode==122 || mode==125 || mode==126;
  int fallback=mode==100 || mode==101 || mode==102 || model_error;
  if(pre_error || mode==114 || mode==121){
   assert(result==(mode==111 || mode==120?-EMSGSIZE:mode==112?-EINVAL:mode==113?-ENOMEM:
                  mode==114?-ENOSPC:mode==121?-EBADMSG:-ENOTSUP));
   assert(!reply);alias_reply=NULL;assert(!release(FULL_IMAGING_CP,p));
  }else{
   assert(!result);
   if(mode!=98){assert(reply && get_size(reply)==12 && get_source(reply)==FULL_IMAGING_CP);
    assert(u32((uint8_t *)reply+8)==(fallback?0xf001u:0xf000u));
    if(mode==115){int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,NULL,&rc)==1 && rc==-EPROTO);}
    if(mode==99){pthread_t receiver;assert(!pthread_create(&receiver,NULL,receive_on_other_thread,NULL) && !pthread_join(receiver,NULL));
     int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,observed_record,&rc)==1 && !rc);reply=NULL;
    }else if(mode==116){full_imaging_functional_observe_receive(FULL_IMAGING_AP,reply,get_source(reply),get_size(reply));
     ((uint8_t *)reply)[8]^=1;int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,observed_record,&rc)==1 && rc==-EBADMSG);
     ((uint8_t *)reply)[8]^=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,observed_record,&rc)==1 && !rc);reply=NULL;
    }else drain();
   }
  }
  unsigned called=!(pre_error || mode==100 || mode==101 || mode==102);
  struct full_imaging_snapshot s;full_imaging_snapshot(&s);
  assert(focus_backend_calls==called && s.focus_reset_requests==called && s.focus_reset_failed==(unsigned)(model_error || mode==121));
  unsigned accepted=!(pre_error || fallback || mode==114 || mode==121);
  assert(s.focus_reset_applied==accepted && focus_applied_logs==accepted);
  assert(!s.functional_busy && !s.live_replies && !s.active_capture && !s.applied && s.faults==(unsigned)(mode==116 || mode==121));
  if(accepted){assert(s.focus_model_instance==u64(actual_focus_receipt.result+8) && s.focus_config_generation==u64(actual_focus_receipt.result+16));
   assert(s.focus_frame_generation==u64(actual_focus_receipt.result+24) && s.focus_result_fnv==focus_hash(actual_focus_receipt.result,192));
   assert(focus_received_logs==1 && focus_free_logs==(mode==116?2u:1u));}
 }else if(mode>=127 && mode<=159){
  query_mode=mode;FILE *input=fopen(argv[3],"rb");assert(input);
  assert(fread(&actual_focus_receipt,1,sizeof actual_focus_receipt,input)==sizeof actual_focus_receipt && fgetc(input)==EOF && !fclose(input));
  memcpy(actual_query_state,state128,128);
  assert(full_imaging_functional_bind_focus_query(NULL)==-EINVAL);
  if(mode!=131){assert(!full_imaging_functional_bind_focus_query(apply_query));assert(!full_imaging_functional_bind_focus_query(apply_query));}
  if(mode==153)assert(full_imaging_functional_bind_focus_query(other_query)==-EALREADY);
  if(mode==154){pthread_mutex_lock(&mutex);pid_t child=fork();assert(child>=0);
   if(!child)_exit(full_imaging_functional_bind_focus_query(apply_query)==-ECHILD?0:1);
   int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));pthread_mutex_unlock(&mutex);}
  if(mode!=130){assert(!full_imaging_functional_bind_focus_reset(apply_focus));void *reset=request(0x403f,0,0);int rc=1;
   assert(full_imaging_functional_dispatch(FULL_IMAGING_CP,reset,&io,&rc)==1 && !rc && reply && u32((uint8_t *)reply+8)==0xf000);drain();}
  if(mode==152)focus_checkpoint.result[160]^=1;
  if(mode==157)assert(!full_imaging_capture_begin_functional(state128,128,instance,generation));
  if(mode==158){void *pending=request(0x4040,FULL_IMAGING_POWER_ON_INHIBIT,0);int rc=1;
   assert(full_imaging_functional_dispatch(FULL_IMAGING_CP,pending,&io,&rc)==1 && !rc && reply);}
  void *p=request(0x403e,mode==140?0:0x10f01u,0);unsigned destination=FULL_IMAGING_CP;int result=1;
  if(mode==128)inline_receive=1;
  if(mode==141)set_source(p,0x80020003);
  if(mode==142)block(p)->size=11;
  if(mode==143)((uint8_t *)p)[0]=0;
  if(mode==144)((uint8_t *)p)[1]=1;
  if(mode==145)destination=FULL_IMAGING_LENS_POSITION_CP;
  if(mode==146)reply_size_delta=-1;
  if(mode==147)allocate_error=-ENOMEM;
  if(mode==148)alias_reply=p;
  if(mode==149)send_error=-ENOSPC;
  unsigned char before[12];memcpy(before,p,12);
  unsigned called_before=query_backend_calls;int handled=full_imaging_functional_dispatch(destination,p,&io,&result);
  int pre=(mode>=140 && mode<=148) || mode==157 || mode==158;
  int unavailable=(mode>=130 && mode<=139) || mode==152 || mode==159;
  if(pre || mode==149 || mode==150){
   assert(handled==(mode!=145));
   if(mode!=145)assert(result==(mode==146?-EMSGSIZE:mode==147?-ENOMEM:mode==148?-EINVAL:mode==149?-ENOSPC:
                          mode==150?-EBADMSG:mode==157 || mode==158?-EBUSY:-ENOTSUP));
   assert(!memcmp(p,before,12));alias_reply=NULL;assert(!release(FULL_IMAGING_CP,p));
   if(mode==158)drain();else assert(!reply);
  }else{
   assert(handled==1 && !result);
   if(mode!=128){assert(reply && get_size(reply)==16 && get_source(reply)==FULL_IMAGING_CP);
    assert(u16((uint8_t *)reply)==1 && u16((uint8_t *)reply+2)==0x403e && u32((uint8_t *)reply+4)==0x1234);
    assert(u32((uint8_t *)reply+8)==(unavailable?0xf001u:0xf000u));
    assert(u32((uint8_t *)reply+12)==(unavailable?0:u32(actual_focus_receipt.canonical+4)));
    if(mode==129){pthread_t receiver;assert(!pthread_create(&receiver,NULL,receive_on_other_thread,NULL) && !pthread_join(receiver,NULL));
     int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,observed_record,&rc)==1 && !rc);reply=NULL;
    }else if(mode==155){full_imaging_functional_observe_receive(FULL_IMAGING_AP,reply,get_source(reply),get_size(reply));
     ((uint8_t *)reply)[12]^=1;int rc=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,observed_record,&rc)==1 && rc==-EBADMSG);
     ((uint8_t *)reply)[12]^=1;assert(full_imaging_release_reply(FULL_IMAGING_AP,reply,release,observed_record,&rc)==1 && !rc);reply=NULL;
    }else drain();
   }
  }
  unsigned called=!pre && mode!=130 && mode!=131;
  assert(query_backend_calls-called_before==called);
  struct full_imaging_snapshot s;full_imaging_snapshot(&s);
  assert(s.focus_query_requests==(unsigned)!pre && s.focus_query_succeeded==(unsigned)(!pre && !unavailable && mode!=149 && mode!=150));
  assert(s.focus_query_failed==(unsigned)(!pre && (unavailable || mode==150)));
  assert(query_logs==(unsigned)(!pre && mode!=149 && mode!=150));
  if(query_logs)assert(query_received==1 && query_freed==(mode==155?2u:1u));
  assert(!s.functional_busy && !s.live_replies && s.faults==(unsigned)(mode==150 || mode==155));
  if(mode==157)full_imaging_capture_end();
 }else{
  assert(!full_imaging_capture_begin_functional(state128,128,instance,generation));assert(full_imaging_capture_begin_functional(state128,128,instance,generation)==-EBUSY);
  struct full_imaging_snapshot s;full_imaging_snapshot(&s);assert(s.active_capture==1 && s.functional_instance==instance && s.functional_generation==generation && s.requested==FULL_IMAGING_POWER_ON_INHIBIT && s.effective==FULL_IMAGING_POWER_ON_INHIBIT);
  full_imaging_capture_end();assert(full_imaging_capture_begin()==-16);
 }
 struct full_imaging_snapshot s;full_imaging_snapshot(&s);assert(s.requested==FULL_IMAGING_POWER_ON_INHIBIT && s.effective==FULL_IMAGING_POWER_ON_INHIBIT && !s.active_capture);
 puts("PASS HOST_ONLY actual-State128-functional-admission strict-cold-04000000-preserved original-interlocks-owner original_CP_D012=0 capture_verified=0");return 0;
}
