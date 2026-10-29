#include "native-video.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Synthetic HOST fixtures. None are a recorded native request/frame/bitstream. */
static void p32(uint8_t *p, uint32_t n)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(n >> (i * 8));
}
static void p64(uint8_t *p, uint64_t n)
{
    p32(p, (uint32_t)n); p32(p + 4, (uint32_t)(n >> 32));
}
static void request(uint8_t *p, unsigned command, unsigned size)
{
    memset(p, 0xa5, NVIDEO_MPR_BYTES); /* Proved-opaque bytes are not reserved zero. */
    p[2] = (uint8_t)command; p[3] = 0;
    p32(p + 0x10, size); p32(p + 0x24, 0x210);
    p64(p + 8, 0x12340000); p64(p + 0x28, 0x12348000);
    if (!command) p[0x19] = p[0x1e] = 0;
}
static void wire_checks(void)
{
    uint8_t wire[96], result[40], original[40], blob[16], src[0x300], dst[0x320];
    struct nvideo_request parsed, before;
    struct nvideo_info info, old;
    unsigned gaps = 0;
    const unsigned sizes[] = {NVIDEO_ENCOPEN_BYTES, 0x80, 4, 0x10};
    for (unsigned c = 0; c <= 3; ++c) {
        request(wire, c, sizes[c]);
        assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, 48, sizes[c], &parsed) == NVIDEO_OK);
        assert(parsed.command == c && parsed.payload_size == sizes[c]);
        assert(parsed.fixed_area == 0x12340000 && parsed.parameter_address == 0x12348000);
        assert(nvideo_native_request(NVIDEO_MPR_SID, wire, 48, sizes[c], &gaps) == NVIDEO_UNSUPPORTED);
        assert(gaps == 63 && nvideo_native_gaps() == 63);
        before = parsed;
        for (size_t n = 0; n < 48; ++n) {
            assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, n, sizes[c], &parsed) == NVIDEO_INVALID);
            assert(memcmp(&before, &parsed, sizeof(parsed)) == 0);
        }
        assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, 49, sizes[c], &parsed) == NVIDEO_INVALID);
        assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, 48, sizes[c] + 1, &parsed) == NVIDEO_INVALID);
        p32(wire + 0x10, sizes[c] + 1);
        assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, 48, sizes[c], &parsed) == NVIDEO_INVALID);
        assert(memcmp(&before, &parsed, sizeof(parsed)) == 0);
    }
    p32(wire + 0x10, 16);
    assert(nvideo_parse_mpr_request(1, wire, 48, 16, &parsed) == NVIDEO_UNSUPPORTED);
    p32(wire + 0x24, 0x1610);
    assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, 48, 16, &parsed) == NVIDEO_UNSUPPORTED);
    request(wire, 4, 16);
    assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, 48, 16, &parsed) == NVIDEO_UNSUPPORTED);
    request(wire, 1, 128); p64(wire + 0x28, UINT64_MAX - 2);
    assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, 48, 128, &parsed) == NVIDEO_RANGE);
    p64(wire + 0x28, 0);
    assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, 48, 128, &parsed) == NVIDEO_RANGE);

    memset(wire, 0, sizeof(wire));
    wire[1] = 6; wire[2] = 8; wire[3] = 1;
    p64(wire + 8, UINT64_C(0x400001020)); p32(wire + 0x10, 65);
    p64(wire + 0x18, UINT64_C(0x1234567887654321));
    p64(wire + 0x20, UINT64_C(0xabcdef0123456789));
    wire[0x2c] = 0x23; wire[0x2d] = 1; wire[0x2e] = 2; wire[0x2f] = 3;
    wire[0x30] = 0x11; wire[0x32] = 4; wire[0x33] = 5;
    assert(nvideo_parse_info(wire, 96, UINT64_C(0x400001000), 97, &info) == NVIDEO_OK);
    assert(info.length == 65 && info.address == UINT64_C(0x400001020) && info.keyframe);
    assert(info.sps_size == 0x123 && info.sps_count == 2 && info.sps_id == 3);
    assert(info.pps_size == 0x11 && info.pps_count == 4 && info.pps_id == 5);
    assert(info.parameter_set_changes == 6 && info.padding == 8 && info.unit == 1);
    assert(nvideo_build_sample64(&info, UINT64_C(0x1234567890), 1, result, sizeof(result)) == NVIDEO_OK);
    assert(memcmp(result, wire + 0x18, 4) == 0);
    assert(memcmp(result + 4, wire + 0x20, 4) == 0);
    assert(memcmp(result + 8, wire + 0x1c, 4) == 0);
    assert(memcmp(result + 12, wire + 0x24, 4) == 0);
    assert(result[16] == 65 && result[32] == 1 && result[33] == 1);
    assert(result[24] == 0x90 && result[28] == 0x12 && result[20] == 0 && result[39] == 0);
    memcpy(original, result, sizeof(result));
    assert(nvideo_build_sample64(&info, UINT64_MAX - 1, 1, result, 40) == NVIDEO_RANGE);
    assert(memcmp(original, result, 40) == 0);
    assert(nvideo_build_sample64(&info, 0, 2, result, 40) == NVIDEO_INVALID);
    assert(nvideo_build_sample64(&info, 0, 1, result, 39) == NVIDEO_INVALID);
    old = info;
    assert(nvideo_parse_info(wire, 96, UINT64_C(0x400001000), 96, &info) == NVIDEO_RANGE);
    assert(memcmp(&old, &info, sizeof(info)) == 0);
    assert(nvideo_parse_info(wire, 95, UINT64_C(0x400001000), 100, &info) == NVIDEO_INVALID);
    assert(nvideo_parse_info(wire, 96, UINT64_MAX - 32, 64, &info) == NVIDEO_RANGE);
    for (unsigned t = 1; t < 10; ++t) {
        wire[0] = (uint8_t)t;
        assert(nvideo_parse_info(wire, 96, UINT64_C(0x400001000), 97, &info) ==
            (t <= 3 || t == 9 ? NVIDEO_OK : NVIDEO_UNSUPPORTED));
        if (t <= 3 || t == 9) assert(!info.keyframe);
    }
    wire[0] = 0; p32(wire + 0x10, 0);
    assert(nvideo_parse_info(wire, 96, UINT64_C(0x400001000), 97, &info) == NVIDEO_INVALID);

    memset(blob, 0, sizeof(blob)); p64(blob, 0x10000); p32(blob + 8, sizeof(src));
    memset(src, 0x5a, sizeof(src)); memset(dst, 0xcc, sizeof(dst));
    const size_t lengths[] = {0x40, 0x1c0, 0x300, 0x80};
    for (size_t i = 0; i < 4; ++i) {
        memset(dst, 0xcc, sizeof(dst));
        assert(nvideo_blob_copy(blob, 16, 0x10000, dst, sizeof(dst), src, lengths[i]) == NVIDEO_OK);
        assert(memcmp(src, dst, lengths[i]) == 0 && dst[lengths[i]] == 0xcc);
    }
    assert(nvideo_blob_copy(blob, 15, 0x10000, dst, sizeof(dst), src, 0x40) == NVIDEO_INVALID);
    assert(nvideo_blob_copy(blob, 16, 0x10001, dst, sizeof(dst), src, 0x40) == NVIDEO_RANGE);
    assert(nvideo_blob_copy(blob, 16, 0x10000, dst, 0x200, src, 0x40) == NVIDEO_RANGE);
    assert(nvideo_blob_copy(blob, 16, 0x10000, dst, sizeof(dst), src, 1) == NVIDEO_UNSUPPORTED);
    p32(blob + 8, 0x3f);
    assert(nvideo_blob_copy(blob, 16, 0x10000, dst, sizeof(dst), src, 0x40) == NVIDEO_RANGE);
}

