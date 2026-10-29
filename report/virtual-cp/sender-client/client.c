/* Virtual-CP bring-up diagnostic: register a custom remote interchip sender via
 * osal_reg_public so AP->CP queue sends (bit31+subsystem, e.g. 0x92840747) no
 * longer hit "No snd_msg registered". CAPTURE-ONLY: logs the queue id, message
 * size and leading bytes of every remote send. It does NOT model a real CP and
 * does NOT fabricate responses; the AP imaging chain may still block waiting for
 * a reply. Normal exported API (osal_reg_public from osal_uipc.ko) only.
 * No private kernel writes, no hardcoded hidden calls. */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

extern int printk(const char *,...);
extern long osal_reg_public(long);

static u32 send_count;

/* osal_snd_msg reads the remote sender as fn = **(slot), i.e. it dereferences the
 * registered value ONCE more before calling (confirmed in osal_uipc.ko: ldr x2,[slot];
 * ldr x2,[x2]; blr x2, and pcie-if.ko which passes &sender_fn_slot, not the bare
 * function). So osal_reg_public must be given the ADDRESS of a function-pointer slot,
 * not the function itself -- passing the bare function makes osal_snd_msg jump into
 * the function's leading bytes as if they were a pointer (the UPM crash). */
static long (*sender_handle)(u32, void *);

/* osal_snd_msg remote path calls the registered sender as sender(queue_id, msg),
 * with the ORIGINAL arguments (x0=qid, x1=msg) preserved. osal_msg_size(msg) is
 * ((u32*)msg)[-2] (u32 at msg-8). */
static long virtual_cp_sender(u32 qid, void *msg)
{
    u32 size = msg ? ((u32 *)msg)[-2] : 0;
    const u8 *b = (const u8 *)msg;
    u32 n = send_count++;
    /* cap the dump so a malformed/huge size cannot over-read; UIPC control
     * messages are 12..40 bytes. */
    u32 dump = size < 24 ? size : 24;
    u32 w0=0,w1=0,w2=0,w3=0,w4=0,w5=0;
    if (b) {
        if (dump > 0)  w0 = b[0]|(b[1]<<8)|(b[2]<<16)|((u32)b[3]<<24);
        if (dump > 4)  w1 = b[4]|(b[5]<<8)|(b[6]<<16)|((u32)b[7]<<24);
        if (dump > 8)  w2 = b[8]|(b[9]<<8)|(b[10]<<16)|((u32)b[11]<<24);
        if (dump > 12) w3 = b[12]|(b[13]<<8)|(b[14]<<16)|((u32)b[15]<<24);
        if (dump > 16) w4 = b[16]|(b[17]<<8)|(b[18]<<16)|((u32)b[19]<<24);
        if (dump > 20) w5 = b[20]|(b[21]<<8)|(b[22]<<16)|((u32)b[23]<<24);
    }
    printk("\0016VIRTUAL_CP_SEND: n=%u qid=%#x size=%u b=%08x,%08x,%08x,%08x,%08x,%08x\n",
           n, qid, size, w0,w1,w2,w3,w4,w5);
    /* Return 0 = accepted by osal_snd_msg. This is NOT a real CP delivery; it is a
     * capture tap so the frame-request protocol becomes visible. */
    return 0;
}

int __attribute__((section(".init.text"))) init_module(void)
{
    sender_handle = virtual_cp_sender; /* runtime fill: avoids a .data init reloc */
    long rc = osal_reg_public((long)&sender_handle);
    /* osal error codes are 0xfffffcXX (e.g. 0xfffffc06 = already registered); only
     * rc==0 means THIS module owns the remote sender. Log the raw value so the
     * interpretation is evidence, not assumption. */
    printk("\0016VIRTUAL_CP_SENDER_REGISTER: rc=%ld (%s)\n", rc,
           rc == 0 ? "remote CP sender registered (capture-only tap)" :
                     "NOT registered - another module may own it, sends still black-holed");
    return rc == 0 ? 0 : (int)rc;
}
