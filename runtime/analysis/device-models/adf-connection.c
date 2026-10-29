/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "adf-connection.h"
#include <unistd.h>
static int adf_native_prerequisites(void){
    struct scalar_connection_snapshot p;full_scalar_connection_snapshot(&p);
    return p.owner_pid==getpid() && p.initialized && p.native_guarded && p.clean_completion && p.ap_consumed==1 &&
        p.connections==1 && p.requests==1 && p.native_reply_frees==1 && p.waiter_frees==1 && p.queued==1 &&
        p.request_freed && p.reply_freed && !p.busy && !p.guard_held && !p.faults && !p.pending_event6 &&
        !p.event6_inflight && p.event6_consumed==1 && !p.retained_messages && !p.live_reply && !p.retained_request &&
        !p.retained_cleanup && !p.releasing_reply;
}
#define EDGE_OWNER_INIT full_adf_connection_owner_init
#define EDGE_NATIVE_DISPATCH full_adf_connection_native_dispatch
#define EDGE_NATIVE_PREREQUISITES adf_native_prerequisites
#define EDGE_TEST_EVENT_CORRUPT full_adf_connection_test_event_corrupt
#define EDGE_TEST_EVENT_CONSUME full_adf_connection_test_event_consume
/* CP raw8f43a skips the type5 pre-handler for this exact type0 peer.
 * raw8f476 calls the common connect and immediately returns: no post-handler. */
#define EDGE_TAG "ADF"
#define EDGE_DESCRIPTION "only-PinMem-OUT2-ADF-IN0"
#define EDGE_PASS_OTHER 1
#define SOURCE_INDEX 2u
#define SOURCE_SLOT 5u
#define PEER_INDEX 0u
#define PEER_SLOT 0u
#define PEER_CP FULL_ADF_CP
#define PEER_REGISTRY full_adf_registry
#define PEER_SNAPSHOT full_adf_snapshot
#define EDGE_DISPATCH full_adf_connection_dispatch
#define EDGE_RELEASE full_adf_connection_release
#define EDGE_SNAPSHOT full_adf_connection_snapshot
#define EDGE_RESET full_adf_connection_test_reset
#include "pin-peer-connection.inc"
