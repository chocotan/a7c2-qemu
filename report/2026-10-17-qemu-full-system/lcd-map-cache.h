#ifndef LCD_MAP_CACHE_H
#define LCD_MAP_CACHE_H
/* latency-v3 functional /dev/mem VMA reuse, not a bitmap reference or GPU format.
 * All acquire/release/flush/seal calls require the original raster mutex.
 * Only snapshot is lock-free: its fields are individually atomic, not one epoch.
 * Never close/reuse a cached fd. Flush succeeds only after every owned VMA is
 * unmapped. A real unmap failure is sticky for this process, even after retry.
 * Fin must seal an already empty cache; it never unmaps unproven live workers.
 */
#define LCD_MAP_SLOTS 8U
#define LCD_MAP_GRANULE 0x100000UL
#define LCD_MAP_MAX_BYTES 0x8000000UL
#define LCD_MAP_PHYS_LOW 0x410000000UL
#define LCD_MAP_PHYS_HIGH 0x500000000UL
struct lcd_map_stats {
    unsigned long hits, misses, maps, unmaps, errors, active, bytes, entries, flushes, failed, sealed;
};
struct lcd_map_entry {
    void *mapping;
    unsigned long physical, length, generation, borrows;
    int fd, prot;
    unsigned int used;
};
struct lcd_map_cache {
    struct lcd_map_entry entries[LCD_MAP_SLOTS];
    struct lcd_map_stats stats;
    unsigned long generation;
    unsigned int next;
    int fault_errno;
};
struct lcd_map_borrow {
    void *address;
    unsigned long length, generation;
    unsigned int slot, active;
};
/* Zero-initialize cache and each borrow exactly once; do not copy live tokens.
 * fd is the existing raster_fd (/dev/mem), prot is exactly READ or READ|WRITE.
 * The returned address denotes the exact requested physical start. No pixel
 * byte outside the original request may be accessed, despite padded VMAs.
 */
int lcd_map_acquire(struct lcd_map_cache *, int fd, unsigned long physical,
                    unsigned long length, int prot, struct lcd_map_borrow *);
int lcd_map_release(struct lcd_map_cache *, struct lcd_map_borrow *);
int lcd_map_flush(struct lcd_map_cache *);
int lcd_map_seal_clean(struct lcd_map_cache *);
void lcd_map_snapshot(const struct lcd_map_cache *, struct lcd_map_stats *);
#endif
