/* Virtual BB ingress. Panel 0118 is retained pending a real backend completion. */
#define BB_TARGET 0x92840747u
#define BB_DEPTH 32u
#define BB_COMMANDS 7u
struct bb_entry { void *message; u32 source; u16 command, value; u8 panel[16]; };
static struct bb_entry bb_ring[BB_DEPTH];
/* Pinned original kernel: raw_spinlock_t is a zero-initialized 4-byte ticket lock. */
extern unsigned long _raw_spin_lock_irqsave(u32 *);
extern void _raw_spin_unlock_irqrestore(u32 *, unsigned long);
static u32 bb_lock, bb_head, bb_count, bb_ready, bb_fault, bb_rejected;
static u32 bb_accepted, bb_consumed, bb_generation[BB_COMMANDS];
static volatile u16 bb_values[BB_COMMANDS];
/* CP69ac86: u8[request+8] -> u32[0x1ff34c8+0x688], no completion reply. */
static volatile u32 bb_042b_parameter;
static volatile u8 bb_042b_wire[10];
/* CP69ee8a builds VDF 2001:0302. This mailbox records the latest request,
 * not a lower-device send or completion; the VDF backend is still missing. */
static volatile u8 bb_0159_vdf_request[12];
static volatile u32 bb_0159_vdf_pending;
/* CP1cd530: 0145 display masks/notification -> VDF0312, not timecode. */
static volatile u8 bb_0145_wire[24], bb_0145_vdf_request[24];
static volatile u32 bb_0145_generation, bb_0145_source, bb_0145_vdf_pending;
/* CP1ccc00/1ce03c normalize 011b/0150 to VDF0104/0306 without an AP reply. */
struct bb_display_intent { u8 wire[20], lower[20]; u32 generation, source, pending; };
static volatile struct bb_display_intent bb_display[2];
static volatile struct bb_entry bb_inflight;
static volatile long bb_free_rc;
static u32 bb_panel_busy;
static volatile u32 bb_panel_generation, bb_panel_pending_mask;
static volatile struct bb_entry bb_panel_pending;
#ifndef BB_RECEIVER_TEST
struct task_struct;
extern struct task_struct *kthread_create_on_node(int (*fn)(void *), void *, int, const char *, ...);
extern int wake_up_process(struct task_struct *);
extern int kthread_stop(struct task_struct *);
extern int kthread_should_stop(void);
extern void msleep(unsigned int);
static struct task_struct *bb_task;
#endif

