/* SPDX-License-Identifier: MIT */
#include "vdf-device.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct msg { unsigned int size, source, pool; unsigned char body[24]; };
static struct msg *meta(void *p) { return (void *)((char *)p - offsetof(struct msg,body)); }
static void *reply, *retained;
static unsigned int sends, frees, reads, allocations;
static int allocate_error, send_error, free_error, backend_error, change_on_read;
static unsigned int lcd=1, evf;
static const unsigned char request_wire[22]={13,32,24,1,22,0,1,128,3,1,0,0,0,0,0,0,0,0,0,0,1,0};
static const unsigned char completion[12]={13,32,24,17,12,0,1,128,0,0,0,0};
static void *message(unsigned int n,unsigned int src,unsigned int pool) {
    struct msg *m=calloc(1,sizeof *m);assert(m);m->size=n;m->source=src;m->pool=pool;return m->body;
}
static int allocate(unsigned int pool,void **out,unsigned int n,unsigned int count) {
    assert(n==12 && count==1);allocations++;
    if(allocate_error)return allocate_error;
    *out=message(n,0,pool);return 0;
}
static int release(unsigned int pool,void *p) {
    assert(meta(p)->pool==pool);
    if(pool==FULL_VDF_INPUT && free_error) {retained=p;return free_error;}
    free(meta(p));frees++;return 0;
}
static void source_set(void *p,unsigned int src) {meta(p)->source=src;}
static unsigned int source_get(void *p) {return meta(p)->source;}
static unsigned int size_get(void *p) {return meta(p)->size;}
static int send(unsigned int dst,void *p) {
    sends++;assert(dst==0x81cf618b && meta(p)->pool==dst && source_get(p)==FULL_VDF_INPUT);
    assert(!memcmp(p,completion,12));if(send_error)return send_error;reply=p;return 0;
}
static int read_outputs(unsigned int *l,unsigned int *e) {
    reads++;*l=(change_on_read && reads>1)?0:lcd;*e=evf;return backend_error;
}
static void log_event(const char *tag,const char *line) {
    assert(strlen(tag)+strlen(line)+6<512);
    if(!strcmp(tag,"FULL_VDF_PANEL_OUT_NOCHANGE "))assert(strstr(line,"applied_mask=3 ") && strstr(line,"reply_raw=0d2018110c00018000000000 "));
}
static const struct full_imaging_io io={allocate,release,source_set,send,size_get,source_get,log_event};
static void reset(void) {
    assert(!reply && !retained);full_vdf_test_reset();
    sends=frees=reads=allocations=0;allocate_error=send_error=free_error=backend_error=change_on_read=0;lcd=1;evf=0;
}
static void *request(void) {void *p=message(22,0x81cf618b,FULL_VDF_INPUT);memcpy(p,request_wire,22);return p;}
static int dispatch(void *p) {int rc=123;assert(full_vdf_panel_out_dispatch(FULL_VDF_INPUT,p,&io,read_outputs,1,&rc)==1);return rc;}
static void consume(void) {int rc=123;void *p=reply;reply=NULL;assert(full_vdf_release_reply(0x81cf618b,p,release,log_event,&rc)==1 && !rc);}
int main(void) {
    reset();
    for(unsigned int i=0;i<2;i++) {
        assert(!dispatch(request()));assert(sends==i+1 && reads==2*(i+1));consume();
    }
    struct full_vdf_snapshot s;full_vdf_snapshot(&s);
    assert(s.panel_out_nochange==2 && s.panel_out_applied_mask==3 && s.native_freed==2 && !s.live_replies && !s.faults);
    for(unsigned int field=8;field<22;field++) {
        reset();unsigned char *p=request();p[field]^=1;
        assert(dispatch(p)==-1021 && !sends && !allocations);assert(!release(FULL_VDF_INPUT,p));
    }
    reset();void *p=request();meta(p)->size=20;assert(dispatch(p)==-1021 && !allocations);meta(p)->size=22;assert(!release(FULL_VDF_INPUT,p));
    reset();p=request();meta(p)->source=0x92840747;assert(dispatch(p)==-1021 && !allocations);assert(!release(FULL_VDF_INPUT,p));
    for(unsigned int scenario=0;scenario<4;scenario++) {
        reset();p=request();
        if(scenario==0)backend_error=-1;
        if(scenario==1)lcd=0;
        if(scenario==2)evf=1;
        if(scenario==3)change_on_read=1;
        assert(dispatch(p)==-1021 && !sends);assert(!release(FULL_VDF_INPUT,p));
    }
    reset();p=request();allocate_error=-12;assert(dispatch(p)==-12 && !sends);assert(!release(FULL_VDF_INPUT,p));
    reset();p=request();send_error=-9;assert(dispatch(p)==-9 && sends==1 && frees==1);assert(!release(FULL_VDF_INPUT,p));
    reset();free_error=-7;assert(!dispatch(request()) && retained && sends==1);consume();
    full_vdf_snapshot(&s);assert(s.faults==1 && s.retained_request==retained);
    free_error=0;assert(!release(FULL_VDF_INPUT,retained));retained=NULL;
    reset();p=request();int rc=123;
    assert(!full_vdf_panel_out_dispatch(FULL_VDF_INPUT,p,&io,read_outputs,0,&rc) && rc==123);
    assert(full_vdf_panel_out_dispatch(FULL_VDF_INPUT,p,&io,NULL,1,&rc) && rc==-1021 && !sends);
    assert(!release(FULL_VDF_INPUT,p));
    puts("panel-out: 26 nochange/ownership/refusal checks passed; no hardware or pixels claimed");return 0;
}
