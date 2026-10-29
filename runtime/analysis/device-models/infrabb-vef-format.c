/* SPDX-License-Identifier: MIT */
#include "infrabb-vef-format.h"
#include "pin-format.h"
#include <string.h>
_Static_assert(sizeof(unsigned int)==4,"Sony field widths");
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static unsigned long long hash(const unsigned char *p,unsigned int n){
    unsigned long long h=0xcbf29ce484222325ULL;for(unsigned int i=0;i<n;i++)h=(h^p[i])*0x100000001b3ULL;return h;
}
int full_infrabb_vef_format_init(struct full_infrabb_vef_format *f){
    if(!f || f->initialized)return -1;
    /* raw5f8488..a0: pin1/ordinal0/code1/component0/flags0/1920/1080. */
    static const unsigned char current[20]={1,0,0,0,0,0,0,0,1,0,0,0,0x80,7,0,0,0x38,4,0,0};
    /* Initial virtual BB table projection, rawfe79ac; not live CP RAM. */
    static const unsigned char expected[16]={1,0,0,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
    *f=(struct full_infrabb_vef_format){.initialized=1,.current_known_bytes=20,.expected_known_bytes=16};
    memcpy(f->current,current,sizeof current);memcpy(f->expected,expected,sizeof expected);
    f->current_fnv=hash(f->current,sizeof f->current);return 0;
}
int full_infrabb_vef_format_internal(const struct full_infrabb_vef_format *f,unsigned char *out,unsigned int n){
    if(!f || f->initialized!=1 || f->current_known_bytes!=20 || f->prepares || !out || n!=36)return -1;
    memset(out,0,n);put32(out+8,0xf0082002);put32(out+12,0x0001001c);memcpy(out+16,f->current,20);return 0;
}
int full_infrabb_vef_format_prepare(struct full_infrabb_vef_format *f,const unsigned char *in,unsigned int n){
    if(!f || f->initialized!=1 || f->current_known_bytes!=20 || f->prepares || !in || n!=36 ||
       u32(in) || u32(in+4) || u32(in+8)!=0xf0082002 || u32(in+12)!=0x0001001c || memcmp(in+16,f->current,20))return -1;
    memcpy(f->command_current,in+16,20);f->command_fnv=hash(f->command_current,20);
    if(f->command_fnv!=f->current_fnv || memcmp(f->command_current,f->current,20))return -1;
    f->command_state=0;f->prepares=1;return 0;
}
int full_infrabb_vef_format_execute(struct full_infrabb_vef_format *f,unsigned int pin_state,unsigned char *out,unsigned int n){
    if(!f || f->initialized!=1 || f->prepares!=1 || f->executions || f->command_state || pin_state || !out || n!=80 ||
       memcmp(f->command_current,f->current,20) || u32(f->command_current)!=1 || u32(f->command_current+4))return -1;
    memset(out,0,n);put32(out,0x4e595353);put32(out+4,0x02000000);put32(out+12,1);put32(out+16,0x20);
    put32(out+0x20,0x59525445);put32(out+0x2c,0x40);put32(out+0x30,16);
    memcpy(out+0x40,f->command_current+8,4);memcpy(out+0x48,f->command_current+12,8);
    f->executions=1;return 0;
}
int full_infrabb_vef_format_consume(struct full_infrabb_vef_format *f,const unsigned char *p,unsigned int n){
    if(!f || f->initialized!=1 || f->expected_known_bytes!=16 || f->executions!=1 || f->matches || f->mismatches || !p || n!=80)return -1;
    /* shortcut: canonical SSYN02/key0 only; expand after auditing a new producer. */
    if(u32(p)!=0x4e595353 || u32(p+4)!=0x02000000 || u32(p+8) || u32(p+12)!=1 || u32(p+16)!=0x20 ||
       u32(p+20) || u32(p+24) || u32(p+28) || u32(p+32)!=0x59525445 || u32(p+36) || u32(p+40) ||
       u32(p+44)!=0x40 || u32(p+48)!=16 || u32(p+52) || u32(p+56) || u32(p+60))return -1;
    f->payload_fnv=hash(p+64,16);
    if(p[64]!=f->expected[0] || p[65]!=f->expected[1] || u16(p+66)!=u16(f->expected+2) ||
       u32(p+72)!=u32(f->expected+8) || u32(p+76)!=u32(f->expected+12)){f->mismatches=1;return -1;}
    f->matches=1;return 0;
}
static int forward_payload(const struct full_infrabb_vef_format *f,const unsigned char *p,unsigned int n,struct pin_yc_payload *decoded){
    return !f || f->initialized!=1 || f->current_known_bytes!=20 || f->expected_known_bytes!=16 ||
        f->prepares!=1 || f->executions!=1 || f->matches!=1 || f->mismatches || f->command_state ||
        u32(f->current)!=1 || u32(f->current+4) || n!=80 || pin_yc_decode(p,n,decoded)?-1:0;
}
int full_infrabb_vef_format_accept_forwarded_vef(struct full_infrabb_vef_format *f,const unsigned char *p,unsigned int n){
    struct pin_yc_payload decoded;
    if(forward_payload(f,p,n,&decoded) || f->forwarded_vef_payload_fnv || f->forwarded_bb_payload_fnv)return -1;
    memcpy(f->current+8,p+64,4);memcpy(f->current+12,p+72,8);
    f->current_fnv=hash(f->current,sizeof f->current);f->forwarded_vef_payload_fnv=hash(p+64,16);return 0;
}
int full_infrabb_vef_format_accept_forwarded_bb(struct full_infrabb_vef_format *f,const unsigned char *p,unsigned int n,int *changed){
    if(!changed)return -1;
    *changed=0;struct pin_yc_payload decoded;
    if(forward_payload(f,p,n,&decoded) || !f->forwarded_vef_payload_fnv || f->forwarded_bb_payload_fnv ||
       f->forwarded_vef_payload_fnv!=hash(p+64,16) || memcmp(f->current+8,p+64,4) || memcmp(f->current+12,p+72,8))return -1;
    *changed=p[64]!=f->expected[0] || p[65]!=f->expected[1] || u16(p+66)!=u16(f->expected+2) ||
        u32(p+72)!=u32(f->expected+8) || u32(p+76)!=u32(f->expected+12);
    if(*changed)memcpy(f->expected,p+64,sizeof f->expected);
    f->forwarded_bb_payload_fnv=hash(p+64,16);return 0;
}

