/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_AIP_GATES_H
#define FULL_ADF_AIP_GATES_H
struct full_adf_aip_gate_registers {
    unsigned int reset3900, gate0c50, gate8814, classification0c54, gate23e0;
};
struct full_adf_aip_gates {
    unsigned int known, software_s, software_k, init_parameter_f, writes, readbacks;
    unsigned long long generation;
    struct full_adf_aip_gate_registers registers;
};
/* Explicit virtual S0/K0 reset; the original init F must be supplied, never guessed. */
int full_adf_aip_gates_init(struct full_adf_aip_gates *,
                           const struct full_adf_aip_gate_registers *, unsigned int);
int full_adf_aip_gates_mode0(struct full_adf_aip_gates *, unsigned long long);
#endif
