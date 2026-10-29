/* SPDX-License-Identifier: MIT */
#include "mbp-mailbox.h"

#include <errno.h>
#include <stddef.h>
#include <string.h>

static int span(const void *pointer, size_t bytes, size_t alignment)
{
    uintptr_t address = (uintptr_t)pointer;
    if (!pointer) return -EINVAL;
    if (bytes > UINTPTR_MAX - address) return -EOVERFLOW;
    return address % alignment ? -EINVAL : 0;
}

static int valid_owner(const imola_mbp *owner)
{
    int result = span(owner, sizeof *owner, _Alignof(imola_mbp));
    if (result) return result;
    return owner->initialized == 1 ? 0 : -EINVAL;
}

static int output_span(const imola_mbp *owner, const void *out,
                       size_t bytes, size_t alignment)
{
    int result = span(out, bytes, alignment);
    if (result) return result;
    if ((uintptr_t)out < (uintptr_t)owner + sizeof *owner &&
        (uintptr_t)owner < (uintptr_t)out + bytes) return -EINVAL;
    return 0;
}

static int endpoint(const imola_mbp *owner, unsigned channel, unsigned role,
                    uint32_t offset)
{
    int result = valid_owner(owner);
    if (result) return result;
    if (channel >= IMOLA_MBP_CHANNELS || role >= IMOLA_MBP_ROLES ||
        (offset & 3u)) return -EINVAL;
    return 0;
}

static imola_mbp_word status(const imola_mbp *owner, unsigned channel,
                              unsigned role)
{
    const imola_mbp_endpoint *self = &owner->endpoints[channel][role];
    const imola_mbp_endpoint *peer = &owner->endpoints[channel][role ^ 1u];
    imola_mbp_word word = {IMOLA_MBP_UNKNOWN_POISON & ~IMOLA_MBP_STATUS_KNOWN,
                           IMOLA_MBP_STATUS_KNOWN};
    if (!peer->pending) word.value |= IMOLA_MBP_TX_CAPACITY;
    if (self->pending) word.value |= IMOLA_MBP_RX_PENDING;
    return word;
}

int imola_mbp_init(imola_mbp *owner)
{
    int result = span(owner, sizeof *owner, _Alignof(imola_mbp));
    if (result) return result;
    if (owner->initialized) return -EALREADY;
    memset(owner, 0, sizeof *owner);
    owner->initialized = 1;
    return 0;
}

int imola_mbp_read(imola_mbp *owner, unsigned channel, unsigned role,
                   uint32_t offset, imola_mbp_word *out)
{
    int result = endpoint(owner, channel, role, offset);
    if (result) return result;
    result = output_span(owner, out, sizeof *out, _Alignof(imola_mbp_word));
    if (result) return result;
    if (offset == IMOLA_MBP_STATUS_DOORBELL) {
        *out = status(owner, channel, role);
        return 0;
    }
    if (offset != IMOLA_MBP_RX_COMMAND && offset != IMOLA_MBP_RX_ARGUMENT)
        return -ENOTSUP;
    imola_mbp_endpoint *self = &owner->endpoints[channel][role];
    if (!self->pending) return -ENODATA;
    unsigned index = (offset - IMOLA_MBP_RX_COMMAND) / 4u;
    imola_mbp_word word = {self->received[index], UINT32_MAX};
    self->read_mask |= 1u << index;
    *out = word;
    return 0;
}

int imola_mbp_write(imola_mbp *owner, unsigned channel, unsigned role,
                    uint32_t offset, uint32_t value)
{
    int result = endpoint(owner, channel, role, offset);
    if (result) return result;
    imola_mbp_endpoint *self = &owner->endpoints[channel][role];
    if (offset == IMOLA_MBP_TX_COMMAND || offset == IMOLA_MBP_TX_ARGUMENT) {
        unsigned index = offset / 4u;
        self->staging[index] = value;
        self->written_mask |= 1u << index;
        return 0;
    }
    if (offset != IMOLA_MBP_STATUS_DOORBELL) return -ENOTSUP;
    if (value == IMOLA_MBP_SUBMIT) {
        imola_mbp_endpoint *peer = &owner->endpoints[channel][role ^ 1u];
        if (self->written_mask != 3u) return -ENODATA;
        if (peer->pending) return -EBUSY;
        memcpy(peer->received, self->staging, sizeof peer->received);
        peer->pending = 1;
        peer->read_mask = 0;
        self->written_mask = 0;
        return 0;
    }
    if (value == IMOLA_MBP_ACK) {
        if (!self->pending) return -ENOENT;
        /* Conservative adapter guard; original hardware enforcement unproved. */
        if (self->read_mask != 3u) return -ENODATA;
        self->pending = 0;
        self->read_mask = 0;
        return 0;
    }
    return -ENOTSUP;
}

int imola_mbp_snapshot(const imola_mbp *owner, imola_mbp_info *out)
{
    int result = valid_owner(owner);
    if (result) return result;
    result = output_span(owner, out, sizeof *out, _Alignof(imola_mbp_info));
    if (result) return result;
    imola_mbp_info info = {0};
    info.diagnostic_only = IMOLA_MBP_DIAGNOSTIC_ONLY;
    info.owned_data_transport = IMOLA_MBP_OWNED_DATA_TRANSPORT;
    info.original_mcu_executed = IMOLA_MBP_ORIGINAL_MCU_EXECUTED;
    info.channels = IMOLA_MBP_CHANNELS;
    info.direction_capacity = IMOLA_MBP_VIRTUAL_DIRECTION_CAPACITY;
    for (unsigned channel = 0; channel < IMOLA_MBP_CHANNELS; ++channel) {
        for (unsigned role = 0; role < IMOLA_MBP_ROLES; ++role) {
            const imola_mbp_endpoint *self = &owner->endpoints[channel][role];
            imola_mbp_endpoint_info *item = &info.endpoints[channel][role];
            item->status = status(owner, channel, role);
            item->staged_words = self->written_mask;
            item->read_words = self->read_mask;
            item->pending = self->pending;
        }
    }
    *out = info;
    return 0;
}
