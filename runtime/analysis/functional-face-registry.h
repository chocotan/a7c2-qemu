/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_FACE_REGISTRY_H
#define FUNCTIONAL_FACE_REGISTRY_H
#include "functional-face-dmm.h"

/* Separate software namespace; no implicit CP-to-AP physical translation. */
#define FUNCTIONAL_FACE_REGISTRY_IOVA UINT64_C(0x70000000)
#define FUNCTIONAL_FACE_REGISTRY_WINDOW UINT64_C(0x100000)

/* One process-owned CP registry, initially empty. Export does not reset entries
 * or registration identities. These callbacks belong exclusively to face DMM:
 * it owns mmap backing and drains all reference/borrow/transport leases before
 * unregister. No callback or logger is invoked under this registry's mutex. */
int functional_face_registry_callbacks(struct functional_face_dmm_registry *);

struct functional_face_registry_inspection {
    struct functional_face_dmm_descriptor original;
    struct functional_face_dmm_descriptor current;
};
/* Diagnostics only: requires the entire saved creator descriptor (reference=0),
 * never a wire handle or snapshot lookup. Does not acquire a byte-access lease.
 * Every consumer MUST use face_dmm_borrowed_span, write/read, release_borrow;
 * logical is a software IOVA, never a pointer or a guest/MMIO mapping. */
int functional_face_registry_inspect_span(const struct functional_face_dmm_descriptor *,
    struct functional_face_registry_inspection *);
#endif
