/* SPDX-License-Identifier: MIT */
#include "adf-aip-gates.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void)
{
    struct full_adf_aip_gate_registers initial={0xa5a5a5a5,0x12345678,0x87654321,0x33333333,0xffffffff};
    struct full_adf_aip_gate_registers saved=initial;
    for(unsigned int f=0;f<=1;f++) {
        struct full_adf_aip_gates state={0};
        assert(!full_adf_aip_gates_init(&state,&initial,f));
        assert(!state.software_s && !state.software_k && state.init_parameter_f==f);
        assert(!full_adf_aip_gates_mode0(&state,1));
        assert(state.registers.reset3900==(initial.reset3900&~0x100u));
        assert(!state.registers.gate0c50 && !state.registers.classification0c54 && !state.registers.gate23e0);
        assert(state.registers.gate8814==(f?0x20u:0u));
        assert(state.init_parameter_f==f && state.writes==5 && state.readbacks==5 && state.generation==1);
        assert(!memcmp(&initial,&saved,sizeof initial));
        struct full_adf_aip_gates before=state;
        assert(full_adf_aip_gates_mode0(&state,1)==-1021);
        assert(full_adf_aip_gates_init(&state,&initial,f)==-1021);
        assert(!memcmp(&before,&state,sizeof state));
    }
    for(unsigned int n=0;n<8;n++) {
        struct full_adf_aip_gates state={0};assert(!full_adf_aip_gates_init(&state,&initial,1));
        if(n==0)state.known=0;
        if(n==1)state.software_s=1;
        if(n==2)state.software_k=1;
        if(n==3)state.init_parameter_f=2;
        if(n==4)state.generation=33;
        if(n==5)state.writes=1;
        if(n==6)state.readbacks=1;
        struct full_adf_aip_gates before=state;
        assert(full_adf_aip_gates_mode0(&state,n==7?0:1)==-1021);
        assert(!memcmp(&before,&state,sizeof state));
    }
    struct full_adf_aip_gates state={0};
    assert(full_adf_aip_gates_init(&state,&initial,2)==-1021);
    assert(full_adf_aip_gates_init(0,&initial,1)==-1021);
    assert(full_adf_aip_gates_init(&state,0,1)==-1021);
    assert(full_adf_aip_gates_mode0(0,1)==-1021);
    puts("ADF_AIP_COLD_GATES_F0_F1_ORIGINAL_RMW_CLASSIFICATION_READBACK_PASS");
    return 0;
}
