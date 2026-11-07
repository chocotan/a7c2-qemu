/* Full-system display transport only. Compile with -I<verified pinned analysis>.
 * Reuse its entire HOSDAP02 validation, retained-source checks and fw_cfg DMA;
 * do not run alongside the old viewer (the same guest flock enforces this).
 */
#define RAMFB_TEST
#include "ramfb-viewer.c"
#include <time.h>
#include <stddef.h>

#define LCD_RECEIPT_OFFSET (RAMFB_DMA + 0x100U)
#define LCD_PERIOD_NS UINT64_C(20000000)
#define LCD_PERFORMANCE_OFFSET (RAMFB_DMA + 0x200U)
#define LCD_PERFORMANCE_SLOTS 16U

/* Initialized before the startup identity, never in the click/frame path. */
static uint32_t lcd_rgba4444[65536];
static void lcd_init_conversion(void) {
    static int initialized;
    if (initialized) return;
    for (unsigned v = 0; v < 65536; ++v) {
        unsigned a = v & 15;
        lcd_rgba4444[v] = ((((v >> 4) & 15) * 17 * a + 7) / 15) |
            (((((v >> 8) & 15) * 17 * a + 7) / 15) << 8) |
            ((((v >> 12) * 17 * a + 7) / 15) << 16);
    }
    initialized = 1;
}
static void lcd_fast_convert(const unsigned char *p, unsigned char *out) {
    for (unsigned i = 0; i < HOSD_PIXELS / 2; ++i) {
        uint16_t v;
        memcpy(&v, p + 2 * i, sizeof v);
        memcpy(out + 4 * i, &lcd_rgba4444[v], sizeof(uint32_t));
    }
}
struct lcd_receipt {
    unsigned char magic[8];
    uint32_t schema, bytes;
    uint64_t revision;
    unsigned char nonce[16];
    uint64_t pid, sequence, source_epoch, source_phys, scanout_phys;
    uint64_t committed_ns, pixel_fnv, container_fnv, submissions, rejections, reserved;
};
_Static_assert(sizeof(struct lcd_receipt) == 128 && offsetof(struct lcd_receipt, revision) == 16,
               "host source receipt ABI");
_Static_assert(LCD_RECEIPT_OFFSET + sizeof(struct lcd_receipt) <= RAMFB_SIZE,
               "receipt must stay inside the reserved scanout pool, outside DMA/config");

/* 16 independent little-endian 128B slots at physical 0x41e5ff200.
 * Both generations must be equal/even; FNV covers bytes [0,104), including
 * nonce/pid/sample/source identity and all four CLOCK_MONOTONIC timestamps.
 * snapshot_ns includes the new-pixel FNV before receipt odd; convert/DMA
 * measures conversion/submission, commit_ns only consumer metadata updates.
 * Durations are timestamp differences, not host input/window latency.
 */
struct lcd_performance {
    unsigned char magic[8];
    uint32_t schema, bytes;
    uint64_t generation;
    unsigned char nonce[16];
    uint64_t pid, sequence, source_sequence, source_epoch;
    uint64_t snapshot_start_ns, after_snapshot_ns, after_convert_dma_ns, after_commit_ns;
    uint64_t record_fnv, generation_end, reserved;
};
_Static_assert(sizeof lcd_rgba4444 == 262144, "conversion lookup size");
_Static_assert(sizeof(struct lcd_performance) == 128 &&
               offsetof(struct lcd_performance, record_fnv) == 104 &&
               offsetof(struct lcd_performance, generation_end) == 112,
               "performance receipt ABI");
_Static_assert(RAMFB_BASE + LCD_PERFORMANCE_OFFSET == UINT64_C(0x41e5ff200) &&
               LCD_RECEIPT_OFFSET + sizeof(struct lcd_receipt) <= LCD_PERFORMANCE_OFFSET &&
               LCD_PERFORMANCE_OFFSET + LCD_PERFORMANCE_SLOTS * sizeof(struct lcd_performance) <= RAMFB_SIZE,
               "performance ring must not overlap source receipt/DMA/scanouts");

static void lcd_record_performance(volatile struct lcd_performance *ring,
        const struct lcd_receipt *source, uint64_t start, uint64_t snapshot_done,
        uint64_t convert_done, uint64_t commit_done) {
    struct lcd_performance record = {.magic={'L','C','D','P','E','R','0','1'},
        .schema=1, .bytes=128, .generation=source->submissions * 2,
        .pid=source->pid, .sequence=source->submissions,
        .source_sequence=source->sequence, .source_epoch=source->source_epoch,
        .snapshot_start_ns=start, .after_snapshot_ns=snapshot_done,
        .after_convert_dma_ns=convert_done, .after_commit_ns=commit_done,
        .generation_end=source->submissions * 2};
    memcpy(record.nonce, source->nonce, sizeof record.nonce);
    record.record_fnv = fnv((const unsigned char *)&record,
                           offsetof(struct lcd_performance, record_fnv), 0);
    volatile struct lcd_performance *target = ring + (record.sequence - 1) % LCD_PERFORMANCE_SLOTS;
    target->generation = record.generation | 1;
    barrier();
    target->generation_end = record.generation | 1;
    barrier();
    memcpy((void *)target, &record, offsetof(struct lcd_performance, generation));
    memcpy((unsigned char *)target + 24, (const unsigned char *)&record + 24,
           offsetof(struct lcd_performance, generation_end) - 24);
    target->reserved = 0;
    barrier();
    target->generation_end = record.generation;
    barrier();
    target->generation = record.generation;
    barrier();
}

