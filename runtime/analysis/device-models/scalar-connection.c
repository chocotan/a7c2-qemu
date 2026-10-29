/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "scalar-connection.h"
#include "vef-pinmem-control-connection.h"
#include <unistd.h>
/* Old full-system builds omit edge7; native admission then remains closed. */
extern void full_vef_pinmem_control_connection_snapshot(struct full_vef_pinmem_control_connection_snapshot *) __attribute__((weak));
static int scalar_native_prerequisites(void){
    if(!full_vef_pinmem_control_connection_snapshot)return 0;
    struct full_vef_pinmem_control_connection_snapshot p;full_vef_pinmem_control_connection_snapshot(&p);
    return p.owner_pid==getpid() && p.initialized && p.clean_completion && p.ap_consumed==1 && p.connections==1 && p.requests==1 &&
        p.queued==1 && p.request_freed && p.reply_freed && !p.busy && !p.guard_held && !p.faults && !p.retained_messages &&
        !p.live_reply && !p.retained_request && !p.retained_cleanup && !p.releasing_reply && p.event8_consumed==1 &&
        !p.event8_pending && !p.event8_inflight && p.manager_calls==1 && !p.manager_return && p.source_ordinal==15 &&
        p.posthook_checked && p.posthook_no_format && !p.callback_selected;
}
#define EDGE_OWNER_INIT full_scalar_connection_owner_init
#define EDGE_NATIVE_DISPATCH full_scalar_connection_native_dispatch
#define EDGE_NATIVE_PREREQUISITES scalar_native_prerequisites
#define EDGE_TEST_EVENT_CORRUPT full_scalar_connection_test_event_corrupt
#define EDGE_TEST_EVENT_CONSUME full_scalar_connection_test_event_consume
#define EDGE_TAG "SCALAR"
#define EDGE_DESCRIPTION "only-PinMem-OUT1-Scalar-IN4"
#define EDGE_PASS_OTHER 0
#define SOURCE_INDEX 1u
#define SOURCE_SLOT 4u
#define PEER_INDEX 4u
#define PEER_SLOT 4u
#define PEER_CP FULL_SCALAR_CP
#define PEER_REGISTRY full_scalar_registry
#define PEER_SNAPSHOT full_scalar_snapshot
#define EDGE_DISPATCH full_scalar_connection_dispatch
#define EDGE_RELEASE full_scalar_connection_release
#define EDGE_SNAPSHOT full_scalar_connection_snapshot
#define EDGE_RESET full_scalar_connection_test_reset
#include "pin-peer-connection.inc"
