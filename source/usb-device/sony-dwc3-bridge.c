/* SPDX-License-Identifier: MIT
 * BRIDGE.md v1 endpoint agent; all operations run under QEMU BQL.
 * Descriptors come exclusively from completed guest EP0 TRBs.
 */
#include "qemu/osdep.h"
#include "sony-dwc3-bridge.h"
#include "qemu/main-loop.h"
#include "qemu/timer.h"
#include "qemu/notify.h"
#include "qemu/cutils.h"
#include "qobject/qdict.h"
#include "qobject/qjson.h"
#include "qobject/qnum.h"
#include "qobject/qbool.h"
#include "qobject/qstring.h"
#include "qapi/error.h"
#include "system/system.h"
#include <sys/socket.h>
#include <sys/un.h>
#include <fcntl.h>

#define MAX_HEADER 16384u
#define MAX_CLIENTS 16u
#define MAX_TX (2u * SDWC_MAX_URB + 65536u)
#define MAX_TOTAL_TX (16u * SDWC_MAX_URB)
#define DISC_TIMEOUT 2500
#define CLIENT_TIMEOUT 10000
#define FRAME_BUDGET (2u * SDWC_MAX_URB)

typedef struct BridgeClient BridgeClient;
typedef struct BridgeRequest {
    struct BridgeRequest *next;
    BridgeClient *client;
    SonyDWC3Urb urb;
    uint32_t wire_id;
} BridgeRequest;

typedef struct BridgeTx {
    struct BridgeTx *next;
    size_t size, sent;
    uint32_t id;
    uint8_t bytes[];
} BridgeTx;

struct BridgeClient {
    struct BridgeClient *next;
    SonyDWC3Bridge *bridge;
    int fd;
    bool hello, dead, close_after_send;
    char role[10];
    uint8_t prefix[8];
    uint32_t prefix_used, json_len, payload_len, json_used, payload_used;
    char *json;
    uint8_t *payload;
    QDict *header;
    GHashTable *ids;
    uint32_t rx_reserved;
    BridgeRequest *requests;
    unsigned pending;
    uint32_t reserved;
    uint32_t retired[256];
    unsigned retired_next;
    BridgeTx *tx_head, *tx_tail;
    size_t tx_bytes;
    int64_t activity;
};

struct SonyDWC3Bridge {
    SonyDWC3 *core;
    char *run_id, *lease, *qmp_host_path, *socket_path;
    int listener;
    dev_t socket_dev;
    ino_t socket_ino;
    BridgeClient *clients, *import_owner;
    unsigned client_count, request_count;
    uint32_t reserved;
    size_t tx_bytes;
    uint64_t next_id, generation;
    int64_t host_pid;
    int (*apply_vbus)(void *, bool);
    void *opaque;
    QEMUTimer *timer;
    Notifier exit_notifier;
    bool ticking, closing, ready;
    unsigned discovery_stage;
    bool discovery_active, discovery_done;
    int discovery_status;
    uint32_t discovery_actual;
    int64_t discovery_deadline, discovery_retry;
    SonyDWC3Urb discovery;
    uint8_t device[18], config_header[9];
    uint8_t *configuration;
    uint16_t config_length;
    uint32_t endpoints;
    const char *reason;
};

static void client_read(void *opaque);
static void client_write(void *opaque);
static void cleanup_clients(SonyDWC3Bridge *b);

static uint32_t be32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
           (uint32_t)p[2] << 8 | p[3];
}
static void put_be32(uint8_t *p, uint32_t v)
{
    p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v;
}
static uint16_t le16(const uint8_t *p) { return p[0] | (uint16_t)p[1] << 8; }
static int64_t now_ms(void) { return qemu_clock_get_ms(QEMU_CLOCK_REALTIME); }

