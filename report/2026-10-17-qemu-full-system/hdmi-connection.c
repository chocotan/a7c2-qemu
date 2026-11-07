/* SPDX-License-Identifier: MIT */
#include "hdmi-connection.h"
#include "hdmi-pin-device.h"
/* Fourth edge: PinMem HDMIVIDEO OUT0 {4,2,0,90590818} -> HDMI VIDEO IN0
 * {4,1,0,909a015a}. Original raw 1295ea..129602 runs 62276c after the common
 * connect regardless of that connect's status; 8100 then carries the object's
 * canonical attributes for a dir2 source, so no 404 pool or 80 B format is
 * published and there is no 0104. The original HSM exit/enter, HPD monitoring,
 * configuration job and driver work are NOT executed by this dispatcher. */
#define EDGE_TAG "HDMI"
#define EDGE_DESCRIPTION "only-PinMem-HDMIVIDEO-OUT0-HDMI-VIDEO-IN0"
#define EDGE_PASS_OTHER 1
#define SOURCE_INDEX 0u
#define SOURCE_SLOT 7u
#define PEER_INDEX 0u
#define PEER_SLOT 0u
#define PEER_CP FULL_HDMI_PIN_CP
#define PEER_REGISTRY full_hdmi_pin_registry
#define PEER_SNAPSHOT full_hdmi_pin_snapshot
#define EDGE_EXPECT_TYPE 4u
#define EDGE_NOTIFY notify_hdmi_connected
#define EDGE_DISPATCH full_hdmi_connection_dispatch
#define EDGE_RELEASE full_hdmi_connection_release
#define EDGE_SNAPSHOT full_hdmi_connection_snapshot
#define EDGE_RESET full_hdmi_connection_test_reset
static int notify_hdmi_connected(unsigned int type){
    return full_hdmi_pin_notify_connected(type);
}
#include "pin-peer-connection.inc"
