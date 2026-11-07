/* SPDX-License-Identifier: MIT */
/* Private inclusion permits adversarial span/counter/sink tests. Python also
 * compiles the production translation unit separately for the broker library. */
#include "../virtual-camera-pipeline/camera-pipeline.h"
static enum vcam_status test_core_vcam_configure(struct vcam_pipeline *, const optical_frame_config *);
static optical_frame_status test_core_optical_configure(optical_frame_owner *, const optical_frame_config *);
#define vcam_configure test_core_vcam_configure
#define optical_frame_configure test_core_optical_configure
#include "functional-camera-core.c"
#undef vcam_configure
#undef optical_frame_configure
#include <assert.h>
#include <inttypes.h>
#include <libavutil/log.h>
#include <sys/wait.h>

#define TEST_WIDTH 128u
#define TEST_HEIGHT 64u
#define TEST_FPS 25u

static int crank_configure_failure;
static unsigned crank_vcam_configures, crank_optical_configures;
static enum vcam_status test_core_vcam_configure(struct vcam_pipeline *p, const optical_frame_config *c)
{
    ++crank_vcam_configures;
    return crank_configure_failure == 1 ? VCAM_OPTICAL : vcam_configure(p, c);
}
static optical_frame_status test_core_optical_configure(optical_frame_owner *o, const optical_frame_config *c)
{
    ++crank_optical_configures;
    return crank_configure_failure == 2 ? OPTICAL_FRAME_INVALID : optical_frame_configure(o, c);
}

