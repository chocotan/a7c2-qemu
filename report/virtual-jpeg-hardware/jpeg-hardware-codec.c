#include "jpeg-hardware-codec.h"
#include "../virtual-jpeg-sos/jpeg-sos.h"

#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <jpeglib.h>
#include <jerror.h>

/* Public av-cam K4512ed/K45130a/K451327/K4513da; source-pins.json. */
static const uint8_t dc_y[29] = {
    0,0,1,5,1,1,1,1,1,1,0,0,0,0,0,0,0,
    0,1,2,3,4,5,6,7,8,9,10,11
};
static const uint8_t dc_c[29] = {
    1,0,3,1,1,1,1,1,1,1,1,1,0,0,0,0,0,
    0,1,2,3,4,5,6,7,8,9,10,11
};
static const uint8_t ac_y[179] = {
    0x10,0,2,1,3,3,2,4,3,5,5,4,4,0,0,1,0x7d,
    1,2,3,0,4,0x11,5,0x12,0x21,0x31,0x41,6,0x13,0x51,0x61,
    7,0x22,0x71,0x14,0x32,0x81,0x91,0xa1,8,0x23,0x42,0xb1,0xc1,
    0x15,0x52,0xd1,0xf0,0x24,0x33,0x62,0x72,0x82,9,0x0a,
    0x16,0x17,0x18,0x19,0x1a,0x25,0x26,0x27,0x28,0x29,0x2a,
    0x34,0x35,0x36,0x37,0x38,0x39,0x3a,0x43,0x44,0x45,0x46,
    0x47,0x48,0x49,0x4a,0x53,0x54,0x55,0x56,0x57,0x58,0x59,
    0x5a,0x63,0x64,0x65,0x66,0x67,0x68,0x69,0x6a,0x73,0x74,
    0x75,0x76,0x77,0x78,0x79,0x7a,0x83,0x84,0x85,0x86,0x87,
    0x88,0x89,0x8a,0x92,0x93,0x94,0x95,0x96,0x97,0x98,0x99,
    0x9a,0xa2,0xa3,0xa4,0xa5,0xa6,0xa7,0xa8,0xa9,0xaa,0xb2,
    0xb3,0xb4,0xb5,0xb6,0xb7,0xb8,0xb9,0xba,0xc2,0xc3,0xc4,
    0xc5,0xc6,0xc7,0xc8,0xc9,0xca,0xd2,0xd3,0xd4,0xd5,0xd6,
    0xd7,0xd8,0xd9,0xda,0xe1,0xe2,0xe3,0xe4,0xe5,0xe6,0xe7,
    0xe8,0xe9,0xea,0xf1,0xf2,0xf3,0xf4,0xf5,0xf6,0xf7,0xf8,
    0xf9,0xfa
};
static const uint8_t ac_c[179] = {
    0x11,0,2,1,2,4,4,3,4,7,5,4,4,0,1,2,0x77,
    0,1,2,3,0x11,4,5,0x21,0x31,6,0x12,0x41,0x51,7,0x61,
    0x71,0x13,0x22,0x32,0x81,8,0x14,0x42,0x91,0xa1,0xb1,0xc1,
    9,0x23,0x33,0x52,0xf0,0x15,0x62,0x72,0xd1,0x0a,0x16,
    0x24,0x34,0xe1,0x25,0xf1,0x17,0x18,0x19,0x1a,0x26,0x27,
    0x28,0x29,0x2a,0x35,0x36,0x37,0x38,0x39,0x3a,0x43,0x44,
    0x45,0x46,0x47,0x48,0x49,0x4a,0x53,0x54,0x55,0x56,0x57,
    0x58,0x59,0x5a,0x63,0x64,0x65,0x66,0x67,0x68,0x69,0x6a,
    0x73,0x74,0x75,0x76,0x77,0x78,0x79,0x7a,0x82,0x83,0x84,
    0x85,0x86,0x87,0x88,0x89,0x8a,0x92,0x93,0x94,0x95,0x96,
    0x97,0x98,0x99,0x9a,0xa2,0xa3,0xa4,0xa5,0xa6,0xa7,0xa8,
    0xa9,0xaa,0xb2,0xb3,0xb4,0xb5,0xb6,0xb7,0xb8,0xb9,0xba,
    0xc2,0xc3,0xc4,0xc5,0xc6,0xc7,0xc8,0xc9,0xca,0xd2,0xd3,
    0xd4,0xd5,0xd6,0xd7,0xd8,0xd9,0xda,0xe2,0xe3,0xe4,0xe5,
    0xe6,0xe7,0xe8,0xe9,0xea,0xf2,0xf3,0xf4,0xf5,0xf6,0xf7,
    0xf8,0xf9,0xfa
};
static const uint8_t zigzag[64] = {
    0,1,8,16,9,2,3,10,17,24,32,25,18,11,4,5,
    12,19,26,33,40,48,41,34,27,20,13,6,7,14,21,28,
    35,42,49,56,57,50,43,36,29,22,15,23,30,37,44,51,
    58,59,52,45,38,31,39,46,53,60,61,54,47,55,62,63
};
static void segment(uint8_t **p, unsigned marker, const uint8_t *data, size_t n)
{
    *(*p)++ = 0xff; *(*p)++ = (uint8_t)marker;
    *(*p)++ = (uint8_t)((n + 2) >> 8); *(*p)++ = (uint8_t)(n + 2);
    memcpy(*p, data, n); *p += n;
}

