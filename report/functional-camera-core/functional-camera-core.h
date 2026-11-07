/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_CAMERA_CORE_H
#define FUNCTIONAL_CAMERA_CORE_H

#include "../../runtime/analysis/functional-bb-startup-abi.h"
#include "../../runtime/analysis/functional-vdf-bit-width-abi.h"
#include "../../runtime/analysis/functional-still-format-abi.h"
#include "../../runtime/analysis/functional-startup-control-abi.h"

#ifdef __cplusplus
extern "C" {
#endif

struct fcam_model;

/* Host-only read-only proof ABI; never copied into the shared FCM1 mailbox.
 * All fields have fixed width, no addresses/borrowed storage escape. FNV1a64
 * covers active R,G,B bytes, row 0..height-1, x 0..width*3-1; skips padding.
 */
#define FCAM_PROOF_VERSION UINT64_C(1)
#define FCAM_PROOF_PROBE UINT64_C(0)
#define FCAM_PROOF_JPEG UINT64_C(1)
#define FCAM_PROOF_H264 UINT64_C(2)
#define FCAM_PROOF_DRAIN UINT64_C(3)
#define FCAM_PROOF_VDF UINT64_C(4)
#define FCAM_PROOF_BB_STARTUP UINT64_C(5)
#define FCAM_PROOF_HISTOGRAM UINT64_C(6)
#define FCAM_PROOF_FRAME_CAPTURE UINT64_C(7)
#define FCAM_PROOF_FRAME_STILL UINT64_C(8)
#define FCAM_PROOF_FRAME_RELEASE UINT64_C(9)
struct fcam_proof_counts {
    uint64_t rendered, consumed, jpeg_encoded, video_encoded, retired;
};
struct fcam_frame_proof {
    uint64_t version, struct_bytes, serial;
    uint64_t model_instance, model_lifetime, owner_pid, opcode, consumer_kind;
    uint64_t config_generation, frame_generation, lease_generation, packet_generation;
    uint64_t width, height, stride, active_bytes;
    uint64_t source_fnv1a64, consumer_before_fnv1a64, consumer_after_fnv1a64;
    uint64_t render_observed, consumer_entered, consumer_returned, encoder_consumed, retired;
    uint64_t source_state, consumer_before_state, consumer_after_state, final_state;
    int64_t render_status, consumer_status, retire_status, operation_status;
    struct fcam_proof_counts before, after;
    /* Codec bytes: JPEG SOS/entropy/EOI, or ordered actual Annex-B packet
     * payloads; excludes functional prefix/Packet96/config duplication.
     * Result bytes: exact staged representation offered to READ_RESULT.
     * Empty digests are FNV offset; byte counts decide whether data exists.
     */
    uint64_t encoded_bytes, encoded_fnv1a64, result_bytes, result_fnv1a64, result_token;
};

/* Read AFTER the original synchronous request, under the same external lock.
 * Returns 0/-errno; rejects wrong size, alias with model storage, busy or forked
 * model. Never renders, encodes, advances counters or changes the last receipt.
 * serial=0 means no actual probe/frame/drain/VDF transaction yet. STATE/READ/RELEASE/CANCEL
 * preserve the preceding job verbatim, including failed/partial observations.
 * consumer_status is the actual VJPEG/video_engine enum for consumer_kind,
 * or optical_frame_status for VDF/BB/histogram. These hash source before and independent
 * packed sink after its actual copy; encoder_consumed/encoded bytes stay zero.
 * BB/histogram result_bytes/result_fnv cover the complete fixed cached receipt.
 * render/retire statuses are optical_frame_status; -ENODATA means not called.
 * operation_status is the actual outer request errno, not an acceptance flag.
 */
int fcam_model_proof_snapshot(const struct fcam_model *model,
                              struct fcam_frame_proof *proof, size_t proof_size);

/* Externally serialized, synchronous host model; instance must be nonzero.
 * Creation initializes real optics/JPEG contexts and probes the installed H.264
 * encoder. Its explicit software VDF route starts disabled (route0/pins1,1);
 * this is not an inference about original CP RAM/state. NULL means
 * initialization failed (errno describes the failure).
 * Internal image bus is FCAM_PIXELS_RGB888, not a Sony physical YC contract.
 */
struct fcam_model *fcam_model_create(uint64_t instance);
void fcam_model_destroy(struct fcam_model *model);

/* Returns 0 or -errno. All declared spans must be live accessible objects of
 * their stated size through return, mutually disjoint and disjoint from model
 * storage. Alternate virtual aliases of one allocation are forbidden. No caller
 * pointer survives return. Arithmetic/alias validation cannot prove mapping.
 * Validation errors preserve output, result and model configuration/counters;
 * real codec/consumer failures may have side effects and set stream_state=3.
 *
 * INIT(empty/Config48), STATE(empty), CONFIGURE(Config48), VIDEO_BEGIN(Config48)
 * and CANCEL(empty) return State128. First INIT acquires/renders/retires one
 * real default 640x480 sensor probe, with no encoder consumer: rendered and
 * frame_generation advance, consumed/jpeg/video stay zero until a real job.
 * Later INIT calls do not repeat the probe. VDF_PATH(canonical16) returns the
 * fixed Vdf160 receipt from functional-vdf-path-abi.h, without a result token.
 * Profile route1/pins5,5/class1 copies one actual leased RGB frame to an
 * independent sink, verifies every active byte/hash, retires, then commits the
 * exact configuration. Route0/pins1,1/class0 commits/readbacks without a frame.
 * Both accept body[4]<=2, preserve opaque bytes3/5..12 and require tail13..15=0.
 * Each successful call commits one new config generation, including repeats.
 * VDF_ZEBRA(Zebra8) returns Zebra168: five saved/read-back opaque source bytes
 * and three reserved zeros; byte1 must be 0 (other enables are ENOTSUP).
 * Reserved bytes5..7 must be zero. Only disabled/pass-through Zebra is defined;
 * threshold units and original CP gate behavior remain unknown. The existing
 * route controls active/class/frame consumption, independently of Zebra enable.
 * Active route transactions use the same actual RGB copy/readback/retire; an
 * inactive route saves/readbacks without a frame/lease or frame-counter delta.
 * INPUT_FNV hashes Zebra8, CONFIG16 is the current route, tail160..167 is the
 * actual saved Zebra8 readback. All Config48 optics/geometry/fps remain intact;
 * only the software display transaction's config generation advances.
 * Both fixed replies require full capacity before any action or allocation.
 * VDF_BIT_WIDTH(Input8) returns BitWidth168/class7, with the existing VDF
 * consumer proof kind. Only software selector0 -> RGB888/eight-bit components
 * is defined; original015e physical bit depth remains unknown. Requires INIT
 * and an active 640x480 route; consumes/readbacks/retires one real RGB frame,
 * then commits/readbacks its separate8-byte display-bus bank and advances both
 * generations once. Later VDF consumers enforce this saved bus domain. Other
 * selectors return ENOTSUP. No Config48, older banks or State128 ABI changes.
 * STILL_FORMAT(canonical16) returns StillFormat176/class8, using the same
 * actual VDF proof consumer4 and result176/FNV/token0. Only the exact second
 * original402d tuple is supported as a software full-frame/FINE RGB identity
 * policy; Config48 and explicit per-job JPEG geometry/quality stay intact.
 * Requires prior INIT and active640x480; every repeat consumes/readbacks and
 * retires a real frame before independent config16 readback and generation
 * commit. Saved valid/config state is enforced by VDF/JPEG/video consumers.
 * STATE/CANCEL preserve this bank and previous proof. Physical tag2/CP
 * selectors/file formats/publication remain unknown; no RAW/HIF or CP ready.
 * STARTUP_CONTROL(canonical32) returns StartupControl192/class9. Only observed
 * 4014/body16 and 4057/request0 are supported; the last8 input bytes must hash
 * actual State128 bytes8..47 from this instance. INIT and active640x480 are
 * required. Each repeat consumes/readbacks/retires a real independent RGB
 * sink, then saves/readbacks a separate mode/settings bank32 and commits both
 * generations once. 4057 also copies/readbacks independent current config40.
 * Saved banks/checkpoint are sealed to instance/lifetime/generation and checked
 * at VDF/JPEG/video boundaries; legitimate Configure leaves the old checkpoint
 * intact without requiring live equality. No original CP enum, queues, ready,
 * physical/EE/capture equivalence is claimed. See the independent ABI header.
 * BB_STARTUP_CONFIG(canonical32) returns BB192/class5; HISTOGRAM(canonical8)
 * returns Hist1192/class6. Policies and wire offsets are specified in
 * functional-bb-startup-abi.h. Both require the active 640x480 route, consume
 * and retire an actual RGB frame, read back separate config/result storage,
 * then advance config/frame generation once. Histogram arrays read the actual
 * independently owned sink pixels after retirement; no borrowed view escapes.
 * Five BB banks/valid bits, software SQ/look/input/gain/interval state and the
 * first histogram cache are independent of Config48 and older display banks.
 * SQ off state is also checked at VIDEO_BEGIN admission. No CP/RTOS, continuous
 * notification, UI or original capture acceptance is established by these ops.
 * Recording/pending-result/busy/fault states reject before touching old work.
 * Route mapping is functional-profile policy, not a Sony physical ASIC claim.
 * CP_PARAMETER_BANK(full original2564) returns ParameterBank2756. Every slot
 * is validated by a fresh strict one-shot stager, then the whole bank is saved.
 * The explicit software projection changes only Config48 fps from slot4151;
 * existing configure commits one generation even when fps is unchanged. All
 * validation precedes this commit; rejected transactions preserve bank/config.
 * Requires INIT, idle stream/optics and no result or retained frame. There is
 * no rendering, encoding, frame-generation change or new frame proof. The
 * bank's committed State128 and all2564 bytes have an independent read API;
 * later Configure/STATE/CANCEL preserve this historical bank receipt.
 * CP_CRANK_CONTROL(full original12) returns Crank208. The declared finite
 * software mode0 consumes unchanged current Config48/FPS through configure,
 * advances config_generation once, and consumes one authorization from the
 * current committed parameter-bank generation. Repeat on that bank is ESTALE.
 * Requires initialized same-instance valid bank/FPS, idle stream/optics and no
 * pending result/retained frame. Byte1/cookie remain opaque; bytes8..11 are0.
 * Rejection preserves authorization/state/output; no frame proof or media.
 * CP_MOVIE_FORMAT(full original20) returns MovieFormat240 after a committed
 * same-instance parameter bank and crank. Observed format5/raw rate1,0 maps
 * to existing RGB888/H.264 at the current bank FPS. Configure consumes actual
 * current Config48 unchanged; only config_generation advances. One transaction
 * per bank/crank pair; no frame lease/proof/media. Byte1/cookie/11/19 are opaque.
 * Once installed, its sealed mapping is checked at VIDEO_BEGIN and actual video
 * consumers; callers without this bank keep the existing route. Later Configure
 * preserves the historical receipt without requiring old State128 == live state.
 * CP_OU_CRANK_CONTROL(full original12/type5/4072/body0) returns OuCrank224.
 * Requires the current bank/crank/movie tuple and just-completed functional4057
 * settings/config40/seal plus its successful real RGB proof at current generation.
 * Existing configure consumes unchanged Config48 once per tuple; only config
 * generation advances. No frame/proof/media/native reply is produced.
 * AUTOFOCUS(AF32) returns: u64 focus_um,
 * u64 score_Q16, u32 coarse_samples,refinement_samples; bytes24..31 zero.
 * STILL returns encoded JPEG or its actual SOS/entropy/EOI suffix. VIDEO_FRAME
 * and VIDEO_END return Packet96 + actual Annex-B config + actual packet bytes;
 * a buffered frame has zero used/total/token, while real drained EOS always has
 * a Packet96 header with FCAM_PACKET_EOS. VIDEO_FRAME's optional four-byte
 * FORCE_IDR flag is validated before rendering and encodes that real RGB frame.
 * It succeeds only with one actual key packet containing IDR NAL type5; missing
 * output faults the stream after consumption, so it must not be retried.
 * A following empty VIDEO_FRAME restores automatic picture selection.
 * No MP4 mux or host file writes.
 *
 * Encoded results are model-owned, <=FCAM_MAX_RESULT_BYTES, one at a time.
 * The creating request copies min(out_capacity,total) bytes (capacity >=1).
 * exec_result is {nonzero token,total,offset=0,used}; READ_RESULT24 requires the
 * current cursor and copies min(request.capacity,out_capacity,remaining), with
 * both capacities >=1 and request.capacity<=out_capacity. Its offset is the
 * first byte of that chunk. RELEASE_RESULT16 requires every byte read and the
 * FNV1a64 of the whole result, then returns zero bytes and retires storage.
 * While pending, only STATE/READ_RESULT/RELEASE_RESULT/CANCEL are accepted.
 * Tokens never repeat during a model lifetime; CANCEL invalidates a live token.
 * For state/AF replies and empty successful replies token,total,offset are zero.
 * State reads do not count as encoded-result readback. Counters are lifetime
 * model events and never claim AP/MPR/Fsys acceptance or capture verification.
 */
int fcam_model_request(struct fcam_model *model, uint32_t opcode,
                       const uint8_t *input, size_t in_size,
                       uint8_t *output, size_t out_capacity,
                       struct fcam_exec_result *result);

/* Read-only committed ParameterBank2756, under the same external lock as the
 * request. Exact nonzero bank_generation prevents stale-bank substitution;
 * receipt instance and committed config generation bind the query. Later
 * configuration changes do not rewrite its historical State128. Rejects busy,
 * fork, wrong size, private-storage aliases, missing/stale/corrupt bank. */
int fcam_model_cp_parameter_bank_snapshot(const struct fcam_model *model,
    uint64_t bank_generation, uint8_t *output, size_t output_bytes);

/* Read-only independently reconstructed Crank208 under the same external lock.
 * Exact nonzero crank_generation and bank_generation must identify the current
 * bank and saved commit. Checks original12, full before/after State128 and the
 * instance/lifetime/generation seal; rejects busy/fork/aliases/stale/corruption.
 * Later Configure preserves this historical receipt; a new bank makes it stale.
 * Does not render, encode, advance counters or change the prior frame proof. */
int fcam_model_cp_crank_control_snapshot(const struct fcam_model *model,
    uint64_t crank_generation, uint64_t bank_generation,
    uint8_t *output, size_t output_bytes);

/* Read-only independently rebuilt MovieFormat240. Exact nonzero movie/bank/
 * crank generations identify the current saved commit. Validates original20,
 * full before/after State128 and instance/lifetime/predecessor seals. Historical
 * state survives Configure. Rejects missing/stale/corrupt/fork/busy/aliases;
 * never renders, encodes, advances counters or changes the prior frame proof. */
int fcam_model_cp_movie_format_snapshot(const struct fcam_model *model,
    uint64_t movie_generation, uint64_t bank_generation, uint64_t crank_generation,
    uint8_t *output, size_t output_bytes);

/* Independently rebuild OuCrank224 from saved original12, before/after State128,
 * current tuple, predecessor4057 checkpoint/proof and instance/lifetime seal.
 * Exact nonzero IDs reject stale substitution; historical state survives later
 * Configure without rewriting older bank/crank/movie receipts. Same lock as
 * request; rejects wrong size, alias, busy, fork and corrupt domain. No frames. */
int fcam_model_cp_ou_crank_snapshot(const struct fcam_model *model,
    uint64_t ou_generation, uint64_t bank_generation, uint64_t crank_generation,
    uint64_t movie_generation, uint8_t *output, size_t output_bytes);

#ifdef __cplusplus
}
#endif
#endif
