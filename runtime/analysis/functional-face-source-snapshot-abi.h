/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_FACE_SOURCE_SNAPSHOT_ABI_H
#define FUNCTIONAL_FACE_SOURCE_SNAPSHOT_ABI_H
#include <stdint.h>

/* Explicit functional image-bus read event. This is not Sony's API40/SDK48
 * message layout and does not assert original global-writer/ASIC exclusion.
 * Host reads actual AP RAM under the owned broker's paused copy window;
 * only the existing dedicated mailbox is written by the host. */
#define FCAM_OP_AP_SOURCE_SNAPSHOT 11u
#define FCAM_ORIGIN_API40_SOURCE_SNAPSHOT 1u /* FCAM_H_FLAGS; legacy origins use 0 */
#define FCAM_FACE_SNAPSHOT_VERSION 1u
#define FCAM_FACE_SNAPSHOT_BASE_BYTES 360u
#define FCAM_FACE_SNAPSHOT_MAX_CP_PAGES 100u
#define FCAM_FACE_SNAPSHOT_MAX_SDK_PAGES 2u
#define FCAM_FACE_SNAPSHOT_MAX_INPUT_BYTES (FCAM_FACE_SNAPSHOT_BASE_BYTES + 8u * 102u)
#define FCAM_FACE_SNAPSHOT_FRAME_BYTES 224u
#define FCAM_FACE_SNAPSHOT_COMMAND UINT32_C(0x02820746)

/* All integers LE; encode/decode bytes, never cast to a wire struct.
 * The original allocation token is minted AT observed birth by the parent;
 * it is a software allocation identity, not observation_sequence/kernel epoch.
 * CP and SDK arrays contain actual present pagemap-derived GPA page addresses.
 * SDK pages cover [frame,frame+224), including context/descriptors/API40.
 * Their VAs, domain labels, or different names alone prove no disjointness.
 * READ_RESULT/RELEASE_RESULT retain the SAME API40 origin flag and tuple. */
#define FCAM_FACE_SNAPSHOT_VERSION_AT 0u
#define FCAM_FACE_SNAPSHOT_UNIT_AT 4u
#define FCAM_FACE_SNAPSHOT_AP_HANDLE_AT 8u
#define FCAM_FACE_SNAPSHOT_CP_HANDLE_AT 12u
#define FCAM_FACE_SNAPSHOT_BYTES_AT 16u
#define FCAM_FACE_SNAPSHOT_CP_COUNT_AT 20u
#define FCAM_FACE_SNAPSHOT_SDK_COUNT_AT 24u
#define FCAM_FACE_SNAPSHOT_REFERENCE_FACTS_AT 28u /* bit0 actual Share21, bit1 actual Open24 */
#define FCAM_FACE_SNAPSHOT_REFERENCE_FACTS 3u
#define FCAM_FACE_SNAPSHOT_ALLOCATION_TOKEN_AT 32u
#define FCAM_FACE_SNAPSHOT_CP_EPOCH_AT 40u
#define FCAM_FACE_SNAPSHOT_CP_REGISTRATION_AT 48u
#define FCAM_FACE_SNAPSHOT_PRODUCER_OWNER_AT 56u
#define FCAM_FACE_SNAPSHOT_PHYSICAL_AT 64u
#define FCAM_FACE_SNAPSHOT_API_FNV_AT 72u
#define FCAM_FACE_SNAPSHOT_BIRTH_OBSERVATION_AT 80u
#define FCAM_FACE_SNAPSHOT_SHARE_OBSERVATION_AT 88u
#define FCAM_FACE_SNAPSHOT_OPEN_OBSERVATION_AT 96u
#define FCAM_FACE_SNAPSHOT_RELATION_AT 104u
#define FCAM_FACE_SNAPSHOT_GENERATION_AT 108u
#define FCAM_FACE_SNAPSHOT_EXTENT_ID_AT 112u
#define FCAM_FACE_SNAPSHOT_PID_AT 116u
#define FCAM_FACE_SNAPSHOT_TID_AT 120u
#define FCAM_FACE_SNAPSHOT_RESERVED_AT 124u
#define FCAM_FACE_SNAPSHOT_SHARE_REQUEST_AT 128u
#define FCAM_FACE_SNAPSHOT_SHARE_REPLY_AT 168u
#define FCAM_FACE_SNAPSHOT_OPEN_REQUEST_AT 208u
#define FCAM_FACE_SNAPSHOT_OPEN_REPLY_AT 248u
#define FCAM_FACE_SNAPSHOT_FRAME_AT 288u
#define FCAM_FACE_SNAPSHOT_API_POINTER_AT 296u
#define FCAM_FACE_SNAPSHOT_API40_AT 304u
#define FCAM_FACE_SNAPSHOT_AP_DESCRIPTOR_AT 344u
#define FCAM_FACE_SNAPSHOT_CP_DESCRIPTOR_AT 352u
#define FCAM_FACE_SNAPSHOT_PAGES_AT 360u /* CP pages then SDK pages, each u64 */

/* Exactly the original three face units: 1d9=0x64000,1da=0xc800,1db=0xd100.
 * Both native refs must come from actual original send/receive/free0 tickets;
 * status is signed i16 at reply+2, source is DMM0061003c, reply is 40B.
 * Open24 count@8==1, handle@12, physical@24, length@32.
 * A successful snapshot result is a retained byte stream of EXACT source bytes,
 * served through existing READ_RESULT64 / RELEASE_RESULT65; it is labelled
 * ap_source_result, never an actual C-model result or rendered CMOS frame.
 * Source CPU-writer completion, native pin counter snapshots and physical ASIC
 * compatibility remain separate claims. No callback until actual guest CP
 * copy/readback and original Close25/extra-owner Free23 have all completed. */
#endif
