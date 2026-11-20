/* SPDX-License-Identifier: GPL-2.0-or-later
 * Functional AP/CP PCI RAM views; physical=false.
 *
 * Interface: explicit side=ap|cp, local-backend, peer-backend, and optional
 * AP-only peer-oom-backend (all HostMemoryBackend links). Region 0 is an
 * unassigned container for native eDMA's pci-memory; never map it to a CPU.
 * AP peer aliases: 0 and 0x400000000. CP peer aliases: 0x400000000 and
 * 0x800000000. Separate AP/CP local ring backing is mandatory.
 *
 * Address evidence: native-link-batch-plan/RING-DIRECTIONS.md, 2026-11-11.
 * This device creates no RAM files, copies no bytes, and provides no IRQ,
 * readiness, envelope, wakeup or acknowledgement. Migration is unsupported
 * until a paired RAM/transport lifecycle contract is defined.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "qemu/units.h"
#include "hw/core/boards.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/sysbus.h"
#include "migration/vmstate.h"
#include "qapi/error.h"
#include "system/address-spaces.h"
#include "system/hostmem.h"
#include "system/ramblock.h"
#include "native-link-board.h"

#define TYPE_NATIVE_PEER_RAM "a7c2-native-peer-ram"
OBJECT_DECLARE_SIMPLE_TYPE(NativePeerRAM, NATIVE_PEER_RAM)

#define AP_VIRT_RAM_BASE UINT64_C(0x40000000)
#define AP_DDR_BASE UINT64_C(0x400000000)
#define AP_DDR_FILE_OFFSET (AP_DDR_BASE - AP_VIRT_RAM_BASE)
#define CP_RING_PCI_BASE UINT64_C(0x800000000)
#define CP_LOCAL_SIZE (UINT64_C(128) * MiB)
#define CP_PEER_MAX_SIZE (UINT64_C(256) * MiB)
#define AP_PEER_MAX_SIZE (UINT64_C(8) * GiB)
#define CP_OOM_BASE UINT64_C(0x0ca21000)
#define CP_OOM_SIZE UINT64_C(0x101000)

G_STATIC_ASSERT(AP_DDR_FILE_OFFSET == UINT64_C(0x3c0000000));
G_STATIC_ASSERT(AP_DDR_FILE_OFFSET == UINT64_C(15) * GiB);

/* Borrowed FD identity and extent; no path lookup, open, close or file I/O. */
typedef struct PeerRAMView {
    MemoryRegion *mr;
    int fd;
    dev_t dev;
    ino_t ino;
    uint64_t file_size;
    uint64_t offset;
    uint64_t size;
} PeerRAMView;

typedef struct PeerRAMWindow {
    MemoryRegion *source;
    uint64_t base;
    uint64_t size;
    const char *name;
} PeerRAMWindow;

struct NativePeerRAM {
    SysBusDevice parent_obj;
    char *side;
    HostMemoryBackend *local_backend;
    HostMemoryBackend *peer_backend;
    HostMemoryBackend *peer_oom_backend;
    MemoryRegion pci_memory;
    MemoryRegion aliases[4];
    unsigned alias_count;
    bool peer_claimed;
    bool oom_claimed;
};

static bool peer_ram_extent_fits(uint64_t offset, uint64_t size, uint64_t length)
{
    return size && offset <= length && size <= length - offset;
}

