#ifndef SONY_CCF_H
#define SONY_CCF_H

#include <stdbool.h>
#include <stdint.h>

#define SONY_CCF_SCU_BASE UINT64_C(0xf1388000)

struct sony_ccf_state {
    uint32_t gates[9];
    uint32_t mux[3];
    uint32_t dividers[5];
    uint32_t resets[8];
};

/* Virtual TEST reset policy; silicon reset values are unknown. NULL is a no-op. */
void sony_ccf_init(struct sony_ccf_state *state);
/* Only aligned 32-bit accesses are accepted. Failure changes nothing. */
bool sony_ccf_read(struct sony_ccf_state *state, uint64_t physical,
                   unsigned size, uint32_t *out);
bool sony_ccf_write(struct sony_ccf_state *state, uint64_t physical,
                    unsigned size, uint32_t value);

#endif