static void encopen_checks(void)
{
    const uint64_t mapped_base = UINT64_C(0x400001234000);
    const size_t bases[] = {0, 0x10, 0x30, 0x50, 0x58};
    const uint8_t selections[] = {0, 1, 0x80, 0xff};
    uint8_t wire[NVIDEO_MPR_BYTES], saved_wire[NVIDEO_MPR_BYTES];
    uint8_t parameters[NVIDEO_ENCOPEN_BYTES + 1], saved_parameters[sizeof(parameters)];
    uint8_t info_wire[NVIDEO_INFO_BYTES] = {0}, sample[NVIDEO_SAMPLE64_BYTES];
    struct {
        struct nvideo_encopen_parameters value;
        uint8_t tail[32];
    } result, before;
    struct {
        struct nvideo_encopen_parameters value;
        uint8_t storage[NVIDEO_ENCOPEN_BYTES];
    } alias, saved_alias;
    _Alignas(struct nvideo_encopen_parameters) uint8_t unaligned[sizeof(result) + 1];
    struct nvideo_info info;
    struct nvideo_request parsed, old_request;
    unsigned gaps = 0;

    request(wire, 0, NVIDEO_ENCOPEN_BYTES);
    p64(wire + 8, UINT64_C(0x1234567800001000));
    p64(wire + 0x28, mapped_base);
    memcpy(saved_wire, wire, sizeof(wire));
    memset(parameters, 0xa5, sizeof(parameters));
    p64(parameters, UINT64_C(0x2345678900002000)); p32(parameters + 8, 0xfedcba98);
    p64(parameters + 0x10, UINT64_C(0x3456789a00003000)); p32(parameters + 0x18, 0x89abcdef);
    p64(parameters + 0x20, UINT64_C(0x456789ab00004000));
    parameters[0x28] = 0x23; parameters[0x29] = 0x81;
    p64(parameters + 0x30, UINT64_C(0x56789abc00005000));
    parameters[0x38] = 0xdc; parameters[0x39] = 0xfe;
    p64(parameters + 0x50, UINT64_C(0x6789abcd00006000));
    p64(parameters + 0x58, UINT64_C(0x789abcde00007000));
    parameters[0x88] = 0xe2;
    memcpy(saved_parameters, parameters, sizeof(parameters));
    memset(&result, 0xcc, sizeof(result));
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_OK);
    assert(result.value.request.command == 0 && result.value.request.payload_size == 0x98);
    assert(result.value.request.fixed_area == UINT64_C(0x1234567800001000));
    assert(result.value.request.parameter_address == mapped_base);
    assert(result.value.main_es_base == UINT64_C(0x2345678900002000));
    assert(result.value.main_es_capacity == UINT32_C(0xfedcba98));
    assert(result.value.secondary_es_base == UINT64_C(0x3456789a00003000));
    assert(result.value.secondary_es_capacity == UINT32_C(0x89abcdef));
    assert(result.value.auxiliary_base == UINT64_C(0x456789ab00004000));
    assert(result.value.auxiliary_capacity == 0x8123);
    assert(result.value.video_info_base == UINT64_C(0x56789abc00005000));
    assert(result.value.video_info_count == 0xfedc && result.value.selection_byte == 0xe2);
    assert(result.value.read_control_base == UINT64_C(0x6789abcd00006000));
    assert(result.value.write_control_base + 4 == UINT64_C(0x789abcde00007004));
    assert(result.value.read_control_base != result.value.write_control_base + 4);
    assert(result.value.read_control_declared_bytes == 0x294);
    assert(result.value.write_control_declared_bytes == 0x330);
    for (size_t i = 0; i < sizeof(result.tail); ++i) assert(result.tail[i] == 0xcc);
    assert(memcmp(wire, saved_wire, sizeof(wire)) == 0);
    assert(memcmp(parameters, saved_parameters, sizeof(parameters)) == 0);

    /* The parsed ES declaration actually bounds the next existing reader. */
    p64(info_wire + 8, result.value.main_es_base + 32); p32(info_wire + 0x10, 65);
    p64(info_wire + 0x18, UINT64_C(0x1234567887654321));
    assert(nvideo_parse_info(info_wire, sizeof(info_wire), result.value.main_es_base,
        result.value.main_es_capacity, &info) == NVIDEO_OK);
    assert(nvideo_build_sample64(&info, 17, 0, sample, sizeof(sample)) == NVIDEO_OK);
    assert(sample[0] == 0x21 && sample[0x10] == 65 && sample[0x18] == 17);
    assert(nvideo_parse_info(info_wire, sizeof(info_wire), result.value.main_es_base,
        96, &info) == NVIDEO_RANGE);
    assert(nvideo_native_request(NVIDEO_MPR_SID, wire, sizeof(wire),
        NVIDEO_ENCOPEN_BYTES, &gaps) == NVIDEO_UNSUPPORTED);
    assert(gaps == 63 && nvideo_native_gaps() == 63);
    memcpy(&before, &result, sizeof(result));

    for (size_t n = 0; n < NVIDEO_ENCOPEN_BYTES; ++n) {
        assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
            parameters, n, &result.value, sizeof(result)) == NVIDEO_INVALID);
        assert(memcmp(&before, &result, sizeof(result)) == 0);
    }
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, sizeof(parameters), &result.value, sizeof(result)) == NVIDEO_INVALID);
    for (size_t n = 0; n < sizeof(wire); ++n) {
        assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, n, mapped_base,
            parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_INVALID);
        assert(memcmp(&before, &result, sizeof(result)) == 0);
    }
    assert(nvideo_parse_encopen_parameters(1, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_UNSUPPORTED);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base + 1,
        parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_RANGE);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        NULL, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_INVALID);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        (const uint8_t *)(uintptr_t)(UINTPTR_MAX - 1), NVIDEO_ENCOPEN_BYTES,
        &result.value, sizeof(result)) == NVIDEO_INVALID);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, NULL, sizeof(result)) == NVIDEO_INVALID);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result.value) - 1) == NVIDEO_INVALID);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, &result.value, SIZE_MAX) == NVIDEO_INVALID);
    memset(unaligned, 0xcc, sizeof(unaligned));
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, (struct nvideo_encopen_parameters *)(void *)(unaligned + 1),
        sizeof(result.value)) == NVIDEO_INVALID);
    for (size_t i = 0; i < sizeof(unaligned); ++i) assert(unaligned[i] == 0xcc);
    assert(memcmp(&before, &result, sizeof(result)) == 0);

    assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, sizeof(wire), 0x98, &parsed) == NVIDEO_OK);
    memcpy(&old_request, &parsed, sizeof(parsed));
    const size_t secondary_fields[] = {0x19, 0x1e};
    for (size_t i = 0; i < 2; ++i) {
        wire[secondary_fields[i]] = 1;
        assert(nvideo_parse_mpr_request(NVIDEO_MPR_SID, wire, sizeof(wire), 0x98, &parsed) == NVIDEO_UNSUPPORTED);
        assert(memcmp(&old_request, &parsed, sizeof(parsed)) == 0);
        assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
            parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_UNSUPPORTED);
        wire[secondary_fields[i]] = 0;
    }
    p32(wire + 0x10, 2 * NVIDEO_ENCOPEN_BYTES);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_INVALID);
    p32(wire + 0x24, 0x1610);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_UNSUPPORTED);
    request(wire, 1, 0x80);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, 0x80, &result.value, sizeof(result)) == NVIDEO_UNSUPPORTED);
    memcpy(wire, saved_wire, sizeof(wire));
    p64(wire + 0x28, UINT64_MAX - NVIDEO_ENCOPEN_BYTES + 1);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_RANGE);
    memcpy(wire, saved_wire, sizeof(wire));
    assert(memcmp(&before, &result, sizeof(result)) == 0);

    for (size_t i = 0; i < sizeof(bases) / sizeof(*bases); ++i) {
        p64(parameters + bases[i], UINT64_MAX - 1);
        assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
            parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_RANGE);
        assert(memcmp(&before, &result, sizeof(result)) == 0);
        memcpy(parameters, saved_parameters, sizeof(parameters));
    }
    /* Auxiliary units are opaque: parsing cannot infer a byte extent. */
    p64(parameters + 0x20, UINT64_MAX - 1);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_OK);
    assert(result.value.auxiliary_base == UINT64_MAX - 1 && result.value.auxiliary_capacity == 0x8123);
    memcpy(parameters, saved_parameters, sizeof(parameters));
    memcpy(&result, &before, sizeof(result));
    /* Even an unused output tail may not alias either input. */
    memset(&alias, 0xcc, sizeof(alias));
    memcpy(alias.storage, parameters, NVIDEO_ENCOPEN_BYTES);
    memcpy(&saved_alias, &alias, sizeof(alias));
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        alias.storage, NVIDEO_ENCOPEN_BYTES, &alias.value, sizeof(alias)) == NVIDEO_INVALID);
    assert(memcmp(&saved_alias, &alias, sizeof(alias)) == 0);
    memcpy(alias.storage, wire, sizeof(wire));
    memcpy(&saved_alias, &alias, sizeof(alias));
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, alias.storage, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, &alias.value, sizeof(alias)) == NVIDEO_INVALID);
    assert(memcmp(&saved_alias, &alias, sizeof(alias)) == 0);
    for (size_t i = 0; i < sizeof(selections); ++i) {
        parameters[0x88] = selections[i];
        assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
            parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_OK);
        assert(result.value.selection_byte == selections[i]);
    }
    /* Declarations alone do not prove allocation validity or mandatory inputs. */
    memset(parameters, 0, NVIDEO_ENCOPEN_BYTES);
    assert(nvideo_parse_encopen_parameters(NVIDEO_MPR_SID, wire, sizeof(wire), mapped_base,
        parameters, NVIDEO_ENCOPEN_BYTES, &result.value, sizeof(result)) == NVIDEO_OK);
    assert(!result.value.secondary_es_base && !result.value.secondary_es_capacity);
    assert(!result.value.auxiliary_base && !result.value.auxiliary_capacity);
    assert(!result.value.video_info_count && result.value.read_control_declared_bytes == 0x294);
    assert(result.value.write_control_declared_bytes == 0x330 && nvideo_native_gaps() == 63);
}