static bool peer_ram_backend_view(HostMemoryBackend *backend, const char *name,
                                  PeerRAMView *view, Error **errp)
{
    MemoryRegion *mr;
    struct stat st;
    Error *local_err = NULL;
    int flags;
    bool discard_data;

    if (!backend || strcmp(object_get_typename(OBJECT(backend)),
                           TYPE_MEMORY_BACKEND_FILE)) {
        error_setg(errp, "%s requires memory-backend-file", name);
        return false;
    }
    mr = host_memory_backend_get_memory(backend);
    if (!mr || !memory_region_is_ram(mr) || memory_region_is_rom(mr) ||
        memory_region_is_ram_device(mr) || !mr->ram_block ||
        !QTAILQ_EMPTY(&mr->subregions)) {
        error_setg(errp, "%s requires initialized plain writable RAM", name);
        return false;
    }
    if (!backend->share || backend->guest_memfd ||
        !qemu_ram_is_shared(mr->ram_block) ||
        !qemu_ram_is_named_file(mr->ram_block)) {
        error_setg(errp, "%s requires shared file RAM without guest-memfd", name);
        return false;
    }
    discard_data = object_property_get_bool(OBJECT(backend), "discard-data",
                                            &local_err);
    if (local_err) {
        error_propagate(errp, local_err);
        return false;
    }
    if (discard_data) {
        error_setg(errp, "%s requires discard-data=false", name);
        return false;
    }

    view->mr = mr;
    view->fd = memory_region_get_fd(mr);
    if (view->fd < 0) {
        error_setg(errp, "%s has no backing FD", name);
        return false;
    }
    if (fstat(view->fd, &st) < 0) {
        error_setg_errno(errp, errno, "%s: backing FD fstat failed", name);
        return false;
    }
    /* Linux memfd has nlink=0; hard-linked AP/CP RAM has nlink>1. */
    if (!S_ISREG(st.st_mode) || st.st_nlink != 1 || st.st_size <= 0) {
        error_setg(errp, "%s requires a nonempty S_IFREG file with nlink=1", name);
        return false;
    }
    flags = fcntl(view->fd, F_GETFL);
    if (flags < 0) {
        error_setg_errno(errp, errno, "%s: backing FD F_GETFL failed", name);
        return false;
    }
    if ((flags & O_ACCMODE) != O_RDWR) {
        error_setg(errp, "%s requires a writable shared backing FD", name);
        return false;
    }

    view->dev = st.st_dev;
    view->ino = st.st_ino;
    view->file_size = (uint64_t)st.st_size;
    view->offset = qemu_ram_get_fd_offset(mr->ram_block);
    view->size = memory_region_size(mr);
    if (view->size != backend->size ||
        !peer_ram_extent_fits(view->offset, view->size, view->file_size)) {
        error_setg(errp, "%s: RAM extent does not fit the backing FD", name);
        return false;
    }
    return true;
}

static bool peer_ram_distinct(const PeerRAMView *a, const PeerRAMView *b,
                              const char *names, Error **errp)
{
    if (a->dev == b->dev && a->ino == b->ino) {
        error_setg(errp, "%s must use different backing file inodes", names);
        return false;
    }
    return true;
}

static bool peer_ram_available(HostMemoryBackend *backend,
                               const PeerRAMView *view, const char *name,
                               Error **errp)
{
    if (host_memory_backend_is_mapped(backend) ||
        memory_region_is_mapped(view->mr)) {
        error_setg(errp, "%s is already owned by a mapping", name);
        return false;
    }
    return true;
}

static bool peer_ram_check_windows(const PeerRAMWindow *windows, unsigned count,
                                   Error **errp)
{
    for (unsigned i = 0; i < count; i++) {
        const PeerRAMWindow *a = &windows[i];

        if (!peer_ram_extent_fits(a->base, a->size, UINT64_MAX)) {
            error_setg(errp, "%s: PCI window overflows uint64", a->name);
            return false;
        }
        for (unsigned j = 0; j < i; j++) {
            const PeerRAMWindow *b = &windows[j];

            if (a->base < b->base + b->size && b->base < a->base + a->size) {
                error_setg(errp, "%s overlaps %s", a->name, b->name);
                return false;
            }
        }
    }
    return true;
}

MemoryRegion *a7c2_native_local_oom(MachineState *machine, Error **errp)
{
    Object *object = object_resolve_path_component(object_get_objects_root(), "native-local-oom");
    HostMemoryBackend *backend = object && object_dynamic_cast(object, TYPE_MEMORY_BACKEND) ?
        MEMORY_BACKEND(object) : NULL;
    PeerRAMView local = { 0 }, oom = { 0 };
    if (!peer_ram_backend_view(machine->memdev, "CP local RAM", &local, errp) ||
        !peer_ram_backend_view(backend, "CP local OOM RAM", &oom, errp) ||
        !peer_ram_distinct(&local, &oom, "CP primary and OOM RAM", errp) ||
        !peer_ram_available(backend, &oom, "CP local OOM RAM", errp)) {
        return NULL;
    }
    if (oom.offset || oom.size != CP_OOM_SIZE) {
        error_setg(errp, "CP local OOM RAM requires offset=0,size=0x101000");
        return NULL;
    }
    return machine_consume_memdev(machine, backend);
}