static int bb_index(u16 command)
{
    switch (command) {
    case 0x0142: return 0;
    case 0x015a: return 1;
    case 0x0160: return 2;
    case 0x0500: return 3;
    case 0x033b: return 4;
    case 0x0159: return 5;
    case 0x042b: return 6;
    default: return -1;
    }
}
static int bb_display_index(u16 command)
{
    return command == 0x011b ? 0 : command == 0x0150 ? 1 : -1;
}
static long bb_reject(void *message, u32 size, long rc)
{
    const u8 *b = message;
    static const char hex[] = "0123456789abcdef";
    char raw[49];
    u32 i;
    if (__sync_fetch_and_add(&bb_rejected, 1) < 32) {
        for (i = 0; i < size && i < 24; ++i) {
            raw[2*i] = hex[b[i] >> 4];
            raw[2*i+1] = hex[b[i] & 15];
        }
        raw[2*i] = 0;
        printk("\0016BB_K_REJECT: destination=%#x source=%#x bytes=%u command=%#x rc=%ld caller_owns=1 completion=0 raw=%s\n",
               BB_TARGET, osal_get_msg_src(message), size, size >= 4 ? get16(b+2) : 0, rc, raw);
    }
    return rc;
}
static long bb_sender(void *message)
{
    u32 size = ((u32 *)message)[-2], i, source;
    const u8 *b = message;
    unsigned long flags;
    int index;
    u16 command, value;
    if ((size != 10 && size != 20 && size != 22 && size != 24) || get16(b) != 0x200d || get16(b+4) != size || get16(b+6) != 0x8001)
        return bb_reject(message, size, -1020);
    command = get16(b+2);
    value = get16(b+8);
    index = bb_index(command);
    if (command == 0x011b) {
        if (size != 10) return bb_reject(message, size, -1020);
    } else if (command == 0x0150) {
        if (size != 20 || b[8] >= 3 || b[12] >= 4)
            return bb_reject(message, size, -1020);
    } else if (command == 0x0118) {
        if (size != 22) return bb_reject(message, size, -1020);
    } else if (command == 0x0145) {
        if (size != 24 || (b[20] != 0 && b[20] != 2))
            return bb_reject(message, size, -1020);
        for (i = 8; i < 16; ++i)
            if (b[i] > 1) return bb_reject(message, size, -1020);
    } else if (size != 10 || index < 0 || (index < 4 && value > 1) || (index == 4 && b[8] != 0)) {
        return bb_reject(message, size, -1020);
    }
    source = osal_get_msg_src(message);
    if (!(source & 0x80000000u) || (source & 0x70000000u) || source == 0x80000000u ||
        (command == 0x011b && source == 0x81b40549u))
        /* CP1cccb2 has a separate internal-source completion, outside this AP subset. */
        return bb_reject(message, size, -1020);
    /* Kernel IRQ/preemption-aware locking; never sleep or free with this lock held. */
    flags = _raw_spin_lock_irqsave(&bb_lock);
    if (!__atomic_load_n(&bb_ready, __ATOMIC_ACQUIRE) || bb_fault || bb_count == BB_DEPTH ||
        (command == 0x0118 && bb_panel_busy)) {
        _raw_spin_unlock_irqrestore(&bb_lock, flags);
        return bb_reject(message, size, -1021);
    }
    for (i = 0; i < bb_count; ++i) {
        if (bb_ring[(bb_head+i) % BB_DEPTH].message == message) {
            _raw_spin_unlock_irqrestore(&bb_lock, flags);
            /* The accepted allocation can be freed now; log only saved metadata. */
            if (__sync_fetch_and_add(&bb_rejected, 1) < 32)
                printk("\0016BB_K_REJECT: destination=%#x source=%#x bytes=%u command=%#x rc=-1021 duplicate=1 existing_owner=receiver completion=0\n",
                       BB_TARGET, source, size, command);
            return -1021;
        }
    }
    i = (bb_head + bb_count) % BB_DEPTH;
    bb_ring[i].message = message;
    bb_ring[i].source = source;
    bb_ring[i].command = command;
    bb_ring[i].value = value;
    if (command == 0x042b) copy(bb_ring[i].panel, b, 10);
    if (command == 0x0145) copy(bb_ring[i].panel, b+8, 16);
    if (bb_display_index(command) >= 0) copy(bb_ring[i].panel, b+8, size-8);
    if (command == 0x0118) {
        copy(bb_ring[i].panel, b+8, 14);
        bb_panel_busy = 1;
    }
    ++bb_count;
    ++bb_accepted;
    _raw_spin_unlock_irqrestore(&bb_lock, flags);
    return 0;
}
/* Detach before free: a pool may immediately reallocate and submit the same address.
 * A failed free is retained separately, latches ingress closed, and is never retried. */
