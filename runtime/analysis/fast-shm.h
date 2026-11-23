/* SPDX-License-Identifier: MIT */
/* Shared-memory virtual CP display & direct App32 input ABI.
 *
 * Lives inside the existing guest reservation memrsv=0x00900000@0x41e100000:uc.
 * QEMU virt board guest RAM starts at 0x40000000, so guest physical address
 * FAST_SHM_PHYS_BASE maps to memfd offset FAST_SHM_MEMFD_OFFSET.
 *
 * Layout inside the 5 MiB window [0x41e100000 .. 0x41e5fffff]:
 *   0x000000 .. 0x12bfff  (1,228,800 B) legacy ramfb slot 0 (untouched)
 *   0x130000 .. 0x210fff  (  921,600 B) playback_bg_rgb  (640x480 RGB24, Guest -> Host)
 *   0x220000 .. 0x300fff  (  921,600 B) custom_cmos_rgb  (640x480 RGB24, Host -> Host+Guest)
 *   0x310000 .. 0x3a5fff  (  614,400 B) osd_rgba4444[0]  (640x480 RGBA4444 ping, Guest -> Host)
 *   0x3b0000 .. 0x445fff  (  614,400 B) osd_rgba4444[1]  (640x480 RGBA4444 pong, Guest -> Host)
 *   0x450000 .. 0x45ffff  (   65,536 B) fast_shm_ctrl + 64-slot SPSC input ring
 *   0x4ff000 .. 0x4fffff  (    4,096 B) legacy fw_cfg RAMFB_DMA / RAMFB_CFG (untouched)
 *
 * Region [0x41e600000 .. 0x41e9fffff] remains reserved exclusively for sd-window-export.
 */
#ifndef A7C2_FAST_SHM_H
#define A7C2_FAST_SHM_H

#include <stddef.h>
#include <stdint.h>

#define FAST_SHM_MAGIC          0x314D4853U /* "SHM1" little-endian */
#define FAST_SHM_VERSION        1U

#define FAST_SHM_PHYS_BASE      UINT64_C(0x41e100000)
#define FAST_SHM_VIRT_RAM_BASE  UINT64_C(0x40000000)
#define FAST_SHM_MEMFD_OFFSET   (FAST_SHM_PHYS_BASE - FAST_SHM_VIRT_RAM_BASE)
#define FAST_SHM_MAP_SIZE       0x500000U

#define FAST_SHM_WIDTH          640U
#define FAST_SHM_HEIGHT         480U
#define FAST_SHM_RGB_BYTES      (FAST_SHM_WIDTH * FAST_SHM_HEIGHT * 3U) /* 921600 */
#define FAST_SHM_OSD_BYTES      (FAST_SHM_WIDTH * FAST_SHM_HEIGHT * 2U) /* 614400 */

#define FAST_SHM_PLAYBACK_BG_OFF 0x130000U
#define FAST_SHM_CUSTOM_CMOS_OFF 0x220000U
#define FAST_SHM_OSD0_OFF        0x310000U
#define FAST_SHM_OSD1_OFF        0x3b0000U
#define FAST_SHM_CTRL_OFF        0x450000U

#define FAST_SHM_FLAG_SHOOTING    (1U << 0)
#define FAST_SHM_FLAG_PLAYBACK_BG (1U << 1)

#define FAST_SHM_RING_SIZE      64U
#define FAST_SHM_RING_MASK      (FAST_SHM_RING_SIZE - 1U)
#define FAST_SHM_KEY_OP_EVENT   1U /* Single 32-byte App32 event */
#define FAST_SHM_KEY_OP_TAP     2U /* Atomic press (status=1) + hold_us + release (status=0) */

struct fast_shm_key_cmd {
    uint64_t seq;      /* Strictly increasing 1, 2, 3, ... */
    uint32_t op;       /* FAST_SHM_KEY_OP_EVENT or FAST_SHM_KEY_OP_TAP */
    uint32_t key;      /* App32 word 0: key_code */
    uint32_t sub;      /* App32 word 1: sub_key_code */
    uint32_t status;   /* App32 word 2: status */
    uint32_t ex;       /* App32 word 4: ex_info */
    uint32_t from;     /* App32 word 6: from_type */
    uint32_t hold_us;  /* TAP hold duration in microseconds (<= 100000) */
    uint32_t _pad;
};

