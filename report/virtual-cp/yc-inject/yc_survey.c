// yc_survey - survey DMM unit types and where their allocations land.
//
// Purpose: find a unit type whose pool is mapped cacheable under the default
// kemco memrsv configuration, so av-cam's arch_phys_to_cache (which rejects
// uncached translations) accepts the unit for its metadata read.
// Evidence: run-09i5nf3n logged ERROR:arch_phys_to_cache for the 0x639 unit
// at 0x4f8500000 (inside the :uc pool 0x430400000+0xCFC00000), while
// DmmCfg.bin carries pool bases 0x404000000/0x405000000 that are cached
// memrsv entries (no :uc suffix in kemco.txt).
//
// Per candidate type: op20 Alloc(0x80000) -> op21 Open -> op2a (real address)
// -> log -> op23 Free. Wire format and reply parsing mirror yc_inject.c
// exactly (osal_reg_msg_queue_cb + osal_valloc_msg_wait + 2-arg osal_snd_msg):
//   request: +0 op u16, +4 type, op20 +0xc=size else +8=handle,
//            +0x14 u16 0x1111 magic, src=reply queue, 0xd8 bytes;
//   reply:   op u16@0, status s16@2, segs u16@8, handle u32@0xc,
//            seg0 u64@0x18, len u32@0x20.
// The survey loop runs in init_module with msleep polling (no task API:
// osal_create_task/osal_reg_msgq* do not exist in this guest - run-auoscimy).

typedef unsigned char  u8;
typedef unsigned short u16;
typedef unsigned int   u32;
typedef unsigned long long u64;

extern long osal_reg_msg_queue_cb(u32 qid, void *slot_out, void *cb, void *cookie);
extern long osal_snd_msg(u32 qid, void *msg);
extern long osal_valloc_msg_wait(u32 qid, void **msg, u32 size, u32 flags);
extern long osal_set_msg_src(void *msg, u32 src);
extern long osal_free_msg(u32 qid, void *msg);
extern int  printk(const char *fmt, ...);
extern void msleep(unsigned int msecs);

#define Q_DMM      0x8061003cu
#define REQ_MAGIC  0x1111u
#define REQ_SIZE   0xd8u

static const u32 reply_candidates[4] = { 0x8aa50751u, 0x8aa60751u, 0x8aa70751u, 0x8aa80751u };

static u32          s_q_reply;
static void        *s_cb_slot;
static volatile int s_got;
static u8           s_reply[REQ_SIZE];

static void put16(u8 *p, u16 v) { p[0] = (u8)v; p[1] = (u8)(v >> 8); }
static u16 rd16(const u8 *b) { return b[0] | (b[1] << 8); }
static u32 rd32(const u8 *b) { return b[0] | (b[1] << 8) | ((u32)b[2] << 16) | ((u32)b[3] << 24); }
static u64 rd64(const u8 *b)
{
    u64 v = 0;
    int i;
    for (i = 0; i < 8; i++) v |= (u64)b[i] << (8 * i);
    return v;
}

static void survey_rcv(void *msg, void *cookie)
{
    const u8 *b = msg;
    int i;
    (void)cookie;
    for (i = 0; i < (int)REQ_SIZE; i++) s_reply[i] = b[i];
    s_got++;
}

