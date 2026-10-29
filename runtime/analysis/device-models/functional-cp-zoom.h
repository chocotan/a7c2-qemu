/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_FUNCTIONAL_CP_ZOOM_H
#define NATIVE_FUNCTIONAL_CP_ZOOM_H
#include "cp-parameter-state.h"
#include "cp-state-publication.h"

struct functional_cp_zoom_snapshot {
    int owner_pid, data_rc, free_rc;
    unsigned int initialized, busy, guard_held, faults, requests;
    unsigned int config_consumed, oneway_consumed, request_freed, free_attempted;
    unsigned int metadata_source, destination, caller;
    unsigned int semantic_applied, published, generation, capture;
    long sender_tid, free_tid;
    void *original_request, *retained_request;
    uint64_t wire_fnv1a64;
    unsigned char wire[CP_PARAMETER_ZOOM_BYTES];
    struct cp_parameter_zoom_readback data;
};
/* Local binding only, after parameter owner init; no construction/RPC/import.
 * Main owns lifetime and serialization of the actual shared parameter owner. */
int functional_cp_zoom_owner_init(struct cp_parameter_state *);
/* Explicit functional profile, actual standalone idle requests:
 * drive=0/trigger=0; both speed bytes are retained without a physical rate map.
 * Data guard is supplied by main under the existing resource reservation.
 * Missing/invalid data or guard returns handled=1/result<0, caller still owns.
 * After the data transaction succeeds the request belongs to this owner and
 * result=0, including a failed original free. Sticky fault retains that pointer
 * and blocks reuse; oneway_consumed=1 only after the one real free returns0.
 * No allocation, send, ACK, host model operation or optical motion occurs.
 * After free0, a strictly newer source sequence may reuse the same address. */
int functional_cp_zoom_dispatch(unsigned int, void *, const struct full_imaging_io *,
    const struct native_cp_state_publication_guard *, const struct cp_start_state_guard *,
    int enabled, int *result);
/* Suppress a repeated free of the still-owned original pointer. A retired
 * diagnostic address does not own unrelated later OSAL messages. Failed free
 * is never retried implicitly; sticky fault and retained pointer stay visible. */
int functional_cp_zoom_release(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result);
void functional_cp_zoom_snapshot(struct functional_cp_zoom_snapshot *);
#endif
