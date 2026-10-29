/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_PROPERTY_STAGE_H
#define NATIVE_CP_PROPERTY_STAGE_H
#include "cp-start-state-provider.h"

#define CP_PROPERTY_STAGE_BYTES 1419512u
#define CP_PROPERTY_STAGE_ALLLANG_OFFSET 0xed000u
#define CP_PROPERTY_STAGE_BASE UINT32_C(0x04000000)
#define CP_PROPERTY_STAGE_MODE_ID UINT32_C(0x01250003)
#define CP_PROPERTY_STAGE_ALH_ID UINT32_C(0x000d003a)
#define CP_PROPERTY_STAGE_ALH_BYTES 256u
#define CP_PROPERTY_STAGE_FNV1A64 UINT64_C(0x5436a35ff036e6b5)

enum cp_property_stage_source {
    CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE = 1
};
enum cp_property_stage_repository {
    CP_PROPERTY_STAGE_REPOSITORY_CP_PRIMARY = 1
};
/* Owned source binding, not native CP state or a publication generation.
 * mode starts at file initializer 3 (eb5650), with all three properties unknown.
 * Only consume binds CP_PRIMARY to the explicitly supplied CP_INITIAL_STAGE.
 * source_sequence identifies the SAME immutable transaction for all values. */
struct cp_property_stage_readback {
    uint32_t owner_pid, mode, cp_base;
    uint64_t source_sequence, stage_fnv1a64;
    enum cp_start_state_origin source_origin;
    enum cp_property_stage_source source;
    enum cp_property_stage_repository repository;
    unsigned char mode_property, mode_property_known, profile_known;
    unsigned char context[CP_START_STATE_PROPERTY_CONTEXT_BYTES];
    /* Initial-stage ALH payload only; native publication/current gate unknown. */
    unsigned char alh_property_known;
    unsigned char ALH_context[CP_PROPERTY_STAGE_ALH_BYTES];
};
struct cp_property_stage {
    uint32_t magic;
    struct cp_property_stage_readback value;
};
int cp_property_stage_init(struct cp_property_stage *);
/* Caller first authenticates complete public CP and ALLLANG files plus this
 * exact stage with SHA-256 from report/cp-property-repository-contract.
 * FNV is consistency checking, NOT authentication. Input must be accessible,
 * immutable and externally serialized with the guard. No buffer is retained.
 * This accepts exactly ALLLANG[ed000:] BEFORE any modeled stage[9]=1 freeze;
 * frozen bytes return -EILSEQ, never repaired/rechecksummed/ignored.
 * Explicit CP_INITIAL_STAGE is required; file-zero/secondary/fallback policies
 * are separate. One successful consume only. Every failure preserves state. */
int cp_property_stage_consume(struct cp_property_stage *,
    const struct cp_start_state_guard *, enum cp_property_stage_source,
    const unsigned char *stage, size_t size);
/* Exact even source sequence, process and origin are required for readback and
 * delivery. Output and all declared input capacities must not alias the owner.
 * HOST_TEST stays HOST_TEST. No ready bits, getter, send or publication occurs. */
int cp_property_stage_snapshot(const struct cp_property_stage *,
    const struct cp_start_state_guard *, struct cp_property_stage_readback *);
/* Delivers only the owned complete profile through the existing consumer.
 * A callback-only provider has repository=0; existing bootstrap metadata stays
 * as-is. This owner's readback holds the CP_PRIMARY binding. Only profile's
 * input-known bit is established; no result getter is run.
 * Caller serializes BOTH owners. A failed delivery leaves both unchanged. */
int cp_property_stage_deliver_profile(const struct cp_property_stage *,
    const struct cp_start_state_guard *, struct cp_start_state_provider *);
#endif
