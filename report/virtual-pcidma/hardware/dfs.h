/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef SONY_VIRTUAL_DFS_SELECTOR_H
#define SONY_VIRTUAL_DFS_SELECTOR_H
#include <stdint.h>

enum sony_dfs_phase {
    SONY_DFS_UNINITIALIZED, SONY_DFS_IDLE, SONY_DFS_PREPARED,
    SONY_DFS_LATCHED, SONY_DFS_BUSY, SONY_DFS_COMPLETE, SONY_DFS_FAULT
};
struct sony_dfs_selector {
    uint32_t phase, initialized, request, init_write, trigger, target, status, current_mode;
    uint32_t faults, requests, completions;
    uint64_t generation, completed_generation;
};
/* Explicit virtual current_mode=0; not a silicon reset or frequency claim. */
void sony_dfs_reset(struct sony_dfs_selector *);
/* Offsets relative to f1388f50, aligned little-endian u32 only. */
int sony_dfs_read(struct sony_dfs_selector *, unsigned int, unsigned int, uint64_t *);
int sony_dfs_write(struct sony_dfs_selector *, unsigned int, unsigned int, uint64_t);
/* Consume one immutable triggered target; no IRQ, original software observes status. */
int sony_dfs_complete(struct sony_dfs_selector *);
#endif
