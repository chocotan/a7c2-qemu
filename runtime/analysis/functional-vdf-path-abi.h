/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_VDF_PATH_ABI_H
#define FUNCTIONAL_VDF_PATH_ABI_H
#include "functional-camera-abi.h"

/* Profile-defined RGB route; not the original selector mask or ASIC layout.
 * Input is the canonical 16-byte VDF path body. Original conversion zeroes
 * bytes13..15. Path1/pins5,5 and path0/pins1,1 are the bounded route subset.
 * Path1 must render -> actual sink copy -> readback -> retire before commit.
 * Path0 disables this virtual route without inventing a frame consumption. */
#define FCAM_VDF_INPUT_BYTES 16u
#define FCAM_VDF_RESULT_BYTES 160u
/* Zebra8 preserves the five original0153 config bytes, then three virtual zero
 * bytes. Only enable byte1==0 is implemented; no physical threshold units.
 * The first160 response bytes retain the VDF schema, but INPUT_FNV hashes
 * Zebra8 and CONFIG contains the actual current route. Bytes160..167 echo the
 * separately saved/read-back Zebra8. Active routes consume a real pass-through
 * RGB frame before commit; inactive routes never invent a frame/lease. */
#define FCAM_ZEBRA_INPUT_BYTES 8u
#define FCAM_ZEBRA_RESULT_BYTES 168u
#define FCAM_ZEBRA_R_CONFIG 160u
/* Software layout policy, not the physical area ordering or enum meanings:
 * exact original case0 body32 (sel7/layout1/src1, in 0,0,640,480, zero out,
 * aspect/type/padding0, timing3/id0). This profile defines in as x,y,w,h and
 * zero out as full-frame pass-through. Only an active 640x480 RGB route is
 * supported. Save/read back all32 bytes and consume/retire the actual full RGB
 * frame before commit. Other layouts/geometries return unsupported/no data.
 * Base160 retains the VDF schema with INPUT_FNV(layout32) and current CONFIG16;
 * the final32 bytes are the independently saved/read-back original layout. */
#define FCAM_LAYOUT_INPUT_BYTES 32u
#define FCAM_LAYOUT_RESULT_BYTES 192u
#define FCAM_LAYOUT_R_CONFIG 160u
/* Explicit display controls, not a generic command ACK: LEu32 command,
 * LEu32 original body bytes, then body8. 0141/body0 refresh consumes a full
 * RGB frame; body8 must be virtual zeros and its original global queue lives.
 * 0152/body8 accepts selector3, enable0,
 * level0..2, magnification0/10/40, color_type0 and one of the four original
 * y/cb/cr triples. 0162/body2 supports only off(0,0), with six virtual zeros.
 * A committed active route must consume/read back/retire a full RGB frame and
 * save/read back this exact16 before replying. Config16 still means the route;
 * INPUT_FNV hashes this envelope and the final16 are its independent readback. */
#define FCAM_DISPLAY_INPUT_BYTES 16u
#define FCAM_DISPLAY_RESULT_BYTES 176u
#define FCAM_DISPLAY_R_CONFIG 160u
#define FCAM_VDF_RESULT_MAX_BYTES FCAM_LAYOUT_RESULT_BYTES
#define FCAM_VDF_ENDPOINT UINT32_C(0x90590819)
#define FCAM_VDF_MASK 1u
#define FCAM_VDF_R_ABI 0u
#define FCAM_VDF_R_BYTES 4u
#define FCAM_VDF_R_INSTANCE 8u
#define FCAM_VDF_R_CONFIG_GENERATION 16u
#define FCAM_VDF_R_FRAME_GENERATION 24u
#define FCAM_VDF_R_LEASE_GENERATION 32u
#define FCAM_VDF_R_INPUT_FNV 40u
#define FCAM_VDF_R_SOURCE_FNV 48u
#define FCAM_VDF_R_SINK_FNV 56u
#define FCAM_VDF_R_ACTIVE_BYTES 64u
#define FCAM_VDF_R_WIDTH 72u
#define FCAM_VDF_R_HEIGHT 76u
#define FCAM_VDF_R_STRIDE 80u
#define FCAM_VDF_R_ENDPOINT 84u
#define FCAM_VDF_R_SELECTED_MASK 88u
#define FCAM_VDF_R_COMPLETED_MASK 92u
#define FCAM_VDF_R_CLASS 96u
#define FCAM_VDF_R_ENABLED 100u
#define FCAM_VDF_R_CONFIG_READBACK 104u
#define FCAM_VDF_R_COMMITTED 108u
#define FCAM_VDF_R_FRAME_CONSUMED 112u
#define FCAM_VDF_R_RETIRED 116u
#define FCAM_VDF_R_STATUS 120u
#define FCAM_VDF_R_RESERVED 124u
#define FCAM_VDF_R_CONFIG 128u /* exact canonical 16-byte readback */
#define FCAM_VDF_R_BEFORE_FRAME_GENERATION 144u
#define FCAM_VDF_R_BEFORE_CONFIG_GENERATION 152u
#endif
