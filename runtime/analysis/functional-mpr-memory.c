/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-mpr-memory.h"
#include <dlfcn.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

/* The public guest libc is 2.25; recent cross headers redirect sscanf to C23. */
extern int fmpr_memory_sscanf(const char *, const char *, ...) __asm__("__isoc99_sscanf");

#define PAGE 4096u
#define UNIT_COUNT 3u
#define LEASE_COUNT 64u
#define ARENA_BYTES (FUNCTIONAL_MPR_MEMORY_MAIN_BYTES + \
    FUNCTIONAL_MPR_MEMORY_SECONDARY_BYTES + FUNCTIONAL_MPR_MEMORY_METADATA_BYTES + 4u * PAGE)
#define ALLOC_SYMBOL "_ZN3mpr10DmmMemInfo14AllocDmmMemoryEiPjPNS0_11BufferTableE"
#define FREE_MASK_SYMBOL "_ZN3mpr10DmmMemInfo13FreeDmmMemoryEij"
#define FREE_ALL_SYMBOL "_ZN3mpr10DmmMemInfo13FreeDmmMemoryEi"
#define INFO_SYMBOL "_ZN3mpr10DmmMemInfo11GetUnitInfoEPvPjS2_S2_PmS2_"
#define FIXED_SYMBOL "_ZN3mpr6memory12GetFixedAreaENS0_13FixedAreaTypeEPPvS3_Pj"
#define TABLE_SYMBOL "_ZN3mpr10DmmMemInfo9SetMemTblEjiPNS0_11BufferTableE"
#define SELECT_SYMBOL "_ZN3mpr10DmmMemInfo19UnitTypeTableSelectEi"
#define ROOT_SYMBOL "_ZN3mpr10DmmMemInfo19mp_AreaExtListStartE"

struct area_node {
    uint32_t type, group, unit, area;
    struct area_node *next;
    uint32_t extent_count, reserved;
    uintptr_t virtual_base;
    uint32_t size;
    uint8_t valid, padding[3];
    uintptr_t iova_base;
    uint32_t extent_size, tail;
};
_Static_assert(sizeof(uintptr_t) == 8, "original MPR requires the 64-bit ABI");
_Static_assert(offsetof(struct area_node, next) == 0x10, "node link ABI");
_Static_assert(offsetof(struct area_node, extent_count) == 0x18, "node count ABI");
_Static_assert(offsetof(struct area_node, virtual_base) == 0x20, "node virtual ABI");
_Static_assert(offsetof(struct area_node, valid) == 0x2c, "node validity ABI");
_Static_assert(offsetof(struct area_node, iova_base) == 0x30, "node IOVA ABI");
_Static_assert(sizeof(struct area_node) == 0x40, "one real extent per node");

typedef void (*table_fn)(uint32_t, int, void *);
typedef void *(*select_fn)(int);
struct original_binding {
    table_fn set_table;
    select_fn select_mode;
    struct area_node **root;
};
struct generation {
    void *mapping;
    uint64_t id;
    uint32_t group;
    int mode;
    struct area_node nodes[UNIT_COUNT];
    struct functional_mpr_memory_span sds[UNIT_COUNT];
};
struct subarea { unsigned table, offset, size; };
/* Complete type6 default branch, including the original still-config areas. */
static const struct subarea metadata[] = {
    {0x040, 0x000000, 0x06d000}, {0x060, 0x06d000, 0x00e000},
    {0x140, 0x07b000, 0x000400}, {0x160, 0x07c000, 0x000400},
    {0x260, 0x07d000, 0x200000}, {0x280, 0x27d000, 0x001400},
    {0x2a0, 0x27f000, 0x000400}, {0x2c0, 0x280000, 0x339000},
    {0x300, 0x5b9000, 0x006000}, {0x320, 0x5bf000, 0x003000},
    {0x640, 0x5c2000, 0x003000}, {0x660, 0x5c5000, 0x200000},
    {0x680, 0x7c5000, 0x001400}, {0x6a0, 0x7c7000, 0x000400},
    {0x6c0, 0x7c8000, 0x003000}, {0x6e0, 0x7cb000, 0x200000},
    {0x700, 0x9cb000, 0x001400}, {0x720, 0x9cd000, 0x000400}
};
static const unsigned unit_types[UNIT_COUNT] = {3, 4, 6};
/* Original CnvAreaId2ModeSubArea(type): types3/4 use bit1, type6 bit4. */
static const unsigned unit_masks[UNIT_COUNT] = {1, 1, 4};
static const unsigned capacities[UNIT_COUNT] = {
    FUNCTIONAL_MPR_MEMORY_MAIN_BYTES, FUNCTIONAL_MPR_MEMORY_SECONDARY_BYTES,
    FUNCTIONAL_MPR_MEMORY_METADATA_BYTES
};
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic pid_t owner;
static _Atomic int enabled;
static struct original_binding original;
static struct generation generations[FUNCTIONAL_MPR_MEMORY_GENERATIONS];
static struct generation *active;
static struct functional_mpr_memory_lease leases[LEASE_COUNT];
static unsigned generation_count;
static uint64_t next_generation = 1, next_token = 1;
static uint32_t next_group = UINT32_C(0xf1000000);
static uintptr_t next_hint = UINT32_C(0x20000000);
static void *fixed_mapping;
static uint64_t fixed_generation;
static struct area_node *saved_root, *published_root;
static int published, closing;
static void (*record_callback)(const char *, const char *);

