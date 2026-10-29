/* SPDX-License-Identifier: MIT */
#include "adf-aip-coefficients.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static const unsigned int expected[16]={
    0x3f85,0x39f2,0x3e99,0x3ff9,0x22e,0x37f,0x2d2,0x3fff,
    0x3c2e,0x3992,0x3a74,0,0x979,0x143f,0x1cc3,0x1fff
};
int main(void)
{
    for(unsigned int pattern=0;pattern<3;pattern++) {
        unsigned int initial[16],saved[16];
        for(unsigned int i=0;i<16;i++)initial[i]=pattern==0?0:pattern==1?0xa5aa1357u+i:0xffffffffu-i;
        memcpy(saved,initial,sizeof saved);
        struct full_adf_aip_coefficients state={0};
        unsigned int control=pattern==0?0:pattern==1?0xa5a5a5a5:0xffffffff;
        assert(!full_adf_aip_coefficients_init(&state,initial,control));
        assert(!full_adf_aip_coefficients_mode0(&state,1));
        assert(state.generation==1 && state.writes==16 && state.readbacks==16);
        for(unsigned int i=0;i<16;i++)
            assert(state.registers[i]==((initial[i]&~0x3fffu)|expected[i]));
        assert(state.control3904==(control&~0x01000000u));
        assert(!memcmp(saved,initial,sizeof saved));
        struct full_adf_aip_coefficients before=state;
        assert(full_adf_aip_coefficients_mode0(&state,1)==-1021);
        assert(full_adf_aip_coefficients_init(&state,initial,control)==-1021);
        assert(!memcmp(&state,&before,sizeof state));
    }
    for(unsigned int bad=0;bad<6;bad++) {
        unsigned int initial[16]={0};struct full_adf_aip_coefficients state={0};
        assert(!full_adf_aip_coefficients_init(&state,initial,0));
        if(bad==0)state.known=0;
        if(bad==1)state.generation=33;
        if(bad==2)state.writes=1;
        if(bad==3)state.readbacks=1;
        struct full_adf_aip_coefficients before=state;
        assert(full_adf_aip_coefficients_mode0(&state,bad==4?0:bad==5?2:1)==-1021);
        assert(!memcmp(&state,&before,sizeof state));
    }
    assert(full_adf_aip_coefficients_init(0,expected,0)==-1021);
    struct full_adf_aip_coefficients empty={0};
    assert(full_adf_aip_coefficients_init(&empty,0,0)==-1021);
    assert(full_adf_aip_coefficients_mode0(0,1)==-1021);
    puts("ADF_AIP_MODE0_16_ACTUAL_RMW_READBACK_UPPER_BITS_PRESERVED_PASS");
    return 0;
}
