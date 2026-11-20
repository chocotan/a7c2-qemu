/* SPDX-License-Identifier: MIT */
#include "cp-background-device.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"%d: %s\n",__LINE__,#x);exit(1); } } while (0)
#define AP 0x80020002u
struct msg { unsigned int owner, source, size, live; unsigned char wire[32]; };
static struct msg messages[24];
static void *reply, *failed_free;
static unsigned int allocations, sends, stores, accepts, observed;
static int allocate_fail, send_fail, inline_free;
static unsigned char ack[12];
static struct msg *lookup(void *p) {
    for (unsigned int i=0;i<24;i++) if (messages[i].wire==p) return &messages[i];
    CHECK(0);return NULL;
}
static void *make(unsigned int owner,unsigned int size,unsigned int source) {
    for (unsigned int i=0;i<24;i++) if (!messages[i].live) {
        struct msg *m=&messages[i];memset(m,0,sizeof *m);
        m->owner=owner;m->size=size;m->source=source;m->live=1;return m->wire;
    }
    CHECK(0);return NULL;
}
static int release(unsigned int owner,void *p) {
    struct msg *m=lookup(p);CHECK(m->live && owner==m->owner);
    if (p==failed_free) return -9;
    m->live=0;return 0;
}
static int allocate(unsigned int owner,void **p,unsigned int size,unsigned int count) {
    CHECK(owner==AP && size==12 && count==1);allocations++;
    if (allocate_fail) return -12;
    *p=make(owner,size,0);return 0;
}
static unsigned int size(void *p) { CHECK(lookup(p)->live);return lookup(p)->size; }
static unsigned int source(void *p) { CHECK(lookup(p)->live);return lookup(p)->source; }
static void set_source(void *p,unsigned int id) { CHECK(lookup(p)->live);lookup(p)->source=id; }
static void record(const char *tag,const char *line) {
    if (!strcmp(tag,"NATIVE_CP_BACKGROUND_PUSH_MR_STORE ")) {
        stores++;CHECK(strstr(line,"handler_executed=1") && strstr(line,"completion=0"));
    }
    if (!strcmp(tag,"NATIVE_CP_BACKGROUND_PUSH_MR_ACCEPT ")) {
        accepts++;CHECK(strstr(line,"ack_queued=1") && strstr(line,"apply_completed=0"));
    }
}
static int send(unsigned int owner,void *p) {
    CHECK(owner==AP && lookup(p)->source==NATIVE_CP_BACKGROUND_SID);
    sends++;reply=p;memcpy(ack,p,12);
    if (send_fail) return -7;
    if (inline_free) { int rc=99;CHECK(native_cp_background_release(owner,p,release,record,&rc)==1 && !rc); }
    return 0;
}
static void observer(unsigned int owner,const unsigned char wire[12]) {
    CHECK(owner==AP && wire[2]==7 && wire[3]==0x30);observed++;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static int dispatch(void *p) {
    int rc=99;CHECK(native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,1,&rc)==1);return rc;
}
static void free_reply(void) {
    int rc=99;CHECK(native_cp_background_release(AP,reply,release,record,&rc)==1 && !rc);
}
int main(int argc,char **argv) {
    CHECK(argc==2);CHECK(!native_cp_background_bind_free_observer(observer));
    unsigned char wire[16]={5,0xa5,0xdf,0x40,0x6c,0,0,0x80,3,0x81,0xfe,0xd7,0x34,0x12,0xcd,0xab};
    if (!strcmp(argv[1],"observed-zero")) { wire[1]=0;memset(wire+8,0,8); }
    unsigned char *p=make(NATIVE_CP_BACKGROUND_SID,16,AP);memcpy(p,wire,16);
    int reject=!strcmp(argv[1],"bad-size") || !strcmp(argv[1],"bad-source");
    if (!strcmp(argv[1],"bad-size")) lookup(p)->size=15;
    if (!strcmp(argv[1],"bad-source")) lookup(p)->source=AP+1;
    if (reject) {
        CHECK(dispatch(p)==-1020 && lookup(p)->live && !sends && !allocations && !stores);
        struct native_cp_background_config_snapshot s={0},zero={0};
        CHECK(!native_cp_background_config_snapshot(&s) && !memcmp(&s,&zero,sizeof s));
        CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));return 0;
    }
    if (!strcmp(argv[1],"allocfail")) {
        allocate_fail=1;CHECK(dispatch(p)==-12 && lookup(p)->live && !stores && !sends);
        struct native_cp_background_config_snapshot s={0},zero={0};
        CHECK(!native_cp_background_config_snapshot(&s) && !memcmp(&s,&zero,sizeof s));
        allocate_fail=0;
    }
    if (!strcmp(argv[1],"inline-free")) inline_free=1;
    if (!strcmp(argv[1],"sendfail")) send_fail=1;
    if (!strcmp(argv[1],"request-free-fail")) failed_free=p;
    int rc=dispatch(p);CHECK(rc==(send_fail?-7:0));
    CHECK(sends==1 && stores==1 && accepts==(send_fail?0u:1u) && !observed);
    CHECK(!memcmp(ack,(unsigned char[]){1,0,0xdf,0x40,0x6c,0,0,0x80,0,0xf0,0,0},12));
    struct native_cp_background_config_snapshot s;CHECK(!native_cp_background_config_snapshot(&s));
    CHECK(s.generation==1 && s.last_opcode==0x40df && s.wire_bytes==16 && s.apply_pending==1);
    CHECK(!memcmp(s.wire,wire,16));
    for (unsigned int i=0;i<NATIVE_CP_BACKGROUND_PARAMETER_BYTES;i++) {
        unsigned int known=(i>=0x3cc && i<=0x3ce) || (i>=0x3d0 && i<=0x3d3);
        CHECK(s.known[i]==known);CHECK(s.value[i]==(known?wire[8+i-0x3cc]:0));
    }
    if (send_fail) { CHECK(lookup(p)->live && !lookup(reply)->live);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p)); }
    else {
        if (!inline_free) free_reply();
        if (failed_free) {
            CHECK(lookup(p)->live);failed_free=NULL;rc=99;
            CHECK(native_cp_background_release(NATIVE_CP_BACKGROUND_SID,p,release,record,&rc)==1 && !rc);
        } else CHECK(!lookup(p)->live);
    }
    /* A 40df free must never reach the strict 3007 predecessor observer. */
    CHECK(!observed);
    for (unsigned int i=0;i<24;i++) CHECK(!messages[i].live);
    return 0;
}