static int process_guard(void) {
    pid_t pid = getpid(), expected = 0;
    atomic_compare_exchange_strong_explicit(&owner, &expected, pid,
        memory_order_acq_rel, memory_order_acquire);
    return atomic_load_explicit(&owner, memory_order_acquire) == pid ? 0 : -ECHILD;
}
static int api_guard(void) {
    int rc = process_guard();
    return rc ? rc : atomic_load_explicit(&enabled, memory_order_acquire) ? 0 : -ENODEV;
}
static int valid_span(uintptr_t p, size_t n) {
    return p && n && n <= UINTPTR_MAX - p;
}
static int disjoint(uintptr_t a, size_t an, uintptr_t b, size_t bn) {
    return a + an <= b || b + bn <= a;
}
static int accessible(uintptr_t p, size_t n, int write) {
    if (!valid_span(p, n)) return -EFAULT;
    FILE *f = fopen("/proc/self/maps", "r");
    if (!f) return -errno;
    char line[512], perms[5];
    unsigned long lo, hi;
    uintptr_t next = p, end = p + n;
    while (next < end && fgets(line, sizeof line, f)) {
        if (fmpr_memory_sscanf(line, "%lx-%lx %4s", &lo, &hi, perms) != 3) continue;
        if (next < lo) break;
        if (next >= hi) continue;
        if (perms[0] != 'r' || (write && perms[1] != 'w')) break;
        next = hi < end ? hi : end;
    }
    int rc = next == end ? 0 : -EFAULT;
    if (fclose(f) && !rc) rc = -errno;
    return rc;
}
static int outputs(void *const *p, const size_t *sizes, size_t count) {
    for (size_t i = 0; i < count; ++i) {
        int rc = accessible((uintptr_t)p[i], sizes[i], 1);
        if (rc) return rc;
        for (size_t j = 0; j < i; ++j)
            if (!disjoint((uintptr_t)p[i], sizes[i], (uintptr_t)p[j], sizes[j])) return -EINVAL;
    }
    return 0;
}
static void *next_symbol(const char *symbol) {
    int saved = errno;
#ifdef FMPR_MEMORY_HOST_TEST
    extern void *fmpr_memory_test_next(const char *);
    void *p = fmpr_memory_test_next(symbol);
#else
    void *p = dlsym(RTLD_NEXT, symbol);
#endif
    errno = saved;
    return p;
}
#define LOAD_FUNCTION(target, name) do { \
    void *fmpr_symbol_ = next_symbol(name); \
    _Static_assert(sizeof(target) == sizeof(fmpr_symbol_), "POSIX function pointer ABI"); \
    memcpy(&(target), &fmpr_symbol_, sizeof(target)); \
} while (0)

