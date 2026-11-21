/* Independent HOSDAP02 consumer. No producer ACKs, locks or camera MMIO. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <signal.h>
#include "headless-osd.h"
#include "../../report/virtual-sensor/sensor-core.h"
#include <stdlib.h>

#define PREVIEW_PROFILE "/tmp/virtual-preview.profile"
#define PREVIEW_NAME "functional-cmos-chart-v1\n"
#define PREVIEW_CUSTOM_RGB "/tmp/virtual-cmos-custom.rgb"
#define PREVIEW_PLAYBACK_FRAME "/tmp/virtual-playback-frame.bin"
#define PREVIEW_SHUTTER_BLINK "/tmp/virtual-shutter-blink"
#define PREVIEW_RGB_BYTES (640U * 480U * 3U)
#define PREVIEW_PLAYBACK_HDR 16U
#define PREVIEW_PLAYBACK_BYTES (PREVIEW_PLAYBACK_HDR + PREVIEW_RGB_BYTES)
static unsigned char *preview_rgb;
static unsigned char *custom_preview_rgb;
static int custom_preview_active;
static struct stat custom_preview_st;
static int preview_enabled;
static int preview_active;

#define RAMFB_BASE UINT64_C(0x41e100000)
#define RAMFB_SIZE 0x500000U
#define RAMFB_SLOT 0x200000U
#define RAMFB_DMA (RAMFB_SIZE - 0x1000U)
#define RAMFB_CFG (RAMFB_DMA + 64U)
#define FW_BASE UINT64_C(0x09020000)
#define XRGB_BYTES (640U * 480U * 4U)
_Static_assert(HOSD_BYTES == 639458 && XRGB_BYTES <= RAMFB_SLOT, "layout");
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "ramfb viewer requires a little-endian guest"
#endif

static int reserved(const char *cmdline) {
    static const char *tokens[]={"memrsv=0x00500000@0x41e100000:uc","memrsv=0x00900000@0x41e100000:uc"};
    unsigned int count=0;
    for(unsigned int i=0;i<2;i++) {
        size_t length=strlen(tokens[i]);const char *p=cmdline;
        while((p=strstr(p,tokens[i]))) {
            if((p==cmdline || p[-1]==' ') && (!p[length] || p[length]==' ' || p[length]=='\n'))count++;
            p+=length;
        }
    }
    return count==1;
}

static uint64_t le(const unsigned char *p, unsigned n) {
    uint64_t v = 0;
    for (unsigned i = 0; i < n; ++i) v |= (uint64_t)p[i] << (8 * i);
    return v;
}
/* shortcut: functional guest compositor bypasses CP/YC; replace when its video-plane ABI is implemented. */
static int preview_scene(const unsigned char *raw) {
    const unsigned char *m = raw + HOSD_HEADER;
    const unsigned char *present = m + 80 + 256*96 + 16;
    for (unsigned i=0; i<258; i++) if (present[i] > 1) return 0;
    if (present[256] != 1 || le(m,2) != 0x1000 || le(m+8,4) != 9 ||
        le(m+12,4) > 16 || le(m+16,4) || le(m+20,4) || le(m+24,4)) return 0;
    for (unsigned i=0; i<256; i++) if (present[i]) {
        const unsigned char *w = m + 80 + 96*i;
        if (le(w,2) != 0x1001 || le(w+8,2) != i || le(w+28,4) > 16) return 0;
    }
    const unsigned ids[] = {0,3,4,5,8};
    for (unsigned i=0; i<sizeof ids/sizeof *ids; i++) {
        const unsigned char *w = m + 80 + 96*ids[i];
        if (present[ids[i]] != 1 || le(w+10,2) != (ids[i] ? 1 : 0) ||
            le(w+12,4) != 1) return 0;
    }
    const unsigned char *w = m + 80;
    return !le(w+16,4) && le(w+20,2) == 640 && le(w+22,2) == 480;
}
static int view_stat(int fd, struct stat *st);
static int read_all(int fd, unsigned char *p, size_t n);
static int preview_profile(int fd) {
    char name[sizeof PREVIEW_NAME];
    struct stat st;
    if (view_stat(fd,&st) || !S_ISREG(st.st_mode) || st.st_size != sizeof PREVIEW_NAME-1 ||
        read(fd,name,sizeof name) != sizeof PREVIEW_NAME-1 ||
        memcmp(name,PREVIEW_NAME,sizeof PREVIEW_NAME-1)) return -1;
    return 1;
}
__attribute__((unused)) static int refresh_custom_preview(const char *path) {
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) {
        if (errno == ENOENT && custom_preview_active) {
            custom_preview_active = 0;
            memset(&custom_preview_st, 0, sizeof custom_preview_st);
            return 1;
        }
        return 0;
    }
    struct stat st;
    if (view_stat(fd, &st) || !S_ISREG(st.st_mode) || (size_t)st.st_size != PREVIEW_RGB_BYTES) {
        close(fd);
        return 0;
    }
    if (custom_preview_active &&
        st.st_dev == custom_preview_st.st_dev && st.st_ino == custom_preview_st.st_ino &&
        st.st_mtim.tv_sec == custom_preview_st.st_mtim.tv_sec &&
        st.st_mtim.tv_nsec == custom_preview_st.st_mtim.tv_nsec) {
        close(fd);
        return 0;
    }
    if (!custom_preview_rgb) {
        custom_preview_rgb = malloc(PREVIEW_RGB_BYTES);
        if (!custom_preview_rgb) { close(fd); return 0; }
    }
    if (read_all(fd, custom_preview_rgb, PREVIEW_RGB_BYTES)) {
        close(fd);
        return 0;
    }
    close(fd);
    custom_preview_st = st;
    custom_preview_active = 1;
    return 1;
}
__attribute__((unused)) static void rgb24_to_xrgb8888(const unsigned char *rgb, unsigned char *out) {
    for (unsigned i = 0; i < 640U * 480U; ++i) {
        out[4U * i + 0] = rgb[3U * i + 2];
        out[4U * i + 1] = rgb[3U * i + 1];
        out[4U * i + 2] = rgb[3U * i + 0];
        out[4U * i + 3] = 0;
    }
}
static uint64_t be(const unsigned char *p, unsigned n) {
    uint64_t v = 0;
    for (unsigned i = 0; i < n; ++i) v = (v << 8) | p[i];
    return v;
}
static void putbe(unsigned char *p, uint64_t v, unsigned n) {
    while (n) { p[--n] = v; v >>= 8; }
}
static uint64_t fnv_bytes(const unsigned char *p, unsigned n, uint64_t h) {
    while (n >= 8) {
#pragma GCC unroll 8
        for (unsigned i=0;i<8;i++) h=(h^p[i])*UINT64_C(1099511628211);
        p+=8; n-=8;
    }
    while(n--)h=(h^*p++)*UINT64_C(1099511628211);
    return h;
}
static uint64_t fnv(const unsigned char *p, unsigned n, int container) {
    uint64_t h = UINT64_C(14695981039346656037);
    if(!container || n<=40)return fnv_bytes(p,n,h);
    h=fnv_bytes(p,40,h);
    unsigned zero_end=n<48?n:48;
    for(unsigned i=40;i<zero_end;i++)h*=UINT64_C(1099511628211);
    return fnv_bytes(p+zero_end,n-zero_end,h);
}
static const char *header_error(const unsigned char *p) {
    uint64_t seq = le(p + 8, 8), source = le(p + 120, 8), phys = le(p + 32, 8);
    unsigned cmd = le(p + 56, 4);
    if (memcmp(p, "HOSDAP02", 8)) return "magic";
    if (le(p + 20, 4) != 640 || le(p + 24, 4) != 480 || le(p + 28, 4) != 1 ||
        le(p + 48, 4) != HOSD_PIXELS || le(p + 52, 4) != sizeof(struct hosd_metadata)) return "format/length";
    if (!seq || !source || source > seq || (cmd != 0x1003 && cmd != 0x1005) ||
        (cmd == 0x1003 && source != seq) || phys < UINT64_C(0x410000000) ||
        phys > UINT64_C(0x500000000) - HOSD_PIXELS) return "identity/bounds";
    if (le(p + 64, 2) != 0x1003 || le(p + 72, 4) != le(p + 16, 4) ||
        le(p + 80, 2) || le(p + 84, 2) != 640 || le(p + 86, 2) != 480 ||
        le(p + 100, 2) != 0x1002 || le(p + 108, 4) != cmd ||
        (cmd == 0x1005 && le(p + 112, 2) != 0x1005)) return "descriptor/pairing";
    return NULL;
}
static const char *validate(const unsigned char *p, size_t n) {
    if (n != HOSD_BYTES) return "container length";
    const char *err = header_error(p);
    if (err) return err;
    return fnv(p, n, 1) == le(p + 40, 8) ? NULL : "container hash";
}
static unsigned char conversion_table[65536][4];
static int conversion_ready;
static void ensure_conversion_table(void) {
    if (conversion_ready) return;
    for (unsigned v = 0; v < 65536; ++v) {
        unsigned a = v & 15;
        conversion_table[v][0] = (((v >> 4) & 15) * 17 * a + 7) / 15;
        conversion_table[v][1] = (((v >> 8) & 15) * 17 * a + 7) / 15;
        conversion_table[v][2] = ((v >> 12) * 17 * a + 7) / 15;
        conversion_table[v][3] = 0;
    }
    conversion_ready = 1;
}
static void convert(const unsigned char *p, unsigned char *out) {
    ensure_conversion_table();
    for (unsigned i = 0; i < HOSD_PIXELS / 2; ++i) {
        unsigned v = (unsigned)p[2 * i] | ((unsigned)p[2 * i + 1] << 8);
        memcpy(out + 4 * i, conversion_table[v], 4);
    }
}
static int convert_frame(const unsigned char *raw, unsigned char *out) {
    const unsigned char *pixels = raw + HOSD_HEADER + sizeof(struct hosd_metadata);
    preview_active = preview_enabled && preview_scene(raw);
    if (!preview_active) { convert(pixels,out); return 0; }
    const unsigned char *bg_rgb = custom_preview_active ? custom_preview_rgb : preview_rgb;
    if (!bg_rgb) {
        sensor_config cfg = sensor_config_default();
        preview_rgb = sensor_frame_rgb(&cfg,sensor_token_next(&cfg,0));
        if (!preview_rgb) return -1;
        bg_rgb = preview_rgb;
    }
    ensure_conversion_table();
    for (unsigned i=0; i<HOSD_PIXELS/2; i++) {
        unsigned v = (unsigned)pixels[2*i] | ((unsigned)pixels[2*i+1] << 8);
        unsigned a = v & 15;
        if (a == 0) {
            out[4*i+0] = bg_rgb[3*i+2];
            out[4*i+1] = bg_rgb[3*i+1];
            out[4*i+2] = bg_rgb[3*i+0];
            out[4*i+3] = 0;
        } else if (a == 15) {
            memcpy(out + 4*i, conversion_table[v], 4);
        } else {
            unsigned inv = 15 - a;
            out[4*i+0] = ((((v >> 4) & 15) * 17 * a) + bg_rgb[3*i+2] * inv + 7) / 15;
            out[4*i+1] = ((((v >> 8) & 15) * 17 * a) + bg_rgb[3*i+1] * inv + 7) / 15;
            out[4*i+2] = (((v >> 12) * 17 * a) + bg_rgb[3*i+0] * inv + 7) / 15;
            out[4*i+3] = 0;
        }
    }
    return 0;
}
static int config(unsigned char *cfg, unsigned char *dma, unsigned slot, unsigned selector) {
    if (slot > 1 || selector < 0x20 || selector >= 0x4000) return -1;
    putbe(cfg, RAMFB_BASE + slot * RAMFB_SLOT, 8);
    putbe(cfg + 8, 0x34325258, 4); /* DRM_FORMAT_XRGB8888 ('X','R','2','4') */
    putbe(cfg + 12, 0, 4); putbe(cfg + 16, 640, 4);
    putbe(cfg + 20, 480, 4); putbe(cfg + 24, 2560, 4);
    putbe(dma, (selector << 16) | 0x18, 4);
    putbe(dma + 4, 28, 4); putbe(dma + 8, RAMFB_BASE + RAMFB_CFG, 8);
    return 0;
}
static void barrier(void) {
#ifdef __aarch64__
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __sync_synchronize();
#endif
}
/* Narrow test seam: bus accesses only; all protocol decisions remain here. */
struct bus {
    void *ctx;
    void (*select)(void *, uint16_t);
    unsigned char (*data)(void *);
    uint64_t (*signature)(void *);
    void (*kick)(void *, uint64_t);
    void (*pause)(void *);
};
static void bus_read(struct bus *b, unsigned char *p, unsigned n) {
    for (unsigned i = 0; i < n; ++i) p[i] = b->data(b->ctx);
}
static int discover(struct bus *b) {
    unsigned char raw[64];
    b->select(b->ctx, 0); bus_read(b, raw, 4);
    if (memcmp(raw, "QEMU", 4)) return -1;
    b->select(b->ctx, 1); bus_read(b, raw, 4);
    if (!(le(raw, 4) & 2) || b->signature(b->ctx) != UINT64_C(0x51454d5520434647)) return -1;
    b->select(b->ctx, 0x19); bus_read(b, raw, 4);
    unsigned count = be(raw, 4);
    if (!count || count > 256) return -1;
    for (unsigned i = 0; i < count; ++i) {
        bus_read(b, raw, 64);
        if (!memcmp(raw + 8, "etc/ramfb\0", 10)) {
            unsigned sel = be(raw + 4, 2);
            return be(raw, 4) == 28 && sel >= 0x20 && sel < 0x4000 ? (int)sel : -1;
        }
    }
    return -1;
}
static int submit(struct bus *b, unsigned char *pool, unsigned slot, unsigned selector) {
    barrier(); /* Finish the inactive scanout before publishing its descriptor. */
    if (config(pool + RAMFB_CFG, pool + RAMFB_DMA, slot, selector)) return -1;
    barrier();
    b->kick(b->ctx, RAMFB_BASE + RAMFB_DMA);
    for (unsigned i = 0; i < 100; ++i) {
        barrier();
        uint32_t ctl = __builtin_bswap32(*(volatile uint32_t *)(pool + RAMFB_DMA));
        if (!ctl) return 0;
        if (ctl & 1) return -1;
        b->pause(b->ctx);
    }
    return -2;
}
static int read_all(int fd, unsigned char *p, size_t n) {
    while (n) {
        ssize_t got = read(fd, p, n);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) return -1;
        p += got; n -= got;
    }
    return 0;
}
struct consumer {
    int fd;
    struct stat st;
    unsigned char header[HOSD_HEADER];
    uint64_t pixel_hash;
};
static int view_stat(int fd, struct stat *st) {
#ifdef __aarch64__
    /* Firmware glibc 2.25 exports the versioned ABI, not glibc 2.33's fstat. */
    extern int __fxstat(int, int, struct stat *);
    return __fxstat(0, fd, st);
#else
    return fstat(fd, st);
#endif
}
/* Caller commits only after successful DMA (or verified retained source). */
static int snapshot(struct consumer *s, int fd, unsigned char *raw, struct stat *st, const char **err) {
    if (view_stat(fd, st) || !S_ISREG(st->st_mode) || st->st_size != HOSD_BYTES ||
        read_all(fd, raw, HOSD_HEADER)) { *err = "read/stat/length"; return -1; }
    *err = header_error(raw);
    if (*err) return -1;
    if (s->fd >= 0 && st->st_dev == s->st.st_dev && st->st_ino == s->st.st_ino &&
        st->st_mtim.tv_sec == s->st.st_mtim.tv_sec && st->st_mtim.tv_nsec == s->st.st_mtim.tv_nsec &&
        st->st_ctim.tv_sec == s->st.st_ctim.tv_sec && st->st_ctim.tv_nsec == s->st.st_ctim.tv_nsec &&
        !memcmp(raw, s->header, HOSD_HEADER)) return 0;
    unsigned char extra;
    if (read_all(fd, raw + HOSD_HEADER, HOSD_BYTES - HOSD_HEADER) || read(fd, &extra, 1) != 0) {
        *err = "read/EOF"; return -1;
    }
    *err = validate(raw, HOSD_BYTES);
    if (*err) return -1;
    if (s->fd >= 0) {
        if (le(raw + 8, 8) == le(s->header + 8, 8) && memcmp(raw, s->header, HOSD_HEADER)) {
            *err = "sequence reused"; return -1;
        }
        if (le(raw + 8, 8) < le(s->header + 8, 8) || le(raw + 120, 8) < le(s->header + 120, 8)) {
            *err = "sequence rollback"; return -1;
        }
        if (le(raw + 120, 8) == le(s->header + 120, 8)) {
            if (memcmp(raw + 16, s->header + 16, 24) || memcmp(raw + 64, s->header + 64, 36) ||
                fnv(raw + HOSD_HEADER + sizeof(struct hosd_metadata), HOSD_PIXELS, 0) != s->pixel_hash) {
                *err = "retained source changed"; return -1;
            }
            return 1;
        }
    }
    return 2;
}
static void commit(struct consumer *s, int fd, struct stat *st, const unsigned char *raw) {
    int same_pixels = s->fd >= 0 && le(raw + 120, 8) == le(s->header + 120, 8);
    if (s->fd >= 0) close(s->fd);
    s->fd = fd; s->st = *st; memcpy(s->header, raw, HOSD_HEADER);
    if (!same_pixels) {
        s->pixel_hash = fnv(raw + HOSD_HEADER + sizeof(struct hosd_metadata), HOSD_PIXELS, 0);
    }
}

