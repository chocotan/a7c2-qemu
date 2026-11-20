/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef A7C2_P1_SPI_MONITOR_H
#define A7C2_P1_SPI_MONITOR_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/*
 * Independent virtual protocol core; no QEMU, MMIO, real loader or device IO.
 * Evidence (numbers below are ROM file offsets; ROM is mapped at 0xffff0000,
 * not evidence of A7C II ROM equivalence):
 * analysis/reference/ILCE-7M4-RE/bootrom/CXD90058_Cetus_0xFFFF0000.bin
 * SHA256 27a06e28a2ae8a7107589b441d0c9aad06889be42e674cb63037dda8e1392b89
 * 17fc..1858: eight little-endian halfwords constitute one 16-byte block.
 * 1870..1898: each emitted item is two frames: ffff, (tag << 8)|byte.
 * 5444..5478 then 4900..4928: C3 ready tags 10,11; low nibble increments.
 * 48dc/48e0 initialize w29=2010, w26=30; 48fc branches to 5444.
 * 49e8 query success branches to 5444: strh w29,[x21] then
 *   strb w26,[x21,#2] reset ready/ACK/response to 10/20/30 per command.
 * 4664..472c: receive full block, then 3a ACK with tags 20..2f (wrap).
 *   ACK advances across command + data blocks, not across commands.
 * 64d0 dispatch: 11=query, 12=checksum, 13=execute, 21=write (22 read blocked).
 * 4970..49e4: query response is 16B, first byte 81, remaining bytes zero.
 * 49ec..4a2c,51d0..5334: checksum request address +8, byte count +12;
 *   unsigned byte sum modulo 2^32, response 81 header/length=4 + LE32 sum.
 * 4a30..4a88,4cbc..4dec: write unit=1<<request[1], byte count +4,
 *   address +8, element count +12; 16B input blocks; success 81 header.
 * 55f4..5698: execute acknowledges with 81 header before handing off +8.
 * 49ac..49e4 (and other response loops): each response BYTE uses tag 30..3f.
 * A7C II client: analysis/scratch/bodydata-file-check-20261031/updater-root/
 * bin/spicom.elf, SHA256
 * 0e92c8501389766edd3489c213a996f39b82b36f7ef9544c9e66f83e85cfb3fc;
 * 400ec8 ready, 400f54 ACK, 400fa8 byte-tag receive, 401264..401280
 * checksum command. 400ee8/400ef4/400f00 reset expected tags to 10/20/30;
 *   401244 (checksum) and 4014cc (write, including each file chunk) call
 *   400ec8 before sending each command. Response tag advances per BYTE,
 *   including the checksum's separate 16B header and 4B payload reads.
 * Client and cross-model ROM support this limited subset.
 *
 * Deliberate restrictions: canonical zero reserved fields, write unit=4 only,
 * nonzero writes/checksums/execute targets, all inside caller-owned bounded virtual RAM.
 * The execute_requested flag records a request, not a completed response; a future
 * adapter must use state == P1_SPI_EXEC_REQUESTED as the handoff boundary.
 * Unsupported formats/commands become BLOCKED, without invented error replies.
 * Partial writes already committed by preceding blocks remain after a failure.
 *
 * BLOCKED integration evidence: chip-select / simultaneous MOSI during output,
 * idle clocks, reset-pin timing, A7C II ROM identity, SPI-loader request protocol,
 * PCIeDMA handoff and actual loader execution. APIs separate receive and output
 * consumption; they DO NOT define a full-duplex transfer or force loader ready.
 */
enum p1_spi_state {
    P1_SPI_OFF, P1_SPI_READY, P1_SPI_COMMAND, P1_SPI_COMMAND_ACK,
    P1_SPI_DATA, P1_SPI_DATA_ACK, P1_SPI_RESPONSE,
    P1_SPI_EXEC_REQUESTED, P1_SPI_BLOCKED
};

enum p1_spi_error {
    P1_SPI_OK, P1_SPI_BAD_CONFIG, P1_SPI_BAD_STATE,
    P1_SPI_UNSUPPORTED, P1_SPI_BAD_REQUEST, P1_SPI_RANGE,
    P1_SPI_READBACK
};

struct p1_spi_monitor {
    uint8_t *ram;
    size_t ram_size;
    uint32_t ram_base;
    enum p1_spi_state state;
    enum p1_spi_error error;
    uint8_t block[16];
    size_t block_used;
    uint8_t request[16];
    uint8_t ack_tag;
    uint16_t output[44];
    size_t output_used, output_pos;
    uint32_t write_address, write_left, execute_address;
    uint64_t blocks_received, bytes_written, bytes_readback, bytes_checksummed;
    bool execute_requested;
};

/* init leaves OFF, does not clear RAM; enter explicitly starts/restarts monitor. */
bool p1_spi_monitor_init(struct p1_spi_monitor *m, uint8_t *ram,
                         uint32_t ram_base, size_t ram_size);
bool p1_spi_monitor_enter(struct p1_spi_monitor *m);
/* Input is accepted only after all previous output has been consumed. */
bool p1_spi_monitor_receive_frame(struct p1_spi_monitor *m, uint16_t frame);
/* 1: consumed frame, 0: no output, -1: blocked/invalid argument. */
int p1_spi_monitor_next_frame(struct p1_spi_monitor *m, uint16_t *frame);

#endif
