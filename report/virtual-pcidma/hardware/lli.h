/* Bounded virtual eDMA linked-list consumer; not a PCIe link/firmware gate. */
#ifndef SONY_EDMA_LLI_H
#define SONY_EDMA_LLI_H
#include <stddef.h>
#include <stdint.h>
enum sony_edma_domain { SONY_EDMA_LOCAL, SONY_EDMA_PCI };
struct sony_edma_bus {
    void *opaque;
    int (*read)(void *, enum sony_edma_domain, uint64_t, void *, size_t);
    int (*write)(void *, enum sony_edma_domain, uint64_t, const void *, size_t);
};
enum sony_edma_result { SONY_EDMA_PAUSED, SONY_EDMA_FAULT, SONY_EDMA_UNSUPPORTED,
                        SONY_EDMA_BUDGET, SONY_EDMA_BAD_INPUT };
struct sony_edma_outcome {
    enum sony_edma_result result;
    uint64_t next, bytes;
    unsigned phase, entries, local_interrupt, write_fault;
};
/* write_direction=1 is local->PCI; 0 is PCI->local. The descriptor list is
 * in the original arch_va_to_phys local address domain. No address coercion.
 * max_steps/max_bytes are explicit diagnostic bounds, not silicon limits.
 */
struct sony_edma_outcome sony_edma_consume(const struct sony_edma_bus *, uint64_t,
    unsigned phase, unsigned write_direction, unsigned max_steps, uint64_t max_bytes);
struct sony_edma_outcome sony_edma_copy(const struct sony_edma_bus *, uint64_t source,
    uint64_t target, uint32_t length, unsigned write_direction, uint64_t max_bytes);
#endif
