/* SPDX-License-Identifier: MIT */
#include "tcin-device.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define CALLER 0x81cf61c9u
struct message { unsigned int size,source,owner;unsigned char body[12]; };
static struct message request,replies[9],second;
static unsigned int allocated,sent,request_frees,reply_frees,reentrant,reentrant_rejected;
static int alloc_error,send_error,request_error,reply_error,duplicate,wrong_size,null_reply,mutate_request;
static unsigned int applied_events,queued_events;
static void *last_reply;
static char last_fault[640];
static struct message *meta(void *p) { return (struct message *)((char *)p - offsetof(struct message,body)); }
static int allocate(unsigned int owner,void **out,unsigned int size,unsigned int count);
static int release(unsigned int owner,void *p) {
    if (p==request.body || p==second.body) {
        assert(owner==FULL_TCIN_INPUT);request_frees++;return request_error;
    }
    assert(owner==meta(p)->owner);reply_frees++;return reply_error;
}
static void set_source(void *p,unsigned int source) { meta(p)->source=source; }
static unsigned int size(void *p) { return meta(p)->size; }
static unsigned int source(void *p) { return meta(p)->source; }
static int send(unsigned int destination,void *p) {
    assert(destination==request.source && meta(p)->source==FULL_TCIN_INPUT);
    static const unsigned char expected[12]={0x0d,0x20,0x29,0x14,12,0,1,0x80,0,0,0,0};
    assert(!memcmp(p,expected,12) && meta(p)->size==12);
    assert(applied_events==sent+1);sent++;last_reply=p;return send_error;
}
static void record(const char *tag,const char *text) {
    if (!strcmp(tag,"FULL_TCIN_FAULT ")) snprintf(last_fault,sizeof last_fault,"%s",text);
    if (!strcmp(tag,"FULL_TCIN_APPLIED ")) {
        assert(strstr(text,"pending=0") && strstr(text,"original_cp_executed=0"));applied_events++;
    }
    if (!strcmp(tag,"FULL_TCIN_REPLY_QUEUED ")) queued_events++;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int count) {
    assert(owner==request.source && bytes==12 && count==1 && allocated<9);
    if (reentrant) {
        reentrant=0;second=request;int rc=0;
        assert(full_tcin_dispatch(FULL_TCIN_INPUT,second.body,&io,1,&rc)==1 && rc==-1021);
        reentrant_rejected=1;
    }
    if (alloc_error) return alloc_error;
    if (null_reply) { *out=0;return 0; }
    if (mutate_request) request.body[8]=1;
    if (duplicate) { *out=request.body;return 0; }
    struct message *m=&replies[allocated++];m->size=wrong_size?8:12;m->owner=owner;*out=m->body;return 0;
}
static void make_request(void) {
    static const unsigned char raw[10]={0x0d,0x20,0x29,0x04,10,0,1,0x80,0,0};
    memcpy(request.body,raw,10);request.size=10;request.source=CALLER;request.owner=FULL_TCIN_INPUT;
}
static void reset(void) {
    full_tcin_test_reset();last_fault[0]=0;memset(replies,0,sizeof(replies));memset(&request,0,sizeof(request));
    allocated=sent=request_frees=reply_frees=reentrant=reentrant_rejected=applied_events=queued_events=0;
    alloc_error=send_error=request_error=reply_error=duplicate=wrong_size=null_reply=mutate_request=0;last_reply=0;make_request();
}
static int dispatch(void) { int rc=99;assert(full_tcin_dispatch(FULL_TCIN_INPUT,request.body,&io,1,&rc)==1);return rc; }
static void free_last(void) { int rc=99;assert(full_tcin_release_reply(meta(last_reply)->owner,last_reply,release,record,&rc)==1 && rc==0); }
static struct full_tcin_snapshot snapshot(void) { struct full_tcin_snapshot s;full_tcin_snapshot(&s);return s; }
int main(int argc,char **argv) {
    assert(argc==2);reset();
    if (!strcmp(argv[1],"normal")) {
        for (unsigned int i=0;i<2;i++) {
            make_request();request.source+=i;
            assert(dispatch()==0);struct full_tcin_snapshot s=snapshot();
            assert(s.applications==i+1 && s.queued==i+1 && s.clean_completion && !s.busy);
            assert(!s.requested && !s.applied && !s.active && !s.connected && !s.pending_flags);
            assert(s.live_replies==1 && s.request_freed==i+1);free_last();
        }
        assert(snapshot().reply_freed==2 && request_frees==2 && reply_frees==2 && queued_events==2);
    } else if (!strcmp(argv[1],"disabled")) {
        int rc=77;assert(!full_tcin_dispatch(FULL_TCIN_INPUT,request.body,&io,0,&rc) && rc==77 && !allocated);
    } else if (!strcmp(argv[1],"invalid")) {
        for (unsigned int i=0;i<7;i++) {
            reset();
            if (i==0) request.body[8]=1;
            if (i==1) request.body[8]=2;
            if (i==2) request.body[9]=1;
            if (i==3) request.body[4]=12;
            if (i==4) request.body[7]=0;
            if (i==5) request.source=FULL_TCIN_INPUT;
            if (i==6) request.size=11;
            assert(dispatch()==-1021 && !allocated && !sent && !request_frees);
        }
        reset();request.size=1;int rc=77;
        assert(!full_tcin_dispatch(FULL_TCIN_INPUT,request.body,&io,1,&rc) && rc==77 && !allocated);
    } else if (!strcmp(argv[1],"noninactive")) {
        for (unsigned int i=0;i<3;i++) {
            reset();full_tcin_test_state(i==0,i==1,i==2);
            assert(dispatch()==-1021 && !allocated && !sent && !request_frees);
        }
    } else if (!strcmp(argv[1],"alloc-fail")) {
        alloc_error=-55;assert(dispatch()==-55 && !sent && !request_frees && !snapshot().applications);
    } else if (!strcmp(argv[1],"alloc-null")) {
        null_reply=1;assert(dispatch()==-1021 && !sent && !request_frees && !snapshot().applications);
    } else if (!strcmp(argv[1],"request-snapshot")) {
        mutate_request=1;assert(dispatch()==0 && request.body[8]==1 && snapshot().requested==0);free_last();
    } else if (!strcmp(argv[1],"cleanup-retention")) {
        assert(dispatch()==0 && dispatch()==0);
        send_error=-66;reply_error=-88;assert(dispatch()==-66);
        assert(snapshot().retained_cleanup_reply==replies[2].body);
        assert(strstr(last_fault,"send_rc=-66") && strstr(last_fault,"cleanup_free_rc=-88") && strstr(last_fault,"retained_cleanup=1"));
        for (unsigned int i=0;i<2;i++) {
            int rc=0;assert(full_tcin_release_reply(CALLER,replies[i].body,release,record,&rc)==1 && rc==-88);
        }
        assert(snapshot().retained_cleanup_reply==replies[2].body && snapshot().cleanup_free_rc==-88);
        reply_error=0;
        for (unsigned int i=0;i<2;i++) {
            int rc=0;assert(full_tcin_release_reply(CALLER,replies[i].body,release,record,&rc)==1 && rc==0);
        }
        assert(snapshot().retained_cleanup_reply==replies[2].body && !snapshot().live_replies && snapshot().faults);
        assert(snapshot().retained_cleanup_owner==CALLER);
        int rc=0;assert(full_tcin_release_reply(CALLER,replies[2].body,release,record,&rc)==1 && rc==0);
        assert(!snapshot().retained_cleanup_reply && !snapshot().retained_cleanup_owner);
    } else if (!strcmp(argv[1],"wrong-size-cleanup")) {
        wrong_size=1;reply_error=-88;assert(dispatch()==-1021);
        assert(snapshot().retained_cleanup_reply==replies[0].body);
        assert(strstr(last_fault,"reply_bytes=8") && strstr(last_fault,"cleanup_free_rc=-88") && strstr(last_fault,"retained_cleanup=1"));
    } else if (!strcmp(argv[1],"wrong-size")) {
        wrong_size=1;assert(dispatch()==-1021 && !sent && !request_frees && reply_frees==1);
    } else if (!strcmp(argv[1],"duplicate")) {
        duplicate=1;assert(dispatch()==-1021 && !sent && !request_frees && snapshot().faults);
    } else if (!strcmp(argv[1],"send-fail")) {
        send_error=-66;assert(dispatch()==-66 && !request_frees && reply_frees==1);
        struct full_tcin_snapshot s=snapshot();assert(s.applications==1 && !s.queued && s.faults && !s.clean_completion);
    } else if (!strcmp(argv[1],"request-free-fail")) {
        request_error=-77;assert(dispatch()==0 && queued_events==1);
        struct full_tcin_snapshot s=snapshot();assert(s.retained_request==request.body && s.faults && !s.clean_completion);
        free_last();assert(dispatch()==-1021 && sent==1);
    } else if (!strcmp(argv[1],"reply-free-fail")) {
        assert(dispatch()==0);reply_error=-88;int rc=0;
        assert(full_tcin_release_reply(CALLER,last_reply,release,record,&rc)==1 && rc==-88);
        assert(snapshot().retained_reply==last_reply && !snapshot().clean_completion);
        reply_error=0;free_last();assert(snapshot().live_replies==0 && !snapshot().retained_reply);
    } else if (!strcmp(argv[1],"wrong-owner")) {
        assert(dispatch()==0);int rc=0;
        assert(full_tcin_release_reply(CALLER+1,last_reply,release,record,&rc)==1 && rc==-1021 && !reply_frees);
        assert(snapshot().retained_reply==last_reply && !snapshot().clean_completion);free_last();
    } else if (!strcmp(argv[1],"busy")) {
        reentrant=1;assert(dispatch()==0 && reentrant_rejected && sent==1 && request_frees==1);free_last();
    } else if (!strcmp(argv[1],"leases")) {
        for (unsigned int i=0;i<8;i++) assert(dispatch()==0);
        assert(dispatch()==-1021 && sent==8 && reply_frees==1 && request_frees==8);
        for (unsigned int i=0;i<8;i++) {
            int rc=0;assert(full_tcin_release_reply(CALLER,replies[i].body,release,record,&rc)==1 && rc==0);
        }
        assert(snapshot().live_replies==0);
    } else return 2;
    puts("TCIN_TEST_PASS: inactive disable only; no samples/genlock/hardware/capture claim");return 0;
}
