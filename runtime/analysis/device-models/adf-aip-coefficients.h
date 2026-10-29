/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_AIP_COEFFICIENTS_H
#define FULL_ADF_AIP_COEFFICIENTS_H
struct full_adf_aip_coefficients {
    unsigned int known, registers[16], control3904, writes, readbacks;
    unsigned long long generation;
};
/* Own virtual register snapshot only; never maps original physical MMIO. */
int full_adf_aip_coefficients_init(struct full_adf_aip_coefficients *,
                                  const unsigned int *, unsigned int);
int full_adf_aip_coefficients_mode0(struct full_adf_aip_coefficients *, unsigned long long);
#endif
