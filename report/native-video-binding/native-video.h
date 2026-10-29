#ifndef NATIVE_VIDEO_BINDING_H
#define NATIVE_VIDEO_BINDING_H

#include "../virtual-video-engine/video-engine.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NVIDEO_MPR_SID UINT32_C(0x8055001f) /* osal_snd_msg destination */
#define NVIDEO_MPR_SOURCE_SID UINT32_C(0x80c70047) /* osal_set_msg_src */
#define NVIDEO_MPR_BYTES 48u
#define NVIDEO_ENCOPEN_BYTES 0x98u
#define NVIDEO_INFO_BYTES 96u
/* Host scratch size; only member offsets 0..0x21 are proved, sizeof is open. */
#define NVIDEO_SAMPLE64_BYTES 40u

enum nvideo_status {
    NVIDEO_OK = 0, NVIDEO_INVALID, NVIDEO_UNSUPPORTED, NVIDEO_RANGE,
    NVIDEO_STALE, NVIDEO_STATE, NVIDEO_SOURCE_ERROR, NVIDEO_DMA_ERROR,
    NVIDEO_CODEC_ERROR
};
enum nvideo_gap {
    NVIDEO_GAP_FRAME_SDS = 1u,
    NVIDEO_GAP_YC_LAYOUT = 2u,
    NVIDEO_GAP_BITSTREAM_FRAMING = 4u,
    NVIDEO_GAP_PARAMETER_SETS = 8u,
    NVIDEO_GAP_COMPLETION_LEASE = 16u,
    NVIDEO_GAP_MPR_PUBLICATION = 32u
};
#define NVIDEO_NATIVE_GAPS 63u

/* Original mpr::Codec -> Avbbc PayloadMpr, NOT a guessed MMIO protocol.
 * command 0=EncOpen (0x98B), 1=start (0x80B), 2=EncIPicture (4B),
 * 3=stop (0x10B), one codec. EncOpen requires zero secondary codec/format.
 * The four bytes in EncIPicture are not proved to be a frame ID or SDS.
 * Undefined/opaque header bytes are ignored; all proved lengths are exact.
 * Pointers are guest address values, never dereferenced by this library.
 */
struct nvideo_request {
    uint16_t command;
    uint8_t codec, file_format, second_codec, second_file_format;
    uint16_t view;
    uint32_t payload_size;
    uint64_t fixed_area, parameter_address;
};
enum nvideo_status nvideo_parse_mpr_request(uint32_t sid,
    const uint8_t *wire, size_t wire_size, size_t parameter_size,
    struct nvideo_request *out);

/* Selected fields of one original AvbbcApi_EncOpen, NOT a rebuilt 0x98B ABI.
 * Counts/capacities retain their source widths; auxiliary units stay opaque.
 * Control extents are source declarations, not measured allocation sizes.
 */
struct nvideo_encopen_parameters {
    struct nvideo_request request;
    uint64_t main_es_base, secondary_es_base, auxiliary_base, video_info_base;
    uint64_t read_control_base, write_control_base;
    uint32_t main_es_capacity, secondary_es_capacity;
    uint32_t read_control_declared_bytes, write_control_declared_bytes;
    uint16_t auxiliary_capacity, video_info_count;
    uint8_t selection_byte; /* Complete A+0x88; selection tests nonzero. */
};
/* Parse the original 48B request using nvideo_parse_mpr_request, then read an
 * exact, caller-owned coherent 0x98B snapshot at logical mapped_base=V (+28).
 * P (+8) is the paired offset-domain address; P and V need not be equal.
 * Caller guarantees both inputs remain accessible/coherent throughout this
 * call. Numerical checks establish neither ownership, coherence nor a lease.
 * All returned addresses are logical values, never host-dereferenced. Zero
 * optional fields are retained; auxiliary_capacity has opaque units and is
 * never used as a byte extent. Nonwrapping proved byte ranges do not establish
 * actual allocations or readiness. Read cursor uses read_control_base+0;
 * write cursor uses the INDEPENDENT write_control_base+4. No UIF is parsed.
 * Unknown parameter bytes are ignored and the snapshot is never rewritten.
 * Inputs may overlap each other. The ENTIRE out_capacity must be accessible,
 * nonwrapping and disjoint from both inputs; out must be suitably aligned.
 * Success writes sizeof(*out) only; every error leaves ALL output unchanged.
 * Invalid spans/sizes/alignment/overlap: INVALID; logical overflow or wrong
 * mapped_base: RANGE; other commands/secondary forms: UNSUPPORTED.
 * No retained pointers, callbacks, native execution, publication or ACK.
 */
enum nvideo_status nvideo_parse_encopen_parameters(uint32_t sid,
    const uint8_t *wire, size_t wire_size, uint64_t mapped_base,
    const uint8_t *parameters, size_t parameter_size,
    struct nvideo_encopen_parameters *out, size_t out_capacity);
