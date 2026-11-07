/* SPDX-License-Identifier: MIT */
/* Reuse the established message allocator/poisoning/failure fixture, while
 * testing the new independent edge after the actual first-edge model. */
#define main first_edge_regression_main
#include "test-pin-connection.c"
#undef main
#include "scalar-connection.h"
#include "scalar-device.h"
static unsigned int scalar_inject,scalar_frees;
static void scalar_record(const char *kind,const char *line){
    record(kind,line);
    if(!strcmp(kind,"FULL_SCALAR_CONNECT_PEER_REPLY ")){
        if(scalar_inject==1)fail_release=1;
        if(scalar_inject==2 || scalar_inject==3){
            for(unsigned int i=0;i<64;i++)if(live[i] && size(live[i])==72)
                put32((unsigned char *)live[i]+(scalar_inject==2?64:56),scalar_inject==2?0xffff:3);
        }
    }
    if(!strcmp(kind,"FULL_SCALAR_CONNECT_REPLY_QUEUED ") && scalar_inject==4)fail_release=1;
    if(!strcmp(kind,"FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE "))scalar_frees++;
}
static const struct full_imaging_io scalar_io={allocate,release,set_source,send,size,source,scalar_record};
static struct scalar_connection_snapshot scalar_state(void){struct scalar_connection_snapshot s;full_scalar_connection_snapshot(&s);return s;}
static void second_seed(void){
    full_scalar_connection_test_reset();full_scalar_test_reset();scalar_inject=scalar_frees=0;
    format_test();int rc=123;void *r=request(FULL_SCALAR_CP,48,0,1,4);
    assert(full_scalar_dispatch(FULL_SCALAR_CP,r,&io,1,&rc) && !rc && queued);
    assert(full_scalar_release_reply(D,queued,release,record,&rc) && !rc);queued=0;
}
static void *second_request(void){
    unsigned char *r=request(FULL_PINMEM_CP,64,1,2,1);
    put32(r+44,FULL_PINMEM_CP);put32(r+56,4);put32(r+60,FULL_SCALAR_CP);return r;
}
#ifndef SCALAR_TEST_MAIN
#define SCALAR_TEST_MAIN main
#endif
int SCALAR_TEST_MAIN(void){
    const char *fixture=getenv("SCALAR_CONNECTION_HOST_FIXTURE");
    if(!fixture)assert(!first_edge_regression_main());
    else{host_fixture=fixture;puts("HOST_FIXTURE_ONLY_NO_VM");}
    second_seed();struct full_vef_snapshot first_before,source_before;
    full_vef_snapshot(&first_before);full_pinmem_snapshot(&source_before);
    struct pin_control_snapshot pool_before,pool_after;pin_control_snapshot(&pool_before);
    int rc=123;void *r=second_request();
    assert(!full_scalar_connection_dispatch(FULL_PINMEM_CP,r,&scalar_io,0,&rc) && rc==123);
    assert(full_scalar_connection_dispatch(FULL_PINMEM_CP,r,&scalar_io,1,&rc) && !rc && queued);
    struct scalar_connection_snapshot state=scalar_state();
    assert(state.connections==1 && !state.faults && state.event6_consumed==1 && !state.pending_event6 && state.yc_callback_seen && !state.yc_format_published);
    assert(size(queued)==56 && source(queued)==FULL_PINMEM_CP && u16((unsigned char *)queued+26)==0x8001);
    assert(u32((unsigned char *)queued+36)==2 && u32((unsigned char *)queued+40)==1 && u32((unsigned char *)queued+44)==FULL_PINMEM_CP && !u32((unsigned char *)queued+48));
    struct full_vef_snapshot first,source_state,peer;full_vef_snapshot(&first);full_pinmem_snapshot(&source_state);full_scalar_snapshot(&peer);
    assert(!memcmp(&first.pins[10],&first_before.pins[10],sizeof first.pins[10]));
    assert(!memcmp(&source_state.pins[1],&source_before.pins[1],sizeof source_state.pins[1]));
    assert(!source_state.pins[4].state && !peer.pins[4].state && source_state.pins[4].peer[3]==FULL_SCALAR_CP && peer.pins[4].peer[3]==FULL_PINMEM_CP);
    pin_control_snapshot(&pool_after);assert(pool_before.allocations==pool_after.allocations && pool_before.payload_writes==pool_after.payload_writes && pool_before.releases==pool_after.releases && !pool_after.live);
    assert(full_scalar_connection_release(D,queued,release,scalar_record,&rc) && !rc);queued=0;
    assert(scalar_frees==1 && scalar_state().waiter_frees==1);
    r=request(FULL_PINMEM_CP,48,0,2,2);assert(!full_scalar_connection_dispatch(FULL_PINMEM_CP,r,&scalar_io,1,&rc));
    assert(full_pinmem_dispatch(FULL_PINMEM_CP,r,&io,1,&rc) && !rc);assert(full_pinmem_release_reply(D,queued,release,record,&rc) && !rc);queued=0;
    puts("SECOND_EDGE_ACTUAL_64_64_72_56_EVENT6_NO_FORMAT_ALLOCATION_FIRST_EDGE_PRESERVED_PASS");
    if(fixture){
        FILE *file=fopen(fixture,"wb");assert(file && fwrite(backing,1,sizeof backing,file)==sizeof backing && !fclose(file));
        full_scalar_connection_test_reset();full_scalar_test_reset();reset();return 0;
    }
    for(unsigned int mode=0;mode<7;mode++){
        second_seed();r=second_request();
        if(mode<3)fail_allocation=allocation_count+mode+1;
        else if(mode==3)send_failure=1;
        else if(mode==4)alias=r;
        else if(mode==5)alias_peer_reply=1;
        else bad_size=72;
        assert(full_scalar_connection_dispatch(FULL_PINMEM_CP,r,&scalar_io,1,&rc) && rc && !queued && scalar_state().faults);
        assert(!release(FULL_PINMEM_CP,r));
    }
    puts("SECOND_EDGE_PRE_SEND_ALLOC_SIZE_ALIAS_AND_SEND_FAILURE_CALLER_OWNERSHIP_PASS");
    for(unsigned int injection=1;injection<=4;injection++){
        second_seed();r=second_request();scalar_inject=injection;
        assert(full_scalar_connection_dispatch(FULL_PINMEM_CP,r,&scalar_io,1,&rc) && scalar_state().faults);
        if(injection==4){
            assert(!rc && queued);assert(full_scalar_connection_release(D,queued,release,scalar_record,&rc) && !rc);queued=0;
        }else{assert(rc && !queued);assert(!release(FULL_PINMEM_CP,r));}
    }
    puts("SECOND_EDGE_NONZERO_STATUS_PEER_MISMATCH_FREE_FAILURE_AND_POST_SEND_NO_DOUBLE_FREE_PASS");
    full_scalar_connection_test_reset();full_scalar_test_reset();reset();return 0;
}
