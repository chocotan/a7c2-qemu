/* SPDX-License-Identifier: MIT */
#ifndef A7PF_MIGRATION_TEST
#include "qemu/osdep.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "system/address-spaces.h"
#include "qapi/error.h"
#include "qemu/error-report.h"
#include "qemu/module.h"
#include "migration/vmstate.h"
#else
#include <glib.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define error_report(...) g_printerr(__VA_ARGS__)
typedef struct A7PFDevice A7PFDevice;
#endif
#include "flash-core.h"
/* The source installer includes this TU from virt.c to keep copied builds small. */
#include "flash-core.c"
#define TYPE_A7PF "sony-persistent-flash"
#ifndef A7PF_MIGRATION_TEST
OBJECT_DECLARE_SIMPLE_TYPE(A7PFDevice, A7PF)
#endif
/* Incoming fields stay separate from the freshly realized FD and live registers. */
typedef struct A7PFMigration {
    uint64_t dev, ino, capacity, container_bytes;
    struct a7pf_slice slices[32];
    uint32_t entries, parts, boot_count, select, count, status, actual, error;
    uint64_t sector, dma_addr, geometry_size, geometry_start;
    uint8_t disk_sha256[32];
} A7PFMigration;
struct A7PFDevice {
#ifndef A7PF_MIGRATION_TEST
    SysBusDevice parent_obj;
    MemoryRegion mmio;
#endif
    struct a7pf core;
    char *backend, *geometry;
    uint64_t expected_dev, expected_ino;
    int32_t backend_fd;
    bool opened, retained_state;
    A7PFMigration migration;
};

static int a7pf_geometry_valid(const struct a7pf *c)
{
    uint64_t end = 0;
    uint32_t previous = 0, parts = 0, boots = 0;
    if (!c->capacity || (c->capacity & 511) ||
        c->capacity > INT64_MAX - 8388608 || c->entries > 32) {
        return -EINVAL;
    }
    for (uint32_t i = 0; i < 32; i++) {
        const struct a7pf_slice *sl = &c->slices[i];
        if (i >= c->entries) {
            if (sl->number || sl->offset || sl->length) {
                return -EINVAL;
            }
            continue;
        }
        if (sl->number <= previous || sl->number > 32 || !sl->length ||
            (sl->offset & 511) || (sl->length & 511) || sl->offset < end) {
            return -EINVAL;
        }
        if (sl->number <= 30) {
            if (sl->offset > c->capacity ||
                sl->length > c->capacity - sl->offset) {
                return -EINVAL;
            }
            parts++;
        } else {
            if (sl->number != 31 + boots || sl->length != 4194304 ||
                sl->offset != c->capacity + boots * 4194304ull) {
                return -EINVAL;
            }
            boots++;
        }
        previous = sl->number;
        end = sl->offset + sl->length;
    }
    return ((boots && boots != 2) || boots != c->boot_count ||
            parts != c->parts ||
            c->container_bytes != c->capacity + boots * 4194304ull) ?
           -EINVAL : 0;
}

static bool a7pf_same_stamp(const struct stat *a, const struct stat *b)
{
    return a->st_dev == b->st_dev && a->st_ino == b->st_ino &&
           a->st_size == b->st_size && a->st_mode == b->st_mode &&
           a->st_uid == b->st_uid && a->st_gid == b->st_gid &&
           a->st_nlink == b->st_nlink &&
           a->st_mtim.tv_sec == b->st_mtim.tv_sec &&
           a->st_mtim.tv_nsec == b->st_mtim.tv_nsec &&
           a->st_ctim.tv_sec == b->st_ctim.tv_sec &&
           a->st_ctim.tv_nsec == b->st_ctim.tv_nsec;
}

