#ifndef VIRTUAL_JPEG_HARDWARE_H
#define VIRTUAL_JPEG_HARDWARE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define VJPEG_DEVICE0_PA UINT64_C(0xf3020000)
#define VJPEG_DEVICE0_EXTERNAL_IRQ 29u
#define VJPEG_NATIVE_HEADER_SIZE 0x23du
#define VJPEG_PREFIX_SIZE (2u + VJPEG_NATIVE_HEADER_SIZE)

enum vjpeg_result {
    VJPEG_OK = 0, VJPEG_INVALID, VJPEG_UNSUPPORTED, VJPEG_NEED_DATA,
    VJPEG_BUSY, VJPEG_BOUNDS, VJPEG_OVERLAP, VJPEG_MEMORY,
    VJPEG_CODEC, VJPEG_VERIFY, VJPEG_CANCELLED, VJPEG_NO_MEMORY
};
enum vjpeg_state { VJPEG_IDLE = 0, VJPEG_ARMED, VJPEG_RUNNING,
                   VJPEG_COMPLETE, VJPEG_FAULT };
enum vjpeg_pixel_contract { VJPEG_PIXELS_UNKNOWN = 0, VJPEG_RGB888 = 1 };
enum vjpeg_coding_contract { VJPEG_CODING_UNKNOWN = 0,
                             VJPEG_SOURCE_HEADER_422 = 1 };
enum vjpeg_access { VJPEG_READ = 1, VJPEG_WRITE = 2 };
enum vjpeg_event { VJPEG_EVENT_DONE = 1, VJPEG_EVENT_FAULT = 2,
                   VJPEG_EVENT_CANCELLED = 4 };

/* K2ac7a0 snapshot: width/height, then two 8-bit DQT arrays in JPEG zigzag order.
 * Source header fixes precision=8, IDs=1/2/3, sampling=21/11/11, Q=0/1/1,
 * source-pinned Huffman tables. The typed contract additionally requires one
 * baseline scan and restart interval zero; native scan registers remain open.
 * width/height are 1..65500 (installed codec limit).
 * Caller must establish this contract independently of uninitialized guest
 * output. No guessed quality number, native YC format or live MMIO binding.
 */
struct vjpeg_coding {
    enum vjpeg_coding_contract contract;
    uint32_t width, height;
    uint8_t quant_zigzag[2][64];
};
struct vjpeg_job {
    uint64_t source_address;
    size_t source_size;
    uint64_t destination_address; /* Effective E (FF DA), not aligned D. */
    size_t destination_capacity;
    enum vjpeg_pixel_contract pixels;
    struct vjpeg_coding coding;
};

/* Every successful probe covers the entire range. Nonzero object identifies
 * canonical backing storage, including aliases; offset is within that object.
 * The owner pins mappings until execute returns. A distinct object may not
 * alias another object. read/write return 0 only for an exact-length transfer.
 */
struct vjpeg_mapping { uint64_t object, offset; };
struct vjpeg_frame {
    enum vjpeg_pixel_contract contract;
    const uint8_t *rgb;
    size_t size, width, height, stride;
    void *lease;
};
struct vjpeg_callbacks {
    int (*probe)(void *, uint64_t, size_t, unsigned, struct vjpeg_mapping *);
    int (*read)(void *, uint64_t, void *, size_t);
    int (*write)(void *, uint64_t, const void *, size_t);
    /* On success RGB is an immutable view of the requested source range.
     * release is called exactly once, even for a malformed returned frame.
     * consumed=1 means the encoder actually attempted to read this lease;
     * it does not imply output success. On acquire failure no release occurs.
     */
    int (*acquire)(void *, uint64_t, size_t, struct vjpeg_frame *);
    void (*release)(void *, void *lease, int consumed);
    void (*irq)(void *, unsigned external_input, int level);
};
struct vjpeg_snapshot {
    enum vjpeg_state state;
    enum vjpeg_result result;
    uint32_t events; /* Explicit virtual W1C events, NOT native B+10 bits. */
    uint32_t output_length;
    unsigned fifo_count, irq_level;
};
struct vjpeg_hw;

/* All entry points are externally serialized; no private locks are taken.
 * Callbacks may inspect/cancel/ack, but may not destroy the device. Other
 * mutation during callbacks returns BUSY. Destroy is forbidden during execute
 * or from any callback. Cancellation takes effect at callback boundaries.
 * irq is only external input 29.
 */
struct vjpeg_hw *vjpeg_hw_create(const struct vjpeg_callbacks *, void *opaque);
void vjpeg_hw_destroy(struct vjpeg_hw *);
enum vjpeg_result vjpeg_hw_prepare(struct vjpeg_hw *, const struct vjpeg_job *);
enum vjpeg_result vjpeg_hw_execute(struct vjpeg_hw *);
enum vjpeg_result vjpeg_hw_cancel(struct vjpeg_hw *);
enum vjpeg_result vjpeg_hw_ack(struct vjpeg_hw *, uint32_t virtual_events);
struct vjpeg_snapshot vjpeg_hw_snapshot(const struct vjpeg_hw *);

/* Only source-pinned offsets, aligned 32-bit words or contained byte/halfword
 * reads are accepted. Start B+8 bit0 executes the explicitly prepared job;
 * registers alone cannot establish native pixels/coding and return NEED_DATA.
 * B+44/B+4c/B+40 implement a one-entry output-length FIFO. B+10/B+14 preserve
 * read/W1C behavior but no native completion/error bit is invented. Native
 * mask/target/status decoding and the QEMU adapter remain the parent's work.
 * Unsupported accesses return UNSUPPORTED; no all-success register bank.
 */
enum vjpeg_result vjpeg_hw_mmio_read(struct vjpeg_hw *, uint32_t offset,
                                    unsigned size, uint32_t *value);
enum vjpeg_result vjpeg_hw_mmio_write(struct vjpeg_hw *, uint32_t offset,
                                     unsigned size, uint32_t value);

/* Pure source-derived arithmetic, checked rather than silently wrapping. */
struct vjpeg_aif { uint32_t high, low; };
struct vjpeg_output {
    uint64_t effective, aligned;
    struct vjpeg_aif aif;
    uint16_t skip;
    uint32_t dma_capacity, threshold;
};
enum vjpeg_result vjpeg_source_address(uint64_t base, uint32_t canvas_x,
    uint32_t valid_x, uint32_t valid_y, uint32_t target_x, uint32_t target_y,
    uint64_t *address);
enum vjpeg_result vjpeg_phys_to_aif(uint64_t physical, struct vjpeg_aif *);
/* AIF decode requires the full span to belong to one source-proved range. */
enum vjpeg_result vjpeg_aif_to_phys(struct vjpeg_aif, size_t span,
                                   uint64_t *physical);
enum vjpeg_result vjpeg_output_layout(uint64_t base, uint32_t offset,
                                      uint32_t capacity, struct vjpeg_output *);
/* Produces SOI + exact original DQT/DHT/SOF prefix, no SOS or entropy.
 * Native builder itself omits SOI and writes the remaining 0x23d bytes.
 */
enum vjpeg_result vjpeg_source_prefix(const struct vjpeg_coding *,
                                     uint8_t output[VJPEG_PREFIX_SIZE]);

#ifdef __cplusplus
}
#endif
#endif
