/* SPDX-License-Identifier: MIT */
/* Host component tests: the real bridge is included, with only pin/pagemap/
 * random/copy-fault boundaries replaced under its explicit host-test guard. */
#define FCAM_HOST_TEST 1
#define FCAM_TEST_WAIT_NS UINT64_C(300000000)
#include "functional-camera-bridge.c"
#include <assert.h>
#include <stdlib.h>
#include <sys/wait.h>

static const char *scenario;
static int pins, unpins, cancelled, released, reentry_seen, readback_closed, pagemap_reads;
static unsigned char *caller_output;
static const size_t encoded_size = FCAM_DATA_BYTES + 13017;
static uint64_t cursor;
static const struct fcam_native_origin origin = {0x1001, 0x2002, 0x3003, 144, UINT64_C(0x12345678)};

int fcam_test_mlock(const void *p, size_t n) {
    assert(p && n == FCAM_MAILBOX_BYTES);
    if (!strcmp(scenario, "pin")) { errno = EPERM; return -1; }
    ++pins; return 0;
}
int fcam_test_munlock(const void *p, size_t n) {
    assert(p && n == FCAM_MAILBOX_BYTES); ++unpins; return 0;
}
int fcam_test_pagemap(const void *p, uint64_t *out) {
    assert(p);
    ++pagemap_reads;
    for (unsigned i = 0; i < FCAM_MAILBOX_PAGES; ++i) out[i] = RAM_FIRST + (2 * (FCAM_MAILBOX_PAGES - i) + 1) * FCAM_PAGE_BYTES;
    if (!strcmp(scenario, "pfnchanged") && pagemap_reads > 1) out[0] += FCAM_PAGE_BYTES;
    if (!strcmp(scenario, "duplicate")) out[3] = out[2];
    if (!strcmp(scenario, "pfnzero")) out[0] = 0;
    if (!strcmp(scenario, "pfnrange")) out[0] = RAM_END;
    if (!strcmp(scenario, "pfnalign")) ++out[0];
    if (!strcmp(scenario, "pagemap")) { errno = EACCES; return -1; }
    return 0;
}
int fcam_test_random(uint64_t *out) { *out = !strcmp(scenario, "noncezero") ? 0 : UINT64_C(0x1234fedc9876abcd); return 0; }
void fcam_test_after_copy(void *p, size_t n) {
    if (((!strcmp(scenario, "readback") || !strcmp(scenario, "bitwidth-copy") ||
          !strcmp(scenario, "stillformat-copy")) && n) || (!strcmp(scenario, "startup-copy") && n == 192))
        ((unsigned char *)p)[n / 2] ^= 0x80;
}
static unsigned char encoded_byte(size_t n) { return (unsigned char)((n * 73 + n / 251 + 17) & 255); }
static void record_test(const char *tag, const char *text) {
    if (!strcmp(tag, "FUNCTIONAL_CAMERA_MAILBOX ")) {
        assert(strstr(text, "phys0=") && strstr(text, "pages=") && strstr(text, "version=1"));
        assert(fcam_bridge_call(NULL, FCAM_OP_STATE, NULL, 0, NULL, 0, NULL) == -EDEADLK);
        ++reentry_seen;
    }
    if (!strcmp(tag, "FUNCTIONAL_CAMERA_TRANSFER ") && strstr(text, "readback_closed=1")) ++readback_closed;
}
static void sleep_short(void) { const struct timespec t = {0, 100000}; nanosleep(&t, NULL); }
static void state_reply(void) {
    memset(mailbox + FCAM_HEADER_BYTES, 0, FCAM_STATE_BYTES);
    put32(mailbox + FCAM_HEADER_BYTES, FCAM_ABI_VERSION);
    put64(mailbox + FCAM_HEADER_BYTES + FCAM_S_INSTANCE, nonce);
    put32(mailbox + FCAM_H_RESPONSE_BYTES, FCAM_STATE_BYTES);
}
static void *server(void *unused) {
    (void)unused;
    uint64_t last = 0;
    for (;;) {
        uint32_t status = status_load();
        if (status == FCAM_STATUS_CLOSED) { status_store(FCAM_STATUS_DETACHED); return NULL; }
        if (status != FCAM_STATUS_REQUEST || get64(mailbox + FCAM_H_SEQUENCE) == last) { sleep_short(); continue; }
        last = get64(mailbox + FCAM_H_SEQUENCE);
        uint32_t op = get32(mailbox + FCAM_H_OPCODE);
        assert(get32(mailbox + FCAM_H_FLAGS) == 0);
        assert(get64(mailbox + FCAM_H_REQUEST_FNV) == fnv(mailbox + FCAM_HEADER_BYTES, get32(mailbox + FCAM_H_REQUEST_BYTES)));
        if (!strcmp(scenario, "lateclose")) {
            const struct timespec pause = {0, 420000000}; nanosleep(&pause, NULL);
            assert(status_load() == FCAM_STATUS_CLOSED);
            status_store(FCAM_STATUS_DETACHED); return NULL;
        }
        put32(mailbox + FCAM_H_RESPONSE_BYTES, 0); put32(mailbox + FCAM_H_ERROR, 0);
        memset(mailbox + FCAM_H_RESULT_TOTAL, 0, 24);
        if (op == FCAM_OP_INIT || op == FCAM_OP_STATE || op == FCAM_OP_CANCEL) {
            if (op == FCAM_OP_CANCEL) ++cancelled;
            state_reply();
        } else if (op == FCAM_OP_VDF_PATH || op == FCAM_OP_VDF_ZEBRA || op == FCAM_OP_VDF_LAYOUT ||
                   op == FCAM_OP_VDF_DISPLAY_CONFIG || op == FCAM_OP_BB_STARTUP_CONFIG || op == FCAM_OP_HISTOGRAM) {
            const unsigned int input_bytes = op == FCAM_OP_VDF_PATH ? FCAM_VDF_INPUT_BYTES :
                op == FCAM_OP_VDF_ZEBRA ? FCAM_ZEBRA_INPUT_BYTES :
                op == FCAM_OP_VDF_LAYOUT ? FCAM_LAYOUT_INPUT_BYTES :
                op == FCAM_OP_BB_STARTUP_CONFIG ? FCAM_BB_INPUT_BYTES :
                op == FCAM_OP_HISTOGRAM ? FCAM_HIST_INPUT_BYTES : FCAM_DISPLAY_INPUT_BYTES;
            const unsigned int result_bytes = op == FCAM_OP_VDF_PATH ? FCAM_VDF_RESULT_BYTES :
                op == FCAM_OP_VDF_ZEBRA ? FCAM_ZEBRA_RESULT_BYTES :
                op == FCAM_OP_VDF_LAYOUT ? FCAM_LAYOUT_RESULT_BYTES :
                op == FCAM_OP_BB_STARTUP_CONFIG ? FCAM_BB_RESULT_BYTES :
                op == FCAM_OP_HISTOGRAM ? FCAM_HIST_RESULT_BYTES : FCAM_DISPLAY_RESULT_BYTES;
            unsigned char config[FCAM_LAYOUT_INPUT_BYTES] = {0};
            memcpy(config, mailbox + FCAM_HEADER_BYTES, input_bytes);
            memset(mailbox + FCAM_HEADER_BYTES, 0, result_bytes);
            put32(mailbox + FCAM_HEADER_BYTES + FCAM_VDF_R_ABI, FCAM_ABI_VERSION);
            put32(mailbox + FCAM_HEADER_BYTES + FCAM_VDF_R_BYTES, result_bytes);
            put64(mailbox + FCAM_HEADER_BYTES + FCAM_VDF_R_INSTANCE, nonce);
            memcpy(mailbox + FCAM_HEADER_BYTES + (op == FCAM_OP_VDF_PATH ? FCAM_VDF_R_CONFIG : FCAM_ZEBRA_R_CONFIG), config, input_bytes);
            if (op == FCAM_OP_BB_STARTUP_CONFIG || op == FCAM_OP_HISTOGRAM)
                put32(mailbox + FCAM_HEADER_BYTES + FCAM_VDF_R_CLASS, op == FCAM_OP_BB_STARTUP_CONFIG ? 5 : 6);
            if (strstr(scenario, "badclass")) put32(mailbox + FCAM_HEADER_BYTES + FCAM_VDF_R_CLASS, 0);
            if (strstr(scenario, "badinstance")) put64(mailbox + FCAM_HEADER_BYTES + FCAM_VDF_R_INSTANCE, nonce + 1);
            if (strstr(scenario, "badreserved")) mailbox[FCAM_HEADER_BYTES + FCAM_VDF_R_RESERVED] = 1;
            put32(mailbox + FCAM_H_RESPONSE_BYTES, strstr(scenario, "badsize") ? result_bytes - 1 : result_bytes);
        } else if (op == FCAM_OP_STILL || op == FCAM_OP_READ_RESULT) {
            if (op == FCAM_OP_STILL) cursor = 0;
            else {
                assert(get64(mailbox + FCAM_HEADER_BYTES) == 77);
                assert(get64(mailbox + FCAM_HEADER_BYTES + 8) == cursor);
            }
            if (!strcmp(scenario, "partial") && op == FCAM_OP_READ_RESULT) {
                put32(mailbox + FCAM_H_ERROR, (uint32_t)-EIO);
            } else {
                size_t used = encoded_size - (size_t)cursor;
                if (used > FCAM_DATA_BYTES) used = FCAM_DATA_BYTES;
                if (!strcmp(scenario, "shortchunk")) --used;
                for (size_t i = 0; i < used; ++i) mailbox[FCAM_HEADER_BYTES + i] = encoded_byte((size_t)cursor + i);
                put32(mailbox + FCAM_H_RESPONSE_BYTES, (uint32_t)used);
                put64(mailbox + FCAM_H_RESULT_TOTAL, encoded_size);
                put64(mailbox + FCAM_H_RESULT_OFFSET, cursor);
                put64(mailbox + FCAM_H_RESULT_TOKEN, 77);
                cursor += used;
            }
        } else if (op == FCAM_OP_RELEASE_RESULT) {
            assert(cursor == encoded_size);
            assert(get64(mailbox + FCAM_HEADER_BYTES) == 77);
            assert(get64(mailbox + FCAM_HEADER_BYTES + 8) == destination_fnv(caller_output, encoded_size));
            for (size_t i = 0; i < encoded_size; ++i) assert(caller_output[i] == encoded_byte(i));
            ++released;
            if (!strcmp(scenario, "latebuffer")) caller_output[encoded_size - 1] ^= 0x40;
        } else abort();
        size_t used = get32(mailbox + FCAM_H_RESPONSE_BYTES);
        put64(mailbox + FCAM_H_RESPONSE_FNV, fnv(mailbox + FCAM_HEADER_BYTES, used));
        if (op == FCAM_OP_INIT) {
            if (!strcmp(scenario, "badnonce")) put64(mailbox + FCAM_H_NONCE, nonce + 1);
            if (!strcmp(scenario, "badpid")) put32(mailbox + FCAM_H_PID, (uint32_t)owner_pid + 1);
            if (!strcmp(scenario, "badpages")) put64(mailbox + FCAM_H_PAGES + 8, pages[0]);
            if (!strcmp(scenario, "badreserved")) mailbox[300] = 1;
            if (!strcmp(scenario, "badseq")) put64(mailbox + FCAM_H_SEQUENCE, last - 1);
            if (!strcmp(scenario, "badop")) put32(mailbox + FCAM_H_OPCODE, FCAM_OP_STATE);
            if (!strcmp(scenario, "badbounds")) put32(mailbox + FCAM_H_RESPONSE_BYTES, FCAM_DATA_BYTES + 1);
            if (!strcmp(scenario, "badfnv")) put64(mailbox + FCAM_H_RESPONSE_FNV, 0);
        }
        status_store(FCAM_STATUS_RESPONSE);
        if (!strncmp(scenario, "bad", 3)) return NULL;
    }
}
static void start_server(pthread_t *t) { assert(!pthread_create(t, NULL, server, NULL)); }
static void finish_server(pthread_t t) { assert(!fcam_bridge_close()); assert(!pthread_join(t, NULL)); assert(!mailbox && unpins == 1); }

