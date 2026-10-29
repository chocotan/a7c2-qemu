/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_START_STATE_PROVIDER_H
#define NATIVE_CP_START_STATE_PROVIDER_H
#include "cp-start-state-data.h"
#define CP_START_STATE_PROPERTY_CONTEXT_BYTES 256u
enum cp_start_state_repository {
    CP_START_STATE_REPOSITORY_PRIMARY = 1,
    CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL = 2
};
/* Explicit virtual property owner, not native CP RAM. init has no known input.
 * The prefetch decodes 55bf60 -> be9130 -> be98c6 for the selected repository.
 * LIF, override, history, M/C, kind and Q stay unknown until real consumers run.
 * data may be passed to existing cp_start_state_data consumers under the same
 * external source lock; this provider does not duplicate their algorithms. */
struct cp_start_state_provider {
    struct cp_start_state_data data;
    uint32_t magic;
    int prefetch_result;
    enum cp_start_state_repository repository;
    unsigned char context[CP_START_STATE_PROPERTY_CONTEXT_BYTES];
    unsigned char property_bootstrapped, property_delivered;
};
struct cp_start_state_provider_readback {
    struct cp_start_state_readback data;
    int prefetch_result;
    enum cp_start_state_repository repository;
    unsigned char context[CP_START_STATE_PROPERTY_CONTEXT_BYTES];
    unsigned char property_bootstrapped, property_delivered;
};
int cp_start_state_provider_init(struct cp_start_state_provider *);
/* The caller's public-asset loader must authenticate complete CP and ALLLANG
 * files and the selected bank using the identities in the provider report.
 * bank is one immutable BK4 bank with its exact declared extent, never a
 * private setting or a whole two-bank file. The parser checks its checksum,
 * tables and data bounds before looking up the SAME full property 01250006.
 * Missing key => -ENODATA, unchanged state, profile unknown. A present payload
 * must match the public schema's complete 256-byte context. SECONDARY_VIRTUAL
 * is a new explicit virtual repository policy: no fallback for PRIMARY, no
 * evidence that native CP selected or consumed that bank. One success only.
 * HOST_TEST remains HOST_TEST. All calls need external source serialization,
 * accessible immutable input spans and the same guard contract as the data
 * owner. Errors preserve state/output. No pointer or input buffer is retained. */
int cp_start_state_provider_bootstrap_property(struct cp_start_state_provider *,
    const struct cp_start_state_guard *, enum cp_start_state_repository,
    const unsigned char *bank, size_t size);
/* Actual callback payload for 01250006. Exactly 256 bytes, every byte known.
 * Delivery is independent of bootstrap and may replace its retained context.
 * Callback-only delivery has repository=0 (unbound), with no bank claim. */
int cp_start_state_provider_deliver_property(struct cp_start_state_provider *,
    const struct cp_start_state_guard *, uint32_t property_id,
    const struct cp_start_state_span *payload);
int cp_start_state_provider_snapshot(const struct cp_start_state_provider *,
    const struct cp_start_state_guard *, struct cp_start_state_provider_readback *);
#endif
