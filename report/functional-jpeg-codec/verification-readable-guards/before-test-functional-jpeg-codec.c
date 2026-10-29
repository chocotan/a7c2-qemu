/* SPDX-License-Identifier: MIT */
/* gpt-6.1-sol, thinking=max. Host-focused execution authorized for central fixes.
 * The bridge and model are real. Original AArch64 methods are represented by
 * explicit source-pinned host ABI fixtures; this is not original SDK execution. */
#define FCAM_HOST_TEST 1
#define FCAM_TEST_WAIT_NS UINT64_C(2000000000)
#include "functional-camera-bridge.c"
#include "functional-jpeg-codec.h"
#include "../../report/functional-camera-core/functional-camera-core.h"
#include <assert.h>
#include <stddef.h>
#include <stdlib.h>
#include <sys/wait.h>

#define TEST_QID UINT32_C(0x80550119)
#define TEST_HANDLE 71u
/* The real 2048x1536 quality-100 result exceeds 2 MiB. */
#define ARENA_SIZE (4u * 1024u * 1024u)
#define NATIVE_PREFIX 575u
uint32_t fixture_entry(void *, const uint8_t *) __asm__(FUNCTIONAL_JPEG_CODEC_EXEC_SYMBOL);
uint32_t fixture_response(void *, const uint8_t *, uint16_t) __asm__(FUNCTIONAL_JPEG_CODEC_RES_SYMBOL);
uint32_t fixture_main_entry(void *, const uint8_t *) __asm__(FUNCTIONAL_JPEG_CODEC_MAIN_EXEC_SYMBOL);
uint32_t fixture_main_response(void *, const uint8_t *, uint16_t) __asm__(FUNCTIONAL_JPEG_CODEC_MAIN_RES_SYMBOL);
uint32_t fixture_comp_entry(void *, const uint8_t *) __asm__(FUNCTIONAL_JPEG_CODEC_COMP_EXEC_SYMBOL);
uint32_t fixture_comp_response(void *, const uint8_t *, uint16_t) __asm__(FUNCTIONAL_JPEG_CODEC_COMP_RES_SYMBOL);
void functional_jpeg_test_lock_owner(void);
void functional_jpeg_test_unlock_owner(void);

static const char *scenario;
static unsigned char object_store[0x30], *object=object_store, manager[0x20], control[0x80];
static uint8_t comp_object[0x28], config_copy[0x78], config_store[0x78], *native_config=config_store;
static uintptr_t control_vtable[22];
static uint8_t dmm_completion[32], previous_ack[16];
static int main_kind, comp_execs, entry_origin=1, reentries, comp_notes, config_notes;
static uint8_t selector, quality_code;
static uint8_t *arena;
static struct fcam_model *model;
static int native_execs, native_responses, requests_freed, release_count, borrow_count;
static _Atomic int record_calls, readback_notes, original_notes, native_done_notes;
static _Atomic int lease_notes, received_notes, freed_notes, rescmd_notes, serialized_writes;
static uintptr_t reply_addresses[2];
static char receipt_text[32768];
static size_t receipt_bytes;
static struct message *retained_reply;
static uint8_t actual_request[104], received_bodies[2][16];
static long producer_tid, receiver_tids[2];
static int send_calls, get_next_calls, lease_retired, callback_origin = 1;
static int memory_failure, bad_shape, bad_request, send_failure, request_release_error;
static uint32_t native_length, native_error, requested_width = 1280, requested_height = 720;
static uint32_t requested_quality = 90;
static uint8_t mode;
static uint64_t generation = 1, lease_token;
static struct functional_mpr_memory_lease held;
static pthread_mutex_t fixture_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t fixture_wake = PTHREAD_COND_INITIALIZER;
static int block_backend, backend_entered, allow_backend;
static unsigned bridge_stills, bridge_chunks, bridge_releases;
static uint8_t *last_model_output;
static size_t last_model_bytes;
struct message { uint32_t source, bytes; uint8_t data[104]; struct message *next; };
static struct message *queue_first, *queue_last;
static struct full_imaging_io fixture_io;

