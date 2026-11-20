"""UNEXECUTED: explicit compiler/native harness group, never part of fake-only pytest discovery.

Run only when the parent authorizes the combined compiler group. No VM/device access.
The harness uses synthetic addresses, records, callbacks and memory, never real AP memory.
"""
from pathlib import Path
import subprocess

import pytest

SOURCE = Path(__file__).resolve().parents[2]/'source/usb-device'


def build_run(tmp_path, name, source):
    path = tmp_path/(name+'.c')
    path.write_text(source)
    binary = tmp_path/name
    subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-misleading-indentation', str(path), '-o', str(binary)],
                   check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)


def test_four_taps_preserve_arguments_errno_and_record_observations(tmp_path):
    text = (SOURCE/'usb-start-observe.c').read_text()
    start = text.index('#ifdef USB_MSC_SCHEDULER_OBSERVE\n')
    block = text[start:text.index('\n/* Compact SHA-256', start)]
    prefix = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <errno.h>
#include <assert.h>
#define USB_MSC_SCHEDULER_OBSERVE 1
static uintptr_t app_base=0x100000;
static unsigned char self_bytes[0x310],event_bytes[24],request_bytes[24];
static uint32_t config1=0x12345678,config2=0x98765432,gate=0x11223301;
static unsigned calls[4],reads,mutate,freed,request_reads;
static char logtext[65536];static size_t logsize;
static void emit(int error,const char *kind,const char *format,...) {
    (void)error;int n=snprintf(logtext+logsize,sizeof logtext-logsize,"%s ",kind);
    assert(n>0);logsize+=(size_t)n;
    va_list args;va_start(args,format);n=vsnprintf(logtext+logsize,sizeof logtext-logsize,format,args);va_end(args);
    assert(n>=0&&(size_t)n+2<sizeof logtext-logsize);logsize+=(size_t)n;
    logtext[logsize++]='\n';logtext[logsize]=0;errno=99;
}
static int readmem(uintptr_t p,void *out,size_t n) {
    reads++;const void *source=0;
    if(p==0x2000+0x302&&n==7)source=self_bytes+0x302;
    if(p==app_base+0x7e640c0+0x218&&n==4)source=&config1;
    if(p==app_base+0x7e64080&&n==4)source=&config2;
    if(p==app_base+0x7e4e608&&n==4)source=&gate;
    if(p>=0x3000&&p+n<=0x3000+sizeof event_bytes)source=event_bytes+(p-0x3000);
    if(p==0x4000&&n==24){assert(!freed);source=request_bytes;request_reads++;}
    if(!source)return 0;memcpy(out,source,n);
    if(mutate&&reads%2==0)((unsigned char *)out)[0]^=1;
    return 1;
}
'''
    suffix = r'''
