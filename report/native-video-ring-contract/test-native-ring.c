#include "native-ring.h"

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

#define CAP (8u * NRING_INFO_BYTES + 128u)
#define SENTINEL_ERRNO 731
struct copy_fixture {
    _Alignas(max_align_t) uint8_t ring[CAP];
    _Alignas(max_align_t) uint8_t out[CAP];
    size_t count;
};
struct advance_fixture {
    struct nring_user users[5];
    struct nring_advance plan;
};

static void init_copy(struct copy_fixture *f)
{
    memset(f, 0xa5, sizeof(*f));
    for (size_t i = 0; i < sizeof(f->ring); ++i)
        f->ring[i] = (uint8_t)((i * 53u + i / NRING_INFO_BYTES * 29u + 17u) & 255u);
    f->count = 12345;
}

static void copy_error(struct copy_fixture *f, const uint8_t *ring, size_t cap,
    uint32_t n, uint32_t w, uint32_t r, uint8_t *out, size_t outcap,
    size_t *count, int expected)
{
    struct copy_fixture before;
    memcpy(&before, f, sizeof(before));
    errno = SENTINEL_ERRNO;
    assert(nring_copy_read_list(ring, cap, n, w, r, out, outcap, count) == expected);
    assert(errno == SENTINEL_ERRNO);
    assert(memcmp(&before, f, sizeof(before)) == 0);
}

static uint32_t model_distance(uint32_t a, uint32_t b, uint32_t n)
{
    return (uint32_t)(((uint64_t)a + n - b) % n);
}

static void copy_order(void)
{
    struct copy_fixture f, before;
    for (uint32_t n = 2; n <= 8; ++n) {
        for (uint32_t r = 0; r < n; ++r) {
            for (uint32_t w = 0; w < n; ++w) {
                size_t count = model_distance(w, r, n);
                init_copy(&f);
                memcpy(&before, &f, sizeof(before));
                errno = SENTINEL_ERRNO;
                assert(nring_copy_read_list(f.ring, sizeof(f.ring), n, w, r,
                    f.out, sizeof(f.out), &f.count) == 0);
                assert(errno == SENTINEL_ERRNO && f.count == count);
                for (size_t i = 0; i < count; ++i) {
                    size_t slot = (r + 1u + i) % n;
                    assert(memcmp(f.out + i * NRING_INFO_BYTES,
                        f.ring + slot * NRING_INFO_BYTES, NRING_INFO_BYTES) == 0);
                }
                assert(memcmp(f.out + count * NRING_INFO_BYTES,
                    before.out + count * NRING_INFO_BYTES,
                    sizeof(f.out) - count * NRING_INFO_BYTES) == 0);
                assert(memcmp(f.ring, before.ring, sizeof(f.ring)) == 0);
            }
        }
    }
}

static void copy_empty(void)
{
    struct copy_fixture f, before;
    init_copy(&f);
    memcpy(&before, &f, sizeof(before));
    errno = SENTINEL_ERRNO;
    assert(nring_copy_read_list(f.ring, 96, 1, 0, 0, NULL, 0, &f.count) == 0);
    assert(f.count == 0 && errno == SENTINEL_ERRNO);
    assert(memcmp(f.out, before.out, sizeof(f.out)) == 0);
    assert(memcmp(f.ring, before.ring, sizeof(f.ring)) == 0);
    assert(nring_copy_read_list(f.ring, 192, 2, 1, 1, f.out, 0, &f.count) == 0);
    assert(f.count == 0 && errno == SENTINEL_ERRNO);
    assert(nring_copy_read_list(f.ring, 192, 2, 0, 1, f.out, 96, &f.count) == 0);
    assert(f.count == 1 && memcmp(f.out, f.ring, 96) == 0);
    assert(nring_copy_read_list(f.ring, 192, 2, 1, 0, f.out, 96, &f.count) == 0);
    assert(f.count == 1 && memcmp(f.out, f.ring + 96, 96) == 0);
}