static bool number(QDict *d, const char *key, uint64_t max, uint64_t *out)
{
    QNum *n = qobject_to(QNum, qdict_get(d, key));
    return n && n->kind != QNUM_DOUBLE && qnum_get_try_uint(n, out) && *out <= max;
}
static bool unscheduled_frame(QDict *d)
{
    QNum *n = qobject_to(QNum, qdict_get(d, "start_frame"));
    int64_t frame;
    return n && n->kind != QNUM_DOUBLE && qnum_get_try_int(n, &frame) &&
           (frame == -1 || frame == 0);
}
static const char *string(QDict *d, const char *key)
{
    QString *s = qobject_to(QString, qdict_get(d, key));
    /* QEMU uses modified UTF-8 for escaped NUL; protocol identities use UTF-8. */
    if (!s || !g_utf8_validate(qstring_get_str(s), -1, NULL)) { return NULL; }
    return qstring_get_str(s);
}
static bool equal(QDict *d, const char *key, const char *expected)
{
    const char *value = string(d, key);
    return value && !strcmp(value, expected);
}
static QDict *response(const char *op, uint32_t id, bool ok)
{
    QDict *d = qdict_new();
    qdict_put_int(d, "version", 1); qdict_put_str(d, "op", op);
    qdict_put_int(d, "id", id); qdict_put_bool(d, "ok", ok);
    return d;
}
static void handlers(BridgeClient *c)
{
    qemu_set_fd_handler(c->fd, c->dead || c->close_after_send ? NULL : client_read,
                        c->dead || !c->tx_head ? NULL : client_write, c);
}
static void dead(BridgeClient *c)
{
    c->dead = true;
    handlers(c);
}
static void send_frame(BridgeClient *c, QDict *d, const uint8_t *data, uint32_t size)
{
    uint64_t id = 0;
    if (!equal(d, "op", "event")) { number(d, "id", UINT32_MAX, &id); }
    GString *json = qobject_to_json(QOBJECT(d));
    qobject_unref(d);
    size_t length = 8 + json->len + size;
    if (c->dead || json->len > MAX_HEADER || size > SDWC_MAX_URB ||
        length > MAX_TX - c->tx_bytes || length > MAX_TOTAL_TX - c->bridge->tx_bytes) {
        g_string_free(json, true); dead(c); return;
    }
    BridgeTx *tx = g_malloc(sizeof(*tx) + length);
    tx->next = NULL; tx->size = length; tx->sent = 0; tx->id = id;
    put_be32(tx->bytes, json->len); put_be32(tx->bytes + 4, size);
    memcpy(tx->bytes + 8, json->str, json->len);
    if (size) { memcpy(tx->bytes + 8 + json->len, data, size); }
    g_string_free(json, true);
    if (c->tx_tail) { c->tx_tail->next = tx; } else { c->tx_head = tx; }
    c->tx_tail = tx; c->tx_bytes += length; c->bridge->tx_bytes += length;
    handlers(c);
}
static void rejected(BridgeClient *c, const char *op, uint32_t id, int error)
{
    QDict *d = response(op, id, false);
    qdict_put_int(d, "status", error);
    qdict_put_str(d, "reason", "unsupported operation or unavailable owned resource");
    send_frame(c, d, NULL, 0);
}
static void retire(BridgeClient *c, uint32_t id)
{
    c->retired[c->retired_next++ % G_N_ELEMENTS(c->retired)] = id;
}
static BridgeRequest *find_request(BridgeClient *c, uint32_t id)
{
    for (BridgeRequest *r = c->requests; r; r = r->next) {
        if (r->wire_id == id) { return r; }
    }
    return NULL;
}
static void release_request(BridgeRequest *r)
{
    BridgeClient *c = r->client;
    BridgeRequest **p = &c->requests;
    while (*p != r) { p = &(*p)->next; }
    *p = r->next;
    c->pending--; c->reserved -= r->urb.length;
    c->bridge->request_count--; c->bridge->reserved -= r->urb.length;
    retire(c, r->wire_id);
    g_free(r->urb.data); g_free(r);
}
static void completed(void *opaque, SonyDWC3Urb *u, int status, uint32_t actual)
{
    BridgeRequest *r = opaque;
    BridgeClient *c = r->client;
    QDict *d = response("complete", r->wire_id, true);
    qdict_put_int(d, "status", status); qdict_put_int(d, "actual_length", actual);
    qdict_put_int(d, "start_frame", 0); qdict_put_int(d, "num_packets", 0);
    qdict_put_int(d, "error_count", 0);
    send_frame(c, d, u->direction ? u->data : NULL, u->direction ? actual : 0);
    release_request(r);
}
static void rx_clear(BridgeClient *c)
{
    c->bridge->reserved -= c->rx_reserved;
    c->rx_reserved = 0;
    g_free(c->json); c->json = NULL;
    g_free(c->payload); c->payload = NULL;
    qobject_unref(c->header); c->header = NULL;
    c->prefix_used = c->json_used = c->payload_used = 0;
    c->json_len = c->payload_len = 0;
}
static void cleanup_clients(SonyDWC3Bridge *b)
{
    BridgeClient **p = &b->clients;
    while (*p) {
        BridgeClient *c = *p;
        if (!c->dead) { p = &c->next; continue; }
        qemu_set_fd_handler(c->fd, NULL, NULL, NULL);
        close(c->fd);
        while (c->requests) {
            BridgeRequest *r = c->requests;
            sony_dwc3_cancel(b->core, r->urb.id);
            release_request(r);
        }
        if (b->import_owner == c) { b->import_owner = NULL; }
        rx_clear(c);
        while (c->tx_head) {
            BridgeTx *tx = c->tx_head;
            c->tx_head = tx->next;
            b->tx_bytes -= tx->size - tx->sent;
            g_free(tx);
        }
        g_hash_table_unref(c->ids);
        *p = c->next; b->client_count--; g_free(c);
    }
}
static void client_write(void *opaque)
{
    BridgeClient *c = opaque;
    size_t budget = FRAME_BUDGET;
    while (c->tx_head && budget) {
        BridgeTx *tx = c->tx_head;
        size_t count = MIN(budget, tx->size - tx->sent);
        ssize_t n = send(c->fd, tx->bytes + tx->sent, count, MSG_NOSIGNAL);
        if (n < 0 && errno == EINTR) { continue; }
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) { break; }
        if (n <= 0) { dead(c); break; }
        tx->sent += n; c->tx_bytes -= n; c->bridge->tx_bytes -= n;
        budget -= n; c->activity = now_ms();
        if (tx->sent == tx->size) {
            c->tx_head = tx->next;
            if (!c->tx_head) { c->tx_tail = NULL; }
            if (tx->id) { g_hash_table_remove(c->ids, GUINT_TO_POINTER(tx->id)); }
            g_free(tx);
        }
    }
    if (!c->tx_head && c->close_after_send) { dead(c); }
    handlers(c);
    cleanup_clients(c->bridge);
}

