/* SPDX-License-Identifier: MIT */
/* Observe the media-detection state machine without changing it.
 *
 * Why this exists: static analysis (agent report, run-28cb5eb6) established that
 * `InfraMediaDetectThreadRM::Update()` should move `MediaInfo+0x38` 0 -> 1 when a
 * channel is enabled and reports portState, and that the first 0->1 only records
 * detection -- `StartInOut()` establishes the downstream notify SID. The open
 * question is purely runtime: which of those actually executed in our guest.
 *
 * Both `Update` and `StartInOut` are reached through the PLT inside this library
 * (`0x10d38 bl 0x8dd0 <…UpdateEv@plt>`), so interposing the public symbols sees the
 * calls. Every wrapper forwards to the original and logs; nothing is altered.
 *
 * Layout (this = InfraMediaDetectThreadRM*), from the same report:
 *   R[i] = this + 0x258 + i*0x18 : +0x10 enable, +0x11 hold, +0x12 portState, +0x13 removeCount
 *   M[j] = this + 0x108 + j*0x70 : +0x08 valid, +0x14 rmdataMask, +0x18 startInOut,
 *                                  +0x1c notifySid, +0x38 status, +0x3c, +0x40
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define OFF_R_BASE 0x258
#define OFF_R_STEP 0x18
#define OFF_M_BASE 0x108
#define OFF_M_STEP 0x70

static int enabled;
static unsigned logged;
static __thread unsigned parsing;

static void console(const char *line) {
    int fd = open("/dev/console", 1);
    if (fd < 0) return;
    write(fd, line, strlen(line));
    write(fd, "\n", 1);
    close(fd);
}

static void *original(const char *name) {
    void *symbol = dlsym(RTLD_NEXT, name);
    if (!symbol) {
        char line[200];
        snprintf(line, sizeof line, "DETECT_OBSERVE_RESOLVE_FAILED %s", name);
        console(line);
    }
    return symbol;
}

static void dump(const char *tag, void *self) {
    if (!enabled || logged > 200) return;
    const unsigned char *base = (const unsigned char *)self;
    char line[420];
    int at = snprintf(line, sizeof line, "%s self=%p", tag, self);
    for (int i = 0; i < 3; ++i) {
        const unsigned char *r = base + OFF_R_BASE + i * OFF_R_STEP;
        at += snprintf(line + at, sizeof line - at, " R%d=%u/%u/%u/%u",
                       i, r[0x10], r[0x11], r[0x12], r[0x13]);
    }
    for (int j = 0; j < 3; ++j) {
        const unsigned char *m = base + OFF_M_BASE + j * OFF_M_STEP;
        at += snprintf(line + at, sizeof line - at, " M%d=valid%u/mask%#x/start%u/sid%#x/status%u",
                       j, m[0x08], *(const unsigned int *)(m + 0x14), m[0x18],
                       *(const unsigned int *)(m + 0x1c), m[0x38]);
    }
    if (at > 0 && at < (int)sizeof line) { logged++; console(line); }
}

__attribute__((constructor)) static void detect_observe_init(void) {
    const char *flag = getenv("FULLSYSTEM_DETECT_OBSERVE");
    enabled = flag && flag[0] == '1' && !flag[1];
}

/* void InfraMediaDetectThreadRM::Update() */
void _ZN24InfraMediaDetectThreadRM6UpdateEv(void *self) {
    void (*fn)(void *) = original("_ZN24InfraMediaDetectThreadRM6UpdateEv");
    dump("DETECT_OBSERVE_UPDATE_BEFORE", self);
    if (fn) fn(self); else { console("DETECT_OBSERVE_UPDATE_MISSING_ORIGINAL"); _exit(126); }
    dump("DETECT_OBSERVE_UPDATE_AFTER", self);
}

/* int InfraMediaDetectThreadRM::StartInOut(unsigned, void*) */
int _ZN24InfraMediaDetectThreadRM10StartInOutEjPv(void *self, unsigned id, void *arg) {
    int (*fn)(void *, unsigned, void *) = original("_ZN24InfraMediaDetectThreadRM10StartInOutEjPv");
    if (enabled) {
        char line[220];
        const unsigned char *base = (const unsigned char *)self;
        snprintf(line, sizeof line, "DETECT_OBSERVE_START_IN_OUT self=%p id=%u arg=%p notifySid=%#x",
                 self, id, arg,
                 (unsigned)(arg ? *(const unsigned int *)arg : 0));
        console(line);
        (void)base;
    }
    if (!fn) { console("DETECT_OBSERVE_START_IN_OUT_MISSING_ORIGINAL"); _exit(126); }
    int rc = fn(self, id, arg);
    if (enabled) {
        char line[220];
        const unsigned char *base = (const unsigned char *)self;
        snprintf(line, sizeof line, "DETECT_OBSERVE_START_IN_OUT_RET rc=%d M0=start%u/sid%#x M1=start%u/sid%#x",
                 rc, base[OFF_M_BASE + 0x18], *(const unsigned int *)(base + OFF_M_BASE + 0x1c),
                 base[OFF_M_BASE + OFF_M_STEP + 0x18],
                 *(const unsigned int *)(base + OFF_M_BASE + OFF_M_STEP + 0x1c));
        console(line);
    }
    return rc;
}

