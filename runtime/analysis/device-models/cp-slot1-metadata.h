/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_SLOT1_METADATA_H
#define NATIVE_CP_SLOT1_METADATA_H
#include <stddef.h>
#include <stdint.h>

#define CP_META_SID UINT32_C(0x811006e9)
#define CP_META_SOURCE UINT32_C(0xa5a5a5a5)
#define CP_META_BYTES 20u
struct cp_meta_inputs {
    uint32_t x, y, z, w, t20, input_I;
    uint8_t q, a, alternate, t91;
};
struct cp_meta_cache { uint32_t x,y,z,w,q,a;uint16_t n16; };
enum cp_meta_form { CP_META_MODE, CP_META_PRIMARY, CP_META_ALTERNATE };
struct cp_meta_packet {
    unsigned char *payload;
    size_t size;
    uint32_t source;
    void *lease;
};
/* Success alloc returns one caller-owned exact20B packet with the actual CP
 * allocator source marker; its tail bytes remain allocator backing. Nonzero
 * alloc returns no ownership. send0 transfers ownership (inline retirement is
 * allowed); nonzero send retains caller ownership. release takes the ACTUAL
 * payload/lease descriptor, never &payload. This is an explicit safe repair of
 * the original failed-send pointer mismatch, not byte-identical failure code.
 * release failure retains ownership for retry; callbacks must not retain the
 * descriptor's stack address. Backend/context/code outlive this instance. */
struct cp_meta_io {
    int (*allocate)(void *,uint32_t,size_t,struct cp_meta_packet *);
    int (*send)(void *,uint32_t,const struct cp_meta_packet *);
    int (*release)(void *,uint32_t,const struct cp_meta_packet *);
};
struct cp_meta_result {
    unsigned int attempted,allocated,submitted,allocation_failures,send_failures;
    unsigned int cleanup_failures,cache_committed;
    int first_io_error;
};
struct cp_meta_view { struct cp_meta_cache cache;unsigned int busy,fault,retained; };
struct cp_slot1_metadata;
/* No inferred cache-valid bit or per-request reset. Owner provides authentic
 * cold/history cache; construction does not suppress a changed tuple. */
struct cp_slot1_metadata *cp_meta_create(const struct cp_meta_cache *,const struct cp_meta_io *,void *);
int cp_meta_destroy(struct cp_slot1_metadata *);
/* Writes18bytes only; preserves the actual allocator's last2bytes. */
int cp_meta_format(const struct cp_meta_inputs *,enum cp_meta_form,unsigned char *,size_t);
/* All three attempts/cache transitions follow original normal-return order.
 * Return0 means the sender pass settled, NOT registry delivery or postwork
 * completion. IO failures are in result; original cache still commits after
 * normal cleanup. Safety/invalid-backend faults stop and do NOT commit cache.
 * Neither this API nor submitted count proves a real subscriber consumed it.
 * One writer per instance; destroy requires caller quiescence. */
int cp_meta_publish(struct cp_slot1_metadata *,const struct cp_meta_inputs *,struct cp_meta_result *);
int cp_meta_retry_release(struct cp_slot1_metadata *);
int cp_meta_snapshot(struct cp_slot1_metadata *,struct cp_meta_view *);
#endif
