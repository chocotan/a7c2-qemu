/* SPDX-License-Identifier: MIT */
/* Host-only callbacks and backing files; no camera or guest is started. */
#define _POSIX_C_SOURCE 200809L
#include "sd-hotplug-adapter.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

struct fixture {
    struct sd_hotplug_adapter adapter;
    struct sd_hotplug_route route;
    sd_backing backing;
    sd_observation mount;
    unsigned tag, guards, validations, flushes, sends;
    bool guard_ok, backing_ok;
    int flush_rc;
    sd_send_result result;
    uint64_t expected_generation;
    sd_operation expected_operation;
    uint8_t payload[7];
};

static bool guard_a(void *context)
{
    struct fixture *f = context;
    assert(f->tag == 1);
    ++f->guards;
    return f->guard_ok;
}

static bool guard_b(void *context)
{
    struct fixture *f = context;
    assert(f->tag == 2);
    ++f->guards;
    return f->guard_ok;
}

static bool backing_ok(void *context, const sd_backing *b)
{
    struct fixture *f = context;
    ++f->validations;
    assert(b->fd == f->backing.fd && b->identity == f->backing.identity &&
           b->size == f->backing.size);
    struct stat st;
    return f->backing_ok && fstat(b->fd, &st) == 0 &&
        (uint64_t)st.st_ino == b->identity && (uint64_t)st.st_size == b->size;
}

static int flush(void *context, uint64_t generation, uint32_t drive)
{
    struct fixture *f = context;
    assert(generation == f->expected_generation && drive == f->mount.drive);
    ++f->flushes;
    return f->flush_rc;
}

static sd_observation observed(uint64_t gen, sd_observation_kind kind, uint32_t drive)
{
    return (sd_observation){.generation = gen, .kind = kind, .drive = drive,
        .genuine = true, .path_validated = true, .owned = true};
}

static sd_send_result send_common(void *context, unsigned tag, uint64_t gen,
    sd_operation op, uint32_t owner, uint32_t source, uint32_t destination,
    const uint8_t payload[7])
{
    struct fixture *f = context;
    assert(f->tag == tag && gen == f->expected_generation &&
           op == f->expected_operation);
    assert(owner == f->route.owner && source == f->route.source &&
           destination == f->route.destination);
    memcpy(f->payload, payload, 7);
    ++f->sends;
    sd_core *c = &f->adapter.core;
    sd_snapshot s;
    assert(sd_snapshot_read(c, &s) == SD_BUSY);
    assert(sd_request_apply(c, (sd_request){999, SD_EJECT}) == SD_BUSY);
    assert(sd_observe(c, observed(gen, SD_NOTIFY_FREE, 0)) == SD_BUSY);
    assert(sd_expire(c, (sd_timeout){gen}) == SD_BUSY);
    assert(sd_hotplug_bind(&f->adapter, &f->backing, &f->mount) == SD_BUSY);
    return f->result;
}

static sd_send_result send_a(void *p, uint64_t g, sd_operation o,
    uint32_t owner, uint32_t source, uint32_t destination, const uint8_t b[7])
{ return send_common(p, 1, g, o, owner, source, destination, b); }

static sd_send_result send_b(void *p, uint64_t g, sd_operation o,
    uint32_t owner, uint32_t source, uint32_t destination, const uint8_t b[7])
{ return send_common(p, 2, g, o, owner, source, destination, b); }

static void prepare(struct fixture *f, unsigned tag)
{
    *f = (struct fixture){.tag = tag, .guard_ok = true, .backing_ok = true,
        .result = {SD_SENT, false}, .expected_generation = 11};
    char path[] = "./sd-adapter-backing-XXXXXX";
    int fd = mkstemp(path);
    assert(fd >= 0 && unlink(path) == 0 && ftruncate(fd, 4096) == 0);
    const char sentinel[] = "unchanged SD backing";
    assert(pwrite(fd, sentinel, sizeof sentinel, 0) == (ssize_t)sizeof sentinel);
    assert(lseek(fd, 73, SEEK_SET) == 73);
    struct stat st;
    assert(fstat(fd, &st) == 0);
    f->backing = (sd_backing){fd, (uint64_t)st.st_ino, 4096};
    f->mount = observed(10, SD_MOUNT, 65 + tag);
    f->route = (struct sd_hotplug_route){0x11110000u + tag,
        0x22220000u + tag, 0x33330000u + tag};
    f->adapter.ops = (struct sd_hotplug_ops){.context = f,
        .guard = tag == 1 ? guard_a : guard_b, .backing_unchanged = backing_ok,
        .flush_original = flush, .send_notification = tag == 1 ? send_a : send_b};
    f->adapter.route = &f->route;
}

