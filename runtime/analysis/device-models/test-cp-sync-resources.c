/* SPDX-License-Identifier: MIT */
#include "cp-sync-resources.h"
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

int main(void) {
    struct cp_sync_resources *s=cp_sync_create(1024);assert(s);
    struct cp_sync_snapshot v;
    assert(!cp_sync_snapshot(s,&v) && v.idle && !v.bytes);
    uint64_t a=0,b=0,c=0,old;
    unsigned char bytes[256],readback[256];
    for (unsigned int i=0;i<sizeof bytes;i++) bytes[i]=(unsigned char)(i*17+3);
    assert(!cp_sync_allocate(s,0,sizeof bytes,&a));old=a;
    struct cp_sync_resources *other=cp_sync_create(1);assert(other);
    uint64_t foreign;
    assert(!cp_sync_allocate(other,0,1,&foreign) && foreign!=a);
    assert(cp_sync_release(other,a)==-ESTALE && cp_sync_release(s,foreign)==-ESTALE);
    assert(!cp_sync_release(other,foreign) && !cp_sync_free(other,0,foreign) && !cp_sync_destroy(other));
    assert(!cp_sync_write(s,a,0,bytes,sizeof bytes));
    assert(!cp_sync_alias(s,60,a,&b));
    assert(!cp_sync_read(s,b,0,readback,sizeof readback));
    assert(!memcmp(bytes,readback,sizeof bytes));
    assert(cp_sync_write(s,a,0,bytes,1)==-EBUSY);
    assert(cp_sync_free(s,0,old)==-EBUSY && cp_sync_destroy(s)==-EBUSY);
    assert(!cp_sync_release(s,a));
    assert(cp_sync_release(s,a)==-ESTALE);
    assert(cp_sync_read(s,a,0,readback,1)==-ESTALE);
    assert(cp_sync_free(s,60,old)==-EBUSY);
    assert(!cp_sync_release(s,b));
    assert(!cp_sync_snapshot(s,&v) && !v.idle && v.bytes==256 && !v.references);
    assert(!cp_sync_free(s,60,old));
    assert(cp_sync_free(s,0,old)==-ENOENT);
    assert(!cp_sync_snapshot(s,&v) && v.idle && !v.bytes && !v.bound_resources);
    assert(!cp_sync_allocate(s,0,256,&a) && a!=old);
    assert(cp_sync_release(s,old)==-ESTALE);
    assert(cp_sync_read(s,a,SIZE_MAX,readback,1)==-EINVAL);
    assert(cp_sync_allocate(s,72,1,&b)==-EINVAL);
    assert(cp_sync_allocate(s,1,769,&b)==-ENOSPC);
    assert(!cp_sync_write(s,a,0,bytes,sizeof bytes)); /* new allocation is writable */
    assert(!cp_sync_acquire(s,0,&c));
    assert(cp_sync_free(s,0,a)==-EBUSY);
    assert(!cp_sync_release(s,a));
    unsigned char attempted=0xee;
    assert(cp_sync_write(s,c,0,&attempted,1)==-EBUSY); /* receiver cannot unfreeze */
    assert(!cp_sync_read(s,c,0,readback,sizeof readback));
    assert(!memcmp(bytes,readback,sizeof bytes));
    assert(!cp_sync_release(s,c));
    assert(!cp_sync_acquire(s,0,&c)); /* even reopening after zero refs stays frozen */
    assert(cp_sync_write(s,c,0,&attempted,1)==-EBUSY);
    assert(!cp_sync_read(s,c,0,readback,sizeof readback));
    assert(!memcmp(bytes,readback,sizeof bytes));
    assert(!cp_sync_release(s,c));
    assert(cp_sync_free(s,0,old)==-ESTALE);
    assert(!cp_sync_snapshot(s,&v) && !v.idle && v.bytes==256);
    assert(!cp_sync_free(s,0,a));
    /* SGC1 exclusion is the original idle predicate, not permission to leak it. */
    assert(!cp_sync_allocate(s,12,128,&a));
    assert(!cp_sync_snapshot(s,&v) && v.idle && v.bytes==128 && v.references==1);
    assert(!cp_sync_alias(s,0,a,&b));
    assert(!cp_sync_snapshot(s,&v) && !v.idle);
    assert(!cp_sync_release(s,a) && !cp_sync_release(s,b) && !cp_sync_free(s,12,a));
    /* Every issued lease is unique; exhausting references rolls alias back. */
    uint64_t tokens[CP_SYNC_LEASE_COUNT];
    assert(!cp_sync_allocate(s,0,1,&tokens[0]));
    for (unsigned int i=1;i<CP_SYNC_LEASE_COUNT;i++) assert(!cp_sync_acquire(s,0,&tokens[i]));
    assert(cp_sync_alias(s,1,tokens[0],&b)==-ENOSPC);
    assert(!cp_sync_snapshot(s,&v) && v.bound_resources==1 && v.references==256);
    pid_t pid=fork();assert(pid>=0);
    if (!pid) _exit(cp_sync_snapshot(s,&v)==-ECHILD && cp_sync_destroy(s)==-ECHILD ? 0:1);
    int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));
    for (unsigned int i=0;i<CP_SYNC_LEASE_COUNT;i++) assert(!cp_sync_release(s,tokens[i]));
    assert(!cp_sync_free(s,0,tokens[0]) && !cp_sync_destroy(s));
    return 0;
}
