/* SPDX-License-Identifier: MIT */
#include "vef-bb-format.h"
#include <string.h>
static unsigned int u32(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;}
static void put(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
int vef_bb_format_build(const unsigned char *record,unsigned int size,unsigned char *out,unsigned int capacity){
    if(!record || size!=20 || !out || capacity<VEF_BB_CONTROL_BYTES)return -1;
    unsigned char bytes[VEF_BB_CONTROL_BYTES]={0};
    put(bytes,0x4e595353);put(bytes+4,0x02000000);put(bytes+12,1);put(bytes+16,32);
    put(bytes+32,0x59525445);put(bytes+44,64);put(bytes+48,16);
    /* 10de24/26/2c load format bytes at record+8/+9/+a; record+0
     * is the pin index later passed to MsgAccessor+70, not the format code. */
    memcpy(bytes+64,record+8,4);memcpy(bytes+72,record+12,8);
    memcpy(out,bytes,sizeof bytes);return 0;
}
int vef_bb_format_decode(const unsigned char *p,unsigned int size,struct vef_bb_format *out){
    if(!p || !out || size<VEF_BB_CONTROL_BYTES)return -1;
    if(u32(p)!=0x4e595353 || u32(p+4)!=0x02000000 || u32(p+8) || u32(p+12)!=1 || u32(p+16)!=32 ||
       u32(p+20) || u32(p+24) || u32(p+28) || u32(p+32)!=0x59525445 || u32(p+36) || u32(p+40) ||
       u32(p+44)!=64 || u32(p+48)!=16 || u32(p+52) || u32(p+56) || u32(p+60) || u32(p+68))return -1;
    *out=(struct vef_bb_format){p[64],p[65],(unsigned short)(p[66]|(unsigned short)p[67]<<8),u32(p+72),u32(p+76)};
    return 0;
}