static void finish(struct fixture *f)
{
    char buf[sizeof "unchanged SD backing"];
    assert(pread(f->backing.fd, buf, sizeof buf, 0) == (ssize_t)sizeof buf);
    assert(memcmp(buf, "unchanged SD backing", sizeof buf) == 0);
    assert(lseek(f->backing.fd, 0, SEEK_CUR) == 73);
    assert(close(f->backing.fd) == 0);
}

static void bind_fixture(struct fixture *f)
{ assert(sd_hotplug_bind(&f->adapter, &f->backing, &f->mount) == SD_OK); }

static sd_snapshot snapshot(struct fixture *f)
{
    sd_snapshot s;
    assert(sd_snapshot_read(&f->adapter.core, &s) == SD_OK);
    return s;
}

static sd_result request(struct fixture *f, uint64_t seq, sd_operation op)
{
    f->expected_operation = op;
    return sd_request_apply(&f->adapter.core, (sd_request){seq, op});
}

static void test_required_inputs_and_mount(void)
{
    struct fixture f;
    prepare(&f, 1);
    struct sd_hotplug_ops ops = f.adapter.ops;
    assert(sd_hotplug_bind(NULL, &f.backing, &f.mount) == SD_INVALID);
    assert(sd_hotplug_bind(&f.adapter, NULL, &f.mount) == SD_INVALID);
    assert(sd_hotplug_bind(&f.adapter, &f.backing, NULL) == SD_INVALID);
    f.adapter.route = NULL;
    assert(sd_hotplug_bind(&f.adapter, &f.backing, &f.mount) == SD_INVALID);
    f.adapter.route = &f.route;
    for (unsigned i = 0; i < 5; ++i) {
        f.adapter.ops = ops;
        if (i == 0) f.adapter.ops.context = NULL;
        if (i == 1) f.adapter.ops.guard = NULL;
        if (i == 2) f.adapter.ops.backing_unchanged = NULL;
        if (i == 3) f.adapter.ops.flush_original = NULL;
        if (i == 4) f.adapter.ops.send_notification = NULL;
        assert(sd_hotplug_bind(&f.adapter, &f.backing, &f.mount) == SD_INVALID);
    }
    f.adapter.ops = ops;
    assert(f.guards == 0 && f.validations == 0);
    for (unsigned i = 0; i < 6; ++i) {
        sd_observation m = f.mount;
        if (i == 0) m.generation = 0;
        if (i == 1) m.kind = SD_UNMOUNT;
        if (i == 2) m.drive = 0;
        if (i == 3) m.rc = -5;
        if (i == 4) m.genuine = false;
        if (i == 5) m.path_validated = false;
        assert(sd_hotplug_bind(&f.adapter, &f.backing, &m) == SD_INVALID);
        sd_snapshot s;
        assert(sd_snapshot_read(&f.adapter.core, &s) == SD_UNBOUND);
    }
    sd_backing bad = f.backing;
    bad.fd = -1;
    assert(sd_hotplug_bind(&f.adapter, &bad, &f.mount) == SD_INVALID);
    bad = f.backing;
    bad.identity = 0;
    assert(sd_hotplug_bind(&f.adapter, &bad, &f.mount) == SD_INVALID);
    bad = f.backing;
    bad.size = 0;
    assert(sd_hotplug_bind(&f.adapter, &bad, &f.mount) == SD_INVALID);
    f.guard_ok = false;
    assert(sd_hotplug_bind(&f.adapter, &f.backing, &f.mount) == SD_GUARD_FAILED);
    f.guard_ok = true;
    f.backing_ok = false;
    assert(sd_hotplug_bind(&f.adapter, &f.backing, &f.mount) == SD_BACKING_FAILED);
    f.backing_ok = true;
    /* Core does not require owned for initial mount; preserve that contract. */
    f.mount.owned = false;
    bind_fixture(&f);
    sd_snapshot s = snapshot(&f);
    assert(s.state == SD_PRESENT && s.generation == f.mount.generation &&
           s.drive == f.mount.drive && s.sequence == 0 && s.bytes[5] == 2);
    assert(sd_hotplug_bind(&f.adapter, &f.backing, &f.mount) == SD_CONFLICT);
    assert(f.adapter.counters.guard_denied == 1 &&
           f.adapter.counters.backing_mismatch == 1);
    finish(&f);
}

