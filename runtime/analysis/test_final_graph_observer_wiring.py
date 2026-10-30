"""Execute the observer's actual Backup/receive boundary code with bounded native stubs."""
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent


def function(source, name):
    match = re.search(r'^(?:static )?(?:int|void) ' + name + r'\([^;]*?\) \{', source, re.M | re.S)
    assert match, name
    start, level = match.end(), 1
    end = start
    while level:
        level += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


def test_actual_bounded_backup_and_receive_hooks(tmp_path):
    source = (HERE / 'menu-observe.c').read_text()
    snippets = '\n'.join(function(source, name) for name in (
        'hdmi_video_backup_read', 'native_hdmi_video_progress',
        'native_hdmi_video_received', 'native_cp_state_received', 'u_osal_rcv_msg_tmo'))
    code = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "device-models/imaging-device.h"
#define syscall(number) ((void)(number),99L)
static int stored_size,read_result,reads,observed,progressed,received,result_code;
static int pinmem_hdmi_video_connection_enabled,cp_owned_state_enabled,publication_received;
static int functional_camera_enabled,functional_received,mpr_received,jpeg_received;
static unsigned int functional_mpr_codec_used,functional_vdf_path_used,functional_layout_stage_used;
static int stage_observed;
static _Thread_local struct {void *pointer;unsigned int destination;uint64_t cycle;} functional_vdf_ticket;
static _Thread_local struct {void *pointer;unsigned int destination;uint64_t cycle;} functional_layout_stage_ticket;
static int (*real_allocate_msg)(unsigned int,void **,unsigned int,unsigned int);
static int (*real_free_msg)(unsigned int,void *);
static void (*real_set_source)(void *,unsigned int);
static int (*real_send_msg)(unsigned int,void *);
static _Thread_local unsigned int native_receive_depth;
static unsigned char stored[8]={1,2,3,4,5,6,7,8};
static char last_record[512];
static int cp_open_result=41,cp_close_result,cp_result,cp_calls;
static int fixture_open(const char *name,int flags){assert(!strcmp(name,"/seed-backup.bin") && !flags);errno=EDOM;return cp_open_result;}
static int fixture_close(int fd){assert(fd==41);errno=EIO;return cp_close_result;}
#define open fixture_open
#define close fixture_close
static int full_hdmi_public_backup_read(int fd,unsigned int key,void *out,unsigned int cap,unsigned int *length){
 assert(fd==41 && ((key>>16)==0x9a || key==0x010704fd));cp_calls++;
 if(length)*length=0;
 if(cp_result)return cp_result;
 if(!length || (cap && !out))return -1021;
 *length=1;if(cap)((unsigned char *)out)[0]=0x7b;return 0;
}
static void native_functional_face_received(unsigned int id,void *p){(void)id;(void)p;}
static void native_background_start_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){
 (void)id;(void)p;(void)source;(void)bytes;
}
static void native_histogram_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){
 (void)id;(void)p;(void)source;(void)bytes;
}
static void record(const char *tag,const char *text) {
 assert(!strcmp(tag,"FULL_HDMI_VIDEO_BACKUP_READ "));
 snprintf(last_record,sizeof last_record,"%s",text);
}
static int size_api(unsigned int key) {assert(key==42);errno=EDOM;return stored_size;}
static int read_api(unsigned int key,void *out,int count) {
 assert(key==42 && count>0 && count<=8);reads++;memcpy(out,stored,(unsigned int)count);
 errno=EIO;return read_result;
}
static int (*real_backup_get_datasize)(unsigned int)=size_api;
static int (*real_backup_nread)(unsigned int,void *,int)=read_api;
static unsigned int source_api(void *p) {assert(p==stored);errno=EDOM;return 13;}
static unsigned int length_api(void *p) {assert(p==stored);errno=EDOM;return 20;}
static unsigned int (*real_get_source)(void *)=source_api,(*real_msg_size)(void *)=length_api;
static int full_hdmi_video_state_observe_receive(unsigned int id,void *p,unsigned int src,unsigned int bytes) {
 assert(id==16 && p==stored && src==13 && bytes==20);observed++;errno=EDOM;return 1;
}
static int native_cp_state_publication_observe_receive(unsigned int id,void *p,unsigned int src,unsigned int bytes) {
 assert(id==16 && p==stored && src==13 && bytes==20 && received>publication_received);
 publication_received++;errno=EDOM;return 1;
}
static int functional_vdf_path_observe_receive_cycle(unsigned int id,void *p,unsigned int src,unsigned int bytes,uint64_t *ticket) {
 assert(id==16 && p==stored && src==13 && bytes==20 && ticket);return 0;
}
static int functional_vdf_layout_stage_observe_receive_cycle(unsigned int id,void *p,unsigned int src,unsigned int bytes,uint64_t *ticket) {
 assert(id==16 && p==stored && src==13 && bytes==20 && ticket);stage_observed++;return 0;
}
static int functional_camera_events_observe_receive(unsigned int id,void *p,unsigned int src,unsigned int bytes) {
 assert(id==16 && p==stored && src==13 && bytes==20);functional_received++;errno=EDOM;return 1;
}
static int functional_jpeg_codec_observe_received(unsigned int id,void *p,const struct full_imaging_io *io) {
 assert(id==16 && p==stored && io->size==real_msg_size && io->source==real_get_source);
 jpeg_received++;errno=EDOM;return 1;
}
static int functional_mpr_codec_observe_received(unsigned int id,void *p,const struct full_imaging_io *io) {
 assert(id==16 && p==stored && io->size==real_msg_size && io->source==real_get_source && io->record==record);
 mpr_received++;errno=EDOM;return 1;
}
static int full_pinmem_hdmi_video_connection_progress(void) {
 assert(observed>progressed);progressed++;errno=EIO;return 1;
}
static int receive_api(unsigned int id,void **p,long timeout) {
 assert(id==16 && timeout==27 && native_receive_depth);received++;*p=stored;
 errno=ERANGE;return result_code;
}
static int (*real_u_rcv_msg_tmo)(unsigned int,void **,long)=receive_api;
''' + snippets + r'''
int main(void) {
 unsigned char out[10];unsigned int length=123;
 memset(out,0xcc,sizeof out);stored_size=8;read_result=5;errno=EINTR;
 assert(!hdmi_video_backup_read(42,out,5,&length));
 assert(length==8 && reads==1 && !memcmp(out,stored,5) && out[5]==0xcc && errno==EINTR);
 stored_size=1;read_result=1;assert(!hdmi_video_backup_read(42,out,8,&length));
 assert(length==1 && reads==2 && out[5]==0xcc);
 stored_size=0;assert(!hdmi_video_backup_read(42,0,0,&length) && !length && reads==2);
 stored_size=8;assert(!hdmi_video_backup_read(42,0,0,&length) && length==8 && reads==2);
 stored_size=-1;assert(hdmi_video_backup_read(42,out,8,&length)==-1021 && !length && reads==2);
 assert(strstr(last_record,"verified_absent=0") && strstr(last_record,"size-error-not-verified-absence"));
 stored_size=8;read_result=4;assert(hdmi_video_backup_read(42,out,8,&length)==-1021 && reads==3);
 read_result=-1;assert(hdmi_video_backup_read(42,out,8,&length)==-1021 && reads==4);
 assert(hdmi_video_backup_read(42,out,0x80000000U,&length)==-1021 && !length && reads==4);
 assert(hdmi_video_backup_read(42,0,1,&length)==-1021 && !length && reads==4);
 assert(hdmi_video_backup_read(42,out,8,0)==-1021 && reads==4);
 real_backup_nread=0;assert(hdmi_video_backup_read(42,out,8,&length)==-1021 && !length && reads==4);
 assert(errno==EINTR);
 assert(!hdmi_video_backup_read(0x9a0009,out,8,&length) && length==1 && out[0]==0x7b && cp_calls==1 && reads==4 && errno==EINTR);
 assert(strstr(last_record,"source=pinned-public-CP-bank") && strstr(last_record,"AP_runtime_value_claimed=0"));
 cp_result=1;assert(hdmi_video_backup_read(0x010704fd,out,8,&length)==1 && !length && cp_calls==2 && errno==EINTR);
 cp_open_result=-1;assert(hdmi_video_backup_read(0x9a0009,out,8,&length)==-1021 && !length && cp_calls==2 && errno==EINTR);
 cp_open_result=41;cp_result=0;cp_close_result=-1;
 assert(hdmi_video_backup_read(0x9a0009,out,8,&length)==-1021 && cp_calls==3 && errno==EINTR);
 void *message=0;
 assert(!u_osal_rcv_msg_tmo(16,&message,27) && received==1 && !observed && !native_receive_depth);
 pinmem_hdmi_video_connection_enabled=1;cp_owned_state_enabled=1;
 assert(!u_osal_rcv_msg_tmo(16,&message,27) && received==2 && observed==1 && progressed==1 && errno==ERANGE);
 assert(publication_received==1);
 result_code=-7;assert(u_osal_rcv_msg_tmo(16,&message,27)==-7 && observed==1 && publication_received==1);
 native_hdmi_video_received(16,0,0);message=0;native_hdmi_video_received(16,&message,0);
 assert(observed==1 && progressed==1);
 message=stored;real_get_source=0;native_hdmi_video_received(16,&message,0);real_get_source=source_api;
 real_msg_size=0;native_hdmi_video_received(16,&message,0);real_msg_size=length_api;
 assert(observed==1);
 result_code=0;native_receive_depth=1;
 assert(!u_osal_rcv_msg_tmo(16,&message,27) && native_receive_depth==1 && observed==1 && publication_received==1);
 native_receive_depth=0;native_hdmi_video_received(16,&message,0);
 assert(observed==2 && progressed==2 && errno==ERANGE);
 native_cp_state_received(16,&message,0);assert(publication_received==2 && errno==ERANGE);
 native_cp_state_received(16,0,0);message=0;native_cp_state_received(16,&message,0);
 message=stored;real_get_source=0;native_cp_state_received(16,&message,0);real_get_source=source_api;
 cp_owned_state_enabled=0;native_cp_state_received(16,&message,0);cp_owned_state_enabled=1;
 assert(publication_received==2 && errno==ERANGE);
 functional_camera_enabled=1;functional_layout_stage_used=1;
 native_cp_state_received(16,&message,0);assert(functional_received==1 && jpeg_received==1 && publication_received==2 && !mpr_received && errno==ERANGE);
 assert(stage_observed==1 && !functional_layout_stage_ticket.pointer);
 functional_mpr_codec_used=1;
 native_cp_state_received(16,&message,0);assert(functional_received==2 && jpeg_received==2 && mpr_received==1 && publication_received==2 && errno==ERANGE);
 native_cp_state_received(16,&message,-1);assert(functional_received==2 && mpr_received==1 && errno==ERANGE);
 functional_camera_enabled=0;
 native_cp_state_received(16,&message,0);assert(publication_received==3 && functional_received==2 && mpr_received==1 && errno==ERANGE);
 puts("PASS actual bounded Backup, unknown absence, errno, real receive, nested receive and failure boundaries");
 return 0;
}
'''
    path = tmp_path / 'observer-boundaries.c'
    path.write_text(code)
    binary = tmp_path / 'observer-boundaries'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                    '-I', str(HERE), str(path), '-o', str(binary)], check=True, capture_output=True, text=True)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert result.stdout.startswith('PASS actual bounded Backup')