static void store64(uint8_t *p, uint64_t v) { for (unsigned i=0;i<8;++i)p[i]=(uint8_t)(v>>(8*i)); }
static uint16_t half(const uint8_t *p) { return (uint16_t)(p[0] | (uint16_t)p[1]<<8); }
static void store16(uint8_t *p, uint16_t v) { p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8); }
static struct message *owner_of(void *p) { return (struct message *)((uint8_t *)p - offsetof(struct message,data)); }
static uint32_t packet_source(void *p) { return owner_of(p)->source; }
static uint32_t packet_size(void *p) { return owner_of(p)->bytes; }
static int packet_release(uint32_t destination, void *p) {
    assert(destination == FUNCTIONAL_JPEG_CODEC_SID);
    if(request_release_error)return request_release_error;
    ++requests_freed; free(owner_of(p)); return 0;
}
static void packet_header(uint8_t *p, size_t bytes) {
    memset(p,0,bytes); put32(p,TEST_QID); put32(p+4,UINT32_C(0xa0a0a0a0));
    store16(p+8,1); store16(p+10,(uint16_t)bytes); put32(p+12,24); put32(p+16,(uint32_t)bytes);
}
static uint16_t sdk_cid(void *p, uint16_t category) { assert(p==manager&&category==3); return 0x2000; }
static uint16_t sdk_mid(void *p, uint16_t category, uint16_t command) {
    assert(p==manager&&category==3&&command==0x304);return 4;
}
static uint32_t sdk_qid(void *p) { return get32((const uint8_t *)p+8); }
static uint32_t sdk_exec(void *p, const uint8_t *trigger) {
    assert(p==object); ++native_execs;
    if(main_kind){
        assert(trigger);if((int16_t)half(trigger+2))return 1;
        assert(trigger==dmm_completion);
        if(!strcmp(scenario,"main-reentry")){
            assert(fixture_main_entry(object,trigger)==0x201);++reentries;
        }
    }else assert(trigger==(const uint8_t *)(uintptr_t)1);
    if (!strcmp(scenario,"off") || !strcmp(scenario,"main-off")) { errno=EINTR;return 0x12345678; }
    struct message *message=calloc(1,sizeof *message);assert(message);
    message->source=TEST_QID;message->bytes=104;
    packet_header(message->data,message->bytes);
    uint8_t *body=message->data+24;
    store16(body,0x2000);store16(body+2,4);store16(body+4,80);store16(body+8,7);
    store16(body+12,0x2000);store16(body+14,0x8310);
    store16(body+16,0x2000);store16(body+18,0x8311);
    put32(body+0x18,0);put32(body+0x1c,72);put32(body+0x20,0);
    put32(body+0x24,0);put32(body+0x28,TEST_HANDLE);put32(body+0x2c,0);
    put32(body+0x34,ARENA_SIZE);put32(body+0x38,64);put32(body+0x3c,ARENA_SIZE-64);
    store16(body+0x40,(uint16_t)requested_width);store16(body+0x42,(uint16_t)requested_height);
    store16(body+0x44,1280);store16(body+0x46,720);
    body[0x49]=main_kind?quality_code:mode?4:3;body[0x4a]=2;body[0x4b]=mode;
    if(bad_request)body[0x49]=9;
    if(!strcmp(scenario,"main-option"))body[0x4c]=1;
    if(!strcmp(scenario,"main-option2"))body[0x4d]=1;
    if(!strcmp(scenario,"main-soi"))body[0x4b]^=1;
    if(!strcmp(scenario,"main-zero") || !strcmp(scenario,"main-screen-zero"))store16(body+0x40,0);
    if(!strcmp(scenario,"main-primary") || !strcmp(scenario,"main-screen-primary"))store16(body+0x44,0);
    if(!strcmp(scenario,"main-primary-mismatch"))store16(body+0x44,640);
    if(!strcmp(scenario,"main-overflow"))put32(body+0x38,UINT32_MAX);
    if(!strcmp(scenario,"main-malformed"))store16(body+6,1);
    if(!strcmp(scenario,"main-length")){put32(body+0x34,65);put32(body+0x3c,1);}
    if(!strcmp(scenario,"main-request-size"))message->bytes=103;
    if(!strcmp(scenario,"length")) { put32(body+0x34,65);put32(body+0x3c,1); }
    memcpy(actual_request,message->data,sizeof actual_request);producer_tid=syscall(SYS_gettid);
    int result=37;
    int handled=functional_jpeg_codec_dispatch(FUNCTIONAL_JPEG_CODEC_SID,message->data,&fixture_io,&result);
    assert(handled);
    if(result)free(message);
    errno=EINTR;
    return 0;
}
static uint32_t sdk_res(void *p, const uint8_t *body, uint16_t mid) {
    ++native_responses;
    uint32_t status=get32(body+8);
    if(mid==0x8310) {
        assert(p==object);
        if(main_kind){
            if(!strcmp(scenario,"main-reentry")){
                assert(fixture_main_response(p,body,mid)==0x201);++reentries;
            }
            return 0;
        }
        if(status)native_error=status;
        return status?0x201:0x200;
    }
    assert(mid==0x8311 && p==(main_kind?(void *)comp_object:(void *)object));
    native_length=status?0:get32(body+12);native_error=status;
    if(main_kind){
        if(!strcmp(scenario,"main-reentry")){
            assert(fixture_comp_response(p,body,mid)==0x201);++reentries;
        }
        put32(native_config+0x5c+12u*selector,native_length+(!strcmp(scenario,"main-native-length")?1u:0u));
        assert(!memcmp(config_copy,config_store,0x54));
    }else put32(control+(mode?0x68:0x5c),native_length);
    return status?0x201:0;
}
static uint32_t sdk_comp_exec(void *p,const uint8_t *trigger){
    assert(p==comp_object && !memcmp(trigger,previous_ack,16));++comp_execs;
    if(!strcmp(scenario,"main-reentry")){
        assert(fixture_comp_entry(p,trigger)==0x201);++reentries;
    }
    return 0;
}
static uint32_t sdk_get_pointer(void *p,uint32_t key,void **out){
    assert(p==control && key==0x1048);*out=native_config;return 0;
}
static void sdk_message_ctor(void *p) { memset(p,0,408); }
static void sdk_nop(void *p) { assert(p); }
static void sdk_sender_ctor(void *p) { memset(p,0,8); }
static int sdk_message_data(void *p, void *body, uint16_t bytes) {
    assert(bytes==16);uint8_t *message=p;
    put32(message+8,1);store16(message+12,40);
    packet_header(message+24,40);put32(message+24,0);memcpy(message+48,body,16);
    return 0;
}
static int sdk_message_source(void *p, uint32_t source) { put32((uint8_t *)p+16,source);return 0; }
static int sdk_send(void *sender, uint32_t destination, void *p) {
    assert(sender&&destination==TEST_QID);uint8_t *message=p;
    assert(get32(message+8)==1&&half(message+34)==40);
    pthread_mutex_lock(&fixture_lock);
    ++send_calls;
    if(send_failure && (send_failure==1 || send_calls==send_failure)) { pthread_mutex_unlock(&fixture_lock);return -EIO; }
    struct message *out=calloc(1,sizeof *out);assert(out);
    out->source=get32(message+16);out->bytes=half(message+34);
    memcpy(out->data,message+24,out->bytes);
    assert(out->source==FUNCTIONAL_JPEG_CODEC_SID);
    if(queue_last)queue_last->next=out;else queue_first=out;
    queue_last=out;pthread_cond_broadcast(&fixture_wake);
    pthread_mutex_unlock(&fixture_lock);
    return 0;
}
#define MAP(name, function) if(!strcmp(symbol,name)) { \
    void (*value)(void)=(void (*)(void))function;void *out=NULL; \
    _Static_assert(sizeof value==sizeof out,"test function ABI");memcpy(&out,&value,sizeof out);return out; }
