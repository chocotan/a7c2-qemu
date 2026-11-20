/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "imaging-device.h"
#include "../functional-camera-abi.h"
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#define CHECK(x) do { if(!(x)){fprintf(stderr,"CHECK failed line=%d: %s\n",__LINE__,#x);exit(1);} } while(0)
struct block {unsigned bytes,source,pool;unsigned char wire[64];};
static _Atomic unsigned freed,logs,allocations,sends,accepted;
static int free_error,reenter,record_reenter;
static void *queued,*nested,*alias;
static struct full_imaging_io io;
static struct block *block(void *p){return (struct block *)((unsigned char *)p-sizeof(unsigned)*3);}
static unsigned size(void *p){return p==alias?16:block(p)->bytes;}
static unsigned source(void *p){return p==alias?FULL_IMAGING_AP:block(p)->source;}
static void put(unsigned char *p,unsigned v){for(unsigned i=0;i<4;++i)p[i]=(unsigned char)(v>>(8*i));}
static void *request(unsigned cmd,unsigned selector){
    struct block *b=calloc(1,sizeof *b);CHECK(b);
    b->bytes=16;b->pool=FULL_IMAGING_CP;b->source=FULL_IMAGING_AP;
    b->wire[0]=5;b->wire[2]=(unsigned char)cmd;b->wire[3]=(unsigned char)(cmd>>8);
    put(b->wire+4,0x8000000bu);put(b->wire+8,selector);return b->wire;
}
static struct full_imaging_snapshot snap(void){struct full_imaging_snapshot s;full_imaging_snapshot(&s);return s;}
static int dispatch(void *p){int rc=99;CHECK(full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,&rc)==1);return rc;}
static int release(unsigned id,void *p){
    CHECK(id==block(p)->pool);
    if(id==FULL_IMAGING_CP && reenter){reenter=0;CHECK(snap().functional_busy);CHECK(dispatch(nested)==-EBUSY);}
    if(id==FULL_IMAGING_CP && free_error)return free_error;
    ++freed;free(block(p));return 0;
}
static int allocate(unsigned id,void **out,unsigned bytes,unsigned count){
    CHECK(count==1 && bytes<=64);++allocations;
    struct block *b=calloc(1,sizeof *b);CHECK(b);b->bytes=bytes;b->pool=id;*out=b->wire;return 0;
}
static void set_source(void *p,unsigned id){block(p)->source=id;}
static int send(unsigned id,void *p){CHECK(id==FULL_IMAGING_AP && !queued);queued=p;++sends;return 0;}
static void record(const char *tag,const char *line){
    CHECK(strstr(tag,"FUNCTIONAL_CAMERA_STILL_UNLOCK") || !strcmp(tag,"FUNCTIONAL_CAMERA_INTERLOCK "));
    CHECK(strstr(line,"capture_verified=0"));
    if(strstr(tag,"STILL_UNLOCK")){
        CHECK(!snap().functional_busy);CHECK(strstr(line,"ap_reply=none"));++logs;
        if(record_reenter){record_reenter=0;CHECK(!dispatch(nested));nested=NULL;}
    }
}
static void reset(unsigned mask,int enabled){
    CHECK(!queued && !nested);free_error=reenter=record_reenter=0;alias=NULL;
    freed=logs=allocations=sends=accepted=0;full_imaging_test_reset(mask);
    if(enabled)CHECK(!full_imaging_functional_enable());
    io=(struct full_imaging_io){.release=release,.size=size,.source=source,.record=record};
}
static void accept(unsigned selector){void *p=request(0x4037,selector);CHECK(!dispatch(p));++accepted;}
static void reject(void *p,int error){
    struct full_imaging_snapshot before=snap();unsigned frees=freed;
    CHECK(dispatch(p)==error);struct full_imaging_snapshot after=snap();
    CHECK(!memcmp(&before,&after,sizeof before));CHECK(freed==frees);CHECK(!release(FULL_IMAGING_CP,p));
}
static void drain(void){
    CHECK(queued);int rc=99;full_imaging_functional_observe_receive(FULL_IMAGING_AP,queued,source(queued),size(queued));
    CHECK(full_imaging_release_reply(FULL_IMAGING_AP,queued,release,NULL,&rc)==1 && !rc);queued=NULL;
}
static void transport(void){io.allocate=allocate;io.set_source=set_source;io.send=send;}
static void *parallel(void *arg){
    (void)arg;void *p=request(0x4037,0x12);int rc=dispatch(p);
    if(!rc)++accepted;else{CHECK(rc==-EBUSY);CHECK(!release(FULL_IMAGING_CP,p));}return NULL;
}
int main(int argc,char **argv){
    CHECK(argc==2);unsigned mode=(unsigned)strtoul(argv[1],NULL,10);CHECK(mode<44);
    reset(FULL_IMAGING_POWER_ON_INHIBIT,mode!=0);
    void *p=NULL;int rc=99;
    if(mode==0){reject(request(0x4037,0x12),-ENODEV);}
    if(mode==1 || mode==37){
        for(unsigned i=0;i<(mode==37?1000u:1u);++i)accept(0x12);
        struct full_imaging_snapshot s=snap();CHECK(s.still_token[0x12]==0x8000000bu && !s.still_active[0x12]);
        CHECK(s.still_unlocks==accepted && s.focus_controls==accepted && freed==accepted && logs==accepted);
        CHECK(!s.functional_still_pending_free && !s.functional_still_free_rc && !s.live_replies);
        CHECK(s.last_focus_message[0]==0x30310002u && s.last_focus_message[3]==0x12);
    }
    if(mode>=2 && mode<=12){
        p=request(0x4037,0x12);unsigned char *w=p;
        if(mode==2)block(p)->source^=1;
        if(mode==3)w[0]=0;
        if(mode==4)w[1]=1;
        if(mode==5)block(p)->bytes=4;
        if(mode==6)block(p)->bytes=8;
        if(mode==7)block(p)->bytes=15;
        if(mode==8)block(p)->bytes=17;
        if(mode>=9 && mode<=11)w[mode]=1;
        if(mode==12){
            static const unsigned char actual[16]={5,0,0x37,0x40,0x0a,0,0,0x80,0x12,0,0,0,0xff,0xff,0xff,0xff};
            memcpy(w,actual,16);CHECK(!dispatch(p) && freed==1 && snap().still_token[0x12]==0x8000000au);
        }
        else reject(p,-ENOTSUP);
    }
    if(mode>=13 && mode<=19){
        p=request(0x4037,0x12);
        if(mode==13)CHECK(!full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,NULL));
        if(mode==14)CHECK(!full_imaging_functional_dispatch(FULL_IMAGING_CP,NULL,&io,&rc));
        if(mode==15)CHECK(!full_imaging_functional_dispatch(FULL_IMAGING_CP,p,NULL,&rc));
        if(mode==16){io.size=NULL;CHECK(!full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,&rc));}
        if(mode==17){io.source=NULL;CHECK(dispatch(p)==-EINVAL);}
        if(mode==18){io.release=NULL;CHECK(dispatch(p)==-EINVAL);}
        if(mode==19)CHECK(!full_imaging_functional_dispatch(FULL_IMAGING_LENS_POSITION_CP,p,&io,&rc));
        CHECK(!freed && !snap().still_unlocks);CHECK(!release(FULL_IMAGING_CP,p));
    }
    if(mode==20){
        for(unsigned selector=0;selector<256;++selector){
            reset(FULL_IMAGING_POWER_ON_INHIBIT,1);p=request(0x4037,selector);
            if(selector<23 && ((0x007e621cu>>selector)&1))CHECK(!dispatch(p) && freed==1);
            else reject(p,-ENOTSUP);
        }
    }
    if(mode==21){
        unsigned char state[128]={0};put(state,FCAM_ABI_VERSION);put(state+4,FCAM_CAPABILITIES);
        put(state+8,640);put(state+12,480);put(state+16,30);put(state+20,95);
        put(state+48,1);put(state+56,1);put(state+64,1);put(state+112,1);
        CHECK(!full_imaging_capture_begin_functional(state,128,1,1));
        reject(request(0x4037,0x12),-EBUSY);full_imaging_capture_end();accept(0x12);
    }
    if(mode==22){
        full_imaging_test_still(0x13,1,99);full_imaging_test_latches(0,1,0);
        reject(request(0x4037,0x13),-EBUSY);CHECK(snap().pending_still_13 && snap().still_active[0x13]);
    }
    if(mode==23 || mode==24){
        unsigned selector=mode==23?2:0x14;
        for(unsigned latch=0;latch<2;++latch){
            reset(FULL_IMAGING_POWER_ON_INHIBIT,1);full_imaging_test_still(selector,1,99);
            full_imaging_test_latches(latch?7:0,0,0);accept(selector);struct full_imaging_snapshot s=snap();
            CHECK(s.still_active[selector]==latch && s.still_token[selector]==(latch?99:0x8000000bu));
            CHECK(!s.focus_trigger[selector] && s.focus_controls==1);
        }
    }
    if(mode==25){
        for(unsigned flag=0;flag<3;++flag){
            reset(FULL_IMAGING_POWER_ON_INHIBIT,1);full_imaging_test_still(9,1,99);
            full_imaging_test_latches(0,0,flag);accept(9);struct full_imaging_snapshot s=snap();
            CHECK(s.still_active[9] && s.still_token[9]==99 && s.focus_latch_09==(flag==1?0:flag));
            CHECK(s.focus_controls==(flag==1?2u:1u) && !s.focus_trigger[9]);
        }
    }
    if(mode>=26 && mode<=28){
        full_imaging_test_still(0x12,1,10);full_imaging_test_still(0x0f,1,20);
        full_imaging_test_arbitration(0x12,0,0,mode==27?0:1,mode==26?1:0);accept(0x12);
        struct full_imaging_snapshot s=snap();CHECK(!s.still_active[0x12] && !s.focus_trigger[0x12]);
        CHECK(s.still_active[0x0f] && s.still_token[0x0f]==20);
        if(mode==26)CHECK(s.af_selector==0x12 && !s.ae_selector && !s.bw_selector && s.focus_controls==1);
        if(mode==27)CHECK(s.af_selector==0x12 && !s.af_gate);
        if(mode==28)CHECK(s.af_selector==0x0f && s.ae_selector==0x0f && s.bw_selector==0x0f && !s.af_gate);
    }
    if(mode==29){full_imaging_test_still(0x13,1,99);full_imaging_test_latches(0,1,0);accept(4);CHECK(snap().af_selector==0x13 && !snap().pending_still_13);}
    if(mode==30){
        transport();
        for(unsigned lock=1;;--lock){
            p=request(0x403d,0x8000);((unsigned char *)p)[12]=(unsigned char)lock;
            CHECK(!dispatch(p));drain();unsigned before=snap().requested;
            accept(0x12);CHECK(snap().requested==before);
            if(!lock)break;
        }
        CHECK(snap().requested==FULL_IMAGING_POWER_ON_INHIBIT && snap().applied==2 && snap().waiter_freed==2);
    }
    if(mode==31){
        p=request(0x4037,0x12);uintptr_t saved=(uintptr_t)p;free_error=-77;CHECK(!dispatch(p));
        struct full_imaging_snapshot s=snap();CHECK(s.faults==1 && s.functional_still_pending_free==saved);
        CHECK(s.functional_still_free_rc==-77 && s.still_unlocks==1 && !freed && logs==1);
        CHECK(full_imaging_capture_begin()!=0);free_error=0;reject(request(0x4037,4),-EBUSY);
        CHECK(!release(FULL_IMAGING_CP,p));
        CHECK(snap().functional_still_pending_free==saved); /* Sticky until test-only owner reset/guest exit. */
    }
    if(mode==32){nested=request(0x4037,4);reenter=1;accept(0x12);CHECK(!release(FULL_IMAGING_CP,nested));nested=NULL;CHECK(snap().still_unlocks==1);}
    if(mode==33){nested=request(0x4037,4);record_reenter=1;accept(0x12);CHECK(!nested && snap().still_unlocks==2 && freed==2 && logs==2);}
    if(mode==34){
        p=request(0x4037,0x12);pid_t child=fork();CHECK(child>=0);
        if(!child){CHECK(dispatch(p)==-ECHILD);_exit(0);}
        int status=0;CHECK(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
        CHECK(!dispatch(p) && freed==1);
    }
    if(mode==35 || mode==40 || mode==41){
        transport();p=request(0x403d,0x8000);CHECK(!dispatch(p) && queued);
        unsigned char saved[24];alias=(unsigned char *)queued+(mode==40?4:mode==41?-4:0);
        memcpy(saved,alias,24);
        unsigned char *w=alias;memset(w,0,16);w[0]=5;w[2]=0x37;w[3]=0x40;w[8]=0x12;
        unsigned count=freed;CHECK(dispatch(alias)==-EBUSY && freed==count && !snap().still_unlocks);
        memcpy(alias,saved,24);alias=NULL;drain();
    }
    if(mode==36){
        io.record=NULL;pthread_t workers[12];
        for(unsigned i=0;i<12;++i)CHECK(!pthread_create(&workers[i],NULL,parallel,NULL));
        for(unsigned i=0;i<12;++i)CHECK(!pthread_join(workers[i],NULL));
        CHECK(accepted>0 && snap().still_unlocks==accepted && freed==12 && !snap().faults);
    }
    if(mode==38){io.record=NULL;accept(0x16);CHECK(freed==1 && !logs && snap().still_token[0x16]==0x8000000bu);}
    if(mode==39){
        io.size=NULL;p=request(0x4037,0x12);CHECK(!full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,&rc));
        CHECK(!release(FULL_IMAGING_CP,p));
    }
    if(mode==42){
        p=request(0x4037,0x12);block(p)->bytes=3;
        CHECK(!full_imaging_functional_dispatch(FULL_IMAGING_CP,p,&io,&rc) && rc==99);
        CHECK(!release(FULL_IMAGING_CP,p));
    }
    if(mode==43){
        full_imaging_test_still(0x0d,1,99);full_imaging_test_still(4,1,20);
        full_imaging_test_arbitration(0x0d,0,0,1,0);accept(0x0d);
        CHECK(snap().af_selector==4 && !snap().af_gate && snap().focus_controls==3 && !snap().focus_trigger[0x0d]);
    }
    CHECK(!queued && !nested);CHECK(!snap().functional_busy);
    CHECK(snap().requested & FULL_IMAGING_POWER_ON_INHIBIT);
    if(mode!=30 && mode!=35 && mode!=40 && mode!=41)CHECK(!allocations && !sends);
    if(mode!=31)CHECK(!snap().faults && !snap().functional_still_pending_free);
    printf("PASS functional-still-unlock mode=%u CP_D012_verified=0 capture_verified=0\n",mode);return 0;
}
