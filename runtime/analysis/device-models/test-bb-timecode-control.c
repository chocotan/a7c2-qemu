/* SPDX-License-Identifier: MIT
 * Lab-only IO with allocation/size/source/liveness metadata. Including the owner
 * permits quiescent overflow and getter-corruption injection without test APIs.
 * The guard models a lab predecessor, NOT the original graph or CP RTOS. */
#include "bb-timecode-control.c"
#include <assert.h>
#include <stdlib.h>

struct message {unsigned int size,source,destination,alive;unsigned char data[16];};
static struct message input,probe,reuse_storage,*output;
static int allocation_observation;
static void *last_reply;
static unsigned char original_input[10],expected_reply[12];
static const char *test_case;
static unsigned int allocated,sent,input_frees,reply_frees,cleanups,reserves,unreserves,pred_calls;
static unsigned int callbacks,request_source_reads,reply_size_reads,alias_offset,short_variant;
static unsigned int committed_reentry,release_reentered,tamper_after_free;
static char events[128][3072],streams[128][768];
static unsigned int event_count,stream_count;
static int is(const char *s) {return !strcmp(test_case,s);}
static void prepare(unsigned int,unsigned int,unsigned int);
static int dispatch(void);
static void callback_snapshot(void) {
    struct full_bb_timecode_snapshot s;full_bb_timecode_control_snapshot(&s);callbacks++;
    if(atomic_load(&owner_pid)==(int)getpid())assert(s.owner_pid==(int)getpid());
}
static struct message *metadata(void *p) {
    if(p==input.data)return &input;
    if(p==probe.data)return &probe;
    assert(output && p==output->data);return output;
}
static unsigned int io_size(void *p) {
    callback_snapshot();struct message *m=metadata(p);assert(m->alive);
    if(output && m==output) {
        reply_size_reads++;
        if(is("allocation-short") && short_variant && reply_size_reads==2)m->size=11;
    }
    return m->size;
}
static unsigned int io_source(void *p) {
    callback_snapshot();struct message *m=metadata(p);assert(m->alive);
    if(output && m==output && is("receive-source-getter")) {
        struct full_bb_timecode_snapshot s;full_bb_timecode_control_snapshot(&s);
        if(s.queued || s.inflight)return m->source+1;
    }
    if(m==&input) {
        request_source_reads++;
        if(is("source-drift") && request_source_reads>=2)return m->source+1;
    }
    return m->source;
}
static unsigned int identity_refused_count;
static char identity_refused_line[3072];
static void io_record(const char *tag,const char *line) {
    if(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_IDENTITY_REFUSED ")) {
        callback_snapshot();assert(strlen(line)<sizeof identity_refused_line);
        strcpy(identity_refused_line,line);identity_refused_count++;return;
    }
    callback_snapshot();assert(strlen(tag)+strlen(line)<4096);
    if(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_EVENT ")) {
        assert(event_count<128 && strlen(line)<sizeof events[0]);
        strcpy(events[event_count++],line);
        if(is("state-readback") && !strncmp(line,"event=STATE_WRITTEN ",20)) {
            pthread_mutex_lock(&mutex);state.dfmode^=1;pthread_mutex_unlock(&mutex);
        }
        if(is("reply-tamper") && tamper_after_free && !strncmp(line,"event=REQUEST_FREE ",19)) {
            assert(output);output->data[11]=1;
        }
        if(is("log-reentry-new-generation") && !strncmp(line,"event=COMMIT ",13) && !committed_reentry) {
            committed_reentry=1;prepare(0x0402,1,0x8abcdef0u);assert(dispatch()==0);
        }
    } else {
        assert(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_BYTES "));
        assert(stream_count<128 && strlen(line)<sizeof streams[0]);strcpy(streams[stream_count++],line);
    }
}
static int io_allocate(unsigned int destination,void **p,unsigned int bytes,unsigned int kind) {
    callback_snapshot();assert(bytes==12 && kind==1 && destination==input.source);
    allocated++;assert(p && !*p && !output);
    if(is("allocation-null"))return 0;
    if(is("allocation-alias")){*p=input.data+alias_offset;return 0;}
    if(is("reuse-after-retired")) {
        assert(!reuse_storage.alive);memset(&reuse_storage,0,sizeof reuse_storage);output=&reuse_storage;
    } else {output=calloc(1,sizeof *output);assert(output);}
    output->size=is("allocation-short") && !short_variant?11:12;
    output->destination=destination;output->alive=1;last_reply=*p=output->data;
    int rc=is("allocation-error") || is("cleanup-fail")?-31:0;
    allocation_observation=full_bb_timecode_control_observe_allocate(destination,*p,bytes,kind,rc);
    assert(allocation_observation>=0);return rc;
}
static void io_set_source(void *p,unsigned int source) {
    callback_snapshot();struct message *m=metadata(p);assert(m==output && m->alive);
    assert(source==FULL_BB_TIMECODE_CONTROL_CP);
    if(!is("set-source"))m->source=source;
    if(is("request-tamper"))input.data[9]=1;
    if(is("reply-tamper") && !tamper_after_free)m->data[8]=1;
}
static int io_release(unsigned int destination,void *p) {
    callback_snapshot();struct message *m=metadata(p);assert(m->alive);
    if(m==&input) {
        input_frees++;assert(destination==FULL_BB_TIMECODE_CONTROL_CP);
        assert(!memcmp(m->data,original_input,10));
        if(is("request-free-fail"))return -41;
        m->alive=0;memset(m->data,0xa5,sizeof m->data);return 0;
    }
    assert(m==output && destination==m->destination);
    struct full_bb_timecode_snapshot s;full_bb_timecode_control_snapshot(&s);
    if(s.reply_received)reply_frees++;else cleanups++;
    if(is("cleanup-fail"))return -77;
    if(is("reply-free-fail") || is("inline-free-fail") || is("retained-alias-allocate"))return -49;
    if(is("release-reentry") && s.reply_received) {
        release_reentered++;int rc=123;
        extern const struct full_imaging_io lab_io;
        extern const struct full_bb_timecode_guard lab_guard;
        assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,probe.data,&lab_io,&lab_guard,1,&rc)==1);
        assert(rc==-EBUSY && probe.alive);
    }
    m->alive=0;memset(m->data,0xdd,sizeof m->data);output=NULL;
    if(m!=&reuse_storage)free(m);
    return 0;
}
static int io_send(unsigned int destination,void *p) {
    callback_snapshot();struct message *m=metadata(p);struct full_bb_timecode_snapshot s;
    full_bb_timecode_control_snapshot(&s);sent++;
    assert(m==output && m->alive && m->size==12 && m->source==FULL_BB_TIMECODE_CONTROL_CP);
    assert(destination==m->destination && s.request_freed && s.request_free_rc==0 && !input.alive);
    assert(!memcmp(m->data,expected_reply,12));
    if(is("receive-source-getter")) {
        assert(full_bb_timecode_control_observe_receive(destination,p,FULL_BB_TIMECODE_CONTROL_CP,12)==-EBADMSG);
        return -33;
    }
    if(is("inline-free") || is("inline-send-fail") || is("inline-free-fail")) {
        assert(full_bb_timecode_control_observe_receive(destination,p,m->source,m->size)==1);
        int rc=99;assert(full_bb_timecode_control_release_reply(destination,p,io_release,io_record,&rc)==1);
        assert(rc==(is("inline-free-fail")?-49:0));
        full_bb_timecode_control_snapshot(&s);
        assert(s.inflight && !s.ap_consumed && s.busy);
        if(!rc)assert(s.reply_freed && s.pending_commit && !s.live_reply);
    }
    return is("send-fail") || is("inline-send-fail")?-33:0;
}
const struct full_imaging_io lab_io={io_allocate,io_release,io_set_source,io_send,io_size,io_source,io_record};
static int guard_reserve(void) {
    callback_snapshot();reserves++;return is("reserve-fail")?-61:0;
}
static void guard_release(void) {
    callback_snapshot();struct full_bb_timecode_snapshot s;full_bb_timecode_control_snapshot(&s);
    assert(s.guard_held && s.busy);unreserves++;
}
static int guard_ready(void) {
    callback_snapshot();pred_calls++;
    if(is("pred-first") && pred_calls==1)return 0;
    if(is("pred-second") && pred_calls==2)return -62;
    return 1;
}
const struct full_bb_timecode_guard lab_guard={guard_reserve,guard_release,guard_ready};
static void prepare(unsigned int command,unsigned int value,unsigned int caller) {
    assert(!output);input=(struct message){.size=10,.source=caller,.destination=FULL_BB_TIMECODE_CONTROL_CP,.alive=1};
    const unsigned char wire[10]={0x0d,0x20,(unsigned char)command,4,10,0,1,0x80,(unsigned char)value,0};
    memcpy(input.data,wire,10);memcpy(original_input,wire,10);
    const unsigned char response[12]={0x0d,0x20,(unsigned char)(command-0x0400),0x14,12,0,1,0x80,0,0,0,0};
    memcpy(expected_reply,response,12);request_source_reads=reply_size_reads=0;
    probe=(struct message){.size=10,.source=0x80000099u,.alive=1};memcpy(probe.data,wire,10);
}
static int dispatch(void) {
    int rc=123;assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&lab_io,&lab_guard,1,&rc)==1);
    return rc;
}
static struct full_bb_timecode_snapshot snap(void) {
    struct full_bb_timecode_snapshot s;full_bb_timecode_control_snapshot(&s);return s;
}
static void consume(void) {
    struct full_bb_timecode_snapshot s=snap();assert(output && s.live_reply==output->data);
    assert(s.busy && !s.guard_held && s.queued && !s.ap_consumed && !s.receiver_tid);
    assert(full_bb_timecode_control_observe_receive(s.source,output->data,output->source,output->size)==1);
    s=snap();assert(s.receiver_tid==tid() && s.sender_tid==tid() && s.reply_received);
    int rc=123;void *p=output->data;
    assert(full_bb_timecode_control_release_reply(s.source,p,io_release,io_record,&rc)==1 && rc==0);
}
static void clean_success(uint64_t generation,unsigned int mask) {
    struct full_bb_timecode_snapshot s=snap();
    assert(s.generation==generation && s.applications==generation && s.known_mask==mask);
    assert(!s.busy && !s.guard_held && !s.faults && !s.inflight && !s.pending_commit);
    assert(s.ap_consumed && s.reply_received && s.reply_freed && s.request_freed && s.queued);
    assert(!s.retained_request && !s.live_reply && !s.retained_reply && !s.retained_cleanup);
    assert(s.send_rc==0 && s.request_free_rc==0 && s.reply_free_rc==0);
    assert(s.request_free_count==generation && s.reply_free_count==generation);
}
static void caller_owned(int rc) {
    assert(dispatch()==rc);struct full_bb_timecode_snapshot s=snap();
    assert(input.alive && !s.retained_request && !s.applications && !s.generation && !sent && !input_frees);
    assert(!s.faults && !s.busy && !s.guard_held && !output);
}
static uint64_t get64(const unsigned char *p) {
    uint64_t n=0;for(unsigned int i=0;i<8;i++)n|=(uint64_t)p[i]<<(8*i);return n;
}
static unsigned int get32(const unsigned char *p) {
    unsigned int n=0;for(unsigned int i=0;i<4;i++)n|=(unsigned int)p[i]<<(8*i);return n;
}
static void state_bytes(unsigned int a,unsigned int b,unsigned int c,uint64_t gen,unsigned int known) {
    unsigned char actual[48];read_state(actual);
    assert(get32(actual)==1 && get32(actual+4)==48 && get32(actual+8)==(unsigned int)getpid());
    assert(get32(actual+12)==known && get64(actual+16)==gen);
    assert(get32(actual+24)==a && get32(actual+28)==b && get32(actual+32)==c);
    assert(!get32(actual+36) && get64(actual+40)==gen && fnv(actual,48)==snap().state_fnv);
}
static unsigned int stage_count(const char *stage) {
    unsigned int n=0;size_t bytes=strlen(stage);
    for(unsigned int i=0;i<event_count;i++)if(!strncmp(events[i]+6,stage,bytes) && events[i][6+bytes]==' ')n++;
    return n;
}
static void order(unsigned int inline_send) {
    static const char *const normal[]={"BEGIN","STATE_WRITTEN","STATE_READBACK","REQUEST_FREE","REPLY_QUEUED","RECEIVE","REPLY_FREE","COMMIT"};
    static const char *const early[]={"BEGIN","STATE_WRITTEN","STATE_READBACK","REQUEST_FREE","RECEIVE","REPLY_FREE","REPLY_QUEUED","COMMIT"};
    assert(event_count==8 && stream_count==4);
    for(unsigned int i=0;i<8;i++) {
        const char *name=inline_send?early[i]:normal[i];
        assert(!strncmp(events[i],"event=",6) && !strncmp(events[i]+6,name,strlen(name)) && events[i][6+strlen(name)]==' ');
    }
    static const char *const kinds[]={"kind=request total=10 offset=0 bytes=10 raw=","kind=state_before total=48 offset=0 bytes=48 raw=",
        "kind=state_after total=48 offset=0 bytes=48 raw=","kind=reply total=12 offset=0 bytes=12 raw="};
    unsigned char decoded[48];
    for(unsigned int i=0;i<4;i++) {
        char *raw=strstr(streams[i],kinds[i]);assert(raw);raw+=strlen(kinds[i]);
        unsigned int n=i==0?10:i==3?12:48;
        for(unsigned int j=0;j<n;j++) {
            unsigned int v=999;assert(sscanf(raw+2*j,"%2x",&v)==1 && v<=255);decoded[j]=(unsigned char)v;
        }
        assert(raw[2*n]==' ');
        if(i==0)assert(!memcmp(decoded,original_input,10));
        if(i==1)assert(get64(decoded+16)==0 && get32(decoded+12)==0 && get64(decoded+40)==0);
        if(i==2)assert(get64(decoded+16)==1 && get32(decoded+12)==2 && get32(decoded+28)==1 && get64(decoded+40)==1);
        if(i==3)assert(!memcmp(decoded,expected_reply,12));
        char fingerprint[40];snprintf(fingerprint,sizeof fingerprint,"whole_fnv=%016" PRIx64,fnv(decoded,n));
        assert(strstr(streams[i],fingerprint));
    }
}
static void *foreign_receive(void *unused) {
    (void)unused;assert(output);
    assert(full_bb_timecode_control_observe_receive(output->destination,output->data,output->source,output->size)==-EPERM);return NULL;
}
static void *foreign_free(void *unused) {
    (void)unused;int rc=0;assert(output);
    assert(full_bb_timecode_control_release_reply(output->destination,output->data,io_release,io_record,&rc)==1 && rc==-EPERM);return NULL;
}
/* History cases use a bounded real lab pool, never host malloc address luck.
 * This allocator deliberately omits the observer: dispatch must observe its
 * actual return, while a foreign caller must invoke the hook explicitly. */