enum vjpeg_result vjpeg_source_prefix(const struct vjpeg_coding *c,
                                     uint8_t out[VJPEG_PREFIX_SIZE])
{
    uint8_t q[130], h[416], sof[15] = {8,0,0,0,0,3,1,0x21,0,2,0x11,1,3,0x11,1};
    uint8_t *p = out;
    if (c == NULL || out == NULL) return VJPEG_INVALID;
    if (c->contract != VJPEG_SOURCE_HEADER_422) return VJPEG_UNSUPPORTED;
    if (!c->width || !c->height || c->width > 65500 || c->height > 65500)
        return VJPEG_INVALID;
    for (size_t t = 0; t < 2; ++t) {
        q[t * 65] = (uint8_t)t;
        for (size_t i = 0; i < 64; ++i) {
            if (!c->quant_zigzag[t][i]) return VJPEG_INVALID;
            q[t * 65 + 1 + i] = c->quant_zigzag[t][i];
        }
    }
    memcpy(h, dc_y, 29); memcpy(h + 29, ac_y, 179);
    memcpy(h + 208, dc_c, 29); memcpy(h + 237, ac_c, 179);
    sof[1] = (uint8_t)(c->height >> 8); sof[2] = (uint8_t)c->height;
    sof[3] = (uint8_t)(c->width >> 8); sof[4] = (uint8_t)c->width;
    *p++ = 0xff; *p++ = 0xd8;
    segment(&p, 0xdb, q, sizeof(q)); segment(&p, 0xc4, h, sizeof(h));
    segment(&p, 0xc0, sof, sizeof(sof));
    return VJPEG_OK;
}

/* Only reorder/split the source control segments for the existing strict
 * SOS checker; table bytes, IDs, dimensions and sampling stay identical. */
static size_t canonical_prefix(const uint8_t *source, uint8_t *out)
{
    uint8_t *p = out;
    *p++ = 0xff; *p++ = 0xd8;
    segment(&p, 0xdb, source + 6, 65);
    segment(&p, 0xdb, source + 71, 65);
    segment(&p, 0xc0, source + 560, 15);
    segment(&p, 0xc4, dc_y, sizeof(dc_y));
    segment(&p, 0xc4, ac_y, sizeof(ac_y));
    segment(&p, 0xc4, dc_c, sizeof(dc_c));
    segment(&p, 0xc4, ac_c, sizeof(ac_c));
    return (size_t)(p - out);
}

struct codec_context {
    struct jpeg_compress_struct codec;
    struct jpeg_error_mgr error;
    struct jpeg_destination_mgr destination;
    jmp_buf jump;
    enum vjpeg_result status;
    uint8_t *output;
    size_t capacity;
    JOCTET probe;
    int probing;
};
static void codec_error(j_common_ptr codec)
{
    struct codec_context *c = (struct codec_context *)codec;
    if (c->status == VJPEG_OK)
        c->status = codec->err->msg_code == JERR_OUT_OF_MEMORY ?
                    VJPEG_NO_MEMORY : VJPEG_CODEC;
    longjmp(c->jump, 1);
}
static void dest_init(j_compress_ptr codec)
{
    struct codec_context *c = (struct codec_context *)codec;
    c->destination.next_output_byte = c->output;
    c->destination.free_in_buffer = c->capacity;
}
static boolean dest_empty(j_compress_ptr codec)
{
    struct codec_context *c = (struct codec_context *)codec;
    if (c->probing) {
        c->status = VJPEG_BOUNDS;
        ERREXIT(codec, JERR_BUFFER_SIZE);
        return FALSE;
    }
    c->probing = 1;
    c->destination.next_output_byte = &c->probe;
    c->destination.free_in_buffer = 1;
    return TRUE;
}
static void dest_finish(j_compress_ptr codec)
{
    struct codec_context *c = (struct codec_context *)codec;
    if (c->probing && c->destination.free_in_buffer != 1) {
        c->status = VJPEG_BOUNDS;
        ERREXIT(codec, JERR_BUFFER_SIZE);
    }
}
static void set_huffman(j_compress_ptr codec, JHUFF_TBL **slot,
                        const uint8_t *source, size_t n)
{
    if (*slot == NULL) *slot = jpeg_alloc_huff_table((j_common_ptr)codec);
    (*slot)->bits[0] = 0;
    memcpy((*slot)->bits + 1, source + 1, 16);
    memset((*slot)->huffval, 0, sizeof((*slot)->huffval));
    memcpy((*slot)->huffval, source + 17, n - 17);
    (*slot)->sent_table = FALSE;
}

