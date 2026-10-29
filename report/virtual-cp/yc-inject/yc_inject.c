/* YC IN1 injection experiment -- feed diagnostic byte buffers into the
 * original av-cam VDT service through its documented cross-chip input
 * (56B 1000:0102 on queue 0x827e073f), substituting for the CP VEF OUT1 peer.
 *
 * Contract (main-verified; see report/virtual-cp/PROTOCOL-CORRECTIONS.md):
 *  - K 1dc570 handler: +2==0x0102, +0x18 (dest type)==0, +0x20 (dest index)<=2,
 *    canonicalized source must equal the registered pin record peer.
 *  - Message: +8 source{0,2,1,0x905a0048}, +0x18 dest{0,1,1,0x827e073f},
 *    +0x28/+0x2c/+0x30 metadata SDS {type,handle,offset}, +0x34=0.
 *  - Metadata = SSYC blob (main header +0xc entry count, +0x10 first entry;
 *    ETRY entries: +0 marker, +4 cate, +0xc payload offset, +0x10 capacity,
 *    +0x14 next) with cate0=ImageSize(0x48), cate1=YcState(8),
 *    cate2=ImageOutTimInfo(0x40, required by the YUV_CONV path).
 *  - Pixel storage = REAL units allocated from the original dmm.ko (op20 on
 *    0x8061003c); never a fabricated handle.
 *  - Unit lifecycle mirrors the real CP: alloc(state 1) -> share(op21) ->
 *    av-cam opens/closes/frees itself. We never op24-open our own units:
 *    a lingering Open makes the flow's final free_unit return DMM status 3
 *    which av-cam maps to err=2 -> LOG_STOP (run-86w_573v).
 *
 * Each submission has its own metadata unit, but all submissions share ONE
 * persistent pixel allocation. No dynamic pixel-retirement fence is proven.
 *
 * Reply handling: the DMM dialog runs sequentially in init_module with
 * msleep polling (yc_survey-proven; callback-chained sends beyond depth 2
 * lose the inline reply -- run-er9vb95m). Late VDT replies (200b:2300 etc.)
 * still arrive via the registered callback and are only logged.
 *
 * Honest limits: default frames are synthetic 1920x1080 luma test patterns;
 * an optional host PNG supplies the same 8-bit luma buffer instead. The
 * YcCompress=2 selects compressed RC format 1 with DCD enabled; the luma
 * bytes are NOT a valid compressed image and this is NOT CMOS/Bayer.
 * Acceptance requires av-cam to actually consume the staged bytes (its
 * logs / flow callbacks / a 200b:2300 notify observed by the observer),
 * not merely successful osal_snd_msg returns.
 */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#include "unit-info.h"

extern int printk(const char *, ...);
extern long osal_reg_msg_queue_cb(u32 qid, void *slot_out, void *cb, void *cookie);
extern long osal_unreg_msg_queue_cb(u32 qid, long slot);
extern long osal_valloc_msg_wait(u32 qid, void **msg, u32 size, u32 flags);
extern long osal_set_msg_src(void *msg, u32 src);
extern long osal_snd_msg(u32 qid, void *msg);
extern long osal_free_msg(u32 qid, void *msg);
extern long osal_msg_size(void *msg);
extern u32 osal_get_msg_src(void *msg);
extern void *memremap(u64 phys, u64 size, int flags);
extern void memunmap(void *addr);
extern void msleep(unsigned int msecs);
extern void *filp_open(const char *name, int flags, unsigned short mode);
extern long kernel_read(void *file, long long offset, void *dst, unsigned long count);
extern int filp_close(void *file, void *owner);

#define MEMREMAP_WB 1

#define Q_VDT_IN        0x827e073fu   /* av-cam VDT service (local queue) */
#define Q_DMM_LOCAL     0x8061003cu   /* original dmm.ko service queue */
static const u32 reply_candidates[4] = { 0x8aa50751u, 0x8aa60751u, 0x8aa70751u, 0x8aa80751u };
static u32 q_reply;
#define SRC_PEER_VEF    0x905a0048u   /* CP VEF OUT1 we substitute for */
#define SRC_FRAME_SYNC  0x80c2019fu   /* frame-sync (vsync) fan-out service; absent in QEMU.
                                         VDT's dispatch routes PURELY on the OSAL source
                                         (K 0x1b9660: src==0x80c2019f -> 0x1dc6e0 ->
                                         0x1ba1d0 -> 0x1bfe28 fires the RSIZE_YUV execute
                                         delegate 0x1d298c). Message body is ignored
                                         (0x1b96d4 zeroes business params). */

#define META_UNIT_TYPE  0xe0b00u      /* metadata unit type: the flow's alloc_unit_share
                                         passes this CONSTANT to op21 Share (K 0x1d3c9c
                                         movz/movk) and dmm.ko Share demands exact type
                                         equality (D 0x8e50-58 -> -3 -> err=1 LOG_STOP,
                                         run-q7glqi7d). Units are 0xf80 in the cacheable
                                         0x424000000 pool (run-dw7rljq8). */
#define PIXEL_UNIT_TYPE 0x643u        /* pixel unit type: 2 MiB units in the same
                                         cacheable pool (survey run-mn0dqmb0). Referenced
                                         from ImageSizeInfo Unit* fields. */
#define DMM_REQ_MAGIC   0x1111u
#define DMM_REQ_SIZE    0xd8u

#define N_FRAMES        3u            /* frames to stream; dmm.ko blocks the next alloc
                                         while a unit is still held (run-o3twx9dn: pumps
                                         never flushed op20#2; run-30c158o_: the free of
                                         unit0 released it), so frames are allocated
                                         SEQUENTIALLY, one live unit at a time. */
