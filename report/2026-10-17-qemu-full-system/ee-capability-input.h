#ifndef NEWEE_CAPABILITY_INPUT_H
#define NEWEE_CAPABILITY_INPUT_H
#include <stddef.h>
#include <stdint.h>

/* Fixed CP f5a47758..., VA=file+0x108000. Byte views are little endian. */
enum ee_input_status { EE_INPUT_OK, EE_INPUT_UNKNOWN, EE_INPUT_INVALID, EE_INPUT_STALE };
struct ee_adc_sample {
    const uint8_t *data;
    size_t bytes;
    uint64_t sampled_at, generation;
    unsigned selector, known, calibrated, virtual_input_state;
};
/* state is the caller-owned original 16-byte/row snapshot, never inferred from Backup. */
int ee_adc_consume(uint8_t *rows, size_t rows_bytes, uint8_t *state, size_t state_bytes,
                   unsigned state_known, const struct ee_adc_sample samples[2],
                   uint64_t now, uint64_t max_age);
int ee_adc_read_key(const uint8_t *rows, size_t rows_bytes, const uint8_t *state,
                    size_t state_bytes, uint32_t keycode, uint32_t *value);

enum ee_gate {
    EE_GATE_CURRENT = 1, EE_GATE_BACKUP = 2, EE_GATE_POLICY = 4,
    EE_GATE_FORCE = 8, EE_GATE_BE9BAE = 16, EE_GATE_OBJECT = 32,
    EE_GATE_TRIGGER = 64
};
enum ee_decision { EE_REJECT_UNKNOWN, EE_REJECT_INVALID, EE_TRIGGER_INACTIVE,
                   EE_NORMAL_SPINAL_OFF, EE_CONTINUE_EE };
struct ee_normal_inputs {
    unsigned known; /* bits CURRENT..OBJECT only; no bit can grant publication */
    uint32_t current[2];
    const uint8_t *backup_00030162;
    size_t backup_bytes;
    uint32_t policy_00030a01, object_110c;
    uint8_t force_e0, be9bae_byte9, object_10bf;
};
struct ee_normal_result {
    unsigned decision, unknown_gates, reason, raw_candidate_valid, raw_candidate;
    unsigned can_publish; /* Always zero: original 19fbf0 consumption is unproved. */
};
struct ee_normal_result ee_normal_select(const struct ee_normal_inputs *in);
#endif
