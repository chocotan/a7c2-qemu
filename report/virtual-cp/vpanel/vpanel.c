/* Virtual panel backend (task #4 implementation): answer the original
 * vdf_set_panel_out request (op-0x200d sub-0x0118 on remote queue 0x92840747)
 * after APPLYING its 14-byte configuration to a virtual panel state, then send
 * the contract completion (op-0x200d sub-0x1118, 12B, result=0) to the
 * requester's dynamic reply queue. This is a DEVICE MODEL for the panel
 * config exchange only: it stores/validates the config (requested->applied),
 * it is NOT display hardware, models no pixels, no subdevice timing, and no
 * CP. All other remote sends stay unanswered (same as before).
 *
 * Contract (main-verified):
 *  - request 22B: {u16 0x200d, u16 0x0118, u16 0x16, u16 0x8001, 14B payload@+8}
 *  - payload: 0=vf_lcd_sel(bit0 LCD,bit1 VF), 1=panel, 5=LcdColorMode,
 *    10=power_save; 2=evf, 7=VfColorMode, 9=evf_framerate, 11=force_normal,
 *    12=priority, 13=magnifier; 3=projector (saved); 4/6/8 unread by CP.
 *  - completion: {0d 20 18 11 0c 00 01 80, u32 result@+8} to the request's
 *    source queue, source=0x92840747. result=0 only after apply.
 *  - AP dispatcher dec: pending--, +8 -> convert_vdf_err_code -> event 0xd1.
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

#define Q_IMAGING 0x92840747u
#define Q_VPANEL_SRC 0x92840747u   /* completion source, per CP evidence */

static void put32(u8 *p, u32 v) { p[0]=(u8)v; p[1]=(u8)(v>>8); p[2]=(u8)(v>>16); p[3]=(u8)(v>>24); }

/* Virtual panel state: requested vs applied per branch (contract: apply both
 * selected branches, or confirm no change, before completing). */
static struct {
    u8 panel, lcd_color, power_save;
    u8 evf, vf_color, framerate, force_normal, priority, magnifier, projector;
    u32 applied_lcd, applied_evf;
} panel_state;
static long (*sender_handle)(u32, void *);
static u32 recv_count, completed, rejected, passthrough;

static long vpanel_complete(u32 dst, u32 result)
{
    void *msg = 0;
    u8 *b;
    long rc;
    if (!dst || (dst & 0x70000000)) return -1024;   /* expect a local dynamic queue */
    rc = osal_valloc_msg_wait(dst, &msg, 12, 1);
    if (rc || !msg) return rc ? rc : -1024;
    b = msg;
    b[0]=0x0d; b[1]=0x20; b[2]=0x18; b[3]=0x11;
    b[4]=0x0c; b[5]=0x00; b[6]=0x01; b[7]=0x80;
    put32(b + 8, result);
    osal_set_msg_src(msg, Q_VPANEL_SRC);
    rc = osal_snd_msg(dst, msg);
    if (rc) osal_free_msg(dst, msg);
    return rc;
}

static long vpanel_sender(u32 qid, void *msg)
{
    u32 size = msg ? ((u32 *)msg)[-2] : 0;
    const u8 *b = (const u8 *)msg;
    u32 n = recv_count++;
    if (qid == Q_IMAGING && b && size == 22 &&
        b[0] == 0x0d && b[1] == 0x20 && b[2] == 0x18 && b[3] == 0x01 &&
        b[6] == 0x01 && b[7] == 0x80) {
        u32 src = osal_get_msg_src(msg);
        const u8 *p = b + 8;
        u8 sel = p[0];
        u32 result = 0;
        long rc;
        /* Apply selected branches to the virtual panel state. */
        if (sel & 1) {
            panel_state.panel = p[1];
            panel_state.lcd_color = p[5];
            panel_state.power_save = p[10];
            panel_state.applied_lcd++;
        }
        if (sel & 2) {
            panel_state.evf = p[2];
            panel_state.vf_color = p[7];
            panel_state.framerate = p[9];
            panel_state.force_normal = p[11];
            panel_state.priority = p[12];
            panel_state.magnifier = p[13];
            panel_state.applied_evf++;
        }
        panel_state.projector = p[3];
        /* Contract errors: all outputs off but power-save requested -> 1. */
        if ((sel & 3) && panel_state.power_save && !panel_state.panel && !panel_state.evf)
            result = 1;
        if (!(sel & 3))
            result = 2;   /* no branch selected: uncovered state */
        rc = vpanel_complete(src, result);
        if (rc) rejected++;
        else completed++;
        printk("\0016VPANEL_118: n=%u sel=%u result=%u dst=%#x rc=%ld lcd=%u,%u,%u evf=%u,%u,%u\n",
               n, sel, result, src, rc, panel_state.panel, panel_state.lcd_color,
               panel_state.power_save, panel_state.evf, panel_state.vf_color,
               panel_state.framerate);
        return 0;
    }
    if ((passthrough++ & 0x3f) == 0)
        printk("\0016VPANEL_PASS: n=%u qid=%#x size=%u (unanswered, by design)\n",
               n, qid, size);
    return 0;
}

int __attribute__((section(".init.text"))) init_module(void)
{
    long rc;
    sender_handle = vpanel_sender;
    rc = osal_reg_public((long)&sender_handle);
    printk("\0016VPANEL_REGISTER: rc=%ld (%s)\n", rc,
           rc == 0 ? "virtual panel backend registered (200d:0118 only)"
                   : "NOT registered - another module owns the sender");
    return rc == 0 ? 0 : (int)rc;
}

void __attribute__((section(".exit.text"))) cleanup_module(void)
{
    osal_unreg_public((long)&sender_handle);
    printk("\0016VPANEL_EXIT: recv=%u completed=%u rejected=%u passthrough=%u\n",
           recv_count, completed, rejected, passthrough);
}
