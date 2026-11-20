"""UNEXECUTED explicit native compiler group for sampler and observer output budgets."""
from pathlib import Path
from usb_scheduler_native_build_draft import build_run

SOURCE = Path(__file__).resolve().parents[2]/'source/usb-device'


def test_observer_shared_cap_and_errno_keep_output_below_four_mib(tmp_path):
    text = (SOURCE/'usb-start-observe.c').read_text()
    block = text[text.index('static void emit('):text.index('static int readmem(')]
    prefix = r'''
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <errno.h>
#include <assert.h>
#include <sys/syscall.h>
static int logfd=9;static unsigned records,errors,capped;
static size_t emitted;static unsigned writes,cap_records;
static long fake_syscall(long number,...){
 va_list args;va_start(args,number);
 if(number==SYS_write){int fd=va_arg(args,int);const char *p=va_arg(args,const char *);size_t n=va_arg(args,size_t);
  assert(fd==9&&n<=1024);emitted+=n;writes++;if(n>=13&&!memcmp(p,"USB_START CAP",13))cap_records++;
  va_end(args);errno=99;return (long)n;
 }
 assert(number==SYS_gettid);va_end(args);errno=99;return 123;
}
#define syscall fake_syscall
'''
    suffix = r'''
int main(void){
 char longtext[4096];memset(longtext,'x',sizeof longtext-1);longtext[sizeof longtext-1]=0;
 for(unsigned i=0;i<10000;i++){errno=27;emit(0,"MSC_PAGE_EVENT_ENTER","%s",longtext);assert(errno==27);}
 for(unsigned i=0;i<10000;i++){errno=41;emit(1,"MSC_PAGE_STATE","%s",longtext);assert(errno==41);}
 assert(writes==768+64+1&&cap_records==1&&emitted<4U*1024U*1024U);
 return 0;
}
'''
    build_run(tmp_path, 'msc-observer-budget', prefix+block+suffix)


def test_sampler_output_cap_keeps_explicit_incomplete_tail_reserve(tmp_path):
    text = (SOURCE/'usb-sender-snapshot.c').read_text()
    block = text[text.index('static void emit('):text.index('static int readmem(')]
    prefix = r'''
#include <stddef.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <setjmp.h>
#include <assert.h>
#define OUTPUT_LIMIT (4U*1024U*1024U)
#define OUTPUT_TAIL_RESERVE 4096U
static size_t output_bytes;static int stop_code;static jmp_buf boundary;
static void stopped(int code){stop_code=code;longjmp(boundary,1);}
#define exit stopped
'''
    suffix = r'''
int main(void){
 output_bytes=OUTPUT_LIMIT-OUTPUT_TAIL_RESERVE-8;
 if(!setjmp(boundary)){emit("SCHED_HEADER","record exceeds remaining budget");return 1;}
 assert(stop_code==80&&output_bytes==OUTPUT_LIMIT-OUTPUT_TAIL_RESERVE-8);
 return 0;
}
'''
    build_run(tmp_path, 'msc-sampler-budget', prefix+block+suffix)
