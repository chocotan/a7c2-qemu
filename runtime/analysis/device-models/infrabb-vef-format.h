/* SPDX-License-Identifier: MIT */
#ifndef FULL_INFRABB_VEF_FORMAT_H
#define FULL_INFRABB_VEF_FORMAT_H
#define FULL_INFRABB_VEF_FORMAT_BYTES 80u
#define FULL_INFRABB_VEF_CURRENT_BYTES 20u
#define FULL_INFRABB_VEF_INTERNAL_BYTES 36u
struct full_infrabb_vef_format {
    unsigned int initialized,current_known_bytes,expected_known_bytes;
    unsigned int prepares,executions,matches,mismatches,command_state;
    unsigned char current[20],command_current[20],expected[16];
    unsigned long long current_fnv,command_fnv,payload_fnv;
    unsigned long long forwarded_vef_payload_fnv,forwarded_bb_payload_fnv;
};
/* Independent ordinal0 projection from public CP constructor 5f8488..5f84a0;
 * ordinal1 remains owned by the existing VEF/PinMem model. No live CP RAM. */
int full_infrabb_vef_format_init(struct full_infrabb_vef_format *);
int full_infrabb_vef_format_internal(const struct full_infrabb_vef_format *,unsigned char *,unsigned int);
int full_infrabb_vef_format_prepare(struct full_infrabb_vef_format *,const unsigned char *,unsigned int);
/* This finite command is synchronous, context3/type2; only connected pin state0. */
int full_infrabb_vef_format_execute(struct full_infrabb_vef_format *,unsigned int,unsigned char *,unsigned int);
/* Match compares code/component/full u16 flags/width/height; payload+4 is
 * unconsumed semantically, but all 16 bytes contribute to the readback digest.
 * The fourth-edge consumer keeps its original same-format-only contract. */
int full_infrabb_vef_format_consume(struct full_infrabb_vef_format *,const unsigned char *,unsigned int);
/* Later SSYN01/key0 delivery updates these same live caches, preserving the
 * completed fourth-edge command, match and payload digest as history. */
int full_infrabb_vef_format_accept_forwarded_vef(struct full_infrabb_vef_format *,const unsigned char *,unsigned int);
int full_infrabb_vef_format_accept_forwarded_bb(struct full_infrabb_vef_format *,const unsigned char *,unsigned int,int *);
#endif
