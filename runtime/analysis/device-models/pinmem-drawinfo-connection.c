/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "pinmem-drawinfo-connection.h"
#include "adf-connection.h"
#include "../drawinfo-registry.h"
#include <unistd.h>
/* The ninth owner recursively admits only the real guarded eighth/seventh
 * chain. Its unique AP reply must have been consumed before this owner. */
static int drawinfo_native_prerequisites(void)
{
    struct scalar_connection_snapshot p;
    full_adf_connection_snapshot(&p);
    return p.owner_pid==getpid() && p.initialized && p.native_guarded &&
        p.clean_completion && p.ap_consumed==1 && p.connections==1 &&
        p.requests==1 && p.queued==1 && p.request_freed==1 && p.reply_freed==1 &&
        p.native_reply_frees==1 && p.waiter_frees==1 &&
        !p.pending_event6 && !p.event6_inflight && p.event6_consumed==1 &&
        !p.faults && !p.busy && !p.guard_held && !p.retained_cleanup &&
        !p.retained_messages && !p.releasing_reply && !p.live_reply &&
        !p.retained_request;
}
/* Public CP f5 raw5d48de is exactly movs r0,#0; bx lr. The selected
 * DrawInfoRawManager +0xc reads no opaque constructor fields. Those fields
 * remain unprojected/unverified; no graphic initialization is claimed. */
#define EDGE_TAG "PINMEM_DRAWINFO"
#define EDGE_DESCRIPTION "only-PinMem-DRAWINFO0-DrawInfo-IN0"
#define EDGE_PASS_OTHER 1
#define SOURCE_TYPE 6u
#define SOURCE_INDEX 0u
#define SOURCE_SLOT 10u
#define PEER_INDEX 0u
#define PEER_SLOT 1u
#define PEER_CP NATIVE_DRAWINFO_CP
#define PEER_REGISTRY native_drawinfo_registry
#define PEER_SNAPSHOT native_drawinfo_snapshot
#define EDGE_OWNER_INIT full_pinmem_drawinfo_connection_owner_init
#define EDGE_NATIVE_DISPATCH full_pinmem_drawinfo_connection_native_dispatch
#define EDGE_NATIVE_PREREQUISITES drawinfo_native_prerequisites
#define EDGE_TEST_EVENT_CORRUPT full_pinmem_drawinfo_connection_test_event_corrupt
#define EDGE_TEST_EVENT_CONSUME full_pinmem_drawinfo_connection_test_event_consume
#define EDGE_DISPATCH full_pinmem_drawinfo_connection_dispatch
#define EDGE_RELEASE full_pinmem_drawinfo_connection_release
#define EDGE_SNAPSHOT full_pinmem_drawinfo_connection_snapshot
#define EDGE_RESET full_pinmem_drawinfo_connection_test_reset
#include "pin-peer-connection.inc"
