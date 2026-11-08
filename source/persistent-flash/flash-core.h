/* SPDX-License-Identifier: MIT */
#ifndef A7PF_CORE_H
#define A7PF_CORE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
#define A7PF_MAGIC 0x46503741u
#define A7PF_VERSION 1u
#define A7PF_MAX_IO 131072u
#define A7PF_MMIO 0x0b000000u
#define A7PF_READ 2u
#define A7PF_WRITE 3u
#define A7PF_FLUSH 4u
#define A7PF_GEOMETRY 1u
#define A7PF_DONE 1u
#define A7PF_FAILED 2u
struct a7pf_slice { uint32_t number; uint64_t offset, length; };
/* DMA returns errno; probe must validate the complete writable RAM span without IO. */
typedef int (*a7pf_dma_fn)(void *, uint64_t, void *, size_t, bool write, bool probe);
struct a7pf_io {
    ssize_t (*read)(int, void *, size_t, off_t);
    ssize_t (*write)(int, const void *, size_t, off_t);
    int (*sync)(int);
};
struct a7pf {
    int fd;
    uint64_t dev, ino, capacity, container_bytes;
    struct a7pf_slice slices[32];
    uint32_t entries, parts, boot_count, select, count, status, actual, error;
    uint64_t sector, dma_addr, geometry_size, geometry_start;
    a7pf_dma_fn dma;
    void *dma_opaque;
    struct a7pf_io io;
    uint8_t bounce[A7PF_MAX_IO];
};
int a7pf_open_regular(const char *path, int flags);
int a7pf_init(struct a7pf *s, int backend_fd, int geometry_fd, uint64_t dev,
              uint64_t ino, a7pf_dma_fn dma, void *opaque);
void a7pf_close(struct a7pf *s);
uint32_t a7pf_read_reg(struct a7pf *s, uint32_t offset);
void a7pf_write_reg(struct a7pf *s, uint32_t offset, uint32_t value);
#endif
