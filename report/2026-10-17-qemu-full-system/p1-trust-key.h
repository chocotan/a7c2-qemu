#ifndef A7C2_P1_TRUST_KEY_H
#define A7C2_P1_TRUST_KEY_H
#include <stddef.h>
#define P1_TRUST_PROFILE "virtual-p1-pinned-key-v1"
#define P1_TRUST_ASSET "/simulation/p1-trust-key/sony-original.pem"
#define P1_TRUST_SID 0x025906beu
#define P1_TRUST_ALLOC_RETURN 0xabc4ul
#define P1_TRUST_SYNC_RETURN 0xabf4ul
/* A virtual provisioned anchor; no Sony BootROM/SKD hardware-history claim. */
typedef unsigned char *(*p1_trust_hash_fn)(const unsigned char *,size_t,unsigned char *);
struct p1_trust_borrow {
    void *message;
    size_t bytes;
    unsigned sid;
    int owner_pid;
    unsigned long allocation_return;
    int live;
};
/* Read an independent, regular, read-only exact Sony PEM, then derive its SHA1. */
int p1_trust_key_read(const char *profile,const char *snapshot,
                      p1_trust_hash_fn sha1,p1_trust_hash_fn sha256,unsigned char digest[20]);
/* Consume one observed allocation; writes only +0..7/+32..59 on success. */
int p1_trust_key_reply(const char *profile,struct p1_trust_borrow *borrow,
                      unsigned sid,void *message,unsigned long caller_return,
                      const unsigned char digest[20]);
#endif
