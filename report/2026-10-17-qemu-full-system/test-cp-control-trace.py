"""Exercise generated CP tracing with immediate peer free and original errno."""
import ast
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class CpControlTrace(unittest.TestCase):
    def test_generated_trace_preserves_original_transport_and_handoff(self):
        tree=ast.parse((HERE/'build-imaging.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build')
        node=next(n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='changes' for t in n.targets))
        before,after=next((a,b) for a,b in ast.literal_eval(node.value) if a.startswith('    unsigned int observed ='))
        snapshot=runpy.run_path(str(HERE/'native-input.py'))['resolve']()/'runtime/analysis/menu-observe.c'
        self.assertEqual(snapshot.read_text().count(before),1)
        program=r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int enabled,next_rc,calls,send_logs,return_logs;
static unsigned int incoming_bytes=24;
static char *fixture_getenv(const char *name){assert(!strcmp(name,"FULLSYSTEM_INPUT_OBSERVE"));return enabled?"1":0;}
#define getenv fixture_getenv
static long fixture_syscall(long number){assert(number==178);return 42;}
#define syscall fixture_syscall
static unsigned int size(void *p){assert(p);return incoming_bytes;}
static unsigned int source(void *p){assert(p);return 0x810261ca;}
static unsigned int (*real_msg_size)(void *)=size,(*real_get_source)(void *)=source;
static void record(const char *tag,const char *line){
assert(strstr(line,"source=0x810261ca"));
if(!strcmp(tag,"FULL_CP_CONTROL_SEND ")){
send_logs++;assert(strstr(line,"raw=00000730"));
if(incoming_bytes==300)assert(strstr(line,"bytes=300 shown=256"));
}else{assert(!strcmp(tag,"FULL_CP_CONTROL_RETURN "));return_logs++;assert(strstr(line,"transport_only=1"));}
errno=ERANGE;
}
static unsigned int record_osd_transport(const char *tag,unsigned int id,void *p){assert(tag&&id&&p);return 0;}
static int real_send_msg(unsigned int id,void *p){
assert(id==0x90030001||id==0x1234);assert(errno==EAGAIN);
calls++;if(!next_rc)free(p);errno=EIO;return next_rc;
}
static int wrapper(unsigned int id,void *message){
''' + after + r'''
(void)observed;return result;}
int main(void){
for(int test=0;test<5;test++){
enabled=test!=0;next_rc=test==3?-1021:0;incoming_bytes=test==4?300:24;
unsigned int id=test==2?0x1234:0x90030001;
unsigned char *p=calloc(1,incoming_bytes);assert(p);p[2]=7;p[3]=0x30;
errno=EAGAIN;int old_calls=calls;int rc=wrapper(id,p);
assert(calls==old_calls+1 && rc==next_rc && errno==EIO);
if(rc){assert(p[2]==7 && p[3]==0x30);free(p);}
}
assert(calls==5 && send_logs==3 && return_logs==3);
puts("CP_TRACE_ORIGINAL_TRANSPORT_RETURN_ERRNO_HANDOFF_AND_BOUNDS_PASS");
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'fixture.c';source.write_text(program)
            binary=root/'fixture'
            subprocess.run(['clang','-O1','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
