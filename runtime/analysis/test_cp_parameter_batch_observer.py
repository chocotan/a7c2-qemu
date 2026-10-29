"""Execute actual observer staging with host-only predecessor and transport fixtures."""
from pathlib import Path
import subprocess

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent


def test_actual_batch_staging_owns_bytes_without_ack_or_publish(tmp_path):
    observer = (HERE / 'menu-observe.c').read_text()
    source = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "device-models/cp-notification-control.h"
#include "device-models/cp-parameter-batch.h"
#include "device-models/cp-output-policy.h"
#include "device-models/cp-parameter-state.h"
static int cp_owned_state_enabled;
static struct cp_parameter_state cp_owned_parameters;
static unsigned long cp_owned_state_mutex[6];
static struct cp_output_policy cp_output_policy_state;
static int cp_notification_control_enabled=1,ready=1,release_rc;
static unsigned int frees,records,wire_bytes=CP_PARAMETER_BATCH_BYTES,wire_source=CP_PARAMETER_BATCH_SOURCE;
static struct cp_parameter_batch cp_parameter_batch_state;
static unsigned long cp_parameter_batch_mutex[6];
static void *cp_parameter_batch_retained_request;
static unsigned int size_of(void *p){(void)p;return wire_bytes;}
static unsigned int source_of(void *p){(void)p;return wire_source;}
static int release_packet(unsigned int id,void *p){assert(id==CP_PARAMETER_BATCH_TARGET && p);frees++;return release_rc;}
static unsigned int (*real_msg_size)(void *)=size_of;
static unsigned int (*real_get_source)(void *)=source_of;
static int (*real_free_msg)(unsigned int,void *)=release_packet;
static int cp_notification_predecessors_ready(void){return ready;}
static long thread(void){return syscall(SYS_gettid);}
#define syscall(number) ((void)(number),thread())
void native_cp_notification_snapshot(struct native_cp_notification_snapshot *out){
 memset(out,0,sizeof(*out));out->owner_pid=getpid();out->initialized=1;out->requests=1;
 out->clean_completion=out->ap_consumed=out->reply_freed=1;out->sender_tid=out->waiter_tid=thread();
}
static int lock(void *p){return pthread_mutex_lock(p);}
static int unlock(void *p){return pthread_mutex_unlock(p);}
#define pthread_mutex_lock lock
#define pthread_mutex_unlock unlock
static void record(const char *tag,const char *text){
 if(!strcmp(tag,"NATIVE_CP_PARAMETER_STATE_CONSUMED ")) {
  assert(strstr(text,"generation_advanced=0 original_CP=0 capture=0"));records++;return;
 }
 assert(!strcmp(tag,"NATIVE_CP_PARAMETER_BATCH_STAGED ") || !strcmp(tag,"NATIVE_CP_OUTPUT_POLICY_CONSUMED "));
 assert(strstr(text,"copied_readback=1") && strstr(text,"stage_only=1 semantic_applied=0 semantic_slots=0 generation_advanced=0 published=0 ACK_sent=0"));records++;
}
''' + function(observer, 'cp_parameter_config_receive') + r'''
int main(int argc,char **argv){
 assert(argc==2);const char *test=argv[1];int policy=!strncmp(test,"policy-",7);if(policy)test+=7;
 unsigned char wire[CP_PARAMETER_BATCH_BYTES];
 for(unsigned int i=0;i<sizeof wire;i++)wire[i]=(unsigned char)(i*37+19);
 wire[0]=5;wire[2]=0x63;wire[3]=0x40;
 for(unsigned int i=0;i<CP_PARAMETER_BATCH_SLOTS;i++){
  const struct cp_parameter_batch_slot *slot=&cp_parameter_batch_slots[i];
  wire[slot->offset]=5;wire[slot->offset+2]=(unsigned char)slot->opcode;
  wire[slot->offset+3]=(unsigned char)(slot->opcode>>8);
 }
 if(!strcmp(test,"owned"))cp_owned_state_enabled=1;
 assert(!cp_parameter_state_init(&cp_owned_parameters,true));
 assert(!cp_parameter_batch_init(&cp_parameter_batch_state,true));
 assert(!cp_output_policy_init(&cp_output_policy_state,true));
 if(policy){wire[2]=0xf9;wire_bytes=CP_OUTPUT_POLICY_BYTES;}
 if(!strcmp(test,"predecessor"))ready=0;
 if(!strcmp(test,"source"))wire_source++;
 if(!strcmp(test,"short"))wire_bytes--;
 if(!strcmp(test,"slot"))wire[cp_parameter_batch_slots[99].offset+2]^=1;
 if(!strcmp(test,"free-failure"))release_rc=-19;
 if(!strcmp(test,"off"))cp_notification_control_enabled=0;
 int result=321,handled=cp_parameter_config_receive(CP_PARAMETER_BATCH_TARGET,wire,&result);
 if(!strcmp(test,"off")){assert(!handled && result==321 && !frees && !records);return 0;}
 assert(handled);
 if(!strcmp(test,"predecessor") || !strcmp(test,"source") || !strcmp(test,"short") || !strcmp(test,"slot")){
  assert(result==-1021 && !frees && !records && !cp_parameter_batch_state.staged);return 0;
 }
 assert(!result && frees==1 && records==(cp_owned_state_enabled?2u:1u));
 if(policy){
  assert(cp_output_policy_state.state.config_consumed && cp_output_policy_state.state.known_mask==CP_OUTPUT_POLICY_KNOWN_MASK);
  assert(!cp_output_policy_state.state.semantic_applied && !cp_output_policy_state.state.published);
  assert(!memcmp(cp_output_policy_state.state.bytes,wire,CP_OUTPUT_POLICY_BYTES));
 }else{
  assert(cp_parameter_batch_state.staged && !cp_parameter_batch_state.semantic_applied);
  assert(!memcmp(cp_parameter_batch_state.bytes,wire,sizeof wire));
 }
 assert(cp_parameter_batch_retained_request==(!strcmp(test,"free-failure")?(void *)wire:NULL));
 for(unsigned int i=0;i<CP_PARAMETER_BATCH_MASK_WORDS;i++)assert(!cp_parameter_batch_state.semantic_consumed[i]);
 wire[8]^=0xff;assert((policy?cp_output_policy_state.state.bytes[8]:cp_parameter_batch_state.bytes[8])!=wire[8]);
 puts("PASS actual observer:190-slot byte staging and transport ownership only; no ACK/generation/publication");return 0;
}
'''
    path = tmp_path / 'batch-observer.c'
    path.write_text(source)
    binary = tmp_path / 'batch-observer'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fsanitize=address,undefined', '-fno-pie', '-no-pie', '-pthread',
                    '-I', str(HERE), str(path), str(HERE / 'device-models/cp-parameter-batch.c'),
                    str(HERE / 'device-models/cp-output-policy.c'),
                    str(HERE / 'device-models/cp-parameter-state.c'), '-o', str(binary)], check=True, capture_output=True, text=True, timeout=20)
    for scenario in ('normal', 'owned', 'predecessor', 'source', 'short', 'slot', 'free-failure', 'off',
                     'policy-normal', 'policy-predecessor', 'policy-source', 'policy-short',
                     'policy-free-failure', 'policy-off'):
        result = subprocess.run([str(binary), scenario], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, scenario + result.stdout + result.stderr