static void copy_invalid(void)
{
    struct copy_fixture f;
    init_copy(&f);
    copy_error(&f, f.ring, CAP, 0, 0, 0, f.out, CAP, &f.count, EINVAL);
    copy_error(&f, f.ring, CAP, 4, 4, 0, f.out, CAP, &f.count, ERANGE);
    copy_error(&f, f.ring, CAP, 4, 1, 4, f.out, CAP, &f.count, ERANGE);
    copy_error(&f, NULL, CAP, 4, 1, 0, f.out, CAP, &f.count, EINVAL);
    copy_error(&f, f.ring, CAP, 4, 1, 0, NULL, CAP, &f.count, EINVAL);
    copy_error(&f, f.ring, CAP, 4, 1, 0, f.out, CAP, NULL, EINVAL);
    copy_error(&f, f.ring, 383, 4, 1, 0, f.out, CAP, &f.count, ENOSPC);
    copy_error(&f, f.ring, CAP, 4, 2, 0, f.out, 191, &f.count, ENOSPC);
    copy_error(&f, f.ring, CAP, 4, 1, 0, NULL, 0, &f.count, ENOSPC);
    copy_error(&f, f.ring, CAP, 1, 0, 0, f.out, CAP,
        (size_t *)(void *)(f.out + 1), EINVAL);
}

static void copy_alias(void)
{
    struct copy_fixture f;
    init_copy(&f);
    copy_error(&f, f.ring, CAP, 4, 1, 0, f.ring, CAP, &f.count, EINVAL);
    /* Source's unused declared tail and output's unused capacity both count. */
    copy_error(&f, f.ring, CAP, 4, 1, 0, f.ring + 4 * 96, 96, &f.count, EINVAL);
    copy_error(&f, f.ring + 96, 4 * 96, 4, 1, 0,
        f.ring, 4 * 96, &f.count, EINVAL);
    copy_error(&f, f.ring, CAP, 4, 1, 0, f.out, CAP,
        (size_t *)(void *)(f.ring + 4 * 96), EINVAL);
    copy_error(&f, f.ring, CAP, 4, 1, 0, f.out, CAP,
        (size_t *)(void *)(f.out + 4 * 96), EINVAL);
    copy_error(&f, f.ring, CAP, 1, 0, 0, f.ring, CAP, &f.count, EINVAL);
}

static void copy_overflow(void)
{
    struct copy_fixture f;
    uintptr_t top = UINTPTR_MAX - UINTPTR_MAX % _Alignof(size_t);
    init_copy(&f);
    copy_error(&f, f.ring, SIZE_MAX, 4, 1, 0, f.out, CAP, &f.count, EOVERFLOW);
    copy_error(&f, f.ring, CAP, 4, 1, 0, f.out, SIZE_MAX, &f.count, EOVERFLOW);
    copy_error(&f, (const uint8_t *)(UINTPTR_MAX - 31), 384,
        4, 1, 0, f.out, CAP, &f.count, EOVERFLOW);
    copy_error(&f, f.ring, CAP, 4, 1, 0, f.out, CAP,
        (size_t *)top, EOVERFLOW);
    copy_error(&f, f.ring, CAP, UINT32_MAX, 1, 0, f.out, CAP, &f.count,
        (uint64_t)UINT32_MAX * NRING_INFO_BYTES > SIZE_MAX ? EOVERFLOW : ENOSPC);
}

static void init_advance(struct advance_fixture *f)
{
    memset(f, 0, sizeof(*f));
    f->users[0] = (struct nring_user){11, 6, 1};
    f->users[1] = (struct nring_user){22, 0, 2};
    f->users[2] = (struct nring_user){33, 7, 3};
    f->users[3] = (struct nring_user){44, UINT32_MAX, 0};
    f->users[4] = (struct nring_user){55, UINT32_MAX, 99};
    f->plan = (struct nring_advance){101, 102, 103};
}

static void advance_error(struct advance_fixture *f,
    const struct nring_user *users, size_t count, uint32_t id,
    size_t returned, size_t borrowed, uint32_t n, uint32_t w, uint32_t shared,
    struct nring_advance *result, int expected)
{
    struct advance_fixture before;
    memcpy(&before, f, sizeof(before));
    errno = SENTINEL_ERRNO;
    assert(nring_advance_read(users, count, id, returned, borrowed,
        n, w, shared, result) == expected);
    assert(errno == SENTINEL_ERRNO);
    assert(memcmp(&before, f, sizeof(before)) == 0);
}

