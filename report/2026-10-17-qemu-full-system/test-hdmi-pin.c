/* SPDX-License-Identifier: MIT */
#define TEST_HDMIPIN
#define main unused_registry_fixture_main
#include "test-vef.c"
#undef main
int main(void){
    reset();int rc=123;
    for(unsigned int type=4;type<=5;type++){
        for(unsigned int variant=0;variant<2;variant++){
            unsigned int dir=variant?0x12345678:1,index=variant?0xdeadbeef:0;
            void *p=request(type,dir,index,0x81cf6101,0x81cf6102);
            assert(full_hdmi_pin_dispatch(FULL_HDMI_PIN_CP,p,&io,1,&rc) && !rc && queued);
            const unsigned char *q=queued;assert(get32(q+32)==type && get32(q+36)==1 && get32(q+40)==0);
            assert(get32(q+44)==1 && get32(q+48)==FULL_HDMI_PIN_CP && !get32(q+52));
            assert(full_hdmi_pin_release_reply(0x81cf6102,queued,release,record,&rc) && !rc);queued=0;
        }
    }
    assert(snapshot().registry_objects==2 && snapshot().queries==4 && snapshot().waiter_freed==4);
    full_hdmi_pin_test_set_state(0,2);expected_state=2;accepted(4,1,0,0x81cf6201);
    assert(snapshot().pins[0].state==2 && snapshot().pins[1].state==1);
    reset();void *p=request(4,1,0,0x81cf6101,0x81cf6102);
    assert(!full_hdmi_pin_dispatch(FULL_HDMI_PIN_CP,p,&io,0,&rc) && !snapshot().initialized);
    ((unsigned char *)p)[0]=0;((unsigned char *)p)[1]=0x25;
    assert(!full_hdmi_pin_dispatch(FULL_HDMI_PIN_CP,p,&io,1,&rc) && !snapshot().initialized);assert(!release(FULL_HDMI_PIN_CP,p));
    for(unsigned int type=0;type<2;type++){
        p=request(type?0x10004:6,1,0,0x81cf6101,0x81cf6101);
        assert(full_hdmi_pin_dispatch(FULL_HDMI_PIN_CP,p,&io,1,&rc) && rc==-1021 && !queued && header(p)->live);assert(!release(FULL_HDMI_PIN_CP,p));
    }
    puts("HDMI_PIN_TWO_OBJECTS_FULL_TYPE_ONLY_CANONICAL_REPLY_AND_2500_DEMUX_PASS");
    for(unsigned int mode=0;mode<4;mode++){
        reset();p=request(4,1,0,0x81cf6101,0x81cf6101);
        if(mode==0)alloc_error=-55;
        if(mode==1)send_error=-66;
        if(mode==2)alias=p;
        if(mode==3)((unsigned char *)p)[26]=1;
        assert(full_hdmi_pin_dispatch(FULL_HDMI_PIN_CP,p,&io,1,&rc) && rc && !queued && header(p)->live);
        assert(!snapshot().queries && !snapshot().pending && !snapshot().live_replies);
        alias=0;alloc_error=send_error=0;assert(!release(FULL_HDMI_PIN_CP,p));
    }
    reset();p=request(4,1,0,0x81cf6101,0x81cf6101);request_error=-77;
    assert(full_hdmi_pin_dispatch(FULL_HDMI_PIN_CP,p,&io,1,&rc) && !rc && snapshot().faults);
    request_error=0;assert(!release(FULL_HDMI_PIN_CP,p));reply_error=-78;
    assert(full_hdmi_pin_release_reply(0x81cf6101,queued,release,record,&rc) && rc==-78 && snapshot().live_replies==1);
    reply_error=0;finish(0x81cf6101);
    puts("HDMI_PIN_FAILURE_OWNERSHIP_AND_REAL_NATIVE_RELEASE_PASS");return 0;
}
