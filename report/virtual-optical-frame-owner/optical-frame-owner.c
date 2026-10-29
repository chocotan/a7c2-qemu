/* SPDX-License-Identifier: MIT */
#include "optical-frame-owner.h"
#include <math.h>
#include <string.h>

static optical_frame_status address(const void *p, size_t n)
{
    if (!p) return OPTICAL_FRAME_INVALID;
    return n > UINTPTR_MAX - (uintptr_t)p ? OPTICAL_FRAME_OVERFLOW : OPTICAL_FRAME_OK;
}

static int overlap(const void *a, size_t n, const void *b, size_t m)
{
    return n && m && (uintptr_t)a < (uintptr_t)b + m &&
           (uintptr_t)b < (uintptr_t)a + n;
}

static optical_frame_status owner_status(const optical_frame_owner *o)
{
    optical_frame_status s = address(o, sizeof *o);
    if (s != OPTICAL_FRAME_OK) return s;
    return o->info.state >= OPTICAL_FRAME_IDLE && o->info.state <= OPTICAL_FRAME_READING
           ? OPTICAL_FRAME_OK : OPTICAL_FRAME_STATE;
}

static optical_frame_status layout(size_t w, size_t h, size_t stride)
{
    if (!w || !h) return OPTICAL_FRAME_INVALID;
    if (w > SIZE_MAX / 3) return OPTICAL_FRAME_OVERFLOW;
    if (stride < w * 3) return OPTICAL_FRAME_INVALID;
    return h > SIZE_MAX / stride ? OPTICAL_FRAME_OVERFLOW : OPTICAL_FRAME_OK;
}

static optical_frame_status token_status(const optical_frame_owner *o,
                                        const optical_frame_lease *lease)
{
    optical_frame_status s = owner_status(o);
    if (s != OPTICAL_FRAME_OK) return s;
    s = address(lease, sizeof *lease);
    if (s != OPTICAL_FRAME_OK) return s;
    if (overlap(lease, sizeof *lease, o, sizeof *o) ||
        overlap(lease, sizeof *lease, o->buffer, o->capacity)) return OPTICAL_FRAME_OVERLAP;
    return o->info.state != OPTICAL_FRAME_IDLE && lease->owner == o &&
           lease->generation == o->info.generation && lease->buffer == o->buffer &&
           lease->capacity == o->capacity ? OPTICAL_FRAME_OK : OPTICAL_FRAME_STALE;
}

static uint64_t pixel_hash(const optical_frame_owner *o)
{
    const optical_frame_config *c = &o->info.config;
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t y = 0; y < c->height; ++y)
        for (size_t x = 0; x < c->width * 3; ++x)
            hash = (hash ^ o->buffer[y * c->stride + x]) * UINT64_C(1099511628211);
    return hash;
}

static optical_frame_view view(const optical_frame_owner *o,
                               const unsigned char *pixels, size_t stride)
{
    optical_frame_view v = {OPTICAL_FRAME_VIRTUAL_RGB888, pixels,
        stride * o->info.config.height, o->info.config.width, o->info.config.height,
        stride, o->info.generation, o->info.metadata};
    return v;
}

optical_frame_status optical_frame_init(optical_frame_owner *o)
{
    optical_frame_status s = address(o, sizeof *o);
    if (s != OPTICAL_FRAME_OK) return s;
    if (o->info.state != OPTICAL_FRAME_UNINITIALIZED) return OPTICAL_FRAME_STATE;
    *o = (optical_frame_owner){0};
    o->info.state = OPTICAL_FRAME_IDLE;
    return OPTICAL_FRAME_OK;
}

optical_frame_status optical_frame_configure(optical_frame_owner *o,
                                            const optical_frame_config *c)
{
    optical_frame_status s = owner_status(o);
    if (s != OPTICAL_FRAME_OK) return s;
    if (o->info.state != OPTICAL_FRAME_IDLE) return OPTICAL_FRAME_STATE;
    s = address(c, sizeof *c);
    if (s != OPTICAL_FRAME_OK) return s;
    if (overlap(c, sizeof *c, o, sizeof *o)) return OPTICAL_FRAME_OVERLAP;
    s = layout(c->width, c->height, c->stride);
    if (s != OPTICAL_FRAME_OK) return s;
    /* Delegate parameter validation to the renderer, without touching a frame. */
    unsigned char probe[3];
    optics_metadata metadata;
    optics_stats stats = {0};
    if (optics_render(&c->params, 1, 1, 3, probe, sizeof probe, 0, &metadata, &stats))
        return OPTICAL_FRAME_INVALID;
    o->info.config = *c;
    o->info.configured = 1;
    return OPTICAL_FRAME_OK;
}