static int bb_worker_step(void)
{
    struct bb_entry e;
    unsigned long flags;
    u32 accepted, consumed, config_generation, i;
    u8 vdf_value = 0;
    int index;
    flags = _raw_spin_lock_irqsave(&bb_lock);
    if (!bb_count || bb_fault) { _raw_spin_unlock_irqrestore(&bb_lock, flags); return 0; }
    e = bb_ring[bb_head];
    bb_ring[bb_head].message = 0;
    bb_head = (bb_head + 1) % BB_DEPTH;
    --bb_count;
    _raw_spin_unlock_irqrestore(&bb_lock, flags);
    if (e.command == 0x0118) {
        /* shortcut: keep one panel request pending; attach branch apply/ACK backend before completing 1118. */
        bb_panel_pending = e;
        bb_panel_pending_mask = 3;
        ++bb_panel_generation;
        printk("\0016BB_K_PANEL_PENDING: generation=%u source=%#x request=%p selector=%#x pending_mask=3 request_retained=1 applied=0 completion=0 backend_missing=1 original_CP=0 capture_verified=0\n",
               bb_panel_generation, e.source, e.message, e.panel[0]);
        return 1;
    }
    bb_inflight = e;
    index = bb_index(e.command);
    if (index < 0 && e.command != 0x0145 && bb_display_index(e.command) < 0) {
        flags = _raw_spin_lock_irqsave(&bb_lock);
        bb_fault = 1;
        _raw_spin_unlock_irqrestore(&bb_lock, flags);
        printk("\0016BB_K_RETAIN: command=%#x message=%p invalid_queued_command=1 fault_latched=1 completion=0\n",
               e.command, e.message);
        return 0;
    }
    bb_free_rc = osal_free_msg(BB_TARGET, e.message);
    flags = _raw_spin_lock_irqsave(&bb_lock);
    if (bb_free_rc) {
        bb_fault = 1;
        _raw_spin_unlock_irqrestore(&bb_lock, flags);
        printk("\0016BB_K_RETAIN: command=%#x message=%p rc=%ld accepted=1 fault_latched=1 completion=0\n",
               e.command, e.message, bb_free_rc);
        return 0;
    }
    bb_inflight.message = 0;
    if (bb_display_index(e.command) >= 0) {
        int slot = bb_display_index(e.command);
        volatile struct bb_display_intent *d = &bb_display[slot];
        u32 size = slot ? 20 : 10;
        u32 lower_size = slot ? 20 : 12;
        u16 lower_command = slot ? 0x0306 : 0x0104;
        const u8 header[8] = {0x0d,0x20,(u8)e.command,(u8)(e.command>>8),(u8)size,0,1,0x80};
        const u8 lower[8] = {1,0x20,(u8)lower_command,(u8)(lower_command>>8),(u8)lower_size,0,1,0};
        for (i = 0; i < 20; ++i) { d->wire[i] = 0; d->lower[i] = 0; }
        for (i = 0; i < 8; ++i) { d->wire[i] = header[i]; d->lower[i] = lower[i]; }
        for (i = 8; i < size; ++i) d->wire[i] = e.panel[i-8];
        if (!slot) {
            d->lower[8] = e.panel[0] & 0x23;
            d->lower[9] = e.panel[1];
        } else {
            d->lower[8] = e.panel[0];
            d->lower[12] = e.panel[4];
            for (i = 8; i < 12; ++i) d->lower[8+i] = e.panel[i];
        }
        d->source = e.source;
        config_generation = ++d->generation;
        /* shortcut: latest intent only; attach VDF0104/0306 consumers before claiming application. */
        d->pending = 1;
        ++bb_consumed;
        _raw_spin_unlock_irqrestore(&bb_lock, flags);
        if (config_generation <= 64)
            printk("\0016BB_K_DISPLAY_CONFIG: command=%#x source=%#x bytes=%u generation=%u lower_destination=0x9059000e lower_source=0x928407b9 lower_command=%#x lower_bytes=%u latest_intent_recorded=1 request_freed=1 ap_reply=none lower_sent=0 applied=0 completion=0 backend_missing=1 original_CP=0 capture_verified=0\n",
                   e.command, e.source, size, config_generation, (u32)lower_command, lower_size);
        return 1;
    }
    if (e.command == 0x0145) {
        const u8 header[8] = {0x0d,0x20,0x45,1,24,0,1,0x80};
        const u8 lower[8] = {1,0x20,0x12,3,24,0,1,0};
        for (i = 0; i < 8; ++i) {
            bb_0145_wire[i] = header[i];
            bb_0145_vdf_request[i] = lower[i];
        }
        for (i = 0; i < 16; ++i) {
            bb_0145_wire[8+i] = e.panel[i];
            /* CP zero-initializes lower padding; original request padding is ignored. */
            bb_0145_vdf_request[8+i] = i < 13 ? e.panel[i] : 0;
        }
        bb_0145_source = e.source;
        config_generation = ++bb_0145_generation;
        /* shortcut: latest intent only; attach VDF0312 owner before reporting application or notifications. */
        bb_0145_vdf_pending = 1;
        ++bb_consumed;
        _raw_spin_unlock_irqrestore(&bb_lock, flags);
        if (config_generation <= 64)
            printk("\0016BB_K_0145_CONFIG: source=%#x generation=%u notify_destination=%#x notify_type=%u internal_event=0x95 lower_destination=0x9059000e lower_source=0x928407b9 lower_command=0x312 lower_bytes=24 latest_intent_recorded=1 request_freed=1 ap_reply=none lower_sent=0 applied=0 notifications=0 completion=0 backend_missing=VDF0312 original_CP=0 capture_verified=0\n",
                   e.source, config_generation, get32(e.panel+8), e.panel[12]);
        return 1;
    }
    bb_values[index] = e.value;
    config_generation = ++bb_generation[index];
    if (e.command == 0x042b) {
        bb_042b_parameter = (u8)e.value;
        for (i = 0; i < 10; ++i) bb_042b_wire[i] = e.panel[i];
    }
    if (e.command == 0x0159) {
        /* CP69eeb8..69eef8 preserve every input bit except bit4; byte9 is ignored. */
        const u8 header[8] = {1,0x20,2,3,12,0,2,0};
        vdf_value = (u8)e.value & 0xef;
        for (i = 0; i < 8; ++i) bb_0159_vdf_request[i] = header[i];
        bb_0159_vdf_request[8] = vdf_value;
        for (i = 9; i < 12; ++i) bb_0159_vdf_request[i] = 0;
        /* shortcut: keep requested config pending; attach VDF0302 before reporting application. */
        bb_0159_vdf_pending = 1;
    }
    ++bb_consumed;
    accepted = bb_accepted;
    consumed = bb_consumed;
    _raw_spin_unlock_irqrestore(&bb_lock, flags);
    if (e.command == 0x042b && consumed <= 64)
        printk("\0016BB_K_042B_CONFIG: source=%#x raw_value=%#x parameter_value=%u parameter_offset=0x688 parameter_bytes=4 parameter_known=1 generation=%u request_freed=1 reply_required=0 applied=0 completion=0 original_CP=0 capture_verified=0\n",
               e.source, e.value, (u32)(u8)e.value, config_generation);
    if (e.command == 0x0159 && consumed <= 64)
        printk("\0016BB_K_0159_CONFIG: source=%#x raw_value=%#x generation=%u internal_event=0xa6 lower_destination=0x9059000e lower_source=0x928407b9 lower_command=0x302 lower_value=%#x lower_request_recorded=1 lower_pending=1 lower_sent=0 applied=0 backend_missing=1 completion=0 original_CP=0 capture_verified=0\n",
               e.source, e.value, config_generation, vdf_value);
    if (consumed <= 64)
        printk("\0016BB_K_CONSUMED: command=%#x source=%#x value=%#x config_generation=%u accepted=%u freed=%u virtual_config_only=1 completion=0 original_CP=0 capture_verified=0\n",
               e.command, e.source, e.value, config_generation, accepted, consumed);
    return 1;
}
#ifndef BB_RECEIVER_TEST
static int bb_worker(void *unused)
{
    (void)unused;
    while (!kthread_should_stop()) {
        /* Bounded batch permits shutdown even under a continuous producer. */
        u32 i;
        for (i = 0; i < BB_DEPTH && !kthread_should_stop() && bb_worker_step(); ++i) {}
        msleep(10);
    }
    return 0;
}
#endif
static long bb_prepare(void)
{
#ifndef BB_RECEIVER_TEST
    bb_task = kthread_create_on_node(bb_worker, 0, -1, "a7c2-bb-rx");
    if ((unsigned long)bb_task >= (unsigned long)-4095L) return (long)bb_task;
    if (!bb_task) return -1021;
#endif
    return 0;
}
static void bb_start(void)
{
    __atomic_store_n(&bb_ready, 1, __ATOMIC_RELEASE);
#ifndef BB_RECEIVER_TEST
    (void)wake_up_process(bb_task);
#endif
}
static void bb_cancel(void)
{
#ifndef BB_RECEIVER_TEST
    (void)kthread_stop(bb_task);
#endif
}
