/* Test-only tracing, scheduling, and opt-in CP storage/address services. */
#include "capid-service.h"
#include "hdmi-format-service.h"
#include "dmm-service.h"
#include "headless-osd.h"
#include "gui-model-store.h"
#include "device-models/vdf-device.h"
#include "device-models/hdmi-device.h"
#include "device-models/hdmi-pin-device.h"
#include "device-models/audio-device.h"
#include "osdpin-registry.h"
#include "dig-level-device.h"
#include "dmm-unit-config.h"
#include "rm-file-device.h"
#include "power-notice.h"
static void (*file_media_flush_pending_fn)(void);
static void (*file_media_flush_cancel_retry_fn)(void);
static void (*real_bt_error_place)(void *,unsigned short,unsigned int);
void observe_bt_error_place(void *,unsigned short,unsigned int) __asm__("_ZN8BTUtils_6BTBlog10errorPlaceEtj");
#include "device-models/pinmem-device.h"
#include "device-models/scalar-device.h"
#include "device-models/adf-device.h"
#include "infrabb-registry.h"
#include "drawinfo-registry.h"
#include "device-models/pin-connection.h"
#include "device-models/pin-buffer-owner.h"
#include "device-models/cp-background-device.h"
typedef unsigned long size_t;
typedef unsigned long pthread_t;
static int (*sd_ack_create)(pthread_t *,const void *,void *(*)(void *),void *);
static int (*sd_ack_detach)(pthread_t);
extern void *dlvsym(void *, const char *, const char *);
extern int open(const char *, int, ...);
extern long write(int, const void *, size_t);
extern long read(int, void *, size_t);
extern long pread(int, void *, size_t, long);
extern int *__errno_location(void);
extern long syscall(long, ...);
extern unsigned long strtoul(const char *, char **, int);
extern int close(int);
extern int getpid(void);
extern char *getenv(const char *);
extern char *strstr(const char *, const char *);
extern int snprintf(char *, size_t, const char *, ...);
extern int sscanf(const char *, const char *, ...);
extern void *mmap(void *, size_t, int, int, int, unsigned long);
extern int munmap(void *, size_t);
extern int mprotect(void *, size_t, int);
static unsigned char *memory_log;
static void *(*real_dlsym)(void *, const char *);
static void *(*real_dlopen)(const char *, int);
static int (*real_attr_policy)(void *, int);
static int (*real_attr_param)(void *, const void *);
static int (*real_thread_param)(pthread_t, int, const void *);
static int (*real_scheduler)(int, int, const void *);
static void *(*real_application_init)(void *);
static void *(*real_uxengine_init2)(void *);
static unsigned long appfw_base;
static unsigned int vdf_config_used;
static unsigned int hdmi_config_used;
static unsigned int audio_config_used;
static unsigned int dig_level_used;
static unsigned int dmm_unit_used;
static unsigned int pin_registry_used;
static unsigned int pin_connection_used;
/* MENU_BB_READY_LATE=1 defers the single 0x2003/0x8201 fulfilment away from the plane-table
   completion (see screen-blocker/REPORT.md E2): on real hardware CP sends it after the output
   pipeline has started, i.e. after the cold-boot chain, not in the middle of it. The event is
   then delivered on the first app-side send that follows an injected key. */
static int bb_ready_pending;
static int bb_key_seen;
static int (*real_updater_init)(void);
static int (*real_updater_exit)(void);
static int (*real_dynamic_id)(unsigned int, unsigned int, unsigned long);
static int (*real_reg_sync)(unsigned int, void **, void *, unsigned long);
static int (*real_reg_async)(unsigned int, void **, void *, unsigned long);
static int (*real_unreg_async)(unsigned int,void *);
static int rm_file_enabled;
static int (*real_send_msg)(unsigned int, void *);
static int (*real_send_sync)(unsigned int, void *);
static int (*real_send_sync_direct)(unsigned int, void *);
static int (*real_stat_msgq)(unsigned int,void *);
static unsigned int (*real_media_open)(const char *,unsigned int,void **);
unsigned int mcmn_drv_open(const char *,unsigned int,void **);
static int (*real_allocate_msg)(unsigned int, void **, unsigned int, unsigned int);
static int (*real_free_msg)(unsigned int, void *);
/* Lens-version virtual service: 0x912503d0 has no kernel queue in QEMU, so requests
   valloc'd by libInfraGetVersion.so+0xe08 borrow the always-present ulog queue pool
   (0x8f013a) and are remembered here so the matching free returns them to that pool. */
#define LENS_POOL_SLOTS 8
static struct { void *message; unsigned int borrowed_from; int live; } lens_pool[LENS_POOL_SLOTS];
static unsigned long lens_pool_lock[6];
static unsigned int backup_service_count;
static int backup_service_enabled;
static unsigned int sensor_service_count;
static unsigned int (*real_get_source)(void *);
static void (*real_set_source)(void *, unsigned int);
static unsigned int (*real_msg_size)(void *);
static int (*real_rcv_msg_tmo)(unsigned int, void **, long);
typedef struct { const char *dli_fname; void *dli_fbase; const char *dli_sname; void *dli_saddr; } Dl_info;
static int (*real_dladdr)(void *, Dl_info *);
extern int pthread_mutex_lock(void *);
extern int pthread_mutex_unlock(void *);
extern int pthread_mutex_trylock(void *);
static unsigned long cap_lock[6]; /* AArch64 glibc 2.25 pthread_mutex_t is 48 bytes */
static struct cap_service capid;
static int capid_enabled;
static int sa_address_enabled;
static int hdmi_format_enabled;
static struct hdmi_format_state hdmi_format;
static int hdmi_photo_enabled;
static struct hdmi_photo_state hdmi_photo;
static int display_info_enabled;
static int subscription_enabled;
static unsigned long captured_menu_controller;
/* The thread that runs the application's UI (learned from create_screen). Activating a mode controller
   from an arbitrary worker thread aborted the guest, so the message-loop path only fires on this tid. */
static unsigned int ui_thread_id;
static unsigned int create_screen_active, create_screen_returned;
static int sequence_event_enabled;
/* Our own 'BB output ready' fulfilment: on real hardware the CP sends it. Fulfilling a promise the
   application has already completed throws future_error(2) and aborts IWrapperBBSub, so this is now
   opt-in only (MENU_BB_READY_INJECT=1) instead of firing on every plane-config request. */
static int bb_ready_inject_enabled;
/* Panel/EVF geometry reported to the model. The retail UI resources are authored for a
   720x480 LCD and a 1024x768 EVF (master_normal.uxc contains 768 fifty times and 480 not at
   all), so 640x480 is a placeholder that may not match any layout. Override with
   QEMU_DISPLAY_SIZE="<panel_w>x<panel_h>,<evf_w>x<evf_h>" and QEMU_DISPLAY_ASPECT="p,e". */
static struct display_info virtual_display = {640, 480, 640, 480, 1, 1};
static int dmm_enabled;
static struct dmm_service dmm;
int sa_address_reply(const unsigned char *, unsigned char *);
static int (*real_kikilog_notify)(unsigned int);
static int (*real_gpe_fill)(int, int, unsigned int *, const void *);
/* MonLib monitor-console guard: MonDrv::Init fails in QEMU (/dev/mem absent at
   devtmpfs and unusable via mknod without the kernel mem driver), leaving the
   console queue pointers NULL; any later MonDrv output then SEGVs inside
   libMWF+0x409d0 (run-y3ruwbci/yol1gsix/podfartv/2jqg0nsj/4vxgchsa). libMWF
   calls its own exports through the PLT, so redirecting the queue probes to
   "queue full" reproduces the real camera's drop-output behavior safely. */
#if 0 /* dq0o3yjm reconstruction: post-good-build additions disabled */
static int (*real_monqueue_isfull)(void *);
static int (*real_monqueue_nearlyfull)(void *);
static int (*real_monqueue_isempty)(void *);
static unsigned long (*real_monqueue_remain)(void *);
static int (*real_monqueue_enqueue)(void *, unsigned char);
static unsigned long (*real_monqueue_dequeue)(void *);
int _ZN8MonQueue6IsFullEv(void *queue) {
    if (!queue) return 1;  /* full: MonDrv::SetInputChar/Putchar drop and return -1 */
    return real_monqueue_isfull ? real_monqueue_isfull(queue) : 0;
}
int _ZN8MonQueue12IsNearlyFullEv(void *queue) {
    if (!queue) return 1;  /* full: MonDrv::PutcharSub drops the character */
    return real_monqueue_nearlyfull ? real_monqueue_nearlyfull(queue) : 0;
}
int _ZN8MonQueue7IsEmptyEv(void *queue) {
    if (!queue) return 1;  /* empty: output drain loops sleep instead of deref */
    return real_monqueue_isempty ? real_monqueue_isempty(queue) : 1;
}
unsigned long _ZN8MonQueue14GetQueueRemainEv(void *queue) {
    if (!queue) return 0x40;  /* default ring capacity headroom */
    return real_monqueue_remain ? real_monqueue_remain(queue) : 0x40;
}
int _ZN8MonQueue7EnQueueEh(void *queue, unsigned char value) {
    if (!queue) return -1;  /* drop */
    return real_monqueue_enqueue ? real_monqueue_enqueue(queue, value) : -1;
}
unsigned long _ZN8MonQueue7DeQueueEv(void *queue) {
    if (!queue) return 0xffffffff;  /* empty marker */
    return real_monqueue_dequeue ? real_monqueue_dequeue(queue) : 0xffffffff;
}
#endif /* dq0o3yjm reconstruction */
static int (*real_gpe_blit)(int, int, unsigned int *, const void *);
static unsigned int gpe_capture_count;
static int software_gpe;
static int software_rgba4444;
static int raster_fd = -1;
static int (*real_draw_initialize)(int);
int software_draw_initialize(int) __asm__("_ZN5mpgpe14InitializeDrawENS_3GpeE");
static int (*real_gperm_initialize)(const void *);
int software_gperm_initialize(const void *) __asm__("_ZNK5mpgpe5Gperm4InitEv");
static int (*real_worker_fill)(int, int, unsigned int, unsigned int, const void *);
static int (*real_worker_blit)(int, int, unsigned int, unsigned int, const void *);
static int (*real_worker_flush)(int, int, unsigned int, unsigned int, const void *);
static int raster_failed;
static unsigned long headless_raster_mutex[6], headless_lifecycle_mutex[6];
#include "gpe-copy.h"
#include "gpe-sprite.h"
#include "sony-lz77.h"
int software_flush_worker(int, int, unsigned int, unsigned int, const void *)
    __asm__("_ZN5mpgpe5FlushENS_3GpeENS_7IntCoreEjjRKNS_10FlushParamE");
static int (*real_draw_complete)(unsigned int, const void *, size_t);
int gpe_uniform_fill(unsigned char *, size_t, const unsigned int *);
int software_fill_worker(int, int, unsigned int, unsigned int, const void *)
    __asm__("_ZN5mpgpe8FillRectENS_3GpeENS_7IntCoreEjjRKNS_13FillRectParamE");
int software_blit_worker(int, int, unsigned int, unsigned int, const void *)
    __asm__("_ZN5mpgpe7BitBlitENS_3GpeENS_7IntCoreEjjRKNS_12BitBlitParamE");
static int same_name(const char *, const char *);
static void record(const char *, const char *);
/* appFw calls iCrypt_HasPublicKey from sequence_boot::run but neither im.elf nor appFw lists
   libInfraCrypt.so in DT_NEEDED, so the dynamic linker fails the lazy lookup and kills the process
   ("symbol lookup error: ... undefined symbol: iCrypt_HasPublicKey"). The library ships in this
   firmware rootfs and defines that symbol, so loading it RTLD_GLOBAL before appFw is imported
   restores the symbol environment instead of faking the call. */
static void load_crypt_library(void) {
    typedef const char *(*dlerror_type)(void);
    dlerror_type get_error = (dlerror_type)real_dlsym((void *)-1, "dlerror");
    static const char *candidates[] = { "libInfraCrypt.so", "/usr/lib/libInfraCrypt.so", "/usr/lib/menu/libInfraCrypt.so" };
    char text[288];
    int written = 0;
    for (unsigned int i = 0; i < sizeof candidates / sizeof candidates[0]; ++i) {
        if (get_error) (void)get_error();               /* clear any stale error */
        /* RTLD_LAZY: bind function symbols on first call instead of demanding every
           dependency symbol now. libInfraSKD.so (pulled in by libInfraCrypt.so) leaves
           osal_unreg_msg_queue_cb unresolved at this point, and RTLD_NOW made that fatal even
           though the symbol appFw actually needs (iCrypt_HasPublicKey) is defined by this same
           library. Data relocations are still resolved eagerly by the loader. */
        void *handle = real_dlopen(candidates[i], 1 | 0x100 /* RTLD_LAZY | RTLD_GLOBAL */);
        const char *reason = (handle || !get_error) ? 0 : get_error();
        written += snprintf(text + written, sizeof text - (size_t)written, "%s%s=%s%s",
                            i ? "; " : "", candidates[i], handle ? "ok" : "FAIL",
                            handle ? "" : (reason && *reason ? reason : "(no dlerror)"));
        if (handle) break;
        if (written > (int)sizeof text - 64) break;
    }
    record("CRYPT_LIB ", text);
}
static void install_option_probes(void);
static void install_honest_route_hook(void);
static unsigned long find_library_base(const char *);
extern unsigned long observe_appfw_base;
static void install_sync_msg_probe(unsigned long);
/* The guest kernel already knows a destination has no receiver ("UIPC ERROR ... No snd_msg
   registered. Skip snd to 0x747") yet still reports success to the caller. Callers that then
   wait for a reply - DataflowInfraReceiver::ReceiveASync with timeout=-1, or OSAL sync calls -
   block forever on an answer nobody will send. This is the same defect that was fixed for
   SID 0x90280964: the transport must not claim a delivery it did not perform.
   MENU_HONEST_ROUTING=1 tracks locally registered ids and returns "no such destination" for a
   send to an id nothing registered, so the firmware's own error paths run instead of hanging.
   It never fabricates a reply and never rewrites one. */
/* The guest kernel already knows a destination has no receiver ("UIPC ERROR ... No snd_msg
   registered. Skip snd to 0x747") yet still reports success, so a caller that waits for a reply -
   DataflowInfraReceiver::ReceiveASync with timeout=-1 - blocks forever on an answer nobody sends.
   The same defect was fixed earlier for SID 0x90280964.
   IMPORTANT SCOPE: this must NOT be driven by "did *this process* register the id". Ids such as
   0x8f013a (ulogio log sink) are registered by *other* processes and are legitimately routed over
   uipc; blocking those broke logging and stopped the first frame entirely (measured: draws 0).
   So the decision is an explicit id list only: MENU_HONEST_ROUTING=0x747[,0x...]. Anything not
   listed keeps the original behaviour, and no reply is ever fabricated. */
static unsigned int honest_ids[16];
static unsigned int honest_id_count;
static void honest_routing_init(void) {
    const char *spec = getenv("MENU_HONEST_ROUTING");
    honest_id_count = 0;
    if (!spec) return;
    while (*spec && honest_id_count < sizeof honest_ids / sizeof honest_ids[0]) {
        while (*spec == ',' || *spec == ' ') ++spec;
        if (!*spec) break;
        unsigned int value = 0;
        unsigned int digits = 0;
        if (spec[0] == '0' && (spec[1] == 'x' || spec[1] == 'X')) spec += 2;
        while (digits < 8) {
            char c = *spec;
            unsigned int nibble;
            if (c >= '0' && c <= '9') nibble = (unsigned int)(c - '0');
            else if (c >= 'a' && c <= 'f') nibble = (unsigned int)(c - 'a' + 10);
            else if (c >= 'A' && c <= 'F') nibble = (unsigned int)(c - 'A' + 10);
            else break;
            value = (value << 4) | nibble;
            ++spec; ++digits;
        }
        if (!digits) break;
        honest_ids[honest_id_count++] = value;
    }
}
/* MEASURED: the guest kernel prints only the low 16 bits ("Skip snd to 0x747") while appFw passes
   the full composite id 0x92840747 (built at 0x34e9d30: mov w0,#0x747 + movk w0,#0x9284,lsl#16).
   Matching the whole value never fired - the run kept three "Skip snd to 0x747" with zero
   HONEST_ROUTE records even though both GOT hooks were armed. Compare the low 16 bits as well, so
   an entry may be written either as 0x747 or as 0x92840747. */
static int honest_no_receiver(unsigned int id) {
    for (unsigned int i = 0; i < honest_id_count; ++i)
        if (honest_ids[i] == id || honest_ids[i] == (id & 0xffff)) return 1;
    return 0;
}
static void start_bus_power_module(void);static void start_bus_power_module(void);
/* ---------------------------------------------------------------------------------------------
   Hooking the *sender's* GOT, not our own interposition.
   MEASURED FAILURE: with MENU_HONEST_ROUTING=0x747 the run still showed six
   "Skip snd to 0x747" and zero HONEST_ROUTE records, i.e. the Dataflow send never reached our
   global osal_snd_msg wrapper at all - dataflowInfraFramework.so calls osal_snd_msg through its
   own PLT/GOT slot (library VA 0x5a1a0, resolved statically from its .rela.plt). To speak about
   that call we must redirect that specific slot. The dispatch below is deliberately minimal: it
   only reports "no such destination" for the allow-listed ids and forwards everything else to the
   real osal, so no menu-forcing or probe logic runs on the Dataflow path.
   --------------------------------------------------------------------------------------------- */
static int pipeline_virtual_serve(unsigned int id, void *message);
static int honest_snd_dispatch(unsigned int id, void *message) {
    /* MEASURED: destinations with bits 28..30 set never enter the kernel cb table at all. The kernel
       osal_snd_msg tests `tst x19,#0x70000000` FIRST (osal_uipc.ko 0x3d78) and, when set, calls the
       single global public handler at [.bss+0x2bc0+0x1112] instead - otherwise it prints
       "No snd_msg registered". Only an in-kernel caller of osal_reg_public can install that handler;
       pcie-if.ko's pcieif_reg_public does exactly that (0x3c88 -> osal_reg_public). The userspace
       osal_reg_public in libosal_uipc.so only writes a local .bss word that nothing ever reads, so a
       userspace registration can never satisfy this path. 0x92840747 belongs to that class, so serve
       it here in the sender's own process instead. */
    if (pipeline_virtual_serve(id, message)) return 0;
    if (honest_no_receiver(id)) {
        static unsigned int seen;
        if (seen++ < 16) {
            char text[144];
            snprintf(text, sizeof text, "n=%u tid=%ld dest=%#x -> -1021 (allow-listed, nothing registered)",
                     seen, syscall(178), id);
            record("HONEST_ROUTE ", text);
        }
        return -1021;
    }
    if (!real_send_msg) real_send_msg = real_dlsym((void *)-1, "osal_snd_msg");
    if (!real_send_msg) return -1021;
    return real_send_msg(id, message);
}
/* infra_wrapper_bb::detail::send_and_wait_cmp_i (appFw 0x34e56e4) requires its osal_snd_msg to
   succeed; a failure logs "assert at infra_wrapper_bb_ipsx_sp_pp_branch.cpp:906" and aborts
   (measured). So the 0x92840747 endpoint cannot be answered with an error - it must be served.
   libInfraAvbbc.so exports InfraAvbbc_Init and registers Dataflow callbacks through
   BizDataflowInfraReceiver::RegSyncCb, i.e. it is a loadable module of the same kind as BusPower.
   MENU_INFRA_AVBBC=1 starts it with its own entry point so any reply it produces is the firmware's
   own, not a stub. */
static void install_pipeline_endpoint(void);
/* ---------------------------------------------------------------------------------------------
   Virtual imaging-pipeline endpoint for 0x92840747.
   MEASURED CONTRACT (appFw 0x34e55c8..0x34e57c8, the `send_and_wait_cmp_i` body):
       34e56e4  bl osal_snd_msg(dest, request)
       34e5778  ldr w0,[x29,#112]              ; the id the caller registered as its source
       34e5784  bl osal_rcv_msg_tmo(source, &reply, -1)
       34e5798  memcpy(caller_buffer, reply, w24)
       34e57a4  bl osal_free_msg(source, reply)
   So the caller sends the request, then blocks forever on its own source queue until somebody
   replies to that source. Nothing in this emulated camera owns 0x747 (kernel: "No snd_msg
   registered ... Skip snd to 0x747"), which is why run_i never returns and the UI promise that
   gates the shooting screen is never fulfilled.
   This endpoint registers 0x747 and, on every request, sends one message back to
   osal_get_msg_src(request), echoing the request body. That is a VIRTUAL endpoint: the reply the
   real imaging pipeline produces on hardware is not known, so the echo must not be recorded as
   verified hardware behaviour. It sends exactly one message per request, invents no status
   values, and logs every exchange.
   --------------------------------------------------------------------------------------------- */
static void *pipeline_handle;
static unsigned int pipeline_requests, pipeline_replies, pipeline_failures;
static void pipeline_endpoint_callback(void *argument, void *message) {
    (void)argument;
    if (!message || !real_get_source || !real_allocate_msg || !real_send_msg || !real_set_source) return;
    unsigned int source = real_get_source(message);
    unsigned int size = real_msg_size ? real_msg_size(message) : 0;
    const unsigned int *words = (const unsigned int *)message;
    if (pipeline_requests++ < 12) {
        char text[224];
        snprintf(text, sizeof text, "n=%u tid=%ld src=%#x bytes=%u w=%08x,%08x,%08x,%08x,%08x,%08x",
                 pipeline_requests, syscall(178), source, size,
                 size >= 4 ? words[0] : 0, size >= 8 ? words[1] : 0, size >= 12 ? words[2] : 0,
                 size >= 16 ? words[3] : 0, size >= 20 ? words[4] : 0, size >= 24 ? words[5] : 0);
        record("PIPELINE_REQ ", text);
    }
    if (!source || !size) { ++pipeline_failures; record("PIPELINE_NO_REPLY ", "no source id or empty request"); return; }
    void *reply = 0;
    if (real_allocate_msg(source, &reply, size, 1) || !reply) {
        ++pipeline_failures;
        record("PIPELINE_FAILED ", "reply allocation refused");
        return;
    }
    {   unsigned char *dst = reply; const unsigned char *src = message;
        for (unsigned int i = 0; i < size; ++i) dst[i] = src[i];
    }
    real_set_source(reply, 0x92840747U);
    if (real_send_msg(source, reply)) {
        ++pipeline_failures;
        if (real_free_msg) real_free_msg(source, reply);
        record("PIPELINE_FAILED ", "reply delivery refused");
        return;
    }
    if (pipeline_replies++ < 12) {
        char text[128];
        snprintf(text, sizeof text, "n=%u to=%#x bytes=%u (echo of request)", pipeline_replies, source, size);
        record("PIPELINE_REPLY ", text);
    }
}
static void install_pipeline_endpoint(void) {
    /* MEASURED BUG (first attempt): this guard tested appfw_base, which is still 0 when the
       appFw-ready hook runs - install_boot_entry_probes sets observe_appfw_base, not appfw_base -
       so the endpoint silently never armed and the run showed zero PIPELINE_ARM records with all
       six "Skip snd to 0x747" still present. Only the registration API is actually required. */
    if (pipeline_handle) return;
    if (!getenv("MENU_PIPELINE_ENDPOINT")) return;
    if (!real_reg_async) real_reg_async = real_dlsym((void *)-1, "osal_reg_msg_queue_cb");
    if (!real_reg_async) { record("PIPELINE_ARM_FAILED ", "no osal_reg_msg_queue_cb"); return; }
    /* MEASURED: u_osal_reg_msg_queue_cb passes the FULL 32-bit id into its ioctl struct
       (str w0,[x29,#48] at libosal_uipc 0x3d04), while the &0x7fff mask at 0x6b98 only indexes
       the userspace cb table. Registering 0x747 therefore yields a kernel entry for 0x747, but the
       sender targets 0x92840747 and the kernel looks it up unmasked -> "No snd_msg registered".
       The earlier stop-on-first-success loop never tried the full form. Register every candidate. */
    unsigned int candidates[2] = { 0x747, 0x92840747 };
    int armed = 0;
    for (unsigned int i = 0; i < 2; ++i) {
        void *handle = 0;
        int rc = real_reg_async(candidates[i], &handle, (void *)pipeline_endpoint_callback, 0);
        char text[160];
        snprintf(text, sizeof text, "id=%#x rc=%d handle=%p", candidates[i], rc, handle);
        record("PIPELINE_ARM ", text);
        if (!rc) { ++armed; if (!pipeline_handle) pipeline_handle = handle ? handle : (void *)1; }
    }
    if (!armed) record("PIPELINE_ARM_FAILED ", "both id forms refused");
}
/* The high-bit public-handler class is unreachable from userspace, so answer the request in the
   caller's own process: reply to the source id the request itself carries. send_and_wait_cmp_i
   blocks on exactly that id (osal_rcv_msg_tmo([x29,#112])), so a message addressed there is
   accepted by the ordinary kernel cb table and wakes the caller. One reply per request; the body is
   an echo, which is a VIRTUAL reply, not measured hardware behaviour. */
static unsigned int pipeline_virt_requests;
static int pipeline_virtual_serve(unsigned int id, void *message) {
    if (!getenv("MENU_PIPELINE_VIRT")) return 0;
    /* MEASURED REGRESSION (previous run): matching every high-bit destination also stole the three
       no-wait 0x90030001 settings messages, which the real CP release service serves - the boot went
       backwards (SEQ_FINISH empty, BOOT_POST_EE 0) even though the pipeline replies themselves worked.
       Restrict to the imaging-pipeline id class only. */
    if (!message || (id & 0xffff0000U) != 0x92840000U) return 0;
    if (!real_get_source || !real_allocate_msg || !real_send_msg || !real_set_source) return 0;
    unsigned int source = real_get_source(message);
    unsigned int size = real_msg_size ? real_msg_size(message) : 0;
    const unsigned int *words = (const unsigned int *)message;
    if (pipeline_virt_requests++ < 12) {
        char text[224];
        snprintf(text, sizeof text, "n=%u tid=%ld dest=%#x src=%#x bytes=%u w=%08x,%08x,%08x,%08x",
                 pipeline_virt_requests, syscall(178), id, source, size,
                 size >= 4 ? words[0] : 0, size >= 8 ? words[1] : 0,
                 size >= 12 ? words[2] : 0, size >= 16 ? words[3] : 0);
        record("PIPELINE_VREQ ", text);
    }
    if (!source) { record("PIPELINE_VFAIL ", "request carries no source id"); return 1; }
    /* MEASURED HEADER (from the firmware's own senders, not guessed): u16 category at +0,
       u16 command at +2, u16 total length INCLUDING the header at +4, u16 unknown at +6 (0x8001
       in every captured request), parameters from +8.  The echo reply was wrong in four separate
       ways and each one is visible in the previous run's log: the command stayed 0x0118 so the
       completion branch for 0x1118 never ran (console.log:1575 unknown-msg); the parameter bytes
       were handed back as a RESULT (console.log:1595 and :1649 report exactly the request's +8
       word, 0x0e000e01 and 0x00010107); a 10-byte request was copied into 12 bytes because the
       caller's memcpy at 0x34e5798 uses w24 unconditionally; and the no-wait senders were answered
       although they free their source right after sending (console.log:1615/:1655 queue M=1).
       So reply only to the synchronous setters, with their real reply command and length. */
    const unsigned char *req = message;
    unsigned int cmd = (size >= 4) ? (unsigned int)req[2] | ((unsigned int)req[3] << 8) : 0;
    unsigned int reply_size;
    switch (cmd) {
        case 0x0118: reply_size = 12; break;   /* vdf_set_panel_out      -> async completion 0x1118 */
        case 0x011a: reply_size = 12; break;   /* disp brightness        -> sync copy of 12 bytes   */
        case 0x013d: reply_size = 12; break;   /* brightness slope       -> sync copy of 12 bytes   */
        case 0x014c: reply_size = 12; break;   /* yuv layout             -> sync copy of 12 bytes   */
        default:
            if (pipeline_virt_requests <= 12) {
                char text[128];
                snprintf(text, sizeof text, "n=%u cmd=%#x bytes=%u -> no reply (no-wait or unproven)",
                         pipeline_virt_requests, cmd, size);
                record("PIPELINE_VDROP ", text);
            }
            return 1;
    }
    void *reply = 0;
    if (real_allocate_msg(source, &reply, reply_size, 1) || !reply) {
        record("PIPELINE_VFAIL ", "reply allocation refused");
        return 1;
    }
    {   unsigned char *dst = reply;
        for (unsigned int i = 0; i < reply_size; ++i) dst[i] = 0;
        dst[0] = req[0]; dst[1] = req[1];                       /* same category as the request */
        unsigned int answer = cmd | 0x1000U;                    /* proven only for 0x0118 -> 0x1118 */
        dst[2] = answer & 0xff; dst[3] = (answer >> 8) & 0xff;
        dst[4] = reply_size & 0xff; dst[5] = (reply_size >> 8) & 0xff;
        dst[6] = 1; dst[7] = 0;                                 /* unproven: +6 field, every request had 0x8001 */
        /* dst[8..11] stays 0 = success; every proven consumer reads its result as a u32 at +8. */
    }
    /* MEASURED: DataflowInfraReceiver::ReceiveASync (dataflowInfraFramework 0x33c9c..) accepts a
       message only when osal_get_msg_src(reply) equals one of five sender ids:
       0x00c00695, 0x80c2019f, 0x0061003c, 0x00c20219, 0x01590438. Anything else makes it return 2
       without filling the caller's message, so run_i keeps waiting even though the reply was
       delivered. The echo previously used set_source(id) = 0x92840747, which is not in that set. */
    unsigned int reply_src = 0x80c2019fU;
    if (getenv("MENU_PIPELINE_SRC")) reply_src = (unsigned int)strtoul(getenv("MENU_PIPELINE_SRC"), 0, 16);
    real_set_source(reply, reply_src);
    if (real_send_msg(source, reply)) {
        if (real_free_msg) real_free_msg(source, reply);
        record("PIPELINE_VFAIL ", "reply delivery refused");
        return 1;
    }
    {   char text[128];
        snprintf(text, sizeof text, "n=%u -> %#x cmd=%#x bytes=%u (virtual, +8=0)", pipeline_virt_requests, source, cmd | 0x1000U, reply_size);
        record("PIPELINE_VREPLY ", text);
    }
    return 1;
}
static void start_avbbc_module(void) {
    void *handle = real_dlopen("libInfraAvbbc.so", 1 | 0x100 /* RTLD_LAZY | RTLD_GLOBAL */);
    char text[256];
    if (!handle) {
        typedef const char *(*dlerror_type)(void);
        dlerror_type get_error = (dlerror_type)real_dlsym((void *)-1, "dlerror");
        const char *reason = get_error ? get_error() : 0;
        snprintf(text, sizeof text, "dlopen failed: %s", reason && *reason ? reason : "(no dlerror)");
        record("AVBBC ", text);
        return;
    }
    typedef void (*init_type)(void);
    init_type avbbc_init = (init_type)real_dlsym(handle, "InfraAvbbc_Init");
    if (!avbbc_init) { record("AVBBC ", "lib loaded but InfraAvbbc_Init missing"); return; }
    record("AVBBC ", "calling InfraAvbbc_Init (firmware's own module entry)");
    avbbc_init();
    record("AVBBC ", "InfraAvbbc_Init returned");
}
static unsigned int honest_hook_state;   /* 0 = not yet, 1 = armed, 2 = permanent failure */
static unsigned int honest_appfw_armed, honest_dataflow_armed;
/* MEASURED REASON FOR THE appFw SLOT: the first attempt only redirected
   dataflowInfraFramework's own GOT slot and the six "Skip snd to 0x747" still appeared with zero
   HONEST_ROUTE records. appFw resolves osal_snd_msg through *its own* GOT slot at VA 0x5bc1d70,
   which is otherwise patched only when MENU_ASYNC_SEND is on - so in a run without that switch the
   honest check never executed. Both senders are redirected here so the allow-list works no matter
   which library issues the call. */
static void install_honest_route_hook(void) {
    /* MEASURED BUG: this gate tested MENU_HONEST_ROUTING only, so a run with just
       MENU_PIPELINE_VIRT=1 left both GOT slots unarmed - zero PIPELINE_VREQ records and all six
       "Skip snd to 0x747" still printed by the kernel. The virtual endpoint needs the same hook. */
    if (honest_hook_state == 2) return;
    if (!getenv("MENU_HONEST_ROUTING") && !getenv("MENU_PIPELINE_VIRT")) return;
    char text[176];
    if (!honest_appfw_armed && observe_appfw_base) {
        unsigned long slot_va = observe_appfw_base + 0x5bc1d70UL;
        if (mprotect((void *)(slot_va & ~0xfffUL), 4096, 3) == 0) {
            *(unsigned long *)slot_va = (unsigned long)honest_snd_dispatch;
            honest_appfw_armed = 1;
            snprintf(text, sizeof text, "appFw osal_snd_msg GOT slot=0x%lx", slot_va);
            record("HONEST_HOOK ", text);
        }
    }
    if (!honest_dataflow_armed) {
        unsigned long base = find_library_base("dataflowInfraFramework.so");
        if (base) {
            unsigned long slot_va = base + 0x5a1a0UL;
            if (mprotect((void *)(slot_va & ~0xfffUL), 4096, 3) == 0) {
                *(unsigned long *)slot_va = (unsigned long)honest_snd_dispatch;
                honest_dataflow_armed = 1;
                snprintf(text, sizeof text, "dataflowInfraFramework osal_snd_msg GOT base=0x%lx slot=0x%lx",
                         base, slot_va);
                record("HONEST_HOOK ", text);
            }
        }
    }
    if (honest_appfw_armed && honest_dataflow_armed) honest_hook_state = 1;
}
/* BusPower is a loadable module that IMDB would dlopen and start with BusPower_Init. In this
   emulated camera nothing starts it, so the 16-byte sync request appFw sends to its queue
   (cate 0x6107 / msgid 0x1000, raw id 0x12282f6) has no receiver: osal returns -1020 and
   sequence_boot::run_i hits its source-level `assert at` on sequence/sequence_boot.cpp:1436,
   which keeps the UI promise the shooting screen waits on from ever being fulfilled.
   Starting the module the way the firmware does is the honest fix: the replies then come from
   BusPower::preProcessCateBusPower itself, not from a stub we invent.
   libBusPower.so imports no device path of its own (its string table has no /dev entry); it only
   needs its own worker thread, which BusPower_Init creates. */
static void install_sync_call_probe(unsigned long);
static void log_option_install_ready(const char *);
static void install_osd_observers(void *);
static void install_frame_observers(unsigned long);
static unsigned long (*real_notify_draw)(void *), (*real_draw_framebuffer)(void *);
static int headless_osd_enabled;
static void start_headless_osd(void);
static void install_sync_direct_probe(unsigned long);
static void install_async_send_probe(unsigned long);
int observe_gpe_fill(int, int, unsigned int *, const void *)
    __asm__("_ZN5mpgpe13GpermFillRectENS_3GpeENS_7IntCoreEPjRKNS_13FillRectParamE");
int observe_gpe_blit(int, int, unsigned int *, const void *)
    __asm__("_ZN5mpgpe12GpermBitBlitENS_3GpeENS_7IntCoreEPjRKNS_12BitBlitParamE");

/* Resolve on the initial thread, before dlopen constructors create IPC threads.
 * Repeated dlsym from those threads could block on the constructor's loader lock.
 */
#ifndef MENU_OBSERVE_TRANSPORT_SELFTEST
__attribute__((constructor))
#endif
static void initialize(void) {
    real_dlsym = dlvsym((void *)-1, "dlsym", "GLIBC_2.17");
    file_media_flush_pending_fn=real_dlsym(0,"file_media_flush_pending");
    file_media_flush_cancel_retry_fn=real_dlsym(0,"file_media_flush_cancel_retry");
    real_dlopen = real_dlsym((void *)-1, "dlopen");
    /* Both load firmware libraries that only exist inside the guest rootfs, so they must never run
       in the host self-test build (check-menu-observe): there they have no library to open. */
    if (!getenv("MENU_OBSERVE_SELFTEST")) {
        honest_routing_init();
    if (getenv("MENU_CRYPT_LIB")) load_crypt_library();
    }
    real_attr_policy = real_dlsym((void *)-1, "pthread_attr_setschedpolicy");
    real_attr_param = real_dlsym((void *)-1, "pthread_attr_setschedparam");
    real_thread_param = real_dlsym((void *)-1, "pthread_setschedparam");
    real_scheduler = real_dlsym((void *)-1, "sched_setscheduler");
    real_dynamic_id = real_dlsym((void *)-1, "osal_dynamic_id");
    real_reg_sync = real_dlsym((void *)-1, "osal_reg_sync_msg_queue_cb");
    real_reg_async = real_dlsym((void *)-1, "osal_reg_msg_queue_cb");
    real_unreg_async = real_dlsym((void *)-1,"osal_unreg_msg_queue_cb");
    const char *rm_mode=getenv("MENU_RM_FILE");
    rm_file_enabled=rm_mode && rm_mode[0]=='1' && !rm_mode[1];
    real_send_msg = real_dlsym((void *)-1, "osal_snd_msg");
    real_send_sync = real_dlsym((void *)-1, "osal_snd_sync_msg");
    real_send_sync_direct = real_dlsym((void *)-1, "osal_snd_sync_direct");
    real_stat_msgq = real_dlsym((void *)-1,"osal_stat_msgq");
    real_media_open = real_dlsym((void *)-1,"mcmn_drv_open");
    real_allocate_msg = real_dlsym((void *)-1, "osal_valloc_msg_wait");
    real_free_msg = real_dlsym((void *)-1, "osal_free_msg");
    real_get_source = real_dlsym((void *)-1, "osal_get_msg_src");
    real_set_source = real_dlsym((void *)-1, "osal_set_msg_src");
    real_msg_size = real_dlsym((void *)-1, "osal_msg_size");
    real_rcv_msg_tmo = real_dlsym((void *)-1, "osal_rcv_msg_tmo");
    real_dladdr = real_dlsym((void *)-1, "dladdr");
    capid_enabled = getenv("QEMU_CAPID_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    (void)0;
    sa_address_enabled = getenv("QEMU_SA_ADDRESS_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    hdmi_format_enabled = getenv("QEMU_HDMI_FORMAT_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    hdmi_photo_enabled = getenv("QEMU_HDMI_PHOTO_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    display_info_enabled = getenv("QEMU_DISPLAY_INFO_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    subscription_enabled = getenv("QEMU_SUBSCRIPTION_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    sequence_event_enabled = getenv("MENU_SEQ_EVENT") && !getenv("MENU_OBSERVE_SELFTEST");
    bb_ready_inject_enabled = getenv("MENU_BB_READY_INJECT") && !getenv("MENU_OBSERVE_SELFTEST");
    if (display_info_enabled && !getenv("MENU_OBSERVE_SELFTEST")) {
        const char *size = getenv("QEMU_DISPLAY_SIZE");
        const char *aspect = getenv("QEMU_DISPLAY_ASPECT");
        unsigned int panel_width = 0, panel_height = 0, evf_width = 0, evf_height = 0, panel_aspect = 0, evf_aspect = 0;
        if (size && sscanf(size, "%ux%u,%ux%u", &panel_width, &panel_height, &evf_width, &evf_height) == 4 &&
            panel_width && panel_height && evf_width && evf_height && panel_width < 8192 && evf_width < 8192) {
            virtual_display.panel_width = panel_width;
            virtual_display.panel_height = panel_height;
            virtual_display.evf_width = evf_width;
            virtual_display.evf_height = evf_height;
        }
        if (aspect && sscanf(aspect, "%u,%u", &panel_aspect, &evf_aspect) == 2 &&
            panel_aspect <= 3 && evf_aspect <= 3) {
            virtual_display.panel_aspect = panel_aspect;
            virtual_display.evf_aspect = evf_aspect;
        }
        char text[120];
        snprintf(text, sizeof text, "reported panel=%ux%u aspect=%u evf=%ux%u aspect=%u",
                 virtual_display.panel_width, virtual_display.panel_height, virtual_display.panel_aspect,
                 virtual_display.evf_width, virtual_display.evf_height, virtual_display.evf_aspect);
        record("DISPLAY_INFO_GEOMETRY ", text);
    }
    dmm_enabled = getenv("QEMU_DMM_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    software_gpe = getenv("QEMU_SOFTWARE_GPE") && !getenv("MENU_OBSERVE_SELFTEST");
    software_rgba4444 = software_gpe && getenv("QEMU_GPE_RGBA4444");
    headless_osd_enabled = getenv("MENU_HEADLESS_OSD") &&
        same_name(getenv("MENU_HEADLESS_OSD"), "1") && !getenv("MENU_OBSERVE_SELFTEST");
    if (!memory_log && !getenv("MENU_OBSERVE_SELFTEST")) {
        int fd = open("/dev/mem", 2);
        if (fd >= 0) {
            void *area = mmap(0, 65536, 3, 1, fd, 0x4102d0000UL);
            if (area != (void *)-1) memory_log = area;
            if (capid_enabled) {
                capid.address = 0x4102e0000ULL; /* dedicated test reservation, not a real CP address */
                area = mmap(0, 0x5000, 3, 1, fd, (unsigned long)capid.address);
                if (area != (void *)-1) {
                    capid.table = area;
                    unsigned char *bytes = area;
                    for (size_t i = 0; i < sizeof *capid.table; ++i) bytes[i] = 0;
                }
            }
            close(fd);
        }
    }
    if (dmm_enabled) {
        char arguments[4097] = {0};
        int fd = open("/proc/cmdline", 0);
        if (fd >= 0) { long count = read(fd, arguments, 4096); if (count > 0) arguments[count] = 0; close(fd); }
        fd = strstr(arguments, "memrsv=0x00100000@0x41e000000:uc") ? open("/dev/mem", 2) : -1;
        if (fd >= 0) {
            void *area = mmap(0, DMM_TEST_SIZE, 3, 1, fd, DMM_TEST_PHYSICAL);
            if (area != (void *)-1) { dmm.memory = area; dmm.physical = DMM_TEST_PHYSICAL; }
            close(fd);
        }
        record("DMM_SERVICE_INIT ", dmm.memory ? "pool=0x41e000000 CP=0x1e000000 slots=2 size=0x80000" : "pool unavailable");
    }
    int command = open("/proc/self/cmdline", 0);
    if (command >= 0) {
        char text[257];
        long length = read(command, text, 256);
        close(command);
        if (length > 0) {
            for (long i = 0; i < length; ++i) if (!text[i]) text[i] = ' ';
            text[length] = 0;
            record("PROGRAM_ARGS ", text);
        }
    }
}
static void record(const char *prefix, const char *name) {
    /* Mirror a few high-value prefixes to stderr so they survive a guest abort: the console capture
       keeps them even when diag.sh never runs. */
    if (prefix) {
        static const char *mirrored[] = {
            "FULL_HDMIPIN_",
            "FULL_OSDPIN_",
            "FULL_AUDIO_",
            "FULL_DIG_LEVEL_",
            "FULL_DMM_UNIT_",
            "NATIVE_CP_BACKGROUND_",
            "FULL_MEDIA_MOUNT_", "KEY_DIAG ",
            "FULL_RM_FILE_",
            "GUI_PROPERTY_",
            "GUI_MODEL_",
            "BT_ERROR_",
            "POWER_", "SHUTDOWN_", "SD_ACK_",
            "INPUT_EVENT32 ",
            "OSD_SUBMIT_MODE ",
            "MODE_ICON_VALUE ", "MODE_ICON_CONSUMER ",
            "FULL_DRAWINFO_",
            "FULL_PIN_",
            "SEQ_FINISH_LIMIT ", "PIN_QUERY ", "PIN_CONTROL_REQUEST ", "FULL_INFRABB_", "FULL_VEF_", "FULL_PINMEM_", "FULL_SCALAR_", "FULL_ADF_",
            "FULL_HDMI_", "FULL_VDF_", "PIPELINE_REQ ", "PIPELINE_REPLY ", "PIPELINE_VREQ ", "PIPELINE_VREPLY ", "PIPELINE_VFAIL ", "PIPELINE_ARM ", "PIPELINE_ARM_FAILED ", "PIPELINE_FAILED ", "PIPELINE_NO_REPLY ", "APPLOG ", "APPFW_LOG ", "DATE_ADD_CALL ", "OPT_WORKER_ENTER ", "OPT_SEND_ENTER ", "OPT_READY ", "ASSERT_CALLER ", "NULL_OBJ_SITE ", "BOOT_FACTOR_BRANCH ", "BOOT_POST_EE ", "HONEST_HOOK ", "HONEST_HOOK_FAILED ", "HONEST_ROUTE ", "HONEST_ROUTE_SYNC ", "REG_747 ", "SHOOTING_ENTER ", "RUN_I_RET ", "RUN_I_GATE ", "SEQ4BD_CREATE ", "SEQ4BD_STAGE ", "SEQ4BD_MADE ", "KEY_INJECT ", "OBJ_DISPATCH ", "BOOT_FULFIL ", "SYNC_CALL ", "SYNC_MSG ", "AVBBC ", "BUSPOWER ", "CRYPT_LIB ", "CP_TIME_SERVICE ", "CP_RELEASE_SERVICE ", "XFer_REQ ", "ASYNC_SEND ", "SEQ_BOOT_RUN_ENTER ", "SEQ_QUEUE_LOOP ", "SEQ_DEP_WAIT ", "SEQ_DEQUEUE ", "BOOT_SEQ_STEP ", "SEQ_FACTORY ", "SEQ_BOOT_CTOR ", "SEQ_FINISH ", "POOL_WORKER ", "ENTRY_PROBE_", "SYNC_DIRECT ", "MENU_CONTROLLER_SEEN ", "MENU_CTOR_PROBE", "BUILD2_", "MENU_INIT_SKIPPED ", "MODE_SENTINELS", "MODE_SLOT ", "MODE_SLOT4 ", "POINTER_SCAN ", "MODE_ACTIVATE", "FORCE_OPEN_", "FORCE_OPEN_FIELDS ", "FORCE_OPEN_SKIPPED ", "OBSERVER_READY ", "FORCE_SET_ENTER ", "MENU_BUILD_", "MENU_OPEN_", "MENU_INIT_", "MENU_APPLY_", "MANAGER_", "FORCE_SET_BEGIN ", "FORCE_SET ", "CREATE_SCREEN_", "VIEW_SLOT_CALLED ", "FACTORY_CALL ", "CTOR_", "BLIT", "OPEN_SET", "SCREEN_REGISTRY", "OSD_", "FRAME_", "VIEW_CONTENT", "RESOURCE_", "GPE_RGBA_" };
        for (unsigned int i = 0; i < sizeof mirrored / sizeof mirrored[0]; ++i) {
            const char *want = mirrored[i];
            unsigned int k = 0;
            while (want[k] && prefix[k] == want[k]) ++k;
            if (!want[k]) {
                char line[768];
                int n = snprintf(line, sizeof line, "OBS %s%s\n", prefix, name ? name : "");
                if (n > 0) {
                    if ((unsigned int)n >= sizeof line) n = sizeof line - 1;
                    /* stderr is redirected into /tmp/im.log by the launcher, so mirror into the kernel
                       log instead: /dev/kmsg lines land in the console capture even if the guest aborts. */
                    static int kmsg = -2;
                    /* /dev/kmsg drops messages under printk_ratelimit; /dev/console does not. */
                    if (kmsg == -2) kmsg = open("/dev/console", 1);
                    if (kmsg >= 0) { long ignored = write(kmsg, line, (unsigned long)n); (void)ignored; }
                    else { long ignored = write(2, line, (unsigned long)n); (void)ignored; }
                }
                break;
            }
        }
    }
#ifdef MENU_OBSERVE_TRANSPORT_SELFTEST
    return;
#endif
    if (!name) return;
    size_t length = 0, plen = 0;
    while (name[length] && length < 1024) ++length;
    while (prefix[plen]) ++plen;
    if (memory_log) {
        unsigned int count = (unsigned int)(plen + length + 1);
        unsigned int offset = __atomic_fetch_add((unsigned int *)memory_log, count,
                                                 __ATOMIC_RELAXED) + 8;
        if (offset + count < 65536) {
            for (size_t i = 0; i < plen; ++i) memory_log[offset + i] = prefix[i];
            for (size_t i = 0; i < length; ++i) memory_log[offset + plen + i] = name[i];
            memory_log[offset + count - 1] = '\n';
        }
    }
    int fd = open("/tmp/menu-load.log", 0x441, 0644);
    if (fd >= 0) {
        write(fd, prefix, plen); write(fd, name, length);
        write(fd, "\n", 1); close(fd);
    }
}
void *dlopen(const char *name, int flags) {
    if (!real_dlopen) initialize();
    record("BEGIN ", name);
    if (flags & 8) { /* RTLD_DEEPBIND hides a library's osal IPC calls from these hooks; strip it. */
        char text[100];
        snprintf(text, sizeof text, "stripped DEEPBIND for %s (requested=%#x)", name, flags);
        record("LOADER_DEEPBIND ", text);
        flags &= ~8;
    }
    if (same_name(name, "libgpe.so") || same_name(name, "/usr/lib/libgpe.so")) {
        char text[100];
        snprintf(text, sizeof text, "requested=%#x effective=%#x software=%d", flags, flags, software_gpe);
        record("GPE_LOADER_FLAGS ", text);
    }
    void *handle = real_dlopen(name, flags);
    if(handle && !__atomic_load_n(&real_bt_error_place,__ATOMIC_ACQUIRE)) {
        void *method=real_dlsym(handle,"_ZN8BTUtils_6BTBlog10errorPlaceEtj");
        if(method && method!=(void *)observe_bt_error_place)
            __atomic_store_n(&real_bt_error_place,(void (*)(void *,unsigned short,unsigned int))method,__ATOMIC_RELEASE);
    }
    record(handle ? "LOADED " : "FAILED ", name);
    if(handle && (same_name(name,"libInfraMediaCommon.so") || same_name(name,"/usr/lib/libInfraMediaCommon.so") ||
                  same_name(name,"libInfraFsys.so") || same_name(name,"/usr/lib/libInfraFsys.so"))) {
        void *method=real_dlsym(handle,"mcmn_drv_open");
        if(method && method!=(void *)mcmn_drv_open)
            __atomic_store_n(&real_media_open,(unsigned int (*)(const char *,unsigned int,void **))method,__ATOMIC_RELEASE);
    }
    if(handle && rm_file_enabled && (same_name(name,"libInfraMediaCommon.so") || same_name(name,"/usr/lib/libInfraMediaCommon.so"))) {
        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,real_send_msg,real_msg_size,real_get_source,record};
        int rc=native_rm_file_start("/image_mmca","/tmp/rm-file.claim",&io,real_reg_async,real_unreg_async,real_stat_msgq);
        char text[120];snprintf(text,sizeof text,"result=%d default_off=1 file_backend_global_nand_unsupported=1",rc);
        record(rc?"FULL_RM_FILE_FAILED ":"FULL_RM_FILE_BOUND ",text);
    }
    if (handle && (getenv("MENU_FRAME_OBSERVE") || headless_osd_enabled) &&
        (same_name(name, "libObj.so") || same_name(name, "/usr/lib/libObj.so"))) {
        real_notify_draw = real_dlsym(handle, "_ZN2ux6wgtsys12WidgetSystem10notifyDrawEv");
        real_draw_framebuffer = real_dlsym(handle, "_ZN2ux6gfxeng14GraphicsEngine15drawFramebufferEv");
        start_headless_osd();
    }
    if (handle && getenv("MENU_OSD_OBSERVE") &&
        (same_name(name, "libObj.so") || same_name(name, "/usr/lib/libObj.so")))
        install_osd_observers(handle);
    if (handle && (same_name(name, "libInfraKikiLogGenerator.so") ||
                   same_name(name, "/usr/lib/libInfraKikiLogGenerator.so"))) {
        void *notify = real_dlsym(handle, "kikilog_set_notify_cb");
        if (notify) real_kikilog_notify = notify;
    }
    if (handle && (same_name(name, "libgpe.so") || same_name(name, "/usr/lib/libgpe.so"))) {
        real_gpe_fill = real_dlsym(handle, "_ZN5mpgpe13GpermFillRectENS_3GpeENS_7IntCoreEPjRKNS_13FillRectParamE");
        real_gpe_blit = real_dlsym(handle, "_ZN5mpgpe12GpermBitBlitENS_3GpeENS_7IntCoreEPjRKNS_12BitBlitParamE");
        real_worker_fill = real_dlsym(handle, "_ZN5mpgpe8FillRectENS_3GpeENS_7IntCoreEjjRKNS_13FillRectParamE");
        real_worker_blit = real_dlsym(handle, "_ZN5mpgpe7BitBlitENS_3GpeENS_7IntCoreEjjRKNS_12BitBlitParamE");
        real_worker_flush = real_dlsym(handle, "_ZN5mpgpe5FlushENS_3GpeENS_7IntCoreEjjRKNS_10FlushParamE");
        real_draw_complete = real_dlsym(handle, "_ZN5mpgpe7message12SendDrawCompEjPKvm");
        real_draw_initialize = real_dlsym(handle, "_ZN5mpgpe14InitializeDrawENS_3GpeE");
        real_gperm_initialize = real_dlsym(handle, "_ZNK5mpgpe5Gperm4InitEv");
        if (software_gpe && real_gpe_fill) {
            unsigned long base = (unsigned long)real_gpe_fill - 0xa758;
            char text[180];
            snprintf(text, sizeof text, "init=%#lx fill=%#lx blit=%#lx",
                     *(unsigned long *)(base + 0x29670), *(unsigned long *)(base + 0x29680), *(unsigned long *)(base + 0x29160));
            record("GPE_WORKER_BIND_BEFORE ", text);
            if (mprotect((void *)(base + 0x29000), 4096, 3) == 0) {
                *(unsigned long *)(base + 0x29670) = (unsigned long)software_draw_initialize;
                *(unsigned long *)(base + 0x29680) = (unsigned long)software_fill_worker;
                *(unsigned long *)(base + 0x29160) = (unsigned long)software_blit_worker;
                *(unsigned long *)(base + 0x29540) = (unsigned long)software_gperm_initialize;
                *(unsigned long *)(base + 0x29110) = (unsigned long)software_flush_worker;
                record("GPE_WORKER_BIND ", "five verified PLT slots mapped to actual CPU raster backend; files unchanged");
            } else record("GPE_WORKER_BIND_FAILED ", "GOT page cannot be made writable");
        }
    }
    return handle;
}
void observe_bt_error_place(void *self,unsigned short group,unsigned int line) {
    int saved=*__errno_location();char text[260];
    unsigned long *frame=__builtin_frame_address(0),fp=frame[0];
    Dl_info info={0};if(real_dladdr)real_dladdr(__builtin_return_address(0),&info);
    snprintf(text,sizeof text,"group=%#x line=%u caller=%s+%#lx fp=%#lx",group,line,
             info.dli_fname?info.dli_fname:"unknown",info.dli_fbase?(unsigned long)__builtin_return_address(0)-(unsigned long)info.dli_fbase:0,fp);
    record("BT_ERROR_PLACE ",text);
    if(fp>=(unsigned long)frame && fp-(unsigned long)frame<0x40000) {
        int fd=open("/proc/self/mem",0);unsigned char bytes[0xd0];
        if(fd>=0 && pread(fd,bytes,sizeof bytes,(long)(fp+0x40))==sizeof bytes) {
            for(unsigned int offset=0;offset<sizeof bytes;offset+=64) {
                unsigned int n=sizeof bytes-offset;if(n>64)n=64;char raw[129];
                for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",bytes[offset+i]);
                snprintf(text,sizeof text,"line=%u fp_offset=%u raw=%s",line,0x40+offset,raw);
                record("BT_ERROR_STACK ",text);
            }
        }
        if(fd>=0)close(fd);
    }
    *__errno_location()=saved;
    void (*original)(void *,unsigned short,unsigned int)=__atomic_load_n(&real_bt_error_place,__ATOMIC_ACQUIRE);
    if(!original)original=real_dlsym((void *)-1,"_ZN8BTUtils_6BTBlog10errorPlaceEtj");
    if(!original || original==observe_bt_error_place)__builtin_trap();
    original(self,group,line);
}
/* appFw reaches uxengine_init2 through its own lazy PLT stub at appFw+0x165fe30
   (R_AARCH64_JUMP_SLOT at appFw+0x5bc2720, verified in the original file). The stub
   is rewritten to an indirect jump through this wrapper so entry and return are
   directly observable. The library file is not modified; the loaded text page is
   patched in place after the expected stub bytes are verified. */
static void *observe_uxengine_init2(void *argument) {
    record("ENTER ", "uxengine_init2");
    void *result = real_uxengine_init2(argument);
    record("RETURN ", "uxengine_init2");
    return result;
}
/* No libgcc __clear_cache/outline-atomics helpers in this guest root, so the
   instruction cache is maintained with the architectural maintenance ops. */
static void clear_cache_range(void *start, size_t length) {
    unsigned long ctr;
    unsigned long step;
    unsigned long address = (unsigned long)start & ~63UL;
    unsigned long end = (unsigned long)start + length;
    __asm__ __volatile__("mrs %0, ctr_el0" : "=r"(ctr));
    step = 4UL << ((ctr >> 16) & 0xf);
    if (!step) step = 64;
    __asm__ __volatile__("dsb ish" ::: "memory");
    for (; address < end; address += step)
        __asm__ __volatile__("ic ivau, %0" :: "r"(address) : "memory");
    __asm__ __volatile__("dsb ish; isb" ::: "memory");
}
static unsigned int patch_uxengine_init2(unsigned long base) {
    unsigned char *stub = (unsigned char *)(base + 0x165fe30UL);
    unsigned long page = (unsigned long)stub & ~0xfffUL;
    unsigned int expected[2] = {0xf0022b10u, 0xf9439211u}; /* adrp x16,#0x5bc2000 ; ldr x17,[x16,#0x720] */
    unsigned int jump[2] = {0x58000051u, 0xd61f0220u};   /* ldr x17, #8 ; br x17 */
    unsigned long target = (unsigned long)observe_uxengine_init2;
    if (!real_uxengine_init2) {
        void *symbol = real_dlsym(0, "uxengine_init2");
        if (!symbol) return 2;
        real_uxengine_init2 = symbol;
    }
    if (*(unsigned int *)stub != expected[0] || *(unsigned int *)(stub + 4) != expected[1]) return 3;
    if (mprotect((void *)page, 4096, 7) != 0) return 4;
    ((unsigned int *)stub)[0] = jump[0];
    ((unsigned int *)stub)[1] = jump[1];
    for (int i = 0; i < 8; ++i) stub[8 + i] = (unsigned char)(target >> (8 * i));
    clear_cache_range(stub, 16);
    if (mprotect((void *)page, 4096, 5) != 0) return 5;
    return 1;
}
/* Zero-injection sentinel for "did the model ever create a screen?". The view vtable is at
   RUNTIME VA base+0x58dbf38 (its file offset is 0x58cbf38: everything from .data.rel.ro onward is
   mapped +0x10000 in memory, so the earlier sentinel at 0x58cbf38 landed on a plain data table and
   could never fire - see force-screen/REPORT.md section 0). .rela.dyn confirms
   *0x58dbf38 = base+0x17cdb00 = view::create_screen, so slot 0 is patched here; replacing that slot with this wrapper
   logs the call without touching any library file or guest state. Signature per the debug name:
   virtual void view::create_screen(int, const ds_create_screen_param*, size_t,
                                    display_orientation_t, const bool*, const char*, const uint32_t*);
   - so the first eight integer arguments are forwarded verbatim. */
static void *(*real_create_screen)(void *, void *, void *, void *, void *, void *, void *, void *);
/* Read-only reconnaissance of the screen factory table. The dispatcher 0x1e4bacc loads its base
   from the GOT slot VA 0x5b4cfd0 -> VA 0x51f7810 and indexes 96-byte entries (per force-screen/REPORT.md
   section 2); entry+0x00 is the factory and entry+0x10 the numeric screen id. The real device's screen
   id counter sits at 604/605, so ids in 480..700 are the menu candidates. No writes, no calls. */
static void dump_factory_table(void) {
    if (!appfw_base) return;
    const unsigned char *table = (const unsigned char *)(appfw_base + 0x51f7810UL);
    unsigned int total = 0, shown = 0;
    for (unsigned int i = 0; i < 864; ++i) {
        const unsigned char *entry = table + (unsigned long)i * 96;
        unsigned long fn = *(const unsigned long *)entry;
        unsigned int id = *(const unsigned int *)(entry + 0x10);
        if (!fn) continue;
        ++total;
        if (id < 480 || id > 700) continue;
        char text[160];
        snprintf(text, sizeof text, "idx=%u fn=appFw+%#lx id=%u", i, fn - appfw_base, id);
        record("FACTORY_ENTRY ", text);
        if (++shown >= 60) break;
    }
    /* The id field at +0x10 is zero in the file image (the loader fills it), so the only way to learn
       the real screen ids is to read the table at runtime. Emit every id compactly: 12 per line. */
    char line[160];
    unsigned int written = 0;
    line[0] = 0;
    for (unsigned int i = 0; i < 864; ++i) {
        const unsigned char *entry = table + (unsigned long)i * 96;
        if (!*(const unsigned long *)entry) continue;
        unsigned int id = *(const unsigned int *)(entry + 0x10);
        char piece[16];
        int n = snprintf(piece, sizeof piece, "%s%u", written ? "," : "", id);
        if (n <= 0) break;
        for (int k = 0; piece[k]; ++k) line[written++] = piece[k];
        if (written > sizeof line - 24) {
            line[written] = 0;
            record("FACTORY_IDS ", line);
            written = 0;
            line[0] = 0;
        }
    }
    if (written) { line[written] = 0; record("FACTORY_IDS ", line); }
    char text[128];
    snprintf(text, sizeof text, "scanned=864 non_null=%u logged=%u (id window 480..700)", total, shown);
    record("FACTORY_TABLE ", text);
}
/* Injectable BB/CP event sequence aimed at the task_main thread (queue [appFw+0x910fa20]).
   bb-events/REPORT.md decoded that switch: only {frame=0x200d, code=0x1148} calls
   promise set_value (hash node 0x910f960), 0x1118 pushes internal event 0xd1 and 0x132b pushes 0x75
   while decrementing [0x910fa24]. Inject them in order and log the surrounding state so we can see
   whether any waiting caller wakes up. */
static void log_app_state(const char *tag) {
    if (!appfw_base) return;
    char text[256];
    snprintf(text, sizeof text,
             "%s promise_flag=%lu promise_ptr=%#lx hash_910f960=%#lx counter_910fa24=%lu hm_910fa1c=%#x tm_910fa20=%#x",
             tag,
             (unsigned long)*(volatile unsigned int *)(appfw_base + 0x910f9fc),
             (unsigned long)*(volatile unsigned long *)(appfw_base + 0x910fa00),
             (unsigned long)*(volatile unsigned long *)(appfw_base + 0x910f960),
             (unsigned long)*(volatile unsigned int *)(appfw_base + 0x910fa24),
             *(volatile unsigned int *)(appfw_base + 0x910fa1c),
             *(volatile unsigned int *)(appfw_base + 0x910fa20));
    record("APP_STATE ", text);
}
static int deliver_bb_event(unsigned int queue, unsigned int frame, unsigned int code, unsigned int extra) {
    void *msg = 0;
    if (real_allocate_msg(queue, &msg, 48, 1)) return -1;
    unsigned char *b = msg;
    for (int i = 0; i < 48; ++i) b[i] = 0;
    b[0] = frame & 0xff; b[1] = frame >> 8;
    b[2] = code & 0xff; b[3] = code >> 8;
    b[4] = 48; b[5] = 1;
    b[6] = extra & 0xff; b[7] = (extra >> 8) & 0xff;
    real_set_source(msg, 0x91ca0816);
    int result = real_send_msg(queue, msg);
    char text[128];
    snprintf(text, sizeof text, "frame=%#x code=%#x to queue %#x result=%d", frame, code, queue, result);
    record(result ? "TASK_MAIN_EVENT_FAILED " : "TASK_MAIN_EVENT ", text);
    if (result) real_free_msg(queue, msg);
    return result;
}
static void task_main_probe(void) {
    if (!appfw_base || !real_allocate_msg || !real_send_msg || !real_set_source || !real_free_msg) return;
    unsigned int queue = *(volatile unsigned int *)(appfw_base + 0x910fa20);
    if (!queue) { record("TASK_MAIN_EVENT ", "queue [0x910fa20] is zero"); return; }
    log_app_state("before");
    deliver_bb_event(queue, 0x200d, 0x1148, 0);
    log_app_state("after_1148");
    deliver_bb_event(queue, 0x200d, 0x1118, 0);
    log_app_state("after_1118");
    deliver_bb_event(queue, 0x200d, 0x132b, 0);
    log_app_state("after_132b");
}
/* Direct render poke: the model builds 28 screens but nothing is ever painted (the software GPE only
   sees one 640x480 fill and a flush). WidgetSystem is the ux widget root; driving its draw entry after
   the screens exist is the cheapest way to find out whether a populated widget tree can paint at all. */
/* The dispatcher's third argument is *(mgr+0x38) for idx <= 0x35f, so the value our factory hook sees
   cannot be turned back into mgr. The one function that receives the real manager (mov x22, x0 at
   0x1e770f0) is at 0x1e770e4 and is called from a single site. Patch its entry with a 16-byte stub
   (ldr x16,#8 / br x16 / .quad trampoline) and have the trampoline capture x0, replay the original
   prologue and continue at 0x1e770e4+16. Loaded literally, so no +-128 MB branch range limit. */
static unsigned long captured_manager;
static void *manager_continue_address;
/* An entry probe must preserve the original LR and all ABI argument registers across its C call. */
#define PROBE_SAVE_ARGS \
"    sub sp, sp, #0xe0\n" \
"    stp x0, x1, [sp, #0]\n" \
"    stp x2, x3, [sp, #16]\n" \
"    stp x4, x5, [sp, #32]\n" \
"    stp x6, x7, [sp, #48]\n" \
"    stp x8, x30, [sp, #64]\n" \
"    stp q0, q1, [sp, #80]\n" \
"    stp q2, q3, [sp, #112]\n" \
"    stp q4, q5, [sp, #144]\n" \
"    stp q6, q7, [sp, #176]\n" \
"    mrs x16, nzcv\n" \
"    str x16, [sp, #208]\n"
#define PROBE_RESTORE_ARGS \
"    ldr x16, [sp, #208]\n" \
"    msr nzcv, x16\n" \
"    ldp q6, q7, [sp, #176]\n" \
"    ldp q4, q5, [sp, #144]\n" \
"    ldp q2, q3, [sp, #112]\n" \
"    ldp q0, q1, [sp, #80]\n" \
"    ldp x8, x30, [sp, #64]\n" \
"    ldp x6, x7, [sp, #48]\n" \
"    ldp x4, x5, [sp, #32]\n" \
"    ldp x2, x3, [sp, #16]\n" \
"    ldp x0, x1, [sp, #0]\n" \
"    add sp, sp, #0xe0\n"
void capture_manager(unsigned long candidate) {
    captured_manager = candidate;
    char text[128];
    snprintf(text, sizeof text, "manager=%#lx (captured at 0x1e770e4 entry)", candidate);
    record("MANAGER_CAPTURED ", text);
}
__asm__(
".text\n"
".globl manager_probe_trampoline\n"
".type manager_probe_trampoline, %function\n"
"manager_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_manager\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-0x80]!\n"      /* 原函数前 4 条指令 */
"    mov x29, sp\n"
"    stp x21, x22, [sp, #0x20]\n"
"    mov x22, x0\n"
"    adrp x16, manager_continue_address\n"
"    ldr x16, [x16, #:lo12:manager_continue_address]\n"
"    br x16\n"
);
extern void manager_probe_trampoline(void);
/* Entry probes for the natural boot chain. sequence_boot::run (0x305e9b8) is the model sequence the
   UI future in boot_start_seq waits on; 0x368059c / 0x36804c8 are appFw's own loggers, which are the
   only visible trace of what a sequence body actually did (the firmware ships that text to kikilog).
   Each probe patches 16 bytes of the loaded text page: ldr x16,[pc,#8] / br x16 / .quad trampoline.
   The trampoline saves every ABI argument register, calls one C recorder, restores them, then replays
   the overwritten prologue instructions and continues at entry+16. Nothing is skipped or forced. */
static void *seq_run_continue, *log_varargs_continue, *log_valist_continue, *pool_worker_continue, *seq_finish_continue;
static void *bootseq_continue, *bootfactory_continue, *bootctor_continue;
static void *queue_loop_continue, *dep_wait_continue, *xfer_continue, *factor_branch_continue, *post_ee_continue, *run_i_gate_continue, *run_i_gate_long, *seq4bd_continue, *seq4bd_req_continue, *seq4bd_make_continue, *null_obj_continue;
/* Read by the entry trampolines to rebuild position-dependent instructions (adrp). */
unsigned long observe_appfw_base;
static unsigned int seq_run_seen, log_seen;
void capture_seq_boot_run(unsigned long this_object) {
    seq_run_seen = 1;
    char text[160];
    snprintf(text, sizeof text, "this=%#lx caller=%p", this_object, __builtin_return_address(0));
    record("SEQ_BOOT_RUN_ENTER ", text);
}
static void format_string_at(unsigned long pointer, char *out, unsigned int capacity) {
    unsigned int n = 0;
    out[0] = 0;
    if (!appfw_base || pointer <= appfw_base || pointer - appfw_base >= 0xa00000UL) return;
    const char *source = (const char *)pointer;
    while (n + 1 < capacity && source[n] >= 0x20 && source[n] < 0x7f) { out[n] = source[n]; ++n; }
    out[n] = 0;
}
void capture_appfw_log_varargs(unsigned long level, unsigned long format, unsigned long caller,
                                unsigned long a2, unsigned long a3, unsigned long a4) {
    if (log_seen < 400) {
        char text[224], fmt[72];
        format_string_at(format, fmt, sizeof fmt);
        snprintf(text, sizeof text, "lv=%lu tid=%ld caller=appFw+%#lx fmt=\"%s\" a2=%#lx a3=%#lx a4=%#lx",
                 level, syscall(178), (unsigned long)(caller - appfw_base), fmt,
                 a2, a3, a4);
        record("APPFW_LOG ", text);
    }
    ++log_seen;
}
void capture_appfw_log_valist(unsigned long format, unsigned long a1, unsigned long caller,
                               unsigned long a2, unsigned long a3, unsigned long a4) {
    if (log_seen < 400) {
        char text[224], fmt[72];
        char s1[48], s2[48];
        format_string_at(format, fmt, sizeof fmt);
        format_string_at(a1, s1, sizeof s1);
        format_string_at(a2, s2, sizeof s2);
        /* The caller keeps the printf arguments in x1..x4, so a3/a4 are the numeric ones
           (line number and the error code of "%s%s(%d) Error: [0x%08X]"). */
        snprintf(text, sizeof text,
                 "tid=%ld caller=appFw+%#lx fmt=\"%s\" s1=\"%s\" s2=\"%s\" n3=%lu code=%#lx",
                 syscall(178), (unsigned long)(caller - appfw_base), fmt, s1, s2, a3, a4);
        record("APPFW_LOG ", text);
    }
    ++log_seen;
}
__asm__(
".text\n"
".globl seq_run_probe_trampoline\n"
".type seq_run_probe_trampoline, %function\n"
"seq_run_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_seq_boot_run\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9b77bfd\n"          /* stp x29,x30,[sp,#-0x90]!  (verified original) */
"    .inst 0x910003fd\n"          /* mov x29,sp */
"    .inst 0xa90153f3\n"          /* stp x19,x20,[sp,#16] */
"    adrp x16, :got:observe_appfw_base\n"
"    ldr x16, [x16, :got_lo12:observe_appfw_base]\n"
"    movz x17, #0x4000\n"
"    movk x17, #0x4c1, lsl #16\n"
"    add x20, x16, x17\n"         /* adrp x20,#0x4c14000 replayed against the real image base */
"    adrp x16, seq_run_continue\n"
"    ldr x16, [x16, #:lo12:seq_run_continue]\n"
"    br x16\n"
".globl log_varargs_probe_trampoline\n"
".type log_varargs_probe_trampoline, %function\n"
"log_varargs_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    ldr x3, [sp, #16]\n"      /* original x2 */
"    ldr x4, [sp, #24]\n"      /* original x3 */
"    ldr x5, [sp, #32]\n"      /* original x4 */
"    mov x2, x30\n"            /* caller */
"    bl capture_appfw_log_varargs\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-0x130]!\n"
"    mov x29, sp\n"
"    stp x19, x20, [sp, #0x10]\n"
"    sxth w20, w0\n"
"    adrp x16, log_varargs_continue\n"
"    ldr x16, [x16, #:lo12:log_varargs_continue]\n"
"    br x16\n"
".globl log_valist_probe_trampoline\n"
".type log_valist_probe_trampoline, %function\n"
"log_valist_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    ldr x3, [sp, #16]\n"      /* original x2 */
"    ldr x4, [sp, #24]\n"      /* original x3 */
"    ldr x5, [sp, #32]\n"      /* original x4 */
"    mov x2, x30\n"
"    bl capture_appfw_log_valist\n"
PROBE_RESTORE_ARGS
"    sub sp, sp, #0x200\n"
"    stp x29, x30, [sp, #-32]!\n"
"    mov x29, sp\n"
"    str x19, [sp, #16]\n"
"    adrp x16, log_valist_continue\n"
"    ldr x16, [x16, #:lo12:log_valist_continue]\n"
"    br x16\n"
);
__asm__(
".text\n"
".globl pool_worker_probe_trampoline\n"
".type pool_worker_probe_trampoline, %function\n"
"pool_worker_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_pool_worker\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-32]!\n"
"    mov x29, sp\n"
"    stp x19, x20, [sp, #16]\n"
"    mov x19, x0\n"
"    adrp x16, pool_worker_continue\n"
"    ldr x16, [x16, #:lo12:pool_worker_continue]\n"
"    br x16\n"
".globl seq_finish_probe_trampoline\n"
".type seq_finish_probe_trampoline, %function\n"
"seq_finish_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x2, x30\n"
"    bl capture_seq_finish\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-32]!\n"
"    mov x29, sp\n"
"    stp x19, x20, [sp, #16]\n"
"    mov x19, x1\n"
"    adrp x16, seq_finish_continue\n"
"    ldr x16, [x16, #:lo12:seq_finish_continue]\n"
"    br x16\n"
);
extern void pool_worker_probe_trampoline(void), seq_finish_probe_trampoline(void);
extern void seq_run_probe_trampoline(void), log_varargs_probe_trampoline(void), log_valist_probe_trampoline(void);
static unsigned int pool_worker_seen, seq_finish_seen;
void capture_pool_worker(unsigned long pool, unsigned long id, unsigned long third) {
    if (pool_worker_seen < 16) {
        char text[160];
        snprintf(text, sizeof text, "n=%u pool_or_obj=%#lx id=%lu third=%#lx caller=appFw+%#lx",
                 ++pool_worker_seen, pool, id & 0xffffffffUL, third,
                 (unsigned long)((unsigned long)__builtin_return_address(0) - appfw_base));
        record("POOL_WORKER ", text);
    } else ++pool_worker_seen;
}
void capture_seq_finish(unsigned long group, unsigned long node, unsigned long caller) {
    unsigned int id = node ? *(const unsigned int *)(node + 0x10) : 0xffffffffU;
    unsigned long cookie = node ? *(const unsigned long *)(node + 0x18) : 0;
    unsigned int count = __atomic_add_fetch(&seq_finish_seen, 1, __ATOMIC_RELAXED);
    if (count <= 40 || id == 0x4bd || id == 0x2a) {
        char text[224];
        snprintf(text, sizeof text, "n=%u action=metadata_erase_enter group=%#lx node=%#lx id=%#x cookie=%#lx caller=appFw+%#lx",
                 count, group, node, id, cookie, caller - appfw_base);
        record("SEQ_FINISH ", text);
    }
    if (count == 41)
        record("SEQ_FINISH_LIMIT ", "first 40 general records; 0x2a and 0x4bd remain unbounded; not an object-destruction census");
}
static unsigned int boot_seq_seen, boot_factory_seen, boot_ctor_seen;
void capture_boot_start_seq(unsigned long transaction, unsigned long second, unsigned long third) {
    if (boot_seq_seen++ < 8) {
        char text[160];
        snprintf(text, sizeof text, "n=%u transaction=%#lx second=%#lx third=%#lx",
                 boot_seq_seen, transaction, second, third);
        record("BOOT_SEQ_STEP ", text);
    }
}
void capture_boot_factory(unsigned long manager, unsigned long id, unsigned long payload) {
    if (boot_factory_seen++ < 16) {
        char text[160];
        snprintf(text, sizeof text, "n=%u manager=%#lx id=%#lx payload=%#lx",
                 boot_factory_seen, manager, id & 0xffffffffUL, payload);
        record("SEQ_FACTORY ", text);
    }
}
void capture_boot_ctor(unsigned long object, unsigned long param) {
    if (boot_ctor_seen++ < 16) {
        char text[160];
        snprintf(text, sizeof text, "n=%u object=%#lx param=%#lx promise=%#lx",
                 boot_ctor_seen, object, param, param ? *(unsigned long *)param : 0);
        record("SEQ_BOOT_CTOR ", text);
    }
}
__asm__(
".text\n"
".globl bootseq_probe_trampoline\n"
".type bootseq_probe_trampoline, %function\n"
"bootseq_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_boot_start_seq\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-0xf0]!\n"
"    mov x29, sp\n"
"    stp x19, x20, [sp, #0x10]\n"
"    add x19, x29, #0xd0\n"
"    adrp x16, bootseq_continue\n"
"    ldr x16, [x16, #:lo12:bootseq_continue]\n"
"    br x16\n"
".globl bootfactory_probe_trampoline\n"
".type bootfactory_probe_trampoline, %function\n"
"bootfactory_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_boot_factory\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-32]!\n"
"    mov x29, sp\n"
"    str x19, [sp, #16]\n"
"    mov x19, x0\n"
"    adrp x16, bootfactory_continue\n"
"    ldr x16, [x16, #:lo12:bootfactory_continue]\n"
"    br x16\n"
".globl bootctor_probe_trampoline\n"
".type bootctor_probe_trampoline, %function\n"
"bootctor_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_boot_ctor\n"
PROBE_RESTORE_ARGS
"    sub sp, sp, #0x70\n"
"    stp x29, x30, [sp, #0x10]\n"
"    add x29, sp, #0x10\n"
"    stp x19, x20, [sp, #0x20]\n"
"    adrp x16, bootctor_continue\n"
"    ldr x16, [x16, #:lo12:bootctor_continue]\n"
"    br x16\n"
);
extern void bootseq_probe_trampoline(void), bootfactory_probe_trampoline(void), bootctor_probe_trampoline(void);
static unsigned int queue_loop_seen, dep_wait_seen;
void capture_queue_loop(unsigned long manager, unsigned long group_struct, unsigned long unused) {
    if (queue_loop_seen < 12) {
        char text[176];
        snprintf(text, sizeof text, "n=%u manager=%#lx group=%#lx waiters_now=%#lx",
                 ++queue_loop_seen, manager, group_struct,
                 group_struct ? *(unsigned long *)(group_struct + 0x20) : 0);
        record("SEQ_QUEUE_LOOP ", text);
    } else ++queue_loop_seen;
}
void capture_dep_wait(unsigned long descriptor, unsigned long unused1, unsigned long unused2) {
    if (descriptor && dep_wait_seen < 24) {
        char text[176];
        unsigned long deps = descriptor;
        unsigned long begin = *(unsigned long *)(deps + 0x1a0), end = *(unsigned long *)(deps + 0x1a8);
        unsigned long first = (begin && end > begin) ? *(unsigned int *)(begin + 0x10) : 0xffffffffUL;
        unsigned long second = (begin && end >= begin + 0x30) ? *(unsigned int *)(begin + 0x28) : 0xffffffffUL;
        snprintf(text, sizeof text, "n=%u id=%u deps=%lu first_dep=%lu second_dep=%lu",
                 ++dep_wait_seen, *(unsigned int *)(deps + 8),
                 end > begin ? (end - begin) / 0x18 : 0, first, second);
        record("SEQ_DEP_WAIT ", text);
    } else ++dep_wait_seen;
}
__asm__(
".text\n"
".globl queue_loop_probe_trampoline\n"
".type queue_loop_probe_trampoline, %function\n"
"queue_loop_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_queue_loop\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-0x80]!\n"
"    mov x2, #0x4400\n"
"    mov x29, sp\n"
"    stp x25, x26, [sp, #0x40]\n"
"    adrp x16, queue_loop_continue\n"
"    ldr x16, [x16, #:lo12:queue_loop_continue]\n"
"    br x16\n"
".globl dep_wait_probe_trampoline\n"
".type dep_wait_probe_trampoline, %function\n"
"dep_wait_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_dep_wait\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9bd7bfd\n"          /* stp x29,x30,[sp,#-48]! */
"    .inst 0xb201f3e2\n"          /* mov x2,#0xaaaaaaaaaaaaaaaa */
"    .inst 0xf2955562\n"          /* movk x2,#0xaaab */
"    .inst 0x910003fd\n"          /* mov x29,sp  (was missing: x29 stayed at the caller's frame) */
"    adrp x16, dep_wait_continue\n"
"    ldr x16, [x16, #:lo12:dep_wait_continue]\n"
"    br x16\n"
);
extern void queue_loop_probe_trampoline(void), dep_wait_probe_trampoline(void);
/* 0x3599b68(payload_ptr, payload, w2=destination SID, w3=source id) is the "allocate an async message
   for a destination, then send it" helper. The group-0 sequence worker blocks on the future of one such
   request, so logging the destination here names the subsystem that never answers. Read-only. */
static unsigned int xfer_seen;
void capture_xfer(unsigned long payload_ptr, unsigned long payload, unsigned long destination) {
    if (xfer_seen < 200) {
        char text[192];
        /* Callers of this helper do not all pass a readable payload pointer (one site passes a small
           integer; dereferencing it cost a SEGV at 0xc). Only read when the destination is the CP/lens
           request queue we are studying AND the pointer/length pass a plausibility check; otherwise
           record the registers alone. */
        unsigned int dest = (unsigned int)(destination & 0xffffffffUL);
        char words[64];
        words[0] = 0;
        if (dest == 0x90030001U && payload_ptr >= 0x100000UL && payload_ptr < 0x800000000000UL &&
            payload >= 4 && payload <= 64) {
            const unsigned int *source = (const unsigned int *)payload_ptr;
            unsigned int count = (unsigned int)(payload / 4);
            if (count > 8) count = 8;
            int used = 0;
            for (unsigned int i = 0; i < count && used < (int)sizeof words - 12; ++i)
                used += snprintf(words + used, sizeof words - used, "%s%08x", i ? "," : "", source[i]);
        }
        snprintf(text, sizeof text, "n=%u dest=%#x arg0=%#lx len=%#lx w=%s",
                 ++xfer_seen, dest, payload_ptr, payload, words[0] ? words : "(not-read)");
        record("XFer_REQ ", text);
    } else ++xfer_seen;
}
__asm__(
".text\n"
".globl xfer_probe_trampoline\n"
".type xfer_probe_trampoline, %function\n"
"xfer_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x2, x2\n"
"    bl capture_xfer\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-64]!\n"
"    mov x29, sp\n"
"    stp x19, x20, [sp, #16]\n"
"    mov x19, x1\n"
"    adrp x16, xfer_continue\n"
"    ldr x16, [x16, #:lo12:xfer_continue]\n"
"    br x16\n"
);
extern void xfer_probe_trampoline(void);
/* 0x305b9a0 is the jump-table target for boot factor > 3 (and the shared epilogue): reaching it
   without the run completing means the factor was out of range. Four position-independent
   instructions are replayed; nothing is skipped. */
void capture_factor_branch(unsigned long unused0, unsigned long unused1, unsigned long unused2) {
    record("BOOT_FACTOR_BRANCH ", "reached 0x305b9a0 = factor>3 silent-return epilogue");
}
__asm__(
".text\n"
".globl factor_branch_probe_trampoline\n"
".type factor_branch_probe_trampoline, %function\n"
"factor_branch_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_factor_branch\n"
PROBE_RESTORE_ARGS
"    mov sp, x29\n"
"    ldp x19, x20, [sp, #16]\n"
"    ldp x21, x22, [sp, #32]\n"
"    ldp x23, x24, [sp, #48]\n"
"    adrp x16, factor_branch_continue\n"
"    ldr x16, [x16, #:lo12:factor_branch_continue]\n"
"    br x16\n"
);
extern void factor_branch_probe_trampoline(void);
/* Relocate both CBNZ targets explicitly: the long path requires byte500==0 && byte501!=0.
   The field meanings are not established. Raw branch encodings cannot be moved into this library. */
void capture_run_i_gate(unsigned long x19, unsigned long unused1, unsigned long unused2) {
    char text[192];
    unsigned int a = 0, b = 0;
    if (x19) {
        a = *(volatile unsigned char *)(x19 + 500);
        b = *(volatile unsigned char *)(x19 + 501);
    }
    snprintf(text, sizeof text, "x19=%#lx byte500=%u byte501=%u -> %s", x19, a, b,
             a ? "normal path (0x305bcbc)" : (b ? "long branch (0x305e8b4)" : "normal path (0x305bcbc)"));
    record("RUN_I_GATE ", text);
}
__asm__(
".text\n"
".globl run_i_gate_probe_trampoline\n"
".type run_i_gate_probe_trampoline, %function\n"
"run_i_gate_probe_trampoline:\n"
/* Mid-function observation must also preserve volatile registers not used for ABI arguments. */
"    sub sp, sp, #0x1d0\n"
"    stp x9, x10, [sp, #0]\n"
"    stp x11, x12, [sp, #16]\n"
"    stp x13, x14, [sp, #32]\n"
"    stp x15, x16, [sp, #48]\n"
"    stp x17, x18, [sp, #64]\n"
"    stp q8, q9, [sp, #80]\n"
"    stp q10, q11, [sp, #112]\n"
"    stp q12, q13, [sp, #144]\n"
"    stp q14, q15, [sp, #176]\n"
"    stp q16, q17, [sp, #208]\n"
"    stp q18, q19, [sp, #240]\n"
"    stp q20, q21, [sp, #272]\n"
"    stp q22, q23, [sp, #304]\n"
"    stp q24, q25, [sp, #336]\n"
"    stp q26, q27, [sp, #368]\n"
"    stp q28, q29, [sp, #400]\n"
"    stp q30, q31, [sp, #432]\n"
PROBE_SAVE_ARGS
"    mov x0, x19\n"                /* x19 is callee-saved and NOT part of PROBE_SAVE_ARGS, so the
                                       first capture argument was the caller's x0 (measured: 0). */
"    bl capture_run_i_gate\n"
PROBE_RESTORE_ARGS
"    ldp q30, q31, [sp, #432]\n"
"    ldp q28, q29, [sp, #400]\n"
"    ldp q26, q27, [sp, #368]\n"
"    ldp q24, q25, [sp, #336]\n"
"    ldp q22, q23, [sp, #304]\n"
"    ldp q20, q21, [sp, #272]\n"
"    ldp q18, q19, [sp, #240]\n"
"    ldp q16, q17, [sp, #208]\n"
"    ldp q14, q15, [sp, #176]\n"
"    ldp q12, q13, [sp, #144]\n"
"    ldp q10, q11, [sp, #112]\n"
"    ldp q8, q9, [sp, #80]\n"
"    ldp x17, x18, [sp, #64]\n"
"    ldp x15, x16, [sp, #48]\n"
"    ldp x13, x14, [sp, #32]\n"
"    ldp x11, x12, [sp, #16]\n"
"    ldp x9, x10, [sp, #0]\n"
"    add sp, sp, #0x1d0\n"
"    .inst 0x3947d260\n"          /* ldrb w0,[x19,#500] */
"    cbnz w0, .Lrun_i_gate_normal\n"
"    .inst 0x3947d660\n"          /* ldrb w0,[x19,#501] */
"    cbnz w0, .Lrun_i_gate_long\n"
".Lrun_i_gate_normal:\n"
"    adrp x16, run_i_gate_continue\n"
"    ldr x16, [x16, #:lo12:run_i_gate_continue]\n"
"    br x16\n"
".Lrun_i_gate_long:\n"
"    adrp x16, run_i_gate_long\n"
"    ldr x16, [x16, #:lo12:run_i_gate_long]\n"
"    br x16\n"
);
extern void run_i_gate_probe_trampoline(void);
/* boot_start_seq looks up sequence 0x4bd (model::sequence_still_record); 0x272fdfc skips creation when
   the lookup succeeds, so reaching 0x272fe00 proves the object was ABSENT at that moment. That is the
   object whose missing mutex later turns into pthread_mutex_lock(NULL+0x2a0). Four replayed
   instructions: mov x0,x19 / mov x2,#0 / mov w1,#1 / str wzr,[x29,#208]. */
void capture_seq_4bd_create(unsigned long unused0, unsigned long unused1, unsigned long unused2) {
    record("SEQ4BD_CREATE ", "lookup(0x4bd) returned NULL -> create branch taken at 0x272fe00");
}
__asm__(
".text\n"
".globl seq4bd_probe_trampoline\n"
".type seq4bd_probe_trampoline, %function\n"
"seq4bd_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_seq_4bd_create\n"
PROBE_RESTORE_ARGS
"    .inst 0xaa1303e0\n"          /* mov x0,x19 */
"    .inst 0xd2800002\n"          /* mov x2,#0 */
"    .inst 0x52800021\n"          /* mov w1,#1 */
"    .inst 0xb900d3bf\n"          /* str wzr,[x29,#208] */
"    adrp x16, seq4bd_continue\n"
"    ldr x16, [x16, #:lo12:seq4bd_continue]\n"
"    br x16\n"
);
extern void seq4bd_probe_trampoline(void);
/* These are entry observations only; generic create_sequence hits do not identify a 4bd request. */
void capture_seq4bd_stage(unsigned long stage, unsigned long unused1, unsigned long unused2) {
    char text[96];
    snprintf(text, sizeof text, "stage=%lu reached", stage);
    record("SEQ4BD_STAGE ", text);
}
__asm__(
".text\n"
".globl seq4bd_req_probe_trampoline\n"
".type seq4bd_req_probe_trampoline, %function\n"
"seq4bd_req_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x0, #1\n"
"    bl capture_seq4bd_stage\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9ba7bfd\n"          /* stp x29,x30,[sp,#-96]! */
"    .inst 0x910003fd\n"          /* mov x29,sp */
"    .inst 0xa90153f3\n"          /* stp x19,x20,[sp,#16] */
"    .inst 0xaa0003f4\n"          /* mov x20,x0 */
"    adrp x16, seq4bd_req_continue\n"
"    ldr x16, [x16, #:lo12:seq4bd_req_continue]\n"
"    br x16\n"
);
extern void seq4bd_req_probe_trampoline(void);
__asm__(
".text\n"
".globl seq4bd_make_probe_trampoline\n"
".type seq4bd_make_probe_trampoline, %function\n"
"seq4bd_make_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x0, #2\n"
"    bl capture_seq4bd_stage\n"
PROBE_RESTORE_ARGS
"    .inst 0xd10343ff\n"          /* sub sp,sp,#0xd0 */
"    .inst 0x528005e0\n"          /* mov w0,#0x2f */
"    .inst 0xa9037bfd\n"          /* stp x29,x30,[sp,#48] */
"    .inst 0x9100c3fd\n"          /* add x29,sp,#0x30 */
"    adrp x16, seq4bd_make_continue\n"
"    ldr x16, [x16, #:lo12:seq4bd_make_continue]\n"
"    br x16\n"
);
extern void seq4bd_make_probe_trampoline(void);
/* 0x305bbec is the join run_i takes when it skips the EE-cap block (w21==0). Reaching it proves the
   boot-factor/EE gate was passed and the failure is later in run_i. Four PI instructions replayed. */
void capture_post_ee(unsigned long unused0, unsigned long unused1, unsigned long unused2) {
    record("BOOT_POST_EE ", "reached 0x305bbec (EE block skipped, run_i continues)");
}
__asm__(
".text\n"
".globl post_ee_probe_trampoline\n"
".type post_ee_probe_trampoline, %function\n"
"post_ee_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_post_ee\n"
PROBE_RESTORE_ARGS
"    .inst 0x910503b4\n"          /* add x20,x29,#0x140 */
"    .inst 0x9103c3b5\n"          /* add x21,x29,#0xf0 */
"    .inst 0xaa1503e0\n"          /* mov x0,x21 */
"    .inst 0x910363b9\n"          /* add x25,x29,#0xd8 */
"    adrp x16, post_ee_continue\n"
"    ldr x16, [x16, #:lo12:post_ee_continue]\n"
"    br x16\n"
);
extern void post_ee_probe_trampoline(void);
/* 0x34f0cc0 is where run_i's tail dereferences a NULL object (SEGV at 0x4 in run-dls3qbqa).
   Log the object and the caller before the same instructions execute, then replay them faithfully:
   if the object is still NULL the guest faults exactly as it does without the probe, but we then
   know which call site and which object handle are involved. Numbers only, no speculative reads. */
static unsigned int null_obj_seen;
void capture_null_obj(unsigned long object, unsigned long caller) {
    if (null_obj_seen++ < 8) {
        unsigned long inner = 0, plus8 = 0;
        if (object && object < 0x800000000000UL && object >= 0x100000UL) {
            inner = *(unsigned long *)object;
            plus8 = *(unsigned long *)(object + 8);
        }
        char text[224];
        snprintf(text, sizeof text, "n=%u object=%#lx inner=%#lx obj_plus8=%#lx caller=appFw+%#lx",
                 null_obj_seen, object, inner, plus8,
                 (unsigned long)(caller - appfw_base));
        record("NULL_OBJ_SITE ", text);
    }
}
__asm__(
".text\n"
".globl null_obj_probe_trampoline\n"
".type null_obj_probe_trampoline, %function\n"
"null_obj_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x1, x30\n"
"    bl capture_null_obj\n"
PROBE_RESTORE_ARGS
"    ldr x1, [x0]\n"
"    ldr w2, [x1, #4]\n"
"    sub w2, w2, #2\n"
"    cmp w2, #1\n"
"    adrp x16, null_obj_continue\n"
"    ldr x16, [x16, #:lo12:null_obj_continue]\n"
"    br x16\n"
);
extern void null_obj_probe_trampoline(void);
/* Every probe verifies the four instructions it is about to overwrite against the expected original
   words. A mismatch aborts the patch instead of silently running a replay that does not match the
   real prologue - that exact mistake (replaying the wrong four instructions) cost a whole
   investigation round. */
/* Who called lib::assert::notify_model_system_error? It reaches __assert_fail through appFw's PLT
   (0x165ff80, GOT slot VA 0x5bc27c8). Patching that slot lets us read the *caller of the assert
   helper*: at this point x29 still belongs to 0x35aa4b4's frame, so [x29+8] is its saved LR.
   The real __assert_fail is then tail-called with the original arguments, so the guest aborts
   exactly as it would without the probe. Numbers only. */
void (*g_real_assert_fail)(const char *, const char *, unsigned int, const char *);
static unsigned int assert_seen;
void capture_assert_call(unsigned long expr, unsigned long file, unsigned long line,
                         unsigned long func, unsigned long frame) {
    if (assert_seen++ >= 8) return;
    unsigned long caller = 0;
    if (frame > 0x100000UL && frame < 0x800000000000UL) caller = *(unsigned long *)(frame + 8);
    char text[288], e[48], f[48], n[48];
    format_string_at(expr, e, sizeof e);
    format_string_at(file, f, sizeof f);
    format_string_at(func, n, sizeof n);
    snprintf(text, sizeof text,
             "n=%u caller=appFw+%#lx expr=\"%s\" file=\"%s\" line=%lu func=\"%s\"",
             assert_seen, (unsigned long)(caller - appfw_base), e, f, line & 0xffffffffUL, n);
    record("ASSERT_CALLER ", text);
}
__asm__(
".text\n"
".globl assert_probe_trampoline\n"
".type assert_probe_trampoline, %function\n"
"assert_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x4, x29\n"                 /* frame of lib::assert::notify_model_system_error */
"    bl capture_assert_call\n"
PROBE_RESTORE_ARGS
"    adrp x16, :got:g_real_assert_fail\n"
"    ldr x16, [x16, :got_lo12:g_real_assert_fail]\n"
"    ldr x16, [x16]\n"
"    br x16\n"
);
extern void assert_probe_trampoline(void);
/* date_time_add_seconds(src7, seconds, dst7) is what run_i calls right before the assert at
   0x305b99c; a rejected source date makes it return non-zero and the firmware asserts. Record the
   source bytes and the second count so a bad (e.g. all-zero) date is visible instead of inferred. */
static unsigned int date_add_seen;
void capture_date_add(unsigned long source, unsigned long seconds, unsigned long destination) {
    if (date_add_seen++ >= 8) return;
    unsigned int v = 0;
    if (source > 0x100000UL && source < 0x800000000000UL) {
        const unsigned char *b = (const unsigned char *)source;
        v = (unsigned int)b[0] | (unsigned int)b[1] << 8 | (unsigned int)b[2] << 16 | (unsigned int)b[3] << 24;
    }
    char text[200];
    snprintf(text, sizeof text, "n=%u src=%#lx secs=%lu(0x%lx) dst=%#lx srcw=%#x tid=%ld",
             date_add_seen, source, seconds, seconds, destination, v, syscall(178));
    record("DATE_ADD_CALL ", text);
}
__asm__(
".text\n"
".globl date_add_probe_trampoline\n"
".type date_add_probe_trampoline, %function\n"
"date_add_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_date_add\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9bc7bfd\n"          /* stp x29,x30,[sp,#-64]! */
"    .inst 0x910003fd\n"          /* mov x29,sp */
"    .inst 0xf9000bf3\n"          /* str x19,[sp,#16] */
"    .inst 0xaa0203f3\n"          /* mov x19,x2 */
"    adrp x16, date_add_continue\n"
"    ldr x16, [x16, #:lo12:date_add_continue]\n"
"    br x16\n"
);
extern void date_add_probe_trampoline(void);
static void *date_add_continue;
static void install_assert_probe(unsigned long base) {
    g_real_assert_fail = (void (*)(const char *, const char *, unsigned int, const char *))
        real_dlsym((void *)-1, "__assert_fail");
    if (!g_real_assert_fail) { record("ASSERT_PROBE_FAILED ", "no __assert_fail"); return; }
    unsigned long page = base + 0x5bc2000UL;
    if (mprotect((void *)page, 4096, 3) != 0) { record("ASSERT_PROBE_FAILED ", "GOT page"); return; }
    *(unsigned long *)(base + 0x5bc27c8UL) = (unsigned long)assert_probe_trampoline;
    record("ASSERT_PROBE_ARMED ", "appFw __assert_fail GOT slot 0x5bc27c8");
}
static void arm_entry_probe(unsigned long target, const unsigned int expected[4], void *trampoline,
                            void *continue_address, const char *label) {
    unsigned long page = target & ~0xfffUL;
    for (int i = 0; i < 4; ++i) {
        if (((const unsigned int *)target)[i] != expected[i]) {
            char text[160];
            snprintf(text, sizeof text, "slot %d is %#010x, expected %#010x", i,
                     ((const unsigned int *)target)[i], expected[i]);
            record("ENTRY_PROBE_MISMATCH ", label);
            record("ENTRY_PROBE_MISMATCH_DETAIL ", text);
            return;
        }
    }
    if (mprotect((void *)page, 4096, 7) != 0) { record("ENTRY_PROBE_FAILED ", label); return; }
    unsigned int *code = (unsigned int *)target;
    code[0] = 0x58000050;                        /* ldr x16, [pc, #8] */
    code[1] = 0xd61f0200;                        /* br  x16 */
    *(unsigned long *)(target + 8) = (unsigned long)trampoline;
    clear_cache_range((void *)target, 16);
    if (mprotect((void *)page, 4096, 5) != 0) record("ENTRY_PROBE_REPROTECT_FAILED ", label);
    record("ENTRY_PROBE_ARMED ", label);
}
/* sequence_boot::run (0x305e9b8) calls run_i (0x305e730? no: 0x305b730) and, immediately after it
   returns, fulfils the promise the UI thread is blocked on:
       305e9e4  bl  run_i
       305e9e8  ldr x0,[x19,#16]      ; promise
       305e9ec  bl  0x2e06480(P)      ; fulfil
   So "run_i returned" is the exact gate for the shooting screen. Observing 0x305e9e8 tells us
   whether the boot sequence body ever completed, which nothing else in the log shows: the
   APPFW_LOG with caller=appFw+0x305e9e0 only proves run_i was *entered*.
   Read-only: the trampoline replays the two overwritten instructions and continues. */
/* run_i's last gate before its source-level `assert at` (sequence/sequence_boot.cpp:1436) is
   0x34caa48(obj, arg); it forwards to 0x350c6fc, which switches on *(u32*)obj and treats a value
   above 4 as the error branch. Recording the object's first word and the eventual return value
   shows whether the firmware asked for a state we never provided, instead of guessing from logs.
   Read-only: the trampoline replays the four overwritten instructions and continues. */
/* run_i (0x305b730) has exactly one `ret`, at 0x305b9bc, reached by the sequential epilogue
   0x305b9b0 (ldp x25/x26, ldp x27/x28, ldp x29/x30). No branch or jump table targets those four
   instructions (checked by scanning every B/BL/B.cond/CBZ/CBNZ/TBZ/TBNZ in run_i's range), so
   patching the epilogue entry observes "run_i returned" without altering any control flow.
   That return is the gate for the UI promise: run() calls run_i and then fulfils it. */
/* 0x205eecc is the function that runs after boot_start_seq's future (0x2e07044) returns and is
   the gate in front of rep_shooting selecting screen 0x235/0x17f/0xa8. Nothing in the log shows
   whether it is ever entered, so observe it directly: a probe here separates "boot sequence never
   got that far" from "it got there but picked a different branch". */
static unsigned int shooting_enter_seen;
void capture_shooting_enter(unsigned long object) {
    if (shooting_enter_seen++ < 4) {
        char text[128];
        snprintf(text, sizeof text, "n=%u tid=%ld this=%#lx", shooting_enter_seen, syscall(178), object);
        record("SHOOTING_ENTER ", text);
    }
}
__asm__(
".text\n"
".globl shooting_enter_trampoline\n"
".type shooting_enter_trampoline, %function\n"
"shooting_enter_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_shooting_enter\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9bc7bfd\n"            /* stp x29,x30,[sp,#-64]! */
"    .inst 0x910003fd\n"            /* mov x29,sp */
"    .inst 0xa9025bf5\n"            /* stp x21,x22,[sp,#32] */
"    .inst 0xaa0003f5\n"            /* mov x21,x0 */
"    adrp x16, shooting_enter_continue\n"
"    ldr x16, [x16, #:lo12:shooting_enter_continue]\n"
"    br x16\n"
);
extern void shooting_enter_trampoline(void);
static void *shooting_enter_continue;
static void install_shooting_probe(unsigned long base) {
    shooting_enter_continue = (void *)(base + 0x205eeccUL + 16);
    arm_entry_probe(base + 0x205eeccUL,
                    (const unsigned int[4]){0xa9bc7bfd, 0x910003fd, 0xa9025bf5, 0xaa0003f5},
                    (void *)shooting_enter_trampoline, shooting_enter_continue, "shooting gate 0x205eecc");
}
static unsigned int run_i_returned_seen;
void capture_run_i_return(unsigned long object, unsigned long frame) {
    if (run_i_returned_seen++ < 4) {
        char text[144];
        snprintf(text, sizeof text, "n=%u tid=%ld object=%#lx frame=%#lx",
                 run_i_returned_seen, syscall(178), object, frame);
        record("RUN_I_RET ", text);
    }
}
__asm__(
".text\n"
".globl run_i_return_trampoline\n"
".type run_i_return_trampoline, %function\n"
"run_i_return_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x1, x29\n"
"    bl capture_run_i_return\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9446bf9\n"            /* ldp x25,x26,[sp,#64] */
"    .inst 0xa94573fb\n"            /* ldp x27,x28,[sp,#80] */
"    .inst 0xa8d47bfd\n"            /* ldp x29,x30,[sp],#320 */
"    .inst 0xd65f03c0\n"            /* ret */
"    adrp x16, run_i_return_continue\n"
"    ldr x16, [x16, #:lo12:run_i_return_continue]\n"
"    br x16\n"
);
extern void run_i_return_trampoline(void);
static void *run_i_return_continue;
static void install_run_i_return_probe(unsigned long base) {
    /* The trampoline ends with `ret`, so the continuation is never taken; it exists only to keep
       the probe macro shape identical to the others. Point it at the real return address. */
    run_i_return_continue = (void *)(base + 0x305b9c0UL);
    arm_entry_probe(base + 0x305b9b0UL,
                    (const unsigned int[4]){0xa9446bf9, 0xa94573fb, 0xa8d47bfd, 0xd65f03c0},
                    (void *)run_i_return_trampoline, run_i_return_continue, "run_i return 0x305b9b0");
}
static unsigned int obj_dispatch_seen;
void capture_obj_dispatch(unsigned long object, unsigned long argument) {
    if (obj_dispatch_seen++ < 8) {
        unsigned int kind = 0xffffffffU;
        if (object > 0x100000UL && object < 0x800000000000UL) kind = *(unsigned int *)object;
        char text[176];
        snprintf(text, sizeof text, "n=%u tid=%ld obj=%#lx kind=%#x arg=%#lx",
                 obj_dispatch_seen, syscall(178), object, kind, argument);
        record("OBJ_DISPATCH ", text);
    }
}
__asm__(
".text\n"
".globl obj_dispatch_trampoline\n"
".type obj_dispatch_trampoline, %function\n"
"obj_dispatch_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_obj_dispatch\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9be7bfd\n"            /* stp x29,x30,[sp,#-32]! */
"    .inst 0x910003fd\n"            /* mov x29,sp */
"    .inst 0xa90153f3\n"            /* stp x19,x20,[sp,#16] */
"    .inst 0xaa0003f3\n"            /* mov x19,x0 */
"    adrp x16, obj_dispatch_continue\n"
"    ldr x16, [x16, #:lo12:obj_dispatch_continue]\n"
"    br x16\n"
);
extern void obj_dispatch_trampoline(void);
static void *obj_dispatch_continue;
static unsigned int boot_fulfil_seen;
void capture_boot_fulfil(unsigned long seq_object, unsigned long promise) {
    if (boot_fulfil_seen++ < 4) {
        char text[160];
        snprintf(text, sizeof text, "n=%u tid=%ld seq=%#lx promise=%#lx run_i_returned=1",
                 boot_fulfil_seen, syscall(178), seq_object, promise);
        record("BOOT_FULFIL ", text);
    }
}
__asm__(
".text\n"
".globl boot_fulfil_trampoline\n"
".type boot_fulfil_trampoline, %function\n"
"boot_fulfil_trampoline:\n"
PROBE_SAVE_ARGS
"    ldr x0, [x19, #16]\n"          /* promise, as the original does before the call */
"    mov x1, x19\n"
"    bl capture_boot_fulfil\n"
PROBE_RESTORE_ARGS
"    .inst 0xf9400a60\n"            /* ldr x0,[x19,#16] */
"    .inst 0x97f69ea5\n"            /* bl 0x2e06480 */
"    adrp x16, boot_fulfil_continue\n"
"    ldr x16, [x16, #:lo12:boot_fulfil_continue]\n"
"    br x16\n"
);
extern void boot_fulfil_trampoline(void);
static void *boot_fulfil_continue;
static void *power_notice_continue;
static unsigned int power_notice_seen;
void capture_power_notice(void *message,unsigned long caller) {
    unsigned int words[4],length=real_msg_size?real_msg_size(message):0;
    unsigned int count=__atomic_add_fetch(&power_notice_seen,1,__ATOMIC_RELAXED);
    if(count>64 && (count&(count-1)))return;
    if(!power_notice_decode(message,length,words)) {
        /* The preserved original CBZ guarantees non-NULL; the callback itself reads its first word. */
        unsigned int command=*(const unsigned int *)message;
        char text[160];snprintf(text,sizeof text,"n=%u ptr=%p cmd=%#x osal_bytes=%u caller=%#lx",count,message,command,length,caller);
        record("POWER_NOTICE_UNDECODED ",text);return;
    }
    long mono[2]={-1,0},wall[2]={-1,0};
    syscall(113,1,mono);syscall(113,0,wall);
    char text[300];
    snprintf(text,sizeof text,"n=%u tid=%ld cmd=%#x src=%#x bytes=%u word4=%#x word8=%#x wordc=%#x mono=%ld.%09ld wall=%ld.%09ld caller=%#lx",
        count,syscall(178),words[0],real_get_source?real_get_source(message):0,length,
        words[1],words[2],words[3],mono[0],mono[1],wall[0],wall[1],caller);
    record("POWER_NOTICE ",text);
}
__asm__(
".text\n"
".globl power_notice_trampoline\n"
".type power_notice_trampoline, %function\n"
"power_notice_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x1, x30\n"
"    bl capture_power_notice\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9b97bfd\n"
"    .inst 0x528028e1\n"
"    .inst 0x72a01241\n"
"    .inst 0x910003fd\n"
"    adrp x16, power_notice_continue\n"
"    ldr x16, [x16, #:lo12:power_notice_continue]\n"
"    br x16\n"
);
extern void power_notice_trampoline(void);
static void *power_model_continue,*shutdown_enter_continue;
void capture_power_model(unsigned long self,const unsigned int *event,unsigned long caller) {
    (void)self;
    if(event[2]!=0x0100003cU && event[2]!=0x0100003dU && event[2]!=0x0100003eU)return;
    char text[220];
    const unsigned int *state=(const unsigned int *)(appfw_base+0x7e5dd88UL);
    snprintf(text,sizeof text,"event=%#x state=[%#x,%#x,%#x] caller=%#lx",event[2],state[0],state[1],state[2],caller);
    record("POWER_MODEL ",text);
}
void capture_shutdown_enter(unsigned long self,unsigned long caller) {
    (void)self;
    const unsigned int *state=(const unsigned int *)(appfw_base+0x7e5dd88UL);
    char text[220];long mono[2]={-1,0};syscall(113,1,mono);
    snprintf(text,sizeof text,"state=[%#x,%#x,%#x] mono=%ld.%09ld caller=%#lx",state[0],state[1],state[2],mono[0],mono[1],caller);
    record("SHUTDOWN_ENTER ",text);
}
__asm__(
".text\n"
".globl power_model_trampoline\n"
".type power_model_trampoline, %function\n"
"power_model_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x2, x30\n"
"    bl capture_power_model\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9b77bfd\n"
"    .inst 0x910003fd\n"
"    .inst 0xa90153f3\n"
"    .inst 0xaa0003f4\n"
"    adrp x16, power_model_continue\n"
"    ldr x16, [x16, #:lo12:power_model_continue]\n"
"    br x16\n"
".globl shutdown_enter_trampoline\n"
".type shutdown_enter_trampoline, %function\n"
"shutdown_enter_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x1, x30\n"
"    bl capture_shutdown_enter\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9b97bfd\n"
"    .inst 0x910003fd\n"
"    .inst 0xa90153f3\n"
"    .inst 0x910103b4\n"
"    adrp x16, shutdown_enter_continue\n"
"    ldr x16, [x16, #:lo12:shutdown_enter_continue]\n"
"    br x16\n"
);
extern void power_model_trampoline(void),shutdown_enter_trampoline(void);
static void *resume_on_continue,*resume_cancel_continue;
void capture_power_resume_route(unsigned long self,unsigned long caller,unsigned long route) {
    char text[180];snprintf(text,sizeof text,"route=%s this=%#lx caller=%#lx tid=%ld original_forwarded=1",
        route?"shutdown-cancel-20a079c":"shutdown-on-20a073c",self,caller,syscall(178));
    record("POWER_RESUME_ROUTE ",text);
}
#define RESUME_ROUTE_TRAMPOLINE(NAME, ROUTE, NEXT) \
".globl " NAME "\n.type " NAME ", %function\n" NAME ":\n" \
PROBE_SAVE_ARGS \
"    mov x1, x30\n    mov x2, #" ROUTE "\n    bl capture_power_resume_route\n" \
PROBE_RESTORE_ARGS \
"    .inst 0xa9bd7bfd\n    .inst 0x910003fd\n    .inst 0xa90153f3\n    .inst 0x9100a3b3\n" \
"    adrp x16, " NEXT "\n    ldr x16, [x16, #:lo12:" NEXT "]\n    br x16\n"
__asm__(".text\n"
RESUME_ROUTE_TRAMPOLINE("resume_on_trampoline","0","resume_on_continue")
RESUME_ROUTE_TRAMPOLINE("resume_cancel_trampoline","1","resume_cancel_continue")
);
#undef RESUME_ROUTE_TRAMPOLINE
extern void resume_on_trampoline(void),resume_cancel_trampoline(void);
static void *power_on_sequence_continue,*power_cancel_sequence_continue;
void capture_power_sequence(const unsigned char *self,unsigned long caller,unsigned long kind) {
    static unsigned int seen[2];
    unsigned int n=__atomic_add_fetch(&seen[kind?1:0],1,__ATOMIC_RELAXED);
    if(n>8 && (n&(n-1)))return;
    char text[300];snprintf(text,sizeof text,"kind=%s n=%u tid=%ld this=%p vtable_app=%#lx byte18=%u word1c=%#x word20=%#x word24=%#x caller_app=%#lx observation_only=1",
        kind?"power_off_cancel-33dccb8":"power_on-33dcf50",n,syscall(178),self,
        *(const unsigned long *)self-appfw_base,self[0x18],*(const unsigned int *)(self+0x1c),
        *(const unsigned int *)(self+0x20),*(const unsigned int *)(self+0x24),caller-appfw_base);
    record("POWER_SEQUENCE_ENTER ",text);
}
#define POWER_SEQUENCE_TRAMPOLINE(NAME, KIND, THIRD, FOURTH, NEXT) \
".globl " NAME "\n.type " NAME ", %function\n" NAME ":\n" \
PROBE_SAVE_ARGS \
"    mov x1, x30\n    mov x2, #" KIND "\n    bl capture_power_sequence\n" \
PROBE_RESTORE_ARGS \
"    .inst 0xa9ba7bfd\n    .inst 0x910003fd\n    .inst " THIRD "\n    .inst " FOURTH "\n" \
"    adrp x16, " NEXT "\n    ldr x16, [x16, #:lo12:" NEXT "]\n    br x16\n"
__asm__(".text\n"
POWER_SEQUENCE_TRAMPOLINE("power_on_sequence_trampoline","0","0xf90013f5","0xaa0003f5","power_on_sequence_continue")
POWER_SEQUENCE_TRAMPOLINE("power_cancel_sequence_trampoline","1","0xa90153f3","0xaa0003f4","power_cancel_sequence_continue")
);
#undef POWER_SEQUENCE_TRAMPOLINE
extern void power_on_sequence_trampoline(void),power_cancel_sequence_trampoline(void);
static void *power_request_continue,*power_queue_continue;
static void *volatile power_request_skip;
void capture_power_request_gate(unsigned long handle,unsigned long value,unsigned long argument,unsigned long gate,unsigned long caller) {
    static unsigned int seen[2];
    unsigned long relative=caller-appfw_base;
    unsigned int n=__atomic_add_fetch(&seen[relative==0x262aafcUL],1,__ATOMIC_RELAXED);
    if(n>8 && (n&(n-1)))return;
    char text[240];snprintf(text,sizeof text,"request=0x100 n=%u tid=%ld handle=%#lx value=%lu argument=%#lx original_gate=%lu caller_app=%#lx observation_only=1",
        n,syscall(178),handle,value,argument,gate,relative);
    record("POWER_REQUEST_GATE ",text);
}
void capture_power_queue_enter(const unsigned char *queue,const unsigned long *holder,unsigned long caller) {
    if(caller-appfw_base!=0x24d8778UL)return;
    static unsigned int seen;
    unsigned int n=__atomic_add_fetch(&seen,1,__ATOMIC_RELAXED);
    if(n>8 && (n&(n-1)))return;
    char text[200];snprintf(text,sizeof text,"request=0x100 n=%u tid=%ld queue_app=%#lx held_object=%#lx observation_only=1",
        n,syscall(178),(unsigned long)queue-appfw_base,*holder);
    record("POWER_QUEUE_ENTER ",text);
}
__asm__(".text\n"
".globl power_request_trampoline\n.type power_request_trampoline, %function\npower_request_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x0, x20\n    mov w1, w21\n    mov x2, x22\n    mov w3, w23\n    ldr x4, [x29, #8]\n    bl capture_power_request_gate\n"
PROBE_RESTORE_ARGS
"    cbz w23, 1f\n    .inst 0xaa1603e2\n    .inst 0x2a1503e1\n    .inst 0xaa1403e0\n"
"    adrp x16, power_request_continue\n    ldr x16, [x16, #:lo12:power_request_continue]\n    br x16\n"
"1:\n    adrp x16, power_request_skip\n    ldr x16, [x16, #:lo12:power_request_skip]\n    br x16\n"
".globl power_queue_trampoline\n.type power_queue_trampoline, %function\npower_queue_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x2, x30\n    bl capture_power_queue_enter\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9be7bfd\n    .inst 0x910003fd\n    .inst 0xa90153f3\n    .inst 0xaa0003f3\n"
"    adrp x16, power_queue_continue\n    ldr x16, [x16, #:lo12:power_queue_continue]\n    br x16\n"
);
extern void power_request_trampoline(void),power_queue_trampoline(void);
static void *osd_submit_continue;
static unsigned long observed_mode_view_params[3];
static unsigned int observed_mode_model_values[3];
void capture_osd_submit_mode(unsigned long self,const unsigned char *message,unsigned long caller) {
    (void)self;
    static unsigned int prior=~0u,budget,guard;
    unsigned int expected=0;
    if(!__atomic_compare_exchange_n(&guard,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return;
    unsigned int mode=*(const unsigned int *)(appfw_base+0x7ee4750UL);
    if(mode!=prior){prior=mode;budget=4;}
    if(!budget){__atomic_store_n(&guard,0,__ATOMIC_RELEASE);return;}
    --budget;
    __atomic_store_n(&guard,0,__ATOMIC_RELEASE);
    unsigned long base=(unsigned long)real_draw_framebuffer-0x174dbcUL;
    unsigned long manager=*(unsigned long *)(base+0x2ebde0UL),fb=manager?*(unsigned long *)(manager+8):0;
    unsigned long on=fb?*(unsigned long *)(fb+0x68):0,off=fb?*(unsigned long *)(fb+0x70):0;
    unsigned int on_id=~0u,off_id=~0u;
    unsigned long on_phys=0,off_phys=0;
    if(fb && ((on==fb+0x20 && off==fb+0x40)||(on==fb+0x40 && off==fb+0x20))) {
        on_id=*(unsigned int *)(on+0x10);off_id=*(unsigned int *)(off+0x10);
        on_phys=*(unsigned long *)(on+0x18);off_phys=*(unsigned long *)(off+0x18);
    }
    char hex[97],text[400];
    for(unsigned int i=0;i<48;i++)snprintf(hex+2*i,3,"%02x",message[i]);
    snprintf(text,sizeof text,"tid=%ld mode=%u raw48=%s on_id=%#x off_id=%#x on_phys=%#lx off_phys=%#lx caller=%#lx metadata_observation_non_atomic=1",
        syscall(178),mode,hex,on_id,off_id,on_phys,off_phys,caller);
    record("OSD_SUBMIT_MODE ",text);
}
__asm__(
".text\n"
".globl osd_submit_trampoline\n"
".type osd_submit_trampoline, %function\n"
"osd_submit_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x2, x30\n"
"    bl capture_osd_submit_mode\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9bc7bfd\n"
"    .inst 0x910003fd\n"
"    .inst 0xa90153f3\n"
"    .inst 0xaa0003f4\n"
"    adrp x16, osd_submit_continue\n"
"    ldr x16, [x16, #:lo12:osd_submit_continue]\n"
"    br x16\n"
);
extern void osd_submit_trampoline(void);
static void *mode_icon_continue;
void capture_mode_icon_value(unsigned long a0,unsigned long a1,unsigned long a2,const unsigned int *model,unsigned long caller) {
    (void)a0;(void)a2;
    unsigned long relative=caller-appfw_base;
    if(relative==0x1d2c394UL || relative==0x1d2c3b4UL || relative==0x1d2c3d4UL) {
        unsigned int slot=(relative-0x1d2c394UL)/0x20;
        __atomic_store_n(&observed_mode_model_values[slot],model[0],__ATOMIC_RELAXED);
        __atomic_store_n(&observed_mode_view_params[slot],a1,__ATOMIC_RELEASE);
    }
    static unsigned int count,changes,prior_dial=~0u,prior_icon=~0u,prior_kind=~0u,guard;
    unsigned int n=__atomic_add_fetch(&count,1,__ATOMIC_RELAXED);
    unsigned int dial=*(const unsigned int *)(appfw_base+0x7ee4750UL),expected=0;
    int changed=0;
    if(__atomic_compare_exchange_n(&guard,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
        if(dial!=prior_dial || model[0]!=prior_icon || model[0x60/4]!=prior_kind) {
            prior_dial=dial;prior_icon=model[0];prior_kind=model[0x60/4];
            ++changes;changed=changes<=64 || !(changes&(changes-1));
        }
        __atomic_store_n(&guard,0,__ATOMIC_RELEASE);
    }
    if(n>8 && (n&(n-1)) && !changed)return;
    int saved_errno=*__errno_location();long stamp[2]={0,0};long clock_rc=syscall(113,1,stamp);
    char text[320];snprintf(text,sizeof text,"n=%u tid=%ld dial=%u icon_model0=%u icon_model60=%u model=%p param=%#lx caller_app=%#lx mono_rc=%ld mono=%ld.%09ld observation_only=1",
        n,syscall(178),dial,model[0],model[0x60/4],model,a1,relative,clock_rc,stamp[0],stamp[1]);
    record("MODE_ICON_VALUE ",text);
    *__errno_location()=saved_errno;
}
__asm__(
".text\n"
".globl mode_icon_trampoline\n"
".type mode_icon_trampoline, %function\n"
"mode_icon_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x4, x30\n"
"    bl capture_mode_icon_value\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9bc7bfd\n"
"    .inst 0x12800000\n"
"    .inst 0x910003fd\n"
"    .inst 0xa90153f3\n"
"    adrp x16, mode_icon_continue\n"
"    ldr x16, [x16, #:lo12:mode_icon_continue]\n"
"    br x16\n"
);
extern void mode_icon_trampoline(void);
static void *mode_icon_consumer_continue;
static void *volatile mode_icon_set_image_return,*volatile mode_icon_set_image_target;
void capture_mode_icon_consumer(const unsigned char *widget,unsigned long caller,unsigned long selected,unsigned long phase) {
    unsigned int resource=*(const unsigned int *)(widget+0x214);
    unsigned int matched=0;int family=0;
    for(unsigned int i=0;i<3;i++)
        if(__atomic_load_n(&observed_mode_view_params[i],__ATOMIC_ACQUIRE)==(unsigned long)(widget+0x1d8))matched|=1u<<i;
    const unsigned int *ids=(const unsigned int *)(appfw_base+0x41b23a0UL);
    if(resource!=~0u)for(unsigned int i=0;i<18;i++)if(resource==ids[i]){family=1;break;}
    if(!matched && !family)return;
    static unsigned int guard,prior=~0u,budget;
    unsigned int expected=0,dial=*(const unsigned int *)(appfw_base+0x7ee4750UL);
    if(!__atomic_compare_exchange_n(&guard,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return;
    if(prior!=dial){prior=dial;budget=32;}
    if(!budget){__atomic_store_n(&guard,0,__ATOMIC_RELEASE);return;}
    --budget;__atomic_store_n(&guard,0,__ATOMIC_RELEASE);
    int saved_errno=*__errno_location();long stamp[2]={0,0};long clock_rc=syscall(113,1,stamp);
    char models[64]="-";unsigned int used=0;
    if(matched) {
        models[0]=0;
        for(unsigned int i=0;i<3;i++)if(matched&(1u<<i)) {
            int written=snprintf(models+used,sizeof models-used,"%s%u:%u",used?";":"",i,
                __atomic_load_n(&observed_mode_model_values[i],__ATOMIC_ACQUIRE));
            if(written>0 && (unsigned int)written<sizeof models-used)used+=(unsigned int)written;
        }
    }
    char text[448];snprintf(text,sizeof text,"stage=%lu tid=%ld widget=%p param=%#lx tracked_mask=%#x last_model0=%s icon_family=%d dial=%u raw_resource=%#x selected_valid=%u selected_resource=%#lx byte204=%u caller=%#lx mono_rc=%ld mono=%ld.%09ld policy=first32_per_dial visibility_unproven=1 non_atomic_metadata=1 observation_only=1",
        phase,syscall(178),(const void *)widget,(unsigned long)(widget+0x1d8),matched,models,family,dial,resource,phase==1,selected,widget[0x204],caller,clock_rc,stamp[0],stamp[1]);
    record("MODE_ICON_CONSUMER ",text);
    *__errno_location()=saved_errno;
}
__asm__(".text\n"
".globl mode_icon_consumer_trampoline\n.type mode_icon_consumer_trampoline, %function\nmode_icon_consumer_trampoline:\n"
PROBE_SAVE_ARGS
"    mov x1, x30\n    mov x2, #0\n    mov x3, #0\n    bl capture_mode_icon_consumer\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9b97bfd\n    .inst 0x910003fd\n    .inst 0x39481001\n    .inst 0xa90153f3\n"
"    adrp x16, mode_icon_consumer_continue\n    ldr x16, [x16, #:lo12:mode_icon_consumer_continue]\n    br x16\n"
".globl mode_icon_set_image_trampoline\n.type mode_icon_set_image_trampoline, %function\nmode_icon_set_image_trampoline:\n"
PROBE_SAVE_ARGS
"    mov w2, w0\n    mov x0, x19\n    ldr x1, [x29, #8]\n    mov x3, #1\n    bl capture_mode_icon_consumer\n"
PROBE_RESTORE_ARGS
"    .inst 0x2a0003e1\n    .inst 0xaa1403e0\n    .inst 0x12800fe2\n"
"    adrp x30, mode_icon_set_image_return\n    ldr x30, [x30, #:lo12:mode_icon_set_image_return]\n"
"    adrp x16, mode_icon_set_image_target\n    ldr x16, [x16, #:lo12:mode_icon_set_image_target]\n    br x16\n"
);
extern void mode_icon_consumer_trampoline(void),mode_icon_set_image_trampoline(void);
static void install_osd_submit_probe(void) {
    unsigned long base=(unsigned long)real_draw_framebuffer-0x174dbcUL;
    osd_submit_continue=(void *)(base+0xf7948UL);
    arm_entry_probe(base+0xf7938UL,(const unsigned int[4]){0xa9bc7bfd,0x910003fd,0xa90153f3,0xaa0003f4},
        (void *)osd_submit_trampoline,osd_submit_continue,"original OSD update message 0xf7938");
    mode_icon_continue=(void *)(appfw_base+0x23a7af4UL);
    arm_entry_probe(appfw_base+0x23a7ae4UL,(const unsigned int[4]){0xa9bc7bfd,0x12800000,0x910003fd,0xa90153f3},
        (void *)mode_icon_trampoline,mode_icon_continue,"original exposure mode icon translator 0x23a7ae4");
    mode_icon_consumer_continue=(void *)(appfw_base+0x17eb1b4UL);
    arm_entry_probe(appfw_base+0x17eb1a4UL,(const unsigned int[4]){0xa9b97bfd,0x910003fd,0x39481001,0xa90153f3},
        (void *)mode_icon_consumer_trampoline,mode_icon_consumer_continue,"original view_icon resource consumer 0x17eb1a4");
    mode_icon_set_image_return=(void *)(appfw_base+0x17eb5bcUL);
    mode_icon_set_image_target=(void *)(appfw_base+0x165f100UL);
    arm_entry_probe(appfw_base+0x17eb5acUL,(const unsigned int[4]){0x2a0003e1,0xaa1403e0,0x12800fe2,0x97f9ced2},
        (void *)mode_icon_set_image_trampoline,mode_icon_set_image_return,"original setImage arguments (BL and original LR replayed)");
}
static void install_power_notice_probe(unsigned long base) {
    /* Keep the original entry's CBZ; these following four instructions are position independent. */
    power_notice_continue=(void *)(base+0x35a3a54UL);
    arm_entry_probe(base+0x35a3a44UL,(const unsigned int[4]){0xa9b97bfd,0x528028e1,0x72a01241,0x910003fd},
        (void *)power_notice_trampoline,power_notice_continue,"original UPM callback_off_cmd 0x35a3a44");
    power_model_continue=(void *)(base+0x1b23e68UL);
    arm_entry_probe(base+0x1b23e58UL,(const unsigned int[4]){0xa9b77bfd,0x910003fd,0xa90153f3,0xaa0003f4},
        (void *)power_model_trampoline,power_model_continue,"original power model handler 0x1b23e58");
    shutdown_enter_continue=(void *)(base+0x20a0bd4UL);
    arm_entry_probe(base+0x20a0bc4UL,(const unsigned int[4]){0xa9b97bfd,0x910003fd,0xa90153f3,0x910103b4},
        (void *)shutdown_enter_trampoline,shutdown_enter_continue,"original shutdown enter 0x20a0bc4");
    resume_on_continue=(void *)(base+0x20a074cUL);
    resume_cancel_continue=(void *)(base+0x20a07acUL);
    arm_entry_probe(base+0x20a073cUL,(const unsigned int[4]){0xa9bd7bfd,0x910003fd,0xa90153f3,0x9100a3b3},
        (void *)resume_on_trampoline,resume_on_continue,"original shutdown power-on route");
    arm_entry_probe(base+0x20a079cUL,(const unsigned int[4]){0xa9bd7bfd,0x910003fd,0xa90153f3,0x9100a3b3},
        (void *)resume_cancel_trampoline,resume_cancel_continue,"original shutdown cancel route");
    power_on_sequence_continue=(void *)(base+0x33dcf60UL);
    power_cancel_sequence_continue=(void *)(base+0x33dccc8UL);
    arm_entry_probe(base+0x33dcf50UL,(const unsigned int[4]){0xa9ba7bfd,0x910003fd,0xf90013f5,0xaa0003f5},
        (void *)power_on_sequence_trampoline,power_on_sequence_continue,"original sequence_power_on run");
    arm_entry_probe(base+0x33dccb8UL,(const unsigned int[4]){0xa9ba7bfd,0x910003fd,0xa90153f3,0xaa0003f4},
        (void *)power_cancel_sequence_trampoline,power_cancel_sequence_continue,"original sequence_power_off_cancel run");
    power_request_continue=(void *)(base+0x24d8738UL);
    power_request_skip=(void *)(base+0x24d8780UL);
    arm_entry_probe(base+0x24d8728UL,(const unsigned int[4]){0x340002d7,0xaa1603e2,0x2a1503e1,0xaa1403e0},
        (void *)power_request_trampoline,power_request_continue,"original request100 gate (both CBZ outcomes replayed)");
    power_queue_continue=(void *)(base+0x24cba2cUL);
    arm_entry_probe(base+0x24cba1cUL,(const unsigned int[4]){0xa9be7bfd,0x910003fd,0xa90153f3,0xaa0003f3},
        (void *)power_queue_trampoline,power_queue_continue,"original request100 queue insertion entry");
}

static void install_boot_entry_probes(unsigned long base) {
    observe_appfw_base = base;
    seq_run_continue = (void *)(base + 0x305e9b8UL + 16);
    log_varargs_continue = (void *)(base + 0x368059cUL + 16);
    log_valist_continue = (void *)(base + 0x36804c8UL + 16);
    /* The 4th destroyed instruction here is an adrp, so this probe needs the image base to replay it.
       It stays opt-in: "run entered" is already visible without patching anything, as the APPFW_LOG
       record whose caller is appFw+0x305e9e0 (the return address of run's first log call). */
    if (getenv("MENU_PROBE_SEQ_RUN"))
        arm_entry_probe(base + 0x305e9b8UL, (const unsigned int[4]){0xa9b77bfd, 0x910003fd, 0xa90153f3, 0xd000ddb4}, (void *)seq_run_probe_trampoline, seq_run_continue, "sequence_boot::run 0x305e9b8");
    arm_entry_probe(base + 0x368059cUL, (const unsigned int[4]){0xa9ad7bfd, 0x910003fd, 0xa90153f3, 0x13003c14}, (void *)log_varargs_probe_trampoline, log_varargs_continue, "appFw log 0x368059c");
    arm_entry_probe(base + 0x36804c8UL, (const unsigned int[4]){0xd10803ff, 0xa9be7bfd, 0x910003fd, 0xf9000bf3}, (void *)log_valist_probe_trampoline, log_valist_continue, "appFw log 0x36804c8");
    pool_worker_continue = (void *)(base + 0x34b8efcUL + 16);
    seq_finish_continue = (void *)(base + 0x31ac094UL + 16);
    arm_entry_probe(base + 0x34b8efcUL, (const unsigned int[4]){0xa9be7bfd, 0x910003fd, 0xa90153f3, 0xaa0003f3}, (void *)pool_worker_probe_trampoline, pool_worker_continue, "pool worker 0x34b8efc");
    arm_entry_probe(base + 0x31ac094UL, (const unsigned int[4]){0xa9be7bfd, 0x910003fd, 0xa90153f3, 0xaa0103f3}, (void *)seq_finish_probe_trampoline, seq_finish_continue, "sequence unregister 0x31ac094");
    bootseq_continue = (void *)(base + 0x272ef3cUL + 16);
    bootfactory_continue = (void *)(base + 0x2490020UL + 16);
    bootctor_continue = (void *)(base + 0x31c7c94UL + 16);
    arm_entry_probe(base + 0x272ef3cUL, (const unsigned int[4]){0xa9b17bfd, 0x910003fd, 0xa90153f3, 0x910343b3}, (void *)bootseq_probe_trampoline, bootseq_continue, "boot_start_seq body 0x272ef3c");
    arm_entry_probe(base + 0x2490020UL, (const unsigned int[4]){0xa9be7bfd, 0x910003fd, 0xf9000bf3, 0xaa0003f3}, (void *)bootfactory_probe_trampoline, bootfactory_continue, "0x2a factory 0x2490020");
    arm_entry_probe(base + 0x31c7c94UL, (const unsigned int[4]){0xd101c3ff, 0xa9017bfd, 0x910043fd, 0xa90253f3}, (void *)bootctor_probe_trampoline, bootctor_continue, "sequence_boot ctor 0x31c7c94");
    queue_loop_continue = (void *)(base + 0x3209d48UL + 16);
    dep_wait_continue = (void *)(base + 0x303cb84UL + 16);
    arm_entry_probe(base + 0x3209d48UL, (const unsigned int[4]){0xa9b87bfd, 0xd2888002, 0x910003fd, 0xa9046bf9}, (void *)queue_loop_probe_trampoline, queue_loop_continue, "group queue loop 0x3209d48");
    arm_entry_probe(base + 0x303cb84UL, (const unsigned int[4]){0xa9bd7bfd, 0xb201f3e2, 0xf2955562, 0x910003fd}, (void *)dep_wait_probe_trampoline, dep_wait_continue, "predecessor wait 0x303cb84");
    /* 0x305e9e8 is `ldr x0,[x19,#16]` right after run_i returns; replacing it with a call into the
       trampoline keeps the two original instructions and adds the observation. */
    obj_dispatch_continue = (void *)(base + 0x34caa48UL + 16);
    arm_entry_probe(base + 0x34caa48UL, (const unsigned int[4]){0xa9be7bfd, 0x910003fd, 0xa90153f3, 0xaa0003f3},
                    (void *)obj_dispatch_trampoline, obj_dispatch_continue, "run_i line1436 gate 0x34caa48");
    boot_fulfil_continue = (void *)(base + 0x305e9e8UL + 8);
    arm_entry_probe(base + 0x305e9e8UL, (const unsigned int[4]){0xf9400a60, 0x97f69ea5, 0xb9407661, 0xd000dda0},
                    (void *)boot_fulfil_trampoline, boot_fulfil_continue, "run_i returned 0x305e9e8");
    xfer_continue = (void *)(base + 0x3599b68UL + 16);
    arm_entry_probe(base + 0x3599b68UL, (const unsigned int[4]){0xa9bc7bfd, 0x910003fd, 0xa90153f3, 0xaa0103f3}, (void *)xfer_probe_trampoline, xfer_continue, "async request build 0x3599b68");
    factor_branch_continue = (void *)(base + 0x305b9a0UL + 16);
    arm_entry_probe(base + 0x305b9a0UL, (const unsigned int[4]){0x910003bf, 0xa94153f3, 0xa9425bf5, 0xa94363f7}, (void *)factor_branch_probe_trampoline, factor_branch_continue, "boot factor >3 epilogue 0x305b9a0");
    seq4bd_req_continue = (void *)(base + 0x25018d4UL + 16);
    arm_entry_probe(base + 0x25018d4UL, (const unsigned int[4]){0xa9ba7bfd, 0x910003fd, 0xa90153f3, 0xaa0003f4},
                    (void *)seq4bd_req_probe_trampoline, seq4bd_req_continue, "0x4bd create request 0x25018d4");
    seq4bd_make_continue = (void *)(base + 0x24cc968UL + 16);
    arm_entry_probe(base + 0x24cc968UL, (const unsigned int[4]){0xd10343ff, 0x528005e0, 0xa9037bfd, 0x9100c3fd},
                    (void *)seq4bd_make_probe_trampoline, seq4bd_make_continue, "model::create_sequence 0x24cc968");
    seq4bd_continue = (void *)(base + 0x272fe10UL + 0);
    arm_entry_probe(base + 0x272fe00UL, (const unsigned int[4]){0xaa1303e0, 0xd2800002, 0x52800021, 0xb900d3bf},
                    (void *)seq4bd_probe_trampoline, seq4bd_continue, "boot_start_seq 0x4bd create 0x272fe00");
    run_i_gate_continue = (void *)(base + 0x305bcacUL + 16);
    run_i_gate_long = (void *)(base + 0x305e8b4UL);
    if (getenv("MENU_RUN_I_GATE"))
        arm_entry_probe(base + 0x305bcacUL, (const unsigned int[4]){0x3947d260, 0x35000060, 0x3947d660, 0x35015fe0},
                    (void *)run_i_gate_probe_trampoline, run_i_gate_continue, "run_i EE-join gate 0x305bcac");
    post_ee_continue = (void *)(base + 0x305bbecUL + 16);
    arm_entry_probe(base + 0x305bbecUL, (const unsigned int[4]){0x910503b4, 0x9103c3b5, 0xaa1503e0, 0x910363b9}, (void *)post_ee_probe_trampoline, post_ee_continue, "run_i post-EE join 0x305bbec");
    null_obj_continue = (void *)(base + 0x34f0cc0UL + 16);
    date_add_continue = (void *)(base + 0x36ecce8UL + 16);
    arm_entry_probe(base + 0x36ecce8UL, (const unsigned int[4]){0xa9bc7bfd, 0x910003fd, 0xf9000bf3, 0xaa0203f3}, (void *)date_add_probe_trampoline, date_add_continue, "date_time_add_seconds 0x36ecce8");
    arm_entry_probe(base + 0x34f0cc0UL, (const unsigned int[4]){0xf9400001, 0xb9400422, 0x51000842, 0x7100045f}, (void *)null_obj_probe_trampoline, null_obj_continue, "NULL object deref site 0x34f0cc0");

}
static void install_manager_probe(unsigned long base) {
    unsigned long target = base + 0x1e770e4UL;
    manager_continue_address = (void *)(target + 16);
    unsigned long page = target & ~0xfffUL;
    if (mprotect((void *)page, 4096, 7) != 0) {
        record("MANAGER_PROBE_FAILED ", "code page not writable");
        return;
    }
    unsigned int *code = (unsigned int *)target;
    code[0] = 0x58000050;                       /* ldr x16, [pc, #8] */
    code[1] = 0xd61f0200;                       /* br  x16 */
    *(unsigned long *)(target + 8) = (unsigned long)manager_probe_trampoline;
    clear_cache_range((void *)target, 16);
    char text[160];
    snprintf(text, sizeof text, "patched 0x1e770e4 -> trampoline=%p continue=%p",
             (void *)manager_probe_trampoline, manager_continue_address);
    record("MANAGER_PROBE_ARMED ", text);
}
/* libc entry points this file uses that are not declared elsewhere (freestanding build). */
extern char *strchr(const char *, int);
extern int dup2(int, int);
extern int sscanf(const char *, const char *, ...);

/* Menu-open attempt: rep_menu_controller is constructed by the framework through its vtable
   (runtime VA base+0x5b0c558, typeinfo base+0x5b0c530); init is slot 4 = base+0x20633c8 and it opens
   one of the menu screens 0x2c8/0x2c9/0x2ca chosen by *(u32*)(base+0x7ed79a8). Nothing in the app
   instantiates it in QEMU, so find an existing instance by scanning writable memory for a pointer to
   that vtable and, if one exists, drive it ourselves. */
static unsigned long find_pointer_in_memory(unsigned long want) {
    int maps = open("/proc/self/maps", 0);
    if (maps < 0) return 0;
    char buffer[8192];
    unsigned long found = 0;
    unsigned long scanned = 0;
    int used = 0;
    for (;;) {
        int n = read(maps, buffer + used, sizeof buffer - 1 - used);
        if (n <= 0) break;
        used += n;
        buffer[used] = 0;
        char *line = buffer;
        char *next;
        while ((next = strchr(line, '\n'))) {
            *next = 0;
            unsigned long start = 0, end = 0;
            char perms[8] = {0};
            /* MEASURED BUG: scanning every writable mapping also matched the observer's own log text.
               The previous run reported instance=0x003d646e756f6640, whose bytes spell ASCII
               "@found=", then read a "vtable" out of string data and crashed. Controller objects are
               heap/anon mappings, so skip any file-backed mapping (the only thing with a '/'). */
            if (sscanf(line, "%lx-%lx %7s", &start, &end, perms) == 3 && perms[0] == 'r' && perms[1] == 'w'
                && !strchr(line, '/')) {
                /* No address window: the instance sat ~1.2 GB away from appFw, which an earlier
                   ±512 MB heuristic wrongly excluded. Bound the scan by total bytes instead. */
                if (scanned < 0x60000000UL && end > start && end - start <= 0x40000000UL) {
                    unsigned long cursor = (start + 7) & ~7UL;
                    while (cursor + 8 <= end && scanned < 0x60000000UL) {
                        unsigned long value = *(volatile unsigned long *)cursor;
                        scanned += 8;
                        if (value == want) { found = cursor; break; }
                        cursor += 8;
                    }
                }
            }
            if (found) break;
            line = next + 1;
        }
        if (found) break;
        used = 0;
    }
    close(maps);
    {
        char text[96];
        snprintf(text, sizeof text, "scanned=%lu MB found=%#lx", scanned >> 20, found);
        record("POINTER_SCAN ", text);
    }
    return found;
}
/* Narrower menu-open attempt: skip rep_menu_controller::init (it runs transactions and constructs
   locals, and aborted when driven out of band) and call its last step directly, open_screen(this,
   &id1, &id2, &id3), with the id the application's own selector already points at. */
static unsigned int menu_open_attempts;
static void try_menu_open_screen(unsigned long instance) {
    if (!appfw_base || menu_open_attempts || !instance) return;
    if (!getenv("MENU_OPEN_SCREEN")) return;
    menu_open_attempts = 1;
    unsigned int selector = *(volatile unsigned int *)(appfw_base + 0x7ed79a8UL);
    unsigned int ids[3];
    ids[0] = selector <= 2 ? 0x2c8u + selector : 0x4b7u;
    ids[1] = 0x4b7u;
    ids[2] = 0x4b7u;
    char text[200];
    snprintf(text, sizeof text, "instance=%#lx selector=%u -> opening id1=%#x id2=%#x id3=%#x",
             instance, selector, ids[0], ids[1], ids[2]);
    record("MENU_OPEN_CALL ", text);
    typedef void (*open_t)(void *, void *, void *, void *);
    open_t open_screen = (open_t)(appfw_base + 0x2063270UL);
    open_screen((void *)instance, &ids[0], &ids[1], &ids[2]);
    record("MENU_OPEN_RETURNED ", "rep_menu_controller::open_screen returned");
}
/* Natural construction path for the menu controller (grok/menu-trigger-grok): factory table entry 838
   (id 0x346) carries aux 0x1d159f0, which builds the controller for a screen id using the per-id
   workspace at 0x7603190 + id*0x5000. Building it ourselves avoids the framework-side dispatch that
   aborted. Fields are logged before any virtual call so a bad object is visible instead of fatal. */
/* The launcher redirects the application's stdout/stderr into /tmp/im.log, so assert() messages vanish
   when the guest aborts. With MENU_STDIO_KMSG=1 send both to /dev/kmsg instead: they then appear in the
   console capture, which is the only channel that survives an abort. */
static void redirect_stdio_to_kmsg(void) {
    int console = open("/dev/console", 1);
    if (console < 0) { record("STDIO_KMSG_FAILED ", "/dev/console not writable"); return; }
    dup2(console, 1);
    dup2(console, 2);
    record("STDIO_KMSG_ACTIVE ", "stdout/stderr now go to /dev/console");
}
/* Observation only: wrap slot 4 (init) of all five mode-controller vtables so we can see which modes the
   framework actually activates in QEMU. Forwarding is 1:1, so this changes no behaviour. */
static const unsigned long mode_vtables[5] = { 0x5b0c4f0UL, 0x5b0c558UL, 0x5b0c5c0UL, 0x5b0c628UL, 0x5b0c690UL };
static void *(*mode_slot4_original[5])(void *, void *);
static const char *mode_slot4_names[5] = { "boot", "menu", "playback", "shooting", "single_playback" };
static unsigned int mode_slot4_calls[5];
static void *observe_mode_slot4(unsigned int index, void *a0, void *a1) {
    ++mode_slot4_calls[index];
    char text[160];
    snprintf(text, sizeof text, "mode=%s call=%u this=%p id_ptr=%p id=%#x", mode_slot4_names[index],
             mode_slot4_calls[index], a0, a1, a1 ? *(const unsigned int *)a1 : 0);
    record("MODE_SLOT4 ", text);
    if (mode_slot4_original[index]) return mode_slot4_original[index](a0, a1);
    return 0;
}
#define MODE_TRAMPOLINE(N) \
    static void *observe_mode_slot4_##N(void *a0, void *a1) { return observe_mode_slot4(N, a0, a1); }
MODE_TRAMPOLINE(0) MODE_TRAMPOLINE(1) MODE_TRAMPOLINE(2) MODE_TRAMPOLINE(3) MODE_TRAMPOLINE(4)
static void *(*const mode_slot4_wrapper[5])(void *, void *) = {
    observe_mode_slot4_0, observe_mode_slot4_1, observe_mode_slot4_2, observe_mode_slot4_3, observe_mode_slot4_4,
};
static void install_mode_sentinels(unsigned long base) {
    unsigned int armed = 0;
    for (unsigned int i = 0; i < 5; ++i) {
        unsigned long *slot = (unsigned long *)(base + mode_vtables[i] + 4 * 8);
        unsigned long page = (unsigned long)slot & ~0xfffUL;
        if (mprotect((void *)page, 4096, 7) != 0) continue;
        if (!*slot) continue;
        mode_slot4_original[i] = (void *(*)(void *, void *))*slot;
        *slot = (unsigned long)mode_slot4_wrapper[i];
        ++armed;
    }
    char text[96];
    snprintf(text, sizeof text, "armed=%u of 5 mode-controller init slots", armed);
    record("MODE_SENTINELS ", text);
}
/* Retain explicit diagnostics for legacy switches whose missing arguments could corrupt live pools. */
static unsigned int controller2_attempts;
static void try_build_controller2(void) {
    if (!getenv("MENU_BUILD_CONTROLLER2") || controller2_attempts) return;
    controller2_attempts = 1;
    record("BUILD2_DISABLED ", "legacy ctor ABI and workspace index were wrong; use framework lifecycle");
}
static unsigned int controller_build_attempts;
static void try_build_controller(void) {
    if (!getenv("MENU_BUILD_CONTROLLER") || controller_build_attempts) return;
    controller_build_attempts = 1;
    record("MENU_BUILD_DISABLED ", "legacy aux ABI omitted required arguments; shared workspace is live");
}
/* Generic mode-controller activation. All five rep_* controllers share one vtable layout (stride 0x68,
   slot 4 = init): boot 0x5b0c4f0, menu 0x5b0c558, playback 0x5b0c5c0, shooting 0x5b0c628,
   single_playback 0x5b0c690 - so "the framework activates a mode" is exactly vtable[4](obj, &screen_id).
   MENU_ACTIVATE_MODE=<0..4|boot|menu|playback|shooting|single> drives the instance we find on the heap. */
/* MEASURED CORRECTION: the previous order was off by one. Read the length-prefixed Itanium name
   each vtable stores at +0x48 (vtable+72 -> name string):
     0x5b0c4f0 "19rep_menu_controller"
     0x5b0c558 "23rep_playback_controller"
     0x5b0c5c0 "23rep_shooting_controller"        <- the real shooting controller
     0x5b0c628 "30rep_single_playback_controller"
     0x5b0c690 "23s_025_008_43_controller"
   So a previous MENU_ACTIVATE_MODE=shooting drove 0x5b0c628, i.e. single_playback - which is why it
   could never produce a shooting screen. There is no "boot" controller in this set. */
static const char *mode_names[5] = { "menu", "playback", "shooting", "single_playback", "s02500843" };
static unsigned int mode_activate_attempts;
static void try_activate_mode(void) {
    if (!appfw_base || mode_activate_attempts) return;
    const char *spec = getenv("MENU_ACTIVATE_MODE");
    if (!spec || !*spec) return;
    mode_activate_attempts = 1;
    int index = -1;
    if (spec[0] >= '0' && spec[0] <= '9') index = spec[0] - '0';
    else for (int i = 0; i < 5; ++i) {
        const char *n = mode_names[i];
        int k = 0;
        while (n[k] && spec[k] == n[k]) ++k;
        if (!n[k]) { index = i; break; }
    }
    if (index < 0 || index > 4) { record("MODE_ACTIVATE ", "bad MENU_ACTIVATE_MODE value"); return; }
    char text[200];
    snprintf(text, sizeof text, "mode=%s vtable=appFw+%#lx scanning heap...", mode_names[index], mode_vtables[index]);
    record("MODE_ACTIVATE_START ", text);
    unsigned long instance = find_pointer_in_memory(appfw_base + mode_vtables[index]);
    if (!instance) { record("MODE_ACTIVATE_NO_INSTANCE ", "no instance of that controller on the heap"); return; }
    typedef void (*init_t)(void *, void *);
    init_t init = (init_t)(*(unsigned long *)(*(unsigned long *)instance + 4 * 8));
    unsigned int screen_id = 0x4b7;
    snprintf(text, sizeof text, "instance=%#lx slot4=%#lx calling init(&id=%#x)",
             instance, (unsigned long)init, screen_id);
    record("MODE_ACTIVATE_CALL ", text);
    init((void *)instance, &screen_id);
    record("MODE_ACTIVATE_RETURNED ", "controller init returned");
}
/* MEASURED: the full-heap scan in try_activate_mode never finishes (it walks up to 1.5 GB and the
   run ended right after MODE_ACTIVATE_START). The UI manager already holds controller pointers - the
   apply path prints boot_controller at +0x330 - so read the slots directly instead of scanning.
   Dereference is guarded by a snapshot of the process's writable mappings so a stale slot cannot
   take the run down with SIGSEGV. */
static int addr_in_writable_map(unsigned long addr) {
    int maps = open("/proc/self/maps", 0);
    if (maps < 0) return 0;
    static char buffer[8192];
    int used = 0, hit = 0;
    for (;;) {
        int n = read(maps, buffer + used, sizeof buffer - 1 - used);
        if (n <= 0) break;
        used += n;
        buffer[used] = 0;
        char *line = buffer, *next;
        while ((next = strchr(line, '\n'))) {
            *next = 0;
            unsigned long start = 0, end = 0;
            char perms[8] = {0};
            if (sscanf(line, "%lx-%lx %7s", &start, &end, perms) == 3 &&
                perms[0] == 'r' && perms[1] == 'w' && addr >= start && addr + 8 <= end) { hit = 1; break; }
            line = next + 1;
        }
        if (hit) break;
        used = 0;
    }
    return hit;
}
static void dump_manager_slots(void) {
    if (!getenv("MENU_MODE_SLOTS") || !captured_manager || !appfw_base) return;
    static unsigned int done;
    if (done) return;
    if ((unsigned int)syscall(178) != ui_thread_id) return;
    done = 1;
    unsigned long m = captured_manager;
    for (unsigned int off = 0x300; off <= 0x3f8; off += 8) {
        unsigned long p = *(unsigned long *)(m + off);
        if (!p || !addr_in_writable_map(p)) continue;
        unsigned long vt = *(unsigned long *)p;
        char text[160];
        snprintf(text, sizeof text, "off=%#x ptr=%#lx vtable_rel=%ld slot4_rel=%ld",
                 off, p, vt ? (long)(vt - appfw_base) : -1L,
                 vt && addr_in_writable_map(vt) ? -1L : (vt ? (long)(*(unsigned long *)(vt + 32) - appfw_base) : -1L));
        record("MODE_SLOT ", text);
    }
}
static unsigned int menu_init_attempts;
static void try_menu_init(void) {
    if (!appfw_base || menu_init_attempts) return;
    if (!getenv("MENU_MENU_INIT") && !getenv("MENU_OPEN_SCREEN")) return;
    if (getenv("MENU_BUILD_CONTROLLER2")) { record("MENU_INIT_SKIPPED ", "using the locally built controller instead"); return; }
    unsigned long vtable = appfw_base + 0x5b0c558UL;
    unsigned int *selector = (unsigned int *)(appfw_base + 0x7ed79a8UL);
    char text[200];
    snprintf(text, sizeof text, "selector_before=%u vtable=appFw+0x5b0c558 scanning...", *selector);
    record("MENU_INIT_START ", text);
    unsigned long instance = captured_menu_controller;
    if (!instance) {
        /* Only fall back to the (slow) scan when we were not able to grab the constructor's object -
           inside the init window the scan is too slow and destabilises the guest. */
        if (getenv("MENU_FORCE_IN_FACTORY")) {
            record("MENU_INIT_NO_CAPTURE ", "ctor probe has not seen the controller and scanning is unsafe here");
            return;
        }
        instance = find_pointer_in_memory(vtable);
    }
    if (!instance) { record("MENU_INIT_NO_INSTANCE ", "no writable pointer to the rep_menu_controller vtable"); return; }
    /* Only now is this attempt spent: a hook point that fired before the framework constructed the
       controller must leave the next hook point free to try again. */
    menu_init_attempts = 1;
    void *instance_manager = *(void **)((char *)instance + 0x180);
    snprintf(text, sizeof text, "instance=%#lx selector=%u vtable=%p manager_180=%p field_178=%#lx",
             instance, *selector, *(void **)instance, instance_manager,
             *(unsigned long *)((char *)instance + 0x178));
    record("MENU_INIT_INSTANCE ", text);
    if (!instance_manager) {
        /* grok: init() dereferences [this+0x180]; an instance without a manager cannot be driven. */
        record("MENU_INIT_UNUSABLE ", "instance+0x180 (manager) is null; skipping init");
        return;
    }
    if (getenv("MENU_OPEN_SCREEN")) {
        /* The caller asked for the narrower path; keep the selector untouched. */
        try_menu_open_screen(instance);
        return;
    }
    if (getenv("MENU_INIT_LOG_ONLY")) {
        record("MENU_INIT_LOG_ONLY ", "scan only; no virtual call");
        return;
    }
    if (getenv("MENU_INIT_SELECTOR")) {
        unsigned int value = (unsigned int)(getenv("MENU_INIT_SELECTOR")[0] - '0');
        unsigned int *mirror = (unsigned int *)(appfw_base + 0x83d9d00UL);   /* publishing function copies this back */
        *selector = value;
        *mirror = value;                                                      /* keep them consistent */
        snprintf(text, sizeof text, "selector and mirror set to %u", value);
        record("MENU_INIT_SELECTOR_SET ", text);
    }
    unsigned int screen_id = 0x4b7;                  /* any id outside the 0x2c8..0x2ca / 0x346 set */
    typedef void (*init_t)(void *, void *);
    init_t init = (init_t)(appfw_base + 0x20633c8UL);
    snprintf(text, sizeof text, "calling init(this=%#lx, id=%#x)", instance, screen_id);
    record("MENU_INIT_CALL ", text);
    init((void *)instance, &screen_id);
    record("MENU_INIT_RETURNED ", "rep_menu_controller::init returned");
}
/* The framework constructs the menu controller itself (an instance with vtable 0x5b0c558 exists on the
   heap), but scanning for it inside the init window is far too slow. Capture it at the constructor
   entry instead - the ctor is menu-specific (it hardcodes w1=0x346 at 0x1d1586c) and x0 is the object
   under construction, so a 16-byte entry stub gives us the pointer in microseconds. */
void capture_menu_controller(unsigned long candidate) {
    if (!captured_menu_controller) {
        captured_menu_controller = candidate;
        char text[144];
        snprintf(text, sizeof text, "object=%#lx (from the rep_menu_controller ctor at 0x1d15858)", candidate);
        record("MENU_CONTROLLER_SEEN ", text);
    }
}
__asm__(
".text\n"
".globl menu_ctor_trampoline\n"
".type menu_ctor_trampoline, %function\n"
"menu_ctor_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_menu_controller\n"
PROBE_RESTORE_ARGS
"    sub sp, sp, #0x1c0\n"              /* 原函数前 4 条 */
"    stp x29, x30, [sp, #0x140]\n"
"    add x29, sp, #0x140\n"
"    stp x23, x24, [sp, #0x170]\n"
"    adrp x16, menu_ctor_continue\n"
"    ldr x16, [x16, #:lo12:menu_ctor_continue]\n"
"    br x16\n"
);
extern void menu_ctor_trampoline(void);
static void *menu_ctor_continue;
static void install_menu_ctor_probe(unsigned long base) {
    unsigned long target = base + 0x1d15858UL;
    menu_ctor_continue = (void *)(target + 16);
    unsigned long page = target & ~0xfffUL;
    if (mprotect((void *)page, 4096, 7) != 0) { record("MENU_CTOR_PROBE_FAILED ", "code page not writable"); return; }
    unsigned int *code = (unsigned int *)target;
    code[0] = 0x58000050;                       /* ldr x16, [pc, #8] */
    code[1] = 0xd61f0200;                       /* br  x16 */
    *(unsigned long *)(target + 8) = (unsigned long)menu_ctor_trampoline;
    clear_cache_range((void *)target, 16);
    record("MENU_CTOR_PROBE_ARMED ", "0x1d15858 patched");
}
/* Manager slot3 enqueues (owner, screen, previous, true, false); it does not render synchronously.
   MENU_OPEN_SET=owner,screen[,previous] defaults previous to owner. Mutation requires EXECUTE. */
static int parse_open_set(const char *spec, unsigned int ids[3]) {
    for (unsigned int slot = 0; slot < 3; ++slot) {
        unsigned int value = 0, digits = 0, radix = 10;
        if (spec[0] == '0' && (spec[1] == 'x' || spec[1] == 'X')) { radix = 16; spec += 2; }
        for (;;) {
            unsigned int digit;
            if (*spec >= '0' && *spec <= '9') digit = (unsigned int)(*spec - '0');
            else if (*spec >= 'a' && *spec <= 'f') digit = (unsigned int)(*spec - 'a' + 10);
            else if (*spec >= 'A' && *spec <= 'F') digit = (unsigned int)(*spec - 'A' + 10);
            else break;
            if (digit >= radix) return 0;
            value = value * radix + digit;
            if (value >= 0x4b7) return 0;
            ++spec; ++digits;
        }
        if (!digits) return 0;
        ids[slot] = value;
        if (!*spec) {
            if (slot == 0) return 0;
            if (slot == 1) ids[2] = ids[0];
            return 1;
        }
        if (*spec++ != ',') return 0;
    }
    return 0;
}
static unsigned int open_set_attempts;
/* Input injection. The 32-byte InfraInput event layout and the MENU key code come from the firmware's
   own conversion tables: +0 key code 0x1ab maps to UIBIZ 0x13, +8 status 1 with +0x14 repeat count 0
   selects MENU_ON 0x0201000f (table A:0x5bc2b60, MENU entry 0x5bc2bb0). The template must go through
   App::input_infra_callback (source 0x005503e0); send_event uses 0x00830128 and bypasses this
   conversion entirely, so it can never produce a key event. Opt-in: MENU_INJECT_KEY=press|pressrelease. */
static unsigned int inject_key_done;
static unsigned int card_error_rendered;
static unsigned int last_input_screen;
static unsigned long long live_key_last_seq;
static unsigned int live_key_code,live_key_status;
static volatile unsigned int live_key_pending;
static volatile unsigned int live_key_stop;
extern int strcmp(const char *, const char *);
extern int usleep(unsigned int);
static unsigned int sd_ack_worker_started,sd_ack_start_failures;
static void *sd_ack_retry_worker(void *unused) {
    (void)unused;
    for(;;) {
        file_media_flush_cancel_retry_fn();
        usleep(100000);
    }
    return 0;
}
static void start_sd_ack_retry_worker(void) {
    if(!file_media_flush_cancel_retry_fn || !sd_ack_create || !sd_ack_detach)return;
    unsigned int expected=0;
    if(!__atomic_compare_exchange_n(&sd_ack_worker_started,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return;
    pthread_t thread;int rc=sd_ack_create(&thread,0,sd_ack_retry_worker,0);
    if(rc) {
        __atomic_store_n(&sd_ack_worker_started,0,__ATOMIC_RELEASE);
        unsigned int n=__atomic_add_fetch(&sd_ack_start_failures,1,__ATOMIC_RELAXED);
        if(n<=8 || !(n&(n-1))) {
            char text[100];snprintf(text,sizeof text,"pid=%d rc=%d failures=%u",getpid(),rc,n);
            record("SD_ACK_RETRY_WORKER_FAILED ",text);
        }
    } else {
        char text[120];snprintf(text,sizeof text,"pid=%d thread=%#lx detach_rc=%d ack_only=1",getpid(),thread,sd_ack_detach(thread));
        record("SD_ACK_RETRY_WORKER ",text);
    }
}
static void *live_key_worker(void *unused) {
    (void)unused;
    const char *path=getenv("MENU_LIVE_KEY_FILE");
    if(!path || strcmp(path,"/tmp/menu-key.request"))return 0;
    while(!__atomic_load_n(&live_key_stop,__ATOMIC_ACQUIRE)) {
        int fd=open(path,0);char buffer[96];
        if(fd>=0) {
            long n=read(fd,buffer,sizeof buffer-1);close(fd);
            if(n>0) {
                unsigned int code=0,status=0;unsigned long long seq=0;buffer[n]=0;
                if(sscanf(buffer,"%x %x %llu",&code,&status,&seq)==3 && seq>live_key_last_seq &&
                   !__atomic_load_n(&live_key_pending,__ATOMIC_ACQUIRE) &&
                   status<=1 && (code==0x1ab||code==0x1ac||code==0x3||code==0x30||
                                 code==0x15||code==0x1af||code==0x1f8)) {
                    /* The verified MENU/confirm path runs on the UI thread after drawFramebuffer.
                       Only record the request here; the UI thread performs the callback. */
                    live_key_code=code;live_key_status=status;live_key_last_seq=seq;
                    __atomic_store_n(&live_key_pending,1,__ATOMIC_RELEASE);
                    char text[120];snprintf(text,sizeof text,"queued pid=%ld seq=%llu key=%#x status=%u",(long)getpid(),seq,code,status);
                    record("KEY_INJECT ",text);
                }
            }
        }
        usleep(20000);
    }
    return 0;
}
static void start_live_key_worker(void) {
    static unsigned int started;
    if(started || !getenv("MENU_LIVE_KEY_FILE"))return;
    int (*create)(pthread_t *,const void *,void *(*)(void *),void *)=real_dlsym((void *)-1,"pthread_create");
    if(!create)return;
    pthread_t thread;
    if(!create(&thread,0,live_key_worker,0))started=1;
}
static unsigned int auto_last_screen_gen, auto_steps;
static unsigned int create_screen_calls;
static void try_inject_key(void) {
    if (!appfw_base) return;
    const char *early_mode = getenv("MENU_INJECT_KEY");
    if (early_mode && !strcmp(early_mode, "auto-firstboot")) {
        /* Scripted first-setup walk: one CONFIRM per newly created screen, always on the
           original UI thread at frame return (the only channel measured to be consumed). */
        if (!__atomic_load_n(&create_screen_returned, __ATOMIC_ACQUIRE) ||
            __atomic_load_n(&create_screen_active, __ATOMIC_ACQUIRE)) return;
        if ((unsigned int)syscall(178) != ui_thread_id) return;
        unsigned int gen = __atomic_load_n(&create_screen_calls, __ATOMIC_ACQUIRE);
        if (gen < 2 || gen == auto_last_screen_gen || auto_steps >= 26) return;
        auto_last_screen_gen = gen; ++auto_steps;
        unsigned char ev[32];
        for (unsigned int i = 0; i < 32; ++i) ev[i] = 0;
        ev[0] = 0xac; ev[1] = 0x01; ev[8] = 1;
        typedef void (*callback_type)(int, const void *);
        callback_type cb = (callback_type)(appfw_base + 0x17988b4UL);
        /* dlg_rec203 (0x431) defaults to "set now"; step down once so the walk continues
           to the following setup page instead of re-entering the date screen. */
        if (__atomic_load_n(&last_input_screen, __ATOMIC_ACQUIRE) == 0x431) {
            unsigned char down[32];
            for (unsigned int i = 0; i < 32; ++i) down[i] = 0;
            down[0] = 0x30; down[8] = 1;
            cb(0, down);
            down[8] = 0;
            cb(0, down);
            record("KEY_INJECT ", "auto-firstboot DOWN sent on dlg_rec203");
        }
        char note[128];
        snprintf(note, sizeof note, "auto-firstboot step=%u gate_screen_calls=%u", auto_steps, gen);
        record("KEY_INJECT ", note);
        cb(0, ev);
        ev[8] = 0;
        cb(0, ev);
        snprintf(note, sizeof note, "auto-firstboot CONFIRM ON+OFF sent step=%u", auto_steps);
        record("KEY_INJECT ", note);
        return;
    }
    if (inject_key_done) return;
    if (!__atomic_load_n(&create_screen_returned, __ATOMIC_ACQUIRE) ||
        __atomic_load_n(&create_screen_active, __ATOMIC_ACQUIRE)) return;
    if ((unsigned int)syscall(178) != ui_thread_id) return;
    const char *mode = getenv("MENU_INJECT_KEY");
    if (!mode || !*mode) return;
    int language=strcmp(mode,"language-pressrelease")==0;
    int confirm=strcmp(mode,"confirm-pressrelease")==0 || language;
    if(language && __atomic_load_n(&last_input_screen,__ATOMIC_ACQUIRE)!=0x12d)return;
    if(confirm && !language && !__atomic_load_n(&card_error_rendered,__ATOMIC_ACQUIRE))return;
    inject_key_done = 1;
    if (strcmp(mode, "press") && strcmp(mode, "pressrelease") && !confirm) {
        record("KEY_INJECT ", "invalid mode; no event submitted");
        return;
    }
    unsigned char event[32];
    for (unsigned int i = 0; i < 32; ++i) event[i] = 0;
    event[0] = confirm?0xac:0xab; event[1] = 0x01; /* existing native input map: ENTER/MENU */
    event[8] = 1;                                   /* status ON */
    typedef void (*callback_type)(int, const void *);
    callback_type callback = (callback_type)(appfw_base + 0x17988b4UL);
    record("KEY_INJECT ", language?"submitting CONFIRM ON after original language screen frame":confirm?"submitting CONFIRM ON after original card-error render":"submitting MENU ON after frame return");
    callback(0, event);
    record("KEY_INJECT ", confirm?"CONFIRM ON sent through App::input_infra_callback":"MENU ON sent through App::input_infra_callback");
    if (strcmp(mode, "pressrelease") == 0 || confirm) {
        event[8] = 0;                               /* status OFF = release */
        callback(0, event);
        record("KEY_INJECT ", confirm?"CONFIRM OFF sent (release)":"MENU OFF sent (release)");
    }
}
static void try_open_set(void) {
    if (!appfw_base || open_set_attempts) return;
    if (!__atomic_load_n(&create_screen_returned, __ATOMIC_ACQUIRE) ||
        __atomic_load_n(&create_screen_active, __ATOMIC_ACQUIRE) ||
        (unsigned int)syscall(178) != ui_thread_id) return;
    if (!captured_manager) {
        if (getenv("MENU_OPEN_SET_LOG_ONLY")) { record("MENU_OPEN_SET_WAIT ", "manager not captured yet"); open_set_attempts = 0; }
        return;
    }
    const char *spec = getenv("MENU_OPEN_SET");
    if (!spec || !*spec) return;
    open_set_attempts = 1;
    void **vtable = *(void ***)captured_manager;
    char text[224];
    if ((unsigned long)vtable != appfw_base + 0x5b0c480UL ||
        (unsigned long)vtable[3] != appfw_base + 0x1e77dd8UL) {
        record("OPEN_SET_NO_VTABLE ", "manager vtable does not match verified ABI");
        return;
    }
    if (!getenv("MENU_OPEN_SET_EXECUTE") || getenv("MENU_OPEN_SET_LOG_ONLY")) {
        snprintf(text, sizeof text,
                 "manager=%#lx vtable=%p slots=%p %p %p %p (log only; no call)",
                 captured_manager, (void *)vtable, vtable[0], vtable[1], vtable[2], vtable[3]);
        record("MENU_OPEN_SET_LOG_ONLY ", text);
        open_set_attempts = 1;
        return;
    }
    unsigned int ids[3];
    if (!parse_open_set(spec, ids)) {
        record("OPEN_SET_BAD_IDS ", "expected owner,screen[,previous], all below 0x4b7");
        return;
    }
    snprintf(text, sizeof text, "manager=%#lx slot3=%p owner=%#x screen=%#x previous=%#x",
             captured_manager, vtable[3], ids[0], ids[1], ids[2]);
    record("OPEN_SET_CALL ", text);
    typedef void (*open_t)(void *, void *, void *, void *, int, int);
    open_t open_screen = (open_t)vtable[3];
    open_screen((void *)captured_manager, &ids[0], &ids[1], &ids[2], 1, 0);
    record("OPEN_SET_RETURNED ", "manager enqueue returned; no claim of display completion");
}
static int ctor_census_attempts_used_class;
/* Bounded sample of objects passing through the shared base ctor; overflow is explicitly logged.
   Classification is deferred until create_screen has returned on the original UI thread. */
static unsigned long captured_objects[16];
static unsigned int captured_object_count;
void capture_controller_object(unsigned long pointer) {
    if (pointer) {
        unsigned int index = __atomic_fetch_add(&captured_object_count, 1, __ATOMIC_RELAXED);
        if (index >= 16) {
            if (index == 16) record("CTOR_CAPTURE_LIMIT ", "first 16 objects only; later constructors still run");
            return;
        }
        __atomic_store_n(&captured_objects[index], pointer, __ATOMIC_RELEASE);
        char text[96];
        snprintf(text, sizeof text, "obj[%u]=%#lx", index, pointer);
        record("CTOR_OBJECT ", text);
    }
}
__asm__(
".text\n"
".globl base_ctor_trampoline\n"
".type base_ctor_trampoline, %function\n"
"base_ctor_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_controller_object\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-0x50]!\n"
"    mov x29, sp\n"
"    stp x19, x20, [sp, #0x10]\n"
"    mov x19, x0\n"
"    adrp x16, base_ctor_continue\n"
"    ldr x16, [x16, #:lo12:base_ctor_continue]\n"
"    br x16\n"
);
extern void base_ctor_trampoline(void);
static void *base_ctor_continue;
static void install_base_ctor_probe(unsigned long base) {
    unsigned long target = base + 0x1ac61f8UL;
    base_ctor_continue = (void *)(target + 16);
    unsigned long page = target & ~0xfffUL;
    if (mprotect((void *)page, 4096, 7) != 0) { record("CTOR_PROBE_FAILED ", "page not writable"); return; }
    unsigned int *code = (unsigned int *)target;
    code[0] = 0x58000050;
    code[1] = 0xd61f0200;
    *(unsigned long *)(target + 8) = (unsigned long)base_ctor_trampoline;
    clear_cache_range((void *)target, 16);
    record("CTOR_PROBE_ARMED ", "0x1ac61f8 patched");
}
static unsigned int ctor_census_processed;
static void ctor_census_and_activate(void) {
    if (!appfw_base || !__atomic_load_n(&create_screen_returned, __ATOMIC_ACQUIRE) ||
        __atomic_load_n(&create_screen_active, __ATOMIC_ACQUIRE) ||
        (unsigned int)syscall(178) != ui_thread_id) return;
    unsigned int count = __atomic_load_n(&captured_object_count, __ATOMIC_ACQUIRE);
    if (count > 16) count = 16;
    const char *want = getenv("MENU_ACTIVATE_CAPTURED");
    for (unsigned int i = ctor_census_processed; i < count; ++i) {
        unsigned long object = __atomic_load_n(&captured_objects[i], __ATOMIC_ACQUIRE);
        if (!object) break;
        ctor_census_processed = i + 1;
        unsigned long vptr = *(unsigned long *)object;
        const char *klass = vptr == appfw_base + 0x5b0e298UL ? "scr0039_boot" : "unknown";
        for (unsigned int k = 0; k < 5; ++k)
            if (vptr == appfw_base + mode_vtables[k]) klass = mode_names[k];
        char text[176];
        snprintf(text, sizeof text, "obj=%#lx vptr=appFw+%#lx class=%s manager_180=%p",
                 object, vptr ? vptr - appfw_base : 0, klass, *(void **)((char *)object + 0x180));
        record("CTOR_CENSUS ", text);
        if (want && klass[0] != 'u' && vptr != appfw_base + 0x5b0e298UL && !ctor_census_attempts_used_class) {
            int match = 1;
            for (int k = 0; want[k] || klass[k]; ++k)
                if (want[k] != klass[k]) { match = 0; break; }
            if (match) {
                void *manager = *(void **)((char *)object + 0x180);
                if (!manager) { record("CTOR_ACTIVATE_SKIPPED ", "manager field is null"); continue; }
                ctor_census_attempts_used_class = 1;
                unsigned long init = *(unsigned long *)(vptr + 4 * 8);
                unsigned int screen_id = 0x4b7;
                snprintf(text, sizeof text, "activating class=%s obj=%#lx init=%#lx", klass, object, init);
                record("CTOR_ACTIVATE_CALL ", text);
                typedef void (*init_t)(void *, void *);
                ((init_t)init)((void *)object, &screen_id);
                record("CTOR_ACTIVATE_RETURNED ", "controller init returned");
            }
        }
    }
}
static int ux_render_attempts;
static void ux_render_poke(const char *why) {
    if (!real_dlsym) return;
    static void *(*get_wgtsys)(void);
    static int (*notify_draw)(void *);
    if (!get_wgtsys) get_wgtsys = real_dlsym((void *)-1, "_ZN2ux6wgtsys12WidgetSystem15sys_getInstanceEv");
    if (!notify_draw) notify_draw = real_dlsym((void *)-1, "_ZN2ux6wgtsys12WidgetSystem10notifyDrawEv");
    if (!get_wgtsys || !notify_draw) {
        record("UX_RENDER_POKE ", "WidgetSystem entry points not found");
        return;
    }
    void *widget_system = get_wgtsys();
    if (!widget_system) { record("UX_RENDER_POKE ", "WidgetSystem instance is NULL"); return; }
    unsigned int attempt = ++ux_render_attempts;
    int draw_result = notify_draw(widget_system);
    char text[192];
    snprintf(text, sizeof text, "attempt=%u why=%s wgtsys=%p notifyDraw=%d", attempt, why, widget_system, draw_result);
    record("UX_RENDER_POKE ", text);
}
/* Screen factory capture. The dispatcher 0x1e4bacc calls factory(id[w0], ctx[x1], mgr+0x40|[mgr+0x38][x2],
   id[w3], idx[w4], param[w5]) - so w4 tells one shared wrapper which table entry it stands for, and the
   originals can be re-read from the saved copy. Writing the table (VA 0x51f7810, .data.rel.ro) only fills
   in the mgr/param context the application itself uses, which is exactly what a forced call would need. */
#define FACTORY_TABLE_ENTRIES 864
static unsigned long *factory_table_address;
static void *(*factory_original[FACTORY_TABLE_ENTRIES])(void *, void *, void *, void *, void *, void *);
static unsigned int factory_capture_count;
static void *captured_mgr_arg;
static unsigned int forced_dispatch_done;

/* Force the application to build another screen set. mgr = the x2 the application itself passed minus
   0x40 (dispatch() derives x2 from mgr), so once we have seen one factory call we hold every input the
   dispatcher needs. Indices come from MENU_FORCE_SET as a comma-separated list. */
static void force_screen_set(const char *why) {
    const char *spec = getenv("MENU_FORCE_SET");
    if (!spec || !*spec) return;
    {
        char diag[176];
        snprintf(diag, sizeof diag, "why=%s done=%u mgr=%#lx base=%#lx spec=%s",
                 why, forced_dispatch_done, captured_manager, appfw_base, spec);
        record("FORCE_SET_ENTER ", diag);
    }
    if (forced_dispatch_done || !captured_manager || !appfw_base) return;
    forced_dispatch_done = 1;
    typedef void *(*dispatch_t)(void *, int, int);
    dispatch_t dispatch = (dispatch_t)(appfw_base + 0x1e4baccUL);
    unsigned int current = 0;
    const char *cursor = spec;
    for (;;) {
        if (*cursor >= '0' && *cursor <= '9') {
            current = current * 10 + (unsigned int)(*cursor - '0');
        } else {
            if (current) {
                /* Log before the call so a crash inside the dispatcher still leaves a trace in /dev/kmsg. */
                char begin[160];
                snprintf(begin, sizeof begin, "begin why=%s idx=%u mgr=%p (mgr_arg=%p)",
                         why, current, (void *)captured_manager, (void *)captured_mgr_arg);
                record("FORCE_SET_BEGIN ", begin);
                void *set = dispatch((void *)captured_manager, (int)current, 0);
                char text[160];
                snprintf(text, sizeof text, "why=%s idx=%u returned=%p", why, current, set);
                record("FORCE_SET ", text);
                if (set && getenv("MENU_FORCE_OPEN_AFTER")) {
                    /* Second half of the same in-init window: hand the freshly built controller to
                       open_screen so it actually pushes its screen, exactly as init's tail does. */
                    unsigned int selector = *(volatile unsigned int *)(appfw_base + 0x7ed79a8UL);
                    unsigned int ids[3];
                    ids[0] = selector <= 2 ? 0x2c8u + selector : 0x4b7u;
                    ids[1] = 0x4b7u;
                    ids[2] = 0x4b7u;
                    void *manager_field = *(void **)((char *)set + 0x180);
                    unsigned long field_178 = *(unsigned long *)((char *)set + 0x178);
                    char open_text[240];
                    snprintf(open_text, sizeof open_text,
                             "controller=%p vtable=%p manager_180=%p field_178=%#lx selector=%u id1=%#x",
                             set, *(void **)set, manager_field, field_178, selector, ids[0]);
                    record("FORCE_OPEN_FIELDS ", open_text);
                    if (!manager_field) {
                        record("FORCE_OPEN_SKIPPED ", "object+0x180 (manager) is null; open_screen would dereference it");
                        return;
                    }
                    record("FORCE_OPEN_BEGIN ", "manager field is non-null; calling open_screen");
                    typedef void (*open_t)(void *, void *, void *, void *);
                    open_t open_screen = (open_t)(appfw_base + 0x2063270UL);
                    open_screen(set, &ids[0], &ids[1], &ids[2]);
                    record("FORCE_OPEN_RETURNED ", "open_screen returned inside init");
                }
            } else {
                record("FORCE_SET ", "ignored an empty index in MENU_FORCE_SET");
            }
            current = 0;
            if (*cursor == 0) break;
        }
        ++cursor;
    }
}
static void *observe_factory_entry(void *a0, void *a1, void *a2, void *a3, void *a4, void *a5) {
    unsigned long index = (unsigned long)a4;
    if (!captured_mgr_arg) captured_mgr_arg = a2;
    if (factory_capture_count < 60 && index < FACTORY_TABLE_ENTRIES) {
        ++factory_capture_count;
        char text[224];
        snprintf(text, sizeof text,
                 "idx=%lu id=%#lx (w0=%#lx w3=%#lx) ctx=%p mgr_arg=%p param=%#lx vtable_hint=0x1e4bacc",
                 index, (unsigned long)a3, (unsigned long)a0, (unsigned long)a3, a1, a2, (unsigned long)a5);
        record("FACTORY_CALL ", text);
    }
    void *result = 0;
    if (index < FACTORY_TABLE_ENTRIES && factory_original[index])
        result = factory_original[index](a0, a1, a2, a3, a4, a5);
    /* Optional in-init trigger: the manager is only usable while Application_System_Init runs, so with
       MENU_FORCE_IN_FACTORY=1 fire here (the manager is mid-use but valid) instead of in the message loop. */
    if (getenv("MENU_FORCE_IN_FACTORY")) force_screen_set("in_factory_during_init");
    /* Same in-init window: init() wraps its body in transactions, so driving it from the message loop
       aborted; calling it while Application_System_Init runs is the supported context. */
    if (getenv("MENU_FORCE_IN_FACTORY") && getenv("MENU_MENU_INIT")) try_menu_init();
    /* (open-set is driven from the init window only: the manager is invalid afterwards) */
    if (getenv("MENU_OPEN_SET")) try_open_set();
    if (getenv("MENU_FORCE_IN_FACTORY") && getenv("MENU_ACTIVATE_MODE")) try_activate_mode();
    if (getenv("MENU_FORCE_IN_FACTORY")) try_build_controller2();
    if (getenv("MENU_FORCE_IN_FACTORY") && getenv("MENU_MENU_INIT")) try_menu_init();
    return result;
}
static void install_factory_capture(unsigned long base) {
    factory_table_address = (unsigned long *)(base + 0x51f7810UL);
    unsigned long page = (unsigned long)factory_table_address & ~0xfffUL;
    if (mprotect((void *)page, 0x200000, 7) != 0) {
        record("FACTORY_HOOK_FAILED ", "factory table page is not writable");
        return;
    }
    unsigned int patched = 0;
    for (unsigned int i = 0; i < FACTORY_TABLE_ENTRIES; ++i) {
        unsigned long *slot = factory_table_address + (unsigned long)i * 12;   /* 96 bytes = 12 words */
        if (!*slot) continue;
        factory_original[i] = (void *(*)(void *, void *, void *, void *, void *, void *))*slot;
        *slot = (unsigned long)observe_factory_entry;
        ++patched;
    }
    char text[128];
    snprintf(text, sizeof text, "patched=%u table=appFw+%#lx", patched, 0x51f7810UL);
    record("FACTORY_HOOK_ARMED ", text);
}
/* Read-only: the factory looks its builder up in a .bss registry at VA 0x7603168 keyed by screen id
   (adrp x6,#0x7603000; add x6,x6,#0x168; ldr x19,[x6,w0,sxtw#3]). Enumerating the non-null entries
   tells us exactly which screen sets the application has registered - a much shorter candidate list for
   the menu than the 864-entry factory table. */
static void dump_screen_registry(void) {
    if (!appfw_base) return;
    const unsigned long *registry = (const unsigned long *)(appfw_base + 0x7603168UL);
    char line[180];
    unsigned int written = 0, count = 0;
    line[0] = 0;
    for (unsigned int i = 0; i < 4096; ++i) {
        if (!registry[i]) continue;
        ++count;
        char piece[24];
        int n = snprintf(piece, sizeof piece, "%s%u:appFw+%#lx", written ? " " : "", i,
                         (unsigned long)registry[i] - appfw_base);
        if (n <= 0) break;
        for (int k = 0; piece[k] && written < sizeof line - 32; ++k) line[written++] = piece[k];
        if (written > sizeof line - 40) {
            line[written] = 0;
            record("SCREEN_REGISTRY ", line);
            written = 0; line[0] = 0;
        }
    }
    if (written) { line[written] = 0; record("SCREEN_REGISTRY ", line); }
    char text[96];
    snprintf(text, sizeof text, "non_null=%u of 4096", count);
    record("SCREEN_REGISTRY_TOTAL ", text);
}
static unsigned long captured_dialog_presenter;
static unsigned int captured_dialog_call,dialog_value_count,last_dialog_value=0xffffffffU;
static void capture_dialog_presenter(int fd,unsigned long caller_fp,unsigned int call) {
    unsigned long p=0,vptr=0,getter=0,table=0,method=0;unsigned int screen=0;
    unsigned short index=0xffff;unsigned int index_known=0;
    if(caller_fp>0x7fffffffffffffdfUL || pread(fd,&p,8,(long)(caller_fp+0x10))!=8 ||
       !p || p>0x7fffffffffffd51fUL || pread(fd,&vptr,8,(long)p)!=8 ||
       vptr!=appfw_base+0x59590b8UL || pread(fd,&screen,4,(long)(p+0x30))!=4 || screen!=0x322 ||
       pread(fd,&getter,8,(long)(p+0x2ac8))!=8 || !getter || getter>0x7ffffffffffffff7UL ||
       pread(fd,&table,8,(long)getter)!=8 || !table || table>0x7ffffffffffffff7UL ||
       pread(fd,&method,8,(long)table)!=8)return;
    if(table==appfw_base+0x59128c0UL && method==appfw_base+0x1882dc8UL &&
       getter<=0x7fffffffffffffedUL && pread(fd,&index,2,(long)(getter+0x10))==2)index_known=1;
    captured_dialog_presenter=p;captured_dialog_call=call;dialog_value_count=0;last_dialog_value=0xffffffffU;
    char text[300];snprintf(text,sizeof text,"call=%u screen=%#x presenter=%#lx getter=%#lx getter_vtable=%#lx method=%#lx method_appFw_offset=%#lx index_known=%u module_index=%#x",
                           call,screen,p,getter,table,method,method>=appfw_base?method-appfw_base:0,index_known,index);
    record("RESOURCE_DIALOG_GETTER_CAPTURED ",text);
}
static void capture_dialog_resource(void) {
    if(!captured_dialog_presenter || dialog_value_count>=16)return;
    int saved_errno=*__errno_location();int fd=open("/proc/self/mem",0);
    unsigned long p=captured_dialog_presenter,vptr=0,array=0,param=0;unsigned int screen=0,kind=0,value=0;
    if(fd>=0 && pread(fd,&vptr,8,(long)p)==8 && vptr==appfw_base+0x59590b8UL &&
       pread(fd,&screen,4,(long)(p+0x30))==4 && screen==0x322 &&
       pread(fd,&array,8,(long)(p+0x28))==8 && array && array<=0x7fffffffffffffbfUL &&
       pread(fd,&kind,4,(long)(array+0x30))==4 && kind==2 &&
       pread(fd,&param,8,(long)(array+0x38))==8 && param && param<=0x7fffffffffffffcbUL &&
       pread(fd,&value,4,(long)(param+0x30))==4 && value!=last_dialog_value) {
        last_dialog_value=value;dialog_value_count++;
        if(value==0x0200a73bU)__atomic_store_n(&card_error_rendered,1,__ATOMIC_RELEASE);
        char text[260];snprintf(text,sizeof text,"call=%u sample=%u tid=%ld screen=%#x presenter=%#lx text_param=%#lx text_resource=%#x source=original-view-string-param",
                               captured_dialog_call,dialog_value_count,syscall(178),screen,p,param,value);
        record("RESOURCE_DIALOG_VALUE ",text);
    }
    if(fd>=0)close(fd);
    *__errno_location()=saved_errno;
}
static void capture_dialog_frames(unsigned long first,unsigned int call) {
    int saved_errno=*__errno_location();
    int fd=open("/proc/self/mem",0);
    unsigned long fp=first;
    unsigned int count=0;
    for(unsigned int depth=0;fd>=0 && depth<16;depth++) {
        unsigned long words[2];
        if(fp<first || fp-first>0x40000UL || fp%16 ||
           fp>0x7fffffffffffffefUL || pread(fd,words,sizeof words,(long)fp)!=(long)sizeof words)break;
        char text[240];
        unsigned long lr=words[1];
        snprintf(text,sizeof text,"call=%u tid=%ld depth=%u fp=%#lx lr=%#lx appFw_offset=%#lx in_appFw=%u",
                 call,syscall(178),depth,fp,lr,lr>=appfw_base?lr-appfw_base:0,
                 appfw_base && lr>=appfw_base && lr-appfw_base<0x6000000UL);
        record("CREATE_SCREEN_DIALOG_FRAME ",text);count++;
        if(lr==appfw_base+0x1e795ecUL) {
            unsigned long event=0;unsigned int group=0,screen=0,extra=0;
            /* 1e78870 saves caller x21 at fp+20; 1e78dbc keeps its input event in x21. */
            if(pread(fd,&event,8,(long)(fp+0x20))==8 && event>=4096 && event<0x8000000000UL &&
               pread(fd,&group,4,(long)(words[0]+0xa4))==4 &&
               pread(fd,&screen,4,(long)(words[0]+0xa8))==4 &&
               pread(fd,&extra,4,(long)(words[0]+0xc8))==4 && screen==0x30c) {
                snprintf(text,sizeof text,"call=%u event=%#lx queue_group=%#x target=%#x extra=%#x",call,event,group,screen,extra);
                record("CREATE_SCREEN_SYSTEM_CAUSE ",text);
                unsigned char data[0x178];
                if(pread(fd,data,sizeof data,(long)event)==sizeof data)for(unsigned int offset=0;offset<sizeof data;offset+=64) {
                    unsigned int n=sizeof data-offset;if(n>64)n=64;char raw[129];
                    for(unsigned int j=0;j<n;j++)snprintf(raw+2*j,3,"%02x",data[offset+j]);
                    snprintf(text,sizeof text,"call=%u offset=%u raw=%s",call,offset,raw);
                    record("CREATE_SCREEN_SYSTEM_EVENT ",text);
                }
            }
        }
        if(depth==0 && lr==appfw_base+0x1d56688UL && words[0]>fp &&
           words[0]-first<=0x40000UL && !(words[0]&15))
            capture_dialog_presenter(fd,words[0],call);
        if(words[0]<=fp)break;
        fp=words[0];
    }
    if(fd>=0)close(fd);
    if(!count)record("CREATE_SCREEN_DIALOG_TRACE_UNAVAILABLE ","no-readable-bounded-frame");
    *__errno_location()=saved_errno;
}
static void *observe_create_screen(void *a0, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7) {
    __atomic_add_fetch(&create_screen_active, 1, __ATOMIC_RELEASE);
    unsigned int id = (unsigned int)(unsigned long)a1;
    unsigned long count = (unsigned long)a3;
    unsigned int orientation = (unsigned int)(unsigned long)a4;
    /* ds_create_screen_param is 52 (0x34) bytes per entry; +0 is the screen kind, which is also the
       index into the ctor tables at VA 0x51b82a0 / 0x51b8790. Log the first kinds so we can tell the
       menu screen apart from whatever this boot actually creates. */
    char kinds[200];
    unsigned int written = 0;
    kinds[0] = 0;
    if (a2 && count && count <= 64) {
        const unsigned char *params = a2;
        for (unsigned long i = 0; i < count && i < 20 && written < sizeof kinds - 12; ++i) {
            unsigned int kind = *(const unsigned int *)(params + i * 52);
            char piece[16];
            int n = snprintf(piece, sizeof piece, "%s%u", i ? "," : "", kind);
            if (n <= 0) break;
            for (int k = 0; piece[k] && written < sizeof kinds - 1; ++k) kinds[written++] = piece[k];
            kinds[written] = 0;
        }
    }
    char text[320];
    snprintf(text, sizeof text, "call=%u id=%#x count=%lu orientation=%u this=%p kinds=[%s]",
             ++create_screen_calls, id, count, orientation, a0, kinds);
    record("CREATE_SCREEN_ARGS ", text);
    static unsigned int system_error_traces;
    if((id==0x322 || (id==0x30c && system_error_traces++<3)) && getenv("MENU_DMM_UNIT_CONFIG"))
        capture_dialog_frames((unsigned long)__builtin_frame_address(0),create_screen_calls);
    if (create_screen_calls == 1) {
        dump_factory_table();
        /* The view owns an arena base/capacity/used tuple here, not display handles. */
        const unsigned char *self = a0;
        char info[200];
        unsigned long arena = self ? *(const unsigned long *)(self + 0x3e98) : 0;
        unsigned int capacity = self ? *(const unsigned int *)(self + 0x3ea0) : 0;
        unsigned int used = self ? *(const unsigned int *)(self + 0x3ea4) : 0;
        unsigned long screens = self ? *(const unsigned long *)(self + 0x3e90) : 0;
        unsigned long first = self ? *(const unsigned long *)(self + 0x3ec8) : 0;
        unsigned long vtable = self ? *(const unsigned long *)self : 0;
        snprintf(info, sizeof info,
                 "this=%p vtable=appFw+%#lx count_slot=%lu arena=%#lx capacity=%u used=%u screen0=%#lx",
                 a0, vtable ? vtable - appfw_base : 0, screens, arena, capacity, used, first);
        record("CREATE_SCREEN_STATE ", info);
    }
    record("CREATE_SCREEN_CALLED ", "view::create_screen entered (vtable sentinel at VA 0x58dbf38)");
    if (!real_create_screen) {
        __atomic_sub_fetch(&create_screen_active, 1, __ATOMIC_RELEASE);
        return 0;
    }
    if (!ui_thread_id) {
        ui_thread_id=(unsigned int)syscall(178);
        char thread[100];snprintf(thread,sizeof thread,"pid=%d tid=%u",getpid(),ui_thread_id);
        record("CREATE_SCREEN_UI_THREAD ",thread);
    }
    void *result = real_create_screen(a0, a1, a2, a3, a4, a5, a6, a7);
    __atomic_store_n(&last_input_screen,id,__ATOMIC_RELEASE);
    if (getenv("MENU_FORCE_IN_FACTORY") && getenv("MENU_MENU_INIT")) try_menu_init();
    snprintf(text, sizeof text, "call=%u returned=%p", create_screen_calls, result);
    record("CREATE_SCREEN_RETURN ", text);
    /* The model is alive here: 28 screens just got created. Read the real display state and,
       when asked, push the task_main event sequence that bb-events decoded. */
    if (a0) {
        char state[224];
        snprintf(state, sizeof state, "count_slot=%lu screen0=%#lx screen1=%#lx arena=%#lx",
                 *(const unsigned long *)((const unsigned char *)a0 + 0x3e90),
                 *(const unsigned long *)((const unsigned char *)a0 + 0x3ec8),
                 *(const unsigned long *)((const unsigned char *)a0 + 0x3ed0),
                 *(const unsigned long *)((const unsigned char *)a0 + 0x3e98));
        record("CREATE_SCREEN_POST ", state);
    }
    if (create_screen_calls == 1 && getenv("MENU_SCREEN_REGISTRY")) dump_screen_registry();
    if (getenv("MENU_TASK_MAIN_EVENTS") && create_screen_calls == 1) task_main_probe();
    if (getenv("MENU_UX_NOTIFY_DRAW")) {
        ux_render_poke("after_create_screen");
        ux_render_poke("after_create_screen_repeat");
    }
    __atomic_add_fetch(&create_screen_returned, 1, __ATOMIC_RELEASE);
    __atomic_sub_fetch(&create_screen_active, 1, __ATOMIC_RELEASE);
    return result;
}
/* The view vtable (runtime VA base+0x58dbf38) has create_screen in slot 0 and nine more methods in
   slots 1..10 (0x17b37ac, 0x17ce838, 0x17b3810, 0x17b388c, 0x17b3894, 0x17ceb44, 0x17cf43c,
   0x17cef74, 0x17b3920, 0x17b38c8 per force-screen/REPORT.md section 1). Creation and display are
   separate operations, so watch every slot to find which one submits a screen to the display. */
static void *(*real_view_slot[11])(void *, void *, void *, void *, void *, void *, void *, void *);
static unsigned int view_slot_calls[11];
static void record_view_content(void *object) {
    const unsigned char *view = object;
    if (!view) return;
    unsigned long count = *(const unsigned long *)(view + 0x3e90);
    unsigned long arena = *(const unsigned long *)(view + 0x3e98);
    unsigned int capacity = *(const unsigned int *)(view + 0x3ea0);
    unsigned int used = *(const unsigned int *)(view + 0x3ea4);
    char text[224];
    snprintf(text, sizeof text, "count=%lu arena=%#lx capacity=%u used=%u update_state=%u draw_state=%u",
             count, arena, capacity, used, *(unsigned int *)(appfw_base + 0x5c1efe4),
             *(unsigned int *)(appfw_base + 0x5c1efe0));
    record("VIEW_CONTENT_STATE ", text);
    if (count > 1000 || !arena || capacity > 0x2000000 || used > capacity || arena + used < arena) return;
    unsigned long end = arena + used;
    unsigned int widgets = 0;
    for (unsigned long i = 0; i < count; ++i) {
        unsigned int kind = *(const unsigned int *)(view + 0x10 + 16 * i);
        unsigned long param = *(const unsigned long *)(view + 0x18 + 16 * i);
        unsigned long widget = *(const unsigned long *)(view + 0x3ec8 + 8 * i);
        if (widget) ++widgets;
        if (i >= 32) continue;
        int valid = param >= arena && param <= end && end - param >= 0x44;
        int show = -1, content = -1;
        if (valid && (kind == 0 || kind == 38 || kind == 101)) {
            show = *(const unsigned char *)(param + 0x2c);
            if (kind == 0) content = *(const int *)(param + 0x3c);
            if (kind == 38) content = *(const int *)(param + 0x30);
            if (kind == 101) content = *(const unsigned char *)(param + 0x40);
        }
        snprintf(text, sizeof text, "item=%lu kind=%u widget=%#lx param=%#lx param_in_arena=%d show=%d content=%d",
                 i, kind, widget, param, valid, show, content);
        record("VIEW_CONTENT_ITEM ", text);
    }
    snprintf(text, sizeof text, "widgets=%u count=%lu sampled=%lu", widgets, count, count < 32 ? count : 32);
    record("VIEW_CONTENT_TOTAL ", text);
}
static void *observe_view_slot_entry(unsigned int slot, void *a0, void *a1, void *a2, void *a3,
                                     void *a4, void *a5, void *a6, void *a7) {
    unsigned int call = ++view_slot_calls[slot];
    if (getenv("MENU_FORCE_IN_FACTORY") && getenv("MENU_MENU_INIT")) try_menu_init();
    if (call <= 3) {
        char text[160];
        snprintf(text, sizeof text, "slot=%u call=%u this=%p a1=%#lx a2=%p a3=%#lx",
                 slot, call, a0, (unsigned long)a1, a2, (unsigned long)a3);
        record("VIEW_SLOT_CALLED ", text);
    }
    if (!real_view_slot[slot]) return 0;
    void *result = real_view_slot[slot](a0, a1, a2, a3, a4, a5, a6, a7);
    if (slot == 2 && call <= 2 && getenv("MENU_FRAME_OBSERVE")) record_view_content(a0);
    return result;
}
#define VIEW_SLOT_TRAMPOLINE(N) \
    static void *observe_view_slot_##N(void *a0, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7) { \
        return observe_view_slot_entry(N, a0, a1, a2, a3, a4, a5, a6, a7); \
    }
VIEW_SLOT_TRAMPOLINE(1) VIEW_SLOT_TRAMPOLINE(2) VIEW_SLOT_TRAMPOLINE(3) VIEW_SLOT_TRAMPOLINE(4)
VIEW_SLOT_TRAMPOLINE(5) VIEW_SLOT_TRAMPOLINE(6) VIEW_SLOT_TRAMPOLINE(7) VIEW_SLOT_TRAMPOLINE(8)
VIEW_SLOT_TRAMPOLINE(9) VIEW_SLOT_TRAMPOLINE(10)
static void *(*const view_slot_wrapper[11])(void *, void *, void *, void *, void *, void *, void *, void *) = {
    0,
    observe_view_slot_1, observe_view_slot_2, observe_view_slot_3, observe_view_slot_4,
    observe_view_slot_5, observe_view_slot_6, observe_view_slot_7, observe_view_slot_8,
    observe_view_slot_9, observe_view_slot_10,
};
static void install_create_screen_sentinel(unsigned long base) {
    char ack_bind[180];snprintf(ack_bind,sizeof ack_bind,"pid=%d pending=%p retry=%p create=%p detach=%p",getpid(),
        file_media_flush_pending_fn,file_media_flush_cancel_retry_fn,sd_ack_create,sd_ack_detach);
    record("SD_ACK_BIND ",ack_bind);
    unsigned long slot_address = base + 0x58dbf38UL;   /* runtime VA, not the file offset */
    unsigned long page = slot_address & ~0xfffUL;
    if (mprotect((void *)page, 4096, 3) != 0) {
        record("CREATE_SCREEN_SENTINEL_FAILED ", "vtable page is not writable");
        return;
    }
    real_create_screen = (void *(*)(void *, void *, void *, void *, void *, void *, void *, void *))
        *(unsigned long *)slot_address;
    *(unsigned long *)slot_address = (unsigned long)observe_create_screen;
    /* Sanity check: the original slot must point inside appFw's own image (create_screen = base+0x17cdb00). */
    char text[200];
    unsigned long delta = (unsigned long)real_create_screen - base;
    snprintf(text, sizeof text, "slot=%#lx original=%#lx (appFw+%#lx; expect 0x17cdb00) wrapper=%#lx",
             slot_address, (unsigned long)real_create_screen, delta, (unsigned long)observe_create_screen);
    record("CREATE_SCREEN_SENTINEL ", text);
    /* Arm slots 1..10 with forwarding wrappers so we can see which of the other view methods
       (activate / enter display layer / open) the application actually reaches. */
    for (unsigned int slot = 1; slot <= 10; ++slot) {
        unsigned long *slot_pointer = (unsigned long *)(base + 0x58dbf38UL + slot * 8UL);
        if (!*slot_pointer) continue;
        real_view_slot[slot] = (void *(*)(void *, void *, void *, void *, void *, void *, void *, void *))*slot_pointer;
        *slot_pointer = (unsigned long)view_slot_wrapper[slot];
    }
    char slots[160];
    snprintf(slots, sizeof slots, "armed slots 1..10: originals appFw+%#lx,%#lx,%#lx,%#lx,%#lx",
             (unsigned long)real_view_slot[1] - base, (unsigned long)real_view_slot[2] - base,
             (unsigned long)real_view_slot[3] - base, (unsigned long)real_view_slot[4] - base,
             (unsigned long)real_view_slot[5] - base);
    record("VIEW_SLOTS_ARMED ", slots);
    {
        /* Which process loaded us, and which of our switches this process can actually see? */
        extern int getpid(void);
        int pid = getpid();
        char env_text[384];
        snprintf(env_text, sizeof env_text, "pid=%d base=%#lx MENU_FORCE_SET=%s MENU_FORCE_IN_FACTORY=%s FACTORY_HOOK=%s CTOR_CENSUS=%s OPEN_SET=%s OPEN_SET_LOG_ONLY=%s",
                 pid, appfw_base,
                 getenv("MENU_FORCE_SET") ? getenv("MENU_FORCE_SET") : "(unset)",
                 getenv("MENU_FORCE_IN_FACTORY") ? "1" : "(unset)",
                 getenv("MENU_FACTORY_HOOK") ? "1" : "(unset)",
                 getenv("MENU_CTOR_CENSUS") ? "1" : "(unset)",
                 getenv("MENU_OPEN_SET") ? getenv("MENU_OPEN_SET") : "(unset)",
                 getenv("MENU_OPEN_SET_LOG_ONLY") ? "1" : "(unset)");
        record("OBSERVER_READY ", env_text);
    }
    if (getenv("MENU_SYNC_DIRECT")) install_sync_direct_probe(appfw_base);
    if (getenv("MENU_ASYNC_SEND")) install_async_send_probe(appfw_base);
    if (getenv("MENU_ENTRY_PROBES")) install_boot_entry_probes(appfw_base);
    if (getenv("MENU_POWER_OBSERVE")) install_power_notice_probe(appfw_base);
    if (getenv("MENU_OSD_SUBMIT_TRACE") && real_draw_framebuffer)install_osd_submit_probe();
    if (getenv("MENU_ASSERT_PROBE")) install_assert_probe(appfw_base);
    if (getenv("MENU_OPTION_PROBES")) install_option_probes();
    if (getenv("MENU_ENTRY_PROBES")) install_run_i_return_probe(appfw_base);
    if (getenv("MENU_ENTRY_PROBES")) install_shooting_probe(appfw_base);
    if (getenv("MENU_SYNC_MSG_HOOK")) install_sync_msg_probe(appfw_base);
    if (getenv("MENU_SYNC_CALL_PROBE")) install_sync_call_probe(appfw_base);
    /* Only now are appFw and its dependencies (libMWF, libosal_*) mapped, so the module can
       resolve them. Starting it earlier crashed bootin.elf with SIGTRAP inside dlopen. */
    if (getenv("MENU_BUSPOWER") && !getenv("MENU_OBSERVE_SELFTEST")) start_bus_power_module();
    if (getenv("MENU_INFRA_AVBBC") && !getenv("MENU_OBSERVE_SELFTEST")) start_avbbc_module();
    if (!getenv("MENU_OBSERVE_SELFTEST")) install_pipeline_endpoint();
    if (getenv("MENU_MODE_SENTINELS")) install_mode_sentinels(appfw_base);
    if (getenv("MENU_STDIO_KMSG")) redirect_stdio_to_kmsg();
    if (getenv("MENU_FACTORY_HOOK")) install_factory_capture(base);
    /* MEASURED BUG: MENU_MODE_SLOTS was missing from this gate, so captured_manager stayed 0 and
   dump_manager_slots() returned immediately - the run produced zero MODE_SLOT records even though
   the string was linked in. Any probe that reads the manager must be listed here. */
    if (getenv("MENU_FORCE_SET") || getenv("MENU_BUILD_CONTROLLER2") || getenv("MENU_OPEN_SET") ||
        getenv("MENU_APPLY_MENU") || getenv("MENU_MODE_SLOTS")) install_manager_probe(base);
    if (getenv("MENU_MENU_INIT") || getenv("MENU_BUILD2_THEN_INIT") || getenv("MENU_APPLY_MENU")) install_menu_ctor_probe(base);
    if (getenv("MENU_CTOR_CENSUS") || getenv("MENU_ACTIVATE_CAPTURED")) install_base_ctor_probe(base);
}
static void *observe_application_init(void *argument) {
    record("ENTER ", "Application_System_Init");
    if (getenv("MENU_MEDIA_INIT_WATCH") && !getenv("MENU_OBSERVE_SELFTEST") &&
        appfw_base && !(appfw_base & 4095UL)) {
        static volatile unsigned int media_init_gate_active;
        char text[192];
        /* Read only: fault in the zero-fill page before the host observes it.
           This does not initialize or replace the original field value. */
        unsigned int prior_still = *(volatile unsigned int *)(appfw_base + 0x7e6e7f0UL);
        media_init_gate_active = 1;
        snprintf(text, sizeof text, "MEDIA_INIT_GATE pid=%d base=%#lx wait_us=10000000 gate=%#lx prior_still=%u",
                 getpid(), appfw_base, (unsigned long)&media_init_gate_active, prior_still);
        record("OBSERVER_READY ", text);
        /* Explicit debug pacing only: no app/BKP/queue state is changed.
           Always continue naturally even if no host debugger connects. */
        usleep(10000000);
        media_init_gate_active = 0;
    }
    void *result = real_application_init(argument);
    record(result ? "RETURN_NONZERO " : "RETURN_ZERO ", "Application_System_Init");
    /* Post-init view-object walk: Application global [appfw+0x5f645e8] -> object;
       find the qword in object[0..0x2000) whose pointee starts with the view
       vtable (appfw+0x58cbf38, slot0=create_screen). In-process reads, no OOM.
       Temporarily disabled: binary-size shift correlates with a deterministic
       init-time UIPC ioctl abort (libc+0xc1cbc) under icount. */
#if 0
    if (result && appfw_base && !getenv("MENU_OBSERVE_SELFTEST")) {
        unsigned long *root = (unsigned long *)(appfw_base + 0x5f645e8);
        unsigned long object = *root;
        char text[140];
        snprintf(text, sizeof text, "object=%#lx", object);
        record("VTWALK_ROOT ", text);
        if (object > 0x7f00000000UL && object < 0x800000000000UL) {
            unsigned long vtable = appfw_base + 0x58cbf38;
            int hits = 0;
            for (unsigned long off = 0; off < 0x2000 && hits < 12; off += 8) {
                unsigned long candidate = *(unsigned long *)(object + off);
                if (candidate < 0x7f00000000UL || candidate > 0x800000000000UL) continue;
                unsigned long first = *(unsigned long *)candidate;
                if (first == vtable) {
                    snprintf(text, sizeof text, "obj_off=%#lx ptr=%#lx", off, candidate);
                    record("VTWALK_VIEW ", text);
                    ++hits;
                }
            }
            snprintf(text, sizeof text, "vtable=%#lx hits=%d", vtable, hits);
            record("VTWALK_DONE ", text);
        }
    }
#endif
    /* Resident-page heap scan for the view object: read /proc/self/maps, scan
       only RESIDENT pages (mincore) of small anonymous rw- mappings for qwords
       equal to the view vtable (appfw+0x58dbf38/0x58cbf38). No page-in, no OOM. */
    if (result && appfw_base && !getenv("MENU_OBSERVE_SELFTEST")) {
        static const char maps_path[] = "/proc/self/maps";
        int mfd = open(maps_path, 0);
        if (mfd >= 0) {
            char all[32768];
            long cap = 0, got;
            while (cap < (long)sizeof all - 1 && (got = read(mfd, all + cap, sizeof all - 1 - cap)) > 0) cap += got;
            all[cap < 0 ? 0 : cap] = 0;
            close(mfd);
            unsigned long vt1 = appfw_base + 0x58dbf38, vt2 = appfw_base + 0x58cbf38;
            char line[320];
            const char *p = all;
            int regions = 0;
            unsigned long hits[16];
            int nhit = 0;
            while (*p && nhit < 16) {
                const char *e = p;
                while (*e && *e != '\n') ++e;
                int len = e - p;
                if (len > 0 && len < 300) {
                    const char *q = p;
                    unsigned long lo = 0, hi = 0;
                    while (*q >= '0' && *q <= '9' || (*q >= 'a' && *q <= 'f')) { lo = lo * 16 + (*q >= 'a' ? *q - 'a' + 10 : *q - '0'); ++q; }
                    if (*q == '-') ++q;
                    while (*q >= '0' && *q <= '9' || (*q >= 'a' && *q <= 'f')) { hi = hi * 16 + (*q >= 'a' ? *q - 'a' + 10 : *q - '0'); ++q; }
                    while (*q == ' ') ++q;
                    if (*q == 'r' && q[1] == 'w' && lo >= 0x7f00000000UL && hi - lo <= 0x1000000UL) {
                        ++regions;
                        for (unsigned long page = lo; page + 4096 <= hi && nhit < 16; page += 4096) {
                            unsigned char vec = 0;
                            if (syscall(232, page, 4096, &vec) != 0) continue;  /* mincore */
                            if (!(vec & 1)) continue;
                            for (unsigned long off = 0; off < 4096 && nhit < 16; off += 8) {
                                unsigned long v = *(unsigned long *)(page + off);
                                if (v == vt1 || v == vt2) hits[nhit++] = page + off;
                            }
                        }
                    }
                }
                p = *e ? e + 1 : e;
            }
            char text[160];
            snprintf(text, sizeof text, "regions=%d hits=%d", regions, nhit);
            record("HEAPSCAN_DONE ", text);
            for (int i = 0; i < nhit && i < 8; ++i) {
                snprintf(text, sizeof text, "addr=%#lx", hits[i]);
                record("HEAPSCAN_VIEW ", text);
            }
        }
    }
    return result;
}
static int observe_updater_init(void) {
    record("ENTER ", "udtr_ufp_init");
    int result = real_updater_init();
    char text[64];
    snprintf(text, sizeof text, "udtr_ufp_init=%d", result);
    record("RETURN ", text);
    return result;
}
static int observe_updater_exit(void) {
    record("ENTER ", "udtr_ufp_exit");
    int result = real_updater_exit();
    char text[64];
    snprintf(text, sizeof text, "udtr_ufp_exit=%d", result);
    record("RETURN ", text);
    return result;
}
static int same_name(const char *name, const char *expected) {
    size_t i = 0;
    while (name && name[i] && name[i] == expected[i]) ++i;
    return name && !name[i] && !expected[i];
}
static int capid_send(unsigned int destination, void *request) {
    if (!capid.table || !real_allocate_msg || !real_free_msg || !real_get_source || !real_set_source || !real_msg_size)
        return -1021;
    if (!request) return -1024;
    unsigned int input_size = real_msg_size(request);
    if (input_size < (destination == 0x9004015e ? 24U : 16U)) return -1024;
    unsigned int *words = request;
    unsigned int operation = destination == 0x9004015e ? words[1] : words[2];
    unsigned int source = real_get_source(request);
    unsigned int size = destination == 0x9004015e ? (operation == 0x1000 ? 16 : operation == 0x1003 ? 0 : 8) : 24;
    if (destination == 0x9004015e && (words[0] || words[2] || words[3] || words[4] || words[5])) return -1024;
    void *reply = 0;
    int result = size ? real_allocate_msg(source, &reply, size, 1) : 0;
    if (result) return result;
    pthread_mutex_lock(cap_lock);
    long owner = syscall(178);
    struct cap_service previous = capid;
    struct cap_table previous_table = *capid.table;
    if (destination == 0x9004015e) {
        unsigned char unused[16];
        result = cap_control(&capid, operation, owner, reply ? reply : unused, &size);
    } else {
        result = cap_sync(&capid, request, input_size, reply);
    }
    if (!result && size) {
        real_set_source(reply, destination);
        result = real_send_msg(source, reply);
    }
    if (result) {
        *capid.table = previous_table;
        capid = previous; /* failed delivery leaves the request and service state unchanged */
    }
    char text[160];
    snprintf(text, sizeof text, "tid=%ld dest=%#x op=%#x source=%#x result=%d header=%u,%u,%u,%u,%u initialized=%d",
             owner, destination, operation, source, result, capid.table->header[0], capid.table->header[1],
             capid.table->header[2], capid.table->header[3], capid.table->header[4], capid.initialized);
    record("CAPID_SERVICE ", text);
    pthread_mutex_unlock(cap_lock);
    if (result) {
        if (reply) real_free_msg(source, reply);
        return result;
    }
    real_free_msg(destination, request); /* a successful virtual send consumes the request */
    return 0;
}
static int sa_address_send(void *request) {
    if (!real_allocate_msg || !real_free_msg || !real_set_source || !real_msg_size) return -1021;
    if (!request || real_msg_size(request) < 80) return -1024;
    const unsigned int *words = request;
    if (words[3] || !words[2]) return -1024; /* reply qid is zero-extended u32 at +8 */
    unsigned int source = words[2];
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 80, 1);
    if (result) return result;
    result = sa_address_reply(request, reply);
    if (!result) {
        const unsigned char *bytes = reply;
        char text[160];
        snprintf(text, sizeof text, "source=%#x status=%u detail=%u first=%#llx",
                 source, bytes[6], bytes[7], ((const unsigned long long *)reply)[2]);
        record("SA_ADDRESS_REPLY ", text);
        real_set_source(reply, 0x00930101);
        result = real_send_msg(source, reply);
    }
    if (result) { real_free_msg(source, reply); return result; }
    real_free_msg(0x00930101, request);
    return 0;
}
static int display_info_send(void *request) {
    if (!real_allocate_msg || !real_msg_size || !real_get_source || !real_set_source || !real_free_msg) return -1021;
    unsigned int source = real_get_source(request);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 18, 1);
    if (result) return result;
    result = display_info_reply(&virtual_display, request, real_msg_size(request), reply);
    if (!result) { real_set_source(reply, 0x92840747); result = real_send_msg(source, reply); }
    if (result) { real_free_msg(source, reply); return result; }
    char geometry[140];
    snprintf(geometry, sizeof geometry, "virtual panel=%ux%u aspect=%u evf=%ux%u aspect=%u",
             virtual_display.panel_width, virtual_display.panel_height, virtual_display.panel_aspect,
             virtual_display.evf_width, virtual_display.evf_height, virtual_display.evf_aspect);
    record("DISPLAY_INFO_SERVICE ", geometry);
    real_free_msg(0x92840747, request);
    return 0;
}
static int yuv_layout_send(void *request) {
    if (!real_allocate_msg || !real_msg_size || !real_get_source || !real_set_source || !real_free_msg) return -1021;
    unsigned int source = real_get_source(request);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 12, 1);
    if (result) return result;
    result = yuv_layout_reply(request, real_msg_size(request), reply);
    if (!result) { real_set_source(reply, 0x92840747); result = real_send_msg(source, reply); }
    if (result) { real_free_msg(source, reply); return result; }
    record("YUV_LAYOUT_SERVICE ", "observed 640x480 layout accepted; original 0x114c status 0");
    real_free_msg(0x92840747, request);
    return 0;
}
/* Reactive CP stand-in: whenever the application blocks on one of the sequence queues it
   allocated for boot sequence 42 (the 0x81cf61xx family, excluding the BB dispatcher queue
   itself), deliver the one event shape the dispatcher is known to accept, exactly once per
   queue. Those queues receive nothing at all in QEMU, which is where the model stalls. */
static void sequence_event_deliver(unsigned int queue, unsigned int ordinal) {
    if (!real_allocate_msg || !real_send_msg || !real_set_source || !real_free_msg) return;
    void *msg = 0;
    if (real_allocate_msg(queue, &msg, 48, 1)) { record("SEQ_EVENT ", "alloc failed"); return; }
    unsigned char *b = msg;
    for (int i = 0; i < 48; ++i) b[i] = 0;
    b[0] = 0x03; b[1] = 0x20;   /* frame 0x2003 */
    b[2] = 0x01; b[3] = 0x82;   /* code 0x8201 */
    b[4] = 48;
    const char *sel = getenv("MENU_SEQ_EVENT_SEL");
    b[10] = (sel && sel[0] >= '0' && sel[0] <= '9') ? (unsigned char)(sel[0] - '0') : 3;
    real_set_source(msg, 0x92840747);
    int result = real_send_msg(queue, msg);
    char text[144];
    if (result) {
        real_free_msg(queue, msg);
        snprintf(text, sizeof text, "send failed queue=%#x result=%d ordinal=%u", queue, result, ordinal);
        record("SEQ_EVENT_FAILED ", text);
        return;
    }
    snprintf(text, sizeof text, "delivered 0x2003/0x8201 to sequence queue %#x (ordinal %u)", queue, ordinal);
    record("SEQ_EVENT_DELIVERED ", text);
}
static void bb_output_ready_event(void) {
    /* Also directly trigger a UX render pass: WidgetSystem::notifyDraw() on the
       singleton. This bypasses the model key processing that never fires in
       QEMU (no CP events), but exercises the real UX→GPE render path. */
    if (real_dlsym) {
        static void *(*get_wgtsys)(void);
        static int (*notify_draw)(void *);
        if (!get_wgtsys) get_wgtsys = real_dlsym((void *)-1, "_ZN2ux6wgtsys12WidgetSystem15sys_getInstanceEv");
        if (!notify_draw) notify_draw = real_dlsym((void *)-1, "_ZN2ux6wgtsys12WidgetSystem10notifyDrawEv");
        if (get_wgtsys && notify_draw) {
            void *wgtsys = get_wgtsys();
            if (wgtsys) {
                int draw_result = notify_draw(wgtsys);
                char text[120];
                snprintf(text, sizeof text, "wgtsys=%p notifyDraw=%d (direct UX render trigger)", wgtsys, draw_result);
                record("UX_RENDER_TRIGGER ", text);
            } else {
                record("UX_RENDER_TRIGGER ", "WidgetSystem::sys_getInstance returned NULL");
            }
        } else {
            record("UX_RENDER_TRIGGER ", "sys_getInstance or notifyDraw not found");
        }
    }

    /* The CP event dispatcher (appFw 0x34e65f8) reads its queue from [appFw+0x910fa1c]
       via helper 0x3510fa4 and accepts exactly: frame u16 0x2003 @+0, code u16 0x8201 @+2,
       u16 3 @+0xa; it then stores u32 @+0x1c into global 0x910f9fc and fulfils a std::promise
       (0x34e6508) that a waiting AppFw sequence holds. On real hardware CP sends this after
       the output pipeline starts. Delivered once, in that accepted format; the stored value
       0 is the neutral/success reading. */
    if (!appfw_base || !real_allocate_msg || !real_send_msg || !real_set_source || !real_free_msg) return;
    unsigned int queue = *(volatile unsigned int *)(appfw_base + 0x910fa1c);
    if (!queue) { record("BB_OUTPUT_READY ", "dispatcher queue id is zero; skipped"); return; }
    void *msg = 0;
    if (real_allocate_msg(queue, &msg, 48, 1)) { record("BB_OUTPUT_READY ", "alloc failed"); return; }
    unsigned char *b = msg;
    for (int i = 0; i < 48; ++i) b[i] = 0;
    b[0] = 0x03; b[1] = 0x20;  /* frame 0x2003 */
    b[2] = 0x01; b[3] = 0x82;  /* code 0x8201 */
    b[4] = 48;                 /* size u16 */
    b[10] = 3;                 /* [+0xa] == 3 selector */
    real_set_source(msg, 0x92840747);
    int result = real_send_msg(queue, msg);
    if (result) { real_free_msg(queue, msg); record("BB_OUTPUT_READY ", "send failed"); return; }
    char text[120];
    snprintf(text, sizeof text, "delivered 0x2003/0x8201 [+a]=3 value=0 to dispatcher queue %#x", queue);
    record("BB_OUTPUT_READY ", text);
}
static int plane_config_send(void *request) {
    if (!real_allocate_msg || !real_msg_size || !real_get_source || !real_set_source || !real_free_msg) return -1021;
    unsigned int source = real_get_source(request);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 12, 1);
    if (result) return result;
    result = plane_config_reply(request, real_msg_size(request), reply);
    if (!result) { real_set_source(reply, 0x92840747); result = real_send_msg(source, reply); }
    if (result) { real_free_msg(source, reply); return result; }
    record("PLANE_CONFIG_SERVICE ", "observed 680-byte 0x147 plane table accepted; original 0x1147 status 0");
    /* CP sends a second, asynchronous SetOutputComp after the output pipeline settles
       ("[ADF][OUT] SetOutputComp:BootExit err %x replyId %x", cpapp-b string file+0x6f1ec).
       AppFw's async waiter (0x34e6afc region) receives ANY message on the reply queue,
       frees it unread (0x34e6b14), releases the dynamic id (0x359a218 = osal_dynamic_id
       release, type bit 0x40) and tears the queue down; content is not consulted.
       Deliver the same original 12-byte completion format as that async notification. */
    void *async_reply = 0;
    int async_result = real_allocate_msg(source, &async_reply, 12, 1);
    if (!async_result) {
        async_result = plane_config_reply(request, real_msg_size(request), async_reply);
        if (!async_result) { real_set_source(async_reply, 0x92840747); async_result = real_send_msg(source, async_reply); }
    }
    if (!async_result) record("PLANE_CONFIG_ASYNC_COMP ", "original-format async SetOutputComp delivered to reply queue (waiter is content-agnostic)");
    else { if (async_reply) real_free_msg(source, async_reply); record("PLANE_CONFIG_ASYNC_COMP ", "async SetOutputComp delivery failed"); }
    if (!async_result) {
        if (getenv("MENU_BB_READY_LATE")) {
            bb_ready_pending = 1;
            record("BB_OUTPUT_READY ", "deferred: MENU_BB_READY_LATE=1 holds the 0x2003/0x8201 fulfilment until after the cold-boot chain and an injected key");
        } else {
            if (bb_ready_inject_enabled) bb_output_ready_event();
        }
        /* Plane completion must not rewrite AppFw business state. In particular,
           +0x7e6e7f0 is the still recording-media selection, not an input gate. */
    }
    real_free_msg(0x92840747, request);
    return 0;
}
static int pin_disconnect_send(void *request) {
    if (!real_allocate_msg || !real_msg_size || !real_get_source || !real_set_source || !real_free_msg) return -1021;
    unsigned int source = real_get_source(request);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 16, 1);
    if (result) return result;
    result = pin_disconnect_reply(request, real_msg_size(request), reply);
    if (!result) { real_set_source(reply, 0x909c015b); result = real_send_msg(source, reply); }
    if (result) { real_free_msg(source, reply); return result; }
    char text[100];
    snprintf(text, sizeof text, "mode=%u; original 0x8101 completion status 0", ((const unsigned char *)request)[8]);
    record("PIN_DISCONNECT_SERVICE ", text);
    real_free_msg(0x909c015b, request);
    return 0;
}
/* Experimental registry service for the boot-sequence subscriptions.
   The model sends 13 subscriptions (0xf02..0xf0e, group 0x2a) to 0x811006e9 through appFw+0x36e8118's
   constructor and then waits. Nothing on this side ever answers them, so this optional service echoes a
   completion back to the sender's queue. Disabled unless QEMU_SUBSCRIPTION_SERVICE=1. */
static int subscription_service(unsigned int destination, void *request) {
    if (!request || !real_allocate_msg || !real_get_source || !real_set_source || !real_send_msg || !real_msg_size)
        return -1021;
    unsigned int source = real_get_source(request);
    unsigned int size = real_msg_size(request);
    if (!size || size > 64) size = 20;
    {
        char seen[96];
        snprintf(seen, sizeof seen, "code=%#x bytes=%u source=%#x",
                 size >= 4 ? (((const unsigned char *)request)[2] | (((const unsigned char *)request)[3] << 8)) : 0,
                 size, source);
        record("SUBSCRIPTION_SEEN ", seen);
    }
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, size, 1);
    if (result) {
        /* The subscription messages carry a poison source (0xa5a5a5a5), so a reply cannot go back
           to the sender. The real registry lives on the CP/BB side; the WBI snapshot pairs
           0x811006e9 with 0x81106114, so that is the candidate event queue. */
        if (getenv("QEMU_SUBSCRIPTION_EVENT")) {
            void *event_message = 0;
            int allocated = real_allocate_msg(0x81106114, &event_message, size, 1);
            if (!allocated) {
                const unsigned char *in_bytes = request;
                unsigned char *out_bytes = event_message;
                for (unsigned int i = 0; i < size; ++i) out_bytes[i] = in_bytes[i];
                real_set_source(event_message, 0x811006e9);
                int sent = real_send_msg(0x81106114, event_message);
                char event_text[128];
                snprintf(event_text, sizeof event_text, "event to 0x81106114 code=%#x result=%d",
                         size >= 4 ? (in_bytes[2] | (in_bytes[3] << 8)) : 0, sent);
                record(sent ? "SUBSCRIPTION_EVENT_FAILED " : "SUBSCRIPTION_EVENT ", event_text);
                if (sent) real_free_msg(0x81106114, event_message);
            } else {
                char event_text[96];
                snprintf(event_text, sizeof event_text, "event alloc failed=%d for 0x81106114", allocated);
                record("SUBSCRIPTION_EVENT_FAILED ", event_text);
            }
        }
        char text[96];
        snprintf(text, sizeof text, "alloc_failed=%d source=%#x; message left for the original path", result, source);
        record("SUBSCRIPTION_UNHANDLED ", text);
        return -1;   /* the hook falls through to real_send_msg */
    }
    const unsigned char *in = request;
    unsigned char *out = reply;
    for (unsigned int i = 0; i < size; ++i) out[i] = in[i];
    real_set_source(reply, destination);
    result = real_send_msg(source, reply);
    char text[128];
    snprintf(text, sizeof text, "code=%#x bytes=%u source=%#x reply_result=%d",
             size >= 4 ? (in[2] | (in[3] << 8)) : 0, size, source, result);
    record(result ? "SUBSCRIPTION_REPLY_FAILED " : "SUBSCRIPTION_REPLY ", text);
    if (result) real_free_msg(source, reply);
    real_free_msg(destination, request);
    return result;
}
static int hdmi_parameter_send(unsigned int destination, void *request) {
    if (!request || !real_allocate_msg || !real_get_source || !real_set_source || !real_free_msg || !real_msg_size)
        return -1021;
    unsigned int source = real_get_source(request);
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 12, 1);
    if (result) return result;
    pthread_mutex_lock(cap_lock);
    struct hdmi_format_state previous = hdmi_format;
    struct hdmi_photo_state previous_photo = hdmi_photo;
    int photo = destination == 0x909a015a;
    result = photo ? hdmi_photo_reply(&hdmi_photo, request, real_msg_size(request), reply) :
                     hdmi_format_reply(&hdmi_format, request, real_msg_size(request), reply);
    if (!result) {
        real_set_source(reply, destination);
        result = real_send_msg(source, reply);
    }
    if (result) { hdmi_format = previous; hdmi_photo = previous_photo; }
    char text[128];
    if (photo)
        snprintf(text, sizeof text, "source=%#x premium=%u preset6=%u applied=%u result=%d completion=0x8102",
                 source, hdmi_photo.premium, hdmi_photo.desired_preset6, hdmi_photo.applied, result);
    else
        snprintf(text, sizeof text, "source=%#x format=%u applied=%u result=%d completion=0x132f",
                 source, hdmi_format.format, hdmi_format.applied, result);
    record(photo ? "HDMI_PHOTO_SERVICE " : "HDMI_FORMAT_SERVICE ", text);
    pthread_mutex_unlock(cap_lock);
    if (result) { real_free_msg(source, reply); return result; }
#ifndef MENU_OBSERVE_TRANSPORT_SELFTEST
    int fd = open(photo ? "/tmp/hdmi-photo-state.bin" : "/tmp/hdmi-format-state.bin", 0x241, 0644);
    if (fd >= 0) {
        write(fd, photo ? (void *)&hdmi_photo : (void *)&hdmi_format,
              photo ? sizeof hdmi_photo : sizeof hdmi_format);
        close(fd);
    }
#endif
    real_free_msg(destination, request);
    return 0;
}
int osal_dynamic_id(unsigned int type, unsigned int owner, unsigned long value) {
    if (!real_dynamic_id) __builtin_trap();
    int result = real_dynamic_id(type, owner, value);
    unsigned int id = (unsigned int)value;
    if (!(type & 0x40)) id = result == 0 && value ? *(unsigned int *)value : 0;
    char text[128];
    snprintf(text, sizeof text, "type=%#x owner=%#x result=%d id=%#x caller=%p",
             type, owner, result, id,
             __builtin_return_address(0));
    if (result != 0 || owner == 0x1cf) record("DYNAMIC_ID ", text);
    return result;
}
/* Registration records are filtered to keep the log readable, but the filter used to
   drop the whole input queue family (0x7a804c / 0x7ae0xx / 0x807a0020). Those are the
   I-InputMain / I-InputEvent receive queues, so their registrations - and therefore the
   key-event handlers - were invisible in every earlier run. */
static int trace_registration(unsigned int id) {
    unsigned int family = (id >> 16) & 0xff;
    if (id == 0x5503e0 || family == 0x55 || family == 0x7a) return 1;
    return ((id >> 16) & 0xfff) == 0x1cf;
}
int osal_reg_sync_msg_queue_cb(unsigned int id, void **handle, void *callback, unsigned long argument) {
    if (!real_reg_sync) __builtin_trap();
    int result = real_reg_sync(id, handle, callback, argument);
    char text[160];
    snprintf(text, sizeof text, "id=%#x result=%d callback=%p arg=%#lx queue=%p caller=%p",
             id, result, callback, argument, handle ? *handle : 0, __builtin_return_address(0));
    if (result != 0 || trace_registration(id)) record("REG_SYNC ", text);
    if (getenv("MENU_OSD_OBSERVE") && (((id >> 16) & 0xfff) == 0x280 || ((id >> 16) & 0xfff) == 0x288))
        record("OSD_REGISTER_SYNC ", text);
    return result;
}
int osal_reg_msg_queue_cb(unsigned int id, void **handle, void *callback, unsigned long argument) {
    if (!real_reg_async) __builtin_trap();
    int result = real_reg_async(id, handle, callback, argument);
    Dl_info info;
    const char *module = "?";
    unsigned long offset = 0;
    void *caller = __builtin_return_address(0);
    if (real_dladdr && real_dladdr(caller, &info) && info.dli_fbase) {
        module = info.dli_fname ? info.dli_fname : "?";
        offset = (unsigned long)caller - (unsigned long)info.dli_fbase;
    }
    char text[240];
    snprintf(text, sizeof text, "id=%#x result=%d callback=%p arg=%#lx queue=%p caller=%s+%#lx",
             id, result, callback, argument, handle ? *handle : 0, module, offset);
    if (!getenv("MENU_REG_SILENT")) record("REG_ASYNC ", text);
    /* run_i blocks in DataflowInfraReceiver::ReceiveASync with timeout=-1 waiting for a reply
       from 0x92840747, and the kernel drops that send ("Skip snd to 0x747"). Recording every
       registration whose low id is 0x747, or whose module prefix is 0x9284, answers statically
       unanswerable question: does anything register that endpoint at all? */
    if ((id & 0xffff) == 0x747 || ((id >> 16) & 0xffff) == 0x9284)
        record("REG_747 ", text);
    if (getenv("MENU_OSD_OBSERVE") && (((id >> 16) & 0xfff) == 0x280 || ((id >> 16) & 0xfff) == 0x288))
        record("OSD_REGISTER_ASYNC ", text);
    return result;
}
/* Inline success reply for the kernel-served version queue: get_lensversion
   (appFw+0x359ab08) sends {cmd=7} via infra_sync_call; upm.ko answers status=1
   (no lens power) which maps to model error 0x151. A successful sync send leaves
   the reply in the caller's message buffer, so writing it here and returning 0
   reproduces the original contract. Reply: halfword +4 status 0, halfwords +6/+8
   version, word +0x18 flag (all zero = generic lens, version 0). */
static int version_transport_reply(unsigned int id, void *message) {
    if (id != 0x004b024e || !message || !real_msg_size || real_msg_size(message) < 36 ||
        *(const unsigned int *)message != 7) return -1024;
    char text[128];
    snprintf(text, sizeof text, "tid=%ld bytes=%u source=%#x caller=%p",
             syscall(178), real_msg_size(message),
             real_get_source ? real_get_source(message) : 0, __builtin_return_address(0));
    record("LENS_VERSION_REQUEST ", text);
    for (unsigned int i = 4; i < 36; ++i) ((unsigned char *)message)[i] = 0;
    record("LENS_VERSION_SERVICE ", "inline sync reply: status 0, version 0, flag 0");
    return 0;
}
/* Bisect: the osal_snd_sync_direct interposition correlates with a NULL
   MonQueue::GetQueueRemain crash (libMWF+0x409d0) during late boot — both crashing
   builds exported it, the good build did not. Keep the function compiled but do
   not interpose (no dlsym redirect, no PLT export) until the mechanism is understood. */
#if 0
int osal_snd_sync_direct(unsigned int id, void *message) {
    if (!real_send_sync_direct) __builtin_trap();
    if (id == 0x004b024e) {
        char probe[128];
        unsigned int probe_size = real_msg_size && message ? real_msg_size(message) : 0;
        snprintf(probe, sizeof probe, "tid=%ld bytes=%u word0=%#x caller=%p",
                 syscall(178), probe_size, message ? *(const unsigned int *)message : 0,
                 __builtin_return_address(0));
        record("SYNC_DIRECT_HIT ", probe);
        int serviced = version_transport_reply(id, message);
        if (!serviced) return 0;
    }
    int result = real_send_sync_direct(id, message);
    char text[140];
    snprintf(text, sizeof text, "tid=%ld dest=%#x result=%d caller=%p",
             syscall(178), id, result, __builtin_return_address(0));
    record("SND_SYNC_DIRECT ", text);
    return result;
}
#endif
static void trace_media_mount_sync(const char *phase,unsigned int id,void *message,int result) {
    if(id!=0x00b08170U || !getenv("MENU_DMM_UNIT_CONFIG") || !message || !real_msg_size)return;
    int saved_errno=*__errno_location();unsigned int n=real_msg_size(message);
    if(n>=16 && n<=64) {
        const unsigned char *p=message;char raw[129],text[360];
        for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",p[i]);
        snprintf(text,sizeof text,"tid=%ld destination=%#x message=%p bytes=%u api=%#x type=%#x media=%#x initial_error=%#x transport=%d raw=%s",
                 syscall(178),id,message,n,((const unsigned short *)p)[0],((const unsigned short *)p)[1],((const unsigned int *)p)[2],
                 ((const unsigned int *)p)[3],result,raw);
        record(phase,text);
    }
    *__errno_location()=saved_errno;
}
static int trace_media_mount_completion(const char *phase,unsigned int id,void *message) {
    if(!getenv("MENU_DMM_UNIT_CONFIG") || !message || !real_msg_size)return 0;
    int matched=0;
    int saved_errno=*__errno_location();unsigned int n=real_msg_size(message);
    if(n>=16 && n<=64) {
        const unsigned short *h=message;const unsigned int *w=message;
        if((h[0]==0x1000 || h[0]==0x1002) && (h[1]==1 || h[1]==2 || h[1]==4) && w[2]==0x1000) {
            matched=1;
            char raw[129],text[360];const unsigned char *p=message;
            for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",p[i]);
            snprintf(text,sizeof text,"tid=%ld id=%#x message=%p bytes=%u source=%#x api=%#x type=%#x media=%#x service_error=%#x raw=%s",
                     syscall(178),id,message,n,real_get_source?real_get_source(message):0,h[0],h[1],w[2],w[3],raw);
            record(phase,text);
        }
    }
    *__errno_location()=saved_errno;
    return matched;
}
int osal_stat_msgq(unsigned int id,void *stats) {
    if(!real_stat_msgq)__builtin_trap();
    int result=real_stat_msgq(id,stats),saved_errno=*__errno_location();
    if(id==0x80d9016eU && getenv("MENU_DMM_UNIT_CONFIG")) {
        const unsigned int *w=stats;char text[220];
        snprintf(text,sizeof text,"tid=%ld id=%#x output=%p result=%d word0=%#x word1=%#x caller=%p",
                 syscall(178),id,stats,result,(!result && w)?w[0]:0,(!result && w)?w[1]:0,__builtin_return_address(0));
        record("FULL_MEDIA_MOUNT_RM_STAT ",text);
    }
    *__errno_location()=saved_errno;
    return result;
}
unsigned int mcmn_drv_open(const char *name,unsigned int flags,void **handle) {
    unsigned int (*call)(const char *,unsigned int,void **)=__atomic_load_n(&real_media_open,__ATOMIC_ACQUIRE);
    if(!call){record("FULL_MEDIA_MOUNT_FORWARD_MISSING ","mcmn_drv_open");__builtin_trap();}
    int entry_errno=*__errno_location(),trace=getenv("MENU_DMM_UNIT_CONFIG")!=0;
    if(trace) {
        char text[220];snprintf(text,sizeof text,"tid=%ld path=%.80s flags=%#x output=%p",
                               syscall(178),name?name:"(null)",flags,handle);
        record("FULL_MEDIA_MOUNT_DEVICE_OPEN_ENTER ",text);
    }
    *__errno_location()=entry_errno;
    unsigned int result=call(name,flags,handle);int result_errno=*__errno_location();
    if(trace) {
        char text[240];snprintf(text,sizeof text,"tid=%ld path=%.80s result=%#x errno=%d handle=%p",
                               syscall(178),name?name:"(null)",result,result_errno,(!result && handle)?*handle:0);
        record("FULL_MEDIA_MOUNT_DEVICE_OPEN_RETURN ",text);
    }
    *__errno_location()=result_errno;
    return result;
}
static void trace_media_rm_sync(const char *phase,unsigned int id,void *message,int result) {
    if(id!=0x80d9016eU || !getenv("MENU_DMM_UNIT_CONFIG") || !message || !real_msg_size)return;
    int saved_errno=*__errno_location();unsigned int n=real_msg_size(message);char text[800];
    if(n && n<=256) {
        const unsigned char *p=message;char raw[513];
        for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",p[i]);
        snprintf(text,sizeof text,"tid=%ld destination=%#x message=%p bytes=%u transport=%d raw=%s",
                 syscall(178),id,message,n,result,raw);
    } else snprintf(text,sizeof text,"tid=%ld destination=%#x message=%p bytes=%u transport=%d payload_skipped=bounded_256",
                    syscall(178),id,message,n,result);
    record(phase,text);*__errno_location()=saved_errno;
}
int _ZN3MWF12EventWrapper11SendAndRecvEPviS1_i(void *self,void *data,int bytes,void *reply,int reply_bytes) {
    static int (*next)(void *,void *,int,void *,int);
    int entry_errno=*__errno_location();
    int (*call)(void *,void *,int,void *,int)=__atomic_load_n(&next,__ATOMIC_ACQUIRE);
    if(!call) {
        call=real_dlsym?real_dlsym((void *)-1,"_ZN3MWF12EventWrapper11SendAndRecvEPviS1_i"):0;
        if(!call){record("FULL_MEDIA_MOUNT_FORWARD_MISSING ","MWF::EventWrapper::SendAndRecv");__builtin_trap();}
        __atomic_store_n(&next,call,__ATOMIC_RELEASE);
    }
    const unsigned int *w=data;const unsigned short *h=data;
    int trace=getenv("MENU_DMM_UNIT_CONFIG") && data && bytes==228 && w[0]==0x1000 && h[2]==3 && h[3]==0xcc && w[6]==0x1000;
    if(trace) {
        char text[180];snprintf(text,sizeof text,"tid=%ld self=%p data=%p bytes=%d media=%#x reply=%p reply_bytes=%d",
                               syscall(178),self,data,bytes,w[6],reply,reply_bytes);
        record("FULL_MEDIA_MOUNT_CONFIG_QUERY_ENTER ",text);
    }
    *__errno_location()=entry_errno;
    int result=call(self,data,bytes,reply,reply_bytes),result_errno=*__errno_location();
    if(trace) {
        char raw[129],text[300];const unsigned char *p=data;
        for(unsigned int i=0;i<64;i++)snprintf(raw+2*i,3,"%02x",p[i]);
        snprintf(text,sizeof text,"tid=%ld self=%p data=%p result=%#x errno=%d business=%#x config_valid_byte=%u raw_first64=%s",
                 syscall(178),self,data,(unsigned int)result,result_errno,w[5],p[28],raw);
        record("FULL_MEDIA_MOUNT_CONFIG_QUERY_RETURN ",text);
    }
    *__errno_location()=result_errno;
    return result;
}
int osal_snd_sync_msg(unsigned int id, void *message) {
    if (!real_send_sync) __builtin_trap();
    trace_media_mount_sync("FULL_MEDIA_MOUNT_ENTER ",id,message,0);
    trace_media_rm_sync("FULL_MEDIA_MOUNT_RM_SYNC_ENTER ",id,message,0);
    /* appFw's own logger (0x367fa80 / 0x36804c8) ships "%4X %s %s" text to SID 0x008f013a and
       0x008f013a only stores it in the guest ulog. Mirror the text to the console so the firmware's
       own lines (sequence_boot::run, boot_factor, out_result, ...) survive a guest abort. Read-only. */
    if (id == 0x008f013a && message && real_msg_size) {
        unsigned int size = real_msg_size(message);
        if (size > 2) {
            const char *text = (const char *)message + 2;
            char line[72];
            unsigned int n = 0, limit = size - 2;
            if (limit > sizeof line - 1) limit = sizeof line - 1;
            while (n < limit && text[n]) { line[n] = text[n]; ++n; }
            line[n] = 0;
            if (n) record("APPLOG ", line);
        }
    }
    if (id == 0x004b024e) {
        char probe[128];
        unsigned int probe_size = real_msg_size && message ? real_msg_size(message) : 0;
        snprintf(probe, sizeof probe, "tid=%ld bytes=%u word0=%#x source=%#x caller=%p",
                 syscall(178), probe_size, message ? *(const unsigned int *)message : 0,
                 (real_get_source && message) ? real_get_source(message) : 0,
                 __builtin_return_address(0));
        record("VERSION_TRANSPORT_HIT ", probe);
        int serviced = version_transport_reply(id, message);
        if (!serviced) return 0;
    }
    if (0 && id == 0x80924127 && message && real_msg_size && real_msg_size(message) >= 40) {
        /* Sensor GetInh/GetState sync query {0x92,0x111} (or sibling subcodes).
           Reply all-zero: status 0, no inhibit flags, no state — the same shape
           a real sensor returns when nothing inhibits the indicator. */
        unsigned int request = *(const unsigned int *)message;
        char text[140];
        snprintf(text, sizeof text, "tid=%ld request=%#x source=%#x caller=%p",
                 syscall(178), request,
                 real_get_source ? real_get_source(message) : 0, __builtin_return_address(0));
        record("SENSOR_GETINH_REQUEST ", text);
        for (unsigned int i = 4; i < 40; ++i) ((unsigned char *)message)[i] = 0;
        if (!__atomic_fetch_add(&sensor_service_count, 1, __ATOMIC_RELAXED))
            record("SENSOR_GETINH_SERVICE ", "first 0x80924127 reply: all-zero 40-byte sensor state");
        return 0;
    }
    if (0 && id == 0x003e014d && message && real_msg_size && real_msg_size(message) >= 8) {
        /* backup_sync_msg reads only the reply status word at +4 (libbackup+0x1ae8).
           Reply success so the after-UUD settings sync can complete instead of
           retrying forever against the absent CP backup queue. Sparse logging:
           the daemon issues tens of thousands of these per run. */
        unsigned int n = __atomic_fetch_add(&backup_service_count, 1, __ATOMIC_RELAXED);
        if (n < 5 || (n % 5000) == 0) {
            char text[140];
            snprintf(text, sizeof text, "tid=%ld n=%u bytes=%u cmd=%#x source=%#x caller=%p",
                     syscall(178), n + 1, real_msg_size(message), ((const unsigned int *)message)[2],
                     real_get_source ? real_get_source(message) : 0, __builtin_return_address(0));
            record("BACKUP_SYNC_REQUEST ", text);
        }
        ((unsigned int *)message)[1] = 0;  /* reply status at +4: success */
        if (!n) record("BACKUP_SYNC_SERVICE ", "first 0x3e014d reply: status 0 (writes acknowledged, no CP storage)");
        return 0;
    }
    int version = id == 0x004b024e && message && real_msg_size && real_msg_size(message) >= 10 && *(unsigned int *)message == 5;
    if (!version && message && real_msg_size) {
        unsigned int size = real_msg_size(message);
        unsigned int code = size >= 4 ? ((const unsigned short *)message)[1] : 0;
        char text[170];
        snprintf(text, sizeof text, "tid=%ld dest=%#x code=%#x bytes=%u source=%#x caller=%p",
                 syscall(178), id, code, size,
                 real_get_source ? real_get_source(message) : 0, __builtin_return_address(0));
        record("SND_SYNC_OTHER ", text);
    }
    int result = real_send_sync(id, message);
    trace_media_mount_sync("FULL_MEDIA_MOUNT_RETURN ",id,message,result);
    trace_media_rm_sync("FULL_MEDIA_MOUNT_RM_SYNC_RETURN ",id,message,result);
    if (version) {
        const unsigned short *p = message;
        char text[120];
        snprintf(text, sizeof text, "transport=%d status=%u major=%u minor=%u source=original provider/dat4", result, p[2], p[3], p[4]);
        record("CURRENT_VERSION_RESULT ", text);
    }
    return result;
}
static int dmm_send(void *request) {
    if (!real_allocate_msg || !real_free_msg || !real_get_source || !real_set_source || !real_msg_size || !real_send_msg)
        return -1021;
    unsigned int source = real_get_source(request);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 40, 1);
    if (result) return result;
    pthread_mutex_lock(cap_lock);
    struct dmm_service previous = dmm;
    result = dmm_service_reply(&dmm, request, real_msg_size(request), reply);
    unsigned int handle = 0, size = 0;
    unsigned long long address = 0;
    int status = -1024;
    if (!result) {
        handle = ((unsigned int *)reply)[3]; size = ((unsigned int *)reply)[8];
        address = ((unsigned long long *)reply)[3]; status = ((short *)reply)[1];
    }
    if (!result) {
        real_set_source(reply, 0x9061003c);
        result = real_send_msg(source, reply);
    }
    if (result) dmm = previous;
    char text[220];
    snprintf(text, sizeof text, "source=%#x op=%#x transport=%d status=%d handle=%#x address=%#llx size=%#x slots=%d/%d opens=%u/%u",
             source, ((unsigned short *)request)[0], result,
             status, handle, address, size, dmm.slots[0].allocated, dmm.slots[1].allocated,
             dmm.slots[0].open_count, dmm.slots[1].open_count);
    record("DMM_SERVICE ", text);
    pthread_mutex_unlock(cap_lock);
    if (result) { real_free_msg(source, reply); return result; }
    real_free_msg(0x9061003c, request);
    return 0;
}
static unsigned int record_osd_transport(const char *prefix, unsigned int id, const void *message) {
    if (!getenv("MENU_OSD_OBSERVE")) return 0;
    unsigned int local = id & 0x7fffffffu;
    if (local != 0x0280074d && local != 0x0280084d && local != 0x0280084e &&
        local != 0x0288076c && local != 0x028808e1) return 0;
    static unsigned int total;
    unsigned int count = __atomic_add_fetch(&total, 1, __ATOMIC_RELAXED);
    if (count > 128) {
        if (count == 129) record("OSD_TRANSPORT_LIMIT ", "first 128 send/receive observations; later calls forwarded");
        return 0;
    }
    unsigned int size = message && real_msg_size ? real_msg_size((void *)message) : 0;
    unsigned int shown = size < 96 ? size : 96;
    const unsigned char *p = message;
    const char digits[] = "0123456789abcdef";
    char hex[193], text[448];
    for (unsigned int i = 0; i < shown; ++i) { hex[2*i] = digits[p[i] >> 4]; hex[2*i+1] = digits[p[i] & 15]; }
    hex[2*shown] = 0;
    snprintf(text, sizeof text, "call=%u tid=%ld endpoint=%#x source=%#x bytes=%u shown=%u payload=%s",
             count, syscall(178), id, message && real_get_source ? real_get_source((void *)message) : 0,
             size, shown, hex);
    record(prefix, text);
    return count;
}
int osal_rcv_msg_tmo(unsigned int id, void **message, long timeout) {
    if (!real_rcv_msg_tmo) __builtin_trap();
    /* Live interaction: the original input loop itself polls 0x5503e0. Feed the queued key
       here as a real allocated message, so the AppFw thread consumes it through its own
       receive path (the same path that handled the scripted first-setup walk). */
    if (id == 0x5503e0) {
        static unsigned int seen_diag;
        if (seen_diag < 3 && __atomic_load_n(&live_key_pending, __ATOMIC_ACQUIRE)) {
            seen_diag++;
            char dg[200];
            snprintf(dg, sizeof dg, "diag appfw=%d alloc=%d src=%d send=%d pending=%u tid=%ld",
                     appfw_base != 0, real_allocate_msg != 0, real_set_source != 0,
                     real_send_msg != 0, __atomic_load_n(&live_key_pending, __ATOMIC_ACQUIRE), syscall(178));
            record("KEY_DIAG ", dg);
        }
    }
    if (id == 0x5503e0 && appfw_base && real_allocate_msg && real_set_source &&
        real_send_msg && __atomic_load_n(&live_key_pending, __ATOMIC_ACQUIRE)) {
        unsigned int code, status;
        if (__atomic_load_n(&live_key_pending, __ATOMIC_ACQUIRE)) {
            code = live_key_code; status = live_key_status;
            __atomic_store_n(&live_key_pending,0,__ATOMIC_RELEASE);
            void *km = 0;
            if (!real_allocate_msg(0x5503e0U, &km, 32, 1) && km) {
                unsigned char *ev = km;
                for (unsigned int i = 0; i < 32; ++i) ev[i] = 0;
                ev[0] = code & 0xff; ev[1] = (code >> 8) & 0xff; ev[8] = status;
                real_set_source(km, 0x5503e0U);
                int sent = real_send_msg(0x5503e0U, km);
                char kt[150];
                snprintf(kt, sizeof kt, "loop posted key=%#x status=%u send=%d tid=%ld",
                         code, status, sent, syscall(178));
                record("KEY_INJECT ", kt);
                if (sent) real_free_msg(0x5503e0U, km);
            } else record("KEY_INJECT ", "loop allocation failed");
        }
    }
    if (sequence_event_enabled && appfw_base) {
        unsigned int dispatcher = *(volatile unsigned int *)(appfw_base + 0x910fa1c);
        if ((id >> 16) == 0x81cf && id != dispatcher) {
            static unsigned int delivered[16];
            static unsigned int delivered_count;
            int already = 0;
            for (unsigned int i = 0; i < delivered_count && i < 16; ++i)
                if (delivered[i] == id) { already = 1; break; }
            if (!already && delivered_count < 16) {
                delivered[delivered_count++] = id;
                sequence_event_deliver(id, delivered_count);
            }
        }
    }
    /* Record each (tid, queue, timeout) tuple once: full receive-map without flooding. */
    static struct { unsigned int tid, queue; long timeout; } seen[256];
    static unsigned int seen_count;
    unsigned int tid = (unsigned int)syscall(178);
    int trace = timeout < 0 || (id >> 16) == 0x81cf || id == 0x5503e0;
    int known = 0;
    for (unsigned int i = 0; i < seen_count && i < 256; ++i)
        if (seen[i].tid == tid && seen[i].queue == id && seen[i].timeout == timeout) { known = 1; break; }
    if (!known) {
        unsigned int slot = __atomic_fetch_add(&seen_count, 1, __ATOMIC_RELAXED);
        if (slot < 256) { seen[slot].tid = tid; seen[slot].queue = id; seen[slot].timeout = timeout; }
        Dl_info info;
        const char *module = "?";
        unsigned long offset = 0;
        void *caller = __builtin_return_address(0);
        if (real_dladdr && real_dladdr(caller, &info) && info.dli_fbase) {
            module = info.dli_fname ? info.dli_fname : "?";
            offset = (unsigned long)caller - (unsigned long)info.dli_fbase;
        }
        char text[240];
        snprintf(text, sizeof text, "tid=%u queue=%#x timeout=%ld caller=%s+%#lx", tid, id, timeout, module, offset);
        record("RCV_SITE ", text);
        if (getenv("MENU_OSD_OBSERVE") && (((id >> 16) & 0xfff) == 0x280 || ((id >> 16) & 0xfff) == 0x288))
            record("OSD_RECEIVER_SITE ", text);
    }
    char text[240];
    if (trace) {
        Dl_info info;
        const char *module = "?";
        unsigned long offset = 0;
        void *caller = __builtin_return_address(0);
        if (real_dladdr && real_dladdr(caller, &info) && info.dli_fbase) {
            module = info.dli_fname ? info.dli_fname : "?";
            offset = (unsigned long)caller - (unsigned long)info.dli_fbase;
        }
        snprintf(text, sizeof text, "tid=%ld queue=%#x timeout=%ld enter caller=%s+%#lx", syscall(178), id, timeout, module, offset);
        record("RCV_MSG_WAIT ", text);
    }
    int result = real_rcv_msg_tmo(id, message, timeout);
    if (!result && id == 0x005503e0 && message && *message &&
        (getenv("MENU_INJECT_KEY") || getenv("MENU_OBSERVE_INPUT")) && real_msg_size && real_get_source &&
        real_msg_size(*message) == 32 && real_get_source(*message) == 0x005503e0) {
        const unsigned int *event = *message;
        if (event[0] == 0x1ab || event[0] == 0x1ac || event[0] == 0x3 || event[0] == 0x30 ||
            event[0] == 0x15 || event[0] == 0x1af) {
            char key_text[128];
            const char *name = event[0]==0x1ab?"MENU":event[0]==0x1ac?"CONFIRM":event[0]==0x3?"UP":
                               event[0]==0x30?"DOWN":event[0]==0x15?"LEFT":"RIGHT";
            snprintf(key_text, sizeof key_text, "App queue received %s key=%#x status=%u repeat=%u",
                     name,event[0], event[2], event[5]);
            record("KEY_INJECT ", key_text);
        }
    }
    if (!result && message && *message && id == 0x5503e0) {
        const unsigned int *ev = *message;
        if(getenv("MENU_OBSERVE_INPUT") && real_msg_size && real_msg_size(*message)==32) {
            static unsigned int count;
            unsigned int n=__atomic_add_fetch(&count,1,__ATOMIC_RELAXED);
            if(n<=128 || !(n&(n-1))) {
                char text[260];snprintf(text,sizeof text,"n=%u tid=%ld words=[%#x,%#x,%#x,%#x,%#x,%#x,%#x,%#x]",
                    n,syscall(178),ev[0],ev[1],ev[2],ev[3],ev[4],ev[5],ev[6],ev[7]);
                record("INPUT_EVENT32 ",text);
            }
        }
        char kt[160];
        snprintf(kt, sizeof kt, "tid=%ld pid=%ld code=%#x status=%u bytes=%u",
                 syscall(178), (long)getpid(), ev[0], (unsigned int)ev[2], real_msg_size ? real_msg_size(*message) : 0);
        record("KEY_RECV ", kt);
    }
    if (!result && message && *message) record_osd_transport("OSD_TRANSPORT_RECEIVE ", id, *message);
    if (!result && id == 0x807a0020 && bb_ready_pending) bb_key_seen = 1;
    if (trace) {
        unsigned int code = 0, size = 0;
        if (!result && message && *message && real_msg_size) {
            size = real_msg_size(*message);
            if (size >= 4) code = ((const unsigned short *)*message)[1];
        }
        snprintf(text, sizeof text, "tid=%ld queue=%#x timeout=%ld result=%d reply_code=%#x bytes=%u",
                 syscall(178), id, timeout, result, code, size);
        record("RCV_MSG_TMO ", text);
    }
    return result;
}
static unsigned int lens_pool_lookup_flags(void *message, unsigned int *from) {
    pthread_mutex_lock(lens_pool_lock);
    unsigned int flags = 0;
    for (int i = 0; i < LENS_POOL_SLOTS; ++i)
        if (lens_pool[i].live && lens_pool[i].message == message) {
            flags = lens_pool[i].live;
            *from = lens_pool[i].borrowed_from;
            lens_pool[i].live = 0;
            break;
        }
    pthread_mutex_unlock(lens_pool_lock);
    return flags;
}
static unsigned int lens_pool_lookup(void *message) {
    unsigned int from = 0;
    lens_pool_lookup_flags(message, &from);
    return from;
}
int osal_valloc_msg_wait(unsigned int id, void **message, unsigned int size, unsigned int count) {
    if (!real_allocate_msg) __builtin_trap();
    if (id == 0x004b024e) {
        char probe[96];
        snprintf(probe, sizeof probe, "tid=%ld size=%u count=%u", syscall(178), size, count);
        record("VERSION_VALLOC_HIT ", probe);
    }
    if (0 && id == 0x80924127 && size == 40 && count == 1 && message) {
        /* libObj sensor GetInh/GetState family (clients at libObj+0xcc07c/+0xed6e0):
           valloc 40 bytes from the absent 0x8092-node sensor queue, sync query
           {0x92,0x111,...}. Without a reply the CInfraIndctr lazy-init at
           libObj+0xc7cfc leaves its [0x28] sub-object dangling and the next
           indicator log SEGVs (run-7fan0f7i/8bgy9uuw at libObj+0xc7ce4). */
        extern void *malloc(unsigned long);
        unsigned char *raw = malloc(16 + 40);
        if (!raw) return -1024;
        for (int i = 0; i < 56; ++i) raw[i] = 0;
        *(unsigned int *)(raw + 8) = 40;
        *message = raw + 16;
        pthread_mutex_lock(lens_pool_lock);
        int slot = -1;
        for (int i = 0; i < LENS_POOL_SLOTS; ++i)
            if (!lens_pool[i].live) { slot = i; break; }
        if (slot >= 0) {
            lens_pool[slot].live = 2;
            lens_pool[slot].message = *message;
            lens_pool[slot].borrowed_from = 0;
        }
        pthread_mutex_unlock(lens_pool_lock);
        record("SENSOR_POOL_ALLOC ", "malloc'd 40 bytes with osal header");
        return 0;
    }
    if (0 && id == 0x003e014d && size == 112 && count == 1 && message && !backup_service_enabled) {
        /* Diagnostic-only path: with the reply service disabled the valloc keeps
           failing exactly as before (silent return 0 + infinite retry), but the
           first commands are logged so the reply policy can be made selective. */
        return real_allocate_msg(id, message, size, count);
    }
    if (0 && id == 0x003e014d && size == 112 && count == 1 && message) {
        /* libbackup backup_sync_msg (libbackup+0x1a10) vallocs 112 bytes from the
           CP-side backup queue; without it every call fails silently (returns 0 with
           the result word untouched) and the daemon retries forever (39k+ per run).
           The message never enters a kernel queue (the sync send is serviced inline),
           so a malloc'd buffer with the 16-byte osal header (size at -8, src at -0xc)
           satisfies osal_msg_size/get_msg_src exactly. */
        extern void *malloc(unsigned long);
        unsigned char *raw = malloc(16 + 112);
        if (!raw) return -1024;
        for (int i = 0; i < 128; ++i) raw[i] = 0;
        *(unsigned int *)(raw + 8) = 112;
        *message = raw + 16;
        pthread_mutex_lock(lens_pool_lock);
        int slot = -1;
        for (int i = 0; i < LENS_POOL_SLOTS; ++i)
            if (!lens_pool[i].live) { slot = i; break; }
        if (slot >= 0) {
            lens_pool[slot].live = 2;  /* 2 = malloc'd, free with free(raw) */
            lens_pool[slot].message = *message;
            lens_pool[slot].borrowed_from = 0;
        }
        pthread_mutex_unlock(lens_pool_lock);
        record("BACKUP_POOL_ALLOC ", slot >= 0 ? "malloc'd 112 bytes with osal header" : "map full; leak instead of wrong free");
        return 0;
    }
    if (id == 0x912503d0 && size == 20 && count == 1 && message) {
        /* Borrow the ulog queue pool: the CP updater queue does not exist in QEMU. */
        int result = real_allocate_msg(0x8f013a, message, 20, 1);
        if (!result) {
            pthread_mutex_lock(lens_pool_lock);
            int slot = -1;
            for (int i = 0; i < LENS_POOL_SLOTS; ++i)
                if (!lens_pool[i].live) { slot = i; break; }
            if (slot >= 0) {
                lens_pool[slot].live = 1;
                lens_pool[slot].message = *message;
                lens_pool[slot].borrowed_from = 0x8f013a;
            }
            pthread_mutex_unlock(lens_pool_lock);
            record("LENS_POOL_ALLOC ", slot >= 0 ? "borrowed 20 bytes from 0x8f013a" : "map full; free will passthrough");
        }
        return result;
    }
    return real_allocate_msg(id, message, size, count);
}
static __attribute__((noinline)) void native_pin_format_readback(void) {
    struct pin_connection_snapshot state;
    full_pin_connection_snapshot(&state);
    if (!state.format_consumed) return;
    struct pin_control_snapshot pool;
    pin_control_snapshot(&pool);
    char text[400];
    snprintf(text, sizeof text,
             "tid=%ld handle=%#x format_cpu_consumed=%u buffer_released=%u live=%u pin_index=%u ordinal=%u code=%u component=%u encoded_flags=%u width=%u height=%u camera_startup_verified=0",
             syscall(178), state.buffer_handle, state.format_consumed, state.buffer_released, pool.live,
             state.format_current.pin_index, state.format_current.ordinal, state.format_current.code,
             state.format_current.component, state.format_current.encoded_flags,
             state.format_current.width, state.format_current.height);
    record("FULL_PIN_FORMAT_PERSISTENT_READBACK ", text);
}
int osal_free_msg(unsigned int id, void *message) {
    if (!real_free_msg) __builtin_trap();
    int media_mount_trace=trace_media_mount_completion("FULL_MEDIA_MOUNT_FREE_ENTER ",id,message);
    int vdf_result;
    if (native_cp_background_release(id,message,real_free_msg,record,&vdf_result)) {
        char text[180];snprintf(text,sizeof text,"tid=%ld owner=%#x message=%p caller=%p rc=%d",
            syscall(178),id,message,__builtin_return_address(0),vdf_result);
        record("NATIVE_CP_BACKGROUND_FREE_CALLER ",text);
        return vdf_result;
    }
    if(rm_file_enabled && native_rm_file_release(id,message,real_free_msg,record,&vdf_result))return vdf_result;
    if (__atomic_load_n(&pin_connection_used, __ATOMIC_ACQUIRE) &&
        full_pin_connection_release(id, message, real_free_msg, record, &vdf_result)) {
        if (!vdf_result) native_pin_format_readback();
        return vdf_result;
    }
    if (__atomic_load_n(&vdf_config_used, __ATOMIC_ACQUIRE) &&
        full_vdf_release_reply(id, message, real_free_msg, record, &vdf_result))
        return vdf_result;
    if (__atomic_load_n(&hdmi_config_used, __ATOMIC_ACQUIRE) &&
        full_hdmi_release_reply(id, message, real_free_msg, record, &vdf_result))
        return vdf_result;
    if (__atomic_load_n(&audio_config_used, __ATOMIC_ACQUIRE) &&
        full_audio_release_reply(id, message, real_free_msg, record, &vdf_result))
        return vdf_result;
    if (__atomic_load_n(&dig_level_used, __ATOMIC_ACQUIRE) &&
        native_dig_level_release(id, message, real_free_msg, record, &vdf_result))
        return vdf_result;
    if (__atomic_load_n(&dmm_unit_used, __ATOMIC_ACQUIRE) &&
        native_dmm_unit_release(id, message, real_free_msg, record, &vdf_result))
        return vdf_result;
    if (__atomic_load_n(&pin_registry_used, __ATOMIC_ACQUIRE) &&
        (full_vef_release_reply(id, message, real_free_msg, record, &vdf_result) ||
         full_pinmem_release_reply(id, message, real_free_msg, record, &vdf_result) ||
         full_scalar_release_reply(id, message, real_free_msg, record, &vdf_result) ||
         full_adf_release_reply(id, message, real_free_msg, record, &vdf_result) ||
         full_hdmi_pin_release_reply(id, message, real_free_msg, record, &vdf_result) ||
         native_osdpin_release_reply(id, message, real_free_msg, record, &vdf_result) ||
         native_drawinfo_release_reply(id, message, real_free_msg, record, &vdf_result) ||
         native_infrabb_release_reply(id, message, real_free_msg, record, &vdf_result)))
        return vdf_result;
    if (id == 0x912503d0 && message) {
        unsigned int from = 0;
        unsigned int flags = lens_pool_lookup_flags(message, &from);
        if (flags == 2) { extern void free(void *); free((char *)message - 16); return 0; }
        if (from) return real_free_msg(from, message);
    }
    int result=real_free_msg(id,message),saved_errno=*__errno_location();
    if(media_mount_trace) {
        char text[180];snprintf(text,sizeof text,"tid=%ld id=%#x message=%p result=%d caller=%p",
                               syscall(178),id,message,result,__builtin_return_address(0));
        record("FULL_MEDIA_MOUNT_FREE_RETURN ",text);
    }
    *__errno_location()=saved_errno;
    return result;
}
/* Virtual CP release-inhibit endpoint (SID 0x90040193, command 0x403d).
   Evidence (analysis/qemu-boot-research/main-screen-entry/cp-cmd/REPORT.md):
   - appFw sends a 16-byte request here from execute_infra_cmd_i (0x353a4ec) and waits for a 12-byte
     reply it copies into its own buffer, then accepts the call only when reply+8 == 0xf000
     (0x353a4f0..0x353a4f8).
   - The real CP producer is cpapp-b.bin file offset 0x9dc4de: it allocates 12 bytes, writes
     type=1, cmd=0x403d, echoes the request token, status 0xf000, source=0x90040193,
     destination=0x80020002, and sends asynchronously.
   - The original defers that reply only while a release is active (0x9d9642 reason mask 0x8000).
     This virtual camera has no active release, so the "no active release" branch (immediate reply)
     is the honest one; the deferral branch is NOT implemented and is recorded as such.
   - This consumes the request: appFw still owns and frees its own buffer, so this function must not
     free it. If the allocation or send fails we refuse to answer instead of inventing success. */
static int cp_release_service(unsigned int destination, void *request) {
    if (!real_allocate_msg || !real_send_msg || !real_set_source || !real_msg_size || !real_get_source)
        return -1021;
    if (!request) return -1024;
    unsigned int size = real_msg_size(request);
    if (size < 16) return -1024;
    const unsigned short *half = request;
    unsigned int type = *(const unsigned char *)request;
    unsigned int command = half[1];
    if (type != 5 || command != 0x403d) return -1024;
    const unsigned int *words = request;
    unsigned int token = words[1];
    unsigned int source = real_get_source(request);
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 12, 1);
    if (result || !reply) return result ? result : -1024;
    unsigned char *body = reply;
    body[0] = 1;                       /* reply type */
    body[1] = 0;                       /* deterministic zero; CP does not guarantee this byte */
    body[2] = (unsigned char)(command & 0xff);
    body[3] = (unsigned char)(command >> 8);
    *(unsigned int *)(body + 4) = token; /* echo the real request token */
    *(unsigned int *)(body + 8) = 0xf000; /* status: success */
    real_set_source(reply, destination);
    result = real_send_msg(source, reply);
    char text[224];
    snprintf(text, sizeof text,
             "cmd=%#x bytes=%u token=%#x source=%#x result=%d request=%08x,%08x,%08x,%08x",
             command, size, token, source, result, words[0], words[1], words[2], words[3]);
    record("CP_RELEASE_SERVICE ", text);
    if (result) record("CP_RELEASE_SERVICE_FAILED ", "reply not delivered; request left unanswered");
    return result;
}
/* SID 0x90280964 is the Darwin (CP) time service. OptionInstaller::TimeManagement::
   initialize_time_manager asks it for the power-off time and the total time, then blocks in
   osal_rcv_msg_tmo(reply_queue, -1) waiting for the answer. Nothing in this emulated camera
   registers that SID, and the transport used to report success anyway, so the worker thread of
   libInfraOptionInstall parked there forever and never reached its ready=1 store
   (libInfraOptionInstall 0xc61c) - which in turn kept every 0x01ae852d license query at
   "not ready" and made sequence_boot::run_i assert.
   The firmware has its own documented fallback for an absent CP: when osal_snd_msg fails it
   reads the same values from the backup subsystem (label_163f0 -> read_from_backup) instead of
   waiting. Reporting the real "no such destination" error therefore hands control to the
   firmware's own degradation path instead of inventing a reply. The reply contract, recovered
   from the shipped library, is recorded in the report for a future real endpoint:
   reply byte+2 == 0, cmd1 requires u32+4 == 1, cmd2 requires (byte+4 & 0xc1) == 0xc1, and
   u32+8 carries the value in both rounds. */
/* Every sync OSAL request goes through one helper (appFw 0x3599c6c: valloc -> memcpy ->
   osal_snd_sync_msg -> copy_back). Hooking osal_snd_sync_msg only shows that helper's own frame,
   so the real client of a failing request stays invisible. This entry probe records the helper's
   caller (x30), the raw destination value, the request length and the first body word, which is
   what identifies the subsystem that asked. Replays the overwritten instructions verbatim. */
static unsigned int sync_call_seen;
void capture_sync_call(unsigned long caller, unsigned long body, unsigned long length,
                       unsigned long raw_id) {
    if (sync_call_seen++ >= 40) return;
    unsigned int first = 0;
    if (body > 0x100000UL && body < 0x800000000000UL) first = *(unsigned int *)body;
    char text[200];
    snprintf(text, sizeof text, "n=%u tid=%ld caller=appFw+%#lx raw=%#x id=%#x len=%lu body0=%08x",
             sync_call_seen, syscall(178), (unsigned long)(caller - appfw_base), raw_id,
             raw_id & 0x7fff, length, first);
    record("SYNC_CALL ", text);
}
__asm__(
".text\n"
".globl sync_call_trampoline\n"
".type sync_call_trampoline, %function\n"
"sync_call_trampoline:\n"
"    mov x3, x2\n"                  /* raw id (w2) */
"    mov x2, x1\n"                  /* length */
"    mov x1, x0\n"                  /* body */
"    mov x0, x30\n"                 /* caller of the helper */
PROBE_SAVE_ARGS
"    bl capture_sync_call\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9bb7bfd\n"            /* stp x29,x30,[sp,#-80]! */
"    .inst 0x910003fd\n"            /* mov x29,sp */
"    .inst 0xa90153f3\n"            /* stp x19,x20,[sp,#16] */
"    .inst 0x2a0203f4\n"            /* mov w20,w2 */
"    adrp x16, sync_call_continue\n"
"    ldr x16, [x16, #:lo12:sync_call_continue]\n"
"    br x16\n"
);
extern void sync_call_trampoline(void);
static void *sync_call_continue;
static void start_bus_power_module(void) {
    void *handle = real_dlopen("libBusPower.so", 1 | 0x100 /* RTLD_LAZY | RTLD_GLOBAL */);
    char text[256];
    if (!handle) {
        typedef const char *(*dlerror_type)(void);
        dlerror_type get_error = (dlerror_type)real_dlsym((void *)-1, "dlerror");
        const char *reason = get_error ? get_error() : 0;
        snprintf(text, sizeof text, "dlopen failed: %s", reason && *reason ? reason : "(no dlerror)");
        record("BUSPOWER ", text);
        return;
    }
    typedef void (*init_type)(void);
    init_type bus_power_init = (init_type)real_dlsym(handle, "BusPower_Init");
    if (!bus_power_init) { record("BUSPOWER ", "lib loaded but BusPower_Init missing"); return; }
    record("BUSPOWER ", "calling BusPower_Init (firmware's own module entry)");
    bus_power_init();
    record("BUSPOWER ", "BusPower_Init returned");
}
static void install_sync_call_probe(unsigned long base) {
    sync_call_continue = (void *)(base + 0x3599c6cUL + 16);
    arm_entry_probe(base + 0x3599c6cUL, (const unsigned int[4]){0xa9bb7bfd, 0x910003fd, 0xa90153f3, 0x2a0203f4},
                    (void *)sync_call_trampoline, sync_call_continue, "sync_call 0x3599c6c");
}
static unsigned int cp_time_unavailable;

int osal_snd_msg(unsigned int id, void *message) {
    if(id==0x9088076bU && message && real_msg_size && getenv("MENU_LIVE_KEY_FILE")) {
        static unsigned int captured;
        unsigned int ticket=__atomic_fetch_add(&captured,1,__ATOMIC_RELAXED),n=real_msg_size(message);
        if(ticket<3 && n<=4096) {
            const unsigned char *p=message;
            for(unsigned int offset=0;offset<n;offset+=128) {
                unsigned int count=n-offset;if(count>128)count=128;
                char raw[257],line[440];
                for(unsigned int j=0;j<count;j++)snprintf(raw+2*j,3,"%02x",p[offset+j]);
                snprintf(line,sizeof line,"capture=%u tid=%ld message=%p bytes=%u offset=%u raw=%s",
                         ticket,syscall(178),message,n,offset,raw);
                record("GUI_PROPERTY_BYTES ",line);
            }
        }
    }
    trace_media_mount_completion("FULL_MEDIA_MOUNT_ASYNC_SEND ",id,message);
    if (!real_send_msg) __builtin_trap();
    if (id == 0x8102021fU && getenv("MENU_DMM_UNIT_CONFIG") && message && real_msg_size) {
        unsigned int bytes = real_msg_size(message);
        if (bytes <= 64) {
            const unsigned char *in = message; char raw[129], text[280];
            for (unsigned int i = 0; i < bytes; ++i) snprintf(raw + i * 2, 3, "%02x", in[i]);
            raw[bytes * 2] = 0;
            snprintf(text, sizeof text, "tid=%ld destination=%#x source=%#x bytes=%u raw=%s",
                     syscall(178), id, real_get_source ? real_get_source(message) : 0, bytes, raw);
            record("FULL_DMM_UNIT_POST_BOOT_REQUEST ", text);
        }
    }
    if (id == 0x90030001U && getenv("MENU_DMM_UNIT_CONFIG") && message && real_msg_size) {
        unsigned int bytes = real_msg_size(message);
        if (bytes >= 4 && bytes <= 64) {
            const unsigned char *in = message; char raw[129], text[280];
            for (unsigned int i = 0; i < bytes; ++i) snprintf(raw + i * 2, 3, "%02x", in[i]);
            raw[bytes * 2] = 0;
            snprintf(text, sizeof text, "tid=%ld destination=%#x source=%#x bytes=%u raw=%s",
                     syscall(178), id, real_get_source ? real_get_source(message) : 0, bytes, raw);
            record("FULL_DMM_UNIT_POST_BOOT_CP_REQUEST ", text);
        }
    }
    if (id==NATIVE_CP_BACKGROUND_SID && getenv("MENU_CP_BACKGROUND") &&
        same_name(getenv("MENU_CP_BACKGROUND"),"virtual-mode3-cold-v1")) {
        const struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,
            real_send_msg,real_msg_size,real_get_source,record};
        int result;
        if (native_cp_background_dispatch(id,message,&io,1,&result)) return result;
    }
    if (id == NATIVE_DMM_UNIT_SID && getenv("MENU_DMM_UNIT_CONFIG")) {
        __atomic_store_n(&dmm_unit_used, 1, __ATOMIC_RELEASE);
        const struct full_imaging_io io = {
            real_allocate_msg, real_free_msg, real_set_source, real_send_msg,
            real_msg_size, real_get_source, record
        };
        int result;
        if (native_dmm_unit_dispatch(id, message, &io, 1, &result)) return result;
    }
    if (id == NATIVE_DIG_LEVEL_SID && getenv("MENU_DIG_LEVEL") &&
        !strcmp(getenv("MENU_DIG_LEVEL"), "virtual")) {
        __atomic_store_n(&dig_level_used, 1, __ATOMIC_RELEASE);
        const struct full_imaging_io io = {
            real_allocate_msg, real_free_msg, real_set_source, real_send_msg,
            real_msg_size, real_get_source, record
        };
        int result;
        if (native_dig_level_dispatch(id, message, &io, 1, &result)) return result;
    }
    if (id == 0x912f0335U && getenv("MENU_AUDIO_BOOT_CONFIG") && message && real_msg_size) {
        unsigned int size = real_msg_size(message);
        if (size <= 64) {
            const unsigned char *in = message; char raw[129], text[256];
            for (unsigned int i = 0; i < size; ++i) snprintf(raw + i * 2, 3, "%02x", in[i]);
            raw[size * 2] = 0;
            snprintf(text, sizeof text, "tid=%ld destination=%#x source=%#x bytes=%u raw=%s",
                     syscall(178), id, real_get_source ? real_get_source(message) : 0, size, raw);
            record("FULL_AUDIO_BOOT_NEXT_REQUEST ", text);
        }
    }
    /* Observe the original destination before choosing a model; native and dump routes can differ. */
    int pin_enabled = getenv("MENU_PIN_REGISTRY") != 0;
    unsigned int pin_bytes = pin_enabled && message && real_msg_size ? real_msg_size(message) : 0;
    if (message && pin_enabled &&
        (pin_bytes == 48 || pin_bytes == 64) && ((const unsigned int *)message)[1] == 0xa0a0a0a0U) {
        const unsigned char *bytes = message;
        const char digits[] = "0123456789abcdef";
        char raw[129], text[256];
        for (unsigned int i = 0; i < pin_bytes; ++i) {
            raw[i * 2] = digits[bytes[i] >> 4];
            raw[i * 2 + 1] = digits[bytes[i] & 15];
        }
        raw[pin_bytes * 2] = 0;
        snprintf(text, sizeof text, "tid=%ld destination=%#x source=%#x bytes=%u raw=%s",
                 syscall(178), id, real_get_source ? real_get_source(message) : 0, pin_bytes, raw);
        record(pin_bytes == 48 ? "PIN_QUERY " : "PIN_CONTROL_REQUEST ", text);
    }
    if ((id == FULL_VEF_CP || id == FULL_PINMEM_CP) && getenv("MENU_PIN_CONNECTION")) {
        if (pin_control_open_guest(1) != 1) {
            record("FULL_PIN_CONNECT_FAULT ", "guest-control-backing-binding-failed");
            return -1021;
        }
        if (!__atomic_exchange_n(&pin_connection_used, 1, __ATOMIC_ACQ_REL))
            record("FULL_PIN_CONNECT_BACKING ", "physical=0x500000000 bytes=8192 owner=virtual-cold pixels_consumed=0");
        const struct full_imaging_io io = {
            real_allocate_msg, real_free_msg, real_set_source, real_send_msg,
            real_msg_size, real_get_source, record
        };
        int result;
        if (full_pin_connection_dispatch(id, message, &io, 2, &result)) return result;
    }
    /* The shared model handles raw 0165 explicitly; all other raw commands still fall through. */
    if (id == FULL_VDF_INPUT && getenv("MENU_PANEL_REVERSE") &&
        !strcmp(getenv("MENU_PANEL_REVERSE"), "virtual")) {
        __atomic_store_n(&vdf_config_used, 1, __ATOMIC_RELEASE);
        const struct full_imaging_io io = {
            real_allocate_msg, real_free_msg, real_set_source, real_send_msg,
            real_msg_size, real_get_source, record
        };
        int result;
        if (full_vdf_reverse_dispatch(id, message, &io, 1, &result)) return result;
    }
    if ((id == FULL_VDF_CP || id == FULL_VDF_INPUT) && getenv("MENU_VDF_CONFIG")) {
        __atomic_store_n(&vdf_config_used, 1, __ATOMIC_RELEASE);
        const struct full_imaging_io io = {
            real_allocate_msg, real_free_msg, real_set_source, real_send_msg,
            real_msg_size, real_get_source, record
        };
        int result;
        if (full_vdf_dispatch(id, message, &io, 1, &result)) return result;
    }
    if (id == FULL_AUDIO_INPUT && getenv("MENU_AUDIO_BOOT_CONFIG")) {
        __atomic_store_n(&audio_config_used, 1, __ATOMIC_RELEASE);
        unsigned int bytes = message && real_msg_size ? real_msg_size(message) : 0;
        if (bytes >= 8 && bytes <= 40) {
            const unsigned char *in = message;
            char raw[81], text[240];
            for (unsigned int i = 0; i < bytes; ++i) snprintf(raw + i * 2, 3, "%02x", in[i]);
            snprintf(text, sizeof text, "tid=%ld destination=%#x source=%#x bytes=%u raw=%s",
                     syscall(178), id, real_get_source ? real_get_source(message) : 0, bytes, raw);
            record("FULL_AUDIO_INPUT ", text);
        }
        const struct full_imaging_io io = {
            real_allocate_msg, real_free_msg, real_set_source, real_send_msg,
            real_msg_size, real_get_source, record
        };
        int result;
        if (full_audio_dispatch_capabilities(id, message, &io, FULL_AUDIO_BOOT,
                                            FULL_AUDIO_CAPS_INPUTLESS, &result)) return result;
    }
    if (id == FULL_HDMI_CP && getenv("MENU_HDMI_BOOT_CONFIG")) {
        __atomic_store_n(&hdmi_config_used, 1, __ATOMIC_RELEASE);
        const struct full_imaging_io io = {
            real_allocate_msg, real_free_msg, real_set_source, real_send_msg,
            real_msg_size, real_get_source, record
        };
        int result;
        if (full_hdmi_dispatch(id, message, &io, FULL_HDMI_BOOT, &result)) return result;
    }
    if ((id == FULL_VEF_CP || id == FULL_PINMEM_CP || id == FULL_SCALAR_CP || id == FULL_ADF_CP || id == FULL_HDMI_PIN_CP ||
         id == NATIVE_INFRABB_CP || id == NATIVE_DRAWINFO_CP || id == NATIVE_OSDPIN_CP) && pin_enabled) {
        __atomic_store_n(&pin_registry_used, 1, __ATOMIC_RELEASE);
        const struct full_imaging_io io = {
            real_allocate_msg, real_free_msg, real_set_source, real_send_msg,
            real_msg_size, real_get_source, record
        };
        int result;
        if (full_vef_dispatch(id, message, &io, 1, &result) ||
            full_pinmem_dispatch(id, message, &io, 1, &result) ||
            full_scalar_dispatch(id, message, &io, 1, &result) ||
            full_adf_dispatch(id, message, &io, 1, &result) ||
            full_hdmi_pin_dispatch(id, message, &io, 1, &result) ||
            native_osdpin_dispatch(id, message, &io, 1, &result) ||
            native_drawinfo_dispatch(id, message, &io, 1, &result) ||
            native_infrabb_dispatch(id, message, &io, 1, &result)) return result;
    }
    if (honest_no_receiver(id)) {
        static unsigned int honest_seen;
        if (honest_seen++ < 24) {
            char text[128];
            snprintf(text, sizeof text, "n=%u tid=%ld dest=%#x -> -1021 (nothing registered)",
                     honest_seen, syscall(178), id);
            record("HONEST_ROUTE ", text);
        }
        return -1021;
    }
    if (getenv("MENU_CP_TIME_SERVICE") && id == 0x90280964 && message) {
        const unsigned char *body = message;
        char text[160];
        if (cp_time_unavailable++ < 8) {
            snprintf(text, sizeof text, "n=%u opcode=%u reply_queue=%#x -> -1021 (no Darwin endpoint)",
                     cp_time_unavailable, body[1], *(const unsigned int *)(body + 4));
            record("CP_TIME_SERVICE ", text);
        }
        /* Not forwarding: the request stays owned by the caller, which frees it on this error. */
        return -1021;
    }
    if (getenv("MENU_CP_RELEASE_SERVICE") && id == 0x90040193 && message) {
        int serviced = cp_release_service(id, message);
        if (serviced == 0) return 0;
        if (serviced != -1024) return serviced;   /* unexpected failure: do not forward to a dead SID */
    }

    /* Force-dispatch from the application's own message loop, i.e. after its UI construction stack has
       unwound: calling the dispatcher from inside create_screen re-entered the manager and aborted. */
    if (create_screen_calls >= 1 && !getenv("MENU_FORCE_IN_FACTORY")) force_screen_set("in_message_loop");
    if (create_screen_calls >= 1 && !getenv("MENU_FORCE_IN_FACTORY")) {
        int right_thread = 1;
        if (getenv("MENU_UI_THREAD_ONLY") && ui_thread_id && (unsigned int)syscall(178) != ui_thread_id)
            right_thread = 0;
        if (right_thread) {
            try_menu_init();
            /* Mode activation from the application's own loop, on its UI thread: scanning here is safe
               (see PHASE-STATUS section 19) and this targets the instance the framework itself built. */
            if (getenv("MENU_ACTIVATE_MODE")) try_activate_mode();
            if ((getenv("MENU_CTOR_CENSUS") || getenv("MENU_ACTIVATE_CAPTURED")) && create_screen_calls >= 1)
                ctor_census_and_activate();
            /* The factory window fires before the manager is captured, so the same submission is also
               attempted from the UI thread once the framework really exists. */
            if (getenv("MENU_OPEN_SET") && captured_manager && create_screen_calls >= 1) try_open_set();
        }
    }
    if (create_screen_calls >= 1) try_build_controller();
    /* Top-level dispatch: the subscription registry is a different destination from the
       BB config queue, so this must sit outside the 0x92840747 branch. */
    if (subscription_enabled && id == 0x811006e9 && message) {
        int handled = subscription_service(id, message);
        if (handled >= 0) return handled;
    }
    if (id == 0x9061003c && message && real_msg_size && real_msg_size(message) >= 40) {
        const unsigned int *words = message;
        char text[180];
        snprintf(text, sizeof text, "tid=%ld op=%#x unit=%#x handle=%#x option=%#x source=%#x",
                 syscall(178), words[0] & 65535, words[1], words[2],
                 ((const unsigned short *)message)[11], real_get_source ? real_get_source(message) : 0);
        record("DMM_REQUEST ", text);
        if (dmm_enabled && (words[0] & 65535) >= 0x20 && (words[0] & 65535) <= 0x23) return dmm_send(message);
    }
    if (capid_enabled && (id == 0x9004015e || id == 0x92850750)) return capid_send(id, message);
    if (id == 0x92840747 && message && real_msg_size && real_msg_size(message) >= 8) {
        const unsigned short *head = message;
        char text[160];
        snprintf(text, sizeof text, "tid=%ld frame=%#x property=%#x bytes=%u flags=%#x source=%#x",
                 syscall(178), head[0], head[1], real_msg_size(message), head[3],
                 real_get_source ? real_get_source(message) : 0);
        record("BB_CONFIG_REQUEST ", text);
        if (display_info_enabled && head[0] == 0x200d && head[1] == 0x16a) return display_info_send(message);
        if (display_info_enabled && head[0] == 0x200d && head[1] == 0x14c) return yuv_layout_send(message);
        if (display_info_enabled && head[0] == 0x200d && head[1] == 0x147) return plane_config_send(message);
        if (display_info_enabled && head[0] == 0x200d && (head[1] == 0x161 || head[1] == 0x13d || head[1] == 0x11a)) {
            unsigned int source = real_get_source ? real_get_source(message) : 0;
            if (!source || !real_allocate_msg || !real_set_source || !real_free_msg) return -1021;
            void *reply = 0;
            int result = real_allocate_msg(source, &reply, 12, 1);
            if (result) return result;
            result = head[1] == 0x161 ? prop_161_reply(message, real_msg_size(message), reply)
                     : head[1] == 0x13d ? prop_13d_reply(message, real_msg_size(message), reply)
                                        : prop_11a_reply(message, real_msg_size(message), reply);
            if (!result) { real_set_source(reply, 0x92840747); result = real_send_msg(source, reply); }
            if (result) { real_free_msg(source, reply); return result; }
            record(head[1] == 0x161 ? "PROP_161_SERVICE " : head[1] == 0x13d ? "PROP_13D_SERVICE " : "PROP_11A_SERVICE ",
                   head[1] == 0x161 ? "observed 10-byte 0x161 request accepted; original 0x1161 completion status 0"
                   : head[1] == 0x13d ? "observed 10-byte 0x13d request accepted; original 0x113d completion status 0"
                                      : "observed 14-byte 0x11a request accepted; original 0x111a completion status 0");
            real_free_msg(0x92840747, message);
            return 0;
        }
        if (hdmi_format_enabled && head[0] == 0x200d && head[1] == 0x32f) return hdmi_parameter_send(id, message);
    }
    if (id == 0x909c015b && message && real_msg_size && real_msg_size(message) >= 12) {
        const unsigned short *head = message;
        char text[160];
        snprintf(text, sizeof text, "tid=%ld frame=%#x code=%#x bytes=%u flags=%#x mode=%u source=%#x",
                 syscall(178), head[0], head[1], real_msg_size(message), head[3],
                 ((const unsigned char *)message)[8], real_get_source ? real_get_source(message) : 0);
        record("PIN_REQUEST ", text);
        if (display_info_enabled && head[0] == 0 && head[1] == 0x101) return pin_disconnect_send(message);
    }
    if (id == 0x909a015a && message && real_msg_size && real_msg_size(message) >= 12) {
        const unsigned short *head = message;
        char text[160];
        snprintf(text, sizeof text, "tid=%ld frame=%#x command=%#x bytes=%u flags=%#x value=%#x source=%#x",
                 syscall(178), head[0], head[1], real_msg_size(message), head[3],
                 ((const unsigned int *)message)[2], real_get_source ? real_get_source(message) : 0);
        record("HDMI_PHOTO_REQUEST ", text);
        if (hdmi_photo_enabled && head[0] == 0x2500 && head[1] == 0x102) return hdmi_parameter_send(id, message);
        if (display_info_enabled && head[0] == 0x2500 && head[1] == 0x109) {
            unsigned int source = real_get_source ? real_get_source(message) : 0;
            if (!source || !real_allocate_msg || !real_set_source || !real_free_msg) return -1021;
            void *reply = 0;
            int result = real_allocate_msg(source, &reply, 12, 1);
            if (result) return result;
            result = pin_hdmi_reply(message, real_msg_size(message), reply);
            if (!result) { real_set_source(reply, id); result = real_send_msg(source, reply); }
            if (result) { real_free_msg(source, reply); return result; }
            record("PIN_HDMI_SERVICE ", "observed 0x2500/0x109 request accepted; original 0x8109 completion status 0");
            real_free_msg(id, message);
            return 0;
        }
    }
    if (id == 0x00930101 && message && real_msg_size && real_msg_size(message) >= 16) {
        const unsigned short *head = message;
        const unsigned long long *addresses = message;
        char text[192];
        snprintf(text, sizeof text, "tid=%ld cmd=%#x count=%u reply=%#llx caller=%p",
                 syscall(178), head[0], head[2], addresses[1], __builtin_return_address(0));
        record("SA_ADDRESS_REQUEST ", text);
        if (head[0] == 0xb850 && head[2] <= 8 && real_msg_size(message) >= 16U + 8U * head[2])
            for (unsigned int i = 0; i < head[2]; ++i) {
                snprintf(text, sizeof text, "index=%u address=%#llx", i, addresses[2 + i]);
                record("SA_ADDRESS_INPUT ", text);
            }
        int result = sa_address_enabled && head[0] == 0xb850 ? sa_address_send(message) : real_send_msg(id, message);
        snprintf(text, sizeof text, "tid=%ld result=%d", syscall(178), result);
        record("SA_ADDRESS_SEND_RETURN ", text);
        return result;
    }
    if (id == 0x912503d0 && message && real_msg_size && real_msg_size(message) == 20 &&
        *(const unsigned int *)message == 0) {
        /* libInfraGetVersion.so+0xe08 lens getter: 20-byte {0} request, dynamic-id reply
           queue in msg source, 1s wait. Reply validated at +0xeec: [+0]==0 status,
           [+4] type<=4 with (1<<type)&0x1d, version at +8/+0xa/+0xe. Type 0 = generic. */
        unsigned int source = real_get_source ? real_get_source(message) : 0;
        char text[160];
        snprintf(text, sizeof text, "tid=%ld source=%#x caller=%p",
                 syscall(178), source, __builtin_return_address(0));
        record("LENS_VERSION_REQUEST ", text);
        if (source && real_allocate_msg && real_set_source && real_free_msg && real_send_msg) {
            void *reply = 0;
            int result = real_allocate_msg(source, &reply, 20, 1);
            if (!result) {
                for (int i = 0; i < 20; ++i) ((unsigned char *)reply)[i] = 0;
                /* status 0 (success), lens type 0 (generic, in 0x1d mask), version 0 */
                real_set_source(reply, 0x912503d0);
                result = real_send_msg(source, reply);
                if (result) real_free_msg(source, reply);
            }
            snprintf(text, sizeof text, "tid=%ld reply=%d", syscall(178), result);
            record("LENS_VERSION_SERVICE ", result ? "reply delivery failed" :
                    "20-byte lens reply delivered: status 0, type 0, version 0");
            unsigned int from = lens_pool_lookup(message);
            real_free_msg(from ? from : 0x912503d0, message);
            return result;
        }
    }
    if (id == 0x912503d0 && getenv("QEMU_NO_CP_UPDATER")) {
        record("TRANSPORT_UNAVAILABLE ", "CP updater 0x912503d0; request not consumed");
        return -1021;
    }
    if (id == 0x9004015e && message) {
        const unsigned int *words = message; /* capidtbl requests are 24 bytes */
        char text[192];
        snprintf(text, sizeof text, "tid=%ld dest=%#x words=%#x,%#x,%#x,%#x,%#x,%#x caller=%p",
                 syscall(178), id, words[0], words[1], words[2], words[3], words[4], words[5],
                 __builtin_return_address(0));
        record("CAPID_SEND ", text);
        int result = real_send_msg(id, message);
        snprintf(text, sizeof text, "tid=%ld dest=%#x result=%d", syscall(178), id, result);
        record("CAPID_SEND_RETURN ", text);
        return result;
    }
    if (bb_ready_inject_enabled && bb_ready_pending && bb_key_seen && id != 0x811006e9) {
        bb_ready_pending = 0;
        record("BB_OUTPUT_READY ", "deferred fulfilment released after the key injection");
        bb_output_ready_event();
    }
    if (message && real_msg_size) {
        unsigned int size = real_msg_size(message);
        unsigned int code = size >= 4 ? ((const unsigned short *)message)[1] : 0;
        /* Known periodic noise: heartbeat/log-drain channels, plus the 0x20f keepalive on
           the model event queue (real key events on 0x5503e0 use code 0x1400 and stay visible). */
        if (id == 0x8f013a || id == 0x8f0139 || id == 0x92b4086f || (id == 0x5503e0 && code == 0x20f))
            return real_send_msg(id, message);
        char text[180];
        snprintf(text, sizeof text, "tid=%ld dest=%#x code=%#x bytes=%u source=%#x caller=%p",
                 syscall(178), id, code, size,
                 real_get_source ? real_get_source(message) : 0, __builtin_return_address(0));
        record("SND_MSG_OTHER ", text);
        /* Payload capture for unmapped CP-facing destinations (event registration probes). */
        if (id == 0x811006e9 || id == 0x80920871 || id == 0x80920572 || id == 0x807a0020 ||
            id == 0x7a804c || id == 0x7ae098 || id == 0x7ae118 || id == 0x5503e0) {
            const unsigned char *bytes = message;
            unsigned int shown = size < 24 ? size : 24;
            char hex[180];
            int at = 0;
            for (unsigned int i = 0; i < shown && at < 150; ++i) at += snprintf(hex + at, sizeof hex - at, "%02x", bytes[i]);
            snprintf(text, sizeof text, "tid=%ld dest=%#x code=%#x payload=%s", syscall(178), id, code, hex);
            record("SND_MSG_PAYLOAD ", text);
        }
    }
    unsigned int observed = record_osd_transport("OSD_TRANSPORT_SEND ", id, message);
    if(id==GUI_MODEL_QUEUE && file_media_flush_pending_fn) {
        file_media_flush_pending_fn();start_sd_ack_retry_worker();
    }
    int result;
    if(!gui_model_service_send(id,message,&result))result=real_send_msg(id,message);
    if (observed) {
        char text[96];
        snprintf(text, sizeof text, "call=%u endpoint=%#x result=%d", observed, id, result);
        record("OSD_TRANSPORT_SEND_RETURN ", text);
    }
    return result;
}
int kikilog_set_notify_cb(unsigned int id) {
    if (!real_kikilog_notify) __builtin_trap();
    int result = real_kikilog_notify(id);
    char text[64];
    snprintf(text, sizeof text, "id=%#x result=%d", id, result);
    record("KIKILOG_NOTIFY ", text);
    return result;
}
static void capture_gpe(unsigned int operation, int gpe, int core, const void *parameters, unsigned int bytes) {
    if (!parameters) return;
    unsigned int index = __atomic_fetch_add(&gpe_capture_count, 1, __ATOMIC_RELAXED);
    if (index >= 256) {
        if (index == 256) record("GPE_CAPTURE_LIMIT ", "first 256 requests; later requests still executed");
        return;
    }
    unsigned int buffer[40] = {operation, (unsigned int)gpe, (unsigned int)core, bytes};
    unsigned char *target = (unsigned char *)(buffer + 4);
    const unsigned char *source = parameters;
    for (unsigned int i = 0; i < bytes; ++i) target[i] = source[i];
    int fd = open("/tmp/gpe-requests.bin", 0x441, 0644);
    if (fd >= 0) { write(fd, buffer, bytes + 16); close(fd); }
    char text[64];
    snprintf(text, sizeof text, "op=%u gpe=%d core=%d bytes=%u", operation, gpe, core, bytes);
    record("GPE_REQUEST ", text);
    if (index < 256) {
        char hex[289];
        const char digits[] = "0123456789abcdef";
        for (unsigned int i = 0; i < bytes; ++i) { hex[i * 2] = digits[source[i] >> 4]; hex[i * 2 + 1] = digits[source[i] & 15]; }
        hex[bytes * 2] = 0;
        record("GPE_PARAMETERS ", hex);
    }
}
static int (*real_osd_set_entry)(void *, const void *);
static unsigned long headless_libobj;
static struct hosd_native headless_native;
static unsigned int headless_stop, headless_started, headless_thread_live;
static pthread_t headless_thread;
static int (*headless_join)(pthread_t, void **);
static int headless_try_raster(void) { return pthread_mutex_trylock(headless_raster_mutex); }
static int headless_unlock_raster(void) { return pthread_mutex_unlock(headless_raster_mutex); }
static int headless_frame(struct hosd_frame *frame, unsigned char *pixels) {
    return hosd_capture_frame(headless_libobj, &headless_native, frame, pixels);
}
/* The entry's first four verified instructions are PC-independent. */
static void *headless_fin_continue __attribute__((used));
__asm__(
".text\n"
".align 2\n"
".globl headless_fin_original\n"
".type headless_fin_original, %function\n"
"headless_fin_original:\n"
"stp x29,x30,[sp,#-48]!\n"
"mov w0,#0x4000\n"
"mov x29,sp\n"
"stp x19,x20,[sp,#16]\n"
"adrp x16,headless_fin_continue\n"
"ldr x16,[x16,#:lo12:headless_fin_continue]\n"
"br x16\n");
extern unsigned long headless_fin_original(void);
static unsigned long (*headless_finish)(void) = headless_fin_original;
static unsigned long observe_grm_fin(void) {
    /* Serialize both startup and actual teardown; no FB access can outlive join. */
    if (pthread_mutex_lock(headless_lifecycle_mutex)) return (unsigned long)-1;
    __atomic_store_n(&headless_stop, 1, __ATOMIC_RELEASE);
    if (headless_thread_live) {
        if (!headless_join || headless_join(headless_thread, 0)) {
            record("OSD_HEADLESS_FAILED ", "join failed; native grm_fin refused");
            pthread_mutex_unlock(headless_lifecycle_mutex);
            return (unsigned long)-1;
        }
        headless_thread_live = 0;
    }
    record("OSD_HEADLESS_JOINED ", "receiver exited before native grm_fin");
    unsigned long result = headless_finish();
    pthread_mutex_unlock(headless_lifecycle_mutex);
    return result;
}
static int install_headless_fin(unsigned long base) {
    unsigned int *entry = (unsigned int *)(base + 0x104404);
    if (entry[0] != 0xa9bd7bfd || entry[1] != 0x52880000 || entry[2] != 0x910003fd || entry[3] != 0xa90153f3)
        return -1;
    void *page = (void *)((unsigned long)entry & ~4095UL);
    if (mprotect(page, 4096, 7)) return -1;
    headless_fin_continue = (void *)(base + 0x104414);
    entry[0] = 0x58000050; entry[1] = 0xd61f0200;
    *(unsigned long *)(entry + 2) = (unsigned long)observe_grm_fin;
    clear_cache_range(entry, 16);
    return mprotect(page, 4096, 5);
}
static void start_headless_osd(void) {
    static struct hosd_ops ops;
    static struct gui_model_store_ops model_ops;
    if (!headless_osd_enabled || !real_draw_framebuffer || !real_rcv_msg_tmo ||
        !real_msg_size || !real_get_source || !real_free_msg || !real_allocate_msg ||
        !real_set_source || !real_send_msg) return;
    if (pthread_mutex_lock(headless_lifecycle_mutex)) return;
    if (headless_started || headless_stop) { pthread_mutex_unlock(headless_lifecycle_mutex); return; }
    headless_started = 1;
    if (!software_rgba4444) { record("OSD_HEADLESS_FAILED ", "requires explicit software GPE RGBA4444 mode"); goto done; }
    int (*stat_queue)(unsigned int, unsigned int *) = real_dlsym((void *)-1, "osal_stat_msgq");
    if (hosd_claim("/tmp/headless-osd.claim", "/proc/modules", stat_queue, record)) {
        record("OSD_HEADLESS_FAILED ", "exclusive startup checks failed; receiver not started");
        goto done;
    }
    headless_libobj = (unsigned long)real_draw_framebuffer - 0x174dbcUL;
    ops = (struct hosd_ops){real_rcv_msg_tmo, real_msg_size, real_get_source, real_free_msg,
                           real_allocate_msg, real_set_source, real_send_msg, headless_frame, record, &headless_stop};
    unsigned long b = headless_libobj;
    headless_native = (struct hosd_native){
        real_dlsym((void *)-1, "osal_wai_sem_tmo"), real_dlsym((void *)-1, "osal_sig_sem"),
        (void *)(b + 0x100d28), (void *)(b + 0x100cd8), (void *)(b + 0x100cec), (void *)(b + 0x100d3c),
        (void *)(b + 0x100cb0), (void *)(b + 0x100eac), (void *)(b + 0x100c3c), headless_try_raster, headless_unlock_raster, record};
    /* Resolve before creating the worker: it must never enter the loader lock. */
    int (*create)(pthread_t *, const void *, void *(*)(void *), void *) = real_dlsym((void *)-1, "pthread_create");
    headless_join = real_dlsym((void *)-1, "pthread_join");
    if (!headless_native.wait_sem || !headless_native.signal_sem || !create || !headless_join || install_headless_fin(b)) {
        record("OSD_HEADLESS_FAILED ", "native lease symbols/actual grm_fin entry hook unavailable"); goto done;
    }
    if (create(&headless_thread, 0, hosd_worker, &ops))
        record("OSD_HEADLESS_FAILED ", "pthread creation unavailable");
    else headless_thread_live = 1;
    if(headless_thread_live && getenv("MENU_GUI_MODELS") &&
       same_name(getenv("MENU_GUI_MODELS"),"virtual-inline-v1")) {
        unsigned int state[4]={0};
        int status=stat_queue(GUI_MODEL_QUEUE,state);
        char text[180];
        snprintf(text,sizeof text,"queue=%#x status=%d pending=%u async=%u broadcast=%u sync=%u",
                 GUI_MODEL_QUEUE,status,state[0],state[1],state[2],state[3]);
        record("GUI_MODEL_STARTUP_QUEUE ",text);
        int claim=-1;
        if(!status && !state[1] && !state[2] && !state[3])claim=open("/tmp/gui-model.claim",0x80c1,0600);
        if(claim<0 || close(claim))record("GUI_MODEL_FAILED ","exclusive model queue startup check failed");
        else {
            model_ops=(struct gui_model_store_ops){real_rcv_msg_tmo,real_msg_size,real_free_msg,
                                                  hosd_persist,record,&headless_stop};
            if(gui_model_service_start(&model_ops))record("GUI_MODEL_FAILED ","model service startup failed");
        }
    }
done:
    pthread_mutex_unlock(headless_lifecycle_mutex);
}
static unsigned int notify_draw_count, draw_framebuffer_count;
static void record_frame_call(const char *prefix, unsigned int count, void *object, unsigned long result) {
    if (count > 8) return;
    char text[192];
    snprintf(text, sizeof text, "call=%u tid=%ld this=%p result=%#lx update_state=%u draw_state=%u",
             count, syscall(178), object, result, *(unsigned int *)(appfw_base + 0x5c1efe4),
             *(unsigned int *)(appfw_base + 0x5c1efe0));
    record(prefix, text);
}
static unsigned long observe_notify_draw(void *object) {
    unsigned int count = __atomic_add_fetch(&notify_draw_count, 1, __ATOMIC_RELAXED);
    record_frame_call("FRAME_NOTIFY_ENTER ", count, object, 0);
    unsigned long result = real_notify_draw(object);
    record_frame_call("FRAME_NOTIFY_RETURN ", count, object, result);
    /* Native-window (ramfb) runs never reach drawFramebuffer, so the verified UI-thread
       injection point is also pumped from the real UX draw callback. */
    return result;
}
static void record_frame_buffers(unsigned int count) {
    if (count > 8) return;
    unsigned long base = (unsigned long)real_draw_framebuffer - 0x174dbcUL;
    unsigned long manager = *(unsigned long *)(base + 0x2ebde0UL);
    if (!manager) return;
    unsigned long fb = *(unsigned long *)(manager + 8);
    if (!fb) return;
    unsigned long on = *(unsigned long *)(fb + 0x68), off = *(unsigned long *)(fb + 0x70);
    if (!((on == fb + 0x20 && off == fb + 0x40) || (on == fb + 0x40 && off == fb + 0x20))) return;
    /* FrameBuffer::update copies desired width/height/format (+0x14) to current fields (+8). */
    char text[224];
    snprintf(text, sizeof text, "call=%u width=%u height=%u bmp_format=%u on=%#lx off=%#lx on_bitmap=%#lx off_bitmap=%#lx",
             count, *(unsigned short *)(fb + 8), *(unsigned short *)(fb + 10),
             *(unsigned int *)(fb + 12), *(unsigned long *)(on + 0x18),
             *(unsigned long *)(off + 0x18), *(unsigned long *)on, *(unsigned long *)off);
    record("FRAME_BUFFERS ", text);
}
static void record_frame_sync(unsigned int count) {
    if (count > 8) return;
    unsigned long base = (unsigned long)real_draw_framebuffer - 0x174dbcUL;
    unsigned long manager = *(unsigned long *)(base + 0x2ebde0UL);
    if (!manager) return;
    unsigned long fb = *(unsigned long *)(manager + 8);
    unsigned long ready = *(unsigned long *)(manager + 0x10), cb = *(unsigned long *)(manager + 0x48);
    unsigned long external = *(unsigned long *)(manager + 0x20);
    unsigned long gate = external ? *(unsigned long *)(external + 0x48) : 0;
    char text[320];
    snprintf(text, sizeof text, "call=%u manager=%#lx ready_obj=%#lx ready_id=%#x callback_obj=%#lx callback_id=%#x external=%#lx external_gate=%#lx external_id=%#x",
             count, manager, ready, ready ? *(unsigned int *)(ready + 8) : 0,
             cb, cb ? *(unsigned int *)(cb + 8) : 0, external, gate, gate ? *(unsigned int *)(gate + 8) : 0);
    record("FRAME_SYNC_OBJECTS ", text);
    if (fb) {
        snprintf(text, sizeof text, "call=%u framebuffer=%#lx fb80_id=%#x fb90_id=%#x mgr60=%u fb78=%u",
                 count, fb, *(unsigned int *)(fb + 0x88), *(unsigned int *)(fb + 0x98),
                 *(unsigned char *)(manager + 0x60), *(unsigned char *)(fb + 0x78));
        record("FRAME_SYNC_FLAGS ", text);
    }
    unsigned long native = *(unsigned long *)(base + 0x2ec900UL);
    if (native) {
        snprintf(text, sizeof text, "call=%u libobj=%#lx table=%#lx native18=%#lx native78=%#lx nativec8=%#lx",
                 count, base, native, *(unsigned long *)(native + 0x18),
                 *(unsigned long *)(native + 0x78), *(unsigned long *)(native + 0xc8));
        record("FRAME_NATIVE_TABLE ", text);
    }
}
static void try_apply_menu_after_frame(void) {
    /* MENU_APPLY_SWEEP=<hex,hex,...> tries several screen ids in one run: each frame re-enters while
       current is back at 0x308 (the nine-parameter apply restores to 0x4b7/0x308), so one run can
       answer "which id is the shooting screen" instead of one id per six-minute boot. */
    static unsigned int attempted;
    static const char *sweep_cursor;
    if (!getenv("MENU_APPLY_MENU") || !captured_manager || !create_screen_returned || create_screen_active) return;
    const char *sweep = getenv("MENU_APPLY_SWEEP");
    if (!sweep || !*sweep) { if (attempted) return; }
    else if (!sweep_cursor) sweep_cursor = sweep;
    if ((unsigned int)syscall(178) != ui_thread_id) return;
    attempted = 1;
    unsigned long manager = captured_manager;
    unsigned long controller = *(unsigned long *)(manager + 0x330);
    unsigned int current = *(unsigned int *)(manager + 0x348);
    unsigned int selector = *(unsigned int *)(appfw_base + 0x7ed79a8);
    unsigned int mirror = *(unsigned int *)(appfw_base + 0x83d9d00);
    unsigned long p30 = *(unsigned long *)(manager + 0x30), p10 = *(unsigned long *)(manager + 0x10);
    char text[224];
    /* Sweeping: accept any current screen and use it as `from`, otherwise a failed transition would
       stall the sweep after the first id (measured: only one MENU_APPLY_ENTER for a five-id list). */
    /* Measured: the second sweep step was SKIPPED although p30/p10/selector were all normal, i.e. the
       exact controller-identity checks below no longer held after the first apply (the manager swapped
       controller state). For plain id enumeration those checks carry no value, so relax them while a
       sweep is running and keep them strict for the single-target case. */
    int sweeping = sweep_cursor != 0;
    if (*(unsigned long *)manager != appfw_base + 0x5b0c480UL ||
        (!sweeping && current != 0x308) ||
        (!sweeping && (controller != appfw_base + 0x7603190UL ||
                       *(unsigned long *)controller != appfw_base + 0x5b0e298UL)) ||
        !p30 || !p10 ||
        (!sweeping && selector > 2)) {
        snprintf(text, sizeof text, "current=%#x controller=%#lx p30=%#lx p10=%#lx selector=%u mirror=%u",
                 current, controller, p30, p10, selector, mirror);
        record("MENU_APPLY_SKIPPED ", text);
        return;
    }
    snprintf(text, sizeof text, "tid=%u manager=%#lx current=%#x selector=%u mirror=%u boot_controller=%#lx",
             ui_thread_id, manager, current, selector, mirror, controller);
    if (!sweep) attempted = 1;
    record("MENU_APPLY_ENTER ", text);
    /* Target override for the shooting screen. The controller ids are consecutive
       (0x346 = menu, see BOOT-TROUBLESHOOTING), and MENU_ACTIVATE_MODE showed that the
       shooting controller is never activated by the firmware itself, so the only way to
       reach that screen is to apply to its id. MENU_APPLY_TARGET=<hex> keeps the proven
       menu target as the default and lets the candidate be measured instead of guessed. */
    unsigned int from = sweep_cursor ? current : 0x4b7, to = 0x346, restore = 0x4b7;
    const char *target_spec = getenv("MENU_APPLY_TARGET");
    if (sweep_cursor) {
        while (*sweep_cursor == ',' || *sweep_cursor == ' ') ++sweep_cursor;
        if (!*sweep_cursor) return;
        static char one[16];
        unsigned int n = 0;
        while (sweep_cursor[n] && sweep_cursor[n] != ',' && n < sizeof one - 1) { one[n] = sweep_cursor[n]; ++n; }
        one[n] = 0;
        sweep_cursor += n;
        target_spec = one;
    }
    if (target_spec && target_spec[0]) {
        unsigned int value = 0, digits = 0;
        const char *q = target_spec;
        if (q[0] == '0' && (q[1] == 'x' || q[1] == 'X')) q += 2;
        while (digits < 8) {
            char c = *q; unsigned int nib;
            if (c >= '0' && c <= '9') nib = (unsigned int)(c - '0');
            else if (c >= 'a' && c <= 'f') nib = (unsigned int)(c - 'a' + 10);
            else if (c >= 'A' && c <= 'F') nib = (unsigned int)(c - 'A' + 10);
            else break;
            value = (value << 4) | nib; ++q; ++digits;
        }
        if (digits) to = value;
    }
    /* Same nine-argument apply ABI as firmware boot; the final zero is a stack argument. */
    typedef void (*apply_t)(void *, const unsigned int *, const unsigned int *, const unsigned int *,
                            unsigned int, unsigned int, unsigned int, unsigned int, unsigned int);
    ((apply_t)(appfw_base + 0x1e78870))((void *)manager, &from, &to, &restore, 0, 1, 0, 0, 0);
    snprintf(text, sizeof text, "current=%#x controller=%#lx", *(unsigned int *)(manager + 0x348),
             *(unsigned long *)(manager + 0x330));
    record("MENU_APPLY_RETURN ", text);
}
static unsigned long observe_draw_framebuffer(void *object) {
    unsigned int count = __atomic_add_fetch(&draw_framebuffer_count, 1, __ATOMIC_RELAXED);
    record_frame_call("FRAME_DRAW_ENTER ", count, object, 0);
    record_frame_sync(count);
    unsigned long result = real_draw_framebuffer(object);
    if(getenv("MENU_DMM_UNIT_CONFIG") && (unsigned int)syscall(178)==ui_thread_id)
        capture_dialog_resource();
    record_frame_call("FRAME_DRAW_RETURN ", count, object, result);
    record_frame_buffers(count);
    log_option_install_ready("frame");
    install_honest_route_hook();
    install_pipeline_endpoint();
    try_apply_menu_after_frame();
    try_inject_key();

    dump_manager_slots();
    if (count == 9) record("FRAME_LOG_LIMIT ", "first 8 frame calls logged; all later calls forwarded");
    return result;
}
/* sequence_boot::run_i asks udate (0x0090013d cmd 0x30) for the boot factor and 0x00910042 for
   time through osal_snd_sync_direct. appFw's own PLT stub at appFw+0x165dea0 loads the GOT slot at
   VA 0x5bc1758; storing this wrapper there observes both without touching the library file and
   without running the lazy resolver. Read-only: the wrapper always forwards and never rewrites a
   reply, so this cannot manufacture a successful boot. */
/* libInfraOptionInstall keeps its readiness flag in a static u32 at library VA 0x44084; while it is
   0 the 0x01ae852d provider answers "not ready" (business status 9) and sequence_boot's license
   query keeps failing. Read the flag itself so that claim is observed, not inferred. */
struct dl_phdr_info_local { unsigned long dlpi_addr; const char *dlpi_name; const void *dlpi_phdr; unsigned short dlpi_phnum; };
extern int dl_iterate_phdr(int (*)(struct dl_phdr_info_local *, unsigned long, void *), void *);
struct base_lookup { const char *needle; unsigned long base; };
static int base_lookup_cb(struct dl_phdr_info_local *info, unsigned long size, void *data) {
    struct base_lookup *lookup = (struct base_lookup *)data;
    (void)size;
    if (info->dlpi_name && __builtin_strstr(info->dlpi_name, lookup->needle)) { lookup->base = info->dlpi_addr; return 1; }
    return 0;
}
static unsigned long find_library_base(const char *needle) {
    struct base_lookup lookup = { needle, 0 };
    dl_iterate_phdr(base_lookup_cb, &lookup);
    return lookup.base;
}
/* libInfraOptionInstall's readiness (0x44084) can only become 1 when its worker (entry 0xbfb8)
   consumes an OSAL message with cmd 6 that its own init posts through 0xbd14. Queue ids match, so
   the open question is whether the worker runs and whether the send happens after it starts.
   Both probes replay the overwritten instructions verbatim and verify the expected bytes first. */
static unsigned int opt_worker_entered, opt_send_entered;
static unsigned int opt_send_queue, opt_send_cmd;
void capture_option_worker(unsigned long arg) {
    if (opt_worker_entered++ < 4) {
        char text[128];
        snprintf(text, sizeof text, "n=%u arg=%#lx tid=%ld", opt_worker_entered, arg, syscall(178));
        record("OPT_WORKER_ENTER ", text);
    }
}
void capture_option_send(unsigned long queue, unsigned long body) {
    if (opt_send_entered++ < 6) {
        opt_send_queue = (unsigned int)queue;
        opt_send_cmd = (body > 0x100000UL && body < 0x800000000000UL) ? *(unsigned int *)body : 0xffffffffU;
        char text[128];
        snprintf(text, sizeof text, "n=%u queue=%#lx cmd=%u tid=%ld", opt_send_entered, queue, opt_send_cmd, syscall(178));
        record("OPT_SEND_ENTER ", text);
    }
}
__asm__(
".text\n"
".globl opt_worker_trampoline\n"
".type opt_worker_trampoline, %function\n"
"opt_worker_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_option_worker\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9b27bfd\n"          /* stp x29,x30,[sp,#-224]! */
"    .inst 0xd00000c1\n"          /* adrp x1,0x25000 */
"    .inst 0x911b3c21\n"          /* add x1,x1,#0x6cf */
"    .inst 0x910003fd\n"          /* mov x29,sp */
"    adrp x16, opt_worker_continue\n"
"    ldr x16, [x16, #:lo12:opt_worker_continue]\n"
"    br x16\n"
".globl opt_send_trampoline\n"
".type opt_send_trampoline, %function\n"
"opt_send_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_option_send\n"
PROBE_RESTORE_ARGS
"    .inst 0xa9bc7bfd\n"          /* stp x29,x30,[sp,#-64]! */
"    .inst 0x52800023\n"          /* mov w3,#1 */
"    .inst 0x52802502\n"          /* mov w2,#0x128 */
"    .inst 0x910003fd\n"          /* mov x29,sp */
"    adrp x16, opt_send_continue\n"
"    ldr x16, [x16, #:lo12:opt_send_continue]\n"
"    br x16\n"
);
extern void opt_worker_trampoline(void);
extern void opt_send_trampoline(void);
static void *opt_worker_continue, *opt_send_continue;
static void install_option_probes(void) {
    unsigned long base = find_library_base("libInfraOptionInstall.so");
    if (!base) { record("OPT_PROBE_FAILED ", "libInfraOptionInstall.so not mapped"); return; }
    opt_worker_continue = (void *)(base + 0xbfb8UL + 16);
    opt_send_continue = (void *)(base + 0xbd14UL + 16);
    arm_entry_probe(base + 0xbfb8UL, (const unsigned int[4]){0xa9b27bfd, 0xd00000c1, 0x911b3c21, 0x910003fd},
                    (void *)opt_worker_trampoline, opt_worker_continue, "option worker 0xbfb8");
    arm_entry_probe(base + 0xbd14UL, (const unsigned int[4]){0xa9bc7bfd, 0x52800023, 0x52802502, 0x910003fd},
                    (void *)opt_send_trampoline, opt_send_continue, "option send 0xbd14");
}
static unsigned int option_ready_logged;
static void log_option_install_ready(const char *when) {
    if (option_ready_logged++ >= 4) return;
    unsigned long base = find_library_base("libInfraOptionInstall.so");
    char text[160];
    if (!base) { snprintf(text, sizeof text, "%s libInfraOptionInstall.so not mapped", when); record("OPT_READY ", text); return; }
    unsigned int ready = *(unsigned int *)(base + 0x44084UL);
    unsigned int arg_queue = *(unsigned int *)(base + 0x44048UL);   /* worker thread arg = receive queue */
    unsigned int snd_queue = *(unsigned int *)(base + 0x44058UL);   /* queue used by the cmd-6 send */
    unsigned int arg_plus4 = *(unsigned int *)(base + 0x4404cUL);
    unsigned int w44060 = *(unsigned int *)(base + 0x44060UL);
    snprintf(text, sizeof text, "%s base=0x%lx ready@0x44084=%u argq@0x44048=%#x argq4=0x%x sndq@0x44058=%#x w44060=%#x tid=%ld",
             when, base, ready, arg_queue, arg_plus4, snd_queue, w44060, syscall(178));
    record("OPT_READY ", text);
}
extern long syscall(long, ...);
static int observe_send_sync_direct(unsigned int id, void *message) {
    if (!real_send_sync_direct) real_send_sync_direct = real_dlsym((void *)-1, "osal_snd_sync_direct");
    if (!real_send_sync_direct) return -1;
    unsigned int size = (real_msg_size && message) ? real_msg_size(message) : 0;
    char text[320];
    const unsigned int *w = (const unsigned int *)message;
    /* osal_snd_sync_direct carries a caller-built struct, not an OSAL message, so osal_msg_size()
       reports 0 for it. Read a fixed 32-byte window instead (every observed call site passes at
       least that) so the request and the filled-in reply are both visible. */
    unsigned int window = (size > 48) ? 48 : (size ? size : 48);
    snprintf(text, sizeof text, "tid=%ld ENTER dest=%#x bytes=%u caller=%p w=%08x,%08x,%08x,%08x,%08x,%08x",
             syscall(178), id, size, (unsigned long)((unsigned long)__builtin_return_address(0) - appfw_base),
             (message && window >= 4) ? w[0] : 0, (message && window >= 8) ? w[1] : 0,
             (message && window >= 12) ? w[2] : 0, (message && window >= 16) ? w[3] : 0,
             (message && window >= 20) ? w[4] : 0, (message && window >= 24) ? w[5] : 0);
    record("SYNC_DIRECT ", text);
    int result = real_send_sync_direct(id, message);
    if (id == 0x01ae852dU) log_option_install_ready("after-01ae852d");
    snprintf(text, sizeof text, "tid=%ld RETURN dest=%#x result=%d w=%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x | %08x,%08x,%08x,%08x",
             syscall(178), id, result,
             (message && window >= 4) ? w[0] : 0, (message && window >= 8) ? w[1] : 0,
             (message && window >= 12) ? w[2] : 0, (message && window >= 16) ? w[3] : 0,
             (message && window >= 20) ? w[4] : 0, (message && window >= 24) ? w[5] : 0,
             (message && window >= 28) ? w[6] : 0, (message && window >= 32) ? w[7] : 0,
             (message && window >= 36) ? w[8] : 0, (message && window >= 40) ? w[9] : 0,
             (message && window >= 44) ? w[10] : 0, (message && window >= 48) ? w[11] : 0);
    record("SYNC_DIRECT ", text);
    return result;
}
/* osal_snd_sync_msg is the transport behind the 0x01ae852d license query and behind most of
   appFw's boot-time requests. A failing send there returns -1020 (0xfffffc04) and the caller
   treats it as fatal, so the SID of each failure has to be observed rather than guessed.
   appFw's PLT stub at appFw+0x165fc40 loads the GOT slot at VA 0x5bc2628. Read-only wrapper: it
   forwards every call and never rewrites a reply. */
static long (*real_send_sync_msg)(unsigned int, void *);
static unsigned int sync_msg_seen;
static long observe_send_sync_msg(unsigned int id, void *message) {
    if (!real_send_sync_msg) real_send_sync_msg = real_dlsym((void *)-1, "osal_snd_sync_msg");
    if (!real_send_sync_msg) return -1;
    if (honest_no_receiver(id)) {
        static unsigned int honest_sync;
        if (honest_sync++ < 16) {
            char text[128];
            snprintf(text, sizeof text, "n=%u tid=%ld dest=%#x -> -1021 (nothing registered)",
                     honest_sync, syscall(178), id);
            record("HONEST_ROUTE_SYNC ", text);
        }
        return -1021;
    }
    long result = real_send_sync_msg(id, message);
    unsigned int failures = (result != 0) ? 1u : 0u;
    static unsigned int failed;
    if (failures) ++failed;
    if (sync_msg_seen < 200 && (failures || getenv("MENU_SYNC_MSG_ALL"))) {
        unsigned int size = (real_msg_size && message) ? real_msg_size(message) : 0;
        const unsigned int *words = (const unsigned int *)message;
        char text[240];
        /* __osal_snd_sync_msg (libosal_uipc 0x61ec) keeps only the low 15 bits of w0 as the
           routing id (`ands w5,w0,#0x7fff`), so the raw argument is a composite value and printing
           it unmasked looks like a pointer. Report both. */
        snprintf(text, sizeof text,
                 "n=%u tid=%ld raw=%#x id=%#x result=%ld fails=%u bytes=%u caller=appFw+%#lx w=%08x,%08x,%08x,%08x,%08x,%08x",
                 ++sync_msg_seen, syscall(178), id, id & 0x7fff, result, failed, size,
                 (unsigned long)((unsigned long)__builtin_return_address(0) - appfw_base),
                 (message && size >= 4) ? words[0] : 0, (message && size >= 8) ? words[1] : 0,
                 (message && size >= 12) ? words[2] : 0, (message && size >= 16) ? words[3] : 0,
                 (message && size >= 20) ? words[4] : 0, (message && size >= 24) ? words[5] : 0);
        record("SYNC_MSG ", text);
    }
    return result;
}
static void install_sync_msg_probe(unsigned long base) {
    real_send_sync_msg = real_dlsym((void *)-1, "osal_snd_sync_msg");
    if (!real_send_sync_msg) { record("SYNC_MSG_ARM_FAILED ", "no osal_snd_sync_msg"); return; }
    unsigned long page = base + 0x5bc2000UL;
    if (mprotect((void *)page, 4096, 3) != 0) { record("SYNC_MSG_ARM_FAILED ", "GOT page"); return; }
    *(unsigned long *)(base + 0x5bc2628UL) = (unsigned long)observe_send_sync_msg;
    record("SYNC_MSG_ARMED ", "appFw osal_snd_sync_msg GOT slot 0x5bc2628");
}
/* Every async send is interesting here: the group-0 sequence worker blocks on a future whose reply
   would arrive through one of them. appFw's osal_snd_msg@plt loads the GOT slot at VA 0x5bc1d70. */
static unsigned int async_send_seen;
static int observe_send_async(unsigned int id, void *message) {
    if (!real_send_msg) real_send_msg = real_dlsym((void *)-1, "osal_snd_msg");
    if (!real_send_msg) return -1;
    if (id != 0x008f013a && async_send_seen < 400) {
        unsigned int size = (real_msg_size && message) ? real_msg_size(message) : 0;
        const unsigned int *words = (const unsigned int *)message;
        char text[224];
        snprintf(text, sizeof text, "n=%u tid=%ld dest=%#x bytes=%u caller=appFw+%#lx w=%08x,%08x,%08x",
                 ++async_send_seen, syscall(178), id, size,
                 (unsigned long)((unsigned long)__builtin_return_address(0) - appfw_base),
                 (message && size >= 4) ? words[0] : 0, (message && size >= 8) ? words[1] : 0,
                 (message && size >= 12) ? words[2] : 0);
        record("ASYNC_SEND ", text);
    } else ++async_send_seen;
    return real_send_msg(id, message);
}
static void install_async_send_probe(unsigned long base) {
    unsigned long page = base + 0x5bc1000UL;
    if (mprotect((void *)page, 4096, 3) != 0) { record("ASYNC_SEND_ARM_FAILED ", "GOT page"); return; }
    *(unsigned long *)(base + 0x5bc1d70UL) = (unsigned long)observe_send_async;
    record("ASYNC_SEND_ARMED ", "appFw osal_snd_msg GOT slot 0x5bc1d70");
}
static void install_sync_direct_probe(unsigned long base) {
    unsigned long page = base + 0x5bc1000UL;
    if (mprotect((void *)page, 4096, 3) != 0) { record("SYNC_DIRECT_ARM_FAILED ", "GOT page not writable"); return; }
    *(unsigned long *)(base + 0x5bc1758UL) = (unsigned long)observe_send_sync_direct;
    record("SYNC_DIRECT_ARMED ", "appFw osal_snd_sync_direct GOT slot 0x5bc1758");
}
static void install_frame_observers(unsigned long base) {
    if (!getenv("MENU_FRAME_OBSERVE")) return;
    if (!real_notify_draw || !real_draw_framebuffer) {
        record("FRAME_PROBES_FAILED ", "libObj exports not captured before appFw init");
        return;
    }
    if (mprotect((void *)(base + 0x5bc2000), 4096, 3) != 0) {
        record("FRAME_PROBES_FAILED ", "appFw GOT page not writable");
        return;
    }
    *(unsigned long *)(base + 0x5bc2098) = (unsigned long)observe_notify_draw;
    *(unsigned long *)(base + 0x5bc2370) = (unsigned long)observe_draw_framebuffer;
    record("FRAME_PROBES_ARMED ", "verified appFw notifyDraw/drawFramebuffer import slots");
}
static int (*real_osd_pin_send)(void *, unsigned int, unsigned int, unsigned int);
static unsigned long (*real_lz_decode)(void *);
static unsigned int lz_decode_count;
static unsigned long osd_libobj_base;
static int (*real_resource_open)(const char *, int, ...);
static void *(*real_resource_fopen)(const char *, const char *);
extern int *__errno_location(void);
static unsigned int resource_open_count;
static void record_resource_open(const char *path, long result, int error) {
    if (!path || !(strstr(path, "image_") || strstr(path, "global.xdb") || strstr(path, ".ltt") ||
                  strstr(path, "fontlist") || strstr(path, "TEXTRM_FONT_LIST") || same_name(path, "/dev/ldec"))) return;
    unsigned int count = __atomic_add_fetch(&resource_open_count, 1, __ATOMIC_RELAXED);
    if (count <= 128) {
        char text[384];
        snprintf(text, sizeof text, "call=%u result=%ld errno=%d path=%.260s", count, result, error, path);
        record("RESOURCE_OPEN ", text);
    } else if (count == 129) record("RESOURCE_LOG_LIMIT ", "first 128 matching resource opens recorded");
}
static int observe_resource_open(const char *path, int flags, ...) {
    int result;
    if ((flags & 0x40) || (flags & 0x410000) == 0x410000) {
        __builtin_va_list args;
        __builtin_va_start(args, flags);
        unsigned int mode = __builtin_va_arg(args, unsigned int);
        __builtin_va_end(args);
        result = real_resource_open(path, flags, mode);
    } else result = real_resource_open(path, flags);
    int error = *__errno_location();
    record_resource_open(path, result, result < 0 ? error : 0);
    *__errno_location() = error;
    return result;
}
static void *observe_resource_fopen(const char *path, const char *mode) {
    void *result = real_resource_fopen(path, mode);
    int error = *__errno_location();
    record_resource_open(path, result ? 1 : -1, result ? 0 : error);
    *__errno_location() = error;
    return result;
}
static unsigned long software_lz_decode(void *object) {
    const unsigned char *p = object;
    if (!p || !osd_libobj_base) return 0;
    void *stream = *(void *const *)(p + 8), *image = *(void *const *)(p + 0x10);
    unsigned int format = *(const unsigned int *)(p + 0x18);
    unsigned int width = *(const unsigned short *)(p + 0x1c), height = *(const unsigned short *)(p + 0x1e);
    unsigned int input_size = *(const unsigned int *)(p + 0x20);
    unsigned int bpp = format == 1 ? 4 : format == 7 ? 2 : format == 8 ? 1 : 0;
    if (!stream || !image || !bpp || !width || !height || width > 8192 || height > 8192 ||
        !input_size || input_size > 0x1000000) {
        record("RESOURCE_LZ_CPU_FAIL ", "unsupported descriptor"); return 0;
    }
    unsigned long row_bytes = ((width + 15UL) & ~15UL) * bpp;
    unsigned long size = row_bytes * height;
    if (size > 0x1000000) { record("RESOURCE_LZ_CPU_FAIL ", "output exceeds bound"); return 0; }
    unsigned long table = *(unsigned long *)stream;
    if (!table || *(unsigned long *)(table + 0x58) != osd_libobj_base + 0x133cc8UL) {
        record("RESOURCE_LZ_CPU_FAIL ", "input stream getter does not match verified pure getter"); return 0;
    }
    const unsigned char *input = *(const unsigned char *const *)((const unsigned char *)stream + 0x10);
    if (sony_lz77_decode(input, input_size, 0, size)) {
        record("RESOURCE_LZ_CPU_FAIL ", "compressed stream failed bounded validation"); return 0;
    }
    unsigned long image_table = *(unsigned long *)image;
    if (!image_table || !*(unsigned long *)(image_table + 0x58)) return 0;
    unsigned int stride = 0;
    typedef void *(*lock_t)(void *, unsigned int *);
    typedef void (*unlock_t)(void *);
    typedef void (*size_t_fn)(void *, unsigned short *, unsigned short *);
    void *output = ((lock_t)(osd_libobj_base + 0x130de8))(image, &stride);
    if (!output) { record("RESOURCE_LZ_CPU_FAIL ", "output bitmap not writable"); return 0; }
    unsigned short output_width = 0, output_height = 0;
    ((size_t_fn)*(unsigned long *)(image_table + 0x58))(image, &output_width, &output_height);
    int result = 5;
    if (stride == row_bytes && output_width >= width && output_height >= height)
        result = sony_lz77_decode(input, input_size, output, size);
    unsigned long nonzero = 0;
    if (!result) for (unsigned long i = 0; i < size; ++i) nonzero += ((const unsigned char *)output)[i] != 0;
    ((unlock_t)(osd_libobj_base + 0x130e00))(image);
    char text[224];
    snprintf(text, sizeof text, "format=%u width=%u height=%u input=%u output=%lu stride=%u bitmap=%ux%u nonzero=%lu result=%d",
             format, width, height, input_size, size, stride, output_width, output_height, nonzero, result);
    record(result ? "RESOURCE_LZ_CPU_FAIL " : "RESOURCE_LZ_CPU_OK ", text);
    return result == 0;
}
static unsigned long observe_lz_decode(void *object) {
    unsigned int count = __atomic_add_fetch(&lz_decode_count, 1, __ATOMIC_RELAXED);
    char text[256];
    if (count <= 64 && object) {
        const unsigned char *p = object;
        unsigned long stream = *(const unsigned long *)(p + 8);
        unsigned long table = stream ? *(const unsigned long *)stream : 0;
        unsigned long getter = table ? *(const unsigned long *)(table + 0x58) : 0;
        snprintf(text, sizeof text, "call=%u object=%p format=%u width=%u height=%u input_bytes=%u stream=%#lx getter=%#lx output=%p",
                 count, object, *(const unsigned int *)(p + 0x18), *(const unsigned short *)(p + 0x1c),
                 *(const unsigned short *)(p + 0x1e), *(const unsigned int *)(p + 0x20), stream, getter,
                 *(void *const *)(p + 0x10));
        record("RESOURCE_LZ_ENTER ", text);
    }
    unsigned long result = getenv("QEMU_SOFTWARE_LZ77") ? software_lz_decode(object) : real_lz_decode(object);
    int error = *__errno_location();
    if (count <= 64) {
        snprintf(text, sizeof text, "call=%u result=%#lx errno=%d", count, result, error);
        record("RESOURCE_LZ_RETURN ", text);
    } else if (count == 65) record("RESOURCE_LZ_LIMIT ", "first 64 decoder calls logged");
    *__errno_location() = error;
    return result;
}
static int (*real_osd_wait_sem)(unsigned int, unsigned int);
static int (*real_osd_signal_sem)(unsigned int);
static unsigned int osd_prepare_count, osd_send_count;
static unsigned int osd_wait_count, osd_signal_count;
static unsigned int frame_wait_count;
static unsigned int ux_wait_tid;
static int observe_osd_wait_sem(unsigned int id, unsigned int timeout) {
    unsigned long caller = (unsigned long)__builtin_return_address(0);
    int target = caller == osd_libobj_base + 0x100224;
    int frame_target = !target && __atomic_load_n(&draw_framebuffer_count, __ATOMIC_RELAXED) >= 2 &&
        timeout == 0xffffffffu && (unsigned int)syscall(178) == ui_thread_id;
    unsigned int count = target ? __atomic_add_fetch(&osd_wait_count, 1, __ATOMIC_RELAXED)
        : frame_target ? ++frame_wait_count : 0;
    /* The successful MENU/confirm path ran on this same thread: the one parked in the UX
       frame wait loop (libObj Semaphore::lock, infinite timeout). Remember it once. */
    if (!target && timeout == 0xffffffffu && caller == osd_libobj_base + 0x1027ac &&
        !__atomic_load_n(&ux_wait_tid, __ATOMIC_ACQUIRE))
        __atomic_store_n(&ux_wait_tid, (unsigned int)syscall(178), __ATOMIC_RELEASE);
    int logged = (target && count <= 16) || (frame_target && count <= 128);
    char text[192];
    if (logged) {
        unsigned long parent = 0;
        if (caller == osd_libobj_base + 0x1027ac) {
            /* Verified Semaphore::lock saves x29/x30 in a 16-byte frame before this call. */
            unsigned long frame = (unsigned long)__builtin_frame_address(0);
            unsigned long upper = *(unsigned long *)frame;
            if (!(upper & 15) && upper > frame && upper - frame < 4096)
                parent = *(unsigned long *)(upper + 8);
        }
        snprintf(text, sizeof text, "call=%u tid=%ld pid=%ld sem=%#x timeout=%#x caller=libObj+%#lx parent=%#lx",
                 count, syscall(178), (long)getpid(), id, timeout, caller-osd_libobj_base, parent);
        record(target ? "OSD_WAIT_ENTER " : "FRAME_SEM_WAIT_ENTER ", text);
        if (frame_target && count <= 2) {
            typedef int (*stat_t)(unsigned int, unsigned int *);
            stat_t stat_msgq = (stat_t)real_dlsym((void *)-1, "osal_stat_msgq");
            /* Query only queues already used by the completed first-frame path. */
            const unsigned int queues[] = {0x8280074d, 0x8280084d, 0x8288076c};
            if (stat_msgq) for (unsigned int i = 0; i < 3; ++i) {
                unsigned int state[4] = {0, 0, 0, 0};
                int status = stat_msgq(queues[i], state);
                snprintf(text, sizeof text, "wait_call=%u endpoint=%#x result=%d state=%u,%u,%u,%u",
                         count, queues[i], status, state[0], state[1], state[2], state[3]);
                record("OSD_KERNEL_QUEUE ", text);
            }
        }
    }
    int result = real_osd_wait_sem(id, timeout);
    if (logged) {
        snprintf(text, sizeof text, "call=%u sem=%#x result=%d", count, id, result);
        record(target ? "OSD_WAIT_RETURN " : "FRAME_SEM_WAIT_RETURN ", text);
    }
    /* Drive the original input callback from the thread that owns the UX wait loop. */
    if (frame_target && count == 129) record("FRAME_SEM_LOG_LIMIT ", "first 128 UI-thread waits logged");
    return result;
}
static int observe_osd_signal_sem(unsigned int id) {
    int result = real_osd_signal_sem(id);
    if (osd_libobj_base && id == *(unsigned int *)(osd_libobj_base + 0x2ebe68)) {
        unsigned int count = __atomic_add_fetch(&osd_signal_count, 1, __ATOMIC_RELAXED);
        if (count <= 16) {
            char text[128];
            snprintf(text, sizeof text, "call=%u tid=%ld sem=%#x result=%d", count, syscall(178), id, result);
            record("OSD_WAIT_SIGNAL ", text);
        }
    }
    return result;
}
static int observe_osd_set_entry(void *stream, const void *entry) {
    unsigned int count = __atomic_add_fetch(&osd_prepare_count, 1, __ATOMIC_RELAXED);
    if (count <= 64 && entry) {
        const unsigned char *p = entry;
        char text[224];
        snprintf(text, sizeof text, "call=%u target=%u width=%u height=%u rt=%#lx be=%#lx",
                 count, *(const unsigned short *)(p + 0x20),
                 *(const unsigned short *)(p + 0x24), *(const unsigned short *)(p + 0x26),
                 *(const unsigned long *)(p + 0x48), *(const unsigned long *)(p + 0x58));
        record("OSD_PREPARE ", text);
    }
    int result = real_osd_set_entry(stream, entry);
    if (count <= 64) {
        char text[80];
        snprintf(text, sizeof text, "call=%u result=%d", count, result);
        record("OSD_PREPARE_RETURN ", text);
    }
    return result;
}
static int observe_osd_pin_send(void *pin, unsigned int a1, unsigned int a2, unsigned int a3) {
    unsigned int count = __atomic_add_fetch(&osd_send_count, 1, __ATOMIC_RELAXED);
    if (count <= 64 && pin) {
        const unsigned int *p = pin;
        char text[160];
        snprintf(text, sizeof text, "call=%u dest=%#x source=%#x state=%u args=%#x,%#x,%#x",
                 count, p[7], p[11], p[12], a1, a2, a3);
        record("OSD_SEND ", text);
    }
    int result = real_osd_pin_send(pin, a1, a2, a3);
    if (count <= 64) {
        char text[80];
        snprintf(text, sizeof text, "call=%u result=%d", count, result);
        record("OSD_SEND_RETURN ", text);
    }
    if (count == 65) record("OSD_LOG_LIMIT ", "first 64 sends logged; later calls still forwarded");
    return result;
}
static void install_osd_observers(void *handle) {
    if (osd_libobj_base) return;
    void *anchor = real_dlsym(handle, "GRM_screenGetOnBitmap");
    real_osd_set_entry = real_dlsym(handle, "_ZN27C_DataflowInfra_StdData_OSD25SetEntry_OsdImageSizeInfoEP34C_DataflowInfra_Entry_OsdImageSize");
    real_osd_pin_send = real_dlsym(handle, "_ZN16DataflowInfraPin4SendEjjj");
    if (!anchor || !real_osd_set_entry || !real_osd_pin_send) {
        record("OSD_PROBES_FAILED ", "required exports unresolved");
        return;
    }
    unsigned long base = (unsigned long)anchor - 0xf8e94UL;
    /* JUMP_SLOT offsets verified with readelf on the original c0897d72 libObj.so. */
    if (mprotect((void *)(base + 0x27e000), 8192, 3) != 0) {
        record("OSD_PROBES_FAILED ", "GOT pages not writable");
        return;
    }
    *(unsigned long *)(base + 0x27ec98) = (unsigned long)observe_osd_set_entry;
    *(unsigned long *)(base + 0x27f528) = (unsigned long)observe_osd_pin_send;
    osd_libobj_base = base;
    real_osd_wait_sem = real_dlsym(handle, "osal_wai_sem_tmo");
    real_osd_signal_sem = real_dlsym(handle, "osal_sig_sem");
    if (real_osd_wait_sem && real_osd_signal_sem) {
        *(unsigned long *)(base + 0x27e1a0) = (unsigned long)observe_osd_wait_sem;
        *(unsigned long *)(base + 0x27f540) = (unsigned long)observe_osd_signal_sem;
        record("OSD_WAIT_PROBES_ARMED ", "VDT submit wait at libObj+0x100220 and matching semaphore signals");
    } else record("OSD_WAIT_PROBES_FAILED ", "OSAL semaphore exports unresolved");
    real_resource_open = real_dlsym(handle, "open");
    real_resource_fopen = real_dlsym(handle, "fopen");
    if (real_resource_open && real_resource_fopen) {
        *(unsigned long *)(base + 0x27e490) = (unsigned long)observe_resource_open;
        *(unsigned long *)(base + 0x27f040) = (unsigned long)observe_resource_fopen;
        record("RESOURCE_PROBES_ARMED ", "libObj image bank/database/font opens; errno and return values preserved");
    }
    unsigned long *decode_slot = (unsigned long *)(base + 0x277900);
    if (*decode_slot == base + 0x15a8b8 && mprotect((void *)(base + 0x277000), 4096, 3) == 0) {
        real_lz_decode = (unsigned long (*)(void *))*decode_slot;
        *decode_slot = (unsigned long)observe_lz_decode;
        record("RESOURCE_LZ_PROBE_ARMED ", "verified Lz77Decoder::decodeImpl vtable slot");
    } else record("RESOURCE_LZ_PROBE_FAILED ", "decoder slot did not match original implementation");
    char text[144];
    snprintf(text, sizeof text, "libObj=%#lx set_entry=+0x27ec98 pin_send=+0x27f528", base);
    record("OSD_PROBES_ARMED ", text);
}
int software_draw_initialize(int gpe) {
    if (!software_gpe) return real_draw_initialize ? real_draw_initialize(gpe) : 5;
    if (gpe != 0) return 5;
    if (raster_fd < 0) raster_fd = open("/dev/mem", 2);
    if (software_rgba4444) record("GPE_RGBA_MODEL ", "opt-in straight RGBA4444/source-over/nearest model; hardware pixel equivalence unverified");
    record("GPE_SOFTWARE_INIT ", raster_fd >= 0 ? "physical bitmap access ready; hardware FIFO unused" : "bitmap access unavailable");
    return raster_fd >= 0 ? 0 : 5;
}
int software_gperm_initialize(const void *object) {
    if (!software_gpe) return real_gperm_initialize ? real_gperm_initialize(object) : 5;
    return object ? software_draw_initialize(((const int *)object)[2]) : 5;
}
static int raster_completion(unsigned int sequence, unsigned int source, const unsigned char *callback_info) {
    void (*callback)(const void *) = *(void (**)(const void *))callback_info;
    struct { unsigned int sequence, reserved; unsigned long argument; } info =
        {sequence, 0, *(const unsigned long *)(callback_info + 8)};
    if (callback) callback(&info);
    if (source) { int status = 0; if (!real_draw_complete || !real_draw_complete(source, &status, sizeof status)) return 5; }
    return 0;
}
int software_fill_worker(int gpe, int core, unsigned int sequence, unsigned int source, const void *parameters) {
    if (!software_gpe) return real_worker_fill ? real_worker_fill(gpe, core, sequence, source, parameters) : 5;
    int previous_failure = raster_failed;
    raster_failed = 1;
    if (!parameters || gpe != 0 || core != 0 || raster_fd < 0) return 5;
    const unsigned int *p = parameters;
    unsigned long long address = *(const unsigned long long *)parameters;
    size_t bytes = ((size_t)p[3] + p[5]) * p[6] * (p[7] ? 4 : 2);
    if (address < 0x410000000ULL || address >= 0x500000000ULL || !bytes || bytes > 0x4000000 ||
        bytes > 0x500000000ULL - address) return 5;
    unsigned long base = address & ~4095ULL;
    size_t offset = address - base, length = (offset + bytes + 4095) & ~4095UL;
    if (pthread_mutex_lock(headless_raster_mutex)) return 5;
    void *mapped = mmap(0, length, 3, 1, raster_fd, base);
    if (mapped == (void *)-1) { pthread_mutex_unlock(headless_raster_mutex); return 5; }
    int result = gpe_uniform_fill((unsigned char *)mapped + offset, bytes, p);
    if (result && software_rgba4444) result = gpe_fill_rgba4444((unsigned char *)mapped + offset, bytes, p);
    if (munmap(mapped, length)) result = 5;
    if (pthread_mutex_unlock(headless_raster_mutex)) result = 5;
    char text[180];
    snprintf(text, sizeof text, "sequence=%u address=%#llx bytes=%lu width=%u height=%u format=%u result=%d",
             sequence, address, bytes, p[4], p[5], p[7], result);
    record("GPE_SOFTWARE_FILL ", text);
    if (result) { raster_failed = 1; return result; }
    const unsigned char *raw = parameters;
    result = raster_completion(sequence, source, raw + 0x28);
    raster_failed = result ? 1 : previous_failure;
    return result;
}
int software_blit_worker(int gpe, int core, unsigned int sequence, unsigned int source, const void *parameters) {
    if (!software_gpe) return real_worker_blit ? real_worker_blit(gpe, core, sequence, source, parameters) : 5;
    capture_gpe(1, gpe, core, parameters, 0x90);
    int previous_failure = raster_failed;
    raster_failed = 1;
    if (!parameters || gpe != 0 || core != 0 || raster_fd < 0) return 5;
    const unsigned char *raw = parameters;
    struct gpe_copy_plan plan;
    struct gpe_sprite_plan sprite;
    int use_sprite = 0;
    /* Non-null callbacks need the deferred command-5 FIFO; libObj's verified path uses NULL. */
    if (*(const unsigned long *)(raw + 0x80)) {
        record("GPE_SOFTWARE_UNSUPPORTED ", "deferred non-null callback is not implemented");
        return 5;
    }
    if (gpe_plan_copy(parameters, &plan)) {
        if (!software_rgba4444 || gpe_plan_sprite(parameters, &sprite)) {
            record("GPE_SOFTWARE_UNSUPPORTED ", "BitBlit outside supported copy or opt-in sprite subset");
            return 5;
        }
        plan = sprite.memory;
        use_sprite = 1;
    }
    if (!raw[0x7a] && !source) return 5;
    if (!plan.rows) {
        int result = raster_completion(sequence, source, raw + 0x80);
        raster_failed = result ? 1 : previous_failure;
        return result;
    }
    unsigned long dst_base = plan.destination & ~4095ULL, src_base = plan.source & ~4095ULL;
    unsigned long dst_offset = plan.destination - dst_base, src_offset = plan.source - src_base;
    unsigned long dst_length = (dst_offset + plan.destination_span + 4095) & ~4095UL;
    unsigned long src_length = (src_offset + plan.source_span + 4095) & ~4095UL;
    if (pthread_mutex_lock(headless_raster_mutex)) return 5;
    void *dst = mmap(0, dst_length, 3, 1, raster_fd, dst_base);
    if (dst == (void *)-1) { pthread_mutex_unlock(headless_raster_mutex); return 5; }
    void *src = mmap(0, src_length, 1, 1, raster_fd, src_base);
    if (src == (void *)-1) { munmap(dst, dst_length); pthread_mutex_unlock(headless_raster_mutex); return 5; }
    int result = use_sprite
        ? gpe_draw_sprite((unsigned char *)dst + dst_offset, plan.destination_span,
                          (const unsigned char *)src + src_offset, plan.source_span, &sprite)
        : gpe_copy_rows((unsigned char *)dst + dst_offset, plan.destination_span,
                        (const unsigned char *)src + src_offset, plan.source_span, &plan);
    if (munmap(src, src_length)) result = 5;
    if (munmap(dst, dst_length)) result = 5;
    if (pthread_mutex_unlock(headless_raster_mutex)) result = 5;
    char text[192];
    snprintf(text, sizeof text, "sequence=%u src=%#llx dst=%#llx rows=%u line=%lu result=%d",
             sequence, plan.source, plan.destination, plan.rows, plan.line, result);
    record(use_sprite ? "GPE_SOFTWARE_SPRITE_APPROX " : "GPE_SOFTWARE_COPY ", text);
    if (result) return result;
    result = raster_completion(sequence, source, raw + 0x80);
    raster_failed = result ? 1 : previous_failure;
    return result;
}
int software_flush_worker(int gpe, int core, unsigned int sequence, unsigned int source, const void *parameters) {
    if (!software_gpe) return real_worker_flush ? real_worker_flush(gpe, core, sequence, source, parameters) : 5;
    if (!parameters || gpe != 0 || core != 0 || raster_fd < 0 || raster_failed) return 5;
    /* The original worker FIFO has already executed all prior CPU operations. */
    record("GPE_SOFTWARE_FLUSH ", "prior raster writes finished; using original callback/SID completion format");
    return raster_completion(sequence, source, (const unsigned char *)parameters + 8);
}
int observe_gpe_fill(int gpe, int core, unsigned int *sequence, const void *parameters) {
    if (!real_gpe_fill) __builtin_trap();
    capture_gpe(0, gpe, core, parameters, 0x38);
    return real_gpe_fill(gpe, core, sequence, parameters);
}
int observe_gpe_blit(int gpe, int core, unsigned int *sequence, const void *parameters) {
    if (!real_gpe_blit) __builtin_trap();
    capture_gpe(1, gpe, core, parameters, 0x90);
    return real_gpe_blit(gpe, core, sequence, parameters);
}
void *dlsym(void *handle, const char *name) {
    if (!real_dlsym) initialize();
    void *symbol = real_dlsym(handle, name);
    record(symbol ? "RESOLVED " : "NO_SYMBOL ", name);
    if (symbol && same_name(name, "Application_System_Init")) {
        /* App dependencies can be local to this dlopen group and absent during our preload constructor. */
        sd_ack_create=real_dlsym(handle,"pthread_create");
        sd_ack_detach=real_dlsym(handle,"pthread_detach");
        start_headless_osd();
        real_application_init = symbol;
        appfw_base = (unsigned long)symbol - 0x1796918;
        start_live_key_worker();
        if (!getenv("MENU_OBSERVE_SELFTEST")) install_create_screen_sentinel(appfw_base);
        if (!getenv("MENU_OBSERVE_SELFTEST")) install_frame_observers(appfw_base);
        if (!getenv("MENU_OBSERVE_DISABLE_UX2_HOOK") && !getenv("MENU_OBSERVE_SELFTEST")) {
            unsigned int patched = patch_uxengine_init2(appfw_base);
            char text[96];
            snprintf(text, sizeof text, "result=%u appfw_base=%#lx wrapper=%#lx",
                     patched, appfw_base, (unsigned long)observe_uxengine_init2);
            record(patched == 1 ? "UX2_HOOK " : "UX2_HOOK_FAILED ", text);
        }
        return observe_application_init;
    }
    if (symbol && same_name(name, "udtr_ufp_init")) {
        real_updater_init = symbol;
        return observe_updater_init;
    }
    if (symbol && same_name(name, "udtr_ufp_exit")) {
        real_updater_exit = symbol;
        return observe_updater_exit;
    }
    if (symbol && same_name(name, "osal_dynamic_id")) {
        real_dynamic_id = symbol;
        return osal_dynamic_id;
    }
    if (symbol && same_name(name, "osal_reg_sync_msg_queue_cb")) {
        real_reg_sync = symbol;
        return osal_reg_sync_msg_queue_cb;
    }
    if (symbol && same_name(name, "osal_snd_msg")) {
        real_send_msg = symbol;
        return osal_snd_msg;
    }
    if (symbol && same_name(name, "osal_valloc_msg_wait")) {
        real_allocate_msg = symbol;
        return osal_valloc_msg_wait;
    }
    if (symbol && same_name(name, "osal_free_msg")) {
        real_free_msg = symbol;
        return osal_free_msg;
    }
    if (symbol && same_name(name, "osal_snd_sync_msg")) {
        real_send_sync = symbol;
        return osal_snd_sync_msg;
    }
    if (symbol && same_name(name, "osal_snd_sync_direct") && 0) {
        real_send_sync_direct = symbol;
    }
    if (symbol && same_name(name, "kikilog_set_notify_cb")) {
        real_kikilog_notify = symbol;
        return kikilog_set_notify_cb;
    }
    if (symbol && same_name(name, "_ZN5mpgpe13GpermFillRectENS_3GpeENS_7IntCoreEPjRKNS_13FillRectParamE")) {
        real_gpe_fill = symbol;
        return observe_gpe_fill;
    }
    if (symbol && same_name(name, "_ZN5mpgpe12GpermBitBlitENS_3GpeENS_7IntCoreEPjRKNS_12BitBlitParamE")) {
        real_gpe_blit = symbol;
        return observe_gpe_blit;
    }
    return symbol;
}
int pthread_attr_setschedpolicy(void *attr, int policy) {
    if (!real_attr_policy) initialize();
    (void)policy;
    return real_attr_policy(attr, 0);
}
int pthread_attr_setschedparam(void *attr, const void *parameter) {
    if (!real_attr_param) initialize();
    int normal_priority = 0;
    (void)parameter;
    return real_attr_param(attr, &normal_priority);
}
int pthread_setschedparam(pthread_t thread, int policy, const void *parameter) {
    if (!real_thread_param) initialize();
    int normal_priority = 0;
    (void)policy; (void)parameter;
    return real_thread_param(thread, 0, &normal_priority);
}
int sched_setscheduler(int pid, int policy, const void *parameter) {
    if (!real_scheduler) initialize();
    int normal_priority = 0;
    (void)policy; (void)parameter;
    return real_scheduler(pid, 0, &normal_priority);
}
