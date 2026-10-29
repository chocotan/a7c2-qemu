"""Exercise the bounded CP release-lock reply against the captured request layout."""
from pathlib import Path
import subprocess


def test_captured_request_layout_and_reply_lease(tmp_path):
    source = Path(__file__).with_name('menu-observe.c').read_text()
    begin = source.index('static int cp_release_service(')
    end = source.index('/* SID 0x90280964', begin)
    function = source[begin:end]
    harness = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void *incoming, *sent_reply;
static unsigned int bytes, source_id, destination_id, sent_destination;
static int allocations, sends, frees, fail_alloc, fail_send;
static int (*real_allocate_msg)(unsigned int, void **, unsigned int, int);
static int (*real_send_msg)(unsigned int, void *);
static int (*real_free_msg)(unsigned int, void *);
static void (*real_set_source)(void *, unsigned int);
static unsigned int (*real_msg_size)(void *);
static unsigned int (*real_get_source)(void *);
static int allocate(unsigned int destination, void **reply, unsigned int size, int wait) {
    assert(destination == source_id && size == 12 && wait == 1);
    ++allocations;
    if (fail_alloc) return fail_alloc;
    *reply = calloc(1, size);
    assert(*reply);
    return 0;
}
static int send(unsigned int destination, void *reply) {
    assert(destination == source_id);
    ++sends;
    sent_reply = reply;
    sent_destination = destination_id;
    return fail_send;
}
static int release(unsigned int destination, void *reply) {
    assert(destination == source_id && reply == sent_reply);
    ++frees; free(reply); sent_reply = 0; return 0;
}
static void set_source(void *reply, unsigned int source) { (void)reply; destination_id = source; }
static unsigned int size_of(void *request) { assert(request == incoming); return bytes; }
static unsigned int source_of(void *request) { assert(request == incoming); return source_id; }
static void record(const char *prefix, const char *text) { (void)prefix; (void)text; }
'''
    harness += function + r'''
static void initialize(void) {
    real_allocate_msg = allocate;
    real_send_msg = send;
    real_free_msg = release;
    real_set_source = set_source;
    real_msg_size = size_of;
    real_get_source = source_of;
}
int main(void) {
    unsigned char request[16] = {5,0,0x3d,0x40,2,0,0,0x80,0,0x80,0,0,1,0,0,0};
    incoming = request; source_id = 0x80020002; bytes = sizeof request;
    initialize();
    assert(cp_release_service(0x90040193, request) == 0);
    assert(allocations == 1 && sends == 1 && sent_destination == 0x90040193);
    assert(destination_id == 0x90040193);
    const unsigned char *reply = sent_reply;
    assert(reply[0] == 1 && reply[2] == 0x3d && reply[3] == 0x40);
    assert(*(const unsigned int *)(reply+4) == 0x80000002);
    assert(*(const unsigned int *)(reply+8) == 0xf000);
    free(sent_reply); sent_reply = 0;
    request[0] = 4;
    assert(cp_release_service(0x90040193, request) == -1024 && allocations == 1 && sends == 1);
    request[0] = 5; fail_alloc = -55;
    assert(cp_release_service(0x90040193, request) == -55 && allocations == 2 && sends == 1);
    fail_alloc = 0; fail_send = -5;
    assert(cp_release_service(0x90040193, request) == -5 && allocations == 3 && sends == 2);
    free(sent_reply);
    assert(frees == 1);
    return 0;
}
'''
    path = tmp_path / 'release.c'
    path.write_text(harness)
    binary = tmp_path / 'release'
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    '-fsanitize=address,undefined', '-no-pie', str(path), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
