"""Host mocked ownership/wire test; never sends to a host or guest power device."""
from pathlib import Path
import subprocess
import struct
import pytest


def test_original_source_setter_is_void_and_only_stores_the_header_word():
    path=Path(__file__).with_name('menu-root')/'usr/lib/libosal_uipc.so'
    if not path.exists():pytest.skip('official assets not prepared')
    data=path.read_bytes();assert data[:6]==b'\x7fELF\x02\x01'
    phoff=struct.unpack_from('<Q',data,0x20)[0]
    entry,count=struct.unpack_from('<HH',data,0x36)
    for index in range(count):
        kind,flags,offset,va,pa,size,mem,alignment=struct.unpack_from('<IIQQQQQQ',data,phoff+index*entry)
        if kind==1 and va<=0x7e20<va+size:
            code=data[offset+0x7e20-va:offset+0x7e28-va]
            assert code==bytes.fromhex('01 40 1f b8 c0 03 5f d6')
            return
    raise AssertionError('source setter is not in an original file-backed segment')


def test_exact_request_and_send_ownership(tmp_path):
    source=r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define INJECT_KEY_HOST_TEST
#include "inject-key.c"
static unsigned int body[4];
static int fail,allocated,sent,freed;
int osal_valloc_msg_wait(unsigned int q,void **out,unsigned int bytes,int wait){
 assert(q==0x80920021 && bytes==16 && wait==1);allocated++;
 if(fail==1){*out=0;return -9;}if(fail==2){*out=0;return 0;}*out=body;return 0;
}
void osal_set_msg_src(void *m,unsigned int s){assert(m==body && s==0x92840747);}
int osal_snd_msg(unsigned int q,void *m){
 assert(q==0x80920021 && m==body);sent++;
 assert(body[0]==0x00920142 && body[1]==8 && body[2]==0 && body[3]==0);
 return fail==3?-8:0;
}
int osal_free_msg(unsigned int q,void *m){assert(q==0x80920021 && m==body);freed++;return 0;}
int main(void){
 char *args[]={"inject-key","--cancel-apo1"};
 for(fail=0;fail<4;fail++){
  allocated=sent=freed=0;memset(body,0xab,sizeof body);
  assert(run(2,args)==(fail==0?0:fail<3?3:4));
  assert(allocated==1 && sent==((fail==0 || fail==3)?1:0));
  assert(freed==(fail==3?1:0));
 }
 return 0;
}
'''
    test=tmp_path/'power-test.c';test.write_text(source);binary=tmp_path/'power-test'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I',str(Path(__file__).parent),str(test),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,capture_output=True)
