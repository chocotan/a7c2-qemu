/* SPDX-License-Identifier: MIT */
#ifndef CAPTURE_DMA_H
#define CAPTURE_DMA_H
#include "capture-output-memory.h"
/* Caller holds the single capture owner's lock and validates the live save phase.
 * Sources are registered JPEG/RAW spans; destinations are writable HEADER/AUX.
 * Both endpoints require current-generation native references. Nonempty copies
 * use source valid bytes and destination capacity; empty copies validate only
 * bound endpoints and references. Alias values belong to this software registry.
 * Performs real byte copy and destination/source readback, no completion event. */
int capture_dma_thumbnail(struct capture_output_memory *,uint64_t destination_alias,
    uint64_t source_alias,size_t bytes,uint64_t *readback_fnv);
#endif
