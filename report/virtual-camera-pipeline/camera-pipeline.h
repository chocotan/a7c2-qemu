/* SPDX-License-Identifier: MIT */
#ifndef VIRTUAL_CAMERA_PIPELINE_H
#define VIRTUAL_CAMERA_PIPELINE_H

#include "../virtual-optical-frame-owner/optical-frame-owner.h"
#include "../virtual-jpeg-hardware/jpeg-hardware.h"
#include "../virtual-video-engine/video-engine.h"

/* Executable host component, not an original Sony request/YC/SDK adapter.
 * Externally serialize every call. Storage must be real, live, non-aliased
 * objects of its declared size; distinct virtual mappings of one allocation
 * are forbidden. No threads, paths, file writes, VM or physical devices.
 */
#define VCAM_MAX_STILL_WIDTH 8192u
#define VCAM_MAX_STILL_HEIGHT 8192u

enum vcam_status {
    VCAM_OK = 0, VCAM_INVALID, VCAM_BUSY, VCAM_STATE, VCAM_BOUNDS,
    VCAM_OVERLAP, VCAM_OPTICAL, VCAM_JPEG, VCAM_VIDEO, VCAM_SINK, VCAM_CANCELLED
};
enum vcam_state { VCAM_IDLE = 0, VCAM_RECORDING, VCAM_DRAINED, VCAM_FAULT };
struct vcam_pipeline;

struct vcam_callbacks {
    /* Optional synchronous observer, after verified JPEG destination readback.
     * External input is 29. Snapshot/cancel permitted; other mutations BUSY.
     * This is a component IRQ, not a guest IRQ injection or native ACK.
     */
    void (*jpeg_irq)(void *context, unsigned external_input, int level);
    /* Optional additional real packet consumer. Called after the memory sink
     * copies/verifies bytes, before publication. Nonzero faults the stream;
     * the exact return survives in snapshot.video.sink_error. Borrowed packet
     * bytes expire on return. May snapshot or request deferred cancellation.
     */
    video_engine_packet_sink packet;
    void *context;
};
struct vcam_record_buffers {
    uint8_t *data;
    size_t data_capacity;
    struct video_engine_packet *packets;
    size_t packet_capacity; /* 1..VIDEO_ENGINE_MAX_FRAMES */
    uint8_t *config; /* Actual Annex-B SPS/PPS extracted from first packet. */
    size_t config_capacity; /* 1..1 MiB */
};
struct vcam_frame_result {
    uint64_t generation;
    optics_metadata metadata;
    int64_t pts; /* Record time base 1/fps; still uses 0. */
};
struct vcam_still_result {
    struct vcam_frame_result frame;
    size_t prefix_length, suffix_length, jpeg_length;
    uint32_t prefix_crc32, suffix_crc32, jpeg_crc32;
};
struct vcam_counts {
    uint64_t rendered, source_read, encoder_consumed, encoded;
    uint64_t output_readback, retired;
};
/* Scalar receipt from the last actual run_frame, unchanged by snapshot,
 * configure/cancel. Hashes read the real leased pool after render and at the
 * actual JPEG acquire / H.264 feed boundary, with padding skipped row by row.
 * JPEG encoded bytes are actual SOS/entropy/EOI handed to jpeg_write. A failed
 * job retains observations, never a success assertion. -ENODATA = not called.
 */
struct vcam_frame_proof {
    uint64_t serial, lease_generation, width, height, stride, active_bytes;
    uint64_t source_fnv1a64, consumer_before_fnv1a64, consumer_after_fnv1a64;
    uint64_t render_observed, consumer_entered, consumer_returned, encoder_consumed, retired;
    uint64_t source_state, consumer_before_state, consumer_after_state, final_state;
    int64_t render_status, consumer_status, retire_status;
    uint64_t encoded_bytes, encoded_fnv1a64;
    struct vcam_counts before, after;
};
struct vcam_info {
    enum vcam_state state;
    enum vcam_status status, last_failure; /* Cancel preserves last_failure. */
    optical_frame_status optical_status;
    optical_frame_info optical;
    struct vjpeg_snapshot jpeg;
    struct video_engine_stream_info video;
    struct vcam_counts counts; /* Lifetime; independent stages, not AP claims. */
    size_t packet_bytes, packet_count, config_bytes, config_required;
    size_t jpeg_written, jpeg_readback;
    uint32_t jpeg_readback_crc32;
    uint64_t irq_assertions;
    int busy, lease_live, jpeg_release_pending;
};

