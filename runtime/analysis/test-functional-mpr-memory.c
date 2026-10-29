/* SPDX-License-Identifier: MIT */
/* HOST_TEST fixtures exercise actual mmap/mprotect and the provider. The
 * original table writer/loader are fixtures; no Sony code executes here. */
#define FMPR_MEMORY_HOST_TEST 1
#include "functional-mpr-memory.c"
#include <assert.h>
#include <stdlib.h>
#include <sys/wait.h>

static struct area_node sentinel, sentinel_tail;
static struct area_node *fixture_root = &sentinel;
static unsigned mmap_calls, table_calls, callbacks, delegates[5];
static int binding_error, bad_table, mmap_error, force_high, missing_symbol;
static int delegate_errno, delegate_mode;
static unsigned delegate_mask, delegate_type;
static void *delegate_pointer;
static void *last_rejected;
static size_t last_rejected_size;

static void store64(void *p, uint64_t value) { memcpy(p, &value, 8); }
static void store32(void *p, uint32_t value) { memcpy(p, &value, 4); }
static void fixture_area(uint8_t *t, unsigned at, const struct area_node *n, unsigned offset, unsigned bytes) {
    store64(t + at, n->virtual_base + offset);
    store64(t + at + 8, n->iova_base + offset);
    store32(t + at + 16, bytes);
    store64(t + at + 24, n->virtual_base - n->iova_base);
}
/* Literal stores from original 2b3048..2b32c4; intentionally independent of
 * the production validation array. Python separately verifies source bytes. */
static void fixture_set_table(uint32_t group, int mode, void *out) {
    uint8_t *t = out;
    assert(mode >= 0 && mode <= 0x22 && mode != 6 && mode != 0x11);
    ++table_calls;
    for (const struct area_node *n = fixture_root; n; n = n->next) {
        if (n->group != group) continue;
        assert(n->valid && n->extent_count == 1 && n->size == n->extent_size);
        assert(n->iova_base == n->virtual_base && n->virtual_base <= UINT32_MAX);
        if (n->type == 3) fixture_area(t, 0x000, n, 0, n->size);
        else if (n->type == 4) fixture_area(t, 0x020, n, 0, n->size);
        else if (n->type == 6) {
            fixture_area(t, 0x040, n, 0x000000, 0x06d000);
            fixture_area(t, 0x060, n, 0x06d000, 0x00e000);
            fixture_area(t, 0x140, n, 0x07b000, 0x000400);
            fixture_area(t, 0x160, n, 0x07c000, 0x000400);
            fixture_area(t, 0x260, n, 0x07d000, 0x200000);
            fixture_area(t, 0x280, n, 0x27d000, 0x001400);
            fixture_area(t, 0x2a0, n, 0x27f000, 0x000400);
            fixture_area(t, 0x2c0, n, 0x280000, 0x339000);
            fixture_area(t, 0x300, n, 0x5b9000, 0x006000);
            fixture_area(t, 0x320, n, 0x5bf000, 0x003000);
            fixture_area(t, 0x640, n, 0x5c2000, 0x003000);
            fixture_area(t, 0x660, n, 0x5c5000, 0x200000);
            fixture_area(t, 0x680, n, 0x7c5000, 0x001400);
            fixture_area(t, 0x6a0, n, 0x7c7000, 0x000400);
            fixture_area(t, 0x6c0, n, 0x7c8000, 0x003000);
            fixture_area(t, 0x6e0, n, 0x7cb000, 0x200000);
            fixture_area(t, 0x700, n, 0x9cb000, 0x001400);
            fixture_area(t, 0x720, n, 0x9cd000, 0x000400);
        } else assert(0);
    }
    if (bad_table == 1) store64(t + 0x260, UINT64_C(0x7ffffffffffff000));
    if (bad_table == 2) store32(t + 0x2c0 + 16, 0);
    if (bad_table == 3) store64(t + 0x740, 1);
}
static void *fixture_select(int mode) {
    return mode < 0 || mode > 0x22 || mode == 5 || mode == 0xd ? NULL : &sentinel;
}
static bool delegate_alloc(int mode, uint32_t *group, void *table) {
    assert(errno == delegate_errno);
    ++delegates[0]; delegate_mode = mode; delegate_pointer = table;
    if (group) *group = UINT32_C(0x12345678);
    errno = E2BIG;
    return true;
}
static char delegate_free_mask(int mode, unsigned mask) {
    assert(errno == delegate_errno);
    ++delegates[1]; delegate_mode = mode; delegate_mask = mask;
    errno = EDOM;
    return (char)0x73;
}
static void delegate_free_all(int mode) {
    assert(errno == delegate_errno);
    ++delegates[2]; delegate_mode = mode; errno = ENOTTY;
}
static char delegate_info(void *address, uint32_t *unit, uint32_t *area,
    uint32_t *offset, uint64_t *iova, uint32_t *size) {
    assert(errno == delegate_errno);
    ++delegates[3]; delegate_pointer = address;
    if (unit) *unit = 31;
    if (area) *area = 32;
    if (offset) *offset = 33;
    if (iova) *iova = 34;
    if (size) *size = 35;
    errno = EINPROGRESS;
    return (char)0x7e;
}
static void delegate_fixed(unsigned type, void **physical, void **virtual_address, uint32_t *size) {
    assert(errno == delegate_errno);
    ++delegates[4]; delegate_type = type;
    if (physical) *physical = (void *)(uintptr_t)37;
    if (virtual_address) *virtual_address = (void *)(uintptr_t)38;
    if (size) *size = 39;
    errno = EOVERFLOW;
}
void *fmpr_memory_test_next(const char *name) {
    void *p = NULL;
    if (missing_symbol) return NULL;
#define FIXTURE_FUNCTION(symbol, function) do { \
    if (!strcmp(name, symbol)) { \
        __typeof__(&(function)) pointer = &(function); \
        memcpy(&p, &pointer, sizeof p); return p; \
    } \
} while (0)
    FIXTURE_FUNCTION(TABLE_SYMBOL, fixture_set_table);
    FIXTURE_FUNCTION(SELECT_SYMBOL, fixture_select);
    FIXTURE_FUNCTION(ALLOC_SYMBOL, delegate_alloc);
    FIXTURE_FUNCTION(FREE_MASK_SYMBOL, delegate_free_mask);
    FIXTURE_FUNCTION(FREE_ALL_SYMBOL, delegate_free_all);
    FIXTURE_FUNCTION(INFO_SYMBOL, delegate_info);
    FIXTURE_FUNCTION(FIXED_SYMBOL, delegate_fixed);
