/* SPDX-License-Identifier: MIT */
#ifndef FULL_HDMI_PUBLIC_BACKUP_H
#define FULL_HDMI_PUBLIC_BACKUP_H
/* Read the same pinned public CP bank used by the virtual CP owners.
 * 0=present with true stored length, 1=structurally absent, -1021=invalid.
 * No AP dynamic-setting or original CP execution claim. */
int full_hdmi_public_backup_read(int fd,unsigned int key,void *out,
                                unsigned int capacity,unsigned int *length);
#endif
