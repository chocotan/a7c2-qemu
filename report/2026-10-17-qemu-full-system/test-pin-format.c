/* SPDX-License-Identifier: MIT */
#include "pin-format.h"
#include "pin-buffer-owner.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
/* Independently transcribed original single-entry wire layout, not a VM log. */
static const unsigned char golden[80]={
    0x53,0x53,0x59,0x4e,0,0,0,1,0,0,0,0,1,0,0,0,
    0x20,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0x45,0x54,0x52,0x59,0,0,0,0,0,0,0,0,0x40,0,0,0,
    0x10,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0xc8,0xf4,0x1f,0,0,0,0,0,0,0x0f,0,0,0x70,8,0,0
};
static unsigned char backing[PIN_CONTROL_CAPACITY];
int main(void){
    unsigned char encoded[81];memset(encoded,0xa5,sizeof encoded);
    struct pin_yc_parameters values={0xc7,3840,2160,200,244};
    assert(pin_yc_build(&values,encoded,79)<0 && encoded[0]==0xa5 && encoded[79]==0xa5);
    assert(!pin_yc_build(&values,encoded,sizeof encoded) && !memcmp(encoded,golden,80) && encoded[80]==0xa5);
    struct pin_yc_payload decoded={0};assert(!pin_yc_decode(golden,sizeof golden,&decoded));
    assert(decoded.code==200 && decoded.component==244 && decoded.encoded_flags==31 && decoded.width==3840 && decoded.height==2160);
    struct pin_yc_current_info current={2,1,0,0,0,1920,1080};
    assert(offsetof(struct pin_yc_current_info,code)==8 && offsetof(struct pin_yc_current_info,width)==12);
    assert(!pin_yc_store(&decoded,&current) && current.pin_index==2 && current.ordinal==1 &&
        current.code==200 && current.component==244 && current.encoded_flags==31 && current.width==3840 && current.height==2160);
    puts("YC_80B_ETRY_INDEPENDENT_GOLDEN_LAYOUT_RAW_FLAGS_TO_ENCODED_STATE_COPY_PASS");
    const unsigned int corrupt[]={0,4,8,12,16,20,24,28,32,36,40,44,48,52,56,60,68};
    for(unsigned int i=0;i<sizeof corrupt/sizeof corrupt[0];i++){
        memcpy(encoded,golden,80);encoded[corrupt[i]]^=1;decoded.width=123;
        assert(pin_yc_decode(encoded,80,&decoded)<0 && decoded.width==123);
    }
    memcpy(encoded,golden,80);encoded[66]=0x80;assert(pin_yc_decode(encoded,80,&decoded)<0);
    assert(pin_yc_decode(golden,79,&decoded)<0);
    puts("YC_UNSUPPORTED_ENTRY_OFFSETS_SIZES_CHAIN_TAG_FLAGS_AND_TRUNCATION_REFUSED_PASS");
    pin_control_test_reset();memset(backing,0,sizeof backing);
    assert(!pin_control_bind_reserved(backing,sizeof backing,PIN_CONTROL_PHYSICAL));
    struct pin_control_lease created,opened;assert(!pin_control_allocate(PIN_CONTROL_UNIT,&created));
    unsigned long long digest=0;assert(!pin_control_write_payload(created.handle,golden,sizeof golden,&digest) && digest);
    assert(!pin_control_share(created.handle,PIN_CONTROL_UNIT));
    assert(!pin_control_open_consumer(created.handle,PIN_CONTROL_UNIT,&opened));
    assert(opened.physical==created.physical && opened.bytes==512);
    assert(!pin_control_release(created.handle));
    assert(!pin_control_read_consumer(created.handle,0,encoded,80) && !memcmp(encoded,golden,80));
    assert(!pin_yc_decode(encoded,80,&decoded) && !pin_yc_store(&decoded,&current));
    assert(!pin_control_release_consumer(created.handle));
    struct pin_control_snapshot s;pin_control_snapshot(&s);assert(!s.live && s.releases==1 && s.payload_writes==1 && s.consumer_reads==1);
    assert(current.pin_index==2 && current.ordinal==1 && current.width==3840 && current.height==2160 && current.code==200);
    assert(!memcmp(backing,golden,80));
    puts("YC_REAL_HOST_BACKING_CONSUMER_READ_PERSISTENT_CPU_CACHE_AFTER_LAST_REFERENCE_RELEASE_PASS");return 0;
}