#ifndef RAMFB_TEST
#include <poll.h>
#include <sys/inotify.h>
static void fault(int signo) {
    (void)signo;
    static const char line[] = "RAMFB_FAIL reason=MMIO/memory signal fault; no display proof\n";
    int fd = open("/tmp/ramfb-viewer.log", O_CREAT | O_WRONLY | O_APPEND, 0600);
    if (fd >= 0) { ssize_t ignored = write(fd, line, sizeof line - 1); (void)ignored; }
    fd = open("/tmp/ramfb-viewer.status", O_CREAT | O_WRONLY | O_TRUNC, 0600);
    if (fd >= 0) { ssize_t ignored = write(fd, line, sizeof line - 1); (void)ignored; }
    _exit(1);
}
static void mm_select(void *ctx, uint16_t key) {
    *(volatile uint16_t *)((unsigned char *)ctx + 8) = __builtin_bswap16(key); barrier();
}
static unsigned char mm_data(void *ctx) { return *(volatile unsigned char *)ctx; }
static uint64_t mm_signature(void *ctx) {
    return __builtin_bswap64(*(volatile uint64_t *)((unsigned char *)ctx + 16));
}
static void mm_kick(void *ctx, uint64_t addr) {
    *(volatile uint64_t *)((unsigned char *)ctx + 16) = __builtin_bswap64(addr); barrier();
}
static void mm_pause(void *ctx) { (void)ctx; usleep(1000); }
static void record(const char *event, const char *reason, const unsigned char *h, unsigned slot) {
    char line[512];
    int n = snprintf(line, sizeof line,
        "RAMFB_%s reason=%s errno=%d seq=%llu pixel_source=%llu source_phys=0x%llx hash=%016llx scanout=0x%llx\n",
        event, reason, errno, (unsigned long long)le(h+8,8), (unsigned long long)le(h+120,8),
        (unsigned long long)le(h+32,8), (unsigned long long)le(h+40,8),
        (unsigned long long)(RAMFB_BASE + slot * RAMFB_SLOT));
    int fd = open("/tmp/ramfb-viewer.log", O_CREAT | O_WRONLY | O_APPEND, 0600);
    if (fd >= 0) {
        if (lseek(fd, 0, SEEK_END) > 65536 - n) ftruncate(fd, 0);
        if (write(fd, line, n) != n) dprintf(2, "RAMFB_LOG_WRITE_FAILED\n");
        close(fd);
    }
    fd = open("/tmp/ramfb-viewer.status", O_CREAT | O_WRONLY | O_TRUNC, 0600);
    if (fd >= 0) { if (write(fd, line, n) != n) dprintf(2, "RAMFB_STATUS_WRITE_FAILED\n"); close(fd); }
    if (!strcmp(event, "FAIL")) dprintf(2, "%s", line);
}
static int present_stage(struct bus *b, unsigned char *pool, const unsigned char *stage,
                         unsigned *slot, unsigned selector) {
    unsigned target = *slot ^ 1;
    memcpy(pool + target * RAMFB_SLOT, stage, XRGB_BYTES);
    int result = submit(b, pool, target, selector);
    if (!result) *slot = target;
    return result;
}
/* Returns: 0 = not active, 1 = active & newly rendered to stage, 2 = active & unchanged. */
static int check_playback_frame(unsigned char *stage, struct stat *last_st, int *was_active) {
    static unsigned char pb_buf[PREVIEW_PLAYBACK_BYTES];
    int fd = open(PREVIEW_PLAYBACK_FRAME, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) {
        int exited = *was_active;
        *was_active = 0;
        memset(last_st, 0, sizeof *last_st);
        return exited ? -1 : 0; /* -1 signals playback just exited, restore live OSD */
    }
    struct stat st;
    if (view_stat(fd, &st) || !S_ISREG(st.st_mode) || (size_t)st.st_size != PREVIEW_PLAYBACK_BYTES) {
        close(fd);
        return *was_active ? 2 : 0;
    }
    if (*was_active &&
        st.st_dev == last_st->st_dev && st.st_ino == last_st->st_ino &&
        st.st_mtim.tv_sec == last_st->st_mtim.tv_sec &&
        st.st_mtim.tv_nsec == last_st->st_mtim.tv_nsec) {
        close(fd);
        return 2;
    }
    if (read_all(fd, pb_buf, PREVIEW_PLAYBACK_BYTES) ||
        memcmp(pb_buf, "VPLAY001", 8) != 0 ||
        le(pb_buf + 12, 2) != 640 || le(pb_buf + 14, 2) != 480) {
        close(fd);
        return *was_active ? 2 : 0;
    }
    close(fd);
    rgb24_to_xrgb8888(pb_buf + PREVIEW_PLAYBACK_HDR, stage);
    *last_st = st;
    *was_active = 1;
    return 1;
}
static int check_shutter_blink(struct stat *last_st, int *have_last) {
    int fd = open(PREVIEW_SHUTTER_BLINK, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return 0;
    struct stat st;
    int ok = !view_stat(fd, &st) && S_ISREG(st.st_mode);
    close(fd);
    if (!ok) return 0;
    if (*have_last &&
        st.st_dev == last_st->st_dev && st.st_ino == last_st->st_ino &&
        st.st_mtim.tv_sec == last_st->st_mtim.tv_sec &&
        st.st_mtim.tv_nsec == last_st->st_mtim.tv_nsec) {
        return 0;
    }
    *last_st = st;
    int triggered = *have_last || st.st_size > 0;
    *have_last = 1;
    return triggered;
}
static int run(void) {
    static unsigned char raw[HOSD_BYTES];
    static unsigned char stage[XRGB_BYTES];
    struct consumer s = {.fd = -1};
    int profile = open(PREVIEW_PROFILE,O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (profile >= 0) {
        preview_enabled = preview_profile(profile);
        close(profile);
        if (preview_enabled < 0) { record("FAIL","virtual-preview profile invalid",raw,0); return 1; }
    } else if (errno != ENOENT) { record("FAIL","virtual-preview profile unreadable",raw,0); return 1; }
    if (preview_enabled) refresh_custom_preview(PREVIEW_CUSTOM_RGB);
    signal(SIGBUS, fault); signal(SIGSEGV, fault);
    int lock = open("/tmp/ramfb-viewer.lock", O_CREAT | O_RDWR, 0600);
    if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) { record("FAIL", "already running/lock", raw, 0); return 1; }
    char cmdline[8192];
    int command = open("/proc/cmdline", O_RDONLY);
    ssize_t count = command >= 0 ? read(command, cmdline, sizeof cmdline - 1) : -1;
    if (command >= 0) close(command);
    if (count <= 0 || count == sizeof cmdline - 1) { record("FAIL", "read cmdline", raw, 0); return 1; }
    cmdline[count] = 0;
    if (!reserved(cmdline)) { record("FAIL", "scanout reservation missing", raw, 0); return 1; }
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) { record("FAIL", "open /dev/mem", raw, 0); return 1; }
    void *mmio = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, FW_BASE);
    if (mmio == MAP_FAILED) { record("FAIL", "mmap fw_cfg", raw, 0); return 1; }
    struct bus b = {mmio, mm_select, mm_data, mm_signature, mm_kick, mm_pause};
    int selector = discover(&b);
    if (selector < 0) { record("FAIL", "fw_cfg signature/DMA/etc/ramfb", raw, 0); return 1; }
    unsigned char *pool = mmap(NULL, RAMFB_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, RAMFB_BASE);
    close(fd);
    if (pool == MAP_FAILED) { record("FAIL", "mmap reserved scanout", raw, 0); return 1; }
    int infd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
    if (infd >= 0) {
        if (inotify_add_watch(infd, "/tmp", IN_MOVED_TO | IN_CLOSE_WRITE | IN_DELETE) < 0) {
            close(infd);
            infd = -1;
        }
    }
    char init[160];
    snprintf(init, sizeof init, "fw_cfg=0x9020000 selector=0x%x DMA=0x%llx config=0x%llx awaiting snapshot",
             selector, (unsigned long long)(RAMFB_BASE + RAMFB_DMA),
             (unsigned long long)(RAMFB_BASE + RAMFB_CFG));
    record("INIT", init, raw, 0);
    unsigned slot = 1, ticks = 0;
    struct stat pb_st, blink_st;
    memset(&pb_st, 0, sizeof pb_st);
    memset(&blink_st, 0, sizeof blink_st);
    int pb_active = 0, have_blink = 0, have_raw = 0;
    for (;;) {
        if (ticks > 0) {
            if (infd >= 0) {
                struct pollfd pfd = {.fd = infd, .events = POLLIN};
                int ready = poll(&pfd, 1, 150);
                if (ready > 0) {
                    char evbuf[2048];
                    while (read(infd, evbuf, sizeof evbuf) > 0) {}
                }
            } else {
                usleep(10000);
            }
        }
        ++ticks;

        int force_redraw = 0;
        int pb = check_playback_frame(stage, &pb_st, &pb_active);
        if (pb == 1) {
            int result = present_stage(&b, pool, stage, &slot, selector);
            if (result) {
                record("FAIL", result == -2 ? "DMA timeout; state uncertain" : "DMA error", raw, slot);
                return 1;
            }
            record("SUBMITTED", "virtual-playback=1 DMA-is-not-screenshot-proof", raw, slot);
        } else if (pb < 0) {
            force_redraw = 1;
        }

        if (preview_enabled && refresh_custom_preview(PREVIEW_CUSTOM_RGB) && have_raw && !pb_active) {
            force_redraw = 1;
        }

        if (have_raw && !pb_active && check_shutter_blink(&blink_st, &have_blink)) {
            memset(stage, 0, XRGB_BYTES);
            int result = present_stage(&b, pool, stage, &slot, selector);
            if (result) {
                record("FAIL", result == -2 ? "DMA timeout; state uncertain" : "DMA error", raw, slot);
                return 1;
            }
            usleep(55000);
            force_redraw = 1;
        }

        int next = open(HOSD_PATH, O_RDONLY | O_NONBLOCK | O_NOFOLLOW);
        if (next < 0) {
            if (ticks == 1 || ticks % 100 == 0) record("WAIT", "snapshot unavailable", s.header, slot);
            continue;
        }
        struct stat st;
        const char *err = NULL;
        int action = snapshot(&s, next, raw, &st, &err);
        if (action < 0) {
            close(next);
            record("REJECT", err, raw, slot);
            continue;
        }
        if (action == 0) {
            close(next);
            if (force_redraw && have_raw && !pb_active) {
                if (convert_frame(raw, stage)) {
                    record("FAIL", "virtual-preview sensor generation failed", raw, slot);
                    return 1;
                }
                int result = present_stage(&b, pool, stage, &slot, selector);
                if (result) {
                    record("FAIL", result == -2 ? "DMA timeout; state uncertain" : "DMA error", raw, slot);
                    return 1;
                }
                record("SUBMITTED",
                       preview_active ? (custom_preview_active ? "virtual-preview=custom-rgb CP-YC-unverified DMA-is-not-screenshot-proof"
                                                               : "virtual-preview=functional-cmos-chart-v1 CP-YC-unverified DMA-is-not-screenshot-proof")
                                      : "virtual-preview=off DMA-is-not-screenshot-proof", raw, slot);
            }
            continue;
        }
        have_raw = 1;
        int need_submit = !pb_active && (action == 2 || force_redraw || (preview_enabled && action == 1));
        if (need_submit) {
            if (convert_frame(raw, stage)) {
                record("FAIL","virtual-preview sensor generation failed",raw,slot);
                close(next); return 1;
            }
            int result = present_stage(&b, pool, stage, &slot, selector);
            if (result) {
                record("FAIL", result == -2 ? "DMA timeout; state uncertain" : "DMA error", raw, slot);
                close(next); return 1;
            }
        }
        commit(&s, next, &st, raw);
        if (!pb_active) {
            record(need_submit ? "SUBMITTED" : "RETAINED",
                   preview_active ? (custom_preview_active ? "virtual-preview=custom-rgb CP-YC-unverified DMA-is-not-screenshot-proof"
                                                           : "virtual-preview=functional-cmos-chart-v1 CP-YC-unverified DMA-is-not-screenshot-proof")
                                  : "virtual-preview=off DMA-is-not-screenshot-proof", raw, slot);
        }
    }
}
void _start(void) { _exit(run()); }
#endif
