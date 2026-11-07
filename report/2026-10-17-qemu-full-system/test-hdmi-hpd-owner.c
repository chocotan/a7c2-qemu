/* SPDX-License-Identifier: MIT */
#include "hdmi-hpd-owner.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static struct hdmi_hpd_owner owner;
static struct hdmi_hpd_snapshot snapshot(void){struct hdmi_hpd_snapshot s;assert(!hdmi_hpd_snapshot(&owner,&s));return s;}
static void consume(unsigned int client,uint64_t lease,unsigned int value){
    unsigned char out[12];assert(!hdmi_hpd_read(&owner,client,lease,out));
    unsigned char expected[12]={1,0,0,0,0,0,0,0,0,0,0,0};expected[8]=(unsigned char)value;
    assert(!memcmp(out,expected,12));assert(!hdmi_hpd_consume(&owner,client,lease,out));
    assert(hdmi_hpd_consume(&owner,client,lease,out)==-1);
}
struct dequeues {unsigned int client,count;uint64_t leases[HDMI_HPD_EVENTS];};
static void *drain(void *argument){
    struct dequeues *batch=argument;
    for(;;){
        unsigned char data[16];memset(data,0xa5,sizeof data);uint64_t lease=0;
        int rc=hdmi_hpd_dequeue(&owner,batch->client,data,sizeof data,&lease);
        if(rc==-11)break;
        assert(rc==0 && batch->count<HDMI_HPD_EVENTS && lease);
        assert(!memcmp(data,(unsigned char[]){1,0,0,0,0,0,0,0,1,0,0,0},12));
        assert(data[12]==0xa5);batch->leases[batch->count++]=lease;
    }
    return 0;
}
int main(void){
    unsigned int client=0,second=0;uint64_t lease=99;unsigned char expected[12]={1};
    assert(hdmi_hpd_init_unplugged(&owner,0)==-1);
    assert(hdmi_hpd_open(&owner,0x909a07f6,&client)==-1);
    assert(!hdmi_hpd_init_unplugged(&owner,1));assert(hdmi_hpd_init_unplugged(&owner,1)==-1);
    assert(!hdmi_hpd_open(&owner,0x909a07f6,&client));assert(client==1);
    assert(hdmi_hpd_open(&owner,0x909a07f6,&second)==-1);
    assert(hdmi_hpd_replay(&owner,client,&lease)==1 && lease==99 && !snapshot().queued);
    assert(!hdmi_hpd_set_mask(&owner,client,HDMI_HPD_MASK_ON));
    assert(!hdmi_hpd_replay(&owner,client,&lease));assert(lease==1 && snapshot().live_events==1);
    assert(hdmi_hpd_consume(&owner,client,lease,expected)==-1 && !snapshot().consumed);
    assert(hdmi_hpd_close(&owner,client)==-1);
    unsigned char out[12];assert(!hdmi_hpd_read(&owner,client,lease,out));out[8]=1;
    assert(hdmi_hpd_consume(&owner,client,lease,out)==-1 && snapshot().live_events==1);
    assert(!hdmi_hpd_set_level(&owner,1));consume(client,lease,0);
    assert(!hdmi_hpd_replay(&owner,client,&lease));consume(client,lease,1);
    unsigned char event_bytes[16];memset(event_bytes,0xa5,sizeof event_bytes);lease=73;
    assert(hdmi_hpd_dequeue(&owner,client,event_bytes,12,&lease)==-11 && lease==73);
    assert(event_bytes[0]==0xa5 && snapshot().queued==snapshot().consumed);
    assert(!hdmi_hpd_replay(&owner,client,&lease));uint64_t next=0;
    assert(hdmi_hpd_dequeue(&owner,client,event_bytes,11,&next)==-90 && next==0);
    assert(event_bytes[0]==0xa5 && snapshot().live_events==1);
    assert(!hdmi_hpd_dequeue(&owner,client,event_bytes,12,&next));
    assert(next==lease && !memcmp(event_bytes,(unsigned char[]){1,0,0,0,0,0,0,0,1,0,0,0},12));
    assert(event_bytes[12]==0xa5 && snapshot().queued==snapshot().consumed);
    assert(hdmi_hpd_read(&owner,client,lease,event_bytes)==-1);
    assert(!hdmi_hpd_set_mask(&owner,client,HDMI_HPD_MASK_OFF));
    assert(hdmi_hpd_replay(&owner,client,&lease)==1 && snapshot().queued==3);
    assert(!hdmi_hpd_open(&owner,0x909a07f7,&second));
    assert(!hdmi_hpd_set_mask(&owner,second,HDMI_HPD_MASK_ON));
    uint64_t leases[HDMI_HPD_EVENTS];
    for(unsigned int i=0;i<HDMI_HPD_EVENTS;i++)assert(!hdmi_hpd_replay(&owner,second,&leases[i]));
    struct hdmi_hpd_snapshot before=snapshot();assert(hdmi_hpd_replay(&owner,second,&lease)==-1);
    struct hdmi_hpd_snapshot after=snapshot();
    assert(before.next_lease==after.next_lease && before.queued==after.queued && before.consumed==after.consumed &&
           before.live_events==after.live_events && !memcmp(before.clients,after.clients,sizeof before.clients));
    assert(hdmi_hpd_read(&owner,second,leases[1],out)==-1);
    unsigned int pending=HDMI_HPD_EVENTS;
    for(unsigned int i=0;i<HDMI_HPD_EVENTS;i++)
        if(owner.events[i].live && owner.events[i].lease==leases[1])pending=i;
    assert(pending<HDMI_HPD_EVENTS);
    unsigned char original[12];memcpy(original,owner.events[pending].wire,12);
    uint64_t illegal_lease=73,words[2]={0x1122334455667788ull,0xaabbccddeeff0011ull};
    assert(hdmi_hpd_dequeue(&owner,second,owner.events[pending].wire,12,&illegal_lease)==-1);
    assert(hdmi_hpd_dequeue(&owner,second,(unsigned char *)words,12,words)==-1);
    assert(hdmi_hpd_dequeue(&owner,second,out,12,&owner.events[pending].lease)==-1);
    assert(hdmi_hpd_read(&owner,second,leases[0],owner.events[pending].wire)==-1);
    assert(hdmi_hpd_replay(&owner,second,&owner.events[pending].lease)==-1);
    assert(hdmi_hpd_snapshot(&owner,&owner.state)==-1);
    assert(hdmi_hpd_open(&owner,0x909a07f8,&owner.state.open_clients)==-1);
    after=snapshot();assert(after.queued==before.queued && after.consumed==before.consumed &&
                             after.live_events==before.live_events && after.open_clients==before.open_clients);
    assert(!memcmp(original,owner.events[pending].wire,12) && illegal_lease==73);
    assert(words[0]==0x1122334455667788ull && words[1]==0xaabbccddeeff0011ull);
    assert(hdmi_hpd_dequeue(&owner,second,out,8,&lease)==-90 && snapshot().live_events==8);
    assert(hdmi_hpd_dequeue(&owner,client,out,12,&lease)==-11 && snapshot().live_events==8);
    for(unsigned int i=0;i<HDMI_HPD_EVENTS;i++){
        assert(hdmi_hpd_read(&owner,client,leases[i],out)==-1);consume(second,leases[i],1);
    }
    for(unsigned int i=0;i<HDMI_HPD_EVENTS;i++)assert(!hdmi_hpd_replay(&owner,second,&leases[i]));
    struct dequeues left={.client=second},right={.client=second};pthread_t thread_a,thread_b;
    assert(!pthread_create(&thread_a,0,drain,&left));
    assert(!pthread_create(&thread_b,0,drain,&right));
    assert(!pthread_join(thread_a,0) && !pthread_join(thread_b,0));
    assert(left.count+right.count==HDMI_HPD_EVENTS);
    unsigned int seen[HDMI_HPD_EVENTS]={0};
    for(unsigned int i=0;i<left.count;i++){
        assert(left.leases[i]>=leases[0] && left.leases[i]<=leases[HDMI_HPD_EVENTS-1]);
        seen[left.leases[i]-leases[0]]++;
    }
    for(unsigned int i=0;i<right.count;i++){
        assert(right.leases[i]>=leases[0] && right.leases[i]<=leases[HDMI_HPD_EVENTS-1]);
        seen[right.leases[i]-leases[0]]++;
    }
    for(unsigned int i=0;i<HDMI_HPD_EVENTS;i++)assert(seen[i]==1);
    assert(snapshot().queued==snapshot().consumed && !snapshot().live_events);
    assert(!hdmi_hpd_close(&owner,client));assert(!hdmi_hpd_close(&owner,second));
    assert(hdmi_hpd_set_mask(&owner,client,HDMI_HPD_MASK_ON)==-1);
    assert(!hdmi_hpd_open(&owner,0x909a07f8,&client));assert(client==3);
    assert(!hdmi_hpd_close(&owner,client));assert(hdmi_hpd_open(&owner,0x909a07f6,&client)==-1);
    assert(hdmi_hpd_set_level(&owner,2)==-1);
    assert(snapshot().queued==snapshot().consumed && !snapshot().live_events);
    /* Inherited mutex deliberately locked: child must refuse before locking. */
    assert(!pthread_mutex_lock(&owner.mutex));pid_t pid=fork();assert(pid>=0);
    if(!pid){struct hdmi_hpd_snapshot s;_exit(hdmi_hpd_snapshot(&owner,&s)==-1?0:1);}
    int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && WEXITSTATUS(status)==0);
    assert(!pthread_mutex_unlock(&owner.mutex));
    puts("HDMI_HPD_EVENT_ATOMIC_OP1_READ_CONSUME_FIFO_FORK_PASS");return 0;
}
#ifdef HDMI_HPD_ORIGINAL_ABI
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
static int abi_main(int argc,char **argv){(void)argc;(void)argv;return main();}
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl abi_entry\nbrk #0\n");
__attribute__((noreturn)) void abi_entry(unsigned long *stack){
    __libc_start_main(abi_main,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
#endif
