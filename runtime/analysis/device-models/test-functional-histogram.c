/* SPDX-License-Identifier: MIT */
/* Component fixture only: it does not run the core, RGB renderer or original AP. */
#define _GNU_SOURCE
#include "functional-histogram.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

#define D UINT32_C(0x80946189)
_Static_assert(FCAM_OP_HISTOGRAM == 10 && FCAM_HIST_CLASS == 6 && FCAM_HIST_PROOF_KIND == 6, "histogram opcode/class/proof contract");
_Static_assert(FCAM_HIST_INPUT_BYTES == 8 && FCAM_HIST_RESULT_BYTES == 1192 && FCAM_HIST_R_BINS == 168, "histogram result contract");
static const unsigned char request_wire[12] = {0x0d,0x20,0x48,1,12,0,1,0x80,1,1,0,0};
static const unsigned char ack_wire[12] = {0x0d,0x20,0x48,0x11,12,0,1,0x80,0,0,0x59,0};
static const unsigned char canonical[8] = {0x48,1,4,0,1,1,0,0};
static const char *scenario;
static struct message { unsigned char *p; unsigned int bytes, source, alive, owns; } messages[3];
static unsigned char model_copy[FCAM_HIST_RESULT_BYTES];
static unsigned int alloc_calls, send_calls, model_calls, free_calls[3], reserve_calls, release_calls, log_calls;
static unsigned int ready_calls;
static uint64_t tickets[3];
static long receive_tids[3], sender_tid;
static struct full_imaging_io io;
static struct native_cp_state_publication_guard guard;
static int *dispatch_output;
static pthread_mutex_t log_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t log_changed = PTHREAD_COND_INITIALIZER;
static pthread_t pending_ack;
static unsigned int ack_main_logged, ack_continue;
static int is(const char *s) { return !strcmp(scenario,s); }
static int starts(const char *s) { return !strncmp(scenario,s,strlen(s)); }
static long tid(void) { return syscall(SYS_gettid); }
static struct functional_histogram_snapshot snap(void) {
    struct functional_histogram_snapshot s = {0}; functional_histogram_snapshot(&s); return s;
}
static uint64_t fnv(const unsigned char *p, size_t n) {
    uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < n; i++) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static void put32(unsigned char *p, uint32_t x) {
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(x >> (i*8));
}
static void put64(unsigned char *p, uint64_t x) {
    for (unsigned int i = 0; i < 8; i++) p[i] = (unsigned char)(x >> (i*8));
}
static int locate(void *p) {
    for (unsigned int i = 0; i < 3; i++) if (messages[i].alive && messages[i].p == p) return (int)i;
    return -1;
}
static unsigned int size_of(void *p) {
    int i = locate(p); assert(i >= 0);
    if (is("evidence-overlap") && i == 1 && tid() != sender_tid) {
        assert(!pthread_mutex_lock(&log_mutex)); ack_main_logged = 1;
        assert(!pthread_cond_broadcast(&log_changed));
        while (!ack_continue) assert(!pthread_cond_wait(&log_changed,&log_mutex));
        assert(!pthread_mutex_unlock(&log_mutex));
    }
    return messages[i].bytes;
}
static unsigned int source_of(void *p) { int i = locate(p); assert(i >= 0); return messages[i].source; }
static void log_record(const char *tag, const char *text) {
    assert(!strncmp(tag,"FUNCTIONAL_HISTOGRAM_",21)); assert(text && strlen(text) < 2300);
    (void)snap();
    assert(!pthread_mutex_lock(&log_mutex)); log_calls++;
    if (starts("evidence-") || is("serial-exhaustion")) assert(fprintf(stdout,"%s%s\n",tag,text) > 0);
    if (is("evidence-overlap") && !strcmp(tag,"FUNCTIONAL_HISTOGRAM_SEND ") && strstr(text," event_role=2 ")) {
        ack_continue = 1; assert(!pthread_cond_broadcast(&log_changed));
    }
    if (is("evidence-interleaved") && !strcmp(tag,"FUNCTIONAL_HISTOGRAM_RECEIVE ") &&
        strstr(text," event_role=2 ")) {
        ack_main_logged = 1; assert(!pthread_cond_broadcast(&log_changed));
        while (!ack_continue) assert(!pthread_cond_wait(&log_changed,&log_mutex));
    }
    assert(!pthread_mutex_unlock(&log_mutex));
}
static int reserve(void) {
    reserve_calls++; assert(snap().busy); assert(!snap().guard_held);
    if (is("bind-busy")) {
        assert(functional_histogram_bind_queue(D) == -EBUSY);
        assert(functional_histogram_bind_queue(D + 1) == -ESTALE);
        assert(!snap().model_complete && !snap().requests);
    }
    if (is("reentrant-dispatch")) {
        int rc = 41; assert(functional_histogram_dispatch(FUNCTIONAL_HISTOGRAM_SID,messages[0].p,&io,&guard,1,&rc) == 1);
        assert(rc == -EBUSY);
    }
    return is("guard-fail") ? -EACCES : is("guard-positive") ? 1 : 0;
}
static void guard_release(void) { release_calls++; assert(snap().busy); assert(!snap().guard_held); }
static int ready(void) { ready_calls++; (void)snap(); return is("guard-miss") ? 0 : is("guard-lost") && ready_calls > 1 ? 0 : 1; }
static int actual_free(unsigned int destination, void *p) {
    const int found = locate(p); assert(found >= 0);
    const unsigned int i = (unsigned int)found;
    assert(destination == (i ? D : FUNCTIONAL_HISTOGRAM_SID)); assert(snap().leases[i].releasing);
    if (!i) assert(snap().original_request == p);
    free_calls[i]++;
    if (is("reentrant-free")) {
        int rc = 41;
        assert(functional_histogram_release_cycle(destination,p,1,actual_free,log_record,&rc) == 1);
        assert(rc == -EBUSY);
    }
    if ((i == 0 && is("request-free-fail")) || (i == 1 && is("ack-free-fail")) ||
        (i == 2 && is("notify-free-fail"))) return -EIO;
    if (i == 0 && (is("request-address-reuse") || is("foreign-retired-reuse"))) {
        messages[i].alive = 0; return 0;
    }
    free(messages[i].p); messages[i].p = NULL; messages[i].alive = messages[i].owns = 0; return 0;
}
static void *free_other_thread(void *arg) {
    const unsigned int role = *(const unsigned int *)arg;
    int rc = 41;
    assert(functional_histogram_release_cycle(D,messages[role].p,tickets[role],actual_free,log_record,&rc) == 1);
    assert(rc == -EPROTO && !free_calls[role]);
    return NULL;
}
static void *receive_thread(void *arg) {
    const unsigned int role = *(const unsigned int *)arg;
    receive_tids[role] = tid();
    assert(functional_histogram_observe_receive_cycle(D,messages[role].p,FUNCTIONAL_HISTOGRAM_SID,
        messages[role].bytes,&tickets[role]) == 1);
    assert(tickets[role] == 1);
    if (role == 2 || is("foreign-ack-free")) {
        if (role == 2 && starts("free-notify-")) {
            if (strstr(scenario,"source")) messages[role].source = D;
            if (strstr(scenario,"size")) messages[role].bytes--;
            if (strstr(scenario,"wire")) messages[role].p[1033] ^= 1;
        }
        int rc = 41;
        assert(functional_histogram_release_cycle(strstr(scenario,"free-notify-destination") ? 42 : D,
            messages[role].p,tickets[role],actual_free,log_record,&rc) == 1);
        assert(rc == (is("foreign-ack-free") || starts("free-notify-") ? -EPROTO : is("notify-free-fail") ? -EIO : 0));
        if (starts("free-notify-")) assert(!free_calls[role]);
    }
    return NULL;
}
static void receive_foreign(unsigned int role) {
    pthread_t thread; assert(!pthread_create(&thread,NULL,receive_thread,&role)); assert(!pthread_join(thread,NULL));
}
static void set_source(void *p, unsigned int source) {
    int i = locate(p); assert(i > 0);
    if ((i == 1 && is("ack-source-fail")) || (i == 2 && is("notify-source-fail"))) return;
    messages[i].source = source;
    if ((i == 1 && is("ack-copy-corrupt")) || (i == 2 && is("notify-copy-corrupt"))) messages[i].p[messages[i].bytes - 1] ^= 1;
}
static int allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int kind) {
    const unsigned int role = ++alloc_calls;
    assert(role < 3 && destination == D && kind == 1 && snap().leases[0].freed);
    assert(bytes == (role == 1 ? 12u : 1034u));
    const char *prefix = role == 1 ? "ack-" : "notify-";
    char key[96]; snprintf(key,sizeof key,"%salloc-fail",prefix);
    if (is(key)) return -ENOMEM;
    if (role == 2 && is("alloc-live-alias")) { *out = messages[1].p; return 0; }
    if (role == 2 && is("alloc-interior-alias")) { *out = messages[1].p + 1; return 0; }
    if (is("alloc-state-alias")) { *out = functional_histogram_test_state_address(); return 0; }
    if (is("alloc-constant-alias")) { *out = (void *)functional_histogram_test_constant_address(); return 0; }
    if (is("alloc-serial-alias")) { *out = functional_histogram_test_serial_address(); return 0; }
    if (is("alloc-io-alias")) { *out = &io; return 0; }
    if (is("alloc-guard-alias")) { *out = &guard; return 0; }
    if (is("alloc-result-alias")) { *out = dispatch_output; return 0; }
    if (is("alloc-wrap")) { *out = (void *)(UINTPTR_MAX - 2u); return 0; }
    if (role == 1 && is("request-address-reuse")) {
        messages[role] = messages[0]; messages[0].owns = 0; messages[0].p = NULL;
        messages[role].alive = 1; messages[role].bytes = bytes; messages[role].source = 0;
    } else {
        messages[role] = (struct message){.p = malloc(1034), .bytes = bytes, .alive = 1, .owns = 1};
        assert(messages[role].p); memset(messages[role].p,0xcc,1034);
    }
    *out = messages[role].p;
    snprintf(key,sizeof key,"%salloc-dirty-fail",prefix); if (is(key)) return -ENOMEM;
    snprintf(key,sizeof key,"%salloc-short",prefix); if (is(key)) messages[role].bytes--;
    snprintf(key,sizeof key,"%salloc-long",prefix); if (is(key)) messages[role].bytes++;
    return 0;
}
static int send_message(unsigned int destination, void *p) {
    const unsigned int role = (unsigned int)locate(p);
    assert(destination == D && role == ++send_calls);
    assert(source_of(p) == FUNCTIONAL_HISTOGRAM_SID);
    assert(snap().leases[role].send_inflight && !snap().leases[role].queued);
    if (role == 1) assert(!memcmp(p,ack_wire,12));
    else {
        const unsigned char *wire = p;
        assert(size_of(p) == 1034 && !memcmp(wire,"\x0d\x20\x0c\x21\x0a\x04\x01\x80\x01\x00",10));
        assert(!memcmp(wire + 10,model_copy + FCAM_HIST_R_BINS,1024));
    }
    if (is("evidence-interleaved") || is("evidence-overlap")) {
        if (role == 1) {
            static unsigned int ack_role = 1;
            assert(!pthread_create(&pending_ack,NULL,receive_thread,&ack_role));
            assert(!pthread_mutex_lock(&log_mutex));
            while (!ack_main_logged) assert(!pthread_cond_wait(&log_changed,&log_mutex));
            assert(!pthread_mutex_unlock(&log_mutex));
        } else receive_foreign(2);
    }
    if (is("inline") || is("evidence-inline") || is("inline-send-fail") || is("inline-notify-send-fail")) {
        if (role == 1) {
            receive_foreign(1); int rc = 41;
            assert(functional_histogram_release_cycle(D,p,tickets[1],actual_free,log_record,&rc) == 1 && rc == 0);
        } else receive_foreign(2);
        assert(!snap().leases[role].consumed);
    }
    return (role == 1 && (is("ack-send-fail") || is("inline-send-fail"))) ||
        (role == 2 && (is("notify-send-fail") || is("inline-notify-send-fail"))) ? -EPIPE : 0;
}
int fcam_bridge_histogram(const struct fcam_native_origin *origin, const unsigned char input[8],
    unsigned char out[1192], struct fcam_bridge_result *result) {
    model_calls++;
    assert(origin->source == D && origin->destination == FUNCTIONAL_HISTOGRAM_SID && origin->command == 0x0148 && origin->bytes == 12);
    assert(origin->wire_fnv1a64 == fnv(request_wire,12)); assert(!memcmp(input,canonical,8));
    assert(snap().guard_held && !snap().request_owned);
    if (is("probing-output-alias")) {
        unsigned char original[12]; memcpy(original,messages[0].p,12);
        functional_histogram_snapshot((struct functional_histogram_snapshot *)(void *)messages[0].p);
        functional_histogram_snapshot((struct functional_histogram_snapshot *)(void *)dispatch_output);
        assert(!functional_histogram_release_cycle(FUNCTIONAL_HISTOGRAM_SID,messages[0].p,1,actual_free,log_record,
            (int *)(void *)messages[0].p));
        assert(!memcmp(original,messages[0].p,12) && *dispatch_output == -EINVAL);
    }
    memset(out,0,1192);
    put32(out + 0,FCAM_ABI_VERSION); put32(out + 4,1192); put64(out + 8,987654321);
    put64(out + 16,43); put64(out + 24,18); put64(out + 32,73);
    put64(out + 40,fnv(input,8)); put64(out + 48,UINT64_C(0x1122334455667788));
    put64(out + 56,UINT64_C(0x1122334455667788)); put64(out + 64,921600);
    put32(out + 72,640); put32(out + 76,480); put32(out + 80,1920); put32(out + 84,FCAM_VDF_ENDPOINT);
    for (unsigned int i = 88; i <= 116; i += 4) put32(out + i,i == 96 ? FCAM_HIST_CLASS : 1);
    out[128] = 1; out[129] = out[130] = 5;
    put64(out + 144,17); put64(out + 152,42); memcpy(out + 160,canonical,8);
    for (unsigned int c = 0; c < 4; c++) for (unsigned int i = 0; i < 256; i++)
        out[168 + c * 256u + i] = (unsigned char)((i * (2*c + 1) + c * 37) & 255);
    *result = (struct fcam_bridge_result){.used = 1192,.required = 1192,.model_instance = 987654321};
    if (starts("evidence-")) {
        assert(fread(out,1,1192,stdin) == 1192 && fgetc(stdin) == EOF && !ferror(stdin));
        result->model_instance = 0;
        for (unsigned int i = 0; i < 8; i++) result->model_instance |= (uint64_t)out[8 + i] << (i * 8);
    }
    if (starts("result-byte-")) {
        const int offset = atoi(scenario + strlen("result-byte-"));
        out[offset] ^= offset == 132 ? 0x80 : 1;
    }
    if (starts("bins-zero-")) memset(out + 168 + 256u * (unsigned int)atoi(scenario + strlen("bins-zero-")),0,256);
    if (starts("bins-no-peak-")) memset(out + 168 + 256u * (unsigned int)atoi(scenario + strlen("bins-no-peak-")),254,256);
    if (is("bins-last-byte")) out[1191] ^= 1;
    if (is("result-short")) result->used--;
    if (is("result-long")) result->used++;
    if (is("result-required")) result->required--;
    if (is("result-instance")) result->model_instance++;
    if (is("result-zero-instance")) { result->model_instance = 0; put64(out + 8,0); }
    if (is("result-token")) result->result_token = 1;
    if (is("result-zero-hashes")) { put64(out + 48,0); put64(out + 56,0); }
    if (is("result-zero-lease")) put64(out + 32,0);
    if (is("result-config-overflow")) { put64(out + 152,UINT64_MAX); put64(out + 16,0); }
    if (is("result-frame-overflow")) { put64(out + 144,UINT64_MAX); put64(out + 24,0); }
    if (is("result-config-zero")) { put64(out + 152,0); put64(out + 16,1); }
    if (is("result-canary")) out[1192] = 0;
    if (is("mutated-input")) ((unsigned char *)input)[7] = 1;
    if (is("mutated-request")) messages[0].p[11] = 1;
    if (is("mutated-source")) messages[0].source++;
    if (is("mutated-size")) messages[0].bytes--;
    memcpy(model_copy,out,1192);
    return is("bridge-error") ? -ENOTSUP : is("bridge-positive") ? 1 : 0;
}
static void cleanup(void) {
    for (unsigned int i = 0; i < 3; i++) if (messages[i].owns) free(messages[i].p);
}
static int run_dispatch(int enabled) {
    int result = 41; dispatch_output = &result;
    assert(functional_histogram_dispatch(FUNCTIONAL_HISTOGRAM_SID,messages[0].p,&io,&guard,enabled,&result) == 1);
    dispatch_output = NULL; return result;
}
static void assert_refused(void) {
    assert(run_dispatch(1) < 0);
    struct functional_histogram_snapshot s = snap();
    assert(!s.request_owned && !s.requests && !s.ap_consumed && !alloc_calls && !send_calls && !free_calls[0]);
    assert(messages[0].alive); assert(!s.busy && !s.guard_held);
}
static void fork_checks(void) {
    functional_histogram_test_hold_lock();
    pid_t child = fork(); assert(child >= 0);
    if (!child) {
        assert(functional_histogram_owner_init() == -EXDEV);
        assert(functional_histogram_bind_queue(D) == -EXDEV);
        assert(snap().faults);
        assert(run_dispatch(1) == -EXDEV);
        uint64_t ticket = 0;
        assert(functional_histogram_observe_receive_cycle(D,messages[0].p,FUNCTIONAL_HISTOGRAM_SID,12,&ticket) == -EXDEV);
        int rc = 41;
        assert(functional_histogram_release_cycle(D,messages[0].p,1,actual_free,log_record,&rc) == 1 && rc == -EXDEV);
        _exit(0);
    }
    int status; assert(waitpid(child,&status,0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    functional_histogram_test_drop_lock();
}
int main(int argc, char **argv) {
    assert(argc == 2); scenario = argv[1]; sender_tid = tid();
    io = (struct full_imaging_io){allocate,actual_free,set_source,send_message,size_of,source_of,log_record};
    guard = (struct native_cp_state_publication_guard){reserve,guard_release,ready};
    messages[0] = (struct message){.p = malloc(1034),.bytes = 12,.source = D,.alive = 1,.owns = 1};
    assert(messages[0].p); memcpy(messages[0].p,request_wire,12);
    if (is("bind-before-init")) { assert(functional_histogram_bind_queue(D) == -ENODEV); cleanup(); return 0; }
    if (is("uninitialized")) { assert_refused(); cleanup(); return 0; }
    assert(!functional_histogram_owner_init()); assert(functional_histogram_owner_init() == -EALREADY);
    assert(functional_histogram_bind_queue(0) == -EINVAL);
    assert(functional_histogram_bind_queue(UINT32_MAX) == -EINVAL);
    assert(functional_histogram_bind_queue(FUNCTIONAL_HISTOGRAM_SID) == -EINVAL);
    if (is("unbound")) { assert_refused(); cleanup(); return 0; }
    assert(!functional_histogram_bind_queue(D)); assert(!functional_histogram_bind_queue(D));
    assert(functional_histogram_bind_queue(D + 1) == -ESTALE);
    assert(!snap().model_complete && !snap().requests && !snap().ap_consumed);
    if (is("fork-held-lock")) { fork_checks(); cleanup(); return 0; }
    if (is("disabled") || is("enabled-two") || is("unrelated") || is("wrong-command") || is("wrong-kind") ||
        is("wrong-destination") || is("null-request") || is("null-io") || is("null-result") || is("short-header")) {
        int result = 41;
        if (is("unrelated")) messages[0].p[0] = 5;
        if (is("wrong-command")) messages[0].p[2]++;
        if (is("wrong-kind")) messages[0].p[3]++;
        if (is("short-header")) messages[0].bytes = 3;
        assert(functional_histogram_dispatch(is("wrong-destination") ? 42 : FUNCTIONAL_HISTOGRAM_SID,
            is("null-request") ? NULL : messages[0].p,is("null-io") ? NULL : &io,&guard,
            is("disabled") ? 0 : is("enabled-two") ? 2 : 1,is("null-result") ? NULL : &result) == 0);
        assert(result == 41 && !model_calls); cleanup(); return 0;
    }
    if (is("result-alias-request") || is("result-alias-io") || is("result-alias-guard") || is("result-alias-state")) {
        int *result = is("result-alias-request") ? (int *)(void *)messages[0].p :
            is("result-alias-io") ? (int *)(void *)&io : is("result-alias-guard") ? (int *)(void *)&guard :
            (int *)functional_histogram_test_state_address();
        assert(!functional_histogram_dispatch(FUNCTIONAL_HISTOGRAM_SID,messages[0].p,&io,&guard,1,result));
        assert(!model_calls && !memcmp(messages[0].p,request_wire,12)); cleanup(); return 0;
    }
    int refusal = 0;
    if (starts("request-byte-")) { messages[0].p[atoi(scenario + strlen("request-byte-"))] ^= 1; refusal = 1; }
    if (is("short-request")) { messages[0].bytes = 11; refusal = 1; }
    if (is("long-request") || is("legacy-mode0-0x800")) { messages[0].bytes = is("long-request") ? 13 : 0x800; refusal = 1; }
    if (is("mode0")) { messages[0].p[9] = 0; refusal = 1; }
    if (is("disable-request")) { messages[0].p[8] = 0; refusal = 1; }
    if (is("wrong-source") || is("source-Q")) { messages[0].source = is("source-Q") ? FUNCTIONAL_HISTOGRAM_SID : D + 1; refusal = 1; }
    if (is("missing-guard")) { guard.predecessor_ready = NULL; refusal = 1; }
    if (is("missing-callback")) { io.send = NULL; refusal = 1; }
    if (starts("result-") || starts("bins-zero-") || starts("bins-no-peak-") || starts("mutated-") ||
        starts("guard-") || starts("bridge-")) refusal = 1;
    if (refusal) { assert_refused(); cleanup(); return 0; }
    if (is("null-guard")) {
        int result = 41; assert(functional_histogram_dispatch(FUNCTIONAL_HISTOGRAM_SID,messages[0].p,&io,NULL,1,&result) == 1);
        assert(result < 0 && !model_calls); cleanup(); return 0;
    }
    if (is("serial-exhaustion")) functional_histogram_test_exhaust_serial();
    assert(run_dispatch(1) == 0);
    struct functional_histogram_snapshot s = snap();
    assert(s.request_owned && s.requests == 1 && s.model_complete && model_calls == 1);
    assert(!pthread_mutex_lock(&log_mutex)); const unsigned int seen_log_calls = log_calls;
    assert(!pthread_mutex_unlock(&log_mutex));
    assert(reserve_calls == 1 && release_calls == 1 && !s.busy && !s.guard_held && seen_log_calls);
    assert(s.ap_consumed == (unsigned int)(is("inline") || is("evidence-inline")));
    assert(!s.capture_verified && !s.physical_asic_verified && !s.ui_applied);
    assert(!memcmp(s.model_result,model_copy,1192));
    assert(s.model_result_fnv1a64 == fnv(model_copy,1192));
    assert(s.notification_selector == 1 && !memcmp(s.notification_wire + 10,model_copy + 168,1024));
    assert(s.notification_fnv1a64 == fnv(s.notification_wire,1034));
    for (unsigned int c = 0; c < 4; c++) assert(s.channel_fnv1a64[c] == fnv(model_copy + 168 + c * 256u,256));
    if (s.faults) {
        assert(!s.ap_consumed);
        if (is("request-free-fail")) {
            assert(!alloc_calls && !send_calls && s.leases[0].pointer == messages[0].p);
            int result = 41;
            assert(functional_histogram_release_cycle(FUNCTIONAL_HISTOGRAM_SID,messages[0].p,1,actual_free,log_record,&result) == 1);
            assert(result == -EIO && free_calls[0] == 1);
        }
        for (unsigned int i = 1; i < 3; i++) if (s.allocation_returned[i] && !s.allocation_alias[i] && !s.leases[i].freed)
            assert(s.leases[i].pointer == s.allocation_returned[i]);
        if (is("inline-send-fail")) assert(s.leases[1].freed && !s.leases[1].pointer && !s.leases[1].queued);
        if (is("inline-notify-send-fail")) assert(s.leases[2].freed && !s.leases[2].pointer && !s.leases[2].queued);
        cleanup(); return 0;
    }
    if (is("evidence-interleaved") || is("evidence-overlap")) {
        assert(!pthread_mutex_lock(&log_mutex)); ack_continue = 1;
        assert(!pthread_cond_broadcast(&log_changed)); assert(!pthread_mutex_unlock(&log_mutex));
        assert(!pthread_join(pending_ack,NULL));
        int rc = 41;
        assert(functional_histogram_release_cycle(D,messages[1].p,tickets[1],actual_free,log_record,&rc) == 1 && !rc);
        s = snap(); assert(s.ap_consumed && s.leases[1].receiver_tid != s.leases[1].free_tid);
        assert(s.leases[2].receiver_tid == s.leases[2].free_tid); cleanup(); return 0;
    }
    if (is("inline") || is("evidence-inline")) { assert(s.ap_consumed); cleanup(); return 0; }
    assert(alloc_calls == 2 && send_calls == 2 && free_calls[0] == 1);
    if (is("foreign-retired-reuse")) {
        messages[0].alive = 1; messages[0].source = 42; messages[0].bytes = 12; messages[0].p[0] = 3;
        int rc = 41; uint64_t ticket = 0;
        assert(!functional_histogram_release_cycle(FUNCTIONAL_HISTOGRAM_SID,messages[0].p,1,actual_free,log_record,&rc));
        assert(!functional_histogram_observe_receive_cycle(D,messages[0].p,FUNCTIONAL_HISTOGRAM_SID,12,&ticket));
        assert(!functional_histogram_dispatch(FUNCTIONAL_HISTOGRAM_SID,messages[0].p,&io,&guard,1,&rc));
    }
    if (is("no-receive") || is("evidence-no-receive") || is("free-before-receive")) {
        if (is("free-before-receive")) {
            int result = 41;
            assert(functional_histogram_release_cycle(D,messages[1].p,1,actual_free,log_record,&result) == 1 && result == -EPROTO);
            assert(!free_calls[1]);
        }
        assert(!snap().ap_consumed); cleanup(); return 0;
    }
    if (is("receive-null-ticket") || is("receive-alias-ticket") || is("snapshot-alias") ||
        is("free-result-alias") || is("unknown-pointer")) {
        unsigned char saved[12]; memcpy(saved,messages[1].p,12);
        if (is("receive-null-ticket") || is("receive-alias-ticket")) {
            assert(functional_histogram_observe_receive_cycle(D,messages[1].p,FUNCTIONAL_HISTOGRAM_SID,12,
                is("receive-null-ticket") ? NULL : (uint64_t *)(void *)messages[1].p) == -EINVAL);
        } else if (is("snapshot-alias")) {
            functional_histogram_snapshot((struct functional_histogram_snapshot *)(void *)messages[1].p);
            functional_histogram_snapshot(functional_histogram_test_state_address());
        } else if (is("free-result-alias")) {
            assert(!functional_histogram_release_cycle(D,messages[1].p,1,actual_free,log_record,(int *)(void *)messages[1].p));
        } else {
            unsigned char unknown[12] = {0}; int result = 41; uint64_t ticket = 0;
            assert(!functional_histogram_observe_receive_cycle(D,unknown,FUNCTIONAL_HISTOGRAM_SID,12,&ticket));
            assert(!functional_histogram_release_cycle(D,unknown,1,actual_free,log_record,&result));
            assert(result == 41 && !ticket);
        }
        assert(!memcmp(saved,messages[1].p,12) && !free_calls[1] && !snap().leases[1].received);
        cleanup(); return 0;
    }
    if (is("no-second-sample") || is("duplicate-owned-dispatch")) {
        int result = 41;
        if (is("duplicate-owned-dispatch")) {
            assert(functional_histogram_dispatch(FUNCTIONAL_HISTOGRAM_SID,messages[1].p,&io,&guard,1,&result) == 1 && result == -EALREADY);
        } else {
            const struct message saved = messages[0];
            unsigned char next[12]; memcpy(next,request_wire,12);
            messages[0] = (struct message){.p = next,.bytes = 12,.source = D,.alive = 1};
            assert(run_dispatch(1) == -EALREADY && !memcmp(next,request_wire,12));
            messages[0] = saved;
        }
        assert(model_calls == 1 && !snap().ap_consumed); cleanup(); return 0;
    }
    if (starts("receive-ack-") || starts("receive-notify-")) {
        const unsigned int role = strstr(scenario,"notify") ? 2u : 1u;
        if (strstr(scenario,"meta-source")) messages[role].source = D;
        if (strstr(scenario,"meta-size")) messages[role].bytes--;
        if (strstr(scenario,"wire")) messages[role].p[messages[role].bytes - 1] ^= 1;
        uint64_t ticket = 0;
        assert(functional_histogram_observe_receive_cycle(strstr(scenario,"destination") ? 42 : D,messages[role].p,
            strstr(scenario,"bad-source") ? D : FUNCTIONAL_HISTOGRAM_SID,
            (role == 1 ? 12u : 1034u) - (strstr(scenario,"bad-size") ? 1u : 0u),&ticket) < 0);
        assert(!ticket && !snap().ap_consumed && !snap().leases[role].received); cleanup(); return 0;
    }
    receive_foreign(1); s = snap();
    assert(s.leases[1].receiver_tid == receive_tids[1] && s.leases[1].sender_tid == tid() && receive_tids[1] != tid());
    if (is("foreign-ack-free")) { assert(s.faults && !free_calls[1]); cleanup(); return 0; }
    if (is("duplicate-receive")) {
        uint64_t ticket = 0; assert(functional_histogram_observe_receive_cycle(D,messages[1].p,FUNCTIONAL_HISTOGRAM_SID,12,&ticket) == -EPROTO);
        assert(!snap().ap_consumed); cleanup(); return 0;
    }
    if (is("receive-only")) { assert(!s.ap_consumed && !s.leases[1].freed); cleanup(); return 0; }
    if (is("free-null-callback")) {
        int result = 41;
        assert(functional_histogram_release_cycle(D,messages[1].p,tickets[1],NULL,log_record,&result) == 1 && result == -EPROTO);
        assert(!free_calls[1] && !snap().ap_consumed); cleanup(); return 0;
    }
    if (is("no-ticket") || is("wrong-ticket")) {
        int rc = 41; assert(functional_histogram_release_cycle(D,messages[1].p,is("no-ticket") ? 0 : 2,actual_free,log_record,&rc) == 1);
        assert(rc == -ESTALE && !free_calls[1]); cleanup(); return 0;
    }
    if (starts("free-ack-")) {
        if (strstr(scenario,"source")) messages[1].source = D;
        if (strstr(scenario,"size")) messages[1].bytes--;
        if (strstr(scenario,"wire")) messages[1].p[11] ^= 1;
        int rc = 41;
        assert(functional_histogram_release_cycle(strstr(scenario,"destination") ? 42 : D,messages[1].p,tickets[1],actual_free,log_record,&rc) == 1);
        assert(rc == -EPROTO && !free_calls[1] && !snap().ap_consumed); cleanup(); return 0;
    }
    void *old_ack = messages[1].p;
    int rc = 41;
    assert(functional_histogram_release_cycle(D,messages[1].p,tickets[1],actual_free,log_record,&rc) == 1);
    assert(rc == (is("ack-free-fail") ? -EIO : 0));
    s = snap(); assert(!s.ap_consumed && !s.notification_consumed);
    if (is("ack-free-fail")) {
        assert(functional_histogram_release_cycle(D,messages[1].p,tickets[1],actual_free,log_record,&rc) == 1 && rc == -EIO);
        assert(free_calls[1] == 1); cleanup(); return 0;
    }
    assert(s.ack_consumed);
    if (is("ack-only")) { cleanup(); return 0; }
    if (is("wrong-notify-free-thread")) {
        assert(functional_histogram_observe_receive_cycle(D,messages[2].p,FUNCTIONAL_HISTOGRAM_SID,1034,&tickets[2]) == 1);
        pthread_t thread; unsigned int role = 2;
        assert(!pthread_create(&thread,NULL,free_other_thread,&role)); assert(!pthread_join(thread,NULL));
        assert(!snap().ap_consumed && snap().leases[2].pointer); cleanup(); return 0;
    }
    receive_foreign(2); s = snap();
    if (is("notify-free-fail") || starts("free-notify-")) {
        assert(!s.ap_consumed && s.leases[2].pointer);
        if (is("notify-free-fail")) assert(s.free_attempted[2] && free_calls[2] == 1);
        cleanup(); return 0;
    }
    assert(s.ap_consumed && s.ack_consumed && s.notification_consumed && !s.faults);
    assert(s.leases[1].free_tid == s.leases[1].sender_tid && s.leases[1].free_tid != s.leases[1].receiver_tid);
    assert(s.leases[2].free_tid == s.leases[2].receiver_tid);
    assert(!functional_histogram_release_cycle(D,old_ack,tickets[1],actual_free,log_record,&rc));
    uint64_t old_ticket = 0;
    assert(!functional_histogram_observe_receive_cycle(D,old_ack,FUNCTIONAL_HISTOGRAM_SID,12,&old_ticket));
    assert(!functional_histogram_bind_queue(D) && functional_histogram_bind_queue(D + 1) == -ESTALE);
    if (messages[0].owns) free(messages[0].p);
    unsigned char new_request[12]; memcpy(new_request,request_wire,12);
    messages[0].p = new_request; messages[0].bytes = 12; messages[0].source = D; messages[0].alive = 1; messages[0].owns = 0;
    assert(run_dispatch(1) == -EALREADY && model_calls == 1 && !memcmp(new_request,request_wire,12));
    cleanup(); return 0;
}
