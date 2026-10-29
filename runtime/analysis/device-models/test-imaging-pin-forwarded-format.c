/* SPDX-License-Identifier: MIT */
/* Real first-edge fixture, then same-owner updates from byte-array DMM backing. */
#define FULL_IMAGING_PIN_CONNECTION_TEST_MAIN first_edge_prerequisite_main
#include "test-imaging-pin-connection.c"
#undef FULL_IMAGING_PIN_CONNECTION_TEST_MAIN
#include <limits.h>

static unsigned int forwarded_logs;
static void forwarded_record(const char *tag,const char *text){
    assert(!strcmp(tag,"FULL_IMAGING_PIN_CONNECT_FORWARD_FORMAT_CONSUMED "));guarded();
    struct full_imaging_pin_connection_snapshot s=connect_snapshot();
    struct pin_control_references r={0};
    assert(!pin_control_references(s.forwarded_handle,&r));
    assert(r.owners==1 && r.opens==1 && !r.creator && r.consumer==1 && r.consumer_open==1);
    assert(s.clean_completion==1 && s.ap_consumed==1 && !s.busy && !s.faults);
    assert(s.format.consumed==s.forwarded_formats+1);
    assert(strstr(text,"mapped_backing_read=1 original_cp_executed=0"));
    assert(strstr(text,"frames_verified=0 capture_verified=0"));
    forwarded_logs++;fprintf(stdout,"%s%s\n",tag,text);
}
/* No transport callbacks: this API may only record, never allocate/send/release. */
static const struct full_imaging_io forwarded_io={.record=forwarded_record};
static void forwarded_reject(unsigned int handle,const struct full_imaging_io *io,unsigned int reads){
    struct full_imaging_pin_connection_snapshot before=connect_snapshot();
    struct pin_control_snapshot pool_before={0},pool_after={0};
    pin_control_snapshot(&pool_before);unsigned int logs=forwarded_logs;
    assert(full_imaging_pin_connection_accept_forwarded_format(handle,io)<0);
    struct full_imaging_pin_connection_snapshot after=connect_snapshot();
    assert(!memcmp(&before,&after,sizeof before) && logs==forwarded_logs);
    pin_control_snapshot(&pool_after);
    assert(pool_after.consumer_reads==pool_before.consumer_reads+reads);
    pool_after.consumer_reads=pool_before.consumer_reads;
    assert(!memcmp(&pool_before,&pool_after,sizeof pool_before));
}
static void forwarded_packet(unsigned char packet[80]){
    static const unsigned char payload[16]={1,1,3,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
    assert(!full_infraimaging_format_build(packet,80));
    ctput32(packet+4,0x01000000);ctput32(packet+0x28,0);
    memcpy(packet+0x40,payload,sizeof payload);
}
static struct pin_control_lease forwarded_open(const unsigned char packet[80]){
    struct pin_control_lease created={0},opened={0};
    assert(!pin_control_allocate(PIN_CONTROL_UNIT,&created));
    assert(!pin_control_write_payload(created.handle,packet,80,0));
    assert(!pin_control_share(created.handle,PIN_CONTROL_UNIT));
    assert(!pin_control_release(created.handle));
    assert(!pin_control_open_consumer(created.handle,PIN_CONTROL_UNIT,&opened));
    assert(opened.handle==created.handle && opened.unit==PIN_CONTROL_UNIT);
    return opened;
}
static void forwarded_accept(unsigned int handle,const unsigned char packet[80]){
    assert(!reserve());
    struct full_imaging_pin_connection_snapshot before=connect_snapshot();
    struct pin_control_snapshot pool_before={0},pool_after={0};pin_control_snapshot(&pool_before);
    unsigned int logs=forwarded_logs;
    assert(!full_imaging_pin_connection_accept_forwarded_format(handle,&forwarded_io));
    struct full_imaging_pin_connection_snapshot after=connect_snapshot();
    const unsigned int expected[5]={packet[65],packet[64],ct32(packet+72),ct32(packet+76),ct16(packet+66)};
    assert(!memcmp(after.format.cache,expected,sizeof expected));
    assert(after.format.payload_fnv64==cthash(packet+64,16));
    assert(after.format.consumed==before.format.consumed+1 && after.format.initialized==1);
    assert(after.forwarded_formats==before.forwarded_formats+1 && after.forwarded_handle==handle);
    assert(forwarded_logs==logs+1);
    /* All first-edge ownership, digest, AP completion and synchronization history stays intact. */
    after.format=before.format;after.forwarded_formats=before.forwarded_formats;after.forwarded_handle=before.forwarded_handle;
    assert(!memcmp(&after,&before,sizeof before));
    pin_control_snapshot(&pool_after);assert(pool_after.consumer_reads==pool_before.consumer_reads+1);
    pool_after.consumer_reads=pool_before.consumer_reads;
    assert(!memcmp(&pool_before,&pool_after,sizeof pool_before));
    forwarded_reject(handle,&forwarded_io,0);
    assert(!pin_control_release_consumer(handle));
    assert(pin_control_references(handle,&(struct pin_control_references){0})<0);
    forwarded_reject(handle,&forwarded_io,0);release_guard();
}
static void first_without_ap(const char *seed){
    host_pid=getpid();char *old[]={"test","normal",(char *)seed,0};
    assert(!bb_prerequisite_main(3,old));alarm(15);
    full_bb_set_mode_snapshot(&connect_bb_before);
    assert(!full_imaging_pin_connection_owner_init());
    connect_request=connect_new_request(64);
    connect_get(CONNECT_SOURCE,0);connect_get(CONNECT_PEER,0);
    native_infraimaging_snapshot(&connect_source_before);native_infrabb_snapshot(&connect_peer_before);
    connect_old_pool();int rc=77;
    assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&connect_io,&connect_guard,1,&rc) && !rc);
    struct full_imaging_pin_connection_snapshot s=connect_snapshot();
    assert(s.clean_completion==1 && s.connections==1 && !s.ap_consumed && s.live_reply);
}
int main(int argc,char **argv){
    assert(argc==3);alarm(20);
    unsigned char packet[80];forwarded_packet(packet);
    if(!strcmp(argv[1],"uninitialized")){
        forwarded_reject(0x8000,&forwarded_io,0);
        assert(!connect_snapshot().initialized);puts("IMAGING_FORWARD_FORMAT_UNINITIALIZED_PASS");return 0;
    }
    if(!strcmp(argv[1],"not-ap-consumed"))first_without_ap(argv[2]);
    else {char *old[]={"test",!strcmp(argv[1],"first-fault")?"wrong-owner":"normal",argv[2],0};
        assert(!first_edge_prerequisite_main(3,old));}
    alarm(15);
    if(!strcmp(argv[1],"first-fault") || !strcmp(argv[1],"not-ap-consumed")){
        struct pin_control_lease opened=forwarded_open(packet);
        forwarded_reject(opened.handle,&forwarded_io,0);
        assert(!pin_control_release_consumer(opened.handle));
        if(!strcmp(argv[1],"not-ap-consumed")){
            int rc=77;assert(full_imaging_pin_connection_release(connect_caller,connect_final->data,connect_free,connect_record,&rc) && !rc);
            connect_finish();
        }
        printf("IMAGING_FORWARD_FORMAT_REJECT_%s_PASS\n",argv[1]);return 0;
    }
    assert(!strcmp(argv[1],"normal"));
    struct full_imaging_pin_connection_snapshot initial=connect_snapshot();
    assert(initial.format.consumed==1 && initial.buffer_freed==1 && initial.ap_consumed==1);
    forwarded_reject(initial.buffer_handle,&forwarded_io,0);
    forwarded_reject(0,&forwarded_io,0);forwarded_reject(0x10008000u,&forwarded_io,0);
    struct pin_control_lease created={0},opened={0};
    assert(!pin_control_allocate(PIN_CONTROL_UNIT,&created));
    assert(!pin_control_write_payload(created.handle,packet,sizeof packet,0));
    forwarded_reject(created.handle,0,0);
    forwarded_reject(created.handle,&(struct full_imaging_io){0},0);
    forwarded_reject(created.handle,&forwarded_io,0);
    assert(!pin_control_share(created.handle,PIN_CONTROL_UNIT));
    forwarded_reject(created.handle,&forwarded_io,0);
    assert(!pin_control_open_consumer(created.handle,PIN_CONTROL_UNIT,&opened));
    forwarded_reject(created.handle,&forwarded_io,0);
    assert(!pin_control_release(created.handle));
    assert(!pin_control_close_consumer(created.handle));
    forwarded_reject(created.handle,&forwarded_io,0);
    assert(!pin_control_open_consumer(created.handle,PIN_CONTROL_UNIT,&opened));
    pin_control_test_hold_lock();
    pid_t child=fork();assert(child>=0);
    if(!child){
        alarm(2);assert(!connect_snapshot().initialized);
        assert(full_imaging_pin_connection_accept_forwarded_format(created.handle,&forwarded_io)<0);
        _exit(0);
    }
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    pin_control_test_drop_lock();
    forwarded_accept(created.handle,packet);
    struct full_imaging_pin_connection_snapshot updated=connect_snapshot();
    assert(updated.format.consumed==2 && updated.forwarded_formats==1);
    assert(updated.format.payload_fnv64==0x37228cd728b41c0dULL);
    puts("IMAGING_FORWARD_FORMAT_ACTUAL_MAPPED_READ_SAME_CACHE_FIRST_HISTORY_PASS");
    puts("IMAGING_FORWARD_FORMAT_REFERENCE_AUTHORITY_DUPLICATE_AND_FORK_PRELOCK_PASS");
    /* Every metadata byte is read from a newly written mapped backing, not a parser-only copy. */
    for(unsigned int offset=0;offset<64;offset++){
        unsigned char corrupt[80];memcpy(corrupt,packet,sizeof corrupt);corrupt[offset]^=1;
        opened=forwarded_open(corrupt);forwarded_reject(opened.handle,&forwarded_io,1);
        assert(!pin_control_release_consumer(opened.handle));
    }
    unsigned char old_packet[80];assert(!full_infraimaging_format_build(old_packet,sizeof old_packet));
    opened=forwarded_open(old_packet);forwarded_reject(opened.handle,&forwarded_io,1);
    assert(!pin_control_release_consumer(opened.handle));
    puts("IMAGING_FORWARD_FORMAT_MALFORMED_BACKING_AND_OLD_VARIANT_PRESERVE_OWNER_PASS");
    memset(packet+0x44,0xa5,4);packet[0x42]=0xcd;packet[0x43]=0xab;
    opened=forwarded_open(packet);forwarded_accept(opened.handle,packet);
    updated=connect_snapshot();assert(updated.format.cache[4]==0xabcd && updated.format.consumed==3);
    assert(updated.forwarded_formats==2 && forwarded_logs==2);
    struct pin_control_snapshot pool={0};pin_control_snapshot(&pool);
    assert(!pool.live && !pool.faults && pool.allocations==pool.releases && pool.allocations>2);
    assert(pool.header_writes==connect_pool_before.header_writes);
    assert(updated.buffer_handle==initial.buffer_handle && updated.buffer_fnv==initial.buffer_fnv);
    assert(updated.dmm_opens==initial.dmm_opens && updated.dmm_frees==initial.dmm_frees);
    puts("IMAGING_FORWARD_FORMAT_FULL_FLAGS_UNUSED_WORD_CALLER_FREE_NO_RESET_PASS");
    return 0;
}
