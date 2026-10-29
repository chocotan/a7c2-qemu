/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef SONY_BACKUP_PEER_H
#define SONY_BACKUP_PEER_H
#include "qemu/typedefs.h"
struct sony_backup_dma_snapshot {
    uint64_t sequence, reset, source, destination, copied;
    uint32_t requested, result, mode;
    bool executing;
};
void sony_pcidma_backup_snapshot(DeviceState *, struct sony_backup_dma_snapshot *);
MemoryRegion *sony_test_peer_memory(PCIDevice *);
void sony_test_peer_attach_dma(PCIDevice *, DeviceState *);
#endif
