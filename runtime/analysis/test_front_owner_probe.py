"""Run the production guest probe function using only mocked ownership APIs."""
from pathlib import Path
import os
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
MOCK = r'''
#include <assert.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[7];
static unsigned int source, releases;
static int scenario(void){const char *s=getenv("PROBE_CASE");assert(s);return atoi(s);}
static int osal_valloc_msg_wait(unsigned int id,void **out,unsigned int size,unsigned int count){
 assert(id==0x8028017cU && size==7 && count==1);
 *out=scenario()==1?0:memory;return scenario()==1 || scenario()==4?-9:0;
}
static unsigned int osal_msg_size(void *p){assert(p==memory);return scenario()==2?8:7;}
static void osal_set_msg_src(void *p,unsigned int id){assert(p==memory && id==0x8028017cU);source=id;}
static unsigned int osal_get_msg_src(void *p){assert(p==memory);return scenario()==3?0:source;}
static int osal_free_msg(unsigned int id,void *p){
 assert(id==0x8028017cU && p==memory && !releases++);
 if(scenario()==2 || scenario()==4)for(int i=0;i<7;i++)assert(memory[i]==0);
 return scenario()==5?-7:0;
}
'''


def test_actual_guest_front_owner_probe_faults():
    source = (HERE/'fsys-file-test.c').read_text()
    start = source.index('static int front_owner_test(void) {')
    end = source.index('static int queue_transport_test(', start)
    with tempfile.TemporaryDirectory() as folder:
        binary = Path(folder)/'probe'
        compiled = subprocess.run(['cc', '-x', 'c', '-', '-o', str(binary),
                                   '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                                   '-fno-omit-frame-pointer', '-no-pie'],
                                  input=MOCK+source[start:end]+'\nint main(void){return front_owner_test();}\n',
                                  text=True, capture_output=True)
        assert compiled.returncode == 0, compiled.stderr
        for case, code in enumerate((0, 24, 25, 25, 25, 26)):
            result = subprocess.run([str(binary)], env={**os.environ, 'PROBE_CASE': str(case)},
                                    text=True, capture_output=True, timeout=10)
            assert result.returncode == code, (case, result.stdout, result.stderr)
            if case == 0:
                assert 'source=0x8028017c content=1 free_rc=0' in result.stdout
