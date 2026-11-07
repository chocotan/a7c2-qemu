/* SPDX-License-Identifier: MIT */
#define MCMN_QUERY_TEST
#include "mcmn-query.c"
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
static unsigned int allocated_bytes,live,requests,replies,queue_frees;
static unsigned int mode,last_command;
static void *pending;
int osal_dynamic_id(unsigned int op,unsigned int owner,unsigned long value){
    if(op==0x2a){assert(owner==0xd5);*(unsigned int *)value=0x80d561ef;return 0;}
    assert(op==0x4a && !owner && value==0x80d561ef);queue_frees++;return 0;
}
int osal_valloc_msg_wait(unsigned int sid,void **p,unsigned int bytes,int wait){
    assert(sid==MCMN_SID && wait==1 && !live);
    allocated_bytes=bytes;*p=malloc(bytes);assert(*p);live=1;return 0;
}
int osal_free_msg(unsigned int sid,void *p){
    assert((sid==MCMN_SID || sid==0x80d561ef) && live && p);free(p);live=0;
    if(sid==0x80d561ef)replies++;
    return 0;
}
int osal_snd_msg(unsigned int sid,void *message){
    assert(sid==MCMN_SID && live && !pending);
    unsigned char *p=message;last_command=u32(p);
    assert(u16(p+4)==1 && u32(p+8)==0x80d561ef && !u32(p+12));
    assert(!u32(p+16) && !u32(p+20));
    if(last_command==9){
        assert(allocated_bytes==136 && u16(p+6)==112);
        for(unsigned int i=24;i<136;i++)assert(!p[i]);
    }else{
        assert(last_command==2 && allocated_bytes==32 && u16(p+6)==8);
        assert(u32(p+24)>=0x101 && u32(p+24)<=0x103 && !u32(p+28));
    }
    requests++;
    if(mode==1)return -55; /* rejected send: caller must free */
    if(mode==2){assert(!osal_free_msg(sid,p));return 0;} /* real receiver consumes, no response */
    pending=malloc(allocated_bytes);assert(pending);memcpy(pending,message,allocated_bytes);
    assert(!osal_free_msg(sid,p));live=1;
    p=pending;
    if(last_command==9){
        for(unsigned int i=0;i<3;i++){put32(p+24+4+i*36+8,i==1?2:0);put32(p+24+4+i*36+16,0x20+i);}
    }else if(mode==4)put32(p+12,0x80000002); /* valid query: absent entry, not a card */
    else put32(p+28,3);
    if(mode==3)put16(p+6,0x2222);
    return 0;
}
int osal_rcv_msg_tmo(unsigned int q,void **p,long timeout){
    assert(q==0x80d561ef && timeout==5000);
    *p=pending;pending=0;return mode==2?-1022:0;
}
unsigned int osal_msg_size(void *p){assert(p && live);return allocated_bytes;}
unsigned int osal_get_msg_src(void *p){assert(p && live);return MCMN_SID;}
static void reset(unsigned int m){assert(!live && !pending);mode=m;requests=replies=queue_frees=0;}
int main(void){
    char *argv[]={"mcmn-query",0};
    reset(0);assert(!run(1,argv));assert(requests==4 && replies==4 && queue_frees==1 && !live);
    reset(1);assert(run(1,argv)==4 && requests==1 && !replies && queue_frees==1 && !live);
    reset(2);assert(run(1,argv)==5 && requests==1 && !replies && queue_frees==1 && !live);
    reset(3);assert(run(1,argv)==7 && requests==1 && replies==1 && queue_frees==1 && !live);
    reset(4);assert(!run(1,argv));assert(requests==4 && replies==4 && !live);
    puts("MCMN_QUERY_HOST_WIRE_AND_OWNERSHIP_PASS no_guest_evidence=1");return 0;
}