static void advance_min(void)
{
    struct advance_fixture f, before;
    init_advance(&f);
    memcpy(&before, &f, sizeof(before));
    errno = SENTINEL_ERRNO;
    assert(nring_advance_read(f.users, 5, 11, 2, 3, 8, 1, 6, &f.plan) == 0);
    assert(f.plan.user_read_index == 0 && f.plan.delta == 1 &&
        f.plan.shared_read_index == 7 && errno == SENTINEL_ERRNO);
    assert(memcmp(f.users, before.users, sizeof(f.users)) == 0);
    /* Independently compare all small cursor combinations and active states. */
    for (uint32_t status = 1; status <= 3; ++status) {
        for (uint32_t n = 1; n <= 6; ++n) {
            for (uint32_t shared = 0; shared < n; ++shared) {
                for (uint32_t r = 0; r < n; ++r) {
                    for (uint32_t other = 0; other < n; ++other) {
                        for (uint32_t done = 0; done < n; ++done) {
                            struct nring_user users[2] = {{1, r, status}, {2, other, 2}};
                            uint32_t next = (r + done) % n;
                            uint32_t d = model_distance(next, shared, n);
                            uint32_t od = model_distance(other, shared, n);
                            if (od < d) d = od;
                            assert(nring_advance_read(users, 2, 1, done, done,
                                n, next, shared, &f.plan) == 0);
                            assert(f.plan.user_read_index == next && f.plan.delta == d &&
                                f.plan.shared_read_index == (shared + d) % n);
                        }
                    }
                }
            }
        }
    }
    assert(errno == SENTINEL_ERRNO);
}

static void advance_count(void)
{
    struct advance_fixture f;
    init_advance(&f);
    advance_error(&f, f.users, 5, 11, 3, 2, 8, 1, 6, &f.plan, ERANGE);
    advance_error(&f, f.users, 5, 11, 0, 4, 8, 1, 6, &f.plan, ERANGE);
    advance_error(&f, f.users, 5, 11, 0, 8, 8, 5, 6, &f.plan, ERANGE);
    advance_error(&f, f.users, 5, 11, SIZE_MAX, SIZE_MAX, 8, 1, 6, &f.plan, ERANGE);
    f.users[0].read_index = 7;
    f.users[1].read_index = 0;
    f.users[2].read_index = 1;
    errno = SENTINEL_ERRNO;
    assert(nring_advance_read(f.users, 5, 11, 0, 2, 8, 1, 6, &f.plan) == 0);
    assert(f.plan.user_read_index == 7 && f.plan.delta == 1 &&
        f.plan.shared_read_index == 7 && errno == SENTINEL_ERRNO);
    f.users[0].read_index = UINT32_MAX - 2;
    assert(nring_advance_read(f.users, 1, 11, 3, 3,
        UINT32_MAX, 1, UINT32_MAX - 3, &f.plan) == 0);
    assert(f.plan.user_read_index == 1 && f.plan.delta == 4 && f.plan.shared_read_index == 1);
    f.users[0].read_index = 0;
    assert(nring_advance_read(f.users, 1, 11, 0, 0, 1, 0, 0, &f.plan) == 0);
    assert(f.plan.user_read_index == 0 && f.plan.shared_read_index == 0 && f.plan.delta == 0);
    advance_error(&f, f.users, 1, 11, 0, 1, 1, 0, 0, &f.plan, ERANGE);
}

static void advance_users(void)
{
    struct advance_fixture f;
    init_advance(&f);
    advance_error(&f, f.users, 5, 999, 0, 0, 8, 1, 6, &f.plan, ENODATA);
    advance_error(&f, NULL, 0, 11, 0, 0, 8, 1, 6, &f.plan, ENODATA);
    advance_error(&f, f.users, 5, 44, 0, 0, 8, 1, 6, &f.plan, ENOTSUP);
    advance_error(&f, f.users, 5, 55, 0, 0, 8, 1, 6, &f.plan, ENOTSUP);
    f.users[1].id = 11;
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 1, 6, &f.plan, EINVAL);
    init_advance(&f);
    f.users[4].id = 44;
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 1, 6, &f.plan, EINVAL);
    init_advance(&f);
    f.users[1].read_index = 8;
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 1, 6, &f.plan, ERANGE);
    init_advance(&f);
    f.users[0].read_index = 8;
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 1, 6, &f.plan, ERANGE);
    init_advance(&f);
    for (size_t i = 0; i < 5; ++i) f.users[i].status = 0;
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 1, 6, &f.plan, ENOTSUP);
}

