/* SPDX-License-Identifier: MIT */
#define TEST_ADF
#define main old_registry_fixture_main
#include "test-vef.c"
#undef main
#include "scalar-device.h"
int main(void){
    static const unsigned int keys[10][3]={{0,1,0},{2,1,0},{2,1,1},{2,1,2},{3,1,0},{5,1,0},{2,2,0},{2,2,1},{2,2,2},{5,2,0}};
    reset();full_scalar_test_reset();
    for(unsigned int i=0;i<10;i++){
        accepted(keys[i][0],keys[i][1],keys[i][2],0x81cf6001+i);
        struct full_vef_snapshot s=snapshot();assert(!memcmp(s.pins[i].self,keys[i],12));
        assert(s.pins[i].self[3]==FULL_ADF_CP && s.pins[i].state==1 && !s.pins[i].peer[3]);
    }
    struct full_vef_snapshot other;full_scalar_snapshot(&other);assert(!other.initialized);
    assert(snapshot().waiter_freed==10 && snapshot().queries==10 && !snapshot().live_replies);
    full_adf_test_set_state(0,2);expected_state=2;accepted(0,1,0,0x81cf6101);
    assert(snapshot().pins[0].state==2 && snapshot().pins[1].state==1);expected_state=1;
    reset();int rc=123;void *p=request(0,1,0,0x81cf6101,0x81cf6102);
    assert(!full_adf_dispatch(FULL_ADF_CP,p,&io,0,&rc) && rc==123 && !snapshot().initialized);
    assert(full_adf_dispatch(FULL_ADF_CP,p,&io,1,&rc) && !rc);finish(0x81cf6102);
    for(unsigned int field=0;field<3;field++){
        p=request(0,1,0,0x81cf6101,0x81cf6101);put32((unsigned char *)p+32+field*4,0x10000+(field==1));
        assert(full_adf_dispatch(FULL_ADF_CP,p,&io,1,&rc) && rc==-1021 && !queued && header(p)->live);
        assert(!release(FULL_ADF_CP,p));
    }
    assert(snapshot().queries==1);puts("ADF_TEN_OBJECTS_U32_MATCH_DYNAMIC_DESTINATION_AND_ISOLATION_PASS");
    for(unsigned int mode=0;mode<5;mode++){
        reset();p=request(0,1,0,0x81cf6101,0x81cf6101);
        if(mode==0)((unsigned char *)p)[26]=1;
        if(mode==1)alloc_error=-55;
        if(mode==2)send_error=-66;
        if(mode==3)alias=p;
        if(mode==4){header(p)->bytes=64;((unsigned char *)p)[10]=64;}
        assert(full_adf_dispatch(FULL_ADF_CP,p,&io,1,&rc) && rc && header(p)->live && !queued);
        assert(!snapshot().queries && !snapshot().pending && !snapshot().live_replies);
        alias=0;alloc_error=send_error=0;assert(!release(FULL_ADF_CP,p));
    }
    reset();p=request(0,1,0,0x81cf6101,0x81cf6101);request_error=-77;
    assert(full_adf_dispatch(FULL_ADF_CP,p,&io,1,&rc) && !rc && snapshot().faults && header(p)->live);
    request_error=0;assert(!release(FULL_ADF_CP,p));reply_error=-78;
    assert(full_adf_release_reply(0x81cf6101,queued,release,record,&rc) && rc==-78 && snapshot().live_replies==1);
    reply_error=0;finish(0x81cf6101);
    puts("ADF_UNSUPPORTED_FAILURE_OWNERSHIP_AND_NATIVE_RELEASE_PASS");return 0;
}
