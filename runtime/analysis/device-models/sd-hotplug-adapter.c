/* SPDX-License-Identifier: MIT */
#include "sd-hotplug-adapter.h"

/* Every hook receives its own stable adapter, never process-global routing. */
static bool hook_guard(void *context)
{
    struct sd_hotplug_adapter *a = context;
    bool ok = a->ops.guard(a->ops.context);
    if (!ok) ++a->counters.guard_denied;
    return ok;
}

static bool hook_backing(void *context, const sd_backing *backing)
{
    struct sd_hotplug_adapter *a = context;
    bool ok = a->ops.backing_unchanged(a->ops.context, backing);
    if (!ok) ++a->counters.backing_mismatch;
    return ok;
}

static bool hook_quiescence(void *context, uint64_t generation, uint32_t drive)
{
    struct sd_hotplug_adapter *a = context;
    int rc = a->ops.flush_original(a->ops.context, generation, drive);
    if (rc) ++a->counters.flush_failed;
    return rc == 0;
}

static sd_send_result hook_notify(void *context, uint64_t generation,
                                 sd_operation operation, const uint8_t payload[7])
{
    struct sd_hotplug_adapter *a = context;
    sd_send_result result = a->ops.send_notification(a->ops.context, generation,
        operation, a->route->owner, a->route->source, a->route->destination, payload);
    switch (result.delivery) {
    case SD_SENT: ++a->counters.sent; break;
    case SD_NOT_SENT: ++a->counters.not_sent; break;
    default: ++a->counters.uncertain; break;
    }
    return result;
}

sd_result sd_hotplug_bind(struct sd_hotplug_adapter *a, const sd_backing *backing,
                          const sd_observation *mounted)
{
    if (!a || !backing || !mounted || !a->route || !a->ops.context ||
        !a->ops.guard || !a->ops.backing_unchanged || !a->ops.flush_original ||
        !a->ops.send_notification) return SD_INVALID;
    const sd_adapters hooks = {
        .context = a,
        .guard = hook_guard,
        .validate_backing = hook_backing,
        .validate_quiescence = hook_quiescence,
        .notify = hook_notify,
    };
    return sd_bind(&a->core, &hooks, backing, mounted);
}