void *functional_jpeg_test_next(const char *symbol) {
    ++get_next_calls;
    MAP(FUNCTIONAL_JPEG_CODEC_EXEC_SYMBOL,sdk_exec);
    MAP(FUNCTIONAL_JPEG_CODEC_RES_SYMBOL,sdk_res);
    MAP(FUNCTIONAL_JPEG_CODEC_MAIN_EXEC_SYMBOL,sdk_exec);
    MAP(FUNCTIONAL_JPEG_CODEC_MAIN_RES_SYMBOL,sdk_res);
    MAP(FUNCTIONAL_JPEG_CODEC_COMP_EXEC_SYMBOL,sdk_comp_exec);
    MAP(FUNCTIONAL_JPEG_CODEC_COMP_RES_SYMBOL,sdk_res);
    MAP("_ZN14AvbbcParamCtrl16ParameterControl8GetValueEjRPv",sdk_get_pointer);
    MAP("_ZN20InfraAvbbcMsgManager9GetOsalIdEv",sdk_qid);
    MAP("_ZN20InfraAvbbcMsgManager10ConvertCidEt",sdk_cid);
    MAP("_ZN20InfraAvbbcMsgManager13ConvertCmdMidEtt",sdk_mid);
    MAP("_ZN16DataflowInfraMsgC1Ev",sdk_message_ctor);
    MAP("_ZN16DataflowInfraMsgD1Ev",sdk_nop);
    MAP("_ZN16DataflowInfraMsg14SetDataflowMsgEPvt",sdk_message_data);
    MAP("_ZN16DataflowInfraMsg8SetSrcIdEj",sdk_message_source);
    MAP("_ZN19DataflowInfraSenderC1Ev",sdk_sender_ctor);
    MAP("_ZN19DataflowInfraSenderD1Ev",sdk_nop);
    MAP("_ZN19DataflowInfraSender9SendASyncEjP16DataflowInfraMsg",sdk_send);
    assert(0);return NULL;
}
int functional_jpeg_test_binding(uintptr_t *base) { *base=0x10000000;return 0; }
int functional_jpeg_test_caller(uintptr_t caller, int response) {
    assert(caller);return response==1?callback_origin:entry_origin;
}
void functional_jpeg_test_after_copy(void *p, size_t bytes) {
    if(!strcmp(scenario,"readback") || !strcmp(scenario,"main-readback"))((uint8_t *)p)[bytes/2]^=0x40;
}
int functional_mpr_memory_acquire_sds(uint32_t type,uint32_t handle,uint32_t offset,
    size_t bytes,struct functional_mpr_memory_lease *out) {
    ++borrow_count;
    if(memory_failure)return memory_failure;
    if(type||handle!=TEST_HANDLE||offset>=ARENA_SIZE||bytes>ARENA_SIZE-offset)return -ENOENT;
    assert(!lease_token);
    held=(struct functional_mpr_memory_lease){
        .span={.virtual_base=(uintptr_t)arena,.iova_base=(uintptr_t)arena,.generation=generation,
            .capacity=ARENA_SIZE,.offset=offset,.group=70,.unit=TEST_HANDLE,.area=3,.unit_type=3},
        .address=(uintptr_t)arena+offset,.bytes=bytes,.token=++lease_token};
    if(!strcmp(scenario,"alias") || !strcmp(scenario,"main-alias"))held.address=(uintptr_t)object;
    if(!strcmp(scenario,"main-lease-offset"))++held.span.offset;
    *out=held;return 0;
}
int functional_mpr_memory_validate(const struct functional_mpr_memory_lease *lease) {
    return lease_retired||!lease_token||memcmp(lease,&held,sizeof held)?-ESTALE:0;
}
int functional_mpr_memory_write(const struct functional_mpr_memory_lease *lease,
    size_t offset,const void *data,size_t bytes) {
    pthread_mutex_lock(&fixture_lock);
    int rc=functional_mpr_memory_validate(lease);
    if(!rc && (!bytes || offset>lease->bytes || bytes>lease->bytes-offset))rc=-EINVAL;
    if(!rc){
        memcpy((void *)(lease->address+offset),data,bytes);
        assert(!memcmp((void *)(lease->address+offset),data,bytes));++serialized_writes;
    }
    pthread_mutex_unlock(&fixture_lock);return rc;
}
int functional_mpr_memory_release(uint64_t token) {
    assert(token==lease_token);
    if(!strcmp(scenario,"receipt-release") || !strcmp(scenario,"receipt-request-release") ||
        !strcmp(scenario,"main-release") || !strcmp(scenario,"main-request-release"))return -91;
    lease_token=0;++release_count;return 0;
}
int fcam_test_mlock(const void *p,size_t bytes) { assert(p&&bytes==FCAM_MAILBOX_BYTES);return 0; }
int fcam_test_munlock(const void *p,size_t bytes) { assert(p&&bytes==FCAM_MAILBOX_BYTES);return 0; }
int fcam_test_random(uint64_t *out) { *out=7;return 0; }
int fcam_test_pagemap(const void *p,uint64_t *out) {
    assert(p);for(unsigned i=0;i<FCAM_MAILBOX_PAGES;++i)out[i]=RAM_FIRST+(i+1)*FCAM_PAGE_BYTES;return 0;
}
void fcam_test_after_copy(void *p,size_t bytes) { (void)p;(void)bytes; }
static const char *jpeg_field(const char *text,const char *name) {
    char key[80];assert(snprintf(key,sizeof key,"%s=",name)>0);const char *p=text;
    while((p=strstr(p,key))){if(p==text || p[-1]==' ')return p+strlen(key);p++;}
    assert(!"missing JPEG receipt field");return NULL;
}
static uint64_t jpeg_number(const char *text,const char *name,int base) {
    const char *p=jpeg_field(text,name);char *end=NULL;uint64_t value=strtoull(p,&end,base);
    assert(end!=p && (!*end || *end==' '));return value;
}
static void jpeg_hex(const char *text,const char *name,uint8_t *out,size_t bytes) {
    const char *p=jpeg_field(text,name);assert(strlen(p)>=bytes*2);
    for(size_t i=0;i<bytes;i++){
        unsigned value=0;
        for(unsigned k=0;k<2;k++){char c=p[2*i+k];assert((c>='0' && c<='9') || (c>='a' && c<='f'));
            value=value*16+(unsigned)(c<='9'?c-'0':c-'a'+10);}
        out[i]=(uint8_t)value;
    }
    assert(!p[2*bytes] || p[2*bytes]==' ');
}
static void record_metadata(const char *tag,const char *text) {
    if(strcmp(tag,"FUNCTIONAL_JPEG_CODEC ")){
        fprintf(stderr,"%s%s\n",tag,text);return;
    }
    struct functional_jpeg_codec_snapshot snapshot;
    assert(!functional_jpeg_codec_snapshot(&snapshot));++record_calls;
    assert(strlen(text)<1024 && !strstr(text,"operation=receipt-format-error"));
    assert(strstr(text,"physical_asic_compatible=0 capture_verified=0"));
    if(getenv("FJPEG_HOST_RECEIPTS")){
        pthread_mutex_lock(&fixture_lock);
        int n=snprintf(receipt_text+receipt_bytes,sizeof receipt_text-receipt_bytes,"%s%s\n",tag,text);
        assert(n>0 && (size_t)n<sizeof receipt_text-receipt_bytes);receipt_bytes+=(size_t)n;
        pthread_mutex_unlock(&fixture_lock);
    }
    if(jpeg_number(text,"sequence",0)){
        assert(strstr(text,main_kind?" kind=main ":" kind=without-pin "));
        assert(jpeg_number(text,"selector",0)==selector);
    }
    if(strstr(text,"operation=original-maincomp-config ")){
        assert(jpeg_number(text,"native_config",0)==(uintptr_t)native_config);
        assert(jpeg_number(text,"config_length_offset",0)==0x5c+12u*selector);
        assert(jpeg_number(text,"expected_length",0)==native_length);
        assert(jpeg_number(text,"actual_length",0)==get32(native_config+0x5c+12u*selector));
        ++config_notes;
    }
    if(strstr(text,"operation=original-maincomp-exec ")){
        uint8_t body[16];jpeg_hex(text,"previous_ack_hex",body,sizeof body);
        assert(!memcmp(body,previous_ack,sizeof body));
        if(!strtoll(jpeg_field(text,"rc"),NULL,0)){
            assert(jpeg_number(text,"comp_object",0)==(uintptr_t)comp_object);
            assert(jpeg_number(text,"comp_exec_entry",0)==0x10122dfc);
            assert(jpeg_number(text,"previous_ack_address",0)==(uintptr_t)previous_ack);
            assert(jpeg_number(text,"original_result",0)==0 && jpeg_number(text,"native_config",0)==(uintptr_t)native_config);
            ++comp_notes;
        }
    }
    if(strstr(text,"operation=original-request ")){
        uint8_t wire[104];jpeg_hex(text,"request_hex",wire,sizeof wire);
        assert(!memcmp(wire,actual_request,sizeof wire));
        assert(jpeg_number(text,"trigger_fnv",16)==fnv(wire,sizeof wire));
        assert(jpeg_number(text,"native_bytes",0)==sizeof wire);
        assert(jpeg_number(text,"producer_tid",0)==(uint64_t)producer_tid);++original_notes;
    }
    if(strstr(text,"operation=request-lease-release-failed ")){
        uint8_t wire[104];jpeg_hex(text,"request_hex",wire,sizeof wire);
        assert(!memcmp(wire,actual_request,sizeof wire));
        assert(strtoll(jpeg_field(text,"rc"),NULL,0)==-91 && strtoll(jpeg_field(text,"primary_rc"),NULL,0)==-77);
        assert(jpeg_number(text,"lease_generation",0)==generation && jpeg_number(text,"lease_token",0)==held.token);
    }
    if(strstr(text,"operation=original-request-lease ")){
        assert(jpeg_number(text,"sds_type",0)==0 && jpeg_number(text,"sds_handle",0)==TEST_HANDLE);
        assert(jpeg_number(text,"sds_offset",0)==0 && jpeg_number(text,"stream_position",0)==64);
        assert(jpeg_number(text,"lease_offset",0)==64 && jpeg_number(text,"lease_address",0)==(uintptr_t)arena+64);
        assert(jpeg_number(text,"lease_capacity",0)==held.bytes && jpeg_number(text,"lease_generation",0)==generation);
        assert(jpeg_number(text,"lease_token",0)==held.token && jpeg_number(text,"lease_unit",0)==TEST_HANDLE);
        assert(jpeg_number(text,"lease_area",0)==3 && jpeg_number(text,"lease_unit_type",0)==3);++lease_notes;
    }
    if(strstr(text,"operation=output-readback ")){
        size_t bytes=(size_t)jpeg_number(text,"bytes",0),skip=mode?0:2;
        assert(bytes==last_model_bytes-skip && serialized_writes==1);
        assert(jpeg_number(text,"readback_fnv",16)==fnv(arena+64,bytes));
        assert(jpeg_number(text,"output_fnv",16)==fnv(arena+64,bytes));
        assert(jpeg_number(text,"model_fnv",16)==fnv(last_model_output,last_model_bytes));
        assert(jpeg_number(text,"model_bytes",0)==last_model_bytes && jpeg_number(text,"model_offset",0)==skip);
        assert(jpeg_number(text,"model_token",0)>0 && jpeg_number(text,"lease_token",0)==held.token);
        assert(jpeg_number(text,"lease_generation",0)==generation && jpeg_number(text,"lease_address",0)==(uintptr_t)arena+64);
        ++readback_notes;
    }
    int observed=strstr(text,"operation=original-received-")!=NULL;
    int freed=strstr(text,"operation=original-freed-")!=NULL;
    int callback=strstr(text,"operation=original-rescmd-")!=NULL;
    if(observed || freed || callback){
        int completion=strstr(text,observed?"operation=original-received-done ":
            freed?"operation=original-freed-done ":"operation=original-rescmd-done ")!=NULL;
        uint8_t body[16];jpeg_hex(text,"response_hex",body,sizeof body);
        assert(!memcmp(body,received_bodies[completion],sizeof body));
        assert(jpeg_number(text,"receiver_tid",0)==(uint64_t)receiver_tids[completion]);
        assert(jpeg_number(text,"receiver_pid",0)==(uint64_t)getpid());
        assert(jpeg_number(text,"response_source",0)==FUNCTIONAL_JPEG_CODEC_SID);
        assert(jpeg_number(text,"response_destination",0)==TEST_QID);
        assert(jpeg_number(text,"lease_generation",0)==generation && jpeg_number(text,"lease_token",0)==held.token);
        if(observed || freed){
            uint8_t packet[40];jpeg_hex(text,"reply_hex",packet,sizeof packet);
            assert(!memcmp(packet+24,body,sizeof body));
            assert(jpeg_number(text,"reply_address",0)==reply_addresses[completion]);
            assert(jpeg_number(text,"receiver_tid",0)==(uint64_t)syscall(SYS_gettid));
            if(freed){
                int expected=strstr(scenario,"free-fail") && completion==(strstr(scenario,"-done")!=NULL)?-77:0;
                assert(strtoll(jpeg_field(text,"free_rc"),NULL,0)==expected);++freed_notes;
            }else ++received_notes;
        } else{
            uint32_t expected=main_kind&&!completion?0:get32(body+8)?0x201:completion?0:0x200;
            assert(jpeg_number(text,"original_result",0)==expected && jpeg_number(text,"expected_result",0)==expected);
            assert(jpeg_number(text,"callback_caller",0) &&
                jpeg_number(text,"res_entry",0)==(main_kind?(completion?0x10122b44:0x10120e64):0x1011a9dc));
            assert(jpeg_number(text,"response_mid",0)==half(body+2));
            ++rescmd_notes;
        }
    }
    if(strstr(text,"operation=original-rescmd-done "))++native_done_notes;
}
static void short_pause(void) { const struct timespec delay={0,1000000};nanosleep(&delay,NULL); }
static void *model_server(void *unused) {
    (void)unused;uint64_t previous=0;
    for(;;) {
        uint32_t status=status_load();
        if(status==FCAM_STATUS_CLOSED) { status_store(FCAM_STATUS_DETACHED);return NULL; }
        if(status!=FCAM_STATUS_REQUEST||get64(mailbox+FCAM_H_SEQUENCE)==previous) { short_pause();continue; }
        previous=get64(mailbox+FCAM_H_SEQUENCE);
        uint32_t op=get32(mailbox+FCAM_H_OPCODE),size=get32(mailbox+FCAM_H_REQUEST_BYTES);
        assert(get64(mailbox+FCAM_H_REQUEST_FNV)==fnv(mailbox+FCAM_HEADER_BYTES,size));
        if(op==FCAM_OP_STILL) {
            pthread_mutex_lock(&fixture_lock);
            ++bridge_stills;backend_entered=1;pthread_cond_broadcast(&fixture_wake);
            while(block_backend&&!allow_backend)pthread_cond_wait(&fixture_wake,&fixture_lock);
            pthread_mutex_unlock(&fixture_lock);
            assert(size==16&&get32(mailbox+FCAM_HEADER_BYTES)==FCAM_STILL_FULL_JPEG);
            assert(get32(mailbox+FCAM_HEADER_BYTES+4)==(requested_width?requested_width:640));
            assert(get32(mailbox+FCAM_HEADER_BYTES+8)==(requested_height?requested_height:480));
            assert(get32(mailbox+FCAM_HEADER_BYTES+12)==requested_quality);
            assert(get32(mailbox+FCAM_H_NATIVE_SOURCE)==TEST_QID);
            assert(get32(mailbox+FCAM_H_NATIVE_DESTINATION)==FUNCTIONAL_JPEG_CODEC_SID);
            assert(get32(mailbox+FCAM_H_NATIVE_BYTES)==104);
            assert(get64(mailbox+FCAM_H_NATIVE_FNV));
            if(!strcmp(scenario,"stale") || !strcmp(scenario,"main-stale"))lease_retired=1;
        }
        struct fcam_exec_result result={0};
        int rc;
        /* The model forbids aliased input/output; transport storage is copied. */
        uint8_t input[FCAM_DATA_BYTES],output[FCAM_DATA_BYTES];
        memcpy(input,mailbox+FCAM_HEADER_BYTES,size);
        if(bad_shape&&op==FCAM_OP_STILL)put32(input+4,get32(input+4)+1);
        if((!strcmp(scenario,"backend") || !strcmp(scenario,"main-backend"))&&op==FCAM_OP_STILL)rc=-EIO;
        else rc=fcam_model_request(model,op,size?input:NULL,size,output,sizeof output,&result);
        if(op==FCAM_OP_READ_RESULT)++bridge_chunks;
        if(op==FCAM_OP_RELEASE_RESULT)++bridge_releases;
        if(!rc&&op==FCAM_OP_STILL) {
            assert(!last_model_output);last_model_bytes=(size_t)result.total;
            last_model_output=malloc(last_model_bytes);assert(last_model_output);
            memcpy(last_model_output,output,result.used);
        } else if(!rc&&op==FCAM_OP_READ_RESULT)
            memcpy(last_model_output+result.offset,output,result.used);
        memcpy(mailbox+FCAM_HEADER_BYTES,output,result.used);
        put32(mailbox+FCAM_H_RESPONSE_BYTES,(uint32_t)result.used);
        put32(mailbox+FCAM_H_ERROR,(uint32_t)rc);
        put64(mailbox+FCAM_H_RESULT_TOKEN,result.token);put64(mailbox+FCAM_H_RESULT_TOTAL,result.total);
        put64(mailbox+FCAM_H_RESULT_OFFSET,result.offset);
        put64(mailbox+FCAM_H_RESPONSE_FNV,fnv(mailbox+FCAM_HEADER_BYTES,result.used));
        status_store(FCAM_STATUS_RESPONSE);
    }
}
static struct message *receive_packet(void) {
    struct timespec deadline;assert(!clock_gettime(CLOCK_REALTIME,&deadline));deadline.tv_sec+=10;
    pthread_mutex_lock(&fixture_lock);
    while(!queue_first)assert(!pthread_cond_timedwait(&fixture_wake,&fixture_lock,&deadline));
    struct message *p=queue_first;queue_first=p->next;if(!queue_first)queue_last=NULL;
    pthread_mutex_unlock(&fixture_lock);return p;
}
static void *free_on_foreign_thread(void *pointer) {
    assert(functional_jpeg_codec_observe_freed(TEST_QID,pointer,0)==0);return NULL;
}
static uint32_t consume_packet(int observe,int mutate_source,int mutate_body) {
    struct message *p=receive_packet();
    if(strstr(scenario,"free-reuse") && half(p->data+26)==0x8311){
        void *others[1024];size_t count=0;struct message *replacement=NULL;
        while(count<sizeof others/sizeof *others){
            struct message *candidate=malloc(sizeof *candidate);assert(candidate);
            if((uintptr_t)candidate->data==reply_addresses[0]){replacement=candidate;break;}
            others[count++]=candidate;
        }
        assert(replacement);memcpy(replacement,p,sizeof *replacement);free(p);p=replacement;
        while(count)free(others[--count]);
        assert(functional_jpeg_codec_observe_freed(TEST_QID,p->data,0)==0);
    }
    if(mutate_source)p->source^=0x10;
    if(mutate_body)p->data[24+6]^=1;
    int completion=half(p->data+26)==0x8311;
    memcpy(received_bodies[completion],p->data+24,16);receiver_tids[completion]=syscall(SYS_gettid);
    uintptr_t address=(uintptr_t)p->data;reply_addresses[completion]=address;
    if(observe) {
        int rc=functional_jpeg_codec_observe_received(TEST_QID,p->data,&fixture_io);
        assert(rc==(mutate_source?0:mutate_body || (completion && !strcmp(scenario,"main-no-comp"))?-EPROTO:1));
        if(!strcmp(scenario,"duplicate"))
            assert(functional_jpeg_codec_observe_received(TEST_QID,p->data,&fixture_io)==-EPROTO);
        if(strstr(scenario,"free-fork")){
            functional_jpeg_test_lock_owner();pid_t child=fork();assert(child>=0);
            if(!child){errno=EDOM;int rc=functional_jpeg_codec_observe_freed(TEST_QID,p->data,0);
                _exit(rc==-ECHILD && errno==EDOM?0:1);}
            int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
            functional_jpeg_test_unlock_owner();
        }
    }
    uint8_t body[16];memcpy(body,p->data+24,sizeof body);
    int free_case=strstr(scenario,"free-")!=NULL && (completion==(strstr(scenario,"-done")!=NULL));
    int omit=free_case && strstr(scenario,"free-none"), fail=free_case && strstr(scenario,"free-fail");
    int wrong_tid=free_case && strstr(scenario,"free-tid"), wrong_destination=free_case && strstr(scenario,"free-destination");
    if(omit || fail)retained_reply=p;else free(p);
    if(!omit){
        errno=EDOM;
        if(wrong_tid){pthread_t thread;assert(!pthread_create(&thread,NULL,free_on_foreign_thread,(void *)address));
            assert(!pthread_join(thread,NULL));}
        else{
            int rc=functional_jpeg_codec_observe_freed(wrong_destination?TEST_QID+1:TEST_QID,(void *)address,fail?-77:0);
            int claimed=observe && !mutate_source && !mutate_body &&
                !(completion && !strcmp(scenario,"main-no-comp"));
            assert(rc==(!claimed || wrong_destination?0:fail?-77:1));
            assert(errno==EDOM);
            if(free_case && (strstr(scenario,"free-duplicate") || fail))
                assert(functional_jpeg_codec_observe_freed(TEST_QID,(void *)address,0)==0);
        }
    }
    if(main_kind){
        if(!completion)memcpy(previous_ack,body,sizeof body);
        return completion?fixture_comp_response(!strcmp(scenario,"main-wrong-object")?object:comp_object,body,half(body+2)):
            fixture_main_response(object,previous_ack,half(body+2));
    }
    return fixture_response(object,body,half(body+2));
}
static void *consume_on_receiver(void *unused) {
    (void)unused;assert(consume_packet(1,0,0)==0x200);assert(!consume_packet(1,0,0));return NULL;
}
static void wait_finished(void) {
    for(unsigned i=0;i<10000;++i) {
        struct functional_jpeg_codec_snapshot s;assert(!functional_jpeg_codec_snapshot(&s));
        pthread_mutex_lock(&fixture_lock);int sent=send_calls;pthread_mutex_unlock(&fixture_lock);
        if(!s.working&&sent)return;
        short_pause();
    }
    assert(0);
}
static void emit_blob(const char *name,const void *p,size_t bytes) {
    assert(printf("BLOB %s %zu\n",name,bytes)>0);assert(fwrite(p,1,bytes,stdout)==bytes);
}
static int test_main_sequence(void){
    main_kind=1;quality_code=2;
    if(!strcmp(scenario,"main-thumb")){selector=1;mode=1;requested_width=160;requested_height=120;quality_code=4;}
    if(!strncmp(scenario,"main-screen",11)){selector=2;requested_width=640;requested_height=360;quality_code=3;}
    if(!strncmp(scenario,"main-q",6))quality_code=(uint8_t)strtoul(scenario+6,NULL,10);
    memset(object,0,0x28);memset(manager,0,sizeof manager);memset(control,0,sizeof control);
    store64(object,UINT64_C(0x101af7c0));put32(object+0xc,0x11223344);
    put32(manager+8,TEST_QID);store64(object+0x10,(uintptr_t)manager);store64(object+0x18,(uintptr_t)control);
    object[0x20]=selector;memcpy(comp_object,object,sizeof comp_object);store64(comp_object,UINT64_C(0x101af808));
    unsigned config_offset=0x54+12u*selector;
    uint32_t requested_capacity=!strcmp(scenario,"main-length")?1:ARENA_SIZE-64;
    put32(config_store+config_offset,TEST_HANDLE);put32(config_store+config_offset+4,64);
    put32(config_store+config_offset+8,requested_capacity);memcpy(config_copy,config_store,sizeof config_copy);
    void (*getter)(void)=(void (*)(void))sdk_get_pointer;
    memcpy(&control_vtable[21],&getter,sizeof getter);store64(control,(uintptr_t)control_vtable);
    if(!strcmp(scenario,"main-off")){
        assert(fixture_main_entry(object,dmm_completion)==0x12345678 && errno==EINTR);
        uint8_t body[16]={0};assert(!fixture_main_response(object,body,0x8310));
        assert(!fixture_comp_entry(comp_object,previous_ack));
        assert(!fixture_comp_response(comp_object,body,0x8311));
        assert(native_execs==1 && native_responses==2 && comp_execs==1 && get_next_calls==4 && !borrow_count);
        return 0;
    }
    void *mapped=mmap((void *)UINT32_C(0x38000000),ARENA_SIZE,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(mapped!=MAP_FAILED && (uintptr_t)mapped<=UINT32_MAX-ARENA_SIZE);arena=mapped;memset(arena,0xa5,ARENA_SIZE);
    assert(!functional_jpeg_codec_enable(record_metadata));
    errno=EDOM;
    assert(functional_jpeg_codec_observe_freed(TEST_QID,(void *)1,0)==0 && errno==EDOM);
    void *object_mapping=NULL,*trigger_mapping=NULL,*config_mapping=NULL;
    size_t page=(size_t)sysconf(_SC_PAGESIZE);
    const uint8_t *trigger=dmm_completion;
    if(!strcmp(scenario,"main-small-object") || !strcmp(scenario,"main-short-object")){
        object_mapping=mmap(NULL,2*page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        assert(object_mapping!=MAP_FAILED && !munmap((uint8_t *)object_mapping+page,page));
        size_t bytes=!strcmp(scenario,"main-small-object")?0x28:0x20;
        object=(uint8_t *)object_mapping+page-bytes;memcpy(object,object_store,bytes);
    }
    if(!strcmp(scenario,"main-dmm-failed") || !strcmp(scenario,"main-dmm-short")){
        trigger_mapping=mmap(NULL,2*page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        assert(trigger_mapping!=MAP_FAILED && !munmap((uint8_t *)trigger_mapping+page,page));
        uint8_t *short_trigger=(uint8_t *)trigger_mapping+page-4;
        memset(short_trigger,0,4);store16(short_trigger+2,!strcmp(scenario,"main-dmm-failed")?0xffff:0);
        trigger=short_trigger;
    }
    if(!strcmp(scenario,"main-bad-trigger"))trigger=(const uint8_t *)(uintptr_t)1;
    if(!strcmp(scenario,"main-vptr"))object[0]^=1;
    if(!strcmp(scenario,"main-selector"))object[0x20]=3;
    if(!strcmp(scenario,"main-caller"))entry_origin=0;
    if(!strcmp(scenario,"main-range"))requested_width=8193;
    if(!strcmp(scenario,"main-quality"))bad_request=1;
    if(!strcmp(scenario,"main-missing"))memory_failure=-ENOENT;
    if(!strcmp(scenario,"main-readonly"))assert(!mprotect(arena,ARENA_SIZE,PROT_READ));
    if(!strcmp(scenario,"main-request-release"))request_release_error=-77;
    if(!strcmp(scenario,"main-fork")){
        functional_jpeg_test_lock_owner();pid_t child=fork();assert(child>=0);
        if(!child){
            struct functional_jpeg_codec_snapshot s;uint8_t body[16]={0};
            _exit(functional_jpeg_codec_snapshot(&s)==-ECHILD && functional_jpeg_codec_shutdown()==-ECHILD &&
                fixture_main_entry(object,dmm_completion)==0x201 && fixture_main_response(object,body,0x8310)==0x201 &&
                fixture_comp_entry(comp_object,body)==0x201 && fixture_comp_response(comp_object,body,0x8311)==0x201 &&
                functional_jpeg_codec_observe_freed(TEST_QID,(void *)1,0)==-ECHILD?0:1);
        }
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
        functional_jpeg_test_unlock_owner();assert(!native_execs && !borrow_count);
        goto idle_cleanup;
    }
    const char *rejected[]={"main-short-object","main-dmm-short","main-bad-trigger","main-vptr","main-selector",
        "main-caller","main-range","main-quality","main-option","main-option2","main-soi","main-zero","main-primary",
        "main-screen-zero","main-screen-primary","main-primary-mismatch",
        "main-overflow","main-malformed","main-request-size","main-missing","main-alias","main-lease-offset","main-readonly",
        "main-request-release","main-dmm-failed"};
    for(size_t i=0;i<sizeof rejected/sizeof *rejected;i++)if(!strcmp(scenario,rejected[i])){
        assert(fixture_main_entry(object,trigger)==(!strcmp(scenario,"main-dmm-failed")?1:0x201));
        assert(!requests_freed && !bridge_stills && !send_calls && !serialized_writes);
        struct functional_jpeg_codec_snapshot s;assert(!functional_jpeg_codec_snapshot(&s));
        if(!strcmp(scenario,"main-request-release")){
            assert(s.pending && s.last_release_error==-91 && lease_token && borrow_count==1);
            assert(functional_jpeg_codec_shutdown()==-EBUSY);return 0;
        }
        assert(!s.pending && !lease_token);
        goto idle_cleanup;
    }
    model=fcam_model_create(7);assert(model);
    assert(!fcam_bridge_init(record_metadata));pthread_t server;assert(!pthread_create(&server,NULL,model_server,NULL));
    struct fcam_native_origin init={TEST_QID,FUNCTIONAL_JPEG_CODEC_SID,4,80,1};
    uint8_t state[128];struct fcam_bridge_result result;
    assert(!fcam_bridge_call(&init,FCAM_OP_INIT,NULL,0,state,sizeof state,&result));
    if(!strcmp(scenario,"main-send"))send_failure=1;
    if(!strcmp(scenario,"main-send-done"))send_failure=2;
    assert(!fixture_main_entry(object,dmm_completion));
    if(!strcmp(scenario,"main-before-ack")){
        assert(fixture_comp_entry(comp_object,previous_ack)==0x201 && !comp_execs);goto retained;
    }
    if(send_failure==1)goto retained;
    int bad_ack=!strcmp(scenario,"main-ack-source") || !strcmp(scenario,"main-ack-body") ||
        !strcmp(scenario,"main-unobserved") || !strcmp(scenario,"main-callback") ||
        (!strstr(scenario,"-done") && (strstr(scenario,"free-none") || strstr(scenario,"free-fail") ||
            strstr(scenario,"free-tid") || strstr(scenario,"free-destination")));
    if(!strcmp(scenario,"main-callback"))callback_origin=0;
    assert(consume_packet(strcmp(scenario,"main-unobserved")!=0,
        !strcmp(scenario,"main-ack-source"),!strcmp(scenario,"main-ack-body"))==(bad_ack?0x201:0));
    if(bad_ack){assert(!native_responses);goto retained;}
    struct functional_jpeg_codec_snapshot s;assert(!functional_jpeg_codec_snapshot(&s));
    assert(s.pending && lease_token && !release_count && s.native_ack==1 && native_responses==1);
    assert(get32(config_store+config_offset+8)==requested_capacity && !memcmp(config_copy,config_store,sizeof config_copy));
    if(!strcmp(scenario,"main-no-comp")){
        assert(consume_packet(1,0,0)==0x201 && !comp_execs);goto retained;
    }
    if(!strcmp(scenario,"main-comp-vptr"))comp_object[0]^=1;
    if(!strcmp(scenario,"main-comp-caller"))entry_origin=0;
    if(!strcmp(scenario,"main-comp-selector"))comp_object[0x20]^=1;
    if(!strcmp(scenario,"main-comp-context"))comp_object[0xc]^=1;
    if(!strcmp(scenario,"main-comp-manager"))store64(comp_object+0x10,(uintptr_t)control);
    if(!strcmp(scenario,"main-comp-control"))store64(comp_object+0x18,(uintptr_t)manager);
    if(!strcmp(scenario,"main-previous-copy")){
        uint8_t copied_ack[16];memcpy(copied_ack,previous_ack,sizeof copied_ack);
        assert(fixture_comp_entry(comp_object,copied_ack)==0x201 && !comp_execs);goto retained;
    }
    uint8_t bad_previous[16];memcpy(bad_previous,previous_ack,sizeof bad_previous);bad_previous[12]^=1;
    if(!strcmp(scenario,"main-config-readonly")){
        config_mapping=mmap(NULL,page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        assert(config_mapping!=MAP_FAILED);memcpy(config_mapping,config_store,sizeof config_store);
        assert(!mprotect(config_mapping,page,PROT_READ));native_config=config_mapping;
    }
    if(!strcmp(scenario,"main-config-alias"))native_config=arena+64;
    if(!strcmp(scenario,"main-config-fields"))put32(config_store+config_offset,TEST_HANDLE+1);
    int bad_comp=!strncmp(scenario,"main-comp-",10) && strcmp(scenario,"main-comp-duplicate") &&
        strcmp(scenario,"main-comp-fields-after");
    bad_comp=bad_comp || !strncmp(scenario,"main-config-",12) || !strcmp(scenario,"main-previous");
    assert(fixture_comp_entry(comp_object,!strcmp(scenario,"main-previous")?bad_previous:previous_ack)==(bad_comp?0x201:0));
    if(bad_comp){assert(!comp_execs);goto retained;}
    assert(comp_execs==1 && comp_notes==1 && lease_token && !release_count);
    if(!strcmp(scenario,"main-comp-duplicate"))assert(fixture_comp_entry(comp_object,previous_ack)==0x201 && comp_execs==1);
    if(send_failure==2)goto retained;
    if(!strcmp(scenario,"main-comp-fields-after"))comp_object[0xc]^=1;
    int bad_done=!strcmp(scenario,"main-done-source") || !strcmp(scenario,"main-done-body") ||
        !strcmp(scenario,"main-wrong-object") || !strcmp(scenario,"main-comp-fields-after") ||
        (strstr(scenario,"-done") && (strstr(scenario,"free-none") || strstr(scenario,"free-fail") ||
            strstr(scenario,"free-tid") || strstr(scenario,"free-destination")));
    int failed=!strcmp(scenario,"main-backend") || !strcmp(scenario,"main-readback") ||
        !strcmp(scenario,"main-stale") || !strcmp(scenario,"main-length");
    assert(consume_packet(1,!strcmp(scenario,"main-done-source"),!strcmp(scenario,"main-done-body"))==
        (bad_done || failed?0x201:0));
    if(bad_done){assert(native_responses==1);goto retained;}
    wait_finished();assert(!functional_jpeg_codec_snapshot(&s));
    if(!strcmp(scenario,"main-native-length")){
        assert(s.pending && s.last_error==-EPROTO && s.native_done==0 && !release_count && config_notes==1);
        goto retained;
    }
    assert(s.native_ack==1 && s.native_done==1 && native_responses==2 && config_notes==1);
    assert(!s.capture_verified && !s.physical_asic_compatible && original_notes==1 && lease_notes==1);
    assert(get32(config_copy+config_offset+8)==requested_capacity);
    assert(get32(config_store+config_offset+8)==native_length);
    if(!strcmp(scenario,"main-release")){
        assert(s.pending && s.last_release_error==-91 && !release_count);goto retained;
    }
    assert(!s.pending && !lease_token && release_count==1 && s.accepted==1 && requests_freed==1);
    if(!strcmp(scenario,"main-expired")){
        assert(fixture_comp_entry(comp_object,previous_ack)==0x201);
        assert(fixture_main_response(object,received_bodies[0],0x8310)==0x201);
        assert(fixture_comp_response(comp_object,received_bodies[1],0x8311)==0x201);
        assert(comp_execs==1 && native_responses==2 && release_count==1);
    }
    if(failed){assert(!native_length && native_error && s.last_error<0 && !readback_notes);}
    else{
        assert(native_length==last_model_bytes-(mode?0:2) && serialized_writes==1 && bridge_stills==1 && bridge_releases==1);
        assert(s.queued==2 && s.received==2 && received_notes==2 && freed_notes==2 && rescmd_notes==2 && native_done_notes==1);
        assert(!memcmp(arena+64,last_model_output+(mode?0:2),native_length));
        if(!strcmp(scenario,"main-reentry"))assert(reentries==4);
        for(size_t i=0;i<64;i++)assert(arena[i]==0xa5);
        for(size_t i=64+native_length;i<ARENA_SIZE;i++)assert(arena[i]==0xa5);
        emit_blob("MODEL_JPEG",last_model_output,last_model_bytes);emit_blob("SDK_STREAM",arena+64,native_length);
        emit_blob("NATIVE_CONFIG",config_store,sizeof config_store);emit_blob("CONFIG_COPY",config_copy,sizeof config_copy);
    }
    assert(!fcam_bridge_call(&init,FCAM_OP_STATE,NULL,0,state,sizeof state,&result));emit_blob("STATE",state,sizeof state);
    assert(functional_jpeg_codec_observe_freed(TEST_QID,(void *)reply_addresses[0],0)==0);
    assert(functional_jpeg_codec_observe_freed(TEST_QID,(void *)reply_addresses[1],0)==0);
    assert(!functional_jpeg_codec_shutdown());
    if(getenv("FJPEG_HOST_RECEIPTS")){
        struct fcam_frame_proof proof;
        assert(!fcam_model_proof_snapshot(model,&proof,sizeof proof));
        emit_blob("HOST_TEST_FRAME_PROOF",&proof,sizeof proof);
        emit_blob("HOST_TEST_RECEIPTS",receipt_text,receipt_bytes);
    }
    assert(!fcam_bridge_close());assert(!pthread_join(server,NULL));fcam_model_destroy(model);free(last_model_output);
    goto mapped_cleanup;
retained:
    wait_finished();assert(lease_token && functional_jpeg_codec_shutdown()==-EBUSY);
    assert(!fcam_bridge_close());assert(!pthread_join(server,NULL));fcam_model_destroy(model);free(last_model_output);
    free(retained_reply);
    while(queue_first){struct message *p=queue_first;queue_first=p->next;free(p);}
    if(config_mapping)assert(!munmap(config_mapping,page));
    if(object_mapping)assert(!munmap(object_mapping,page));
    assert(!munmap(arena,ARENA_SIZE));return 0;
idle_cleanup:
    assert(!functional_jpeg_codec_shutdown());
mapped_cleanup:
    if(object_mapping)assert(!munmap(object_mapping,page));
    if(trigger_mapping)assert(!munmap(trigger_mapping,page));
    assert(!munmap(arena,ARENA_SIZE));return 0;
}
int main(int argc,char **argv) {
    assert(argc==2);scenario=argv[1];
    fixture_io=(struct full_imaging_io){.release=packet_release,.size=packet_size,.source=packet_source};
    if(!strncmp(scenario,"main-",5))return test_main_sequence();
    memset(object,0,sizeof object_store);memset(manager,0,sizeof manager);memset(control,0xa5,sizeof control);
    store64(object,UINT64_C(0x101af448));
    put32(manager+8,TEST_QID);put32(object+0xc,0x11223344);
    store64(object+0x10,(uintptr_t)manager);store64(object+0x18,(uintptr_t)control);
    put32(object+0x20,0x1047);
    if(!strcmp(scenario,"full"))mode=1;
    if(!strcmp(scenario,"fallback"))requested_width=requested_height=0;
    if(!strcmp(scenario,"wide")) { requested_width=8192;requested_height=16; }
    if(!strcmp(scenario,"range"))requested_width=8193;
    if(!strcmp(scenario,"chunks")) { requested_width=2048;requested_height=1536;requested_quality=100; }
    if(!strcmp(scenario,"off")) {
        struct functional_jpeg_codec_snapshot s;
        assert(!functional_jpeg_codec_snapshot(&s)&&!s.enabled&&!s.accepted);
        assert(!functional_jpeg_codec_dispatch(FUNCTIONAL_JPEG_CODEC_SID,(void *)1,NULL,NULL));
        errno=ENOTTY;assert(fixture_entry(object,(const uint8_t *)(uintptr_t)1)==0x12345678&&errno==EINTR);
        uint8_t body[16]={0};assert(fixture_response(object,body,0x8310)==0x200);
        assert(native_execs==1&&native_responses==1&&get_next_calls==2&&!borrow_count);
        return 0;
    }
    object[0x24]=mode;store16(object+0x26,(uint16_t)requested_width);store16(object+0x28,(uint16_t)requested_height);
    void *mapped=mmap((void *)UINT32_C(0x38000000),ARENA_SIZE,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(mapped!=MAP_FAILED&&(uintptr_t)mapped<=UINT32_MAX-ARENA_SIZE);arena=mapped;memset(arena,0xa5,ARENA_SIZE);
    assert(!functional_jpeg_codec_enable(record_metadata));
    assert(functional_jpeg_codec_enable(record_metadata)==-EALREADY);
    if(!strcmp(scenario,"receipt-request-release")){
        request_release_error=-77;
        assert(fixture_entry(object,(const uint8_t *)(uintptr_t)1)==0x201);
        struct functional_jpeg_codec_snapshot s;assert(!functional_jpeg_codec_snapshot(&s));
        assert(s.pending && !s.accepted && !s.encoded && s.rejected==1 && s.last_release_error==-91);
        assert(lease_token==held.token && lease_token && borrow_count==1 && !serialized_writes && !requests_freed);
        assert(!original_notes && !readback_notes && !bridge_stills && !send_calls);
        assert(functional_jpeg_codec_shutdown()==-EBUSY);return 0;
    }
    if(!strcmp(scenario,"fork")) {
        functional_jpeg_test_lock_owner();
        pid_t child=fork();assert(child>=0);
        if(!child) {
            struct functional_jpeg_codec_snapshot s;
            _exit(functional_jpeg_codec_shutdown()==-ECHILD&&functional_jpeg_codec_snapshot(&s)==-ECHILD&&
                fixture_entry(object,(const uint8_t *)(uintptr_t)1)==0x201 &&
                functional_jpeg_codec_observe_freed(TEST_QID,(void *)1,0)==-ECHILD?0:1);
        }
        int status;assert(waitpid(child,&status,0)==child&&WIFEXITED(status)&&!WEXITSTATUS(status));
        functional_jpeg_test_unlock_owner();assert(!functional_jpeg_codec_shutdown());
        assert(!munmap(arena,ARENA_SIZE));return 0;
    }
    if(!strcmp(scenario,"missing"))memory_failure=-ENOENT;
    if(!strcmp(scenario,"request"))bad_request=1;
    if(memory_failure||bad_request||!strcmp(scenario,"alias")||!strcmp(scenario,"range")) {
        assert(fixture_entry(object,(const uint8_t *)(uintptr_t)1)==0x201);
        assert(native_execs==1&&!requests_freed&&!bridge_stills&&!send_calls);
        assert(!functional_jpeg_codec_shutdown());assert(!munmap(arena,ARENA_SIZE));return 0;
    }
    model=fcam_model_create(7);assert(model);
    errno=ENOTTY;
    int bridge_rc=fcam_bridge_init(NULL);
    assert(bridge_rc==-EINVAL && errno==ENOTTY && !mailbox && !sequence);
    bridge_rc=fcam_bridge_init(record_metadata);
    if(bridge_rc)fprintf(stderr,"fcam_bridge_init: rc=%d (%s)\n",bridge_rc,strerror(-bridge_rc));
    assert(!bridge_rc);pthread_t server;assert(!pthread_create(&server,NULL,model_server,NULL));
    struct fcam_native_origin init={TEST_QID,FUNCTIONAL_JPEG_CODEC_SID,4,80,1};
    uint8_t state[128];struct fcam_bridge_result result;
    assert(!fcam_bridge_call(&init,FCAM_OP_INIT,NULL,0,state,sizeof state,&result));
    assert(get32(state+8)==640&&get32(state+12)==480&&get64(state+64)==1);
    assert(!get64(state+72)&&!get64(state+80));
    if(!strcmp(scenario,"chunks")||!strcmp(scenario,"wide")) {
        int wide=!strcmp(scenario,"wide");
        uint8_t config[48]={0};put32(config,640);put32(config+4,480);put32(config+8,30);
        put32(config+12,requested_quality);put32(config+16,wide?800:400);put32(config+20,100);
        /* Default exposure clips the width-scaled defocused 8192-pixel scene. */
        put64(config+24,wide?16667:10000);put64(config+32,wide?3000000:4000000);
        assert(!fcam_bridge_call(&init,FCAM_OP_CONFIGURE,config,sizeof config,state,sizeof state,&result));
    }
    if(!strcmp(scenario,"shape"))bad_shape=1;
    if(!strcmp(scenario,"send"))send_failure=1;
    if(!strcmp(scenario,"busy"))block_backend=1;
    assert(!fixture_entry(object,(const uint8_t *)(uintptr_t)1));
    if(!strcmp(scenario,"busy")) {
        pthread_mutex_lock(&fixture_lock);
        while(!backend_entered)pthread_cond_wait(&fixture_wake,&fixture_lock);
        pthread_mutex_unlock(&fixture_lock);
        assert(fixture_entry(object,(const uint8_t *)(uintptr_t)1)==0x201);
        assert(functional_jpeg_codec_shutdown()==-EBUSY);
        pthread_mutex_lock(&fixture_lock);allow_backend=1;pthread_cond_broadcast(&fixture_wake);pthread_mutex_unlock(&fixture_lock);
    }
    if(send_failure) {
        wait_finished();assert(!native_responses&&lease_token&&send_calls==1);
        assert(functional_jpeg_codec_shutdown()==-EBUSY);
        assert(!fcam_bridge_close());assert(!pthread_join(server,NULL));
        fcam_model_destroy(model);free(last_model_output);return 0;
    }
    if(!strcmp(scenario,"callback")||!strcmp(scenario,"source")||!strcmp(scenario,"cookie")||
        !strcmp(scenario,"duplicate")||!strcmp(scenario,"unobserved")) {
        if(!strcmp(scenario,"callback"))callback_origin=0;
        assert(consume_packet(strcmp(scenario,"unobserved")!=0,
            !strcmp(scenario,"source"),!strcmp(scenario,"cookie"))==0x201);
        wait_finished();assert(!native_responses&&lease_token);
        assert(functional_jpeg_codec_shutdown()==-EBUSY);
        assert(!fcam_bridge_close());assert(!pthread_join(server,NULL));fcam_model_destroy(model);free(last_model_output);
        while(queue_first) { struct message *p=queue_first;queue_first=p->next;free(p); }
        return 0;
    }
    int failed=!strcmp(scenario,"readback")||!strcmp(scenario,"stale")||!strcmp(scenario,"backend")||
        !strcmp(scenario,"length")||bad_shape;
    if(!strcmp(scenario,"receipt-thread")){
        pthread_t receiver;assert(!pthread_create(&receiver,NULL,consume_on_receiver,NULL));
        assert(!pthread_join(receiver,NULL));
        assert(receiver_tids[0]!=producer_tid && receiver_tids[1]==receiver_tids[0]);
    }else{
        assert(consume_packet(1,0,0)==(failed?0x201:0x200));
        if(!failed)assert(!consume_packet(1,0,0));
    }
    wait_finished();
    struct functional_jpeg_codec_snapshot s;assert(!functional_jpeg_codec_snapshot(&s));
    if(!strcmp(scenario,"receipt-release")){
        assert(s.pending && lease_token && s.last_release_error==-91 && !release_count);
        assert(native_length && serialized_writes==1 && received_notes==2 && rescmd_notes==2);
        assert(functional_jpeg_codec_shutdown()==-EBUSY);
        assert(fixture_entry(object,(const uint8_t *)(uintptr_t)1)==0x201);
        assert(!functional_jpeg_codec_snapshot(&s) && s.accepted==1 && s.pending && s.rejected==1);
        assert(serialized_writes==1 && borrow_count==1 && lease_token==held.token);
        assert(!fcam_bridge_close());assert(!pthread_join(server,NULL));fcam_model_destroy(model);free(last_model_output);
        return 0;
    }
    assert(!s.pending&&!lease_token&&release_count==1&&s.accepted==1&&requests_freed==1);
    assert(!s.capture_verified&&!s.physical_asic_compatible&&record_calls&&original_notes==1);
    if(failed)assert(!native_length&&native_error&&s.last_error<0&&!readback_notes);
    else {
        assert(native_length&&native_length==get32(control+(mode?0x68:0x5c)));
        assert(s.encoded==1&&s.bytes_readback==native_length&&s.queued==2&&s.received==2);
        assert(s.native_ack==1&&s.native_done==1&&native_responses==2&&readback_notes==1&&native_done_notes==1);
        assert(lease_notes==1 && received_notes==2 && rescmd_notes==2 && serialized_writes==1);
        assert(bridge_stills==1&&bridge_releases==1&&last_model_bytes>NATIVE_PREFIX);
        if(!strcmp(scenario,"chunks"))assert(bridge_chunks>0&&last_model_bytes>FCAM_DATA_BYTES);
        assert(native_length==last_model_bytes-(mode?0:2));
        assert(!memcmp(arena+64,last_model_output+(mode?0:2),native_length));
        for(size_t i=0;i<64;++i)assert(arena[i]==0xa5);
        for(size_t i=64+native_length;i<ARENA_SIZE;++i)assert(arena[i]==0xa5);
        emit_blob("MODEL_JPEG",last_model_output,last_model_bytes);
        emit_blob("SDK_STREAM",arena+64,native_length);
        emit_blob("NATIVE_CONFIG",control,sizeof control);
    }
    assert(!fcam_bridge_call(&init,FCAM_OP_STATE,NULL,0,state,sizeof state,&result));
    if(!failed)assert(get64(state+64)==2&&get64(state+72)==1&&get64(state+80)==1);
    emit_blob("STATE",state,sizeof state);
    assert(!functional_jpeg_codec_shutdown());
    assert(!fcam_bridge_close());assert(!pthread_join(server,NULL));
    fcam_model_destroy(model);free(last_model_output);assert(!munmap(arena,ARENA_SIZE));
    return 0;
}
