/* SPDX-License-Identifier: MIT */
/* Copy one chunk of the guest card image into the reserved export window.
 *
 * The host then reads that window with QMP pmemsave, so the card leaves the VM
 * without any faked transport: the guest only does a plain pread of its own file
 * plus a memcpy into a declared reserved region.
 *
 * Usage: card-export <image> <chunk-index> [chunk-bytes]
 * Prints CARD_EXPORT_CHUNK index=<n> offset=<o> bytes=<b> fnv64=<hex> window=<phys>
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <sys/mman.h>
#include "guest-stat-compat.h"
/* Host glibc headers redirect strtoul to __isoc23_strtoul, absent on Sony 2.25. */
extern unsigned long strtoul(const char *, char **, int);
extern int printf(const char *, ...);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                             void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");

#define CARD_WINDOW_PHYSICAL 0x41eb00000UL
#define CARD_WINDOW_BYTES    0x400000UL
#define PROT_READ_WRITE      3
#define MAP_SHARED_FLAG      1

static int unchanged(const struct stat *a, const struct stat *b) {
    return a->st_dev == b->st_dev && a->st_ino == b->st_ino && a->st_size == b->st_size &&
        a->st_mtim.tv_sec == b->st_mtim.tv_sec && a->st_mtim.tv_nsec == b->st_mtim.tv_nsec &&
        a->st_ctim.tv_sec == b->st_ctim.tv_sec && a->st_ctim.tv_nsec == b->st_ctim.tv_nsec;
}

static int run(int argc, char **argv) {
    if (argc < 3 || argc > 4) {
        printf("CARD_EXPORT_USAGE argc=%d\n", argc);
        return 2;
    }
    char *end;
    unsigned long index = strtoul(argv[2], &end, 0);
    if (end == argv[2] || *end || index >= 512) { printf("CARD_EXPORT_BAD_INDEX %s\n", argv[2]); return 2; }
    unsigned long chunk = CARD_WINDOW_BYTES;
    if (argc == 4) {
        chunk = strtoul(argv[3], &end, 0);
        if (end == argv[3] || *end || !chunk || chunk > CARD_WINDOW_BYTES) { printf("CARD_EXPORT_BAD_SIZE\n"); return 2; }
    }
    unsigned long offset = index * CARD_WINDOW_BYTES;
    int fd = open(argv[1], O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) { printf("CARD_EXPORT_OPEN_FAILED %s\n", argv[1]); return 3; }
    struct stat before, after;
    if (fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_size <= 0 ||
        offset > (unsigned long)before.st_size || chunk > (unsigned long)before.st_size - offset) {
        close(fd); printf("CARD_EXPORT_BAD_SOURCE\n"); return 3;
    }
    /* Read straight into the window through a temporary copy: pread into the mapped
     * region keeps one memcpy and lets the digest run over exactly what the host reads. */
    int mem = open("/dev/mem", O_RDWR | O_SYNC | O_CLOEXEC);
    if (mem < 0) { close(fd); printf("CARD_EXPORT_DEVMEM_FAILED\n"); return 4; }
    volatile unsigned char *window = mmap(0, CARD_WINDOW_BYTES, PROT_READ_WRITE,
                                          MAP_SHARED_FLAG, mem, (long)CARD_WINDOW_PHYSICAL);
    close(mem);
    if ((void *)window == (void *)-1) { close(fd); printf("CARD_EXPORT_MMAP_FAILED\n"); return 5; }
    long got = pread(fd, (void *)window, chunk, (long)offset);
    int stable = !fstat(fd, &after) && unchanged(&before, &after);
    close(fd);
    if (got != (long)chunk || !stable) {
        munmap((void *)window, CARD_WINDOW_BYTES);
        printf("CARD_EXPORT_SHORT_READ index=%lu got=%ld want=%lu\n", index, got, chunk);
        return 6;
    }
    unsigned long long hash = 0xcbf29ce484222325ULL;
    for (unsigned long i = 0; i < chunk; ++i) hash = (hash ^ window[i]) * 0x100000001b3ULL;
    munmap((void *)window, CARD_WINDOW_BYTES);
    printf("CARD_EXPORT_SOURCE dev=%llu ino=%llu size=%lld mtime=%lld.%09ld ctime=%lld.%09ld\n",
           (unsigned long long)before.st_dev, (unsigned long long)before.st_ino,
           (long long)before.st_size, (long long)before.st_mtim.tv_sec, before.st_mtim.tv_nsec,
           (long long)before.st_ctim.tv_sec, before.st_ctim.tv_nsec);
    printf("CARD_EXPORT_CHUNK index=%lu offset=%lu bytes=%lu fnv64=%016llx window=%#lx\n",
           index, offset, chunk, hash, CARD_WINDOW_PHYSICAL);
    return 0;
}

__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
