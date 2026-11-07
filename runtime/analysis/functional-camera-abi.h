/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_CAMERA_ABI_H
#define FUNCTIONAL_CAMERA_ABI_H
#include <stddef.h>
#include <stdint.h>

/* Explicit software-defined hardware, not the Sony physical ASIC ABI.
 * All wire integers are little-endian; never cast wire storage to C structs. */
#define FCAM_PROFILE "virtual-functional-camera-v1"
#define FCAM_ABI_VERSION 1u
#define FCAM_MAGIC UINT32_C(0x314d4346) /* FCM1 */
#define FCAM_PAGE_BYTES 4096u
#define FCAM_MAILBOX_PAGES 16u
#define FCAM_MAILBOX_BYTES (FCAM_PAGE_BYTES * FCAM_MAILBOX_PAGES)
#define FCAM_HEADER_BYTES 512u
#define FCAM_DATA_BYTES (FCAM_MAILBOX_BYTES - FCAM_HEADER_BYTES)
#define FCAM_STATE_BYTES 128u
#define FCAM_CONFIG_BYTES 48u
#define FCAM_AF_BYTES 32u
#define FCAM_PACKET_HEADER_BYTES 96u
#define FCAM_MAX_RESULT_BYTES (64u * 1024u * 1024u)
#define FCAM_DEFAULT_WIDTH 640u
#define FCAM_DEFAULT_HEIGHT 480u
#define FCAM_DEFAULT_FPS 30u
#define FCAM_DEFAULT_QUALITY 90u
#define FCAM_MAX_STILL_WIDTH 8192u
#define FCAM_MAX_STILL_HEIGHT 8192u
#define FCAM_MAX_VIDEO_WIDTH 1920u
#define FCAM_MAX_VIDEO_HEIGHT 1080u
#define FCAM_PIXELS_RGB888 1u /* internal virtual image bus: R,G,B; top row first */
#define FCAM_CAP_STILL 1u
#define FCAM_CAP_H264 2u
#define FCAM_CAP_AF 4u
#define FCAM_CAP_FIXED_OPTICS 8u
#define FCAM_CAPABILITIES 15u

/* One pinned 16-page guest-owned mailbox. PFNs are actual pagemap-derived
 * physical page addresses, immutable until the broker has detached. Only this
 * dedicated storage may be written by the host transport. */
#define FCAM_H_MAGIC 0u
#define FCAM_H_VERSION 4u
#define FCAM_H_PID 8u
#define FCAM_H_STATUS 12u
#define FCAM_H_NONCE 16u
#define FCAM_H_SEQUENCE 24u
#define FCAM_H_OPCODE 32u
#define FCAM_H_REQUEST_BYTES 36u
#define FCAM_H_RESPONSE_CAPACITY 40u
#define FCAM_H_RESPONSE_BYTES 44u
#define FCAM_H_ERROR 48u /* signed errno: 0 or a negative value */
#define FCAM_H_FLAGS 52u
#define FCAM_H_REQUEST_FNV 56u
#define FCAM_H_RESPONSE_FNV 64u
#define FCAM_H_RESULT_TOTAL 72u
#define FCAM_H_RESULT_OFFSET 80u
#define FCAM_H_RESULT_TOKEN 88u
#define FCAM_H_PRODUCER_TID 96u
#define FCAM_H_NATIVE_SOURCE 100u
#define FCAM_H_NATIVE_DESTINATION 104u
#define FCAM_H_NATIVE_COMMAND 108u
#define FCAM_H_NATIVE_BYTES 112u
#define FCAM_H_NATIVE_FNV 120u
#define FCAM_H_PAGES 128u /* 16 x u64; bytes256..511 are virtual reserved zero */
#define FCAM_STATUS_IDLE 0u
#define FCAM_STATUS_REQUEST 1u
#define FCAM_STATUS_RESPONSE 2u
#define FCAM_STATUS_CLOSED 3u
#define FCAM_STATUS_DETACHED 4u /* host stopped all access; guest may unpin */

