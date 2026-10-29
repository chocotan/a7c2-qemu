/* SPDX-License-Identifier: MIT */
#include "infrabb-vef-format.h"
#include "pin-buffer-owner.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[PIN_CONTROL_CAPACITY];
int main(int argc,char **argv){
    assert(argc==2);const char *name=argv[1];
    struct full_infrabb_vef_format f={0};assert(!full_infrabb_vef_format_init(&f));
    const unsigned char current[20]={1,0,0,0,0,0,0,0,1,0,0,0,0x80,7,0,0,0x38,4,0,0};
    const unsigned char expected[16]={1,0,0,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
    assert(f.initialized && f.current_known_bytes==20 && f.expected_known_bytes==16 && !memcmp(f.current,current,20) && !memcmp(f.expected,expected,16));
    struct full_infrabb_vef_format before=f;assert(full_infrabb_vef_format_init(&f)==-1 && !memcmp(&before,&f,sizeof f));
    unsigned char internal[36],packet[80],readback[80];assert(!full_infrabb_vef_format_internal(&f,internal,36));
    assert(!memcmp(internal+16,current,20));
    if(!strcmp(name,"bad-internal")){
        for(unsigned int i=0;i<36;i++){internal[i]^=1;assert(full_infrabb_vef_format_prepare(&f,internal,36)==-1);internal[i]^=1;assert(!memcmp(&f,&before,sizeof f));}
        puts("INFRABB_VEF_FORMAT_HOST_TEST_PASS");return 0;
    }
    assert(!full_infrabb_vef_format_prepare(&f,internal,36) && f.command_fnv==f.current_fnv && !memcmp(f.current,f.command_current,20));
    assert(full_infrabb_vef_format_prepare(&f,internal,36)==-1);
    if(!strcmp(name,"not-connected")){
        assert(full_infrabb_vef_format_execute(&f,1,packet,80)==-1 && !f.executions);
        puts("INFRABB_VEF_FORMAT_HOST_TEST_PASS");return 0;
    }
    assert(!full_infrabb_vef_format_execute(&f,0,packet,80));assert(packet[7]==2 && !memcmp(packet+64,expected,16));
    assert(full_infrabb_vef_format_execute(&f,0,packet,80)==-1);
    if(!strcmp(name,"bad-header")){
        for(unsigned int i=0;i<64;i++){packet[i]^=1;assert(full_infrabb_vef_format_consume(&f,packet,80)==-1);packet[i]^=1;assert(!f.matches && !f.mismatches);}
        puts("INFRABB_VEF_FORMAT_HOST_TEST_PASS");return 0;
    }
    assert(!pin_control_bind_reserved(memory,sizeof memory,PIN_CONTROL_PHYSICAL));
    struct pin_control_lease lease={0},opened={0};assert(!pin_control_allocate(PIN_CONTROL_UNIT,&lease));
    unsigned int at=80;
    if(!strcmp(name,"code"))at=64;else if(!strcmp(name,"component"))at=65;else if(!strcmp(name,"flags-low"))at=66;
    else if(!strcmp(name,"flags-high"))at=67;else if(!strcmp(name,"width"))at=73;else if(!strcmp(name,"height"))at=77;
    else if(!strcmp(name,"unconsumed"))at=68;
    if(at<80)packet[at]^=1;
    unsigned long long digest=0;assert(!pin_control_write_payload(lease.handle,packet,80,&digest));
    assert(!pin_control_close_creator(lease.handle));assert(!pin_control_transfer_creator(lease.handle,PIN_CONTROL_UNIT));
    assert(!pin_control_open_consumer(lease.handle,PIN_CONTROL_UNIT,&opened));
    assert(opened.physical==lease.physical && opened.handle==lease.handle && opened.bytes==512);
    assert(!pin_control_read_consumer(lease.handle,0,readback,80) && !memcmp(packet,readback,80));
    int rc=full_infrabb_vef_format_consume(&f,readback,80);
    struct pin_control_references refs={0};struct pin_control_snapshot pool={0};
    if(at<80 && at!=68){
        assert(rc==-1 && !f.matches && f.mismatches && !memcmp(f.expected,expected,16));
        assert(!pin_control_references(lease.handle,&refs) && refs.owners==1 && refs.opens==1 && refs.consumer_open==1);
        pin_control_snapshot(&pool);assert(pool.live==1 && !pool.consumer_closes && !pool.consumer_releases);
    }else{
        assert(!rc && f.matches==1 && !f.mismatches && f.payload_fnv && !memcmp(f.current,current,20));
        assert(!pin_control_close_consumer(lease.handle));assert(!pin_control_references(lease.handle,&refs));
        assert(refs.owners==1 && !refs.opens && refs.consumer && !refs.consumer_open);
        assert(!pin_control_release_closed_consumer(lease.handle));pin_control_snapshot(&pool);
        assert(pool.allocations==1 && pool.releases==1 && !pool.live && !pool.faults && !pool.shares && pool.creator_transfers==1 && pool.consumer_closes==1);
        assert(pin_control_references(lease.handle,&refs)==-1);
    }
    puts("INFRABB_VEF_FORMAT_HOST_TEST_PASS");return 0;
}
