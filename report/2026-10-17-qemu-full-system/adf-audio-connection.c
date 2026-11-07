/* SPDX-License-Identifier: MIT */
#include "adf-audio-connection.h"
#include "adf-device.h"
#include "hdmi-pin-device.h"
/* Fifth edge: ADF AUDIO OUT0 {5,2,0,9058003f} -> HDMI AUDIO IN0
 * {5,1,0,909a015a}. The AUDIO object's own callback (CP raw622798) stores the
 * independent HDMI shared byte +60h; it must not touch the VIDEO byte +58h. */
#define EDGE_TAG "ADFAUDIO"
#define EDGE_DESCRIPTION "only-ADF-AUDIO-OUT0-HDMI-AUDIO-IN0"
#define EDGE_PASS_OTHER 1
#define SOURCE_INDEX 0u
#define SOURCE_SLOT 9u /* ADF {5,2,0} AUDIO OUT */
#define PEER_INDEX 0u
#define PEER_SLOT 1u
#define EDGE_SOURCE_CP FULL_ADF_CP
#define EDGE_SOURCE_REGISTRY full_adf_registry
#define EDGE_SOURCE_SNAPSHOT full_adf_snapshot
#define PEER_CP FULL_HDMI_PIN_CP
#define PEER_REGISTRY full_hdmi_pin_registry
#define PEER_SNAPSHOT full_hdmi_pin_snapshot
#define EDGE_EXPECT_TYPE 5u
#define EDGE_NOTIFY notify_hdmi_audio_connected
#define EDGE_DISPATCH full_adf_audio_connection_dispatch
#define EDGE_RELEASE full_adf_audio_connection_release
#define EDGE_SNAPSHOT full_adf_audio_connection_snapshot
#define EDGE_RESET full_adf_audio_connection_test_reset
static int notify_hdmi_audio_connected(unsigned int type){
    return full_hdmi_pin_notify_connected(type);
}
#include "pin-peer-connection.inc"
