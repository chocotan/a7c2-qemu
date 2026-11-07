/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_CAPTURE_INPUT_H
#define FUNCTIONAL_CAPTURE_INPUT_H
#include <stddef.h>
#include <stdint.h>

struct capture_input;
struct capture_input_info {
    uint64_t token, model_instance, model_lifetime, config_generation, frame_generation;
    uint64_t source_fnv1a64, metadata_alias, pixel_alias;
    uintptr_t metadata_cpu, pixel_cpu, parameter_cpu;
    size_t pixel_bytes;
    uint32_t metadata_unit, pixel_unit, width, height, stride;
    uint32_t mapping_references, pixel_references, owner_references, metadata_readonly;
    uint64_t request_fnv1a64;
    uint32_t request_cookie;
    uint8_t request_trigger;
};
struct capture_input_mapping { uint64_t token; uintptr_t address; size_t bytes; };
/* Explicit software bus. Header96+RGB must be the actual fully read model17
 * output, matched to original4038. No Sony packing/physical-address claim.
 * RGB and submitted P128 pages become read-only before success; metadata1024
 * remains writable for the serializer; callers must hold its mapping borrow.
 * One owner per object, externally serialized; callbacks/guest pointers are not
 * invoked here. No original OSAL/MPR/serializer/completion is synthesized. */
int capture_input_create(const uint8_t *frame, size_t bytes,
    const uint8_t request[16], const uint8_t parameter_snapshot[128], struct capture_input **out);
int capture_input_info(const struct capture_input *, struct capture_input_info *);
/* Long-lived job attachment pins storage without opening a writer or reader. */
int capture_input_hold(struct capture_input *, struct capture_input_mapping *);
int capture_input_drop(struct capture_input *, const struct capture_input_mapping *);
/* Only exact software metadata alias ranges, cache0/caller0x29 are supported.
 * This returning-error API must be reserved before entering original void ctor.
 * Map/unmap release borrowed references, never munmap owner storage. */
int capture_input_map(struct capture_input *, uint64_t alias, size_t bytes,
    uint32_t cache, uint32_t caller, struct capture_input_mapping *);
int capture_input_unmap(struct capture_input *, const struct capture_input_mapping *);
/* Commit metadata only after every writer borrow ended; make its actual page
 * read-only. A subsequent writer may reopen it only with no metadata reader or
 * pixel reader. Asynchronous consumers must hold metadata_read until finished. */
int capture_input_seal_metadata(struct capture_input *);
int capture_input_metadata_read(struct capture_input *, uint32_t unit, uint32_t offset,
    size_t bytes, struct capture_input_mapping *);
int capture_input_release_metadata(struct capture_input *, const struct capture_input_mapping *);
/* Read-only actual RGB range; caller must use its returned mapping until release.
 * Unit is a software registry ID; not an unproven original app_dmm handle. */
int capture_input_pixels(struct capture_input *, uint32_t unit, uint32_t offset,
    size_t bytes, struct capture_input_mapping *);
int capture_input_release_pixels(struct capture_input *, const struct capture_input_mapping *);
/* Refuses every outstanding metadata/pixel borrow; no DONE/ACK inference. */
int capture_input_destroy(struct capture_input *);
#endif
