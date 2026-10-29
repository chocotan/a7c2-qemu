/* SPDX-License-Identifier: GPL-2.0-or-later
 * Explicit QEMU PCIe TEST function with a real RAM BAR. Not Sony CP identity.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "qemu/units.h"
#include "hw/pci/pci_device.h"
#include "hw/pci/pci_ids.h"
#include "hw/pci/pcie.h"
#include "hw/core/qdev-properties.h"
#include "backup_peer.h"
#include "lli.h"

#define TYPE_TEST_PEER "a7c2-test-pcie-peer"
OBJECT_DECLARE_SIMPLE_TYPE(TestPeerState, TEST_PEER)
struct TestPeerState {
    PCIDevice parent_obj;
    MemoryRegion *memory;
    MemoryRegion backup_data, backup_control;
    DeviceState *dma;
    struct sony_backup_dma_snapshot at_freeze;
    bool backup, frozen;
    char *initial_image;
    uint64_t epoch;
    uint32_t rejected_writes;
};
#define BACKUP_BYTES 0x15a8f8u
#define BACKUP_MAGIC 0x42555031u
static bool fresh_transfer(TestPeerState *s)
{
    struct sony_backup_dma_snapshot now;
    if (!s->dma || !s->frozen) return false;
    sony_pcidma_backup_snapshot(s->dma, &now);
    return !now.executing && now.reset == s->at_freeze.reset &&
        now.sequence == s->at_freeze.sequence + 1 &&
        now.source == 0x404000000ULL && now.destination == 0x4040ed000ULL &&
        now.requested == BACKUP_BYTES && now.copied == BACKUP_BYTES && now.mode == 8 &&
        now.result == SONY_EDMA_PAUSED;
}
static MemTxResult backup_read(void *opaque, hwaddr offset, uint64_t *value,
                               unsigned size, MemTxAttrs attrs)
{
    TestPeerState *s = opaque;
    const uint8_t *p = memory_region_get_ram_ptr(&s->backup_data);
    if (offset > 16 * MiB - size) return MEMTX_ACCESS_ERROR;
    *value = 0;
    for (unsigned i = 0; i < size; ++i) *value |= (uint64_t)p[offset + i] << (8 * i);
    return MEMTX_OK;
}
static MemTxResult backup_write(void *opaque, hwaddr offset, uint64_t value,
                                unsigned size, MemTxAttrs attrs)
{
    TestPeerState *s = opaque;
    uint8_t *p = memory_region_get_ram_ptr(&s->backup_data);
    if (s->frozen || offset > 16 * MiB - size) {
        s->rejected_writes++;
        return MEMTX_ACCESS_ERROR;
    }
    for (unsigned i = 0; i < size; ++i) p[offset + i] = value >> (8 * i);
    memory_region_set_dirty(&s->backup_data, offset, size);
    return MEMTX_OK;
}
static const MemoryRegionOps backup_ops = {
    .read_with_attrs = backup_read, .write_with_attrs = backup_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {.min_access_size = 1, .max_access_size = 8, .unaligned = false},
    .impl = {.min_access_size = 1, .max_access_size = 8, .unaligned = false},
};
static MemTxResult control_read(void *opaque, hwaddr offset, uint64_t *value,
                                unsigned size, MemTxAttrs attrs)
{
    TestPeerState *s = opaque;
    if (size != 4 || offset & 3) return MEMTX_ACCESS_ERROR;
    switch (offset) {
    case 0: *value = BACKUP_MAGIC; break;
    case 4: *value = 1; break;
    case 8: *value = BACKUP_BYTES; break;
    case 12: *value = s->frozen; break;
    case 16: *value = (uint32_t)s->epoch; break;
    case 20: *value = s->epoch >> 32; break;
    case 28: *value = s->rejected_writes; break;
    case 32: *value = fresh_transfer(s); break;
    default: return MEMTX_ACCESS_ERROR;
    }
    return MEMTX_OK;
}
static MemTxResult control_write(void *opaque, hwaddr offset, uint64_t value,
                                 unsigned size, MemTxAttrs attrs)
{
    TestPeerState *s = opaque;
    struct sony_backup_dma_snapshot now;
    if (size != 4 || offset != 24 || !s->dma) return MEMTX_ACCESS_ERROR;
    sony_pcidma_backup_snapshot(s->dma, &now);
    if (now.executing) return MEMTX_ACCESS_ERROR;
    if (value == 1 && !s->frozen) {
        uint8_t *p = memory_region_get_ram_ptr(&s->backup_data);
        s->at_freeze = now;
        p[9] = 1;
        s->frozen = true;
        s->epoch++;
        memory_region_set_dirty(&s->backup_data, 9, 1);
        return MEMTX_OK;
    }
    if (value == 2 && fresh_transfer(s)) {
        s->frozen = false;
        return MEMTX_OK;
    }
    return MEMTX_ACCESS_ERROR;
}
static const MemoryRegionOps control_ops = {
    .read_with_attrs = control_read, .write_with_attrs = control_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {.min_access_size = 4, .max_access_size = 4},
    .impl = {.min_access_size = 4, .max_access_size = 4},
};
MemoryRegion *sony_test_peer_memory(PCIDevice *device)
{
    return TEST_PEER(device)->memory;
}
void sony_test_peer_attach_dma(PCIDevice *device, DeviceState *dma)
{
    TestPeerState *s = TEST_PEER(device);
    assert(s->backup && !s->dma && !s->frozen);
    s->dma = dma;
    object_ref(OBJECT(dma));
}
static void reset_peer(DeviceState *device)
{
    TestPeerState *s = TEST_PEER(device);
    s->epoch++;
    s->frozen = false;
    memset(&s->at_freeze, 0, sizeof(s->at_freeze));
}

static void realize_peer(PCIDevice *device, Error **errp)
{
    TestPeerState *s=TEST_PEER(device);
    if (s->backup) {
        if (s->memory) {
            error_setg(errp,"Backup peer owns its guarded backing; external RAM is rejected");
            return;
        }
        if (!memory_region_init_rom_device(&s->backup_data, OBJECT(device), &backup_ops,
                                          s, "sony-backup-data", 16 * MiB, errp)) return;
        /* Direct ROMD reads are not clamped to a shorter alias by this QEMU;
         * callbacks keep the high primary window's last transaction bounded. */
        memory_region_rom_device_set_romd(&s->backup_data, false);
        s->memory = &s->backup_data;
        if (s->initial_image) {
            FILE *file = fopen(s->initial_image, "rb");
            uint8_t *bytes = memory_region_get_ram_ptr(&s->backup_data);
            if (!file) {
                error_setg_errno(errp, errno, "Cannot open virtual Backup initial record");
                return;
            }
            size_t count = fread(bytes, 1, BACKUP_BYTES + 1, file);
            bool failed = ferror(file);
            int closed = fclose(file);
            if (failed || closed || count != BACKUP_BYTES) {
                error_setg(errp, "Virtual Backup initial record has wrong length or read failure");
                return;
            }
            g_autofree char *digest = g_compute_checksum_for_data(G_CHECKSUM_SHA256, bytes, count);
            if (strcmp(digest, "a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977")) {
                error_setg(errp, "Virtual Backup initial record is not the pinned public fixture");
                return;
            }
            memory_region_set_dirty(&s->backup_data, 0, count);
        }
        memory_region_init_io(&s->backup_control, OBJECT(device), &control_ops,
                              s, "sony-backup-control", 4096);
        pci_register_bar(device, 1, PCI_BASE_ADDRESS_SPACE_MEMORY, &s->backup_control);
    } else if (!s->memory || !memory_region_is_ram(s->memory) ||
        memory_region_size(s->memory)!=16*MiB) {
        error_setg(errp,"a7c2-test-pcie-peer requires its explicit 16MiB owned RAM link (set=%d ram=%d size=%" PRIu64 ")",
                   s->memory!=NULL,s->memory?memory_region_is_ram(s->memory):0,
                   s->memory?memory_region_size(s->memory):0);
        return;
    }
    /* A test identity, using QEMU's existing test-device vendor/device pair.
     * BAR enable and bridge windows are controlled by actual PCI config writes.
     */
    pci_register_bar(device,0,PCI_BASE_ADDRESS_SPACE_MEMORY,s->memory);
    if (pcie_endpoint_cap_init(device,0x70)<0) {
        error_setg(errp,"PCIe test capability could not be created");
    }
}
static void exit_peer(PCIDevice *device)
{
    TestPeerState *s = TEST_PEER(device);
    if (s->dma) object_unref(OBJECT(s->dma));
    pcie_cap_exit(device);
}
static const Property properties[]={
    DEFINE_PROP_BOOL("backup-control",TestPeerState,backup,false),
    DEFINE_PROP_STRING("initial-image",TestPeerState,initial_image),
    DEFINE_PROP_LINK("memory",TestPeerState,memory,TYPE_MEMORY_REGION,MemoryRegion *),
};
static void class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(klass); PCIDeviceClass *pc=PCI_DEVICE_CLASS(klass);
    pc->realize=realize_peer; pc->exit=exit_peer;
    pc->vendor_id=PCI_VENDOR_ID_REDHAT; pc->device_id=PCI_DEVICE_ID_REDHAT_TEST;
    pc->class_id=PCI_CLASS_OTHERS; pc->revision=1;
    dc->desc="Explicit PCIe RAM test peer; no CP identity or sensor";
    dc->user_creatable=false;
    device_class_set_legacy_reset(dc,reset_peer);
    device_class_set_props(dc,properties);
}
static const TypeInfo type_info={
    .name=TYPE_TEST_PEER,.parent=TYPE_PCI_DEVICE,.instance_size=sizeof(TestPeerState),
    .class_init=class_init,.interfaces=(const InterfaceInfo[]){{INTERFACE_PCIE_DEVICE},{}}
};
static void register_types(void) { type_register_static(&type_info); }
type_init(register_types)
