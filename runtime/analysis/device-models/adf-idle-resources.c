/* SPDX-License-Identifier: MIT
 * Bounded virtual resource prep for Idle@66ac48; no replies or input callbacks.
 * Contract: report/adf-proc-path-0323.md, resource findings 41a. */
#include "adf-idle-resources.h"

static int zero_storage(const struct full_adf_idle_resources *resources)
{
    const unsigned char *bytes = (const unsigned char *)resources;
    for (unsigned int i = 0; i < sizeof *resources; i++)
        if (bytes[i]) return 0;
    return 1;
}

int full_adf_idle_resources_init(struct full_adf_idle_resources *resources)
{
    if (!resources || !zero_storage(resources)) return -1021;
    struct full_adf_idle_resources cold = {0};
    cold.known = 1;
    for (unsigned int i = 0; i < FULL_ADF_IDLE_CONTROLLERS; i++) {
        cold.controllers[i].known = 1;
        cold.controllers[i].selector = i == FULL_ADF_IDLE_AUDIO ? 2 : 0;
        cold.controllers[i].registered = 1;
    }
    for (unsigned int i = 0; i < FULL_ADF_IDLE_STOCKERS; i++) {
        cold.stockers[i].known = 1;
        cold.stockers[i].policy = 1;
    }
    for (unsigned int i = 0; i < FULL_ADF_IDLE_PINS; i++) {
        cold.pins[i].known = 1;
        cold.pins[i].type = 2 - i;
        cold.pins[i].done_mask = 3;
    }
    *resources = cold;
    return 0;
}

/* completed selects only the two fully specified virtual states. */
static int readback(const struct full_adf_idle_resources *resources, unsigned int completed)
{
    if (!resources || resources->known != 1 || resources->generation != completed ||
        resources->preparations != completed) return 0;
    for (unsigned int i = 0; i < FULL_ADF_IDLE_CONTROLLERS; i++) {
        const struct full_adf_idle_controller *controller = &resources->controllers[i];
        if (controller->known != 1 || controller->selector != (i == FULL_ADF_IDLE_AUDIO ? 2u : 0u) ||
            controller->mode || controller->registered != 1 || controller->busy ||
            controller->flags || controller->events || controller->mode_writes != completed ||
            controller->flag_writes != (i == FULL_ADF_IDLE_YC ? completed : 0u)) return 0;
    }
    for (unsigned int i = 0; i < FULL_ADF_IDLE_STOCKERS; i++) {
        const struct full_adf_idle_stocker *stocker = &resources->stockers[i];
        if (stocker->known != 1 || stocker->read_index >= FULL_ADF_IDLE_STOCK_CAPACITY ||
            stocker->write_index >= FULL_ADF_IDLE_STOCK_CAPACITY || stocker->count ||
            stocker->policy != 1 || stocker->resource_uses ||
            stocker->clear_calls != completed || stocker->clear_result) return 0;
        for (unsigned int slot = 0; slot < FULL_ADF_IDLE_STOCK_CAPACITY; slot++)
            if (stocker->opaque_tokens[slot]) return 0;
    }
    for (unsigned int i = 0; i < FULL_ADF_IDLE_PINS; i++) {
        const struct full_adf_idle_pin *pin = &resources->pins[i];
        if (pin->known != 1 || pin->type != 2 - i || pin->current_path || pin->requested_path ||
            pin->phase1_path || pin->phase2_path || pin->phase != 2 * completed ||
            pin->pending || pin->done_mask != 3 || pin->opaque_lease || pin->lease_uses ||
            pin->registrations != completed || pin->phase1_calls != completed ||
            pin->phase2_calls != completed) return 0;
    }
    return 1;
}

int full_adf_idle_resources_admissible(const struct full_adf_idle_resources *resources)
{
    return readback(resources, 0);
}

static int clear_empty_stocker(struct full_adf_idle_stocker *stocker)
{
    /* ClearAll with count zero does not touch slots, indices or external buffers. */
    if (stocker->count) return -1021;
    stocker->clear_calls++;
    return 0;
}

static int prepare_pin(struct full_adf_idle_pin *pin)
{
    pin->requested_path = 0;
    pin->done_mask = 0;
    pin->pending = 1;
    pin->registrations++;
    /* Path0 vtable+28 returns zero synchronously; it creates no async pin. */
    pin->phase1_path = pin->requested_path;
    pin->phase = 1;
    pin->phase1_calls++;
    pin->done_mask |= 1;
    if (pin->done_mask != 1 || pin->phase != 1 || pin->pending != 1) return -1021;
    pin->phase2_path = pin->requested_path;
    pin->phase = 2;
    pin->phase2_calls++;
    pin->done_mask |= 2;
    pin->current_path = pin->requested_path;
    pin->pending = 0;
    /* 674142 requires both preparation phases, not just the current path. */
    return pin->done_mask == 3 ? 0 : -1021;
}

int full_adf_idle_resources_prepare(struct full_adf_idle_resources *resources,
                                    unsigned long long generation)
{
    if (generation != 1 || !full_adf_idle_resources_admissible(resources)) return -1021;
    struct full_adf_idle_resources next = *resources;
    for (unsigned int i = 0; i < FULL_ADF_IDLE_CONTROLLERS; i++) {
        next.controllers[i].mode = 0;
        next.controllers[i].mode_writes++;
        if (i == FULL_ADF_IDLE_YC) {
            next.controllers[i].flags = 0;
            next.controllers[i].flag_writes++;
        }
        unsigned int first = i == FULL_ADF_IDLE_AUDIO ? FULL_ADF_IDLE_AUDIO0 : FULL_ADF_IDLE_YC0;
        unsigned int end = i == FULL_ADF_IDLE_AUDIO ? FULL_ADF_IDLE_YC0 : FULL_ADF_IDLE_STOCKERS;
        for (unsigned int stock = first; stock < end; stock++) {
            next.stockers[stock].clear_result = clear_empty_stocker(&next.stockers[stock]);
            if (next.stockers[stock].clear_result) return -1021;
        }
    }
    for (unsigned int i = 0; i < FULL_ADF_IDLE_PINS; i++)
        if (prepare_pin(&next.pins[i])) return -1021;
    next.generation = generation;
    next.preparations++;
    if (!readback(&next, 1)) return -1021;
    *resources = next;
    return 0;
}
