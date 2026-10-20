from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class MediaMountTrace(unittest.TestCase):
    def test_mwf_trace_preserves_original_call_data_result_and_errno(self):
        source=(HERE/'menu-observe.c').read_text()
        body=source.split('int _ZN3MWF12EventWrapper11SendAndRecvEPviS1_i(',1)[1].split('\nint osal_snd_sync_msg(',1)[0]
        wrapper='int _ZN3MWF12EventWrapper11SendAndRecvEPviS1_i('+body
        completion='static int trace_media_mount_completion('+source.split('static int trace_media_mount_completion(',1)[1].split('\nint osal_stat_msgq(',1)[0]
        stat='int osal_stat_msgq('+source.split('int osal_stat_msgq(',1)[1].split('\nunsigned int mcmn_drv_open(',1)[0]
        media_open='unsigned int mcmn_drv_open(const char *name,unsigned int flags,void **handle) {'+source.split('unsigned int mcmn_drv_open(const char *name,unsigned int flags,void **handle) {',1)[1].split('\nstatic void trace_media_rm_sync(',1)[0]
        rm_trace='static void trace_media_rm_sync('+source.split('static void trace_media_rm_sync(',1)[1].split('\nint _ZN3MWF',1)[0]
        fixture=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define RTLD_NEXT ((void *)-1)
#define syscall(...) 101L
static void *expected_data;
static int expected_bytes,expected_result,resolves,records;
static unsigned int message_size;
static char last_record[900];
static unsigned int size_of(void *p){assert(p);return message_size;}
static unsigned int source_of(void *p){assert(p);return 0xb08170;}
static unsigned int (*real_msg_size)(void *)=size_of;
static unsigned int (*real_get_source)(void *)=source_of;
static unsigned int original_open(const char *name,unsigned int flags,void **handle) {
    assert(!strcmp(name,"/nondev/rm2") && flags==0x123 && handle && errno==EAGAIN);
    *handle=(void *)0xbeef;errno=ENOENT;return 0x80000004U;
}
static unsigned int (*real_media_open)(const char *,unsigned int,void **)=original_open;
static int original_stat(unsigned int id,void *stats) {
    assert(id==0x80d9016e && stats);((unsigned int *)stats)[0]=7;((unsigned int *)stats)[1]=0;
    errno=EBUSY;return 0;
}
static int (*real_stat_msgq)(unsigned int,void *)=original_stat;
static int original(void *self,void *data,int bytes,void *reply,int reply_bytes) {
    assert(self==(void *)0x123 && data==expected_data && bytes==expected_bytes);
    assert(!reply && !reply_bytes && errno==EAGAIN);
    if(bytes==228)((unsigned char *)data)[28]=1;
    errno=EIO;return expected_result;
}
static void *resolve(void *handle,const char *name) {
    assert(handle==RTLD_NEXT && !strcmp(name,"_ZN3MWF12EventWrapper11SendAndRecvEPviS1_i"));
    ++resolves;errno=ENOENT;return original;
}
static void *(*real_dlsym)(void *,const char *)=resolve;
static void record(const char *phase,const char *text) {
    assert(strstr(phase,"FULL_MEDIA_MOUNT_") && text[0]);++records;strcpy(last_record,text);errno=99;
}
'''
        checks=r'''
int main(void) {
    uint32_t payload[57]={0},small[2]={0};unsigned char expected[228];
    payload[0]=0x1000;((uint16_t *)payload)[2]=3;((uint16_t *)payload)[3]=0xcc;payload[6]=0x1000;
    memcpy(expected,payload,228);expected[28]=1;
    setenv("MENU_DMM_UNIT_CONFIG","1",1);expected_data=payload;expected_bytes=228;expected_result=-7;errno=EAGAIN;
    assert(_ZN3MWF12EventWrapper11SendAndRecvEPviS1_i((void *)0x123,payload,228,0,0)==-7);
    assert(errno==EIO && !memcmp(payload,expected,228) && resolves==1 && records==2);
    expected_data=small;expected_bytes=8;expected_result=3;errno=EAGAIN;
    assert(_ZN3MWF12EventWrapper11SendAndRecvEPviS1_i((void *)0x123,small,8,0,0)==3);
    assert(errno==EIO && !small[0] && !small[1] && resolves==1 && records==2);
    unsetenv("MENU_DMM_UNIT_CONFIG");expected_data=0;expected_bytes=0;expected_result=1;errno=EAGAIN;
    assert(_ZN3MWF12EventWrapper11SendAndRecvEPviS1_i((void *)0x123,0,0,0,0)==1);
    assert(errno==EIO && resolves==1 && records==2);
    setenv("MENU_DMM_UNIT_CONFIG","1",1);payload[0]=0x41000;payload[1]=0x100001;payload[2]=0x1000;payload[3]=0x7fffffff;
    memcpy(expected,payload,228);message_size=40;errno=EIO;
    assert(trace_media_mount_completion("FULL_MEDIA_MOUNT_FREE_ENTER ",0x80020001,payload)==1);
    assert(errno==EIO && !memcmp(payload,expected,228) && records==3);
    assert(strstr(last_record,"api=0x1000 type=0x4") && strstr(last_record,"service_error=0x7fffffff"));
    message_size=8;assert(trace_media_mount_completion("FULL_MEDIA_MOUNT_FREE_ENTER ",0x80020001,small)==0);
    assert(errno==EIO && records==3);
    unsetenv("MENU_DMM_UNIT_CONFIG");message_size=40;
    assert(trace_media_mount_completion("FULL_MEDIA_MOUNT_FREE_ENTER ",0x80020001,payload)==0);
    assert(errno==EIO && records==3);
    setenv("MENU_DMM_UNIT_CONFIG","1",1);void *opened=0;errno=EAGAIN;
    assert(mcmn_drv_open("/nondev/rm2",0x123,&opened)==0x80000004U);
    assert(opened==(void *)0xbeef && errno==ENOENT && records==5);
    message_size=228;errno=EIO;memcpy(expected,payload,228);
    trace_media_rm_sync("FULL_MEDIA_MOUNT_RM_SYNC_RETURN ",0x80d9016e,payload,-1020);
    assert(errno==EIO && records==6 && !memcmp(expected,payload,228));
    assert(strstr(last_record,"transport=-1020") && strstr(last_record,"bytes=228"));
    message_size=257;
    trace_media_rm_sync("FULL_MEDIA_MOUNT_RM_SYNC_RETURN ",0x80d9016e,payload,-1020);
    assert(errno==EIO && records==7 && strstr(last_record,"payload_skipped=bounded_256"));
    unsigned int stats[2]={99,99};
    assert(osal_stat_msgq(0x80d9016e,stats)==0 && stats[0]==7 && stats[1]==0);
    assert(errno==EBUSY && records==8 && strstr(last_record,"word1=0"));
    unsetenv("MENU_DMM_UNIT_CONFIG");
    assert(osal_stat_msgq(0x80d9016e,stats)==0 && errno==EBUSY && records==8);
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            program=Path(temporary)/'trace'
            subprocess.run(['cc','-x','c','-','-o',str(program),'-Wall','-Wextra','-Werror',
                            '-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie'],
                           input=fixture+completion+stat+media_open+rm_trace+wrapper+checks,text=True,check=True,capture_output=True)
            subprocess.run([str(program)],check=True,capture_output=True,timeout=20)


if __name__=='__main__':unittest.main()