/* -- message delivery observation -------------------------------------------
 * Update() alone cannot tell whether the 7-byte front-end state ever arrived:
 * ParseInternalMessage is the only place that decodes it (byte0==2, length>=7,
 * then writes R[i] enable/hold/portState/removeCount). Logging the raw message
 * separates "packet never delivered" from "delivered but decoded differently".
 */
static void hex_into(char *line, int *at, int limit, const unsigned char *p, int count) {
    for (int i = 0; i < count && *at < limit - 4; ++i)
        *at += snprintf(line + *at, limit - *at, "%02x", p[i]);
}

/* Dump the message object only. Never dereference a field: run-5v0bc8z0 showed that
 * guessing a payload pointer from the object layout crashes the guest. The payload is
 * read through the interposer below, which sees the pointer the parser itself uses. */
static void dump_bytes(const char *tag, void *self, const void *msg, unsigned int arg) {
    if (!enabled || !msg) return;
    char line[420];
    int limit = (int)sizeof line;
    snprintf(line, limit, "%s self=%p arg=%u msg=%p", tag, self, arg, msg);
    /* ObjMsg fields are opaque; only its own API may expose readable data. */
    console(line);
}

/* MWF::Struct::GetValue() — the parser calls this at 0x109b4 to obtain the payload.
 * Interposing it is safe because the returned pointer is valid by construction. */
const unsigned char *_ZNK3MWF6Struct8GetValueEv(void *self) {
    const unsigned char *(*fn)(void *) = dlsym(RTLD_NEXT, "_ZNK3MWF6Struct8GetValueEv");
    if (!fn) { console("DETECT_OBSERVE_GETVALUE_MISSING_ORIGINAL"); _exit(126); }
    const unsigned char *value = fn(self);
    if (enabled && parsing && value) {
        int (*size_fn)(void *)=dlsym(RTLD_NEXT,"_ZNK3MWF6Struct7GetSizeEv");
        int size=size_fn?size_fn(self):0;
        if (size<=0) return value;
        char line[220];
        int limit = (int)sizeof line;
        int at = snprintf(line, limit, "DETECT_OBSERVE_GETVALUE struct=%p value=%p bytes=%d head=", self, value,size);
        hex_into(line, &at, limit, value, size<12?size:12);
        console(line);
    }
    return value;
}

int _ZN24InfraMediaDetectThreadRM20ParseInternalMessageEjPN3MWF6ObjMsgE(void *self, unsigned int id, void *msg) {
    int (*fn)(void *, unsigned int, void *) =
        dlsym(RTLD_NEXT, "_ZN24InfraMediaDetectThreadRM20ParseInternalMessageEjPN3MWF6ObjMsgE");
    dump_bytes("DETECT_OBSERVE_PARSE_RM", self, msg, id);
    if (!fn) { console("DETECT_OBSERVE_PARSE_RM_MISSING_ORIGINAL"); _exit(126); }
    ++parsing;
    int rc=fn(self,id,msg);
    --parsing;
    if (enabled) {
        const unsigned char *b = (const unsigned char *)self;
        char line[260];
        snprintf(line, sizeof line, "DETECT_OBSERVE_PARSE_RM_AFTER R0=%u/%u/%u/%u R1=%u/%u/%u/%u R2=%u/%u/%u/%u",
                 b[0x268], b[0x269], b[0x26a], b[0x26b], b[0x280], b[0x281], b[0x282], b[0x283],
                 b[0x298], b[0x299], b[0x29a], b[0x29b]);
        console(line);
    }
    return rc;
}

int _ZN26InfraMediaDetectThreadBase12ParseMessageEPN3MWF6ObjMsgE(void *self, void *msg) {
    int (*fn)(void *, void *) = dlsym(RTLD_NEXT, "_ZN26InfraMediaDetectThreadBase12ParseMessageEPN3MWF6ObjMsgE");
    dump_bytes("DETECT_OBSERVE_PARSE_BASE", self, msg, 0);
    if (!fn) { console("DETECT_OBSERVE_PARSE_BASE_MISSING_ORIGINAL"); _exit(126); }
    return fn(self,msg);
}

/* -- cmd3 subscribe observation ---------------------------------------------
 * Interposing the global osal_snd_msg/osal_stat_msgq crashed the guest
 * (run-a8365cb6: SEGV right after DETECT_OBSERVE_PROFILE=on, before any probe
 * line) because those symbols are also used by libraries loaded before this
 * preload, so RTLD_NEXT could not always find the original. Keep the probe
 * narrow instead: this method IS reached through the library's PLT
 * (0xff30 / 0x10048 / 0x104a8 -> 0x9780), so interposing it is safe and it
 * answers the delivery question directly: did the cmd3 subscribe succeed?
 */
int _ZN24InfraMediaDetectThreadRM23SetOsalIdForMediaNotifyEj(void *self, unsigned int notify_sid) {
    int (*fn)(void *, unsigned int) =
        dlsym(RTLD_NEXT, "_ZN24InfraMediaDetectThreadRM23SetOsalIdForMediaNotifyEj");
    if (!fn) { console("DETECT_OBSERVE_CMD3_MISSING_ORIGINAL"); _exit(126); }
    int rc = fn(self, notify_sid);
    if (enabled) {
        char line[200];
        snprintf(line, sizeof line, "DETECT_OBSERVE_CMD3 notify_sid=%#x rc=%d", notify_sid, rc);
        console(line);
    }
    return rc;
}