#define META_OFF        0x0u
#define PIXEL_OFF       0x1000u
#define FRAME_W         1920u
#define FRAME_H         1080u
static int uncompressed_input;
#define ACTIVE_PIXEL_TYPE (uncompressed_input ? 0x431u : PIXEL_UNIT_TYPE)
/* YcCompress=2 -> 1 byte/px (K 0x1c63e8: N = ((W*H*b)>>2 * M[c])/b, M[2]=4,
 * b=8): 1920*1080 = 2,073,600 B, fits the 2 MiB pixel unit. The RSIZE_YUV
 * acceptance gate (K 0x1d1dc8) requires TargetSize >= the 0304-derived output
 * (1280x720) and TargetSize%1920==0 / %1080==0, so the input must present real
 * UVC work-canvas geometry, NOT the camera's 3:2 sensor geometry; the pixel
 * CONTENT layout for compress=2 is not mapped: it requires hardware DCD,
 * so raw luma can validate transport/dispatch, never pixel conversion. */
/* RDIMG's original M[0]=10 formula requires 2.5*area storage even though
 * the downstream format-0 RC rectangle uses 2*area bytes. Initialize both. */
#define FRAME_BYTES     (FRAME_W * FRAME_H * (uncompressed_input ? 5u : 2u) / 2u)
#define VDT_FMT_NV12_720 0x11u
#define VDT_FMT_NV12_FHD 0x10u

static void put16(u8 *p, u16 v) { p[0]=(u8)v; p[1]=(u8)(v>>8); }
static void put32(u8 *p, u32 v) { p[0]=(u8)v; p[1]=(u8)(v>>8); p[2]=(u8)(v>>16); p[3]=(u8)(v>>24); }
static void put64(u8 *p, u64 v) { put32(p,(u32)v); put32(p+4,(u32)(v>>32)); }

static u32 meta_h[N_FRAMES];
static u64 meta_addr[N_FRAMES];
static u32 meta_len[N_FRAMES];
static u8 *meta_va[N_FRAMES];
static u32 pix_h;            /* ONE persistent pixel unit. K 0x1d42f8 drains unit639
                                outputs, NOT this input. Keeper replacement at 1c300c
                                and each RC job's input Free at 1d2744 are separate;
                                neither alone proves aggregate retirement. Per-frame
                                pixel allocs previously blocked (run-vqiu06ih).
                                Constant neutral/PNG diagnostics do not prove safe
                                dynamic generations; see PIXEL-RETIREMENT.md. */
static u64 pix_addr;
static u32 pix_len;
static u8 *pix_va;
static int input_loaded;
static int neutral_initialized;
static int ownership_observe;
static u16 info_tag;
static int info_pending, info_done;
static int resources_owned; /* Failed diagnostics retain ownership state until VM shutdown. */

static long cb_slot;
static volatile int s_got;            /* incremented per callback invocation */
static volatile int s_out_connected;  /* set when the OUT1 0100/8100 handshake completes */
static u8  s_reply[DMM_REQ_SIZE];     /* last reply body (DMM replies are 0xd8) */

static u16 rd16(const u8 *b) { return b[0] | (b[1] << 8); }
static u32 rd32(const u8 *b) { return b[0] | (b[1] << 8) | ((u32)b[2] << 16) | ((u32)b[3] << 24); }
static u64 rd64(const u8 *b)
{
    u64 v = 0;
    int i;
    for (i = 0; i < 8; i++) v |= (u64)b[i] << (8 * i);
    return v;
}

static u64 input_digest(const u8 *bytes, u32 length)
{
    u64 value = 0xcbf29ce484222325ULL;
    u32 i;
    for (i = 0; i < length; i++) value = (value ^ bytes[i]) * 0x100000001b3ULL;
    return value;
}

/* The isolated initramfs includes this file only for an opt-in host PNG. Read
 * directly into the real DMM unit; reject a truncated/oversized file instead
 * of silently displaying the synthetic frame as if it were the user's PNG. */
static int load_input(void)
{
    if (uncompressed_input) return 0;
    void *file = filp_open("/simulation/yc-input.gray", 0, 0);
    long status = (long)file, count, extra;
    u8 probe;
    int close_rc;
    if (status < 0 && status >= -4095) {
        if (status == -2) { printk("\0016YCIN_INPUT: no PNG staged; synthetic pattern\n"); return 0; }
        printk("\0016YCIN_INPUT: open failed rc=%ld\n", status);
        return -1;
    }
    count = kernel_read(file, 0, pix_va, FRAME_BYTES);
    extra = count == FRAME_BYTES ? kernel_read(file, FRAME_BYTES, &probe, 1) : -1;
    close_rc = filp_close(file, 0);
    if (count != FRAME_BYTES || extra != 0 || close_rc) {
        printk("\0016YCIN_INPUT: rejected bytes=%ld extra=%ld close=%d expected=%u\n",
               count, extra, close_rc, FRAME_BYTES);
        return -1;
    }
    printk("\0016YCIN_INPUT: PNG luma readback bytes=%u fnv64=%016llx\n",
           FRAME_BYTES, (unsigned long long)input_digest(pix_va, FRAME_BYTES));
    return 1;
}

/* cb(msg, cookie) -- ABI main-verified in osal_uipc.ko @0x28e4, invoked with
 * the osal lock released (process context). NOTE: osal_reg_msg_queue_cb may
 * invoke the cb once at registration with an internal/empty message; only
 * trust messages whose op matches expectations. */
/* cb(msg, cookie) -- ABI main-verified in osal_uipc.ko @0x28e4, invoked with
 * the osal lock released (process context). NOTE: osal_reg_msg_queue_cb may
 * invoke the cb once at registration with an internal/empty message; only
 * trust messages whose op matches expectations.
 * Reply messages MUST be freed here: the queue pool is tiny, and unfreed
 * replies exhaust it so the NEXT DMM reply can never be delivered
 * (run-bwik4oez: unit1 op20 got no reply after unit0's three). */