/* Every original request remains unsupported until the listed gaps close.
 * This never starts the component encoder, writes guest memory, or ACKs.
 */
enum nvideo_status nvideo_native_request(uint32_t sid,
    const uint8_t *wire, size_t wire_size, size_t parameter_size,
    unsigned *gaps);

/* Actual original VideoInfo ring entry (K1609c8, M2820fc), not an SDS.
 * PTS/DTS units remain the caller's native units. No 1/fps conversion implied.
 * Accepts MPR sample types {0,1,2,3,9}; type0 is the original sync predicate.
 * Requires a nonempty, contiguous AU wholly inside the caller's ES lease.
 */
struct nvideo_info {
    uint8_t type, parameter_set_changes, padding, unit;
    uint64_t address, pts, dts;
    uint32_t length;
    uint16_t vps_size, sps_size, pps_size;
    uint8_t vps_count, sps_count, pps_count;
    uint8_t vps_id, sps_id, pps_id;
    int keyframe;
};
enum nvideo_status nvideo_parse_info(const uint8_t *wire, size_t size,
    uint64_t es_base, size_t es_capacity, struct nvideo_info *out);
/* Original SetVideoSampleInfo -> Sampletype64 field permutation. Requires a
 * validated native info entry; does not infer native AU framing/extradata.
 * Writes 40 host scratch bytes atomically, zeroes unassigned bytes, no MPR
 * calls. This is a proved member mapping, not a recovered complete sizeof.
 */
enum nvideo_status nvideo_build_sample64(const struct nvideo_info *info,
    uint64_t file_offset, int last_sample, uint8_t *wire, size_t size);

/* Original blob descriptor = {base:u64, capacity:u32}, 16-byte pool slot.
 * Pure bounded copy of the exact start blobs {0x40,0x1c0,0x300,0x80}.
 * The pool's full capacity is retained; it is not the copied length.
 * K218c68 -> K2290d8 RETURNS this lease to the free pool; it is not a reader.
 */
enum nvideo_status nvideo_blob_copy(const uint8_t *descriptor, size_t size,
    uint64_t mapped_base, uint8_t *mapped, size_t mapped_capacity,
    const uint8_t *source, size_t source_size);

/* Explicit HOST RGB888 Annex-B component bridge. It never emits an original
 * native completion. Owner serializes calls and owns the borrowed stream.
 * All callbacks are synchronous, must not reenter, and remain valid until
 * destroy. acquire must return the exact requested owner/sequence/SDS lease.
 * release is called exactly once after every successful acquire, including
 * all validation/codec/DMA failures, and before publish. Nonzero release or
 * write/read return aborts the stream without publishing or retry.
 */
struct nvideo_sds { uint32_t type, handle, offset; };
struct nvideo_frame_key {
    uint64_t owner, sequence;
    struct nvideo_sds sds; /* Caller ledger identity; not a proved native frame request. */
};
enum nvideo_source_layout { NVIDEO_HOST_RGB888 = 1 };
struct nvideo_source {
    struct nvideo_frame_key key;
    enum nvideo_source_layout layout;
    struct video_engine_rgb rgb;
};
struct nvideo_component_completion {
    struct nvideo_frame_key key;
    uint64_t address;
    size_t length;
    int64_t pts, dts, duration; /* Engine timebase 1/fps, component only. */
    int keyframe;
};
struct nvideo_ops {
    int (*acquire)(void *, const struct nvideo_frame_key *, struct nvideo_source *);
    int (*release)(void *, const struct nvideo_source *);
    int (*write)(void *, uint64_t address, const uint8_t *, size_t);
    int (*read)(void *, uint64_t address, uint8_t *, size_t);
    void (*publish)(void *, const struct nvideo_component_completion *);
};
struct nvideo_binding;
struct nvideo_binding *nvideo_component_create(struct video_engine_stream *,
    const struct nvideo_ops *, void *context);
void nvideo_component_destroy(struct nvideo_binding *);
enum nvideo_status nvideo_component_begin(struct nvideo_binding *,
    size_t width, size_t height, unsigned fps, size_t max_packet_bytes,
    uint64_t owner);
enum nvideo_status nvideo_component_frame(struct nvideo_binding *,
    const struct nvideo_frame_key *, uint64_t destination,
    size_t destination_capacity, int64_t pts, int64_t duration);
enum nvideo_status nvideo_component_finish(struct nvideo_binding *);
enum nvideo_status nvideo_component_cancel(struct nvideo_binding *);
/* Actual error from acquire/release/write/read, not rewritten as success. */
int nvideo_component_error(const struct nvideo_binding *);
unsigned nvideo_native_gaps(void);

#ifdef __cplusplus
}
#endif
#endif