static uint64_t lcd_now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return 0;
    return (uint64_t)t.tv_sec * UINT64_C(1000000000) + t.tv_nsec;
}
/* Retained snapshots already proved this pixel hash; new pixels hash once. */
static void lcd_commit_verified(struct consumer *s, int fd, struct stat *st,
        const unsigned char *raw, uint64_t pixel_hash) {
    if (s->fd >= 0) close(s->fd);
    s->fd = fd; s->st = *st; memcpy(s->header, raw, HOSD_HEADER);
    s->pixel_hash = pixel_hash;
}
/* Keep DMA failure before ownership transfer; exercised through the same bus seam. */
static int lcd_submit_commit_verified(struct bus *b, unsigned char *pool,
        unsigned slot, unsigned selector, struct consumer *s, int fd,
        struct stat *st, const unsigned char *raw, uint64_t pixel_hash, uint64_t *submitted_ns) {
    int result = submit(b, pool, slot, selector);
    if (result) return result;
    *submitted_ns = lcd_now();
    if (!*submitted_ns) return -3;
    lcd_commit_verified(s, fd, st, raw, pixel_hash);
    return 0;
}
static uint64_t lcd_next_deadline(uint64_t deadline, uint64_t now) {
    deadline += LCD_PERIOD_NS;
    if (deadline <= now) deadline += ((now - deadline) / LCD_PERIOD_NS + 1) * LCD_PERIOD_NS;
    return deadline;
}
static void lcd_busy(volatile struct lcd_receipt *target, uint64_t revision) {
    target->revision = revision | 1;
    barrier();
}
static void lcd_publish(volatile struct lcd_receipt *target, const struct lcd_receipt *receipt) {
    /* Keep the seqlock odd across the whole copy and publish the even word last. */
    memcpy((void *)target, receipt, offsetof(struct lcd_receipt, revision));
    memcpy((unsigned char *)target + 24, (const unsigned char *)receipt + 24,
           sizeof *receipt - 24);
    barrier();
    target->revision = receipt->revision;
    barrier();
}