static long vdt_send_enveloped(const u8 *inner, u32 inner_len);
static long dmm_send(u16 op, u32 type, u32 size_or_handle);
static unsigned nv12_consumed;
static void consume_nv12_notification(const u8 *inner)
{
    const u32 expected=1920u*1080u*3u/2u;
    if (!uncompressed_input || rd16(inner+4)!=0x30 || !rd32(inner+8) ||
        rd32(inner+0x18)!=expected || inner[0x1c]!=VDT_FMT_NV12_FHD || nv12_consumed>=3) return;
    u64 address=rd64(inner+0x10);
    if (address<0x400000000ULL || address>0x500000000ULL-expected) return;
    void *pixels=memremap(address,expected,MEMREMAP_WB);
    if (!pixels) {
        printk("\0013YCIN_NV12_READ_FAILED: handle=%#x addr=%#llx\n",rd32(inner+8),(unsigned long long)address);
        return;
    }
    u64 digest=input_digest(pixels,expected);
    memunmap(pixels);
    printk("\0016YCIN_NV12_CONSUMED: seq=%u handle=%#x addr=%#llx bytes=%u format=%#x fnv64=%016llx full_read=1 lifetime=callback-only\n",
        ++nv12_consumed,rd32(inner+8),(unsigned long long)address,expected,inner[0x1c],(unsigned long long)digest);
}

static long yc_reply_cb(void *msg, void *cookie)
{
    u8 *b = (u8 *)msg;
    const u8 *in;
    u32 op, status;
    int i;
    (void)cookie;
    if (!b) return 0;
    /* op28 has its own correlated slot; never overwrite the allocation dialog. */
    long message_bytes = osal_msg_size(msg);
    if (message_bytes >= 2 && rd16(b) == 0x8028) {
        u32 source = osal_get_msg_src(msg);
        struct yc_unit_info info;
        char raw[81];
        const char hex[] = "0123456789abcdef";
        u32 shown = message_bytes > 0x28 ? 0x28 : (u32)message_bytes;
        for (u32 j = 0; j < shown; ++j) {
            raw[j*2] = hex[b[j] >> 4]; raw[j*2+1] = hex[b[j] & 15];
        }
        raw[shown*2] = 0;
        int pending = __atomic_load_n(&info_pending, __ATOMIC_ACQUIRE);
        int valid = pending && !yc_info_decode(b, (unsigned long)message_bytes, source,
                                              info_tag, ACTIVE_PIXEL_TYPE, pix_len, &info);
        if (valid) {
            printk("\0016YCIN_OWNERSHIP: tag=%#x handle=%#x addr=%#llx capacity=%#x type=%#x extents=%u refs=%u opens=%u source=%#x bytes=%ld raw=%s retirement_verified=0\n",
                   info_tag, pix_h, (unsigned long long)pix_addr, pix_len, info.type,
                   info.extents, info.references, info.opens, source, message_bytes, raw);
            __atomic_store_n(&info_pending, 0, __ATOMIC_RELEASE);
            __atomic_store_n(&info_done, 1, __ATOMIC_RELEASE);
        } else {
            printk("\0013YCIN_OWNERSHIP_REJECTED: source=%#x bytes=%ld pending=%d expected_tag=%#x raw=%s\n",
                   source, message_bytes, pending, info_tag, raw);
        }
        osal_free_msg(q_reply, msg);
        return 0;
    }
    if (message_bytes < 8) {
        printk("\0013YCIN_REPLY_REJECTED: bytes=%ld too short\n", message_bytes);
        osal_free_msg(q_reply, msg);
        return 0;
    }
    /* VDT messages may arrive with the Dataflow envelope (marker 0xa0a0a0a0 at
     * +4): COMP replies and the OUT1 0100 connect request are enveloped
     * (run-klidlryw); DMM replies and pin data are not. */
    in = (b[4] == 0xa0 && b[5] == 0xa0 && b[6] == 0xa0 && b[7] == 0xa0) ? b + 0x18 : b;
    op = rd16(in);
    status = rd16(in + 2);
    if (op >= 0x8020 && op <= 0x802a) {
        for (i = 0; i < (int)DMM_REQ_SIZE; i++)
            s_reply[i] = i < message_bytes ? b[i] : 0;
        s_got++;
        printk("\0016YCIN_REPLY: op=%04x status=%d handle=%#x addr=%#llx len=%#x\n",
               op, (int)(short)status, rd32(b + 0xc), rd64(b + 0x18), rd32(b + 0x20));
    } else if (op == 0x1000 && rd16(in + 2) == 0x0100) {
        /* VDT's OUT1 connect request to us (enveloped): answer 1000:8100
         * (inner len 0x30, copy both endpoint quads, u32@+0x28/+0x2c=0),
         * also enveloped (K 0x1d8a50-0x1d8a84; 0x958d4 sets pin state 0). */
        u8 r[0x30];
        printk("\0016YCIN_VDT_REPLY: OUT1 connect request 1000:0100\n");
        for (i = 0; i < 0x30; i++) r[i] = 0;
        put16(r + 0x00, 0x1000);
        put16(r + 0x02, 0x8100);
        put16(r + 0x04, 0x30);
        put16(r + 0x06, 1);
        for (i = 0x08; i < 0x28; i++) r[i] = in[i];   /* copy src+dst quads */
        printk("\0016YCIN_VDT_REPLY: 8100 send rc=%ld\n", vdt_send_enveloped(r, 0x30));
        s_out_connected = 1;
    } else if (op == 0x1000 && rd16(in + 2) == 0x0102 && in != b) {
        /* Converted-output delivery from VDT OUT1 (enveloped 1000:0102; SDS at
         * in+0x28 = {type 0xe0b00, meta handle, offset}). Just log it: the pixel
         * unit is persistent and reused for the next frame. */
        printk("\0016YCIN_VDT_REPLY: OUT1 frame delivery, meta h=%#x (frame consumed by flow)\n",
               rd32(in + 0x2c));
    } else {
        /* VDT replies/notifies: 1301/1304/1305 COMP, 2300 frame notify, ... */
        if (op==0x200b && rd16(in+2)==0x2300 && in!=b && rd16(b+8)==1 &&
            rd16(b+0xa)>=0x48 && rd32(b+0x10)>=0x48 && rd32(b+0xc)==0x18)
            consume_nv12_notification(in);
        printk("\0016YCIN_VDT_REPLY: op=%04x:%04x +4=%04x env=%d\n",
               op, rd16(in + 2), rd16(in + 4), in != b);
        u32 length=rd16(in+4);
        if (length>0x38) length=0x38;
        for (u32 offset=0;offset+16<=length;offset+=16)
            printk("\0016YCIN_VDT_DUMP: in+%02x %08x %08x %08x %08x\n",offset,
                rd32(in+offset),rd32(in+offset+4),rd32(in+offset+8),rd32(in+offset+12));
    }
    osal_free_msg(q_reply, msg);
    return 0;
}

