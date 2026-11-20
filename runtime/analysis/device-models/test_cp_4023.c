#define _GNU_SOURCE
/* Include the production translation unit for synthetic unknown/overflow inputs;
 * no test input setter or reset is exported to the runtime. */
#include "cp-background-device.c"
#include <stdlib.h>
#include <sys/wait.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1); } } while (0)
struct message { unsigned n,source;unsigned char wire[64]; };
static _Atomic unsigned active,frees,sends,allocations,accepted,logs;
static int free_failure,release_probe,record_probe;
static struct message *header(void *p) { return (void *)((unsigned char *)p-8); }
static unsigned size(void *p) { return header(p)->n; }
static unsigned source(void *p) { return header(p)->source; }
static void *make(unsigned value,unsigned extra,unsigned token) {
    struct message *m=calloc(1,sizeof *m);CHECK(m);m->n=12;m->source=0x80020002;
    m->wire[0]=5;m->wire[2]=0x23;m->wire[3]=0x40;put32(m->wire+4,token);
    m->wire[8]=(unsigned char)value;m->wire[10]=(unsigned char)extra;atomic_fetch_add(&active,1);return m->wire;
}
static int release(unsigned,void *);
static void record(const char *,const char *);
static int allocate(unsigned a,void **b,unsigned c,unsigned d) { (void)a;(void)b;(void)c;(void)d;atomic_fetch_add(&allocations,1);return -17; }
static int send(unsigned a,void *b) { (void)a;(void)b;atomic_fetch_add(&sends,1);return -17; }
static const struct full_imaging_io io={.size=size,.source=source,.release=release,.record=record,.allocate=allocate,.send=send};
static int dispatch(void *p,const struct full_imaging_io *transport) {
    int rc=123;CHECK(native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,transport,1,&rc)==1);return rc;
}
static struct native_cp_background_4023_snapshot snap(void) {
    struct native_cp_background_4023_snapshot s;CHECK(!native_cp_background_4023_snapshot(&s));return s;
}
static struct native_cp_background_config_snapshot csnap(void) {
    struct native_cp_background_config_snapshot s;CHECK(!native_cp_background_config_snapshot(&s));return s;
}
static int release(unsigned id,void *p) {
    CHECK(id==NATIVE_CP_BACKGROUND_SID && p);
    if(release_probe) {
        release_probe=0;struct native_cp_background_remainder_snapshot s;
        CHECK(!native_cp_background_remainder_snapshot(id,0x4023,&s) && s.pending && s.request==(uintptr_t)p);
        int rc=123;CHECK(native_cp_background_release(id,p,release,record,&rc)==1 && rc==-1021);
        unsigned char saved[12];memcpy(saved,p,12);((unsigned char *)p)[2]=0xb8;
        CHECK(dispatch(p,&io)==-1021);memcpy(p,saved,12);
        void *q=make(2,0,0x80000011);CHECK(dispatch(q,&io)==-1021);CHECK(!release(id,q));
        CHECK(snap().retired==0);
    }
    if(free_failure)return -17;
    atomic_fetch_sub(&active,1);atomic_fetch_add(&frees,1);free(header(p));return 0;
}
static void record(const char *tag,const char *text) {
    if(strcmp(tag,"NATIVE_CP_BACKGROUND_4023_RETIRE "))return;
    CHECK(strstr(text,"central_delivered=0") && strstr(text,"apply_completed=0") &&
          strstr(text,"handler_complete=0 completion=0 original_CP=0 capture_verified=0"));
    atomic_fetch_add(&logs,1);
    if(record_probe) {
        record_probe=0;CHECK(snap().retired==1);
        CHECK(!dispatch(make(2,0,0x80000011),&io));CHECK(snap().retired==2);
    }
}
static void verify_retired(unsigned n) {
    struct native_cp_background_4023_snapshot s=snap();struct native_cp_background_remainder_snapshot r;
    CHECK(!native_cp_background_remainder_snapshot(NATIVE_CP_BACKGROUND_SID,0x4023,&r));
    CHECK(s.generation==n && s.retired==n && r.generation==n && !r.request && !r.pending);
    CHECK(!active && !sends && !allocations);
}
static void *produce(void *unused) {
    (void)unused;
    for(unsigned i=0;i<100;i++) {
        void *p=make(2,i,i);int rc=dispatch(p,&io);CHECK(!rc || rc==-1021);
        if(rc)CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));else atomic_fetch_add(&accepted,1);
    }
    return NULL;
}
static void seed(unsigned old,unsigned p134,unsigned p198) {
    CHECK(!active);memset(&config,0,sizeof config);memset(&parameter4023,0,sizeof parameter4023);
    memset(&remainder_pending[1],0,sizeof remainder_pending[1]);
    store_parameter(0x688,4,old);store_parameter(0x134,4,p134);store_parameter(0x198,4,p198);
    store_parameter(0x2ba,1,7);store_parameter(0x7a6,1,255);
}
int main(int argc,char **argv) {
    CHECK(argc==2);alarm(25);
    if(!strcmp(argv[1],"sequence") || !strcmp(argv[1],"reuse")) {
        unsigned n=!strcmp(argv[1],"reuse")?10000:2;
        for(unsigned i=0;i<n;i++)CHECK(!dispatch(make(2,n==2?0:i,i?0x80000011:0x8000000d),&io));
        verify_retired(n);struct native_cp_background_4023_snapshot s=snap();struct native_cp_background_config_snapshot c=csnap();
        CHECK(s.central_pending==1 && s.central_generation==1 && !s.central_old688_known && !s.central_p134_known && !s.central_p198_known);
        CHECK(u32(s.central_request+4)==0x8000000d && u32(s.wire+4)==0x80000011);
        CHECK(s.parameter688==2 && s.parameter720==(n==2?0:(unsigned char)(n-1)) && !s.counter_delta && !s.initial_transition_unknown);
        CHECK(c.generation==n && c.apply_pending && u32(c.value+0x688)==2 && c.known[0x688] && c.known[0x68b]);
        CHECK(!c.known[0x134] && !c.known[0x198] && !c.known[0x2ba] && !c.known[0x7a6]);
        unsigned char expected[32]={0};expected[4]=6;expected[5]=0x83;CHECK(!memcmp(s.central_wire,expected,32));
    } else if(!strcmp(argv[1],"bounded")) {
        CHECK(!dispatch(make(2,0,13),&io));struct native_cp_background_4023_snapshot s=snap();
        struct native_cp_background_config_snapshot c=csnap();void *p=make(3,9,17);
        CHECK(dispatch(p,&io)==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));
        struct native_cp_background_4023_snapshot t=snap();struct native_cp_background_config_snapshot d=csnap();
        CHECK(!memcmp(&s,&t,sizeof s) && !memcmp(&c,&d,sizeof c));
        CHECK(!dispatch(make(8,3,18),&io));CHECK(!dispatch(make(0,4,19),&io));
        p=make(1,5,20);CHECK(dispatch(p,&io)==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));
        CHECK(!dispatch(make(0,5,21),&io));
        verify_retired(4);t=snap();d=csnap();CHECK(t.central_pending==1 && t.central_generation==1 && !t.counter_delta);
        CHECK(!t.clear2ba_pending && d.known[0x2ba] && !d.value[0x2ba] && !d.known[0x7a6]);
    } else if(!strcmp(argv[1],"semantics")) {
        const unsigned olds[]={0,1,2,8,256,0xffffffffu};
        for(unsigned gate=0;gate<3;gate++)for(unsigned j=0;j<6;j++)for(unsigned value=0;value<256;value++) {
            unsigned old=olds[j],a=gate==1?1:0,b=gate==2?1:0;seed(old,a,b);
            CHECK(!dispatch(make(value,0xa5,17),&io));struct native_cp_background_4023_snapshot s=snap();
            struct native_cp_background_config_snapshot c=csnap();
            unsigned increment=(value==0 && old==1) || (value==1 && old==0);
            unsigned event=!a && !b && old!=value && ((value|8)!=8);
            CHECK(s.central_pending==(event?2u:0u) && s.retired==1 && s.counter_delta==increment && !s.initial_transition_unknown);
            CHECK(c.known[0x7a6] && c.value[0x7a6]==(unsigned char)(255+increment));
            CHECK(u32(c.value+0x688)==value && c.value[0x720]==0xa5 && c.apply_pending);
            if(old!=value)CHECK(c.known[0x2ba] && !c.value[0x2ba] && !s.clear2ba_pending);
            else CHECK(!c.known[0x2ba] && s.clear2ba_pending);
        }
    } else if(!strcmp(argv[1],"unknown-crossing")) {
        CHECK(!dispatch(make(0,0,1),&io));CHECK(!dispatch(make(1,0,2),&io));
        CHECK(!dispatch(make(0,0,3),&io));verify_retired(3);
        CHECK(snap().initial_transition_unknown && snap().counter_delta==2 && snap().central_pending==1);
        CHECK(!csnap().known[0x7a6]);
    } else if(!strcmp(argv[1],"reentrant")) {
        release_probe=1;record_probe=1;CHECK(!dispatch(make(2,0,13),&io));verify_retired(2);CHECK(logs==2);
    } else if(!strcmp(argv[1],"minimal")) {
        struct full_imaging_io minimal={.size=size,.source=source,.release=release};
        CHECK(!dispatch(make(2,0,13),&minimal));CHECK(!dispatch(make(2,0,17),&minimal));verify_retired(2);CHECK(!logs);
    } else if(!strcmp(argv[1],"free-failure")) {
        void *p=make(2,0,13);free_failure=1;CHECK(!dispatch(p,&io));free_failure=0;
        CHECK(active==1 && !snap().retired && snap().generation==1 && snap().central_pending==1);
        struct native_cp_background_remainder_snapshot r;CHECK(!native_cp_background_remainder_snapshot(NATIVE_CP_BACKGROUND_SID,0x4023,&r) && r.pending && r.request==(uintptr_t)p);
        void *q=make(2,0,17);CHECK(dispatch(q,&io)==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,q));
        int rc=123;CHECK(native_cp_background_release(0,p,release,record,&rc)==1 && rc==-1021 && active==1);
        CHECK(native_cp_background_release(NATIVE_CP_BACKGROUND_SID,p,release,record,&rc)==1 && !rc);verify_retired(1);
        q=make(2,0,18);CHECK(dispatch(q,&io)==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,q));CHECK(snap().generation==1);
    } else if(!strcmp(argv[1],"reject")) {
        for(unsigned n=0;n<=40;n++)if(n!=12) {
            void *p=make(2,0,13);header(p)->n=n;int rc=123,h=native_cp_background_dispatch(NATIVE_CP_BACKGROUND_SID,p,&io,1,&rc);
            CHECK(n<4?(!h && rc==123):(h && rc==-1020));CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));
        }
        for(unsigned k=0;k<11;k++) {
            unsigned char *p=make(2,0,13);struct full_imaging_io bad=io;unsigned dst=NATIVE_CP_BACKGROUND_SID;int rc=123;
            switch(k) {
            case 0:header(p)->source=0;break;case 1:header(p)->source=0x90030001;break;
            case 2:bad.source=NULL;break;case 3:bad.release=NULL;break;case 4:bad.size=NULL;break;
            case 5:p[0]=0;break;case 6:p[0]=13;break;case 7:dst=NATIVE_CP_CAPTURE_SID;break;
            default:break;
            }
            int h=native_cp_background_dispatch(dst,p,&bad,k!=8,k==9?NULL:&rc);
            if(k<4)CHECK(h && rc==-1020);else if(k==4)CHECK(h && rc==-1021);
            else if(k==10)CHECK(h && !rc);else CHECK(!h && rc==123);
            if(k!=10)CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));
        }
        verify_retired(1);CHECK(native_cp_background_4023_snapshot(NULL)==-1024);
    } else if(!strcmp(argv[1],"fork")) {
        CHECK(!dispatch(make(2,0,13),&io));pid_t child=fork();CHECK(child>=0);
        if(!child) {
            alarm(3);struct native_cp_background_4023_snapshot s,before;memset(&s,0xa5,sizeof s);before=s;
            CHECK(native_cp_background_4023_snapshot(&s)==-1021 && !memcmp(&s,&before,sizeof s));
            void *p=make(2,0,17);CHECK(dispatch(p,&io)==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));_exit(0);
        }
        int status;CHECK(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));verify_retired(1);
    } else if(!strcmp(argv[1],"aliases")) {
        unsigned char *a=make(2,0,13),*b=make(2,0,14),*c=make(2,0,15);
        /* Synthetic live-slot ownership while a release callback is in flight. */
        atomic_store(&remainder_request[6],(uintptr_t)a);atomic_store(&remainder_request[7],(uintptr_t)b);
        atomic_store(&remainder_request[0],(uintptr_t)c);
        unsigned char *all[]={a,b,c};for(unsigned k=0;k<3;k++) {
            all[k][2]=0x23;header(all[k])->n=12;CHECK(dispatch(all[k],&io)==-1021);
        }
        CHECK(!snap().generation);
        atomic_store(&remainder_request[6],0);atomic_store(&remainder_request[7],0);atomic_store(&remainder_request[0],0);
        for(unsigned k=0;k<3;k++)CHECK(!release(NATIVE_CP_BACKGROUND_SID,all[k]));
    } else if(!strcmp(argv[1],"overflow")) {
        for(unsigned k=0;k<2;k++) {
            config.generation=k?0:UINT32_MAX;parameter4023.generation=k?UINT32_MAX:0;
            void *p=make(2,0,13);struct native_cp_background_4023_snapshot s=snap();struct native_cp_background_config_snapshot c=csnap();
            CHECK(dispatch(p,&io)==-1021);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));
            struct native_cp_background_4023_snapshot t=snap();struct native_cp_background_config_snapshot d=csnap();CHECK(!memcmp(&s,&t,sizeof s) && !memcmp(&c,&d,sizeof c));
        }
    } else if(!strcmp(argv[1],"concurrent")) {
        pthread_t threads[8];for(unsigned i=0;i<8;i++)CHECK(!pthread_create(&threads[i],NULL,produce,NULL));
        for(unsigned i=0;i<8;i++)CHECK(!pthread_join(threads[i],NULL));
        CHECK(accepted>0 && accepted<=800);verify_retired(accepted);CHECK(frees==800 && logs==accepted && snap().central_generation==1);
    } else CHECK(0);
    CHECK(!active && !sends && !allocations);
    printf("{\"case\":\"%s\",\"frees\":%u,\"logs\":%u,\"central_delivered\":false,\"capture_verified\":false}\n",argv[1],(unsigned)frees,(unsigned)logs);
    return 0;
}
