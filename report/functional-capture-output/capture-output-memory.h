/* SPDX-License-Identifier: MIT */
#ifndef CAPTURE_OUTPUT_MEMORY_H
#define CAPTURE_OUTPUT_MEMORY_H
#include <stddef.h>
#include <stdint.h>
#include "../functional-capture-input/capture-input.h"

enum capture_output_role { CAPTURE_OUT_METADATA, CAPTURE_OUT_MAIN, CAPTURE_OUT_THUMB,
    CAPTURE_OUT_HEADER, CAPTURE_OUT_AUX, CAPTURE_OUT_COUNT };
struct capture_output_memory;
struct capture_output_span {
    uintptr_t cpu;
    uint64_t alias, generation;
    size_t bytes, capacity;
    uint32_t handle, unit_type, references;
};
struct capture_output_info {
    uint64_t generation, frame_token, model_instance, model_lifetime, config_generation;
    uint64_t source_RGB_fnv, original_map_base;
    uint32_t native_references, export_references;
    uint64_t request_fnv1a64;
    uint32_t request_cookie;
    uint8_t request_trigger;
};
/* Single-job software owner, externally serialized. Real captured input is held
 * until destroy; Main/Thm must be actual same-job codec output at the caller.
 * Main loses only SOI; Thm is complete. Unknown Exif metadata uses explicit -1
 * sentinels. This makes no original parameter/XMP/AP/Fsys acceptance claim. */
int capture_output_memory_create(struct capture_input *,const void *main,size_t main_bytes,
    const void *thumbnail,size_t thumbnail_bytes,uint64_t actual_map_base,
    struct capture_output_memory **);
int capture_output_memory_info(struct capture_output_memory *,struct capture_output_info *);
int capture_output_memory_span(struct capture_output_memory *,enum capture_output_role,
    struct capture_output_span *);
/* The original1006 transfers one initial reference per metadata/Main/Thm
 * handle. Reserve before send, commit on acceptance or observed consumption;
 * cancel only a definite unsent handoff with no native use. */
int capture_output_memory_publish_begin(struct capture_output_memory *);
int capture_output_memory_publish_commit(struct capture_output_memory *);
int capture_output_memory_publish_cancel(struct capture_output_memory *);
/* Roll back an unobserved failed op20 reply, never a live shared allocation. */
int capture_output_memory_cancel_allocation(struct capture_output_memory *,uint32_t handle);
/* Exact original40B requests20(option1, unit@+4),21(option1),2a/28(query by
 * handle),23(option2). Only observed header80d61/Aux27f allocate from this job.
 * Queries do not pin. Replies require the same actual original mapbase. Reject
 * unknown handles/options without modifying output or references. The software
 * alias is CPU minus that base; it is never an unregistered physical pointer. */
int capture_output_memory_reply(struct capture_output_memory *,const uint8_t request[40],
    uint64_t current_actual_map_base,uint8_t reply[40]);
/* Original MPR/Fsys consumers can outlive original DMM close/free. Each actual
 * pending consumer must hold one token until its own completion/readback. */
int capture_output_memory_hold(struct capture_output_memory *,uint64_t *token);
int capture_output_memory_drop(struct capture_output_memory *,uint64_t token);
/* Requires all native refs and explicit exports released. A root owns every
 * mapped byte until then; close/free never unmaps a live capture's buffers. */
int capture_output_memory_destroy(struct capture_output_memory *);
#endif