static void test_instances_routing_observations(void)
{
    struct fixture a, b;
    prepare(&a, 1);
    prepare(&b, 2);
    b.mount.generation = 800;
    b.expected_generation = 801;
    bind_fixture(&a);
    bind_fixture(&b);
    a.guard_ok = false;
    assert(request(&a, 1, SD_EJECT) == SD_GUARD_FAILED);
    assert(a.adapter.counters.guard_denied == 1 && b.adapter.counters.guard_denied == 0);
    a.guard_ok = true;
    assert(request(&a, 1, SD_EJECT) == SD_PENDING);
    assert(request(&b, 1, SD_EJECT) == SD_PENDING);
    assert(a.sends == 1 && b.sends == 1 && a.flushes == 1 && b.flushes == 1);
    const uint8_t ejected[7] = {2, 0, 0, 2, 0, 0x10, 0};
    assert(memcmp(a.payload, ejected, 7) == 0 && memcmp(b.payload, ejected, 7) == 0);
    sd_core *c = &a.adapter.core;
    assert(snapshot(&a).state == SD_EJECTING && snapshot(&b).state == SD_EJECTING);
    assert(sd_observe(c, observed(801, SD_UNMOUNT, a.mount.drive)) == SD_STALE);
    assert(sd_observe(c, observed(11, SD_UNMOUNT, b.mount.drive)) == SD_MISMATCH);
    sd_observation free = observed(11, SD_NOTIFY_FREE, 0);
    free.owned = false;
    assert(sd_observe(c, free) == SD_MISMATCH);
    free.owned = true;
    free.genuine = false;
    assert(sd_observe(c, free) == SD_MISMATCH);
    assert(sd_observe(c, observed(11, SD_UNMOUNT, a.mount.drive)) == SD_PENDING);
    assert(snapshot(&a).state == SD_EJECTING);
    assert(sd_observe(c, observed(11, SD_NOTIFY_FREE, 0)) == SD_OK);
    assert(snapshot(&a).state == SD_ABSENT && snapshot(&b).state == SD_EJECTING);
    a.expected_generation = 12;
    assert(request(&a, 2, SD_INSERT) == SD_PENDING);
    const uint8_t inserted[7] = {2, 0, 0, 2, 0, 0x12, 0};
    assert(memcmp(a.payload, inserted, 7) == 0 && a.flushes == 1);
    assert(sd_observe(c, observed(11, SD_NOTIFY_FREE, 0)) == SD_STALE);
    assert(sd_observe(c, observed(12, SD_NOTIFY_FREE, 0)) == SD_PENDING);
    assert(snapshot(&a).state == SD_INSERTING);
    assert(sd_observe(c, observed(12, SD_MOUNT, 99)) == SD_OK);
    assert(snapshot(&a).state == SD_PRESENT && snapshot(&a).drive == 99);
    /* No observations for B: successful send is not completion. */
    assert(sd_expire(&b.adapter.core, (sd_timeout){801}) == SD_UNCERTAIN);
    assert(snapshot(&b).state == SD_FAILED_UNCERTAIN);
    assert(a.adapter.counters.sent == 2 && b.adapter.counters.sent == 1);
    finish(&a);
    finish(&b);
}

