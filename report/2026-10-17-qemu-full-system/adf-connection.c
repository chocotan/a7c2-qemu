/* SPDX-License-Identifier: MIT */
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
