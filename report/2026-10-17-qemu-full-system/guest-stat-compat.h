/* SPDX-License-Identifier: MIT */
#ifndef FULL_GUEST_STAT_COMPAT_H
#define FULL_GUEST_STAT_COMPAT_H
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <stddef.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
/* Same original kernel ABI used by bounded-log.c. Modern host headers reference
 * fstat/fstatat symbols absent from Sony glibc2.25; do not link the host libc. */
#if defined(__aarch64__) && !defined(FULL_OSD_HOST_FIXTURE)
_Static_assert(SYS_fstat==80 && SYS_newfstatat==79,"unexpected arm64 stat syscalls");
_Static_assert(sizeof(struct stat)==128 && offsetof(struct stat,st_mode)==16 &&
               offsetof(struct stat,st_uid)==24 && offsetof(struct stat,st_size)==48,
               "unexpected Sony4.9 arm64 kernel stat layout");
static inline int full_guest_fstat(int fd,struct stat *st){
    return (int)syscall(SYS_fstat,fd,st);
}
static inline int full_guest_fstatat(int directory,const char *name,struct stat *st,int flags){
    return (int)syscall(SYS_newfstatat,directory,name,st,flags);
}
#define fstat full_guest_fstat
#define fstatat full_guest_fstatat
#endif
#endif
