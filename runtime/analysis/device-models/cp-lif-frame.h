/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_LIF_FRAME_H
#define NATIVE_CP_LIF_FRAME_H
#include <stddef.h>
#include <stdint.h>

#define CP_LIF_FRAME_MAX_BYTES 0x220u
#define CP_LIF_FRAME_MAX_RX_BYTES (CP_LIF_FRAME_MAX_BYTES + 1u)
#define CP_LIF_BITMAP_BYTES 16u
#define CP_LIF_MAX_FIELDS 39u

enum cp_lif_origin {
    CP_LIF_ORIGIN_NONE = 0,
    CP_LIF_ORIGIN_VIRTUAL_SOURCE = 1,
    CP_LIF_ORIGIN_HOST_TEST = 2
};
enum cp_lif_bitmap_event {
    CP_LIF_BITMAP_UNKNOWN = 0,
    CP_LIF_BITMAP_A923D0_SNAPSHOT = 1
};
/* Caller holds its external source/transport lock. Matching even sequences and
 * quiescent=1 describe one immutable transaction; this is not a native receipt.
 * A zero-initialized context has unknown inputs. Known bytes must be 0 or 1.
 * bitmap is the actual a923d0 snapshot of 1b1aa12..21 to 1b1aa23..32;
 * this typed input does not verify an original outgoing command 0a.
 * type1_source_byte is the full u8 at 1b1aa10, NOT a guessed admission flag. */
struct cp_lif_frame_context {
    uint64_t sequence_before, sequence_after;
    enum cp_lif_origin origin;
    enum cp_lif_bitmap_event bitmap_event;
    unsigned char quiescent;
    unsigned char bitmap[CP_LIF_BITMAP_BYTES], bitmap_known[CP_LIF_BITMAP_BYTES];
    unsigned char type1_source_byte, type1_source_known;
};
struct cp_lif_field_view {
    uint16_t offset;
    unsigned char length, id, command;
};
struct cp_lif_command_view {
    uint16_t offset, length, metadata;
    unsigned char command, first_field, field_count;
};
/* Views are offsets into this caller-owned frame[]; no input pointers survive.
 * rx_length includes the optional extra zero, frame_length excludes it.
 * transport_decoded describes decoding only: no receive callback, CP state,
 * current/known reply, semantic application, publication, worker, ready or ACK. */
struct cp_lif_decoded_frame {
    uint64_t source_sequence;
    enum cp_lif_origin origin;
    enum cp_lif_bitmap_event bitmap_event;
    uint16_t frame_length, rx_length;
    unsigned char flags, opaque, extra_zero, transport_decoded;
    unsigned char command_count, field_count;
    struct cp_lif_command_view commands[2];
    struct cp_lif_field_view fields[CP_LIF_MAX_FIELDS];
    unsigned char frame[CP_LIF_FRAME_MAX_RX_BYTES];
};
/* Stateless, returns 0 or negative errno and leaves all output bytes unchanged
 * on failure. Supports each top command 5/6 at most once, in either order.
 * Other commands/duplicates are an explicit -ENOTSUP subset boundary.
 * Required unknown input is -ENODATA; known type1 source byte zero is -EACCES.
 * All input/output objects must be accessible; typed alignment, address wrap
 * and overlap with the FULL out_capacity (including unused tail) are checked.
 * out_capacity >= sizeof(*out); only sizeof(*out) bytes are written on success.
 * This API owns no PID, sequence history or mutex. The caller binds freshness
 * and source origin under its lock; replay/staleness detection stays there. */
int cp_lif_frame_decode(const unsigned char *rx, size_t rx_size,
    const struct cp_lif_frame_context *, struct cp_lif_decoded_frame *out,
    size_t out_capacity);
#endif
