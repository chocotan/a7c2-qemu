/* SPDX-License-Identifier: MIT */
#include "raw-template.h"
#include <errno.h>
#include <unistd.h>

static uint64_t le(const uint8_t *p, size_t n)
{
    uint64_t v = 0;
    for (size_t i = 0; i < n; ++i) v |= (uint64_t)p[i] << (8 * i);
    return v;
}
static void put(uint8_t *p, uint64_t v, size_t n)
{
    for (size_t i = 0; i < n; ++i) p[i] = (uint8_t)(v >> (8 * i));
}
static int equal(const uint8_t *a, const uint8_t *b, size_t n)
{
    for (size_t i = 0; i < n; ++i) if (a[i] != b[i]) return 0;
    return 1;
}
static const uint8_t original_entry[24] = {2, 1, 0, 0, 3};
static int scope_matches(const struct raw_template_scope *a,
                         const struct raw_template_scope *b)
{
    return a->libmpr_base == b->libmpr_base && a->job == b->job &&
        a->raw_object == b->raw_object && a->pid == b->pid &&
        a->owns == b->owns && a->context == b->context;
}
static int check(const struct raw_template_scope *s, void *app, uintptr_t shadow)
{
    static const uint8_t site[16] = {
        0xe0,0x03,0x14,0xaa,0x02,0x41,0x81,0xd2,
        0x01,0x00,0x80,0x52,0x6f,0x15,0xf8,0x97
    };
    if (!s || !s->libmpr_base || !s->job || !s->raw_object || !s->owns ||
        !app || sizeof(uintptr_t) != 8) return -EINVAL;
    if (s->pid != getpid()) return -ECHILD;
    if (s->libmpr_base > UINTPTR_MAX - 0x2fd680 ||
        (uintptr_t)app > UINTPTR_MAX - 0x26e0 ||
        (uintptr_t)s->raw_object > UINTPTR_MAX - 0x14d8) return -EOVERFLOW;
    /* Validate owner/mappings BEFORE dereferencing either native object. */
    if (s->owns(s->context, s->job, s->raw_object, app) != 1) return -ESTALE;
    const uint8_t *base = (const uint8_t *)s->libmpr_base;
    const uint8_t *raw = s->raw_object;
    if (!equal(base + 0x277c58, site, sizeof site) ||
        !equal(base + 0x2deeb0, original_entry, sizeof original_entry)) return -ELIBBAD;
    uintptr_t raw_vptr = le(raw, 8);
    if ((raw_vptr != s->libmpr_base + 0x2fb6e0 &&
         (!shadow || raw_vptr != shadow)) ||
        le(raw + 0x1488, 8) != (uintptr_t)app ||
        le(base + 0x2fb6f8, 8) != s->libmpr_base + 0x268f5c ||
        le(app, 8) != s->libmpr_base + 0x2fbcf0 ||
        le(base + 0x2fbd30, 8) != s->libmpr_base + 0x277b7c ||
        le(base + 0x2fbd38, 8) != s->libmpr_base + 0x278af0) return -ELIBBAD;
    return 0;
}
int raw_template_after_memset(struct raw_template_lease *lease,
                              const struct raw_template_scope *s,
                              void *destination, int value, size_t bytes,
                              uintptr_t caller)
{
    if (!lease || !s) return -EINVAL;
    if (s->libmpr_base > UINTPTR_MAX - 0x277c68) return -EOVERFLOW;
    if (caller != s->libmpr_base + 0x277c68) return -ENOMSG;
    if (value || bytes != 0xa08 || (uintptr_t)destination < 0x1be8) return -EPROTO;
    void *app = (void *)((uintptr_t)destination - 0x1be8);
    int rc = check(s, app, lease->raw_vtable);
    if (rc) return rc;
    if (lease->active) return -EBUSY;
    uint8_t *entry = (uint8_t *)app + 0x1a38;
    if (!equal(entry, original_entry, sizeof original_entry)) return -EPROTO;
    lease->scope = *s;
    lease->app_object = app;
    for (size_t i = 0; i < sizeof lease->saved; ++i) lease->saved[i] = entry[i];
    lease->serialized_short14 = 0;
    lease->short14[0] = 14;
    lease->short14[1] = 0;
    /* Publish the data pointer before enabling the original count-zero entry. */
    put(entry + 16, (uintptr_t)lease->short14, 8);
    put(entry + 8, 1, 4);
    lease->active = 1;
    if (le(entry, 4) != 0x102 || le(entry + 4, 4) != 3 ||
        le(entry + 8, 4) != 1 || le(entry + 12, 4) != 0 ||
        le(entry + 16, 8) != (uintptr_t)lease->short14 ||
        le(lease->short14, 2) != 14) return -EIO;
    return 0;
}
int raw_template_restore(struct raw_template_lease *lease,
                         const struct raw_template_scope *current)
{
    if (!lease || !current || !lease->active) return -EINVAL;
    if (!scope_matches(&lease->scope, current)) return -ESTALE;
    if (!equal(lease->saved, original_entry, sizeof lease->saved)) return -EPROTO;
    int rc = check(current, lease->app_object, lease->raw_vtable);
    if (rc) return rc;
    uint8_t *entry = (uint8_t *)lease->app_object + 0x1a38;
    /* Native @26c444 replaces the source pointer with the TIFF inline value. */
    uintptr_t data = le(entry + 16, 8);
    if (le(entry, 4) != 0x102 || le(entry + 4, 4) != 3 ||
        le(entry + 8, 4) != 1 || le(entry + 12, 4) != 0 ||
        (data != (uintptr_t)lease->short14 &&
         (!lease->serialized_short14 || data != lease->serialized_short14)) ||
        le(lease->short14, 2) != 14) return -EPROTO;
    put(entry + 8, 0, 4);
    for (size_t i = 0; i < sizeof lease->saved; ++i) entry[i] = lease->saved[i];
    if (!equal(entry, lease->saved, sizeof lease->saved)) return -EIO;
    lease->active = 0;
    return 0;
}