/* av-cam's own 0xd8/0x1111 DMM protocol (K 0x2781e0/0x278eec wrappers):
 * op20 Alloc: +4=type, +0xc=size; others: +4=type, +8=handle;
 * +0x14 u16 0x1111 magic. Reply: op u16@0, status s16@2, segs u16@8,
 * handle u32@0xc, seg0 u64@0x18, len u32@0x20. Replies are sized by the
 * original opcode/extent count, NOT by the request size; op28 is 0x28 bytes. */
static long dmm_send(u16 op, u32 type, u32 size_or_handle)
{
    void *req = 0;
    u8 *r;
    long rc;
    int i;

    rc = osal_valloc_msg_wait(Q_DMM_LOCAL, &req, DMM_REQ_SIZE, 1);
    if (rc || !req) { printk("\0016YCIN_FAIL: dmm valloc rc=%ld\n", rc); return rc ? rc : -1024; }
    r = (u8 *)req;
    for (i = 0; i < (int)DMM_REQ_SIZE; ++i) r[i] = 0;
    put16(r, op);
    put32(r + 4, type);
    if (op == 0x20)
        put32(r + 0xc, size_or_handle);  /* size */
    else
        put32(r + 8, size_or_handle);    /* handle */
    put16(r + 0x14, op == 0x28 ? info_tag : DMM_REQ_MAGIC);
    put16(r + 0x16, 0);
    osal_set_msg_src(req, q_reply);
    rc = osal_snd_msg(Q_DMM_LOCAL, req);
    printk("\0016YCIN_OP: op=%02x type=%#x arg=%#x send rc=%ld\n", op, type, size_or_handle, rc);
    if (rc) osal_free_msg(Q_DMM_LOCAL, req);
    return rc;
}

static void build_metadata_and_frame(u32 idx)
{
    u8 *m = meta_va[idx];
    u8 *p = pix_va;
    u32 x, y;
    { u32 i; for (i = 0; i < 0x600; ++i) m[i] = 0; }
    m[0]='S'; m[1]='S'; m[2]='Y'; m[3]='C';
    put32(m + 0x0c, 4);
    put32(m + 0x10, 0x20);
    m[0x20]='E'; m[0x21]='T'; m[0x22]='R'; m[0x23]='Y';
    put32(m + 0x24, 0);
    put32(m + 0x2c, 0x100);
    put32(m + 0x30, 0x48);
    put32(m + 0x34, 0x40);
    m[0x40]='E'; m[0x41]='T'; m[0x42]='R'; m[0x43]='Y';
    put32(m + 0x44, 1);
    put32(m + 0x4c, 0x148);
    put32(m + 0x50, 8);
    put32(m + 0x54, 0x60);
    /* cate=2 ImageOutTimInfo, payload 0x40 @0x150: required by the YUV_CONV path
     * (K 0x1d44e8 -> 942ec; missing entry -> error GetEntry_ImageOutTimInfo +
     * LOG_STOP). Zero-filled first probe; field values pending contract work. */
    m[0x60]='E'; m[0x61]='T'; m[0x62]='R'; m[0x63]='Y';
    put32(m + 0x64, 2);
    put32(m + 0x6c, 0x150);
    put32(m + 0x70, 0x40);
    put32(m + 0x74, 0x80);
    /* cate=5 CameraInfo, payload 0x3a8 @0x190: WITHOUT it the frame takes the
     * thumbnail path and the RC/UVC conversion step never runs (run-icq94ctv:
     * only RDSTP+RDIMG copy, no SA/YUV_CONV, no 2300). The missing-branch
     * defaults (K 0x1d9bcc/0x1db5cc: 60, 1) are written to +0x17c/+0x180 so
     * present-vs-missing behaves identically on the pin path. */
    m[0x80]='E'; m[0x81]='T'; m[0x82]='R'; m[0x83]='Y';
    put32(m + 0x84, 5);
    put32(m + 0x8c, 0x190);
    put32(m + 0x90, 0x3a8);
    put32(m + 0x94, 0);
    put32(m + 0x190 + 0x17c, 60);
    put32(m + 0x190 + 0x180, 1);
    {
        u8 *I = m + 0x100;
        put32(I + 0x00, ACTIVE_PIXEL_TYPE); /* original DMM pixel allocation */
        put32(I + 0x04, pix_h);
        put64(I + 0x08, pix_addr);
        put64(I + 0x10, pix_len);
        put32(I + 0x18, 0);                  /* UnitDataOffset: pixels at unit start */
        /* ImageAttach/DataSite/Aspect/IibNumber/YcCompress(0=plain RC format)/BitDepth(8)/
         * Transfer/Placement/Content/Scan all 0: first probe values. */
        I[0x20] = uncompressed_input ? 0 : 2; /* raw diagnostic is not compressed YC */
        I[0x21] = 0;                          /* YcBitDepth: 8-bit */
        put16(I + 0x2a, FRAME_W);             /* RecordSize X/Y */
        put16(I + 0x2c, FRAME_H);
        put16(I + 0x2e, FRAME_W);             /* CanvasSize X/Y */
        put16(I + 0x30, FRAME_H);
        put16(I + 0x36, FRAME_W);             /* ValidSize (offsets 0) */
        put16(I + 0x38, FRAME_H);
        put16(I + 0x3e, FRAME_W);             /* TargetSize (offsets 0) */
        put16(I + 0x40, FRAME_H);
        /* YcState @0x148: YRange, Colorimetry, ChromaPhase, Scanline, CP, Author, Bits, Valid */
        m[0x148] = 0; m[0x149] = 0; m[0x14a] = 0; m[0x14b] = 1;
        m[0x14c] = 0; m[0x14d] = 4; m[0x14e] = 8; m[0x14f] = 0;
    }
    if (uncompressed_input) {
        /* No post-publication stores, even of identical bytes: input retirement is unproven. */
        if (!neutral_initialized) {
            for (x = 0; x < FRAME_BYTES; ++x) p[x] = 128;
            neutral_initialized = 1;
        }
        printk("\0016YCIN_UNCOMPRESSED: bytes=%u fnv64=%016llx component_order_unverified=1\n",
               FRAME_BYTES, (unsigned long long)input_digest(p, FRAME_BYTES));
    } else if (!input_loaded) {
        for (y = 0; y < FRAME_H; ++y)
            for (x = 0; x < FRAME_W; ++x)
                p[y * FRAME_W + x] = (u8)(x / 8 + y + idx * 30);
        p[0]='Y'; p[1]='C'; p[2]='I'; p[3]='N';
        p[4]='F'; p[5]=(u8)('0'+idx);
    }
}

