/* SPDX-License-Identifier: MIT */
#ifndef PMBP_LIBC_H
#define PMBP_LIBC_H
#include "pmbp-candidate.h"
#include <fcntl.h>
#include <sys/uio.h>
struct pmbp_libc_io {
 int (*open)(const char *,int,mode_t);
 int (*stat)(int,int,struct stat *);
 int (*close)(int);
 ssize_t (*write)(int,const void *,size_t);
 ssize_t (*pwrite)(int,const void *,size_t,off_t);
 ssize_t (*pread)(int,void *,size_t,off_t);
 int (*ioctl)(int,unsigned long,void *);
 int (*duplicate)(int);
 ssize_t (*read)(int,void *,size_t);
 off_t (*seek)(int,off_t,int);
 int (*dup)(int);
 int (*dup2)(int,int);
 int (*dup3)(int,int,int);
 int (*fcntl)(int,int,...);
 ssize_t (*pwritev)(int,const struct iovec *,int,off_t);
 int (*fsync)(int);
};
const struct pmbp_libc_io *pmbp_native_io(void);
void *pmbp_next(const char *);
int pmbp_libc_identity(void);
#endif
