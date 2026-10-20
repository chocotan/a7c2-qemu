/* SPDX-License-Identifier: MIT */
#include "pin-format.h"
#include <string.h>
_Static_assert(sizeof(unsigned int)==4 && sizeof(unsigned short)==2,"Sony field widths");
_Static_assert(sizeof(struct pin_yc_current_info)==20,"VEF currentinfo layout");
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int n){p[0]=(unsigned char)n;p[1]=(unsigned char)(n>>8);}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
int pin_yc_build(const struct pin_yc_parameters *values,unsigned char *out,unsigned int capacity){
    if(!values || !out || capacity<PIN_YC_FORMAT_BYTES)return -1;
    unsigned char packet[PIN_YC_FORMAT_BYTES]={0x53,0x53,0x59,0x4e,0,0,0,1};
    put32(packet+0xc,1);put32(packet+0x10,0x20);
    put32(packet+0x20,0x59525445);put32(packet+0x2c,0x40);put32(packet+0x30,0x10);
    packet[0x40]=values->code;packet[0x41]=values->component;
    put16(packet+0x42,(values->raw_flags&7)|((values->raw_flags>>3)&0x18));
    put32(packet+0x48,values->width);put32(packet+0x4c,values->height);
    memcpy(out,packet,sizeof packet);return 0;
}
int pin_yc_decode(const unsigned char *packet,unsigned int capacity,struct pin_yc_payload *out){
    if(!packet || !out || capacity<PIN_YC_FORMAT_BYTES)return -1;
    if(u32(packet)!=0x4e595353 || u32(packet+4)!=0x01000000 || u32(packet+8) ||
       u32(packet+0xc)!=1 || u32(packet+0x10)!=0x20 ||
       u32(packet+0x14) || u32(packet+0x18) || u32(packet+0x1c) ||
       u32(packet+0x20)!=0x59525445 || u32(packet+0x24) || u32(packet+0x28) ||
       u32(packet+0x2c)!=0x40 || u32(packet+0x30)!=0x10 || u32(packet+0x34) ||
       u32(packet+0x38) || u32(packet+0x3c) || u32(packet+0x44) || (u16(packet+0x42)&~0x1fu))return -1;
    *out=(struct pin_yc_payload){packet[0x40],packet[0x41],(unsigned short)u16(packet+0x42),u32(packet+0x48),u32(packet+0x4c)};
    return 0;
}
int pin_yc_store(const struct pin_yc_payload *values,struct pin_yc_current_info *current){
    if(!values || !current || values->encoded_flags&~0x1fu)return -1;
    current->code=values->code;current->component=values->component;current->encoded_flags=values->encoded_flags;
    current->width=values->width;current->height=values->height;return 0;
}