static void advance_spans(void)
{
    struct advance_fixture f;
    uintptr_t top = UINTPTR_MAX - UINTPTR_MAX % _Alignof(struct nring_advance);
    init_advance(&f);
    advance_error(&f, f.users, 5, 11, 0, 0, 0, 0, 0, &f.plan, EINVAL);
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 8, 6, &f.plan, ERANGE);
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 1, 8, &f.plan, ERANGE);
    advance_error(&f, NULL, 5, 11, 0, 0, 8, 1, 6, &f.plan, EINVAL);
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 1, 6, NULL, EINVAL);
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 1, 6,
        (struct nring_advance *)(void *)((uint8_t *)&f.plan + 1), EINVAL);
    advance_error(&f, (const struct nring_user *)(const void *)((const uint8_t *)f.users + 1),
        4, 11, 0, 0, 8, 1, 6, &f.plan, EINVAL);
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 1, 6,
        (struct nring_advance *)(void *)&f.users[4], EINVAL);
    advance_error(&f, f.users, SIZE_MAX / sizeof(*f.users) + 1,
        11, 0, 0, 8, 1, 6, &f.plan, EOVERFLOW);
    advance_error(&f, (const struct nring_user *)top, 1,
        11, 0, 0, 8, 1, 6, &f.plan, EOVERFLOW);
    advance_error(&f, f.users, 5, 11, 0, 0, 8, 1, 6,
        (struct nring_advance *)top, EOVERFLOW);
}

static void host_flow(void)
{
    struct copy_fixture f;
    struct nring_user users[2] = {{7, 3, 1}, {8, 3, 2}};
    struct nring_advance plan;
    uint32_t shared = 3;
    size_t consumed = 0;
    const size_t slots[3] = {4, 0, 1};
    init_copy(&f);
    errno = SENTINEL_ERRNO;
    assert(nring_copy_read_list(f.ring, 5 * 96, 5, 1, users[0].read_index,
        f.out, sizeof(f.out), &f.count) == 0);
    assert(f.count == 3 && users[0].read_index == 3 && shared == 3);
    /* HOST consumer really compares every copied byte before counting a slot. */
    for (size_t i = 0; i < f.count; ++i) {
        assert(memcmp(f.out + i * 96, f.ring + slots[i] * 96, 96) == 0);
        ++consumed;
    }
    assert(nring_advance_read(users, 2, 7, consumed, f.count, 5, 1, shared, &plan) == 0);
    assert(users[0].read_index == 3 && shared == 3);
    users[0].read_index = plan.user_read_index;
    shared = plan.shared_read_index;
    assert(users[0].read_index == 1 && shared == 3 && plan.delta == 0);
    assert(nring_copy_read_list(f.ring, 5 * 96, 5, 1, users[1].read_index,
        f.out, sizeof(f.out), &f.count) == 0);
    consumed = 0;
    for (size_t i = 0; i < f.count; ++i) {
        assert(memcmp(f.out + i * 96, f.ring + slots[i] * 96, 96) == 0);
        ++consumed;
    }
    assert(nring_advance_read(users, 2, 8, consumed, f.count, 5, 1, shared, &plan) == 0);
    users[1].read_index = plan.user_read_index;
    shared = plan.shared_read_index;
    assert(users[1].read_index == 1 && shared == 1 && plan.delta == 3);
    assert(nring_copy_read_list(f.ring, 5 * 96, 5, 1, users[0].read_index,
        NULL, 0, &f.count) == 0 && f.count == 0);
    assert(errno == SENTINEL_ERRNO);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "copy-order")) copy_order();
    else if (!strcmp(argv[1], "copy-empty")) copy_empty();
    else if (!strcmp(argv[1], "copy-invalid")) copy_invalid();
    else if (!strcmp(argv[1], "copy-alias")) copy_alias();
    else if (!strcmp(argv[1], "copy-overflow")) copy_overflow();
    else if (!strcmp(argv[1], "advance-min")) advance_min();
    else if (!strcmp(argv[1], "advance-count")) advance_count();
    else if (!strcmp(argv[1], "advance-users")) advance_users();
    else if (!strcmp(argv[1], "advance-spans")) advance_spans();
    else if (!strcmp(argv[1], "host-flow")) host_flow();
    else return 2;
    puts("HOST consumer-slot checks passed; native production remains blocked");
    return 0;
}
