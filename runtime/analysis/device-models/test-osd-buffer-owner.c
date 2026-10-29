/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include "osd-buffer-owner.h"
#include <assert.h>
#include <limits.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#define TEST_PHYSICAL 0x510000000ULL
#define TEST_CP_ALIAS 0x81000000u
#define THREAD_LOOPS 1000u
struct guarded_memory {
    _Alignas(256) unsigned char before[256];
    unsigned char bytes[FULL_OSD_POOL_BYTES];
    unsigned char after[256];
};
static struct guarded_memory first_memory, second_memory;
static unsigned char *bound_memory = first_memory.bytes;
static unsigned int handles[FULL_OSD_POOL_SLOTS];
static unsigned int fork_handle, fork_side;
static int fork_on_lock;
static unsigned int completed;

static struct full_osd_pool_snapshot snapshot(void)
{
    struct full_osd_pool_snapshot out;
    full_osd_pool_snapshot(&out);
    return out;
}

static void passed(const char *name)
{
    ++completed;
    puts(name);
}

#define REJECT_UNCHANGED(call) do { \
    struct full_osd_pool_snapshot before_ = snapshot(), after_; \
    unsigned char old_[FULL_OSD_POOL_BYTES]; \
    memcpy(old_, bound_memory, sizeof old_); \
    assert((call) == FULL_OSD_POOL_REJECT); \
    after_ = snapshot(); \
    assert(!memcmp(&before_, &after_, sizeof before_)); \
    assert(!memcmp(old_, bound_memory, sizeof old_)); \
} while (0)

static unsigned int opposite(unsigned int side)
{
    return side == FULL_OSD_PINMEM_SIDE ? FULL_OSD_PEER_SIDE : FULL_OSD_PINMEM_SIDE;
}

static unsigned int creator(unsigned int index)
{
    return index < 4u ? FULL_OSD_PEER_SIDE : FULL_OSD_PINMEM_SIDE;
}

static void guards(void)
{
    for (unsigned int i = 0; i < sizeof first_memory.before; ++i) {
        assert(first_memory.before[i] == 0xcc && first_memory.after[i] == 0xcc);
        assert(second_memory.before[i] == 0xcc && second_memory.after[i] == 0xcc);
    }
}

static void references(unsigned int index, unsigned int owners, unsigned int opens)
{
    struct full_osd_pool_snapshot out = snapshot();
    assert(out.slots[index].handle == handles[index]);
    assert(out.slots[index].owners == owners && out.slots[index].open_count == opens);
    assert(out.slots[index].live == (owners != 0));
}

static void child_probe(void)
{
    unsigned char data[256], known[256];
    unsigned int handle = 0x12345678u;
    struct full_osd_mapping mapping;
    memset(data, 0x77, sizeof data);
    memset(known, 1, sizeof known);
    alarm(3);
    assert(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES,
                              TEST_PHYSICAL, TEST_CP_ALIAS) == FULL_OSD_POOL_REJECT);
    assert(full_osd_pool_allocate(fork_side, &handle) == FULL_OSD_POOL_REJECT);
    assert(handle == 0x12345678u);
    assert(full_osd_pool_share(fork_side, fork_handle) == FULL_OSD_POOL_REJECT);
    assert(full_osd_pool_open(opposite(fork_side), fork_handle) == FULL_OSD_POOL_REJECT);
    assert(full_osd_pool_write(fork_side, fork_handle, 0, data, known, 256) == FULL_OSD_POOL_REJECT);
    assert(full_osd_pool_read(fork_side, fork_handle, 0, data, known, 256) == FULL_OSD_POOL_REJECT);
    assert(full_osd_pool_mapping(fork_side, fork_handle, &mapping) == FULL_OSD_POOL_REJECT);
    assert(full_osd_pool_release(fork_side, fork_handle) == FULL_OSD_POOL_REJECT);
    struct full_osd_pool_snapshot out = snapshot();
    assert(out.owner_pid == (unsigned int)getppid() && !out.initialized && out.faults == 1);
    assert(!out.live && !out.allocations && !out.releases);
    for (unsigned int i = 0; i < sizeof data; ++i)
        assert(data[i] == 0x77 && known[i] == 1);
    _exit(0);
}

