/* RETIRED prototype: the native runner rejects MENU_CP_EMULATION.
 * 0x1118 is panel-configuration completion (+8=result), not a pixel descriptor.
 * src!=qid cannot distinguish sync/async; the async source is an AP dynamic queue.
 * Sends to Q_IMAGING_FRAME re-enter this sender and are dropped, not delivered.
 * Unvalidated DMM handles and generic success ACKs cannot be used for imaging.
 * Kept as failure evidence only; see ../PROTOCOL-CORRECTIONS.md.
 *
 * Historical, disproven description follows:
 * Virtual-CP emulation -- frame-production increment.
 *
 * Extends the receive+respond increment (cp_emulation v1) with:
 *  - a CP-side frame buffer in the DMM pool (phys 0x41e000000, one 0x80000
 *    slot), filled with a deterministic TEST-PATTERN frame (gradient tagged
 *    with a frame counter -- NOT real CMOS/lens pixels);
 *  - an op2a (DMM handle->physical-segment query) responder on queue
 *    0x9061003c so the AP's ICDT can resolve our frame buffer;
 *  - a frame-ready notification on the imaging frame queue (0x92840747, op
 *    0x200d family, sub-op 0x1118 = frame-done) carrying the buffer handle.
 *
 * The AP PULLS the frame bytes itself via interchip_transfer_async -> icdt.ko
 * -> PCI DMA (established: CP never pushes). So this module only has to keep
 * the bytes readable at the DMM segment and send the notification.
 *
 * Honest limits: the frame is a synthetic test pattern; the imaging session
 * setup handshake (stream config) is NOT yet emulated, so the AP may not be in
 * a state that pulls. This increment proves the produce->notify->op2a->pull
 * machinery end-to-end. Normal exported osal_uipc + memremap APIs only.
 */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

extern int printk(const char *, ...);
extern long osal_reg_public(long);
extern long osal_unreg_public(long);
extern long osal_valloc_msg_wait(u32 qid, void **msg, u32 size, u32 flags);
extern long osal_set_msg_src(void *msg, u32 src);
extern long osal_snd_msg(u32 qid, void *msg);
extern u32 osal_get_msg_src(void *msg);
extern long osal_free_msg(u32 qid, void *msg);
extern void *memremap(u64 phys, u64 size, int flags);
extern void memunmap(void *addr);

#define MEMREMAP_WB 1

/* DMM pool: CP-side frame buffer. The DMM pool is a reserved (memrsv) physical
 * region; slot 0 is ours. CP-side physical segment = pool - 0x400000000. */
#define DMM_POOL_PHYS   0x41e000000ULL
#define DMM_SLOT_SIZE   0x80000u
#define FRAME_BYTES     0x64000u          /* matches the AP's observed pull size */
#define CP_SEG_PHYS     (DMM_POOL_PHYS - 0x400000000ULL)  /* CP-side view of slot 0 */
#define FRAME_HANDLE    0x8001u           /* CP-side buffer handle (bit15 = CP) */

#define Q_IMAGING_FRAME 0x92840747u       /* imaging frame queue (op 0x200d) */
#define Q_DMM_OP2A      0x9061003cu       /* remote DMM op2a query queue */
#define Q_VIRTCP_SOURCE 0x90030001u       /* our (virtual CP) source id in replies */

static u32 recv_count, reply_count, reply_fail, op2a_count, frame_ready_count;
static u8 *frame_buf;                     /* memremap'd DMM slot 0 */
static u32 frame_index;
static long (*sender_handle)(u32, void *);

static void put16(u8 *p, u16 v) { p[0] = (u8)v; p[1] = (u8)(v >> 8); }
static void put32(u8 *p, u32 v) { p[0]=(u8)v; p[1]=(u8)(v>>8); p[2]=(u8)(v>>16); p[3]=(u8)(v>>24); }

/* Fill the frame buffer with a deterministic test pattern: first 16 bytes carry
 * the frame index + a simple checksum; the rest is a per-row gradient that
 * depends on the frame index, so a stale buffer cannot read as a fresh frame. */
static void produce_frame(void)
{
    u32 i;
    if (!frame_buf) return;
    frame_index++;
    for (i = 0; i < FRAME_BYTES; ++i) frame_buf[i] = (u8)(i + frame_index * 31);
    put32(frame_buf, frame_index);
    put32(frame_buf + 4, 0x43504d53);    /* 'CPMS' tag so a reader can identify it */
}