#undef FIXTURE_FUNCTION
    if (!strcmp(name, ROOT_SYMBOL)) return &fixture_root;
    assert(0);
    return NULL;
}
int fmpr_memory_test_binding(void) { return binding_error; }
void *fmpr_memory_test_mmap(void *hint, size_t n, int protection, int flags, int fd, off_t offset) {
    ++mmap_calls;
    assert(!(flags & MAP_FIXED));
    if (mmap_error) { errno = mmap_error; return MAP_FAILED; }
    void *p = mmap(force_high ? NULL : hint, n, protection, flags, fd, offset);
    if (p != MAP_FAILED && p != hint) { last_rejected = p; last_rejected_size = n; }
    return p;
}
static void record_event(const char *tag, const char *text) {
    assert(!strcmp(tag, "FUNCTIONAL_MPR_MEMORY"));
    assert(strstr(text, "software_identity_iova=1"));
    assert(strstr(text, "capture_verified=0"));
    assert(pthread_mutex_trylock(&mutex) == 0);
    pthread_mutex_unlock(&mutex);
    ++callbacks;
    errno = ERANGE;
}
static void enable_model(void) {
    sentinel.next = &sentinel_tail;
    sentinel.group = 123;
    sentinel_tail.group = 124;
    assert(!functional_mpr_memory_enable(record_event));
    assert(mmap_calls == 0 && table_calls == 0 && fixture_root == &sentinel);
    assert(functional_mpr_memory_enable(record_event) == -EALREADY);
}
static struct functional_mpr_memory_snapshot snapshot(void) {
    struct functional_mpr_memory_snapshot s;
    memset(&s, 0xa5, sizeof s);
    assert(!functional_mpr_memory_snapshot(&s));
    return s;
}
struct guarded_table { uint64_t before; uint8_t table[0x760]; uint64_t after; };
static void initialize(struct guarded_table *t) {
    t->before = UINT64_C(0x1234abcd5678eeff);
    t->after = UINT64_C(0xffee102030405060);
    memset(t->table, 0xa5, sizeof t->table);
}
static void canaries(const struct guarded_table *t) {
    assert(t->before == UINT64_C(0x1234abcd5678eeff));
    assert(t->after == UINT64_C(0xffee102030405060));
}
static uint32_t allocate(struct guarded_table *t, int mode) {
    struct { uint32_t before, group, after; } group = {0xaabbccdd, 0xcccccccc, 0xddccbbaa};
    initialize(t);
    errno = EOWNERDEAD;
    assert(fmpr_memory_alloc(mode, &group.group, t->table));
    assert(errno == EOWNERDEAD && group.group && group.group != 0xcccccccc);
    assert(group.before == 0xaabbccdd && group.after == 0xddccbbaa);
    canaries(t);
    return group.group;
}
static void finish(void) {
    if (active) fmpr_memory_free_all(active->mode);
    assert(!functional_mpr_memory_shutdown());
    struct functional_mpr_memory_snapshot s = snapshot();
    assert(!s.enabled && !s.active_group && !s.mapped_bytes && !s.generations && !s.leases);
    assert(fixture_root == &sentinel && sentinel.next == &sentinel_tail);
}
static void test_layout(void) {
    enable_model();
    struct guarded_table t;
    uint32_t group = allocate(&t, 3);
    assert(table_calls == 1 && generation_count == 1 && active->group == group);
    assert(snapshot().active_mask == 5 && snapshot().mapped_bytes == ARENA_BYTES);
    uint8_t expected[0x760] = {0};
    unsigned calls = table_calls;
    fixture_set_table(group, 3, expected);
    table_calls = calls;
    assert(!memcmp(expected, t.table, sizeof expected));
    for (unsigned u = 0; u < UNIT_COUNT; ++u) {
        struct area_node *n = &active->nodes[u];
        assert(n->group == group && n->unit && n->area == unit_types[u]);
        assert(!(n->virtual_base & (PAGE - 1)) && n->virtual_base + n->size <= UINT32_MAX);
        assert(n->size == capacities[u]);
        uint8_t *bytes = (void *)n->virtual_base;
        for (size_t at = 0; at < n->size; at += PAGE) {
            assert(!bytes[at]); bytes[at] = (uint8_t)(u + 1); assert(bytes[at] == u + 1);
        }
        assert(!bytes[n->size - 1]); bytes[n->size - 1] = 0xfe;
        assert(bytes[0] == u + 1 && bytes[n->size - 1] == 0xfe);
        assert(accessible(n->virtual_base - PAGE, PAGE, 0) == -EFAULT);
        assert(accessible(n->virtual_base + n->size, PAGE, 0) == -EFAULT);
        struct functional_mpr_memory_span s;
        assert(!functional_mpr_memory_query(n->virtual_base, n->size, &s));
        assert(s.group == group && s.capacity == n->size && s.offset == 0);
        assert(s.iova_base == s.virtual_base && s.unit == n->unit);
        assert(functional_mpr_memory_query(n->virtual_base + n->size - 1, 2, &s) == -ENOENT);
    }
    /* Actual StillBufConfig consumer needs T260 and writable T2a0+0x78. */
    assert(!accessible(read64(t.table + 0x260), read32(t.table + 0x270), 1));
    assert(!accessible(read64(t.table + 0x2a0), 0x78, 1));
    canaries(&t);
    finish();
}
static void test_info(void) {
    enable_model();
    struct guarded_table t;
    allocate(&t, 3);
    uint32_t unit = 0, area = 0, offset = 0, size = 0;
    uint64_t physical = 0;
    uintptr_t address = read64(t.table + 0x2c0) + 123;
    assert(fmpr_memory_get_info((void *)address, &unit, &area, &offset, &physical, &size) == 1);
    assert(unit == active->nodes[2].unit && area == 6 && offset == 0x280000 + 123);
    assert(physical == active->nodes[2].virtual_base && size == FUNCTIONAL_MPR_MEMORY_METADATA_BYTES);
    /* Original ChangeVirtToPhysAddr source formula; not a replacement export. */
    uint64_t translated = physical + offset;
    assert(translated == address && address - offset - physical == 0);
    assert(fmpr_memory_get_info((void *)address, &unit, &area, &offset, &physical, NULL) == 1);
    uint32_t before[] = {unit, area, offset, size};
    uint64_t pbefore = physical;
    assert(!fmpr_memory_get_info((void *)1, &unit, &area, &offset, &physical, &size));
    assert(errno == ENOENT && unit == before[0] && area == before[1] && offset == before[2] &&
        size == before[3] && physical == pbefore);
    assert(!fmpr_memory_get_info((void *)address, &unit, &unit, &offset, &physical, &size));
    assert(errno == EINVAL && unit == before[0] && offset == before[2] && physical == pbefore);
    assert(!fmpr_memory_get_info((void *)address, &unit, &area, NULL, &physical, &size));
    assert(errno == EFAULT && unit == before[0]);
    finish();
}
static void test_fixed(void) {
    enable_model();
    void *p = (void *)1, *v = (void *)2;
    uint32_t size = 3;
    fmpr_memory_fixed(2, &p, NULL, &size);
    assert(errno == EFAULT && mmap_calls == 0 && p == (void *)1 && size == 3);
    fmpr_memory_fixed(2, &p, &v, &size);
    assert(p == v && (uintptr_t)p <= UINT32_MAX && size == 512 && mmap_calls == 1);
    assert(snapshot().mapped_bytes == PAGE && !snapshot().generations);
    assert(!memcmp(v, (uint8_t[512]){0}, 512));
    memset(v, 0xac, 512);
    void *p2 = NULL, *v2 = NULL;
    fmpr_memory_fixed(2, &p2, &v2, &size);
    assert(p2 == p && v2 == v && mmap_calls == 1 && ((uint8_t *)v)[511] == 0xac);
    struct functional_mpr_memory_span s;
    assert(!functional_mpr_memory_query((uintptr_t)v, 512, &s));
    assert(s.capacity == 512 && !s.group && s.unit_type == 2);
    assert(functional_mpr_memory_query((uintptr_t)v, 513, &s) == -ENOENT);
    uint32_t unit, area, off;
    uint64_t physical;
    assert(fmpr_memory_get_info((uint8_t *)v + 511, &unit, &area, &off, &physical, &size));
    assert(off == 511 && physical == (uintptr_t)v && size == 512);
    struct functional_mpr_memory_lease lease;
    assert(!functional_mpr_memory_acquire((uintptr_t)v, 512, &lease));
    assert(functional_mpr_memory_shutdown() == -EBUSY);
    assert(!functional_mpr_memory_release(lease.token));
    delegate_errno = EOWNERDEAD; errno = delegate_errno;
    fmpr_memory_fixed(1, &p2, &v2, &size);
    assert(delegates[4] == 1 && delegate_type == 1 && size == 39 && errno == EOVERFLOW);
    finish();
}
static void test_retention(void) {
    enable_model();
    uintptr_t old[FUNCTIONAL_MPR_MEMORY_GENERATIONS];
    uint64_t prior_id = 0;
    struct guarded_table t;
    struct functional_mpr_memory_span span;
    for (unsigned g = 0; g < FUNCTIONAL_MPR_MEMORY_GENERATIONS; ++g) {
        uint32_t group = allocate(&t, 3);
        old[g] = read64(t.table);
        for (unsigned i = 0; i < g; ++i) assert(old[g] != old[i]);
        assert(!((uint8_t *)old[g])[17]);
        ((uint8_t *)old[g])[17] = (uint8_t)(g + 1);
        assert(!functional_mpr_memory_query(old[g], 32, &span));
        assert(span.generation > prior_id && span.group == group); prior_id = span.generation;
        assert(functional_mpr_memory_shutdown() == -EBUSY);
        fmpr_memory_free_all(3);
        assert(!active && snapshot().mapped_bytes == (uint64_t)(g + 1) * ARENA_BYTES);
        assert(functional_mpr_memory_query(old[g], 1, &span) == -ENOENT);
        for (unsigned i = 0; i <= g; ++i) assert(((uint8_t *)old[i])[17] == i + 1);
    }
    uint32_t group = 0xcccccccc;
    initialize(&t); struct guarded_table before = t;
    assert(!fmpr_memory_alloc(3, &group, t.table) && errno == ENOSPC);
    assert(group == 0xcccccccc && !memcmp(&t, &before, sizeof t));
    assert(generation_count == FUNCTIONAL_MPR_MEMORY_GENERATIONS);
    finish();
    for (unsigned g = 0; g < FUNCTIONAL_MPR_MEMORY_GENERATIONS; ++g)
        assert(accessible(old[g], 1, 0) == -EFAULT);
    assert(!functional_mpr_memory_enable(record_event));
    allocate(&t, 3);
    assert(active->id > prior_id);
    finish();
}
static void test_masks(void) {
    enable_model(); struct guarded_table t; allocate(&t, 3);
    uintptr_t es = read64(t.table), meta = read64(t.table + 0x40);
    struct functional_mpr_memory_lease es_lease, meta_lease;
    assert(!functional_mpr_memory_acquire(es, 64, &es_lease));
    assert(!functional_mpr_memory_acquire(meta, 64, &meta_lease));
    assert(!functional_mpr_memory_validate(&es_lease));
    const uint8_t pattern[8] = {1, 7, 2, 9, 3, 11, 4, 13};
    assert(!functional_mpr_memory_write(&es_lease, 5, pattern, sizeof pattern));
    assert(!memcmp((void *)(es + 5), pattern, sizeof pattern));
    assert(!fmpr_memory_free_mask(4, 7) && errno == EINVAL);
    assert(!fmpr_memory_free_mask(3, 8) && errno == EINVAL);
    assert(fmpr_memory_free_mask(3, 0) && fmpr_memory_free_mask(3, 2));
    assert(snapshot().active_mask == 5);
    assert(fmpr_memory_free_mask(3, 1));
    assert(snapshot().active_mask == 4);
    assert(functional_mpr_memory_validate(&es_lease) == -ESTALE);
    assert(functional_mpr_memory_write(&es_lease, 5, "retired!", 8) == -ESTALE);
    assert(!memcmp((void *)(es + 5), pattern, sizeof pattern));
    assert(!functional_mpr_memory_validate(&meta_lease));
    assert(!fmpr_memory_alloc(3, (uint32_t *)&t.before, t.table) && errno == EBUSY);
    assert(fmpr_memory_free_mask(3, 4));
    assert(!active && functional_mpr_memory_validate(&meta_lease) == -ESTALE);
    assert(functional_mpr_memory_shutdown() == -EBUSY);
    assert(!functional_mpr_memory_release(es_lease.token));
    assert(functional_mpr_memory_release(es_lease.token) == -ESTALE);
    assert(!functional_mpr_memory_release(meta_lease.token));
    assert(!fmpr_memory_free_mask(3, 7) && errno == ENOENT);
    finish();
}
static void test_leases(void) {
    enable_model(); struct guarded_table t; allocate(&t, 3);
    uintptr_t es = read64(t.table);
    struct functional_mpr_memory_lease writer;
    assert(!functional_mpr_memory_acquire(es, 16, &writer));
    const uint8_t input[16] = {19, 71, 3, 8, 42, 77, 1, 31, 67, 12, 9, 11, 2, 29, 5, 17};
    assert(!functional_mpr_memory_write(&writer, 0, input, sizeof input));
    assert(!memcmp((void *)es, input, sizeof input));
    assert(functional_mpr_memory_write(&writer, 0, NULL, 0) == -EINVAL);
    assert(functional_mpr_memory_write(&writer, SIZE_MAX, input, 1) == -EINVAL);
    assert(functional_mpr_memory_write(&writer, 15, input, 2) == -EINVAL);
    assert(functional_mpr_memory_write(&writer, 0, (void *)1, 16) == -EFAULT);
    assert(!memcmp((void *)es, input, sizeof input));
    assert(!functional_mpr_memory_release(writer.token));
    assert(functional_mpr_memory_write(&writer, 0, "after release", 13) == -ESTALE);
    assert(!memcmp((void *)es, input, sizeof input));
    struct functional_mpr_memory_lease all[LEASE_COUNT], before;
    for (unsigned i = 0; i < LEASE_COUNT; ++i) {
        assert(!functional_mpr_memory_acquire(es + i, 1, &all[i]));
        assert(!functional_mpr_memory_validate(&all[i]));
    }
    assert(snapshot().leases == LEASE_COUNT);
    before = all[0];
    assert(functional_mpr_memory_acquire(es, 1, &all[0]) == -ENOSPC);
    assert(!memcmp(&before, &all[0], sizeof before));
    struct functional_mpr_memory_lease tampered = all[0];
    tampered.bytes = 2; assert(functional_mpr_memory_validate(&tampered) == -ESTALE);
    tampered = all[0]; ++tampered.span.unit;
    assert(functional_mpr_memory_validate(&tampered) == -ESTALE);
    assert(!functional_mpr_memory_release(all[0].token));
    assert(!functional_mpr_memory_acquire(es, 1, &tampered));
    assert(tampered.token != all[0].token);
    for (unsigned i = 1; i < LEASE_COUNT; ++i) assert(!functional_mpr_memory_release(all[i].token));
    assert(!functional_mpr_memory_release(tampered.token));
    finish();
}
/* Original cee78..cef38: get real unit/area/offset for T260, then use
 * unit (not area or an address) in both stream fields of the 0x78 config. */
