/* SPDX-License-Identifier: MIT */
#include "functional-face-ap-observer.h"
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/wait.h>
static unsigned int events;
static struct functional_face_ap_observer recorded;
static void record_event(enum functional_face_ap_event event,const struct functional_face_ap_observer *s) {
    assert(event>=FACE_AP_SUBMIT && event<=FACE_AP_RETAINED);events++;recorded=*s;
}
static void put(unsigned char *p,unsigned int v,unsigned int n) {for(unsigned int i=0;i<n;i++)p[i]=(unsigned char)(v>>(i*8));}
static int begin(struct functional_face_ap_observer *s,unsigned char *q) {
    return functional_face_ap_begin(s,1,1,17,FUNCTIONAL_FACE_AP_DMM,0x81cf1234,q,40,record_event);
}
int main(int argc,char **argv) {
    assert(argc==2);struct functional_face_ap_observer s={0},before;
    unsigned char q[40]={0},r[56]={0};put(q,0x20,2);put(q+4,0x1d9,4);put(q+12,0xffffffffu,4);
    unsigned char saved[40];memcpy(saved,q,40);
    if(!strcmp(argv[1],"gates")) {
        assert(!functional_face_ap_begin(&s,0,1,17,FUNCTIONAL_FACE_AP_DMM,1,q,40,record_event));
        assert(!functional_face_ap_begin(&s,1,0,17,FUNCTIONAL_FACE_AP_DMM,1,q,40,record_event));
        assert(!functional_face_ap_begin(&s,1,1,17,0x9061003c,1,q,40,record_event));
        assert(!functional_face_ap_begin(&s,1,1,17,FUNCTIONAL_FACE_AP_DMM,0,q,40,record_event));
        assert(!functional_face_ap_begin(&s,1,1,17,FUNCTIONAL_FACE_AP_DMM,1,q,39,record_event));
        assert(!functional_face_ap_begin(&s,1,1,17,FUNCTIONAL_FACE_AP_DMM,1,q,41,record_event));
        q[0]=0x2a;assert(!begin(&s,q));q[0]=0x20;put(q+4,0x1dd,4);assert(!begin(&s,q));
        put(q+4,0x1d9,4);q[0]=0x24;put(q+8,0x8402,4);assert(!begin(&s,q));
        assert(!events && !s.active && !s.sequence);
    } else if(!strcmp(argv[1],"births")) {
        struct functional_face_ap_birth facts[4],out,untouched;
        for(unsigned int i=0;i<4;i++) {
            put(q+4,0x1d9+i,4);assert(begin(&s,q)==1);functional_face_ap_sent(&s,17,0,record_event);
            memset(r,0,sizeof r);put(r,0x8020,2);put(r+12,0x42d+i,4);put(r+24,0xdeadbeef,4);put(r+32,0x400000,4);
            functional_face_ap_received(&s,17,s.source,FUNCTIONAL_FACE_AP_DMM,r,40,0,record_event);
            functional_face_ap_freed(&s,17,s.source,r,0,record_event);
            assert(!functional_face_ap_observed_birth(&s,17,0x1d9+i,0x42d+i,&facts[i]));
            assert(facts[i].observations==1 && facts[i].observation_sequence==i+1 && !facts[i].ambiguous && !facts[i].any_free_observed);
        }
        for(unsigned int i=0;i<4;i++)assert(!functional_face_ap_observed_birth(&s,17,0x1d9+i,0x42d+i,&out) && out.observation_sequence==facts[i].observation_sequence);
        memset(&out,0xa7,sizeof out);memcpy(&untouched,&out,sizeof out);
        assert(functional_face_ap_observed_birth(&s,18,0x1d9,0x42d,&out)==-ECHILD && !memcmp(&out,&untouched,sizeof out));
        assert(functional_face_ap_observed_birth(&s,17,0x1d9,0x42e,&out)==-ESTALE && !memcmp(&out,&untouched,sizeof out));
        pid_t child=fork();assert(child>=0);
        if(!child){assert(functional_face_ap_observed_birth(&s,17,0x1d9,0x42d,&out)==-ECHILD);_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
        q[0]=0x23;put(q+4,0,4);put(q+8,0x42d,4);assert(begin(&s,q)==1);functional_face_ap_sent(&s,17,0,record_event);
        put(r,0x8023,2);put(r+2,3,2);functional_face_ap_received(&s,17,s.source,FUNCTIONAL_FACE_AP_DMM,r,40,0,record_event);
        functional_face_ap_freed(&s,17,s.source,r,0,record_event);
        assert(!functional_face_ap_observed_birth(&s,17,0x1d9,0x42d,&out) && out.any_free_observed);
        q[0]=0x20;put(q+4,0x1d9,4);put(q+8,0,4);assert(begin(&s,q)==1);functional_face_ap_sent(&s,17,0,record_event);
        put(r,0x8020,2);put(r+2,0,2);put(r+12,0x82d,4);functional_face_ap_received(&s,17,s.source,FUNCTIONAL_FACE_AP_DMM,r,40,0,record_event);
        functional_face_ap_freed(&s,17,s.source,r,0,record_event);
        assert(s.births[0].ambiguous && s.births[0].handle==0x42d && s.births[0].observations==2);
        assert(functional_face_ap_observed_birth(&s,17,0x1d9,0x42d,&out)==-ESTALE);
        assert(functional_face_ap_observed_birth(&s,17,0x1d9,0x82d,&out)==-ESTALE);
        struct functional_face_ap_observer malformed={0};
        assert(begin(&malformed,q)==1);functional_face_ap_sent(&malformed,17,0,record_event);
        put(r+12,0x7fff,4);functional_face_ap_received(&malformed,17,malformed.source,FUNCTIONAL_FACE_AP_DMM,r,40,0,record_event);
        functional_face_ap_freed(&malformed,17,malformed.source,r,0,record_event);
        assert(malformed.births[0].ambiguous && malformed.births[0].observations==1);
        assert(functional_face_ap_observed_birth(&malformed,17,0x1d9,0x7fff,&out)==-ESTALE);
    } else {
        assert(begin(&s,q)==1 && s.active && s.sequence==1 && events==1);before=s;
        if(!strcmp(argv[1],"retained")) {
            q[4]=0xda;assert(begin(&s,q)==-EBUSY && s.dropped==1);
            before.dropped=1;assert(!memcmp(&s,&before,sizeof s));
        } else if(!strcmp(argv[1],"sendfail")) {
            functional_face_ap_sent(&s,17,-73,record_event);assert(!s.active && s.send_result==-73);
            assert(begin(&s,q)==1 && s.sequence==2 && !s.send_seen);
        } else if(!strcmp(argv[1],"fork")) {
            pid_t child=fork();assert(child>=0);
            if(!child) {assert(begin(&s,q)==-ECHILD);functional_face_ap_sent(&s,17,0,record_event);assert(!memcmp(&s,&before,sizeof s));_exit(0);}
            int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
            assert(!memcmp(&s,&before,sizeof s));
        } else if(!strcmp(argv[1],"sequence")) {
            s.active=0;s.sequence=UINT64_MAX;before=s;assert(begin(&s,q)==-EOVERFLOW && !memcmp(&s,&before,sizeof s));
        } else {
            put(r,0x8020,2);put(r+12,0x409,4);put(r+24,0x12345000,4);put(r+32,0x64000,4);
            functional_face_ap_received(&s,17,s.source,0x8061003c,r,56,0,record_event);assert(!s.received);
            functional_face_ap_sent(&s,17,0,record_event);assert(s.send_seen && !s.send_result);
            if(!strcmp(argv[1],"reply")) {
                before=s;
                functional_face_ap_received(&s,18,s.source,0x8061003c,r,56,0,record_event);
                functional_face_ap_received(&s,17,s.source+1,0x8061003c,r,56,0,record_event);
                functional_face_ap_received(&s,17,s.source,0x8061003c,r,39,0,record_event);
                functional_face_ap_received(&s,17,s.source,0x8061003c,r,56,-1,record_event);
                r[0]^=1;functional_face_ap_received(&s,17,s.source,0x8061003c,r,56,0,record_event);r[0]^=1;
                assert(!memcmp(&s,&before,sizeof s));
            }
            functional_face_ap_received(&s,17,s.source,0x8061003c,r,56,0,record_event);
            assert(s.received && s.reply_bytes==56 && s.reply_source==0x8061003c && !memcmp(s.reply_wire,r,40));
            r[12]^=1;before=s;
            functional_face_ap_received(&s,17,s.source,0xdeadbeef,r,56,0,record_event);assert(!memcmp(&s,&before,sizeof s));
            void *p=malloc(1);assert(p);uintptr_t old=(uintptr_t)p;s.reply=old;free(p);
            if(!strcmp(argv[1],"freefail")) {
                functional_face_ap_freed(&s,17,s.source,(void *)old,-79,record_event);assert(s.active && s.free_attempts==1 && s.free_result==-79);
                assert(begin(&s,q)==-EBUSY && s.dropped==1);
            }
            functional_face_ap_freed(&s,18,s.source,(void *)old,0,record_event);assert(s.active);
            functional_face_ap_freed(&s,17,s.source+1,(void *)old,0,record_event);assert(s.active);
            functional_face_ap_freed(&s,17,s.source,(void *)old,0,record_event);
            assert(!s.active && s.free_result==0 && recorded.reply==old && !memcmp(s.request_wire,saved,40));
            assert(begin(&s,q)==1 && s.sequence==2 && !s.received);
        }
    }
    printf("AP_OBSERVER_HOSTTEST_PASS mode=%s observation_only=1 native_pin=0 byte_access=0 capture_verified=0\n",argv[1]);
    return 0;
}