/* PIN_CONNECT = 1000:0100, 40B inner frame to the same VDT queue (contract
 * closed against av-cam; main byte-verified: K 0x953f8/0x95680/0x9581c/0x95810).
 * Establishes the VEF OUT1 -> VDT IN1 topology edge that the 1000:0102 pin
 * data requires (vdt_pin.cpp: "Received PIN without PIN_CONNECT!").
 * Wire order per endpoint is {type,dir,index,SID}. The 8100 COMP goes to the
 * frame's source SID (0x905a0048), not to us -- expected; verify via ulog. */
static long yc_send_pin_connect(void)
{
    void *msg = 0;
    u8 *b;
    long rc = osal_valloc_msg_wait(Q_VDT_IN, &msg, 40, 1);
    if (rc || !msg) return rc ? rc : -1024;
    b = msg;
    { int i; for (i = 0; i < 40; ++i) b[i] = 0; }
    put16(b + 0x00, 0x1000);
    put16(b + 0x02, 0x0100);
    put16(b + 0x04, 40);
    put16(b + 0x06, 1);
    put32(b + 0x08, 0); put32(b + 0x0c, 2); put32(b + 0x10, 1); put32(b + 0x14, SRC_PEER_VEF);
    put32(b + 0x18, 0); put32(b + 0x1c, 1); put32(b + 0x20, 1); put32(b + 0x24, Q_VDT_IN);
    osal_set_msg_src(msg, q_reply);
    rc = osal_snd_msg(Q_VDT_IN, msg);
    printk("\0016YCIN_PIN_CONNECT: 1000:0100 rc=%ld\n", rc);
    return rc;
}

/* 200b:0304 set-output-format, layout from libInfraStreamingUsb+0x11104:
 * {200b,0304,0028,0001, notifyQ:u32@+8, u8@+0xc, format:u8@+0xd, ... u8@+0x10, 1@+0x11}.
 * Sent BEFORE the frames so the VDT flow has a configured output; the reply
 * (200b:1304) and any 200b:2300 notify arrive on our queue. */
static long yc_send_set_format(void)
{
    u8 b[0x28];
    long rc;
    { int i; for (i = 0; i < 0x28; ++i) b[i] = 0; }
    put16(b + 0x00, 0x200b);
    put16(b + 0x02, 0x0304);
    put16(b + 0x04, 0x28);
    put16(b + 0x06, 1);
    put32(b + 0x08, q_reply);          /* notify destination (real USB service is idle here) */
    b[0x0c] = 0;
    b[0x0d] = uncompressed_input ? VDT_FMT_NV12_FHD : VDT_FMT_NV12_720;
    b[0x10] = 0;
    b[0x11] = 1;
    rc = vdt_send_enveloped(b, 0x28);
    printk("\0016YCIN_SETFMT: 200b:0304 fmt=%#x rc=%ld\n", b[0x0d], rc);
    return rc;
}

/* Frame-sync notification: drives the RSIZE_YUV execute delegate. Sent after
 * each frame (the frame's processing up to the RSIZE_YUV enqueue runs
 * synchronously inside our 0102 send). */
static long yc_send_frame_sync(void)
{
    void *msg = 0;
    u8 *b;
    long rc = osal_valloc_msg_wait(Q_VDT_IN, &msg, 16, 1);
    int i;
    if (rc || !msg) return rc ? rc : -1024;
    b = msg;
    for (i = 0; i < 16; ++i) b[i] = 0;
    osal_set_msg_src(msg, SRC_FRAME_SYNC);
    rc = osal_snd_msg(Q_VDT_IN, msg);
    printk("\0016YCIN_SYNC: frame-sync notify rc=%ld\n", rc);
    return rc;
}

static long yc_send_input(u32 idx)
{
    void *msg = 0;
    u8 *b;
    long rc = osal_valloc_msg_wait(Q_VDT_IN, &msg, 56, 1);
    if (rc || !msg) return rc ? rc : -1024;
    b = msg;
    { int i; for (i = 0; i < 56; ++i) b[i] = 0; }
    put16(b + 0x00, 0x1000);
    put16(b + 0x02, 0x0102);
    put32(b + 0x08, 0); put32(b + 0x0c, 2); put32(b + 0x10, 1); put32(b + 0x14, SRC_PEER_VEF);
    put32(b + 0x18, 0); put32(b + 0x1c, 1); put32(b + 0x20, 1); put32(b + 0x24, Q_VDT_IN);
    put32(b + 0x28, META_UNIT_TYPE);
    put32(b + 0x2c, meta_h[idx]);
    put32(b + 0x30, META_OFF);
    put32(b + 0x34, 0);
    osal_set_msg_src(msg, q_reply);
    return osal_snd_msg(Q_VDT_IN, msg);
}

