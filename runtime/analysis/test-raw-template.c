/* SPDX-License-Identifier: MIT */
#include "raw-template.h"
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
struct owner { void *raw, *app; uint64_t job; int live; };
static int owns(void *context, uint64_t job, void *raw, void *app)
{
    struct owner *o = context;
    return o->live && job == o->job && raw == o->raw && app == o->app;
}
static void ptr(void *destination, uintptr_t value)
{
    unsigned char *p = destination;
    for (unsigned i = 0; i < 8; ++i) p[i] = (unsigned char)(value >> (8 * i));
}
int main(void)
{
    unsigned char *base = calloc(1, 0x2fd680), *raw = calloc(1, 0x14d8);
    unsigned char *app = calloc(1, 0x26e0);
    assert(base && raw && app && sizeof(uintptr_t) == 8);
    const unsigned char code[16] = {0xe0,3,0x14,0xaa,2,0x41,0x81,0xd2,1,0,0x80,0x52,0x6f,0x15,0xf8,0x97};
    const unsigned char entry[24] = {2,1,0,0,3};
    memcpy(base + 0x277c58, code, sizeof code);
    memcpy(base + 0x2deeb0, entry, sizeof entry);
    memcpy(app + 0x1a38, entry, sizeof entry);
    uintptr_t b = (uintptr_t)base;
    ptr(raw, b + 0x2fb6e0); ptr(raw + 0x1488, (uintptr_t)app);
    ptr(app, b + 0x2fbcf0); ptr(base + 0x2fb6f8, b + 0x268f5c);
    ptr(base + 0x2fbd30, b + 0x277b7c); ptr(base + 0x2fbd38, b + 0x278af0);
    struct owner owner = {raw, app, 7, 1};
    struct raw_template_scope scope = {b, 7, raw, getpid(), owns, &owner};
    struct raw_template_lease lease = {0};
    assert(raw_template_after_memset(&lease, &scope, app + 0x1be8, 0, 0xa08, b) == -ENOMSG);
    owner.live = 0;
    assert(raw_template_after_memset(&lease, &scope, app + 0x1be8, 0, 0xa08, b + 0x277c68) == -ESTALE);
    assert(!memcmp(app + 0x1a38, entry, sizeof entry));
    owner.live = 1; base[0x277c58] ^= 1;
    assert(raw_template_after_memset(&lease, &scope, app + 0x1be8, 0, 0xa08, b + 0x277c68) == -ELIBBAD);
    base[0x277c58] ^= 1;
    assert(raw_template_after_memset(&lease, &scope, app + 0x1be8, 0, 0xa08, b + 0x277c68) == 0);
    assert(app[0x1a40] == 1 && lease.active && lease.short14[0] == 14 && !lease.short14[1]);
    assert(raw_template_after_memset(&lease, &scope, app + 0x1be8, 0, 0xa08, b + 0x277c68) == -EBUSY);
    struct raw_template_scope stale = scope; ++stale.job;
    assert(raw_template_restore(&lease, &stale) == -ESTALE);
    app[0x1a3c] ^= 1;
    assert(raw_template_restore(&lease, &scope) == -EPROTO && lease.active);
    app[0x1a3c] ^= 1;
    assert(raw_template_restore(&lease, &scope) == 0 && !lease.active);
    assert(!memcmp(app + 0x1a38, entry, sizeof entry));
    assert(raw_template_after_memset(&lease, &scope, app + 0x1be8, 0, 0xa08, b + 0x277c68) == 0);
    unsigned char inline14[4] = {14, 0, 0, 0}, foreign[4] = {14, 0, 0, 0};
    ptr(app + 0x1a48, (uintptr_t)inline14);
    /* An inline-looking pointer is insufficient until its exact owner is checked. */
    assert(raw_template_restore(&lease, &scope) == -EPROTO && lease.active);
    lease.serialized_short14 = (uintptr_t)inline14;
    ptr(app + 0x1a48, (uintptr_t)foreign);
    assert(raw_template_restore(&lease, &scope) == -EPROTO && lease.active);
    ptr(app + 0x1a48, (uintptr_t)inline14);
    app[0x1a38] ^= 1;
    assert(raw_template_restore(&lease, &scope) == -EPROTO && lease.active);
    app[0x1a38] ^= 1;
    assert(raw_template_restore(&lease, &scope) == 0 && !lease.active);
    assert(!memcmp(app + 0x1a38, entry, sizeof entry));
    assert(raw_template_after_memset(&lease, &scope, app + 0x1be8, 0, 0xa08, b + 0x277c68) == 0);
    assert(!lease.serialized_short14);
    assert(raw_template_restore(&lease, &scope) == 0);
    free(app); free(raw); free(base);
    return 0;
}
