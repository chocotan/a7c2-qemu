/* SPDX-License-Identifier: MIT */
#include "adf-idle-resources.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

/* External Speech storage is deliberately never passed to the preparation API. */
static unsigned char external_speech[1024 * 1024], external_before[1024 * 1024];
static unsigned int rejected;

static void cold(struct full_adf_idle_resources *resources)
{
    memset(resources, 0, sizeof *resources);
    assert(!full_adf_idle_resources_init(resources));
    assert(full_adf_idle_resources_admissible(resources) == 1);
}

static void reject_unchanged(struct full_adf_idle_resources *resources,
                             unsigned long long generation, int admissible)
{
    unsigned char before[sizeof *resources];
    memcpy(before, resources, sizeof before);
    assert(full_adf_idle_resources_admissible(resources) == admissible);
    assert(!memcmp(before, resources, sizeof before));
    assert(full_adf_idle_resources_prepare(resources, generation) == -1021);
    assert(!memcmp(before, resources, sizeof before));
    assert(!memcmp(external_before, external_speech, sizeof external_speech));
    rejected++;
}

static void check_positive(void)
{
    struct full_adf_idle_resources resources, snapshot;
    cold(&resources);
    for (unsigned int i = 0; i < FULL_ADF_IDLE_CONTROLLERS; i++) {
        assert(resources.controllers[i].known == 1);
        assert(resources.controllers[i].selector == (i == FULL_ADF_IDLE_AUDIO ? 2u : 0u));
        assert(resources.controllers[i].registered == 1);
    }
    for (unsigned int i = 0; i < FULL_ADF_IDLE_STOCKERS; i++) {
        /* Empty ClearAll must preserve all valid cursor positions. */
        resources.stockers[i].read_index = FULL_ADF_IDLE_STOCK_CAPACITY - 1;
        resources.stockers[i].write_index = i;
        assert(resources.stockers[i].known == 1 && resources.stockers[i].policy == 1);
    }
    assert(full_adf_idle_resources_admissible(&resources));
    assert(!full_adf_idle_resources_prepare(&resources, 1));
    memcpy(&snapshot, &resources, sizeof snapshot);
    assert(snapshot.known == 1 && snapshot.generation == 1 && snapshot.preparations == 1);
    for (unsigned int i = 0; i < FULL_ADF_IDLE_CONTROLLERS; i++) {
        const struct full_adf_idle_controller *controller = &snapshot.controllers[i];
        assert(controller->known == 1 && controller->registered == 1);
        assert(controller->selector == (i == FULL_ADF_IDLE_AUDIO ? 2u : 0u));
        assert(!controller->mode && !controller->flags && !controller->busy && !controller->events);
        assert(controller->mode_writes == 1);
        assert(controller->flag_writes == (i == FULL_ADF_IDLE_YC ? 1u : 0u));
    }
    for (unsigned int i = 0; i < FULL_ADF_IDLE_STOCKERS; i++) {
        const struct full_adf_idle_stocker *stocker = &snapshot.stockers[i];
        assert(stocker->known == 1 && stocker->policy == 1 && !stocker->count);
        assert(stocker->clear_calls == 1 && !stocker->clear_result && !stocker->resource_uses);
        assert(stocker->read_index == FULL_ADF_IDLE_STOCK_CAPACITY - 1 && stocker->write_index == i);
        for (unsigned int slot = 0; slot < FULL_ADF_IDLE_STOCK_CAPACITY; slot++)
            assert(!stocker->opaque_tokens[slot]);
    }
    for (unsigned int i = 0; i < FULL_ADF_IDLE_PINS; i++) {
        const struct full_adf_idle_pin *pin = &snapshot.pins[i];
        assert(pin->known == 1 && pin->type == 2 - i);
        assert(!pin->current_path && !pin->requested_path && !pin->phase1_path && !pin->phase2_path);
        assert(pin->phase == 2 && pin->done_mask == 3 && !pin->pending);
        assert(!pin->opaque_lease && !pin->lease_uses);
        assert(pin->registrations == 1 && pin->phase1_calls == 1 && pin->phase2_calls == 1);
    }
    assert(!memcmp(external_before, external_speech, sizeof external_speech));
    reject_unchanged(&resources, 1, 0);
    reject_unchanged(&resources, 2, 0);
    assert(!memcmp(&snapshot, &resources, sizeof snapshot));
    puts("ADF_IDLE_PREPARATION_PASS controllers=2 empty_clear_calls=5 synchronous_pins=3 phase1=3 phase2=3");
}

static void check_init_and_generations(void)
{
    struct full_adf_idle_resources resources;
    assert(full_adf_idle_resources_init(0) == -1021);
    assert(!full_adf_idle_resources_admissible(0));
    assert(full_adf_idle_resources_prepare(0, 1) == -1021);
    memset(&resources, 0, sizeof resources);
    reject_unchanged(&resources, 1, 0);
    for (unsigned int kind = 0; kind < 3; kind++) {
        unsigned char before[sizeof resources];
        memset(&resources, 0, sizeof resources);
        if (kind == 0) resources.stockers[4].opaque_tokens[19] = 0x8400;
        if (kind == 1) resources.pins[2].opaque_lease = 0x8401;
        if (kind == 2) assert(!full_adf_idle_resources_init(&resources));
        memcpy(before, &resources, sizeof before);
        assert(full_adf_idle_resources_init(&resources) == -1021);
        assert(!memcmp(before, &resources, sizeof before));
    }
    cold(&resources);
    reject_unchanged(&resources, 0, 1);
    reject_unchanged(&resources, 2, 1);
    reject_unchanged(&resources, ULLONG_MAX, 1);
    for (unsigned int kind = 0; kind < 6; kind++) {
        cold(&resources);
        switch (kind) {
        case 0: resources.known = 0; break;
        case 1: resources.known = 2; break;
        case 2: resources.preparations = 1; break;
        case 3: resources.preparations = UINT_MAX; break;
        case 4: resources.generation = 1; break;
        case 5: resources.generation = ULLONG_MAX; break;
        }
        reject_unchanged(&resources, 1, 0);
    }
}

