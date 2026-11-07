/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef A7PF_TRIM_ZERO_H
#define A7PF_TRIM_ZERO_H
/* Independent virtual-storage convention; physical Sony erase semantics unknown. */
#ifdef __KERNEL__
#include <linux/uaccess.h>
#else
#include <errno.h>
#include <stddef.h>
#include <string.h>
#endif
#define PF_ALFRED_TRIM 0x40084124U
#define PF_TRIM_CHUNK 131072U
static unsigned int pf_trim_le32(const unsigned char *p)
{
    return (unsigned int)p[0] | (unsigned int)p[1]<<8 |
           (unsigned int)p[2]<<16 | (unsigned int)p[3]<<24;
}
static int pf_trim_gate(int enabled, unsigned int selector, int writable,
                        int readonly, unsigned int cmd)
{
    if (cmd != PF_ALFRED_TRIM) return -ENOTTY;
    if (enabled != 1) return -EOPNOTSUPP;
    if (selector != 4) return -ENODEV;
    if (!writable) return -EBADF;
    if (readonly) return -EROFS;
    return 0;
}
static int pf_trim_zero(int enabled, unsigned int selector, int writable,
                        int readonly, unsigned int cmd, unsigned long long sectors,
                        const unsigned char *arg, unsigned int arg_bytes,
                        void *buffer, void *opaque,
                        int (*io)(void *, unsigned long long, unsigned int, int),
                        int (*flush)(void *))
{
    unsigned long long sector = 0;
    unsigned int count, bytes, i;
    int err = pf_trim_gate(enabled, selector, writable, readonly, cmd);
    unsigned char *p = buffer;
    if (err) return err;
    if (!arg || arg_bytes != 8) return -EFAULT;
    count = pf_trim_le32(arg+4);
    /* Reject before narrowing or shifting: only the exact whole p4 is admitted. */
    if (!sectors || sectors > 0xffffffffULL || pf_trim_le32(arg) ||
        !count || (unsigned long long)count != sectors) return -EINVAL;
    if (!buffer || !io || !flush) return -EINVAL;
    while (sector < sectors) {
        bytes = (unsigned int)((sectors-sector > PF_TRIM_CHUNK/512) ?
                               PF_TRIM_CHUNK : (sectors-sector)*512);
        memset(p, 0, bytes);
        err = io(opaque, sector, bytes, 1);
        if (err) return err;
        err = flush(opaque);
        if (err) return err;
        err = io(opaque, sector, bytes, 0);
        if (err) return err;
        for (i = 0; i < bytes; i++) if (p[i]) return -EIO;
        sector += bytes/512;
    }
    return 0;
}
#ifdef __KERNEL__
static bool functional_alfred_trim_zero;
module_param(functional_alfred_trim_zero, bool, 0444);
MODULE_PARM_DESC(functional_alfred_trim_zero,
                 "Explicit virtual p4 whole-slice durable zero model (not physical erase)");
static int pf_trim_io(void *opaque, unsigned long long sector,
                      unsigned int bytes, int write)
{ return transfer(opaque, (sector_t)sector, bytes, write != 0); }
static int pf_trim_flush(void *opaque)
{
    struct pf_disk *pd = opaque;
    writel(pd->selector, regs+0x10);
    return command(4);
}
static int pf_ioctl(struct block_device *bdev, fmode_t mode,
                    unsigned int cmd, unsigned long arg)
{
    struct pf_disk *pd = bdev->bd_disk->private_data;
    unsigned char wire[8];
    int err = pf_trim_gate(functional_alfred_trim_zero, pd->selector,
                           !!(mode & FMODE_WRITE), bdev_read_only(bdev), cmd);
    if (err) return err;
    if (pd->disk != bdev->bd_disk || bdev != bdev->bd_contains ||
        get_capacity(bdev->bd_disk) != pd->sectors) return -EINVAL;
    if (copy_from_user(wire, (const void __user *)arg, sizeof(wire))) return -EFAULT;
    mutex_lock(&io_lock);
    err = pf_trim_zero(functional_alfred_trim_zero, pd->selector,
                       !!(mode & FMODE_WRITE), bdev_read_only(bdev), cmd,
                       pd->sectors, wire, sizeof(wire), bounce, pd,
                       pf_trim_io, pf_trim_flush);
    mutex_unlock(&io_lock);
    return err;
}
#endif
#endif