static void native_peer_ram_realize(DeviceState *dev, Error **errp)
{
    NativePeerRAM *s = NATIVE_PEER_RAM(dev);
    PeerRAMView local = { 0 }, peer = { 0 }, oom = { 0 };
    PeerRAMWindow windows[4];
    unsigned count = 2;
    bool ap;

    if (s->side && !strcmp(s->side, "ap")) {
        ap = true;
    } else if (s->side && !strcmp(s->side, "cp")) {
        ap = false;
    } else {
        error_setg(errp, "native peer RAM requires explicit side=ap or side=cp");
        return;
    }
    if (!ap && s->peer_oom_backend) {
        error_setg(errp, "peer-oom-backend is only supported for side=ap");
        return;
    }
    if (memory_region_is_mapped(&s->pci_memory)) {
        error_setg(errp, "native peer RAM container must not be CPU-mapped");
        return;
    }
    if (!peer_ram_backend_view(s->local_backend, "local-backend", &local, errp) ||
        !peer_ram_backend_view(s->peer_backend, "peer-backend", &peer, errp) ||
        !peer_ram_distinct(&local, &peer, "local-backend and peer-backend", errp)) {
        return;
    }
    /* The machine owns its CPU RAM; never acquire or clear that mapped bit. */
    if (MACHINE(qdev_get_machine())->ram != local.mr ||
        !host_memory_backend_is_mapped(s->local_backend) ||
        local.mr->container != get_system_memory() ||
        local.mr->addr != (ap ? AP_VIRT_RAM_BASE : 0)) {
        error_setg(errp, "local-backend must be machine RAM directly mapped at %s",
                   ap ? "0x40000000" : "0");
        return;
    }
    if (!peer_ram_available(s->peer_backend, &peer, "peer-backend", errp)) {
        return;
    }

    if (local.offset != 0 ||
        (ap ? local.size <= AP_DDR_FILE_OFFSET : local.size != CP_LOCAL_SIZE)) {
        error_setg(errp, "local-backend requires offset=0 and %s",
                   ap ? "RAM extending beyond the 15GiB AP DDR file offset"
                      : "exactly 128MiB CP RAM at CPU base 0");
        return;
    }
    if (peer.offset != (ap ? 0 : AP_DDR_FILE_OFFSET) ||
        peer.size > (ap ? CP_PEER_MAX_SIZE : AP_PEER_MAX_SIZE)) {
        error_setg(errp, "peer-backend requires %s",
                   ap ? "CP RAM offset=0,size<=256MiB"
                      : "AP DDR file view offset=15GiB,size<=8GiB");
        return;
    }

    windows[0] = (PeerRAMWindow) {
        .source = peer.mr,
        .base = ap ? 0 : AP_DDR_BASE,
        .size = peer.size,
        .name = "native-peer-body",
    };
    windows[1] = (PeerRAMWindow) {
        .source = peer.mr,
        .base = ap ? AP_DDR_BASE : CP_RING_PCI_BASE,
        .size = peer.size,
        .name = "native-peer-ring",
    };
    if (s->peer_oom_backend) {
        if (!peer_ram_backend_view(s->peer_oom_backend, "peer-oom-backend",
                                   &oom, errp) ||
            !peer_ram_distinct(&local, &oom,
                               "local-backend and peer-oom-backend", errp) ||
            !peer_ram_distinct(&peer, &oom,
                               "peer-backend and peer-oom-backend", errp) ||
            !peer_ram_available(s->peer_oom_backend, &oom,
                                "peer-oom-backend", errp)) {
            return;
        }
        if (oom.offset != 0 || oom.size != CP_OOM_SIZE) {
            error_setg(errp, "peer-oom-backend requires offset=0,size=0x101000");
            return;
        }
        windows[2] = (PeerRAMWindow) {
            .source = oom.mr,
            .base = CP_OOM_BASE,
            .size = oom.size,
            .name = "native-peer-oom-body",
        };
        windows[3] = (PeerRAMWindow) {
            .source = oom.mr,
            .base = AP_DDR_BASE + CP_OOM_BASE,
            .size = oom.size,
            .name = "native-peer-oom-ring",
        };
        count = 4;
    }
    if (!peer_ram_check_windows(windows, count, errp)) {
        return;
    }

    /* All rejection paths precede ownership and topology changes (under BQL). */
    g_assert(s->alias_count == 0 && !s->peer_claimed && !s->oom_claimed);
    host_memory_backend_set_mapped(s->peer_backend, true);
    s->peer_claimed = true;
    if (s->peer_oom_backend) {
        host_memory_backend_set_mapped(s->peer_oom_backend, true);
        s->oom_claimed = true;
    }
    memory_region_transaction_begin();
    memory_region_set_size(&s->pci_memory, UINT64_MAX);
    for (unsigned i = 0; i < count; i++) {
        memory_region_init_alias(&s->aliases[i], OBJECT(s), windows[i].name,
                                 windows[i].source, 0, windows[i].size);
        memory_region_add_subregion(&s->pci_memory, windows[i].base,
                                    &s->aliases[i]);
        s->alias_count++;
    }
    memory_region_set_enabled(&s->pci_memory, true);
    memory_region_transaction_commit();
    g_assert(s->alias_count == (ap && s->peer_oom_backend ? 4 : 2));
}

