/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_RM_FILE_DEVICE_H
#define NATIVE_RM_FILE_DEVICE_H
#include "device-models/imaging-device.h"
#define NATIVE_RM_FILE_SID 0x80d9016eU
/* MENU_RM_FILE_IMAGE / MENU_RM_FILE_CLAIM override the supplied paths when set.
 * Unset retains caller defaults (/image_mmca and /tmp/rm-file.claim in observer).
 * Empty or invalid overrides fail the existing validation; never fall back. */
int native_rm_file_start(const char *,const char *,const struct full_imaging_io *,
                        int (*)(unsigned int,void **,void *,unsigned long),
                        int (*)(unsigned int,void *),int (*)(unsigned int,void *));
int native_rm_file_release(unsigned int,void *,int (*)(unsigned int,void *),
                           void (*)(const char *,const char *),int *);
#endif
