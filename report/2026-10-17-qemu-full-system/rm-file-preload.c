/* SPDX-License-Identifier: MIT */
/* Start the file-backed RM/media provider inside the guest firmware process.
 *
 * Provenance: the provider itself is `rm-file-device.c` / `rm-file-device.h`,
 * ported from the sibling deliverable `report/2026-10-17-qemu-native-camera`
 * (their observer called it under MENU_RM_FILE=1). This project must not edit the
 * observer snapshot, so the call site lives here instead: `rm_file_start_lazy()`
 * resolves the ORIGINAL osal entry points and hands the provider a
 * `full_imaging_io` built from them. It is called from the verified
 * `mcmn_param_init` hook, i.e. inside the firmware's own init sequence.
 *
 * It is only active when MENU_RM_FILE_IMAGE names the backing image, so an
 * ordinary GUI session is unaffected.
 */
#define _GNU_SOURCE
#include "rm-file-device.h"
#include <dlfcn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Guest user-space OSAL entry points (same ones mcmn-query.c uses). */
typedef int (*valloc_fn)(unsigned int, void **, unsigned int, int);
typedef int (*free_fn)(unsigned int, void *);
typedef int (*send_fn)(unsigned int, void *);
typedef void (*set_src_fn)(void *, unsigned int);
typedef unsigned int (*size_fn)(void *);
typedef unsigned int (*src_fn)(void *);
typedef int (*reg_fn)(unsigned int, void **, void *, unsigned long);
typedef int (*unreg_fn)(unsigned int, void *);
typedef int (*statq_fn)(unsigned int, void *);

static valloc_fn p_valloc;
static free_fn p_free;
static send_fn p_send;
static set_src_fn p_set_src;
static size_fn p_size;
static src_fn p_src;
static reg_fn p_reg;
static unreg_fn p_unreg;
static statq_fn p_statq;
static int active;

static void console(const char *tag, const char *text) {
    char line[512];
    int length = snprintf(line, sizeof line, "%s%s\n", tag, text ? text : "-");
    if (length <= 0 || length >= (int)sizeof line) return;
    int fd = open("/dev/console", 1);
    if (fd < 0) return;
    write(fd, line, (unsigned long)length);
    close(fd);
}


/* Resolve an osal entry point.
 *
 * A constructor runs before the firmware has loaded its own libraries, so a plain
 * dlsym(RTLD_DEFAULT) failed for osal_msg_size / osal_get_msg_src / osal_set_msg_src /
 * osal_stat_msgq / osal_unreg_msg_queue_cb in 27 of 27 processes (run-tdk1nnvz).
 * Fall back to opening the library that exports them.
 */
static void *osal_handle;

static void *need(const char *name) {
    void *symbol = dlsym(RTLD_DEFAULT, name);
    if (symbol) return symbol;
    if (!osal_handle) {
        static const char *candidates[] = {
            "libosal_uipc.so", "/usr/lib/libosal_uipc.so", "libosal_utm.so", "/usr/lib/libosal_utm.so"
        };
        for (unsigned i = 0; i < sizeof candidates / sizeof *candidates && !osal_handle; ++i)
            osal_handle = dlopen(candidates[i], RTLD_NOW | RTLD_GLOBAL);
    }
    if (osal_handle) symbol = dlsym(osal_handle, name);
    if (!symbol) {
        char line[200];
        snprintf(line, sizeof line, "RM_FILE_PRELOAD_RESOLVE_FAILED %s handle=%p", name, osal_handle);
        console("", line);
    }
    return symbol;
}


/* The io vtable the provider expects: every call goes to the ORIGINAL osal. */
static int io_allocate(unsigned int dst, void **out, unsigned int n, unsigned int count) {
    return p_valloc(dst, out, n, (int)count);
}
static int io_release(unsigned int dst, void *p) { return p_free(dst, p); }
static void io_set_source(void *p, unsigned int source) { p_set_src(p, source); }
static int io_send(unsigned int dst, void *p) { return p_send(dst, p); }
static unsigned int io_size(void *p) { return p_size(p); }
static unsigned int io_source(void *p) { return p_src(p); }
static void io_record(const char *tag, const char *text) { console(tag, text); }

static const struct full_imaging_io IO = {
    io_allocate, io_release, io_set_source, io_send, io_size, io_source, io_record
};

static void resolve_all(void) {
    p_valloc = (valloc_fn)need("osal_valloc_msg_wait");
    p_free = (free_fn)need("osal_free_msg");
    p_send = (send_fn)need("osal_snd_msg");
    p_set_src = (set_src_fn)need("osal_set_msg_src");
    p_size = (size_fn)need("osal_msg_size");
    p_src = (src_fn)need("osal_get_msg_src");
    p_reg = (reg_fn)need("osal_reg_msg_queue_cb");
    p_unreg = (unreg_fn)need("osal_unreg_msg_queue_cb");
    p_statq = (statq_fn)need("osal_stat_msgq");
}

/* Started lazily from the firmware's own init sequence (see file-media-config.c),
 * not from a constructor: by then the guest libraries are loaded. */
void rm_file_start_lazy(void) {
    static int attempted;
    if (attempted) return;
    attempted = 1;
    const char *image = getenv("MENU_RM_FILE_IMAGE");
    const char *claim = getenv("MENU_RM_FILE_CLAIM");
    if (!image || !image[0]) return;            /* opt-in only */
    if (!claim || !claim[0]) claim = "/tmp/rm-file.claim";
    resolve_all();
    if (!p_valloc || !p_free || !p_send || !p_set_src || !p_size || !p_src ||
        !p_reg || !p_unreg || !p_statq) {
        console("RM_FILE_PRELOAD_FAILED ", "incomplete osal resolution");
        return;
    }
    int rc = native_rm_file_start(image, claim, &IO, p_reg, p_unreg, p_statq);
    active = rc == 0;
    char line[200];
    snprintf(line, sizeof line, "image=%s claim=%s rc=%d", image, claim, rc);
    console("RM_FILE_PRELOAD_START ", line);
}
