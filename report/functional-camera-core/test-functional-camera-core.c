/* SPDX-License-Identifier: MIT */
/* Private inclusion permits adversarial span/counter/sink tests. Python also
 * compiles the production translation unit separately for the broker library. */
#include "functional-camera-core.c"
#include <assert.h>
#include <inttypes.h>
#include <libavutil/log.h>

#define TEST_WIDTH 128u
#define TEST_HEIGHT 64u
#define TEST_FPS 25u

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
    assert(video_frame(m) == -EIO);
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
