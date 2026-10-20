/* SPDX-License-Identifier: MIT */
#include "audio-device.h"
#include <assert.h>
#include <stddef.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct block { unsigned int bytes,source,pool;unsigned char body[64]; };
static struct block *header(void *p) { return (void *)((char *)p - offsetof(struct block,body)); }
static const unsigned char request10[10]={0x0d,0x20,0x30,3,10,0,1,0x80,8,0};
static const unsigned char expected12[12]={0x0d,0x20,0x30,0x13,12,0,1,0x80,0,0,0x58,0};
static const unsigned char query8[8]={0x0d,0x20,0x3f,3,8,0,1,0x80};
static const unsigned char capability8[8]={0x0d,0x20,0x27,3,8,0,1,0x80};
static const unsigned char query24[24]={0x0d,0x20,0x3f,0x13,24,0,1,0x80,0,0,0x58,0,
                                     0,0,0,0,0,0,0,0x1d,8,0,0,0};
static const unsigned char table40[40]={0x0d,0x20,0x29,3,40,0,1,0x80,
    0,0,0,0x1d,8,0,0,0,0x80,0,0,0,1,6,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
static const char metadata[]="{\"ready\":true,\"physical\":\"0x41d000000\",\"virtual_bus\":\"0x1d000000\",\"audio_phys64\":\"0x81d000000\",\"capacity\":131072,\"bytes\":66368,\"fnv64\":\"0500159a93ab9e42\",\"source_sha256\":\"5d94c660c48afde364fbb936105abdaf5c35f8bf8fc0bfd6945cd12146f6824a\",\"lifetime\":\"vm\",\"audio_output_verified\":false}\n";
static unsigned char *sound_source,*sound_memory;
static unsigned int expected_status;
static int worker_profile=FULL_AUDIO_VOLUME,worker_capabilities,partial_allocate;
static void *queue[8],*failed,*alias;
static unsigned int count,requests_freed,replies_freed,sends,allocs;
static int alloc_error,send_error,free_error,request_error;
static pthread_mutex_t mock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed=PTHREAD_COND_INITIALIZER;
static struct block reused;
static int reuse,available,waiting,free_entered,claimed,finish_free;
static unsigned int reused_frees;
static int allocate(unsigned int dst,void **out,unsigned int bytes,unsigned int n) {
    assert((dst>>28)==8 && (bytes==12 || bytes==24 || bytes==28) && n==1);
    pthread_mutex_lock(&mock);allocs++;
    if (alias) { *out=alias;pthread_mutex_unlock(&mock);return 0; }
    if (alloc_error && !partial_allocate) { int rc=alloc_error;pthread_mutex_unlock(&mock);return rc; }
    struct block *b;
    if (reuse) {
        while (!available) { waiting=1;pthread_cond_broadcast(&changed);pthread_cond_wait(&changed,&mock); }
        available=0;b=&reused;
        if (free_entered) { claimed=1;pthread_cond_broadcast(&changed); }
    } else { b=calloc(1,sizeof *b);assert(b); }
    b->pool=dst;b->bytes=bytes;b->source=0;*out=b->body;
    pthread_mutex_unlock(&mock);return alloc_error;
}
static int release(unsigned int pool,void *p) {
    pthread_mutex_lock(&mock);assert(header(p)->pool==pool);
    int rc=pool==FULL_AUDIO_INPUT?request_error:free_error;
    if (rc) { failed=p;pthread_mutex_unlock(&mock);return rc; }
    if (header(p)==&reused) {
        if (++reused_frees==1) {
            free_entered=available=1;pthread_cond_broadcast(&changed);
            while (!finish_free) pthread_cond_wait(&changed,&mock);
        } else available=1;
    } else free(header(p));
    if (pool==FULL_AUDIO_INPUT) requests_freed++;else replies_freed++;
    pthread_cond_broadcast(&changed);pthread_mutex_unlock(&mock);return 0;
}
static unsigned int size(void *p) { return header(p)->bytes; }
static unsigned int source(void *p) { return header(p)->source; }
static void set_source(void *p,unsigned int id) { header(p)->source=id; }
static int send(unsigned int dst,void *p) {
    assert(header(p)->pool==dst && source(p)==FULL_AUDIO_INPUT);
    const unsigned char *bytes=p;
    if (bytes[2]==0x30) { assert(size(p)==12 && !memcmp(p,expected12,12)); }
    else if (bytes[2]==0x3f) { assert(size(p)==24 && !memcmp(p,query24,24)); }
    else if (bytes[2]==0x27) {
        unsigned char fixture[28]={0x0d,0x20,0x27,0x13,28,0,1,0x80,0,0,0x58,0};
        fixture[8]=(unsigned char)expected_status;fixture[9]=(unsigned char)(expected_status>>8);
        if (!expected_status) { memset(fixture+12,0x80,16);fixture[20]=0x81; }
        assert(size(p)==28 && !memcmp(p,fixture,28));
    }
    else {
        unsigned char fixture[12]={0x0d,0x20,0x29,0x13,12,0,1,0x80,0,0,0x58,0};
        if (bytes[2]==0x2c) fixture[2]=0x2c;
        if (bytes[2]==0x2a) fixture[2]=0x2a;
        fixture[8]=(unsigned char)expected_status;fixture[9]=(unsigned char)(expected_status>>8);
        assert(size(p)==12 && !memcmp(p,fixture,12));
    }
    pthread_mutex_lock(&mock);sends++;
    if (send_error) { int rc=send_error;pthread_mutex_unlock(&mock);return rc; }
    assert(count<8);queue[count++]=p;pthread_cond_broadcast(&changed);pthread_mutex_unlock(&mock);return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
static void *request(const unsigned char *body,unsigned int n,unsigned int src) {
    struct block *b=calloc(1,sizeof *b);assert(b && n<=64);
    b->pool=FULL_AUDIO_INPUT;b->source=src;b->bytes=n;memcpy(b->body,body,n);return b->body;
}
static struct full_audio_snapshot snapshot(void) { struct full_audio_snapshot s;full_audio_snapshot(&s);return s; }
static void reset(void) {
    assert(!count && !failed);requests_freed=replies_freed=sends=allocs=0;
    alloc_error=send_error=free_error=request_error=partial_allocate=0;alias=0;expected_status=0;
    reuse=available=waiting=free_entered=claimed=finish_free=0;reused_frees=0;full_audio_test_reset();
    worker_capabilities=0;
}
static void accepted(unsigned int value,unsigned int high,unsigned int src) {
    unsigned char body[10];memcpy(body,request10,10);body[8]=(unsigned char)value;body[9]=(unsigned char)high;
    int rc=123;assert(full_audio_dispatch(FULL_AUDIO_INPUT,request(body,10,src),&io,1,&rc) && !rc);
}
static void native_free(void *p) {
    int rc=123;assert(full_audio_release_reply(header(p)->pool,p,release,0,&rc) && !rc);
}
static void *pop(void) {
    pthread_mutex_lock(&mock);assert(count);void *p=queue[0];memmove(queue,queue+1,--count*sizeof queue[0]);
    pthread_mutex_unlock(&mock);return p;
}
static void drain(void) { native_free(pop()); }
static void *free_worker(void *p) { native_free(p);return 0; }
static void *send_worker(void *p) {
    int rc=123;
    int handled=worker_capabilities?full_audio_dispatch_capabilities(FULL_AUDIO_INPUT,p,&io,worker_profile,FULL_AUDIO_CAPS_INPUTLESS,&rc):
                                    full_audio_dispatch(FULL_AUDIO_INPUT,p,&io,worker_profile,&rc);
    assert(handled && !rc);return 0;
}
static void bind_owner(void) {
    assert(!full_sound_test_bind(sound_memory,SYSTEM_SOUND_CAPACITY,sound_source,SYSTEM_SOUND_BYTES,metadata));
}
static void aba(int query) {
    reset();worker_profile=query?FULL_AUDIO_BOOT:FULL_AUDIO_VOLUME;
    worker_capabilities=query==2;
    reuse=available=1;
    if (query==2) {
        int rc;assert(full_audio_dispatch_capabilities(FULL_AUDIO_INPUT,request(capability8,8,0x81cf61c1),&io,
                      FULL_AUDIO_BOOT,FULL_AUDIO_CAPS_INPUTLESS,&rc) && !rc);
    } else if (query) {
        bind_owner();int rc;
        assert(full_audio_dispatch(FULL_AUDIO_INPUT,request(query8,8,0x81cf61c1),&io,FULL_AUDIO_BOOT,&rc) && !rc);
    } else accepted(1,0,0x81cf61c1);
    void *old=pop();
    unsigned char body[10];memcpy(body,request10,10);body[8]=16;
    void *next=request(query==2?capability8:query?query8:body,query?8:10,0x81cf61c2);pthread_t sender,receiver;
    assert(!pthread_create(&sender,0,send_worker,next));
    pthread_mutex_lock(&mock);while (!waiting) pthread_cond_wait(&changed,&mock);pthread_mutex_unlock(&mock);
    assert(!pthread_create(&receiver,0,free_worker,old));
    pthread_mutex_lock(&mock);while (!claimed) pthread_cond_wait(&changed,&mock);
    assert(sends==1 && !replies_freed && free_entered);finish_free=1;
    pthread_cond_broadcast(&changed);pthread_mutex_unlock(&mock);
    assert(!pthread_join(receiver,0) && !pthread_join(sender,0));
    struct full_audio_snapshot s=snapshot();assert(!s.faults && s.native_freed==1 && s.live_replies==1);
    void *now=pop();assert(now==old && header(now)->pool==0x81cf61c2);native_free(now);s=snapshot();
    assert(s.native_freed==2 && !s.live_replies);
    if (query==2) assert(s.capabilities.queries==2 && !s.applied);
    else if (query) assert(s.queries==2 && !s.applied);
    else assert(s.applied==2 && s.wire_volume==16 && s.driver_level==15);
}
static unsigned long long digest(const unsigned char *p,unsigned int n) {
    unsigned long long h=0xcbf29ce484222325ULL;
    for (unsigned int i=0;i<n;i++) h=(h^p[i])*0x100000001b3ULL;
    return h;
}
static void put32(unsigned char *p,unsigned int n) {
    for (unsigned int i=0;i<4;i++) p[i]=(unsigned char)(n>>(i*8));
}
static void table_request(unsigned char *p,unsigned int kind,unsigned int offset,unsigned int bytes) {
    memcpy(p,table40,40);p[20]=(unsigned char)kind;put32(p+8,0x1d000000+offset);put32(p+16,bytes);
}
static void transaction(const unsigned char *p,unsigned int n,unsigned int status,int transport) {
    expected_status=status;int rc=123;void *req=request(p,n,0x8abc1234);
    assert(full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_BOOT,&rc));
    assert(rc==transport);
    if (transport) { assert(!count);release(FULL_AUDIO_INPUT,req); }
    else drain();
}
static void system_volume_tests(void) {
    reset();struct full_audio_snapshot s=snapshot();
    for (unsigned int i=0;i<30;i++) assert(s.system_volume[i]==7);
    unsigned char config[10]={0x0d,0x20,0x2c,3,10,0,1,0x80,0,1};
    transaction(config,10,0,0);s=snapshot();
    assert(s.system_volume[0]==0 && s.system_volume[1]==7 && !s.known && !s.applied);
    config[8]=7;config[9]=30;transaction(config,10,0,0);
    assert(snapshot().system_volume[29]==7);
    config[8]=2;config[9]=0;transaction(config,10,0,0);s=snapshot();
    for (unsigned int i=0;i<30;i++) assert(s.system_volume[i]==2);
    config[8]=0;config[9]=31;transaction(config,10,0,0);
    assert(!memcmp(snapshot().system_volume,s.system_volume,30));
    s=snapshot();config[8]=8;config[9]=0;transaction(config,10,0xe002,0);
    assert(!memcmp(snapshot().system_volume,s.system_volume,30));
    assert(snapshot().system_volume_applied==s.system_volume_applied);
    config[8]=5;config[9]=1;send_error=-66;transaction(config,10,0,-66);send_error=0;
    assert(!memcmp(snapshot().system_volume,s.system_volume,30));
    assert(snapshot().system_volume_applied==s.system_volume_applied);
    int rc=123;void *req=request(config,10,0x8abc1234);unsigned int before=allocs;
    assert(!full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_VOLUME,&rc) && rc==123 && allocs==before);
    assert(!release(FULL_AUDIO_INPUT,req));
    assert(full_sound_ready()!=0); /* Independent of the 0329/backing owner. */
    puts("SYSTEM_SOUND_PER_KIND_VOLUME_STATE_PASS");
}
static void system_path_tests(void) {
    reset();unsigned char config[10]={0x0d,0x20,0x2a,3,10,0,1,0x80,7,0xff};
    transaction(config,10,0,0);struct full_audio_snapshot s=snapshot();
    assert(s.system_path==7 && s.path_register==1 && s.path_control_argument==0 && s.path_control_consumed==1);
    assert(!s.known && !s.applied && s.system_volume[0]==7);
    config[8]=0xfd;transaction(config,10,0,0);s=snapshot();
    assert(s.system_path==5 && s.path_register==1 && s.path_control_consumed==1 && s.path_applied==2);
    config[8]=0;transaction(config,10,0,0);s=snapshot();
    assert(!s.system_path && !s.path_register && s.path_control_argument==1 && s.path_control_consumed==2);
    config[8]=0xf8;transaction(config,10,0,0);assert(snapshot().path_control_consumed==2);
    config[8]=4;send_error=-66;transaction(config,10,0,-66);
    assert(!snapshot().system_path && !snapshot().path_register && snapshot().path_control_consumed==2);
    send_error=0;transaction(config,10,0,0);s=snapshot();
    assert(s.system_path==4 && s.path_register==1 && s.path_control_consumed==3);
    config[4]=9;transaction(config,10,0,-1021);
    assert(snapshot().system_path==4 && snapshot().path_applied==5);
    reset();puts("AUDIO_SYSTEM_PATH_MASK_IDLE_CONTROL127_STATE_AND_ROLLBACK_PASS");
}
static void capability_query(unsigned int status,int transport) {
    expected_status=status;int rc=123;void *p=request(capability8,8,0x81cf61ca);
    assert(full_audio_dispatch_capabilities(FULL_AUDIO_INPUT,p,&io,FULL_AUDIO_BOOT,FULL_AUDIO_CAPS_INPUTLESS,&rc));
    assert(rc==transport);
    if (transport) { assert(!count);release(FULL_AUDIO_INPUT,p); }else drain();
}
static void capability_tests(void) {
    reset();int rc=123;void *p=request(capability8,8,0x81cf61ca);unsigned int count_before=allocs;
    assert(!full_audio_dispatch(FULL_AUDIO_INPUT,p,&io,FULL_AUDIO_BOOT,&rc) && rc==123 && allocs==count_before);
    assert(!full_audio_dispatch_capabilities(FULL_AUDIO_INPUT,p,&io,FULL_AUDIO_VOLUME,FULL_AUDIO_CAPS_INPUTLESS,&rc));
    assert(!release(FULL_AUDIO_INPUT,p));capability_query(0,0);
    struct full_audio_snapshot s=snapshot();
    assert(s.capabilities.profile==FULL_AUDIO_CAPS_INPUTLESS && s.capabilities.valid==7 && !s.capabilities.input_devices);
    assert(!s.capabilities.pro && !s.capabilities.aip && !s.capabilities.znr && s.capabilities.queries==1);
    assert(!s.applied && !s.queries && !s.table_applied && full_sound_ready()!=0);
    for (unsigned int i=0;i<16;i++) assert(s.capabilities.flags[i]==(i==8?0x81:0x80));
    for (unsigned int fault=0;fault<6;fault++) {
        reset();struct full_audio_capabilities owner;full_audio_capabilities_inputless(&owner);
        if (!fault)owner.valid=6;else if(fault==1)owner.input_devices=1;else if(fault==2)owner.pro=1;
        else if(fault==3)owner.aip=1;else if(fault==4)owner.znr=1;else owner.error=0xefff;
        full_audio_test_capabilities_bind(&owner);capability_query(0xefff,0);
        assert(snapshot().capabilities.error==0xefff && !snapshot().capabilities.queries);
        owner=snapshot().capabilities;owner.valid=7;owner.input_devices=owner.pro=owner.aip=owner.znr=0;
        full_audio_test_capabilities_bind(&owner);capability_query(0xefff,0); /* Error stays latched. */
    }
    reset();send_error=-66;capability_query(0,-66);send_error=0;
    assert(!snapshot().capabilities.profile && !snapshot().capabilities.queries);
    capability_query(0,0);assert(snapshot().capabilities.queries==1);
    for(unsigned int i=0;i<50;i++)aba(2);
    puts("AUDIO_INPUTLESS_CAPABILITY_OWNER_STATUS_ERROR_28B_ABA_PASS");
}
static void boot_tests(const char *path) {
    FILE *f=fopen(path,"rb");assert(f);
    sound_source=malloc(SYSTEM_SOUND_BYTES);sound_memory=calloc(1,SYSTEM_SOUND_CAPACITY);
    assert(sound_source && sound_memory && fread(sound_source,1,SYSTEM_SOUND_BYTES,f)==SYSTEM_SOUND_BYTES);
    assert(fgetc(f)==EOF);fclose(f);memcpy(sound_memory,sound_source,SYSTEM_SOUND_BYTES);
    reset();transaction(query8,8,0,-1021);assert(!allocs);
    assert(full_sound_test_bind(sound_memory,SYSTEM_SOUND_CAPACITY-1,sound_source,SYSTEM_SOUND_BYTES,metadata));
    assert(full_sound_test_bind(sound_memory,SYSTEM_SOUND_CAPACITY,sound_source,SYSTEM_SOUND_BYTES-1,metadata));
    const char *fields[]={"true","41d000000","1d000000","81d000000","131072","66368",
                          "0500159a93ab9e42",SYSTEM_SOUND_SHA256,"vm","false"};
    for (unsigned int i=0;i<sizeof fields/sizeof *fields;i++) {
        char bad[sizeof metadata];memcpy(bad,metadata,sizeof bad);char *at=strstr(bad,fields[i]);assert(at);*at='!';
        assert(full_sound_test_bind(sound_memory,SYSTEM_SOUND_CAPACITY,sound_source,SYSTEM_SOUND_BYTES,bad));
        transaction(query8,8,0,-1021);assert(!allocs);
    }
    sound_memory[32]^=1;
    assert(full_sound_test_bind(sound_memory,SYSTEM_SOUND_CAPACITY,sound_source,SYSTEM_SOUND_BYTES,metadata));
    sound_memory[32]^=1;sound_memory[SYSTEM_SOUND_BYTES]=1;
    assert(full_sound_test_bind(sound_memory,SYSTEM_SOUND_CAPACITY,sound_source,SYSTEM_SOUND_BYTES,metadata));
    sound_memory[SYSTEM_SOUND_BYTES]=0;
    bind_owner();transaction(query8,8,0,0);assert(snapshot().queries==1 && allocs==1 && replies_freed==1);
    /* Boot audio shares this queue with display/VDF services. Those requests
     * must fall through unchanged, without allocation, free or false error. */
    const unsigned int nonaudio[]={0x165,0x32f,0x16a,0x14c,0x142,0x15a,0x145,0x11b};
    for (unsigned int i=0;i<sizeof nonaudio/sizeof nonaudio[0];i++) {
        unsigned char body[10];memcpy(body,request10,10);
        body[2]=(unsigned char)nonaudio[i];body[3]=(unsigned char)(nonaudio[i]>>8);
        void *req=request(body,10,0x81cf61c4);int result=123;
        unsigned int before_allocs=allocs,before_frees=requests_freed;
        assert(!full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_BOOT,&result));
        assert(result==123 && allocs==before_allocs && requests_freed==before_frees);
        assert(!release(FULL_AUDIO_INPUT,req));
    }
    assert(digest(sound_memory,SYSTEM_SOUND_BYTES)==SYSTEM_SOUND_FNV);
    sound_memory[80]^=1;transaction(query8,8,0,-1021);sound_memory[80]^=1;
    assert(allocs==1);transaction(query8,8,0,0);
    /* AP sub_3060464's 25 defaults, in kind order; zero-size continuous entries are intentional. */
    static const unsigned int offsets[25]={0,0x80,0x540,0xa00,0x1880,0x2600,0,0,0,
        0x6000,0x64c0,0x6c00,0x71c0,0x7540,0x7c80,0x8240,0,0,0x8d00,0x97c0,0xb7c0,0xe840,0x540,0xa00,0x1880};
    static const unsigned int sizes[25]={0x80,0x4c0,0x4c0,0xe80,0xd80,0x2440,0,0,0,
        0x4c0,0x740,0x5c0,0x380,0x740,0x5c0,0xac0,0,0,0xac0,0x2000,0x3080,0x1b00,0x4c0,0xe80,0xd80};
    unsigned char body[40];
    for (unsigned int i=0;i<25;i++) {
        table_request(body,i+1,offsets[i],sizes[i]);
        if (i==7 || i==8 || i==16 || i==17) { body[24]=1;put32(body+28,0x720);put32(body+32,0x4e0); }
        transaction(body,40,0,0);struct full_audio_snapshot s=snapshot();
        assert(s.table[i].cpu==0x1d000000+offsets[i] && s.table[i].offset==offsets[i] && s.table[i].size==sizes[i]);
        assert(s.table[i].digest==digest(sound_source+offsets[i],sizes[i]));
        transaction(body,40,0,0);body[25]=0xff;body[26]=0xa5;body[27]=0x42;memset(body+36,0xa5,4);
        transaction(body,40,0,0);s=snapshot();
        assert(!s.table[i].descriptor[17] && !s.table[i].descriptor[18] && !s.table[i].descriptor[19]);
        for (unsigned int j=28;j<32;j++) assert(!s.table[i].descriptor[j]);
    }
    table_request(body,1,0,0x80);body[21]++;transaction(body,40,0xe004,0);
    assert(snapshot().table[0].descriptor[13]==6);
    struct full_audio_snapshot prior=snapshot();send_error=-66;
    body[22]=0;transaction(body,40,0,-66);send_error=0;
    assert(!memcmp(snapshot().table,prior.table,sizeof prior.table));
    body[22]=0;transaction(body,40,0,0);assert(!snapshot().table[0].descriptor[14]);
    assert(!full_sound_ready());body[22]=1;transaction(body,40,0,0);assert(snapshot().table[0].descriptor[13]==7);
    for (unsigned int kind=26;kind<=30;kind++) { table_request(body,kind,0,0x80);transaction(body,40,0,0); }
    table_request(body,31,0,0x80);transaction(body,40,0xe004,0);
    body[22]=0;transaction(body,40,0,0);assert(!full_sound_ready());
    table_request(body,0,0,0x80);transaction(body,40,0xe002,0);
    table_request(body,1,0,0x80);body[22]=2;transaction(body,40,0xe004,0);
    body[22]=1;body[23]=2;unsigned int before=allocs;transaction(body,40,0,-1021);assert(allocs==before);
    body[23]=0;body[24]=2;transaction(body,40,0,-1021);assert(allocs==before);
    table_request(body,1,SYSTEM_SOUND_BYTES-1,2);transaction(body,40,0,-1021);
    table_request(body,1,SYSTEM_SOUND_BYTES,0);transaction(body,40,0,-1021);
    table_request(body,1,0,0xffffffffu);transaction(body,40,0,-1021);
    table_request(body,1,0,0x80);body[12]=7;transaction(body,40,0,-1021);
    body[12]=0xff;transaction(body,40,0,-1021);
    table_request(body,1,SYSTEM_SOUND_CAPACITY-0x40,1);transaction(body,40,0,-1021);
    table_request(body,1,0,SYSTEM_SOUND_CAPACITY-0x3f);transaction(body,40,0,-1021);
    table_request(body,1,0,0x80);
    for (unsigned int n=4;n<40;n++) transaction(body,n,0,-1021);
    memcpy(body,query8,8);body[2]=0x2b;transaction(body,8,0,-1021);
    body[0]=4;body[1]=0x20;body[2]=3;body[3]=2;transaction(body,8,0,-1021);
    for (unsigned int i=4;i<8;i++) {
        memcpy(body,query8,8);body[i]^=0x10;transaction(body,8,0,-1021);
    }
    for (unsigned int dst=0;dst<3;dst++) {
        static const unsigned int bad[]={0,0x80000000,0x928407b9};int rc=123;
        void *req=request(query8,8,bad[dst]);before=allocs;
        assert(full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_BOOT,&rc) && rc==-1021 && allocs==before);
        release(FULL_AUDIO_INPUT,req);
    }
    for (unsigned int cmd=0;cmd<2;cmd++) for (unsigned int failure=0;failure<5;failure++) {
        reset();bind_owner();table_request(body,1,0,0x80);
        const unsigned char *p=cmd?body:query8;unsigned int n=cmd?40:8;
        if (failure<2) { alloc_error=-55;partial_allocate=failure==1; }
        else { send_error=-66;if (failure==3) free_error=-77; }
        if (failure==4) { send_error=0;request_error=-88; }
        int rc;void *req=request(p,n,0x8abc1234);
        assert(full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_BOOT,&rc));
        struct full_audio_snapshot s=snapshot();
        if (failure<4) {
            assert(rc==(failure<2?-55:-66) && !s.queries && !s.table_applied && !s.table[0].descriptor[14]);
            assert(!requests_freed && !count && s.faults==(failure==3));
            if (failed) { free_error=0;release(0x8abc1234,failed);failed=0; }
            release(FULL_AUDIO_INPUT,req);
        } else {
            assert(!rc && s.faults && s.retained_request==req && count==1);
            request_error=0;release(FULL_AUDIO_INPUT,failed);failed=0;drain();
        }
    }
    reset();bind_owner();int rc;void *req=request(query8,8,0x8abc1234);alias=req;
    assert(full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_BOOT,&rc) && rc==-1021 && snapshot().faults);
    alias=0;release(FULL_AUDIO_INPUT,req);
    reset();bind_owner();transaction(query8,8,0,0);
    req=request(query8,8,0x8abc1234);assert(full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_VOLUME,&rc)==0);
    release(FULL_AUDIO_INPUT,req);
    req=request(query8,8,0x8abc1234);assert(full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_BOOT,&rc) && !rc);
    void *reply=pop();free_error=-77;
    assert(full_audio_release_reply(0x8abc1234,reply,release,0,&rc) && rc==-77);
    free_error=0;failed=0;native_free(reply);assert(snapshot().native_freed==2);
    reset();bind_owner();req=request(query8,8,0x8abc1234);
    assert(full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_BOOT,&rc) && !rc);reply=pop();
    assert(full_audio_release_reply(0x8abc1235,reply,release,0,&rc) && rc==-1021 && !replies_freed);
    native_free(reply);assert(!snapshot().live_replies);
    reset();bind_owner();alloc_error=-55;partial_allocate=1;free_error=-77;
    transaction(query8,8,0,-55);assert(snapshot().faults && snapshot().retained_reply==failed);
    free_error=alloc_error=0;partial_allocate=0;release(0x8abc1234,failed);failed=0;
    before=allocs;transaction(query8,8,0,-1021);assert(allocs==before);
    reset();bind_owner();
    for (unsigned int i=0;i<8;i++) {
        req=request(query8,8,0x8abc1234+i);
        assert(full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_BOOT,&rc) && !rc);
    }
    req=request(query8,8,0x8abc1240);before=allocs;
    assert(full_audio_dispatch(FULL_AUDIO_INPUT,req,&io,FULL_AUDIO_BOOT,&rc) && rc==-1021);
    assert(snapshot().live_replies==8 && snapshot().queries==8 && allocs==before+1);
    release(FULL_AUDIO_INPUT,req);while (count) drain();
    assert(snapshot().request_freed==8 && snapshot().native_freed==8 && !snapshot().faults);
    for (unsigned int i=0;i<50;i++) aba(1);
    reset();free(sound_source);free(sound_memory);sound_source=sound_memory=0;
    puts("AUDIO_BOOT_OWNER_TABLE_25_SLICES_STATUS_OWNERSHIP_ABA_PASS");
}
int main(int argc,char **argv) {
    system_path_tests();
    system_volume_tests();
    capability_tests();
    reset();unsigned int level=123;assert(full_audio_replay_config(&level)==-1021 && level==123);
    void *p=request(request10,10,0x81cf61c1);int rc=123;
    assert(!full_audio_dispatch(FULL_AUDIO_INPUT,p,&io,0,&rc) && rc==123 && !allocs);release(FULL_AUDIO_INPUT,p);
    static const unsigned int values[]={0,1,8,16,17,255},levels[]={0,0,7,15,15,15};
    for (unsigned int i=0;i<6;i++) {
        accepted(values[i],0xa5,0x81cf61c1);struct full_audio_snapshot s=snapshot();
        assert(s.known && s.wire_volume==values[i] && s.driver_level==levels[i]);
        unsigned char control[64]={4};control[4]=(unsigned char)levels[i];
        assert(!memcmp(control,s.driver_control,64) && s.live_replies==1);
        assert(!full_audio_replay_config(&level) && level==levels[i]);drain();
    }
    for (unsigned int ap=0;ap<16;ap++) { accepted(16-ap,0,0x8abc1234);assert(snapshot().driver_level==15-ap);drain(); }
    for (unsigned int n=0;n<10;n++) {
        p=request(request10,n,0x81cf61c1);unsigned int before=allocs;rc=123;
        int handled=full_audio_dispatch(FULL_AUDIO_INPUT,p,&io,1,&rc);
        assert(n<4?!handled:(handled && rc==-1021));assert(allocs==before);release(FULL_AUDIO_INPUT,p);
    }
    for (unsigned int failure=0;failure<3;failure++) {
        reset();p=request(request10,10,0x81cf61c1);
        if (!failure) alloc_error=-55;else send_error=-66;
        if (failure==2) free_error=-77;
        assert(full_audio_dispatch(FULL_AUDIO_INPUT,p,&io,1,&rc) && rc==(failure?-66:-55));
        struct full_audio_snapshot s=snapshot();assert(!s.known && !s.applied && !count && !requests_freed);
        assert(s.faults==(failure==2));
        if (failed) { free_error=0;release(0x81cf61c1,failed);failed=0; }
        release(FULL_AUDIO_INPUT,p);
    }
    reset();request_error=-88;accepted(8,0,0x81cf61c1);assert(snapshot().faults==1 && failed && count==1);
    request_error=0;release(FULL_AUDIO_INPUT,failed);failed=0;drain();
    p=request(request10,10,0x81cf61c1);assert(full_audio_dispatch(FULL_AUDIO_INPUT,p,&io,1,&rc) && rc==-1021);
    release(FULL_AUDIO_INPUT,p);
    reset();accepted(8,0,0x81cf61c1);p=pop();free_error=-77;
    assert(full_audio_release_reply(0x81cf61c1,p,release,0,&rc) && rc==-77 && snapshot().faults==1);
    free_error=0;failed=0;native_free(p);assert(snapshot().waiter_freed==1 && !snapshot().live_replies);
    reset();accepted(8,0,0x81cf61c1);p=pop();
    assert(full_audio_release_reply(0x81cf61c2,p,release,0,&rc) && rc==-1021 && !replies_freed);
    native_free(p);assert(!snapshot().live_replies);
    for (unsigned int i=0;i<50;i++) aba(0);
    assert(argc==1 || argc==2);if (argc==2) boot_tests(argv[1]);
    puts("AUDIO_VOLUME_CONFIG_OWNERSHIP_ABA_PASS");return 0;
}