enum vjpeg_result vjpeg_encode(const struct vjpeg_frame *f,
    const struct vjpeg_coding *coding, uint8_t *out, size_t capacity,
    size_t *offset, size_t *length)
{
    uint8_t source[VJPEG_PREFIX_SIZE], canonical[VJPEG_PREFIX_SIZE + 16];
    enum vjpeg_result status = vjpeg_source_prefix(coding, source);
    size_t canonical_size;
    struct jpeg_sos_view view;
    struct codec_context *c;
    *offset = *length = 0;
    if (status != VJPEG_OK) return status;
    canonical_size = canonical_prefix(source, canonical);
    c = calloc(1, sizeof(*c));
    if (c == NULL) return VJPEG_NO_MEMORY;
    c->codec.err = jpeg_std_error(&c->error);
    c->error.error_exit = codec_error;
    if (setjmp(c->jump)) {
        status = c->status;
        jpeg_destroy_compress(&c->codec); free(c);
        return status;
    }
    jpeg_create_compress(&c->codec);
    c->output = out; c->capacity = capacity;
    c->destination.init_destination = dest_init;
    c->destination.empty_output_buffer = dest_empty;
    c->destination.term_destination = dest_finish;
    c->codec.dest = &c->destination;
    c->codec.image_width = (JDIMENSION)coding->width;
    c->codec.image_height = (JDIMENSION)coding->height;
    c->codec.input_components = 3; c->codec.in_color_space = JCS_RGB;
    jpeg_set_defaults(&c->codec);
    c->codec.optimize_coding = FALSE; c->codec.arith_code = FALSE;
    c->codec.restart_interval = 0;
    c->codec.write_JFIF_header = FALSE; c->codec.write_Adobe_marker = FALSE;
    c->codec.dct_method = JDCT_ISLOW;
    for (int t = 0; t < 2; ++t) {
        JQUANT_TBL **slot = &c->codec.quant_tbl_ptrs[t];
        if (*slot == NULL) *slot = jpeg_alloc_quant_table((j_common_ptr)&c->codec);
        for (size_t z = 0; z < 64; ++z)
            (*slot)->quantval[zigzag[z]] = coding->quant_zigzag[t][z];
        (*slot)->sent_table = FALSE;
    }
    for (int i = 0; i < 3; ++i) {
        jpeg_component_info *p = &c->codec.comp_info[i];
        p->component_id = i + 1; p->h_samp_factor = i == 0 ? 2 : 1;
        p->v_samp_factor = 1; p->quant_tbl_no = i == 0 ? 0 : 1;
        p->dc_tbl_no = p->ac_tbl_no = i == 0 ? 0 : 1;
    }
    set_huffman(&c->codec, &c->codec.dc_huff_tbl_ptrs[0], dc_y, sizeof(dc_y));
    set_huffman(&c->codec, &c->codec.dc_huff_tbl_ptrs[1], dc_c, sizeof(dc_c));
    set_huffman(&c->codec, &c->codec.ac_huff_tbl_ptrs[0], ac_y, sizeof(ac_y));
    set_huffman(&c->codec, &c->codec.ac_huff_tbl_ptrs[1], ac_c, sizeof(ac_c));
    jpeg_start_compress(&c->codec, TRUE);
    while (c->codec.next_scanline < c->codec.image_height) {
        JSAMPROW row = (JSAMPROW)(f->rgb +
            (size_t)c->codec.next_scanline * f->stride);
        if (jpeg_write_scanlines(&c->codec, &row, 1) != 1)
            ERREXIT(&c->codec, JERR_CANT_SUSPEND);
    }
    jpeg_finish_compress(&c->codec);
    view = jpeg_sos_suffix(out, c->probing ? capacity :
        capacity - c->destination.free_in_buffer, canonical, canonical_size);
    jpeg_destroy_compress(&c->codec); free(c);
    if (view.status != JPEG_SOS_OK) return VJPEG_VERIFY;
    *offset = view.offset; *length = view.length;
    return VJPEG_OK;
}