/* Linker wrapping holds the real private mutex during fork; no production hook. */
int __real_pthread_mutex_lock(pthread_mutex_t *mutex);
int __wrap_pthread_mutex_lock(pthread_mutex_t *mutex);
int __wrap_pthread_mutex_lock(pthread_mutex_t *mutex)
{
    int rc = __real_pthread_mutex_lock(mutex);
    if (!rc && fork_on_lock) {
        fork_on_lock = 0;
        pid_t child = fork();
        assert(child >= 0);
        if (!child)
            child_probe();
        int status = 0;
        assert(waitpid(child, &status, 0) == child);
        assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    }
    return rc;
}

struct parallel_case {
    unsigned int handle, creator_side, consumer_side;
    _Atomic unsigned int start;
};

static void *writer(void *opaque)
{
    struct parallel_case *test = opaque;
    unsigned char data[256], known[256];
    memset(known, 1, sizeof known);
    while (!atomic_load(&test->start))
        sched_yield();
    for (unsigned int i = 0; i < THREAD_LOOPS; ++i) {
        memset(data, (int)(10u + i % 200u), sizeof data);
        assert(!full_osd_pool_write(test->creator_side, test->handle, 0, data, known, 256));
    }
    return NULL;
}

static void *reader(void *opaque)
{
    struct parallel_case *test = opaque;
    unsigned char data[256], known[256];
    while (!atomic_load(&test->start))
        sched_yield();
    for (unsigned int i = 0; i < THREAD_LOOPS; ++i) {
        assert(!full_osd_pool_read(test->consumer_side, test->handle, 0, data, known, 256));
        for (unsigned int j = 0; j < sizeof data; ++j)
            assert(data[j] == data[0] && known[j] == 1);
    }
    return NULL;
}

static void check_unbound_and_bind(void)
{
    memset(&first_memory, 0xcc, sizeof first_memory);
    memset(&second_memory, 0xcc, sizeof second_memory);
    unsigned int handle = 0x12345678u;
    unsigned char data = 0x77, known = 1;
    struct full_osd_mapping mapping;
    REJECT_UNCHANGED(full_osd_pool_allocate(FULL_OSD_PINMEM_SIDE, &handle));
    REJECT_UNCHANGED(full_osd_pool_share(FULL_OSD_PINMEM_SIDE, 0xe1000010u));
    REJECT_UNCHANGED(full_osd_pool_open(FULL_OSD_PEER_SIDE, 0xe1000010u));
    REJECT_UNCHANGED(full_osd_pool_write(FULL_OSD_PINMEM_SIDE, 0xe1000010u, 0, &data, &known, 1));
    REJECT_UNCHANGED(full_osd_pool_read(FULL_OSD_PINMEM_SIDE, 0xe1000010u, 0, &data, &known, 1));
    REJECT_UNCHANGED(full_osd_pool_mapping(FULL_OSD_PINMEM_SIDE, 0xe1000010u, &mapping));
    REJECT_UNCHANGED(full_osd_pool_release(FULL_OSD_PINMEM_SIDE, 0xe1000010u));
    assert(handle == 0x12345678u && data == 0x77 && known == 1);
    full_osd_pool_snapshot(NULL);
    assert(!snapshot().owner_pid && !snapshot().faults);
    passed("OSD_POOL_UNBOUND_NO_OWNERSHIP_OR_OUTPUT_SIDE_EFFECT_PASS");

    REJECT_UNCHANGED(full_osd_pool_bind(NULL, FULL_OSD_POOL_BYTES, TEST_PHYSICAL, TEST_CP_ALIAS));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES - 1, TEST_PHYSICAL, TEST_CP_ALIAS));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES + 1, TEST_PHYSICAL, TEST_CP_ALIAS));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, TEST_PHYSICAL + 1, TEST_CP_ALIAS));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, TEST_PHYSICAL, TEST_CP_ALIAS + 1));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, 0xfffffffffffff500ULL, TEST_CP_ALIAS));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, TEST_PHYSICAL, 0xfffff500u));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, 0x500000000ULL, TEST_CP_ALIAS));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, 0x4ffffff00ULL, TEST_CP_ALIAS));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, 0x41d000000ULL, TEST_CP_ALIAS));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, 0x81d000000ULL, TEST_CP_ALIAS));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, TEST_PHYSICAL, 0x80000000u));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, TEST_PHYSICAL, 0x7fffff00u));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, TEST_PHYSICAL, 0x1d000000u));
    assert(!snapshot().owner_pid);
    passed("OSD_POOL_BIND_RANGE_ALIGNMENT_AND_EXISTING_NAMESPACE_GUARDS_PASS");

    assert(!full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES, TEST_PHYSICAL, TEST_CP_ALIAS));
    struct full_osd_pool_snapshot out = snapshot();
    assert(out.owner_pid == (unsigned int)getpid() && out.initialized && !out.faults && !out.live);
    assert(!out.original_allocator_capacity_verified && !out.original_cp_pages_verified);
    for (unsigned int i = 0; i < FULL_OSD_POOL_BYTES; ++i)
        assert(first_memory.bytes[i] == FULL_OSD_POOL_UNKNOWN_BYTE);
    guards();
    passed("OSD_POOL_ACTUAL_4096B_BIND_POISON_AND_UNVERIFIED_SOURCE_BOUNDARIES_PASS");
}

