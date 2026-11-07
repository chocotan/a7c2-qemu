/* SPDX-License-Identifier: MIT */
#ifndef PIN_CONTROL_WIRE_H
#define PIN_CONTROL_WIRE_H
#define PIN_CONTROL_DMM_SID 0x0061003cu
#define PIN_CONTROL_CLIENT_SID 0x9059000eu
#define PIN_CONTROL_CONSUMER_SID 0x905a0048u
#define PIN_CONTROL_MESSAGE_BYTES 0x98u
/* Only the explicit virtual CP dispatcher may call this interface. This is
 * not the AP's same-numbered native service. Return 0 disabled/not-owned,
 * 1 consumed with in-place reply, -1 refused with caller bytes unchanged.
 * OSAL message ownership stays with the synchronous caller. Buffer ownership
 * belongs to the finite control pool and is independent of message free. */
int pin_control_dmm_message(unsigned int,unsigned int,unsigned char *,unsigned int,int);
#endif
