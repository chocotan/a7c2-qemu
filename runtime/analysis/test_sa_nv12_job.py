from pathlib import Path
import subprocess


def test_actual_pinned_job_shape_and_rejection_no_partial_admission(tmp_path):
    models=Path(__file__).resolve().parent/'device-models'
    source=r'''
#include <assert.h>
#include <string.h>
#include "sa-nv12-job.h"
int main(void){
 uint32_t r[1024]={[0]=1,[1]=1,[2]=0x80000000,[0x30/4]=0x7d0e0900,
  [0x110/4]=0x1f96f480,[0x114/4]=0x1f96f500};
 uint32_t p[128]={0x1564e,1920,1080,3840,1,0,0,0,0x3e140000,0x2bd95000};
 uint32_t t[88]={1,0,0x180,0x1f96f480,1,0x200,0x1518180,0x3e140000,
  1,0x1518200,0x2a30180,0x2bd95000};
 struct sa_nv12_job job,sentinel;
 assert(!sa_nv12_job_decode(r,p,t,&job));
 assert(job.source==0x4f8500000ull&&job.destination==0x4af654000ull&&job.parameters==0x47e5bd200ull);
 assert(job.table==0x47e5bd400ull&&job.program==0x47d0e0900ull);
 memset(&sentinel,0x5a,sizeof sentinel);
 for(unsigned i=0;i<6;i++){
  job=sentinel;
  switch(i){case 0:r[1]=0;break;case 1:p[1]=1280;break;case 2:t[12]=1;break;
   case 3:p[9]=p[8];t[11]=p[9];break;case 4:p[8]=0xffffffff;t[7]=p[8];break;
   case 5:r[0x60/4]=1;break;}
  assert(sa_nv12_job_decode(r,p,t,&job)==-1&&!memcmp(&job,&sentinel,sizeof job));
  switch(i){case 0:r[1]=1;break;case 1:p[1]=1920;break;case 2:t[12]=0;break;
   case 3:p[9]=0x2bd95000;t[11]=p[9];break;case 4:p[8]=0x3e140000;t[7]=p[8];break;
   case 5:r[0x60/4]=0;break;}
 }return 0;
}
'''
    harness=tmp_path/'job.c';harness.write_text(source);binary=tmp_path/'job'
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-no-pie',
        '-I',str(models),str(harness),str(models/'sa-nv12-job.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)


def test_actual_postcommit_mismatch_reports_written_output(tmp_path):
    models=Path(__file__).resolve().parent/'device-models'
    source=(models/'sony_sa_data.c').read_text()
    begin=source.index('    memcpy(destination,output,SA_NV12_OUTPUT_BYTES);')
    end=source.index('    input_hash=',begin)
    block=source[begin:end]
    harness=r'''
#include <assert.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#define SA_NV12_OUTPUT_BYTES 16u
#define LOG_GUEST_ERROR 1
static int address_space_memory,unmaps;
static char event[1024];static unsigned char target[16];
static void address_space_unmap(void *space,void *buffer,size_t length,bool write,size_t bytes){
 assert(space==&address_space_memory&&buffer==target&&length==16&&write&&bytes==16);unmaps++;
}
static void qemu_log_mask(int mask,const char *format,...){
 assert(mask==1);va_list args;va_start(args,format);vsnprintf(event,sizeof event,format,args);va_end(args);
}
static int forced_mismatch(const void *a,const void *b,size_t length){
 assert(!memcmp(a,b,length));((unsigned char*)a)[0]^=1;return 1;
}
static void execute_postcommit(void){
 unsigned char output[16];memset(output,128,sizeof output);void *destination=target;size_t length=16;
 struct {uint64_t source,destination;} job={0x4f8500000ull,0x4af654000ull};
#define memcmp forced_mismatch
BLOCK
#undef memcmp
 assert(0);
}
int main(void){execute_postcommit();assert(unmaps==1);
 assert(strstr(event,"OUTPUT_MISMATCH")&&strstr(event,"output_written=1")&&strstr(event,"completion_published=0"));
 assert(target[1]==128&&target[15]==128);return 0;}
'''.replace('BLOCK',block)
    path=tmp_path/'postcommit.c';path.write_text(harness);binary=tmp_path/'postcommit'
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-no-pie',str(path),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