static void check_allocation_and_payloads(void)
{
    struct full_osd_mapping mappings[FULL_OSD_POOL_SLOTS];
    unsigned char data[256], known[256], actual[256], actual_known[256];
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i) {
        assert(!full_osd_pool_allocate(creator(i), &handles[i]));
        assert(!full_osd_pool_mapping(creator(i), handles[i], &mappings[i]));
        const struct full_osd_mapping *m = &mappings[i];
        assert(m->handle == handles[i] && m->handle > 0xffffu && m->unit == FULL_OSD_POOL_UNIT);
        assert(m->generation == 1 && m->extent == 256);
        assert(m->physical == TEST_PHYSICAL + i * 256u && m->cp_alias == TEST_CP_ALIAS + i * 256u);
        for (unsigned int j = 0; j < i; ++j) {
            assert(m->handle != mappings[j].handle);
            assert(m->physical != mappings[j].physical && m->cp_alias != mappings[j].cp_alias);
        }
        assert(!full_osd_pool_read(creator(i), handles[i], 0, actual, actual_known, 256));
        for (unsigned int j = 0; j < sizeof actual; ++j)
            assert(actual[j] == FULL_OSD_POOL_UNKNOWN_BYTE && !actual_known[j]);
        references(i, 1, 1);
    }
    unsigned int untouched = 0x12345678u;
    REJECT_UNCHANGED(full_osd_pool_allocate(FULL_OSD_PINMEM_SIDE, &untouched));
    assert(untouched == 0x12345678u);
    struct full_osd_pool_snapshot out = snapshot();
    assert(out.live == 16 && out.allocations == 16 && !out.shares && !out.opens && out.reads == 16);
    passed("OSD_POOL_SIXTEEN_DISTINCT_MAPPINGS_AND_SEVENTEENTH_REJECT_PASS");

    /* Synthetic tagged payloads exercise storage, not Sony wire serialization. */
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i) {
        unsigned int length = i < 4u ? 64u : (i < 12u ? 128u : 16u);
        memset(data, FULL_OSD_POOL_UNKNOWN_BYTE, sizeof data);
        memset(known, 0, sizeof known);
        memset(data, 0, length);
        memset(known, 1, length);
        data[4] = (unsigned char)i;
        memcpy(data + length - 4u, "TEST", 4);
        unsigned int hole = i < 4u || i >= 12u ? 2u : 8u;
        unsigned int hole_offset = i < 12u ? 16u : 10u;
        memset(data + hole_offset, FULL_OSD_POOL_UNKNOWN_BYTE, hole);
        memset(known + hole_offset, 0, hole);
        assert(!full_osd_pool_write(creator(i), handles[i], 0, data, known, 256));
        assert(!full_osd_pool_read(creator(i), handles[i], 0, actual, actual_known, 256));
        assert(!memcmp(data, actual, 256) && !memcmp(known, actual_known, 256));
        assert(!memcmp(first_memory.bytes + i * 256u, data, 256));
        out = snapshot();
        assert(out.slots[i].known_bytes == length - hole);
    }
    passed("OSD_POOL_64B_128B_16B_ZERO_TAGS_HOLES_AND_ALL_BYTES_REAL_READBACK_PASS");

    unsigned int invalid[] = {0u, 0x8000u, FULL_OSD_POOL_UNIT, handles[0] ^ 0x10u,
                              handles[0] ^ 0x01000000u, 0xe100002cu, 0xffffffffu};
    for (unsigned int i = 0; i < sizeof invalid / sizeof invalid[0]; ++i) {
        REJECT_UNCHANGED(full_osd_pool_write(creator(0), invalid[i], 0, data, known, 256));
        REJECT_UNCHANGED(full_osd_pool_read(creator(0), invalid[i], 0, actual, actual_known, 256));
        REJECT_UNCHANGED(full_osd_pool_mapping(creator(0), invalid[i], &mappings[0]));
        REJECT_UNCHANGED(full_osd_pool_share(creator(0), invalid[i]));
        REJECT_UNCHANGED(full_osd_pool_open(opposite(creator(0)), invalid[i]));
        REJECT_UNCHANGED(full_osd_pool_release(creator(0), invalid[i]));
    }
    REJECT_UNCHANGED(full_osd_pool_allocate(0, &untouched));
    REJECT_UNCHANGED(full_osd_pool_allocate(3, &untouched));
    REJECT_UNCHANGED(full_osd_pool_allocate(FULL_OSD_PINMEM_SIDE, NULL));
    REJECT_UNCHANGED(full_osd_pool_mapping(0, handles[0], &mappings[0]));
    REJECT_UNCHANGED(full_osd_pool_mapping(3, handles[0], &mappings[0]));
    REJECT_UNCHANGED(full_osd_pool_mapping(creator(0), handles[0], NULL));
    REJECT_UNCHANGED(full_osd_pool_mapping(opposite(creator(0)), handles[0], &mappings[0]));
    REJECT_UNCHANGED(full_osd_pool_open(opposite(creator(0)), handles[0]));
    REJECT_UNCHANGED(full_osd_pool_release(opposite(creator(0)), handles[0]));
    REJECT_UNCHANGED(full_osd_pool_share(opposite(creator(0)), handles[0]));
    passed("OSD_POOL_UNIT_HANDLE_ROLE_AND_UNOPENED_OWNER_REJECT_UNCHANGED_PASS");

    const unsigned int offsets[] = {0u, 256u, UINT_MAX, 255u, 1u};
    const unsigned int lengths[] = {0u, 1u, 2u, 2u, UINT_MAX};
    for (unsigned int i = 0; i < sizeof offsets / sizeof offsets[0]; ++i) {
        memset(actual, 0x77, sizeof actual);
        memset(actual_known, 0x66, sizeof actual_known);
        REJECT_UNCHANGED(full_osd_pool_write(creator(0), handles[0], offsets[i], data, known, lengths[i]));
        REJECT_UNCHANGED(full_osd_pool_read(creator(0), handles[0], offsets[i], actual, actual_known, lengths[i]));
        for (unsigned int j = 0; j < sizeof actual; ++j)
            assert(actual[j] == 0x77 && actual_known[j] == 0x66);
    }
    REJECT_UNCHANGED(full_osd_pool_write(creator(0), handles[0], 0, NULL, known, 1));
    REJECT_UNCHANGED(full_osd_pool_write(creator(0), handles[0], 0, data, NULL, 1));
    REJECT_UNCHANGED(full_osd_pool_read(creator(0), handles[0], 0, NULL, actual_known, 1));
    REJECT_UNCHANGED(full_osd_pool_read(creator(0), handles[0], 0, actual, NULL, 1));
    known[255] = 2;
    REJECT_UNCHANGED(full_osd_pool_write(creator(0), handles[0], 0, data, known, 256));
    passed("OSD_POOL_OVERFLOW_NULL_AND_NONBINARY_MASK_NO_PARTIAL_WRITE_PASS");

    unsigned char tail[8], tail_known[8];
    memset(tail, 0, sizeof tail);
    memset(tail_known, 1, sizeof tail_known);
    unsigned int prior = snapshot().slots[7].known_bytes;
    assert(!full_osd_pool_write(creator(7), handles[7], 248, tail, tail_known, 8));
    tail[0] = FULL_OSD_POOL_UNKNOWN_BYTE;
    tail[1] = 0x66;
    tail_known[0] = 0;
    assert(!full_osd_pool_write(creator(7), handles[7], 248, tail, tail_known, 2));
    assert(!full_osd_pool_read(creator(7), handles[7], 248, actual, actual_known, 8));
    assert(!memcmp(actual, tail, 8) && !memcmp(actual_known, tail_known, 8));
    assert(!memcmp(first_memory.bytes + 7u * 256u + 248u, tail, 8));
    assert(snapshot().slots[7].known_bytes == prior + 7u);
    guards();
    passed("OSD_POOL_PARTIAL_LAST_BYTE_WRITE_AND_KNOWN_COUNT_REPLACEMENT_PASS");
}