/* Dataflow envelope (K 0x947e8-0x948c8 builds it; 0x96984-0x9699c detects the
 * 0xa0a0a0a0 marker at wire +4; GetReplyId 0x94b78 reads the reply queue from
 * the envelope for type-1 messages and FAILS (-0x1e) for bare messages --
 * which is why bare sends log 'cannot send response(err=0xFFFFFFE0)' and why
 * REQUEST_CONNECT with reply_id==0 was rejected with ERR_PARAM (K 0x95268
 * cbz). Layout: +0 u32 reply queue, +4 u32 0xa0a0a0a0, +8 u16 type=1,
 * +0xa u16 total, +0xc u32 inner offset=0x18, +0x10 u32 total, +0x14 u32 0,
 * +0x18 inner. Statically derived, run-verified pending. */
static long vdt_send_enveloped(const u8 *inner, u32 inner_len)
{
    void *msg = 0;
    u8 *b;
    u32 total = 0x18 + inner_len;
    long rc = osal_valloc_msg_wait(Q_VDT_IN, &msg, total, 1);
    int i;
    if (rc || !msg) return rc ? rc : -1024;
    b = msg;
    for (i = 0; i < (int)total; ++i) b[i] = 0;
    put32(b + 0x00, q_reply);            /* Dataflow reply_id */
    put32(b + 0x04, 0xa0a0a0a0u);
    put16(b + 0x08, 1);                  /* Dataflow type */
    put16(b + 0x0a, (u16)total);
    put32(b + 0x0c, 0x18);               /* inner offset */
    put32(b + 0x10, total);
    for (i = 0; i < (int)inner_len; ++i) b[0x18 + i] = inner[i];
    osal_set_msg_src(msg, q_reply);
    return osal_snd_msg(Q_VDT_IN, msg);
}

/* 200b:0301 SET_OUTPUT_PIN_FORMAT (K 0x1d9df0-0x1d9e40): u32@+8=0x101
 * (REC_MAIN = YC OUT1), u8@+0xc=0 (60P), u16@+0x10=width, u16@+0x12=height.
 * The OUT1 pin format must MATCH the input (320x240/60P) or the flow builder
 * takes the plain-resize branch (K 0x1e4f24) instead of the UVC converter
 * branch. K reads at most +0x13; send 0x28 zero-padded (original client
 * length not closed -- noted in the contract doc). */
static long yc_send_out_pin_format(void)
{
    u8 b[0x28];
    long rc;
    { int i; for (i = 0; i < 0x28; ++i) b[i] = 0; }
    put16(b + 0x00, 0x200b);
    put16(b + 0x02, 0x0301);
    put16(b + 0x04, 0x28);
    put16(b + 0x06, 1);
    put32(b + 0x08, 0x101);            /* REC_MAIN: YC OUT1 */
    b[0x0c] = 0;                       /* 60P */
    put16(b + 0x10, FRAME_W);
    put16(b + 0x12, FRAME_H);
    rc = vdt_send_enveloped(b, 0x28);
    printk("\0016YCIN_OUTFMT: 200b:0301 %ux%u rc=%ld\n", FRAME_W, FRAME_H, rc);
    return rc;
}

/* 1000:0001 REQUEST_CONNECT for the OUT1 edge (K 0x1d7e98-0x1d7eec):
 * source@+8 = {0,2,1,0x827e073f} (VDT YC OUT1), destination@+0x18 =
 * {0,1,0,our queue}. VDT then sends US 1000:0100; we must answer 1000:8100
 * (K 0x1d8a50-0x1d8a84; 0x958d4 sets pin state 0 = connected). */
static long yc_send_request_connect(void)
{
    u8 b[0x28];
    long rc;
    { int i; for (i = 0; i < 0x28; ++i) b[i] = 0; }
    put16(b + 0x00, 0x1000);
    put16(b + 0x02, 0x0001);
    put16(b + 0x04, 0x28);
    put16(b + 0x06, 2);                /* original connect requests use kind=2 (A 0x3511230) */
    put32(b + 0x08, 0); put32(b + 0x0c, 2); put32(b + 0x10, 1); put32(b + 0x14, Q_VDT_IN);
    put32(b + 0x18, 0); put32(b + 0x1c, 1); put32(b + 0x20, 0); put32(b + 0x24, q_reply);
    rc = vdt_send_enveloped(b, 0x28);
    printk("\0016YCIN_REQCONN: 1000:0001 rc=%ld\n", rc);
    return rc;
}

/* 200b:0305 UVC streaming enable (K 0x1dc424: payload u8@+8 in {0,1}, requires
 * a prior successful 0304; K 0x1ba248-0x1ba274 sets the flow streaming flag).
 * Real client (libInfraStreamingUsb U 0x11324-0x1137c): {200b,0305,0010,+6=1,
 * u8@+8=1}. */
static long yc_send_uvc_enable(void)
{
    u8 b[0x10];
    long rc;
    { int i = 0; for (i = 0; i < 0x10; ++i) b[i] = 0; }
    put16(b + 0x00, 0x200b);
    put16(b + 0x02, 0x0305);
    put16(b + 0x04, 0x10);
    put16(b + 0x06, 1);
    b[0x08] = 1;                       /* streaming on */
    rc = vdt_send_enveloped(b, 0x10);
    printk("\0016YCIN_UVC: 200b:0305 enable rc=%ld\n", rc);
    return rc;
}

/* wait for a DMM reply with the EXPECTED op; other ops (pump replies) are
 * consumed and ignored. DMM defers some replies (2nd concurrent alloc:
 * run-30c158o_) and flushes them when the NEXT request arrives -- so after
 * each slice without the expected reply, PUMP with a harmless op2a on the
 * last good handle. Budget in slices; one slice ~= 0.93s guest under icount. */
static int wait_for_op(u16 want_op, u32 pump_handle, int slices)
{
    int i;
    for (i = 0; i < slices; i++) {
        unsigned waited = 0;
        while (!s_got && waited < 50) {
            msleep(10);
            waited += 10;
        }
        if (s_got) {
            u16 op = rd16(s_reply);
            s_got = 0;
            if (op == want_op) return 1;
            printk("\0016YCIN_PUMP: ignored reply op=%04x while waiting %04x\n", op, want_op);
            continue;
        }
        if (pump_handle) {
            printk("\0016YCIN_PUMP: kick op2a h=%#x (waiting %04x)\n", pump_handle, want_op);
            dmm_send(0x2a, 0, pump_handle);
        }
    }
    return 0;
}

