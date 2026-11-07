#include "lcd-map-cache.h"
extern int *__errno_location(void);
extern void *mmap(void *, unsigned long, int, int, int, unsigned long);
extern int munmap(void *, unsigned long);
#ifndef LCD_MAP_MMAP
#define LCD_MAP_MMAP mmap
#endif
#ifndef LCD_MAP_MUNMAP
#define LCD_MAP_MUNMAP munmap
#endif
#define LOAD(p) __atomic_load_n((p), __ATOMIC_RELAXED)
#define ADD(p,n) __atomic_fetch_add((p),(n),__ATOMIC_RELAXED)
#define SUB(p,n) __atomic_fetch_sub((p),(n),__ATOMIC_RELAXED)
#define STORE(p,n) __atomic_store_n((p),(n),__ATOMIC_RELAXED)
static int fail(struct lcd_map_cache *cache, int error, int sticky) {
    if (cache) {
        ADD(&cache->stats.errors,1UL);
        if (sticky && !LOAD(&cache->stats.failed)) {
            cache->fault_errno=error;
            STORE(&cache->stats.failed,1UL);
        }
    }
    *__errno_location()=error;
    return -1;
}
static int drop(struct lcd_map_cache *cache, unsigned int slot) {
    struct lcd_map_entry *entry=&cache->entries[slot];
    if (LCD_MAP_MUNMAP(entry->mapping,entry->length))
        return fail(cache,*__errno_location(),1); /* Still owned: never forget a failed unmap. */
    ADD(&cache->stats.unmaps,1UL);
    SUB(&cache->stats.bytes,entry->length);
    SUB(&cache->stats.entries,1UL);
    entry->used=0; entry->mapping=0; entry->length=0;
    return 0;
}
int lcd_map_acquire(struct lcd_map_cache *cache, int fd, unsigned long physical,
                    unsigned long length, int prot, struct lcd_map_borrow *borrow) {
    if (!cache || !borrow) return fail(cache,22,0); /* EINVAL */
    if (borrow->active) return fail(cache,16,0); /* EBUSY; preserve the existing borrow. */
    if (LOAD(&cache->stats.failed)) return fail(cache,cache->fault_errno,0);
    if (LOAD(&cache->stats.sealed)) return fail(cache,108,0); /* ESHUTDOWN */
    if (fd<0) return fail(cache,9,0);
    if ((prot!=1 && prot!=3) || !length || physical<LCD_MAP_PHYS_LOW ||
        physical>=LCD_MAP_PHYS_HIGH || length>LCD_MAP_PHYS_HIGH-physical)
        return fail(cache,22,0);
    for (unsigned int slot=0;slot<LCD_MAP_SLOTS;slot++) {
        struct lcd_map_entry *entry=&cache->entries[slot];
        if (entry->used && entry->fd==fd && (entry->prot & prot)==prot &&
            physical>=entry->physical && physical-entry->physical<=entry->length &&
            length<=entry->length-(physical-entry->physical)) {
            entry->borrows++;
            *borrow=(struct lcd_map_borrow){(unsigned char *)entry->mapping+(physical-entry->physical),
                length,entry->generation,slot,1};
            ADD(&cache->stats.hits,1UL); ADD(&cache->stats.active,1UL);
            return 0;
        }
    }
    ADD(&cache->stats.misses,1UL);
    unsigned long base=physical & ~(LCD_MAP_GRANULE-1UL);
    unsigned long end=(physical+length+LCD_MAP_GRANULE-1UL) & ~(LCD_MAP_GRANULE-1UL);
    unsigned long span=end-base;
    if (span>LCD_MAP_MAX_BYTES) return fail(cache,12,0); /* ENOMEM, bounded resource model. */
    unsigned int chosen=LCD_MAP_SLOTS;
    for (unsigned int slot=0;slot<LCD_MAP_SLOTS;slot++)
        if (!cache->entries[slot].used) { chosen=slot;break; }
    for (unsigned int attempt=0;attempt<LCD_MAP_SLOTS &&
         (chosen==LCD_MAP_SLOTS || span>LCD_MAP_MAX_BYTES-LOAD(&cache->stats.bytes));attempt++) {
        unsigned int victim=LCD_MAP_SLOTS;
        for (unsigned int n=0;n<LCD_MAP_SLOTS;n++) {
            unsigned int slot=(cache->next+n)%LCD_MAP_SLOTS;
            if (cache->entries[slot].used && !cache->entries[slot].borrows) { victim=slot;break; }
        }
        if (victim==LCD_MAP_SLOTS) return fail(cache,16,0);
        if (drop(cache,victim)) return -1;
        chosen=victim; cache->next=(victim+1)%LCD_MAP_SLOTS;
    }
    if (chosen==LCD_MAP_SLOTS || span>LCD_MAP_MAX_BYTES-LOAD(&cache->stats.bytes))
        return fail(cache,16,0);
    void *mapping=LCD_MAP_MMAP(0,span,prot,1,fd,base); /* Actual MAP_SHARED; never upgrade RO. */
    if (mapping==(void *)-1) return fail(cache,*__errno_location(),0);
    unsigned long generation=++cache->generation;
    if (!generation) generation=++cache->generation;
    cache->entries[chosen]=(struct lcd_map_entry){mapping,base,span,generation,1,fd,prot,1};
    *borrow=(struct lcd_map_borrow){(unsigned char *)mapping+(physical-base),length,generation,chosen,1};
    ADD(&cache->stats.maps,1UL); ADD(&cache->stats.active,1UL);
    ADD(&cache->stats.bytes,span); ADD(&cache->stats.entries,1UL);
    return 0;
}
int lcd_map_release(struct lcd_map_cache *cache, struct lcd_map_borrow *borrow) {
    if (!cache || !borrow || !borrow->active || borrow->slot>=LCD_MAP_SLOTS)
        return fail(cache,22,0);
    struct lcd_map_entry *entry=&cache->entries[borrow->slot];
    if (!entry->used || !entry->borrows || entry->generation!=borrow->generation)
        return fail(cache,22,0);
    entry->borrows--; SUB(&cache->stats.active,1UL);
    *borrow=(struct lcd_map_borrow){0};
    return 0;
}
int lcd_map_flush(struct lcd_map_cache *cache) {
    if (!cache) return fail(cache,22,0);
    ADD(&cache->stats.flushes,1UL);
    for (unsigned int slot=0;slot<LCD_MAP_SLOTS;slot++) {
        struct lcd_map_entry *entry=&cache->entries[slot];
        if (!entry->used) continue;
        if (entry->borrows) { fail(cache,16,1);continue; }
        /* Retry retained failed VMAs too, but the fault never becomes success. */
        drop(cache,slot);
    }
    if (LOAD(&cache->stats.failed)) { *__errno_location()=cache->fault_errno;return -1; }
    return 0;
}
int lcd_map_seal_clean(struct lcd_map_cache *cache) {
    if (!cache) return fail(cache,22,0);
    if (LOAD(&cache->stats.failed)) return fail(cache,cache->fault_errno,0);
    if (LOAD(&cache->stats.entries) || LOAD(&cache->stats.active) || LOAD(&cache->stats.bytes))
        return fail(cache,16,0);
    STORE(&cache->stats.sealed,1UL); /* Fin admission guard; no live VMA is unmapped here. */
    return 0;
}
void lcd_map_snapshot(const struct lcd_map_cache *cache, struct lcd_map_stats *out) {
    if (!cache || !out) return;
#define SNAP(field) out->field=LOAD(&cache->stats.field)
    SNAP(hits); SNAP(misses); SNAP(maps); SNAP(unmaps); SNAP(errors); SNAP(active);
    SNAP(bytes); SNAP(entries); SNAP(flushes); SNAP(failed); SNAP(sealed);
#undef SNAP
}