static void discovery_complete(void *opaque, SonyDWC3Urb *u, int status, uint32_t actual)
{
    SonyDWC3Bridge *b = opaque;
    b->discovery_active = false; b->discovery_done = true;
    b->discovery_status = status; b->discovery_actual = actual;
}
static void discovery_cancel(SonyDWC3Bridge *b)
{
    if (b->discovery_active) { sony_dwc3_cancel(b->core, b->discovery.id); }
    b->discovery_active = b->discovery_done = false;
    g_free(b->discovery.data); memset(&b->discovery, 0, sizeof(b->discovery));
    b->discovery_stage = 0;
}
static void invalidate(SonyDWC3Bridge *b, const char *kind, const char *reason)
{
    discovery_cancel(b);
    b->ready = false; b->reason = reason; b->endpoints = 0;
    g_clear_pointer(&b->configuration, g_free); b->config_length = 0;
    b->discovery_retry = now_ms() + 50;
    for (BridgeClient *c = b->clients; c; c = c->next) {
        if (!c->hello || strcmp(c->role, "usbip") || c->dead) { continue; }
        while (c->requests) {
            sony_dwc3_cancel(b->core, c->requests->urb.id);
            release_request(c->requests);
        }
        QDict *d = response("event", 1, true);
        qdict_put_str(d, "kind", kind); qdict_put_str(d, "reason", reason);
        send_frame(c, d, NULL, 0);
        c->close_after_send = true; handlers(c);
    }
}
static bool configuration_valid(const uint8_t *raw, unsigned size)
{
    if (size < 9 || raw[0] != 9 || raw[1] != 2 || le16(raw + 2) != size ||
        !raw[4] || !raw[5] || !(raw[7] & 0x80)) { return false; }
    bool interfaces[256] = {0};
    unsigned count = 0, offset = 9, expected = 0, endpoints = 0, seen_ep = 0;
    bool current = false, valid = true;
    GHashTable *alternates = g_hash_table_new(g_direct_hash, g_direct_equal);
    while (offset < size) {
        unsigned len = raw[offset], type = offset + 1 < size ? raw[offset + 1] : 0;
        if (len < 2 || len > size - offset) { valid = false; break; }
        const uint8_t *p = raw + offset;
        if (type == 4) {
            unsigned key = len >= 9 ? ((p[2] << 8) | p[3]) + 1 : 0;
            if (!key || p[2] >= raw[4] || (current && endpoints != expected) ||
                g_hash_table_contains(alternates, GUINT_TO_POINTER(key))) {
                valid = false; break;
            }
            g_hash_table_add(alternates, GUINT_TO_POINTER(key));
            current = true; expected = p[4]; endpoints = seen_ep = 0;
            if (!p[3]) { interfaces[p[2]] = true; count++; }
        } else if (type == 5) {
            if (len < 7 || !current || (p[2] & 0x70) || !(p[2] & 15) ||
                (p[3] & 3) < 2 || (p[3] & ~3) ||
                !le16(p + 4) || le16(p + 4) > ((p[3] & 3) == 2 ? 512 : 1024)) {
                valid = false; break;
            }
            unsigned ep = (p[2] & 15) * 2 + !!(p[2] & 0x80);
            if (seen_ep & (1u << ep)) { valid = false; break; }
            seen_ep |= 1u << ep; endpoints++;
        } else if (type == 2 || type == 48) {
            valid = false; break;
        }
        offset += len;
    }
    if (!current || endpoints != expected || count != raw[4]) { valid = false; }
    for (unsigned i = 0; i < count; i++) { valid &= interfaces[i]; }
    g_hash_table_unref(alternates);
    return valid;
}
static void discovery_fail(SonyDWC3Bridge *b, const char *reason)
{
    discovery_cancel(b); b->reason = reason; b->ready = false;
    b->discovery_retry = now_ms() + 1000;
}
static void discovery_submit(SonyDWC3Bridge *b, unsigned stage, unsigned length)
{
    SonyDWC3Urb *u = &b->discovery;
    g_free(u->data); memset(u, 0, sizeof(*u));
    u->id = ++b->next_id; u->direction = 1; u->length = length;
    u->flags = 1; u->data = g_malloc0(length);
    u->setup[0] = 0x80; u->setup[1] = 6; u->setup[3] = stage == 1 ? 1 : 2;
    u->setup[6] = length; u->setup[7] = length >> 8;
    u->complete = discovery_complete; u->opaque = b;
    b->discovery_stage = stage; b->discovery_active = true;
    b->discovery_done = false; b->discovery_deadline = now_ms() + DISC_TIMEOUT;
    int rc = sony_dwc3_submit(b->core, u);
    if (rc) { b->discovery_active = false; discovery_fail(b, "guest EP0 discovery submit blocked"); }
}
static void discovery_tick(SonyDWC3Bridge *b)
{
    if (b->discovery_active && now_ms() > b->discovery_deadline) {
        discovery_fail(b, "guest EP0 descriptor request timed out; reset may be required");
    }
    if (!b->discovery_done) { return; }
    unsigned stage = b->discovery_stage;
    b->discovery_done = false;
    if (b->discovery_status || b->discovery_actual != b->discovery.length) {
        discovery_fail(b, "guest EP0 descriptor request failed or returned a short descriptor"); return;
    }
    const uint8_t *p = b->discovery.data;
    if (stage == 1) {
        if (p[0] != 18 || p[1] != 1 || !p[17] ||
            (p[7] != 8 && p[7] != 16 && p[7] != 32 && p[7] != 64) ||
            le16(p + 2) < 0x100 || le16(p + 2) > 0x210) {
            discovery_fail(b, "guest device descriptor exceeds USB2 functional profile"); return;
        }
        memcpy(b->device, p, 18); discovery_submit(b, 2, 9);
    } else if (stage == 2) {
        if (p[0] != 9 || p[1] != 2 || le16(p + 2) < 9 || !p[5]) {
            discovery_fail(b, "guest configuration header invalid"); return;
        }
        memcpy(b->config_header, p, 9); discovery_submit(b, 3, le16(p + 2));
    } else {
        if (memcmp(p, b->config_header, 9) || !configuration_valid(p, b->discovery_actual)) {
            discovery_fail(b, "guest configuration tree invalid or unsupported"); return;
        }
        b->config_length = b->discovery_actual;
        b->endpoints = 3;
        for (unsigned i = 9; i < b->config_length; i += p[i]) {
            /* The guest's DALEPENA/configuration gates the active alternate. */
            if (p[i + 1] == 5) {
                b->endpoints |= 1u << ((p[i + 2] & 15) * 2 + !!(p[i + 2] & 0x80));
            }
        }
        g_free(b->configuration); b->configuration = g_memdup2(p, b->config_length);
        discovery_cancel(b); b->ready = true; b->reason = NULL;
    }
}