static struct message history_pool[RETIRED_REPLY_CAPACITY+1];
static unsigned int history_next,history_reuse=RETIRED_REPLY_CAPACITY+1;
static int history_allocate_rc,history_allocate_null,history_reserve_rc,history_ready_rc=1;
static int history_release_rc,history_inline,history_send_rc,history_check_aliases;
static unsigned int history_free_checks,history_record_checks,history_guard_checks;
static int history_has(void *p) {
    pthread_mutex_lock(&mutex);int found=retired_index(p)!=RETIRED_REPLY_CAPACITY;
    pthread_mutex_unlock(&mutex);return found;
}
static void history_duplicate(void *p) {
    unsigned int frees=reply_frees,cleanup=cleanups;int rc=123;
    assert(full_bb_timecode_control_release_reply(input.source,p,io_release,io_record,&rc)==1 && rc==-EALREADY);
    assert(reply_frees==frees && cleanups==cleanup);
}
static void history_busy_observation(void *p) {
    int saved_errno=errno;errno=EDOM;
    assert(full_bb_timecode_control_observe_allocate(input.source,p,12,1,0)==-EBUSY && errno==EDOM);
    errno=saved_errno;
}
static int history_allocate(unsigned int destination,void **p,unsigned int bytes,unsigned int count) {
    callback_snapshot();allocated++;
    assert(p && !*p && !output && bytes && bytes<=16 && count==1);
    if(history_allocate_null)return 0;
    unsigned int i=history_reuse;
    if(i==RETIRED_REPLY_CAPACITY+1)i=history_next++;
    history_reuse=RETIRED_REPLY_CAPACITY+1;
    assert(i<RETIRED_REPLY_CAPACITY+1 && !history_pool[i].alive);
    output=&history_pool[i];*output=(struct message){.size=bytes,.destination=destination,.alive=1};
    last_reply=*p=output->data;return history_allocate_rc;
}
static int history_release(unsigned int destination,void *p) {
    if(p==input.data) {
        if(history_check_aliases) {
            struct full_bb_timecode_snapshot s=snap();
            assert(s.retained_request==p && s.retained_reply==last_reply);
            history_busy_observation(p);history_busy_observation(last_reply);
        }
        return io_release(destination,p);
    }
    callback_snapshot();assert(output && output->alive && output->data==p && output->destination==destination);
    struct full_bb_timecode_snapshot s=snap();
    if(s.reply_received)reply_frees++;else cleanups++;
    if(s.retained_cleanup==p)history_busy_observation(p);
    if(history_release_rc)return history_release_rc;
    if(history_inline){history_busy_observation(p);history_free_checks++;}
    output->alive=0;memset(output->data,0xdd,sizeof output->data);output=NULL;
    if(history_inline){history_busy_observation(p);history_free_checks++;}
    return 0;
}
static void history_record(const char *tag,const char *line) {
    io_record(tag,line);
    if(history_inline && !strcmp(tag,"FUNCTIONAL_BB_TIMECODE_EVENT ") && !strncmp(line,"event=REPLY_FREE ",17)) {
        struct full_bb_timecode_snapshot s=snap();
        assert(s.reply_freed && s.pending_commit && s.busy && s.inflight && !s.ap_consumed);
        assert(history_has(last_reply));history_busy_observation(last_reply);history_record_checks++;
    }
}
static int history_send(unsigned int destination,void *p) {
    int rc=io_send(destination,p);assert(!rc);
    if(history_inline) {
        struct full_bb_timecode_snapshot s=snap();
        assert(full_bb_timecode_control_observe_receive(destination,p,FULL_BB_TIMECODE_CONTROL_CP,12)==1);
        rc=123;assert(full_bb_timecode_control_release_reply(destination,p,history_release,history_record,&rc)==1 && !rc);
        s=snap();assert(s.reply_freed && s.pending_commit && s.inflight && s.busy && !s.ap_consumed);
        history_busy_observation(p);history_duplicate(p);
    }
    return history_send_rc;
}
static int history_reserve(void) {
    callback_snapshot();reserves++;
    if(history_check_aliases)history_busy_observation(input.data);
    return history_reserve_rc;
}
static int history_ready(void) {callback_snapshot();pred_calls++;return history_ready_rc;}
static void history_unreserve(void) {
    guard_release();
    if(history_inline){history_busy_observation(last_reply);history_guard_checks++;}
}
static const struct full_imaging_io history_io={history_allocate,history_release,io_set_source,history_send,io_size,io_source,history_record};
static const struct full_bb_timecode_guard history_guard={history_reserve,history_unreserve,history_ready};
static int history_dispatch(void) {
    int rc=123;
    assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&history_io,&history_guard,1,&rc)==1);
    return rc;
}
static void history_prepare(void) {
    event_count=stream_count=0;prepare(0x0401,1,0x81234567u);
}
static void history_consume(void) {
    struct full_bb_timecode_snapshot s=snap();assert(output && s.live_reply==output->data);
    assert(s.busy && s.queued && !s.guard_held && !s.ap_consumed);
    assert(full_bb_timecode_control_observe_receive(s.source,output->data,output->source,12)==1);
    int rc=123;assert(full_bb_timecode_control_release_reply(s.source,last_reply,history_release,history_record,&rc)==1 && !rc);
}
static void *history_complete(void) {
    history_prepare();assert(history_dispatch()==0);void *p=last_reply;history_consume();
    clean_success(snap().generation,2);assert(history_has(p));return p;
}
static void run_history(void) {
    void *p=history_complete();
    if(is("history-reserve-fail") || is("history-pred-fail") || is("history-allocation-fail")) {
        if(is("history-reserve-fail"))history_reserve_rc=-61;
        if(is("history-pred-fail"))history_ready_rc=0;
        if(is("history-allocation-fail"))history_allocate_rc=-31;
        history_prepare();unsigned int freed=input_frees;
        assert(history_dispatch()==(history_reserve_rc?-61:history_ready_rc!=1?-ENODATA:-31));
        struct full_bb_timecode_snapshot s=snap();
        assert(input.alive && !memcmp(input.data,original_input,10) && input_frees==freed);
        assert(!s.busy && !s.faults && !s.guard_held && !s.retained_request && !output && s.generation==1);
        assert(s.transaction==2 && s.requests==2);history_duplicate(p);assert(history_has(p));
        if(is("history-allocation-fail")) {
            assert(cleanups==1);history_allocate_rc=0;history_allocate_null=1;
            history_prepare();assert(history_dispatch()==-ENOMEM && input.alive && !snap().busy && !snap().faults);
            history_duplicate(p);assert(history_has(p) && cleanups==1);
        }
    } else if(is("history-multiple")) {
        void *q=history_complete(),*r=history_complete();assert(p!=q && p!=r && q!=r);
        history_duplicate(p);history_duplicate(q);history_duplicate(r);
        assert(full_bb_timecode_control_observe_receive(input.source,p,FULL_BB_TIMECODE_CONTROL_CP,12)==-EALREADY);
        history_prepare();assert(history_dispatch()==0);struct full_bb_timecode_snapshot before=snap();
        history_duplicate(p);history_duplicate(q);history_duplicate(r);
        struct full_bb_timecode_snapshot after=snap();
        assert(!after.faults && after.busy && after.live_reply==before.live_reply && after.generation==before.generation);
        history_consume();clean_success(4,2);assert(history_has(p) && history_has(q) && history_has(r));
    } else if(is("history-reallocate-one")) {
        void *q=history_complete(),*r=history_complete(),*fresh=NULL;
        history_reuse=1;assert(history_allocate(0x90001111u,&fresh,7,1)==0 && fresh==q);
        history_duplicate(q); /* A fake allocator return alone did not call the observer. */
        assert(full_bb_timecode_control_observe_allocate(0x90001111u,fresh,7,1,-31)==0);
        assert(full_bb_timecode_control_observe_allocate(0x90001111u,fresh,7,2,0)==0);
        assert(full_bb_timecode_control_observe_allocate(0x90001111u,NULL,7,1,0)==0);
        history_duplicate(q);assert(history_has(q));
        int saved_errno=errno;errno=ERANGE;
        assert(full_bb_timecode_control_observe_allocate(0x90001111u,fresh,7,1,0)==1 && errno==ERANGE);
        assert(full_bb_timecode_control_observe_allocate(0x90001111u,fresh,7,1,0)==0 && errno==ERANGE);
        errno=saved_errno;
        int rc=123;assert(!full_bb_timecode_control_release_reply(0x90001111u,fresh,history_release,history_record,&rc) && rc==123);
        assert(!full_bb_timecode_control_observe_receive(0x90001111u,fresh,0,7));
        history_duplicate(p);history_duplicate(r);assert(!history_has(q) && history_has(p) && history_has(r));
        output->alive=0;output=NULL; /* Actual foreign pool free after hook declined. */
    } else if(is("history-own-reallocate")) {
        void *q=history_complete();history_reuse=0;history_prepare();assert(history_dispatch()==0 && last_reply==p);
        assert(!history_has(p) && history_has(q));history_duplicate(q);assert(!snap().faults);
        history_consume();clean_success(3,2);history_duplicate(p);history_duplicate(q);
        assert(history_has(p) && history_has(q));
    } else if(is("history-aliases")) {
        history_check_aliases=1;history_prepare();assert(history_dispatch()==0);void *q=last_reply;
        history_busy_observation(q);history_busy_observation(q);history_duplicate(p);assert(!snap().faults);
        assert(full_bb_timecode_control_observe_receive(input.source,q,FULL_BB_TIMECODE_CONTROL_CP,12)==1);
        history_release_rc=-49;int rc=123;
        assert(full_bb_timecode_control_release_reply(input.source,q,history_release,history_record,&rc)==1 && rc==-49);
        struct full_bb_timecode_snapshot before=snap();history_busy_observation(q);history_busy_observation(q);
        struct full_bb_timecode_snapshot after=snap();
        assert(after.faults && after.busy && after.retained_reply==q && after.live_reply==q);
        assert(after.reply_free_rc==before.reply_free_rc && !after.reply_freed && !after.ap_consumed);
        history_duplicate(p);assert(history_has(p) && !history_has(q));
    } else if(is("history-inline-observation")) {
        history_inline=1;history_prepare();assert(history_dispatch()==0);void *q=last_reply;
        clean_success(2,2);assert(history_has(q) && history_free_checks==2 && history_record_checks==1 && history_guard_checks==1);
        history_duplicate(p);history_duplicate(q);
        history_send_rc=-33;history_prepare();assert(history_dispatch()==-33);void *r=last_reply;
        struct full_bb_timecode_snapshot s=snap();
        assert(s.faults && s.busy && s.reply_freed && s.pending_commit && !s.ap_consumed && s.send_rc==-33);
        history_busy_observation(r);history_duplicate(r);history_duplicate(p);history_duplicate(q);
        assert(history_has(r) && history_has(p) && history_has(q));
        assert(history_free_checks==4 && history_record_checks==2 && history_guard_checks==2);
    } else if(is("history-capacity")) {
        assert(RETIRED_REPLY_CAPACITY==64u);
        for(unsigned int i=1;i<RETIRED_REPLY_CAPACITY;i++)assert(history_complete()==history_pool[i].data);
        history_prepare();unsigned char before[sizeof state];void *entries[RETIRED_REPLY_CAPACITY];
        void *old_request=request_identity,*old_reply=reply_identity;unsigned int old_slot=retired_slot;
        unsigned int old_allocated=allocated,old_reserves=reserves,old_unreserves=unreserves;
        pthread_mutex_lock(&mutex);memcpy(before,&state,sizeof state);memcpy(entries,retired_replies,sizeof entries);pthread_mutex_unlock(&mutex);
        assert(history_dispatch()==-ENOSPC && input.alive && !memcmp(input.data,original_input,10));
        pthread_mutex_lock(&mutex);assert(!memcmp(before,&state,sizeof state) && !memcmp(entries,retired_replies,sizeof entries));pthread_mutex_unlock(&mutex);
        assert(request_identity==old_request && reply_identity==old_reply && retired_slot==old_slot);
        assert(allocated==old_allocated && reserves==old_reserves && unreserves==old_unreserves && !output);
        for(unsigned int i=0;i<RETIRED_REPLY_CAPACITY;i++)history_duplicate(history_pool[i].data);
        void *fresh=NULL;history_reuse=0;assert(!history_allocate(input.source,&fresh,12,1) && fresh==p);
        assert(full_bb_timecode_control_observe_allocate(input.source,fresh,12,1,0)==1);
        output->alive=0;output=NULL;
        void *new_reply=history_complete();assert(new_reply==history_pool[RETIRED_REPLY_CAPACITY].data && !history_has(p));
        for(unsigned int i=1;i<=RETIRED_REPLY_CAPACITY;i++)assert(history_has(history_pool[i].data));
        clean_success(RETIRED_REPLY_CAPACITY+1,2);
    } else if(is("history-fork-before-lock")) {
        history_prepare();int original=atomic_load(&owner_pid),rc=123;unsigned int calls=callbacks;
        pthread_mutex_lock(&mutex);atomic_store(&owner_pid,original+1);
        assert(full_bb_timecode_control_owner_init()==-ECHILD && snap().faults);
        assert(history_dispatch()==-ECHILD && input.alive);
        assert(full_bb_timecode_control_observe_allocate(input.source,p,12,1,0)==-ECHILD);
        assert(full_bb_timecode_control_observe_receive(input.source,p,FULL_BB_TIMECODE_CONTROL_CP,12)==-ECHILD);
        assert(full_bb_timecode_control_release_reply(input.source,p,history_release,history_record,&rc)==1 && rc==-ECHILD);
        assert(callbacks==calls);atomic_store(&owner_pid,original);pthread_mutex_unlock(&mutex);
        history_duplicate(p);assert(history_has(p) && !snap().faults);
    } else {assert(!"unknown history case");}
    /* Fixture teardown after retained-alias assertions, never owner recovery. */
    if(output){output->alive=0;output=NULL;}
}
int main(int argc,char **argv) {
    assert(argc==2);test_case=argv[1];
    if(is("fork-before-mutex")) {
        prepare(0x0401,1,0x81234567u);assert(dispatch()==-ECHILD && input.alive && snap().faults);
        assert(!callbacks && !allocated && !reserves);
    }
    assert(full_bb_timecode_control_owner_init()==0);prepare(0x0401,1,0x81234567u);
    if(!strncmp(test_case,"history-",8)) {run_history();}
    else if(is("normal-three")) {
        state_bytes(0,0,0,0,0);
        for(unsigned int i=0;i<3;i++) {
            if(i)prepare(0x0400+i,i!=1,0x81234567u);else prepare(0x0400,1,0x81234567u);
            assert(dispatch()==0);assert(output && !memcmp(output->data,expected_reply,12));consume();
            clean_success(i+1,(1u<<(i+1))-1);state_bytes(1,0,i==2,i+1,(1u<<(i+1))-1);
            struct full_bb_timecode_snapshot s=snap();for(unsigned int j=0;j<3;j++)assert(s.command_generations[j]==(j<=i?j+1:0));
        }
    } else if(is("repeat")) {
        assert(dispatch()==0);struct full_bb_timecode_snapshot before=snap();
        assert(full_bb_timecode_control_owner_init()==-EALREADY);struct full_bb_timecode_snapshot after=snap();
        assert(before.generation==after.generation && before.live_reply==after.live_reply && after.busy);
        consume();prepare(0x0401,1,0x81234567u);assert(dispatch()==0);consume();
        clean_success(2,2);state_bytes(0,1,0,2,2);assert(snap().command_generations[1]==2);
    } else if(is("dynamic-callers") || is("source-boundary")) {
        if(is("source-boundary")) {
            const unsigned int bad[]={0,0x80000000u,0x90000000u,0xffffffffu};
            for(unsigned int i=0;i<4;i++){input.source=bad[i];caller_owned(-EINVAL);}
        }
        const unsigned int sources[]={0x80000001u,0x8fffffffu};
        for(unsigned int i=0;i<2;i++) {
            prepare(0x0401,i,sources[i]);assert(dispatch()==0);assert(output->destination==sources[i]);consume();clean_success(i+1,2);
        }
    } else if(is("disabled-unrelated")) {
        int rc=99;
        assert(!full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&lab_io,&lab_guard,0,&rc));
        assert(!full_bb_timecode_control_dispatch(0x90000001u,input.data,&lab_io,&lab_guard,1,&rc));
        input.data[2]=3;assert(!full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&lab_io,&lab_guard,1,&rc));
        assert(rc==99 && input.alive && !allocated && !reserves);
    } else if(is("malformed-size")) {
        const unsigned int sizes[]={4,8,9,11};
        for(unsigned int i=0;i<4;i++){input.size=sizes[i];caller_owned(-EINVAL);}
        int rc=99;input.size=3;assert(!full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&lab_io,&lab_guard,1,&rc) && rc==99);
    } else if(is("malformed-header")) {
        const unsigned int offsets[]={0,1,4,5,6,7};
        for(unsigned int i=0;i<6;i++){input.data[offsets[i]]^=1;caller_owned(-EINVAL);input.data[offsets[i]]^=1;}
    } else if(is("malformed-body")) {
        input.data[8]=2;caller_owned(-EINVAL);input.data[8]=1;input.data[9]=1;caller_owned(-EINVAL);
    } else if(is("missing-io")) {
        struct full_imaging_io bad=lab_io;bad.source=NULL;int rc=99;
        assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&bad,&lab_guard,1,&rc)==1 && rc==-EINVAL);
        assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&lab_io,&lab_guard,2,&rc)==1 && rc==-EINVAL);
        unsigned int before_calls=callbacks;
        assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&lab_io,&lab_guard,1,NULL)==1 && callbacks==before_calls);
        assert(!reserves && !allocated && input.alive);
    } else if(is("fork-before-mutex")) {
        int original=atomic_load(&owner_pid),rc=99;unsigned int before_calls=callbacks;
        pthread_mutex_lock(&mutex);atomic_store(&owner_pid,original+1);
        assert(full_bb_timecode_control_owner_init()==-ECHILD && snap().faults);
        assert(dispatch()==-ECHILD);
        assert(full_bb_timecode_control_observe_allocate(1,input.data,12,1,0)==-ECHILD);
        assert(full_bb_timecode_control_observe_receive(1,input.data,1,12)==-ECHILD);
        assert(full_bb_timecode_control_release_reply(1,input.data,io_release,io_record,&rc)==1 && rc==-ECHILD);
        full_bb_timecode_control_snapshot(NULL);assert(callbacks==before_calls);
        atomic_store(&owner_pid,original);pthread_mutex_unlock(&mutex);
    } else if(is("busy")) {
        assert(dispatch()==0);uint64_t generation=snap().generation;int rc=99;
        assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,probe.data,&lab_io,&lab_guard,1,&rc)==1 && rc==-EBUSY);
        assert(snap().generation==generation && snap().busy_count==1 && probe.alive && allocated==1);consume();clean_success(1,2);
    } else if(is("reserve-fail")) {
        caller_owned(-61);assert(reserves==1 && !unreserves && !allocated && snap().guard_failures==1);
    } else if(is("pred-first") || is("pred-second")) {
        caller_owned(is("pred-first")?-ENODATA:-62);assert(unreserves==1 && snap().guard_failures==1);
        assert(pred_calls==(is("pred-first")?1u:2u));
    } else if(is("overflow")) {
        struct full_bb_timecode_snapshot baseline=state;
        uint64_t *fields[]={&state.transaction,&state.generation,&state.requests,&state.applications,&state.request_free_count,
            &state.reply_free_count,&state.busy_count,&state.guard_failures,&state.command_generations[0],&state.command_generations[1],&state.command_generations[2]};
        for(unsigned int i=0;i<sizeof fields/sizeof *fields;i++) {
            *fields[i]=UINT64_MAX;assert(dispatch()==-EOVERFLOW);state=baseline;
        }
        assert(!allocated && !reserves && !input_frees && !sent);
    } else if(is("allocation-error")) {
        caller_owned(-31);assert(allocated==1 && cleanups==1);
    } else if(is("allocation-null")) {
        caller_owned(-ENOMEM);assert(allocated==1 && !cleanups);
    } else if(is("allocation-short")) {
        caller_owned(-EMSGSIZE);short_variant=1;prepare(0x0401,1,0x81234567u);caller_owned(-EBADMSG);assert(cleanups==2);
    } else if(is("allocation-alias")) {
        caller_owned(-EINVAL);alias_offset=1;caller_owned(-EINVAL);assert(!cleanups && input.alive);
    } else if(is("cleanup-fail")) {
        assert(dispatch()==-31);struct full_bb_timecode_snapshot s=snap();
        assert(s.allocate_rc==-31 && s.cleanup_rc==-77 && s.retained_cleanup==last_reply && s.faults && s.busy);
        assert(input.alive && !s.retained_request && !s.generation && !s.guard_held && cleanups==1);
    } else if(is("set-source") || is("source-drift") || is("request-tamper") || is("reply-tamper")) {
        caller_owned(-EBADMSG);assert(cleanups==1 && !sent);
        if(is("reply-tamper")) {
            tamper_after_free=1;prepare(0x0401,1,0x81234567u);assert(dispatch()==-EBADMSG);
            struct full_bb_timecode_snapshot s=snap();
            assert(s.generation==1 && s.faults && s.busy && s.request_freed && input_frees==1 && cleanups==2 && !sent);
        }
    } else if(is("state-readback")) {
        assert(dispatch()==-EBADMSG);struct full_bb_timecode_snapshot s=snap();
        assert(s.generation==1 && s.applications==1 && s.dfmode==0 && s.known_mask==2);
        assert(s.faults && s.busy && s.retained_request==input.data && !s.guard_held && !s.retained_reply && cleanups==1);
        assert(!input_frees && !sent && !stage_count("STATE_READBACK") && !stage_count("COMMIT"));
    } else if(is("send-fail")) {
        assert(dispatch()==-33);struct full_bb_timecode_snapshot s=snap();
        assert(s.send_rc==-33 && s.request_freed && s.faults && s.busy && !s.guard_held && !s.ap_consumed && !s.live_reply);
        assert(s.generation==1 && s.applications==1 && cleanups==1 && !stage_count("COMMIT"));
    } else if(is("request-free-fail")) {
        assert(dispatch()==-41);struct full_bb_timecode_snapshot s=snap();
        assert(s.request_free_rc==-41 && s.retained_request==input.data && s.faults && s.busy && !s.request_freed);
        assert(s.generation==1 && input_frees==1 && !sent && cleanups==1 && !stage_count("COMMIT"));
    } else if(is("receive-source-getter")) {
        assert(dispatch()==-33);struct full_bb_timecode_snapshot s=snap();
        assert(output && s.send_rc==-33 && s.faults && s.busy && !s.reply_received && s.retained_reply==last_reply);
        assert(!reply_frees && !cleanups && !stage_count("COMMIT"));
    } else if(is("receive-metadata") || is("receive-content") || is("wrong-receiver-thread")) {
        assert(dispatch()==0);
        if(is("receive-metadata"))assert(full_bb_timecode_control_observe_receive(input.source,last_reply,FULL_BB_TIMECODE_CONTROL_CP+1,12)==-EPERM);
        else if(is("receive-content")){output->data[8]=1;assert(full_bb_timecode_control_observe_receive(input.source,last_reply,output->source,12)==-EBADMSG);}
        else {pthread_t worker;assert(!pthread_create(&worker,NULL,foreign_receive,NULL));assert(!pthread_join(worker,NULL));}
        assert(snap().faults && snap().busy && snap().retained_reply==last_reply && !snap().reply_received && !reply_frees);
    } else if(is("free-before-receive") || is("wrong-free-destination") || is("wrong-free-thread")) {
        assert(dispatch()==0);int rc=99;
        if(is("free-before-receive"))assert(full_bb_timecode_control_release_reply(input.source,last_reply,io_release,io_record,&rc)==1 && rc==-EBUSY);
        else {
            assert(full_bb_timecode_control_observe_receive(input.source,last_reply,output->source,12)==1);
            if(is("wrong-free-destination"))assert(full_bb_timecode_control_release_reply(input.source+1,last_reply,io_release,io_record,&rc)==1 && rc==-EPERM);
            else {pthread_t worker;assert(!pthread_create(&worker,NULL,foreign_free,NULL));assert(!pthread_join(worker,NULL));}
        }
        assert(!reply_frees && snap().faults && snap().busy && !snap().ap_consumed && snap().retained_reply==last_reply);
    } else if(is("reply-free-fail")) {
        assert(dispatch()==0);assert(full_bb_timecode_control_observe_receive(input.source,last_reply,output->source,12)==1);
        int rc=99;assert(full_bb_timecode_control_release_reply(input.source,last_reply,io_release,io_record,&rc)==1 && rc==-49);
        struct full_bb_timecode_snapshot s=snap();assert(s.reply_free_rc==-49 && s.faults && s.retained_reply==last_reply && !s.ap_consumed);
        assert(reply_frees==1 && !s.reply_free_count && !stage_count("COMMIT"));
    } else if(is("duplicate")) {
        assert(dispatch()==0);void *p=last_reply;consume();unsigned int calls=callbacks;int rc=99;
        assert(full_bb_timecode_control_release_reply(input.source,p,io_release,io_record,&rc)==1 && rc==-EALREADY);
        assert(full_bb_timecode_control_observe_receive(input.source,p,FULL_BB_TIMECODE_CONTROL_CP,12)==-EALREADY);
        assert(!full_bb_timecode_control_observe_receive(input.source,probe.data,0,12));
        assert(!full_bb_timecode_control_release_reply(input.source,probe.data,io_release,io_record,&rc));
        assert(callbacks==calls+2 && reply_frees==1);clean_success(1,2);
    } else if(is("reuse-after-retired")) {
        /* This case uses a real one-slot pool: real free retires its metadata;
         * real next allocation reuses the same backing address even under ASAN. */
        assert(dispatch()==0);void *p=last_reply;consume();clean_success(1,2);int rc=99;
        assert(full_bb_timecode_control_release_reply(input.source,p,io_release,io_record,&rc)==1 && rc==-EALREADY);
        assert(full_bb_timecode_control_observe_allocate(input.source,p,12,1,-31)==0);
        assert(full_bb_timecode_control_observe_allocate(input.source,p,12,2,0)==0);
        assert(full_bb_timecode_control_release_reply(input.source,p,io_release,io_record,&rc)==1 && rc==-EALREADY);
        input.source=0x8abcd123u;void *fresh=NULL;
        assert(io_allocate(input.source,&fresh,12,1)==0 && fresh==p && allocation_observation==1);
        assert(full_bb_timecode_control_observe_allocate(input.source,fresh,12,1,0)==0);
        assert(full_bb_timecode_control_observe_receive(input.source,fresh,0,12)==0);
        rc=99;assert(full_bb_timecode_control_release_reply(input.source,fresh,io_release,io_record,&rc)==0 && rc==99);
        assert(output==&reuse_storage && output->alive && output->destination==input.source);
        /* Actual foreign pool free, after the timecode hook declines ownership. */
        output->alive=0;memset(output->data,0xbb,sizeof output->data);output=NULL;
        clean_success(1,2);assert(stage_count("COMMIT")==1 && reply_frees==1);
    } else if(is("live-alias-allocate")) {
        assert(dispatch()==0);struct full_bb_timecode_snapshot before=snap();
        /* Fault injection: a real allocator callback returning this live object
         * as a new success must be refused; no new allocation owns the alias. */
        assert(full_bb_timecode_control_observe_allocate(input.source,last_reply,12,1,0)==-EBUSY);
        assert(full_bb_timecode_control_observe_allocate(input.source,last_reply,12,1,0)==-EBUSY);
        struct full_bb_timecode_snapshot after=snap();
        assert(after.live_reply==before.live_reply && after.generation==before.generation && after.busy && !after.faults);
        consume();clean_success(1,2);
    } else if(is("retained-alias-allocate")) {
        assert(dispatch()==0);assert(full_bb_timecode_control_observe_receive(input.source,last_reply,output->source,12)==1);
        int rc=0;assert(full_bb_timecode_control_release_reply(input.source,last_reply,io_release,io_record,&rc)==1 && rc==-49);
        struct full_bb_timecode_snapshot before=snap();
        assert(full_bb_timecode_control_observe_allocate(input.source,last_reply,12,1,0)==-EBUSY);
        struct full_bb_timecode_snapshot after=snap();
        assert(after.faults && after.busy && after.retained_reply==before.retained_reply && after.reply_free_rc==-49 && !after.ap_consumed);
        assert(reply_frees==1 && !stage_count("COMMIT"));
    } else if(is("inline-free")) {
        assert(dispatch()==0);clean_success(1,2);assert(!output && reply_frees==1 && !cleanups);order(1);
    } else if(is("inline-send-fail")) {
        assert(dispatch()==-33);struct full_bb_timecode_snapshot s=snap();
        assert(!output && s.reply_freed && s.send_rc==-33 && s.reply_free_rc==0 && s.faults && s.busy && !s.ap_consumed);
        assert(reply_frees==1 && !cleanups && !stage_count("COMMIT") && !stage_count("REPLY_QUEUED"));
    } else if(is("inline-free-fail")) {
        assert(dispatch()==-49);struct full_bb_timecode_snapshot s=snap();
        assert(output && s.send_rc==0 && s.reply_free_rc==-49 && s.queued && s.faults && !s.ap_consumed && s.retained_reply==last_reply);
        assert(reply_frees==1 && !cleanups && !stage_count("COMMIT") && stage_count("REPLY_QUEUED")==1);
    } else if(is("release-reentry") || is("log-order")) {
        assert(dispatch()==0);consume();clean_success(1,2);assert(callbacks>20);
        if(is("release-reentry"))assert(release_reentered==1 && snap().busy_count==1);
        if(is("log-order"))order(0);
    } else if(is("log-reentry-new-generation")) {
        assert(dispatch()==0);consume();struct full_bb_timecode_snapshot s=snap();
        assert(committed_reentry && s.generation==2 && s.transaction==2 && s.busy && !s.ap_consumed && output);
        assert(strstr(events[7],"generation=1 ") && strstr(events[7],"transaction=1 "));
        consume();clean_success(2,6);assert(stage_count("COMMIT")==2);
    } else {assert(!"unknown case");}
    /* Fixture teardown only, after retained-pointer assertions; not recovery. */
    if(output!=&reuse_storage)free(output);
    output=NULL;
    printf("BB_TIMECODE_LAB_CASE_PASS case=%s capture_verified=0 physical_verified=0\n",test_case);return 0;
}
