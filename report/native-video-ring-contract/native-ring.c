#include "native-ring.h"

#include <errno.h>
#include <string.h>

static int span(const void *p, size_t n)
{
    if (n && !p) return EINVAL;
    return n > UINTPTR_MAX - (uintptr_t)p ? EOVERFLOW : 0;
}

static int overlaps(const void *a, size_t an, const void *b, size_t bn)
{
    return an && bn && (uintptr_t)a < (uintptr_t)b + bn &&
        (uintptr_t)b < (uintptr_t)a + an;
}

static uint32_t distance(uint32_t cursor, uint32_t base, uint32_t n)
{
    return cursor >= base ? cursor - base :
        (uint32_t)((uint64_t)cursor + n - base);
}

static uint32_t wrap_once(uint32_t cursor, uint32_t count, uint32_t n)
{
    uint64_t sum = (uint64_t)cursor + count;
    return (uint32_t)(sum >= n ? sum - n : sum);
}

static int active(uint32_t status)
{
    return status >= 1 && status <= 3;
}

int nring_copy_read_list(const uint8_t *ringbytes, size_t ring_capacity,
    uint32_t slot_count, uint32_t write_index, uint32_t user_read_index,
    uint8_t *out_bytes, size_t out_capacity, size_t *out_count)
{
    uint64_t ring_size = (uint64_t)slot_count * NRING_INFO_BYTES;
    uint32_t available, next;
    size_t first, needed;
    int rc, saved_errno = errno;
    if (!slot_count || !out_count ||
        (uintptr_t)out_count % _Alignof(size_t)) return EINVAL;
    if (write_index >= slot_count || user_read_index >= slot_count) return ERANGE;
    if (ring_size > SIZE_MAX) return EOVERFLOW;
    if ((rc = span(ringbytes, ring_capacity)) ||
        (rc = span(out_bytes, out_capacity)) ||
        (rc = span(out_count, sizeof(*out_count)))) return rc;
    if (overlaps(ringbytes, ring_capacity, out_bytes, out_capacity) ||
        overlaps(ringbytes, ring_capacity, out_count, sizeof(*out_count)) ||
        overlaps(out_bytes, out_capacity, out_count, sizeof(*out_count))) return EINVAL;
    if (ring_capacity < (size_t)ring_size) return ENOSPC;
    available = distance(write_index, user_read_index, slot_count);
    needed = (size_t)available * NRING_INFO_BYTES;
    if (out_capacity < needed) return ENOSPC;
    next = wrap_once(user_read_index, 1, slot_count);
    first = slot_count - next;
    if (first > available) first = available;
    if (first) memcpy(out_bytes, ringbytes + (size_t)next * NRING_INFO_BYTES,
        first * NRING_INFO_BYTES);
    if ((size_t)available > first) memcpy(out_bytes + first * NRING_INFO_BYTES,
        ringbytes, ((size_t)available - first) * NRING_INFO_BYTES);
    *out_count = available;
    errno = saved_errno;
    return 0;
}

int nring_advance_read(const struct nring_user *users, size_t user_count,
    uint32_t user_id, size_t returned_count, size_t borrowed_count,
    uint32_t slot_count, uint32_t write_index, uint32_t shared_read_index,
    struct nring_advance *result)
{
    size_t extent, selected = user_count;
    struct nring_advance plan;
    int rc;
    if (!slot_count || !result ||
        (uintptr_t)result % _Alignof(struct nring_advance) ||
        (user_count && (uintptr_t)users % _Alignof(struct nring_user))) return EINVAL;
    if (write_index >= slot_count || shared_read_index >= slot_count) return ERANGE;
    if (user_count > SIZE_MAX / sizeof(*users)) return EOVERFLOW;
    extent = user_count * sizeof(*users);
    if ((rc = span(users, extent)) ||
        (rc = span(result, sizeof(*result)))) return rc;
    if (overlaps(users, extent, result, sizeof(*result))) return EINVAL;
    for (size_t i = 0; i < user_count; ++i) {
        for (size_t j = 0; j < i; ++j)
            if (users[i].id == users[j].id) return EINVAL;
        if (active(users[i].status) && users[i].read_index >= slot_count) return ERANGE;
        if (users[i].id == user_id) selected = i;
    }
    if (selected == user_count) return ENODATA;
    if (!active(users[selected].status)) return ENOTSUP;
    if (returned_count > borrowed_count || borrowed_count >= slot_count ||
        borrowed_count > distance(write_index, users[selected].read_index, slot_count))
        return ERANGE;
    plan.user_read_index = wrap_once(users[selected].read_index,
        (uint32_t)returned_count, slot_count);
    plan.delta = slot_count;
    for (size_t i = 0; i < user_count; ++i) {
        uint32_t d;
        if (!active(users[i].status)) continue;
        d = distance(i == selected ? plan.user_read_index : users[i].read_index,
            shared_read_index, slot_count);
        if (d < plan.delta) plan.delta = d;
    }
    plan.shared_read_index = wrap_once(shared_read_index, plan.delta, slot_count);
    *result = plan;
    return 0;
}
