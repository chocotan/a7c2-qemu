/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_FUNCTIONAL_CAMERA_EVENTS_H
#define NATIVE_FUNCTIONAL_CAMERA_EVENTS_H

/* Parent calls only in its enabled functional profile, after outermost actual
 * OSAL receive success and at actual OSAL free; never for synthetic callbacks.
 * No enable setter: the parent's actual-handler gate remains default off.
 * Capture the backend's cycle ticket at receive; free reuses that immutable
 * event ticket. ACK tickets follow the original sender through the imaging
 * worker's promise handoff; notice tickets remain bound to their receiver.
 * Only handled=1 receives activate tickets; pending reservations cannot free.
 * Backend still validates wire bytes and ownership. Duplicate active events
 * return -EALREADY; a full five-entry ledger returns -ENOSPC without eviction.
 * Returns backend handling (receive: 0/unhandled, 1/accepted, negative/refused;
 * release: 0/unowned, 1/handled with *result); only the backend calls real_free.
 * Receive preserves errno; release leaves backend/real-free errno intact.
 * No packet/allocator/queue ABI change and no claim of AP consumption here.
 * shortcut: a post-free alias after a fresh receive for the same freeing thread
 * at the same address is indistinguishable with the plain-pointer OSAL ABI; upgrade only
 * if the native transport gains an event identity beyond its pointer. */
int functional_camera_events_observe_receive(unsigned int destination, void *pointer,
    unsigned int source, unsigned int bytes);
int functional_camera_events_release(unsigned int destination, void *pointer,
    int (*real_free)(unsigned int, void *),
    void (*record)(const char *, const char *), int *result);

#endif