/* op2a responder: reply {802a, status 0, segcount 1, seg addr, len 0x80000}. */
static void answer_op2a(void *req)
{
    u32 reply_qid = osal_get_msg_src(req);
    void *reply = 0;
    u8 *r;
    long rc;
    if (!reply_qid || reply_qid == Q_DMM_OP2A) return;
    rc = osal_valloc_msg_wait(reply_qid, &reply, 40, 1);
    if (rc || !reply) { reply_fail++; return; }
    r = (u8 *)reply;
    { int i; for (i = 0; i < 40; ++i) r[i] = 0; }
    put16(r, 0x802a);                    /* op | 0x8000 */
    put16(r + 2, 0);                     /* status = success */
    put16(r + 8, 1);                     /* segment count = 1 */
    put32(r + 12, FRAME_HANDLE);         /* the handle */
    put32(r + 0x18, (u32)CP_SEG_PHYS);   /* segment address (low) */
    put32(r + 0x1c, (u32)(CP_SEG_PHYS >> 32));  /* segment address (high) */
    put32(r + 0x20, DMM_SLOT_SIZE);      /* segment length */
    osal_set_msg_src(reply, Q_VIRTCP_SOURCE);
    rc = osal_snd_msg(reply_qid, reply);
    if (rc) { osal_free_msg(reply_qid, reply); reply_fail++; }
    else op2a_count++;
    printk("\0016VIRTCP_OP2A: to=%#x seg=%#llx rc=%ld\n", reply_qid,
           (unsigned long long)CP_SEG_PHYS, rc);
}

/* Send a frame-ready notification on the imaging frame queue: {0x200d, 0x1118,
 * frame_handle, frame_index}. The AP's imaging dispatch thread (sub_34f34e8)
 * receives it. */
static void send_frame_ready(void)
{
    void *msg = 0;
    u8 *m;
    long rc;
    if (!frame_buf) return;
    produce_frame();
    rc = osal_valloc_msg_wait(Q_IMAGING_FRAME, &msg, 16, 1);
    if (rc || !msg) { reply_fail++; return; }
    m = (u8 *)msg;
    { int i; for (i = 0; i < 16; ++i) m[i] = 0; }
    put16(m, 0x200d);                    /* cate */
    put16(m + 2, 0x1118);                /* sub-op = frame-done */
    put32(m + 8, FRAME_HANDLE);          /* buffer handle */
    put32(m + 12, frame_index);          /* frame index */
    osal_set_msg_src(msg, Q_VIRTCP_SOURCE);
    rc = osal_snd_msg(Q_IMAGING_FRAME, msg);
    if (rc) { osal_free_msg(Q_IMAGING_FRAME, msg); reply_fail++; }
    else frame_ready_count++;
    printk("\0016VIRTCP_FRAME_READY: idx=%u handle=%#x rc=%ld\n",
           frame_index, FRAME_HANDLE, rc);
}

