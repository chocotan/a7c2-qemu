"""The data kernel alone is not guest pixel/IRQ completion evidence."""
from pathlib import Path
import subprocess


def test_identity_bytes_guards_and_failure_without_writes(tmp_path):
    models=Path(__file__).parent/'device-models'
    harness=r'''
#include <assert.h>
#include <string.h>
#include "rc-identity.h"
int main(void){
 unsigned char input[128],output[128],before[128];
 for(unsigned i=0;i<sizeof input;i++)input[i]=(unsigned char)(i*37+11);
 memset(output,0xa5,sizeof output);
 struct rc_identity_image in={8,3,20,0,1,2,sizeof input},out=in;
 out.stride=24;
 assert(!rc_identity_copy(&in,input,&out,output));
 for(unsigned y=0;y<3;y++){
  assert(!memcmp(input+y*20,output+y*24,16));
  for(unsigned x=16;x<24;x++)assert(output[y*24+x]==0xa5);
 }
 memcpy(before,output,sizeof output);
 for(int fault=0;fault<9;fault++){
  struct rc_identity_image bad=out;
  if(fault==0)bad.format=1; /* No fake compressed decoder. */
  if(fault==1)bad.width=4;
  if(fault==2)bad.height=2;
  if(fault==3)bad.phase++;
  if(fault==4)bad.type++;
  if(fault==5)bad.stride=15;
  if(fault==6)bad.capacity=63;
  if(fault==7)bad.height=0;
  if(fault==8)bad.width=8193;
  assert(rc_identity_copy(&in,input,&bad,output)==-1);
  assert(!memcmp(before,output,sizeof output));
 }
 assert(!rc_identity_copy(&in,input,&in,input));
 assert(rc_identity_copy(&in,input,&in,input+1)==-1);
 assert(rc_identity_copy(&in,0,&out,output)==-1);
 assert(rc_identity_copy(0,input,&out,output)==-1);
 assert(rc_identity_copy(&in,(void *)(UINTPTR_MAX-1),&out,output)==-1);
 assert(!memcmp(before,output,sizeof output));return 0;
}
'''
    path=tmp_path/'identity.c';path.write_text(harness)
    binary=tmp_path/'identity'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-no-pie','-I',str(models),str(path),str(models/'rc-identity.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
