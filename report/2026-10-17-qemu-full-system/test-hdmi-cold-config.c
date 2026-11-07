/* SPDX-License-Identifier: MIT */
#include "hdmi-hpd-owner.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct hdmi_hpd_owner owner,noncold,changed,overflow,lease_exhausted,lease_reserved;
static unsigned char initial[18]={6,'I','L','C','E','-','7','C','M','2',0,0,0,0,0,0,0,0x7f};
static struct hdmi_hpd_snapshot snapshot(struct hdmi_hpd_owner *o){
    struct hdmi_hpd_snapshot s;assert(!hdmi_hpd_snapshot(o,&s));return s;
}
static unsigned int fresh(struct hdmi_hpd_owner *o){
    unsigned int id=0;assert(!hdmi_hpd_init_unplugged(o,1));
    assert(!hdmi_hpd_open(o,0x909a07f6,&id));assert(id==1);
    assert(!hdmi_config_bind_fresh(o,id));assert(hdmi_config_bind_fresh(o,id)==-1);
    assert(hdmi_config_write_initial(o,id,initial,18)==18);
    struct hdmi_hpd_snapshot s=snapshot(o);assert(s.config.initial[17]==0 && s.config.initial_known);
    return id;
}
static uint64_t pop(struct hdmi_hpd_owner *o,unsigned int id,unsigned int kind){
    unsigned char bytes[16];memset(bytes,0xa5,sizeof bytes);uint64_t lease=0;
    assert(!hdmi_hpd_dequeue(o,id,bytes,16,&lease));
    unsigned char expected[12]={0};expected[0]=(unsigned char)kind;
    assert(!memcmp(bytes,expected,12) && bytes[12]==0xa5 && lease);return lease;
}
struct work {struct hdmi_hpd_owner *owner;unsigned int id;uint64_t generation;int rc;};
static void *worker(void *arg){struct work *w=arg;w->rc=hdmi_config_work_once(w->owner,w->id,w->generation);return 0;}

