"""Host-side failure-path checks of the actual freestanding module init wrapper."""
from pathlib import Path
import subprocess


def test_failed_init_detaches_callback_or_retains_module(tmp_path):
    module = Path(__file__).resolve().parents[2] / 'report/virtual-cp/yc-inject/yc_inject.c'
    source = module.read_text()
    wrapper = source[source.index('int __attribute__((section(".init.text"))) init_module(void)'):]
    harness = r'''
#include <assert.h>
static unsigned int q_reply;
static int resources_owned;
static long cb_slot = 123;
static int result, unreg_result, unreg_calls;
static int start_injection(void) { return result; }
static int printk(const char *fmt, ...) { (void)fmt; return 0; }
static long osal_unreg_msg_queue_cb(unsigned int q, long slot) {
    assert(q == 0x8aa50751 && slot == 123);
    ++unreg_calls;
    return unreg_result;
}
'''
    harness += wrapper + r'''
int main(void) {
    /* Successful init and failed registration must not detach another queue. */
    result = 0; q_reply = 0x8aa50751;
    assert(init_module() == 0 && unreg_calls == 0);
    result = -1023; q_reply = 0;
    assert(init_module() == -1023 && unreg_calls == 0);
    /* Invalid PNG after registration: successful detach makes an error safe. */
    q_reply = 0x8aa50751; unreg_result = 0;
    assert(init_module() == -1023 && q_reply == 0 && unreg_calls == 1);
    /* Interrupted detach: returning zero retains the callback's module code. */
    q_reply = 0x8aa50751; unreg_result = -1;
    assert(init_module() == 0 && q_reply == 0x8aa50751 && unreg_calls == 2);
    resources_owned = 1;unreg_result = 0;
    assert(init_module() == 0 && q_reply == 0 && unreg_calls == 3);
    return 0;
}
'''
    path = tmp_path / 'failure.c'; path.write_text(harness)
    executable = tmp_path / 'failure'
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
    assert '.xword cleanup_module' not in module.with_name('descriptor.S').read_text()


def test_actual_allocator_requires_contiguous_bounded_segments(tmp_path):
    module = Path(__file__).resolve().parents[2]/'report/virtual-cp/yc-inject/yc_inject.c'
    source=module.read_text()
    helper=source[source.index('static int alloc_unit('):source.index('static int start_injection(')]
    harness=r'''
#include <assert.h>
#include <string.h>
typedef unsigned char u8;typedef unsigned short u16;typedef unsigned int u32;typedef unsigned long u64;
#define DMM_REQ_SIZE 0xd8u
static int s_got,resources_owned;static u8 s_reply[DMM_REQ_SIZE];static int mode;
static int printk(const char *fmt,...){(void)fmt;return 0;}
static u16 rd16(const u8*p){u16 v;memcpy(&v,p,2);return v;}
static u32 rd32(const u8*p){u32 v;memcpy(&v,p,4);return v;}
static u64 rd64(const u8*p){u64 v;memcpy(&v,p,8);return v;}
static void put32(u8*p,u32 v){memcpy(p,&v,4);}
static void put64(u8*p,u64 v){memcpy(p,&v,8);}
static int wait_for_op(u16 op,u32 pump,u32 timeout){(void)op;(void)pump;(void)timeout;return 1;}
static int dmm_send(u16 op,u32 type,u32 value){
 (void)type;(void)value;memset(s_reply,0,sizeof s_reply);put32(s_reply+0xc,0x415);
 if(op==0x2a){
  s_reply[8]=mode==3?13:2;
  put64(s_reply+0x18,0x428000000ul);put32(s_reply+0x20,0x200000);
  put64(s_reply+0x28,mode==1?0x429000000ul:0x428200000ul);
  put32(s_reply+0x30,mode==2?0:0x200000);
 }
 return 0;
}
'''
    main=r'''
int main(void){u32 h,len;u64 addr;
 assert(!alloc_unit(0x644,&h,&addr,&len,0));assert(h==0x415&&addr==0x428000000ul&&len==0x400000);
 assert(resources_owned);
 for(mode=1;mode<=3;mode++)assert(alloc_unit(0x644,&h,&addr,&len,0)==-1);
 return 0;}
'''
    path=tmp_path/'segments.c';path.write_text(harness+helper+main)
    binary=tmp_path/'segments'
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-no-pie',str(path),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)


