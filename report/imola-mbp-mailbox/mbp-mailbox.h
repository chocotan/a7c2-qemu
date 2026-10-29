/* SPDX-License-Identifier: MIT */
#ifndef IMOLA_MBP_MAILBOX_H
#define IMOLA_MBP_MAILBOX_H

#include <stdint.h>

#define IMOLA_MBP_CHANNELS 2u
#define IMOLA_MBP_ROLES 2u
#define IMOLA_MBP_VIRTUAL_DIRECTION_CAPACITY 1u
#define IMOLA_MBP_DIAGNOSTIC_ONLY 1u
#define IMOLA_MBP_OWNED_DATA_TRANSPORT 1u
#define IMOLA_MBP_ORIGINAL_MCU_EXECUTED 0u

/* Source-linked addresses only; this API does not bind physical aliases. */
#define IMOLA_MBP_SOURCE_SPU0_BASE UINT32_C(0xbf062000)
#define IMOLA_MBP_SOURCE_SPU1_BASE UINT32_C(0xbf072000)
#define IMOLA_MBP_SOURCE_RAM1_BASE UINT32_C(0xbe000000)
#define IMOLA_MBP_TX_COMMAND UINT32_C(0x00)
#define IMOLA_MBP_TX_ARGUMENT UINT32_C(0x04)
#define IMOLA_MBP_RX_COMMAND UINT32_C(0x08)
#define IMOLA_MBP_RX_ARGUMENT UINT32_C(0x0c)
#define IMOLA_MBP_STATUS_DOORBELL UINT32_C(0x10)
#define IMOLA_MBP_TX_CAPACITY UINT32_C(0x02)
#define IMOLA_MBP_RX_PENDING UINT32_C(0x08)
#define IMOLA_MBP_STATUS_KNOWN UINT32_C(0x0a)
#define IMOLA_MBP_UNKNOWN_POISON UINT32_C(0xa5a5a5a5)
#define IMOLA_MBP_SUBMIT UINT32_C(1)
#define IMOLA_MBP_ACK UINT32_C(4)

typedef enum {
    IMOLA_MBP_SPU = 0,
    IMOLA_MBP_MBP = 1
} imola_mbp_role;

typedef struct {
    uint32_t value;
    uint32_t known_bits;
} imola_mbp_word;

typedef struct {
    /* Private state, exposed only for caller-owned fixed-size storage. */
    uint32_t staging[2];
    uint32_t received[2];
    uint32_t written_mask;
    uint32_t read_mask;
    uint32_t pending;
} imola_mbp_endpoint;

typedef struct {
    uint32_t initialized;
    imola_mbp_endpoint endpoints[IMOLA_MBP_CHANNELS][IMOLA_MBP_ROLES];
} imola_mbp;

typedef struct {
    imola_mbp_word status;
    uint32_t staged_words; /* Fresh bitmask: bit 0 command, bit 1 argument. */
    uint32_t read_words; /* RX-read bitmask with the same bit assignments. */
    uint32_t pending;
} imola_mbp_endpoint_info;

typedef struct {
    uint32_t diagnostic_only;
    uint32_t owned_data_transport;
    uint32_t original_mcu_executed;
    uint32_t channels;
    uint32_t direction_capacity;
    imola_mbp_endpoint_info endpoints[IMOLA_MBP_CHANNELS][IMOLA_MBP_ROLES];
} imola_mbp_info;

/* Externally serialized C11 host component; no heap, callbacks, IRQ or I/O.
 * Begin with `imola_mbp owner = {0}; imola_mbp_init(&owner);` exactly once.
 * Do not copy or modify owner internals. Every pointer must name a live, aligned
 * object of the declared type/size. Range/overlap checks cannot prove mapping.
 * Results are 0 or negative errno; errors leave owner and outputs unchanged.
 * Channel/role inputs are checked unsigned values, never truncated to u8.
 */
int imola_mbp_init(imola_mbp *owner);
int imola_mbp_read(imola_mbp *owner, unsigned channel, unsigned role,
                   uint32_t offset, imola_mbp_word *out);
int imola_mbp_write(imola_mbp *owner, unsigned channel, unsigned role,
                    uint32_t offset, uint32_t value);
/* Metadata only: snapshot neither exposes payload nor marks any word read. */
int imola_mbp_snapshot(const imola_mbp *owner, imola_mbp_info *out);

/* Explicit virtual policies, not claims about hardware POR/depth/ACK guards:
 * Init empties both directions of both logical SPU<->MBP pairs.
 * 0/4 stage fresh words in either order; doorbell 1 copies both to peer RX iff
 * both staged and peer empty, clearing only sender's written mask on success.
 * Reads 8/c require pending data, return full known words, mark read bits and
 * never retire data. Doorbell 4 retires only after both RX words were read.
 * Status knows ONLY mask 0xA: bit1=peer RX empty, bit3=own RX pending. Other bits
 * carry A5 poison and remain unknown. This is capacity, never encoder ready.
 * No scalar CPU-MMIO wrapper is enabled: callers must consume only known bits;
 * physical aliases, IRQ wiring and whole-guest instruction consumption remain
 * unproved. Commands and arguments are opaque u32, including command 0x20.
 */
#endif
