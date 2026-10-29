/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-state-publication.h"
#include <assert.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

/* Virtual source fixtures exercise actual consumers; never native evidence. */
struct message {unsigned int size,source;unsigned char body[];};
static struct message *envelope(void *p) {return (struct message *)((unsigned char *)p - offsetof(struct message,body));}
static unsigned int allocations,sends,frees,reservations,unlocks;
static int scenario,predecessor=1;
static void *ack_pointer,*notice_pointer;
static struct cp_start_state_data data;
static struct cp_start_state_guard source_guard;
static struct cp_state_snapshot full;
static void inspect(void) {struct native_cp_state_publication_snapshot s;native_cp_state_publication_snapshot(&s);assert(s.owner_pid==getpid());}
static void *message(unsigned int size,unsigned int source) {
    struct message *m=malloc(sizeof *m+size);assert(m);m->size=size;m->source=source;memset(m->body,0,size);return m->body;
}
static int allocate(unsigned int destination,void **p,unsigned int size,unsigned int option) {
    inspect();assert(destination==NATIVE_CP_STATE_PUBLICATION_AP && option==1);allocations++;
    if((scenario==5 && allocations==1) || (scenario==6 && allocations==3)) {*p=NULL;return -12;}
    *p=message(size,0);return 0;
}
static int release(unsigned int destination,void *p) {
    inspect();assert(destination==NATIVE_CP_STATE_PUBLICATION_AP || destination==NATIVE_CP_STATE_PUBLICATION_SID);frees++;
    if(scenario==8 && envelope(p)->body[0]==0)return -5;
    free(envelope(p));return 0;
}
static void set_source(void *p,unsigned int source) {inspect();envelope(p)->source=source;}
static unsigned int size(void *p) {inspect();return envelope(p)->size;}
static unsigned int get_source(void *p) {inspect();return envelope(p)->source;}
static void logger(const char *tag,const char *text) {inspect();assert(strstr(tag,"NATIVE_CP_STATE_PUBLICATION_"));assert(strstr(text,"business_applied=0 original_CP=0 EE=0 frame=0 capture=0"));}
static int send(unsigned int destination,void *p) {
    inspect();assert(destination==NATIVE_CP_STATE_PUBLICATION_AP);sends++;
    int is_notice=envelope(p)->size==CP_STATE_SNAPSHOT_BYTES;
    if(is_notice)notice_pointer=p;else ack_pointer=p;
    if(scenario==7 && sends==1)return -9;
    if(scenario==9 && sends==3)return -9;
    if(scenario==3) {
        int rc=-123;
        if(is_notice)assert(native_cp_state_publication_observe_receive(destination,p,NATIVE_CP_STATE_PUBLICATION_SID,CP_STATE_SNAPSHOT_BYTES)==1);
        assert(native_cp_state_publication_release(destination,p,release,logger,&rc)==1 && rc==0);
        if(is_notice)notice_pointer=NULL;else ack_pointer=NULL;
    }
    return 0;
}
static int reserve(void) {inspect();reservations++;return scenario==10?-16:0;}
static void unlock(void) {inspect();unlocks++;}
static int prior(void) {inspect();return predecessor;}
static int start_provider(void *context,struct cp_start_state_data *out,struct cp_start_state_guard *guard) {
    assert(context==&data);inspect();if(scenario==4)return -ENODATA;*out=data;*guard=source_guard;return 0;
}
static int full_provider(void *context,struct cp_state_snapshot *out) {
    assert(context==&data);inspect();*out=full;
    if(scenario==11)out->known[20]=0;
    if(scenario==12)out->generation.shadow_generation=out->generation.published_generation;
    if(scenario==13)out->bytes[CP_STATE_SNAPSHOT_LENS_OFFSET+8]=3;
    return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,get_source,logger};