static void fixture_still_config(const struct guarded_table *t, uint8_t config[0x78]) {
    uint32_t unit, area, offset;
    uint64_t physical;
    assert(fmpr_memory_get_info((void *)(uintptr_t)read64(t->table + 0x260),
        &unit, &area, &offset, &physical, NULL));
    assert(area == 6 && physical + offset == read64(t->table + 0x260));
    memset(config, 0, 0x78);
    uint32_t size = read32(t->table + 0x270);
    store32(config + 0x54, unit);
    store32(config + 0x58, offset + 0x100dc);
    store32(config + 0x5c, size - 0x130d8);
    store32(config + 0x60, unit);
    store32(config + 0x64, offset + size - 0x2ffc);
    store32(config + 0x68, 0x2ffc);
}
/* Original I11b260..28c/35c..384, using the SAME producer's config. */
static void fixture_jpeg_output(const uint8_t config[0x78], unsigned mode, uint8_t body[0x50]) {
    memset(body, 0, 0x50);
    unsigned at = mode ? 0x60 : 0x54;
    store32(body + 0x28, read32(config + at));
    uint32_t position = read32(config + at + 4), capacity = read32(config + at + 8);
    store32(body + 0x34, position + capacity);
    store32(body + 0x38, position);
    store32(body + 0x3c, capacity);
}
static int acquire_jpeg_output(const uint8_t body[0x50], struct functional_mpr_memory_lease *lease) {
    return functional_mpr_memory_acquire_sds(read32(body + 0x24), read32(body + 0x28),
        read32(body + 0x2c) + read32(body + 0x38), read32(body + 0x3c), lease);
}
static void expect_sds_failure(int rc, uint32_t type, uint32_t handle, uint32_t offset, size_t bytes) {
    struct functional_mpr_memory_lease lease, before;
    memset(&lease, 0xa5, sizeof lease); before = lease;
    uint64_t tokens = next_token;
    assert(functional_mpr_memory_acquire_sds(type, handle, offset, bytes, &lease) == rc);
    assert(!memcmp(&lease, &before, sizeof lease) && next_token == tokens);
}
static void test_sds_output(void) {
    enable_model(); struct guarded_table t; allocate(&t, 0x13);
    uint8_t config[0x78], body[0x50]; fixture_still_config(&t, config);
    for (unsigned mode = 0; mode < 2; ++mode) {
        fixture_jpeg_output(config, mode, body);
        struct functional_mpr_memory_lease lease;
        uint32_t handle = read32(body + 0x28), position = read32(body + 0x38);
        size_t capacity = read32(body + 0x3c);
        assert(handle == active->nodes[2].unit && handle != active->nodes[2].area);
        assert(read32(body + 0x34) == position + capacity);
        assert(!acquire_jpeg_output(body, &lease));
        assert(lease.address == active->nodes[2].virtual_base + position && lease.bytes == capacity);
        assert(lease.span.unit == handle && lease.span.area == 6 && lease.span.offset == position);
        assert(lease.span.generation == active->id && !functional_mpr_memory_validate(&lease));
        uint8_t *p = (void *)lease.address;
        p[-1] = 0x17; p[capacity] = 0x73;
        const uint8_t bytes[] = {0x31, 0x67, 0x99, 0x21, 0x55};
        assert(!functional_mpr_memory_write(&lease, 3, bytes, sizeof bytes));
        assert(!memcmp(p + 3, bytes, sizeof bytes) && p[-1] == 0x17 && p[capacity] == 0x73);
        assert(!functional_mpr_memory_release(lease.token));
        /* Native p2c base offset is added to position; neither is a pointer. */
        store32(body + 0x2c, 13);
        assert(!acquire_jpeg_output(body, &lease) && lease.address == (uintptr_t)p + 13);
        assert(!functional_mpr_memory_release(lease.token));
    }
    finish();
}
static void test_sds_refusal(void) {
    enable_model(); struct guarded_table t; allocate(&t, 0x13);
    const struct area_node *n = &active->nodes[2];
    expect_sds_failure(-ENODATA, 1, n->unit, 0, 1);
    expect_sds_failure(-ENODATA, UINT32_MAX, n->unit, 0, 1);
    uint32_t foreign[] = {0, active->group, n->area, (uint32_t)n->virtual_base,
        (uint32_t)n->virtual_base + 1, n->unit + 1, UINT32_C(0x12345678)};
    for (size_t i = 0; i < sizeof foreign / sizeof *foreign; ++i)
        expect_sds_failure(-ENODATA, 0, foreign[i], 0, 1);
    expect_sds_failure(-EINVAL, 0, n->unit, 0, 0);
    expect_sds_failure(-EOVERFLOW, 0, n->unit, UINT32_MAX, 1);
    expect_sds_failure(-EOVERFLOW, 0, n->unit, 1, SIZE_MAX);
    expect_sds_failure(-ERANGE, 0, n->unit, n->size, 1);
    expect_sds_failure(-ERANGE, 0, n->unit, n->size - 1, 2);
    assert(functional_mpr_memory_acquire_sds(0, n->unit, 0, 1, NULL) == -EFAULT);
    struct functional_mpr_memory_lease lease;
    assert(!functional_mpr_memory_acquire_sds(0, n->unit, n->size - 1, 1, &lease));
    assert(lease.bytes == 1 && !functional_mpr_memory_release(lease.token));
    assert(!functional_mpr_memory_acquire_sds(0, n->unit, 0, n->size, &lease));
    assert(lease.bytes == n->size && !functional_mpr_memory_release(lease.token));
    void *p, *v; uint32_t size;
    fmpr_memory_fixed(2, &p, &v, &size);
    expect_sds_failure(-ENODATA, 0, (uint32_t)(uintptr_t)v, 0, 1);
    finish();
}
static void test_sds_retirement(void) {
    enable_model(); struct guarded_table t; allocate(&t, 0x13);
    uint32_t old = active->nodes[2].unit, es = active->nodes[0].unit;
    struct functional_mpr_memory_lease lease;
    assert(!functional_mpr_memory_acquire_sds(0, old, 19, 32, &lease));
    const uint8_t bytes[] = {23, 77, 3, 19};
    assert(!functional_mpr_memory_write(&lease, 0, bytes, sizeof bytes));
    assert(fmpr_memory_free_mask(0x13, 1));
    expect_sds_failure(-ESTALE, 0, es, 0, 1);
    assert(!functional_mpr_memory_validate(&lease));
    assert(fmpr_memory_free_mask(0x13, 4));
    expect_sds_failure(-ESTALE, 0, old, 19, 32);
    assert(functional_mpr_memory_write(&lease, 0, "stale", 4) == -ESTALE);
    assert(!memcmp((void *)lease.address, bytes, sizeof bytes));
    allocate(&t, 0x13);
    assert(active->nodes[2].unit != old);
    expect_sds_failure(-ESTALE, 0, old, 19, 32);
    uint32_t current = active->nodes[2].unit;
    /* Mutating the public node cannot register an alias or recycle an old ID. */
    active->nodes[2].unit = old;
    expect_sds_failure(-ESTALE, 0, old, 19, 32);
    expect_sds_failure(-ESTALE, 0, current, 19, 32);
    active->nodes[2].unit = current;
    uintptr_t base = active->nodes[2].virtual_base;
    ++active->nodes[2].virtual_base;
    expect_sds_failure(-ESTALE, 0, current, 19, 32);
    active->nodes[2].virtual_base = base;
    struct area_node primary = active->nodes[0];
    active->nodes[0].virtual_base = active->nodes[0].iova_base = base;
    expect_sds_failure(-ESTALE, 0, current, 19, 32);
    active->nodes[0] = primary;
    struct area_node *ours = fixture_root; fixture_root = &sentinel;
    expect_sds_failure(-ESTALE, 0, current, 19, 32);
    fixture_root = ours;
    assert(!functional_mpr_memory_release(lease.token));
    assert(!functional_mpr_memory_acquire_sds(0, current, 19, 32, &lease));
    assert(!functional_mpr_memory_validate(&lease) && !functional_mpr_memory_release(lease.token));
    finish();
    expect_sds_failure(-ENODEV, 0, current, 19, 32);
    assert(!functional_mpr_memory_enable(record_event)); allocate(&t, 0x13);
    expect_sds_failure(-ENODATA, 0, current, 19, 32);
    finish();
}
static void test_sds_capacity(void) {
    enable_model(); struct guarded_table t; allocate(&t, 0x13);
    uint32_t handle = active->nodes[2].unit;
    struct functional_mpr_memory_lease all[LEASE_COUNT];
    for (unsigned i = 0; i < LEASE_COUNT; ++i)
        assert(!functional_mpr_memory_acquire_sds(0, handle, i, 1, &all[i]));
    expect_sds_failure(-ENOSPC, 0, handle, 0, 1);
    for (unsigned i = 0; i < LEASE_COUNT; ++i) assert(!functional_mpr_memory_release(all[i].token));
    uint64_t token = next_token; next_token = UINT64_MAX;
    expect_sds_failure(-EOVERFLOW, 0, handle, 0, 1);
    next_token = token;
    finish();
}
static void test_sds_publication(void) {
    enable_model(); struct guarded_table t; initialize(&t);
    uint32_t group = 0;
    bad_table = 2;
    uint32_t unpublished = next_group + UNIT_COUNT;
    assert(!fmpr_memory_alloc(0x13, &group, t.table));
    expect_sds_failure(-ENODATA, 0, unpublished, 0, 1);
    assert(!generation_count && !snapshot().leases);
    bad_table = 0;
    sentinel.unit = next_group + 1;
    assert(!fmpr_memory_alloc(0x13, &group, t.table) && errno == EADDRINUSE);
    expect_sds_failure(-ENODATA, 0, sentinel.unit, 0, 1);
    sentinel.unit = 0;
    allocate(&t, 0x13);
    struct functional_mpr_memory_lease lease;
    assert(!functional_mpr_memory_acquire_sds(0, unpublished, 0, 1, &lease));
    assert(!functional_mpr_memory_release(lease.token));
    finish();
}
static void test_still_modes(void) {
    enable_model();
    struct guarded_table t;
    /* Original GetDmmModeId's complete table plus its default, not modes6/11. */
    for (int mode = 0x10; mode <= 0x22; ++mode) {
        if (mode == 0x11 || mode == 0x12 || mode == 0x14) continue;
        allocate(&t, mode);
        uint8_t config[0x78], body[0x50]; fixture_still_config(&t, config);
        fixture_jpeg_output(config, 0, body);
        struct functional_mpr_memory_lease lease;
        assert(!acquire_jpeg_output(body, &lease) && !functional_mpr_memory_release(lease.token));
        finish();
        if (mode != 0x22) assert(!functional_mpr_memory_enable(record_event));
    }
}
static void test_validation(void) {
    enable_model();
    struct guarded_table t; initialize(&t); struct guarded_table before = t;
    uint32_t group = 0xcccccccc;
    assert(!fmpr_memory_alloc(3, NULL, t.table) && errno == EFAULT);
    assert(!fmpr_memory_alloc(3, &group, (void *)1) && errno == EFAULT);
    assert(!fmpr_memory_alloc(3, (uint32_t *)t.table, t.table) && errno == EINVAL);
    assert(!memcmp(&t, &before, sizeof t) && group == 0xcccccccc && !mmap_calls);
    int unsupported[] = {-1, 5, 6, 0xd, 0x11, 0x23};
    for (size_t i = 0; i < sizeof unsupported / sizeof *unsupported; ++i) {
        assert(!fmpr_memory_alloc(unsupported[i], &group, t.table) && errno == ENOTSUP);
        assert(!memcmp(&t, &before, sizeof t) && group == 0xcccccccc && !mmap_calls);
    }
    void *read_only = mmap(NULL, PAGE, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(read_only != MAP_FAILED);
    assert(!fmpr_memory_alloc(3, &group, read_only) && errno == EFAULT && !mmap_calls);
    assert(!munmap(read_only, PAGE));
    struct functional_mpr_memory_span span, span_before;
    memset(&span, 0x5a, sizeof span); span_before = span;
    assert(functional_mpr_memory_query(UINTPTR_MAX - 1, 9, &span) == -EINVAL);
    assert(functional_mpr_memory_query(1, 0, &span) == -EINVAL);
    assert(!memcmp(&span, &span_before, sizeof span));
    finish();
}
static void test_rollback(void) {
    enable_model();
    struct guarded_table t; initialize(&t); struct guarded_table before = t;
    uint32_t group = 0xcccccccc;
    for (bad_table = 1; bad_table <= 3; ++bad_table) {
        assert(!fmpr_memory_alloc(3, &group, t.table) && errno == EPROTO);
        assert(!active && !generation_count && fixture_root == &sentinel);
        assert(!snapshot().mapped_bytes && group == 0xcccccccc && !memcmp(&t, &before, sizeof t));
    }
    bad_table = 0;
    allocate(&t, 3); finish();
}
static void test_collision(void) {
    void *existing = mmap((void *)next_hint, PAGE, PROT_READ | PROT_WRITE,
        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(existing == (void *)next_hint);
    memset(existing, 0xac, PAGE);
    enable_model();
    struct guarded_table t; allocate(&t, 3);
    assert(last_rejected && mmap_calls >= 2 && last_rejected_size == ARENA_BYTES);
    assert(accessible((uintptr_t)last_rejected, 1, 0) == -EFAULT);
    assert(((uint8_t *)existing)[0] == 0xac && ((uint8_t *)existing)[PAGE - 1] == 0xac);
    assert(read64(t.table) != (uintptr_t)existing);
    finish();
    assert(((uint8_t *)existing)[0] == 0xac);
    assert(!munmap(existing, PAGE));
}
static void test_mapping_failure(int high) {
    enable_model();
    struct guarded_table t; initialize(&t); struct guarded_table before = t;
    uint32_t group = 0xcccccccc;
    mmap_error = high ? 0 : ENOMEM; force_high = high;
    assert(!fmpr_memory_alloc(3, &group, t.table));
    assert(errno == (high ? ENOSPC : ENOMEM) || (high && errno == EADDRNOTAVAIL));
    assert(!memcmp(&t, &before, sizeof t) && group == 0xcccccccc && !table_calls);
    assert(!snapshot().mapped_bytes && fixture_root == &sentinel);
    if (last_rejected) assert(accessible((uintptr_t)last_rejected, 1, 0) == -EFAULT);
    finish();
}
static void test_root(void) {
    enable_model(); struct guarded_table t; allocate(&t, 3);
    fmpr_memory_free_all(3);
    struct area_node foreign = {0};
    struct area_node *ours = fixture_root;
    fixture_root = &foreign;
    assert(functional_mpr_memory_shutdown() == -ESTALE);
    assert(snapshot().enabled && snapshot().mapped_bytes == ARENA_BYTES);
    fixture_root = ours;
    struct area_node *next = ours->next; ours->next = &foreign;
    assert(functional_mpr_memory_shutdown() == -ESTALE);
    ours->next = next;
    finish();
}
static void test_binding(void) {
    binding_error = -ELIBBAD;
    assert(functional_mpr_memory_enable(record_event) == -ELIBBAD && !mmap_calls);
    binding_error = 0; missing_symbol = 1;
    assert(functional_mpr_memory_enable(record_event) == -ENOSYS && !mmap_calls);
    missing_symbol = 0;
    sentinel.valid = 1;
    assert(functional_mpr_memory_enable(record_event) == -EBUSY && !mmap_calls);
    sentinel.valid = 0; sentinel.next = &sentinel;
    assert(functional_mpr_memory_enable(record_event) == -ELOOP && !mmap_calls);
    sentinel.next = NULL;
    enable_model(); finish();
}
static void test_disabled(void) {
    uint32_t group = 0, unit = 0, area = 0, offset = 0, size = 0;
    uint64_t physical = 0;
    void *p = NULL, *v = NULL;
    delegate_errno = EOWNERDEAD; errno = delegate_errno;
    assert(fmpr_memory_alloc(-12, &group, (void *)3));
    assert(group == 0x12345678 && delegates[0] == 1 && delegate_mode == -12 &&
        delegate_pointer == (void *)3 && errno == E2BIG);
    errno = delegate_errno;
    assert(fmpr_memory_free_mask(-13, 0xdead) == (char)0x73);
    assert(delegate_mode == -13 && delegate_mask == 0xdead && errno == EDOM);
    errno = delegate_errno; fmpr_memory_free_all(-14);
    assert(delegate_mode == -14 && errno == ENOTTY);
    errno = delegate_errno;
    assert(fmpr_memory_get_info((void *)5, &unit, &area, &offset, &physical, &size) == (char)0x7e);
    assert(delegate_pointer == (void *)5 && unit == 31 && area == 32 && offset == 33 &&
        physical == 34 && size == 35 && errno == EINPROGRESS);
    errno = delegate_errno; fmpr_memory_fixed(2, &p, &v, &size);
    assert(delegate_type == 2 && p == (void *)37 && v == (void *)38 && size == 39 && errno == EOVERFLOW);
    assert(!mmap_calls && !snapshot().enabled);
    missing_symbol = 1;
    assert(!fmpr_memory_alloc(3, &group, NULL) && errno == ENOSYS);
    assert(group == 0x12345678);
}
static void test_fork(void) {
    enable_model(); struct guarded_table t; allocate(&t, 3);
    struct functional_mpr_memory_span span;
    struct functional_mpr_memory_lease lease = {0};
    pthread_mutex_lock(&mutex);
    pid_t pid = fork(); assert(pid >= 0);
    if (!pid) {
        alarm(2);
        assert(functional_mpr_memory_enable(NULL) == -ECHILD);
        assert(functional_mpr_memory_query(1, 1, &span) == -ECHILD);
        assert(functional_mpr_memory_acquire(1, 1, &lease) == -ECHILD);
        assert(functional_mpr_memory_acquire_sds(0, active->nodes[2].unit, 0, 1, &lease) == -ECHILD);
        assert(functional_mpr_memory_validate(&lease) == -ECHILD);
        assert(functional_mpr_memory_write(&lease, 0, NULL, 0) == -ECHILD);
        assert(functional_mpr_memory_release(1) == -ECHILD);
        assert(functional_mpr_memory_shutdown() == -ECHILD);
        struct functional_mpr_memory_snapshot s;
        assert(functional_mpr_memory_snapshot(&s) == -ECHILD);
        uint32_t group = 0;
        assert(!fmpr_memory_alloc(3, &group, t.table) && errno == ECHILD);
        assert(!fmpr_memory_free_mask(3, 7) && errno == ECHILD);
        fmpr_memory_free_all(3); assert(errno == ECHILD);
        fmpr_memory_fixed(0, NULL, NULL, NULL); assert(errno == ECHILD);
        assert(!fmpr_memory_get_info(NULL, NULL, NULL, NULL, NULL, NULL) && errno == ECHILD);
        _exit(0);
    }
    pthread_mutex_unlock(&mutex);
    int status; assert(waitpid(pid, &status, 0) == pid && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(active && snapshot().active_mask == 5);
    finish();
}
int main(int argc, char **argv) {
    assert(argc == 2);
    if (!strcmp(argv[1], "layout")) test_layout();
    else if (!strcmp(argv[1], "info")) test_info();
    else if (!strcmp(argv[1], "fixed")) test_fixed();
    else if (!strcmp(argv[1], "retention")) test_retention();
    else if (!strcmp(argv[1], "masks")) test_masks();
    else if (!strcmp(argv[1], "leases")) test_leases();
    else if (!strcmp(argv[1], "sds-output")) test_sds_output();
    else if (!strcmp(argv[1], "sds-refusal")) test_sds_refusal();
    else if (!strcmp(argv[1], "sds-retirement")) test_sds_retirement();
    else if (!strcmp(argv[1], "sds-capacity")) test_sds_capacity();
    else if (!strcmp(argv[1], "sds-publication")) test_sds_publication();
    else if (!strcmp(argv[1], "still-modes")) test_still_modes();
    else if (!strcmp(argv[1], "validation")) test_validation();
    else if (!strcmp(argv[1], "rollback")) test_rollback();
    else if (!strcmp(argv[1], "collision")) test_collision();
    else if (!strcmp(argv[1], "map-error")) test_mapping_failure(0);
    else if (!strcmp(argv[1], "high-map")) test_mapping_failure(1);
    else if (!strcmp(argv[1], "root")) test_root();
    else if (!strcmp(argv[1], "binding")) test_binding();
    else if (!strcmp(argv[1], "disabled")) test_disabled();
    else if (!strcmp(argv[1], "fork")) test_fork();
    else assert(0);
    return 0;
}
