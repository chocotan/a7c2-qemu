/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef A7C2_BEETS_QEMU_H
#define A7C2_BEETS_QEMU_H
#include "hw/core/qdev.h"
#define TYPE_SONY_BEETS "sony-beets-register-candidate"
int sony_beets_reset_complete(DeviceState *dev, const uint8_t reply[2], uint8_t mode);
int sony_beets_port_response(DeviceState *dev, const uint8_t reply[4]);
#endif
