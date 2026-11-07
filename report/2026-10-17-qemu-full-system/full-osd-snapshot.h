/* SPDX-License-Identifier: MIT */
#ifndef FULL_OSD_SNAPSHOT_H
#define FULL_OSD_SNAPSHOT_H
#include <stddef.h>
#define FULL_OSD_SNAPSHOT_BYTES (128U + 24930U + 614400U)
#define FULL_OSD_SNAPSHOT_LIMIT 16U
#define FULL_OSD_SNAPSHOT_DIRECTORY "/log/qemu/immutable-osd"
struct full_osd_snapshot_request {
    int enabled;
    const char *nonce;
    void (*log)(void *context,const char *record);
    void *log_context;
#ifdef FULL_OSD_HOST_FIXTURE
    const char *host_fixture_directory;
#endif
};
enum full_osd_snapshot_result {
    FULL_OSD_DISABLED=0, FULL_OSD_COMMITTED=1, FULL_OSD_NO_REQUEST=2,
    FULL_OSD_NONCE_EXISTS=3, FULL_OSD_REJECTED=-1,
    FULL_OSD_LIMIT_REACHED=-2, FULL_OSD_IO_FAILED=-3
};
/* Caller retains bytes and ACK ownership. One hex nonce and an exact
 * "HOSDREQ1 <nonce>\n" request commit once. Only COMMIT establishes a complete
 * file; crash leftovers consume a slot but are never assumed complete. */
int full_osd_snapshot_save(const void *,size_t,const struct full_osd_snapshot_request *);
/* Called only by the single original hosd worker while it owns the container.
 * Explicit environment gate + host-written nonce mailbox; never controls ACK. */
int full_osd_capture_owned(const void *,size_t,void (*)(const char *,const char *));
#endif