static void config_wire(uint8_t out[FCAM_CONFIG_BYTES], uint32_t width, uint32_t height,
                         uint64_t focus, uint64_t shutter)
{
    memset(out, 0, FCAM_CONFIG_BYTES);
    put32(out, width); put32(out + 4, height); put32(out + 8, TEST_FPS);
    put32(out + 12, 90); put32(out + 16, 400); put32(out + 20, 100);
    put64(out + 24, shutter); put64(out + 32, focus);
}
static void still_wire(uint8_t out[144], uint32_t flags, uint32_t width,
                        uint32_t height, uint32_t quality)
{
    memset(out, 0, 144);
    put32(out, flags); put32(out + 4, width); put32(out + 8, height);
    put32(out + 12, quality);
    for (size_t t = 0; t < 2; ++t)
        for (size_t z = 0; z < 64; ++z) out[16 + t * 64 + z] = (uint8_t)(3 + t + z % 13);
}
static void snapshot(struct fcam_model *m, uint8_t out[FCAM_STATE_BYTES])
{
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_STATE, NULL, 0, out, FCAM_STATE_BYTES, &result) == 0);
    assert(!result.token && !result.total && !result.offset && result.used == FCAM_STATE_BYTES);
}
static void state_request(struct fcam_model *m, uint32_t op, const uint8_t *in, size_t size)
{
    uint8_t out[FCAM_STATE_BYTES];
    struct fcam_exec_result result;
    assert(fcam_model_request(m, op, in, size, out, sizeof(out), &result) == 0);
    assert(result.used == sizeof(out) && !result.token && !result.total && !result.offset);
}
static void expect_error(struct fcam_model *m, uint32_t op, const uint8_t *in,
                          size_t size, size_t capacity, int expected)
{
    uint8_t out[FCAM_DATA_BYTES], before[FCAM_STATE_BYTES], after[FCAM_STATE_BYTES];
    struct fcam_exec_result result;
    unsigned char old_result[sizeof(result)];
    memset(out, 0xa7, sizeof(out));
    memset(&result, 0x59, sizeof(result));
    memcpy(old_result, &result, sizeof(result));
    snapshot(m, before);
    assert(fcam_model_request(m, op, in, size, out, capacity, &result) == expected);
    for (size_t i = 0; i < sizeof(out); ++i) assert(out[i] == 0xa7);
    assert(!memcmp(old_result, &result, sizeof(result)));
    snapshot(m, after);
    assert(!memcmp(before, after, sizeof(before)));
}
static struct fcam_model *new_model(void)
{
    struct fcam_model *m = fcam_model_create(UINT64_C(0x1234567812345678));
    assert(m);
    state_request(m, FCAM_OP_INIT, NULL, 0);
    assert(m->sensor_initialized && m->rendered == 1 && m->frame_generation == 1 &&
           !m->consumed && !m->jpeg_encoded && !m->video_encoded);
    return m;
}
static void setup(struct fcam_model *m, uint32_t width, uint32_t height,
                    uint64_t focus, uint64_t shutter)
{
    uint8_t config[FCAM_CONFIG_BYTES];
    config_wire(config, width, height, focus, shutter);
    state_request(m, FCAM_OP_CONFIGURE, config, sizeof(config));
}
static void release(struct fcam_model *m, uint64_t token, const uint8_t *data, size_t size)
{
    uint8_t request[16];
    struct fcam_exec_result result = {1, 2, 3, 4};
    put64(request, token); put64(request + 8, fnv(data, size));
    assert(fcam_model_request(m, FCAM_OP_RELEASE_RESULT, request, sizeof(request), NULL, 0, &result) == 0);
    assert(!result.token && !result.total && !result.offset && !result.used);
}
static uint8_t *collect(struct fcam_model *m, uint32_t op, const uint8_t *in,
                         size_t in_size, size_t chunk, size_t *size)
{
    uint8_t out[FCAM_DATA_BYTES], read_request[24] = {0};
    struct fcam_exec_result result;
    assert(chunk && chunk <= sizeof(out));
    assert(fcam_model_request(m, op, in, in_size, out, chunk, &result) == 0);
    assert(result.token && result.total && result.total <= FCAM_MAX_RESULT_BYTES &&
           !result.offset && result.used && result.used <= chunk);
    const uint64_t token = result.token, total = result.total;
    uint8_t *data = malloc((size_t)total);
    assert(data);
    memcpy(data, out, result.used);
    size_t cursor = result.used;
    while (cursor < total) {
        put64(read_request, token); put64(read_request + 8, cursor);
        put32(read_request + 16, (uint32_t)chunk);
        memset(out, 0xcc, sizeof(out));
        assert(fcam_model_request(m, FCAM_OP_READ_RESULT, read_request, sizeof(read_request),
                                  out, chunk, &result) == 0);
        assert(result.token == token && result.total == total && result.offset == cursor &&
               result.used && result.used <= chunk && result.used <= total - cursor);
        memcpy(data + cursor, out, result.used);
        cursor += result.used;
    }
    release(m, token, data, (size_t)total);
    *size = (size_t)total;
    return data;
}
static void blob(const char *kind, const uint8_t *data, size_t size)
{
    assert(printf("BLOB %s %zu\n", kind, size) > 0);
    assert(fwrite(data, 1, size, stdout) == size);
}
static void init_checks(void)
{
    struct fcam_model *m = fcam_model_create(9);
    assert(m && !m->rendered && !m->sensor_initialized);
    uint8_t config[48];
    config_wire(config, 64, 32, 4000000, 5000);
    expect_error(m, FCAM_OP_INIT, config, sizeof(config), 127, -ENOSPC);
    m->frame_generation = UINT64_MAX;
    expect_error(m, FCAM_OP_INIT, config, sizeof(config), 128, -EOVERFLOW);
    assert(m->generation == 1 && m->config.width == FCAM_DEFAULT_WIDTH);
    m->frame_generation = 0;
    state_request(m, FCAM_OP_INIT, config, sizeof(config));
    assert(m->sensor_initialized && m->rendered == 1 && m->frame_generation == 1 &&
           !m->consumed && !m->jpeg_encoded && !m->video_encoded);
    assert(m->config.width == 64 && m->config.height == 32 && m->generation == 2);
    assert(m->owner.info.config.width == 64 && m->owner.info.config.height == 32 &&
           m->owner.info.counts.rendered == 1 && m->owner.info.counts.retired == 1 &&
           !m->owner.info.counts.read);
    state_request(m, FCAM_OP_INIT, NULL, 0);
    assert(m->rendered == 1 && m->generation == 2);
    fcam_model_destroy(m);
}
static void contracts(void)
{
    init_checks();
    errno = 0;
    assert(!fcam_model_create(0) && errno == EINVAL);
    fcam_model_destroy(NULL);
    struct fcam_model *m = new_model();
    uint8_t state_bytes[FCAM_STATE_BYTES], config[FCAM_CONFIG_BYTES], still[144], af[FCAM_AF_BYTES] = {0};
    snapshot(m, state_bytes);
    assert(get32(state_bytes) == FCAM_ABI_VERSION);
    assert((get32(state_bytes + FCAM_S_CAPS) & ~FCAM_CAPABILITIES) == 0);
    assert(get32(state_bytes + FCAM_S_CAPS) == FCAM_CAPABILITIES);
    assert(get32(state_bytes + FCAM_S_WIDTH) == FCAM_DEFAULT_WIDTH);
    assert(get32(state_bytes + FCAM_S_HEIGHT) == FCAM_DEFAULT_HEIGHT);
    assert(get32(state_bytes + FCAM_S_FPS) == FCAM_DEFAULT_FPS);
    assert(get32(state_bytes + FCAM_S_FNUMBER) == 400);
    assert(get32(state_bytes + FCAM_S_ISO) == 100);
    assert(get64(state_bytes + FCAM_S_SHUTTER) == 16667);
    assert(get64(state_bytes + FCAM_S_FOCUS) == 3000000);
    assert(get64(state_bytes + FCAM_S_GENERATION) == 1);
    assert(get64(state_bytes + FCAM_S_INSTANCE) == UINT64_C(0x1234567812345678));
    assert(get64(state_bytes + FCAM_S_RENDERED) == 1);
    assert(!get64(state_bytes + FCAM_S_CONSUMED) && !get64(state_bytes + FCAM_S_JPEG_ENCODED) &&
           !get64(state_bytes + FCAM_S_VIDEO_ENCODED));
    assert(m->owner.info.counts.retired == 1 && !m->owner.info.counts.read);
    for (size_t i = 120; i < 128; ++i) assert(!state_bytes[i]);
    state_request(m, FCAM_OP_INIT, NULL, 0);
    assert(m->rendered == 1 && m->frame_generation == 1 && m->generation == 1);
    expect_error(m, FCAM_OP_STATE, NULL, 0, 127, -ENOSPC);
    expect_error(m, FCAM_OP_STATE, state_bytes, 1, 128, -EINVAL);
    expect_error(m, 0, NULL, 0, 128, -ENOTSUP);
    expect_error(m, FCAM_OP_VIDEO_FRAME, NULL, 0, 128, -EPIPE);
    expect_error(m, FCAM_OP_VIDEO_END, NULL, 0, 128, -EPIPE);
    expect_error(m, FCAM_OP_READ_RESULT, af, 24, 128, -EINVAL);
    config_wire(config, TEST_WIDTH, TEST_HEIGHT, 1000000, 2500);
    expect_error(m, FCAM_OP_CONFIGURE, config, 47, 128, -EINVAL);
    config[44] = 1;
    expect_error(m, FCAM_OP_CONFIGURE, config, 48, 128, -EINVAL);
    config[44] = 0; put32(config + 40, 1);
    expect_error(m, FCAM_OP_CONFIGURE, config, 48, 128, -EINVAL);
    put32(config + 40, 0); put32(config + 16, 500);
    expect_error(m, FCAM_OP_CONFIGURE, config, 48, 128, -ERANGE);
    put32(config + 16, 400); put64(config + 32, 99999);
    expect_error(m, FCAM_OP_CONFIGURE, config, 48, 128, -ERANGE);
    put64(config + 32, UINT64_MAX);
    state_request(m, FCAM_OP_INIT, config, 48);
    snapshot(m, state_bytes);
    assert(get64(state_bytes + FCAM_S_FOCUS) == UINT64_MAX);
    setup(m, TEST_WIDTH, TEST_HEIGHT, 1000000, 2500);
    const uint64_t generation = m->generation;
    m->generation = UINT64_MAX;
    expect_error(m, FCAM_OP_CONFIGURE, config, 48, 128, -EOVERFLOW);
    m->generation = generation;
    config_wire(config, 1922, 16, 1000000, 2500);
    expect_error(m, FCAM_OP_VIDEO_BEGIN, config, 48, 128, -ERANGE);
    config_wire(config, 128, 63, 1000000, 2500);
    expect_error(m, FCAM_OP_VIDEO_BEGIN, config, 48, 128, -ERANGE);
    config_wire(config, 128, 64, 1000000, 2500);
    put32(config + 8, 121);
    expect_error(m, FCAM_OP_VIDEO_BEGIN, config, 48, 128, -ERANGE);
    still_wire(still, 3, TEST_WIDTH, TEST_HEIGHT, 90);
    expect_error(m, FCAM_OP_STILL, still, 16, 128, -EINVAL);
    still_wire(still, FCAM_STILL_FULL_JPEG, 8193, 1, 90);
    expect_error(m, FCAM_OP_STILL, still, 16, 128, -ERANGE);
    still_wire(still, FCAM_STILL_FULL_JPEG, 128, 64, 0);
    expect_error(m, FCAM_OP_STILL, still, 16, 128, -ERANGE);
    still_wire(still, FCAM_STILL_FULL_JPEG | FCAM_STILL_HAS_QUANT, 128, 64, 90);
    expect_error(m, FCAM_OP_STILL, still, 16, 128, -EINVAL);
    still[22] = 0;
    expect_error(m, FCAM_OP_STILL, still, 144, 128, -EINVAL);
    expect_error(m, FCAM_OP_AUTOFOCUS, af, sizeof(af), 32, -EINVAL);
    uint8_t out[128], oversized[FCAM_DATA_BYTES + 1u];
    struct fcam_exec_result result, old_result;
    memset(out, 0x55, sizeof(out));
    memset(&result, 0x66, sizeof(result));
    memcpy(&old_result, &result, sizeof(result));
    assert(fcam_model_request(m, FCAM_OP_STATE, out, 1, out, sizeof(out), &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_STATE, NULL, 0, m->pool, 128, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_STATE, (const uint8_t *)&m->owner, 32,
                              out, sizeof(out), &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_STATE, NULL, 0, out, sizeof(out),
                              (struct fcam_exec_result *)(void *)m) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_STATE, NULL, 0, (uint8_t *)&result,
                              sizeof(result), &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_STATE, (const uint8_t *)(UINTPTR_MAX - 3u), 8,
                              out, sizeof(out), &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_STATE, NULL, 0, (uint8_t *)(UINTPTR_MAX - 3u),
                              8, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_STATE, NULL, 0, oversized,
                              sizeof(oversized), &result) == -E2BIG);
    assert(fcam_model_request(m, FCAM_OP_STATE, NULL, 0, NULL, 128, &result) == -EINVAL);
    assert(fcam_model_request(NULL, FCAM_OP_STATE, NULL, 0, out, sizeof(out), &result) == -EINVAL);
    assert(!memcmp(&result, &old_result, sizeof(result)));
    for (size_t i = 0; i < sizeof(out); ++i) assert(out[i] == 0x55);
    fcam_model_destroy(m);
}
static void chunks(size_t chunk)
{
    struct fcam_model *m = new_model();
    setup(m, TEST_WIDTH, TEST_HEIGHT, 1000000, 2500);
    uint8_t still[144], out[FCAM_DATA_BYTES], request[24] = {0}, config[FCAM_CONFIG_BYTES];
    struct fcam_exec_result result;
    still_wire(still, FCAM_STILL_FULL_JPEG, TEST_WIDTH, TEST_HEIGHT, 90);
    assert(fcam_model_request(m, FCAM_OP_STILL, still, 16, out, 1, &result) == 0);
    const uint64_t token = result.token;
    const size_t total = (size_t)result.total;
    uint8_t *data = malloc(total);
    assert(data && token && total > 1 && result.used == 1 && !result.offset);
    data[0] = out[0];
    memset(still, 0xff, sizeof(still)); /* No caller input survives the request. */
    config_wire(config, 128, 64, 1000000, 2500);
    expect_error(m, FCAM_OP_CONFIGURE, config, 48, 128, -EBUSY);
    expect_error(m, FCAM_OP_INIT, NULL, 0, 128, -EBUSY);
    expect_error(m, FCAM_OP_STILL, still, 16, 128, -EBUSY);
    put64(request, token); put64(request + 8, fnv(data, 1));
    expect_error(m, FCAM_OP_RELEASE_RESULT, request, 16, 128, -EBUSY);
    put64(request, token + 1); put64(request + 8, 1); put32(request + 16, 1);
    expect_error(m, FCAM_OP_READ_RESULT, request, 24, 128, -ESTALE);
    put64(request, token); put64(request + 8, 0);
    expect_error(m, FCAM_OP_READ_RESULT, request, 24, 128, -ESPIPE);
    put64(request + 8, 1); put32(request + 16, 129);
    expect_error(m, FCAM_OP_READ_RESULT, request, 24, 128, -ENOSPC);
    put32(request + 16, 1); put32(request + 20, 1);
    expect_error(m, FCAM_OP_READ_RESULT, request, 24, 128, -EINVAL);
    put32(request + 20, 0);
    for (size_t cursor = 1; cursor < total; ) {
        put64(request + 8, cursor); put32(request + 16, (uint32_t)chunk);
        assert(fcam_model_request(m, FCAM_OP_READ_RESULT, request, 24, out, chunk, &result) == 0);
        assert(result.token == token && result.total == total && result.offset == cursor &&
               result.used && result.used <= chunk && result.used <= total - cursor);
        memcpy(data + cursor, out, result.used);
        cursor += result.used;
    }
    put64(request + 8, total); put32(request + 16, 1);
    expect_error(m, FCAM_OP_READ_RESULT, request, 24, 128, -ENODATA);
    put64(request + 8, fnv(data, total) ^ 1u);
    expect_error(m, FCAM_OP_RELEASE_RESULT, request, 16, 128, -EBADMSG);
    release(m, token, data, total);
    expect_error(m, FCAM_OP_RELEASE_RESULT, request, 16, 128, -ESTALE);
    uint8_t bytes[128];
    snapshot(m, bytes);
    assert(get64(bytes + FCAM_S_RESULT_READ) == total && !get32(bytes + FCAM_S_PENDING_RESULTS));
    assert(get64(bytes + FCAM_S_RENDERED) == 2 && get64(bytes + FCAM_S_CONSUMED) == 1);
    assert(get64(bytes + FCAM_S_JPEG_ENCODED) == 1);
    blob("JPEG", data, total);
    free(data);
    still_wire(still, FCAM_STILL_SCAN_ONLY, 128, 64, 90);
    assert(fcam_model_request(m, FCAM_OP_STILL, still, 16, out, 1, &result) == 0);
    assert(result.token > token);
    const uint64_t cancelled = result.token;
    const uint64_t generation = m->generation;
    state_request(m, FCAM_OP_CANCEL, NULL, 0);
    assert(m->generation == generation && m->rendered == 3 && m->jpeg_encoded == 2);
    put64(request, cancelled); put64(request + 8, 1); put32(request + 16, 1);
    expect_error(m, FCAM_OP_READ_RESULT, request, 24, 128, -ESTALE);
    fcam_model_destroy(m);
}
static struct fcam_frame_proof frame_proof(struct fcam_model *m)
{
    struct fcam_frame_proof proof;
    assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0);
    assert(proof.version == FCAM_PROOF_VERSION && proof.struct_bytes == sizeof(proof));
    assert(proof.model_instance == m->instance && proof.model_lifetime == m->lifetime &&
           proof.owner_pid == (uint64_t)getpid());
    return proof;
}
static void same_proof(struct fcam_model *m, const struct fcam_frame_proof *expected)
{
    const struct fcam_frame_proof proof = frame_proof(m);
    assert(!memcmp(&proof, expected, sizeof(proof)));
}
static void consumed_proof(struct fcam_model *m, const struct fcam_frame_proof *p)
{
    assert(p->render_observed == 1 && p->consumer_entered == 1 && p->consumer_returned == 1 &&
           p->encoder_consumed == 1 && p->retired == 1);
    assert(p->source_state == OPTICAL_FRAME_RENDERED && p->consumer_before_state == OPTICAL_FRAME_READING &&
           p->consumer_after_state == OPTICAL_FRAME_READING && p->final_state == OPTICAL_FRAME_IDLE);
    assert(p->source_fnv1a64 == p->consumer_before_fnv1a64 &&
           p->source_fnv1a64 == p->consumer_after_fnv1a64 &&
           p->source_fnv1a64 == active_hash(m->pool, (size_t)p->width, (size_t)p->height, (size_t)p->stride));
    assert(p->active_bytes == p->width * p->height * 3 && p->stride >= p->width * 3 && p->lease_generation);
    assert(p->after.rendered == p->before.rendered + 1 && p->after.consumed == p->before.consumed + 1 &&
           p->after.retired == p->before.retired + 1);
    assert(p->render_status == OPTICAL_FRAME_OK && p->retire_status == OPTICAL_FRAME_OK);
}
static void proof_checks(void)
{
    struct fcam_model *m = fcam_model_create(77);
    assert(m);
    struct fcam_frame_proof p = frame_proof(m), untouched;
    assert(!p.serial && !p.render_observed && !p.consumer_entered && !p.result_token);
    memset(&untouched, 0xa5, sizeof(untouched));
    p = untouched;
    assert(fcam_model_proof_snapshot(NULL, &p, sizeof(p)) == -EINVAL);
    assert(fcam_model_proof_snapshot(m, NULL, sizeof(p)) == -EINVAL);
    assert(fcam_model_proof_snapshot(m, &p, sizeof(p) - 1) == -EINVAL);
    assert(fcam_model_proof_snapshot(m, (struct fcam_frame_proof *)(void *)m->pool, sizeof(p)) == -EINVAL);
    assert(fcam_model_proof_snapshot(m, &m->proof, sizeof(p)) == -EINVAL);
    m->busy = 1;
    assert(fcam_model_proof_snapshot(m, &p, sizeof(p)) == -EBUSY);
    m->busy = 0;
    ++m->owner_pid;
    assert(fcam_model_proof_snapshot(m, &p, sizeof(p)) == -ECHILD);
    --m->owner_pid;
    assert(!memcmp(&p, &untouched, sizeof(p)));
    uint8_t config[48], out[FCAM_DATA_BYTES], request[24] = {0}, still[144];
    struct fcam_exec_result result;
    config_wire(config, 64, 32, 1000000, 2500);
    put32(config + 12, 0);
    expect_error(m, FCAM_OP_INIT, config, sizeof(config), 128, -ERANGE);
    assert(!frame_proof(m).serial && !m->sensor_initialized);
    put32(config + 12, 90);
    state_request(m, FCAM_OP_INIT, config, sizeof(config));
    p = frame_proof(m);
    assert(p.serial == 1 && p.opcode == FCAM_OP_INIT && p.consumer_kind == FCAM_PROOF_PROBE &&
           p.config_generation == 2 && p.frame_generation == 1 && p.width == 640 && p.height == 480 &&
           p.stride == 1920 && p.active_bytes == 640u * 480u * 3u && p.render_observed && p.retired);
    assert(p.source_fnv1a64 == fnv(m->pool, (size_t)p.active_bytes) && !p.consumer_entered &&
           !p.consumer_returned && !p.encoder_consumed && p.consumer_status == -ENODATA);
    assert(!p.encoded_bytes && p.encoded_fnv1a64 == FNV_OFFSET && !p.result_bytes && !p.result_token);
    assert(!p.before.rendered && p.after.rendered == 1 && p.after.retired == 1 &&
           !p.after.consumed && !p.after.jpeg_encoded && !p.after.video_encoded);
    state_request(m, FCAM_OP_STATE, NULL, 0);
    state_request(m, FCAM_OP_INIT, NULL, 0);
    setup(m, 128, 64, 1000000, 2500);
    same_proof(m, &p);
    still_wire(still, FCAM_STILL_FULL_JPEG, 128, 64, 90);
    assert(fcam_model_request(m, FCAM_OP_STILL, still, 16, out, 37, &result) == 0);
    const uint64_t token = result.token, total = result.total;
    p = frame_proof(m);
    consumed_proof(m, &p);
    assert(p.serial == 2 && p.consumer_kind == FCAM_PROOF_JPEG && p.frame_generation == 2 &&
           p.config_generation == m->generation && p.consumer_status == VJPEG_OK && !p.operation_status);
    assert(p.after.jpeg_encoded == p.before.jpeg_encoded + 1 && p.after.video_encoded == p.before.video_encoded);
    assert(p.result_bytes == total && p.result_token == token && p.result_fnv1a64 == fnv(m->result_data, (size_t)total));
    assert(p.encoded_bytes == total - VJPEG_PREFIX_SIZE &&
           p.encoded_fnv1a64 == fnv(m->result_data + VJPEG_PREFIX_SIZE, (size_t)p.encoded_bytes));
    while (m->result_cursor < total) {
        put64(request, token); put64(request + 8, m->result_cursor); put32(request + 16, 63);
        assert(fcam_model_request(m, FCAM_OP_READ_RESULT, request, 24, out, 63, &result) == 0);
        same_proof(m, &p);
    }
    release(m, token, m->result_data, (size_t)total);
    same_proof(m, &p);
    config_wire(config, 128, 64, 1000000, 2500);
    state_request(m, FCAM_OP_VIDEO_BEGIN, config, sizeof(config));
    same_proof(m, &p);
    for (size_t i = 0; i < 2; ++i) {
        size_t size;
        uint8_t *packet = collect(m, FCAM_OP_VIDEO_FRAME, NULL, 0, 37, &size);
        p = frame_proof(m);
        consumed_proof(m, &p);
        assert(p.serial == i + 3 && p.consumer_kind == FCAM_PROOF_H264 && p.consumer_status == VIDEO_ENGINE_OK &&
               !p.operation_status && p.frame_generation == i + 3 && p.packet_generation == get64(packet + 56));
        assert(p.after.video_encoded == p.before.video_encoded + 1 && p.after.jpeg_encoded == p.before.jpeg_encoded);
        const size_t prefix = FCAM_PACKET_HEADER_BYTES + get32(packet + 64);
        assert(p.encoded_bytes == get64(packet + 48) && p.encoded_bytes == size - prefix &&
               p.encoded_fnv1a64 == fnv(packet + prefix, size - prefix));
        assert(p.result_bytes == size && p.result_fnv1a64 == fnv(packet, size) && p.result_token);
        free(packet);
    }
    size_t size;
    uint8_t *eos = collect(m, FCAM_OP_VIDEO_END, NULL, 0, 1, &size);
    p = frame_proof(m);
    assert(p.serial == 5 && p.consumer_kind == FCAM_PROOF_DRAIN && p.frame_generation == 4 &&
           !p.render_observed && !p.retired && !p.encoder_consumed && p.consumer_entered && p.consumer_returned &&
           !p.encoded_bytes && p.encoded_fnv1a64 == FNV_OFFSET && !p.width && !p.height);
    assert(!memcmp(&p.before, &p.after, sizeof(p.before)) && !p.operation_status &&
           p.result_bytes == size && p.result_fnv1a64 == fnv(eos, size));
    free(eos);
    state_request(m, FCAM_OP_CANCEL, NULL, 0);
    same_proof(m, &p);
    still_wire(still, FCAM_STILL_SCAN_ONLY, 128, 64, 90);
    assert(fcam_model_request(m, FCAM_OP_STILL, still, 16, out, 1, &result) == 0);
    p = frame_proof(m);
    assert(p.serial == 6 && p.result_bytes == p.encoded_bytes && p.result_fnv1a64 == p.encoded_fnv1a64);
    state_request(m, FCAM_OP_CANCEL, NULL, 0);
    same_proof(m, &p);
    fcam_model_destroy(m);

    /* Same true pipeline/encoder with padded source rows, and a real failed
     * tiny-destination encode. No independent image or counter-only fixture. */
    m = fcam_model_create(78);
    assert(m && stage(m) == 0);
    optical_frame_config optical = optical_config(&defaults);
    optical.width = 128; optical.height = 64; optical.stride = 395;
    memset(m->pool, 0xa5, optical.stride * optical.height);
    assert(vcam_configure(m->still, &optical) == VCAM_OK);
    struct vjpeg_coding coding = {VJPEG_SOURCE_HEADER_422, 128, 64, {{0}}};
    assert(quant_tables(&m->quant, 90, coding.quant_zigzag) == 0);
    struct vcam_still_result captured;
    assert(vcam_capture_still(m->still, &coding, m->result_data, FCAM_MAX_RESULT_BYTES, &captured) == VCAM_OK);
    struct vcam_frame_proof observed = vcam_frame_proof_snapshot(m->still);
    assert(observed.stride == 395 && observed.active_bytes == 128u * 64u * 3u &&
           observed.consumer_entered && observed.consumer_returned && observed.retired &&
           observed.source_fnv1a64 == observed.consumer_before_fnv1a64 &&
           observed.source_fnv1a64 == observed.consumer_after_fnv1a64 &&
           observed.source_fnv1a64 == active_hash(m->pool, 128, 64, 395));
    for (size_t y = 0; y < 64; ++y)
        for (size_t x = 384; x < 395; ++x) {
            assert(m->pool[y * 395 + x] == 0xa5);
            m->pool[y * 395 + x] = 0x6d;
        }
    assert(observed.source_fnv1a64 == active_hash(m->pool, 128, 64, 395));
    memset(&captured, 0x59, sizeof(captured));
    const struct vcam_still_result old = captured;
    assert(vcam_capture_still(m->still, &coding, m->result_data, VJPEG_PREFIX_SIZE + 1, &captured) == VCAM_JPEG);
    assert(!memcmp(&captured, &old, sizeof(old)));
    observed = vcam_frame_proof_snapshot(m->still);
    assert(observed.serial == 2 && observed.render_observed && observed.consumer_entered && observed.consumer_returned &&
           observed.encoder_consumed && observed.consumer_status != VJPEG_OK && observed.retired &&
           observed.retire_status == OPTICAL_FRAME_OK && !observed.encoded_bytes &&
           observed.source_fnv1a64 == observed.consumer_before_fnv1a64 &&
           observed.source_fnv1a64 == observed.consumer_after_fnv1a64);
    assert(observed.after.rendered == observed.before.rendered + 1 &&
           observed.after.encoder_consumed == observed.before.encoder_consumed + 1 &&
           observed.after.retired == observed.before.retired + 1 &&
           observed.after.output_readback == observed.before.output_readback);
    fcam_model_destroy(m);
}
static void codec_fault(void)
{
    struct fcam_model *m = new_model();
    uint8_t config[48], out[128];
    config_wire(config, 128, 64, 1000000, 2500);
    state_request(m, FCAM_OP_VIDEO_BEGIN, config, 48);
    expect_error(m, FCAM_OP_CONFIGURE, config, 48, 128, -EBUSY);
    expect_error(m, FCAM_OP_AUTOFOCUS, config, 32, 32, -EBUSY);
    assert(stage(m) == 0);
    proof_begin(m, FCAM_OP_VIDEO_FRAME);
    m->result_size = FCAM_MAX_RESULT_BYTES - 1u; /* Force a real encoder sink bound fault. */
    assert(video_frame(m, 0) == -EIO);
    m->result_size = 0; /* Fault injection's unused capacity is not produced bytes. */
    proof_finish(m, -EIO);
    const struct fcam_frame_proof failed = frame_proof(m);
    consumed_proof(m, &failed);
    assert(failed.operation_status == -EIO && failed.consumer_status == VIDEO_ENGINE_SINK_ERROR &&
           failed.encoded_bytes > 0 && !failed.result_token && !failed.result_bytes &&
           failed.after.video_encoded == failed.before.video_encoded + 1);
    assert(m->stream_state == 3 && !m->token && m->rendered == 2 && m->consumed == 1 &&
           m->video_encoded == 1);
    const struct video_engine_stream_info info = video_engine_stream_snapshot(m->video);
    assert(info.state == VIDEO_ENGINE_STREAM_FAULT && info.frames_consumed == 1 &&
           info.packets_received == 1 && !info.packets_published && info.sink_error == -E2BIG);
    optical_frame_info optical;
    assert(optical_frame_snapshot(&m->owner, &optical) == OPTICAL_FRAME_OK);
    assert(optical.state == OPTICAL_FRAME_IDLE && optical.counts.retired == 2);
    discard(m);
    expect_error(m, FCAM_OP_VIDEO_FRAME, NULL, 0, 128, -EIO);
    state_request(m, FCAM_OP_CANCEL, NULL, 0);
    uint8_t still[144], chunk[FCAM_DATA_BYTES], ack[16];
    struct fcam_exec_result result;
    still_wire(still, FCAM_STILL_FULL_JPEG, 128, 64, 90);
    assert(fcam_model_request(m, FCAM_OP_STILL, still, 16, chunk, sizeof(chunk), &result) == 0);
    assert(result.used == result.total && result.token);
    put64(ack, result.token); put64(ack + 8, fnv(chunk, result.used));
    m->result_data[0] ^= 1u;
    struct fcam_exec_result old_result;
    memset(&result, 0x59, sizeof(result));
    memcpy(&old_result, &result, sizeof(result));
    assert(fcam_model_request(m, FCAM_OP_RELEASE_RESULT, ack, sizeof(ack), NULL, 0, &result) == -EIO);
    assert(!memcmp(&old_result, &result, sizeof(result)) && m->stream_state == 3 && m->token);
    state_request(m, FCAM_OP_CANCEL, NULL, 0);
    snapshot(m, out);
    assert(!get32(out + FCAM_S_STREAM_STATE) && get64(out + FCAM_S_VIDEO_ENCODED) == 1);
    /* Source generation/hash guards remain those of the real owner. */
    optical_frame_lease lease;
    assert(optical_frame_acquire(&m->owner, m->pool, FRAME_CAPACITY, &lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_render(&m->owner, &lease) == OPTICAL_FRAME_OK);
    memset(&result, 0x59, sizeof(result));
    memcpy(&old_result, &result, sizeof(result));
    memset(out, 0xa7, sizeof(out));
    assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, sizeof(out), &result) == -EIO);
    assert(m->stream_state == 3 && !memcmp(&old_result, &result, sizeof(result)));
    for (size_t i = 0; i < sizeof(out); ++i) assert(out[i] == 0xa7);
    optical_frame_lease stale = lease;
    --stale.generation;
    assert(optical_frame_retire(&m->owner, &stale) == OPTICAL_FRAME_STALE);
    m->pool[0] ^= 1u;
    assert(optical_frame_consumer_read(&m->owner, &lease, consume_frame, m) == OPTICAL_FRAME_CHANGED);
    m->pool[0] ^= 1u;
    assert(optical_frame_retire(&m->owner, &lease) == OPTICAL_FRAME_OK);
    state_request(m, FCAM_OP_CANCEL, NULL, 0);
    fcam_model_destroy(m);
}
static void streaming(size_t count)
{
    struct fcam_model *m = new_model();
    uint8_t config[48], state_bytes[128];
    config_wire(config, 16, 16, 1000000, 2500);
    state_request(m, FCAM_OP_VIDEO_BEGIN, config, 48);
    uint64_t last_token = 0;
    for (size_t i = 0; i < count; ++i) {
        size_t size;
        uint8_t *packet = collect(m, FCAM_OP_VIDEO_FRAME, NULL, 0, FCAM_DATA_BYTES, &size);
        assert(size > FCAM_PACKET_HEADER_BYTES && get64(packet + 8) == i &&
               get64(packet + 16) == i && get64(packet + 24) == 1 &&
               get32(packet + 32) == 1 && get32(packet + 36) == TEST_FPS &&
               get64(packet + 56) == i + 2 && !get32(packet + 44));
        assert(m->next_token > last_token);
        last_token = m->next_token;
        free(packet);
    }
    size_t size;
    uint8_t *eos = collect(m, FCAM_OP_VIDEO_END, NULL, 0, 1, &size);
    assert(size == FCAM_PACKET_HEADER_BYTES && get32(eos + 44) == FCAM_PACKET_EOS &&
           !get64(eos + 48) && !get32(eos + 64));
    free(eos);
    snapshot(m, state_bytes);
    assert(get32(state_bytes + FCAM_S_STREAM_STATE) == 2 &&
           get64(state_bytes + FCAM_S_RENDERED) == count + 1 &&
           get64(state_bytes + FCAM_S_CONSUMED) == count &&
           get64(state_bytes + FCAM_S_VIDEO_ENCODED) == count);
    expect_error(m, FCAM_OP_VIDEO_END, NULL, 0, 128, -EPIPE);
    fcam_model_destroy(m);
}
static void products(size_t count)
{
    struct fcam_model *m = new_model();
    uint8_t still[144], config[48], af[32] = {0}, af_result[32];
    uint8_t bytes[128];
    struct fcam_exec_result result;
    for (size_t variant = 0; variant < 2; ++variant) {
        setup(m, TEST_WIDTH, TEST_HEIGHT, 2000000, variant ? 3300 : 2500);
        put32(af, variant ? TEST_WIDTH / 2 + 4 : 4); put32(af + 4, 4);
        put32(af + 8, TEST_WIDTH / 2 - 8); put32(af + 12, TEST_HEIGHT - 8);
        put64(af + 16, 500000); put64(af + 24, 8000000);
        const uint64_t before = m->generation;
        assert(fcam_model_request(m, FCAM_OP_AUTOFOCUS, af, 32, af_result, 32, &result) == 0);
        assert(result.used == 32 && !result.token && !result.total && !result.offset);
        assert(m->generation == before + 1 && get32(af_result + 16) == 17 &&
               get32(af_result + 20) > 0 && get32(af_result + 20) <= 12 && get64(af_result + 8));
        blob("AF", af_result, 32);
        snapshot(m, bytes);
        assert(get64(bytes + FCAM_S_FOCUS) == get64(af_result));
        const uint32_t flags = FCAM_STILL_FULL_JPEG | (variant ? FCAM_STILL_HAS_QUANT : 0);
        still_wire(still, flags, TEST_WIDTH, TEST_HEIGHT, variant ? 92 : 80);
        size_t size;
        uint8_t *full = collect(m, FCAM_OP_STILL, still, variant ? 144 : 16, 63, &size);
        blob("JPEG", full, size);
        blob("STILL_RGB", m->pool, (size_t)TEST_WIDTH * TEST_HEIGHT * 3u);
        put32(still, (flags & ~3u) | FCAM_STILL_SCAN_ONLY);
        size_t scan_size;
        uint8_t *scan = collect(m, FCAM_OP_STILL, still, variant ? 144 : 16, 1, &scan_size);
        assert(size == VJPEG_PREFIX_SIZE + scan_size && !memcmp(full + VJPEG_PREFIX_SIZE, scan, scan_size));
        blob("SCAN", scan, scan_size);
        free(full); free(scan);
    }
    /* Real still encode beyond the video ceiling, without rendering 14M pixels. */
    still_wire(still, FCAM_STILL_FULL_JPEG, 2048, 16, 85);
    size_t size;
    uint8_t *wide = collect(m, FCAM_OP_STILL, still, 16, FCAM_DATA_BYTES, &size);
    blob("WIDE", wide, size);
    free(wide);
    config_wire(config, TEST_WIDTH, TEST_HEIGHT, 1000000, 2500);
    state_request(m, FCAM_OP_VIDEO_BEGIN, config, 48);
    for (size_t i = 0; i < count; ++i) {
        uint8_t *packet = collect(m, FCAM_OP_VIDEO_FRAME, NULL, 0, i % 2 ? 63 : FCAM_DATA_BYTES, &size);
        assert(get64(packet + 8) == i && get64(packet + 16) == i && get64(packet + 24) == 1);
        blob("PACKET", packet, size);
        blob("VIDEO_RGB", m->pool, (size_t)TEST_WIDTH * TEST_HEIGHT * 3u);
        free(packet);
    }
    uint8_t *eos = collect(m, FCAM_OP_VIDEO_END, NULL, 0, 63, &size);
    blob("EOS", eos, size);
    free(eos);
    snapshot(m, bytes);
    blob("STATE", bytes, sizeof(bytes));
    assert(m->rendered == count + 6 && m->consumed == count + 5 && m->jpeg_encoded == 5 &&
           m->video_encoded == count && m->frame_generation == count + 6);
    fcam_model_destroy(m);
}
static void forced_idr(void)
{
    struct fcam_model *m = new_model();
    uint8_t config[48], flags[8] = {1};
    expect_error(m, FCAM_OP_VIDEO_FRAME, flags, 4, 128, -EPIPE);
    config_wire(config, 128, 64, 1000000, 2500);
    state_request(m, FCAM_OP_VIDEO_BEGIN, config, 48);
    expect_error(m, FCAM_OP_VIDEO_FRAME, flags, 3, 128, -EINVAL);
    expect_error(m, FCAM_OP_VIDEO_FRAME, flags, 8, 128, -EINVAL);
    flags[0] = 0;
    expect_error(m, FCAM_OP_VIDEO_FRAME, flags, 4, 128, -EINVAL);
    flags[0] = 2;
    expect_error(m, FCAM_OP_VIDEO_FRAME, flags, 4, 128, -EINVAL);
    flags[0] = 1;
    flags[3] = 1;
    expect_error(m, FCAM_OP_VIDEO_FRAME, flags, 4, 128, -EINVAL);
    flags[3] = 0;
    for (size_t i = 0; i < 3; ++i) {
        size_t size;
        uint8_t *packet = collect(m, FCAM_OP_VIDEO_FRAME, i == 1 ? flags : NULL,
                                  i == 1 ? 4 : 0, 37, &size);
        struct fcam_frame_proof proof = frame_proof(m);
        consumed_proof(m, &proof);
        assert(proof.encoder_consumed == 1 && proof.after.video_encoded == i + 1 &&
               get64(packet + 8) == i && get64(packet + 16) == i);
        blob("PACKET", packet, size);
        blob("VIDEO_RGB", m->pool, 128u * 64u * 3u);
        free(packet);
    }
    size_t size;
    uint8_t *eos = collect(m, FCAM_OP_VIDEO_END, NULL, 0, 1, &size);
    assert(size == FCAM_PACKET_HEADER_BYTES && get32(eos + 44) == FCAM_PACKET_EOS);
    free(eos);
    expect_error(m, FCAM_OP_VIDEO_FRAME, flags, 4, 128, -EPIPE);
    state_request(m, FCAM_OP_CANCEL, NULL, 0);
    fcam_model_destroy(m);
}
static void retained_capture(void)
{
    struct fcam_model *m = new_model();
    uint8_t request[16] = {5, 0, 0x38, 0x40, 0x78, 0x56, 0x34, 0x12, 2};
    expect_error(m, FCAM_OP_FRAME_CAPTURE, request, 16, 128, -ENODATA);
    setup(m, 128, 64, 1000000, 2500);
    request[9] = 1;
    expect_error(m, FCAM_OP_FRAME_CAPTURE, request, 16, 128, -EINVAL);
    request[9] = 0;
    m->capture_owner.info.generation = UINT64_MAX;
    expect_error(m, FCAM_OP_FRAME_CAPTURE, request, 16, 128, -EOVERFLOW);
    m->capture_owner.info.generation = 0;
    const uint64_t retired = m->retired;
    size_t size;
    uint8_t *source = collect(m, FCAM_OP_FRAME_CAPTURE, request, 16, 7, &size);
    assert(size == 96 + 128u * 64u * 3u && get32(source) == 1 && get32(source + 4) == 96);
    assert(get64(source + 8) == m->capture_token && get64(source + 16) == m->instance &&
           get64(source + 24) == m->lifetime && get64(source + 88) == fnv(request, 16));
    assert(get32(source + 80) == UINT32_C(0x12345678) && source[84] == 2 &&
           !memcmp(source + 96, m->capture_rgb, m->capture_bytes));
    assert(m->retired == retired && m->capture_owner.info.state == OPTICAL_FRAME_RENDERED);
    const uint64_t token = m->capture_token, digest = fnv(source + 96, size - 96);
    const uint64_t generation = m->capture_frame_generation;
    const struct fcam_frame_proof captured = frame_proof(m);
    assert(captured.consumer_kind == FCAM_PROOF_FRAME_CAPTURE && captured.render_observed == 1 &&
           captured.encoder_consumed == 0 && captured.retired == 0);
    blob("CAPTURE", source, size);
    expect_error(m, FCAM_OP_FRAME_CAPTURE, request, 16, 128, -EBUSY);
    uint8_t done[16] = {0}, input[160] = {0};
    struct fcam_exec_result result;
    put64(done, token);
    assert(fcam_model_request(m, FCAM_OP_STATE, NULL, 0, m->capture_rgb, 128, &result) == -EINVAL);
    expect_error(m, FCAM_OP_FRAME_RELEASE, done, 16, 0, -EBUSY);
    put32(done + 8, 1);
    expect_error(m, FCAM_OP_FRAME_RELEASE, done, 16, 0, -EBADMSG);
    struct fcam_model *other = new_model();
    setup(other, 128, 64, 1000000, 2500);
    uint8_t *other_source = collect(other, FCAM_OP_FRAME_CAPTURE, request, 16, 128, &size);
    assert(get64(other_source + 8) != token);
    put64(input, token); still_wire(input + 16, FCAM_STILL_FULL_JPEG, 128, 64, 100);
    expect_error(other, FCAM_OP_FRAME_STILL, input, 32, 128, -ESTALE);
    state_request(other, FCAM_OP_CANCEL, NULL, 0);
    free(other_source); fcam_model_destroy(other);
    setup(m, 128, 64, 4000000, 20000);
    uint8_t ordinary[144]; still_wire(ordinary, FCAM_STILL_FULL_JPEG, 128, 64, 100);
    uint8_t *different = collect(m, FCAM_OP_STILL, ordinary, 16, 128, &size);
    free(different);
    assert(fnv(m->pool, 128u * 64u * 3u) != digest);
    blob("OTHER_RGB", m->pool, 128u * 64u * 3u);
    const uint64_t rendered = m->rendered;
    for (unsigned selector = 0; selector < 3; ++selector) {
        const uint32_t flags = selector == 2 ? FCAM_STILL_SCAN_ONLY | FCAM_STILL_HAS_QUANT : FCAM_STILL_FULL_JPEG;
        put32(input + 8, selector);
        still_wire(input + 16, flags, selector ? 64 : 128, selector ? 32 : 64, 100);
        uint8_t *encoded = collect(m, FCAM_OP_FRAME_STILL, input,
                                   selector == 2 ? 160 : 32, 33, &size);
        const struct fcam_frame_proof proof = frame_proof(m);
        assert(proof.consumer_kind == FCAM_PROOF_FRAME_STILL && proof.render_observed == 0 &&
               proof.encoder_consumed == 1 && proof.retired == 0 && proof.operation_status == 0 &&
               proof.frame_generation == generation && proof.source_fnv1a64 == digest &&
               proof.consumer_before_fnv1a64 == digest && proof.consumer_after_fnv1a64 == digest &&
               m->rendered == rendered && m->capture_token == token &&
               m->capture_owner.info.state == OPTICAL_FRAME_RENDERED);
        blob(selector == 0 ? "MAIN" : selector == 1 ? "THM" : "SCAN", encoded, size);
        if (selector == 2) {
            struct vjpeg_coding coding = {VJPEG_SOURCE_HEADER_422, 64, 32, {{0}}};
            memcpy(coding.quant_zigzag, input + 32, 128);
            uint8_t prefix[VJPEG_PREFIX_SIZE]; assert(vjpeg_source_prefix(&coding, prefix) == VJPEG_OK);
            blob("SCAN_PREFIX", prefix, sizeof(prefix));
        }
        free(encoded);
        expect_error(m, FCAM_OP_FRAME_STILL, input, selector == 2 ? 160 : 32, 128, -EALREADY);
    }
    put32(done + 8, 7);
    assert(fcam_model_request(m, FCAM_OP_FRAME_RELEASE, done, 16, NULL, 0, &result) == 0);
    assert(!result.used && !result.token && !m->capture_token && !m->capture_rgb &&
           m->capture_owner.info.state == OPTICAL_FRAME_IDLE);
    expect_error(m, FCAM_OP_FRAME_STILL, input, 160, 128, -ESTALE);
    expect_error(m, FCAM_OP_FRAME_RELEASE, done, 16, 0, -ESTALE);
    free(source);
    source = collect(m, FCAM_OP_FRAME_CAPTURE, request, 16, 128, &size);
    assert(get64(source + 8) != token);
    m->capture_rgb[0] ^= 1;
    put64(input, m->capture_token); put32(input + 8, 0);
    assert(fcam_model_request(m, FCAM_OP_FRAME_STILL, input, 160,
                             input + 159, 1, &result) == -EINVAL);
    uint8_t out[128];
    assert(fcam_model_request(m, FCAM_OP_FRAME_STILL, input, 160, out, sizeof(out), &result) == -EIO);
    assert(m->capture_token && m->stream_state == 3);
    state_request(m, FCAM_OP_CANCEL, NULL, 0);
    assert(!m->capture_token && !m->capture_rgb && !m->stream_state);
    free(source);
    source = collect(m, FCAM_OP_FRAME_CAPTURE, request, 16, 128, &size);
    m->capture_owner.info.state = OPTICAL_FRAME_STAGED;
    state_request(m, FCAM_OP_CANCEL, NULL, 0);
    assert(!m->capture_token && frame_proof(m).source_fnv1a64 == 0);
    free(source); fcam_model_destroy(m);
}
static void parameter_input(uint8_t raw[FCAM_CP_PARAMETER_BANK_BYTES], uint32_t fps, uint32_t cookie)
{
    for (size_t i = 0; i < FCAM_CP_PARAMETER_BANK_BYTES; ++i) raw[i] = (uint8_t)(i * 73u + i / 29u + 19u);
    raw[0] = 5; raw[2] = 0x63; raw[3] = 0x40; put32(raw + 4, cookie);
    for (size_t i = 0; i < CP_PARAMETER_BATCH_SLOTS; ++i) {
        const struct cp_parameter_batch_slot *slot = &cp_parameter_batch_slots[i];
        raw[slot->offset] = 5; raw[slot->offset + 2] = (uint8_t)slot->opcode;
        raw[slot->offset + 3] = (uint8_t)(slot->opcode >> 8);
    }
    put32(raw + FCAM_CP_PARAMETER_FPS_AT, fps);
}
static void parameter_error(struct fcam_model *m, const uint8_t *raw, size_t bytes,
                            size_t capacity, int error)
{
    const struct fcam_model before = *m;
    uint8_t output[FCAM_CP_PARAMETER_BANK_RESULT_BYTES + 8];
    memset(output, 0xa5, sizeof output);
    struct fcam_exec_result result = {1, 2, 3, 4}, previous = result;
    assert(fcam_model_request(m, FCAM_OP_CP_PARAMETER_BANK, raw, bytes, output, capacity, &result) == error);
    assert(!memcmp(m, &before, sizeof before) && !memcmp(&result, &previous, sizeof result));
    for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
}
static void parameter_bank_checks(void)
{
    _Static_assert(FCAM_OP_CP_PARAMETER_BANK == 20u && FCAM_STATE_BYTES == 128u && FCAM_CONFIG_BYTES == 48u,
                   "independent bank opcode preserves original wire layouts");
    struct fcam_model *m = new_model();
    setup(m, 128, 64, UINT64_MAX, 8642);
    uint8_t raw[FCAM_CP_PARAMETER_BANK_BYTES + 1], output[FCAM_CP_PARAMETER_BANK_RESULT_BYTES];
    uint8_t readback[FCAM_CP_PARAMETER_BANK_RESULT_BYTES], before[FCAM_STATE_BYTES], after[FCAM_STATE_BYTES];
    struct fcam_exec_result result;
    memset(readback, 0xa5, sizeof readback);
    assert(fcam_model_cp_parameter_bank_snapshot(m, 1, readback, sizeof readback) == -ENODATA);
    for (size_t i = 0; i < sizeof readback; ++i) assert(readback[i] == 0xa5);
    parameter_input(raw, 60, UINT32_C(0x80000026));
    struct cp_parameter_batch boot;
    assert(cp_parameter_batch_init(&boot, true) == 0);
    assert(cp_parameter_batch_stage(&boot, CP_PARAMETER_BATCH_SOURCE, CP_PARAMETER_BATCH_TARGET,
                                    raw, FCAM_CP_PARAMETER_BANK_BYTES) == CP_PARAMETER_BATCH_STAGED);
    const struct cp_parameter_batch boot_before = boot;
    const struct fcam_frame_proof proof = frame_proof(m);
    for (unsigned repeat = 0; repeat < 3; ++repeat) {
        parameter_input(raw, repeat ? 30 : 60, repeat ? UINT32_C(0x80000061) : UINT32_C(0x80000026));
        raw[FCAM_CP_PARAMETER_BANK_BYTES - 1] ^= (uint8_t)repeat;
        snapshot(m, before);
        assert(fcam_model_request(m, FCAM_OP_CP_PARAMETER_BANK, raw, FCAM_CP_PARAMETER_BANK_BYTES,
                                  output, sizeof output, &result) == 0);
        snapshot(m, after);
        assert(!result.token && !result.total && !result.offset && result.used == sizeof output);
        assert(get32(output) == 1 && get32(output + 4) == sizeof output && get64(output + 8) == m->instance &&
               get64(output + 16) == repeat + 1 && get64(output + 24) == get64(before + 56) &&
               get64(output + 32) == get64(before + 56) + 1 && get64(output + 40) == fnv(raw, FCAM_CP_PARAMETER_BANK_BYTES) &&
               get32(output + 48) == (repeat ? 30u : 60u) && get32(output + 52) == 190 &&
               get32(output + 56) == FCAM_CP_PARAMETER_BANK_BYTES && !get32(output + 60));
        put32(before + FCAM_S_FPS, repeat ? 30 : 60);
        put64(before + FCAM_S_GENERATION, get64(before + FCAM_S_GENERATION) + 1);
        assert(!memcmp(before, after, sizeof after) && !memcmp(output + 64, after, sizeof after));
        assert(!memcmp(output + 192, raw, FCAM_CP_PARAMETER_BANK_BYTES));
        assert(fcam_model_cp_parameter_bank_snapshot(m, repeat + 1, readback, sizeof readback) == 0 &&
               !memcmp(readback, output, sizeof output));
        same_proof(m, &proof);
        assert(!memcmp(&boot, &boot_before, sizeof boot));
    }
    assert(cp_parameter_batch_stage(&boot, CP_PARAMETER_BATCH_SOURCE, CP_PARAMETER_BATCH_TARGET,
                                    raw, FCAM_CP_PARAMETER_BANK_BYTES) == -EBUSY);
    assert(!memcmp(&boot, &boot_before, sizeof boot));
    parameter_error(m, raw, 0, sizeof output, -EINVAL);
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES - 1, sizeof output, -EINVAL);
    parameter_error(m, raw, sizeof raw, sizeof output, -EINVAL);
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output - 1, -ENOSPC);
    for (size_t i = 0; i < CP_PARAMETER_BATCH_SLOTS; ++i) {
        const size_t at = cp_parameter_batch_slots[i].offset;
        raw[at] ^= 1; parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EPROTO); raw[at] ^= 1;
        raw[at + 2] ^= 1; parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EPROTO); raw[at + 2] ^= 1;
    }
    for (size_t i = 0; i <= 2; i += 2) {
        raw[i] ^= 1; parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EPROTO); raw[i] ^= 1;
    }
    put32(raw + FCAM_CP_PARAMETER_FPS_AT, 0);
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -ERANGE);
    put32(raw + FCAM_CP_PARAMETER_FPS_AT, 121);
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -ERANGE);
    put32(raw + FCAM_CP_PARAMETER_FPS_AT, 30);
    const uint64_t generation = m->generation;
    m->generation = UINT64_MAX;
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EOVERFLOW); m->generation = generation;
    m->parameter_bank_generation = UINT64_MAX;
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EOVERFLOW); m->parameter_bank_generation = 3;
    m->busy = 1; parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EBUSY); m->busy = 0;
    m->vdf_busy = 1; parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EBUSY); m->vdf_busy = 0;
    m->owner.info.state = OPTICAL_FRAME_STAGED;
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EBUSY); m->owner.info.state = OPTICAL_FRAME_IDLE;
    m->capture_owner.info.state = OPTICAL_FRAME_RENDERED;
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EBUSY); m->capture_owner.info.state = OPTICAL_FRAME_IDLE;
    for (uint32_t stream = 1; stream <= 3; ++stream) {
        m->stream_state = stream;
        parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, stream == 3 ? -EIO : -EBUSY);
    }
    m->stream_state = 0;
    uint8_t still[144]; still_wire(still, FCAM_STILL_FULL_JPEG, 128, 64, 90);
    assert(fcam_model_request(m, FCAM_OP_STILL, still, 16, after, sizeof after, &result) == 0 && result.token);
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EBUSY);
    state_request(m, FCAM_OP_CANCEL, NULL, 0);
    const uint8_t capture[16] = {5,0,0x38,0x40,0x61,0,0,0x80,2,0,0,0,0x19,0,0,0};
    size_t retained_size;
    uint8_t *retained = collect(m, FCAM_OP_FRAME_CAPTURE, capture, sizeof capture, 128, &retained_size);
    assert(retained_size > FCAM_FRAME_HEADER_BYTES && m->capture_token && !m->token);
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -EBUSY);
    free(retained); state_request(m, FCAM_OP_CANCEL, NULL, 0);
    assert(fcam_model_cp_parameter_bank_snapshot(m, 3, readback, sizeof readback) == 0 &&
           !memcmp(readback, output, sizeof output));
    memset(readback, 0xa5, sizeof readback);
    assert(fcam_model_cp_parameter_bank_snapshot(m, 2, readback, sizeof readback) == -ESTALE);
    assert(fcam_model_cp_parameter_bank_snapshot(m, 0, readback, sizeof readback) == -ESTALE);
    assert(fcam_model_cp_parameter_bank_snapshot(m, 3, readback, sizeof readback - 1) == -EINVAL);
    assert(fcam_model_cp_parameter_bank_snapshot(m, 3, (uint8_t *)m, sizeof readback) == -EINVAL);
    m->busy = 1; assert(fcam_model_cp_parameter_bank_snapshot(m, 3, readback, sizeof readback) == -EBUSY); m->busy = 0;
    m->parameter_bank[FCAM_CP_PARAMETER_BANK_BYTES - 1] ^= 1;
    assert(fcam_model_cp_parameter_bank_snapshot(m, 3, readback, sizeof readback) == -EIO);
    m->parameter_bank[FCAM_CP_PARAMETER_BANK_BYTES - 1] ^= 1;
    m->parameter_state[FCAM_S_RENDERED] ^= 1;
    assert(fcam_model_cp_parameter_bank_snapshot(m, 3, readback, sizeof readback) == -EIO);
    m->parameter_state[FCAM_S_RENDERED] ^= 1;
    ++m->lifetime;
    assert(fcam_model_cp_parameter_bank_snapshot(m, 3, readback, sizeof readback) == -EIO);
    --m->lifetime;
    for (size_t i = 0; i < sizeof readback; ++i) assert(readback[i] == 0xa5);
    pid_t child = fork(); assert(child >= 0);
    if (!child) {
        assert(fcam_model_cp_parameter_bank_snapshot(m, 3, readback, sizeof readback) == -ECHILD);
        parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -ECHILD);
        _exit(0);
    }
    int child_status;
    assert(waitpid(child, &child_status, 0) == child && WIFEXITED(child_status) && !WEXITSTATUS(child_status));
    fcam_model_destroy(m);
    m = fcam_model_create(99); assert(m);
    parameter_error(m, raw, FCAM_CP_PARAMETER_BANK_BYTES, sizeof output, -ENODATA);
    fcam_model_destroy(m);
}
static void crank_error(struct fcam_model *m, const uint8_t *input, size_t bytes,
                         size_t capacity, int error)
{
    const struct fcam_model before = *m;
    uint8_t output[FCAM_CP_CRANK_RESULT_BYTES + 8];
    memset(output, 0xa5, sizeof output);
    struct fcam_exec_result result = {1, 2, 3, 4}, previous = result;
    assert(fcam_model_request(m, FCAM_OP_CP_CRANK_CONTROL, input, bytes, output, capacity, &result) == error);
    assert(!memcmp(m, &before, sizeof before) && !memcmp(&result, &previous, sizeof result));
    for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
}
static void crank_query_error(struct fcam_model *m, uint64_t crank, uint64_t bank, int error)
{
    const struct fcam_model before = *m;
    uint8_t output[FCAM_CP_CRANK_RESULT_BYTES]; memset(output, 0xa5, sizeof output);
    assert(fcam_model_cp_crank_control_snapshot(m, crank, bank, output, sizeof output) == error);
    assert(!memcmp(m, &before, sizeof before));
    for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
}
static void crank_control_checks(void)
{
    _Static_assert(FCAM_OP_CP_CRANK_CONTROL == 21u && FCAM_OP_CP_PARAMETER_BANK == 20u &&
        FCAM_CP_CRANK_READBACK_OFFSET + FCAM_CP_CRANK_INPUT_BYTES == FCAM_CP_CRANK_R_RESERVED &&
        FCAM_CP_CRANK_R_RESERVED + 4 == FCAM_CP_CRANK_RESULT_BYTES, "independent exact208 crank ABI");
    struct fcam_model *m = fcam_model_create(99); assert(m);
    uint8_t request[13] = {5,0xa7,0x9d,0x40,0x60,0x55,0xaa,0x80};
    crank_error(m, request, 12, 208, -ENODATA);
    state_request(m, FCAM_OP_INIT, NULL, 0);
    crank_error(m, request, 12, 208, -ENODATA);
    crank_query_error(m, 1, 1, -ENODATA);
    setup(m, 128, 64, UINT64_MAX, 8642);
    uint8_t bank[FCAM_CP_PARAMETER_BANK_BYTES], bank_receipt[FCAM_CP_PARAMETER_BANK_RESULT_BYTES];
    uint8_t bank_saved[FCAM_CP_PARAMETER_BANK_RESULT_BYTES], bank_readback[FCAM_CP_PARAMETER_BANK_RESULT_BYTES];
    uint8_t receipt[FCAM_CP_CRANK_RESULT_BYTES + 8], readback[FCAM_CP_CRANK_RESULT_BYTES];
    uint8_t before[128], after[128], original[12];
    struct fcam_exec_result result;
    for (uint64_t generation = 1; generation <= 3; ++generation) {
        if (generation > 1) crank_query_error(m, generation - 1, generation, -ESTALE);
        parameter_input(bank, generation == 2 ? 60 : 30, (uint32_t)(0x80000060u + generation));
        assert(!fcam_model_request(m, FCAM_OP_CP_PARAMETER_BANK, bank, sizeof bank,
                                  bank_receipt, sizeof bank_receipt, &result));
        memcpy(bank_saved, bank_receipt, sizeof bank_saved);
        if (generation > 1) crank_query_error(m, generation - 1, generation - 1, -ESTALE);
        if (generation == 1) {
            crank_query_error(m, 1, 1, -ENODATA);
            const size_t sizes[] = {0, 11, 13};
            for (size_t i = 0; i < sizeof sizes / sizeof sizes[0]; ++i)
                crank_error(m, request, sizes[i], 208, -EINVAL);
            for (size_t cap = 0; cap < 208; ++cap) crank_error(m, request, 12, cap, -ENOSPC);
            const size_t malformed[] = {0, 2, 3};
            for (size_t i = 0; i < sizeof malformed / sizeof malformed[0]; ++i) {
                request[malformed[i]] ^= 1; crank_error(m, request, 12, 208, -EINVAL); request[malformed[i]] ^= 1;
            }
            for (size_t i = 8; i < 12; ++i) {
                request[i] = 1; crank_error(m, request, 12, 208, -ENOTSUP); request[i] = 0;
            }
            struct fcam_exec_result sentinel = {1,2,3,4}, saved = sentinel;
            memset(receipt, 0xa5, sizeof receipt);
            assert(fcam_model_request(m, 21, receipt, 12, receipt, 208, &sentinel) == -EINVAL);
            assert(fcam_model_request(m, 21, m->crank_request, 12, receipt, 208, &sentinel) == -EINVAL);
            assert(fcam_model_request(m, 21, request, 12, (uint8_t *)m, 208, &sentinel) == -EINVAL);
            assert(fcam_model_request(m, 21, request, 12, receipt, 208,
                                      (struct fcam_exec_result *)(void *)receipt) == -EINVAL);
            assert(!memcmp(&sentinel, &saved, sizeof saved));
            m->busy = 1; crank_error(m, request, 12, 208, -EBUSY); m->busy = 0;
            m->vdf_busy = 1; crank_error(m, request, 12, 208, -EBUSY); m->vdf_busy = 0;
            m->owner.info.state = OPTICAL_FRAME_STAGED;
            crank_error(m, request, 12, 208, -EBUSY); m->owner.info.state = OPTICAL_FRAME_IDLE;
            m->capture_owner.info.state = OPTICAL_FRAME_RENDERED;
            crank_error(m, request, 12, 208, -EBUSY); m->capture_owner.info.state = OPTICAL_FRAME_IDLE;
            for (uint32_t stream = 1; stream <= 3; ++stream) {
                m->stream_state = stream;
                crank_error(m, request, 12, 208, stream == 3 ? -EIO : -EBUSY);
            }
            m->stream_state = 0;
            const uint64_t current_generation = m->generation;
            m->generation = UINT64_MAX; crank_error(m, request, 12, 208, -EOVERFLOW); m->generation = current_generation;
            const uint32_t fps = m->config.fps;
            m->config.fps = fps + 1; crank_error(m, request, 12, 208, -ESTALE); m->config.fps = fps;
            const uint32_t quality = m->config.quality;
            m->config.quality = 0; crank_error(m, request, 12, 208, -ERANGE); m->config.quality = quality;
            m->parameter_bank[2563] ^= 1; crank_error(m, request, 12, 208, -EIO); m->parameter_bank[2563] ^= 1;
            m->parameter_state[FCAM_S_GENERATION] ^= 1;
            crank_error(m, request, 12, 208, -EIO); m->parameter_state[FCAM_S_GENERATION] ^= 1;
            m->instance ^= 1; crank_error(m, request, 12, 208, -EIO); m->instance ^= 1;
            uint8_t still[144], byte; still_wire(still, FCAM_STILL_FULL_JPEG, 128, 64, 90);
            assert(!fcam_model_request(m, FCAM_OP_STILL, still, 16, &byte, 1, &result) && result.token);
            crank_error(m, request, 12, 208, -EBUSY);
            state_request(m, FCAM_OP_CANCEL, NULL, 0);
            const uint8_t capture[16] = {5,0,0x38,0x40,0x61,0,0,0x80,2};
            size_t retained_size;
            uint8_t *retained = collect(m, FCAM_OP_FRAME_CAPTURE, capture, 16, 128, &retained_size);
            assert(retained_size > FCAM_FRAME_HEADER_BYTES && m->capture_token && !m->token);
            crank_error(m, request, 12, 208, -EBUSY);
            free(retained); state_request(m, FCAM_OP_CANCEL, NULL, 0);
        }
        const struct fcam_frame_proof proof = frame_proof(m);
        for (int failure = 1; failure <= 2; ++failure) {
            crank_configure_failure = failure;
            crank_error(m, request, 12, 208, -EIO);
            crank_configure_failure = 0;
            assert(m->crank_bank_generation != generation && m->crank_generation == generation - 1);
            same_proof(m, &proof);
        }
        request[1] = (uint8_t)(0xa4u + generation); put32(request + 4, (uint32_t)(0xfedcba00u + generation));
        memcpy(original, request, sizeof original);
        snapshot(m, before);
        const unsigned vcam_calls = crank_vcam_configures, optical_calls = crank_optical_configures;
        memset(receipt, 0xa5, sizeof receipt);
        assert(!fcam_model_request(m, 21, request, 12, receipt, sizeof receipt, &result));
        snapshot(m, after);
        assert(crank_vcam_configures == vcam_calls + 1 && crank_optical_configures == optical_calls + 1);
        assert(result.used == 208 && !result.token && !result.total && !result.offset);
        assert(get32(receipt) == 1 && get32(receipt + 4) == 208 && get64(receipt + 8) == m->instance &&
            get64(receipt + 16) == generation && get64(receipt + 24) == generation &&
            get64(receipt + 32) == get64(before + 56) && get64(receipt + 40) == get64(before + 56) + 1 &&
            get64(receipt + 48) == fnv(original, 12) && !get32(receipt + 56) && get32(receipt + 60) == m->config.fps);
        put64(before + FCAM_S_GENERATION, get64(before + FCAM_S_GENERATION) + 1);
        assert(!memcmp(before, after, 128) && !memcmp(receipt + 64, after, 128));
        assert(!memcmp(receipt + 192, original, 12) && !get32(receipt + 204));
        for (size_t i = 208; i < sizeof receipt; ++i) assert(receipt[i] == 0xa5);
        assert(!fcam_model_cp_crank_control_snapshot(m, generation, generation, readback, sizeof readback) &&
               !memcmp(readback, receipt, sizeof readback));
        assert(!fcam_model_cp_parameter_bank_snapshot(m, generation, bank_readback, sizeof bank_readback) &&
               !memcmp(bank_saved, bank_readback, sizeof bank_saved));
        assert(get64(bank_readback + 32) < get64(receipt + 40));
        request[1] ^= 1; request[4] ^= 1;
        crank_error(m, request, 12, 208, -ESTALE);
        assert(!fcam_model_cp_crank_control_snapshot(m, generation, generation, readback, sizeof readback) &&
               !memcmp(readback + 192, original, 12));
        readback[207] ^= 1;
        assert(!fcam_model_cp_crank_control_snapshot(m, generation, generation, readback, sizeof readback) &&
               !memcmp(readback, receipt, sizeof readback));
        uint8_t config[48] = {0}; config40(&m->config, config); put32(config + 12, 71);
        state_request(m, FCAM_OP_CONFIGURE, config, sizeof config);
        assert(!fcam_model_cp_crank_control_snapshot(m, generation, generation, readback, sizeof readback) &&
               !memcmp(readback, receipt, sizeof readback));
        assert(!fcam_model_cp_parameter_bank_snapshot(m, generation, bank_readback, sizeof bank_readback) &&
               !memcmp(bank_readback, bank_saved, sizeof bank_saved));
        same_proof(m, &proof);
    }
    crank_query_error(m, 0, 3, -ESTALE); crank_query_error(m, 2, 3, -ESTALE);
    crank_query_error(m, 3, 0, -ESTALE); crank_query_error(m, 3, 2, -ESTALE);
    assert(fcam_model_cp_crank_control_snapshot(m, 3, 3, readback, 207) == -EINVAL);
    assert(fcam_model_cp_crank_control_snapshot(m, 3, 3, (uint8_t *)m, 208) == -EINVAL);
    m->busy = 1; crank_query_error(m, 3, 3, -EBUSY); m->busy = 0;
    uint8_t *mutations[] = {m->crank_request, m->crank_request + 1, m->crank_request + 4, m->crank_request + 11,
        m->crank_before_state + 64, m->crank_state + 56, m->crank_state + 127,
        (uint8_t *)&m->crank_input_fnv, (uint8_t *)&m->crank_seal, (uint8_t *)&m->crank_bank_seal,
        (uint8_t *)&m->instance, (uint8_t *)&m->lifetime, m->parameter_bank + 2563};
    for (size_t i = 0; i < sizeof mutations / sizeof mutations[0]; ++i) {
        *mutations[i] ^= 1; crank_query_error(m, 3, 3, -EIO); *mutations[i] ^= 1;
    }
    m->crank_generation = 0;
    crank_query_error(m, 3, 3, -EIO); crank_error(m, request, 12, 208, -EIO);
    m->crank_generation = 3;
    pid_t child = fork(); assert(child >= 0);
    if (!child) { crank_query_error(m, 3, 3, -ECHILD); crank_error(m, request, 12, 208, -ECHILD); _exit(0); }
    int child_status;
    assert(waitpid(child, &child_status, 0) == child && WIFEXITED(child_status) && !WEXITSTATUS(child_status));
    parameter_input(bank, 30, UINT32_C(0x80000064));
    assert(!fcam_model_request(m, 20, bank, sizeof bank, bank_receipt, sizeof bank_receipt, &result));
    const uint64_t seal = m->crank_seal;
    m->crank_generation = UINT64_MAX; m->crank_seal = crank_hash(m);
    crank_error(m, request, 12, 208, -EOVERFLOW);
    m->crank_generation = 3; m->crank_seal = seal;
    assert(!fcam_model_request(m, 21, request, 12, receipt, sizeof receipt, &result));
    assert(get64(receipt + 16) == 4 && get64(receipt + 24) == 4);
    fcam_model_destroy(m);
}
static void movie_error(struct fcam_model *m, const uint8_t *input, size_t bytes,
                        size_t capacity, int error)
{
    const struct fcam_model before = *m;
    uint8_t output[FCAM_CP_MOVIE_FORMAT_RESULT_BYTES + 8]; memset(output, 0xa5, sizeof output);
    struct fcam_exec_result result = {1,2,3,4}, previous = result;
    assert(fcam_model_request(m, FCAM_OP_CP_MOVIE_FORMAT, input, bytes, output, capacity, &result) == error);
    assert(!memcmp(m, &before, sizeof before) && !memcmp(&result, &previous, sizeof result));
    for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
}
static void movie_query_error(struct fcam_model *m, uint64_t movie, uint64_t bank, uint64_t crank, int error)
{
    const struct fcam_model before = *m;
    uint8_t output[FCAM_CP_MOVIE_FORMAT_RESULT_BYTES]; memset(output, 0xa5, sizeof output);
    assert(fcam_model_cp_movie_format_snapshot(m, movie, bank, crank, output, sizeof output) == error);
    assert(!memcmp(m, &before, sizeof before));
    for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
}
static void movie_format_checks(void)
{
    _Static_assert(FCAM_OP_CP_MOVIE_FORMAT == 22u && FCAM_CP_MOVIE_FORMAT_STATE_OFFSET + FCAM_STATE_BYTES == 208u &&
        FCAM_CP_MOVIE_FORMAT_READBACK_OFFSET + FCAM_CP_MOVIE_FORMAT_INPUT_BYTES == FCAM_CP_MOVIE_FORMAT_R_RESERVED &&
        FCAM_CP_MOVIE_FORMAT_R_RESERVED + 12u == FCAM_CP_MOVIE_FORMAT_RESULT_BYTES, "independent exact240 movie ABI");
    struct fcam_model *m = fcam_model_create(99); assert(m);
    uint8_t request[21] = {5,0xa7,0,0x40,0x60,0x55,0xaa,0x80,5,1,0,0xb3,0,0,0,0,0,0,1,0xc4};
    const uint8_t crank[12] = {5,0xa7,0x9d,0x40,0x60,0x55,0xaa,0x80};
    uint8_t bank[FCAM_CP_PARAMETER_BANK_BYTES], bank_saved[FCAM_CP_PARAMETER_BANK_RESULT_BYTES];
    uint8_t bank_query[FCAM_CP_PARAMETER_BANK_RESULT_BYTES], crank_saved[FCAM_CP_CRANK_RESULT_BYTES];
    uint8_t crank_query[FCAM_CP_CRANK_RESULT_BYTES], output[248], query[240], before[128], after[128];
    struct fcam_exec_result result;
    movie_error(m, request, 20, 240, -ENODATA);
    state_request(m, FCAM_OP_INIT, NULL, 0);
    movie_query_error(m, 1, 1, 1, -ENODATA);
    setup(m, 128, 64, UINT64_MAX, 8642);
    for (uint64_t generation = 1; generation <= 3; ++generation) {
        parameter_input(bank, generation == 2 ? 60 : 30, (uint32_t)(0x80000060u + generation));
        assert(!fcam_model_request(m, 20, bank, sizeof bank, bank_saved, sizeof bank_saved, &result));
        movie_error(m, request, 20, 240, generation == 1 ? -ENODATA : -ESTALE);
        assert(!fcam_model_request(m, 21, crank, sizeof crank, crank_saved, sizeof crank_saved, &result));
        if (generation > 1) movie_query_error(m, generation - 1, generation - 1, generation - 1, -ESTALE);
        if (generation == 1) {
            const size_t lengths[] = {0,19,21};
            for (size_t i = 0; i < sizeof lengths / sizeof lengths[0]; ++i)
                movie_error(m, request, lengths[i], 240, -EINVAL);
            for (size_t cap = 0; cap < 240; ++cap) movie_error(m, request, 20, cap, -ENOSPC);
            const size_t bad_header[] = {0,2,3}, selectors[] = {8,9,10,12,13,14,15,16,17,18};
            for (size_t i = 0; i < sizeof bad_header / sizeof bad_header[0]; ++i) {
                request[bad_header[i]] ^= 1; movie_error(m, request, 20, 240, -EINVAL); request[bad_header[i]] ^= 1;
            }
            for (size_t i = 0; i < sizeof selectors / sizeof selectors[0]; ++i) {
                request[selectors[i]] ^= 1; movie_error(m, request, 20, 240, -ENOTSUP); request[selectors[i]] ^= 1;
            }
            assert(fcam_model_request(m, 22, output, 20, output, 240, &result) == -EINVAL);
            assert(fcam_model_request(m, 22, m->movie_request, 20, output, 240, &result) == -EINVAL);
            assert(fcam_model_request(m, 22, request, 20, (uint8_t *)m, 240, &result) == -EINVAL);
            m->busy = 1; movie_error(m, request, 20, 240, -EBUSY); m->busy = 0;
            m->vdf_busy = 1; movie_error(m, request, 20, 240, -EBUSY); m->vdf_busy = 0;
            m->owner.info.state = OPTICAL_FRAME_STAGED;
            movie_error(m, request, 20, 240, -EBUSY); m->owner.info.state = OPTICAL_FRAME_IDLE;
            m->capture_owner.info.state = OPTICAL_FRAME_RENDERED;
            movie_error(m, request, 20, 240, -EBUSY); m->capture_owner.info.state = OPTICAL_FRAME_IDLE;
            for (uint32_t stream = 1; stream <= 3; ++stream) {
                m->stream_state = stream; movie_error(m, request, 20, 240, stream == 3 ? -EIO : -EBUSY);
            }
            m->stream_state = 0;
            const uint64_t generation_before = m->generation;
            m->generation = UINT64_MAX; movie_error(m, request, 20, 240, -EOVERFLOW); m->generation = generation_before;
            const uint32_t fps = m->config.fps, quality_before = m->config.quality, caps = m->caps;
            m->config.fps = fps + 1; movie_error(m, request, 20, 240, -ESTALE); m->config.fps = fps;
            m->config.quality = 0; movie_error(m, request, 20, 240, -ERANGE); m->config.quality = quality_before;
            m->caps &= ~FCAM_CAP_H264; movie_error(m, request, 20, 240, -ENOTSUP); m->caps = caps;
            m->parameter_bank[2563] ^= 1; movie_error(m, request, 20, 240, -EIO); m->parameter_bank[2563] ^= 1;
            m->crank_request[11] ^= 1; movie_error(m, request, 20, 240, -EIO); m->crank_request[11] ^= 1;
            uint8_t still[144], byte; still_wire(still, 1, 128, 64, 90);
            assert(!fcam_model_request(m, 16, still, 16, &byte, 1, &result) && result.token);
            movie_error(m, request, 20, 240, -EBUSY); state_request(m, FCAM_OP_CANCEL, NULL, 0);
            const uint8_t capture[16] = {5,0,0x38,0x40,0x61,0,0,0x80,2};
            size_t retained_size; uint8_t *retained = collect(m, 17, capture, 16, 128, &retained_size);
            assert(retained_size > FCAM_FRAME_HEADER_BYTES && m->capture_token);
            movie_error(m, request, 20, 240, -EBUSY);
            free(retained); state_request(m, FCAM_OP_CANCEL, NULL, 0);
        }
        const struct fcam_frame_proof proof = frame_proof(m);
        for (int failure = 1; failure <= 2; ++failure) {
            crank_configure_failure = failure; movie_error(m, request, 20, 240, -EIO); crank_configure_failure = 0;
            same_proof(m, &proof);
        }
        request[1] = (uint8_t)(0xa0u + generation); request[11] ^= 0x15; request[19] ^= 0x31;
        put32(request + 4, (uint32_t)(0xfedcba00u + generation));
        snapshot(m, before);
        const unsigned vcam_calls = crank_vcam_configures, optical_calls = crank_optical_configures;
        memset(output, 0xa5, sizeof output);
        assert(!fcam_model_request(m, 22, request, 20, output, sizeof output, &result));
        assert(crank_vcam_configures == vcam_calls + 1 && crank_optical_configures == optical_calls + 1);
        snapshot(m, after); put64(before + 56, get64(before + 56) + 1);
        assert(result.used == 240 && !result.token && !result.total && !result.offset);
        assert(get32(output) == 1 && get32(output + 4) == 240 && get64(output + 8) == 99 &&
            get64(output + 16) == generation && get64(output + 24) == generation && get64(output + 32) == generation &&
            get64(output + 40) + 1 == get64(after + 56) && get64(output + 48) == get64(after + 56) &&
            get64(output + 56) == fnv(request,20) && get32(output + 64) == 5 && !get32(output + 68) &&
            get32(output + 72) == m->config.fps && get32(output + 76) == 1 && !memcmp(before,after,128) &&
            !memcmp(output + 80,after,128) && !memcmp(output + 208,request,20));
        for (size_t i = 228; i < 240; ++i) assert(!output[i]);
        for (size_t i = 240; i < sizeof output; ++i) assert(output[i] == 0xa5);
        assert(!fcam_model_cp_movie_format_snapshot(m,generation,generation,generation,query,sizeof query) && !memcmp(query,output,240));
        query[239] ^= 1;
        assert(!fcam_model_cp_movie_format_snapshot(m,generation,generation,generation,query,sizeof query) && !memcmp(query,output,240));
        assert(!fcam_model_cp_parameter_bank_snapshot(m,generation,bank_query,sizeof bank_query) && !memcmp(bank_query,bank_saved,sizeof bank_query));
        assert(!fcam_model_cp_crank_control_snapshot(m,generation,generation,crank_query,sizeof crank_query) && !memcmp(crank_query,crank_saved,sizeof crank_query));
        request[1] ^= 1; movie_error(m,request,20,240,-ESTALE);
        uint8_t config[48] = {0}; config40(&m->config,config); put32(config + 12,71);
        state_request(m,FCAM_OP_CONFIGURE,config,sizeof config);
        assert(!fcam_model_cp_movie_format_snapshot(m,generation,generation,generation,query,sizeof query) && !memcmp(query,output,240));
        same_proof(m,&proof);
        put32(config + 8,m->config.fps == 30 ? 60 : 30);
        expect_error(m,FCAM_OP_VIDEO_BEGIN,config,sizeof config,128,-ESTALE);
        put32(config + 8,m->config.fps);
        m->movie_request[19] ^= 1;
        expect_error(m,FCAM_OP_VIDEO_BEGIN,config,sizeof config,128,-EIO);
        optical_frame_view dummy = {0};
        assert(consume_video_frame(&dummy,m,0) == -EIO);
        m->movie_request[19] ^= 1;
        state_request(m,FCAM_OP_VIDEO_BEGIN,config,sizeof config);
        m->movie_seal ^= 1;
        expect_error(m,FCAM_OP_VIDEO_FRAME,NULL,0,128,-EIO);
        expect_error(m,FCAM_OP_VIDEO_END,NULL,0,128,-EIO);
        m->movie_seal ^= 1;
        size_t packet_size; uint8_t *packet = collect(m,FCAM_OP_VIDEO_FRAME,NULL,0,128,&packet_size);
        assert(packet_size > FCAM_PACKET_HEADER_BYTES && get32(packet + 68) == FCAM_CODEC_AVC1);
        free(packet); state_request(m,FCAM_OP_CANCEL,NULL,0);
    }
    movie_query_error(m,0,3,3,-ESTALE); movie_query_error(m,3,0,3,-ESTALE); movie_query_error(m,3,3,0,-ESTALE);
    assert(fcam_model_cp_movie_format_snapshot(m,3,3,3,query,239) == -EINVAL);
    assert(fcam_model_cp_movie_format_snapshot(m,3,3,3,(uint8_t *)m,240) == -EINVAL);
    m->busy = 1; movie_query_error(m,3,3,3,-EBUSY); m->busy = 0;
    uint8_t *mutations[] = {m->movie_request,m->movie_request+1,m->movie_request+4,m->movie_request+11,m->movie_request+19,
        m->movie_before_state+64,m->movie_state+56,m->movie_state+127,(uint8_t *)&m->movie_input_fnv,
        (uint8_t *)&m->movie_seal,(uint8_t *)&m->movie_bank_seal,(uint8_t *)&m->movie_crank_seal,
        (uint8_t *)&m->instance,(uint8_t *)&m->lifetime,m->parameter_bank+2563,m->crank_request+11};
    for (size_t i = 0; i < sizeof mutations / sizeof mutations[0]; ++i) {
        *mutations[i] ^= 1; movie_query_error(m,3,3,3,-EIO); *mutations[i] ^= 1;
    }
    m->movie_generation = 0; movie_query_error(m,3,3,3,-EIO); m->movie_generation = 3;
    pid_t child = fork(); assert(child >= 0);
    if (!child) { movie_query_error(m,3,3,3,-ECHILD); movie_error(m,request,20,240,-ECHILD); _exit(0); }
    int child_status;
    assert(waitpid(child,&child_status,0) == child && WIFEXITED(child_status) && !WEXITSTATUS(child_status));
    parameter_input(bank,30,UINT32_C(0x80000064));
    assert(!fcam_model_request(m,20,bank,sizeof bank,bank_saved,sizeof bank_saved,&result));
    assert(!fcam_model_request(m,21,crank,sizeof crank,crank_saved,sizeof crank_saved,&result));
    const uint64_t saved_seal = m->movie_seal;
    m->movie_generation = UINT64_MAX; m->movie_seal = movie_hash(m);
    movie_error(m,request,20,240,-EOVERFLOW);
    m->movie_generation = 3; m->movie_seal = saved_seal;
    assert(!fcam_model_request(m,22,request,20,output,sizeof output,&result) && get64(output+16) == 4);
    fcam_model_destroy(m);
}
static void ou_error(struct fcam_model *m, const uint8_t *input, size_t bytes, size_t capacity, int error)
{
    const struct fcam_model before = *m;
    uint8_t output[FCAM_CP_OU_CRANK_RESULT_BYTES + 8]; memset(output, 0xa5, sizeof output);
    struct fcam_exec_result result = {1,2,3,4}, saved = result;
    assert(fcam_model_request(m, 23, input, bytes, output, capacity, &result) == error);
    assert(!memcmp(m, &before, sizeof before) && !memcmp(&result, &saved, sizeof saved));
    for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
}
static void ou_query_error(struct fcam_model *m, uint64_t ou, uint64_t bank, uint64_t crank, uint64_t movie, int error)
{
    const struct fcam_model before = *m;
    uint8_t output[224]; memset(output, 0xa5, sizeof output);
    assert(fcam_model_cp_ou_crank_snapshot(m, ou, bank, crank, movie, output, sizeof output) == error);
    assert(!memcmp(m, &before, sizeof before));
    for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
}
static void ou_settings_commit(struct fcam_model *m)
{
    uint8_t config[40], input[32] = {0}, output[192]; struct fcam_exec_result result;
    config40(&m->config, config); put32(input, UINT32_C(0x00044057)); put64(input + 24, fnv(config, sizeof config));
    assert(!fcam_model_request(m, 14, input, sizeof input, output, sizeof output, &result));
    assert(result.used == 192 && !memcmp(output + 160, input, sizeof input));
}
static void ou_crank_checks(void)
{
    _Static_assert(FCAM_OP_CP_OU_CRANK_CONTROL == 23 && FCAM_CP_OU_CRANK_RESULT_BYTES == 224 &&
        FCAM_CP_OU_CRANK_STATE_OFFSET + FCAM_STATE_BYTES == FCAM_CP_OU_CRANK_READBACK_OFFSET &&
        FCAM_CP_OU_CRANK_READBACK_OFFSET + FCAM_CP_OU_CRANK_INPUT_BYTES == FCAM_CP_OU_CRANK_R_RESERVED &&
        FCAM_CP_OU_CRANK_R_RESERVED + 4 == FCAM_CP_OU_CRANK_RESULT_BYTES, "exact independent OuCrank224");
    struct fcam_model *m = fcam_model_create(99); assert(m);
    uint8_t request[13] = {5,0,0x72,0x40,0x61,0,0,0x80};
    uint8_t bank[2564], bank_saved[2756], bank_query[2756], crank_saved[208], crank_query[208];
    uint8_t movie_saved[240], movie_query[240], output[232], query[224], before[128], after[128];
    const uint8_t crank[12] = {5,0xa7,0x9d,0x40,0x61,0,0,0x80};
    const uint8_t movie[20] = {5,0xb7,0,0x40,0x61,0,0,0x80,5,1,0,0xc7,0,0,0,0,0,0,1,0xd7};
    const uint8_t route[16] = {1,5,5}; uint8_t route_out[160]; struct fcam_exec_result result;
    ou_error(m, request, 12, 224, -ENODATA); state_request(m, 1, NULL, 0);
    assert(!fcam_model_request(m, 5, route, sizeof route, route_out, sizeof route_out, &result));
    ou_query_error(m, 1, 1, 1, 1, -ENODATA);
    for (uint64_t generation = 1; generation <= 2; ++generation) {
        parameter_input(bank, generation == 1 ? 30 : 60, (uint32_t)(0x80000060u + generation));
        assert(!fcam_model_request(m, 20, bank, sizeof bank, bank_saved, sizeof bank_saved, &result));
        assert(!fcam_model_request(m, 21, crank, sizeof crank, crank_saved, sizeof crank_saved, &result));
        ou_error(m, request, 12, 224, generation == 1 ? -ENODATA : -ESTALE);
        ou_settings_commit(m);
        assert(!fcam_model_request(m, 22, movie, sizeof movie, movie_saved, sizeof movie_saved, &result));
        ou_error(m, request, 12, 224, -ESTALE);
        if (generation > 1) ou_query_error(m, 1, 1, 1, 1, -ESTALE);
        ou_settings_commit(m);
        if (generation == 1) {
            const size_t sizes[] = {0,11,13};
            for (size_t i = 0; i < sizeof sizes / sizeof sizes[0]; ++i) ou_error(m, request, sizes[i], 224, -EINVAL);
            ou_error(m, request, 12, 223, -ENOSPC); ou_error(m, request, 12, 0, -ENOSPC);
            const size_t header[] = {0,2,3};
            for (size_t i = 0; i < sizeof header / sizeof header[0]; ++i) {
                request[header[i]] ^= 1; ou_error(m, request, 12, 224, -EINVAL); request[header[i]] ^= 1;
            }
            for (size_t i = 8; i < 12; ++i) { request[i] = 1; ou_error(m, request, 12, 224, -ENOTSUP); request[i] = 0; }
            assert(fcam_model_request(m, 23, output, 12, output, 224, &result) == -EINVAL);
            assert(fcam_model_request(m, 23, m->ou.request, 12, output, 224, &result) == -EINVAL);
            assert(fcam_model_request(m, 23, request, 12, (uint8_t *)m, 224, &result) == -EINVAL);
            assert(fcam_model_request(m, 23, request, 12, output, 224, (struct fcam_exec_result *)(void *)output) == -EINVAL);
            m->busy = 1; ou_error(m, request, 12, 224, -EBUSY); m->busy = 0;
            m->vdf_busy = 1; ou_error(m, request, 12, 224, -EBUSY); m->vdf_busy = 0;
            m->owner.info.state = OPTICAL_FRAME_STAGED;
            ou_error(m, request, 12, 224, -EBUSY); m->owner.info.state = OPTICAL_FRAME_IDLE;
            m->capture_owner.info.state = OPTICAL_FRAME_RENDERED;
            ou_error(m, request, 12, 224, -EBUSY); m->capture_owner.info.state = OPTICAL_FRAME_IDLE;
            m->capture_token = 77; ou_error(m, request, 12, 224, -EBUSY); m->capture_token = 0;
            m->token = 77; ou_error(m, request, 12, 224, -EBUSY); m->token = 0;
            for (uint32_t stream = 1; stream <= 3; ++stream) {
                m->stream_state = stream; ou_error(m, request, 12, 224, stream == 3 ? -EIO : -EBUSY);
            }
            m->stream_state = 0;
            const uint64_t saved_generation = m->generation;
            m->generation = UINT64_MAX; ou_error(m, request, 12, 224, -EOVERFLOW); m->generation = saved_generation;
            m->startup_saved_seal[1] ^= 1; ou_error(m, request, 12, 224, -EIO); m->startup_saved_seal[1] ^= 1;
            m->settings_snapshot40[0] ^= 1; ou_error(m, request, 12, 224, -EIO); m->settings_snapshot40[0] ^= 1;
            m->movie_seal ^= 1; ou_error(m, request, 12, 224, -EIO); m->movie_seal ^= 1;
            m->proof.operation_status = -EIO; ou_error(m, request, 12, 224, -ESTALE); m->proof.operation_status = 0;
            m->proof.after.retired ^= 1; ou_error(m, request, 12, 224, -ESTALE); m->proof.after.retired ^= 1;
            uint8_t wire[48] = {0}; config40(&m->config, wire);
            state_request(m, 3, wire, sizeof wire); ou_error(m, request, 12, 224, -ESTALE); ou_settings_commit(m);
        }
        const struct fcam_frame_proof proof = frame_proof(m);
        for (int failure = 1; failure <= 2; ++failure) {
            crank_configure_failure = failure; ou_error(m, request, 12, 224, -EIO); crank_configure_failure = 0;
            same_proof(m, &proof);
        }
        if (generation == 2) {
            request[1] = 0xe7; put32(request + 4, UINT32_C(0xfedcba98));
            const uint64_t old_generation = m->ou.generation, old_seal = m->ou.seal;
            m->ou.generation = UINT64_MAX; m->ou.seal = ou_hash(m);
            ou_error(m, request, 12, 224, -EOVERFLOW); m->ou.generation = old_generation; m->ou.seal = old_seal;
        }
        snapshot(m, before);
        const unsigned vcam_calls = crank_vcam_configures, optical_calls = crank_optical_configures;
        memset(output, 0xa5, sizeof output);
        assert(!fcam_model_request(m, 23, request, 12, output, sizeof output, &result));
        assert(crank_vcam_configures == vcam_calls + 1 && crank_optical_configures == optical_calls + 1);
        snapshot(m, after);
        assert(result.used == 224 && !result.token && !result.total && !result.offset);
        assert(get32(output) == 1 && get32(output + 4) == 224 && get64(output + 8) == 99 &&
            get64(output + 16) == generation && get64(output + 24) == generation && get64(output + 32) == generation &&
            get64(output + 40) == generation && get64(output + 48) == get64(before + 56) &&
            get64(output + 56) == get64(before + 56) + 1 && get64(output + 64) == fnv(request,12) &&
            !get32(output + 72) && get32(output + 76) == m->config.fps && !memcmp(output + 208,request,12) && !get32(output + 220));
        put64(before + 56,get64(before + 56) + 1);
        assert(!memcmp(before,after,128) && !memcmp(output + 80,after,128)); same_proof(m,&proof);
        for (size_t i = 224; i < sizeof output; ++i) assert(output[i] == 0xa5);
        memset(request,0xee,12);
        assert(!fcam_model_cp_ou_crank_snapshot(m,generation,generation,generation,generation,query,224) && !memcmp(query,output,224));
        query[223] ^= 1; output[0] ^= 1;
        assert(!fcam_model_cp_ou_crank_snapshot(m,generation,generation,generation,generation,query,224) && query[0] == 1 && !query[223]);
        assert(!fcam_model_cp_parameter_bank_snapshot(m,generation,bank_query,sizeof bank_query) && !memcmp(bank_query,bank_saved,sizeof bank_saved));
        assert(!fcam_model_cp_crank_control_snapshot(m,generation,generation,crank_query,sizeof crank_query) && !memcmp(crank_query,crank_saved,sizeof crank_saved));
        assert(!fcam_model_cp_movie_format_snapshot(m,generation,generation,generation,movie_query,sizeof movie_query) && !memcmp(movie_query,movie_saved,sizeof movie_saved));
        memcpy(request,query+208,12); request[1] ^= 1; ou_error(m,request,12,224,-ESTALE);
        uint8_t wire[48] = {0}; config40(&m->config,wire); put32(wire+12,71);
        state_request(m,3,wire,sizeof wire);
        assert(!fcam_model_cp_ou_crank_snapshot(m,generation,generation,generation,generation,output,224) && !memcmp(output,query,224));
        request[1] ^= 1;
    }
    uint8_t *mutations[] = {m->ou.request,m->ou.request+1,m->ou.request+4,m->ou.request+11,m->ou.before+64,m->ou.after+127,
        m->ou.settings,m->ou.checkpoint,(uint8_t *)&m->ou.settings_seal,(uint8_t *)&m->ou.predecessor.operation_status,
        (uint8_t *)&m->ou.seal,(uint8_t *)&m->ou.status,(uint8_t *)&m->ou.bank_seal,(uint8_t *)&m->ou.crank_seal,
        (uint8_t *)&m->ou.movie_seal,(uint8_t *)&m->instance,(uint8_t *)&m->lifetime};
    for (size_t i = 0; i < sizeof mutations / sizeof mutations[0]; ++i) {
        *mutations[i] ^= 1; ou_query_error(m,2,2,2,2,-EIO); *mutations[i] ^= 1;
    }
    m->ou.generation = 0; ou_query_error(m,2,2,2,2,-EIO); ou_error(m,request,12,224,-EIO); m->ou.generation = 2;
    ou_query_error(m,0,2,2,2,-ESTALE); ou_query_error(m,2,1,2,2,-ESTALE);
    ou_query_error(m,2,2,1,2,-ESTALE); ou_query_error(m,2,2,2,1,-ESTALE);
    assert(fcam_model_cp_ou_crank_snapshot(m,2,2,2,2,query,223) == -EINVAL);
    assert(fcam_model_cp_ou_crank_snapshot(m,2,2,2,2,(uint8_t *)m,224) == -EINVAL);
    assert(fcam_model_cp_ou_crank_snapshot(m,2,2,2,2,m->ou.before,224) == -EINVAL);
    m->busy = 1; ou_query_error(m,2,2,2,2,-EBUSY); m->busy = 0;
    pid_t child = fork(); assert(child >= 0);
    if (!child) { ou_query_error(m,2,2,2,2,-ECHILD); ou_error(m,request,12,224,-ECHILD); _exit(0); }
    int status;
    assert(waitpid(child,&status,0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    fcam_model_destroy(m);
}
static void quality(unsigned quality)
{
    struct fcam_model *m = new_model();
    setup(m, 128, 64, 1000000, 2500);
    uint8_t still[144];
    still_wire(still, FCAM_STILL_FULL_JPEG, 128, 64, quality);
    size_t size;
    uint8_t *jpeg = collect(m, FCAM_OP_STILL, still, 16, 63, &size);
    blob("JPEG", jpeg, size);
    free(jpeg);
    fcam_model_destroy(m);
}
int main(int argc, char **argv)
{
    av_log_set_level(AV_LOG_ERROR);
    assert(argc >= 2);
    if (!strcmp(argv[1], "contracts")) contracts();
    else if (!strcmp(argv[1], "proof")) proof_checks();
    else if (!strcmp(argv[1], "fault")) codec_fault();
    else if (!strcmp(argv[1], "empty")) streaming(0);
    else if (!strcmp(argv[1], "long")) streaming(601);
    else if (!strcmp(argv[1], "idr")) forced_idr();
    else if (!strcmp(argv[1], "parameters")) parameter_bank_checks();
    else if (!strcmp(argv[1], "crank")) crank_control_checks();
    else if (!strcmp(argv[1], "movie")) movie_format_checks();
    else if (!strcmp(argv[1], "ou-crank")) ou_crank_checks();
    else if (!strcmp(argv[1], "retained")) retained_capture();
    else {
        assert(argc == 3);
        const unsigned value = (unsigned)strtoul(argv[2], NULL, 10);
        if (!strcmp(argv[1], "chunks")) { assert(value && value <= FCAM_DATA_BYTES); chunks(value); }
        else if (!strcmp(argv[1], "quality")) { assert(value && value <= 100); quality(value); }
        else { assert(!strcmp(argv[1], "products") && (value == 2 || value == 4)); products(value); }
    }
    assert(fflush(stdout) == 0);
    return 0;
}
