/* SPDX-License-Identifier: MIT */
#ifndef A7C2_RAW_TEMPLATE_H
#define A7C2_RAW_TEMPLATE_H
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

/* Caller serializes each lease and retains it at a stable address until native
 * teardown. owns must verify the live capture job, RAW object, app allocation
 * (0x26e0 bytes), writable mapping and DMM generation; 1 means verified. */
struct raw_template_scope {
    uintptr_t libmpr_base;
    uint64_t job;
    void *raw_object;
    pid_t pid;
    int (*owns)(void *context, uint64_t job, void *raw_object, void *app_object);
    void *context;
};
struct raw_template_lease {
    struct raw_template_scope scope;
    void *app_object;
    /* Optional pinned instance shadow, whose ownership must be checked by owns. */
    uintptr_t raw_vtable;
    uint8_t saved[24];
    uint8_t short14[2];
    /* Exact inline SHORT destination verified by the native writer at teardown. */
    uintptr_t serialized_short14;
    unsigned active;
};

/* Invoke AFTER delegated memset, with its ORIGINAL caller return address.
 * 0 = changed and read back, -ENOMSG = unrelated call, other negative = refuse.
 * The lease must be zero initialized. This does not install a libc hook. */
int raw_template_after_memset(struct raw_template_lease *,
                              const struct raw_template_scope *,
                              void *destination, int value, size_t bytes,
                              uintptr_t caller);
/* Invoke while both objects are live, BEFORE original teardown. Success means
 * original instance bytes were restored, not that ARW was generated/written.
 * Restore before invoking either native destructor; never let native teardown
 * observe short14 as an owned allocation. */
int raw_template_restore(struct raw_template_lease *,
                         const struct raw_template_scope *);
#endif
