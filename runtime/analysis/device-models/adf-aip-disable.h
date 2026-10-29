/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_AIP_DISABLE_H
#define FULL_ADF_AIP_DISABLE_H
struct full_adf_aip_disable_registers {
    unsigned int active0400, route8828, route882c, route8830;
    unsigned int route8928, route892c, route8930, controla000;
};
struct full_adf_aip_disable {
    unsigned int known, software_byte, completion_byte, calls, writes, readbacks;
    struct full_adf_aip_disable_registers registers;
};
int full_adf_aip_disable_init(struct full_adf_aip_disable *,
                             const struct full_adf_aip_disable_registers *,unsigned int);
/* Explicit owned S0 and observed active0400.bit0==0 only, bounded to the
 * AF/B0 and subsequent Notify2 B0 (three calls). Never clears active0400 bits
 * to manufacture cold state, never accesses external DMM memory. */
int full_adf_aip_disable_apply(struct full_adf_aip_disable *,unsigned int);
#endif
