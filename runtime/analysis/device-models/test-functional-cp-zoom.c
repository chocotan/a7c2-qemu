/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-cp-zoom.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

static struct cp_parameter_state parameters, before;
static struct cp_start_state_guard data_guard;
static struct full_imaging_io io;
static struct native_cp_state_publication_guard guard;
static unsigned char packet[16]={5,0,1,0x40,0x4c,0,0,0x80,0,2,0,2};
static const char *scenario;
static unsigned int wire_size=12, metadata_source=CP_PARAMETER_BATCH_SOURCE;
static unsigned int frees, reserves, unreserves, ready_calls, size_calls, source_calls, logged;
static int held;
static int is(const char *name) { return !strcmp(scenario,name); }
static uint64_t hash(const unsigned char *p) {
    uint64_t h=UINT64_C(14695981039346656037);
    for(unsigned i=0;i<12;i++){h^=p[i];h*=UINT64_C(1099511628211);}return h;
}
static int forbidden_allocate(unsigned int d,void **p,unsigned int n,unsigned int a) {
    (void)d;(void)p;(void)n;(void)a;assert(!"4001 must never allocate ACK");return -EIO;
}
static int forbidden_send(unsigned int d,void *p) {
    (void)d;(void)p;assert(!"4001 must never send ACK");return -EIO;
}
static void forbidden_set_source(void *p,unsigned int s) {
    (void)p;(void)s;assert(!"4001 preserves original metadata");
}
static unsigned int size(void *p) {
    (void)p;size_calls++;
    if(is("mutated-size") && size_calls==2)return 13;
    return wire_size;
}
static unsigned int source(void *p) {
    (void)p;source_calls++;
    if(is("mutated-wire") && source_calls==1)packet[9]^=1;
    if(is("mutated-source") && source_calls==2)return UINT32_C(0x8000004c);
    if(is("post-store-wire") && source_calls==3)packet[9]^=1;
    return metadata_source;
}
static void fork_check(void) {
    pid_t pid=fork();int status;assert(pid>=0);
    if(!pid){
        struct functional_cp_zoom_snapshot s={0};functional_cp_zoom_snapshot(&s);
        assert(s.faults && !s.oneway_consumed);
        int rc=999;assert(functional_cp_zoom_dispatch(CP_PARAMETER_BATCH_TARGET,packet,&io,&guard,&data_guard,1,&rc)==1);
        assert(rc==-EXDEV);assert(functional_cp_zoom_owner_init(&parameters)<0);_exit(0);
    }
    assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));
}
static int release(unsigned int d,void *p) {
    assert(d==CP_PARAMETER_BATCH_TARGET && p==packet && held && (is("repeat")?frees<2:!frees));frees++;
    struct cp_parameter_zoom_readback data={0};
    assert(!cp_parameter_state_read_zoom(&parameters,&data_guard,&data));
    assert(data.config_consumed && data.known_mask==0x3ff && data.count==frees);
    assert(data.fields[0]==0 && data.fields[4]==packet[9] && data.fields[5]==0 && data.fields[9]==packet[11]);
    struct functional_cp_zoom_snapshot s={0};functional_cp_zoom_snapshot(&s);
    assert(s.busy && s.guard_held && s.config_consumed && !s.oneway_consumed && s.retained_request==packet);
    if(is("reentrant-free")) {
        int rc=0;assert(functional_cp_zoom_release(d,p,release,NULL,&rc)==1 && rc==-EBUSY);assert(frees==1);
    }
    if(is("reentrant-dispatch")) {
        int rc=0;assert(functional_cp_zoom_dispatch(d,p,&io,&guard,&data_guard,1,&rc)==1 && rc==-EBUSY);assert(frees==1);
    }
    if(is("fork-in-free"))fork_check();
    return is("free-fail")?-EIO:0;
}
static int reserve(void) { reserves++;if(is("guard-fail"))return -EBUSY;assert(!held);held=1;return 0; }
static void unreserve(void) { assert(held);held=0;unreserves++; }
static int ready(void) {
    ready_calls++;assert(held);
    if(is("guard-miss"))return 0;
    if(is("guard-lost") && ready_calls==2)return 0;
    if(is("post-store-guard") && ready_calls==3)return 0;
    return 1;
}
static void record(const char *tag,const char *text) {
    assert(!strcmp(tag,"FUNCTIONAL_CP_ZOOM "));
    assert(strstr(text,"image_offsets=69c,698,6a0,6a4 widths=4,1,4,1"));
    assert(strstr(text,"applied=0 published=0 generation=0 capture=0 ack_allocated=0 ack_sent=0"));
    assert(strstr(text,"physical_zoom_verified=0"));logged++;
    if(is("success"))puts(text);
}
static void init_parameters(void) {
    unsigned char batch[CP_PARAMETER_BATCH_BYTES];
    struct cp_parameter_import d={0};
    d.source_sequence=2;d.stage_fnv1a64=CP_PROPERTY_STAGE_FNV1A64;
    d.origin=CP_START_STATE_ORIGIN_HOST_TEST;d.properties_consumed=d.defaults_selected=1;
    assert(!cp_parameter_state_init(&parameters,true));
    memset(parameters.bytes,0xa5,sizeof(parameters.bytes));
    assert(!cp_parameter_state_consume_common_stores(&parameters));
    assert(!cp_parameter_state_consume_default_stores(&parameters,&d));
    memset(batch,0x9b,sizeof(batch));batch[0]=5;batch[2]=0x63;batch[3]=0x40;
    for(size_t i=0;i<CP_PARAMETER_BATCH_SLOTS;i++) {
        const struct cp_parameter_batch_slot *s=&cp_parameter_batch_slots[i];
        batch[s->offset]=5;batch[s->offset+2]=(unsigned char)s->opcode;batch[s->offset+3]=(unsigned char)(s->opcode>>8);
    }
    assert(cp_parameter_state_consume(&parameters,CP_PARAMETER_BATCH_SOURCE,CP_PARAMETER_BATCH_TARGET,
        batch,sizeof(batch))==CP_PARAMETER_STATE_PARTIAL);
    /* Source-owned unknown holes retain opaque bytes even next to zoom fields. */
    for(size_t i=0x699;i<0x69c;i++){parameters.bytes[i]=0xa5;parameters.known_mask[i/8]&=(unsigned char)~(1u<<(i%8));}
    memset(parameters.bytes+0x69c,0xff,8);
}
int main(int argc,char **argv) {
    assert(argc==2);scenario=argv[1];init_parameters();
    data_guard=(struct cp_start_state_guard){(uint32_t)getpid(),16,16,CP_START_STATE_ORIGIN_HOST_TEST,1};
    io=(struct full_imaging_io){forbidden_allocate,release,forbidden_set_source,forbidden_send,size,source,record};
    guard=(struct native_cp_state_publication_guard){reserve,unreserve,ready};
    if(!is("missing-owner"))assert(!functional_cp_zoom_owner_init(&parameters));
    if(is("init-repeat")){assert(functional_cp_zoom_owner_init(&parameters)==-EALREADY);return 0;}
    if(is("fork")){fork_check();return 0;}
    unsigned int destination=CP_PARAMETER_BATCH_TARGET;int enabled=1,result=999;
    void *request=packet;
    const struct native_cp_state_publication_guard *g=&guard;
    const struct cp_start_state_guard *dg=&data_guard;
    if(is("default-off"))enabled=0;
    if(is("enabled-two"))enabled=2;
    if(is("destination"))destination=0;
    if(is("type"))packet[0]=4;
    if(is("command"))packet[2]=2;
    if(is("short"))wire_size=11;
    if(is("tiny"))wire_size=3;
    if(is("long"))wire_size=13;
    if(is("source"))metadata_source=UINT32_C(0x8000004c);
    if(is("zero-source"))metadata_source=0;
    if(is("caller"))memset(packet+4,0,4);
    if(is("opaque")){packet[1]=0x9b;packet[4]=0x19;packet[5]=0xfe;packet[6]=0x7a;packet[7]=0x81;packet[9]=0xff;packet[11]=0x80;}
    if(is("drive"))packet[8]=1;
    if(is("trigger"))packet[10]=1;
    if(is("missing-source"))io.source=NULL;
    if(is("missing-free"))io.release=NULL;
    if(is("missing-guard"))g=NULL;
    if(is("missing-data-guard"))dg=NULL;
    if(is("alias-io-guard"))g=(const void *)&io;
    if(is("alias-data-guard"))dg=(const void *)&guard;
    if(is("guard-owner"))data_guard.owner_pid++;
    if(is("guard-torn"))data_guard.sequence_after++;
    if(is("guard-odd"))data_guard.sequence_before=data_guard.sequence_after=17;
    if(is("guard-quiescent"))data_guard.quiescent=0;
    if(is("guard-origin"))data_guard.source_origin=CP_START_STATE_ORIGIN_NONE;
    if(is("missing-common"))parameters.common_stores_consumed=0;
    if(is("missing-bootstrap"))parameters.default_stores_consumed=0;
    if(is("missing-bulk"))parameters.batch.staged=false;
    if(is("owner-pid"))parameters.batch.owner_pid++;
    if(is("alias")){memcpy(parameters.bytes,packet,12);request=parameters.bytes;}
    if(is("alias-guard"))dg=(const void *)&parameters;
    if(is("alias-result")){
        before=parameters;
        assert(!functional_cp_zoom_dispatch(destination,request,&io,g,dg,enabled,(void *)&parameters));
        assert(!memcmp(&parameters,&before,sizeof parameters));return 0;
    }
    before=parameters;
    int handled=functional_cp_zoom_dispatch(destination,request,&io,g,dg,enabled,&result);
    int success=is("success") || is("opaque") || is("free-fail") || is("reentrant-free") ||
        is("reentrant-dispatch") || is("fork-in-free") || is("duplicate") || is("repeat") || is("foreign-reuse") ||
        is("post-store-wire") || is("post-store-guard");
    struct functional_cp_zoom_snapshot s={0};functional_cp_zoom_snapshot(&s);
    assert(!held && !s.busy && !s.guard_held && !s.semantic_applied && !s.published && !s.generation && !s.capture);
    assert(!memcmp(&parameters.batch,&before.batch,sizeof parameters.batch));
    assert(!memcmp(parameters.config_consumed,before.config_consumed,sizeof parameters.config_consumed));
    assert(!memcmp(parameters.semantic_complete,before.semantic_complete,sizeof parameters.semantic_complete));
    if(success) {
        assert(handled==1 && result==0 && s.requests==1 && s.config_consumed==1 && logged==1);
        assert(s.original_request==packet && s.wire_fnv1a64==hash(s.wire));
        assert(s.sender_tid==syscall(SYS_gettid) && s.data.count==1 && s.data.known_mask==0x3ff);
        assert(s.metadata_source==CP_PARAMETER_BATCH_SOURCE && s.caller==s.data.caller);
        assert(s.data.fields[0]==0 && !s.data.fields[1] && !s.data.fields[2] && !s.data.fields[3]);
        assert(!s.data.fields[5] && !s.data.fields[6] && !s.data.fields[7] && !s.data.fields[8]);
        assert(s.data.fields[4]==s.wire[9] && s.data.fields[9]==s.wire[11]);
        int fault=is("free-fail") || is("post-store-wire") || is("post-store-guard");
        assert(s.faults==(unsigned int)fault && s.oneway_consumed==(unsigned int)!fault);
        assert(s.request_freed==(unsigned int)!fault && s.retained_request==(fault?packet:NULL));
        if(is("post-store-wire") || is("post-store-guard"))assert(!frees && !s.free_attempted && s.data_rc<0);
        else assert(frees==1 && s.free_attempted && s.free_tid==s.sender_tid && s.free_rc==(is("free-fail")?-EIO:0));
        for(size_t i=0x699;i<0x69c;i++)assert(parameters.bytes[i]==0xa5 && !(parameters.known_mask[i/8]&(1u<<(i%8))));
        unsigned int calls=size_calls+source_calls;
        if(fault) {
            assert(functional_cp_zoom_dispatch(destination,packet,&io,g,dg,enabled,&result)==1 && !result);
            assert(size_calls+source_calls==calls && frees==(s.free_attempted?1u:0u));
            assert(functional_cp_zoom_release(destination,packet,release,NULL,&result)==1 && result<0);
        } else {
            result=321;
            assert(!functional_cp_zoom_release(destination,packet,release,NULL,&result) && result==321);
            assert(functional_cp_zoom_dispatch(destination,packet,&io,g,dg,enabled,&result)==1 && result==-EALREADY);
            assert(frees==1 && parameters.zoom.count==1);
        }
        before=parameters;
        assert(!functional_cp_zoom_release(destination,packet,release,NULL,(void *)&parameters));
        assert(!memcmp(&parameters,&before,sizeof parameters));
        if(is("repeat")) {
            data_guard.sequence_before=data_guard.sequence_after=18;
            packet[4]=0x4d;packet[9]=0xff;packet[11]=0x80;
            assert(functional_cp_zoom_dispatch(destination,packet,&io,g,dg,enabled,&result)==1 && !result);
            functional_cp_zoom_snapshot(&s);
            assert(s.requests==2 && s.oneway_consumed && s.request_freed && !s.faults && !s.retained_request);
            assert(s.data.count==2 && s.data.source_sequence==18 && s.caller==UINT32_C(0x8000004d));
            assert(s.data.fields[4]==0xff && s.data.fields[9]==0x80 && frees==2 && logged==2);
        } else if(is("foreign-reuse")) {
            memset(packet,0x9a,12);result=321;
            assert(!functional_cp_zoom_release(UINT32_C(0x80020002),packet,release,NULL,&result) && result==321);
            assert(!functional_cp_zoom_dispatch(destination,packet,&io,g,dg,enabled,&result) && frees==1);
            assert(parameters.zoom.count==1);
        } else {
            unsigned char next[12];memcpy(next,s.wire,12);
            assert(functional_cp_zoom_dispatch(destination,next,&io,g,dg,enabled,&result)==1 && result<0);
            assert(parameters.zoom.count==1);
        }
    } else {
        assert(!frees && !s.requests && !s.config_consumed && !s.oneway_consumed && !s.retained_request);
        assert(!memcmp(&parameters,&before,sizeof parameters));
        if(is("default-off") || is("enabled-two") || is("destination") || is("type") || is("command") || is("tiny") || is("alias-io-guard") || is("alias-data-guard"))assert(!handled);
        else assert(handled==1 && result<0);
    }
    assert(reserves==unreserves+(is("guard-fail")?1u:0u));return 0;
}