/* One caller-owned frame pool, reused as AF scratch only without a live lease.
 * Never copy/reinitialize this opaque owner. All buffer spans and descriptors
 * are disjoint from pipeline storage, frame pool and other active buffers.
 * Keep frame_pool alive and unmodified until destroy. Creation allocates only
 * controller/codec state; caller owns frame/output/packet/config/MP4 buffers.
 */
struct vcam_pipeline *vcam_create(uint8_t *frame_pool, size_t frame_capacity,
                                   const struct vcam_callbacks *callbacks);
enum vcam_status vcam_destroy(struct vcam_pipeline *pipeline);
struct vcam_info vcam_snapshot(const struct vcam_pipeline *pipeline);
struct vcam_frame_proof vcam_frame_proof_snapshot(const struct vcam_pipeline *pipeline);

/* Configure/AF allowed between recording leases; dimensions stay fixed during
 * a record, focus/exposure/stride may change. Frame capacity >= stride*height.
 * Still dimensions are bounded by VCAM_MAX_STILL_WIDTH/HEIGHT; video further
 * requires VIDEO_ENGINE_MAX_WIDTH/HEIGHT, even dimensions and integer fps
 * 1..VIDEO_ENGINE_MAX_FPS.
 */
enum vcam_status vcam_configure(struct vcam_pipeline *,
                                const optical_frame_config *config);
enum vcam_status vcam_autofocus(struct vcam_pipeline *,
                                const optical_frame_af_request *request,
                                optical_frame_af_result *result);

/* Strict caller-proved RGB/source-header-422 coding, never guessed guest tables.
 * Output is SOI + source DQT/DHT/SOF order + actual hardware SOS/entropy/EOI.
 * Core callbacks probe/read/write/acquire/release this exact pool/output pair.
 * Destination bound is caller supplied (suffix <= UINT32_MAX). A failed encode
 * may leave output bytes, but result stays unchanged. JPEG completion asserts
 * only after exact readback + CRC; outer retirement follows callback return.
 */
enum vcam_status vcam_capture_still(struct vcam_pipeline *,
    const struct vjpeg_coding *coding, uint8_t *output, size_t capacity,
    struct vcam_still_result *result);

/* Fixed-rate record: accepted frames get pts=dts=0,1,... duration=1. No raw
 * input pointer survives feed; packets are copied before feed returns. Record
 * buffers remain exclusive/immutable until successful end or cancel. Packet
 * sink overflow/failure is sticky; no retry/drop presented as success.
 */
enum vcam_status vcam_record_begin(struct vcam_pipeline *, unsigned fps,
                                  const struct vcam_record_buffers *buffers);
enum vcam_status vcam_record_frame(struct vcam_pipeline *,
                                  struct vcam_frame_result *result);
/* Finish/EOS/drain, then existing bounded-memory MP4 mux. OUTPUT_TOO_SMALL
 * yields VCAM_BOUNDS + exact result.required and retains DRAINED for retry;
 * NULL/0 is a sizing query. Successful end returns IDLE. Empty end is STATE.
 * MP4 is a host memory product, not original MPR/Fsys or native capture.
 */
enum vcam_status vcam_record_end(struct vcam_pipeline *, uint8_t *output,
                                size_t capacity, struct video_engine_result *result);
/* Cancel between frames, or defer from an observer until borrowed callback
 * returns; never revoke a published packet/IRQ. Preserves stage/error evidence.
 * All other reentrant mutation, including destroy, returns BUSY.
 */
enum vcam_status vcam_cancel(struct vcam_pipeline *);
#endif
