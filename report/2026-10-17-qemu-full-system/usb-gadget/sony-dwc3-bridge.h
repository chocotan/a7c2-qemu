/* SPDX-License-Identifier: MIT */
#ifndef SONY_DWC3_BRIDGE_H
#define SONY_DWC3_BRIDGE_H
#include "sony-dwc3.h"

typedef struct SonyDWC3Bridge SonyDWC3Bridge;
typedef struct Error Error;
typedef struct SonyDWC3BridgeConfig {
    const char *run_id;
    const char *lease;
    const char *qmp_host_path;   /* Host identity, never opened in namespace. */
    const char *socket_path;     /* Namespace path inside the owned run bind. */
} SonyDWC3BridgeConfig;

/* QEMU main-loop/BQL only. No host drivers or physical USB access.
 * apply_vbus must drive the board's original extcon/VBUS path; an absent
 * handler fails the vbus operation. The core's input is a separate signal.
 * The bridge stores its own copies of config strings, including the secret.
 */
SonyDWC3Bridge *sony_dwc3_bridge_new(SonyDWC3 *, const SonyDWC3BridgeConfig *,
    int (*apply_vbus)(void *, bool), void *opaque, Error **errp);
typedef struct SonyDWC3BridgeState {
    unsigned discovery_stage, pending;
    bool discovery_active, discovery_done, ready, import_owner;
} SonyDWC3BridgeState;
/* False means no bridge; output is then unknown and must not be reported zero. */
bool sony_dwc3_bridge_state(const SonyDWC3Bridge *, SonyDWC3BridgeState *);
void sony_dwc3_bridge_tick(SonyDWC3Bridge *);
void sony_dwc3_bridge_free(SonyDWC3Bridge *);
#endif
