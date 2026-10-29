/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "hdmi-device.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

struct message { unsigned int owner, source, bytes, live;unsigned char data[32]; } pool[16];
static void *queued,*last_reply;
static int alloc_error,send_error,free_error,alias_allocate;
static void *alias;
static unsigned int requests_freed,replies_freed,allocations;
static unsigned int expected_rate_selector,expected_rate_value;
static struct {
    pthread_mutex_t mutex;
    pthread_cond_t condition;
    int active,waiting,freed,reused;
    void *old;
    unsigned int destination,command,value;
    int resolution_test;
    unsigned char resolution[6];
} race={.mutex=PTHREAD_MUTEX_INITIALIZER,.condition=PTHREAD_COND_INITIALIZER};
static struct message *message(void *p) {
    for (unsigned int i=0;i<16;i++) if (pool[i].data==p) return &pool[i];
    assert(0);return 0;
}
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int wait) {
    assert(wait==1 && bytes<=32);allocations++;
    if (alias_allocate) { *out=alias;return 0; }
    if (alloc_error) { *out=0;return alloc_error; }
    if (race.active && owner==race.destination) {
        pthread_mutex_lock(&race.mutex);
        race.waiting=1;pthread_cond_broadcast(&race.condition);
        while (!race.freed) assert(!pthread_cond_wait(&race.condition,&race.mutex));
        struct message *m=message(race.old);assert(!m->live);
        *m=(struct message){.owner=owner,.bytes=bytes,.live=1};*out=m->data;
        race.reused=1;pthread_cond_broadcast(&race.condition);
        pthread_mutex_unlock(&race.mutex);return 0;
    }
    for (unsigned int i=0;i<16;i++) if (!pool[i].live) {
        pool[i]=(struct message){.owner=owner,.bytes=bytes,.live=1};*out=pool[i].data;return 0;
    }
    assert(0);return -1;
}
static int release(unsigned int owner,void *p) {
    struct message *m=message(p);assert(m->live && m->owner==owner);
    if (free_error) return free_error;
    if (race.active && p==race.old && owner!=race.destination) {
        pthread_mutex_lock(&race.mutex);
        m->live=0;replies_freed++;race.freed=1;pthread_cond_broadcast(&race.condition);
        /* Hand this exact address to the allocator before real free returns.
         * The module must still clear the old lease before A can commit. */
        while (!race.reused) assert(!pthread_cond_wait(&race.condition,&race.mutex));
        pthread_mutex_unlock(&race.mutex);return 0;
    }
    m->live=0;
    if (owner==FULL_HDMI_CP) { memset(m->data,0xdd,sizeof m->data);requests_freed++; }
    else replies_freed++;
    return 0;
}
static unsigned int size(void *p) { return message(p)->bytes; }
static unsigned int source(void *p) { return message(p)->source; }
static void set_source(void *p,unsigned int src) { message(p)->source=src; }
static int send(unsigned int dst,void *p) {
    struct message *m=message(p);assert(m->live && m->owner==dst && m->source==FULL_HDMI_CP);
    if (send_error) return send_error;
    assert(!queued);queued=p;return 0;
}
static void record(const char *tag,const char *line) {
    if (!strcmp(tag,"FULL_HDMI_COMMIT ") && strstr(line,"command=0x117 ")) {
        char expected[72];snprintf(expected,sizeof expected,"selector=%u rate=%u ",expected_rate_selector,expected_rate_value);
        assert(strstr(line,expected) && strstr(line,"dp_applied=0"));
    }
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static struct full_hdmi_snapshot snapshot(void) { struct full_hdmi_snapshot s;full_hdmi_snapshot(&s);return s; }
static void reset(void) {
    full_hdmi_test_reset();memset(pool,0,sizeof pool);queued=last_reply=alias=0;
    alloc_error=send_error=free_error=alias_allocate=0;requests_freed=replies_freed=allocations=0;
}
static void *request(unsigned int command,unsigned int value,unsigned int sid) {
    unsigned char *p=0;unsigned int length=(command==0x20a || command==0x201)?8:command==0x101?16:12;
    assert(!allocate(FULL_HDMI_CP,(void **)&p,length,1));set_source(p,sid);
    p[0]=0;p[1]=0x25;p[2]=(unsigned char)command;p[3]=(unsigned char)(command>>8);
    p[4]=(unsigned char)length;p[6]=1;if(length==12)p[8]=(unsigned char)value;return p;
}
static void finish(unsigned int command,unsigned int value,unsigned int sid) {
    assert(queued);unsigned char *p=queued;unsigned int length=command==0x10a?12:16;
    unsigned char expected[16]={0,0x25,0x0a,0,0,0,1,0};
    expected[3]=command==0x10a?0x81:0x82;expected[4]=(unsigned char)length;
    if(command==0x10a)expected[8]=1;else expected[12]=(unsigned char)value;
    assert(size(p)==length && !memcmp(p,expected,length));
    int rc=123;assert(full_hdmi_release_reply(sid,p,release,record,&rc) && !rc);
    last_reply=p;queued=0;
}
static void transaction(unsigned int command,unsigned int value,unsigned int sid) {
    int rc=123;void *p=request(command,value,sid);
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc);
    finish(command,value<6?value:0,sid);
}
static void finish_resolution(unsigned int command,const unsigned char fields[6],unsigned int sid) {
    assert(queued);unsigned char *p=queued;unsigned int length=command==0x101?12:20;
    unsigned char expected[20]={0,0x25,1,0,0,0,1,0};
    expected[3]=command==0x101?0x81:0x82;expected[4]=(unsigned char)length;
    if(command==0x201)memcpy(expected+12,fields,6);
    assert(size(p)==length && !memcmp(p,expected,length));
    int rc=123;assert(full_hdmi_release_reply(sid,p,release,record,&rc) && !rc);last_reply=p;queued=0;
}
static void resolution_transaction(unsigned int command,const unsigned char fields[6],unsigned int sid) {
    int rc=123;unsigned char *p=request(command,0,sid);
    if(command==0x101){memcpy(p+8,fields,6);p[14]=0xaa;p[15]=0xbb;}
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,FULL_HDMI_BOOT,&rc) && !rc);
    finish_resolution(command,fields,sid);
}
static void resolution_configuration(void) {
    reset();int rc=123;void *p=request(0x201,0,0x81c10201);
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,FULL_HDMI_BOOT,&rc) && rc==-1021 && message(p)->live);
    assert(!release(FULL_HDMI_CP,p));
    p=request(0x101,0,0x81c10201);unsigned int before=allocations;rc=123;
    assert(!full_hdmi_dispatch(FULL_HDMI_CP,p,&io,FULL_HDMI_DEFINITION,&rc) && rc==123 && allocations==before);
    assert(!release(FULL_HDMI_CP,p));
    transaction(0x10a,3,0x81c10202);
    const unsigned char boot[6]={0,0,0,0,6,5};
    resolution_transaction(0x101,boot,0x81c10203);resolution_transaction(0x201,boot,0x81c10204);
    assert(snapshot().definition==3 && snapshot().known);
    for(unsigned int i=0;i<32;i++) {
        unsigned char fields[6];for(unsigned int j=0;j<6;j++)fields[j]=(unsigned char)(i*37+j*51);
        resolution_transaction(0x101,fields,0x81c10300+i);resolution_transaction(0x201,fields,0x81c10400+i);
        assert(!memcmp(snapshot().resolution,fields,6) && snapshot().definition==3);
    }
    struct full_hdmi_snapshot saved=snapshot();p=request(0x101,0,0x81c10500);send_error=-66;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,FULL_HDMI_BOOT,&rc) && rc==-66);
    assert(!memcmp(snapshot().resolution,saved.resolution,6) && snapshot().resolution_applied==saved.resolution_applied);
    send_error=0;assert(!release(FULL_HDMI_CP,p));resolution_transaction(0x201,saved.resolution,0x81c10501);
    assert(!snapshot().faults && !snapshot().live_replies);
    puts("HDMI_RESOLUTION_SIX_FIELDS_RAW_PRESERVATION_GETTER_20B_PASS");
}
static void rate_transaction(unsigned int selector,unsigned int rate,unsigned int dp_selector,unsigned int dp_rate) {
    unsigned int sid=0x81e00100+selector;unsigned char *p=request(0x117,selector,sid);int rc=123;
    expected_rate_selector=selector;expected_rate_value=rate;
    p[9]=(unsigned char)rate;p[10]=(unsigned char)dp_selector;p[11]=(unsigned char)dp_rate;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,FULL_HDMI_BOOT,&rc) && !rc);
    const unsigned char expected[12]={0,0x25,0x17,0x81,12,0,1,0,0,0,0,0};
    assert(queued && size(queued)==12 && !memcmp(queued,expected,12));
    assert(full_hdmi_release_reply(sid,queued,release,record,&rc) && !rc);queued=0;
}
static void rate_configuration(void) {
    reset();int rc=123;void *p=request(0x117,0,0x81e00001);unsigned int before=allocations;
    assert(!full_hdmi_dispatch(FULL_HDMI_CP,p,&io,FULL_HDMI_DEFINITION,&rc) && rc==123 && allocations==before);
    assert(!release(FULL_HDMI_CP,p));p=request(0x217,0,0x81e00001);rc=123;
    assert(!full_hdmi_dispatch(FULL_HDMI_CP,p,&io,FULL_HDMI_BOOT,&rc) && rc==123);
    assert(!release(FULL_HDMI_CP,p)); /* No invented GET_OUTPUT_FRAME_RATE. */
    assert(!snapshot().rate_known_mask);
    rate_transaction(2,17,0,255);assert(snapshot().rate_known_mask==4 && snapshot().rates[2]==17 && !snapshot().rates[0]);
    const unsigned int values[]={0,1,17,127,255};
    for(unsigned int selector=0;selector<5;selector++)for(unsigned int i=0;i<5;i++) {
        struct full_hdmi_snapshot previous=snapshot();rate_transaction(selector,values[i],(selector+1)%5,values[(i+1)%5]);
        struct full_hdmi_snapshot s=snapshot();assert(s.rates[selector]==values[i]);
        for(unsigned int j=0;j<5;j++)if(j!=selector)assert(s.rates[j]==previous.rates[j]);
    }
    struct full_hdmi_snapshot previous=snapshot();
    rate_transaction(5,1,2,3);rate_transaction(255,0,0,0);
    assert(!memcmp(snapshot().rates,previous.rates,5) && snapshot().rate_known_mask==31);
    previous=snapshot();p=request(0x117,0,0x81e00002);((unsigned char *)p)[9]=42;send_error=-66;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,FULL_HDMI_BOOT,&rc) && rc==-66);
    assert(!memcmp(snapshot().rates,previous.rates,5) && snapshot().rate_requests==previous.rate_requests);
    assert(!memcmp(snapshot().last_rate_payload,previous.last_rate_payload,4) && !snapshot().pending);
    send_error=0;assert(!release(FULL_HDMI_CP,p));assert(!snapshot().faults && !snapshot().live_replies);
    puts("HDMI_RATE_FIVE_SELECTORS_PRESERVE_DP_UNAPPLIED_NO_GETTER_PASS");
}
static void configuration(void) {
    reset();void *p=request(0x20a,0,0x81c10001);int rc=123;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-1021 && message(p)->live);
    assert(!release(FULL_HDMI_CP,p)); /* Unknown cold value is not zero-ready. */
    for (unsigned int value=0;value<256;value++) {
        unsigned int sid=0x81c10002+value;
        transaction(0x10a,value,sid);assert(snapshot().known && snapshot().definition==(value<6?value:0));
        transaction(0x20a,value,sid+0x1000);
    }
    struct full_hdmi_snapshot s=snapshot();assert(s.applied==256 && s.queries==256);
    assert(s.waiter_freed==512 && !s.live_replies && !s.faults);
    assert(requests_freed==513 && replies_freed==512);
}
static void errors_and_activation(void) {
    reset();int rc=123;void *p=request(0x10a,4,0x8abc1234);unsigned int count=allocations;
    assert(!full_hdmi_dispatch(FULL_HDMI_CP,p,&io,0,&rc) && rc==123 && allocations==count);
    assert(!full_hdmi_dispatch(0x9059000e,p,&io,1,&rc) && rc==123);
    ((unsigned char *)p)[2]=9;
    assert(!full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==123);((unsigned char *)p)[2]=10;
    ((unsigned char *)p)[6]=0;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-1021 && message(p)->live);
    ((unsigned char *)p)[6]=1;send_error=-66;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-66 && message(p)->live && !snapshot().known);
    send_error=0;alloc_error=-67;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-67 && !snapshot().pending);
    alloc_error=0;assert(!release(FULL_HDMI_CP,p));transaction(0x10a,3,0x8abc1234);
    struct full_hdmi_snapshot before=snapshot();p=request(0x10a,5,0x8abc1235);send_error=-66;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-66);
    assert(snapshot().definition==before.definition && snapshot().applied==before.applied && !snapshot().live_replies);
    send_error=0;assert(!release(FULL_HDMI_CP,p));
    p=request(0x10a,2,0x8abc1236);assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc);
    assert(full_hdmi_release_reply(0x8abc1237,queued,release,record,&rc) && rc==-1021);
    assert(snapshot().faults && snapshot().live_replies==1);
    assert(full_hdmi_release_reply(0x8abc1236,queued,release,record,&rc) && !rc);queued=0;
    p=request(0x10a,1,0x8abc1238);assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-1021);
    assert(!release(FULL_HDMI_CP,p));
    reset();p=request(0x10a,1,0x8abc1238);alias_allocate=1;alias=p;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-1021 && message(p)->live && snapshot().faults);
    alias_allocate=0;assert(!release(FULL_HDMI_CP,p));
    reset();p=request(0x10a,1,0x8abc1238);free_error=-69;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc && snapshot().faults && message(p)->live);
    free_error=0;assert(!release(FULL_HDMI_CP,p));finish(0x10a,1,0x8abc1238);
}
static void reused_pool(void) {
    reset();transaction(0x10a,1,0x81c10001);void *address=last_reply;
    for(unsigned int i=0;i<100;i++) {
        unsigned int sid=0x81d10001+i;
        transaction(0x10a,i%6,sid);assert(last_reply==address);
        transaction(0x20a,i%6,sid+0x1000);assert(last_reply==address);
    }
    assert(snapshot().native_freed==201 && !snapshot().live_replies);
}
static void reply_and_cleanup_faults(void) {
    reset();int rc=123;unsigned int sid=0x81c10101;
    void *p=request(0x10a,1,sid);
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc);
    free_error=-71;
    assert(full_hdmi_release_reply(sid,queued,release,record,&rc) && rc==-71);
    assert(snapshot().faults && snapshot().live_replies==1 && message(queued)->live);
    free_error=0;finish(0x10a,1,sid);assert(!snapshot().live_replies);
    p=request(0x10a,2,sid);assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-1021);
    assert(!release(FULL_HDMI_CP,p));
    reset();p=request(0x10a,4,sid);send_error=-66;free_error=-72;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-66);
    struct full_hdmi_snapshot s=snapshot();
    assert(!s.known && !s.applied && !s.live_replies && s.faults && s.retained_reply);
    assert(message(s.retained_reply)->live && message(p)->live && !queued);
    free_error=send_error=0;
    assert(!release(sid,s.retained_reply));assert(!release(FULL_HDMI_CP,p));
}
static void *allocate_while_freeing(void *p) {
    int rc=123;assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,race.resolution_test?FULL_HDMI_BOOT:FULL_HDMI_DEFINITION,&rc) && !rc);
    assert(queued==race.old);
    if(race.resolution_test)finish_resolution(race.command,race.resolution,race.destination);
    else finish(race.command,race.value,race.destination);
    return 0;
}
static void interleaved_real_free(void) {
    for (unsigned int iteration=0;iteration<50;iteration++) {
        reset();int resolution_test=(iteration&2)!=0;
        unsigned int first=iteration%2?(resolution_test?0x201:0x20a):(resolution_test?0x101:0x10a);
        const unsigned char initial[6]={0,0,0,0,6,5},updated[6]={255,254,253,252,251,250};
        if (first==0x20a) transaction(0x10a,1,0x81c10011);
        if (first==0x201) resolution_transaction(0x101,initial,0x81c10011);
        void *p=request(first,1,0x81c10012);int rc=123;
        if(first==0x101)memcpy((unsigned char *)p+8,initial,6);
        assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,resolution_test?FULL_HDMI_BOOT:FULL_HDMI_DEFINITION,&rc) && !rc);
        void *old=queued;queued=0;
        unsigned int second=resolution_test?(first==0x101?0x201:0x101):(first==0x10a?0x20a:0x10a);
        void *next=request(second,second==0x20a?1:2,0x81c10013);
        if(second==0x101)memcpy((unsigned char *)next+8,updated,6);
        race.active=1;race.old=old;race.destination=0x81c10013;race.command=second;
        race.resolution_test=resolution_test;memcpy(race.resolution,second==0x201?initial:updated,6);
        race.value=second==0x20a?1:2;race.waiting=race.freed=race.reused=0;
        pthread_t allocator;assert(!pthread_create(&allocator,0,allocate_while_freeing,next));
        pthread_mutex_lock(&race.mutex);
        while (!race.waiting) assert(!pthread_cond_wait(&race.condition,&race.mutex));
        pthread_mutex_unlock(&race.mutex);
        assert(full_hdmi_release_reply(0x81c10012,old,release,record,&rc) && !rc);
        assert(!pthread_join(allocator,0));race.active=0;
        assert(race.reused && !snapshot().faults && !snapshot().live_replies && !snapshot().pending);
    }
    puts("HDMI_INTERLEAVED_REAL_FREE_ALLOCATE_SAME_ADDRESS_50_PASS");
}
static void audio_connected_marker(void) {
    reset();struct full_hdmi_snapshot cold=snapshot();
    assert(!cold.audio_pin_connected_known && !cold.audio_pin_connected_writes);
    transaction(0x10a,3,0x81b10001);
    const unsigned char fields[6]={3,4,5,6,7,8};
    resolution_transaction(0x101,fields,0x81b10002);resolution_transaction(0x201,fields,0x81b10003);
    rate_transaction(2,17,4,23);struct full_hdmi_snapshot before=snapshot();
    assert(!full_hdmi_audio_pin_connected_one());struct full_hdmi_snapshot after=snapshot();
    assert(after.audio_pin_connected_known==1 && after.audio_pin_connected==1 && after.audio_pin_connected_writes==1 && after.audio_pin_connected_owner_pid==getpid());
    assert(full_hdmi_audio_pin_connected_one()==-1021);struct full_hdmi_snapshot same=snapshot();assert(!memcmp(&same,&after,sizeof same));
    after.audio_pin_connected=before.audio_pin_connected;after.audio_pin_connected_known=before.audio_pin_connected_known;
    after.audio_pin_connected_writes=before.audio_pin_connected_writes;after.audio_pin_connected_owner_pid=before.audio_pin_connected_owner_pid;
    assert(!memcmp(&after,&before,sizeof before));
    pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(full_hdmi_audio_pin_connected_one()==-1021);_exit(0);}
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    /* Later requests preserve the same marker in this existing owner. */
    transaction(0x20a,3,0x81b10004);assert(snapshot().audio_pin_connected_writes==1);
    reset();void *p=request(0x10a,1,0x81b10005);int rc=77;
    assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc);
    assert(full_hdmi_audio_pin_connected_one()==-1021 && !snapshot().audio_pin_connected_known);
    finish(0x10a,1,0x81b10005);assert(!full_hdmi_audio_pin_connected_one());
    puts("HDMI_SHARED_AUDIO_CONNECTED_ONE_OLD_UNKNOWN_CONFIG_PRESERVED_PASS");
}
int main(void) {
    alarm(15);
    configuration();resolution_configuration();rate_configuration();errors_and_activation();reused_pool();reply_and_cleanup_faults();interleaved_real_free();audio_connected_marker();
    puts("HDMI_DEFINITION_STATE_NORMALIZATION_GETTER_OWNERSHIP_ABA_PASS");return 0;
}