#define FCAM_OP_INIT 1u
#define FCAM_OP_STATE 2u
#define FCAM_OP_CONFIGURE 3u
#define FCAM_OP_AUTOFOCUS 4u
#define FCAM_OP_VDF_PATH 5u
#define FCAM_OP_VDF_ZEBRA 6u
#define FCAM_OP_VDF_LAYOUT 7u
#define FCAM_OP_VDF_DISPLAY_CONFIG 8u
#define FCAM_OP_BB_STARTUP_CONFIG 9u
#define FCAM_OP_HISTOGRAM 10u
#define FCAM_OP_VDF_BIT_WIDTH 12u
#define FCAM_OP_STILL_FORMAT 13u
#define FCAM_OP_STARTUP_CONTROL 14u
#define FCAM_OP_CP_PARAMETER_BANK 20u
#define FCAM_OP_CP_CRANK_CONTROL 21u
#define FCAM_OP_CP_MOVIE_FORMAT 22u
#define FCAM_OP_CP_OU_CRANK_CONTROL 23u
#define FCAM_OP_STILL 16u
#define FCAM_OP_FRAME_CAPTURE 17u
#define FCAM_OP_FRAME_STILL 18u
#define FCAM_OP_FRAME_RELEASE 19u
#define FCAM_FRAME_HEADER_BYTES 96u
#define FCAM_OP_VIDEO_BEGIN 32u
#define FCAM_OP_VIDEO_FRAME 33u
#define FCAM_OP_VIDEO_END 34u
#define FCAM_VIDEO_FRAME_FORCE_IDR 1u
#define FCAM_OP_READ_RESULT 64u
#define FCAM_OP_RELEASE_RESULT 65u
#define FCAM_OP_CANCEL 66u
#define FCAM_STILL_FULL_JPEG 1u
#define FCAM_STILL_SCAN_ONLY 2u
#define FCAM_STILL_HAS_QUANT 4u

/* Config48: u32 width,height,fps,quality,fnumber_x100,ISO; u64 shutter_us,
 * focus_um (UINT64_MAX=infinity); u32 flags,reserved0. AF32: u32 x,y,w,h,
 * u64 near_um,far_um. Still16: u32 flags,width,height,quality, optionally
 * followed by two source DQT zigzag arrays (128 bytes). VideoBegin=Config48.
 * VideoFrame=empty for normal feed, or u32 flags=FCAM_VIDEO_FRAME_FORCE_IDR
 * to encode this actual frame as IDR. READ_RESULT24: u64 token,offset;
 * u32 capacity,reserved0.
 * RELEASE_RESULT16: u64 token,whole-result FNV1a64 after real guest readback.
 * No model operation writes a host JPEG/MP4 file or substitutes for MPR/Fsys. */

/* Retained software RGB bus; no Sony pixel layout or native allocation claim.
 * FRAME_CAPTURE16: original type5/4038 body, with actual origin checked by bridge.
 * Result Frame96 then immutable packed RGB: u32 version=1,header_bytes=96;
 * u64 frame_token,instance,lifetime,config_generation,frame_generation;
 * u32 width,height,stride,RGB888=1; u64 rgb_bytes,rgb_fnv; u32 cookie;
 * u8 trigger,reserved0[3]; u64 whole-original-request FNV at byte88.
 * FRAME_STILL32/160: u64 frame_token; u32 selector(0 Main,1 Thm,2 Scn),reserved0;
 * Still16/144. All selectors read this same slot; software nearest-neighbor scale.
 * FRAME_RELEASE16: u64 frame_token; u32 encoded_selector_mask,disposition(0/1).
 * Normal release requires Main encoded; disposition1 explicitly abandons the job.
 * The mask is checked against actual successful encodes, never a native DONE ACK.
 * Transfer-result release does not retire the optical frame. CANCEL abandons both.
 */
static inline int fcam_capture_input_valid(const uint8_t *p, size_t size)
{
    if (!p || size != 16 || p[0] != 5 || p[1] || p[2] != 0x38 || p[3] != 0x40 ||
        p[9] || p[10] || p[11]) return 0;
    return p[8] == 2 || p[8] == 10 || p[8] == 12 || p[8] == 8 || p[8] == 9 || p[8] == 3;
}

/* State128: u32 ABI,caps,width,height,fps,quality,fnumber_x100,ISO;
 * u64 shutter_us,focus_um,instance,config_generation,rendered,consumed,
 * jpeg_encoded,video_encoded,result_bytes_read;
 * u32 pending_results,stream_state; u64 frame_generation,reserved0.
 * stream_state: 0=idle,1=recording,2=drained,3=fault. Counters name model
 * events only, never original AP/Fsys/capture acceptance. */
#define FCAM_S_ABI 0u
#define FCAM_S_CAPS 4u
#define FCAM_S_WIDTH 8u
#define FCAM_S_HEIGHT 12u
#define FCAM_S_FPS 16u
#define FCAM_S_QUALITY 20u
#define FCAM_S_FNUMBER 24u
#define FCAM_S_ISO 28u
#define FCAM_S_SHUTTER 32u
#define FCAM_S_FOCUS 40u
#define FCAM_S_INSTANCE 48u
#define FCAM_S_GENERATION 56u
#define FCAM_S_RENDERED 64u
#define FCAM_S_CONSUMED 72u
#define FCAM_S_JPEG_ENCODED 80u
#define FCAM_S_VIDEO_ENCODED 88u
#define FCAM_S_RESULT_READ 96u
#define FCAM_S_PENDING_RESULTS 104u
#define FCAM_S_STREAM_STATE 108u
#define FCAM_S_FRAME_GENERATION 112u

