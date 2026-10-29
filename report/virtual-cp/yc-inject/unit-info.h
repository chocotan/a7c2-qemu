/* Original dmm.ko op28 wire format; counts are observations, never a retirement fence. */
#ifndef YC_UNIT_INFO_H
#define YC_UNIT_INFO_H

struct yc_unit_info {
    unsigned int extents, references, opens, bytes, type;
};

static inline unsigned int yc_info_u16(const unsigned char *p)
{
    return p[0] | (unsigned int)p[1] << 8;
}

static inline unsigned int yc_info_u32(const unsigned char *p)
{
    return yc_info_u16(p) | yc_info_u16(p + 2) << 16;
}

static inline int yc_info_decode(const unsigned char *p, unsigned long length,
                                unsigned int source, unsigned int tag,
                                unsigned int type, unsigned int bytes,
                                struct yc_unit_info *out)
{
    if (!p || !out || length != 0x28 || (source & 0x7fffffffu) != 0x0061003cu || !tag || tag > 0xffffu)
        return -1;
    if (yc_info_u16(p) != 0x8028 || yc_info_u16(p + 2) || yc_info_u16(p + 6) != tag)
        return -1;
    struct yc_unit_info info = {yc_info_u16(p + 8), yc_info_u16(p + 10),
                               yc_info_u16(p + 12), yc_info_u32(p + 16), yc_info_u32(p + 20)};
    if (!info.extents || info.extents > 12 || !info.references || info.references > 255 ||
        info.opens > 255 || info.type != type || info.bytes != bytes)
        return -1;
    *out = info;
    return 0;
}
#endif
