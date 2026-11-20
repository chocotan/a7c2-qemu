/* Host-only test wrapper; link the current production flash-core.c unchanged. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "flash-core.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>

static int no_dma(void *opaque, uint64_t address, void *buffer, size_t length,
                  bool write, bool probe)
{
    (void)opaque; (void)address; (void)buffer; (void)length;
    (void)write; (void)probe;
    return ENOSYS;
}

/* Return the failed checkpoint, never issue storage IO or silently accept errors. */
int check_ofd(int backend, int geometry)
{
    struct a7pf first, second, other;
    struct stat st;
    char path[64];
    int independent = -1, result = 0, err;
    first.fd = second.fd = other.fd = -1;
    if (fstat(backend, &st) || !S_ISREG(st.st_mode)) return 1;
    if (snprintf(path, sizeof(path), "/proc/self/fd/%d", backend) >= (int)sizeof(path)) return 2;
    independent = open(path, O_RDWR | O_CLOEXEC | O_NONBLOCK);
    if (independent < 0) return 3;
    err = a7pf_init(&first, backend, geometry, st.st_dev, st.st_ino, no_dma, NULL);
    if (err) { result = 4; goto done; }
    err = a7pf_init(&second, backend, geometry, st.st_dev, st.st_ino, no_dma, NULL);
    if (err) { result = 5; goto done; }
    if (first.fd == backend || second.fd == backend || first.fd == second.fd) {
        result = 6; goto done;
    }
    err = a7pf_init(&other, independent, geometry, st.st_dev, st.st_ino, no_dma, NULL);
    if ((err != EAGAIN && err != EACCES) || other.fd != -1) {
        result = 7; goto done;
    }
    a7pf_close(&second);
    a7pf_close(&first);
    /* Only Python now owns the OFD; close must not have issued F_UNLCK. */
    err = a7pf_init(&other, independent, geometry, st.st_dev, st.st_ino, no_dma, NULL);
    if ((err != EAGAIN && err != EACCES) || other.fd != -1) result = 8;
done:
    a7pf_close(&other);
    a7pf_close(&second);
    a7pf_close(&first);
    close(independent);
    return result;
}
