/* SPDX-License-Identifier: MIT */
#ifndef FULL_HDMI_UPM_RECEIPT_H
#define FULL_HDMI_UPM_RECEIPT_H
#include <stddef.h>
#include <stdint.h>

#define FULL_HDMI_UPM_MAILBOX_MAGIC UINT32_C(0x4d505548)
#define FULL_HDMI_UPM_MAILBOX_VERSION 1u
#define FULL_HDMI_UPM_MAILBOX_PAGE 4096u
#define FULL_HDMI_UPM_MAILBOX_BYTES 256u
#define FULL_HDMI_UPM_MAILBOX_PROOF 0x7fu
#define FULL_HDMI_UPM_RECEIPT_ERROR (-1021)
enum full_hdmi_upm_mailbox_status {
    FULL_HDMI_UPM_UNARMED=0, FULL_HDMI_UPM_ARMED=1,
    FULL_HDMI_UPM_REQUEST=2, FULL_HDMI_UPM_RECEIPT=3
};
/* Frozen ABI v1: all integer fields LITTLE ENDIAN, offsets in comments.
 * One record occupies the first 256 bytes of one dedicated pinned 4K page.
 * The host arms status=1 only after validating/arming original breakpoints.
 * Guest publishes status=2 before send; host writes status=3 LAST, after the
 * complete actual native bridge/receive/consumer/branch/free/allocator/return.
 * stage_mask bits 0..6 correspond to those seven events, exactly 0x7f.
 * digest is FNV-1a-64 (offset cbf29ce484222325, prime 100000001b3) over
 * bytes [0,20) + [24,152) + [160,256); status and digest are excluded.
 * No receipt may authorize a second free or write hardware/ready state.
 */
struct full_hdmi_upm_mailbox {
    uint32_t magic, version;                 /* 0,4 */
    uint64_t nonce;                          /* 8 */
    uint32_t owner_pid, status;              /* 16,20 */
    uint64_t lease, user_pointer;            /* 24,32 */
    unsigned char raw[16], effective[16];    /* 40,56 */
    uint64_t kernel_pointer, receiver_task;  /* 72,80 */
    uint32_t receiver_tid; int32_t free_rc;   /* 88,92 */
    uint32_t ref_before, allocator_seen;     /* 96,100: must both be 1 */
    uint32_t stage_mask, index;              /* 104,108: index 0 then 1 */
    uint64_t consumer_pc, free_return_pc;    /* 112,120: upm+126e8,+14c */
    uint64_t mapping_user_base;              /* 128 */
    uint64_t mapping_kernel_base;            /* 136 */
    uint32_t native_producer_tid, reserved0; /* 144,148 */
    uint64_t digest;                         /* 152 */
    uint64_t upm_text, osal_text;             /* 160,168: actual bases */
    uint32_t source, queue, message_bytes;   /* 176,180,184 */
    uint32_t body_source;                    /* 188 */
    uint64_t allocator_pc;                   /* 192: osal+4720/4768/478c */
    uint64_t bridge_seq, free_seq;           /* 200,208: strictly ordered */
    uint64_t producer_task;                  /* 216 */
    unsigned char reserved[32];             /* 224..255: zero */
};
_Static_assert(sizeof(struct full_hdmi_upm_mailbox)==256, "mailbox ABI size");
_Static_assert(offsetof(struct full_hdmi_upm_mailbox,status)==20, "status ABI");
_Static_assert(offsetof(struct full_hdmi_upm_mailbox,digest)==152, "digest ABI");
_Static_assert(offsetof(struct full_hdmi_upm_mailbox,upm_text)==160, "bases ABI");
_Static_assert(offsetof(struct full_hdmi_upm_mailbox,reserved)==224, "reserved ABI");

/* stage 0: prepare/await armed, BEFORE real send. stage 1: await/verify receipt,
 * AFTER successful real send, before any next allocation. 0=success, -1021=fault.
 * raw/effective are immutable copies, never dereferenced from the freed pointer.
 * Exactly two transactions, raw op 0/2 and effective op 0/3, in that order.
 * Page is retained until owner exit. There is deliberately no cleanup/free API.
 * record(tag,text) is required. Both waits are bounded to 10 guest seconds.
 */
int full_hdmi_upm_receipt(unsigned int stage, unsigned long long lease,
    void *pointer, const unsigned char raw[16], const unsigned char effective[16],
    void (*record)(const char *,const char *));

#ifdef FULL_HDMI_UPM_RECEIPT_TEST
/* Pure snapshot validator only: synthetic host-test records are not VM proof. */
int full_hdmi_upm_receipt_validate(const void *snapshot, size_t bytes,
    const struct full_hdmi_upm_mailbox *expected);
#endif
#endif
