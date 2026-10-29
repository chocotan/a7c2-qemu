/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_OUTPUT_POLICY_H
#define NATIVE_CP_OUTPUT_POLICY_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

#define CP_OUTPUT_POLICY_BYTES 20u
#define CP_OUTPUT_POLICY_SOURCE UINT32_C(0x80020002)
#define CP_OUTPUT_POLICY_TARGET UINT32_C(0x90030001)
#define CP_OUTPUT_POLICY_STATUS_KNOWN UINT32_C(1)
#define CP_OUTPUT_POLICY_AE_SMOOTHING_KNOWN UINT32_C(2)
#define CP_OUTPUT_POLICY_INTERVAL_KNOWN UINT32_C(4)
#define CP_OUTPUT_POLICY_SHUT_LOW_LIMIT_KNOWN UINT32_C(8)
#define CP_OUTPUT_POLICY_KNOWN_MASK UINT32_C(15)

/* Public CP SHA256 f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428,
 * 18090880 bytes: ONLY VA [108000,1248b80) maps to raw VA-108000.
 * Record 10fab8c + 224*20 = 10fbd0c: {40f9,35a135,0,0,364c69}.
 * Handler 35a134..35a17c reads u8 +8/+9, LE32 +12/+16, then stores
 * zero-extended values to RAM 165a720+184/+188/+18c/+190. The only call
 * is debug logging b4457a. Checker 364c68..364ce8 compares these four
 * fields when its mode is 1; it does not validate ranges or start hardware.
 * RAM addresses are annotations, never offsets into the firmware file.
 * Dispatcher 35cf70..35d090 calls the setter and, for record+8==0,
 * 996fec..996ffa merely sets a local dirty byte. No success reply is built.
 * The unsupported-opcode reply at 35d010 is outside this admitted path.
 */
struct cp_output_policy_snapshot {
    uint32_t known_mask;
    uint32_t interval_rec_status, interval_rec_ae_smoothing;
    uint32_t interval_rec_interval, interval_rec_shut_low_limit;
    unsigned char bytes[CP_OUTPUT_POLICY_BYTES];
    bool config_consumed;
    bool semantic_applied, published, cp_native, ee, capture;
};

/* Explicit host-local interval-recording configuration owner. No transport,
 * original CP RAM writes, pending completion, generation, or hardware apply.
 * All five completion/effect flags above remain false. config_consumed means
 * only the four source-proven setter assignments were made to this owner.
 * Init has known_mask==0: initialized zero storage is NOT known CP data.
 * Caller serializes access and keeps input readable and stable until return.
 */
struct cp_output_policy {
    pid_t owner_pid;
    bool enabled;
    struct cp_output_policy_snapshot state;
};
enum cp_output_policy_result { CP_OUTPUT_POLICY_CONFIG_CONSUMED = 1 };

int cp_output_policy_init(struct cp_output_policy *, bool enabled);
/* Exact source/target/type5/40f9/20B only. +1/+4..7/+10..11 remain opaque
 * input bytes, including a nonzero cookie or padding. Repeated valid calls
 * replace local configuration; all errors leave the complete owner unchanged.
 * Input must not overlap any owner storage. Fork requires a fresh init.
 */
int cp_output_policy_stage(struct cp_output_policy *, uint32_t source,
                           uint32_t target, const void *input, size_t size);
/* Copy readback, with a required-known field mask. Unsupported mask bits
 * return -ENOTSUP; unavailable fields return -ENODATA, including before stage
 * with mask==0. Output must not overlap owner storage. Errors preserve output.
 * This readback is local virtual configuration, not CP/EE/hardware state.
 */
int cp_output_policy_snapshot(const struct cp_output_policy *,
                              uint32_t required_known_mask,
                              struct cp_output_policy_snapshot *output);
#endif