optical_frame_status optical_frame_acquire(optical_frame_owner *o,
                                          unsigned char *buffer, size_t capacity,
                                          optical_frame_lease *lease)
{
    optical_frame_status s = owner_status(o);
    if (s != OPTICAL_FRAME_OK) return s;
    if (o->info.state != OPTICAL_FRAME_IDLE || !o->info.configured) return OPTICAL_FRAME_STATE;
    s = address(buffer, capacity);
    if (s != OPTICAL_FRAME_OK) return s;
    s = address(lease, sizeof *lease);
    if (s != OPTICAL_FRAME_OK) return s;
    if (overlap(buffer, capacity, o, sizeof *o) ||
        overlap(lease, sizeof *lease, o, sizeof *o) ||
        overlap(lease, sizeof *lease, buffer, capacity)) return OPTICAL_FRAME_OVERLAP;
    if (capacity < o->info.config.stride * o->info.config.height) return OPTICAL_FRAME_TOO_SMALL;
    if (o->info.generation == UINT64_MAX || o->info.counts.staged == UINT64_MAX)
        return OPTICAL_FRAME_OVERFLOW;
    o->buffer = buffer;
    o->capacity = capacity;
    o->info.state = OPTICAL_FRAME_STAGED;
    ++o->info.generation;
    ++o->info.counts.staged;
    *lease = (optical_frame_lease){o, o->info.generation, buffer, capacity};
    return OPTICAL_FRAME_OK;
}

optical_frame_status optical_frame_render(optical_frame_owner *o,
                                         const optical_frame_lease *lease)
{
    optical_frame_status s = token_status(o, lease);
    if (s != OPTICAL_FRAME_OK) return s;
    if (o->info.state != OPTICAL_FRAME_STAGED) return OPTICAL_FRAME_STATE;
    if (o->info.counts.rendered == UINT64_MAX) return OPTICAL_FRAME_OVERFLOW;
    const optical_frame_config *c = &o->info.config;
    optics_stats stats = {o->info.counts.rendered};
    optics_metadata metadata;
    if (optics_render(&c->params, c->width, c->height, c->stride, o->buffer,
                      o->capacity, o->info.generation, &metadata, &stats))
        return OPTICAL_FRAME_INVALID;
    o->info.metadata = metadata;
    o->info.counts.rendered = stats.completed_frames;
    o->info.state = OPTICAL_FRAME_RENDERED;
    return OPTICAL_FRAME_OK;
}

optical_frame_status optical_frame_consumer_read(optical_frame_owner *o,
                                                const optical_frame_lease *lease,
                                                optical_frame_consumer consumer,
                                                void *context)
{
    optical_frame_status s = token_status(o, lease);
    if (s != OPTICAL_FRAME_OK) return s;
    if (o->info.state != OPTICAL_FRAME_RENDERED) return OPTICAL_FRAME_STATE;
    if (!consumer) return OPTICAL_FRAME_INVALID;
    if (o->info.counts.read == UINT64_MAX) return OPTICAL_FRAME_OVERFLOW;
    if (pixel_hash(o) != o->info.metadata.pixel_fnv1a) return OPTICAL_FRAME_CHANGED;
    optical_frame_view v = view(o, o->buffer, o->info.config.stride);
    o->info.state = OPTICAL_FRAME_READING;
    ++o->info.counts.read;
    int result = consumer(&v, context);
    o->info.state = OPTICAL_FRAME_RENDERED;
    if (pixel_hash(o) != o->info.metadata.pixel_fnv1a) return OPTICAL_FRAME_CHANGED;
    return result ? OPTICAL_FRAME_CONSUMER_FAILED : OPTICAL_FRAME_OK;
}

