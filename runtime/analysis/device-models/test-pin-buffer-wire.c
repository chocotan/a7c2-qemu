/* SPDX-License-Identifier: MIT */
#include "pin-buffer-owner.h"
#include "pin-buffer-wire.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static void put16(unsigned char *p,unsigned int n){p[0]=(unsigned char)n;p[1]=(unsigned char)(n>>8);}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static unsigned char memory[PIN_CONTROL_CAPACITY];
static void request(unsigned char *p,unsigned int command,unsigned int option){
    memset(p,0xa5,PIN_CONTROL_MESSAGE_BYTES);put16(p,command);put32(p+4,PIN_CONTROL_UNIT);put32(p+0xc,0xffffffff);
    put16(p+0x14,0);put16(p+0x16,option);
}
int main(void){
    pin_control_test_reset();memset(memory,0,sizeof memory);
    unsigned char packet[PIN_CONTROL_MESSAGE_BYTES],copy[PIN_CONTROL_MESSAGE_BYTES];request(packet,0x20,1);memcpy(copy,packet,sizeof copy);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1)==-1 && !memcmp(packet,copy,sizeof copy));
    assert(!pin_control_bind_reserved(memory,sizeof memory,PIN_CONTROL_PHYSICAL));
    assert(!pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,0) && !memcmp(packet,copy,sizeof copy));
    assert(!pin_control_dmm_message(PIN_CONTROL_DMM_SID+1,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1));
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID+1,packet,sizeof packet,1)==-1);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet-1,1)==-1);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1)==1);
    unsigned int handle=u32(packet+0xc);assert(handle==0x8000 && u16(packet)==0x8020 && !u16(packet+2) && !u16(packet+6));
    assert(u16(packet+8)==1 && !u16(packet+0xa) && u32(packet+0x10)==0x404 && u32(packet+0x18)==0 && u32(packet+0x1c)==5 && u32(packet+0x20)==512);
    for(unsigned int i=0x24;i<sizeof packet;i++)assert(!packet[i]);
    assert(!pin_control_write_ssyn(handle,0));static const unsigned char header[32]={0x53,0x53,0x59,0x4e,0,0,0,1};
    assert(!memcmp(memory,header,sizeof header));
    request(packet,0x23,2);put32(packet+8,handle);memcpy(copy,packet,sizeof copy);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1)==1);
    assert(u16(packet)==0x8023 && !u16(packet+2) && !u16(packet+6) && !u16(packet+8) && !u16(packet+0xa) && u32(packet+0xc)==handle);
    for(unsigned int i=0x10;i<sizeof packet;i++)assert(!packet[i]);
    assert(!memcmp(memory,header,sizeof header));
    memcpy(packet,copy,sizeof packet);assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1)==-1 && !memcmp(packet,copy,sizeof copy));
    puts("VIRTUAL_CP_DMM_98H_ALLOC_DESCRIPTOR_ACTUAL_HEADER_AND_FREE_REPLY_PASS");
    for(unsigned int option=0;option<5;option++)if(option!=1){
        request(packet,0x20,option);memcpy(copy,packet,sizeof copy);
        assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1)==-1 && !memcmp(packet,copy,sizeof copy));
    }
    request(packet,0x20,1);put32(packet+4,0x405);memcpy(copy,packet,sizeof copy);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1)==-1 && !memcmp(packet,copy,sizeof copy));
    puts("VIRTUAL_CP_DMM_FINITE_SUBSET_REFUSAL_PRESERVES_CALLER_MESSAGE_PASS");
    request(packet,0x20,1);assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1)==1);handle=u32(packet+0xc);
    assert(!pin_control_write_ssyn(handle,0));
    request(packet,0x21,0);put32(packet+8,handle);memcpy(copy,packet,sizeof copy);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CONSUMER_SID,packet,sizeof packet,1)==-1 && !memcmp(packet,copy,sizeof copy));
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1)==1);
    assert(u16(packet)==0x8021 && u32(packet+0xc)==handle && u32(packet+0x10)==PIN_CONTROL_UNIT && !u16(packet+8));
    request(packet,0x23,2);put32(packet+8,handle);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1)==1);
    struct pin_control_references refs;assert(!pin_control_references(handle,&refs) && refs.owners==1 && !refs.opens);
    request(packet,0x24,0);put32(packet+8,handle);put32(packet+4,0xdeadbeef);put32(packet+0xc,0);memcpy(copy,packet,sizeof copy);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,packet,sizeof packet,1)==-1 && !memcmp(packet,copy,sizeof copy));
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CONSUMER_SID,packet,sizeof packet,1)==1);
    assert(u16(packet)==0x8024 && u32(packet+0xc)==handle && u16(packet+8)==1 && !u32(packet+0x10) && u32(packet+0x20)==512);
    assert(!pin_control_references(handle,&refs) && refs.owners==1 && refs.opens==1);
    request(packet,0x25,0xffff);put32(packet+8,handle);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CONSUMER_SID,packet,sizeof packet,1)==1);
    assert(u16(packet)==0x8025 && u32(packet+0xc)==handle && !u16(packet+8) && !u32(packet+0x10));
    assert(!pin_control_references(handle,&refs) && refs.owners==1 && !refs.opens);
    request(packet,0x24,0);put32(packet+8,handle);put32(packet+0xc,0);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CONSUMER_SID,packet,sizeof packet,1)==1);
    request(packet,0x23,2);put32(packet+8,handle);
    assert(pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CONSUMER_SID,packet,sizeof packet,1)==1);
    struct pin_control_snapshot pool;pin_control_snapshot(&pool);assert(!pool.live && pool.shares==1 && pool.consumer_opens==2 && pool.consumer_closes==2 && pool.consumer_releases==1);
    puts("VIRTUAL_CP_DMM_21_SHARE_24_OPEN_25_CLOSE_23_ROLE_RELEASE_ACTUAL_BACKING_PASS");return 0;
}
