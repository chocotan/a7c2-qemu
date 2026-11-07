#!/usr/bin/env python3
"""Exercise the actual generated wrapper fragment with real forwarding mocks."""
import ast
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class BackupLogging(unittest.TestCase):
    def test_generated_sampling_keeps_every_call_and_error(self):
        tree=ast.parse((HERE/'build-imaging.py').read_text())
        fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='build')
        assignment=next(node for node in fn.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='changes' for t in node.targets))
        changes=ast.literal_eval(assignment.value)
        snapshot=runpy.run_path(str(HERE/'native-input.py'))['resolve']()
        original=(snapshot/'runtime/analysis/menu-observe.c').read_text()
        start=original.index('    if (!version && message && real_msg_size) {')
        stop=original.index('    if (version) {',start)
        fragment=original[start:stop]
        for before,after in changes:
            if before in ('    if (!version && message && real_msg_size) {','    int result = real_send_sync(id, message);'):
                self.assertEqual(fragment.count(before),1);fragment=fragment.replace(before,after)
        program=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
static int enabled,calls,verbose,samples,errors;
static char *getenv(const char *name){assert(!strcmp(name,"FULLSYSTEM_BACKUP_LOG"));return enabled?"sampled":0;}
static long syscall(long n){assert(n==178);return 1;}
static unsigned int msg_size(void *p){assert(p);return 112;}
static unsigned int get_source(void *p){assert(p);return 0;}
static unsigned int (*real_msg_size)(void *)=msg_size,(*real_get_source)(void *)=get_source;
static int next_error;
static int real_send_sync(unsigned int id,void *p){assert(id==0x003e014d || id==0x555);calls++;((unsigned int*)p)[1]=0x12345678;return next_error;}
static void record(const char *tag,const char *line){assert(line);if(!strcmp(tag,"SND_SYNC_OTHER "))verbose++;else if(!strcmp(tag,"FULL_BACKUP_LOG_SAMPLE "))samples++;else if(!strcmp(tag,"FULL_BACKUP_LOG_ERROR "))errors++;else assert(0);}
static int wrapper(unsigned int id,void *message){int version=0;
''' + fragment + r'''
return result;}
int main(void){
unsigned int message[28]={0};
for(int i=0;i<10;i++)assert(wrapper(0x003e014d,message)==0);
assert(calls==10 && verbose==10 && !samples && !errors);
enabled=1;verbose=0;
for(int i=1;i<=1024;i++){
next_error=i%17==0?-1020:0;int before=calls;
assert(wrapper(0x003e014d,message)==next_error && calls==before+1 && message[1]==0x12345678);
}
assert(verbose==15 && errors==60 && samples==15);
next_error=0;assert(wrapper(0x555,message)==0 && verbose==16 && samples==15);
puts("ACTUAL_GENERATED_WRAPPER_1035_CALLS_ERRORS_RETURN_BYTES_AND_DEFAULT_PROFILE_PASS");return 0;}
'''
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary);source=path/'test.c';source.write_text(program)
            subprocess.run(['clang','-O1','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(source),'-o',str(path/'test')],check=True)
            result=subprocess.run([str(path/'test')],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
