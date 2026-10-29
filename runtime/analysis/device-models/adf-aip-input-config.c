/* SPDX-License-Identifier: MIT */
#include "adf-aip-input-config.h"
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef char aip_requires_u32[(UINT_MAX == 0xffffffffU && CHAR_BIT == 8) ? 1 : -1];
#define FNV_START 0xcbf29ce484222325ULL

/* F5 CP SHA256 f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428.
 * ROM e900c4/e8ff2c/e9002c/e90050/f28fd4/fd35c5/fd35d7/51c488/f2906e. */
static const unsigned int merge_rows[9][6] = {
    {0xff,8,0x54,0x44,4,1}, {1,1,0x58,0x45,30,2}, {0xff,8,0x5c,0x49,4,2},
    {0xff,8,0x60,0x49,4,0}, {0xff,8,0x64,0x49,4,0}, {0xff,8,0x68,0x49,4,0},
    {0xff,8,0x6c,0x49,4,0}, {0xf,4,0x70,0x4c,8,1}, {1,1,0x74,0x4d,32,2}
};
static const unsigned int gate_masks[8] = {
    0xf,0xf0,0xf00,0xf000,0x10000,0x20000,0x40000,0x80000
};
static const unsigned int filter9_register_offsets[9] = {
    0x1d4,0x224,0x1f4,0x1f8,0x1fc,0x200,0x20c,0x210,0x21c
};
static const unsigned int filter11_register_offsets[11] = {
    0x1d8,0x1dc,0x1e0,0x1e4,0x1e8,0x1ec,0x1f0,0x204,0x208,0x214,0x218
};
static const unsigned int filter9_offsets[4] = {0xb0,0xb9,0xc2,0xcb};
static const unsigned int filter9_shifts[9] = {19,0,19,0,19,0,20,0,20};
static const unsigned int filter11_shifts[11] = {16,9,3,0,0,14,11,6,3,3,3};
static const unsigned int selector_offsets[6] = {0xd4,0xe0,0xf0,0xf3,0,0xe};
static const unsigned int route_table3[24] = {
    0x7f,0,0,0,0,0x7f,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
};
static const unsigned int side_tone[6] = {0x80,0x80,0x80,0,0,0};
/* ROM 1116fd0 after the original selector2 type0/ch2/sample0/depth0 conversion. */
static const unsigned int input02[9] = {
    0x08080100,0x20011ff7,0x14141414,0x14090814,0x15141414,
    0x15141416,0x14141416,0,0x43211121
};
static unsigned long long hash_bytes(unsigned long long hash,const void *data,unsigned long size)
{
    const unsigned char *bytes=data;
    for (unsigned long i=0;i<size;i++) hash=(hash^bytes[i])*0x100000001b3ULL;
    return hash;
}
static unsigned long long hash_u32(unsigned long long hash,unsigned int value)
{
    for (unsigned int i=0;i<4;i++) { hash=(hash^(value&0xff))*0x100000001b3ULL;value>>=8; }
    return hash;
}
static unsigned long long seal(const struct full_adf_aip_input_config *s)
{
    return hash_bytes(FNV_START,s,offsetof(struct full_adf_aip_input_config,seal));
}
static int fault(struct full_adf_aip_input_config *s)
{
    if (s) { s->fault=1;s->seal=seal(s); }
    return -1021;
}
static int zero_storage(const void *data,unsigned long size)
{
    const unsigned char *bytes=data;
    for (unsigned long i=0;i<size;i++) if (bytes[i]) return 0;
    return 1;
}
static int overlaps(const void *a,unsigned long a_size,const void *b,unsigned long b_size)
{
    uintptr_t aa=(uintptr_t)a,bb=(uintptr_t)b;
    return aa<=bb ? bb-aa<a_size : aa-bb<b_size;
}
static int valid(const struct full_adf_aip_input_config *s,unsigned int stage)
{
    return s && s->identity==s && s->known==1 && !s->fault && !s->busy &&
        s->public_config && s->public_config==s->asset_identity && s->selector==2 &&
        s->capability_word8==1 && s->stage==stage && !s->source && !s->active &&
        !s->software14 && !s->software18 && s->seal==seal(s);
}
static int public_read(struct full_adf_aip_input_config *s,unsigned int offset,
                       unsigned int mask,unsigned int *value)
{
    if (full_adf_public_config_aip_read(s->public_config,offset,mask,value)) return -1021;
    s->public_reads++;
    s->public_read_hash=hash_u32(s->public_read_hash,offset);
    s->public_read_hash=hash_u32(s->public_read_hash,mask);
    s->public_read_hash=hash_u32(s->public_read_hash,*value);
    return 0;
}
static unsigned int register_read(struct full_adf_aip_input_config *s,unsigned int offset)
{
    const volatile unsigned int *reg=&s->registers[offset/4];
    unsigned int value=*reg;
    s->register_reads++;
    s->register_read_hash=hash_u32(s->register_read_hash,FULL_ADF_AIP_INPUT_CONFIG_BASE+offset);
    s->register_read_hash=hash_u32(s->register_read_hash,value);
    return value;
}
static int write_register(struct full_adf_aip_input_config *s,unsigned int offset,unsigned int value)
{
    if ((offset&3) || offset/4>=FULL_ADF_AIP_INPUT_CONFIG_REGISTERS ||
        s->writes>=FULL_ADF_AIP_INPUT_CONFIG_TRACE) return -1021;
    volatile unsigned int *reg=&s->registers[offset/4];
    *reg=value;
    unsigned int at=s->writes++;
    s->trace[at].address=FULL_ADF_AIP_INPUT_CONFIG_BASE+offset;
    s->trace[at].value=value;
    s->write_hash=hash_u32(s->write_hash,s->trace[at].address);
    s->write_hash=hash_u32(s->write_hash,value);
    s->trace[at].readback=register_read(s,offset);
    if (s->trace[at].readback!=value) return -1021;
    s->readbacks++;
    return 0;
}
static unsigned int le32(const unsigned char *p)
{
    return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;
}
static int signed16(unsigned int value)
{
    return (value&0x8000) ? (int)(value&0xffff)-0x10000 : (int)(value&0xffff);
}
static int merge(struct full_adf_aip_input_config *s,const unsigned int raw[9])
{
    unsigned int bit=0,flags=0,count=0;
    for (unsigned int i=0;i<9;i++) {
        const unsigned int *row=merge_rows[i];
        unsigned int fallback;
        if (public_read(s,row[2],0xffffffffU,&fallback)) return -1021;
        /* 51bf0a..44: rows 3..6 intentionally inherit the bit cursor and flags. */
        if (i<3 || i>=7) {
            if (public_read(s,row[3],((0x106U>>i)&1) ? 0xffffffffU : 0xff,&flags)) return -1021;
            count=row[4];bit=1;
        }
        unsigned int mask=row[0],value=0;
        for (unsigned int j=0;j<count;j++) {
            value|=((flags&bit) ? fallback : raw[i])&mask;
            bit<<=1;mask<<=row[1];
        }
        s->cache[i]=value;
    }
    return 0;
}
static unsigned int classify(struct full_adf_aip_input_config *s,unsigned int offset)
{
    /* b63a6c: unsigned ranges and the two actual shared route-register reads. */
    unsigned int route=register_read(s,offset);
    if (route==20) return 3;
    if (route-14U<6) return 2;
    if ((route&~3U)==4 || route-21U<6) return 1;
    unsigned int source=register_read(s,0x360),input=register_read(s,0x60);
    if (route-8U<6 || source-8U<=5) return input==8 ? 3 : (input<4 ? 0 : 2);
    if (source<=20 && ((1U<<source)&0x0010000fU)) return 3;
    return source-14U<6 ? 2 : 1;
}
static int apply(struct full_adf_aip_input_config *s,const unsigned int raw[9])
{
    unsigned int value;
    if (merge(s,raw)) return -1021;
    /* shortcut: owned cold active0/cache7=0 only; coefficient and active work need new evidence. */
    if (s->active || s->cache[7]) return -1021;
#define WRITE(offset,data) do { if (write_register(s,(offset),(data))) return -1021; } while (0)
#define READ(offset,mask) do { if (public_read(s,(offset),(mask),&value)) return -1021; } while (0)
    unsigned int w1=s->cache[1],w8=s->cache[8];
    for (unsigned int i=0;i<4;i++) WRITE(0x60+4*i,(s->cache[0]>>(8*i))&0xff);
    WRITE(0x70,(w1>>2)&1);WRITE(0x74,(w1>>1)&1);WRITE(0x78,w1&1);
    WRITE(0x94,(~(w1>>3))&1);
    if (w1&1) { WRITE(0x98,0x80);WRITE(0x9c,0); }
    unsigned int gates=register_read(s,0x100);
    for (unsigned int i=0;i<8;i++) {
        if (!(w1&(0x10U<<i)) && ((s->cache[7]>>(4*i))&0xf)) return -1021;
        gates|=gate_masks[i];
    }
    WRITE(0x100,gates);
    unsigned int enabled=0;
    for (unsigned int i=0;i<4;i++) {
        unsigned int select=(w1>>(12+4*i))&0xf;
        if (!select) continue;
        enabled|=1U<<i;
        unsigned int control=0x300;
        if (select!=1) { READ(0xaa+select,0xff);control=((value&0x1f)|((value&0xe0)<<1))<<3|0x100; }
        WRITE(0x1c4+4*i,control);
    }
    WRITE(0x1c0,enabled);
    unsigned int select=(w8>>4)&7;
    if (select>=sizeof filter9_offsets/sizeof *filter9_offsets) return -1021;
    for (unsigned int i=0;i<9;i++) {
        READ(filter9_offsets[select]+i,0xff);
        unsigned int coefficient=value<<filter9_shifts[i];
        if ((0x55U>>i)&1) coefficient=0U-coefficient;
        WRITE(filter9_register_offsets[i],coefficient);
    }
    WRITE(0x220,0);
    select=selector_offsets[w8&1];
    for (unsigned int i=0;i<11;i++) { READ(select+i,0xff);WRITE(filter11_register_offsets[i],value<<filter11_shifts[i]); }
    WRITE(0x240,(w1>>29)&1);
    if (!(w8&0x1000)) { READ(0xed,0xff); } else value=0;
    WRITE(0x248,value);
    for (unsigned int i=0;i<3;i++) {
        if (!(w8&0x100)) { READ(0xf9+i,0xff); } else value=0;
        WRITE(0x258+12*i,value);
    }
    select=selector_offsets[2+((w8>>8)&1)];
    for (unsigned int i=0;i<3;i++) { READ(select+i,0xff);WRITE(0x250+12*i,value); }
    select=2*((w8>>20)&3);
    READ(0xfc+select,0xffff);
    int low=signed16(value);
    if (low<=1) low=1;
    READ(0x17c+select,0xffff);
    int high=signed16(value)+low;
    if (high>0x7fff) high=0x7fff;
    if (high<1) high=1;
    WRITE(0x27c,(unsigned int)high|((unsigned int)low<<16));
    select=selector_offsets[4+((w8>>16)&1)];
    READ(0x104+select,0xff);WRITE(0x274,value);
    READ(0x105+select,0xff);WRITE(0x278,value);
    READ(0x106+select,0xffff);WRITE(0x280,(unsigned int)signed16(value));
    for (unsigned int i=0;i<4;i++) { READ(0x108+select+2*i,0xffff);WRITE(0x284+4*i,value); }
    READ(0x110+select,0xffff);WRITE(0x294,(unsigned int)signed16(value));
    READ(0x120,0xff);WRITE(0x298,value);
    READ(0x121,1);WRITE(0x29c,value);
    if (w1&1) { READ(0x121,2);value>>=1; } else value=0;
    WRITE(0x2a0,value);
    WRITE(0x2c0,(w1>>28)&1);
    for (unsigned int i=0;i<6;i++) WRITE(0x2c4+4*i,side_tone[i]);
    select=(w8>>24)&7;
    if (select!=0 && select!=3) return -1021;
    for (unsigned int i=0;i<24;i++) {
        if (select==0) { READ(0x124+i,0xff); } else value=route_table3[i];
        /* In S0, software14/software18 are explicit virtual-reset zeros. */
        WRITE(0x2dc+4*i,value);
    }
    for (unsigned int i=0;i<5;i++)
        for (unsigned int j=0;j<4;j++) WRITE(0x360+16*i+4*j,(s->cache[2+i]>>(8*j))&0xff);
    unsigned int all_disabled=1;
    for (unsigned int i=0;i<4;i++) if (register_read(s,0x60+4*i)!=8) { all_disabled=0;break; }
    if (all_disabled) return -1021;
    READ(0x40,0xff);s->flag3c=value || (w8&0x70)>0x10;
    WRITE(0,0);WRITE(4,0x83);
    unsigned int kind=classify(s,0x374);WRITE(8,kind);
    kind=classify(s,0x38c);WRITE(0xc,kind);
    READ(0x188,0xff);WRITE(0x18,value);
    if (!(w8&0x10000000)) { WRITE(0x10,3);WRITE(0x14,0); }
    else {
        unsigned int route=register_read(s,0x60),mode=value,result=0;
        if (mode && (route>3 || mode>=7)) {
            result=mode<7 ? 2 : 3;
            if (route>=5) result=3;
            if (mode==7) result=2;
        }
        WRITE(0x10,result);WRITE(0x14,mode<2 ? 0 : (mode==2 ? 3 : 0x83));
    }
#undef READ
#undef WRITE
    return 0;
}
int full_adf_aip_input_config_init(struct full_adf_aip_input_config *s,
                                 struct full_adf_public_config *config,unsigned int cap8,
                                 const unsigned int reset[FULL_ADF_AIP_INPUT_CONFIG_REGISTERS])
{
    if (!s || !config || !reset || cap8!=1 || !zero_storage(s,sizeof *s) ||
        overlaps(s,sizeof *s,config,sizeof *config) || overlaps(s,sizeof *s,reset,sizeof s->registers)) return -1021;
    unsigned int selector_key;
    if (full_adf_public_config_read(config,0x690227,&selector_key) || selector_key) return -1021;
    s->identity=s;s->known=1;s->public_config=config;s->asset_identity=config;
    s->source=0;s->active=0;s->software14=0;s->software18=0;s->flag3c=0;
    s->capability_word8=cap8;s->selector=selector_key ? 0 : cap8+1;
    s->public_read_hash=FNV_START;s->register_read_hash=FNV_START;s->write_hash=FNV_START;
    memcpy(s->registers,reset,sizeof s->registers);
    s->seal=seal(s);
    return 0;
}
int full_adf_aip_input_config_make02(struct full_adf_aip_input_config *s,void *out,unsigned long bytes)
{
    if (!valid(s,0) || !out || bytes!=FULL_ADF_AIP_INPUT_CONFIG_BYTES ||
        overlaps(out,bytes,s,sizeof *s) || overlaps(out,bytes,s->public_config,sizeof *s->public_config)) return fault(s);
    unsigned int key;
    if (full_adf_public_config_read(s->public_config,0x690227,&key) || key) return fault(s);
    unsigned char *p=out;
    for (unsigned int i=0;i<11;i++) {
        unsigned int word=i==0 ? 2 : (i==1 ? FULL_ADF_AIP_INPUT_CONFIG_BYTES : input02[i-2]);
        for (unsigned int j=0;j<4;j++) p[4*i+j]=(unsigned char)(word>>(8*j));
    }
    s->builds=1;s->stage=1;s->seal=seal(s);
    return 0;
}
int full_adf_aip_input_config_consume03(struct full_adf_aip_input_config *s,unsigned int source)
{
    if (!valid(s,1) || source || s->builds!=1 || s->applies03 || s->applies02 ||
        !zero_storage(s->cache,sizeof s->cache)) return fault(s);
    unsigned int cached[9];memcpy(cached,s->cache,sizeof cached);
    s->busy=1;s->source=source;
    if (apply(s,cached)) return fault(s);
    s->applies03=1;s->stage=2;s->busy=0;s->seal=seal(s);
    return 0;
}
int full_adf_aip_input_config_consume02(struct full_adf_aip_input_config *s,
                                      const void *raw,unsigned long bytes)
{
    if (!valid(s,2) || !raw || bytes!=FULL_ADF_AIP_INPUT_CONFIG_BYTES ||
        s->builds!=1 || s->applies03!=1 || s->applies02) return fault(s);
    const unsigned char *p=raw;
    if (le32(p)!=2 || le32(p+4)!=FULL_ADF_AIP_INPUT_CONFIG_BYTES) return fault(s);
    unsigned int words[9];
    for (unsigned int i=0;i<9;i++) { words[i]=le32(p+8+4*i);if (words[i]!=input02[i]) return fault(s); }
    s->busy=1;
    if (apply(s,words)) return fault(s);
    s->applies02=1;s->stage=3;s->busy=0;s->seal=seal(s);
    return 0;
}