optical_frame_status optical_frame_copy(optical_frame_owner *o,
                                       const optical_frame_lease *lease,
                                       unsigned char *dst, size_t capacity,
                                       size_t stride, optical_frame_view *out)
{
    optical_frame_status s = token_status(o, lease);
    if (s != OPTICAL_FRAME_OK) return s;
    if (o->info.state != OPTICAL_FRAME_RENDERED) return OPTICAL_FRAME_STATE;
    s = layout(o->info.config.width, o->info.config.height, stride);
    if (s != OPTICAL_FRAME_OK) return s;
    s = address(dst, capacity);
    if (s != OPTICAL_FRAME_OK) return s;
    s = address(out, sizeof *out);
    if (s != OPTICAL_FRAME_OK) return s;
    if (overlap(dst, capacity, o->buffer, o->capacity) ||
        overlap(dst, capacity, o, sizeof *o) ||
        overlap(dst, capacity, lease, sizeof *lease) ||
        overlap(out, sizeof *out, o->buffer, o->capacity) ||
        overlap(out, sizeof *out, o, sizeof *o) ||
        overlap(out, sizeof *out, lease, sizeof *lease) ||
        overlap(out, sizeof *out, dst, capacity)) return OPTICAL_FRAME_OVERLAP;
    if (capacity < stride * o->info.config.height) return OPTICAL_FRAME_TOO_SMALL;
    if (o->info.counts.read == UINT64_MAX || o->info.counts.copied == UINT64_MAX)
        return OPTICAL_FRAME_OVERFLOW;
    if (pixel_hash(o) != o->info.metadata.pixel_fnv1a) return OPTICAL_FRAME_CHANGED;
    for (size_t y = 0; y < o->info.config.height; ++y)
        memcpy(dst + y * stride, o->buffer + y * o->info.config.stride,
               o->info.config.width * 3);
    *out = view(o, dst, stride);
    ++o->info.counts.read;
    ++o->info.counts.copied;
    return OPTICAL_FRAME_OK;
}

optical_frame_status optical_frame_retire(optical_frame_owner *o,
                                         const optical_frame_lease *lease)
{
    optical_frame_status s = token_status(o, lease);
    if (s != OPTICAL_FRAME_OK) return s;
    if (o->info.state != OPTICAL_FRAME_STAGED && o->info.state != OPTICAL_FRAME_RENDERED)
        return OPTICAL_FRAME_STATE;
    if (o->info.counts.retired == UINT64_MAX) return OPTICAL_FRAME_OVERFLOW;
    o->buffer = NULL;
    o->capacity = 0;
    o->info.metadata = (optics_metadata){0};
    o->info.state = OPTICAL_FRAME_IDLE;
    ++o->info.counts.retired;
    return OPTICAL_FRAME_OK;
}

optical_frame_status optical_frame_snapshot(const optical_frame_owner *o,
                                           optical_frame_info *out)
{
    optical_frame_status s = owner_status(o);
    if (s != OPTICAL_FRAME_OK) return s;
    s = address(out, sizeof *out);
    if (s != OPTICAL_FRAME_OK) return s;
    if (overlap(out, sizeof *out, o, sizeof *o) ||
        overlap(out, sizeof *out, o->buffer, o->capacity)) return OPTICAL_FRAME_OVERLAP;
    *out = o->info;
    return OPTICAL_FRAME_OK;
}

static double luminance(const unsigned char *p)
{
    return (54.0 * p[0] + 183.0 * p[1] + 19.0 * p[2]) / 256.0;
}

static double contrast(const unsigned char *pixels, size_t stride,
                       const optical_frame_af_request *r)
{
    double total = 0;
    for (size_t y = 0; y < r->height - 1; ++y)
        for (size_t x = 0; x < r->width - 1; ++x) {
            const unsigned char *p = pixels + (r->y + y) * stride + (r->x + x) * 3;
            double value = luminance(p);
            double dx = luminance(p + 3) - value;
            double dy = luminance(p + stride) - value;
            total += dx * dx + dy * dy;
        }
    return total / (2.0 * (double)(r->width - 1) * (double)(r->height - 1));
}