static bool valid_submit(BridgeClient *c, QDict *d, uint32_t payload)
{
    uint64_t direction, endpoint, length, value;
    const char *setup = string(d, "setup");
    if (strcmp(c->role, "usbip") || !c->bridge->ready ||
        !number(d, "direction", 1, &direction) || !number(d, "endpoint", 15, &endpoint) ||
        !number(d, "transfer_length", SDWC_MAX_URB, &length) ||
        !number(d, "seqnum", UINT32_MAX, &value) ||
        !number(d, "devid", UINT32_MAX, &value) || value != 0x10001 ||
        !number(d, "transfer_flags", UINT32_MAX, &value) ||
        !unscheduled_frame(d) ||
        !number(d, "num_packets", 0, &value) ||
        !number(d, "interval", INT32_MAX, &value) ||
        !setup || strlen(setup) != 16 || payload != (direction ? 0 : length)) { return false; }
    for (unsigned i = 0; i < 16; i++) {
        if (!g_ascii_isdigit(setup[i]) && (setup[i] < 'a' || setup[i] > 'f')) { return false; }
    }
    if (!(c->bridge->endpoints & (1u << (endpoint * 2 + direction)))) { return false; }
    if (!endpoint) {
        uint8_t setup_bytes[8];
        for (unsigned i = 0; i < 8; i++) {
            setup_bytes[i] = g_ascii_xdigit_value(setup[i * 2]) * 16 + g_ascii_xdigit_value(setup[i * 2 + 1]);
        }
        if (le16(setup_bytes + 6) != length || (length && (setup_bytes[0] >> 7) != direction)) {
            return false;
        }
    }
    if (c->pending >= SDWC_MAX_URBS || c->bridge->request_count >= SDWC_MAX_URBS ||
        length > SDWC_MAX_BYTES - c->bridge->reserved) { return false; }
    c->rx_reserved = length; c->bridge->reserved += length;
    return true;
}
static bool validate_header(BridgeClient *c)
{
    uint64_t version, id, n;
    if (memchr(c->json, 0, c->json_len) || !g_utf8_validate(c->json, c->json_len, NULL)) { return false; }
    bool quoted = false, escaped = false;
    for (unsigned i = 0; i < c->json_len; i++) {
        char ch = c->json[i];
        if (escaped) {
            if (ch != '"' && ch != '\\' && ch != '/' && !strchr("bfnrtu", ch)) { return false; }
            escaped = false; continue;
        }
        if (quoted && ch == '\\') { escaped = true; continue; }
        if (ch == '"') { quoted = !quoted; }
        if (!quoted && ch == '\'') { return false; } /* QEMU's single-quote extension. */
    }
    Error *error = NULL;
    QObject *object = qobject_from_json(c->json, &error);
    error_free(error);
    c->header = qobject_to(QDict, object);
    if (!c->header) { qobject_unref(object); return false; }
    QDict *d = c->header;
    const char *op = string(d, "op");
    if (!number(d, "version", 1, &version) || version != 1 || !op ||
        !number(d, "id", UINT32_MAX, &id) || !id ||
        g_hash_table_size(c->ids) >= 72 ||
        g_hash_table_contains(c->ids, GUINT_TO_POINTER((uint32_t)id))) { return false; }
    /* Requests are flat. Reject unknown nested/numeric values as well. */
    for (const QDictEntry *e = qdict_first(d); e; e = qdict_next(d, e)) {
        if (!g_utf8_validate(qdict_entry_key(e), -1, NULL)) { return false; }
        QObject *v = qdict_entry_value(e);
        QNum *num = qobject_to(QNum, v);
        if (num && num->kind == QNUM_DOUBLE) { return false; }
        if (!num && !qobject_to(QString, v) && !qobject_to(QBool, v)) { return false; }
    }
    if (!c->hello) {
        return !c->payload_len && !strcmp(op, "hello");
    }
    if (!strcmp(op, "submit")) { return valid_submit(c, d, c->payload_len); }
    if (c->payload_len) { return false; }
    if (!strcmp(op, "describe")) { return true; }
    if (!strcmp(op, "cancel")) { return !strcmp(c->role, "usbip") && number(d, "target", UINT32_MAX, &n) && n; }
    if (!strcmp(op, "reset")) { return !strcmp(c->role, "usbip"); }
    if (!strcmp(op, "vbus")) { return !strcmp(c->role, "control") && qobject_to(QBool, qdict_get(d, "present")); }
    return false;
}
static void describe(BridgeClient *c, uint32_t id)
{
    SonyDWC3Bridge *b = c->bridge;
    QDict *d = response("describe", id, true);
    if (!b->ready || !sony_dwc3_ready(b->core)) {
        if (!b->discovery_stage && now_ms() >= b->discovery_retry &&
            sony_dwc3_ready(b->core) && (!b->import_owner || (b->import_owner == c && !c->pending))) {
            discovery_submit(b, 1, 18);
        }
        qdict_put_bool(d, "ready", false);
        qdict_put_str(d, "reason", b->reason ? b->reason : "guest EP0 descriptor discovery pending");
        send_frame(c, d, NULL, 0); return;
    }
    QDict *device = qdict_new();
    qdict_put_str(device, "busid", "dwc3-1"); qdict_put_int(device, "busnum", 1);
    qdict_put_int(device, "devnum", 1); qdict_put_int(device, "speed", 3);
    qdict_put_int(device, "configuration_value", b->configuration[5]);
    qdict_put_str(device, "descriptor_source", "guest-ep0");
    qdict_put_bool(d, "ready", true); qdict_put(d, "device", device);
    uint8_t *raw = g_malloc(18 + b->config_length);
    memcpy(raw, b->device, 18); memcpy(raw + 18, b->configuration, b->config_length);
    send_frame(c, d, raw, 18 + b->config_length); g_free(raw);
}
static int bridge_semantic_flags(uint32_t flags, uint32_t *semantic)
{
    /* 0x00ff0000: Linux HCD DMA/setup mapping metadata, not gadget or wire semantics. */
    *semantic = flags & ~(0x4u | 0x20u | 0x80u | 0x100u | 0x200u | 0x00ff0000u);
    return (*semantic & ~(1u | 0x40u)) ? -EOPNOTSUPP : 0;
}
static void dispatch(BridgeClient *c)
{
    SonyDWC3Bridge *b = c->bridge;
    QDict *d = c->header;
    const char *op = string(d, "op");
    uint64_t id;
    number(d, "id", UINT32_MAX, &id);
    if (!c->hello) {
        uint64_t pid;
        const char *role = string(d, "role");
        if (!equal(d, "run_id", b->run_id) || !equal(d, "lease", b->lease) ||
            !equal(d, "qmp_path", b->qmp_host_path) || !role ||
            (strcmp(role, "control") && strcmp(role, "discovery") && strcmp(role, "usbip")) ||
            !number(d, "vm_pid", INT32_MAX, &pid) || !pid ||
            (b->host_pid && b->host_pid != pid) ||
            (!strcmp(role, "usbip") && b->import_owner)) { dead(c); return; }
        b->host_pid = pid; c->hello = true; pstrcpy(c->role, sizeof(c->role), role);
        if (!strcmp(role, "usbip")) { b->import_owner = c; }
        QDict *reply = response("hello", id, true);
        qdict_put_str(reply, "run_id", b->run_id); qdict_put_str(reply, "lease", b->lease);
        qdict_put_str(reply, "qmp_path", b->qmp_host_path);
        qdict_put_int(reply, "vm_pid", pid); qdict_put_str(reply, "role", role);
        send_frame(c, reply, NULL, 0);
    } else if (!strcmp(op, "describe")) {
        describe(c, id);
    } else if (!strcmp(op, "submit")) {
        uint64_t ep, in, length, flags;
        number(d, "endpoint", 15, &ep); number(d, "direction", 1, &in);
        number(d, "transfer_length", SDWC_MAX_URB, &length);
        number(d, "transfer_flags", UINT32_MAX, &flags);
        /* DMA mapping, buffer ownership, direction and interrupt hint are host bookkeeping. */
        uint32_t semantic;
        if (bridge_semantic_flags((uint32_t)flags, &semantic)) {
            QDict *reply = response("complete", id, true);
            qdict_put_int(reply, "status", -EOPNOTSUPP); qdict_put_int(reply, "actual_length", 0);
            qdict_put_int(reply, "start_frame", 0); qdict_put_int(reply, "num_packets", 0);
            qdict_put_int(reply, "error_count", 0); send_frame(c, reply, NULL, 0); retire(c, id); return;
        }
        BridgeRequest *r = g_new0(BridgeRequest, 1);
        r->client = c; r->wire_id = id;
        r->urb.id = ++b->next_id; r->urb.endpoint = ep; r->urb.direction = in;
        r->urb.length = length; r->urb.flags = semantic;
        r->urb.data = g_malloc0(MAX(length, 1));
        if (!in && length) { memcpy(r->urb.data, c->payload, length); }
        const char *setup = string(d, "setup");
        for (unsigned i = 0; i < 8; i++) {
            r->urb.setup[i] = g_ascii_xdigit_value(setup[i * 2]) * 16 + g_ascii_xdigit_value(setup[i * 2 + 1]);
        }
        r->urb.complete = completed; r->urb.opaque = r;
        r->next = c->requests; c->requests = r;
        c->pending++; c->reserved += length; b->request_count++;
        c->rx_reserved = 0; /* Reservation moves to the live URB before synchronous callback. */
        int rc = sony_dwc3_submit(b->core, &r->urb);
        if (rc) { completed(r, &r->urb, rc, 0); }
    } else if (!strcmp(op, "cancel")) {
        uint64_t target;
        number(d, "target", UINT32_MAX, &target);
        BridgeRequest *r = find_request(c, target);
        bool known = r != NULL;
        if (r) {
            int rc = sony_dwc3_cancel(b->core, r->urb.id);
            if (rc) { dead(c); return; }
            release_request(r);
            g_hash_table_remove(c->ids, GUINT_TO_POINTER((uint32_t)target));
        } else {
            for (unsigned i = 0; i < G_N_ELEMENTS(c->retired); i++) { known |= c->retired[i] == target; }
        }
        if (!known) { dead(c); return; }
        QDict *reply = response("cancelled", id, true);
        qdict_put_int(reply, "target", target); qdict_put_int(reply, "status", 0);
        send_frame(c, reply, NULL, 0);
    } else if (!strcmp(op, "reset")) {
        /* The discovery cache identifies this cable generation; a bus reset
         * keeps that identity but must not interrupt an in-flight probe. */
        if (b->discovery_active || b->discovery_done) {
            rejected(c, op, id, -EBUSY); return;
        }
        int rc = sony_dwc3_bus_reset(b->core);
        if (rc) { rejected(c, op, id, rc); }
        else { send_frame(c, response(op, id, true), NULL, 0); }
    } else if (!strcmp(op, "vbus")) {
        bool present = qbool_get_bool(qobject_to(QBool, qdict_get(d, "present")));
        int rc = b->apply_vbus ? b->apply_vbus(b->opaque, present) : -EOPNOTSUPP;
        if (rc) { rejected(c, op, id, rc); }
        else {
            QDict *reply = response(op, id, true);
            qdict_put_bool(reply, "present", present); send_frame(c, reply, NULL, 0);
        }
    }
}
static void client_read(void *opaque)
{
    BridgeClient *c = opaque;
    SonyDWC3Bridge *b = c->bridge;
    size_t budget = FRAME_BUDGET;
    while (!c->dead && !c->close_after_send && budget) {
        uint8_t *dest;
        uint32_t *used, length;
        if (c->prefix_used < 8) {
            dest = c->prefix; used = &c->prefix_used; length = 8;
        } else if (c->json_used < c->json_len) {
            dest = (uint8_t *)c->json; used = &c->json_used; length = c->json_len;
        } else {
            dest = c->payload; used = &c->payload_used; length = c->payload_len;
        }
        if (*used < length) {
            ssize_t n = recv(c->fd, dest + *used, MIN(budget, length - *used), 0);
            if (n < 0 && errno == EINTR) { continue; }
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) { break; }
            if (n <= 0) { dead(c); break; }
            *used += n; budget -= n; c->activity = now_ms();
            if (*used < length) { continue; }
        }
        if (c->prefix_used == 8 && !c->json) {
            c->json_len = be32(c->prefix); c->payload_len = be32(c->prefix + 4);
            if (!c->json_len || c->json_len > MAX_HEADER || c->payload_len > SDWC_MAX_URB) { dead(c); break; }
            c->json = g_malloc0(c->json_len + 1);
        }
        if (c->json_used == c->json_len && !c->header) {
            if (!validate_header(c)) { dead(c); break; }
            uint64_t id;
            number(c->header, "id", UINT32_MAX, &id);
            g_hash_table_add(c->ids, GUINT_TO_POINTER((uint32_t)id));
            if (c->payload_len) { c->payload = g_malloc(c->payload_len); }
        }
        if (c->header && c->payload_used == c->payload_len) {
            dispatch(c); rx_clear(c);
        }
    }
    sony_dwc3_bridge_tick(b);
}

