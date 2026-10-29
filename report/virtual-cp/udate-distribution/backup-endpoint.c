/* Strict virtual Backup exchange. The transport must supply real backing;
 * the disabled endpoint preserves the original unserved public-message path. */
#define BACKUP_TARGET 0x903e0811u
#define BACKUP_SOURCE 0x003e0811u
#define BACKUP_REQUEST_BYTES 40u
#define BACKUP_REPLY_BYTES 4096u
#define BACKUP_DATA_BYTES 0x15a8f8u
#define BACKUP_INITIAL_FNV64 0x5436a35ff036e6b5UL
#define BACKUP_FROZEN_FNV64 0xa718b3aa73db052aUL

struct backup_backend {
    void *opaque;
    long (*freeze)(void *); /* set primary byte9, then deny every modeled writer */
    long (*read)(void *, u32, void *, u32);
    long (*unlock)(void *);
};
static struct backup_backend backup_backend;
static u32 backup_enabled, backup_busy, backup_faults, backup_frozen;
static u64 backup_generation, backup_readback;
static struct retained_message backup_retained[2];

static long backup_fail(const char *where, long rc)
{
    u32 count = __sync_add_and_fetch(&backup_faults, 1);
    if (count <= 16)
        printk("\0016BACKUP_K_ERROR: stage=%s rc=%ld frozen=%u faults=%u dma_verified=0 capture_verified=0\n",
               where, rc ? rc : -1021, __atomic_load_n(&backup_frozen, __ATOMIC_ACQUIRE), count);
    return rc ? rc : -1021;
}
static void backup_retain(u32 id, void *message)
{
    u32 i;
    for (i = 0; i < 2; ++i) {
        if (!backup_retained[i].message) {
            backup_retained[i].message = message;
            backup_retained[i].id = id;
            break;
        }
    }
    __sync_fetch_and_add(&backup_faults, 1);
    printk("\0016BACKUP_K_RETAIN: id=%#x message=%p overflow=%u frozen=%u\n",
           id, message, i == 2, backup_frozen);
}
static long backup_read_record(u8 suspend, u64 expected, u64 *fingerprint)
{
    u8 bytes[256];
    u32 offset, i;
    u64 hash = 14695981039346656037UL;
    for (offset = 0; offset < BACKUP_DATA_BYTES; offset += sizeof(bytes)) {
        u32 size = BACKUP_DATA_BYTES - offset;
        long rc;
        if (size > sizeof(bytes)) size = sizeof(bytes);
        rc = backup_backend.read(backup_backend.opaque, offset, bytes, size);
        if (rc) return rc;
        if (!offset && (get32(bytes) != 0x04000000u || bytes[9] != suspend ||
                        get32(bytes + 12) != 0x00344b42u ||
                        (u64)get32(bytes + 24) + get32(bytes + 28) != BACKUP_DATA_BYTES))
            return -1021;
        for (i = 0; i < size; ++i) { hash ^= bytes[i]; hash *= 1099511628211UL; }
    }
    if (hash != expected) return -1021;
    *fingerprint = hash;
    return 0;
}

static long backup_sender(u32 qid, void *message)
{
    const u8 *body = message;
    u32 source, stage;
    void *reply = 0;
    long rc;
    const char *where = "allocate";
    if (!backup_enabled) return 0;
    if (!backup_backend.freeze || !backup_backend.read || !backup_backend.unlock)
        return backup_fail("backend-unavailable", -1020);
    if (!message || ((u32 *)message)[-2] != BACKUP_REQUEST_BYTES)
        return backup_fail("request-size", -1021);
    source = osal_get_msg_src(message);
    stage = get32(body + 32);
    if (qid != BACKUP_TARGET || get32(body) != 0x30 || get32(body + 4) != 0 ||
        get32(body + 8) != BACKUP_TARGET || get32(body + 12) != source ||
        (source & 0xffff8000u) != 0x803e0000u || !(source & 0x7fffu) ||
        get32(body + 16) != 1 || get32(body + 20) != 1 ||
        get32(body + 24) != 1 || get32(body + 28) != 1 ||
        (stage != 3 && stage != 0) || get32(body + 36) != 0) {
        if (__atomic_load_n(&backup_faults, __ATOMIC_ACQUIRE) < 16)
            printk("\0016BACKUP_K_REJECT: destination=%#x source=%#x words_le=%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x\n",
                   qid, source, get32(body), get32(body+4), get32(body+8), get32(body+12),
                   get32(body+16), get32(body+20), get32(body+24), get32(body+28), stage, get32(body+36));
        return backup_fail("request-shape", -1021);
    }
    if (__sync_lock_test_and_set(&backup_busy, 1))
        return backup_fail("busy", -1021);
    if (__atomic_load_n(&backup_faults, __ATOMIC_ACQUIRE) || (stage == 3 ? backup_frozen : !backup_frozen)) {
        rc = backup_fail("order-or-latched-fault", -1021);
        __sync_lock_release(&backup_busy);
        return rc;
    }
    rc = osal_valloc_msg_wait(source, &reply, BACKUP_REPLY_BYTES, 1);
    if (rc || !reply) goto failed;
    zero(reply, BACKUP_REPLY_BYTES);
    copy(reply, message, BACKUP_REQUEST_BYTES);
    if (stage == 3) {
        where = "freeze";
        /* A failed freeze may have changed backing; retain its lease as uncertain. */
        __atomic_store_n(&backup_frozen, 1, __ATOMIC_RELEASE);
        rc = backup_backend.freeze(backup_backend.opaque);
        if (rc) goto failed;
        where = "frozen-readback";
        rc = backup_read_record(1, BACKUP_FROZEN_FNV64, &backup_readback);
        if (rc) goto failed;
        put32((u8 *)reply + 32, 1);
        ++backup_generation;
    } else {
        where = "unlock";
        rc = backup_backend.unlock(backup_backend.opaque);
        if (rc) goto failed;
        __atomic_store_n(&backup_frozen, 0, __ATOMIC_RELEASE);
    }
    where = "concurrent-fault";
    if (__atomic_load_n(&backup_faults, __ATOMIC_ACQUIRE)) { rc = -1021; goto failed; }
    osal_set_msg_src(reply, BACKUP_SOURCE);
    where = "reply-send";
    rc = osal_snd_msg(source, reply);
    if (rc) goto failed;
    reply = 0;
    rc = osal_free_msg(qid, message);
    if (rc) backup_retain(qid, message);
    printk("\0016BACKUP_K_REPLY: generation=%llu stage=%u normalized=%u bytes=%u data_bytes=%u frozen=%u readback=%016lx request_free_rc=%ld faults=%u virtual_stage_only=1 dma_verified=0 capture_verified=0\n",
           (unsigned long long)backup_generation, stage, stage == 3 ? 1 : 0,
           BACKUP_REPLY_BYTES, BACKUP_DATA_BYTES, backup_frozen, backup_readback, rc, backup_faults);
    __sync_lock_release(&backup_busy);
    return 0;
failed:
    if (reply) {
        long freed = osal_free_msg(source, reply);
        if (freed) backup_retain(source, reply);
    }
    /* Publish the permanent fault before another caller can acquire the guard. */
    rc = backup_fail(where, rc);
    __sync_lock_release(&backup_busy);
    /* Caller still owns and frees the original request on nonzero return. */
    return rc;
}
