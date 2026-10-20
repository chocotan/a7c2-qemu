/* SPDX-License-Identifier: MIT */
#define SCALAR_TEST_MAIN second_edge_regression_main
#include "test-scalar-connection.c"
#include "adf-connection.h"
#include "adf-device.h"
static unsigned int adf_inject;
static void adf_record(const char *kind,const char *line){
    record(kind,line);
    if(!strcmp(kind,"FULL_ADF_CONNECT_PEER_REPLY ")){
        if(adf_inject==1)fail_release=1;
        if(adf_inject==2 || adf_inject==3){
            for(unsigned int i=0;i<64;i++)if(live[i] && size(live[i])==72)
                put32((unsigned char *)live[i]+(adf_inject==2?64:60),adf_inject==2?0xe002:FULL_SCALAR_CP);
        }
    }
    if(!strcmp(kind,"FULL_ADF_CONNECT_REPLY_QUEUED ") && adf_inject==4)fail_release=1;
}
static const struct full_imaging_io adf_io={allocate,release,set_source,send,size,source,adf_record};
static struct scalar_connection_snapshot adf_state(void){struct scalar_connection_snapshot s;full_adf_connection_snapshot(&s);return s;}
static void third_seed(void){
    full_adf_connection_test_reset();full_adf_test_reset();adf_inject=0;
    second_seed();int rc;void *r=second_request();
    assert(full_scalar_connection_dispatch(FULL_PINMEM_CP,r,&scalar_io,1,&rc) && !rc);
    assert(full_scalar_connection_release(D,queued,release,scalar_record,&rc) && !rc);queued=0;
    r=request(FULL_PINMEM_CP,48,0,2,2);assert(full_pinmem_dispatch(FULL_PINMEM_CP,r,&io,1,&rc) && !rc);
    assert(full_pinmem_release_reply(D,queued,release,record,&rc) && !rc);queued=0;
    r=request(FULL_ADF_CP,48,0,1,0);assert(full_adf_dispatch(FULL_ADF_CP,r,&io,1,&rc) && !rc);
    assert(full_adf_release_reply(D,queued,release,record,&rc) && !rc);queued=0;
}
static void *third_request(void){
    unsigned char *r=request(FULL_PINMEM_CP,64,1,2,2);
    put32(r+44,FULL_PINMEM_CP);put32(r+56,0);put32(r+60,FULL_ADF_CP);return r;
}
int main(void){
    const char *fixture=getenv("ADF_CONNECTION_HOST_FIXTURE");
    if(!fixture)assert(!second_edge_regression_main());
    else{host_fixture=fixture;puts("HOST_FIXTURE_ONLY_NO_VM");}
    third_seed();struct full_vef_snapshot pinmem_before,scalar_before,vef_before;
    full_pinmem_snapshot(&pinmem_before);full_scalar_snapshot(&scalar_before);full_vef_snapshot(&vef_before);
    struct pin_control_snapshot before,after;pin_control_snapshot(&before);
    int rc=123;void *r=third_request();
    assert(!full_adf_connection_dispatch(FULL_PINMEM_CP,r,&adf_io,0,&rc) && rc==123);
    assert(full_adf_connection_dispatch(FULL_PINMEM_CP,r,&adf_io,1,&rc) && !rc && queued);
    struct scalar_connection_snapshot s=adf_state();assert(s.connections==1 && !s.faults && s.event6_consumed && !s.pending_event6 && s.yc_callback_seen && !s.yc_format_published);
    assert(size(queued)==56 && source(queued)==FULL_PINMEM_CP && u32((unsigned char *)queued+40)==2 && !u32((unsigned char *)queued+48));
    struct full_vef_snapshot pinmem,adf,scalar,vef;full_pinmem_snapshot(&pinmem);full_adf_snapshot(&adf);full_scalar_snapshot(&scalar);full_vef_snapshot(&vef);
    assert(!memcmp(&scalar_before,&scalar,sizeof scalar) && !memcmp(&vef_before,&vef,sizeof vef));
    assert(!memcmp(&pinmem_before.pins[1],&pinmem.pins[1],sizeof pinmem.pins[1]) && !memcmp(&pinmem_before.pins[4],&pinmem.pins[4],sizeof pinmem.pins[4]));
    assert(!pinmem.pins[5].state && !adf.pins[0].state && pinmem.pins[5].peer[3]==FULL_ADF_CP && adf.pins[0].peer[3]==FULL_PINMEM_CP);
    pin_control_snapshot(&after);assert(before.allocations==after.allocations && before.payload_writes==after.payload_writes && before.releases==after.releases && !after.live);
    assert(!full_scalar_connection_release(D,queued,release,record,&rc));
    assert(full_adf_connection_release(D,queued,release,adf_record,&rc) && !rc);queued=0;assert(adf_state().waiter_frees==1);
    r=request(FULL_PINMEM_CP,48,0,2,0);put32((unsigned char *)r+32,4);
    assert(!full_adf_connection_dispatch(FULL_PINMEM_CP,r,&adf_io,1,&rc));
    assert(full_pinmem_dispatch(FULL_PINMEM_CP,r,&io,1,&rc) && !rc);assert(full_pinmem_release_reply(D,queued,release,record,&rc) && !rc);queued=0;
    puts("THIRD_EDGE_FOUR_FRAMES_EVENT6_PREVIOUS_EDGES_AND_BACKING_PRESERVED_PASS");
    if(fixture){FILE *f=fopen(fixture,"wb");assert(f && fwrite(backing,1,sizeof backing,f)==sizeof backing && !fclose(f));goto done;}
    for(unsigned int mode=0;mode<7;mode++){
        third_seed();r=third_request();
        if(mode<3)fail_allocation=allocation_count+mode+1;
        else if(mode==3)send_failure=1;
        else if(mode==4)alias=r;
        else if(mode==5)alias_peer_reply=1;
        else bad_size=72;
        assert(full_adf_connection_dispatch(FULL_PINMEM_CP,r,&adf_io,1,&rc) && rc && !queued && adf_state().faults);
        assert(!release(FULL_PINMEM_CP,r));
    }
    for(unsigned int injection=1;injection<=4;injection++){
        third_seed();r=third_request();adf_inject=injection;
        assert(full_adf_connection_dispatch(FULL_PINMEM_CP,r,&adf_io,1,&rc) && adf_state().faults);
        if(injection==4){assert(!rc && queued);assert(full_adf_connection_release(D,queued,release,adf_record,&rc) && !rc);queued=0;}
        else{assert(rc && !queued);assert(!release(FULL_PINMEM_CP,r));}
    }
    third_seed();r=second_request();assert(!full_adf_connection_dispatch(FULL_PINMEM_CP,r,&adf_io,1,&rc) && !adf_state().started);assert(!release(FULL_PINMEM_CP,r));
    puts("THIRD_EDGE_FAILURE_OWNERSHIP_PEER_SID_STATUS_FREE_AND_PASS_OTHER_PASS");
done:
    full_adf_connection_test_reset();full_adf_test_reset();full_scalar_connection_test_reset();full_scalar_test_reset();reset();return 0;
}