/* exact copy of yc_inject.c dmm_send semantics */
static long dmm_send(u16 op, u32 type, u32 size_or_handle)
{
    void *req = 0;
    u8 *r;
    long rc;
    int i;

    rc = osal_valloc_msg_wait(Q_DMM, &req, REQ_SIZE, 1);
    if (rc || !req) return rc ? rc : -1024;
    r = (u8 *)req;
    for (i = 0; i < (int)REQ_SIZE; ++i) r[i] = 0;
    put16(r, op);
    if (op == 0x20) {
        r[4] = (u8)type; r[5] = (u8)(type >> 8); r[6] = (u8)(type >> 16); r[7] = (u8)(type >> 24);
        r[0xc] = (u8)size_or_handle; r[0xd] = (u8)(size_or_handle >> 8);
        r[0xe] = (u8)(size_or_handle >> 16); r[0xf] = (u8)(size_or_handle >> 24);
    } else {
        r[4] = (u8)type; r[5] = (u8)(type >> 8); r[6] = (u8)(type >> 16); r[7] = (u8)(type >> 24);
        r[8] = (u8)size_or_handle; r[9] = (u8)(size_or_handle >> 8);
        r[0xa] = (u8)(size_or_handle >> 16); r[0xb] = (u8)(size_or_handle >> 24);
    }
    put16(r + 0x14, REQ_MAGIC);
    put16(r + 0x16, 0);
    osal_set_msg_src(req, s_q_reply);
    rc = osal_snd_msg(Q_DMM, req);
    if (rc) osal_free_msg(Q_DMM, req);
    return rc;
}

/* wait for one DMM reply; returns 1 if a reply arrived within the budget */
static int wait_reply(unsigned ms)
{
    unsigned waited = 0;
    while (!s_got && waited < ms) {
        msleep(10);
        waited += 10;
    }
    return s_got != 0;
}

int __attribute__((section(".init.text"))) init_module(void)
{
    long rc = -1018;
    unsigned i;

    s_q_reply = 0;
    for (i = 0; i < 4 && !s_q_reply; ++i) {
        rc = osal_reg_msg_queue_cb(reply_candidates[i], &s_cb_slot, survey_rcv, 0);
        printk("\0016YCSVY: REGISTER qid=%#x rc=%ld\n", reply_candidates[i], rc);
        if (!rc) s_q_reply = reply_candidates[i];
    }
    if (!s_q_reply) return (int)rc;

    /* Isolation probe for run-8bnjik8k: a second CONCURRENT 0x643 alloc
     * (first unit held, not freed) never got a reply there. Here: alloc
     * 0x643 twice without freeing, op2a both, then free both. */
    {
        u32 h[2] = {0, 0};
        int k;
        for (k = 0; k < 2; k++) {
            s_got = 0;
            dmm_send(0x20, 0x643, 0x80000);
            printk("\0016YCSVY_OP: op=20 #%d type=0x643\n", k);
            if (!wait_reply(200) || rd16(s_reply) != 0x8020 || (short)rd16(s_reply + 2) != 0) {
                printk("\0016YCSVY: ALLOC%d_FAIL got=%d op=%04x status=%d\n", k, s_got,
                       s_got ? rd16(s_reply) : 0,
                       s_got ? (int)(short)rd16(s_reply + 2) : -999);
                break;
            }
            h[k] = rd32(s_reply + 0xc);
            printk("\0016YCSVY: ALLOC%d_OK handle=%#x\n", k, h[k]);

            s_got = 0;
            dmm_send(0x2a, 0, h[k]);
            if (wait_reply(200) && rd16(s_reply) == 0x802a && (short)rd16(s_reply + 2) == 0)
                printk("\0016YCSVY: UNIT%d addr=%#llx len=%#x\n", k,
                       rd64(s_reply + 0x18), rd32(s_reply + 0x20));
            else
                printk("\0016YCSVY: OP2A%d_FAIL got=%d\n", k, s_got);
        }
        for (k = 0; k < 2; k++) {
            if (!h[k]) continue;
            s_got = 0;
            dmm_send(0x23, 0, h[k]);
            wait_reply(200);
            printk("\0016YCSVY: FREE%d got=%d op=%04x status=%d\n", k, s_got,
                   s_got ? rd16(s_reply) : 0,
                   s_got ? (int)(short)rd16(s_reply + 2) : -999);
        }
    }

    printk("\0016YCSVY: SURVEY_DONE\n");
    return 0;   /* stay resident: reply queue stays registered */
}

void __attribute__((section(".exit.text"))) cleanup_module(void)
{
}
