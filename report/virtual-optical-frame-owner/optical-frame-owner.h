/* SPDX-License-Identifier: MIT */
#ifndef VIRTUAL_OPTICAL_FRAME_OWNER_H
#define VIRTUAL_OPTICAL_FRAME_OWNER_H

#include "../virtual-optics/optics.h"

/* Caller-owned, externally serialized C11 host component; no allocation, I/O,
 * Sony packing, SDS/DMA binding, device-ready signal, or AP consumption claim.
 * Start with `optical_frame_owner owner = {0}; optical_frame_init(&owner);`.
 * Do not reinitialize, copy, or edit owner internals, including after retirement.
 * All pointer/size arguments must name actual live objects of the stated size;
 * arithmetic/overlap checks cannot establish that arbitrary pointers are mapped.
 */
typedef enum {
    OPTICAL_FRAME_OK = 0,
    OPTICAL_FRAME_INVALID,
    OPTICAL_FRAME_STATE,
    OPTICAL_FRAME_TOO_SMALL,
    OPTICAL_FRAME_OVERFLOW,
    OPTICAL_FRAME_OVERLAP,
    OPTICAL_FRAME_STALE,
    OPTICAL_FRAME_CHANGED,
    OPTICAL_FRAME_CONSUMER_FAILED,
    OPTICAL_FRAME_UNSUPPORTED, /* Retained numeric value; AF no longer uses it. */
    OPTICAL_FRAME_NO_CONTRAST
} optical_frame_status;

typedef enum {
    OPTICAL_FRAME_UNINITIALIZED = 0,
    OPTICAL_FRAME_IDLE,
    OPTICAL_FRAME_STAGED,
    OPTICAL_FRAME_RENDERED,
    OPTICAL_FRAME_READING
} optical_frame_state;

typedef struct {
    optics_params params; /* f/4, f/8, f/16; focus metres, shutter seconds, ISO. */
    size_t width, height, stride; /* stride >= width*3; stride*height must fit. */
} optical_frame_config;

typedef struct {
    uint64_t staged, rendered, read, copied, retired;
} optical_frame_counts;

struct optical_frame_owner;
typedef struct {
    const struct optical_frame_owner *owner;
    uint64_t generation;
    unsigned char *buffer;
    size_t capacity;
} optical_frame_lease;

typedef enum { OPTICAL_FRAME_VIRTUAL_RGB888 = 1 } optical_frame_format;
typedef struct {
    optical_frame_format format; /* Explicit virtual R,G,B bytes; top row first. */
    const unsigned char *pixels;
    size_t size, width, height, stride; /* size=stride*height; padding is not pixels. */
    uint64_t generation;
    optics_metadata metadata; /* Identity/hash are out-of-band, never row pixels. */
} optical_frame_view;

typedef struct {
    optical_frame_state state;
    int configured;
    uint64_t generation;
    optical_frame_config config;
    optics_metadata metadata; /* Valid only in RENDERED/READING. */
    optical_frame_counts counts;
} optical_frame_info;

typedef struct optical_frame_owner {
    /* Private implementation state, public only to permit caller-owned storage. */
    optical_frame_info info;
    unsigned char *buffer;
    size_t capacity;
} optical_frame_owner;

/* Except init's zeroed storage, every function requires an initialized owner.
 * Configuration is copied, so its source may subsequently change or expire.
 * Configure/AF require IDLE; acquire requires IDLE + valid configuration.
 * Error returns leave owner/output objects unchanged, except an invoked consumer
 * increments read even on failure; callbacks may change their context. Forbidden
 * pixel mutations return CHANGED with the lease still live. AF scratch may be
 * written after a scan begins, even on NO_CONTRAST; its result stays unchanged.
 * Generation/counter exhaustion fails closed; configuration never resets either.
 */
optical_frame_status optical_frame_init(optical_frame_owner *owner);
optical_frame_status optical_frame_configure(optical_frame_owner *owner,
                                            const optical_frame_config *config);
