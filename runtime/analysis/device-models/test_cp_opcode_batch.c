#define _GNU_SOURCE
#include "cp-background-device.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1); } } while (0)
/* Expected wire sizes/offsets are independently transcribed from original CP pins. */
struct contract { unsigned op, bytes, offset, width, dirty; };
static const struct contract contracts[]={
    {0x4001,12,0,0,0},{0x401c,12,0x2ec,4,1},{0x402a,12,0x160,4,0},
    {0x4043,8,0x2bd,1,1},{0x4051,12,0xd18,4,1},{0x4084,12,0x337,1,1},
    {0x409c,8,0xb52,1,1},{0x4003,8,0x7a6,1,1},{0x4022,32,0x6c8,4,0},{0x4028,16,0x2d8,4,0},{0x40af,12,0x164,4,1},{0x40b8,12,0x170,4,1},
    {0x40c5,12,0x3a4,4,1},{0x40d1,12,0xd14,4,1},{0x40ed,12,0xbb2,1,1},
    {0x40fb,12,0xaf0,4,1},{0x4102,12,0xbec,4,1},{0x4139,184,0x870,176,0},
    {0x4177,12,0x1c4,4,1},{0x40ee,12,0x180,4,1},{0x4083,12,0xbd1,1,0},
    {0x4048,12,0,0,1},{0x4167,12,0xcfc,4,1},{0x414a,12,0x1a0,4,1},
    {0x400f,12,0,0,1},{0x4147,12,0x19c,4,1},{0x40d3,12,0xb24,4,1},
    {0x4151,24,0,0,1},{0x4080,12,0x1fc,4,1},{0x40a1,12,0x750,4,1},{0x40b6,12,0x780,4,1},{0x40b4,12,0x77c,4,1},{0x40a3,12,0x2a0,4,1},
    {0x4002,12,0x690,4,1}, {0x400a,12,0xb2c,4,0}, {0x400b,12,0xb30,4,0}, {0x400c,12,0xb34,4,0}, {0x400d,12,0xb38,4,0}, {0x4010,12,0x2a8,4,1}, {0x4012,12,0xcb8,4,0}, {0x4013,12,0xcbc,4,0}, {0x4017,12,0xcf8,4,1}, {0x401e,12,0x568,4,1}, {0x402f,12,0x964,4,0}, {0x403a,12,0x2c8,4,1}, {0x4044,12,0x974,4,0}, {0x4049,12,0xcc4,4,0}, {0x404f,12,0x336,1,1}, {0x405a,12,0x2d4,1,1}, {0x405b,12,0x2e8,1,1}, {0x4061,12,0x33c,4,1}, {0x4064,12,0x700,4,1}, {0x406e,12,0x590,4,1}, {0x4079,12,0x354,4,1}, {0x407b,12,0x9b8,4,1}, {0x407d,12,0xb48,4,1}, {0x4088,12,0x1b0,4,1}, {0x40a4,12,0x364,4,1}, {0x40a9,12,0x368,4,1}, {0x40b3,12,0x754,4,1}, {0x40b7,12,0x16c,4,1}, {0x40c3,12,0xb53,1,1}, {0x40c4,12,0x3a0,4,1}, {0x40c7,12,0x788,4,1}, {0x40ce,12,0x384,4,1}, {0x40d4,12,0x168,4,1}, {0x40dc,12,0x3c4,4,1}, {0x40e4,12,0x1b4,4,1}, {0x40e6,12,0x3d4,4,1}, {0x40f1,12,0xa04,4,1}, {0x40fc,12,0xaf4,4,1}, {0x40fd,12,0xbe8,4,1}, {0x40fe,12,0x198,4,1}, {0x4100,12,0x7b4,4,1}, {0x4101,12,0x3d8,4,1}, {0x4105,12,0x7b8,4,1}, {0x4137,12,0xcec,4,1}, {0x4138,12,0x558,1,1}, {0x413a,12,0x36c,4,1}, {0x413d,12,0x58,4,1}, {0x413e,12,0x5b4,4,1}, {0x4141,12,0xfc,4,0}, {0x4142,12,0x300,4,1}, {0x4145,12,0x3dc,4,1}, {0x4146,12,0x3e0,4,1}, {0x414c,12,0x7c0,4,1}, {0x414f,12,0x174,4,1}, {0x415c,8,0x404,4,1}, {0x4161,12,0x409,1,1}, {0x4163,12,0xb0c,4,1}, {0x4166,12,0xd4,4,1}, {0x4169,12,0x414,4,1}, {0x416a,12,0x3ac,4,1}, {0x416c,12,0xba0,4,1}
};
#define CONTRACT_COUNT (sizeof contracts/sizeof contracts[0])
struct message { unsigned bytes,source; unsigned char wire[185]; };
static _Atomic unsigned active,releases,records;
static int fail_free,reenter;
static const struct contract *current;
static unsigned bytes(void *p) { return ((struct message *)((char *)p-8))->bytes; }
static unsigned source(void *p) { return ((struct message *)((char *)p-8))->source; }
static void *make(const struct contract *c,unsigned v) {
    struct message *m=malloc(sizeof *m);CHECK(m);
    memset(m,0xa5,sizeof *m);m->bytes=c->bytes;m->source=0x80020002;
    m->wire[0]=5;m->wire[2]=(unsigned char)c->op;m->wire[3]=(unsigned char)(c->op>>8);
    for(unsigned i=8;i<c->bytes;i++)m->wire[i]=(unsigned char)(v+i-8);
    atomic_fetch_add(&active,1);return m->wire;
}
static int dispatch(void *,const struct full_imaging_io *);
static int release(unsigned id,void *p);
static void record(const char *tag,const char *line) {
    if(!strcmp(tag,"NATIVE_CP_BACKGROUND_PARAMETER_ACCEPT ")) {
        CHECK(strstr(line,"apply_completed=0") && strstr(line,"completion=0 original_CP=0 capture_verified=0"));
        atomic_fetch_add(&records,1);
    }
}
static const struct full_imaging_io io={.size=bytes,.source=source,.release=release,.record=record};
static int release(unsigned id,void *p) {
    CHECK(id==NATIVE_CP_BACKGROUND_SID && p);
    if(fail_free)return -17;
    if(reenter) {
        reenter=0;void *next=make(current,9);CHECK(dispatch(next,&io)==-1021);
        CHECK(!release(id,next));
        struct native_cp_background_config_snapshot s;
        CHECK(!native_cp_background_config_snapshot(&s) && s.generation==1);
    }
    atomic_fetch_add(&releases,1);atomic_fetch_sub(&active,1);free((char *)p-8);return 0;
}
static int dispatch(void *p,const struct full_imaging_io *transport) {
    int rc=123;CHECK(native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,transport,1,&rc)==1);return rc;
}
static void expected_store(struct native_cp_background_config_snapshot *s,unsigned off,unsigned width,uint32_t value) {
    for(unsigned i=0;i<width;i++){s->value[off+i]=(unsigned char)(value>>(8*i));s->known[off+i]=1;}
}
static unsigned expected_known_word(const struct native_cp_background_config_snapshot *s,unsigned off) {
    return s->known[off]&&s->known[off+1]&&s->known[off+2]&&s->known[off+3];
}
static uint32_t expected_word(const struct native_cp_background_config_snapshot *s,unsigned off) {
    return (uint32_t)s->value[off]|(uint32_t)s->value[off+1]<<8|(uint32_t)s->value[off+2]<<16|(uint32_t)s->value[off+3]<<24;
}
static void unknown_store(struct native_cp_background_config_snapshot *s,unsigned off,unsigned width) {
    for(unsigned i=0;i<width;i++)s->known[off+i]=0;
}
static void update_expected(struct native_cp_background_config_snapshot *s,const struct contract *c,const unsigned char *wire) {
    switch(c->op) {
    case 0x4001:
        expected_store(s,0x69c,4,wire[8]);expected_store(s,0x698,1,wire[9]);
        expected_store(s,0x6a0,4,wire[10]);expected_store(s,0x6a4,1,wire[11]);break;
    case 0x400f:
        expected_store(s,0xb10,4,wire[8]);expected_store(s,0xb14,1,wire[9]);
        expected_store(s,0xb15,1,wire[10]);break;
    case 0x4048:
        expected_store(s,0x2c0,1,wire[8]);expected_store(s,0x2c4,4,wire[9]);
        expected_store(s,0x2bf,1,wire[10]);break;
    case 0x4151: {
        const unsigned input[]={8,12,14,16,20,22,23},output[]={0x3e8,0x3ec,0x3f0,0x3f4,0x3f8,0x3fc,0x400};
        const unsigned read_width[]={4,2,1,4,2,1,1},write_width[]={4,2,4,4,2,4,4};
        for(unsigned field=0;field<7;field++) {
            uint32_t value=0;
            for(unsigned byte=0;byte<read_width[field];byte++)value|=(uint32_t)wire[input[field]+byte]<<(8*byte);
            expected_store(s,output[field],write_width[field],value);
        }
        break;
    }
    case 0x4080: {
        /* Independent transcription of 0x357bd4 + 0x8da97e with tri-state inputs. */
        expected_store(s,0x1fc,4,wire[8]);
        unsigned known[4]={0,0,0,0};uint32_t value[4]={0,0,0,0};
        if(expected_known_word(s,0x21c)&&expected_word(s,0x21c)==1) {
            known[0]=known[1]=known[2]=1;value[0]=value[1]=value[2]=2;
            if(expected_known_word(s,0x214)) { known[3]=1;value[3]=expected_word(s,0x214)==1; }
        } else if(expected_known_word(s,0x21c)&&s->known[0x2a4]) {
            if(s->value[0x2a4]==2) { known[0]=known[1]=known[2]=known[3]=1; }
            else {
                if(expected_known_word(s,0x1fc)&&expected_word(s,0x1fc)==1) {
                    unsigned selected_known=0,selected=0;
                    if(s->known[0x228]) {
                        if(s->value[0x228]) { if(expected_known_word(s,0x224)) { selected_known=1;selected=expected_word(s,0x224); } }
                        else if(expected_known_word(s,0x200)) { selected_known=1;selected=expected_word(s,0x200); }
                    }
                    if(selected_known) { known[0]=1;value[0]=selected==1; }
                } else if(expected_known_word(s,0x1fc)) { known[0]=1;value[0]=0; }
                if(expected_known_word(s,0x208)) {
                    if(expected_word(s,0x208)!=1) { known[1]=1;value[1]=0; }
                    else if(expected_known_word(s,0x204)) {
                        uint32_t mode=expected_word(s,0x204);
                        known[1]=1;value[1]=mode==2?3:mode==1?1:0;
                    }
                }
                if(expected_known_word(s,0x20c)&&expected_known_word(s,0x210)) {
                    known[2]=known[3]=1;
                    value[2]=(expected_word(s,0x20c)==1)&(expected_word(s,0x210)==1);
                    value[3]=value[2];
                }
            }
        }
        if(known[0])expected_store(s,0x22c,4,value[0]);else unknown_store(s,0x22c,4);
        if(known[1])expected_store(s,0x230,4,value[1]);else unknown_store(s,0x230,4);
        if(known[2])expected_store(s,0x234,4,value[2]);else unknown_store(s,0x234,4);
        if(known[3])expected_store(s,0x218,1,value[3]);else unknown_store(s,0x218,1);
        break;
    }
    case 0x40a3: {
        /* Independent transcription of 0x358754's provable core: store +0x2a0
         * (singleton-selected, known only when both branches agree), byte +0x2a4
         * branch table, then the 0x8da97e recalc on the updated state. */
        if(wire[8]==0)expected_store(s,0x2a0,4,0);else unknown_store(s,0x2a0,4);
        if(expected_known_word(s,0x138)&&expected_word(s,0x138)==0x20) expected_store(s,0x2a4,1,2);
        else if(expected_known_word(s,0x138)&&expected_word(s,0x138)==0x1f) unknown_store(s,0x2a4,1);
        else if(expected_known_word(s,0x138)&&expected_known_word(s,0x29c)) {
            if(expected_word(s,0x29c)==2) expected_store(s,0x2a4,1,1);
            else if(expected_word(s,0x29c)==1) {
                if(expected_known_word(s,0x2a0)) expected_store(s,0x2a4,1,expected_word(s,0x2a0)==1);
                else unknown_store(s,0x2a4,1);
            } else expected_store(s,0x2a4,1,0);
        } else unknown_store(s,0x2a4,1);
        /* recalc (same inputs as 4080 case, after the 0x2a0/0x2a4 updates) */
        {
            unsigned known[4]={0,0,0,0};uint32_t value[4]={0,0,0,0};
            if(expected_known_word(s,0x21c)&&expected_word(s,0x21c)==1) {
                known[0]=known[1]=known[2]=1;value[0]=value[1]=value[2]=2;
                if(expected_known_word(s,0x214)) { known[3]=1;value[3]=expected_word(s,0x214)==1; }
            } else if(expected_known_word(s,0x21c)&&s->known[0x2a4]) {
                if(s->value[0x2a4]==2) { known[0]=known[1]=known[2]=known[3]=1; }
                else {
                    if(expected_known_word(s,0x1fc)&&expected_word(s,0x1fc)==1) {
                        unsigned selected_known=0,selected=0;
                        if(s->known[0x228]) {
                            if(s->value[0x228]) { if(expected_known_word(s,0x224)) { selected_known=1;selected=expected_word(s,0x224); } }
                            else if(expected_known_word(s,0x200)) { selected_known=1;selected=expected_word(s,0x200); }
                        }
                        if(selected_known) { known[0]=1;value[0]=selected==1; }
                    } else if(expected_known_word(s,0x1fc)) { known[0]=1;value[0]=0; }
                    if(expected_known_word(s,0x208)) {
                        if(expected_word(s,0x208)!=1) { known[1]=1;value[1]=0; }
                        else if(expected_known_word(s,0x204)) {
                            uint32_t mode=expected_word(s,0x204);
                            known[1]=1;value[1]=mode==2?3:mode==1?1:0;
                        }
                    }
                    if(expected_known_word(s,0x20c)&&expected_known_word(s,0x210)) {
                        known[2]=known[3]=1;
                        value[2]=(expected_word(s,0x20c)==1)&(expected_word(s,0x210)==1);
                        value[3]=value[2];
                    }
                }
            }
            if(known[0])expected_store(s,0x22c,4,value[0]);else unknown_store(s,0x22c,4);
            if(known[1])expected_store(s,0x230,4,value[1]);else unknown_store(s,0x230,4);
            if(known[2])expected_store(s,0x234,4,value[2]);else unknown_store(s,0x234,4);
            if(known[3])expected_store(s,0x218,1,value[3]);else unknown_store(s,0x218,1);
        }
        break;
    }
    case 0x401c:
        s->delta2ec+=(uint32_t)(wire[8]&128?(int)wire[8]-256:(int)wire[8]);
        expected_store(s,0x2f4,4,wire[9]);break;
    case 0x409c:s->deltab52=(unsigned char)(s->deltab52+1u);break;
    case 0x4003: /* gated counter: singleton 0x173efe8 unbound -> no mutation */ break;
    case 0x4022:
        expected_store(s,0x6c8,4,wire[8]);
        expected_store(s,0x6ac,2,wire[10]|(unsigned)wire[11]<<8);
        expected_store(s,0x6ae,2,wire[12]|(unsigned)wire[13]<<8);
        expected_store(s,0x6cc,2,wire[14]|(unsigned)wire[15]<<8);
        expected_store(s,0x6ce,2,wire[16]|(unsigned)wire[17]<<8);
        expected_store(s,0x6d0,2,wire[20]|(unsigned)wire[21]<<8);
        expected_store(s,0x6d2,2,wire[18]|(unsigned)wire[19]<<8);
        expected_store(s,0x774,4,wire[22]);expected_store(s,0x784,4,wire[23]);
        expected_store(s,0x6d4,4,wire[24]);expected_store(s,0x6d8,4,wire[25]);
        expected_store(s,0x6dc,4,wire[26]);expected_store(s,0x6e0,4,wire[27]);
        expected_store(s,0x778,2,wire[28]|(unsigned)wire[29]<<8);
        expected_store(s,0x77a,2,wire[30]|(unsigned)wire[31]<<8);break;
    case 0x4028:
        unknown_store(s,0x2d8,4);unknown_store(s,0x2e0,4);
        unknown_store(s,0x2e4,2);unknown_store(s,0x2e6,2);break;
    case 0x4139:
        memcpy(s->value+0x870,wire+8,176);memset(s->known+0x870,1,176);
        expected_store(s,0x86f,1,1);break;
    default:expected_store(s,c->offset,c->width,c->op==0x4043||c->op==0x415c?1:c->op==0x40ed?wire[8]!=0:wire[8]);break;
    }
    s->generation++;s->last_opcode=c->op;s->wire_bytes=c->bytes;s->apply_pending|=c->dirty;
    memset(s->wire,0,sizeof s->wire);memcpy(s->wire,wire,c->bytes);
}
static void equal(const struct native_cp_background_config_snapshot *a,const struct native_cp_background_config_snapshot *b) {
    CHECK(a->generation==b->generation && a->last_opcode==b->last_opcode && a->wire_bytes==b->wire_bytes && a->apply_pending==b->apply_pending);
    CHECK(a->delta2ec==b->delta2ec && a->deltab52==b->deltab52);
    CHECK(!memcmp(a->value,b->value,sizeof a->value));CHECK(!memcmp(a->known,b->known,sizeof a->known));
    CHECK(!memcmp(a->wire,b->wire,sizeof a->wire));
}
static void *produce(void *arg) {
    const struct contract *c=&contracts[(uintptr_t)arg%CONTRACT_COUNT];
    for(unsigned i=0;i<300;i++) {
        void *p=make(c,i);int rc=dispatch(p,&io);
        if(rc==-1021)CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));else CHECK(rc==0);
    }
    return NULL;
}
int main(int argc,char **argv) {
    CHECK(argc>=2);
    unsigned opcode=argc==3?(unsigned)strtoul(argv[2],NULL,0):0;
    if(opcode) {
        for(unsigned i=0;i<CONTRACT_COUNT;i++)if(contracts[i].op==opcode)current=&contracts[i];
        CHECK(current);
    }
    if(!strcmp(argv[1],"wire40b4")) {
        unsigned char wire[12]={0x05,0x00,0xb4,0x40,0x47,0x00,0x00,0x80,0x01,0x00,0x00,0x00};
        CHECK(current && current->op==0x40b4);
        unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
        struct native_cp_background_config_snapshot s;
        CHECK(!native_cp_background_config_snapshot(&s) && s.generation==1 && s.apply_pending);
        CHECK(s.last_opcode==0x40b4 && !s.known[0x77b] && !s.known[0x780]);
        for(unsigned i=0;i<4;i++)CHECK(s.known[0x77c+i] && s.value[0x77c+i]==(i?0:1));
        CHECK(releases==1 && records==1 && !active);
    } else if(!strcmp(argv[1],"wire40b6")) {
        unsigned char wire[12]={0x05,0x00,0xb6,0x40,0x46,0x00,0x00,0x80,0xff,0x00,0x00,0x00};
        CHECK(current && current->op==0x40b6);
        unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
        struct native_cp_background_config_snapshot s;
        CHECK(!native_cp_background_config_snapshot(&s) && s.generation==1 && s.apply_pending);
        CHECK(s.last_opcode==0x40b6 && !s.known[0x77f] && !s.known[0x784]);
        for(unsigned i=0;i<4;i++)CHECK(s.known[0x780+i] && s.value[0x780+i]==(i?0:0xff));
        CHECK(releases==1 && records==1 && !active);
    } else if(!strcmp(argv[1],"wire40a1")) {
        unsigned char wire[12]={0x05,0x00,0xa1,0x40,0x45,0x00,0x00,0x80,0xff,0x00,0x00,0x00};
        CHECK(current && current->op==0x40a1);
        for(unsigned v=0;v<2;v++) {
            wire[8]=(unsigned char)(v?0x00:0xff);
            unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
            struct native_cp_background_config_snapshot s;
            CHECK(!native_cp_background_config_snapshot(&s) && s.generation==v+1 && s.apply_pending);
            CHECK(s.last_opcode==0x40a1 && !s.known[0x74f] && !s.known[0x754]);
            for(unsigned i=0;i<4;i++)CHECK(s.known[0x750+i] && s.value[0x750+i]==(i?0:wire[8]));
        }
        CHECK(releases==2 && records==2 && !active);
    } else if(!strcmp(argv[1],"wire4080")) {
        unsigned char wire[12]={0x05,0x00,0x80,0x40,0x41,0x00,0x00,0x80,0x00,0x00,0x00,0x00};
        CHECK(current && current->op==0x4080);
        struct native_cp_background_config_snapshot expected={0};
        for(unsigned v=0;v<2;v++) {
            wire[8]=(unsigned char)(v?0xff:0);
            unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
            update_expected(&expected,current,wire);
            struct native_cp_background_config_snapshot s;
            CHECK(!native_cp_background_config_snapshot(&s));equal(&s,&expected);
            CHECK(s.generation==v+1 && s.apply_pending && s.last_opcode==0x4080);
            CHECK(s.known[0x1fc] && s.value[0x1fc]==wire[8] && !s.known[0x1fb] && !s.known[0x200]);
            CHECK(!s.known[0x218] && !s.known[0x22c] && !s.known[0x230] && !s.known[0x234]);
        }
        CHECK(releases==2 && records==2 && !active);
    } else if(!strcmp(argv[1],"wire40a3")) {
        /* Observed failure wire from candidate45 runtime-1 (value 0). */
        unsigned char wire[12]={0x05,0x00,0xa3,0x40,0x4c,0x00,0x00,0x80,0x00,0x00,0x00,0x00};
        CHECK(current && current->op==0x40a3);
        unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
        struct native_cp_background_config_snapshot s,expected={0};
        update_expected(&expected,current,wire);
        CHECK(!native_cp_background_config_snapshot(&s));equal(&s,&expected);
        /* value 0: both singleton branches agree, store known; 0x138/0x29c
         * unknown makes byte 0x2a4 and the recalc outputs unknown. */
        CHECK(s.known[0x2a0] && s.value[0x2a0]==0 && s.value[0x2a1]==0 && !s.known[0x29f]);
        CHECK(!s.known[0x2a4] && !s.known[0x218] && !s.known[0x22c]);
        CHECK(s.generation==1 && s.apply_pending && s.last_opcode==0x40a3);
        CHECK(releases==1 && records==1 && !active);
    } else if(!strcmp(argv[1],"wire4151")) {
        const unsigned char wire[]={0x05,0x00,0x51,0x41,0x3f,0x00,0x00,0x80,0x1e,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,0x00,0x01,0x00};
        CHECK(current && current->op==0x4151);
        unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
        struct native_cp_background_config_snapshot s,expected={0};
        update_expected(&expected,current,wire);
        CHECK(!native_cp_background_config_snapshot(&s));equal(&s,&expected);
        CHECK(s.value[0x3e8]==30 && s.value[0x3ec]==1 && s.value[0x3f4]==1 && s.value[0x3f8]==1 && s.value[0x3fc]==1);
        CHECK(!s.known[0x3e7] && !s.known[0x3ee] && !s.known[0x3ef] && !s.known[0x3fa] && !s.known[0x3fb] && !s.known[0x404]);
        CHECK(releases==1 && records==1 && !active);
    } else if(!strcmp(argv[1],"wire40d3")) {
        const unsigned char wire[]={0x05,0x00,0xd3,0x40,0x40,0x00,0x00,0x80,0x00,0x00,0x00,0x00};
        CHECK(current && current->op==0x40d3);
        unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
        struct native_cp_background_config_snapshot s;
        CHECK(!native_cp_background_config_snapshot(&s) && s.generation==1 && s.apply_pending);
        CHECK(s.last_opcode==0x40d3 && !s.known[0xb23] && !s.known[0xb28]);
        for(unsigned i=0;i<4;i++)CHECK(s.known[0xb24+i] && s.value[0xb24+i]==0);
        CHECK(releases==1 && records==1 && !active);
    } else if(!strcmp(argv[1],"wire4147")) {
        const unsigned char wire[]={0x05,0x00,0x47,0x41,0x37,0x00,0x00,0x80,0x01,0x00,0x00,0x00};
        CHECK(current && current->op==0x4147);
        unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
        struct native_cp_background_config_snapshot s;
        CHECK(!native_cp_background_config_snapshot(&s) && s.generation==1 && s.apply_pending);
        CHECK(s.last_opcode==0x4147 && !s.known[0x19b] && !s.known[0x1a0]);
        for(unsigned i=0;i<4;i++)CHECK(s.known[0x19c+i] && s.value[0x19c+i]==(i?0:1));
        CHECK(releases==1 && records==1 && !active);
    } else if(!strcmp(argv[1],"wire400f")) {
        const unsigned char wire[]={0x05,0x00,0x0f,0x40,0x3b,0x00,0x00,0x80,0x02,0x04,0x00,0x00};
        CHECK(current && current->op==0x400f);
        unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
        struct native_cp_background_config_snapshot s;
        CHECK(!native_cp_background_config_snapshot(&s) && s.generation==1 && s.apply_pending);
        CHECK(s.last_opcode==0x400f && !s.known[0xb0f] && !s.known[0xb16]);
        for(unsigned i=0;i<6;i++)CHECK(s.known[0xb10+i] && s.value[0xb10+i]==(i==0?2:i==4?4:0));
        CHECK(releases==1 && records==1 && !active);
    } else if(!strcmp(argv[1],"wire414a")) {
        const unsigned char wire[]={0x05,0x00,0x4a,0x41,0x2e,0x00,0x00,0x80,0x01,0x00,0x00,0x00};
        CHECK(current && current->op==0x414a);
        unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
        struct native_cp_background_config_snapshot s;
        CHECK(!native_cp_background_config_snapshot(&s) && s.generation==1 && s.apply_pending);
        CHECK(s.last_opcode==0x414a && !s.known[0x19f] && !s.known[0x1a4]);
        for(unsigned i=0;i<4;i++)CHECK(s.known[0x1a0+i] && s.value[0x1a0+i]==(i?0:1));
        CHECK(releases==1 && records==1 && !active);
    } else if(!strcmp(argv[1],"wire4167")) {
        const unsigned char wire[]={0x05,0x00,0x67,0x41,0x2b,0x00,0x00,0x80,0x00,0x00,0x00,0x00};
        CHECK(current && current->op==0x4167);
        for(unsigned v=0;v<2;v++) {
            unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);
            p[8]=(unsigned char)(v?0xff:0);CHECK(!dispatch(p,&io));
            struct native_cp_background_config_snapshot s;
            CHECK(!native_cp_background_config_snapshot(&s) && s.generation==v+1 && s.apply_pending);
            CHECK(s.last_opcode==0x4167 && !s.known[0xcfb] && !s.known[0xd00]);
            for(unsigned i=0;i<4;i++)CHECK(s.known[0xcfc+i] && s.value[0xcfc+i]==(i?0:(v?0xff:0)));
        }
        CHECK(releases==2 && records==2 && !active);
    } else if(!strcmp(argv[1],"wire4048")) {
        const unsigned char wire[]={0x05,0x00,0x48,0x40,0x2a,0x00,0x00,0x80,0x00,0x01,0x01,0x00};
        CHECK(current && current->op==0x4048);
        unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);CHECK(!dispatch(p,&io));
        struct native_cp_background_config_snapshot s;
        CHECK(!native_cp_background_config_snapshot(&s) && s.generation==1 && s.apply_pending);
        CHECK(s.value[0x2c0]==0 && s.value[0x2bf]==1 && s.value[0x2c4]==1);
        CHECK(s.known[0x2c0] && s.known[0x2bf] && !s.known[0x2c1]);
        for(unsigned i=0;i<4;i++)CHECK(s.known[0x2c4+i] && s.value[0x2c4+i]==(i?0:1));
        CHECK(releases==1 && records==1 && !active);
    } else if(!strcmp(argv[1],"wire40ee")) {
        CHECK(NATIVE_CP_BACKGROUND_SID==0x90030001u);
        const unsigned char wire[]={0x05,0x00,0xee,0x40,0x26,0x00,0x00,0x80,0x00,0x00,0x00,0x00};
        CHECK(current && current->op==0x40ee);
        for(unsigned v=0;v<2;v++) {
            unsigned char *p=make(current,0);memcpy(p,wire,sizeof wire);
            p[8]=(unsigned char)(v?0xff:0);
            CHECK(!dispatch(p,&io));
            struct native_cp_background_config_snapshot s;
            CHECK(!native_cp_background_config_snapshot(&s) && s.generation==v+1 && s.apply_pending);
            CHECK(s.last_opcode==0x40ee && s.wire_bytes==12 && s.value[0x180]==(v?0xff:0));
            CHECK(s.value[0x181]==0 && s.value[0x182]==0 && s.value[0x183]==0);
            CHECK(s.known[0x180] && s.known[0x181] && s.known[0x182] && s.known[0x183]);
        }
        CHECK(releases==2 && records==2 && !active);
    } else if(!strcmp(argv[1],"values")) {
        CHECK(current);struct native_cp_background_config_snapshot expected={0},actual;
        CHECK(native_cp_background_config_snapshot(NULL)==-1024);
        for(unsigned v=0;v<256;v++) {
            unsigned char *p=make(current,v),wire[184];memcpy(wire,p,current->bytes);
            if(current->op==0x4083 && v==2) {
                CHECK(dispatch(p,&io)==-1021 && active==1);
                CHECK(!native_cp_background_config_snapshot(&actual));equal(&actual,&expected);
                CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));continue;
            }
            CHECK(!dispatch(p,&io));update_expected(&expected,current,wire);
            CHECK(!native_cp_background_config_snapshot(&actual));equal(&actual,&expected);
        }
        CHECK(records==(current->op==0x4083?255u:256u) && releases==256 && !active);
        if(current->op==0x401c)CHECK(actual.delta2ec==0xffffff80u && !actual.known[0x2ec]);
        if(current->op==0x409c)CHECK(!actual.deltab52 && !actual.known[0xb52]);
        if(current->op==0x4003)CHECK(!actual.known[0x7a6] && !actual.value[0x7a6]);
        if(current->op==0x4022)CHECK(actual.known[0x6c8] && actual.value[0x6c8]==(unsigned)expected.wire[8] && actual.known[0x77a]);
        if(current->op==0x4028)CHECK(!actual.known[0x2d8] && !actual.known[0x2e6]);
    } else if(!strcmp(argv[1],"reject")) {
        CHECK(current);struct native_cp_background_config_snapshot before={0},after;
        CHECK(!native_cp_background_config_snapshot(&before));
        for(unsigned k=0;k<12;k++) {
            unsigned char *p=make(current,7);struct message *m=(void *)(p-8);
            struct full_imaging_io bad=io;int rc=123,handled;
            switch(k) {
            case 0:m->bytes=4;break;
            case 1:m->bytes=current->bytes-1;break;
            case 2:m->bytes=current->bytes+1;break;
            case 3:m->source=0;break;
            case 4:m->source=NATIVE_CP_BACKGROUND_SID;break;
            case 5:m->source=0x81cf61c6;break;
            case 6:bad.release=NULL;break;
            case 7:bad.source=NULL;break;
            case 8:p[0]=1;break;
            case 9:p[0]=13;break;
            case 10:bad.size=NULL;break;
            default:break;
            }
            handled=native_cp_background_dispatch(k==11?0x90040193:NATIVE_CP_BACKGROUND_SID,p,&bad,1,&rc);
            if(k<8)CHECK(handled && rc==-1020);
            else if(k==10)CHECK(handled && rc==-1021);
            else CHECK(!handled && rc==123);
            CHECK(!records && active==1);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));
            CHECK(!native_cp_background_config_snapshot(&after));equal(&before,&after);
        }
        void *p=make(current,0);int rc=123;
        CHECK(!native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,0,&rc) && rc==123);
        CHECK(!native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,1,NULL));
        CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));
        CHECK(native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,NULL,&io,1,&rc)==1 && rc==-1021);
        rc=123;CHECK(native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,NULL,NULL,1,&rc)==1 && rc==-1021);
    } else if(!strcmp(argv[1],"free-failure")) {
        CHECK(current);void *p=make(current,7);fail_free=1;CHECK(!dispatch(p,&io));
        struct native_cp_background_config_snapshot before,after;
        CHECK(!native_cp_background_config_snapshot(&before) && before.generation==1);
        void *next=make(current,8);CHECK(dispatch(next,&io)==-1021);
        fail_free=0;CHECK(!release(NATIVE_CP_BACKGROUND_SID,next));int rc=123;
        CHECK(native_cp_background_release(NATIVE_CP_BACKGROUND_SID,p,release,record,&rc)==1 && !rc);
        CHECK(!native_cp_background_config_snapshot(&after));equal(&before,&after);
        next=make(current,8);CHECK(dispatch(next,&io)==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,next));
    } else if(!strcmp(argv[1],"reentrant")) {
        CHECK(current);reenter=1;CHECK(!dispatch(make(current,7),&io));CHECK(releases==2 && records==1 && !active);
    } else if(!strcmp(argv[1],"fork")) {
        CHECK(current);CHECK(!dispatch(make(current,7),&io));pid_t child=fork();CHECK(child>=0);
        if(!child) {
            alarm(3);struct native_cp_background_config_snapshot s,before;
            memset(&s,0xa5,sizeof s);before=s;
            CHECK(native_cp_background_config_snapshot(&s)==-1021 && !memcmp(&s,&before,sizeof s));
            void *p=make(current,9);CHECK(dispatch(p,&io)==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));_exit(0);
        }
        int status;CHECK(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    } else if(!strcmp(argv[1],"all-opcodes")) {
        for(unsigned op=0;op<65536;op++) {
            const struct contract *c=NULL;for(unsigned i=0;i<CONTRACT_COUNT;i++)if(contracts[i].op==op)c=&contracts[i];
            struct contract unknown={op,12,0,0,0};unsigned char *p=make(c?c:&unknown,0);
            int rc=123;
            int handled=native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,1,&rc);
            if(c)CHECK(handled && !rc);
            else if(op==0x404e){CHECK(handled && rc==-1020);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));}
            else if(op==0x4070 || op==0x4023 || op==0x4077){CHECK(handled && !rc);}
            else if(op==0x4022 || op==0x4028){CHECK(handled && rc==-1020);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));}
            /* The limited all-opcodes fixture has no allocate/send/set_source callbacks.
             * 40df is claimed but rejected as missing-transport before its size check. */
            else if(op==0x40df){CHECK(handled && rc==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));}
            else{if(handled || rc!=123)fprintf(stderr,"unexpected opcode=%#x handled=%d rc=%d\n",op,handled,rc);CHECK(!handled && rc==123);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));}
        }
        struct native_cp_background_4070_snapshot pending;
        CHECK(!native_cp_background_4070_snapshot(&pending) && !pending.pending && !pending.request && pending.retired==1 && pending.deferred_count==1);
        struct native_cp_background_4023_snapshot retired;
        CHECK(!native_cp_background_4023_snapshot(&retired) && retired.generation==1 && retired.retired==1);
        const unsigned retained[]={0x4077};
        for(unsigned i=0;i<1;i++) {
            struct native_cp_background_remainder_snapshot s;
            CHECK(!native_cp_background_remainder_snapshot(NATIVE_CP_BACKGROUND_SID,retained[i],&s) && !s.pending && !s.request && s.retired==1 && s.deferred_count==1);
        }
        CHECK(records==CONTRACT_COUNT && !active);
    } else if(!strcmp(argv[1],"sticky")) {
        const struct contract *c=&contracts[0];CHECK(!dispatch(make(c,0),&io));
        struct native_cp_background_config_snapshot s;CHECK(!native_cp_background_config_snapshot(&s) && !s.apply_pending);
        CHECK(!dispatch(make(&contracts[7],3),&io));CHECK(!dispatch(make(&contracts[2],4),&io));
        CHECK(!dispatch(make(&contracts[14],5),&io));CHECK(!native_cp_background_config_snapshot(&s) && s.apply_pending && s.generation==4);
        struct native_cp_background_parameter_snapshot legacy;CHECK(!native_cp_background_parameter_snapshot(&legacy) && !legacy.parameter_valid && !legacy.generation && legacy.apply_pending);
    } else if(!strcmp(argv[1],"concurrent")) {
        pthread_t threads[8];for(unsigned i=0;i<8;i++)CHECK(!pthread_create(&threads[i],NULL,produce,(void *)(uintptr_t)i));
        for(unsigned i=0;i<8;i++)CHECK(!pthread_join(threads[i],NULL));
        struct native_cp_background_config_snapshot s;CHECK(!native_cp_background_config_snapshot(&s) && s.generation==records && records>0 && releases==2400 && !active);
    } else CHECK(0);
    CHECK(!active);printf("{\"case\":\"%s\",\"opcode\":%u,\"accepted\":%u,\"released\":%u,\"active\":%u,\"completion\":false}\n",argv[1],opcode,(unsigned)records,(unsigned)releases,(unsigned)active);return 0;
}
