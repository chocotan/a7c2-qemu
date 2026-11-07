/* SPDX-License-Identifier: MIT */
#ifndef VEF_BB_FORMAT_H
#define VEF_BB_FORMAT_H
#define VEF_BB_CONTROL_BYTES 80u
struct vef_bb_format {unsigned char code,component;unsigned short flags;unsigned int width,height;};
/* Original VEF f008 builds version2 SSYN from the current 20B record.
 * Stateless encoding only: neither a buffer lease nor a pixel-ready signal. */
int vef_bb_format_build(const unsigned char *,unsigned int,unsigned char *,unsigned int);
int vef_bb_format_decode(const unsigned char *,unsigned int,struct vef_bb_format *);
#endif