def test_full_init_keeps_failed_shared_allocation_state(tmp_path):
    module=Path(__file__).resolve().parents[2]/'report/virtual-cp/yc-inject/yc_inject.c'
    fixture=r'''
#include <assert.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include "MODULE_SOURCE"
static int fault,allocations,shares,mappings,detaches,retained,done;
static unsigned callback_bytes=DMM_REQ_SIZE;
static void *mapped;
int printk(const char *fmt,...){
 if(strstr(fmt,"YCIN_RETAINED"))retained++;
 if(strstr(fmt,"YCIN_INIT_DONE"))done++;
 return 0;
}
long osal_reg_msg_queue_cb(u32 q,void *slot,void *cb,void *cookie){
 (void)q;(void)cb;(void)cookie;*(long*)slot=19;return 0;
}
long osal_unreg_msg_queue_cb(u32 q,long slot){assert(q&&slot==19);detaches++;return 0;}
long osal_valloc_msg_wait(u32 q,void **out,u32 size,u32 flags){
 (void)q;(void)flags;*out=calloc(1,size);return *out?0:-1;
}
long osal_set_msg_src(void *p,u32 src){(void)p;(void)src;return 0;}
long osal_free_msg(u32 q,void *p){(void)q;free(p);return 0;}
long osal_msg_size(void *p){(void)p;return callback_bytes;}
u32 osal_get_msg_src(void *p){(void)p;return Q_DMM_LOCAL;}
long osal_snd_msg(u32 q,void *message){
 if(q==Q_DMM_LOCAL){
  if(rd16(message)==0x28){
   assert(rd32((u8*)message+8)==pix_h);
   assert(rd16((u8*)message+0x14)==info_tag);
   assert(info_pending && !info_done);
   u8 *reply=calloc(1,40);assert(reply);
   put16(reply,0x8028);put16(reply+6,info_tag);put16(reply+8,1);
   put16(reply+10,3);put16(reply+12,2);put32(reply+16,pix_len);put32(reply+20,0x431);
   callback_bytes=40;yc_reply_cb(reply,0);free(message);return 0;
  }
  u16 op=rd16(message);memset(s_reply,0,sizeof s_reply);
  put16(s_reply,op|0x8000);put32(s_reply+0xc,0x415);put16(s_reply+8,1);
  put64(s_reply+0x18,0x428000000ul);put32(s_reply+0x20,0x400000);
  if(op==0x20)allocations++;
  if(op==0x21)shares++;
  if(op==0x2a&&fault){put16(s_reply+8,2);put64(s_reply+0x28,0x429000000ul);put32(s_reply+0x30,16);}
  s_got++;
 }else{s_out_connected=1;}
 free(message);return 0;
}
void *memremap(u64 pa,u64 size,int flags){(void)pa;(void)flags;mappings++;mapped=malloc(size);return mapped;}
void memunmap(void *p){assert(0);(void)p;}
void msleep(unsigned int n){(void)n;}
void *filp_open(const char *name,int flags,unsigned short mode){
 (void)flags;(void)mode;
 return strstr(name,"uncompressed")||strstr(name,"ownership-observe")?(void*)-2:(void*)123;
}
long kernel_read(void *f,long long offset,void *dst,unsigned long n){
 (void)dst;(void)n;assert(f==(void*)123&&offset==0);return 1; /* Truncated PNG. */
}
int filp_close(void *f,void *owner){(void)f;(void)owner;return 0;}
int main(int argc,char **argv){
 (void)argv;fault=argc>1;
 assert(init_module()==0); /* Resident failed diagnostic, never successful input. */
 assert(allocations==1&&shares==1&&resources_owned&&detaches==1&&retained==1&&!done&&!q_reply);
 assert(mappings==(fault?0:1));free(mapped);
 /* The real callback must never copy 216 bytes from a 40-byte DMM reply. */
 callback_bytes=40;u8 *reply=calloc(1,40);assert(reply);put16(reply,0x8020);
 memset(s_reply,0xa5,sizeof s_reply);yc_reply_cb(reply,0);
 for(unsigned i=40;i<DMM_REQ_SIZE;i++)assert(!s_reply[i]);
 ownership_observe=1;uncompressed_input=1;pix_h=0x415;pix_len=0x500000;pix_addr=0x425558000UL;
 observe_ownership(0x4c01);assert(info_done && !info_pending);
 observe_ownership(0x4c02);assert(info_done && !info_pending);
 assert(allocations==1 && shares==1); /* observations never Share/Open/Free the unit */
 /* A stale reply cannot satisfy the second transaction. */
 info_pending=1;info_done=0;reply=calloc(1,40);assert(reply);
 put16(reply,0x8028);put16(reply+6,0x4c01);yc_reply_cb(reply,0);
 assert(info_pending && !info_done);
 return 0;
}
'''.replace('MODULE_SOURCE',str(module))
    path=tmp_path/'actual-init.c';path.write_text(fixture)
    binary=tmp_path/'actual-init'
    subprocess.run(['cc','-O1','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-no-pie',str(path),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
    subprocess.run([str(binary),'bad-segment'],check=True,timeout=10)
