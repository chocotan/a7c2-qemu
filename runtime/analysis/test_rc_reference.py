"""Experimental backend tests verify its declared byte operation, not ASIC fidelity."""
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent


def test_observed_contract_and_asymmetric_bytes(tmp_path):
    source=r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "rc-reference.h"
int main(void){
 uint32_t rc[32]={1,0x00c0050a,0,0x01000100,0x01000100,0,0x1000,0x1000,
  0,0,0x07800438,0x07800438,1,0,0,0x07800438};
 uint32_t input[32]={[0]=3,[8]=0x25558000,[9]=3840,[11]=1079};
 uint32_t output[32]={[0]=3,[8]=0xf8500000,[9]=3840,[11]=1079};
 uint32_t ip[4]={0},op[4]={0,0,1,0};
 struct rc_reference_request request,sentinel;
 assert(!rc_reference_decode(rc,input,output,ip,op,&request));
 assert(request.source==0x425558000ull&&request.destination==0x4f8500000ull);
 size_t bytes=request.input.capacity;
 unsigned char *src=malloc(bytes),*dst=malloc(bytes+16);
 assert(src&&dst);
 for(size_t i=0;i<bytes;i++)src[i]=(i*29u+(i/3840u)*71u+(i%7u)*53u)&255;
 memset(dst,0xa5,bytes+16);
 assert(!rc_identity_copy(&request.input,src,&request.output,dst));
 assert(!memcmp(src,dst,bytes));
 for(size_t i=bytes;i<bytes+16;i++)assert(dst[i]==0xa5);
 memset(&sentinel,0x5a,sizeof sentinel);
 for(unsigned test=0;test<9;test++){
  request=sentinel;
  switch(test){case 0:rc[1]^=1;break;case 1:rc[6]++;break;case 2:rc[8]++;break;
   case 3:input[9]++;break;case 4:input[6]=1;break;case 5:op[2]=0;break;
   case 6:input[0]=2;break;case 7:output[8]=input[8]+32;break;
   case 8:input[6]=0x100;input[8]=0xfffffff0;break;}
  assert(rc_reference_decode(rc,input,output,ip,op,&request)==-1);
  assert(!memcmp(&request,&sentinel,sizeof request));
  switch(test){case 0:rc[1]^=1;break;case 1:rc[6]--;break;case 2:rc[8]--;break;
   case 3:input[9]--;break;case 4:input[6]=0;break;case 5:op[2]=1;break;
   case 6:input[0]=3;break;case 7:output[8]=0xf8500000;break;
   case 8:input[6]=0;input[8]=0x25558000;break;}
 }
 free(src);free(dst);return 0;
}
'''
    path=tmp_path/'reference.c';path.write_text(source)
    models=HERE/'device-models';binary=tmp_path/'reference'
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-no-pie',
        '-I',str(models),str(path),str(models/'rc-reference.c'),str(models/'rc-identity.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