static void test_send_outcomes(void)
{
    for (unsigned delivery = SD_SENT; delivery <= SD_DELIVERY_UNCERTAIN; ++delivery) {
        for (unsigned ack = 0; ack < 2; ++ack) {
            struct fixture f;
            prepare(&f, 1);
            /* Supplied zero is preserved; absence of route is separately refused. */
            f.route.source = 0;
            f.result = (sd_send_result){(sd_delivery)delivery, ack != 0};
            bind_fixture(&f);
            sd_result wanted = delivery == SD_SENT ? SD_PENDING :
                delivery == SD_NOT_SENT && !ack ? SD_ROLLED_BACK : SD_UNCERTAIN;
            assert(request(&f, 1, SD_EJECT) == wanted);
            sd_snapshot s = snapshot(&f);
            assert(s.generation == 11);
            assert(s.state == (wanted == SD_PENDING ? SD_EJECTING :
                wanted == SD_ROLLED_BACK ? SD_PRESENT : SD_FAILED_UNCERTAIN));
            assert(s.bytes[5] == (wanted == SD_ROLLED_BACK ? 2 : 0x10));
            assert(f.adapter.counters.sent == (delivery == SD_SENT));
            assert(f.adapter.counters.not_sent == (delivery == SD_NOT_SENT));
            assert(f.adapter.counters.uncertain == (delivery == SD_DELIVERY_UNCERTAIN));
            if (wanted == SD_PENDING) {
                assert(sd_observe(&f.adapter.core,
                    observed(11, SD_UNMOUNT, f.mount.drive)) == SD_PENDING);
                assert(snapshot(&f).state == SD_EJECTING);
                assert(sd_expire(&f.adapter.core, (sd_timeout){11}) == SD_UNCERTAIN);
            }
            finish(&f);
        }
    }
}

static void test_failures_and_retry(void)
{
    struct fixture f;
    prepare(&f, 1);
    bind_fixture(&f);
    assert(ftruncate(f.backing.fd, 4097) == 0);
    assert(request(&f, 1, SD_EJECT) == SD_BACKING_FAILED);
    assert(f.adapter.counters.backing_mismatch == 1 && f.sends == 0 && f.flushes == 0);
    assert(ftruncate(f.backing.fd, 4096) == 0);
    f.flush_rc = -5;
    assert(request(&f, 2, SD_EJECT) == SD_QUIESCENCE_FAILED);
    assert(f.adapter.counters.flush_failed == 1 && f.sends == 0);
    assert(snapshot(&f).generation == 10 && snapshot(&f).bytes[5] == 2);
    f.flush_rc = 0;
    f.result = (sd_send_result){SD_NOT_SENT, false};
    assert(request(&f, 3, SD_EJECT) == SD_ROLLED_BACK);
    assert(request(&f, 3, SD_EJECT) == SD_DUPLICATE && f.sends == 1);
    assert(request(&f, 2, SD_EJECT) == SD_STALE);
    f.expected_generation = 12;
    f.result = (sd_send_result){SD_SENT, false};
    assert(request(&f, 4, SD_EJECT) == SD_PENDING);
    assert(sd_observe(&f.adapter.core, observed(11, SD_NOTIFY_FREE, 0)) == SD_STALE);
    sd_observation error = observed(12, SD_UNMOUNT, f.mount.drive);
    error.rc = -5;
    assert(sd_observe(&f.adapter.core, error) == SD_UNCERTAIN);
    assert(snapshot(&f).state == SD_FAILED_UNCERTAIN);
    assert(request(&f, 5, SD_INSERT) == SD_UNCERTAIN && f.sends == 2);
    finish(&f);
}

int main(void)
{
    test_required_inputs_and_mount();
    test_instances_routing_observations();
    test_send_outcomes();
    test_failures_and_retry();
    puts("PASS: 4 groups; inputs/mount, instances/routes/observations, six send outcomes, failures/retry");
    return 0;
}
