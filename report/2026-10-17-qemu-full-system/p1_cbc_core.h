#ifndef P1_CBC_CORE_H
#define P1_CBC_CORE_H

#include <stddef.h>
#include <stdint.h>

#define P1_CBC_PROFILE "official-k8-cbc-core-v1"
#define P1_CBC_ASSET_SHA256 "eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31"
#define P1_CBC_KEY_SOURCE "fwtool/sony/constants.py:key_cxd90057_k8@beaed6b7beb90d8dc513b53640535d5594855fcfaeb183b9504ea22286378cb3"
#define P1_CBC_FORMAT_SOURCE "fwtool/sony/fdat.py@962b570e68a407d5ca1b5d47923641ca0ae8d7e33b2e03348bae0b1187b6b64d"
#define P1_CBC_MAX_CHUNK 1024u
#include "p1_cbc_stock_limits.h"
#define P1_CBC_MAX_STREAM P1_STOCK_CBC_BYTES
#define P1_CBC_MAX_GENERATIONS 16u
#define P1_CBC_MAX_OPERATION_NS UINT64_C(250000000)

struct p1_cbc;

enum p1_cbc_error {
    P1_CBC_OK = 0, P1_CBC_E_ARGUMENT, P1_CBC_E_OFF, P1_CBC_E_CONFIG,
    P1_CBC_E_STATE, P1_CBC_E_EPOCH, P1_CBC_E_OPERATION, P1_CBC_E_CONTEXT,
    P1_CBC_E_LENGTH, P1_CBC_E_LEASE, P1_CBC_E_CAPACITY, P1_CBC_E_CRYPTO,
    P1_CBC_E_LIMIT, P1_CBC_E_PROCESS, P1_CBC_E_CLOCK, P1_CBC_E_TIMEOUT
};

struct p1_cbc_config {
    const char *profile, *asset_sha256, *key_source, *format_source;
    uint64_t epoch;
    const uint8_t *key, *iv;
    size_t key_length, iv_length;
};

/* Model memory only: readable/writable allocation, never a borrowed native OSAL packet.
 * The caller owns it throughout; the core never allocates or frees this memory. */
struct p1_cbc_lease {
    uint64_t epoch, serial;
    uint8_t *packet;
    size_t allocation_capacity, payload_capacity;
};

/* Typed fields correspond only to the known five-u64 helper body, not a native ABI. */
struct p1_cbc_request {
    uint64_t operation;
    uint8_t context[8];
    uint64_t field16, field24, input_length;
};

struct p1_cbc_result {
    enum p1_cbc_error error;
    uint64_t operation_status; /* 1 only after model consumption; 0 on every refusal. */
    size_t output_length;
    uint64_t elapsed_ns;
};

/* Constructor is OFF; no environment, constructor hook, worker or native integration.
 * One process, one sequential receiver, no concurrent calls (including creation).
 * Backend is the installed OpenSSL EVP API; no private AES_KEY layout or callback.
 * Each dispatch does at most 64 AES blocks. A late result is refused before commit;
 * this is not a preemptive wall-clock deadline for a stalled crypto library. */
struct p1_cbc *p1_cbc_new(void);
void p1_cbc_delete(struct p1_cbc *core);
enum p1_cbc_error p1_cbc_configure(struct p1_cbc *, const struct p1_cbc_config *);
enum p1_cbc_error p1_cbc_borrow(struct p1_cbc *, const struct p1_cbc_lease *);
struct p1_cbc_result p1_cbc_apply(struct p1_cbc *, const struct p1_cbc_lease *,
                               const struct p1_cbc_request *);
/* Invalidates model context and any model borrow, zeroes key/IV; no native free/ACK.
 * Next configure requires a strictly greater epoch. Tokens have no crypto authority. */
enum p1_cbc_error p1_cbc_retire(struct p1_cbc *, uint64_t epoch, const uint8_t context[8]);

#endif
