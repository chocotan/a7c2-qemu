/* SPDX-License-Identifier: MIT */
#ifndef SD_HOTPLUG_ADAPTER_H
#define SD_HOTPLUG_ADAPTER_H

#include "sd-state.h"

/* Caller-supplied IDs: protocol validation belongs to the concrete backend. */
struct sd_hotplug_route {
    uint32_t owner, source, destination;
};

struct sd_hotplug_ops {
    void *context;
    bool (*guard)(void *);
    bool (*backing_unchanged)(void *, const sd_backing *);
    int (*flush_original)(void *, uint64_t generation, uint32_t drive);
    /* Delivery and already-observed evidence are independent. Queue actual
     * observations until this callback returns; core rejects reentrant access. */
    sd_send_result (*send_notification)(void *, uint64_t generation,
        sd_operation, uint32_t owner, uint32_t source, uint32_t destination,
        const uint8_t payload[7]);
};

struct sd_hotplug_counters {
    uint64_t guard_denied, backing_mismatch, flush_failed;
    uint64_t sent, not_sent, uncertain;
};

/* Configure ops and route before bind; zero core/counters once. Keep this object,
 * context and route alive at stable addresses, with ops/route immutable after
 * bind. One owning worker serializes ALL core calls, including observations and
 * timeouts. No process-global state or extra lifecycle mutex is provided. */
struct sd_hotplug_adapter {
    sd_core core;
    struct sd_hotplug_ops ops;
    const struct sd_hotplug_route *route;
    struct sd_hotplug_counters counters;
};

/* Caller supplies actual backing and the already-observed mount, unchanged.
 * All pointers/callbacks/context/route are mandatory. IDs are passed verbatim;
 * the caller validates their protocol meaning (an explicitly supplied 0 stays 0).
 * Subsequent requests/observations/timeouts/snapshots use sd-state.h directly. */
sd_result sd_hotplug_bind(struct sd_hotplug_adapter *, const sd_backing *,
                          const sd_observation *already_observed_mount);
#endif
