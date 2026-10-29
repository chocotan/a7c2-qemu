#ifndef NATIVE_JPEG_BINDING_H
#define NATIVE_JPEG_BINDING_H

#include "../virtual-jpeg-hardware/jpeg-hardware.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Raw av-cam offsets, base zero; native device0 PA f3020000 / external IRQ29.
 * The original memory input's component/plane ordering and scan/restart
 * programming are not proved. START therefore fails closed, even when every
 * modeled register and table has been written. No API enables guessed pixels.
 */
enum njpeg_gap {
    NJPEG_GAP_PIXEL_LAYOUT = 1u,
    NJPEG_GAP_SCAN_RESTART = 2u,
    NJPEG_GAP_LOGICAL_GEOMETRY = 4u
};
struct njpeg_configuration {
    /* Hardware-rounded dimensions, not an unproved original prefix geometry. */
    struct vjpeg_coding coding;
    uint64_t source_address, source_dma_span, destination_aligned;
    uint64_t destination_address;
    uint32_t source_stride, source_access_width, destination_capacity;
    uint32_t destination_dma_capacity, threshold, interrupt_mask; /* B+18 word. */
    uint16_t destination_skip;
    /* Original P+28/+2c, validated against W16/H8 hardware dimensions. */
    uint32_t logical_width, logical_height;
    unsigned gaps;
};
struct njpeg_binding;
struct njpeg_binding *njpeg_create(void);
void njpeg_destroy(struct njpeg_binding *);
/* Missing writes return NEED_DATA; unsupported values return UNSUPPORTED.
 * No reads of guest prefix/data or owner memory occur in this converter.
 */
enum vjpeg_result njpeg_resolve(const struct njpeg_binding *,
                                struct njpeg_configuration *);
/* Caller supplies an immutable original P snapshot, including bytes +28..2f,
 * from the same submission as the register snapshot. No pointer is retained.
 * Source K2acd18 saves these exact u32s; K2ac7a0 writes them to SOF0.
 * Resolves logical geometry only: pixel layout and scan/restart stay blocked.
 * Output is zero on failure except forbidden overlap, which leaves it intact. */
enum vjpeg_result njpeg_resolve_parameter_geometry(const struct njpeg_binding *,
    const void *parameter, size_t bytes, struct njpeg_configuration *);
enum vjpeg_result njpeg_mmio_read(const struct njpeg_binding *, uint32_t offset,
                                  unsigned size, uint32_t *value);
enum vjpeg_result njpeg_mmio_write(struct njpeg_binding *, uint32_t offset,
                                   unsigned size, uint32_t value);
enum vjpeg_result njpeg_last_result(const struct njpeg_binding *);

/* Original K2afd30 priority table. Values are original dispatcher codes;
 * only code1/bit0 (encode success) and code3/bit2 (encode rejection) are named.
 * Other code meanings remain unproved, and are never synthesized here.
 */
#define NJPEG_ENCODE_DONE UINT32_C(1)
#define NJPEG_ENCODE_REJECTED UINT32_C(4)
unsigned njpeg_interrupt_code(uint32_t status);

/* Separate adapter for an ALREADY EXECUTED, independently supported host core.
 * It imports an actual successful vjpeg_hw object only after write/readback/
 * release; it cannot prepare or execute that core. It is NOT connected to
 * njpeg_binding: unknown native pixels can never publish success through it.
 * Owner serializes access; interrupt_mask is an explicit HOST enable gate.
 * irq_level is a proposed IRQ29 level for that supported host execution only.
 * B+18 polarity, guest GIC enables/targets and EOIR still need owner proof.
 * The borrowed core must live until W1C and FIFO-pop finish. They acknowledge
 * the underlying core too, so the same result cannot be imported twice.
 * No virtual event bit is copied to a native bit; success maps explicitly to 1.
 */
struct njpeg_completion {
    uint32_t status, length, interrupt_mask;
    unsigned fifo_count, irq_level;
    struct vjpeg_hw *owner;
};
enum vjpeg_result njpeg_completion_import(struct njpeg_completion *,
                                          struct vjpeg_hw *);
enum vjpeg_result njpeg_completion_read(const struct njpeg_completion *,
    uint32_t offset, unsigned size, uint32_t *value);
enum vjpeg_result njpeg_completion_write(struct njpeg_completion *,
    uint32_t offset, unsigned size, uint32_t value);

#ifdef __cplusplus
}
#endif
#endif