/* Packet result: a software-defined header, NOT original VideoInfo96.
 * u32 width,height; i64 pts,dts,duration; u32 timebase_num,timebase_den,
 * keyframe,flags; u64 packet_bytes,frame_generation; u32 config_bytes,codec;
 * bytes72..95 reserved0, then Annex-B config bytes and the real encoded packet.
 * The original-MPR adapter owns any required AVCC conversion/native timebase. */
#define FCAM_CODEC_AVC1 UINT32_C(0x61766331)
#define FCAM_PACKET_EOS 1u

/* Complete original type5/4063 is an opaque software parameter bank. All 190
 * fixed slots are validated with the existing strict batch validator. Only
 * slot4151's first u32 at absolute0x86c projects to Config48 fps (1..120);
 * all other Config48 fields and all original/opaque bytes, including cookies,
 * survive unchanged. This defines no unknown Sony slot/counter semantics.
 * A successful repeat still advances config_generation, never frame_generation.
 * ParameterBank2756: version/size, instance, bank_generation, before/new config
 * generations, full-input FNV; fps/slot_count/raw_bytes/reserved0; committed
 * State128 followed by an independent complete2564-byte bank readback.
 * No RGB, encoder result, native ACK, ready publication or media is produced. */
#define FCAM_CP_PARAMETER_VERSION 1u
#define FCAM_CP_PARAMETER_BANK_BYTES 2564u
#define FCAM_CP_PARAMETER_BANK_RESULT_BYTES 2756u
#define FCAM_CP_PARAMETER_BANK_SLOTS 190u
#define FCAM_CP_PARAMETER_FPS_AT 0x86cu
#define FCAM_CP_PARAMETER_SOURCE UINT32_C(0x80020002)
#define FCAM_CP_PARAMETER_TARGET UINT32_C(0x90030001)
#define FCAM_CP_PARAMETER_COMMAND UINT32_C(0x4063)
#define FCAM_CP_PARAMETER_R_VERSION 0u
#define FCAM_CP_PARAMETER_R_BYTES 4u
#define FCAM_CP_PARAMETER_R_INSTANCE 8u
#define FCAM_CP_PARAMETER_R_BANK_GENERATION 16u
#define FCAM_CP_PARAMETER_R_BEFORE_CONFIG_GENERATION 24u
#define FCAM_CP_PARAMETER_R_CONFIG_GENERATION 32u
#define FCAM_CP_PARAMETER_R_INPUT_FNV 40u
#define FCAM_CP_PARAMETER_R_FPS 48u
#define FCAM_CP_PARAMETER_R_SLOTS 52u
#define FCAM_CP_PARAMETER_R_RAW_BYTES 56u
#define FCAM_CP_PARAMETER_R_RESERVED 60u
#define FCAM_CP_PARAMETER_BANK_STATE_OFFSET 64u
#define FCAM_CP_PARAMETER_BANK_READBACK_OFFSET 192u

/* Finite post-bank software crank mode0; no Sony physical register claim.
 * Input is the exact original type5/409d12, with byte1/cookie opaque and
 * bytes8..11 zero. Current Config48/FPS is consumed by configure unchanged;
 * only config_generation advances. One commit per parameter-bank generation.
 * Crank208: version/size, instance, crank/bank generations, before/after config
 * generations, full-input FNV, mode0/FPS, committed State128, original12,
 * reserved zero4. No frame, encoder, result token, media or native ACK. */
#define FCAM_CP_CRANK_VERSION 1u
#define FCAM_CP_CRANK_INPUT_BYTES 12u
#define FCAM_CP_CRANK_RESULT_BYTES 208u
#define FCAM_CP_CRANK_SOURCE UINT32_C(0x80020002)
#define FCAM_CP_CRANK_TARGET UINT32_C(0x90030001)
#define FCAM_CP_CRANK_COMMAND UINT32_C(0x409d)
#define FCAM_CP_CRANK_R_VERSION 0u
#define FCAM_CP_CRANK_R_BYTES 4u
#define FCAM_CP_CRANK_R_INSTANCE 8u
#define FCAM_CP_CRANK_R_CRANK_GENERATION 16u
#define FCAM_CP_CRANK_R_BANK_GENERATION 24u
#define FCAM_CP_CRANK_R_BEFORE_CONFIG_GENERATION 32u
#define FCAM_CP_CRANK_R_CONFIG_GENERATION 40u
#define FCAM_CP_CRANK_R_INPUT_FNV 48u
#define FCAM_CP_CRANK_R_MODE 56u
#define FCAM_CP_CRANK_R_FPS 60u
#define FCAM_CP_CRANK_STATE_OFFSET 64u
#define FCAM_CP_CRANK_READBACK_OFFSET 192u
#define FCAM_CP_CRANK_R_RESERVED 204u

