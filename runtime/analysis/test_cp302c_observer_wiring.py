"""Exercise actual observer gates; snapshot fixtures are host tests, not native proof."""
from pathlib import Path
import subprocess

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent


def test_actual_all13_gate_and_predecessor_free_boundary(tmp_path):
    observer = (HERE / 'menu-observe.c').read_text()
    snippets = '\n'.join(function(observer, name) for name in (
        'cp302c_no_transition_predecessors_ready', 'observe_cp302c_3007_free',
        'cp_notification_predecessors_ready_for', 'cp_notification_predecessors_ready',
        'cp_capture_format_predecessors_ready_for', 'cp_capture_format_predecessors_ready',
        'cp_startup_controls_predecessors_ready_for', 'cp_startup_controls_predecessors_ready',
        'cp_ee_controls_predecessors_ready', 'cp_movie_format_predecessors_ready',
        'cp_movie_format_completed', 'cp_ee_controls_after_movie_predecessors_ready',
        'cp_owned_state_predecessors_ready'))
    code = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "device-models/cp-background-device.h"
#include "device-models/cp302c-no-transition.h"
#include "device-models/cp-notification-control.h"
#include "device-models/cp-parameter-batch.h"
#include "device-models/cp-output-policy.h"
#include "device-models/cp-capture-format.h"
#include "device-models/cp-startup-controls-diagnostic.h"
#include "device-models/cp-ee-controls-diagnostic.h"
#include "device-models/cp-movie-format-diagnostic.h"
#include "device-models/pinmem-hdmi-video-connection.h"
#include "device-models/pinmem-osd-connection.h"
#include "device-models/adf-hdmi-audio-connection.h"
static long current_tid=99;
#define syscall(number) ((void)(number),current_tid)
static struct full_pinmem_hdmi_video_connection_snapshot video;
static struct full_pinmem_osd_connection_snapshot osd;
static struct full_adf_hdmi_audio_connection_snapshot audio;
static struct full_osd_pool_snapshot pool;
static struct native_cp302c_snapshot central;
static struct native_cp_notification_snapshot notification;
static struct native_cp_capture_format_diagnostic_snapshot format;
static struct native_cp_startup_controls_diagnostic_snapshot startup;
static struct native_cp_ee_controls_diagnostic_snapshot ee_controls;
static struct native_cp_movie_format_diagnostic_snapshot movie;
void native_cp_ee_controls_diagnostic_snapshot(struct native_cp_ee_controls_diagnostic_snapshot *out){*out=ee_controls;}
void native_cp_movie_format_diagnostic_snapshot(struct native_cp_movie_format_diagnostic_snapshot *out){*out=movie;}
void native_cp_startup_controls_diagnostic_snapshot(struct native_cp_startup_controls_diagnostic_snapshot *out){*out=startup;}
void native_cp_capture_format_diagnostic_snapshot(struct native_cp_capture_format_diagnostic_snapshot *out){*out=format;}
static struct cp_parameter_batch cp_parameter_batch_state;
static struct cp_output_policy cp_output_policy_state;
int cp_output_policy_snapshot(const struct cp_output_policy *owner,uint32_t mask,struct cp_output_policy_snapshot *out){
 (void)mask;*out=owner->state;return 0;
}
static unsigned long cp_parameter_batch_mutex[6];
static void *cp_parameter_batch_retained_request;
static int pthread_mutex_lock(void *p){(void)p;return 0;}
static int pthread_mutex_unlock(void *p){(void)p;return 0;}
void native_cp_notification_snapshot(struct native_cp_notification_snapshot *out){*out=notification;}
static unsigned int free_calls,records;
static int cp302c_no_transition_enabled,cp302c_diagnostic_enabled;
void full_pinmem_hdmi_video_connection_snapshot(struct full_pinmem_hdmi_video_connection_snapshot *out){*out=video;}
void full_pinmem_osd_connection_snapshot(struct full_pinmem_osd_connection_snapshot *out){*out=osd;}
void full_adf_hdmi_audio_connection_snapshot(struct full_adf_hdmi_audio_connection_snapshot *out){*out=audio;}
void full_osd_pool_snapshot(struct full_osd_pool_snapshot *out){*out=pool;}
void native_cp302c_snapshot(struct native_cp302c_snapshot *out){*out=central;errno=ERANGE;}
int native_cp302c_observe_3007_reply_freed(unsigned int source,unsigned int destination,const void *wire,
 unsigned int bytes,int queued,int freed,long sender,long waiter){
 assert(source==NATIVE_CP_BACKGROUND_SID && destination==0x80020002u && bytes==12);
 assert(!queued && !freed && sender==99 && waiter==99 && ((const unsigned char *)wire)[2]==7);
 free_calls++;central.predecessor_completed=central.history_valid=central.current_known=1;errno=EDOM;return 0;
}
static void record(const char *tag,const char *text){
 if(strstr(tag,"NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_PREDECESSORS")) {
  assert(strstr(text,"diagnostic_only=1 business_applied=0 capture_verified=0"));records++;return;
 }
 if(strstr(tag,"NATIVE_CP_EE_DIAGNOSTIC_PREDECESSORS")) {
  assert(strstr(text,"data_3003_supported=0 business_applied=0 EE_verified=0 capture_verified=0"));records++;return;
 }
 if(strstr(tag,"NATIVE_CP_STARTUP_DIAGNOSTIC_PREDECESSORS")) {
  assert(strstr(text,"diagnostic_only=1 business_applied=0 EE_verified=0 capture_verified=0"));records++;return;
 }
 if(strstr(tag,"NATIVE_CP_CAPTURE_FORMAT_DIAGNOSTIC_PREDECESSORS")) {
  assert(strstr(text,"business_applied=0 generation_advanced=0 EE_verified=0 capture_verified=0"));records++;return;
 }
 if(strstr(tag,"NATIVE_CP_NOTIFICATION_PREDECESSORS")) {
  assert(strstr(text,"CP_history_verified=0 EE_verified=0 capture_verified=0"));records++;return;
 }
 assert(strstr(tag,cp302c_diagnostic_enabled?"NATIVE_CP302C_DIAGNOSTIC_":"NATIVE_CP302C_NOCONVERT_"));records++;
 if(strstr(tag,"ALL13_READBACK"))assert(strstr(text,"global_DMM_idle_claimed=0"));
 else assert(strstr(text,"real_send_already_returned=1 actual_free_rc=0 observe_rc=0 predecessor_completed=1"));
 errno=EIO;
}
''' + snippets + r'''
#define REJECT(change,restore) do{change;assert(!cp302c_no_transition_predecessors_ready());restore;assert(cp302c_no_transition_predecessors_ready());}while(0)
int main(void){
 assert(!cp302c_no_transition_predecessors_ready());
 int pid=getpid();video.connection.owner_pid=osd.owner_pid=audio.owner_pid=audio.marker_owner_pid=pid;
 video.connection.initialized=video.connection.clean_completion=video.connection.ap_consumed=1;
 video.connection.connections=video.connection.request_freed=video.connection.reply_freed=1;
 video.peer_ready=video.source_gate_known=video.source_history_known=1;
 osd.initialized=osd.clean_completion=osd.ap_consumed=osd.connections=1;
 osd.request_freed=osd.reply_freed=osd.metadata_ready=1;
 audio.initialized=audio.clean_completion=audio.ap_consumed=audio.connections=1;
 audio.request_freed=audio.reply_freed=audio.marker_known=audio.marker_value=1;audio.marker_writes=1;
 pool.owner_pid=(unsigned int)pid;pool.initialized=1;pool.live=16;
 pool.allocations=pool.shares=pool.opens=16;
 for(unsigned int i=0;i<FULL_OSD_POOL_SLOTS;i++){
  pool.slots[i].live=pool.slots[i].creator_open=pool.slots[i].consumer_open=1;
  pool.slots[i].owners=pool.slots[i].open_count=2;
 }
 assert(cp302c_no_transition_predecessors_ready());
 REJECT(video.connection.owner_pid++,video.connection.owner_pid--);
 REJECT(osd.owner_pid++,osd.owner_pid--);
 REJECT(audio.marker_owner_pid++,audio.marker_owner_pid--);
 REJECT(video.connection.ap_consumed=0,video.connection.ap_consumed=1);
 REJECT(video.source_gate_known=0,video.source_gate_known=1);
 REJECT(video.source_gate=1,video.source_gate=0);
 REJECT(video.connection.pending_event6=1,video.connection.pending_event6=0);
 REJECT(video.connection.faults=1,video.connection.faults=0);
 REJECT(osd.live_reply=&central,osd.live_reply=NULL);
 REJECT(osd.metadata_ready=0,osd.metadata_ready=1);
 REJECT(audio.retained_request=&central,audio.retained_request=NULL);
 REJECT(audio.reply_freed=0,audio.reply_freed=1);
 REJECT(pool.live=15,pool.live=16);
 REJECT(pool.slots[7].owners=1,pool.slots[7].owners=2);
 REJECT(pool.slots[9].open_count=1,pool.slots[9].open_count=2);
 REJECT(pool.slots[11].consumer_open=0,pool.slots[11].consumer_open=1);
 unsigned char wire[12]={1,0,7,0x30,0xc1,0xff,0xff,0xff,0,0xf0,0,0};
 unsigned int old_records=records;errno=EINTR;observe_cp302c_3007_free(0x80020002u,wire);
 assert(!free_calls && records==old_records && errno==EINTR);
 central.predecessor_sender_tid=99;cp302c_no_transition_enabled=1;
 observe_cp302c_3007_free(0x80020002u,wire);
 assert(free_calls==1 && records==old_records+1 && central.predecessor_completed && errno==EINTR);
 cp302c_diagnostic_enabled=1;assert(cp302c_no_transition_predecessors_ready());
 errno=EINTR;observe_cp302c_3007_free(0x80020002u,wire);
 assert(free_calls==2 && errno==EINTR);
 REJECT(video.connection.ap_consumed=0,video.connection.ap_consumed=1);
 REJECT(pool.slots[3].owners=1,pool.slots[3].owners=2);
 memset(&central,0,sizeof central);assert(!cp_notification_predecessors_ready());
 central.owner_pid=pid;central.initialized=central.diagnostic=central.diagnostic_transport=1;
 central.requests=central.clean_completion=central.ap_consumed=1;
 central.request_freed=central.reply_freed=1;central.sender_tid=central.waiter_tid=99;
 assert(cp_notification_predecessors_ready());
#define REJECT_NEXT(change,restore) do{change;assert(!cp_notification_predecessors_ready());restore;assert(cp_notification_predecessors_ready());}while(0)
 REJECT_NEXT(central.owner_pid++,central.owner_pid--);
 REJECT_NEXT(central.diagnostic=0,central.diagnostic=1);
 REJECT_NEXT(central.ap_consumed=0,central.ap_consumed=1);
 REJECT_NEXT(central.waiter_tid=100,central.waiter_tid=99);
 REJECT_NEXT(central.sender_tid=100,central.sender_tid=99);
 REJECT_NEXT(central.reply_free_rc=-7,central.reply_free_rc=0);
 REJECT_NEXT(central.live_reply=&central,central.live_reply=NULL);
 REJECT_NEXT(central.history_valid=1,central.history_valid=0);
 REJECT_NEXT(pool.slots[1].open_count=1,pool.slots[1].open_count=2);
 assert(!cp_capture_format_predecessors_ready());
 notification.owner_pid=pid;notification.initialized=notification.requests=notification.clean_completion=1;
 notification.ap_consumed=notification.request_freed=notification.reply_freed=1;
 notification.d018_consumed=notification.d018_readback=notification.startup_sticky=1;
 notification.sender_tid=notification.waiter_tid=99;
 cp_parameter_batch_state.owner_pid=pid;cp_parameter_batch_state.staged=true;
 cp_output_policy_state.state.config_consumed=true;
 cp_output_policy_state.state.known_mask=CP_OUTPUT_POLICY_KNOWN_MASK;
 assert(cp_capture_format_predecessors_ready());
#define REJECT_FORMAT(change,restore) do{change;assert(!cp_capture_format_predecessors_ready());restore;assert(cp_capture_format_predecessors_ready());}while(0)
 REJECT_FORMAT(notification.ap_consumed=0,notification.ap_consumed=1);
 REJECT_FORMAT(notification.waiter_tid=100,notification.waiter_tid=99);
 REJECT_FORMAT(notification.d018_readback=0,notification.d018_readback=1);
 REJECT_FORMAT(cp_parameter_batch_state.staged=false,cp_parameter_batch_state.staged=true);
 REJECT_FORMAT(cp_parameter_batch_state.semantic_applied=true,cp_parameter_batch_state.semantic_applied=false);
 REJECT_FORMAT(cp_parameter_batch_retained_request=&central,cp_parameter_batch_retained_request=NULL);
 REJECT_FORMAT(cp_output_policy_state.state.config_consumed=false,cp_output_policy_state.state.config_consumed=true);
 REJECT_FORMAT(cp_output_policy_state.state.known_mask=0,cp_output_policy_state.state.known_mask=CP_OUTPUT_POLICY_KNOWN_MASK);
 assert(!cp_startup_controls_predecessors_ready());
 format.owner_pid=pid;format.initialized=format.diagnostic_only=format.no_publication=1;
 format.requests=format.clean_completion=format.ap_consumed=format.queued=1;
 format.request_freed=format.reply_freed=1;format.sender_tid=format.waiter_tid=99;
 format.reply_free_destination=0x80020002u;format.reply_free_source=NATIVE_CP_CAPTURE_FORMAT_SID;
 format.reply_free_bytes=12;
 assert(cp_startup_controls_predecessors_ready());
#define REJECT_STARTUP(change,restore) do{change;assert(!cp_startup_controls_predecessors_ready());restore;assert(cp_startup_controls_predecessors_ready());}while(0)
 REJECT_STARTUP(format.owner_pid++,format.owner_pid--);
 REJECT_STARTUP(format.reply_freed=0,format.reply_freed=1);
 REJECT_STARTUP(format.source_business_applied=1,format.source_business_applied=0);
 REJECT_STARTUP(format.waiter_tid=100,format.waiter_tid=99);
 REJECT_STARTUP(format.freed_reply_wire[7]=1,format.freed_reply_wire[7]=0);
 REJECT_STARTUP(format.reply_free_source=0,format.reply_free_source=NATIVE_CP_CAPTURE_FORMAT_SID);
 REJECT_STARTUP(format.live_reply=&central,format.live_reply=NULL);
 assert(!cp_ee_controls_predecessors_ready());
 startup.owner_pid=pid;startup.initialized=startup.diagnostic_only=1;
 startup.requests=startup.completed=2;
 startup.leases[0].opcode=0x4014;startup.leases[1].opcode=0x40c8;startup.leases[2].opcode=0x4057;
 for(unsigned int i=0;i<CP_STARTUP_CONTROLS_COMMANDS;i++) {
  if(i==1)continue;
  struct native_cp_startup_controls_diagnostic_lease *s=&startup.leases[i];
  s->requests=s->clean_completion=s->ap_consumed=s->queued=s->request_freed=s->reply_freed=1;
  s->sender_tid=s->waiter_tid=99;s->source=s->destination=s->reply_free_destination=0x80020002u;
  s->request_destination=s->reply_free_source=NATIVE_CP_STARTUP_CONTROLS_SID;s->reply_free_bytes=12;
 }
 assert(cp_ee_controls_predecessors_ready());
 current_tid=100;assert(!cp_startup_controls_predecessors_ready());assert(cp_ee_controls_predecessors_ready());
#define REJECT_EE(change,restore) do{change;assert(!cp_ee_controls_predecessors_ready());restore;assert(cp_ee_controls_predecessors_ready());}while(0)
 REJECT_EE(startup.owner_pid++,startup.owner_pid--);
 REJECT_EE(startup.completed=1,startup.completed=2);
 REJECT_EE(startup.leases[2].request_freed=0,startup.leases[2].request_freed=1);
 REJECT_EE(startup.leases[0].waiter_tid=100,startup.leases[0].waiter_tid=99);
 REJECT_EE(startup.leases[2].sender_tid=100,startup.leases[2].sender_tid=99);
 REJECT_EE(startup.leases[0].reply_free_rc=-1,startup.leases[0].reply_free_rc=0);
 REJECT_EE(startup.leases[1].retained_request=&central,startup.leases[1].retained_request=NULL);
 REJECT_EE(startup.leases[0].source=0,startup.leases[0].source=0x80020002u);
 REJECT_EE(startup.leases[2].reply_free_bytes=16,startup.leases[2].reply_free_bytes=12);
 REJECT_EE(startup.leases[2].freed_reply_wire[7]=1,startup.leases[2].freed_reply_wire[7]=0);
 REJECT_EE(startup.published=1,startup.published=0);
 REJECT_EE(format.waiter_tid=100,format.waiter_tid=99);
 REJECT_EE(central.reply_free_rc=-1,central.reply_free_rc=0);
 REJECT_EE(notification.d018_readback=0,notification.d018_readback=1);
 REJECT_EE(pool.slots[1].open_count=1,pool.slots[1].open_count=2);
 assert(!cp_movie_format_predecessors_ready());assert(!cp_ee_controls_after_movie_predecessors_ready());
 ee_controls.owner_pid=pid;ee_controls.initialized=ee_controls.diagnostic_only=1;
 ee_controls.requests=ee_controls.completed=1;
 struct native_cp_ee_controls_diagnostic_lease *d=&ee_controls.leases[0];
 d->opcode=0x409d;d->requests=d->queued=d->clean_completion=d->ap_consumed=d->request_freed=d->reply_freed=1;
 d->sender_tid=d->waiter_tid=100;d->source=d->destination=d->reply_free_destination=0x80020002u;
 d->request_destination=d->reply_free_source=NATIVE_CP_EE_CONTROLS_SID;d->reply_free_bytes=12;
 assert(cp_movie_format_predecessors_ready());
#define REJECT_MOVIE_PRE(change,restore) do{change;assert(!cp_movie_format_predecessors_ready());restore;assert(cp_movie_format_predecessors_ready());}while(0)
 REJECT_MOVIE_PRE(ee_controls.owner_pid++,ee_controls.owner_pid--);
 REJECT_MOVIE_PRE(ee_controls.completed=0,ee_controls.completed=1);
 REJECT_MOVIE_PRE(d->sender_tid=99,d->sender_tid=100);
 REJECT_MOVIE_PRE(d->waiter_tid=101,d->waiter_tid=100);
 REJECT_MOVIE_PRE(d->reply_free_rc=-1,d->reply_free_rc=0);
 REJECT_MOVIE_PRE(d->reply_free_source=0,d->reply_free_source=NATIVE_CP_EE_CONTROLS_SID);
 REJECT_MOVIE_PRE(d->live_reply=&central,d->live_reply=NULL);
 assert(!cp_movie_format_completed());assert(!cp_ee_controls_after_movie_predecessors_ready());
 movie.owner_pid=pid;movie.initialized=movie.diagnostic_only=movie.no_publication=1;
 movie.requests=movie.queued=movie.clean_completion=movie.ap_consumed=movie.request_freed=movie.reply_freed=1;
 movie.sender_tid=movie.waiter_tid=100;movie.source=movie.destination=movie.reply_free_destination=0x80020002u;
 movie.request_destination=movie.reply_free_source=NATIVE_CP_MOVIE_FORMAT_SID;movie.reply_free_bytes=12;
 movie.known_field_mask=movie.virtual_field_mask=movie.virtual_fields_consumed=CP_MOVIE_FORMAT_KNOWN_MASK;
 movie.virtual_fields_readback=1;movie.virtual_fields[0]=movie.virtual_readback[0]=5;
 movie.virtual_fields[1]=movie.virtual_readback[1]=1;movie.virtual_fields[6]=movie.virtual_readback[6]=1;
 assert(cp_movie_format_completed());assert(cp_ee_controls_after_movie_predecessors_ready());
#define REJECT_MOVIE(change,restore) do{change;assert(!cp_ee_controls_after_movie_predecessors_ready());restore;assert(cp_ee_controls_after_movie_predecessors_ready());}while(0)
 REJECT_MOVIE(movie.owner_pid++,movie.owner_pid--);
 REJECT_MOVIE(movie.reply_freed=0,movie.reply_freed=1);
 REJECT_MOVIE(movie.waiter_tid=101,movie.waiter_tid=100);
 REJECT_MOVIE(movie.reply_free_bytes=16,movie.reply_free_bytes=12);
 REJECT_MOVIE(movie.freed_reply_wire[4]=1,movie.freed_reply_wire[4]=0);
 REJECT_MOVIE(movie.virtual_field_mask=0x3f,movie.virtual_field_mask=CP_MOVIE_FORMAT_KNOWN_MASK);
 REJECT_MOVIE(movie.virtual_readback[3]=1,movie.virtual_readback[3]=0);
 REJECT_MOVIE(movie.business_applied=1,movie.business_applied=0);
 REJECT_MOVIE(movie.live_reply=&central,movie.live_reply=NULL);
 current_tid=101;assert(cp_ee_controls_after_movie_predecessors_ready());
 assert(!cp_owned_state_predecessors_ready());
 struct native_cp_ee_controls_diagnostic_lease *oneway=&ee_controls.leases[1];
 oneway->opcode=0x4072;oneway->requests=oneway->oneway=oneway->oneway_consumed=1;
 oneway->request_freed=oneway->clean_completion=oneway->virtual_fields_readback=1;
 oneway->virtual_field_mask=oneway->virtual_fields_consumed=3;
 oneway->source=0x80020002u;oneway->request_destination=NATIVE_CP_EE_CONTROLS_SID;
 assert(cp_owned_state_predecessors_ready());
#define REJECT_OWNED(change,restore) do{change;assert(!cp_owned_state_predecessors_ready());restore;assert(cp_owned_state_predecessors_ready());}while(0)
 REJECT_OWNED(oneway->oneway_consumed=0,oneway->oneway_consumed=1);
 REJECT_OWNED(oneway->queued=1,oneway->queued=0);
 REJECT_OWNED(oneway->reply_freed=1,oneway->reply_freed=0);
 REJECT_OWNED(oneway->request_free_rc=-1,oneway->request_free_rc=0);
 REJECT_OWNED(oneway->source=0,oneway->source=0x80020002u);
 REJECT_OWNED(oneway->virtual_readback[0]=1,oneway->virtual_readback[0]=0);
 REJECT_OWNED(movie.reply_freed=0,movie.reply_freed=1);
 puts("PASS actual all13 gate: persistent OSD references required; original-free evidence forwarded transparently");
 return 0;
}
'''
    path = tmp_path / 'cp302c-observer-boundaries.c'
    path.write_text(code)
    binary = tmp_path / 'cp302c-observer-boundaries'
    built = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                            '-fsanitize=address,undefined', '-fno-pie', '-no-pie', '-I', str(HERE),
                            str(path), '-o', str(binary)], capture_output=True, text=True, timeout=20)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith('PASS actual all13 gate: persistent OSD references required')
