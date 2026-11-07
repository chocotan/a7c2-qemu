/* SPDX-License-Identifier: MIT */
#include "pin-buffer-owner.h"
#include "pin-buffer-wire.h"
#include <string.h>
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int n){p[0]=(unsigned char)n;p[1]=(unsigned char)(n>>8);}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static void put64(unsigned char *p,unsigned long long n){for(unsigned int i=0;i<8;i++)p[i]=(unsigned char)(n>>(8*i));}
int pin_control_dmm_message(unsigned int destination,unsigned int source,unsigned char *packet,unsigned int bytes,int enabled){
    if(enabled!=1 || destination!=PIN_CONTROL_DMM_SID)return 0;
    if(!packet || bytes!=PIN_CONTROL_MESSAGE_BYTES)return -1;
    unsigned int command=u16(packet),token=u16(packet+0x14),option=u16(packet+0x16);
    struct pin_control_lease lease={0};unsigned int handle=0;
    if(command==0x20 && option==1 && source==PIN_CONTROL_CLIENT_SID){
        if(u32(packet+4)!=PIN_CONTROL_UNIT || pin_control_allocate(PIN_CONTROL_UNIT,&lease))return -1;
        handle=lease.handle;
    }else if(command==0x21 && option==0 && source==PIN_CONTROL_CLIENT_SID){
        handle=u32(packet+8);
        if(u32(packet+4)!=PIN_CONTROL_UNIT || pin_control_share(handle,PIN_CONTROL_UNIT))return -1;
    }else if(command==0x24 && option==0 && source==PIN_CONTROL_CONSUMER_SID){
        handle=u32(packet+8);
        /* Original cmd24 looks up the handle, not the uninitialized unit@4.
         * Its producer sets wait@c=0 for this synchronous finite path. */
        if(u32(packet+0xc) || pin_control_open_consumer(handle,PIN_CONTROL_UNIT,&lease))return -1;
    }else if(command==0x25 && source==PIN_CONTROL_CONSUMER_SID){
        handle=u32(packet+8);
        /* This producer only initializes token@14, not option@16. The
         * original close wrapper does not inspect option. */
        if(pin_control_close_consumer(handle))return -1;
    }else if(command==0x23 && option==2 && (source==PIN_CONTROL_CLIENT_SID || source==PIN_CONTROL_CONSUMER_SID)){
        handle=u32(packet+8);
        if(source==PIN_CONTROL_CLIENT_SID?pin_control_release(handle):pin_control_release_consumer(handle))return -1;
    }else return -1;
    memset(packet,0,bytes);put16(packet,command|0x8000);put16(packet+6,token);put32(packet+0xc,handle);
    if(command==0x20 || command==0x21)put32(packet+0x10,PIN_CONTROL_UNIT);
    if(command==0x20 || command==0x24){
        put16(packet+8,1);
        put64(packet+0x18,lease.physical);put32(packet+0x20,lease.bytes);
    }
    return 1;
}