/* Finite post-bank/crank software format5/raw-rate1,0 -> RGB888/H.264 at
 * current bank FPS. Current Config48 is consumed unchanged through configure.
 * MovieFormat240 has independent original20/state/seal readback, no frame lease.
 * Once installed its seal/mapping is enforced by actual video consumers; legacy
 * callers without this bank retain their previous behavior. Sony enums unknown. */
#define FCAM_CP_MOVIE_FORMAT_INPUT_BYTES 20u
#define FCAM_CP_MOVIE_FORMAT_RESULT_BYTES 240u
#define FCAM_CP_MOVIE_FORMAT_VERSION 1u
#define FCAM_CP_MOVIE_FORMAT_SOFTWARE_CODEC_H264 1u
#define FCAM_CP_MOVIE_FORMAT_SOURCE UINT32_C(0x80020002)
#define FCAM_CP_MOVIE_FORMAT_TARGET UINT32_C(0x90030001)
#define FCAM_CP_MOVIE_FORMAT_COMMAND UINT32_C(0x4000)
#define FCAM_CP_MOVIE_FORMAT_R_VERSION 0u
#define FCAM_CP_MOVIE_FORMAT_R_BYTES 4u
#define FCAM_CP_MOVIE_FORMAT_R_INSTANCE 8u
#define FCAM_CP_MOVIE_FORMAT_R_MOVIE_GENERATION 16u
#define FCAM_CP_MOVIE_FORMAT_R_BANK_GENERATION 24u
#define FCAM_CP_MOVIE_FORMAT_R_CRANK_GENERATION 32u
#define FCAM_CP_MOVIE_FORMAT_R_BEFORE_CONFIG_GENERATION 40u
#define FCAM_CP_MOVIE_FORMAT_R_CONFIG_GENERATION 48u
#define FCAM_CP_MOVIE_FORMAT_R_INPUT_FNV 56u
#define FCAM_CP_MOVIE_FORMAT_R_FORMAT 64u
#define FCAM_CP_MOVIE_FORMAT_R_RATE 68u
#define FCAM_CP_MOVIE_FORMAT_R_FPS 72u
#define FCAM_CP_MOVIE_FORMAT_R_CODEC 76u
#define FCAM_CP_MOVIE_FORMAT_STATE_OFFSET 80u
#define FCAM_CP_MOVIE_FORMAT_READBACK_OFFSET 208u
#define FCAM_CP_MOVIE_FORMAT_R_RESERVED 228u

/* One-way post-movie/current4057 software mode0, without frame/media or native ACK.
 * Configure consumes unchanged Config48 once per current bank/crank/movie tuple.
 * Original type5/4072/12B keeps byte1/cookie opaque and requires body4 zero. */
#define FCAM_CP_OU_CRANK_VERSION 1u
#define FCAM_CP_OU_CRANK_INPUT_BYTES 12u
#define FCAM_CP_OU_CRANK_RESULT_BYTES 224u
#define FCAM_CP_OU_CRANK_SOURCE UINT32_C(0x80020002)
#define FCAM_CP_OU_CRANK_TARGET UINT32_C(0x90030001)
#define FCAM_CP_OU_CRANK_COMMAND UINT32_C(0x4072)
#define FCAM_CP_OU_CRANK_R_VERSION 0u
#define FCAM_CP_OU_CRANK_R_BYTES 4u
#define FCAM_CP_OU_CRANK_R_INSTANCE 8u
#define FCAM_CP_OU_CRANK_R_OU_GENERATION 16u
#define FCAM_CP_OU_CRANK_R_BANK_GENERATION 24u
#define FCAM_CP_OU_CRANK_R_CRANK_GENERATION 32u
#define FCAM_CP_OU_CRANK_R_MOVIE_GENERATION 40u
#define FCAM_CP_OU_CRANK_R_BEFORE_CONFIG_GENERATION 48u
#define FCAM_CP_OU_CRANK_R_CONFIG_GENERATION 56u
#define FCAM_CP_OU_CRANK_R_INPUT_FNV 64u
#define FCAM_CP_OU_CRANK_R_MODE 72u
#define FCAM_CP_OU_CRANK_R_FPS 76u
#define FCAM_CP_OU_CRANK_STATE_OFFSET 80u
#define FCAM_CP_OU_CRANK_READBACK_OFFSET 208u
#define FCAM_CP_OU_CRANK_R_RESERVED 220u

/* Host model result description, not a wire structure. The model copies each
 * result chunk into the supplied output before reporting its consumption. */
struct fcam_exec_result {
    uint64_t token, total, offset;
    size_t used;
};

#endif
