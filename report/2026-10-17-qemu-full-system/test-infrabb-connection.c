/* SPDX-License-Identifier: MIT */
#include "infrabb-connection.h"
#include "infrabb-device.h"
#include "pin-registry-core.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Host fixture only; no guest, DMA, imaging or wire0104 evidence. */
struct packet {unsigned unit,source,bytes;unsigned char body[80];};
static struct packet *packet(void *p){return (struct packet *)((unsigned char *)p - offsetof(struct packet,body));}
static void *queued;
static unsigned int live,event6,post_reads,peer_reply_seen;
static unsigned char backing[PIN_CONTROL_CAPACITY];
static void put(unsigned char *p,unsigned x){for(unsigned i=0;i<4;i++)p[i]=(unsigned char)(x>>(i*8));}
static void *allocate(unsigned d,unsigned n){assert(n<=80);struct packet *p=calloc(1,sizeof *p);assert(p);p->unit=d;p->bytes=n;live++;return p->body;}
static int allocate_io(unsigned d,void **out,unsigned n,unsigned flags){(void)flags;*out=allocate(d,n);return 0;}
static int release(unsigned d,void *p){assert(packet(p)->unit==d && live);free(packet(p));live--;return 0;}
static void set_source(void *p,unsigned s){packet(p)->source=s;}
static unsigned size(void *p){return packet(p)->bytes;}
static unsigned source(void *p){return packet(p)->source;}
static int send(unsigned d,void *p){assert(d==0x81cf61ca && !queued);queued=p;return 0;}
static void record(const char *kind,const char *text){
    if(strstr(kind,"EVENT6_CONSUMED"))event6++;
    if(!strcmp(kind,"FULL_INFRABB_CONNECT_PEER_REPLY "))peer_reply_seen=1;
    if(!strcmp(kind,"FULL_INFRABB_POST_CONSUMED ")){fprintf(stderr,"%s%s\n",kind,text);assert(peer_reply_seen && strstr(text,"bytes_read=80"));post_reads++;}
}
static const struct full_imaging_io io={allocate_io,release,set_source,send,size,source,record};
static void *request(unsigned sid,unsigned bytes,unsigned type,unsigned dir,unsigned index){
    unsigned char *p=allocate(sid,bytes);set_source(p,0x81cf61ca);
    put(p,0x81cf61ca);put(p+4,0xa0a0a0a0);put(p+8,(bytes<<16)|1);put(p+12,0x18);put(p+16,bytes);
    put(p+24,bytes==48?0x1000:0x00011000);put(p+28,bytes==48?0x00020018:0x00020028);
    put(p+32,type);put(p+36,dir);put(p+40,index);
    if(bytes==64){put(p+44,FULL_INFRABB_CP);put(p+48,0);put(p+52,1);put(p+56,1);put(p+60,FULL_VEF_CP);}
    return p;
}
int main(void){
    for(unsigned mode=0;mode<4;mode++){
        assert(!live && !queued);peer_reply_seen=event6=post_reads=0;
        full_infrabb_connection_test_reset();full_infrabb_test_reset();full_vef_test_reset();pin_control_test_reset();
        memset(backing,0,sizeof backing);
        if(mode!=3)assert(!pin_control_bind_reserved(backing,sizeof backing,PIN_CONTROL_PHYSICAL));
        int rc=17;void *p=request(FULL_INFRABB_CP,48,0,2,1);
        assert(full_infrabb_dispatch(FULL_INFRABB_CP,p,&io,1,&rc) && !rc && queued);
        assert(full_infrabb_release_reply(0x81cf61ca,queued,release,record,&rc) && !rc);queued=0;
        p=request(FULL_VEF_CP,48,0,1,1);
        assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && !rc && queued);
        assert(full_vef_release_reply(0x81cf61ca,queued,release,record,&rc) && !rc);queued=0;
        if(mode==1 || mode==2){
            unsigned char current[20];assert(!full_vef_current_record(0,current,20));put(current+8,0x00020307);put(current+12,321);put(current+16,123);
            assert(!full_vef_update_current_record(0,current,20));
        }
        if(mode==2)pin_registry_test_set_state(full_infrabb_registry(),1,0);
        p=request(FULL_INFRABB_CP,64,0,2,1);
        assert(full_infrabb_connection_dispatch(FULL_INFRABB_CP,p,&io,1,&rc) && !rc && queued);
        struct scalar_connection_snapshot edge;full_infrabb_connection_snapshot(&edge);
        assert(edge.connections==1 && edge.direct_completion==1 && !edge.event6_consumed && !event6 && !edge.pending_event6 && edge.bb_request_flag);
        struct full_vef_snapshot s,v;full_infrabb_snapshot(&s);full_vef_snapshot(&v);
        assert(!s.pins[5].state && !v.pins[1].state && s.pins[5].peer[3]==FULL_VEF_CP && v.pins[1].peer[3]==FULL_INFRABB_CP);
        struct post_report post;full_infrabb_post_snapshot(&post);
        unsigned status=mode==0?POST_RELEASED_SAME:mode==1?POST_RELEASED_CHANGED:mode==2?POST_RETAINED_UNSUPPORTED:POST_ALLOC_FAILED;
        assert(edge.peer_post_status==status && post.status==status && !post.after.shares);
        if(mode!=3){assert(post_reads==1 && post.consumed_bytes==80 && post.format_valid);assert(post.format.width==(mode?321:1920));}
        if(mode==2){assert(post.refs.owners==1 && !post.refs.opens && post.retained);assert(!pin_control_release_transferred_owner(post.actual_handle));}
        assert(full_infrabb_connection_release(0x81cf61ca,queued,release,record,&rc) && !rc);queued=0;assert(!live);
        printf("INFRABB_DIRECT_POST mode=%u post=%u bytes=%u shares=%llu source=0 peer=0 native8001=0 event6=0 PASS\n",mode,post.status,post.consumed_bytes,post.after.shares);
    }
    full_infrabb_connection_test_reset();full_infrabb_test_reset();full_vef_test_reset();pin_control_test_reset();return 0;
}