static const struct native_cp_state_publication_guard guard={reserve,unlock,prior};
static struct native_cp_state_publication_providers providers={&data,start_provider,full_provider};
static void seed(void) {
    assert(cp_start_state_data_init(&data)==0);
    source_guard=(struct cp_start_state_guard){(uint32_t)getpid(),2,2,CP_START_STATE_ORIGIN_VIRTUAL_SOURCE,1};
    unsigned char history[7]={0},history_known[7];memset(history_known,1,sizeof history_known);
    struct cp_start_state_span h={history,history_known,sizeof history,sizeof history_known};
    assert(cp_start_state_data_consume_event(&data,&source_guard,CP_START_STATE_EVENT_HISTORY,&h)==0);
    unsigned char lif[CP_START_STATE_LIF_BYTES]={0},lk[CP_START_STATE_LIF_BYTES];
    unsigned char bank[CP_START_STATE_OVERRIDE_BYTES]={0},bk[CP_START_STATE_OVERRIDE_BYTES];
    memset(lk,1,sizeof lk);memset(bk,1,sizeof bk);lif[0x81]=0x62;lif[0x82]=1;lif[0x128]=3;
    struct cp_start_state_span l={lif,lk,sizeof lif,sizeof lk},b={bank,bk,sizeof bank,sizeof bk};
    assert(cp_start_state_data_consume_lif(&data,&source_guard,&l,&b,NULL)==0);
    unsigned char property[5]={0,0,0,0,2},pk[5]={1,1,1,1,1};
    struct cp_start_state_span p={property,pk,sizeof property,sizeof pk};
    assert(cp_start_state_data_consume_property(&data,&source_guard,CP_START_STATE_PROPERTY_ID,&p)==0);
    unsigned char adj[0x31]={0},ak[0x31];memset(ak,1,sizeof ak);
    adj[0x26]=0xff;adj[0x28]=0x80;adj[0x2a]=0x0a;adj[0x2c]=1;
    struct cp_start_state_span a={adj,ak,sizeof adj,sizeof ak};
    assert(cp_start_state_data_consume_adj(&data,&source_guard,&a)==0);
    struct cp_start_state_span empty={NULL,NULL,0,0};
    assert(cp_start_state_data_consume_event(&data,&source_guard,CP_START_STATE_EVENT_FOURTH_READ,&empty)==0);
    memset(&full,0,sizeof full);memset(full.known,1,sizeof full.known);full.bytes[0]=6;full.bytes[2]=0x40;full.bytes[3]=0x20;
    for(unsigned int i=0;i<CP_FULL_STATE_SNAPSHOT_BLOCKS;i++) {
        const struct cp_full_state_snapshot_block *s=&cp_full_state_snapshot_blocks[i];
        full.bytes[s->offset]=6;full.bytes[s->offset+2]=(unsigned char)s->command;full.bytes[s->offset+3]=(unsigned char)(s->command>>8);
    }
    full.bytes[CP_STATE_SNAPSHOT_LENS_OFFSET+8]=4;
    full.bytes[CP_STATE_SNAPSHOT_APERTURE_OFFSET+8]=0x90;full.bytes[CP_STATE_SNAPSHOT_APERTURE_OFFSET+9]=1;
    full.generation=(struct cp_state_snapshot_generation){CP_STATE_SNAPSHOT_PUBLISHED_BYTES,7,7,0};
}
static void *request(int mode) {
    unsigned int length=mode?12:24;unsigned char *p=message(length,NATIVE_CP_STATE_PUBLICATION_AP);
    p[0]=mode?5:0;p[2]=mode?0x73:scenario==2?0:3;p[3]=mode?0x40:0x30;
    p[4]=0x78;p[5]=0x56;p[6]=0x34;p[7]=0x12;if(mode)p[8]=1;return p;
}
static int dispatch(void *p,int enabled,int *result) {
    return native_cp_state_publication_dispatch(NATIVE_CP_STATE_PUBLICATION_SID,p,&io,&guard,&providers,enabled,result);
}
static void free_ack(void) {
    if(ack_pointer) {int rc=-1;assert(native_cp_state_publication_release(NATIVE_CP_STATE_PUBLICATION_AP,ack_pointer,release,logger,&rc)==1 && !rc);ack_pointer=NULL;}
}
static void *foreign_ack_thread(void *unused) {
    (void)unused;int rc=123;
    assert(native_cp_state_publication_release(NATIVE_CP_STATE_PUBLICATION_AP,ack_pointer,release,logger,&rc)==1 && rc==-EPROTO);
    return NULL;
}
static void *receive_thread(void *unused) {
    (void)unused;assert(native_cp_state_publication_observe_receive(NATIVE_CP_STATE_PUBLICATION_AP,notice_pointer,NATIVE_CP_STATE_PUBLICATION_SID,CP_STATE_SNAPSHOT_BYTES)==1);
    int rc=-1;assert(native_cp_state_publication_release(NATIVE_CP_STATE_PUBLICATION_AP,notice_pointer,release,logger,&rc)==1 && rc==0);notice_pointer=NULL;return NULL;
}
int main(int argc,char **argv) {
    assert(argc==2);scenario=atoi(argv[1]);assert(native_cp_state_publication_owner_init()==0);seed();
    int result=321;void *p=request(0);
    if(scenario==14) {
        pid_t child=fork();assert(child>=0);
        if(!child) {int rc=123;assert(dispatch(p,1,&rc)==1 && rc==-EXDEV);_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
        free(envelope(p));return 0;
    }
    if(scenario==17) {
        ((unsigned char *)p)[8]=1;assert(dispatch(p,1,&result)==1 && result<0 && !allocations && !sends);free(envelope(p));return 0;
    }
    if(scenario==18)predecessor=0;
    if(scenario==0) {assert(!dispatch(p,0,&result) && result==321 && !allocations);free(envelope(p));return 0;}
    if(scenario==10 || scenario==4 || scenario==5 || scenario==18) {
        assert(dispatch(p,1,&result)==1 && result<0 && !sends);
        struct native_cp_state_publication_snapshot s;native_cp_state_publication_snapshot(&s);assert(!s.leases[0].pointer && !s.start_requests);
        free(envelope(p));assert(!reservations || unlocks==(scenario==10?0u:1u));return 0;
    }
    assert(dispatch(p,1,&result)==1 && result==0);
    struct native_cp_state_publication_snapshot s;native_cp_state_publication_snapshot(&s);
    if(scenario==7 || scenario==8) {
        assert(s.faults && !s.start_complete);
        if(scenario==8) {scenario=1;free(envelope(p));free_ack();}
        else free(envelope(p));
        return 0;
    }
    if(scenario==16) {
        pthread_t thread;assert(!pthread_create(&thread,NULL,foreign_ack_thread,NULL));assert(!pthread_join(thread,NULL));
        native_cp_state_publication_snapshot(&s);assert(s.faults && !s.start_complete);free_ack();return 0;
    }
    if(ack_pointer) {
        const unsigned char *a=ack_pointer;assert(envelope(ack_pointer)->size==16 && a[0]==1 && a[2]==(scenario==2?0:3) && a[3]==0x30);
        assert(a[4]==0x78 && a[8]==0 && a[9]==0xf0 && a[12]==1 && a[13]==1 && a[14]==1 && a[15]==1);
    }
    free_ack();native_cp_state_publication_snapshot(&s);assert(s.start_complete && s.start_data_known_mask==15 && !s.shadow_generation);
    p=request(1);result=999;assert(dispatch(p,1,&result)==1);
    if(scenario==6 || scenario==11 || scenario==12 || scenario==13) {
        assert(result<0);native_cp_state_publication_snapshot(&s);assert(!s.mode1_requests && !s.shadow_generation && !s.leases[2].pointer);
        free(envelope(p));return 0;
    }
    assert(result==0);free_ack();native_cp_state_publication_snapshot(&s);
    if(scenario==9) {assert(s.faults && !s.mode1_complete && !s.shadow_generation);free(envelope(p));return 0;}
    if(scenario==15) {
        int rc=123;assert(native_cp_state_publication_release(NATIVE_CP_STATE_PUBLICATION_AP,notice_pointer,release,logger,&rc)==1 && rc==-EPROTO);
        native_cp_state_publication_snapshot(&s);assert(s.faults && !s.shadow_generation && !s.notification_ap_consumed);
        free(envelope(notice_pointer));return 0;
    }
    if(scenario!=3) {assert(s.notification_queued && !s.notification_ap_consumed && !s.shadow_generation);
        pthread_t t;assert(!pthread_create(&t,NULL,receive_thread,NULL));assert(!pthread_join(t,NULL));}
    native_cp_state_publication_snapshot(&s);assert(s.mode1_complete && s.notification_ap_consumed && s.shadow_generation==7 && s.published_generation==7);
    assert(s.leases[4].consumed && s.leases[4].received && !s.leases[4].pointer && !s.business_applied && !s.original_cp && !s.ee && !s.frame && !s.capture);
    assert(reservations==unlocks && !s.busy && !s.guard_held && !s.faults);
    puts("PASS source-backed data publication fixture, no native CP or capture claim");return 0;
}
