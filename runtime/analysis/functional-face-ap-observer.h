/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_FACE_AP_OBSERVER_H
#define FUNCTIONAL_FACE_AP_OBSERVER_H
#include <stddef.h>
#include <stdint.h>
#define FUNCTIONAL_FACE_AP_DMM UINT32_C(0x0061003c)
enum functional_face_ap_event { FACE_AP_SUBMIT=1, FACE_AP_SEND_RETURN, FACE_AP_RECEIVE, FACE_AP_FREE_RETURN, FACE_AP_RETAINED };
/* Thread-confined passive evidence. This owns NO message or native allocation,
 * creates NO pin/byte-access capability and never changes a transport result. */
struct functional_face_ap_birth {
    uint32_t unit, handle, observations, ambiguous, any_free_observed, reply_source;
    uint64_t observation_sequence;
};
struct functional_face_ap_observer {
    int owner_pid;
    int64_t sender_tid;
    uint64_t sequence, dropped;
    uint32_t active, source, op, unit, handle, send_seen, received, free_attempts;
    int send_result, free_result;
    uintptr_t request, reply;
    uint32_t reply_source, reply_bytes;
    unsigned char request_wire[40], reply_wire[40];
    struct functional_face_ap_birth births[4];
};
typedef void (*functional_face_ap_record)(enum functional_face_ap_event, const struct functional_face_ap_observer *);
/* caller_verified must come from the parent's real original-code byte checks.
 * A retained transaction is not overwritten. Failure leaves original IO alone. */
int functional_face_ap_begin(struct functional_face_ap_observer *, int explicit_enabled, int caller_verified,
    int64_t actual_tid, uint32_t destination, uint32_t source, const void *request, size_t bytes,
    functional_face_ap_record);
void functional_face_ap_sent(struct functional_face_ap_observer *, int64_t, int actual_result, functional_face_ap_record);
void functional_face_ap_received(struct functional_face_ap_observer *, int64_t, uint32_t queue,
    uint32_t actual_source, void *reply, size_t actual_bytes, int original_receive_result, functional_face_ap_record);
/* Call AFTER the actual original free. Never dereferences the freed pointer. */
void functional_face_ap_freed(struct functional_face_ap_observer *, int64_t, uint32_t queue,
    void *reply, int actual_result, functional_face_ap_record);
/* Saved original birth FACTS only, never refreshed from a current raw handle.
 * any_free_observed records this thread only; absence is NOT a liveness proof.
 * It does not distinguish owner-drop from allocation retirement. Caller still
 * needs an actual retained owner and validated mapping. observation_sequence
 * is NOT the kernel allocation epoch. */
int functional_face_ap_observed_birth(const struct functional_face_ap_observer *, int64_t,
    uint32_t unit, uint32_t full_handle, struct functional_face_ap_birth *);
#endif