static void native_peer_ram_unrealize(DeviceState *dev)
{
    NativePeerRAM *s = NATIVE_PEER_RAM(dev);
    unsigned count = s->alias_count;

    memory_region_transaction_begin();
    memory_region_set_enabled(&s->pci_memory, false);
    for (unsigned i = 0; i < count; i++) {
        memory_region_del_subregion(&s->pci_memory, &s->aliases[i]);
    }
    memory_region_set_size(&s->pci_memory, 0);
    memory_region_transaction_commit();
    for (unsigned i = 0; i < count; i++) {
        object_unparent(OBJECT(&s->aliases[i]));
    }
    s->alias_count = 0;
    if (s->oom_claimed) {
        host_memory_backend_set_mapped(s->peer_oom_backend, false);
        s->oom_claimed = false;
    }
    if (s->peer_claimed) {
        host_memory_backend_set_mapped(s->peer_backend, false);
        s->peer_claimed = false;
    }
    /* The empty SysBus region-0 shell remains QOM-owned until finalization. */
    g_assert(QTAILQ_EMPTY(&s->pci_memory.subregions));
}

static void native_peer_ram_init(Object *obj)
{
    NativePeerRAM *s = NATIVE_PEER_RAM(obj);

    memory_region_init(&s->pci_memory, obj, "native-peer-pci-memory", 0);
    memory_region_set_enabled(&s->pci_memory, false);
    sysbus_init_mmio(SYS_BUS_DEVICE(obj), &s->pci_memory);
}

static bool native_peer_ram_physical(Object *obj, Error **errp)
{
    return false;
}

static const Property native_peer_ram_properties[] = {
    DEFINE_PROP_STRING("side", NativePeerRAM, side),
    DEFINE_PROP_LINK("local-backend", NativePeerRAM, local_backend,
                     TYPE_MEMORY_BACKEND, HostMemoryBackend *),
    DEFINE_PROP_LINK("peer-backend", NativePeerRAM, peer_backend,
                     TYPE_MEMORY_BACKEND, HostMemoryBackend *),
    DEFINE_PROP_LINK("peer-oom-backend", NativePeerRAM, peer_oom_backend,
                     TYPE_MEMORY_BACKEND, HostMemoryBackend *),
};

/* shortcut: migration stays blocked until a paired RAM/transport contract exists. */
static const VMStateDescription native_peer_ram_vmstate = {
    .name = TYPE_NATIVE_PEER_RAM,
    .unmigratable = true,
};

static void native_peer_ram_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);

    dc->realize = native_peer_ram_realize;
    dc->unrealize = native_peer_ram_unrealize;
    dc->vmsd = &native_peer_ram_vmstate;
    dc->hotpluggable = false;
    dc->desc = "Functional AP/CP PCI RAM aliases (physical=false; no IRQ or ACK)";
    device_class_set_props(dc, native_peer_ram_properties);
    object_class_property_add_bool(klass, "physical", native_peer_ram_physical,
                                   NULL);
}

static const TypeInfo native_peer_ram_type = {
    .name = TYPE_NATIVE_PEER_RAM,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(NativePeerRAM),
    .instance_init = native_peer_ram_init,
    .class_init = native_peer_ram_class_init,
};

static void native_peer_ram_register_types(void)
{
    type_register_static(&native_peer_ram_type);
}

type_init(native_peer_ram_register_types)
