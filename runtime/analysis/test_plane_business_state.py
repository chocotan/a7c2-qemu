"""Execute the actual plane reply handler against sentinel AppFw business fields."""
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent

FIXTURE = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
static unsigned long appfw_base;
static unsigned int allocations, sent, released, scenario, bb_ready_pending;
static int bb_ready_inject_enabled;
static unsigned char incoming[680], reply1[12], reply2[12];
static int alloc_msg(unsigned int id,void **out,unsigned int bytes,unsigned int count){
 assert(id==0x80020002 && bytes==12 && count==1);allocations++;
 *out=allocations==1?reply1:reply2;
 if(scenario==2 && allocations==2){*out=0;return -9;}
 return 0;
}
static unsigned int msg_size(void *p){assert(p==incoming);return sizeof incoming;}
static unsigned int get_source(void *p){assert(p==incoming);return 0x80020002;}
static void set_source(void *p,unsigned int id){assert((p==reply1 || p==reply2) && id==0x92840747);}
static int send_msg(unsigned int id,void *p){assert(id==0x80020002 && (p==reply1 || p==reply2));sent++;return scenario==1?-5:0;}
static int free_msg(unsigned int id,void *p){
 assert((id==0x92840747 && p==incoming) || (id==0x80020002 && (p==reply1 || p==reply2)));
 released++;return 0;
}
static int (*real_allocate_msg)(unsigned int,void **,unsigned int,unsigned int)=alloc_msg;
static unsigned int (*real_msg_size)(void *)=msg_size;
static unsigned int (*real_get_source)(void *)=get_source;
static void (*real_set_source)(void *,unsigned int)=set_source;
static int (*real_send_msg)(unsigned int,void *)=send_msg;
static int (*real_free_msg)(unsigned int,void *)=free_msg;
static void record(const char *tag,const char *text){assert(tag && text && !strstr(tag,"KEY_GATE_OVERRIDE"));}
static int plane_config_reply(void *in,unsigned int n,void *out){
 assert(in==incoming && n==680 && (out==reply1 || out==reply2));memset(out,0,12);return 0;
}
static void bb_output_ready_event(void){assert(0 && "not enabled by this test");}
'''

MAIN = r'''
int main(int argc,char **argv){
 assert(argc==2);scenario=(unsigned int)atoi(argv[1]);
 void *mapping=mmap(0,0x8000000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 assert(mapping!=MAP_FAILED);appfw_base=(unsigned long)mapping;
 const unsigned int offsets[]={0x7e814f0,0x7e6e7f0,0x7e73770,0x7ede5c0,0x7e71a70,0x7e5d9e8,0x7e71b50};
 for(unsigned int i=0;i<7;i++)*(unsigned int *)(appfw_base+offsets[i])=0x13579000+i;
 if(scenario==3)setenv("MENU_BB_READY_LATE","1",1);else unsetenv("MENU_BB_READY_LATE");
 int rc=plane_config_send(incoming);
 assert(rc==(scenario==1?-5:0));
 for(unsigned int i=0;i<7;i++)assert(*(unsigned int *)(appfw_base+offsets[i])==0x13579000+i);
 assert(allocations==(scenario==1?1U:2U));
 assert(sent==((scenario==1 || scenario==2)?1U:2U));
 assert(released==1);
 assert(bb_ready_pending==(scenario==3));
 assert(!munmap(mapping,0x8000000));return 0;
}
'''


def test_plane_completion_does_not_rewrite_business_fields():
    source = (HERE/'menu-observe.c').read_text()
    start = source.index('static int plane_config_send(void *request) {')
    end = source.index('static int pin_disconnect_send(', start)
    actual = source[start:end]
    with tempfile.TemporaryDirectory() as folder:
        binary = Path(folder)/'plane-test'
        result = subprocess.run(['cc', '-x', 'c', '-', '-o', str(binary),
                                 '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                                 '-fno-omit-frame-pointer', '-no-pie'],
                                input=FIXTURE+actual+MAIN, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        for scenario in range(4):
            result = subprocess.run([str(binary), str(scenario)], capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, (scenario, result.stdout, result.stderr)
