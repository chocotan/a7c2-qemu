/* SPDX-License-Identifier: MIT */
#ifndef EE_NORMAL_WAKE_COLD_H
#define EE_NORMAL_WAKE_COLD_H
#include <sys/types.h>
#include "ee-capability-input.h"
#include "imaging-device.h"
#define EE_NWC_PROFILE "virtual-normal-wake-cold-v1"
#define EE_NWC_DEST 0x80020002u
#define EE_NWC_SOURCE 0x90bf0274u
#define EE_NWC_BACKUP_SHA "9d1e03129a8216c101f653acd406c890c8488e5440c0892ec3dda6f5e0e0da92"
#define EE_NWC_BANK_SHA "657dc090bf08010c0a079fc40080270989fe979c734de86570dc78e56de0feaf"
#define EE_NWC_CP_SHA "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428"
enum ee_nwc_status {
    EE_NWC_OK=0, EE_NWC_DISABLED, EE_NWC_INVALID, EE_NWC_OWNER,
    EE_NWC_GENERATION, EE_NWC_UNKNOWN, EE_NWC_DUPLICATE, EE_NWC_NOT_ARMED,
    EE_NWC_INPUT, EE_NWC_NO_DELIVERY, EE_NWC_ALLOCATE, EE_NWC_TRANSPORT,
    EE_NWC_LEASE, EE_NWC_READER, EE_NWC_FREE, EE_NWC_BUSY
};
enum ee_nwc_initial_bit {
    EE_NWC_FORCE=1, EE_NWC_BE9=2, EE_NWC_STATE=4, EE_NWC_CALIBRATION=8,
    EE_NWC_INITIAL_ALL=15
};
/* The adapter verifies the helper envelope SHA/size against its launch assets.
 * These are the unchanged raw records from that verified complete AP+CP file. */
struct ee_nwc_assets {
    pid_t pid;
    uint64_t generation;
    const char *backup_sha256, *cp_bank_sha256, *cp_sha256;
    size_t cp_bank_offset;
    unsigned verified, keymap_group;
    const uint8_t *rows;
    size_t rows_bytes;
    uint8_t backup_00030162[64], policy_00030a01[4], config_0092001c[4];
};
/* v1 has explicit functional-platform initial state only, never CP history.
 * Every initial input must have both its known and model_defined bit set. */
struct ee_nwc_initial {
    pid_t pid;
    uint64_t generation;
    unsigned known, model_defined;
    const char *provenance;
    uint8_t force_e0, be9bae_byte9;
    const uint8_t *stable_state;
    size_t stable_bytes;
};
/* Zero preserves the original callback-only API default. */
enum ee_nwc_admission_source { EE_NWC_CALLBACK=0, EE_NWC_KERNELDEFAULT=1 };
struct ee_nwc_init {
    pid_t pid;
    uint64_t generation;
    int fd;
    uintptr_t mapping, allocator;
    uint32_t bytes, pool0, pool1, dynamic_id;
    unsigned abi_verified, fd_verified, map_verified;
};
struct ee_nwc_prime {
    pid_t pid;
    uint64_t generation, message_generation, receive_event, free_event;
    uintptr_t message, receiver_tid, free_actor_tid;
    uint32_t source;
    int size, receive_rc, free_rc;
    unsigned source_known, size_known, free_returned;
};
/* Called after the real wait-lock unlock; callback and kernel receive admissions
 * retain independent evidence. No kernel receipt can imply registration rc0. */
struct ee_nwc_gate {
    pid_t pid;
    uint64_t generation;
    uintptr_t consumer, promise, reader;
    uint64_t registration_event, unlock_event;
    unsigned observer_installed, consumer_registered, wait_unlocked;
    unsigned notification_id;
    int registration_rc;
    enum ee_nwc_admission_source admission_source;
    uintptr_t waiter_tid;
    struct ee_nwc_init init;
    struct ee_nwc_prime prime;
};
struct ee_nwc_lease {
    pid_t pid;
    uint64_t generation;
    uintptr_t message;
    unsigned destination, source, bytes;
    uint8_t wire[12];
    uint64_t message_generation;
};
struct ee_nwc_receive { struct ee_nwc_lease lease; uintptr_t consumer; };
struct ee_nwc_reader {
    pid_t pid;
    uint64_t generation;
    uintptr_t reader, promise;
    unsigned notification_id, returned, output;
};
/* Copy lease metadata at free entry; report this only after real free returns. */
struct ee_nwc_free { struct ee_nwc_lease lease; unsigned owner; int rc; uintptr_t free_actor_tid; };
struct ee_nwc_snapshot {
    pid_t pid;
    uint64_t generation;
    unsigned constructed, configured, first_cold, armed, attempted, busy;
    unsigned allocated, send_called, send_returned, received, reader_returned;
    unsigned free_returned, retired, pending, fault, last_rejected;
    unsigned free_begun, owned_copy, wait_returned;
    uintptr_t free_actor_tid;
    unsigned initial_known, model_defined, object_110c, object_10bf;
    unsigned current[2], adc_status, reader_output, free_owner;
    int allocate_rc, send_rc, free_rc;
    char provenance[96];
    struct ee_normal_result selection;
    struct ee_nwc_gate gate;
    struct ee_nwc_lease lease;
    struct ee_nwc_receive receive_observed;
    struct ee_nwc_reader reader_observed;
    struct ee_nwc_free free_observed;
};
struct ee_nwc;
/* NULL/unknown profiles return DISABLED and leave *out NULL; nothing auto-starts.
 * Keep exactly one service per observer PID/launch generation. */
int ee_nwc_create(struct ee_nwc **out, const char *profile, pid_t pid,
                  uint64_t generation, const struct full_imaging_io *io);
int ee_nwc_configure(struct ee_nwc *, const struct ee_nwc_assets *, const struct ee_nwc_initial *);
int ee_nwc_arm(struct ee_nwc *, const struct ee_nwc_gate *);
int ee_nwc_trigger(struct ee_nwc *, uint64_t generation,
                   const struct ee_adc_sample samples[2], uint64_t now, uint64_t max_age);
int ee_nwc_observe_receive(struct ee_nwc *, const struct ee_nwc_receive *);
int ee_nwc_observe_reader(struct ee_nwc *, const struct ee_nwc_reader *);
int ee_nwc_observe_free(struct ee_nwc *, const struct ee_nwc_free *);
/* Only the exact alive native allocation can be CPU-read, under the same private
 * lock that seals its borrow before native free. Arbitrary passive reads stay unknown. */
int ee_nwc_copy_owned(struct ee_nwc *, const struct ee_nwc_lease *, unsigned native_size, uint8_t out[12]);
int ee_nwc_free_begin(struct ee_nwc *, const struct ee_nwc_lease *);
int ee_nwc_fail(struct ee_nwc *, int reason);
int ee_nwc_init_valid(const struct ee_nwc_init *, pid_t, uint64_t);
int ee_nwc_span(const struct ee_nwc_init *, uintptr_t, size_t);
int ee_nwc_observe_wait(struct ee_nwc *, pid_t, uint64_t, uintptr_t promise, uintptr_t waiter_tid);
int ee_nwc_snapshot(struct ee_nwc *, struct ee_nwc_snapshot *);
/* Caller first quiesces all callbacks. Pending ownership requires a non-NULL
 * handoff snapshot: ownership/errors transfer to caller, never auto-free. */
int ee_nwc_destroy(struct ee_nwc *, struct ee_nwc_snapshot *handoff);
#endif