static uint64_t fnv(const void *pointer, size_t bytes) {
    const uint8_t *p = pointer;
    uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; ++i) { h ^= p[i]; h *= UINT64_C(1099511628211); }
    return h;
}
#ifndef FMPR_MEMORY_HOST_TEST
static int verify_binding(const struct original_binding *b) {
    struct pin { uintptr_t va; size_t bytes; uint64_t fnv; };
    static const struct pin pins[] = {
        {0x2b2be0, 0x858, UINT64_C(0x3b6dfcdbaabf7769)},
        {0x2b273c, 0x1a8, UINT64_C(0xb674767f3a94b06a)},
        {0x2e0eb4, 0x023, UINT64_C(0x92ddae20189f8dfb)},
        {0x2e0ed8, 0x02e, UINT64_C(0x8dd9ff5b75cdf3ac)},
        {0x2b2920, 0x050, UINT64_C(0xc44e08fa79c60490)},
        {0x2b2b6c, 0x074, UINT64_C(0x15d7076b4ea4f2c3)},
        {0xcee2c, 0x184, UINT64_C(0xca74699d6f05d6e9)}
    };
    Dl_info info;
    void *writer = NULL, *selector = NULL;
    memcpy(&writer, &b->set_table, sizeof writer);
    memcpy(&selector, &b->select_mode, sizeof selector);
    if (!dladdr(writer, &info) || !info.dli_fbase) return -ELIBBAD;
    uintptr_t base = (uintptr_t)info.dli_fbase;
    if (base > UINTPTR_MAX - 0x3d8300 || (uintptr_t)writer != base + 0x2b2be0 ||
        (uintptr_t)selector != base + 0x2b273c || (uintptr_t)b->root != base + 0x3d82f8)
        return -ELIBBAD;
    for (size_t i = 0; i < sizeof pins / sizeof *pins; ++i) {
        int rc = accessible(base + pins[i].va, pins[i].bytes, 0);
        if (rc || fnv((void *)(base + pins[i].va), pins[i].bytes) != pins[i].fnv) return -ELIBBAD;
    }
    return accessible((uintptr_t)b->root, sizeof *b->root, 1);
}
#endif
static int bind_original(struct original_binding *b) {
    memset(b, 0, sizeof *b);
    LOAD_FUNCTION(b->set_table, TABLE_SYMBOL);
    LOAD_FUNCTION(b->select_mode, SELECT_SYMBOL);
    b->root = next_symbol(ROOT_SYMBOL);
    if (!b->set_table || !b->select_mode || !b->root) return -ENOSYS;
#ifdef FMPR_MEMORY_HOST_TEST
    extern int fmpr_memory_test_binding(void);
    return fmpr_memory_test_binding();
#else
    return verify_binding(b);
#endif
}
static int inactive_root(struct area_node *node) {
    struct area_node *seen[128];
    size_t count = 0;
    while (node) {
        if ((uintptr_t)node % _Alignof(struct area_node)) return -EFAULT;
        if (count == sizeof seen / sizeof *seen) return -ELOOP;
        for (size_t i = 0; i < count; ++i) if (seen[i] == node) return -ELOOP;
        int rc = accessible((uintptr_t)node, sizeof *node, 0);
        if (rc) return rc;
        if (node->valid) return -EBUSY;
        seen[count++] = node;
        node = node->next;
    }
    return 0;
}
static int root_intact(void) {
    if (*original.root != (published ? published_root : saved_root)) return -ESTALE;
    for (unsigned g = 0; g < generation_count; ++g)
        for (unsigned u = 0; u < UNIT_COUNT; ++u) {
            struct area_node *next = u + 1 < UNIT_COUNT ? &generations[g].nodes[u + 1] :
                g ? &generations[g - 1].nodes[0] : saved_root;
            if (generations[g].nodes[u].next != next) return -ESTALE;
        }
    return 0;
}
static uint64_t mapped_bytes_locked(void) {
    uint64_t bytes = fixed_mapping ? PAGE : 0;
    for (unsigned g = 0; g < generation_count; ++g)
        if (generations[g].mapping) bytes += ARENA_BYTES;
    return bytes;
}
static uint32_t active_mask(void) {
    unsigned mask = 0;
    if (active) for (unsigned i = 0; i < UNIT_COUNT; ++i)
        if (active->nodes[i].valid) mask |= unit_masks[i];
    return mask;
}
static int contains(uintptr_t base, size_t capacity, uintptr_t p, size_t n) {
    return valid_span(p, n) && p >= base && p - base < capacity && n <= capacity - (p - base);
}
static int query_locked(uintptr_t address, size_t bytes, struct functional_mpr_memory_span *out) {
    if (!valid_span(address, bytes)) return -EINVAL;
    if (closing || !atomic_load_explicit(&enabled, memory_order_relaxed)) return -ENODEV;
    if (fixed_mapping && contains((uintptr_t)fixed_mapping, FUNCTIONAL_MPR_MEMORY_FIXED_BYTES, address, bytes)) {
        *out = (struct functional_mpr_memory_span){
            .virtual_base = (uintptr_t)fixed_mapping, .iova_base = (uintptr_t)fixed_mapping,
            .generation = fixed_generation, .capacity = FUNCTIONAL_MPR_MEMORY_FIXED_BYTES,
            .offset = address - (uintptr_t)fixed_mapping, .unit_type = 2
        };
        return 0;
    }
    if (active) for (unsigned i = 0; i < UNIT_COUNT; ++i) {
        const struct area_node *n = &active->nodes[i];
        if (n->valid && contains(n->virtual_base, n->size, address, bytes)) {
            *out = (struct functional_mpr_memory_span){
                .virtual_base = n->virtual_base, .iova_base = n->iova_base,
                .generation = active->id, .capacity = n->size,
                .offset = address - n->virtual_base, .group = n->group,
                .unit = n->unit, .area = n->area, .unit_type = n->type
            };
            return 0;
        }
    }
    return -ENOENT;
}
/* No fixed replacement: a refused hint unmaps only its new return mapping. */
static void *map_low(size_t bytes, int protection) {
    for (unsigned attempt = 0; attempt < 64; ++attempt) {
        uintptr_t hint = next_hint;
        if (hint > UINT32_C(0xf0000000) || bytes > UINT32_C(0xf0000000) - hint) {
            errno = ENOSPC;
            return MAP_FAILED;
        }
        next_hint += (bytes + PAGE - 1) / PAGE * PAGE + PAGE;
#ifdef FMPR_MEMORY_HOST_TEST
        extern void *fmpr_memory_test_mmap(void *, size_t, int, int, int, off_t);
        void *p = fmpr_memory_test_mmap((void *)hint, bytes, protection, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
#else
        void *p = mmap((void *)hint, bytes, protection, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
#endif
        if (p == MAP_FAILED) return MAP_FAILED;
        if ((uintptr_t)p == hint && !(hint & (PAGE - 1)) && bytes <= (uint64_t)UINT32_MAX + 1 - hint) return p;
        int saved = errno;
        if (munmap(p, bytes)) return MAP_FAILED;
        errno = saved;
    }
    errno = EADDRNOTAVAIL;
    return MAP_FAILED;
}
static int reserve_generation(struct generation *g, int mode, uint32_t group) {
    void *p = map_low(ARENA_BYTES, PROT_NONE);
    if (p == MAP_FAILED) return -errno;
    uintptr_t start = (uintptr_t)p + PAGE;
    memset(g, 0, sizeof *g);
    g->mapping = p;
    g->id = next_generation++;
    g->group = group;
    g->mode = mode;
    for (unsigned u = 0; u < UNIT_COUNT; ++u) {
        if (mprotect((void *)start, capacities[u], PROT_READ | PROT_WRITE)) {
            int rc = -errno;
            munmap(p, ARENA_BYTES);
            memset(g, 0, sizeof *g);
            return rc;
        }
        g->nodes[u] = (struct area_node){
            .type = unit_types[u], .group = group, .unit = group + u + 1,
            .area = unit_types[u], .extent_count = 1, .virtual_base = start,
            .size = capacities[u], .valid = 1, .iova_base = start,
            .extent_size = capacities[u]
        };
        g->nodes[u].next = u + 1 < UNIT_COUNT ? &g->nodes[u + 1] : *original.root;
        start += capacities[u] + PAGE;
    }
    return 0;
}
static uint64_t read64(const void *p) { uint64_t v; memcpy(&v, p, sizeof v); return v; }
static uint32_t read32(const void *p) { uint32_t v; memcpy(&v, p, sizeof v); return v; }
static int table_entry(const uint8_t *t, unsigned at, uintptr_t p, unsigned bytes) {
    return read64(t + at) == p && read64(t + at + 8) == p &&
        read32(t + at + 16) == bytes && !read32(t + at + 20) && !read64(t + at + 24);
}
static int validate_table(const struct generation *g, const uint8_t *t) {
    if (!table_entry(t, 0, g->nodes[0].virtual_base, capacities[0]) ||
        !table_entry(t, 0x20, g->nodes[1].virtual_base, capacities[1])) return -EPROTO;
    for (size_t i = 0; i < sizeof metadata / sizeof *metadata; ++i)
        if (!table_entry(t, metadata[i].table, g->nodes[2].virtual_base + metadata[i].offset,
            metadata[i].size)) return -EPROTO;
    for (unsigned at = 0; at < FUNCTIONAL_MPR_MEMORY_TABLE_BYTES; at += 0x20) {
        uintptr_t v = read64(t + at);
        uint64_t p = read64(t + at + 8), correction = read64(t + at + 24);
        unsigned bytes = read32(t + at + 16);
        if (!v) { if (p || bytes || correction || read32(t + at + 20)) return -EPROTO; continue; }
        int owned = 0;
        for (unsigned u = 0; u < UNIT_COUNT; ++u)
            if (contains(g->nodes[u].virtual_base, g->nodes[u].size, v, bytes)) owned = 1;
        if (!owned || v != p || correction || read32(t + at + 20)) return -EPROTO;
        int expected = at == 0 || at == 0x20;
        for (size_t i = 0; i < sizeof metadata / sizeof *metadata; ++i)
            if (at == metadata[i].table) expected = 1;
        if (!expected) return -EPROTO;
    }
    return 0;
}
static void note(void (*callback)(const char *, const char *), const char *operation,
    int rc, uint64_t generation, uint32_t group, uint64_t bytes) {
    if (!callback) return;
    int saved = errno;
    char message[224];
    snprintf(message, sizeof message,
        "operation=%s rc=%d generation=%" PRIu64 " group=%u mapped_bytes=%" PRIu64
        " software_identity_iova=1 physical_asic_verified=0 capture_verified=0",
        operation, rc, generation, group, bytes);
    callback("FUNCTIONAL_MPR_MEMORY", message);
    errno = saved;
}

int functional_mpr_memory_enable(void (*record)(const char *, const char *)) {
    int rc = process_guard();
    if (rc) return rc;
    pthread_mutex_lock(&mutex);
    if (atomic_load_explicit(&enabled, memory_order_relaxed)) rc = -EALREADY;
    else if (sysconf(_SC_PAGESIZE) != PAGE) rc = -ENOTSUP;
    else {
        struct original_binding b;
        rc = bind_original(&b);
        if (!rc) rc = accessible((uintptr_t)b.root, sizeof *b.root, 1);
        if (!rc) rc = inactive_root(*b.root);
        if (!rc) {
            original = b;
            saved_root = *b.root;
            published_root = NULL;
            published = closing = 0;
            record_callback = record;
            atomic_store_explicit(&enabled, 1, memory_order_release);
        }
    }
    pthread_mutex_unlock(&mutex);
    return rc;
}

bool fmpr_memory_alloc(int, uint32_t *, void *) __asm__(ALLOC_SYMBOL);
bool fmpr_memory_alloc(int mode, uint32_t *group, void *table) {
    int saved = errno, rc = process_guard();
    if (rc) { errno = -rc; return false; }
    if (!atomic_load_explicit(&enabled, memory_order_acquire)) {
        bool (*delegate)(int, uint32_t *, void *) = NULL;
        LOAD_FUNCTION(delegate, ALLOC_SYMBOL);
        if (!delegate) { errno = ENOSYS; return false; }
        errno = saved;
        return delegate(mode, group, table);
    }
    void *out[] = {group, table};
    const size_t sizes[] = {sizeof *group, FUNCTIONAL_MPR_MEMORY_TABLE_BYTES};
    rc = outputs(out, sizes, 2);
    if (rc) { errno = -rc; return false; }
    pthread_mutex_lock(&mutex);
    if (closing || !atomic_load_explicit(&enabled, memory_order_relaxed)) rc = -ENODEV;
    else if (active) rc = -EBUSY;
    else if (mode < 0 || mode > 0x22 || mode == 6 || mode == 0x11) rc = -ENOTSUP;
    else if (!original.select_mode(mode)) rc = -ENOTSUP;
    else if (generation_count == FUNCTIONAL_MPR_MEMORY_GENERATIONS) rc = -ENOSPC;
    else if (next_generation == UINT64_MAX || next_group > UINT32_MAX - 8) rc = -EOVERFLOW;
    else if ((rc = root_intact()) == 0 && (rc = inactive_root(*original.root)) == 0) {
        uint32_t id = next_group;
        for (struct area_node *n = *original.root; n; n = n->next)
            if ((n->group >= id && n->group <= id + 3) ||
                (n->unit > id && n->unit <= id + UNIT_COUNT)) { rc = -EADDRINUSE; break; }
        struct generation *g = &generations[generation_count];
        if (!rc) rc = reserve_generation(g, mode, id);
        if (!rc) {
            uint8_t candidate[FUNCTIONAL_MPR_MEMORY_TABLE_BYTES] = {0};
            struct area_node *prior = *original.root;
            *original.root = &g->nodes[0];
            original.set_table(id, mode, candidate);
            rc = validate_table(g, candidate);
            if (rc) {
                *original.root = prior;
                munmap(g->mapping, ARENA_BYTES);
                memset(g, 0, sizeof *g);
            } else {
                /* Original GetStillBufConfig stores node+8's unit directly in
                 * config+54/+60; JPEG uses it as the type0 SDS handle. */
                for (unsigned u = 0; u < UNIT_COUNT; ++u) {
                    const struct area_node *n = &g->nodes[u];
                    g->sds[u] = (struct functional_mpr_memory_span){
                        .virtual_base = n->virtual_base, .iova_base = n->iova_base,
                        .generation = g->id, .capacity = n->size, .group = n->group,
                        .unit = n->unit, .area = n->area, .unit_type = n->type
                    };
                }
                memcpy(table, candidate, sizeof candidate);
                memcpy(group, &id, sizeof id);
                active = g;
                ++generation_count;
                next_group += 8;
                published = 1;
                published_root = &g->nodes[0];
            }
        }
    }
    void (*callback)(const char *, const char *) = record_callback;
    uint64_t generation = active ? active->id : 0;
    uint32_t id = active ? active->group : 0;
    uint64_t bytes = mapped_bytes_locked();
    pthread_mutex_unlock(&mutex);
    note(callback, "allocate", rc, generation, id, bytes);
    errno = rc ? -rc : saved;
    return !rc;
}
static int retire_locked(int mode, unsigned mask) {
    if (closing || !atomic_load_explicit(&enabled, memory_order_relaxed)) return -ENODEV;
    if (!active) return -ENOENT;
    if (active->mode != mode) return -EINVAL;
    if (mask & ~7u) return -EINVAL;
    int rc = root_intact();
    if (rc) return rc;
    /* shortcut: retired generations stay mapped; collect only after original
     * MPR/Fsys drain proof is wired into the parent's coordinated shutdown. */
    for (unsigned u = 0; u < UNIT_COUNT; ++u)
        if (unit_masks[u] & mask) active->nodes[u].valid = 0;
    if (!active_mask()) active = NULL;
    return 0;
}
char fmpr_memory_free_mask(int, unsigned) __asm__(FREE_MASK_SYMBOL);
char fmpr_memory_free_mask(int mode, unsigned mask) {
    int saved = errno, rc = process_guard();
    if (rc) { errno = -rc; return 0; }
    if (!atomic_load_explicit(&enabled, memory_order_acquire)) {
        char (*delegate)(int, unsigned) = NULL;
        LOAD_FUNCTION(delegate, FREE_MASK_SYMBOL);
        if (!delegate) { errno = ENOSYS; return 0; }
        errno = saved;
        return delegate(mode, mask);
    }
    pthread_mutex_lock(&mutex);
    uint64_t generation = active ? active->id : 0;
    uint32_t group = active ? active->group : 0;
    rc = retire_locked(mode, mask);
    void (*callback)(const char *, const char *) = record_callback;
    uint64_t bytes = mapped_bytes_locked();
    pthread_mutex_unlock(&mutex);
    note(callback, "retire", rc, generation, group, bytes);
    errno = rc ? -rc : saved;
    return rc ? 0 : 1;
}
void fmpr_memory_free_all(int) __asm__(FREE_ALL_SYMBOL);
void fmpr_memory_free_all(int mode) {
    int saved = errno, rc = process_guard();
    if (rc) { errno = -rc; return; }
    if (!atomic_load_explicit(&enabled, memory_order_acquire)) {
        void (*delegate)(int) = NULL;
        LOAD_FUNCTION(delegate, FREE_ALL_SYMBOL);
        if (!delegate) { errno = ENOSYS; return; }
        errno = saved;
        delegate(mode);
        return;
    }
    (void)fmpr_memory_free_mask(mode, 7);
}
char fmpr_memory_get_info(void *, uint32_t *, uint32_t *, uint32_t *, uint64_t *, uint32_t *) __asm__(INFO_SYMBOL);
char fmpr_memory_get_info(void *address, uint32_t *unit, uint32_t *area,
    uint32_t *offset, uint64_t *iova, uint32_t *size) {
    int saved = errno, rc = process_guard();
    if (rc) { errno = -rc; return 0; }
    if (!atomic_load_explicit(&enabled, memory_order_acquire)) {
        char (*delegate)(void *, uint32_t *, uint32_t *, uint32_t *, uint64_t *, uint32_t *) = NULL;
        LOAD_FUNCTION(delegate, INFO_SYMBOL);
        if (!delegate) { errno = ENOSYS; return 0; }
        errno = saved;
        return delegate(address, unit, area, offset, iova, size);
    }
    void *out[] = {unit, area, offset, iova, size};
    const size_t sizes[] = {4, 4, 4, 8, 4};
    rc = outputs(out, sizes, size ? 5 : 4);
    if (rc) { errno = -rc; return 0; }
    struct functional_mpr_memory_span s;
    pthread_mutex_lock(&mutex);
    rc = query_locked((uintptr_t)address, 1, &s);
    if (!rc) {
        uint32_t off = (uint32_t)s.offset, capacity = (uint32_t)s.capacity;
        memcpy(unit, &s.unit, 4); memcpy(area, &s.area, 4);
        memcpy(offset, &off, 4); memcpy(iova, &s.iova_base, 8);
        if (size) memcpy(size, &capacity, 4);
    }
    pthread_mutex_unlock(&mutex);
    errno = rc ? -rc : saved;
    return rc ? 0 : 1;
}
void fmpr_memory_fixed(unsigned, void **, void **, uint32_t *) __asm__(FIXED_SYMBOL);
void fmpr_memory_fixed(unsigned type, void **physical, void **virtual_address, uint32_t *size) {
    int saved = errno, rc = process_guard();
    if (rc) { errno = -rc; return; }
    if (!atomic_load_explicit(&enabled, memory_order_acquire) || type != 2) {
        void (*delegate)(unsigned, void **, void **, uint32_t *) = NULL;
        LOAD_FUNCTION(delegate, FIXED_SYMBOL);
        if (!delegate) { errno = ENOSYS; return; }
        errno = saved;
        delegate(type, physical, virtual_address, size);
        return;
    }
    void *out[] = {physical, virtual_address, size};
    const size_t sizes[] = {sizeof *physical, sizeof *virtual_address, sizeof *size};
    rc = outputs(out, sizes, 3);
    if (rc) { errno = -rc; return; }
    pthread_mutex_lock(&mutex);
    if (closing || !atomic_load_explicit(&enabled, memory_order_relaxed)) rc = -ENODEV;
    else if (!fixed_mapping) {
        if (next_generation == UINT64_MAX) rc = -EOVERFLOW;
        else {
            void *p = map_low(PAGE, PROT_READ | PROT_WRITE);
            if (p == MAP_FAILED) rc = -errno;
            else { fixed_mapping = p; fixed_generation = next_generation++; }
        }
    }
    if (!rc) {
        uint32_t bytes = FUNCTIONAL_MPR_MEMORY_FIXED_BYTES;
        memcpy(physical, &fixed_mapping, sizeof *physical);
        memcpy(virtual_address, &fixed_mapping, sizeof *virtual_address);
        memcpy(size, &bytes, sizeof bytes);
    }
    void (*callback)(const char *, const char *) = record_callback;
    uint64_t generation = fixed_generation, bytes = mapped_bytes_locked();
    pthread_mutex_unlock(&mutex);
    note(callback, "fixed-area2", rc, generation, 0, bytes);
    errno = rc ? -rc : saved;
}

int functional_mpr_memory_query(uintptr_t address, size_t bytes, struct functional_mpr_memory_span *out) {
    int rc = api_guard();
    if (rc) return rc;
    if ((rc = accessible((uintptr_t)out, sizeof *out, 1))) return rc;
    struct functional_mpr_memory_span s;
    pthread_mutex_lock(&mutex);
    rc = query_locked(address, bytes, &s);
    if (!rc) memcpy(out, &s, sizeof s);
    pthread_mutex_unlock(&mutex);
    return rc;
}
static int acquire_locked(uintptr_t address, size_t bytes, struct functional_mpr_memory_lease *out) {
    struct functional_mpr_memory_lease lease = {.address = address, .bytes = bytes};
    int rc = query_locked(address, bytes, &lease.span);
    unsigned i = 0;
    if (!rc) {
        for (; i < LEASE_COUNT && leases[i].token; ++i) {}
        if (i == LEASE_COUNT) rc = -ENOSPC;
        else if (next_token == UINT64_MAX) rc = -EOVERFLOW;
        else { lease.token = next_token++; leases[i] = lease; memcpy(out, &lease, sizeof lease); }
    }
    return rc;
}
int functional_mpr_memory_acquire(uintptr_t address, size_t bytes, struct functional_mpr_memory_lease *out) {
    int rc = api_guard();
    if (rc) return rc;
    if ((rc = accessible((uintptr_t)out, sizeof *out, 1))) return rc;
    pthread_mutex_lock(&mutex);
    rc = acquire_locked(address, bytes, out);
    pthread_mutex_unlock(&mutex);
    return rc;
}
int functional_mpr_memory_acquire_sds(uint32_t type, uint32_t handle,
    uint32_t offset, size_t bytes, struct functional_mpr_memory_lease *out) {
    int rc = api_guard();
    if (rc) return rc;
    if ((rc = accessible((uintptr_t)out, sizeof *out, 1))) return rc;
    if (type || !handle) return -ENODATA;
    if (!bytes) return -EINVAL;
    if (bytes > UINT32_MAX - offset) return -EOVERFLOW;
    pthread_mutex_lock(&mutex);
    if (closing || !atomic_load_explicit(&enabled, memory_order_relaxed)) rc = -ENODEV;
    else if (!(rc = root_intact())) {
        rc = -ENODATA;
        for (unsigned g = 0; g < generation_count; ++g)
            for (unsigned u = 0; u < UNIT_COUNT; ++u) {
                const struct functional_mpr_memory_span *s = &generations[g].sds[u];
                if (s->unit != handle) continue;
                const struct area_node *n = &generations[g].nodes[u];
                rc = -ESTALE;
                if (active != &generations[g] || !n->valid ||
                    n->unit != s->unit || n->area != s->area || n->type != s->unit_type ||
                    n->group != s->group || n->virtual_base != s->virtual_base ||
                    n->iova_base != s->iova_base || n->size != s->capacity ||
                    n->extent_count != 1 || n->extent_size != s->capacity ||
                    s->generation != active->id) goto done;
                if (offset >= s->capacity || bytes > s->capacity - offset) {
                    rc = -ERANGE;
                    goto done;
                }
                struct functional_mpr_memory_span expected = *s, current;
                expected.offset = offset;
                if (query_locked(s->virtual_base + offset, bytes, &current) ||
                    memcmp(&expected, &current, sizeof current)) {
                    rc = -ESTALE;
                    goto done;
                }
                rc = acquire_locked(s->virtual_base + offset, bytes, out);
                goto done;
            }
    }
done:
    pthread_mutex_unlock(&mutex);
    return rc;
}
static int validate_lease_locked(const struct functional_mpr_memory_lease *copy) {
    for (unsigned i = 0; i < LEASE_COUNT; ++i) if (copy->token && leases[i].token == copy->token) {
        const struct functional_mpr_memory_lease *stored = &leases[i];
        struct functional_mpr_memory_span current;
        if (copy->address == stored->address && copy->bytes == stored->bytes &&
            !memcmp(&copy->span, &stored->span, sizeof copy->span) &&
            !query_locked(copy->address, copy->bytes, &current) &&
            !memcmp(&current, &stored->span, sizeof current)) return 0;
        break;
    }
    return -ESTALE;
}
int functional_mpr_memory_validate(const struct functional_mpr_memory_lease *lease) {
    int rc = api_guard();
    if (rc) return rc;
    if ((rc = accessible((uintptr_t)lease, sizeof *lease, 0))) return rc;
    struct functional_mpr_memory_lease copy;
    memcpy(&copy, lease, sizeof copy);
    pthread_mutex_lock(&mutex);
    rc = validate_lease_locked(&copy);
    pthread_mutex_unlock(&mutex);
    return rc;
}
int functional_mpr_memory_write(const struct functional_mpr_memory_lease *lease,
    size_t offset, const void *data, size_t bytes) {
    int rc = api_guard();
    if (rc) return rc;
    if ((rc = accessible((uintptr_t)lease, sizeof *lease, 0))) return rc;
    struct functional_mpr_memory_lease copy;
    memcpy(&copy, lease, sizeof copy);
    if (!bytes || offset > copy.bytes || bytes > copy.bytes - offset) return -EINVAL;
    if ((rc = accessible((uintptr_t)data, bytes, 0))) return rc;
    pthread_mutex_lock(&mutex);
    rc = validate_lease_locked(&copy);
    if (!rc) {
        uint64_t expected = fnv(data, bytes);
        void *destination = (void *)(copy.address + offset);
        memmove(destination, data, bytes);
        if (fnv(destination, bytes) != expected) rc = -EIO;
    }
    pthread_mutex_unlock(&mutex);
    return rc;
}
int functional_mpr_memory_release(uint64_t token) {
    int rc = api_guard();
    if (rc) return rc;
    pthread_mutex_lock(&mutex);
    rc = -ESTALE;
    for (unsigned i = 0; i < LEASE_COUNT; ++i) if (token && leases[i].token == token) {
        memset(&leases[i], 0, sizeof leases[i]); rc = 0; break;
    }
    pthread_mutex_unlock(&mutex);
    return rc;
}
int functional_mpr_memory_snapshot(struct functional_mpr_memory_snapshot *out) {
    int rc = process_guard();
    if (rc) return rc;
    if ((rc = accessible((uintptr_t)out, sizeof *out, 1))) return rc;
    pthread_mutex_lock(&mutex);
    struct functional_mpr_memory_snapshot s = {
        .generations = generation_count, .active_generation = active ? active->id : 0,
        .enabled = (uint32_t)atomic_load_explicit(&enabled, memory_order_relaxed),
        .active_group = active ? active->group : 0, .active_mask = active_mask(),
        .fixed_mapped = fixed_mapping != NULL, .mapped_bytes = mapped_bytes_locked()
    };
    for (unsigned i = 0; i < LEASE_COUNT; ++i) if (leases[i].token) ++s.leases;
    memcpy(out, &s, sizeof s);
    pthread_mutex_unlock(&mutex);
    return 0;
}
int functional_mpr_memory_shutdown(void) {
    int rc = api_guard();
    if (rc) return rc;
    pthread_mutex_lock(&mutex);
    if (active) rc = -EBUSY;
    for (unsigned i = 0; !rc && i < LEASE_COUNT; ++i) if (leases[i].token) rc = -EBUSY;
    if (!rc) rc = root_intact();
    if (!rc) {
        closing = 1;
        *original.root = saved_root;
        published = 0;
        for (unsigned g = 0; g < generation_count; ++g) if (generations[g].mapping) {
            if (munmap(generations[g].mapping, ARENA_BYTES)) { rc = -errno; break; }
            generations[g].mapping = NULL;
        }
        if (!rc && fixed_mapping) {
            if (munmap(fixed_mapping, PAGE)) rc = -errno;
            else fixed_mapping = NULL;
        }
        if (!rc) {
            generation_count = 0;
            memset(generations, 0, sizeof generations);
            fixed_generation = 0;
            closing = 0;
            atomic_store_explicit(&enabled, 0, memory_order_release);
        }
    }
    pthread_mutex_unlock(&mutex);
    return rc;
}
