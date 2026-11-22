/* SPDX-License-Identifier: MIT */
#ifndef VIRTUAL_CMOS_CAPTURE_H
#define VIRTUAL_CMOS_CAPTURE_H

#include <stddef.h>
#include <stdint.h>
#include "virtual-lens-hud.h"

/* Software virtual CMOS capture (Baseline DCT JPEG + Sony EXIF APP1) and
 * virtual SD Playback renderer using the firmware's real libInfraFsys APIs.
 * Software virtual model only; never claims physical CP ASIC or ISP encode. */

#define VIRTUAL_CMOS_W 640u
#define VIRTUAL_CMOS_H 480u
#define VIRTUAL_CMOS_RGB_BYTES (VIRTUAL_CMOS_W * VIRTUAL_CMOS_H * 3u)
#define VIRTUAL_CMOS_CUSTOM_RGB_PATH "/tmp/virtual-cmos-custom.rgb"
#define VIRTUAL_PLAYBACK_FRAME_PATH "/tmp/virtual-playback-frame.bin"
#define VIRTUAL_PLAYBACK_MAGIC "VPLAY001"
#define VIRTUAL_PLAYBACK_BG_PATH "/tmp/virtual-playback-bg.bin"
#define VIRTUAL_PLAYBACK_BG_MAGIC "VPBG0001"
#define VIRTUAL_PLAYBACK_HEADER_BYTES 16u
#define VIRTUAL_PLAYBACK_FRAME_BYTES (VIRTUAL_PLAYBACK_HEADER_BYTES + VIRTUAL_CMOS_RGB_BYTES)
#define VIRTUAL_SHUTTER_BLINK_PATH "/tmp/virtual-shutter-blink"

struct virtual_cmos_fsys_ops {
    unsigned int (*get_mount_drives)(void);
    int (*mkdir_fn)(const char *);
    int (*open_fn)(const char *, uint64_t *, unsigned int);
    int (*write_fn)(uint64_t, const void *, int);
    int (*read_fn)(uint64_t, void *, int);
    int (*flush_fn)(uint64_t);
    int (*close_fn)(uint64_t);
    int (*remove_fn)(const char *);
    int (*flush_volume_fn)(unsigned char);
};

struct virtual_cmos_capture_result {
    char path[64];
    char source[16];
    size_t bytes;
    uint64_t fnv1a64;
    uint32_t file_number;
    int readback_verified;
};

struct virtual_cmos_playback_state {
    int active;
    unsigned char drive;
    uint32_t files[256];
    unsigned int count;
    unsigned int index;
    uint32_t frame_seq;
};

int virtual_cmos_encode_jpeg(const uint8_t *rgb, unsigned width, unsigned height,
                             const struct virtual_lens_hud_state *hud,
                             uint8_t **out_buf, size_t *out_len);

int virtual_cmos_decode_jpeg(const uint8_t *jpeg, size_t jpeg_len,
                             uint8_t *rgb640x480,
                             unsigned *src_width, unsigned *src_height,
                             char *exif_summary, size_t exif_cap);

int virtual_cmos_load_active_rgb(const char *custom_rgb_path,
                                 uint8_t *rgb_out,
                                 char *source_out, size_t source_cap);

int virtual_cmos_capture_to_sd(const struct virtual_cmos_fsys_ops *ops,
                               const char *custom_rgb_path,
                               const struct virtual_lens_hud_state *hud,
                               struct virtual_cmos_capture_result *result);

int virtual_cmos_playback_enter(struct virtual_cmos_playback_state *pb,
                                const struct virtual_cmos_fsys_ops *ops,
                                const char *frame_path);

int virtual_cmos_playback_step(struct virtual_cmos_playback_state *pb,
                               const struct virtual_cmos_fsys_ops *ops,
                               const char *frame_path, int delta);

int virtual_cmos_playback_delete(struct virtual_cmos_playback_state *pb,
                                 const struct virtual_cmos_fsys_ops *ops,
                                 const char *frame_path);

void virtual_cmos_playback_exit(struct virtual_cmos_playback_state *pb,
                                const char *frame_path);

int virtual_cmos_render_playback_bg(const struct virtual_cmos_fsys_ops *ops,
                                    const char *jpeg_path,
                                    const char *bg_path,
                                    uint32_t seq);

#endif
