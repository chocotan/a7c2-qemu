#define _GNU_SOURCE
#include "p1-trust-key.h"
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
/* Original AArch64 glibc 2.25 exports __fxstat(version=0), not fstat. */
#ifdef __aarch64__
extern int __fxstat(int,int,struct stat *);
#define snapshot_stat(fd,st) __fxstat(0,fd,st)
#else
#define snapshot_stat(fd,st) fstat(fd,st)
#endif

int p1_trust_key_read(const char *profile,const char *snapshot,
                      p1_trust_hash_fn sha1,p1_trust_hash_fn sha256,unsigned char digest[20]) {
    static const unsigned char expected[32]={
        0x82,0x81,0x41,0x3b,0x56,0x07,0x44,0x69,0x39,0x61,0x3e,0x07,0xd0,0x20,0xb2,0xc7,
        0xd8,0xee,0x23,0x71,0x34,0x90,0x99,0xde,0x56,0xbc,0x82,0x88,0xf7,0xbe,0x0a,0x43};
    int saved=errno,fd=-1,ok=0;
    unsigned char pem[452],hash[32],derived[20];
    struct stat before,after;
    if(!profile || strcmp(profile,P1_TRUST_PROFILE) || !snapshot || !sha1 || !sha256 || !digest)goto done;
    fd=open(snapshot,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
    if(fd<0 || snapshot_stat(fd,&before) || !S_ISREG(before.st_mode) || (before.st_mode&0222) ||
       before.st_size!=451 || before.st_nlink!=1)goto done;
    size_t used=0;
    while(used<sizeof pem) {
        ssize_t n=read(fd,pem+used,sizeof pem-used);
        if(n<0 && errno==EINTR)continue;
        if(n<0)goto done;
        if(!n)break;
        used+=(size_t)n;
    }
    if(used!=451 || snapshot_stat(fd,&after) || before.st_dev!=after.st_dev || before.st_ino!=after.st_ino ||
       before.st_mode!=after.st_mode || before.st_size!=after.st_size || before.st_nlink!=after.st_nlink ||
       before.st_mtim.tv_sec!=after.st_mtim.tv_sec || before.st_mtim.tv_nsec!=after.st_mtim.tv_nsec ||
       before.st_ctim.tv_sec!=after.st_ctim.tv_sec || before.st_ctim.tv_nsec!=after.st_ctim.tv_nsec ||
       sha256(pem,used,hash)!=hash || memcmp(hash,expected,sizeof hash) || sha1(pem,used,derived)!=derived)goto done;
    memcpy(digest,derived,sizeof derived);ok=1;
 done:
    if(fd>=0)close(fd);
    errno=saved;return ok;
}

int p1_trust_key_reply(const char *profile,struct p1_trust_borrow *borrow,
                      unsigned sid,void *message,unsigned long caller_return,
                      const unsigned char digest[20]) {
    int saved=errno,ok=0;
    uint64_t query[5],status=1,length=20;
    if(!profile || strcmp(profile,P1_TRUST_PROFILE) || !borrow || !digest || !message ||
       !borrow->live || borrow->message!=message || borrow->bytes!=60 || borrow->sid!=P1_TRUST_SID ||
       sid!=P1_TRUST_SID || borrow->owner_pid!=getpid() || borrow->allocation_return!=P1_TRUST_ALLOC_RETURN ||
       caller_return!=P1_TRUST_SYNC_RETURN)goto done;
    memcpy(query,message,sizeof query);
    if(query[0]!=1 || query[1] || query[2] || query[3] || query[4]!=20)goto done;
    memcpy(message,&status,8);memcpy((char *)message+32,&length,8);
    memcpy((char *)message+40,digest,20);
    borrow->live=0;ok=1;
 done:
    errno=saved;return ok;
}