#ifndef LCD_STREAM_TEST
static void lcd_select(void *ctx, uint16_t key) {
    *(volatile uint16_t *)((unsigned char *)ctx + 8) = __builtin_bswap16(key); barrier();
}
static unsigned char lcd_data(void *ctx) { return *(volatile unsigned char *)ctx; }
static uint64_t lcd_signature(void *ctx) {
    return __builtin_bswap64(*(volatile uint64_t *)((unsigned char *)ctx + 16));
}
static void lcd_kick(void *ctx, uint64_t address) {
    *(volatile uint64_t *)((unsigned char *)ctx + 16) = __builtin_bswap64(address); barrier();
}
static void lcd_pause(void *ctx) { (void)ctx; usleep(1000); }
static int lcd_error(const char *reason) {
    dprintf(2, "LCD_STREAM_FAIL reason=%s errno=%d; no new display proof\n", reason, errno);
    return 1;
}
static int lcd_run(void) {
    static unsigned char raw[HOSD_BYTES];
    struct consumer s = {.fd = -1};
    struct lcd_receipt receipt = {.magic={'L','C','D','R','A','M','0','1'}, .schema=1, .bytes=128};
    int lock = open("/tmp/ramfb-viewer.lock", O_CREAT | O_RDWR | O_NOFOLLOW, 0600);
    if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) return lcd_error("already running/lock");
    char cmdline[8192];
    int fd = open("/proc/cmdline", O_RDONLY);
    ssize_t length = fd >= 0 ? read(fd, cmdline, sizeof cmdline - 1) : -1;
    if (fd >= 0) close(fd);
    if (length <= 0 || length == sizeof cmdline - 1) return lcd_error("cmdline read");
    cmdline[length] = 0;
    if (!reserved(cmdline)) return lcd_error("scanout reservation missing");
    fd = open("/dev/urandom", O_RDONLY | O_NOFOLLOW);
    if (fd < 0 || read_all(fd, receipt.nonce, sizeof receipt.nonce)) return lcd_error("source nonce");
    close(fd);
    receipt.pid = getpid();
    fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) return lcd_error("open /dev/mem");
    void *mmio = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, FW_BASE);
    if (mmio == MAP_FAILED) return lcd_error("mmap fw_cfg");
    struct bus b = {mmio, lcd_select, lcd_data, lcd_signature, lcd_kick, lcd_pause};
    int selector = discover(&b);
    if (selector < 0) return lcd_error("fw_cfg signature/DMA/etc/ramfb");
    unsigned char *pool = mmap(NULL, RAMFB_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, RAMFB_BASE);
    close(fd);
    if (pool == MAP_FAILED) return lcd_error("mmap reserved scanout");
    volatile struct lcd_receipt *target = (void *)(pool + LCD_RECEIPT_OFFSET);
    lcd_busy(target, 1); /* Old metadata from a previous viewer never passes as this session. */
    volatile struct lcd_performance *performance = (void *)(pool + LCD_PERFORMANCE_OFFSET);
    memset((void *)performance, 0, LCD_PERFORMANCE_SLOTS * sizeof *performance);
    barrier();
    lcd_init_conversion();
    char nonce_hex[33];
    for (unsigned i = 0; i < 16; ++i) snprintf(nonce_hex + i * 2, 3, "%02x", receipt.nonce[i]);
    const char *identity = "\nLCD_STREAM_SOURCE nonce=%s pid=%llu receipt_phys=0x%llx period_ns=%llu\n";
    dprintf(2, identity, nonce_hex, (unsigned long long)receipt.pid,
            (unsigned long long)(RAMFB_BASE + LCD_RECEIPT_OFFSET), (unsigned long long)LCD_PERIOD_NS);
    int console = open("/dev/console", O_WRONLY | O_NOCTTY | O_NOFOLLOW);
    if (console < 0) return lcd_error("open startup identity console");
    int printed = dprintf(console, identity, nonce_hex, (unsigned long long)receipt.pid,
            (unsigned long long)(RAMFB_BASE + LCD_RECEIPT_OFFSET), (unsigned long long)LCD_PERIOD_NS);
    close(console);
    if (printed <= 0) return lcd_error("publish startup identity console");
    unsigned slot = 1;
    uint64_t deadline = lcd_now();
    if (!deadline) return lcd_error("monotonic clock");
    for (;;) {
        struct timespec due = {.tv_sec=deadline / UINT64_C(1000000000),
                               .tv_nsec=deadline % UINT64_C(1000000000)};
        int sleeping;
        do { sleeping = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &due, NULL); }
        while (sleeping == EINTR);
        if (sleeping) { errno=sleeping; return lcd_error("deadline wait"); }
        int next = open(HOSD_PATH, O_RDONLY | O_NONBLOCK | O_NOFOLLOW);
        if (next >= 0) {
            struct stat st;
            const char *error = NULL;
            uint64_t snapshot_start = lcd_now();
            if (!snapshot_start) { close(next); return lcd_error("snapshot clock"); }
            int action = snapshot(&s, next, raw, &st, &error);
            if (action <= 0) {
                close(next);
                if (action < 0) {
                    ++receipt.rejections;
                    if (receipt.rejections == 1 || receipt.rejections % 100 == 0)
                        dprintf(2, "LCD_STREAM_REJECT reason=%s count=%llu\n", error,
                                (unsigned long long)receipt.rejections);
                }
            } else {
                uint64_t pixel_hash = action == 2 ?
                    fnv(raw + HOSD_HEADER + sizeof(struct hosd_metadata), HOSD_PIXELS, 0) : s.pixel_hash;
                uint64_t snapshot_done = action == 2 ? lcd_now() : 0;
                if (action == 2 && !snapshot_done) { close(next); return lcd_error("snapshot completion clock"); }
                lcd_busy(target, receipt.revision + 1);
                if (action == 2) {
                    unsigned active = slot ^ 1;
                    lcd_fast_convert(raw + HOSD_HEADER + sizeof(struct hosd_metadata), pool + active * RAMFB_SLOT);
                    int result = lcd_submit_commit_verified(&b, pool, active, selector, &s,
                        next, &st, raw, pixel_hash, &receipt.committed_ns);
                    if (result) {
                        close(next);
                        return lcd_error(result == -2 ? "DMA timeout" : result == -3 ? "commit clock" : "DMA failure");
                    }
                    slot = active;
                    ++receipt.submissions;
                } else {
                    lcd_commit_verified(&s, next, &st, raw, pixel_hash);
                }
                uint64_t commit_done = action == 2 ? lcd_now() : 0;
                if (action == 2 && !commit_done) return lcd_error("commit completion clock");
                receipt.sequence = le(s.header + 8, 8);
                receipt.source_epoch = le(s.header + 120, 8);
                receipt.source_phys = le(s.header + 32, 8);
                receipt.scanout_phys = RAMFB_BASE + slot * RAMFB_SLOT;
                receipt.pixel_fnv = s.pixel_hash;
                receipt.container_fnv = le(s.header + 40, 8);
                receipt.revision += 2;
                lcd_publish(target, &receipt);
                if (action == 2)
                    lcd_record_performance(performance, &receipt, snapshot_start, snapshot_done,
                                           receipt.committed_ns, commit_done);
            }
        } else if (errno != ENOENT) {
            return lcd_error("open original snapshot");
        }
        uint64_t now = lcd_now();
        if (!now) return lcd_error("deadline clock");
        deadline = lcd_next_deadline(deadline, now);
    }
}
void _start(void) { _exit(lcd_run()); }
#endif
