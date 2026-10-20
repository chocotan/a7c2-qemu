/* SPDX-License-Identifier: MIT */
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