static void accept_client(void *opaque)
{
    SonyDWC3Bridge *b = opaque;
    for (unsigned i = 0; i < MAX_CLIENTS; i++) {
        int fd = accept4(b->listener, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
        if (fd < 0) { if (errno == EINTR) { continue; } break; }
        struct ucred peer;
        socklen_t length = sizeof(peer);
        if (b->client_count == MAX_CLIENTS || getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &length) ||
            length != sizeof(peer) || peer.uid != getuid()) { close(fd); continue; }
        BridgeClient *c = g_new0(BridgeClient, 1);
        c->bridge = b; c->fd = fd; c->activity = now_ms();
        c->ids = g_hash_table_new(g_direct_hash, g_direct_equal);
        c->next = b->clients; b->clients = c; b->client_count++;
        handlers(c);
    }
}
bool sony_dwc3_bridge_state(const SonyDWC3Bridge *b, SonyDWC3BridgeState *out)
{
    if (!b || !out) { return false; }
    *out = (SonyDWC3BridgeState) {
        .discovery_stage = b->discovery_stage, .pending = b->request_count,
        .discovery_active = b->discovery_active, .discovery_done = b->discovery_done,
        .ready = b->ready, .import_owner = b->import_owner != NULL,
    };
    return true;
}
void sony_dwc3_bridge_tick(SonyDWC3Bridge *b)
{
    if (!b || b->ticking || b->closing) { return; }
    b->ticking = true;
    if (b->generation != b->core->cable_generation) {
        b->generation = b->core->cable_generation;
        invalidate(b, b->core->connected ? "device_changed" : "disconnect", "guest controller cable generation changed");
    }
    sony_dwc3_pump(b->core);
    discovery_tick(b);
    for (BridgeClient *c = b->clients; c; c = c->next) {
        if ((!c->hello || c->prefix_used || c->tx_bytes) && now_ms() - c->activity > CLIENT_TIMEOUT) { dead(c); }
    }
    cleanup_clients(b);
    b->ticking = false;
    timer_mod(b->timer, now_ms() + 10);
}
static void timer_tick(void *opaque) { sony_dwc3_bridge_tick(opaque); }
static void unlink_owned_socket(SonyDWC3Bridge *b)
{
    struct stat st;
    if (b->socket_ino && !lstat(b->socket_path, &st) && S_ISSOCK(st.st_mode) &&
        st.st_uid == getuid() && st.st_dev == b->socket_dev && st.st_ino == b->socket_ino) {
        unlink(b->socket_path);
    }
}
static void exit_notify(Notifier *n, void *data)
{
    SonyDWC3Bridge *b = container_of(n, SonyDWC3Bridge, exit_notifier);
    unlink_owned_socket(b);
}
SonyDWC3Bridge *sony_dwc3_bridge_new(SonyDWC3 *core, const SonyDWC3BridgeConfig *cfg,
    int (*apply_vbus)(void *, bool), void *opaque, Error **errp)
{
    struct sockaddr_un addr = { .sun_family = AF_UNIX };
    struct stat st;
    if (!cfg->run_id || !*cfg->run_id || strlen(cfg->run_id) > 96 ||
        !cfg->lease || strlen(cfg->lease) < 32 || strlen(cfg->lease) > 128 ||
        !cfg->qmp_host_path || cfg->qmp_host_path[0] != '/' ||
        strlen(cfg->qmp_host_path) > 4096 || !g_utf8_validate(cfg->qmp_host_path, -1, NULL) ||
        !cfg->socket_path || cfg->socket_path[0] != '/' ||
        strlen(cfg->socket_path) >= sizeof(addr.sun_path)) {
        error_setg(errp, "DWC3 bridge requires prebound run/lease/host-QMP and a short absolute owned socket path"); return NULL;
    }
    for (const char *p = cfg->run_id; *p; p++) {
        if (!g_ascii_isalnum(*p) && *p != '_' && *p != '.' && *p != '-') {
            error_setg(errp, "DWC3 bridge run ID is not a bounded run identifier"); return NULL;
        }
    }
    for (const char *p = cfg->lease; *p; p++) {
        if ((unsigned char)*p < 33 || (unsigned char)*p > 126) {
            error_setg(errp, "DWC3 bridge lease must be bounded printable ASCII"); return NULL;
        }
    }
    char *parent = g_path_get_dirname(cfg->socket_path);
    bool safe = !lstat(parent, &st) && S_ISDIR(st.st_mode) && st.st_uid == getuid() && !(st.st_mode & 0022);
    g_free(parent);
    if (!safe) { error_setg(errp, "DWC3 bridge socket parent is not an owned protected directory"); return NULL; }
    SonyDWC3Bridge *b = g_new0(SonyDWC3Bridge, 1);
    b->core = core; b->listener = -1;
    b->run_id = g_strdup(cfg->run_id); b->lease = g_strdup(cfg->lease);
    b->qmp_host_path = g_strdup(cfg->qmp_host_path); b->socket_path = g_strdup(cfg->socket_path);
    b->apply_vbus = apply_vbus; b->opaque = opaque;
    b->generation = core->cable_generation;
    b->reason = "original guest has not produced EP0 descriptors";
    b->listener = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    pstrcpy(addr.sun_path, sizeof(addr.sun_path), cfg->socket_path);
    if (b->listener < 0 || bind(b->listener, (struct sockaddr *)&addr, sizeof(addr))) {
        error_setg_errno(errp, errno, "DWC3 bridge bind failed (existing paths are never replaced)");
        sony_dwc3_bridge_free(b); return NULL;
    }
    if (lstat(b->socket_path, &st) || !S_ISSOCK(st.st_mode) || st.st_uid != getuid()) {
        error_setg(errp, "DWC3 bridge bound socket identity unavailable"); sony_dwc3_bridge_free(b); return NULL;
    }
    b->socket_dev = st.st_dev; b->socket_ino = st.st_ino;
    if (chmod(b->socket_path, 0600) || listen(b->listener, MAX_CLIENTS)) {
        error_setg_errno(errp, errno, "DWC3 bridge socket permissions/listen failed"); sony_dwc3_bridge_free(b); return NULL;
    }
    b->timer = timer_new_ms(QEMU_CLOCK_REALTIME, timer_tick, b);
    b->exit_notifier.notify = exit_notify; qemu_add_exit_notifier(&b->exit_notifier);
    qemu_set_fd_handler(b->listener, accept_client, NULL, b);
    timer_mod(b->timer, now_ms() + 10);
    return b;
}
void sony_dwc3_bridge_free(SonyDWC3Bridge *b)
{
    if (!b) { return; }
    b->closing = true;
    if (b->timer) {
        timer_del(b->timer); timer_free(b->timer);
        qemu_remove_exit_notifier(&b->exit_notifier);
    }
    if (b->listener >= 0) {
        qemu_set_fd_handler(b->listener, NULL, NULL, NULL); close(b->listener);
    }
    for (BridgeClient *c = b->clients; c; c = c->next) { dead(c); }
    cleanup_clients(b); discovery_cancel(b); unlink_owned_socket(b);
    g_free(b->configuration); g_free(b->run_id); g_free(b->lease);
    g_free(b->qmp_host_path); g_free(b->socket_path); g_free(b);
}
