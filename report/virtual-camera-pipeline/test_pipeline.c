/* SPDX-License-Identifier: MIT */
/* Include the implementation for adversarial checks of private lease callbacks;
 * Python also compiles camera-pipeline.c independently as a production TU. */
#include "camera-pipeline.c"
#include <assert.h>
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <libavutil/log.h>

#define WIDTH 128u
#define HEIGHT 64u
#define STRIDE (WIDTH * 3u + 11u)
#define FRAME_BYTES (STRIDE * HEIGHT)
#define GUARD 16u
#define JPEG_BYTES 65536u
#define DATA_BYTES 262144u
#define CONFIG_BYTES 256u

struct fixture {
    uint8_t pool[FRAME_BYTES + 2 * GUARD];
    uint8_t jpeg[JPEG_BYTES + 2 * GUARD];
    uint8_t data[DATA_BYTES + 2 * GUARD];
    uint8_t config[CONFIG_BYTES + 2 * GUARD];
    struct video_engine_packet packets[8];
    struct vcam_pipeline *p;
    struct vcam_record_buffers buffers;
    int mode, assertions, packets_seen;
};
static optical_frame_config configuration(double focus, double exposure)
{
    const optical_frame_config config = {{4, focus, exposure / 400.0, 100},
                                          WIDTH, HEIGHT, STRIDE};
    return config;
}
static struct vjpeg_coding coding(void)
{
    struct vjpeg_coding c = {VJPEG_SOURCE_HEADER_422, WIDTH, HEIGHT, {{0}}};
    /* Explicit test-only tables, not original guest values or a quality guess. */
    for (size_t t = 0; t < 2; ++t)
        for (size_t i = 0; i < 64; ++i) c.quant_zigzag[t][i] = (uint8_t)(3 + t + i % 13);
    return c;
}
static void check_busy(struct fixture *f)
{
    const struct vcam_info info = vcam_snapshot(f->p);
    assert(info.busy && info.lease_live && info.optical.state == OPTICAL_FRAME_READING);
    assert(info.optical.counts.retired + 1 == info.optical.counts.rendered);
    optical_frame_config config = configuration(1, 1);
    optical_frame_af_request request = {0, 0, 32, 32, 0.5, 8};
    optical_frame_af_result af;
    struct vcam_frame_result frame;
    struct vcam_still_result still;
    struct vjpeg_coding c = coding();
    struct video_engine_result mux;
    assert(vcam_configure(f->p, &config) == VCAM_BUSY);
    assert(vcam_autofocus(f->p, &request, &af) == VCAM_BUSY);
    assert(vcam_capture_still(f->p, &c, f->jpeg + GUARD, JPEG_BYTES, &still) == VCAM_BUSY);
    assert(vcam_record_begin(f->p, 25, &f->buffers) == VCAM_BUSY);
    assert(vcam_record_frame(f->p, &frame) == VCAM_BUSY);
    assert(vcam_record_end(f->p, NULL, 0, &mux) == VCAM_BUSY);
    assert(vcam_destroy(f->p) == VCAM_BUSY);
}
static void observe_irq(void *opaque, unsigned input, int level)
{
    struct fixture *f = opaque;
    assert(input == VJPEG_DEVICE0_EXTERNAL_IRQ);
    if (!level) return;
    check_busy(f);
    const struct vcam_info info = vcam_snapshot(f->p);
    assert(info.jpeg.state == VJPEG_COMPLETE && info.jpeg.irq_level == 1);
    assert(info.jpeg_release_pending && info.jpeg_written && info.jpeg_written == info.jpeg_readback);
    assert(info.jpeg_readback == info.jpeg.output_length);
    assert(info.jpeg_readback_crc32 == crc32(f->jpeg + GUARD + VJPEG_PREFIX_SIZE,
                                            info.jpeg_readback));
    assert(info.counts.output_readback >= info.irq_assertions);
    assert(info.counts.encoded >= info.irq_assertions);
    ++f->assertions;
    if (f->mode == 4) assert(vcam_cancel(f->p) == VCAM_OK);
}
static int observe_packet(const struct video_engine_stream_packet *packet, void *opaque)
{
    struct fixture *f = opaque;
    check_busy(f);
    struct vcam_info info = vcam_snapshot(f->p);
    assert(packet->pts == f->packets_seen && packet->dts == packet->pts && packet->duration == 1);
    assert(info.video.packets_received == info.packet_count + 1);
    assert(!memcmp(f->data + GUARD + info.packet_bytes, packet->data, packet->size));
    ++f->packets_seen;
    if (f->mode == 1) return -731;
    if (f->mode == 2) assert(vcam_cancel(f->p) == VCAM_OK);
    if (f->mode == 3) f->pool[GUARD] ^= 1;
    if (f->mode == 5) f->data[GUARD + info.packet_bytes] ^= 1;
    if (f->mode == 6) f->config[GUARD] ^= 1;
    return 0;
}
static void start(struct fixture *f)
{
    memset(f, 0, sizeof(*f));
    memset(f->pool, 0xa5, sizeof(f->pool));
    memset(f->jpeg, 0xa5, sizeof(f->jpeg));
    memset(f->data, 0xa5, sizeof(f->data));
    memset(f->config, 0xa5, sizeof(f->config));
    const struct vcam_callbacks callbacks = {observe_irq, observe_packet, f};
    f->p = vcam_create(f->pool + GUARD, FRAME_BYTES, &callbacks);
    assert(f->p);
    f->buffers = (struct vcam_record_buffers){f->data + GUARD, DATA_BYTES,
                                            f->packets, 8, f->config + GUARD, CONFIG_BYTES};
    optical_frame_config config = configuration(2, 1);
    assert(vcam_configure(f->p, &config) == VCAM_OK);
}
static void guards(const struct fixture *f)
{
    for (size_t i = 0; i < GUARD; ++i) {
        assert(f->pool[i] == 0xa5 && f->pool[GUARD + FRAME_BYTES + i] == 0xa5);
        assert(f->jpeg[i] == 0xa5 && f->jpeg[GUARD + JPEG_BYTES + i] == 0xa5);
        assert(f->data[i] == 0xa5 && f->data[GUARD + DATA_BYTES + i] == 0xa5);
        assert(f->config[i] == 0xa5 && f->config[GUARD + CONFIG_BYTES + i] == 0xa5);
    }
    for (size_t y = 0; y < HEIGHT; ++y)
        for (size_t x = WIDTH * 3; x < STRIDE; ++x)
            assert(f->pool[GUARD + y * STRIDE + x] == 0xa5);
}
static void stop(struct fixture *f)
{
    guards(f);
    assert(vcam_destroy(f->p) == VCAM_OK);
}
static void poison(struct fixture *f)
{
    for (size_t y = 0; y < HEIGHT; ++y) memset(f->pool + GUARD + y * STRIDE, 0xcc, WIDTH * 3);
}
static void blob(const char *kind, const uint8_t *data, size_t size)
{
    assert(printf("BLOB %s %zu\n", kind, size) > 0);
    assert(fwrite(data, 1, size, stdout) == size);
}
static void lifecycle(void)
{
    struct fixture f;
    start(&f);
    assert(!vcam_create(NULL, 1, NULL));
    assert(!vcam_create(f.pool, 0, NULL));
    assert(vcam_snapshot(NULL).status == VCAM_INVALID);
    assert(vcam_destroy(NULL) == VCAM_OK);
    optical_frame_config config = configuration(1, 1);
    config.stride = FRAME_BYTES;
    assert(vcam_configure(f.p, &config) == VCAM_BOUNDS);
    config = configuration(1, 1); config.params.f_number = 5;
    assert(vcam_configure(f.p, &config) == VCAM_OPTICAL);
    assert(vcam_record_begin(f.p, 0, &f.buffers) == VCAM_VIDEO);
    struct vcam_record_buffers overflow = f.buffers;
    overflow.packet_capacity = SIZE_MAX;
    assert(vcam_record_begin(f.p, 25, &overflow) == VCAM_BOUNDS);
    optical_frame_config odd = configuration(1, 1);
    odd.width = WIDTH - 1;
    assert(vcam_configure(f.p, &odd) == VCAM_OK);
    assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_VIDEO);
    config = configuration(1, 1);
    assert(vcam_configure(f.p, &config) == VCAM_OK);
    assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
    struct vcam_still_result still;
    struct vjpeg_coding c = coding();
    assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, JPEG_BYTES, &still) == VCAM_BUSY);
    assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_BUSY);
    config = configuration(1, 1); config.width -= 2;
    assert(vcam_configure(f.p, &config) == VCAM_BUSY);
    struct video_engine_result mux;
    assert(vcam_record_end(f.p, NULL, 0, &mux) == VCAM_STATE);
    assert(vcam_cancel(f.p) == VCAM_CANCELLED);
    struct vcam_record_buffers bad = f.buffers;
    bad.config = bad.data;
    assert(vcam_record_begin(f.p, 25, &bad) == VCAM_OVERLAP);
    assert(vcam_capture_still(f.p, &c, f.pool + GUARD, FRAME_BYTES, &still) == VCAM_OVERLAP);
    assert(vcam_snapshot(f.p).counts.rendered == 0);
    assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
    optical_frame_config *aliased = (optical_frame_config *)(void *)f.buffers.data;
    memcpy(aliased, &config, sizeof(config));
    assert(vcam_configure(f.p, aliased) == VCAM_OVERLAP);
    assert(vcam_cancel(f.p) == VCAM_CANCELLED);
    stop(&f);
}
static int adversarial_borrow(const optical_frame_view *view, void *opaque)
{
    struct fixture *f = opaque;
    struct vcam_pipeline *p = f->p;
    p->borrowed = view;
    struct vjpeg_mapping source, destination;
    p->jpeg_output = f->jpeg + GUARD;
    p->jpeg_capacity = JPEG_BYTES;
    assert(!jpeg_probe(p, SOURCE_ADDRESS, view->size, VJPEG_READ, &source));
    assert(!jpeg_probe(p, OUTPUT_ADDRESS, JPEG_BYTES - VJPEG_PREFIX_SIZE,
                       VJPEG_READ | VJPEG_WRITE, &destination));
    assert(source.object && destination.object && source.object != destination.object);
    assert(source.offset == 0 && destination.offset == VJPEG_PREFIX_SIZE);
    assert(jpeg_probe(p, SOURCE_ADDRESS, view->size + 1, VJPEG_READ, &source));
    assert(jpeg_probe(p, OUTPUT_ADDRESS, JPEG_BYTES, VJPEG_READ | VJPEG_WRITE, &destination));
    assert(jpeg_probe(p, SOURCE_ADDRESS, view->size, VJPEG_WRITE, &source));
    struct vjpeg_frame frame = {0};
    assert(jpeg_acquire(p, SOURCE_ADDRESS + 1, view->size, &frame));
    ++p->lease.generation;
    assert(jpeg_acquire(p, SOURCE_ADDRESS, view->size, &frame));
    --p->lease.generation;
    ++p->lease.capacity;
    assert(jpeg_acquire(p, SOURCE_ADDRESS, view->size, &frame));
    --p->lease.capacity;
    optical_frame_view unknown = *view;
    unknown.format = (optical_frame_format)0;
    p->borrowed = &unknown;
    assert(jpeg_acquire(p, SOURCE_ADDRESS, view->size, &frame));
    p->borrowed = view;
    assert(!jpeg_acquire(p, SOURCE_ADDRESS, view->size, &frame));
    assert(frame.rgb == p->pool && frame.lease == &p->lease && frame.size == FRAME_BYTES);
    uint8_t readback[7];
    assert(!jpeg_read(p, SOURCE_ADDRESS + 3, readback, sizeof(readback)));
    assert(!memcmp(readback, view->pixels + 3, sizeof(readback)));
    assert(jpeg_write(p, OUTPUT_ADDRESS + JPEG_BYTES, readback, sizeof(readback)));
    jpeg_release(p, &p->lease, 0);
    assert(p->info.jpeg_release_pending && p->owner.info.state == OPTICAL_FRAME_READING);
    assert(p->owner.info.counts.retired == 0);
    assert(vcam_cancel(p) == VCAM_OK);
    assert(p->owner.info.state == OPTICAL_FRAME_READING && p->info.lease_live);
    assert(!p->owner.info.counts.retired);
    p->borrowed = NULL;
    p->jpeg_output = NULL;
    p->jpeg_capacity = 0;
    return 0;
}
static void callbacks(void)
{
    struct fixture f;
    start(&f);
    struct vcam_pipeline *p = f.p;
    assert(optical_frame_acquire(&p->owner, p->pool, p->pool_capacity, &p->lease) == OPTICAL_FRAME_OK);
    p->info.lease_live = 1;
    assert(optical_frame_render(&p->owner, &p->lease) == OPTICAL_FRAME_OK);
    p->info.busy = 1;
    assert(optical_frame_consumer_read(&p->owner, &p->lease, adversarial_borrow, &f) == OPTICAL_FRAME_OK);
    p->info.busy = 0;
    assert(optical_frame_retire(&p->owner, &p->lease) == OPTICAL_FRAME_OK);
    p->info.lease_live = 0;
    assert(vcam_snapshot(p).counts.retired == 1);
    stop(&f);
}
static void stale_lease(void)
{
    struct fixture f;
    start(&f);
    struct vcam_pipeline *p = f.p;
    assert(optical_frame_acquire(&p->owner, p->pool, p->pool_capacity, &p->lease) == OPTICAL_FRAME_OK);
    p->info.lease_live = 1;
    ++p->lease.generation;
    assert(vcam_cancel(p) == VCAM_OPTICAL);
    assert(p->info.lease_live && !p->owner.info.counts.retired);
    assert(p->info.optical_status == OPTICAL_FRAME_STALE);
    optical_frame_config config = configuration(1, 1);
    assert(vcam_configure(p, &config) == VCAM_BUSY);
    assert(vcam_destroy(p) == VCAM_BUSY);
    --p->lease.generation;
    assert(vcam_cancel(p) == VCAM_CANCELLED);
    assert(!p->info.lease_live && p->owner.info.counts.retired == 1);
    stop(&f);
}
static int cancel_jpeg_borrow(const optical_frame_view *view, void *opaque)
{
    struct vcam_pipeline *p = opaque;
    p->borrowed = view;
    assert(vcam_cancel(p) == VCAM_OK);
    assert(vjpeg_hw_snapshot(p->jpeg).state == VJPEG_FAULT);
    assert(vjpeg_hw_snapshot(p->jpeg).result == VJPEG_CANCELLED);
    assert(p->info.lease_live && !p->owner.info.counts.retired);
    p->borrowed = NULL;
    return 0;
}
static void jpeg_cancel(void)
{
    struct fixture f;
    start(&f);
    struct vcam_pipeline *p = f.p;
    struct vjpeg_job job = {SOURCE_ADDRESS, FRAME_BYTES, OUTPUT_ADDRESS,
        JPEG_BYTES - VJPEG_PREFIX_SIZE, VJPEG_RGB888, coding()};
    assert(vjpeg_hw_prepare(p->jpeg, &job) == VJPEG_OK);
    assert(optical_frame_acquire(&p->owner, p->pool, p->pool_capacity, &p->lease) == OPTICAL_FRAME_OK);
    p->info.lease_live = p->info.busy = 1;
    assert(optical_frame_render(&p->owner, &p->lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_consumer_read(&p->owner, &p->lease, cancel_jpeg_borrow, p) == OPTICAL_FRAME_OK);
    assert(optical_frame_retire(&p->owner, &p->lease) == OPTICAL_FRAME_OK);
    p->info.lease_live = p->info.busy = 0;
    assert(!vcam_snapshot(p).irq_assertions && !vcam_snapshot(p).counts.encoder_consumed);
    stop(&f);
}
static void af_checks(void)
{
    struct fixture f;
    start(&f);
    optical_frame_af_result af;
    for (size_t layer = 0; layer < 2; ++layer) {
        optical_frame_af_request request = {layer * WIDTH / 2 + 4, 4, WIDTH / 2 - 8, HEIGHT - 8, 0.5, 8};
        assert(vcam_autofocus(f.p, &request, &af) == VCAM_OK);
        assert(fabs(af.focus_m - (layer ? 4.0 : 1.0)) < (layer ? 0.2 : 0.08));
        assert(af.score > 0 && af.coarse_samples == 17 && af.refinement_samples <= 12);
    }
    optical_frame_config flat = configuration(2, 1e-300);
    assert(vcam_configure(f.p, &flat) == VCAM_OK);
    optical_frame_af_request request = {4, 4, 48, 48, 0.5, 8};
    memset(&af, 0xa5, sizeof(af));
    optical_frame_af_result before = af;
    assert(vcam_autofocus(f.p, &request, &af) == VCAM_OPTICAL);
    assert(vcam_snapshot(f.p).optical_status == OPTICAL_FRAME_NO_CONTRAST);
    assert(!memcmp(&af, &before, sizeof(af)));
    assert(vcam_snapshot(f.p).optical.config.params.focus_m == 2);
    assert(!vcam_snapshot(f.p).counts.rendered);
    stop(&f);
}
static void jpeg_errors(void)
{
    struct fixture f;
    start(&f);
    struct vjpeg_coding c = coding();
    struct vcam_still_result result;
    memset(&result, 0xa5, sizeof(result));
    const struct vcam_still_result before = result;
    c.contract = VJPEG_CODING_UNKNOWN;
    assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, JPEG_BYTES, &result) == VCAM_JPEG);
    assert(vcam_snapshot(f.p).jpeg.result == VJPEG_UNSUPPORTED);
    c = coding(); c.quant_zigzag[0][9] = 0;
    assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, JPEG_BYTES, &result) == VCAM_JPEG);
    assert(vcam_snapshot(f.p).jpeg.result == VJPEG_INVALID);
    c = coding(); c.width -= 2;
    assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, JPEG_BYTES, &result) == VCAM_INVALID);
    assert(!f.assertions && !vcam_snapshot(f.p).counts.rendered);
    c = coding();
    assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, VJPEG_PREFIX_SIZE, &result) == VCAM_BOUNDS);
    assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, VJPEG_PREFIX_SIZE + 16, &result) == VCAM_JPEG);
    struct vcam_info info = vcam_snapshot(f.p);
    assert(info.jpeg.result == VJPEG_BOUNDS && info.jpeg.state == VJPEG_FAULT);
    assert(info.counts.rendered == 1 && info.counts.source_read == 1 && info.counts.encoder_consumed == 1);
    assert(!info.counts.encoded && !info.counts.output_readback && info.counts.retired == 1);
    assert(!info.irq_assertions && !info.lease_live && !memcmp(&result, &before, sizeof(result)));
    assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, JPEG_BYTES, &result) == VCAM_OK);
    assert(f.assertions == 1 && result.jpeg_length == result.prefix_length + result.suffix_length);
    assert(result.prefix_length == VJPEG_PREFIX_SIZE && result.frame.generation == 2);
    assert(!vcam_snapshot(f.p).jpeg_release_pending);
    const size_t exact = result.jpeg_length;
    uint8_t *saved = malloc(exact);
    assert(saved); memcpy(saved, f.jpeg + GUARD, exact);
    assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, exact - 1, &result) == VCAM_JPEG);
    assert(f.assertions == 1 && vcam_snapshot(f.p).jpeg.result == VJPEG_BOUNDS);
    assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, exact, &result) == VCAM_OK);
    assert(f.assertions == 2 && result.jpeg_length == exact && !memcmp(saved, f.jpeg + GUARD, exact));
    free(saved);
    stop(&f);
}
static void sink_failure(void)
{
    struct fixture f;
    start(&f);
    f.mode = 1;
    struct vcam_frame_result frame;
    assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
    assert(vcam_record_frame(f.p, &frame) == VCAM_SINK);
    const struct vcam_info failed = vcam_snapshot(f.p);
    assert(vcam_record_frame(f.p, &frame) == VCAM_STATE);
    assert(vcam_snapshot(f.p).counts.encoder_consumed == failed.counts.encoder_consumed);
    struct vcam_info info = vcam_snapshot(f.p);
    assert(info.state == VCAM_FAULT && info.video.sink_error == -731);
    assert(info.video.frames_consumed == 1 && info.video.packets_received == 1 && !info.video.packets_published);
    assert(!info.packet_count && info.counts.encoder_consumed == 1 && info.counts.encoded == 1);
    assert(info.counts.output_readback == 1 && info.counts.retired == 1 && !info.lease_live);
    assert(vcam_cancel(f.p) == VCAM_CANCELLED);
    info = vcam_snapshot(f.p);
    assert(info.last_failure == VCAM_SINK && info.video.sink_error == -731);
    assert(info.video.status == VIDEO_ENGINE_SINK_ERROR && info.video.frames_consumed == 1);
    stop(&f);
}
static void capacities(void)
{
    for (int test = 0; test < 3; ++test) {
        struct fixture f;
        start(&f);
        if (test == 0) f.buffers.data_capacity = 1;
        if (test == 1) f.buffers.config_capacity = 1;
        if (test == 2) f.buffers.packet_capacity = 1;
        assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
        struct vcam_frame_result frame;
        if (test == 2) assert(vcam_record_frame(f.p, &frame) == VCAM_OK);
        assert(vcam_record_frame(f.p, &frame) == VCAM_BOUNDS);
        struct vcam_info info = vcam_snapshot(f.p);
        assert(info.state == VCAM_FAULT && !info.lease_live);
        assert(info.counts.retired == (test == 2 ? 2u : 1u));
        if (test == 1) assert(info.config_required > 1 && info.video.sink_error == SINK_CONFIG);
        if (test == 2) assert(info.packet_count == 1 && info.video.sink_error == SINK_INDEX);
        assert(vcam_cancel(f.p) == VCAM_CANCELLED);
        stop(&f);
    }
}
static void cancellation(void)
{
    struct fixture f;
    start(&f);
    struct vcam_frame_result frame;
    assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
    assert(vcam_record_frame(f.p, &frame) == VCAM_OK);
    assert(vcam_cancel(f.p) == VCAM_CANCELLED);
    assert(vcam_snapshot(f.p).video.state == VIDEO_ENGINE_STREAM_CANCELLED);
    assert(vcam_snapshot(f.p).counts.retired == 1);
    f.packets_seen = 0;
    f.mode = 2;
    assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
    assert(vcam_record_frame(f.p, &frame) == VCAM_CANCELLED);
    struct vcam_info info = vcam_snapshot(f.p);
    assert(info.state == VCAM_IDLE && info.video.state == VIDEO_ENGINE_STREAM_CANCELLED);
    assert(info.counts.encoder_consumed == 2 && info.counts.retired == 2);
    assert(info.video.packets_published == 1 && !info.lease_live);
    f.mode = 4;
    struct vjpeg_coding c = coding();
    struct vcam_still_result still = {0};
    assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, JPEG_BYTES, &still) == VCAM_CANCELLED);
    assert(!still.jpeg_length && f.assertions == 1);
    assert(vcam_snapshot(f.p).counts.retired == 3);
    stop(&f);
}
static void mutation(void)
{
    for (int test = 0; test < 3; ++test) {
        struct fixture f;
        start(&f);
        f.mode = test == 0 ? 3 : test + 4;
        assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
        struct vcam_frame_result frame = {0};
        assert(vcam_record_frame(f.p, &frame) == (test == 0 ? VCAM_OPTICAL : VCAM_SINK));
        struct vcam_info info = vcam_snapshot(f.p);
        assert(info.state == VCAM_FAULT && info.counts.retired == 1 && !info.lease_live);
        assert(!frame.generation);
        if (test == 0) assert(info.optical_status == OPTICAL_FRAME_CHANGED && info.video.packets_published == 1);
        else assert(info.video.sink_error == SINK_VERIFY && !info.video.packets_published);
        assert(vcam_cancel(f.p) == VCAM_CANCELLED);
        stop(&f);
    }
}
static void mux_checks(void)
{
    struct fixture f;
    start(&f);
    assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
    struct vcam_frame_result frame;
    assert(vcam_record_frame(f.p, &frame) == VCAM_OK);
    assert(vcam_record_frame(f.p, &frame) == VCAM_OK);
    struct video_engine_result mux;
    assert(vcam_record_end(f.p, NULL, 0, &mux) == VCAM_BOUNDS);
    assert(mux.status == VIDEO_ENGINE_OUTPUT_TOO_SMALL && mux.required > 1 && !mux.used);
    const size_t required = mux.required;
    assert(vcam_snapshot(f.p).state == VCAM_DRAINED);
    assert(vcam_snapshot(f.p).video.state == VIDEO_ENGINE_STREAM_FINISHED);
    assert(vcam_record_frame(f.p, &frame) == VCAM_STATE);
    uint8_t *output = malloc(required + 1);
    assert(output); memset(output, 0xa5, required + 1);
    assert(vcam_record_end(f.p, output, required - 1, &mux) == VCAM_BOUNDS);
    assert(mux.required == required && !mux.used);
    for (size_t i = 0; i <= required; ++i) assert(output[i] == 0xa5);
    assert(vcam_record_end(f.p, output, required, &mux) == VCAM_OK);
    assert(mux.used == required && output[required] == 0xa5);
    free(output);
    f.packets_seen = 0;
    assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
    assert(vcam_record_frame(f.p, &frame) == VCAM_OK);
    f.data[GUARD + 5] ^= 1;
    assert(vcam_record_end(f.p, NULL, 0, &mux) == VCAM_SINK);
    assert(vcam_snapshot(f.p).state == VCAM_FAULT);
    stop(&f);
    for (int field = 0; field < 2; ++field) {
        start(&f);
        assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
        assert(vcam_record_frame(f.p, &frame) == VCAM_OK);
        if (field == 0) f.config[GUARD] ^= 1;
        else f.packets[0].pts = 9;
        assert(vcam_record_end(f.p, NULL, 0, &mux) == (field == 0 ? VCAM_SINK : VCAM_VIDEO));
        if (field == 1) assert(mux.status == VIDEO_ENGINE_INVALID_ARGUMENT);
        assert(vcam_snapshot(f.p).state == VCAM_FAULT);
        stop(&f);
    }
}
static void products(size_t count)
{
    struct fixture f;
    start(&f);
    struct vjpeg_coding c = coding();
    for (size_t layer = 0; layer < 2; ++layer) {
        optical_frame_config config = configuration(2, layer ? 1.2 : 0.75);
        assert(vcam_configure(f.p, &config) == VCAM_OK);
        optical_frame_af_request request = {layer * WIDTH / 2 + 4, 4, WIDTH / 2 - 8, HEIGHT - 8, 0.5, 8};
        optical_frame_af_result af;
        assert(vcam_autofocus(f.p, &request, &af) == VCAM_OK);
        struct vcam_still_result still;
        assert(vcam_capture_still(f.p, &c, f.jpeg + GUARD, JPEG_BYTES, &still) == VCAM_OK);
        blob("STILL_RGB", f.pool + GUARD, FRAME_BYTES);
        blob("JPEG", f.jpeg + GUARD, still.jpeg_length);
        assert(printf("META {\"kind\":\"still\",\"generation\":%" PRIu64 ",\"hash\":%" PRIu64
            ",\"focus\":%.17g,\"blur\":[%.17g,%.17g],\"prefix\":%zu,\"suffix\":%zu,"
            "\"prefix_crc\":%" PRIu32 ",\"suffix_crc\":%" PRIu32 ",\"jpeg_crc\":%" PRIu32 "}\n",
            still.frame.generation, still.frame.metadata.pixel_fnv1a, af.focus_m,
            still.frame.metadata.blur_radius_px[0], still.frame.metadata.blur_radius_px[1],
            still.prefix_length, still.suffix_length, still.prefix_crc32, still.suffix_crc32,
            still.jpeg_crc32) > 0);
        poison(&f);
    }
    assert(vcam_record_begin(f.p, 25, &f.buffers) == VCAM_OK);
    for (size_t i = 0; i < count; ++i) {
        optical_frame_config config = configuration(i % 2 ? 4 : 1, 0.6 + (double)i * 0.17);
        assert(vcam_configure(f.p, &config) == VCAM_OK);
        if (i == count / 2) {
            optical_frame_af_request request = {WIDTH / 2 + 4, 4, WIDTH / 2 - 8, HEIGHT - 8, 0.5, 8};
            optical_frame_af_result af;
            assert(vcam_autofocus(f.p, &request, &af) == VCAM_OK);
        }
        struct vcam_frame_result frame;
        assert(vcam_record_frame(f.p, &frame) == VCAM_OK);
        assert(frame.generation == i + 3 && frame.metadata.frame_number == frame.generation);
        assert(frame.pts == (int64_t)i);
        struct vcam_info info = vcam_snapshot(f.p);
        assert(info.packet_count == i + 1 && info.video.frames_consumed == i + 1);
        blob("VIDEO_RGB", f.pool + GUARD, FRAME_BYTES);
        assert(printf("META {\"kind\":\"frame\",\"generation\":%" PRIu64 ",\"hash\":%" PRIu64
                      ",\"pts\":%" PRId64 "}\n", frame.generation,
                      frame.metadata.pixel_fnv1a, frame.pts) > 0);
        poison(&f); /* Prove both encoders retain no borrowed raw input. */
        guards(&f);
    }
    struct video_engine_result mux;
    assert(vcam_record_end(f.p, NULL, 0, &mux) == VCAM_BOUNDS);
    uint8_t *mp4 = malloc(mux.required);
    assert(mp4);
    assert(vcam_record_end(f.p, mp4, mux.required, &mux) == VCAM_OK);
    struct vcam_info info = vcam_snapshot(f.p);
    blob("H264", f.data + GUARD, info.packet_bytes);
    blob("CONFIG", f.config + GUARD, info.config_bytes);
    blob("MP4", mp4, mux.used);
    for (size_t i = 0; i < info.packet_count; ++i) {
        const struct video_engine_packet packet = f.packets[i];
        assert(printf("META {\"kind\":\"packet\",\"offset\":%zu,\"size\":%zu,\"pts\":%" PRId64
                      ",\"dts\":%" PRId64 ",\"duration\":%" PRId64 ",\"keyframe\":%d}\n",
                      packet.offset, packet.size, packet.pts, packet.dts, packet.duration, packet.keyframe) > 0);
    }
    assert(printf("META {\"kind\":\"done\",\"rendered\":%" PRIu64 ",\"source_read\":%" PRIu64
        ",\"encoder_consumed\":%" PRIu64 ",\"encoded\":%" PRIu64 ",\"output_readback\":%" PRIu64
        ",\"retired\":%" PRIu64 ",\"irq\":%" PRIu64 ",\"packets\":%zu,\"width\":%u,"
        "\"height\":%u,\"stride\":%u,\"fps\":25}\n", info.counts.rendered, info.counts.source_read,
        info.counts.encoder_consumed, info.counts.encoded, info.counts.output_readback, info.counts.retired,
        info.irq_assertions, info.packet_count, WIDTH, HEIGHT, STRIDE) > 0);
    assert(info.counts.rendered == count + 2 && info.counts.source_read == count + 2 &&
        info.counts.encoder_consumed == count + 2 && info.counts.encoded == count + 2 &&
        info.counts.output_readback == count + 2 && info.counts.retired == count + 2);
    assert(info.video.state == VIDEO_ENGINE_STREAM_FINISHED && info.irq_assertions == 2);
    free(mp4);
    stop(&f);
}
static void geometry(void)
{
    const size_t capacity = (size_t)VCAM_MAX_STILL_WIDTH * 2u * 3u;
    uint8_t *pool = malloc(capacity);
    assert(pool);
    struct vcam_pipeline *p = vcam_create(pool, capacity, NULL);
    assert(p);
    optical_frame_config config = {{4, 1, 0.0025, 100},
                                    VCAM_MAX_STILL_WIDTH, 2, VCAM_MAX_STILL_WIDTH * 3u};
    uint8_t data[1024], extra[256];
    struct video_engine_packet packet;
    const struct vcam_record_buffers buffers = {data, sizeof(data), &packet, 1,
                                                extra, sizeof(extra)};
    assert(vcam_configure(p, &config) == VCAM_OK);
    assert(vcam_record_begin(p, 25, &buffers) == VCAM_VIDEO);
    config.width = 2;
    config.height = VCAM_MAX_STILL_HEIGHT;
    config.stride = 6;
    assert(vcam_configure(p, &config) == VCAM_OK);
    assert(vcam_record_begin(p, 25, &buffers) == VCAM_VIDEO);
    ++config.height;
    assert(vcam_configure(p, &config) == VCAM_BOUNDS);
    config.height = 1;
    config.width = VCAM_MAX_STILL_WIDTH + 1u;
    config.stride = config.width * 3u;
    assert(vcam_configure(p, &config) == VCAM_BOUNDS);
    assert(vcam_snapshot(p).counts.rendered == 0);
    assert(vcam_destroy(p) == VCAM_OK);
    free(pool);
}
int main(int argc, char **argv)
{
    av_log_set_level(AV_LOG_ERROR);
    assert(argc >= 2);
    if (!strcmp(argv[1], "geometry")) geometry();
    else if (!strcmp(argv[1], "lifecycle")) lifecycle();
    else if (!strcmp(argv[1], "callbacks")) callbacks();
    else if (!strcmp(argv[1], "af")) af_checks();
    else if (!strcmp(argv[1], "stale")) stale_lease();
    else if (!strcmp(argv[1], "jpeg_cancel")) jpeg_cancel();
    else if (!strcmp(argv[1], "jpeg_errors")) jpeg_errors();
    else if (!strcmp(argv[1], "sink")) sink_failure();
    else if (!strcmp(argv[1], "capacities")) capacities();
    else if (!strcmp(argv[1], "cancel")) cancellation();
    else if (!strcmp(argv[1], "mutation")) mutation();
    else if (!strcmp(argv[1], "mux")) mux_checks();
    else {
        assert(!strcmp(argv[1], "products") && argc == 3);
        const size_t count = (size_t)strtoul(argv[2], NULL, 10);
        assert(count >= 2 && count <= 6);
        products(count);
    }
    assert(fflush(stdout) == 0);
    return 0;
}