struct fast_shm_ctrl {
    /* Header: offset 0..31 */
    uint32_t magic;                /* Host writes FAST_SHM_MAGIC before starting QEMU */
    uint32_t version;              /* Host writes FAST_SHM_VERSION */
    uint32_t guest_display_ready;  /* Guest sets 1 once OSD SHM publisher is active */
    uint32_t guest_input_ready;    /* Guest sets 1 once fast_input_worker is polling */
    uint32_t host_features;        /* Host bitmask (bit 0 = fast-shm enabled) */
    uint32_t _hdr_pad[3];

    /* Display state (Guest writes -> Host reads): offset 32..95 */
    uint64_t osd_seq;              /* Bumped on OSD pixel or shooting-flag update */
    uint32_t osd_slot;             /* 0 or 1: active OSD RGBA4444 buffer */
    uint32_t display_flags;        /* FAST_SHM_FLAG_* */
    uint32_t playback_bg_seq;      /* Bumped after writing FAST_SHM_PLAYBACK_BG_OFF */
    uint32_t blink_seq;            /* Bumped on virtual shutter blink */
    uint64_t osd_pixel_seq;        /* Bumped only on 0x1003 pixel capture */
    uint64_t osd_frame_phys;       /* Last AP RGBA4444 DDR physical address */
    uint32_t osd_frame_id;         /* Last AP frame ID */
    uint32_t _disp_pad[5];

    /* Custom CMOS source (Host writes -> Host+Guest reads): offset 96..127 */
    uint32_t custom_cmos_active;   /* 1 when custom 640x480 RGB24 is active */
    uint32_t custom_cmos_seq;      /* Bumped after writing FAST_SHM_CUSTOM_CMOS_OFF */
    uint32_t _cmos_pad[6];

    /* Input SPSC ring (Host writes key_head, Guest writes key_tail): offset 128..191 */
    uint64_t key_head;
    uint64_t key_tail;
    uint64_t key_ack_seq;
    int32_t  key_last_rc;
    uint32_t key_sent_count;
    uint32_t _ring_pad[8];

    /* Ring slots: offset 192..2751 */
    struct fast_shm_key_cmd ring[FAST_SHM_RING_SIZE];
};

_Static_assert(sizeof(struct fast_shm_key_cmd) == 40U, "fast_shm_key_cmd size");
_Static_assert(offsetof(struct fast_shm_ctrl, osd_seq) == 32U, "fast_shm_ctrl osd_seq offset");
_Static_assert(offsetof(struct fast_shm_ctrl, custom_cmos_active) == 96U, "fast_shm_ctrl cmos offset");
_Static_assert(offsetof(struct fast_shm_ctrl, key_head) == 128U, "fast_shm_ctrl ring header offset");
_Static_assert(offsetof(struct fast_shm_ctrl, ring) == 192U, "fast_shm_ctrl ring array offset");
_Static_assert(sizeof(struct fast_shm_ctrl) == 2752U, "fast_shm_ctrl size");
_Static_assert(FAST_SHM_PLAYBACK_BG_OFF + FAST_SHM_RGB_BYTES <= FAST_SHM_CUSTOM_CMOS_OFF, "bg overlap");
_Static_assert(FAST_SHM_CUSTOM_CMOS_OFF + FAST_SHM_RGB_BYTES <= FAST_SHM_OSD0_OFF, "cmos overlap");
_Static_assert(FAST_SHM_OSD0_OFF + FAST_SHM_OSD_BYTES <= FAST_SHM_OSD1_OFF, "osd0 overlap");
_Static_assert(FAST_SHM_OSD1_OFF + FAST_SHM_OSD_BYTES <= FAST_SHM_CTRL_OFF, "osd1 overlap");
_Static_assert(FAST_SHM_CTRL_OFF + sizeof(struct fast_shm_ctrl) <= FAST_SHM_MAP_SIZE - 0x1000U, "ctrl overlap");

/* Virtual video recording control + 512 KiB MP4 Fsys chunk buffer inside unused tail:
 *   0x451000 .. 0x451fff  (  4,096 B) struct fast_shm_video_ctrl
 *   0x460000 .. 0x4dffff  (524,288 B) MP4 transfer chunk staging buffer
 */
#define FAST_SHM_VIDEO_MAGIC      0x31444956U /* "VID1" little-endian */
#define FAST_SHM_VIDEO_VERSION    1U
#define FAST_SHM_VIDEO_CTRL_OFF   0x451000U
#define FAST_SHM_VIDEO_BUF_OFF    0x460000U
#define FAST_SHM_VIDEO_BUF_SIZE   (512U * 1024U)

