/* SPDX-License-Identifier: MIT */
#include "adf-aip-disable.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void)
{
    struct full_adf_aip_disable_registers initial={0xa5a5a5a4,1,2,3,4,5,6,7};
    struct full_adf_aip_disable s={0};
    assert(!full_adf_aip_disable_init(&s,&initial,1));
    for(unsigned int i=0;i<3;i++) {
        assert(!full_adf_aip_disable_apply(&s,0));
        assert(s.registers.active0400==initial.active0400);
        assert(!s.registers.route8828 && !s.registers.route882c && !s.registers.route8830);
        assert(!s.registers.route8928 && !s.registers.route892c && !s.registers.route8930 && !s.registers.controla000);
        assert(!s.software_byte && s.completion_byte==1 && s.calls==i+1 && s.writes==7*(i+1) && s.readbacks==s.writes);
    }
    assert(s.calls==3 && s.writes==21 && s.readbacks==21);
    struct full_adf_aip_disable before=s;
    assert(full_adf_aip_disable_apply(&s,0)==-1021 && !memcmp(&s,&before,sizeof s));
    for(unsigned int bad=0;bad<6;bad++) {
        memset(&s,0,sizeof s);assert(!full_adf_aip_disable_init(&s,&initial,1));
        if(bad==0)s.known=0;
        if(bad==1)s.registers.active0400|=1;
        if(bad==2)s.writes=1;
        if(bad==3)s.readbacks=1;
        if(bad==4)s.completion_byte=1;
        before=s;
        assert(full_adf_aip_disable_apply(&s,bad==5?1:0)==-1021 && !memcmp(&s,&before,sizeof s));
    }
    assert(full_adf_aip_disable_init(&s,&initial,1)==-1021);
    assert(full_adf_aip_disable_init(0,&initial,1)==-1021);
    assert(full_adf_aip_disable_apply(0,0)==-1021);
    puts("ADF_AIP_AF_B0_SEVEN_REAL_WRITES_READBACK_ACTIVE_BIT_PRESERVED_PASS");
    return 0;
}