static int focus_sample(const optical_frame_config *c,
                        const optical_frame_af_request *r,
                        unsigned char *scratch, size_t capacity,
                        double diopters, double *focus_m, double *score)
{
    optics_params p = c->params;
    p.focus_m = diopters == 0 ? INFINITY : 1.0 / diopters;
    p.focus_m = fmax(r->near_m, fmin(r->far_m, p.focus_m));
    optics_metadata metadata;
    optics_stats stats = {0};
    if (optics_render(&p, c->width, c->height, c->stride, scratch, capacity,
                      0, &metadata, &stats)) return -1;
    *focus_m = p.focus_m;
    *score = contrast(scratch, c->stride, r);
    return 0;
}

optical_frame_status optical_frame_autofocus(optical_frame_owner *o,
                                            const optical_frame_af_request *r,
                                            unsigned char *scratch, size_t capacity,
                                            optical_frame_af_result *out)
{
    optical_frame_status s = owner_status(o);
    if (s != OPTICAL_FRAME_OK) return s;
    if (o->info.state != OPTICAL_FRAME_IDLE || !o->info.configured) return OPTICAL_FRAME_STATE;
    s = address(r, sizeof *r);
    if (s != OPTICAL_FRAME_OK) return s;
    s = address(scratch, capacity);
    if (s != OPTICAL_FRAME_OK) return s;
    s = address(out, sizeof *out);
    if (s != OPTICAL_FRAME_OK) return s;
    if (overlap(r, sizeof *r, o, sizeof *o) ||
        overlap(scratch, capacity, o, sizeof *o) ||
        overlap(out, sizeof *out, o, sizeof *o) ||
        overlap(scratch, capacity, r, sizeof *r) ||
        overlap(out, sizeof *out, r, sizeof *r) ||
        overlap(out, sizeof *out, scratch, capacity)) return OPTICAL_FRAME_OVERLAP;
    const optical_frame_config *c = &o->info.config;
    s = layout(c->width, c->height, c->stride);
    if (s != OPTICAL_FRAME_OK) return s;
    if (capacity < c->stride * c->height) return OPTICAL_FRAME_TOO_SMALL;
    if (r->width < 2 || r->height < 2 || r->x > c->width || r->y > c->height ||
        r->width > c->width - r->x || r->height > c->height - r->y ||
        !isfinite(r->near_m) || r->near_m < 0.1 ||
        isnan(r->far_m) || r->far_m <= r->near_m) return OPTICAL_FRAME_INVALID;
    double low = isinf(r->far_m) ? 0 : 1.0 / r->far_m;
    double high = 1.0 / r->near_m, step = (high - low) / 16.0;
    if (step <= 0 || low + step == low || high - step == high) return OPTICAL_FRAME_INVALID;
    optical_frame_af_result result = {0};
    result.score = -1;
    double best = low, worst_score = INFINITY;
    for (size_t i = 0; i < 17; ++i) {
        double d = i == 16 ? high : low + (high - low) * ((double)i / 16.0);
        double focus_m, score;
        if (focus_sample(c, r, scratch, capacity, d, &focus_m, &score))
            return OPTICAL_FRAME_INVALID;
        ++result.coarse_samples;
        worst_score = fmin(worst_score, score);
        if (score > result.score) {
            best = d;
            result.focus_m = focus_m;
            result.score = score;
        }
    }
    /* shortcut: bounded local refinement can miss narrow/multiple peaks; use a
     * denser scan if the renderer gains non-checker scenes or different lenses. */
    for (size_t round = 0; round < 6; ++round) {
        step *= 0.5;
        double center = best;
        for (int side = -1; side <= 1; side += 2) {
            double d = center + side * step;
            if (d < low || d > high || d == center) continue;
            double focus_m, score;
            if (focus_sample(c, r, scratch, capacity, d, &focus_m, &score))
                return OPTICAL_FRAME_INVALID;
            ++result.refinement_samples;
            worst_score = fmin(worst_score, score);
            if (score > result.score) {
                best = d;
                result.focus_m = focus_m;
                result.score = score;
            }
        }
    }
    if (result.score <= 0 || result.score - worst_score <= fmax(1e-9, result.score * 1e-6))
        return OPTICAL_FRAME_NO_CONTRAST;
    o->info.config.params.focus_m = result.focus_m;
    *out = result;
    return OPTICAL_FRAME_OK;
}
