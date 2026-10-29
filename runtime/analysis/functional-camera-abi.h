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
#define FCAM_OP_STILL 16u
#define FCAM_OP_VIDEO_BEGIN 32u
#define FCAM_OP_VIDEO_FRAME 33u
#define FCAM_OP_VIDEO_END 34u
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
 * VideoFrame=empty. READ_RESULT24: u64 token,offset; u32 capacity,reserved0.
 * RELEASE_RESULT16: u64 token,whole-result FNV1a64 after real guest readback.
 * No model operation writes a host JPEG/MP4 file or substitutes for MPR/Fsys. */

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

/* Host model result description, not a wire structure. The model copies each
 * result chunk into the supplied output before reporting its consumption. */
struct fcam_exec_result {
    uint64_t token, total, offset;
    size_t used;
};

#endif