int main(void){
    unsigned char config[36]={0},saved[36],out[12];
    for(unsigned int i=8;i<36;i++)config[i]=(unsigned char)(0x55^i);memcpy(saved,config,36);
    assert(hdmi_config_bind_fresh(&owner,1)==-1);
    unsigned int first=fresh(&owner),second=0;assert(!hdmi_hpd_open(&owner,0x909a07f7,&second));
    uint64_t generation=0,lease=0;
    assert(hdmi_config_write_initial(&owner,first,initial,18)==-1);
    config[0]=1;assert(hdmi_config_submit(&owner,first,config,36,&generation)==-1 && !generation);
    config[0]=0;assert(hdmi_config_submit(&owner,second,config,36,&generation)==-1);
    assert(!hdmi_config_submit(&owner,first,config,36,&generation) && generation==1);
    memset(config+8,0xff,28);
    struct hdmi_hpd_snapshot s=snapshot(&owner);
    assert(s.config.job_live && s.config.descriptor_live && !s.config.job_applied && !s.config.completed);
    assert(!memcmp(s.config.staged,saved,36));
    assert(hdmi_hpd_set_level(&owner,0)==-1 && !snapshot(&owner).level_updates);
    assert(hdmi_hpd_dequeue(&owner,first,out,12,&lease)==-11);
    assert(hdmi_hpd_close(&owner,first)==-1);
    assert(hdmi_config_work_once(&owner,second,generation)==-1);
    assert(hdmi_config_work_once(&owner,first,generation+1)==-1);
    struct work w={&owner,first,generation,-1};pthread_t thread;
    assert(!pthread_create(&thread,0,worker,&w));assert(!pthread_join(thread,0));assert(w.rc==0);
    s=snapshot(&owner);assert(!s.config.job_live && !s.config.descriptor_live && s.config.completed==1 && s.config.applied_count==1);
    assert(!memcmp(s.config.applied,saved,36));assert(hdmi_config_work_once(&owner,first,generation)==-1);
    assert(hdmi_hpd_dequeue(&owner,second,out,12,&lease)==-11);assert(pop(&owner,first,7)==s.config.completion_lease);

    /* A stale first-handle HPD event must not satisfy or hide config work. */
    assert(!hdmi_hpd_set_mask(&owner,first,HDMI_HPD_MASK_ON));assert(!hdmi_hpd_replay(&owner,first,&lease));
    assert(hdmi_config_submit(&owner,first,saved,36,&generation)==-1);pop(&owner,first,1);
    assert(!hdmi_config_submit(&owner,first,saved,36,&generation));
    assert(!hdmi_hpd_replay(&owner,first,&lease));assert(hdmi_config_work_once(&owner,first,generation)==-2);
    s=snapshot(&owner);assert(s.config.job_live && s.config.descriptor_live && s.config.job_applied && s.config.applied_count==2 && s.config.completed==1);
    assert(hdmi_hpd_set_level(&owner,0)==-1 && hdmi_hpd_set_level(&owner,1)==-1 && !snapshot(&owner).level_updates);
    pop(&owner,first,1);assert(!hdmi_config_work_once(&owner,first,generation));pop(&owner,first,7);
    assert(snapshot(&owner).config.applied_count==2);

    /* Global capacity pressure retains the applied job and descriptor. */
    assert(!hdmi_hpd_set_mask(&owner,second,HDMI_HPD_MASK_ON));
    for(unsigned int i=0;i<HDMI_HPD_EVENTS;i++)assert(!hdmi_hpd_replay(&owner,second,&lease));
    assert(!hdmi_config_submit(&owner,first,saved,36,&generation));
    assert(hdmi_config_work_once(&owner,first,generation)==-2 && hdmi_hpd_close(&owner,first)==-1);
    pop(&owner,second,1);assert(!hdmi_config_work_once(&owner,first,generation));pop(&owner,first,7);
    for(unsigned int i=1;i<HDMI_HPD_EVENTS;i++)pop(&owner,second,1);
    s=snapshot(&owner);assert(s.config.submitted==3 && s.config.applied_count==3 && s.config.completed==3);
    assert(s.queued==s.consumed && !s.live_events);
    assert(!hdmi_hpd_close(&owner,first));assert(hdmi_config_submit(&owner,first,saved,36,&generation)==-1);

    unsigned int id=fresh(&noncold);noncold.state.config.current_mode=4;noncold.state.config.target_mode=4;
    assert(hdmi_config_submit(&noncold,id,saved,36,&generation)==-1);
    assert(snapshot(&noncold).config.current_mode==4 && !snapshot(&noncold).config.submitted);
    id=fresh(&changed);assert(!hdmi_hpd_set_level(&changed,0));
    assert(hdmi_config_submit(&changed,id,saved,36,&generation)==-1 && !snapshot(&changed).config.submitted);
    id=fresh(&overflow);overflow.state.config.generation=UINT64_MAX;
    assert(hdmi_config_submit(&overflow,id,saved,36,&generation)==-1 && snapshot(&overflow).config.generation==UINT64_MAX);
    id=fresh(&lease_exhausted);lease_exhausted.state.next_lease=UINT64_MAX;generation=123;
    assert(hdmi_config_submit(&lease_exhausted,id,saved,36,&generation)==-1 && generation==123);
    assert(!snapshot(&lease_exhausted).config.job_live && !snapshot(&lease_exhausted).config.descriptor_live);
    id=fresh(&lease_reserved);assert(!hdmi_hpd_open(&lease_reserved,0x909a07f7,&second));
    assert(!hdmi_hpd_set_mask(&lease_reserved,second,HDMI_HPD_MASK_ON));
    lease_reserved.state.next_lease=UINT64_MAX-2;
    assert(!hdmi_config_submit(&lease_reserved,id,saved,36,&generation));
    assert(!hdmi_hpd_replay(&lease_reserved,second,&lease) && lease==UINT64_MAX-1);
    lease=17;assert(hdmi_hpd_replay(&lease_reserved,second,&lease)==-1 && lease==17);
    assert(!hdmi_config_work_once(&lease_reserved,id,generation));
    assert(pop(&lease_reserved,id,7)==UINT64_MAX && pop(&lease_reserved,second,1)==UINT64_MAX-1);
    s=snapshot(&lease_reserved);assert(s.config.completed==1 && !s.config.job_live && !s.config.descriptor_live);
    assert(hdmi_config_submit(&lease_reserved,id,saved,36,&generation)==-1);
    puts("HDMI_COLD_REAL_CONFIG_JOB_SAME_OWNER_COMPLETION_BACKPRESSURE_PASS");return 0;
}
#ifdef HDMI_HPD_ORIGINAL_ABI
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
static int abi_main(int argc,char **argv){(void)argc;(void)argv;return main();}
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl abi_entry\nbrk #0\n");
__attribute__((noreturn)) void abi_entry(unsigned long *stack){
    __libc_start_main(abi_main,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
#endif
