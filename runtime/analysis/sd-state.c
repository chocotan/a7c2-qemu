#include "sd-state.h"

static sd_result access_core(sd_core *c)
{
    if (!c) return SD_UNBOUND;
    if (c->callback) return SD_BUSY;
    if (!c->bound) return SD_UNBOUND;
    c->callback = true;
    bool ok = c->adapters.guard(c->adapters.context);
    c->callback = false;
    return ok ? SD_OK : SD_GUARD_FAILED;
}

static void bytes(const sd_core *c, uint8_t out[7])
{
    const uint8_t b[7] = {2, 0, 0, 2, 0,
        (uint8_t)((c->remove_count << 4) | (c->present ? 2 : 0)), 0};
    for (unsigned i = 0; i < 7; ++i) out[i] = b[i];
}

static sd_result uncertain(sd_core *c)
{
    c->state = SD_FAILED_UNCERTAIN;
    return SD_UNCERTAIN;
}

static bool validate(sd_core *c, bool quiescence, uint64_t generation)
{
    c->callback = true;
    bool ok = quiescence
        ? c->adapters.validate_quiescence(c->adapters.context, generation, c->drive)
        : c->adapters.validate_backing(c->adapters.context, &c->backing);
    c->callback = false;
    return ok;
}

sd_result sd_bind(sd_core *c, const sd_adapters *a, const sd_backing *b,
                  const sd_observation *m)
{
    if (!c || !a || !b || !m || !a->guard || !a->validate_backing ||
        !a->validate_quiescence || !a->notify) return SD_INVALID;
    if (c->callback) return SD_BUSY;
    if (c->bound) return SD_CONFLICT;
    c->callback = true;
    bool guarded = a->guard(a->context);
    c->callback = false;
    if (!guarded) return SD_GUARD_FAILED;
    if (b->fd < 0 || !b->identity || !b->size || !m->generation ||
        m->kind != SD_MOUNT || !m->genuine || !m->path_validated ||
        m->rc || !m->drive) return SD_INVALID;
    c->callback = true;
    bool valid = a->validate_backing(a->context, b);
    c->callback = false;
    if (!valid) return SD_BACKING_FAILED;
    *c = (sd_core){ .adapters = *a, .backing = *b, .state = SD_PRESENT,
        .generation = m->generation, .drive = m->drive,
        .bound = true, .present = true };
    return SD_OK;
}

static sd_result request_new(sd_core *c, sd_operation op)
{
    if (c->state == SD_FAILED_UNCERTAIN) return SD_UNCERTAIN;
    if (c->state == SD_EJECTING || c->state == SD_INSERTING)
        return c->operation == op ? SD_PENDING : SD_BUSY;
    if ((op == SD_EJECT && c->state == SD_ABSENT) ||
        (op == SD_INSERT && c->state == SD_PRESENT)) return SD_ALREADY;
    if (c->generation == UINT64_MAX) return SD_EXHAUSTED;
    uint64_t next = c->generation + 1;
    if (!validate(c, false, next)) return SD_BACKING_FAILED;
    if (op == SD_EJECT && !validate(c, true, next))
        return SD_QUIESCENCE_FAILED;

    uint8_t previous_count = c->remove_count;
    c->generation = next;
    c->operation = op;
    c->attempted = true;
    c->fs_ack = c->free_ack = false;
    c->observed_drive = 0;
    c->present = op == SD_INSERT;
    c->state = op == SD_EJECT ? SD_EJECTING : SD_INSERTING;
    if (op == SD_EJECT) c->remove_count = (c->remove_count + 1) & 15;
    uint8_t payload[7];
    bytes(c, payload);
    c->callback = true;
    sd_send_result sent = c->adapters.notify(c->adapters.context, next, op, payload);
    c->callback = false;
    if (sent.delivery == SD_NOT_SENT && !sent.observable_ack) {
        c->present = op == SD_EJECT;
        c->state = c->present ? SD_PRESENT : SD_ABSENT;
        c->remove_count = previous_count;
        return SD_ROLLED_BACK;
    }
    if (sent.delivery != SD_SENT) return uncertain(c);
    return SD_PENDING;
}

sd_result sd_request_apply(sd_core *c, sd_request r)
{
    sd_result rc = access_core(c);
    if (rc != SD_OK) return rc;
    if (!r.sequence || (r.operation != SD_EJECT && r.operation != SD_INSERT))
        return SD_INVALID;
    if (r.sequence < c->sequence) return SD_STALE;
    if (r.sequence == c->sequence) {
        if (r.operation != c->last_operation) return SD_CONFLICT;
        return c->state == SD_FAILED_UNCERTAIN ? SD_UNCERTAIN : SD_DUPLICATE;
    }
    c->sequence = r.sequence;
    c->last_operation = r.operation;
    return request_new(c, r.operation);
}

sd_result sd_observe(sd_core *c, sd_observation o)
{
    sd_result rc = access_core(c);
    if (rc != SD_OK) return rc;
    if (!o.generation || o.generation != c->generation) return SD_STALE;
    if (!c->attempted) return SD_MISMATCH;
    if (o.kind != SD_MOUNT && o.kind != SD_UNMOUNT && o.kind != SD_NOTIFY_FREE)
        return SD_INVALID;
    if (!o.genuine || (o.kind == SD_NOTIFY_FREE && !o.owned)) return SD_MISMATCH;
    if (o.rc) return uncertain(c);
    if (c->state == SD_FAILED_UNCERTAIN) return SD_UNCERTAIN;
    bool active = c->state == SD_EJECTING || c->state == SD_INSERTING;
    if (o.kind == SD_NOTIFY_FREE) {
        if (c->free_ack) return SD_DUPLICATE;
        if (!active) return uncertain(c);
        c->free_ack = true;
    } else {
        if ((c->operation == SD_EJECT && o.kind != SD_UNMOUNT) ||
            (c->operation == SD_INSERT && o.kind != SD_MOUNT)) return SD_MISMATCH;
        if (o.kind == SD_UNMOUNT &&
            o.drive != (c->fs_ack ? c->observed_drive : c->drive)) return SD_MISMATCH;
        if (o.kind == SD_MOUNT && (!o.drive || !o.path_validated))
            return uncertain(c);
        if (c->fs_ack)
            return c->observed_drive == o.drive ? SD_DUPLICATE : uncertain(c);
        if (!active) return uncertain(c);
        c->fs_ack = true;
        c->observed_drive = o.drive;
    }
    if (!c->fs_ack || !c->free_ack) return SD_PENDING;
    c->state = c->operation == SD_EJECT ? SD_ABSENT : SD_PRESENT;
    c->drive = c->operation == SD_EJECT ? 0 : c->observed_drive;
    return SD_OK;
}

sd_result sd_expire(sd_core *c, sd_timeout t)
{
    sd_result rc = access_core(c);
    if (rc != SD_OK) return rc;
    if (!t.generation || t.generation != c->generation) return SD_STALE;
    if (c->state == SD_FAILED_UNCERTAIN) return SD_UNCERTAIN;
    return c->state == SD_EJECTING || c->state == SD_INSERTING
        ? uncertain(c) : SD_ALREADY;
}

sd_result sd_snapshot_read(sd_core *c, sd_snapshot *s)
{
    sd_result rc = access_core(c);
    if (rc != SD_OK) return rc;
    if (!s) return SD_INVALID;
    *s = (sd_snapshot){ .state = c->state, .generation = c->generation,
        .sequence = c->sequence, .drive = c->drive };
    bytes(c, s->bytes);
    return SD_OK;
}
