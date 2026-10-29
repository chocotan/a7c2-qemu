/* SPDX-License-Identifier: MIT */
#ifndef FULL_OSD_PIN_FORMAT_H
#define FULL_OSD_PIN_FORMAT_H

#include "osd-buffer-owner.h"

#define FULL_OSD_PINMEM_SID 0x90590818u
#define FULL_OSD_PEER_SID 0x9080003bu
#define FULL_OSD_NOTICE_BYTES 80u
#define FULL_OSD_FORMAT_KEY0 0u
#define FULL_OSD_FORMAT_TAG100 0x100u
#define FULL_OSD_FORMAT_TAG101 0x101u
#define FULL_OSD_FORMAT_TAG102 0x102u
#define FULL_OSD_FORMAT_PLANES 4u
#define FULL_OSD_FORMAT_REJECT (-1021)

struct full_osd_format_view {
    unsigned int tag, version, header_flags, payload_offset, payload_bytes;
    unsigned char payload[128], known[128];
};

struct full_osd_format_plane {
    struct full_osd_mapping mapping;
    unsigned int handle, ordinal, tag, payload_bytes, reloads;
    unsigned int selection_mask, selection_mask_known;
    unsigned char payload[128], known[128];
};

struct full_osd_format_state {
    unsigned int owner_pid, initialized, faults, notices, opens, retained_opens;
    unsigned int new100, new101, new102, reload100, ready;
    unsigned int readiness_transitions, readiness_post_pending;
    unsigned int last_handler_status, last_outer_status, unsupported_work;
    unsigned int fifo_submissions, output_callbacks, completion_callbacks;
    struct full_osd_format_plane outputs[FULL_OSD_FORMAT_PLANES];
    /* Three distinct original banks: +68, +28 and +38 respectively. */
    struct full_osd_format_plane incoming100[FULL_OSD_FORMAT_PLANES];
    struct full_osd_format_plane incoming101[FULL_OSD_FORMAT_PLANES];
    struct full_osd_format_plane incoming102[FULL_OSD_FORMAT_PLANES];
    struct full_osd_mapping held[FULL_OSD_POOL_SLOTS];
};

/* Raw CP: 5d606c/5d6124 store numeric 01000000, LE bytes 00 00 00 01.
 * Peer 9d578 -> 58289e stores numeric 1, LE 01 00 00 00, and header+8=3.
 * Peer 46a0ba zeroes its mapping before serialization. Only the used prefix
 * is attributed to these producers; the virtual tail is a5 with known=0.
 * Source payload holes remain a5/known=0, never invented original stack bytes.
 */
int full_osd_format_build_initial(unsigned int kind, unsigned char *data,
                                  unsigned char *known, unsigned int bytes,
                                  unsigned int *used);
/* Reverse key0 completion: new tag101/16B; peer_handle is the full DMM
 * handle of an existing, shared peer-created output, never its local u16 lease.
 * Payload {category=0, peer_handle, mask:u16=0, opaque:u16, result:u32=0}.
 */
int full_osd_format_build_completion101(unsigned int peer_handle, unsigned char *data,
                                       unsigned char *known, unsigned int bytes,
                                       unsigned int *used);
/* 5d61a2: five actual +fc row bytes must be known/inactive. Mutates only the
 * selected tag100 backing count to zero; emits no notice/Share/Open and does
 * not refresh the OSD copy. Nonzero/unknown rows require audited active work.
 */
int full_osd_format_apply_inactive100(unsigned int handle,
                                     const unsigned char row_enabled[5],
                                     const unsigned char row_known[5]);
/* shortcut: one audited initial ETRY only; expand after closing multi-tag work.
 * Stricter producer identity/version checks supplement the original reader,
 * which only compares magic/tag. Padding and opaque payload bytes are copied,
 * not used as business inputs. No pixels or general graphics execution.
 */
int full_osd_format_parse(const unsigned char *data, const unsigned char *known,
                          unsigned int bytes, struct full_osd_format_view *out);
/* Exact 24-byte OSAL + 56-byte 1000/0102/38/1. First descriptor is the
 * receiving peer, second the producer, both {1,3,0,SID}. Transport SIDs are
 * supplied separately, as in the existing OSAL io.source API. Outer +20..23
 * are explicit virtual opaque padding (a5/known=0), not source-proven zeroes.
 * This helper does not send, allocate messages, Share, Open or ACK anything.
 */
int full_osd_notice_build(unsigned int producer_side, unsigned int handle,
                          unsigned char *data, unsigned char *known, unsigned int bytes);
int full_osd_notice_validate(unsigned int producer_side, unsigned int source_sid,
                             unsigned int destination_sid, const unsigned char *data,
                             unsigned int bytes, struct full_osd_mapping *mapping);
/* The caller serializes state access. Init reads all four existing peer-owned
 * output resources and their actual key0 bytes; it does not allocate resources.
 * Consume is only PinMem -> OSD, with one pool Open per new handle followed by
 * actual mapping/read/parse/cache copy. References persist, including failed
 * opens/reads; endpoint destruction must have a separately audited contract.
 * Unsupported active mask, completion or repeated tag101/tag102 never become
 * no-op success. New tag101 matches its embedded full peer handle to an output;
 * mask=0 selects the initial no-plane-callback branch. ready only describes
 * the tag101/tag102 banks. A transition leaves readiness_post_pending=1 for
 * the endpoint to perform the separately audited outer completion/diagnostics.
 * An existing tag100 count=0 reload returns 0 for a completed observed path,
 * but records subhandler=13 / outer=0, matching 46b33c and 46b06c. The endpoint
 * must inspect this status; outer zero alone is never a business-success proof.
 */
int full_osd_format_state_init(struct full_osd_format_state *state,
                               const unsigned int output_handles[FULL_OSD_FORMAT_PLANES]);
int full_osd_format_consume_notice(struct full_osd_format_state *state,
                                  unsigned int source_sid, unsigned int destination_sid,
                                  const unsigned char *notice, unsigned int bytes);
/* Endpoint variant after its actual DMM24 request/reply has Opened the role.
 * Verifies the returned full mapping against the currently open pool resource;
 * registers that reference without a second Open. It accepts new handles only.
 */
int full_osd_format_consume_opened_notice(struct full_osd_format_state *state,
                                         unsigned int source_sid, unsigned int destination_sid,
                                         const unsigned char *notice, unsigned int bytes,
                                         const struct full_osd_mapping *opened_mapping);
void full_osd_format_snapshot(const struct full_osd_format_state *state,
                              struct full_osd_format_state *out);

#endif