#define FAST_SHM_VIDEO_OP_BEGIN   1U
#define FAST_SHM_VIDEO_OP_CHUNK   2U
#define FAST_SHM_VIDEO_OP_COMMIT  3U
#define FAST_SHM_VIDEO_OP_ABORT   4U

struct fast_shm_video_ctrl {
    /* Header: offset 0..15 */
    uint32_t magic;               /* Host writes FAST_SHM_VIDEO_MAGIC */
    uint32_t version;             /* Host writes FAST_SHM_VIDEO_VERSION */
    uint32_t guest_video_ready;   /* Guest sets 1 when fast-shm + Fsys worker ready */
    uint32_t _v_pad0;

    /* Guest -> Host recording triggers: offset 16..31 */
    uint32_t rec_toggle_seq;      /* Guest increments on REC press (or Movie SHUTTER) */
    uint32_t rec_stop_seq;        /* Guest increments on force-stop (e.g. Playback/APO) */
    uint32_t rec_mode_switch;     /* 1=STILL, 2=MOVIE, 3=SQ */
    uint32_t _v_pad1;

    /* Host -> Guest recording indicator status: offset 32..63 */
    uint32_t rec_active;          /* 1 while actively recording frames */
    uint32_t rec_saving;          /* 1 while finalizing/writing MP4 to SD */
    uint32_t rec_elapsed_ms;      /* Elapsed recording time in ms for HUD */
    uint32_t rec_frames;          /* Frames captured/encoded */
    uint32_t rec_hud_seq;         /* Bumped by host on REC indicator/timer change */
    uint32_t _v_pad2[3];

    /* Host -> Guest MP4 Fsys SD-write handshake: offset 64..191 */
    uint32_t xfer_req_seq;        /* Host increments after preparing buffer/args */
    uint32_t xfer_op;             /* FAST_SHM_VIDEO_OP_* */
    uint32_t xfer_len;            /* Payload bytes in FAST_SHM_VIDEO_BUF_OFF (CHUNK) */
    uint32_t xfer_flags;          /* Reserved */
    uint64_t xfer_total_bytes;    /* Expected total bytes on COMMIT */
    uint64_t xfer_expected_hash;  /* FNV-1a 64-bit over MP4 bytes on COMMIT */

    uint32_t xfer_ack_seq;        /* Guest stores matching xfer_req_seq on completion */
    int32_t  xfer_status;         /* 0 or negative errno */
    uint32_t xfer_file_num;       /* C0001..C9999 */
    uint32_t xfer_readback_ok;    /* 1 when full Fsys readback + FNV verify + FlushVolume ok */
    uint64_t xfer_bytes_written;  /* Guest written byte count */
    uint64_t xfer_guest_hash;     /* Guest verified readback FNV-1a hash */
    char     xfer_guest_path[64]; /* Guest Fsys path, e.g. "A:/PRIVATE/M4ROOT/CLIP/C0001.MP4" */
};

_Static_assert(offsetof(struct fast_shm_video_ctrl, rec_toggle_seq) == 16U, "video rec_toggle_seq offset");
_Static_assert(offsetof(struct fast_shm_video_ctrl, rec_active) == 32U, "video rec_active offset");
_Static_assert(offsetof(struct fast_shm_video_ctrl, xfer_req_seq) == 64U, "video xfer_req_seq offset");
_Static_assert(offsetof(struct fast_shm_video_ctrl, xfer_ack_seq) == 96U, "video xfer_ack_seq offset");
_Static_assert(sizeof(struct fast_shm_video_ctrl) == 192U, "fast_shm_video_ctrl size");
_Static_assert(FAST_SHM_CTRL_OFF + sizeof(struct fast_shm_ctrl) <= FAST_SHM_VIDEO_CTRL_OFF, "video ctrl overlap");
_Static_assert(FAST_SHM_VIDEO_CTRL_OFF + sizeof(struct fast_shm_video_ctrl) <= FAST_SHM_VIDEO_BUF_OFF, "video buf overlap");
_Static_assert(FAST_SHM_VIDEO_BUF_OFF + FAST_SHM_VIDEO_BUF_SIZE <= FAST_SHM_MAP_SIZE - 0x1000U, "video tail overlap");

#endif /* A7C2_FAST_SHM_H */