static const struct fcam_native_origin bit_width_origin = {0x1001, 0x200d, 0x015e, 10, UINT64_C(0x0123456789abcdef)};
static void *bit_width_server(void *unused) {
    (void)unused;
    uint64_t last = 0;
    for (;;) {
        uint32_t status = status_load();
        if (status == FCAM_STATUS_CLOSED) { status_store(FCAM_STATUS_DETACHED); return NULL; }
        if (status != FCAM_STATUS_REQUEST || get64(mailbox + FCAM_H_SEQUENCE) == last) { sleep_short(); continue; }
        last = get64(mailbox + FCAM_H_SEQUENCE);
        assert(get32(mailbox + FCAM_H_OPCODE) == FCAM_OP_VDF_BIT_WIDTH);
        assert(get32(mailbox + FCAM_H_FLAGS) == 0 && get32(mailbox + FCAM_H_REQUEST_BYTES) == 8);
        assert(get32(mailbox + FCAM_H_NATIVE_SOURCE) == bit_width_origin.source &&
            get32(mailbox + FCAM_H_NATIVE_DESTINATION) == bit_width_origin.destination &&
            get32(mailbox + FCAM_H_NATIVE_COMMAND) == 0x015e && get32(mailbox + FCAM_H_NATIVE_BYTES) == 10 &&
            get64(mailbox + FCAM_H_NATIVE_FNV) == bit_width_origin.wire_fnv1a64);
        unsigned char input[8]; memcpy(input, mailbox + FCAM_HEADER_BYTES, sizeof input);
        assert(fcam_bit_width_input_valid(input) && get64(mailbox + FCAM_H_REQUEST_FNV) == fnv(input, sizeof input));
        unsigned char *p = mailbox + FCAM_HEADER_BYTES;
        memset(p, 0, FCAM_BIT_WIDTH_RESULT_BYTES);
        put32(p + FCAM_VDF_R_ABI, FCAM_ABI_VERSION); put32(p + FCAM_VDF_R_BYTES, FCAM_BIT_WIDTH_RESULT_BYTES);
        put64(p + FCAM_VDF_R_INSTANCE, nonce); put64(p + FCAM_VDF_R_CONFIG_GENERATION, 5);
        put64(p + FCAM_VDF_R_FRAME_GENERATION, 6); put64(p + FCAM_VDF_R_LEASE_GENERATION, 6);
        put64(p + FCAM_VDF_R_INPUT_FNV, fnv(input, sizeof input));
        put64(p + FCAM_VDF_R_SOURCE_FNV, UINT64_C(0xabcdef1020304050));
        put64(p + FCAM_VDF_R_SINK_FNV, UINT64_C(0xabcdef1020304050));
        put64(p + FCAM_VDF_R_ACTIVE_BYTES, 640u * 480u * 3u);
        put32(p + FCAM_VDF_R_WIDTH, 640); put32(p + FCAM_VDF_R_HEIGHT, 480); put32(p + FCAM_VDF_R_STRIDE, 1920);
        put32(p + FCAM_VDF_R_ENDPOINT, FCAM_VDF_ENDPOINT);
        put32(p + FCAM_VDF_R_SELECTED_MASK, 1); put32(p + FCAM_VDF_R_COMPLETED_MASK, 1);
        put32(p + FCAM_VDF_R_CLASS, FCAM_BIT_WIDTH_CLASS);
        for (size_t at = FCAM_VDF_R_ENABLED; at <= FCAM_VDF_R_RETIRED; at += 4) put32(p + at, 1);
        p[FCAM_VDF_R_CONFIG] = 1; p[FCAM_VDF_R_CONFIG + 1] = p[FCAM_VDF_R_CONFIG + 2] = 5;
        put64(p + FCAM_VDF_R_BEFORE_FRAME_GENERATION, 5); put64(p + FCAM_VDF_R_BEFORE_CONFIG_GENERATION, 4);
        memcpy(p + FCAM_BIT_WIDTH_R_CONFIG, input, sizeof input);
        if (strstr(scenario, "badclass")) put32(p + FCAM_VDF_R_CLASS, 1);
        if (strstr(scenario, "badtail")) p[FCAM_BIT_WIDTH_R_CONFIG + 7] = 1;
        if (strstr(scenario, "badinputfnv")) p[FCAM_VDF_R_INPUT_FNV] ^= 1;
        if (strstr(scenario, "badsink")) p[FCAM_VDF_R_SINK_FNV] ^= 1;
        if (strstr(scenario, "badinstance")) put64(p + FCAM_VDF_R_INSTANCE, nonce + 1);
        if (strstr(scenario, "badreserved")) p[FCAM_VDF_R_RESERVED] = 1;
        if (strstr(scenario, "badframe")) put64(p + FCAM_VDF_R_FRAME_GENERATION, 5);
        if (strstr(scenario, "badgeneration")) put64(p + FCAM_VDF_R_BEFORE_CONFIG_GENERATION, UINT64_MAX);
        if (strstr(scenario, "badroute")) p[FCAM_VDF_R_CONFIG] = 0;
        if (strstr(scenario, "badretire")) put32(p + FCAM_VDF_R_RETIRED, 0);
        size_t used = strstr(scenario, "badsize") ? FCAM_BIT_WIDTH_RESULT_BYTES - 1 : FCAM_BIT_WIDTH_RESULT_BYTES;
        int error = !strcmp(scenario, "bitwidth-upstream") ? -EIO : 0;
        if (error) used = 0;
        put32(mailbox + FCAM_H_ERROR, (uint32_t)error); put32(mailbox + FCAM_H_RESPONSE_BYTES, (uint32_t)used);
        if (strstr(scenario, "badtoken")) {
            put64(mailbox + FCAM_H_RESULT_TOTAL, used); put64(mailbox + FCAM_H_RESULT_TOKEN, 77);
        }
        put64(mailbox + FCAM_H_RESPONSE_FNV, fnv(p, used));
        if (strstr(scenario, "badfnv")) put64(mailbox + FCAM_H_RESPONSE_FNV, 0);
        status_store(FCAM_STATUS_RESPONSE);
    }
}
static void bit_width_bridge_test(void) {
    unsigned char input[8] = {0}, output[FCAM_BIT_WIDTH_RESULT_BYTES + 8];
    memset(output, 0xa5, sizeof output);
    struct fcam_bridge_result result = {1, 2, 3, 4}, before = result;
    if (!strcmp(scenario, "bitwidth-validation")) {
        unsigned char sized_input[9] = {0};
        for (size_t n = 0; n <= sizeof sized_input; ++n) {
            if (n == 8) continue;
            assert(fcam_bridge_call(&bit_width_origin, FCAM_OP_VDF_BIT_WIDTH, sized_input, n,
                output, sizeof output, &result) == -EINVAL);
        }
        assert(fcam_bridge_call(&bit_width_origin, FCAM_OP_VDF_BIT_WIDTH, input, 8,
            output, 167, &result) == -ENOSPC);
        for (size_t i = 1; i < 8; ++i) {
            input[i] = 1;
            assert(fcam_bridge_call(&bit_width_origin, FCAM_OP_VDF_BIT_WIDTH, input, 8,
                output, sizeof output, &result) == -EINVAL); input[i] = 0;
        }
        for (unsigned int i = 1; i <= 3; ++i) {
            input[0] = (unsigned char)i;
            assert(fcam_bridge_call(&bit_width_origin, FCAM_OP_VDF_BIT_WIDTH, input, 8,
                output, sizeof output, &result) == -ENOTSUP);
        }
        input[0] = 0;
        assert(fcam_bridge_call(&origin, FCAM_OP_VDF_BIT_WIDTH, input, 8,
            output, sizeof output, &result) == -EINVAL);
        assert(sequence == 0 && !memcmp(&result, &before, sizeof result));
        for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
        return;
    }
    pthread_t host; assert(!pthread_create(&host, NULL, bit_width_server, NULL));
    const int rc = fcam_bridge_call(&bit_width_origin, FCAM_OP_VDF_BIT_WIDTH, input, sizeof input,
        output, sizeof output, &result);
    if (!strcmp(scenario, "bitwidth")) {
        assert(!rc && result.used == 168 && result.required == 168 && result.model_instance == nonce && !result.result_token);
        assert(bit_width_reply_valid(output, input) && !memcmp(output + 160, input, 8));
        assert(readback_closed == 1 && !released && !cancelled);
        for (size_t i = 168; i < sizeof output; ++i) assert(output[i] == 0xa5);
    } else {
        const int expected = !strcmp(scenario, "bitwidth-upstream") || !strcmp(scenario, "bitwidth-copy") ? -EIO :
            strstr(scenario, "badfnv") ? -EBADMSG : -EPROTO;
        assert(rc == expected && !memcmp(&result, &before, sizeof result) && !readback_closed);
        if (strcmp(scenario, "bitwidth-copy"))
            for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
    }
    finish_server(host);
}
static struct fcam_native_origin still_format_origin;
static void *still_format_server(void *unused) {
    (void)unused;
    uint64_t last = 0;
    for (;;) {
        uint32_t status = status_load();
        if (status == FCAM_STATUS_CLOSED) { status_store(FCAM_STATUS_DETACHED); return NULL; }
        if (status != FCAM_STATUS_REQUEST || get64(mailbox + FCAM_H_SEQUENCE) == last) { sleep_short(); continue; }
        last = get64(mailbox + FCAM_H_SEQUENCE);
        assert(get32(mailbox + FCAM_H_OPCODE) == FCAM_OP_STILL_FORMAT);
        assert(get32(mailbox + FCAM_H_FLAGS) == 0 && get32(mailbox + FCAM_H_REQUEST_BYTES) == 16);
        assert(get32(mailbox + FCAM_H_NATIVE_SOURCE) == UINT32_C(0x80020002) &&
            get32(mailbox + FCAM_H_NATIVE_DESTINATION) == UINT32_C(0x90030001) &&
            get32(mailbox + FCAM_H_NATIVE_COMMAND) == 0x402d && get32(mailbox + FCAM_H_NATIVE_BYTES) == 24 &&
            get64(mailbox + FCAM_H_NATIVE_FNV) == still_format_origin.wire_fnv1a64);
        unsigned char input[16]; memcpy(input, mailbox + FCAM_HEADER_BYTES, sizeof input);
        assert(fcam_still_format_input_valid(input) && get64(mailbox + FCAM_H_REQUEST_FNV) == fnv(input, sizeof input));
        unsigned char *p = mailbox + FCAM_HEADER_BYTES;
        memset(p, 0, FCAM_STILL_FORMAT_RESULT_BYTES);
        put32(p + FCAM_VDF_R_ABI, 1); put32(p + FCAM_VDF_R_BYTES, 176);
        put64(p + FCAM_VDF_R_INSTANCE, nonce); put64(p + FCAM_VDF_R_CONFIG_GENERATION, 4 + last);
        put64(p + FCAM_VDF_R_FRAME_GENERATION, 5 + last); put64(p + FCAM_VDF_R_LEASE_GENERATION, 5 + last);
        put64(p + FCAM_VDF_R_INPUT_FNV, fnv(input, sizeof input));
        put64(p + FCAM_VDF_R_SOURCE_FNV, UINT64_C(0xabcdef1020304050));
        put64(p + FCAM_VDF_R_SINK_FNV, UINT64_C(0xabcdef1020304050));
        put64(p + FCAM_VDF_R_ACTIVE_BYTES, 921600);
        put32(p + FCAM_VDF_R_WIDTH, 640); put32(p + FCAM_VDF_R_HEIGHT, 480); put32(p + FCAM_VDF_R_STRIDE, 1920);
        put32(p + FCAM_VDF_R_ENDPOINT, FCAM_VDF_ENDPOINT);
        put32(p + FCAM_VDF_R_SELECTED_MASK, 1); put32(p + FCAM_VDF_R_COMPLETED_MASK, 1);
        put32(p + FCAM_VDF_R_CLASS, FCAM_STILL_FORMAT_CLASS);
        for (size_t at = FCAM_VDF_R_ENABLED; at <= FCAM_VDF_R_RETIRED; at += 4) put32(p + at, 1);
        p[FCAM_VDF_R_CONFIG] = 1; p[FCAM_VDF_R_CONFIG + 1] = p[FCAM_VDF_R_CONFIG + 2] = 5;
        put64(p + FCAM_VDF_R_BEFORE_FRAME_GENERATION, 4 + last);
        put64(p + FCAM_VDF_R_BEFORE_CONFIG_GENERATION, 3 + last);
        memcpy(p + FCAM_STILL_FORMAT_R_CONFIG, input, sizeof input);
        /* Full response FNV is recomputed after each semantic corruption. */
        static const struct { const char *name; size_t at; uint64_t value; size_t bytes; } corruptions[] = {
            {"stillformat-class7", FCAM_VDF_R_CLASS, 7, 4}, {"stillformat-class5", FCAM_VDF_R_CLASS, 5, 4},
            {"stillformat-badabi", FCAM_VDF_R_ABI, 2, 4},
            {"stillformat-baddeclared", FCAM_VDF_R_BYTES, 168, 4},
            {"stillformat-badinputfnv", FCAM_VDF_R_INPUT_FNV, 0, 8},
            {"stillformat-badsink", FCAM_VDF_R_SINK_FNV, 0, 8},
            {"stillformat-badactive", FCAM_VDF_R_ACTIVE_BYTES, 921599, 8},
            {"stillformat-badwidth", FCAM_VDF_R_WIDTH, 639, 4},
            {"stillformat-badheight", FCAM_VDF_R_HEIGHT, 479, 4},
            {"stillformat-badstride", FCAM_VDF_R_STRIDE, 1921, 4},
            {"stillformat-badendpoint", FCAM_VDF_R_ENDPOINT, 0, 4},
            {"stillformat-badselected", FCAM_VDF_R_SELECTED_MASK, 3, 4},
            {"stillformat-badcompleted", FCAM_VDF_R_COMPLETED_MASK, 0, 4},
            {"stillformat-badenabled", FCAM_VDF_R_ENABLED, 0, 4},
            {"stillformat-badreadback", FCAM_VDF_R_CONFIG_READBACK, 0, 4},
            {"stillformat-badcommit", FCAM_VDF_R_COMMITTED, 0, 4},
            {"stillformat-badconsume", FCAM_VDF_R_FRAME_CONSUMED, 0, 4},
            {"stillformat-badretire", FCAM_VDF_R_RETIRED, 0, 4},
            {"stillformat-badstatus", FCAM_VDF_R_STATUS, 1, 4},
            {"stillformat-badreserved", FCAM_VDF_R_RESERVED, 1, 4},
            {"stillformat-badlease", FCAM_VDF_R_LEASE_GENERATION, 0, 8},
            {"stillformat-badframe", FCAM_VDF_R_FRAME_GENERATION, 0, 8},
            {"stillformat-badconfig", FCAM_VDF_R_CONFIG_GENERATION, 0, 8},
            {"stillformat-overflowframe", FCAM_VDF_R_BEFORE_FRAME_GENERATION, UINT64_MAX, 8},
            {"stillformat-overflowconfig", FCAM_VDF_R_BEFORE_CONFIG_GENERATION, UINT64_MAX, 8},
            {"stillformat-badroute", FCAM_VDF_R_CONFIG, 0, 1},
            {"stillformat-badroutepin", FCAM_VDF_R_CONFIG + 1, 1, 1},
            {"stillformat-badroutemode", FCAM_VDF_R_CONFIG + 4, 3, 1},
            {"stillformat-badroutetail", FCAM_VDF_R_CONFIG + 15, 1, 1},
            {"stillformat-badtail", FCAM_STILL_FORMAT_R_CONFIG + 15, 1, 1},
            {"stillformat-badslot", FCAM_STILL_FORMAT_R_CONFIG + 9, 0, 1}
        };
        for (size_t i = 0; i < sizeof corruptions / sizeof corruptions[0]; ++i)
            if (!strcmp(scenario, corruptions[i].name)) {
                if (corruptions[i].bytes == 8) put64(p + corruptions[i].at, corruptions[i].value);
                else if (corruptions[i].bytes == 4) put32(p + corruptions[i].at, (uint32_t)corruptions[i].value);
                else p[corruptions[i].at] = (unsigned char)corruptions[i].value;
            }
        if (!strcmp(scenario, "stillformat-badinstance")) put64(p + FCAM_VDF_R_INSTANCE, nonce + 1);
        size_t used = !strcmp(scenario, "stillformat-size168") ? 168 :
            !strcmp(scenario, "stillformat-badsize") ? 175 : 176;
        if (!strcmp(scenario, "stillformat-size168")) put32(p + FCAM_VDF_R_BYTES, 168);
        int error = !strcmp(scenario, "stillformat-upstream") || !strcmp(scenario, "stillformat-errorpayload") ? -EIO : 0;
        if (error && strcmp(scenario, "stillformat-errorpayload")) used = 0;
        put32(mailbox + FCAM_H_ERROR, (uint32_t)error); put32(mailbox + FCAM_H_RESPONSE_BYTES, (uint32_t)used);
        if (!strcmp(scenario, "stillformat-badtoken")) {
            put64(mailbox + FCAM_H_RESULT_TOTAL, used); put64(mailbox + FCAM_H_RESULT_TOKEN, 77);
        }
        put64(mailbox + FCAM_H_RESPONSE_FNV, fnv(p, used));
        if (!strcmp(scenario, "stillformat-badfnv")) put64(mailbox + FCAM_H_RESPONSE_FNV, 0);
        if (!strcmp(scenario, "stillformat-badflags")) put32(mailbox + FCAM_H_FLAGS, 1);
        if (!strcmp(scenario, "stillformat-badsource")) put32(mailbox + FCAM_H_NATIVE_SOURCE, 0x80020003);
        if (!strcmp(scenario, "stillformat-baddestination")) put32(mailbox + FCAM_H_NATIVE_DESTINATION, 0x90030002);
        if (!strcmp(scenario, "stillformat-badorigin")) put64(mailbox + FCAM_H_NATIVE_FNV, 0);
        status_store(FCAM_STATUS_RESPONSE);
        /* Malformed origin binding cannot be detached; host fixture relinquishes only its thread. */
        if (!strcmp(scenario, "stillformat-badflags")) return NULL;
    }
}
static void still_format_bridge_test(void) {
    unsigned char input[16]; memcpy(input, fcam_still_format_initial, sizeof input);
    unsigned char wire[24] = {5,0,0x2d,0x40,0x3b,0,0,0x80}; memcpy(wire + 8, input, 16);
    still_format_origin = (struct fcam_native_origin){0x80020002, 0x90030001, 0x402d, 24, fnv(wire, 24)};
    unsigned char output[184]; memset(output, 0xa5, sizeof output);
    struct fcam_bridge_result result = {1,2,3,4}, before = result;
    if (!strcmp(scenario, "stillformat-validation")) {
        unsigned char sized[17] = {0}; memcpy(sized, input, 16);
        for (size_t n = 0; n <= sizeof sized; ++n) if (n != 16)
            assert(fcam_bridge_call(&still_format_origin, 13, sized, n, output, sizeof output, &result) == -EINVAL);
        for (size_t n = 0; n < 176; ++n)
            assert(fcam_bridge_call(&still_format_origin, 13, input, 16, output, n, &result) == -ENOSPC);
        for (size_t i = 0; i < 16; ++i) for (unsigned value = 0; value < 256; ++value) {
            if (value == fcam_still_format_initial[i]) continue;
            input[i] = (unsigned char)value;
            assert(fcam_bridge_call(&still_format_origin, 13, input, 16, output, sizeof output, &result) == -ENOTSUP);
            input[i] = fcam_still_format_initial[i];
        }
        static const unsigned char first_m[16] = {2,0,1,1,1,1,1,0,1,1,1,1,1,0,0,0};
        assert(fcam_bridge_call(&still_format_origin, 13, first_m, 16, output, sizeof output, &result) == -ENOTSUP);
        for (size_t i = 0; i < 4; ++i) {
            struct fcam_native_origin wrong = still_format_origin;
            if (i == 0) ++wrong.source; else if (i == 1) ++wrong.destination;
            else if (i == 2) ++wrong.command; else --wrong.bytes;
            assert(fcam_bridge_call(&wrong, 13, input, 16, output, sizeof output, &result) == -EINVAL);
        }
        assert(fcam_bridge_call(&still_format_origin, 13, input, 16, input, 176, &result) == -EINVAL);
        assert(fcam_bridge_call(&still_format_origin, 13, input, 16, output, 176,
            (struct fcam_bridge_result *)(void *)output) == -EINVAL);
        assert(sequence == 0 && !memcmp(&result, &before, sizeof result));
        for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
        return;
    }
    pthread_t host; assert(!pthread_create(&host, NULL, still_format_server, NULL));
    const int rc = fcam_bridge_call(&still_format_origin, 13, input, 16, output, sizeof output, &result);
    if (!strcmp(scenario, "stillformat")) {
        assert(!rc && result.used == 176 && result.required == 176 && result.model_instance == nonce && !result.result_token);
        assert(still_format_reply_valid(output, input) && !memcmp(output + 160, input, 16));
        const uint64_t generation = get64(output + 16), frame = get64(output + 24);
        /* Native opaque tail stays in wire FNV; its caller-produced canonical tail remains zero. */
        wire[4]++; wire[22] = 0xa7; wire[23] = 0x56;
        still_format_origin.wire_fnv1a64 = fnv(wire, sizeof wire);
        assert(!fcam_bridge_call(&still_format_origin, 13, input, 16, output, sizeof output, &result));
        assert(get64(output + 16) == generation + 1 && get64(output + 24) == frame + 1);
        assert(readback_closed == 2 && !released && !cancelled);
        for (size_t i = 176; i < sizeof output; ++i) assert(output[i] == 0xa5);
    } else {
        const int expected = !strcmp(scenario, "stillformat-upstream") || !strcmp(scenario, "stillformat-copy") ? -EIO :
            !strcmp(scenario, "stillformat-badfnv") ? -EBADMSG : -EPROTO;
        assert(rc == expected && !memcmp(&result, &before, sizeof result) && !readback_closed && !released && !cancelled);
        if (strcmp(scenario, "stillformat-copy"))
            for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
    }
    if (!strcmp(scenario, "stillformat-badflags")) {
        assert(!pthread_join(host, NULL) && poisoned && mailbox && !unpins);
    } else finish_server(host);
}
static struct fcam_native_origin startup_origin;
static void startup_input(unsigned command, const unsigned char *actual_state, unsigned char input[32]) {
    memset(input, 0, 32); input[0] = (unsigned char)command; input[1] = (unsigned char)(command >> 8);
    input[2] = command == 0x4014 ? 16 : 4;
    if (command == 0x4014) memcpy(input + 4, fcam_startup_control_mode_body, 16);
    put64(input + 24, fnv(actual_state + 8, 40));
    unsigned char wire[24] = {5,0,0,0,0x3c,0,0,0x80}; wire[2] = input[0]; wire[3] = input[1];
    memcpy(wire + 8, input + 4, input[2]);
    startup_origin = (struct fcam_native_origin){0x80020002, 0x90030001, command,
        command == 0x4014 ? 24u : 12u, fnv(wire, command == 0x4014 ? 24u : 12u)};
}
static void *startup_server(void *unused) {
    (void)unused; uint64_t last = 0, config_generation = 4, frame_generation = 5;
    for (;;) {
        uint32_t status = status_load();
        if (status == FCAM_STATUS_CLOSED) { status_store(FCAM_STATUS_DETACHED); return NULL; }
        if (status != FCAM_STATUS_REQUEST || get64(mailbox + FCAM_H_SEQUENCE) == last) { sleep_short(); continue; }
        last = get64(mailbox + FCAM_H_SEQUENCE);
        const uint32_t op = get32(mailbox + FCAM_H_OPCODE);
        assert(get32(mailbox + FCAM_H_FLAGS) == 0);
        assert(get32(mailbox + FCAM_H_NATIVE_SOURCE) == startup_origin.source &&
            get32(mailbox + FCAM_H_NATIVE_DESTINATION) == startup_origin.destination &&
            get32(mailbox + FCAM_H_NATIVE_COMMAND) == startup_origin.command &&
            get32(mailbox + FCAM_H_NATIVE_BYTES) == startup_origin.bytes &&
            get64(mailbox + FCAM_H_NATIVE_FNV) == startup_origin.wire_fnv1a64);
        put32(mailbox + FCAM_H_ERROR, 0); memset(mailbox + FCAM_H_RESULT_TOTAL, 0, 24);
        unsigned char *p = mailbox + FCAM_HEADER_BYTES; size_t used;
        if (op == FCAM_OP_STATE) {
            assert(!get32(mailbox + FCAM_H_REQUEST_BYTES)); state_reply(); used = 128;
            put32(p + 8, 640); put32(p + 12, 480); put32(p + 16, 30); put32(p + 20, 73);
            put32(p + 24, 800); put32(p + 28, 640); put64(p + 32, 8642); put64(p + 40, UINT64_MAX);
            put64(p + FCAM_S_GENERATION, config_generation); put64(p + FCAM_S_FRAME_GENERATION, frame_generation);
        } else {
            assert(op == FCAM_OP_STARTUP_CONTROL && get32(mailbox + FCAM_H_REQUEST_BYTES) == 32);
            unsigned char input[32]; memcpy(input, p, 32);
            assert(fcam_startup_control_validate_basic(input) && get64(input + 24) == current_config40_fnv);
            assert(get64(mailbox + FCAM_H_REQUEST_FNV) == fnv(input, 32));
            memset(p, 0, 192); used = 192;
            put32(p, 1); put32(p + 4, 192); put64(p + 8, nonce);
            put64(p + 16, config_generation + 1); put64(p + 24, frame_generation + 1); put64(p + 32, frame_generation + 1);
            put64(p + 40, fnv(input, 32)); put64(p + 48, UINT64_C(0xabcdef1020304050));
            put64(p + 56, UINT64_C(0xabcdef1020304050)); put64(p + 64, 921600);
            put32(p + 72, 640); put32(p + 76, 480); put32(p + 80, 1920);
            put32(p + 84, FCAM_VDF_ENDPOINT); put32(p + 88, 1); put32(p + 92, 1); put32(p + 96, 9);
            for (size_t at = 100; at <= 116; at += 4) put32(p + at, 1);
            p[128] = 1; p[129] = p[130] = 5; put64(p + 144, frame_generation); put64(p + 152, config_generation);
            ++config_generation; ++frame_generation;
            memcpy(p + 160, input, 32);
            static const struct { const char *name; size_t at; uint64_t value; size_t bytes; } corrupt[] = {
                {"startup-class5",96,5,4}, {"startup-class8",96,8,4}, {"startup-declared",4,176,4},
                {"startup-tailbody",164,1,1}, {"startup-tailreserved",180,1,1}, {"startup-tailfp",184,0,8},
                {"startup-inputfnv",40,0,8}, {"startup-sink",56,0,8}, {"startup-active",64,921599,8},
                {"startup-width",72,639,4}, {"startup-heightstride",76,479,4}, {"startup-endpoint",84,0,4},
                {"startup-selectedcompleted",88,3,4}, {"startup-route",143,1,1},
                {"startup-generations",24,0,8}, {"startup-overflow",152,UINT64_MAX,8},
                {"startup-lease",32,0,8}, {"startup-enabled",100,0,4}, {"startup-readback",104,0,4},
                {"startup-commit",108,0,4}, {"startup-consume",112,0,4}, {"startup-retire",116,0,4},
                {"startup-status",120,1,4}, {"startup-instance",8,1,8}
            };
            for (size_t i = 0; i < sizeof corrupt / sizeof corrupt[0]; ++i) if (!strcmp(scenario, corrupt[i].name)) {
                if (corrupt[i].bytes == 8) put64(p + corrupt[i].at, corrupt[i].value);
                else if (corrupt[i].bytes == 4) put32(p + corrupt[i].at, (uint32_t)corrupt[i].value);
                else p[corrupt[i].at] = (unsigned char)corrupt[i].value;
            }
            if (!strcmp(scenario, "startup-generations")) {
                put64(p + 16, 101); put64(p + 24, 102); put64(p + 144, 101); put64(p + 152, 100);
            }
            if (!strcmp(scenario, "startup-heightstride")) put32(p + 80, 1921);
            if (!strcmp(scenario, "startup-selectedcompleted")) put32(p + 92, 0);
            if (!strcmp(scenario, "startup-size176")) used = 176;
            if (!strcmp(scenario, "startup-short")) used = 191;
            if (!strcmp(scenario, "startup-token")) { put64(mailbox + FCAM_H_RESULT_TOTAL, used); put64(mailbox + FCAM_H_RESULT_TOKEN, 77); }
            if (!strcmp(scenario, "startup-upstream") || !strcmp(scenario, "startup-errorpayload")) {
                put32(mailbox + FCAM_H_ERROR, (uint32_t)-EIO);
                if (!strcmp(scenario, "startup-upstream")) used = 0;
            }
            if (!strcmp(scenario, "startup-origin")) put32(mailbox + FCAM_H_NATIVE_BYTES, 12);
            if (!strcmp(scenario, "startup-flags")) put32(mailbox + FCAM_H_FLAGS, 1);
        }
        put32(mailbox + FCAM_H_RESPONSE_BYTES, (uint32_t)used); put64(mailbox + FCAM_H_RESPONSE_FNV, fnv(p, used));
        if (op == 14 && !strcmp(scenario, "startup-fnv")) put64(mailbox + FCAM_H_RESPONSE_FNV, 0);
        status_store(FCAM_STATUS_RESPONSE);
        if (op == 14 && !strcmp(scenario, "startup-flags")) return NULL;
    }
}
static void startup_bridge_test(void) {
    unsigned char actual_state[128] = {0}, input[33], output[200]; memset(output, 0xa5, sizeof output);
    startup_input(0x4014, actual_state, input);
    struct fcam_bridge_result r = {1,2,3,4}, previous = r;
    assert(fcam_bridge_call(&startup_origin, 14, input, 32, output, 192, &r) == -ENODATA);
    assert(!sequence && !memcmp(&r, &previous, sizeof r));
    pthread_t host; assert(!pthread_create(&host, NULL, startup_server, NULL));
    assert(!fcam_bridge_call(&startup_origin, 2, NULL, 0, actual_state, 128, &r));
    assert(r.used == 128 && !r.result_token); readback_closed = 0; r = previous;
    startup_input(0x4014, actual_state, input);
    if (!strcmp(scenario, "startup-validation")) {
        const uint64_t before_sequence = sequence;
        for (size_t n = 0; n <= 33; ++n) if (n != 32)
            assert(fcam_bridge_call(&startup_origin, 14, input, n, output, 192, &r) == -EINVAL);
        for (size_t cap = 0; cap < 192; ++cap)
            assert(fcam_bridge_call(&startup_origin, 14, input, 32, output, cap, &r) == -ENOSPC);
        for (size_t slot = 0; slot < 2; ++slot) {
            startup_input(slot ? 0x4057 : 0x4014, actual_state, input);
            for (size_t i = 0; i < 32; ++i) {
                input[i] ^= 1;
                assert(fcam_bridge_call(&startup_origin, 14, input, 32, output, 192, &r) ==
                    (i < 2 ? -EINVAL : i < 24 ? -ENOTSUP : -ESTALE)); input[i] ^= 1;
            }
            for (size_t i = 0; i < 4; ++i) {
                struct fcam_native_origin wrong = startup_origin;
                if (!i) ++wrong.source; else if (i == 1) ++wrong.destination;
                else if (i == 2) ++wrong.command; else ++wrong.bytes;
                assert(fcam_bridge_call(&wrong, 14, input, 32, output, 192, &r) == -EINVAL);
            }
        }
        assert(sequence == before_sequence && !memcmp(&r, &previous, sizeof r) && !readback_closed);
        for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
        finish_server(host); return;
    }
    const int rc = fcam_bridge_call(&startup_origin, 14, input, 32, output, 200, &r);
    if (!strcmp(scenario, "startup")) {
        assert(!rc && r.used == 192 && r.required == 192 && r.model_instance == nonce && !r.result_token);
        assert(rgb_config_reply_valid(output, input, 32, 9) && !memcmp(output + 160, input, 32));
        uint64_t generation = get64(output + 16), frame = get64(output + 24);
        for (size_t i = 0; i < 3; ++i) {
            startup_input(i == 1 ? 0x4014 : 0x4057, actual_state, input);
            if (i < 2) assert(!fcam_bridge_call(&startup_origin, 2, NULL, 0, actual_state, 128, &r));
            startup_input(i == 1 ? 0x4014 : 0x4057, actual_state, input);
            assert(!fcam_bridge_call(&startup_origin, 14, input, 32, output, 200, &r));
            assert(get64(output + 16) == generation + 1 && get64(output + 24) == frame + 1);
            generation += 1; frame += 1;
            assert(r.used == 192 && !r.result_token && !memcmp(output + 160, input, 32));
        }
        assert(readback_closed == 6 && !released && !cancelled);
        for (size_t i = 192; i < 200; ++i) assert(output[i] == 0xa5);
    } else {
        const int expected = !strcmp(scenario, "startup-upstream") || !strcmp(scenario, "startup-copy") ? -EIO :
            !strcmp(scenario, "startup-fnv") ? -EBADMSG : -EPROTO;
        assert(rc == expected && !memcmp(&r, &previous, sizeof r) && !readback_closed && !released && !cancelled);
        if (strcmp(scenario, "startup-copy")) for (size_t i = 0; i < 200; ++i) assert(output[i] == 0xa5);
    }
    if (!strcmp(scenario, "startup-flags")) assert(!pthread_join(host, NULL) && poisoned && mailbox && !unpins);
    else finish_server(host);
}
static unsigned char *snapshot_source;
static size_t snapshot_bytes, snapshot_cursor;
static struct fcam_native_origin snapshot_origin;
static void *snapshot_server(void *unused) {
    (void)unused; uint64_t last = 0;
    for (;;) {
        uint32_t status = status_load();
        if (status == FCAM_STATUS_CLOSED) { status_store(FCAM_STATUS_DETACHED); return NULL; }
        if (status != FCAM_STATUS_REQUEST || get64(mailbox + FCAM_H_SEQUENCE) == last) { sleep_short(); continue; }
        last = get64(mailbox + FCAM_H_SEQUENCE);
        uint32_t op = get32(mailbox + FCAM_H_OPCODE);
        assert(get32(mailbox + FCAM_H_FLAGS) == FCAM_ORIGIN_API40_SOURCE_SNAPSHOT);
        assert(get32(mailbox + FCAM_H_NATIVE_SOURCE) == snapshot_origin.source &&
            get32(mailbox + FCAM_H_NATIVE_DESTINATION) == snapshot_origin.destination &&
            get32(mailbox + FCAM_H_NATIVE_COMMAND) == snapshot_origin.command &&
            get32(mailbox + FCAM_H_NATIVE_BYTES) == 40 && get64(mailbox + FCAM_H_NATIVE_FNV) == snapshot_origin.wire_fnv1a64);
        assert(get64(mailbox + FCAM_H_REQUEST_FNV) == fnv(mailbox + FCAM_HEADER_BYTES, get32(mailbox + FCAM_H_REQUEST_BYTES)));
        put32(mailbox + FCAM_H_RESPONSE_BYTES, 0); put32(mailbox + FCAM_H_ERROR, 0);
        memset(mailbox + FCAM_H_RESULT_TOTAL, 0, 24);
        if (op == FCAM_OP_AP_SOURCE_SNAPSHOT || op == FCAM_OP_READ_RESULT) {
            if (op == FCAM_OP_AP_SOURCE_SNAPSHOT) {
                snapshot_cursor = 0;
                assert(get32(mailbox + FCAM_HEADER_BYTES + FCAM_FACE_SNAPSHOT_BYTES_AT) == snapshot_bytes);
            } else {
                assert(get64(mailbox + FCAM_HEADER_BYTES) == 91 &&
                    get64(mailbox + FCAM_HEADER_BYTES + 8) == snapshot_cursor);
            }
            if (op == FCAM_OP_READ_RESULT && !strcmp(scenario, "snapshot-partial")) {
                put32(mailbox + FCAM_H_ERROR, (uint32_t)-EIO);
            } else if (strcmp(scenario, "snapshot-empty")) {
                size_t total = snapshot_bytes - (!strcmp(scenario, "snapshot-total") ? 1u : 0u);
                size_t used = total - snapshot_cursor;
                if (used > FCAM_DATA_BYTES) used = FCAM_DATA_BYTES;
                if (!strcmp(scenario, "snapshot-short")) --used;
                memcpy(mailbox + FCAM_HEADER_BYTES, snapshot_source + snapshot_cursor, used);
                put32(mailbox + FCAM_H_RESPONSE_BYTES, (uint32_t)used);
                put64(mailbox + FCAM_H_RESULT_TOTAL, total); put64(mailbox + FCAM_H_RESULT_OFFSET, snapshot_cursor);
                put64(mailbox + FCAM_H_RESULT_TOKEN, op == FCAM_OP_READ_RESULT && !strcmp(scenario, "snapshot-token") ? 92 : 91);
                snapshot_cursor += used;
            }
        } else if (op == FCAM_OP_RELEASE_RESULT) {
            assert(snapshot_cursor == snapshot_bytes && get64(mailbox + FCAM_HEADER_BYTES) == 91);
            assert(!memcmp(snapshot_source, caller_output, snapshot_bytes) &&
                get64(mailbox + FCAM_HEADER_BYTES + 8) == fnv(snapshot_source, snapshot_bytes));
            if (!strcmp(scenario, "snapshot-release")) put32(mailbox + FCAM_H_ERROR, (uint32_t)-EIO);
            else ++released;
        } else if (op == FCAM_OP_CANCEL) {
            ++cancelled; state_reply();
        } else abort();
        size_t used = get32(mailbox + FCAM_H_RESPONSE_BYTES);
        put64(mailbox + FCAM_H_RESPONSE_FNV, fnv(mailbox + FCAM_HEADER_BYTES, used));
        if (op == FCAM_OP_AP_SOURCE_SNAPSHOT && !strcmp(scenario, "snapshot-digest")) put64(mailbox + FCAM_H_RESPONSE_FNV, 0);
        if (op == FCAM_OP_AP_SOURCE_SNAPSHOT && !strcmp(scenario, "snapshot-flags")) put32(mailbox + FCAM_H_FLAGS, 0);
        status_store(FCAM_STATUS_RESPONSE);
    }
}
static void snapshot_bridge_test(void) {
    unsigned int unit = !strcmp(scenario, "snapshot-1da") ? 0x1da : !strcmp(scenario, "snapshot-1db") ? 0x1db : 0x1d9;
    static const size_t lengths[3] = {0x64000, 0xc800, 0xd100}; snapshot_bytes = lengths[unit - 0x1d9];
    snapshot_source = malloc(snapshot_bytes); caller_output = malloc(snapshot_bytes); assert(snapshot_source && caller_output);
    for (size_t i = 0; i < snapshot_bytes; ++i) snapshot_source[i] = (unsigned char)((i * 37 + (unit - 0x1d9) * 53 + 11) ^ (i >> 7));
    memset(caller_output, 0xa5, snapshot_bytes);
    unsigned char packet[FCAM_FACE_SNAPSHOT_MAX_INPUT_BYTES] = {0};
    put32(packet, 1); put32(packet + 4, unit); put32(packet + 8, 0x92a); put32(packet + 12, 0x8402 + unit - 0x1d9);
    put32(packet + 16, (uint32_t)snapshot_bytes);
    unsigned int cp_count = (unsigned int)((snapshot_bytes + FCAM_PAGE_BYTES - 1) / FCAM_PAGE_BYTES);
    put32(packet + 20, cp_count); put32(packet + 24, 2);
    const size_t input_bytes = FCAM_FACE_SNAPSHOT_BASE_BYTES + 8u * (cp_count + 2);
    put64(packet + 72, fnv(packet + FCAM_FACE_SNAPSHOT_API40_AT, 40));
    snapshot_origin = (struct fcam_native_origin){0x92a, 0x8402 + unit - 0x1d9, FCAM_FACE_SNAPSHOT_COMMAND, 40, get64(packet + 72)};
    struct fcam_bridge_result result = {1, 2, 3, 4}, before = result;
    if (!strcmp(scenario, "snapshot-schema")) {
        assert(fcam_bridge_call(&snapshot_origin, FCAM_OP_AP_SOURCE_SNAPSHOT, packet, input_bytes - 1,
            caller_output, snapshot_bytes, &result) == -EINVAL);
        put32(packet + 20, cp_count - 1);
        assert(fcam_bridge_call(&snapshot_origin, FCAM_OP_AP_SOURCE_SNAPSHOT, packet, input_bytes,
            caller_output, snapshot_bytes, &result) == -EINVAL);
        assert(!memcmp(&result, &before, sizeof before) && sequence == 0);
    } else {
        pthread_t host; assert(!pthread_create(&host, NULL, snapshot_server, NULL));
        int rc = fcam_bridge_call(&snapshot_origin, FCAM_OP_AP_SOURCE_SNAPSHOT, packet, input_bytes,
            caller_output, snapshot_bytes, &result);
        if (!strcmp(scenario, "snapshot-1d9") || !strcmp(scenario, "snapshot-1da") || !strcmp(scenario, "snapshot-1db")) {
            assert(!rc && result.used == snapshot_bytes && result.required == snapshot_bytes && result.result_token == 91);
            assert(released == 1 && !cancelled && !memcmp(snapshot_source, caller_output, snapshot_bytes));
        } else {
            assert(rc < 0 && !memcmp(&result, &before, sizeof before));
            if (!strcmp(scenario, "snapshot-partial") || !strcmp(scenario, "snapshot-release") || !strcmp(scenario, "snapshot-token")) assert(cancelled == 1);
            else for (size_t i = 0; i < snapshot_bytes; ++i) assert(caller_output[i] == 0xa5);
            assert(!released && !readback_closed);
        }
        finish_server(host);
    }
    free(snapshot_source); free(caller_output);
}
static void *state_call(void *unused) {
    (void)unused;
    unsigned char out[FCAM_STATE_BYTES]; struct fcam_bridge_result result;
    assert(!fcam_bridge_call(&origin, FCAM_OP_INIT, NULL, 0, out, sizeof out, &result));
    assert(result.used == sizeof out && result.model_instance == nonce); return NULL;
}
int main(int argc, char **argv) {
    assert(argc == 2); scenario = argv[1];
    errno = ENOTTY;
    int rc = fcam_bridge_init(record_test);
    assert(errno == ENOTTY);
    if (!strcmp(scenario, "pin") || !strcmp(scenario, "duplicate") || !strcmp(scenario, "pfnzero") ||
        !strcmp(scenario, "pfnrange") || !strcmp(scenario, "pfnalign") || !strcmp(scenario, "pagemap") || !strcmp(scenario, "noncezero")) {
        assert(rc < 0 && !mailbox && !reentry_seen); return 0;
    }
    assert(!rc && mailbox && pins == 1 && reentry_seen == 1 && sequence == 0);
    if (!strcmp(scenario, "pfnchanged")) {
        unsigned char output[128]; struct fcam_bridge_result result;
        assert(fcam_bridge_call(&origin, FCAM_OP_STATE, NULL, 0, output, sizeof output, &result) == -ESTALE);
        assert(sequence == 0 && status_load() == FCAM_STATUS_IDLE && mailbox && !unpins && poisoned);
        assert(fcam_bridge_close() == -ESTALE && mailbox && !unpins); return 0;
    }
    if (!strcmp(scenario, "timeoutretain")) {
        unsigned char *saved = mailbox;
        assert(fcam_bridge_close() == -ETIMEDOUT);
        assert(mailbox == saved && !unpins && status_load() == FCAM_STATUS_CLOSED);
        assert(fcam_bridge_init(record_test) == -ESHUTDOWN); return 0;
    }
    if (!strcmp(scenario, "fork")) {
        assert(!pthread_mutex_lock(&mutex));
        pid_t child = fork(); assert(child >= 0);
        if (!child) _exit(fcam_bridge_close() == -ECHILD ? 0 : 1);
        int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
        assert(!pthread_mutex_unlock(&mutex)); return 0;
    }
    unsigned char out[FCAM_STATE_BYTES]; memset(out, 0xa5, sizeof out);
    struct fcam_bridge_result result = {17, 18, 19, 20}, before = result;
    if (!strcmp(scenario, "validation")) {
        assert(fcam_bridge_call(&origin, 999, NULL, 0, out, sizeof out, &result) == -EINVAL);
        assert(fcam_bridge_call(&origin, FCAM_OP_STATE, NULL, 0, (void *)(UINTPTR_MAX - 3), 8, &result) == -EINVAL);
        assert(fcam_bridge_call(&origin, FCAM_OP_CONFIGURE, out, 48, out, sizeof out, &result) == -EINVAL);
        unsigned char config[FCAM_VDF_INPUT_BYTES] = {1, 5, 5};
        assert(fcam_bridge_call(&origin, FCAM_OP_VDF_PATH, config, sizeof config - 1, out, sizeof out, &result) == -EINVAL);
        assert(fcam_bridge_call(&origin, FCAM_OP_VDF_ZEBRA, config, FCAM_ZEBRA_INPUT_BYTES - 1, out, sizeof out, &result) == -EINVAL);
        unsigned char layout[FCAM_LAYOUT_INPUT_BYTES] = {0};
        assert(fcam_bridge_call(&origin, FCAM_OP_VDF_LAYOUT, layout, sizeof layout - 1, out, sizeof out, &result) == -EINVAL);
        assert(fcam_bridge_call(&origin, FCAM_OP_VDF_DISPLAY_CONFIG, layout, FCAM_DISPLAY_INPUT_BYTES - 1, out, sizeof out, &result) == -EINVAL);
        assert(fcam_bridge_call(&origin, FCAM_OP_BB_STARTUP_CONFIG, layout, FCAM_BB_INPUT_BYTES - 1, out, sizeof out, &result) == -EINVAL);
        assert(fcam_bridge_call(&origin, FCAM_OP_HISTOGRAM, layout, FCAM_HIST_INPUT_BYTES - 1, out, sizeof out, &result) == -EINVAL);
        assert(!memcmp(&before, &result, sizeof result));
        for (size_t i = 0; i < sizeof out; ++i) assert(out[i] == 0xa5);
        assert(sequence == 0 && status_load() == FCAM_STATUS_IDLE); return 0;
    }
    if (!strncmp(scenario, "bitwidth", 8)) { bit_width_bridge_test(); return 0; }
    if (!strncmp(scenario, "stillformat", 11)) { still_format_bridge_test(); return 0; }
    if (!strncmp(scenario, "startup", 7)) { startup_bridge_test(); return 0; }
    if (!strncmp(scenario, "snapshot-", 9)) { snapshot_bridge_test(); return 0; }
    pthread_t host; start_server(&host);
    if (!strncmp(scenario, "bb", 2) || !strncmp(scenario, "hist", 4)) {
        const int histogram = !strncmp(scenario, "hist", 4);
        unsigned char input[FCAM_BB_INPUT_BYTES] = {0}, response[FCAM_HIST_RESULT_BYTES + 8];
        const size_t input_bytes = histogram ? FCAM_HIST_INPUT_BYTES : FCAM_BB_INPUT_BYTES;
        const size_t result_bytes = histogram ? FCAM_HIST_RESULT_BYTES : FCAM_BB_RESULT_BYTES;
        input[0] = histogram ? 0x48 : 0x11; input[1] = 1; input[2] = histogram ? 4 : 28;
        if (histogram) input[4] = input[5] = 1; else { input[6] = 0x0f; input[7] = 2; }
        memset(response, 0xa5, sizeof response);
        if (strstr(scenario, "small")) {
            rc = fcam_bridge_call(&origin, histogram ? FCAM_OP_HISTOGRAM : FCAM_OP_BB_STARTUP_CONFIG,
                input, input_bytes, response, result_bytes - 1, &result);
            assert(rc == -ENOSPC && sequence == 0 && status_load() == FCAM_STATUS_IDLE);
        } else rc = histogram ? fcam_bridge_histogram(&origin, input, response, &result) :
            fcam_bridge_bb_startup_config(&origin, input, response, &result);
        if (!strcmp(scenario, "bb") || !strcmp(scenario, "hist")) {
            assert(!rc && result.used == result_bytes && result.required == result_bytes && !result.result_token);
            assert(!memcmp(response + 160, input, input_bytes));
            assert(get32(response + FCAM_VDF_R_CLASS) == (histogram ? 6u : 5u));
            for (size_t i = result_bytes; i < sizeof response; ++i) assert(response[i] == 0xa5);
        } else {
            assert(rc == (strstr(scenario, "small") ? -ENOSPC : -EPROTO));
            assert(!memcmp(&before, &result, sizeof result));
            for (size_t i = 0; i < sizeof response; ++i) assert(response[i] == 0xa5);
        }
        finish_server(host); return 0;
    }
    if (!strncmp(scenario, "vdf", 3) || !strncmp(scenario, "zebra", 5) || !strncmp(scenario, "layout", 6) || !strncmp(scenario, "display", 7)) {
        const int zebra = !strncmp(scenario, "zebra", 5), layout = !strncmp(scenario, "layout", 6), display = !strncmp(scenario, "display", 7);
        unsigned char config[FCAM_LAYOUT_INPUT_BYTES] = {1, 5, 5}, response[FCAM_VDF_RESULT_MAX_BYTES];
        if (zebra) {config[0] = 3; config[1] = 0; config[2] = 0x20; config[3] = 75; config[4] = 65;}
        if (layout) {config[0] = 7; config[1] = config[2] = 1; config[8] = 0x80; config[9] = 2; config[10] = 0xe0; config[11] = 1; config[24] = 3;}
        if (display) {memset(config, 0, sizeof config); put32(config, 0x152); put32(config + 4, 8); config[8] = 3; config[10] = 1; config[13] = 235; config[14] = config[15] = 128;}
        const size_t input_bytes = display ? FCAM_DISPLAY_INPUT_BYTES : layout ? FCAM_LAYOUT_INPUT_BYTES : zebra ? FCAM_ZEBRA_INPUT_BYTES : FCAM_VDF_INPUT_BYTES;
        const size_t result_bytes = display ? FCAM_DISPLAY_RESULT_BYTES : layout ? FCAM_LAYOUT_RESULT_BYTES : zebra ? FCAM_ZEBRA_RESULT_BYTES : FCAM_VDF_RESULT_BYTES;
        memset(response, 0xa5, sizeof response);
        rc = fcam_bridge_call(&origin, display ? FCAM_OP_VDF_DISPLAY_CONFIG : layout ? FCAM_OP_VDF_LAYOUT : zebra ? FCAM_OP_VDF_ZEBRA : FCAM_OP_VDF_PATH,
                              config, input_bytes, response, result_bytes, &result);
        if (!strcmp(scenario, "vdf") || !strcmp(scenario, "zebra") || !strcmp(scenario, "layout") || !strcmp(scenario, "display")) {
            assert(!rc && result.used == result_bytes && result.required == result_bytes && !result.result_token);
            assert(!memcmp(response + (zebra || layout || display ? FCAM_ZEBRA_R_CONFIG : FCAM_VDF_R_CONFIG), config, input_bytes));
            for (size_t i = result_bytes; i < sizeof response; ++i) assert(response[i] == 0xa5);
        } else {
            assert(rc == -EPROTO && !memcmp(&before, &result, sizeof result));
            for (size_t i = 0; i < sizeof response; ++i) assert(response[i] == 0xa5);
        }
        finish_server(host); return 0;
    }
    if (!strcmp(scenario, "serialize")) {
        pthread_t a, b; assert(!pthread_create(&a, NULL, state_call, NULL)); assert(!pthread_create(&b, NULL, state_call, NULL));
        assert(!pthread_join(a, NULL)); assert(!pthread_join(b, NULL)); assert(sequence == 2);
        finish_server(host); return 0;
    }
    if (!strcmp(scenario, "lateclose")) {
        assert(fcam_bridge_call(&origin, FCAM_OP_INIT, NULL, 0, out, sizeof out, &result) == -ETIMEDOUT);
        assert(mailbox && !unpins && poisoned);
        assert(fcam_bridge_call(&origin, FCAM_OP_STATE, NULL, 0, out, sizeof out, &result) == -ESHUTDOWN);
        finish_server(host); return 0;
    }
    if (!strncmp(scenario, "bad", 3)) {
        assert(fcam_bridge_call(&origin, FCAM_OP_INIT, NULL, 0, out, sizeof out, &result) < 0);
        assert(!memcmp(&before, &result, sizeof result));
        for (size_t i = 0; i < sizeof out; ++i) assert(out[i] == 0xa5);
        assert(!pthread_join(host, NULL)); return 0;
    }
    unsigned char request[16] = {0}; put32(request, FCAM_STILL_FULL_JPEG); put32(request + 4, 640); put32(request + 8, 480); put32(request + 12, 90);
    caller_output = malloc(encoded_size); assert(caller_output); memset(caller_output, 0xa5, encoded_size);
    size_t capacity = !strcmp(scenario, "enospc") ? 10 : encoded_size;
    rc = fcam_bridge_call(&origin, FCAM_OP_STILL, request, sizeof request, caller_output, capacity, &result);
    if (!strcmp(scenario, "transfer")) {
        assert(!rc && result.used == encoded_size && result.required == encoded_size && result.result_token == 77);
        assert(released == 1 && !cancelled && readback_closed == 1);
    } else if (!strcmp(scenario, "enospc")) {
        assert(rc == -ENOSPC && result.used == 0 && result.required == encoded_size && cancelled == 1 && !released);
        for (size_t i = 0; i < encoded_size; ++i) assert(caller_output[i] == 0xa5);
    } else if (!strcmp(scenario, "partial")) {
        assert(rc == -EIO && cancelled == 1 && !released && !readback_closed);
        assert(!memcmp(&before, &result, sizeof result));
        for (size_t i = 0; i < FCAM_DATA_BYTES; ++i) assert(caller_output[i] == encoded_byte(i));
        for (size_t i = FCAM_DATA_BYTES; i < encoded_size; ++i) assert(caller_output[i] == 0xa5);
    } else if (!strcmp(scenario, "latebuffer")) {
        assert(rc == -EIO && cancelled == 1 && released == 1 && !readback_closed);
        assert(!memcmp(&before, &result, sizeof result));
    } else if (!strcmp(scenario, "readback")) {
        assert(rc == -EIO && cancelled == 1 && !released && !readback_closed);
    } else if (!strcmp(scenario, "shortchunk")) {
        assert(rc == -EPROTO && !released && !readback_closed);
        for (size_t i = 0; i < encoded_size; ++i) assert(caller_output[i] == 0xa5);
    } else abort();
    free(caller_output); finish_server(host); return 0;
}