static void check_controllers(void)
{
    struct full_adf_idle_resources resources;
    for (unsigned int index = 0; index < FULL_ADF_IDLE_CONTROLLERS; index++)
        for (unsigned int kind = 0; kind < 11; kind++) {
            cold(&resources);
            struct full_adf_idle_controller *controller = &resources.controllers[index];
            switch (kind) {
            case 0: controller->known = 0; break;
            case 1: controller->known = 2; break;
            case 2: controller->selector ^= 2; break;
            case 3: controller->mode = 1; break;
            case 4: controller->registered = 0; break;
            case 5: controller->registered = 2; break;
            case 6: controller->busy = 1; break;
            case 7: controller->flags = 1; break;
            case 8: controller->events = 1; break;
            case 9: controller->mode_writes = 1; break;
            case 10: controller->flag_writes = 1; break;
            }
            reject_unchanged(&resources, 1, 0);
        }
}

static void check_stockers(void)
{
    struct full_adf_idle_resources resources;
    for (unsigned int index = 0; index < FULL_ADF_IDLE_STOCKERS; index++) {
        for (unsigned int kind = 0; kind < 14; kind++) {
            cold(&resources);
            struct full_adf_idle_stocker *stocker = &resources.stockers[index];
            switch (kind) {
            case 0: stocker->known = 0; break;
            case 1: stocker->known = 2; break;
            case 2: stocker->read_index = FULL_ADF_IDLE_STOCK_CAPACITY; break;
            case 3: stocker->write_index = FULL_ADF_IDLE_STOCK_CAPACITY; break;
            case 4: stocker->read_index = UINT_MAX; break;
            case 5: stocker->write_index = UINT_MAX; break;
            case 6: stocker->count = 1; break;
            case 7: stocker->count = FULL_ADF_IDLE_STOCK_CAPACITY; break;
            case 8: stocker->policy = 0; break;
            case 9: stocker->policy = 2; break;
            case 10: stocker->resource_uses = 1; break;
            case 11: stocker->clear_calls = 1; break;
            case 12: stocker->clear_result = 1; break;
            case 13: stocker->clear_result = -1; break;
            }
            reject_unchanged(&resources, 1, 0);
        }
        for (unsigned int slot = 0; slot < FULL_ADF_IDLE_STOCK_CAPACITY; slot++)
            for (unsigned int token = 0; token < 3; token++) {
                cold(&resources);
                /* count=0 must not conceal a foreign token, even in the last slot. */
                resources.stockers[index].opaque_tokens[slot] = token == 0 ? 0x8400 :
                                                               token == 1 ? 0x8401 : ULLONG_MAX;
                reject_unchanged(&resources, 1, 0);
            }
    }
}

static void check_pins(void)
{
    struct full_adf_idle_resources resources;
    for (unsigned int index = 0; index < FULL_ADF_IDLE_PINS; index++)
        for (unsigned int kind = 0; kind < 22; kind++) {
            cold(&resources);
            struct full_adf_idle_pin *pin = &resources.pins[index];
            switch (kind) {
            case 0: pin->known = 0; break;
            case 1: pin->known = 2; break;
            case 2: pin->type = 3; break;
            case 3: pin->type = (pin->type + 1) % 3; break;
            case 4: pin->current_path = 1; break;
            case 5: pin->requested_path = 1; break;
            case 6: pin->phase1_path = 1; break;
            case 7: pin->phase2_path = 1; break;
            case 8: pin->phase = 1; break;
            case 9: pin->pending = 1; break;
            case 10: pin->done_mask = 0; break;
            case 11: pin->done_mask = 1; break;
            case 12: pin->done_mask = 2; break;
            case 13: pin->done_mask = 4; break;
            case 14: pin->done_mask = 7; break;
            case 15: pin->opaque_lease = 0x8400; break;
            case 16: pin->opaque_lease = 0x8401; break;
            case 17: pin->lease_uses = 1; break;
            case 18: pin->registrations = 1; break;
            case 19: pin->phase1_calls = 1; break;
            case 20: pin->phase2_calls = 1; break;
            case 21: pin->phase = 2; break;
            }
            reject_unchanged(&resources, 1, 0);
        }
}

int main(void)
{
    for (unsigned int i = 0; i < sizeof external_speech; i++)
        external_speech[i] = (unsigned char)(i * 13u + 37u);
    external_speech[0] = 0; external_speech[1] = 0x84;
    external_speech[0x80000] = 1; external_speech[0x80001] = 0x84;
    memcpy(external_before, external_speech, sizeof external_speech);
    check_positive();
    check_init_and_generations();
    check_controllers();
    check_stockers();
    check_pins();
    assert(!memcmp(external_before, external_speech, sizeof external_speech));
    printf("ADF_IDLE_RESOURCES_PASS rejected_unchanged=%u external_bytes=%u preparation_only=1 adf_complete=0 pixel_work=0\n",
           rejected, (unsigned int)sizeof external_speech);
    return 0;
}
