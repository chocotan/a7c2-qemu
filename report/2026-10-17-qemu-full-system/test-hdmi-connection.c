/* SPDX-License-Identifier: MIT */
/* Host test for the fourth (PinMem HDMIVIDEO -> HDMI VIDEO) and fifth
 * (ADF AUDIO -> HDMI AUDIO) captured edges on F's own peer engine. */
#define _GNU_SOURCE
#include "pin-registry-core.h"
#include "pinmem-device.h"
#include "adf-device.h"
#include "hdmi-pin-device.h"
#include "hdmi-connection.h"
#include "adf-audio-connection.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct message {unsigned int owner,bytes,source;unsigned char data[];};
static void *live[32],*sent[16];
static unsigned int send_fail,release_fail,alloc_fail,allocs,sends;
static int log_count;
static int logs(void){return log_count;}

static struct message *head(void *p){return (struct message *)((unsigned char *)p-sizeof(struct message));}
static int allocate(unsigned int id,void **out,unsigned int n,unsigned int wait){
    assert(wait==1);allocs++;
    if(alloc_fail)return -57;
    struct message *m=calloc(1,sizeof *m+n);assert(m);
    m->owner=id;m->bytes=n;m->source=id;*out=m->data;
    for(unsigned int i=0;i<32;i++)if(!live[i]){live[i]=*out;return 0;}
    abort();
}
static int release(unsigned int id,void *p){
    if(!(p && head(p)->owner==id)){fprintf(stderr,"BAD RELEASE want=%#x got=%#x p=%p\n",id,p?head(p)->owner:0u,p);abort();}
    if(release_fail)return -58;
    for(unsigned int i=0;i<32;i++)if(live[i]==p){live[i]=0;free(head(p));return 0;}
    abort();
}
static unsigned int size(void *p){return head(p)->bytes;}
static unsigned int source(void *p){return head(p)->source;}
static void set_source(void *p,unsigned int id){head(p)->source=id;}
static int send(unsigned int id,void *p){
    assert(head(p)->owner==id && sends<16);sends++;
    if(send_fail)return -77;
    sent[sends-1]=p;return 0;
}
static void record(const char *kind,const char *line){(void)kind;(void)line;log_count++;}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static const unsigned int D=0x81cf61c2;

static void reset_all(void){
    for(unsigned int i=0;i<32;i++)if(live[i]){free(head(live[i]));live[i]=0;}
    memset(sent,0,sizeof sent);send_fail=release_fail=alloc_fail=0;allocs=sends=0;log_count=0;
    full_pinmem_test_reset();full_adf_test_reset();full_hdmi_pin_test_reset();
    full_hdmi_connection_test_reset();full_adf_audio_connection_test_reset();
    /* A cold owner initializes every pin at state 1 on its first dispatch; the
     * test drives that constructor through the explicit test hook instead. */
    full_pinmem_test_set_state(0,1);full_adf_test_set_state(0,1);full_hdmi_pin_test_set_state(0,1);
}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
/* Build the captured 64 B Connect: envelope + S group + P group. */
static void *connect_request(const unsigned int s[4],const unsigned int p[4]){
    void *m=0;assert(!allocate(s[3],&m,64,1));unsigned char *b=m;
    memset(b,0,64);put32(b,D); /* outer reply SID, as captured */put32(b+4,0xa0a0a0a0);put16(b+8,1);put16(b+10,64);
    put32(b+12,24);put32(b+16,64);put16(b+24,0x1000);put16(b+26,1);put16(b+28,40);put16(b+30,2);
    for(unsigned int i=0;i<4;i++){put32(b+32+4*i,s[i]);put32(b+48+4*i,p[i]);}
    set_source(m,D);return m;
}
static const unsigned int S4[4]={4,2,0,0x90590818},P4[4]={4,1,0,0x909a015a};
static const unsigned int S5[4]={5,2,0,0x9058003f},P5[4]={5,1,0,0x909a015a};