static void check_shared_mutation_and_process(void)
{
    unsigned char data[256], known[256];
    unsigned char value = 0xb7, one = 1;
    struct full_osd_mapping before, after;
    assert(!full_osd_pool_mapping(creator(0), handles[0], &before));
    assert(!full_osd_pool_share(creator(0), handles[0]));
    references(0, 2, 1);
    REJECT_UNCHANGED(full_osd_pool_share(creator(0), handles[0]));
    REJECT_UNCHANGED(full_osd_pool_open(creator(0), handles[0]));
    REJECT_UNCHANGED(full_osd_pool_read(opposite(creator(0)), handles[0], 0, data, known, 256));
    REJECT_UNCHANGED(full_osd_pool_release(opposite(creator(0)), handles[0]));
    assert(!full_osd_pool_write(creator(0), handles[0], 0, &value, &one, 1));
    assert(first_memory.bytes[0] == value);
    assert(!full_osd_pool_open(opposite(creator(0)), handles[0]));
    assert(!full_osd_pool_read(opposite(creator(0)), handles[0], 0, data, known, 256));
    assert(data[0] == value && known[0] == 1);
    assert(!full_osd_pool_mapping(opposite(creator(0)), handles[0], &after));
    assert(!memcmp(&before, &after, sizeof before));
    REJECT_UNCHANGED(full_osd_pool_open(opposite(creator(0)), handles[0]));
    passed("OSD_POOL_SHARE_PRESERVES_CREATOR_WRITES_AND_CONSUMER_SINGLE_OPEN_PASS");

    for (unsigned int i = 1; i < FULL_OSD_POOL_SLOTS; ++i) {
        assert(!full_osd_pool_share(creator(i), handles[i]));
        assert(!full_osd_pool_open(opposite(creator(i)), handles[i]));
    }
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i) {
        value = (unsigned char)(0x80u + i);
        assert(!full_osd_pool_mapping(creator(i), handles[i], &before));
        assert(!full_osd_pool_write(creator(i), handles[i], 0, &value, &one, 1));
        assert(!full_osd_pool_read(opposite(creator(i)), handles[i], 0, data, known, 256));
        assert(data[0] == value && known[0] == 1);
        assert(!memcmp(first_memory.bytes + i * 256u, data, 256));
        assert(!full_osd_pool_mapping(opposite(creator(i)), handles[i], &after));
        assert(!memcmp(&before, &after, sizeof before));
        references(i, 2, 2);
    }
    struct full_osd_pool_snapshot out = snapshot();
    assert(out.live == 16 && out.allocations == 16 && out.shares == 16 && out.opens == 16 && !out.releases);
    passed("OSD_POOL_ALL_SIXTEEN_PERSIST_WITH_TWO_OWNERS_TWO_OPENS_AND_CURRENT_DATA_PASS");

    struct full_osd_pool_snapshot prior = snapshot();
    for (unsigned int i = 0; i < 50; ++i) {
        assert(!full_osd_pool_read(opposite(creator(0)), handles[0], 0, data, known, 256));
        assert(data[0] == 0x80 && known[0] == 1);
    }
    out = snapshot();
    assert(out.reads == prior.reads + 50 && out.shares == prior.shares && out.opens == prior.opens);
    assert(out.allocations == prior.allocations && out.live == prior.live);
    value = 0;
    assert(!full_osd_pool_write(opposite(creator(0)), handles[0], 255, &value, &one, 1));
    assert(!full_osd_pool_read(creator(0), handles[0], 255, data, known, 1));
    assert(data[0] == 0 && known[0] == 1 && first_memory.bytes[255] == 0);
    passed("OSD_POOL_REPEAT_READS_NO_NEW_OPEN_SHARE_AND_BIDIRECTIONAL_CURRENT_BYTES_PASS");

    REJECT_UNCHANGED(full_osd_pool_bind(second_memory.bytes, FULL_OSD_POOL_BYTES,
                                      TEST_PHYSICAL + 0x10000u, TEST_CP_ALIAS + 0x10000u));
    REJECT_UNCHANGED(full_osd_pool_bind(first_memory.bytes, FULL_OSD_POOL_BYTES,
                                      TEST_PHYSICAL, TEST_CP_ALIAS));
    for (unsigned int i = 0; i < FULL_OSD_POOL_BYTES; ++i)
        assert(second_memory.bytes[i] == 0xcc);
    guards();
    passed("OSD_POOL_LIVE_REBIND_REFUSES_WITHOUT_RESET_OR_OTHER_BACKING_WRITES_PASS");

    fork_handle = handles[3];
    fork_side = creator(3);
    prior = snapshot();
    fork_on_lock = 1;
    assert(!full_osd_pool_mapping(fork_side, fork_handle, &after));
    assert(!fork_on_lock);
    out = snapshot();
    assert(!memcmp(&prior, &out, sizeof prior));
    passed("OSD_POOL_FORK_ALL_ENTRYPOINTS_REFUSE_BEFORE_INHERITED_LOCK_PASS");

    struct parallel_case parallel = {handles[4], creator(4), opposite(creator(4)), 0};
    memset(data, 3, sizeof data);
    memset(known, 1, sizeof known);
    assert(!full_osd_pool_write(creator(4), handles[4], 0, data, known, 256));
    prior = snapshot();
    pthread_t writing, reading;
    assert(!pthread_create(&writing, NULL, writer, &parallel));
    assert(!pthread_create(&reading, NULL, reader, &parallel));
    atomic_store(&parallel.start, 1);
    assert(!pthread_join(writing, NULL) && !pthread_join(reading, NULL));
    out = snapshot();
    assert(out.writes == prior.writes + THREAD_LOOPS && out.reads == prior.reads + THREAD_LOOPS);
    assert(out.slots[4].known_bytes == 256 && out.shares == prior.shares && out.opens == prior.opens);
    assert(!full_osd_pool_read(opposite(creator(4)), handles[4], 0, data, known, 256));
    for (unsigned int i = 0; i < 256; ++i)
        assert(data[i] == (unsigned char)(10u + (THREAD_LOOPS - 1u) % 200u) && known[i] == 1);
    assert(!memcmp(first_memory.bytes + 4u * 256u, data, 256));
    passed("OSD_POOL_PARALLEL_FULL_EXTENT_READS_NEVER_TORN_OR_CACHED_PASS");
}