static int a7pf_disk_hash(A7PFDevice *s, uint8_t digest[32], bool sync)
{
    struct a7pf *c = &s->core;
    struct stat before, after;
    int err = a7pf_geometry_valid(c);
    if (err) {
        return err;
    }
    err = backend_valid(c);
    if (err) {
        return -err;
    }
    /* Use the actual syscall, never the optional core IO test callbacks. */
    if (sync && fdatasync(c->fd)) {
        return -errno;
    }
    if (fstat(c->fd, &before)) {
        return -errno;
    }
    err = backend_valid(c);
    if (err) {
        return -err;
    }
    GChecksum *hash = g_checksum_new(G_CHECKSUM_SHA256);
    uint8_t *buffer = g_malloc(A7PF_MAX_IO);
    err = 0;
    for (uint64_t off = 0; off < c->container_bytes;) {
        size_t bytes = MIN((uint64_t)A7PF_MAX_IO, c->container_bytes - off);
        ssize_t got = pread(c->fd, buffer, bytes, off);
        if (got < 0) {
            if (errno == EINTR) {
                continue;
            }
            err = -errno;
            break;
        }
        if (got != (ssize_t)bytes) {
            err = -EIO;
            break;
        }
        g_checksum_update(hash, buffer, bytes);
        off += bytes;
    }
    if (!err && fstat(c->fd, &after)) {
        err = -errno;
    }
    if (!err && !a7pf_same_stamp(&before, &after)) {
        err = -ESTALE;
    }
    if (!err) {
        err = -backend_valid(c);
    }
    if (!err) {
        gsize length = 32;
        g_checksum_get_digest(hash, digest, &length);
    }
    g_free(buffer);
    g_checksum_free(hash);
    return err;
}

static void a7pf_copy_state(A7PFMigration *m, const struct a7pf *c)
{
    m->dev = c->dev;
    m->ino = c->ino;
    m->capacity = c->capacity;
    m->container_bytes = c->container_bytes;
    memcpy(m->slices, c->slices, sizeof(m->slices));
    m->entries = c->entries;
    m->parts = c->parts;
    m->boot_count = c->boot_count;
    m->select = c->select;
    m->count = c->count;
    m->status = c->status;
    m->actual = c->actual;
    m->error = c->error;
    m->sector = c->sector;
    m->dma_addr = c->dma_addr;
    m->geometry_size = c->geometry_size;
    m->geometry_start = c->geometry_start;
}

static int a7pf_pre_save(void *opaque)
{
    A7PFDevice *s = opaque;
    if (!s->retained_state) {
        error_report("persistent flash: retained-state is disabled\n");
        return -EOPNOTSUPP;
    }
    if (!s->opened) {
        return -EBADF;
    }
    if (s->core.dev != s->expected_dev || s->core.ino != s->expected_ino) {
        return -ESTALE;
    }
    int err = a7pf_disk_hash(s, s->migration.disk_sha256, true);
    if (err) {
        error_report("persistent flash: pre_save disk validation: %s\n",
                     strerror(-err));
        return err;
    }
    /* All IO completes synchronously under BQL; DONE/FAILED are completed IO. */
    a7pf_copy_state(&s->migration, &s->core);
    return 0;
}

static int a7pf_post_load(void *opaque, int version_id)
{
    A7PFDevice *s = opaque;
    const A7PFMigration *m = &s->migration;
    struct a7pf *c = &s->core;
    uint8_t digest[32];
    int err;
    if (!s->retained_state || version_id != 1) {
        return -EOPNOTSUPP;
    }
    if (!s->opened) {
        return -EBADF;
    }
    if (m->dev != c->dev || m->ino != c->ino ||
        m->dev != s->expected_dev || m->ino != s->expected_ino ||
        m->capacity != c->capacity || m->container_bytes != c->container_bytes ||
        m->entries != c->entries || m->parts != c->parts ||
        m->boot_count != c->boot_count) {
        return -ESTALE;
    }
    for (uint32_t i = 0; i < 32; i++) {
        if (m->slices[i].number != c->slices[i].number ||
            m->slices[i].offset != c->slices[i].offset ||
            m->slices[i].length != c->slices[i].length) {
            return -ESTALE;
        }
    }
    err = a7pf_disk_hash(s, digest, false);
    if (!err && memcmp(digest, m->disk_sha256, sizeof(digest))) {
        err = -ESTALE;
    }
    if (err) {
        error_report("persistent flash: post_load disk validation: %s\n",
                     strerror(-err));
        return err;
    }
    c->select = m->select;
    c->count = m->count;
    c->status = m->status;
    c->actual = m->actual;
    c->error = m->error;
    c->sector = m->sector;
    c->dma_addr = m->dma_addr;
    c->geometry_size = m->geometry_size;
    c->geometry_start = m->geometry_start;
    return 0;
}

