/* SPDX-License-Identifier: MIT */
#include "remote-state.h"
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
static unsigned int freed;
static int release(unsigned int id,void *p) {assert(id==REMOTE_STATE_SID);free(p);freed++;return 0;}
static void record(const char *prefix,const char *text) {assert(prefix && text);}
int main(void) {
    struct remote_state s={0},saved;
    unsigned char wire[REMOTE_STATE_WIRE_BYTES];
    memset(wire,0xa5,sizeof wire);wire[0]=1;wire[1]=0x23;wire[2]=wire[3]=0;
    assert(remote_state_apply(&s,wire,sizeof wire)==1 && s.control_command==0x2301);
    wire[0]=3;memset(wire+8,0x55,REMOTE_STATE_BYTES);
    assert(remote_state_apply(&s,wire,sizeof wire)==1 && s.generation==1);
    for(unsigned int i=0;i<10000;i++) {
        wire[4]=(unsigned char)i;wire[1503]=(unsigned char)(i>>4);
        assert(remote_state_apply(&s,wire,sizeof wire)==0);
        void *p=malloc(sizeof wire);assert(p);memcpy(p,wire,sizeof wire);
        assert(full_remote_state_dispatch(REMOTE_STATE_SID,p,sizeof wire,REMOTE_STATE_SID,release,record)==0);
    }
    assert(s.generation==1 && freed==10000);
    wire[1495]^=1;assert(remote_state_apply(&s,wire,sizeof wire)==1 && s.generation==2);
    saved=s;wire[0]=0x8f;
    assert(remote_state_apply(&s,wire,sizeof wire)<0 && !memcmp(&s,&saved,sizeof s));
    void *p=malloc(sizeof wire);assert(p);memcpy(p,wire,sizeof wire);
    assert(full_remote_state_dispatch(REMOTE_STATE_SID,p,sizeof wire,REMOTE_STATE_SID,release,record)<0);
    assert(freed==10000);free(p);
    wire[0]=4;memset(wire+8,0x36,36);
    assert(remote_state_apply(&s,wire,sizeof wire)==1 && s.gps_init_seen);
    assert(!memcmp(s.gps_configuration,wire+8,36));
    wire[44]^=1;
    assert(remote_state_apply(&s,wire,sizeof wire)==0); /* init padding */
    wire[0]=0;memset(wire+8,0x77,1432);
    assert(remote_state_apply(&s,wire,sizeof wire)==1 && s.gps_generation==1);
    assert(!memcmp(s.gps_bytes,wire+8,1432));
    wire[1440]^=1;
    assert(remote_state_apply(&s,wire,sizeof wire)==0); /* snapshot padding */
    p=malloc(sizeof wire);assert(p);memcpy(p,wire,sizeof wire);
    assert(full_remote_state_dispatch(REMOTE_STATE_SID,p,sizeof wire,0xa1e057,release,record)==0);
    assert(freed==10001);
    p=malloc(sizeof wire);assert(p);memcpy(p,wire,sizeof wire);
    assert(full_remote_state_dispatch(REMOTE_STATE_SID,p,sizeof wire,0xa1e058,release,record)<0);
    assert(freed==10001);free(p);
    wire[0]=3;assert(remote_state_apply(&s,wire,sizeof wire-1)<0);
    p=malloc(sizeof wire);assert(p);memcpy(p,wire,sizeof wire);
    assert(full_remote_state_dispatch(REMOTE_STATE_SID,p,sizeof wire,1,release,record)<0);
    assert(freed==10001);free(p);
    puts("REMOTE_STATE_TEST_PASS repeats=10000 padding_ignored=1 atomic_rejects=1 ownership=1");
}
