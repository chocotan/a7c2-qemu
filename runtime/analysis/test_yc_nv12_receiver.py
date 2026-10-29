"""Execute the actual bounded notification reader, not an ACK/presence check."""
from pathlib import Path
import subprocess


def test_notification_consumes_full_buffer_and_drops_mapping(tmp_path):
    module=Path(__file__).resolve().parents[2]/'report/virtual-cp/yc-inject/yc_inject.c'
    source=module.read_text()
    readers=source[source.index('static u16 rd16('):source.index('/* The isolated initramfs')]
    body=source[source.index('static unsigned nv12_consumed;'):source.index('static long yc_reply_cb(')]
    harness=r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char u8;typedef unsigned short u16;typedef unsigned int u32;typedef unsigned long u64;
#define VDT_FMT_NV12_FHD 0x10u
#define MEMREMAP_WB 1
static int uncompressed_input=1,maps,unmaps,failmap;
static u8 *pixels;static char logline[1024];
static void *memremap(u64 address,u64 length,int mode){
 assert(address==0x4af654000ul&&length==3110400&&mode==1);maps++;return failmap?NULL:pixels;
}
static void memunmap(void *mapping){assert(mapping==pixels);unmaps++;}
static int printk(const char *format,...){
 va_list args;va_start(args,format);vsnprintf(logline,sizeof logline,format,args);va_end(args);return 0;
}
'''+readers+body+r'''
static void put(u8 *p,u64 value,unsigned size){for(unsigned i=0;i<size;i++)p[i]=value>>(i*8);}
int main(void){u8 notification[0x30]={0};pixels=malloc(3110400);assert(pixels);memset(pixels,128,3110400);
 put(notification+4,0x30,2);put(notification+8,0x41c,4);put(notification+0x10,0x4af654000ul,8);
 put(notification+0x18,3110400,4);notification[0x1c]=0x10;
 consume_nv12_notification(notification);assert(maps==1&&unmaps==1&&nv12_consumed==1);
 assert(strstr(logline,"full_read=1")&&strstr(logline,"fnv64="));
 unsigned long digest=input_digest(pixels,3110400);pixels[3110399]^=1;
 assert(input_digest(pixels,3110400)!=digest);consume_nv12_notification(notification);
 assert(maps==2&&unmaps==2&&nv12_consumed==2);
 failmap=1;consume_nv12_notification(notification);assert(nv12_consumed==2&&unmaps==2);failmap=0;
 for(int fault=0;fault<5;fault++){
  u8 damaged[0x30];memcpy(damaged,notification,sizeof damaged);int before=maps;
  switch(fault){case 0:damaged[4]=0x20;break;case 1:damaged[0x1c]=0x11;break;
   case 2:put(damaged+0x10,0x4fffffff0ul,8);break;case 3:put(damaged+0x18,1,4);break;
   case 4:put(damaged+8,0,4);break;}
  consume_nv12_notification(damaged);assert(maps==before);
 }
 uncompressed_input=0;consume_nv12_notification(notification);assert(nv12_consumed==2);
 uncompressed_input=1;consume_nv12_notification(notification);int before=maps;
 consume_nv12_notification(notification);assert(nv12_consumed==3&&maps==before);
 free(pixels);return 0;}
'''
    path=tmp_path/'receiver.c';path.write_text(harness);binary=tmp_path/'receiver'
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=address,undefined','-no-pie',
        str(path),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
