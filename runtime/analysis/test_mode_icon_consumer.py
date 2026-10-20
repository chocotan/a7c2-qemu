from pathlib import Path
import subprocess


def test_icon_observation_binds_parameters_without_mutating_widget(tmp_path):
    source = (Path(__file__).parent / 'menu-observe.c').read_text()
    start = source.index('void capture_mode_icon_consumer(')
    function = source[start:].split('\n__asm__(', 1)[0]
    harness = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
static unsigned long appfw_base,observed_mode_view_params[3];
static unsigned int observed_mode_model_values[3];
static unsigned int records;
static char last[512];
static long fake_syscall(long number,...) {
 if(number==178)return 77;
 assert(number==113);
 va_list args;va_start(args,number);assert(va_arg(args,int)==1);
 long *stamp=va_arg(args,long *);stamp[0]=10;stamp[1]=20;va_end(args);
 errno=EACCES;return 0;
}
#define syscall fake_syscall
static void record(const char *prefix,const char *text) {
 assert(!strcmp(prefix,"MODE_ICON_CONSUMER "));
 assert(strstr(text,"visibility_unproven=1") && strstr(text,"observation_only=1"));
 assert(strstr(text,"policy=first32_per_dial"));
 records++;snprintf(last,sizeof last,"%s",text);errno=ENOSPC;
}
'''
    harness += function
    harness += r'''
int main(void) {
 assert(sizeof(unsigned long)==8);
 void *memory=mmap(NULL,0x8000000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 assert(memory!=MAP_FAILED);appfw_base=(unsigned long)memory;
 unsigned int *ids=(unsigned int *)(appfw_base+0x41b23a0UL);
 for(unsigned int i=0;i<18;i++)ids[i]=0x02000000U+i;
 unsigned int *dial=(unsigned int *)(appfw_base+0x7ee4750UL);*dial=1;
 union { unsigned long alignment;unsigned char bytes[0x300]; } widget={0};
 unsigned char *p=widget.bytes;unsigned int *resource=(unsigned int *)(p+0x214);
 *resource=0x11111111U;p[0x204]=1;
 capture_mode_icon_consumer(p,0x100,0,0);assert(records==0);
 observed_mode_view_params[0]=(unsigned long)(p+0x1d8);
 unsigned char before[sizeof widget.bytes];memcpy(before,p,sizeof before);
 errno=EDOM;
 for(unsigned int i=0;i<36;i++)capture_mode_icon_consumer(p,0x100,0,0);
 assert(records==32 && errno==EDOM && !memcmp(before,p,sizeof before));
 assert(strstr(last,"tracked_mask=0x1") && strstr(last,"icon_family=0"));
 observed_mode_view_params[0]=0;*dial=2;
 capture_mode_icon_consumer(p,0x100,0,0);assert(records==32);
 *resource=ids[0];capture_mode_icon_consumer(p,0x100,0,0);
 assert(records==33 && errno==EDOM && strstr(last,"icon_family=1"));
 assert(strstr(last,"tracked_mask=0 "));
 observed_mode_view_params[0]=observed_mode_view_params[2]=(unsigned long)(p+0x1d8);
 observed_mode_model_values[0]=5;observed_mode_model_values[2]=6;
 *resource=0x11111111U;memcpy(before,p,sizeof before);
 capture_mode_icon_consumer(p,0x100,0,0);
 assert(records==34 && strstr(last,"tracked_mask=0x5"));
 assert(strstr(last,"last_model0=0:5;2:6") && strstr(last,"selected_valid=0"));
 capture_mode_icon_consumer(p,0x100,0x0200ff00UL,1);
 assert(records==35 && strstr(last,"selected_valid=1") && strstr(last,"selected_resource=0x200ff00"));
 assert(errno==EDOM && !memcmp(before,p,sizeof before));
 assert(!munmap(memory,0x8000000));
 return 0;
}
'''
    test = tmp_path / 'icon-consumer.c'
    binary = tmp_path / 'icon-consumer'
    test.write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(test), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, capture_output=True)
