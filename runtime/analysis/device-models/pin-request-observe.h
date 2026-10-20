/* SPDX-License-Identifier: MIT */
#ifndef FULL_PIN_REQUEST_OBSERVE_H
#define FULL_PIN_REQUEST_OBSERVE_H
/* Read-only capture selector. Unknown services are never intercepted. Only
 * exact Dataflow Get/RequestConnect envelopes expand the known-SID log set. */
static inline unsigned int pin_observe_u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static inline unsigned int pin_observe_u32(const unsigned char *p){return pin_observe_u16(p)|pin_observe_u16(p+2)<<16;}
static inline int full_pin_request_visible(unsigned int id,const void *message,unsigned int bytes){
    if(!message)return 0;
    if(id==0x905a0048u || id==0x90590818u || (id&0x7fffu)==0x464u)return 1;
    if(bytes!=48 && bytes!=64)return 0;
    const unsigned char *p=message;
    return pin_observe_u32(p+4)==0xa0a0a0a0 && pin_observe_u16(p+8)==1 && pin_observe_u16(p+10)==bytes &&
        pin_observe_u32(p+12)==24 && pin_observe_u32(p+16)==bytes && pin_observe_u16(p+24)==0x1000 &&
        pin_observe_u16(p+26)==(bytes==48?0:1) && pin_observe_u16(p+28)==bytes-24 && pin_observe_u16(p+30)==2;
}
#endif
