/* SPDX-License-Identifier: MIT */
#ifndef CAPTURE_NOTIFICATIONS_H
#define CAPTURE_NOTIFICATIONS_H
#include "capture-output-memory.h"
#define CAPTURE_NOTIFY_POLICY "original-consumer-virtual-cp-jpeg-v1"
#define CAPTURE_NOTIFY_START_BYTES 24u
#define CAPTURE_NOTIFY_ENTRY_BYTES 52u
#define CAPTURE_NOTIFY_INFO_BYTES 0x2e8u
struct capture_notifications {
    struct capture_output_memory *owner;
    uint64_t lease_token,frame_token,request_fnv1a64;
    uint32_t job_scalar;
    uint8_t start[CAPTURE_NOTIFY_START_BYTES];
    uint8_t entry[CAPTURE_NOTIFY_ENTRY_BYTES];
    uint8_t info[CAPTURE_NOTIFY_INFO_BYTES];
};
/* Builds/pins only; never allocates/sends OSAL or calls AP/MPR. The caller must
 * obtain LocalTime12 from this actual job's clock (offset minutes/year/month/
 * day/hour/minute/second, reserved0, fractional0 = whole-second policy).
 * Start/entry use proven consumer shapes. Info's type4/source90030001/exact
 * bytes are an explicit functional policy; original CP1006 writer is unknown.
 * Normal single-JPEG mode/actual readiness and natural AP callback order remain
 * caller requirements. EE1001 never means saved or output resources retired. */
int capture_notifications_build(struct capture_output_memory *,const uint8_t original4038[16],
    const uint8_t actual_job_time[12],struct capture_notifications *);
/* Releases just this notification lease. Original DMM/Fsys references have
 * their own actual retirement events and remain held independently. */
int capture_notifications_release(struct capture_notifications *);
#endif