#ifndef A7PF_MIGRATION_TEST
static const VMStateDescription a7pf_slice_vmstate = {
    .name = "sony-persistent-flash/slice",
    .version_id = 1,
    .minimum_version_id = 1,
    .fields = (const VMStateField[]) {
        VMSTATE_UINT32(number, struct a7pf_slice),
        VMSTATE_UINT64(offset, struct a7pf_slice),
        VMSTATE_UINT64(length, struct a7pf_slice),
        VMSTATE_END_OF_LIST()
    },
};
static const VMStateDescription a7pf_vmstate = {
    .name = TYPE_A7PF,
    .version_id = 1,
    .minimum_version_id = 1,
    .pre_save = a7pf_pre_save,
    .post_load = a7pf_post_load,
    .fields = (const VMStateField[]) {
        VMSTATE_UINT64(migration.dev, A7PFDevice),
        VMSTATE_UINT64(migration.ino, A7PFDevice),
        VMSTATE_UINT64(migration.capacity, A7PFDevice),
        VMSTATE_UINT64(migration.container_bytes, A7PFDevice),
        VMSTATE_STRUCT_ARRAY(migration.slices, A7PFDevice, 32, 0,
                             a7pf_slice_vmstate, struct a7pf_slice),
        VMSTATE_UINT32(migration.entries, A7PFDevice),
        VMSTATE_UINT32(migration.parts, A7PFDevice),
        VMSTATE_UINT32(migration.boot_count, A7PFDevice),
        VMSTATE_UINT32(migration.select, A7PFDevice),
        VMSTATE_UINT32(migration.count, A7PFDevice),
        VMSTATE_UINT32(migration.status, A7PFDevice),
        VMSTATE_UINT32(migration.actual, A7PFDevice),
        VMSTATE_UINT32(migration.error, A7PFDevice),
        VMSTATE_UINT64(migration.sector, A7PFDevice),
        VMSTATE_UINT64(migration.dma_addr, A7PFDevice),
        VMSTATE_UINT64(migration.geometry_size, A7PFDevice),
        VMSTATE_UINT64(migration.geometry_start, A7PFDevice),
        VMSTATE_UINT8_ARRAY(migration.disk_sha256, A7PFDevice, 32),
        VMSTATE_END_OF_LIST()
    },
};
static int a7pf_ram_dma(void *opaque, uint64_t addr, void *data, size_t size,
                         bool write, bool probe)
{
    uint64_t cursor=addr, remaining=size;
    (void)opaque;
    RCU_READ_LOCK_GUARD();
    while (remaining) {
        hwaddr translated, span=remaining;
        MemoryRegion *mr=address_space_translate(&address_space_memory, cursor,
                                                  &translated, &span, write,
                                                  MEMTXATTRS_UNSPECIFIED);
        if (!mr || !span || !memory_region_is_ram(mr) || mr->readonly ||
            memory_region_is_ram_device(mr)) return EFAULT;
        cursor+=span; remaining-=span;
    }
    if (!probe) {
        MemTxResult result = write ?
            address_space_write(&address_space_memory, addr, MEMTXATTRS_UNSPECIFIED, data, size) :
            address_space_read(&address_space_memory, addr, MEMTXATTRS_UNSPECIFIED, data, size);
        if (result!=MEMTX_OK) return EFAULT;
    }
    return 0;
}
static uint64_t a7pf_mmio_read(void *opaque, hwaddr offset, unsigned size)
{ return a7pf_read_reg(&A7PF(opaque)->core, offset); }
static void a7pf_mmio_write(void *opaque, hwaddr offset, uint64_t value, unsigned size)
{ a7pf_write_reg(&A7PF(opaque)->core, offset, value); }
static const MemoryRegionOps a7pf_ops = {
    .read=a7pf_mmio_read, .write=a7pf_mmio_write, .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4, .max_access_size=4, .unaligned=false},
    .impl={.min_access_size=4, .max_access_size=4, .unaligned=false},
};
static void a7pf_realize(DeviceState *dev, Error **errp)
{
    A7PFDevice *s=A7PF(dev);
    int backend=-1, geometry=-1, err=EINVAL;
    if ((!s->backend && s->backend_fd<0) || (s->backend && s->backend_fd>=0) ||
        !s->geometry || !s->expected_dev || !s->expected_ino) goto failed;
    backend=s->backend_fd>=0 ? fcntl(s->backend_fd,F_DUPFD_CLOEXEC,3) :
                              a7pf_open_regular(s->backend, O_RDWR);
    if (backend<0) { err=errno; goto failed; }
    geometry=a7pf_open_regular(s->geometry, O_RDONLY);
    if (geometry<0) { err=errno; goto failed; }
    err=a7pf_init(&s->core, backend, geometry, s->expected_dev, s->expected_ino,
                   a7pf_ram_dma, s);
    if (err) goto failed;
    s->opened=true;
    close(backend); close(geometry);
    return;
failed:
    if (backend>=0) close(backend);
    if (geometry>=0) close(geometry);
    error_setg_errno(errp, err, "persistent flash backend/geometry rejected");
}
static void a7pf_unrealize(DeviceState *dev)
{
    A7PFDevice *s=A7PF(dev);
    if (s->opened) a7pf_close(&s->core);
    s->opened=false;
}
static const Property a7pf_props[] = {
    DEFINE_PROP_STRING("backend", A7PFDevice, backend),
    DEFINE_PROP_INT32("backend-fd", A7PFDevice, backend_fd, -1),
    DEFINE_PROP_STRING("geometry", A7PFDevice, geometry),
    DEFINE_PROP_UINT64("expected-dev", A7PFDevice, expected_dev, 0),
    DEFINE_PROP_UINT64("expected-ino", A7PFDevice, expected_ino, 0),
    DEFINE_PROP_BOOL("retained-state", A7PFDevice, retained_state, false),
};
static void a7pf_instance_init(Object *obj)
{
    A7PFDevice *s=A7PF(obj);
    s->core.fd=-1;
    memory_region_init_io(&s->mmio, obj, &a7pf_ops, s, TYPE_A7PF, 0x1000);
    sysbus_init_mmio(SYS_BUS_DEVICE(obj), &s->mmio);
}
static void a7pf_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(klass);
    dc->realize=a7pf_realize; dc->unrealize=a7pf_unrealize;
    dc->vmsd=&a7pf_vmstate;
    device_class_set_props(dc, a7pf_props);
    dc->desc="Functional persistent raw flash with validated slices (not Sony physical eMMC)";
    dc->user_creatable=true;
}
static const TypeInfo a7pf_type = {
    .name=TYPE_A7PF, .parent=TYPE_SYS_BUS_DEVICE,
    .instance_size=sizeof(A7PFDevice), .instance_init=a7pf_instance_init,
    .class_init=a7pf_class_init,
};
static void a7pf_register_types(void) { type_register_static(&a7pf_type); }
type_init(a7pf_register_types)
#endif /* !A7PF_MIGRATION_TEST */