static void check_releases_reuse_and_rebind(void)
{
    unsigned char data[256], known[256], value = 0x42, one = 1;
    assert(!full_osd_pool_release(opposite(creator(0)), handles[0]));
    references(0, 1, 1);
    REJECT_UNCHANGED(full_osd_pool_release(opposite(creator(0)), handles[0]));
    REJECT_UNCHANGED(full_osd_pool_open(opposite(creator(0)), handles[0]));
    REJECT_UNCHANGED(full_osd_pool_share(creator(0), handles[0]));
    REJECT_UNCHANGED(full_osd_pool_read(opposite(creator(0)), handles[0], 0, data, known, 1));
    assert(!full_osd_pool_write(creator(0), handles[0], 0, &value, &one, 1));
    assert(!full_osd_pool_read(creator(0), handles[0], 0, data, known, 1));
    assert(data[0] == value && known[0] == 1);

    assert(!full_osd_pool_release(creator(1), handles[1]));
    references(1, 1, 1);
    REJECT_UNCHANGED(full_osd_pool_release(creator(1), handles[1]));
    REJECT_UNCHANGED(full_osd_pool_write(creator(1), handles[1], 0, &value, &one, 1));
    assert(!full_osd_pool_write(opposite(creator(1)), handles[1], 0, &value, &one, 1));
    assert(!full_osd_pool_read(opposite(creator(1)), handles[1], 0, data, known, 1));
    assert(data[0] == value && known[0] == 1);
    assert(snapshot().live == 16 && snapshot().releases == 2);
    passed("OSD_POOL_EITHER_ROLE_RELEASE_LEAVES_OTHER_ROLE_READ_WRITE_USABLE_PASS");

    unsigned char old_memory[FULL_OSD_POOL_BYTES];
    memcpy(old_memory, bound_memory, sizeof old_memory);
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i) {
        struct full_osd_pool_snapshot out = snapshot();
        if (out.slots[i].creator_open)
            assert(!full_osd_pool_release(creator(i), handles[i]));
        if (out.slots[i].consumer_open)
            assert(!full_osd_pool_release(opposite(creator(i)), handles[i]));
        references(i, 0, 0);
        REJECT_UNCHANGED(full_osd_pool_release(creator(i), handles[i]));
        REJECT_UNCHANGED(full_osd_pool_release(opposite(creator(i)), handles[i]));
    }
    struct full_osd_pool_snapshot out = snapshot();
    assert(!out.live && !out.faults && out.releases == 32 && out.allocations == 16);
    assert(out.shares == 16 && out.opens == 16 && !memcmp(old_memory, bound_memory, sizeof old_memory));
    guards();
    passed("OSD_POOL_ALL_SIXTEEN_EXPLICIT_ROLE_RELEASES_RETIRE_WITHOUT_ERASING_EVIDENCE_PASS");

    unsigned int newer;
    assert(!full_osd_pool_allocate(FULL_OSD_PINMEM_SIDE, &newer));
    assert(newer != handles[0] && snapshot().slots[0].generation == 2);
    REJECT_UNCHANGED(full_osd_pool_read(creator(0), handles[0], 0, data, known, 256));
    REJECT_UNCHANGED(full_osd_pool_release(creator(0), handles[0]));
    assert(!full_osd_pool_read(FULL_OSD_PINMEM_SIDE, newer, 0, data, known, 256));
    for (unsigned int i = 0; i < 256; ++i)
        assert(data[i] == FULL_OSD_POOL_UNKNOWN_BYTE && !known[i]);
    assert(!full_osd_pool_share(FULL_OSD_PINMEM_SIDE, newer));
    assert(!full_osd_pool_release(FULL_OSD_PINMEM_SIDE, newer));
    out = snapshot();
    assert(out.live == 1 && out.slots[0].owners == 1 && !out.slots[0].open_count);
    REJECT_UNCHANGED(full_osd_pool_release(FULL_OSD_PEER_SIDE, newer));
    assert(!full_osd_pool_open(FULL_OSD_PEER_SIDE, newer));
    assert(!full_osd_pool_write(FULL_OSD_PEER_SIDE, newer, 0, &value, &one, 1));
    assert(!full_osd_pool_read(FULL_OSD_PEER_SIDE, newer, 0, data, known, 1));
    assert(data[0] == value && known[0] == 1);
    assert(!full_osd_pool_release(FULL_OSD_PEER_SIDE, newer));
    assert(!snapshot().live && snapshot().releases == 34);
    passed("OSD_POOL_NEW_GENERATION_STALE_REFS_AND_PENDING_CONSUMER_AFTER_CREATOR_RELEASE_PASS");

    struct full_osd_pool_snapshot prior = snapshot();
    memcpy(old_memory, first_memory.bytes, sizeof old_memory);
    assert(!full_osd_pool_bind(second_memory.bytes, FULL_OSD_POOL_BYTES,
                              TEST_PHYSICAL + 0x10000u, TEST_CP_ALIAS + 0x10000u));
    bound_memory = second_memory.bytes;
    out = snapshot();
    assert(out.allocations == prior.allocations && out.releases == prior.releases);
    assert(out.shares == prior.shares && out.opens == prior.opens && out.reads == prior.reads && out.writes == prior.writes);
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i) {
        assert(out.slots[i].generation == prior.slots[i].generation);
        assert(!out.slots[i].known_bytes);
    }
    assert(!memcmp(first_memory.bytes, old_memory, sizeof old_memory));
    assert(!full_osd_pool_allocate(FULL_OSD_PEER_SIDE, &handles[0]));
    assert(handles[0] != newer && snapshot().slots[0].generation == 3);
    struct full_osd_mapping mapping;
    assert(!full_osd_pool_mapping(FULL_OSD_PEER_SIDE, handles[0], &mapping));
    assert(mapping.physical == TEST_PHYSICAL + 0x10000u && mapping.cp_alias == TEST_CP_ALIAS + 0x10000u);
    REJECT_UNCHANGED(full_osd_pool_mapping(FULL_OSD_PEER_SIDE, newer, &mapping));
    assert(!full_osd_pool_release(FULL_OSD_PEER_SIDE, handles[0]));
    guards();
    passed("OSD_POOL_EMPTY_REBIND_PRESERVES_ALL_HISTORY_GENERATIONS_AND_OLD_BACKING_PASS");

    const unsigned long long physical = ULLONG_MAX - (FULL_OSD_POOL_BYTES - 1u);
    const unsigned int cp_alias = UINT_MAX - (FULL_OSD_POOL_BYTES - 1u);
    assert(!full_osd_pool_bind(second_memory.bytes, FULL_OSD_POOL_BYTES, physical, cp_alias));
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i) {
        assert(!full_osd_pool_allocate(FULL_OSD_PINMEM_SIDE, &handles[i]));
        assert(!full_osd_pool_mapping(FULL_OSD_PINMEM_SIDE, handles[i], &mapping));
        assert(mapping.physical == physical + i * 256u && mapping.cp_alias == cp_alias + i * 256u);
    }
    assert(mapping.physical + 255u == ULLONG_MAX && mapping.cp_alias + 255u == UINT_MAX);
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i)
        assert(!full_osd_pool_release(FULL_OSD_PINMEM_SIDE, handles[i]));
    out = snapshot();
    assert(!out.live && !out.faults && out.allocations == 34 && out.releases == 51);
    assert(out.shares == 17 && out.opens == 17);
    assert(!out.original_allocator_capacity_verified && !out.original_cp_pages_verified);
    guards();
    passed("OSD_POOL_LAST_VALID_64BIT_AND_32BIT_MAPPING_BOUNDARIES_PASS");
}

int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--self-check")) {
        fputs("usage: test-osd-buffer-owner --self-check\n", stderr);
        return 2;
    }
    check_unbound_and_bind();
    check_allocation_and_payloads();
    check_shared_mutation_and_process();
    check_releases_reuse_and_rebind();
    assert(completed == 19);
    struct full_osd_pool_snapshot out = snapshot();
    printf("OSD_BUFFER_OWNER_SELF_CHECK_PASS checks=%u allocations=%llu releases=%llu live=%u faults=%u\n",
           completed, out.allocations, out.releases, out.live, out.faults);
    return 0;
}
