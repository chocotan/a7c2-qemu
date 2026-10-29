/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-property-stage-file.h"
#include "adf-public-config.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int file_stat(int fd, struct stat *st) {
#ifdef __aarch64__
    /* Firmware glibc 2.25 exports this ABI instead of fstat. */
    extern int __fxstat(int, int, struct stat *);
    return __fxstat(0, fd, st);
#else
    return fstat(fd, st);
#endif
}
static int disjoint(const void *a,size_t an,const void *b,size_t bn) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && an<=UINTPTR_MAX-x && bn<=UINTPTR_MAX-y &&
           (x+an<=y || y+bn<=x);
}
int cp_property_stage_load_public_file(struct cp_property_stage *stage,
    const struct cp_start_state_guard *guard, int fd, struct cp_parameter_import *decision)
{
    int incoming_errno = errno, rc = -EINVAL;
    struct stat before, after;
    unsigned char *bytes = NULL, extra;
    size_t at = 0;
    unsigned long long hash = 0xcbf29ce484222325ULL;
    struct cp_property_stage next;
    struct cp_parameter_import imported;
    if(fd<0 || !stage || !guard || !decision ||
       (uintptr_t)stage%_Alignof(struct cp_property_stage) ||
       (uintptr_t)guard%_Alignof(struct cp_start_state_guard) ||
       (uintptr_t)decision%_Alignof(struct cp_parameter_import) ||
       !disjoint(stage,sizeof(*stage),guard,sizeof(*guard)) ||
       !disjoint(stage,sizeof(*stage),decision,sizeof(*decision)) ||
       !disjoint(guard,sizeof(*guard),decision,sizeof(*decision))) goto done;
    if (file_stat(fd, &before) || !S_ISREG(before.st_mode) ||
        before.st_size != (off_t)FULL_ADF_PUBLIC_SEED_BYTES) { rc = -EILSEQ; goto done; }
    bytes = malloc(FULL_ADF_PUBLIC_SEED_BYTES);
    if (!bytes) { rc = -ENOMEM; goto done; }
    while (at < FULL_ADF_PUBLIC_SEED_BYTES) {
        ssize_t actual = pread(fd, bytes + at, FULL_ADF_PUBLIC_SEED_BYTES - at, (off_t)at);
        if (actual < 0 && errno == EINTR) continue;
        if (actual <= 0 || (size_t)actual > FULL_ADF_PUBLIC_SEED_BYTES - at) { rc = -EIO; goto done; }
        for (ssize_t i = 0; i < actual; ++i) hash = (hash ^ bytes[at + (size_t)i]) * 0x100000001b3ULL;
        at += (size_t)actual;
    }
    if (hash != FULL_ADF_PUBLIC_SEED_FNV || pread(fd, &extra, 1, FULL_ADF_PUBLIC_SEED_BYTES) != 0 ||
        file_stat(fd, &after) || before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
        before.st_size != after.st_size || before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
        before.st_mtim.tv_nsec != after.st_mtim.tv_nsec || before.st_ctim.tv_sec != after.st_ctim.tv_sec ||
        before.st_ctim.tv_nsec != after.st_ctim.tv_nsec) { rc = -EILSEQ; goto done; }
    memcpy(&next,stage,sizeof(next));
    rc = cp_property_stage_consume(&next, guard, CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE,
                                  bytes + CP_PROPERTY_STAGE_ALLLANG_OFFSET, CP_PROPERTY_STAGE_BYTES);
    if(!rc)rc=cp_parameter_import_inspect(&next,guard,bytes+CP_PROPERTY_STAGE_ALLLANG_OFFSET,
                                        CP_PROPERTY_STAGE_BYTES,&imported);
    if(!rc){memcpy(stage,&next,sizeof(next));memcpy(decision,&imported,sizeof(imported));}
done:
    free(bytes);
    errno = incoming_errno;
    return rc;
}