static void observe_ownership(u16 tag)
{
    if (!ownership_observe) return;
    info_tag = tag;
    __atomic_store_n(&info_done, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&info_pending, 1, __ATOMIC_RELEASE);
    printk("\0016YCIN_OWNERSHIP_REQUEST: tag=%#x handle=%#x addr=%#llx capacity=%#x type=%#x\n",
           tag, pix_h, (unsigned long long)pix_addr, pix_len, ACTIVE_PIXEL_TYPE);
    long sent = dmm_send(0x28, ACTIVE_PIXEL_TYPE, pix_h);
    if (!sent) for (unsigned int n = 0; n < 100 && !__atomic_load_n(&info_done, __ATOMIC_ACQUIRE); ++n)
        msleep(10);
    if (sent || !__atomic_load_n(&info_done, __ATOMIC_ACQUIRE))
        printk("\0013YCIN_OWNERSHIP_FAILED: tag=%#x send=%ld reason=no-validated-reply retirement_verified=0\n", tag, sent);
    __atomic_store_n(&info_pending, 0, __ATOMIC_RELEASE);
}

/* VFC tick: av-cam's frame counter lives in its own BSS (KVA base
 * 0xffffffc001000000 + raw 0xba1cd4, writer K 0x1b7690 / reader 0x1b7868).
 * In QEMU nothing advances it (no sensor vsync), and the RSIZE_YUV execute
 * gate requires a 24-bit diff in [1,0x7ffffe] between the current VFC and the
 * module's cached prevVFC (K 0x1d298c). We tick it per frame -- this
 * substitutes the sensor's frame-sync signal, it does NOT fake any conversion
 * result; the RC/SA pipeline still runs (or fails) on its own merits. */
#define AV_CAM_KVA      0xffffffc001000000ULL
#define VFC_SLOT        (AV_CAM_KVA + 0xba1cd4ULL)
static void vfc_tick(u32 v)
{
    volatile u32 *slot = (volatile u32 *)(u64)VFC_SLOT;
    slot[0] = v;            /* VFC */
    /* +4/+8/+0xc left as-is: updater never runs in this guest (enable flag
     * 0xba1cd0 stays 0), and the RC gate only diffs slot[0]. */
}

/* Allocate one unit of the given type, wait for each reply, resolve its real
 * segment. */
static int alloc_unit(u32 type, u32 *handle, u64 *addr, u32 *len, u32 pump)
{
    s_got = 0;
    if (dmm_send(0x20, type, 0x80000)) return -1;
    if (!wait_for_op(0x8020, pump, 40) || (short)rd16(s_reply + 2) != 0) {
        printk("\0016YCIN_DMM: op20 type=%#x FAILED status=%d\n",
               type, (int)(short)rd16(s_reply + 2));
        return -1;
    }
    *handle = rd32(s_reply + 0xc);
    resources_owned = 1;

    s_got = 0;
    if (dmm_send(0x21, type, *handle)) return -1;
    if (!wait_for_op(0x8021, 0, 20) || (short)rd16(s_reply + 2) != 0) {
        printk("\0016YCIN_DMM: op21 type=%#x FAILED status=%d\n",
               type, (int)(short)rd16(s_reply + 2));
        return -1;
    }

    s_got = 0;
    if (dmm_send(0x2a, 0, *handle)) return -1;
    if (!wait_for_op(0x802a, 0, 20) || (short)rd16(s_reply + 2) != 0) {
        printk("\0016YCIN_DMM: op2a type=%#x FAILED status=%d\n",
               type, (int)(short)rd16(s_reply + 2));
        return -1;
    }
    {
        u32 count = rd16(s_reply + 8), segment;
        u64 total = 0, first = 0;
        if (!count || count > (DMM_REQ_SIZE - 0x18) / 0x10) return -1;
        for (segment = 0; segment < count; ++segment) {
            u64 start = rd64(s_reply + 0x18 + segment * 0x10);
            u32 bytes = rd32(s_reply + 0x20 + segment * 0x10);
            printk("\0016YCIN_SEGMENT: type=%#x index=%u count=%u addr=%#llx len=%#x\n",
                   type, segment, count, (unsigned long long)start, bytes);
            if (!segment) first = start;
            if (!bytes || start != first + total || start < 0x400000000ULL ||
                start >= 0x500000000ULL || bytes > 0x500000000ULL - start ||
                total + bytes > 0xffffffffULL) return -1;
            total += bytes;
        }
        *addr = first;
        *len = (u32)total;
    }
    printk("\0016YCIN_DMM: type=%#x handle=%#x addr=%#llx len=%#x\n",
           type, *handle, *addr, *len);
    return 0;
}