static void run_edge(int edge){
    const unsigned int *S=edge==4?S4:S5,*P=edge==4?P4:P5;
    unsigned int dst=edge==4?0x90590818u:0x9058003fu;
    void *request=connect_request(S,P);int rc=123;
    int handled=edge==4?full_hdmi_connection_dispatch(dst,request,&io,1,&rc)
                       :full_adf_audio_connection_dispatch(dst,request,&io,1,&rc);
    assert(handled==1 && rc==0 && logs()>0);
    assert(sends==1 && allocs==4);
    void *reply=sent[0];assert(reply && size(reply)==56 && source(reply)==(edge==4?0x90590818u:0x9058003fu));
    /* Accepted requests are consumed by the edge, with a separate queued reply. */
    int frc=123;
    int claimed=edge==4?full_hdmi_connection_release(D,reply,release,record,&frc)
                       :full_adf_audio_connection_release(D,reply,release,record,&frc);
    assert(claimed==1 && !frc);
    struct scalar_connection_snapshot snap;
    if(edge==4)full_hdmi_connection_snapshot(&snap);else full_adf_audio_connection_snapshot(&snap);
    assert(snap.started && snap.connections==1 && snap.event6_consumed && snap.native_reply_frees==1 &&
           snap.waiter_frees==1 && !snap.faults && !snap.pending_event6);
    /* Each edge owns exactly one shared byte. */
    assert(full_hdmi_pin_video_connected()==(edge==4));
    assert(full_hdmi_pin_audio_connected()==(edge==5));
}

int main(void){
    reset_all();run_edge(4);
    puts("HDMI_CONNECT_FOUR_FRAMES_EVENT6_AND_VIDEO_BYTE_PASS");
    reset_all();run_edge(5);
    puts("ADF_AUDIO_CONNECT_FOUR_FRAMES_EVENT6_AND_AUDIO_BYTE_PASS");

    /* The other edge's exact pair is not claimed by this dispatcher. */
    reset_all();{void *q=connect_request(S5,P5);int rc=7;unsigned int before=allocs;
        assert(!full_hdmi_connection_dispatch(S5[3],q,&io,1,&rc) && rc==7 && allocs==before);
        assert(!release(S5[3],q));}
    reset_all();{void *q=connect_request(S4,P4);int rc=7;unsigned int before=allocs;
        assert(!full_adf_audio_connection_dispatch(S4[3],q,&io,1,&rc) && rc==7 && allocs==before);
        assert(!release(S4[3],q));}
    /* Wrong destination, wrong length and a 48 B Get are not claimed. */
    reset_all();{void *q=connect_request(S4,P4);int rc=7;
        assert(!full_hdmi_connection_dispatch(0x9058003fu,q,&io,1,&rc) && rc==7);
        assert(!release(S4[3],q));}
    reset_all();{void *q=connect_request(S4,P4);int rc=7;
        assert(!full_hdmi_connection_dispatch(S4[3],q,&io,0,&rc) && rc==7);
        assert(!release(S4[3],q));}
    puts("HDMI_AUDIO_EDGES_REJECT_FOREIGN_PAIR_DESTINATION_AND_DISABLED_PASS");

    /* Repeat is refused after the first edge committed. */
    reset_all();{
        void *first=connect_request(S4,P4);int rc=123;
        assert(full_hdmi_connection_dispatch(S4[3],first,&io,1,&rc)==1 && !rc);
        void *second=connect_request(S4,P4);rc=123;
        assert(full_hdmi_connection_dispatch(S4[3],second,&io,1,&rc)==1 && rc==-1021);
        assert(!release(S4[3],second));  /* refused: still caller-owned */
        /* first was consumed by the committed edge and must not be freed again */
        struct scalar_connection_snapshot s;full_hdmi_connection_snapshot(&s);
        assert(s.connections==1 && !s.faults); /* a repeat is refused, not a fault */
    }
    puts("HDMI_CONNECT_REPEAT_REJECTED_PASS");

    /* Allocation and send failures stay caller-owned and mark a fault. */
    reset_all();{void *q=connect_request(S4,P4);int rc=123;alloc_fail=1;
        assert(full_hdmi_connection_dispatch(S4[3],q,&io,1,&rc)==1 && rc==-1021);
        alloc_fail=0;assert(!release(S4[3],q));}
    reset_all();{void *q=connect_request(S5,P5);int rc=123;send_fail=1;
        assert(full_adf_audio_connection_dispatch(S5[3],q,&io,1,&rc)==1 && rc==-1021);
        send_fail=0;assert(!release(S5[3],q));}
    puts("HDMI_AUDIO_CONNECT_FAILURES_RETAIN_CALLER_OWNERSHIP_PASS");
    reset_all();return 0;
}
