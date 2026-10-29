/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_PUBLIC_CONFIG_H
#define FULL_ADF_PUBLIC_CONFIG_H
#define FULL_ADF_PUBLIC_SEED_BYTES 2390264UL
#define FULL_ADF_PUBLIC_SEED_FNV 0x6109fb020e03a76eULL
#define FULL_ADF_AIP_BACKUP_BYTES 393U
struct full_adf_public_config {
    unsigned int known, pin_immediately, system_selector, output_source, prelude_flag;
    unsigned int key690219, key690227, key690228, key6902a8, key6902f1;
    unsigned char aip_values[FULL_ADF_AIP_BACKUP_BYTES], aip_known[FULL_ADF_AIP_BACKUP_BYTES];
    unsigned long bytes;
    unsigned long long fnv, queries;
};
/* Caller serializes access and opens only /seed-backup.bin after host SHA/BK4 checks.
 * This owned semantic projection is not CP RAM or its runtime registry; copies
 * remain valid read-only snapshots. Unknown bytes carry 0xa5 with known mask 0. */
int full_adf_public_config_load(struct full_adf_public_config *, int);
int full_adf_public_config_read(struct full_adf_public_config *, unsigned int, unsigned int *);
/* Little-endian projection: only mask-selected known bits are returned; other
 * result bits are zero, not claims about unknown bytes. Failure changes nothing. */
int full_adf_public_config_aip_read(struct full_adf_public_config *, unsigned int offset,
                                  unsigned int mask, unsigned int *out);
#endif
