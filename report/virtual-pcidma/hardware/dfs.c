/* SPDX-License-Identifier: GPL-2.0-or-later
 * Public UPM normal subset: init101, request101, target100|mode0..6, trigger1.
 * This consumes virtual selector requests, without AVB/CPU frequency changes. */
#include "dfs.h"
#include <string.h>

static int reject(struct sony_dfs_selector *s)
{
    s->faults++;
    s->phase=SONY_DFS_FAULT;
    return -1;
}
void sony_dfs_reset(struct sony_dfs_selector *s)
{
    memset(s,0,sizeof(*s));
    s->phase=SONY_DFS_UNINITIALIZED;
}
int sony_dfs_read(struct sony_dfs_selector *s,unsigned int offset,unsigned int size,uint64_t *value)
{
    if (!value || size!=4 || (offset&3)) return reject(s);
    switch(offset) {
    case 0:*value=s->request;break;
    case 4:*value=s->init_write;break; /* virtual latch; native read semantics unknown */
    case 8:*value=s->trigger;break;   /* virtual latch; no self-clear claim */
    case 12:*value=s->target;break;
    case 16:*value=s->status;break;
    default:return reject(s);
    }
    return 0;
}
int sony_dfs_write(struct sony_dfs_selector *s,unsigned int offset,unsigned int size,uint64_t value)
{
    if (size!=4 || (offset&3) || value>UINT32_MAX || s->phase==SONY_DFS_FAULT)
        return reject(s);
    if (offset==4) {
        if (value!=0x101 || (s->phase!=SONY_DFS_UNINITIALIZED &&
                s->phase!=SONY_DFS_IDLE && s->phase!=SONY_DFS_COMPLETE)) return reject(s);
        s->initialized=1;s->init_write=(uint32_t)value;
        if (s->phase==SONY_DFS_UNINITIALIZED) s->phase=SONY_DFS_IDLE;
        return 0;
    }
    if (!s->initialized) return reject(s);
    switch(offset) {
    case 0:
        if (value!=0x101 || (s->phase!=SONY_DFS_IDLE && s->phase!=SONY_DFS_COMPLETE)) return reject(s);
        s->request=(uint32_t)value;s->phase=SONY_DFS_PREPARED;
        /* UPM waits for the old busy bit before writing the new target. */
        return 0;
    case 12:
        if (s->phase!=SONY_DFS_PREPARED || value<0x100 || value>0x106) return reject(s);
        s->target=(uint32_t)value;s->phase=SONY_DFS_LATCHED;
        return 0;
    case 8:
        if (value!=1 || s->phase!=SONY_DFS_LATCHED) return reject(s);
        s->trigger=1;s->status=s->current_mode|0x100;
        s->generation++;s->requests++;s->phase=SONY_DFS_BUSY;
        return 0;
    default:return reject(s);
    }
}
int sony_dfs_complete(struct sony_dfs_selector *s)
{
    if (s->phase!=SONY_DFS_BUSY || s->faults) return 0;
    s->current_mode=s->target&0xff;
    s->status=s->current_mode;
    s->request=1;
    s->completed_generation=s->generation;
    s->completions++;s->phase=SONY_DFS_COMPLETE;
    return 1;
}
