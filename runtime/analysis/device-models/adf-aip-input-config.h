/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_AIP_INPUT_CONFIG_H
#define FULL_ADF_AIP_INPUT_CONFIG_H
#include "adf-public-config.h"
#define FULL_ADF_AIP_INPUT_CONFIG_REGISTERS 236U
#define FULL_ADF_AIP_INPUT_CONFIG_BYTES 44U
#define FULL_ADF_AIP_INPUT_CONFIG_TRACE 256U
#define FULL_ADF_AIP_INPUT_CONFIG_BASE 0xf48a2000U

struct full_adf_aip_input_config_write {
    unsigned int address, value, readback;
};
struct full_adf_aip_input_config {
    const struct full_adf_aip_input_config *identity;
    struct full_adf_public_config *public_config;
    const struct full_adf_public_config *asset_identity;
    unsigned int known, fault, busy, selector, capability_word8, stage;
    unsigned int source, active, software14, software18, flag3c;
    unsigned int cache[9], registers[FULL_ADF_AIP_INPUT_CONFIG_REGISTERS];
    unsigned int builds, applies03, applies02, writes, readbacks, register_reads, public_reads;
    unsigned long long public_read_hash, register_read_hash, write_hash;
    struct full_adf_aip_input_config_write trace[FULL_ADF_AIP_INPUT_CONFIG_TRACE];
    unsigned long long seal;
};
/* Caller serializes this one-shot owner and retains the same loaded public asset.
 * These are independent virtual reset fields/registers, not reconstructed CP RAM.
 * Registers are copied from the caller; unaddressed words/bits remain unchanged. */
int full_adf_aip_input_config_init(struct full_adf_aip_input_config *,
                                 struct full_adf_public_config *, unsigned int capability_word8,
                                 const unsigned int reset[FULL_ADF_AIP_INPUT_CONFIG_REGISTERS]);
/* Exact first selector2 type0/ch2/sample0/depth0/delay0 packet, LE32 {2,44,9 words}. */
int full_adf_aip_input_config_make02(struct full_adf_aip_input_config *, void *, unsigned long bytes);
/* Order: init -> make02 -> consume03(source0) -> consume02(exact original 44B). */
int full_adf_aip_input_config_consume03(struct full_adf_aip_input_config *, unsigned int source);
int full_adf_aip_input_config_consume02(struct full_adf_aip_input_config *,
                                      const void *, unsigned long bytes);
#endif
