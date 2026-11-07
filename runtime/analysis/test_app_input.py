from pathlib import Path
import subprocess
import tempfile
import unittest
import os
import select

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
#include <unistd.h>
#include <errno.h>
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
int main(int argc,char **argv){
 if(argc==2 && !strcmp(argv[1],"--serve-app")){
  fail_send=getenv("INPUT_TEST_FAIL")!=0;return serve_app();
 }
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
            def start(fail=False):
                env=dict(os.environ)
                if fail:env['INPUT_TEST_FAIL']='1'
                return subprocess.Popen([str(program),'--serve-app'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
            def line(process):
                self.assertTrue(select.select([process.stdout],[],[],10)[0],'Original sender reply timed out')
                return process.stdout.readline(512)
            process=start();self.assertEqual(line(process),b'APP_INPUT_SERVER_READY\n')
            for seq,status in ((1,1),(2,0)):
                process.stdin.write(f'{seq} 0x1ac 0 {status} 0x123 1\n'.encode());process.stdin.flush()
                self.assertEqual(line(process),f'APP_INPUT_RESULT {seq} 0\n'.encode())
            process.stdin.write(b'STOP 3\n');process.stdin.flush()
            _,error=process.communicate(timeout=10);self.assertEqual(process.returncode,0,error)
            process=start();self.assertEqual(line(process),b'APP_INPUT_SERVER_READY\n')
            process.stdin.write(b'1 0x1ac 0 1 0 0\n');process.stdin.flush()
            self.assertEqual(line(process),b'APP_INPUT_RESULT 1 0\n')
            _,error=process.communicate(b'STOP 1\n',timeout=10);self.assertEqual(process.returncode,2,error)
            for malformed in (b'0 1 0 1 0 0\n',b'-1 1 0 1 0 0\n',b'1 0x100000000 0 1 0 0\n',
                              b'1 1 0 1 0\n',b'1 1 0 1 0 0\x00hidden\n',b'x'*256,b'STOP 0\n',b'STOP -1\n'):
                process=start();self.assertEqual(line(process),b'APP_INPUT_SERVER_READY\n')
                _,error=process.communicate(malformed,timeout=10)
                self.assertEqual(process.returncode,2,error);self.assertNotIn(b'INJECT_KEY_SEND',error)
            process=start(True);self.assertEqual(line(process),b'APP_INPUT_SERVER_READY\n')
            process.stdin.write(b'1 0x1ac 0 1 0 0\n');process.stdin.flush()
            self.assertEqual(line(process),b'APP_INPUT_RESULT 1 4\n')
            _,error=process.communicate(timeout=10);self.assertEqual(process.returncode,0,error)


if __name__=='__main__':unittest.main()