static uintptr_t original_init(uintptr_t self,uintptr_t arg){assert(self==0x2000&&arg==0x778899&&errno==27);calls[0]++;self_bytes[0x303]=0x44;errno=41;return 0xfedcba9876543210UL;}
static uint32_t original_event(uintptr_t self,uintptr_t event,uint32_t id){assert(self==0x2000&&event==0x3000&&id&&errno==27);calls[1]++;errno=41;return 0x87654321;}
static void original_submit(uintptr_t input,uint32_t flag,uintptr_t assoc){assert(input==0x5555&&flag==0xabcdef03&&assoc==0x123456789abcUL&&errno==27);calls[2]++;errno=41;}
static void original_consume(uintptr_t request){assert(request==0x4000&&errno==27);calls[3]++;freed=1;errno=41;}
static void reset(void){logsize=0;logtext[0]=0;reads=0;mutate=0;freed=0;}
int main(void){
 real_msc_page_init=original_init;real_msc_page_event=original_event;real_msc_submit=original_submit;real_msc_consume=original_consume;
 for(unsigned i=0;i<7;i++)self_bytes[0x302+i]=(unsigned char)(i+1);
 uint32_t a=0x10203040,b=0x50607080,c=0x90abcdef;
 memcpy(event_bytes+8,&a,4);memcpy(event_bytes+0xc,&b,4);memcpy(event_bytes+0x14,&c,4);
 uint32_t id=0x367,flag=3;uintptr_t assoc=0x123456789abcUL,input=0x5555;
 memcpy(request_bytes,&id,4);memcpy(request_bytes+4,&flag,4);memcpy(request_bytes+8,&assoc,8);memcpy(request_bytes+0x10,&input,8);
 reset();errno=27;assert(u_msc_page_init(0x2000,0x778899)==0xfedcba9876543210UL&&errno==41);
 assert(calls[0]==1&&strstr(logtext,"MSC_PAGE_INIT_ENTER self=0x2000 x1=0x778899 lr=0x"));
 assert(strstr(logtext,"phase=init-enter self=0x2000 flags302_308=01020304050607 config1=0x12345678 config2=0x98765432 readable=1 stable=1"));
 assert(strstr(logtext,"MSC_PAGE_INIT_RETURN")&&strstr(logtext,"phase=init-return self=0x2000 flags302_308=01440304050607"));
 uint32_t events[]={0x01000053,0x01000054,0x01000055,0x01000056,0x01000057,0x01000058,0x01000116,0x01000289,0x01000291};
 for(unsigned i=0;i<sizeof events/sizeof *events;i++){
  reset();errno=27;assert(u_msc_page_event(0x2000,0x3000,events[i])==0x87654321&&errno==41);
  assert(strstr(logtext,"MSC_PAGE_EVENT_ENTER self=0x2000 event=0x3000 id=0x"));
  char expected[32];snprintf(expected,sizeof expected,"id=%#x",events[i]);assert(strstr(logtext,expected));
  assert(strstr(logtext,"event8=0x10203040 eventc=0x50607080 event14=0x90abcdef readable=1 stable=1"));
  assert(strstr(logtext,"phase=event-enter")&&strstr(logtext,"phase=event-return")&&strstr(logtext,"w0=0x87654321"));
 }
 uint32_t ignored[]={0x01000052,0x01000059,0x01000115,0x01000117,0x01000288,0x01000290,0xffffffff};
 for(unsigned i=0;i<sizeof ignored/sizeof *ignored;i++){
  reset();errno=27;assert(u_msc_page_event(0x2000,0x3000,ignored[i])==0x87654321&&errno==41);
  assert(!reads&&!logsize);
 }
 assert(calls[1]==16);
 reset();errno=27;u_msc_submit(0x5555,0xabcdef03,0x123456789abcUL);assert(errno==41&&calls[2]==1);
 assert(strstr(logtext,"input=0x5555 flag_low8=0x3 x1_raw=0xabcdef03 associated=0x123456789abc lr=0x"));
 assert(strstr(logtext,"phase=submit-enter gate_raw32=0x11223301 gate_low8=0x1 readable=1 stable=1"));
 assert(strstr(logtext,"phase=submit-return")&&strstr(logtext,"MSC_SUBMIT_RETURN input=0x5555 return_type=void"));
 assert(!strstr(logtext,"rc=")&&!strstr(logtext,"w0="));
 reset();errno=27;u_msc_consume(0x4000);assert(errno==41&&calls[3]==1&&request_reads==2);
 assert(strstr(logtext,"request=0x4000 id=0x367 flag=0x3 associated=0x123456789abc input=0x5555 readable=1 stable=1"));
 assert(strstr(logtext,"MSC_CONSUME_RETURN request=0x4000 return_type=void")&&!strstr(logtext,"rc="));
 assert(!memcmp(request_bytes,&id,4)&&!memcmp(event_bytes+8,&a,4));
 reset();mutate=1;msc_page_state("unstable",0x2000);assert(strstr(logtext,"stable=0"));
 reset();msc_page_state("missing",0);assert(strstr(logtext,"readable=0 stable=0"));
 return 0;
}
'''
    build_run(tmp_path, 'msc-passive-taps', prefix+block+suffix)


@pytest.mark.parametrize('changed', ['none', 'header', 'active-object', 'active-control',
                                      'pending-object', 'pending-control', 'run', 'node'])
def test_group6_all_objects_controls_and_stability(tmp_path, changed):
    text = (SOURCE/'usb-sender-snapshot.c').read_text()
    block = text[text.index('static int scheduled('):text.index('static int cmp_tid(')]
    prefix = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <assert.h>
static int reads_ok=1;
static uintptr_t base=0x100000,group;
static unsigned objects,controls;
struct region {uintptr_t address;unsigned char data[0x1b8];size_t size;unsigned reads;};
static struct region regions[12];static unsigned region_count;static const char *change;
static void emit(const char *kind,const char *format,...){assert(kind&&format);}
static void rawhex(const char *kind,const unsigned char *data,size_t size,unsigned long id){
 assert(data&&size);if(!strcmp(kind,"OBJECT")){assert(size==16&&id<=2);objects++;}
 if(!strcmp(kind,"CONTROL")){assert(size==0x1b8&&id<=2);controls++;}
}
static struct region *add(uintptr_t p,size_t n){struct region *r=regions+region_count++;assert(region_count<=12);r->address=p;r->size=n;return r;}
static void put64(struct region *r,size_t off,uintptr_t value){memcpy(r->data+off,&value,8);}
static int readmem(uintptr_t p,void *out,size_t n){
 for(unsigned i=0;i<region_count;i++){struct region *r=regions+i;if(p==r->address&&n==r->size){
  memcpy(out,r->data,n);r->reads++;
  uintptr_t selected=!strcmp(change,"header")?group:!strcmp(change,"active-object")?0x2000:
   !strcmp(change,"active-control")?0x3000:!strcmp(change,"pending-object")?0x2040:
   !strcmp(change,"pending-control")?0x3400:!strcmp(change,"run")?0x5010:
   !strcmp(change,"node")?0x6000:0;
  if(selected==p&&r->reads==2)((unsigned char *)out)[0]^=1;
  return 1;
 }}reads_ok=0;return 0;
}
'''
    suffix = r'''
int main(void){
 change=CHANGE;uintptr_t manager=base+0x910a108;group=manager+0x310+6*0x90;
 assert(group==base+0x910a778);uintptr_t head=group+0x10;
 struct region *header=add(group,0x90);put64(header,0,manager);uint32_t six=6;memcpy(header->data+8,&six,4);
 put64(header,0x10,0x6000);put64(header,0x18,0x6020);put64(header,0x20,2);put64(header,0x88,0x2000);
 for(unsigned i=0;i<3;i++){
  struct region *object=add(0x2000+i*0x40,16);put64(object,0,0x5000);put64(object,8,0x3000+i*0x400);
  struct region *control=add(0x3000+i*0x400,0x1b8);uint32_t id=0x367+i;memcpy(control->data+8,&id,4);
 }
 struct region *run=add(0x5010,8);put64(run,0,base+0x34796b0);
 struct region *node=add(0x6000,24);put64(node,0,0x6020);put64(node,8,head);put64(node,16,0x2040);
 node=add(0x6020,24);put64(node,0,head);put64(node,8,0x6000);put64(node,16,0x2080);
 int complete=0,stable=0;scheduler(base,&complete,&stable);
 if(!strcmp(change,"none")){
  assert(complete&&stable&&reads_ok&&objects==3&&controls==3);
  for(unsigned i=0;i<region_count;i++)assert(regions[i].reads>=2);
 }else assert(!stable);
 return 0;
}
'''
    build_run(tmp_path, 'msc-group6-'+changed, '#define CHANGE "'+changed+'"\n'+prefix+block+suffix)