optical_frame_status optical_frame_acquire(optical_frame_owner *owner,
                                          unsigned char *buffer, size_t capacity,
                                          optical_frame_lease *lease);
/* Buffer[capacity] must remain exclusively leased and unmodified until retire.
 * Render requires STAGED and the exact owner/generation/buffer/capacity token.
 * Requires capacity >= stride*height, including last-row padding, as optics does.
 * All validation precedes the first pixel write; padding is never written.
 */
optical_frame_status optical_frame_render(optical_frame_owner *owner,
                                         const optical_frame_lease *lease);

/* Borrowed view valid only during this synchronous callback. It must not retain
 * pixels, modify them, or modify owner/lease. Reentrant mutations are rejected.
 * `read` counts callback invocations after full active-pixel hash verification,
 * including callbacks returning nonzero; it proves no particular consumer read.
 * Nonzero callback return -> CONSUMER_FAILED. No caller ACK API exists.
 */
typedef int (*optical_frame_consumer)(const optical_frame_view *view, void *context);
optical_frame_status optical_frame_consumer_read(optical_frame_owner *owner,
                                                const optical_frame_lease *lease,
                                                optical_frame_consumer consumer,
                                                void *context);
/* Full-frame active-pixel copy; dst stride/capacity explicitly bounded, padding
 * unchanged. Source/owner/lease/view/destination declared spans must be disjoint.
 * Source hash must match rendered metadata. On success read++, copied++; neither
 * means AP consumed/encoded. out_view describes caller-owned destination pixels.
 */
optical_frame_status optical_frame_copy(optical_frame_owner *owner,
                                       const optical_frame_lease *lease,
                                       unsigned char *dst, size_t capacity,
                                       size_t stride, optical_frame_view *out_view);
/* Retire accepts STAGED or RENDERED and the exact token, with no implied read or
 * encoding. Duplicate/stale/wrong-buffer retirement leaves the lease live.
 */
optical_frame_status optical_frame_retire(optical_frame_owner *owner,
                                         const optical_frame_lease *lease);
optical_frame_status optical_frame_snapshot(const optical_frame_owner *owner,
                                           optical_frame_info *out_info);
/* Virtual contrast AF over the existing renderer, never a native Sony AF ACK.
 * ROI is in configured frame pixels and must be at least 2x2, wholly in bounds.
 * Distances use optics_params units: finite near_m >= 0.1 metres, far_m > near_m
 * with positive INFINITY allowed. No scene-depth metadata guides the search.
 */
typedef struct {
    size_t x, y, width, height;
    double near_m, far_m;
} optical_frame_af_request;

typedef struct {
    double focus_m; /* Best actually sampled distance, metres. */
    double score; /* Mean squared gradient of Y=(54*R+183*G+19*B)/256, 0..65025. */
    size_t coarse_samples, refinement_samples; /* Actual renders: 17 + at most 12. */
} optical_frame_af_result;

/* Requires configured IDLE; STAGED/RENDERED/READING reject with STATE before any
 * scratch write. Scratch capacity >= configured stride*height; all declared
 * owner/request/scratch/result spans must be disjoint. No allocation or I/O.
 * Validates before rendering 17 uniform-diopter samples + six halving rounds.
 * Each sample renders the whole configured frame and scores only the ROI.
 * A zero/flat score response returns NO_CONTRAST, leaving owner/result unchanged.
 * Scratch active pixels may change after scanning even on failure; padding and
 * excess capacity never change. Success changes only configured focus and result;
 * frame generation/counters/metadata stay unchanged. Scratch holds the last
 * trial, not necessarily the winner: acquire/render normally for a focused frame.
 */
optical_frame_status optical_frame_autofocus(optical_frame_owner *owner,
                                            const optical_frame_af_request *request,
                                            unsigned char *scratch, size_t capacity,
                                            optical_frame_af_result *result);
#endif