static long virtual_cp_emu_sender(u32 qid, void *msg)
{
    u32 size = msg ? ((u32 *)msg)[-2] : 0;
    const u8 *b = (const u8 *)msg;
    u32 n = recv_count++;
    u32 w0 = 0;
    if (b && size > 0) w0 = b[0] | (b[1] << 8) | (b[2] << 16) | ((u32)b[3] << 24);

    /* DMM op2a query: resolve our frame buffer's physical segment. */
    if (qid == Q_DMM_OP2A && msg && size >= 40 && (w0 & 0xffff) == 0x2a) {
        answer_op2a(msg);
        return 0;
    }

    /* Imaging frame queue: two AP send patterns (subagent-confirmed).
     *  - sync RPC (send_and_wait): msg_src = a PRIVATE reply queue (!= qid); AP
     *    blocks in osal_rcv_msg_tmo and reads u32 result @reply+0 (0=OK). MUST
     *    answer or appFw hangs.
     *  - async (fire-and-forget): msg_src == qid; the CP later answers on the
     *    imaging queue with sub-op = request|0x1000.
     * Our own sends re-enter us with source==Q_VIRTCP_SOURCE; drop those. */
    if (qid == Q_IMAGING_FRAME && msg) {
        u32 src = osal_get_msg_src(msg);
        u16 sub_op = (u16)((w0 >> 16) & 0xffff);
        printk("\0016VIRTCP_RECV: n=%u qid=%#x size=%u op=%04x sub=%04x src=%#x\n",
               n, qid, size, w0 & 0xffff, sub_op, src);
        if (src == Q_VIRTCP_SOURCE) return 0;   /* our own echo/completion */
        if (src && src != qid) {
            void *reply = 0;
            long rc = osal_valloc_msg_wait(src, &reply, 12, 1);
            if (rc == 0 && reply) {
                u8 *r = (u8 *)reply;
                int i;
                for (i = 0; i < 12; ++i) r[i] = 0;   /* u32 result=0 (OK) @+0 */
                osal_set_msg_src(reply, Q_VIRTCP_SOURCE);
                rc = osal_snd_msg(src, reply);
                if (rc) { osal_free_msg(src, reply); reply_fail++; } else reply_count++;
                printk("\0016VIRTCP_ACK: sub=%04x to=%#x rc=%ld\n", sub_op, src, rc);
            }
            /* 0x118 = vdf_set_panel_out: it is sent as a SYNC rpc here (private
             * reply queue) AND registers a pending frame on the AP (dat_910fa28++).
             * After ACKing it, produce a frame + push the 0x1118 frame-done so the
             * AP's pending sequence advances and it pulls the frame via ICDT. */
            if (sub_op == 0x118) send_frame_ready();
        } else if (src == qid) {
            void *cmp = 0;
            long rc = osal_valloc_msg_wait(qid, &cmp, 16, 1);
            if (rc == 0 && cmp) {
                u8 *c = (u8 *)cmp;
                int i;
                for (i = 0; i < 16; ++i) c[i] = 0;
                put16(c, 0x200d);
                put16(c + 2, sub_op | 0x1000);       /* completion sub-op */
                put32(c + 8, FRAME_HANDLE);          /* buffer handle */
                osal_set_msg_src(cmp, Q_VIRTCP_SOURCE);
                rc = osal_snd_msg(qid, cmp);         /* re-enters us; guard drops */
                if (rc) { osal_free_msg(qid, cmp); reply_fail++; } else reply_count++;
                printk("\0016VIRTCP_COMPLETE: sub=%04x->%04x rc=%ld\n", sub_op, sub_op|0x1000, rc);
            }
            /* A 0x118-family request registers a pending frame (counter++); only
             * then does a 0x1118 frame-done advance a sequence and trigger the
             * AP's ICDT pull. Produce + notify on it. */
            if (sub_op == 0x118) send_frame_ready();
        }
        return 0;
    }

    printk("\0016VIRTCP_RECV: n=%u qid=%#x size=%u op=%04x sub=%04x\n",
           n, qid, size, w0 & 0xffff, (w0 >> 16) & 0xffff);
    return 0;
}

int __attribute__((section(".init.text"))) init_module(void)
{
    long rc;
    frame_buf = memremap(DMM_POOL_PHYS, DMM_SLOT_SIZE, MEMREMAP_WB);
    if (!frame_buf) {
        printk("\0016VIRTCP_REGISTER: memremap of DMM pool %#llx FAILED\n",
               (unsigned long long)DMM_POOL_PHYS);
        return -12; /* ENOMEM */
    }
    produce_frame();
    sender_handle = virtual_cp_emu_sender;
    rc = osal_reg_public((long)&sender_handle);
    printk("\0016VIRTCP_REGISTER: rc=%ld frame_buf=%p (%s)\n", rc, frame_buf,
           rc == 0 ? "virtual-CP emulation (frame-production) registered"
                   : "NOT registered - another module owns the sender");
    if (rc != 0) { memunmap(frame_buf); frame_buf = 0; }
    return rc == 0 ? 0 : (int)rc;
}

void __attribute__((section(".exit.text"))) cleanup_module(void)
{
    osal_unreg_public((long)&sender_handle);
    if (frame_buf) memunmap(frame_buf);
    printk("\0016VIRTCP_EXIT: recv=%u replied=%u op2a=%u frame_ready=%u fail=%u\n",
           recv_count, reply_count, op2a_count, frame_ready_count, reply_fail);
}