#define W 64u
#define H 48u
#define CAP 65536u
struct fixture {
    uint8_t rgb[W * H * 3], dma[CAP + 32];
    struct nvideo_component_completion result;
    struct nvideo_binding *binding;
    int acquired, released, written, read, published;
    int acquire_error, release_error, write_error, read_error, corrupt, wrong_key, wrong_layout;
    int emit;
};
static int acquire(void *context, const struct nvideo_frame_key *key, struct nvideo_source *out)
{
    struct fixture *f = context;
    ++f->acquired;
    if (f->acquire_error) return f->acquire_error;
    out->key = *key;
    if (f->wrong_key) ++out->key.sds.handle;
    out->layout = f->wrong_layout ? 0 : NVIDEO_HOST_RGB888;
    out->rgb = (struct video_engine_rgb){ f->rgb, sizeof(f->rgb), W * 3 };
    return 0;
}
static int release(void *context, const struct nvideo_source *source)
{
    struct fixture *f = context;
    assert(source->rgb.data == f->rgb);
    ++f->released;
    return f->release_error;
}
static int dma_write(void *context, uint64_t address, const uint8_t *p, size_t n)
{
    struct fixture *f = context;
    assert(address == 0x4000 && n <= CAP);
    ++f->written;
    if (f->write_error) return f->write_error;
    memcpy(f->dma + 16, p, n);
    if (f->corrupt) f->dma[16] ^= 1;
    return 0;
}
static int dma_read(void *context, uint64_t address, uint8_t *p, size_t n)
{
    struct fixture *f = context;
    assert(address >= 0x4000 && address - 0x4000 + n <= CAP);
    ++f->read;
    if (f->read_error) return f->read_error;
    memcpy(p, f->dma + 16 + (address - 0x4000), n);
    return 0;
}
static void publish(void *context, const struct nvideo_component_completion *p)
{
    struct fixture *f = context;
    assert(f->released == f->acquired && f->written && f->read);
    assert(p->address == 0x4000 && p->length && p->length <= CAP);
    f->result = *p; ++f->published;
    assert(nvideo_component_cancel(f->binding) == NVIDEO_STATE);
    nvideo_component_destroy(f->binding); /* Reentry must not free it. */
    if (f->emit) assert(fwrite(f->dma + 16, 1, p->length, stdout) == p->length);
}
static const struct nvideo_ops ops = { acquire, release, dma_write, dma_read, publish };
static void component_checks(const char *mode)
{
    struct fixture f;
    struct nvideo_frame_key key = {7, 10, {3, 11, 19}};
    enum nvideo_status expected = NVIDEO_OK;
    struct video_engine_stream *stream = video_engine_stream_create();
    memset(&f, 0, sizeof(f)); memset(f.dma, 0xa7, sizeof(f.dma));
    assert(stream);
    for (size_t y = 0; y < H; ++y) for (size_t x = 0; x < W; ++x) {
        size_t i = (y * W + x) * 3;
        f.rgb[i] = x < W / 2 ? 230 : 12;
        f.rgb[i + 1] = y < H / 2 ? 180 : 24;
        f.rgb[i + 2] = (uint8_t)(x * 3);
    }
    if (!strcmp(mode, "acquire")) { f.acquire_error = -71; expected = NVIDEO_SOURCE_ERROR; }
    if (!strcmp(mode, "release")) { f.release_error = -72; expected = NVIDEO_SOURCE_ERROR; }
    if (!strcmp(mode, "write")) { f.write_error = -73; expected = NVIDEO_DMA_ERROR; }
    if (!strcmp(mode, "read")) { f.read_error = -74; expected = NVIDEO_DMA_ERROR; }
    if (!strcmp(mode, "corrupt")) { f.corrupt = 1; expected = NVIDEO_DMA_ERROR; }
    if (!strcmp(mode, "key")) { f.wrong_key = 1; expected = NVIDEO_STALE; }
    if (!strcmp(mode, "layout")) { f.wrong_layout = 1; expected = NVIDEO_UNSUPPORTED; }
    if (!strcmp(mode, "small")) expected = NVIDEO_RANGE;
    f.emit = !strcmp(mode, "emit");
    f.binding = nvideo_component_create(stream, &ops, &f);
    assert(f.binding);
    assert(nvideo_component_begin(f.binding, W, H, 25, CAP, 7) == NVIDEO_OK);
    assert(nvideo_component_begin(f.binding, W, H, 25, CAP, 7) == NVIDEO_STATE);
    assert(nvideo_component_frame(f.binding, &key, UINT64_MAX, CAP, 0, 1) == NVIDEO_INVALID);
    struct nvideo_frame_key stale = key; stale.owner = 8;
    assert(nvideo_component_frame(f.binding, &stale, 0x4000, CAP, 0, 1) == NVIDEO_STALE);
    assert(!f.acquired);
    assert(nvideo_component_frame(f.binding, &key, 0x4000, !strcmp(mode, "small") ? 1 : CAP, 0, 1) == expected);
    assert(f.acquired == 1 && f.released == (f.acquire_error ? 0 : 1));
    assert(f.dma[0] == 0xa7 && f.dma[15] == 0xa7 && f.dma[CAP + 16] == 0xa7);
    if (expected != NVIDEO_OK) {
        assert(!f.published);
        if (f.acquire_error) assert(nvideo_component_error(f.binding) == -71);
        if (f.release_error) assert(nvideo_component_error(f.binding) == -72);
        if (f.write_error) assert(nvideo_component_error(f.binding) == -73);
        if (f.read_error) assert(nvideo_component_error(f.binding) == -74);
        if (!f.acquire_error) {
            assert(nvideo_component_frame(f.binding, &key, 0x4000, CAP, 1, 1) == expected);
            assert(f.acquired == 1);
        }
    } else {
        struct video_engine_stream_info s = video_engine_stream_snapshot(stream);
        assert(f.published == 1 && s.frames_consumed == 1 && s.packets_received == 1);
        assert(f.result.key.owner == 7 && f.result.key.sequence == 10 && f.result.pts == 0);
        assert(f.result.dts == 0 && f.result.duration == 1 && f.result.keyframe);
        assert(nvideo_component_frame(f.binding, &key, 0x4000, CAP, 1, 1) == NVIDEO_STALE);
        assert(f.acquired == 1);
        key.sequence = 11;
        for (size_t i = 0; i < sizeof(f.rgb); ++i) f.rgb[i] = (uint8_t)(255 - f.rgb[i]);
        assert(nvideo_component_frame(f.binding, &key, 0x4000, CAP, 1, 1) == NVIDEO_OK);
        assert(f.published == 2 && f.released == 2 && f.result.pts == 1);
        assert(!f.result.keyframe);
        assert(nvideo_component_finish(f.binding) == NVIDEO_OK);
        assert(video_engine_stream_snapshot(stream).state == VIDEO_ENGINE_STREAM_FINISHED);
    }
    assert(nvideo_component_cancel(f.binding) == NVIDEO_OK);
    assert(nvideo_component_begin(f.binding, W, H, 25, CAP, 7) == NVIDEO_OK);
    assert(nvideo_component_finish(f.binding) == NVIDEO_OK);
    nvideo_component_destroy(f.binding); video_engine_stream_destroy(stream);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "wire")) wire_checks();
    else if (!strcmp(argv[1], "encopen")) encopen_checks();
    else component_checks(argv[1]);
    return 0;
}
