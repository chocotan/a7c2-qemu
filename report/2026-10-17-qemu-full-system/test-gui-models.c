/* SPDX-License-Identifier: MIT */
#include "gui-models.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#ifndef GUI_MODELS_TEST
static unsigned int freed, faults;
static int release_message(unsigned int id,void *p) {
    assert(id==0x9088076bu);freed++;free(p);return 0;
}
static void observe(const char *prefix,const char *text) {
    assert(prefix && text);
    if(!strcmp(prefix,"FULL_GUI_MODELS_FAULT "))faults++;
}
#endif
static void put(unsigned char *p,unsigned int v) {
    for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));
}
int main(void) {
    struct gui_model_state s={0},before;
    unsigned char b[GUI_MODEL_BATCH_MAX]={0};
    put(b+4,20);put(b+8,0x15);put(b+12,12);put(b+16,2);put(b+20,0x100);
    assert(gui_models_apply(&s,b,28)==(1<<5));
    assert(s.values[5].size==12 && s.values[5].generation==1);
    for(unsigned int i=0;i<10000;i++)assert(gui_models_apply(&s,b,28)==0);
    assert(s.values[5].generation==1 && s.batches==10001);
    put(b+20,0x101);assert(gui_models_apply(&s,b,28)==(1<<5));
    assert(s.values[5].generation==2);
    before=s;
    /* Declared lengths, unknown IDs and a truncated final record never commit. */
    put(b+12,0xffffffff);assert(gui_models_apply(&s,b,28)==-1);
    assert(!memcmp(&s,&before,sizeof s));
    put(b+12,12);put(b+8,64);assert(gui_models_apply(&s,b,28)==-1);
    assert(!memcmp(&s,&before,sizeof s));
    put(b+8,0x15);put(b+4,40);memcpy(b+28,b+8,20);
    assert(gui_models_apply(&s,b,48)==-1); /* duplicate ID */
    assert(!memcmp(&s,&before,sizeof s));
    put(b+4,0);assert(gui_models_apply(&s,b,8)==0);
    assert(s.values[5].generation==2); /* omission is not deletion */
    memset(b,0,sizeof b);put(b+4,636);put(b+8,0x10);put(b+12,628);
    assert(gui_models_apply(&s,b,644)==1);
    assert(s.history[0].version==0x21 && s.history[0].changes[1][0]==0xffffffffu);
    assert(s.history[0].changes[1][1]==0x3ffffu);
    assert(gui_models_apply(&s,b,644)==0);
    assert(s.history[0].version==0x22 && s.history[0].changes[2][0]==0);
    for(unsigned int i=0;i<62;i++)assert(gui_models_apply(&s,b,644)==0);
    assert(s.history[0].version==0x20 && s.values[0].generation==1);
    b[643]=1;assert(gui_models_apply(&s,b,644)==1);
    assert(s.history[0].version==0x21 && s.history[0].changes[1][0]==0xffffffffu);
    assert(s.history[0].bytes[1][627]==1); /* compare/copy includes final byte */
    const unsigned int ids[]={0x15,0x16,0x19,0x1a,0x1b};
    const unsigned int sizes[]={12,20,12,4,16};
    for(unsigned int h=0;h<5;h++) {
        memset(b,0,sizeof b);put(b+4,8+sizes[h]);put(b+8,ids[h]);put(b+12,sizes[h]);
        struct gui_model_state one={0};
        assert(gui_models_apply(&one,b,16+sizes[h])>0);
        assert(one.history[h+1].version==0x21);
        assert(gui_models_apply(&one,b,16+sizes[h])==0);
        assert(one.history[h+1].version==0x22);
        assert(one.history[h+1].changes[2][0]==0);
        b[15+sizes[h]]=1;
        assert(gui_models_apply(&one,b,16+sizes[h])>0);
        assert(one.history[h+1].version==0x23);
        assert(one.history[h+1].changes[3][0]==0xffffffffu);
    }
#ifndef GUI_MODELS_TEST
    /* Exercise production ownership, not just parser results: each accepted
     * allocation is released once, malformed requests remain sender-owned. */
    memset(b,0,sizeof b);put(b+4,20);put(b+8,0x15);put(b+12,12);
    for(unsigned int i=0;i<10000;i++) {
        void *request=malloc(28);assert(request);memcpy(request,b,28);
        assert(full_gui_models_dispatch(0x9088076bu,request,28,release_message,observe)==0);
    }
    assert(freed==10000 && !faults);
    void *request=malloc(28);assert(request);memcpy(request,b,28);
    ((unsigned char *)request)[8]=0xff;
    assert(full_gui_models_dispatch(0x9088076bu,request,28,release_message,observe)<0);
    assert(freed==10000);free(request);
#endif
    puts("GUI_MODELS_TEST_PASS repeats=10000 atomic_rejects=1");
}
