/* SPDX-License-Identifier: MIT */
#include "device-models/functional-startup-control.c"
#include <assert.h>
int fcam_bridge_call(const struct fcam_native_origin *o,uint32_t op,const void *i,size_t n,void *out,size_t cap,struct fcam_bridge_result *r){(void)o;(void)op;(void)i;(void)n;(void)out;(void)cap;(void)r;return -ENOSYS;}
int main(void){
    state.command=FCAM_STARTUP_CONTROL_CMD_MODE;state.cycle=3;
    state.model_instance=7;state.config_generation=8;state.request_owned=state.model_complete=1;
    state.leases[0].freed=1;
    state.leases[1].queued=state.leases[1].received=state.leases[1].freed=1;
    state.leases[1].free_tid=state.leases[1].sender_tid=9;
    for(unsigned i=0;i<24;++i)state.original_wire[i]=(unsigned char)i;
    for(unsigned i=0;i<32;++i)state.canonical32[i]=(unsigned char)(i+9);
    refresh();assert(state.mode_consumed && state.mode_cycle==3 && state.mode_model_instance==7 && state.mode_config_generation==8);
    unsigned char wire[24],canonical[32];memcpy(wire,state.mode_wire,24);memcpy(canonical,state.mode_canonical32,32);
    assert(state.mode_wire_fnv==hash(wire,24) && state.mode_canonical_fnv==hash(canonical,32));
    refresh();assert(state.completed_cycles==1);
    state.command=FCAM_STARTUP_CONTROL_CMD_SETTINGS;state.cycle=4;state.ap_consumed=0;
    memset(state.original_wire,0xa5,24);memset(state.canonical32,0x5a,32);refresh();
    assert(state.completed_cycles==2 && state.command_completed[1]==1 && state.mode_cycle==3);
    assert(!memcmp(wire,state.mode_wire,24) && !memcmp(canonical,state.mode_canonical32,32));
    state.command=FCAM_STARTUP_CONTROL_CMD_MODE;state.cycle=5;state.ap_consumed=0;state.faults=1;refresh();
    assert(state.mode_cycle==3 && state.completed_cycles==2);return 0;
}