static int start_injection(void)
{
    long rc = -1018;
    u32 idx;
    unsigned int i;

    {
        void *mode = filp_open("/simulation/yc-input-uncompressed", 0, 0);
        long status = (long)mode;
        if (status < 0 && status >= -4095) {
            if (status != -2) return -1023;
        } else {
            if (filp_close(mode, 0)) return -1023;
            uncompressed_input = 1;
        }
        printk("\0016YCIN_SOURCE_MODE: uncompressed=%d pixel_type=%#x bytes=%u\n",
               uncompressed_input, ACTIVE_PIXEL_TYPE, FRAME_BYTES);
    }
    {
        void *mode = filp_open("/simulation/yc-ownership-observe", 0, 0);
        if ((u64)mode < (u64)-4095 && mode) {
            filp_close(mode, 0);
            if (!uncompressed_input) return -1024;
            ownership_observe = 1;
        }
    }

    cb_slot = 0;
    q_reply = 0;
    for (i = 0; i < 4 && !q_reply; ++i) {
        rc = osal_reg_msg_queue_cb(reply_candidates[i], &cb_slot, yc_reply_cb, 0);
        printk("\0016YCIN_REGISTER: qid=%#x rc=%ld\n", reply_candidates[i], rc);
        if (!rc) q_reply = reply_candidates[i];
    }
    if (!q_reply) return (int)rc;

    rc = yc_send_pin_connect();
    if (rc) return (int)rc;
    rc = yc_send_set_format();
    if (rc) return (int)rc;
    /* Output side so the flow builder takes the converter branch
     * (K 0x1b9c04: OUT1 unconnected -> FREE_PIN; UVC flag + matching pin
     * format -> FLOW_READ_STP_READ_IMAGE_RC_UVC which constructs YUV_CONV):
     * 0301 sets OUT1 pin format = input (320x240/60P), REQUEST_CONNECT
     * connects OUT1 to our queue, VDT's 0100 is answered 8100 by the reply
     * callback, then 0305 enables UVC streaming. */
    rc = yc_send_out_pin_format();
    if (rc) return (int)rc;
    rc = yc_send_request_connect();
    if (rc) return (int)rc;
    {
        unsigned waited = 0;
        while (!s_out_connected && waited < 2000) {   /* ~=30s guest under icount */
            msleep(20);
            waited += 20;
        }
        printk("\0016YCIN_OUT1: connected=%d waited=%ums\n", s_out_connected, waited);
        /* continue anyway: the flow decision is re-evaluated per frame, and
         * the ulog will show which branch was taken */
    }
    rc = yc_send_uvc_enable();
    if (rc) return (int)rc;

    /* Sequential streaming: fresh META unit per frame (the flow frees it right
     * after consuming, which paces the next alloc), ONE persistent pixel unit. */
    if (alloc_unit(ACTIVE_PIXEL_TYPE, &pix_h, &pix_addr, &pix_len, 0)) return -1020;
    if (pix_addr < 0x400000000ULL || pix_addr >= 0x500000000ULL ||
        pix_len > 0x500000000ULL - pix_addr || pix_len < FRAME_BYTES) {
        printk("\0016YCIN_MAP: REFUSED pixel addr=%#llx len=%#x\n", pix_addr, pix_len);
        return -1021;
    }
    pix_va = memremap(pix_addr, pix_len, MEMREMAP_WB);
    printk("\0016YCIN_MAP: pixel va=%p addr=%#llx len=%#x\n", pix_va, pix_addr, pix_len);
    if (!pix_va) return -1022;
    input_loaded = load_input();
    if (input_loaded < 0) return -1023;
    observe_ownership(0x4c01);
    for (idx = 0; idx < N_FRAMES; ++idx) {
        if (alloc_unit(META_UNIT_TYPE, &meta_h[idx], &meta_addr[idx], &meta_len[idx],
                       meta_h[0])) return -1020;
        if (meta_addr[idx] < 0x400000000ULL || meta_addr[idx] >= 0x500000000ULL ||
            meta_len[idx] > 0x500000000ULL - meta_addr[idx] || meta_len[idx] < 0x600) {
            printk("\0016YCIN_MAP: REFUSED frame=%u meta=%#llx/%#x\n",
                   idx, meta_addr[idx], meta_len[idx]);
            return -1021;
        }
        meta_va[idx] = memremap(meta_addr[idx], meta_len[idx], MEMREMAP_WB);
        printk("\0016YCIN_MAP: frame=%u meta_va=%p\n", idx, meta_va[idx]);
        if (!meta_va[idx]) return -1022;
        build_metadata_and_frame(idx);
        vfc_tick(idx + 1);
        {
            /* Readback: the write must be visible in the same mapping av-cam uses. */
            const u8 *v = meta_va[idx];
            printk("\0016YCIN_VERIFY: frame=%u blob[0..7]=%02x %02x %02x %02x %02x %02x %02x %02x\n",
                   idx, v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
            if (v[0] != 'S' || v[1] != 'S' || v[2] != 'Y' || v[3] != 'C') {
                printk("\0016YCIN_VERIFY: SSYC NOT readable after write; aborting injection\n");
                return -1023;
            }
        }
        rc = yc_send_input(idx);
        printk("\0016YCIN_SEND: 1000:0102 frame=%u meta=%#x pix=%#x rc=%ld (rc=0 only means queued; watch av-cam logs)\n",
               idx, meta_h[idx], pix_h, rc);
        if (rc) return (int)rc;
        rc = yc_send_frame_sync();
        if (rc) return (int)rc;
        /* No explicit free-wait: dmm.ko blocks the next same-type alloc until the
         * flow frees the previous frame's unit (run-30c158o_/run-o3twx9dn), which
         * paces frames to the flow's consumption. The op20 wait budget with pump
         * kicks covers the deferral. */
    }
    if (uncompressed_input) {
        /* Sensor timing continues after finite frame submission; original flow
         * scheduling decides whether completed RC output can enter YUV. */
        for (idx=0;idx<8;++idx) {
            msleep(40);
            vfc_tick(N_FRAMES+idx+1);
            rc=yc_send_frame_sync();
            printk("\0016YCIN_DRAIN_CLOCK: tick=%u rc=%ld\n",N_FRAMES+idx+1,rc);
            if (rc) return (int)rc;
        }
    }
    observe_ownership(0x4c02);
    printk("\0016YCIN_INIT_DONE: %u frames queued\n", (unsigned)N_FRAMES);
    return 0;   /* stay resident: reply queue + mappings stay alive */
}

int __attribute__((section(".init.text"))) init_module(void)
{
    int rc = start_injection();
    long detached = 0;
    if (!rc) return 0;
    /* Failed init is not followed by cleanup_module() by Linux. Unregister now. */
    if (q_reply) detached = osal_unreg_msg_queue_cb(q_reply, cb_slot);
    printk("\0013YCIN_INIT_FAILED: rc=%d unregister=%ld\n", rc, detached);
    if (!detached) q_reply = 0;
    if (detached || resources_owned) {
        /* Shared/in-flight DMM ownership cannot safely be unwound by this probe. */
        printk("\0013YCIN_RETAINED: failed diagnostic resources=%d resident until VM shutdown\n", resources_owned);
        return 0;
    }
    return rc;
}
