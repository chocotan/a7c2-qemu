from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class AppInput(unittest.TestCase):
    def test_original_app_event_layout_and_failure_cleanup(self):
        source=(HERE/'inject-key.c').read_text()
        begin=source.index('static unsigned int field(')
        body=source[begin:source.index('#ifndef INJECT_KEY_HOST_TEST',begin)]
        fixture=r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned int data[8],bytes,source_id,calls,freed;
static int fail_send;
static int osal_valloc_msg_wait(unsigned int q,void **out,unsigned int n,int count){
 assert(q==0x5503e0 && count==1 && n==32);*out=data;bytes=n;return 0;
}
static void osal_set_msg_src(void *p,unsigned int src){assert(p==data);source_id=src;}
static int osal_snd_msg(unsigned int q,void *p){assert(q==0x5503e0 && p==data);calls++;return fail_send?-7:0;}
static int osal_free_msg(unsigned int q,void *p){assert(q==0x5503e0 && p==data);freed++;return 0;}
'''
        checks=r'''
int main(void){
 char *args[]={"inject-key","--app","0x5503e0","0x5503e0","0x1ac","0","1","0x123","1"};
 assert(!run(9,args) && bytes==32 && source_id==0x5503e0 && calls==1 && !freed);
 const unsigned int pressed[8]={0x1ac,0,1,0,0x123,0,1,0};assert(!memcmp(data,pressed,32));
 args[6]="0";assert(!run(9,args));
 const unsigned int released[8]={0x1ac,0,0,0,0x123,0,1,0};assert(!memcmp(data,released,32));
 fail_send=1;assert(run(9,args)==4 && freed==1);
 args[2]="0x807a0020";assert(run(9,args)==2 && freed==1);
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            program=Path(temporary)/'input'
            compiled=subprocess.run(['cc','-x','c','-','-o',str(program),'-Wall','-Wextra','-Werror',
                                     '-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie'],
                                    input=fixture+body+checks,text=True,capture_output=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result=subprocess.run([str(program)],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
