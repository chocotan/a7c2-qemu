// SPDX-License-Identifier: GPL-2.0-only
/* Functional MMIO disk; no Sony eMMC encryption is simulated. */
#include <linux/module.h>
#include <linux/blkdev.h>
#include <linux/bio.h>
#include <linux/io.h>
#include <linux/highmem.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/string.h>

#define PF_MAGIC 0x46503741
#define PF_MAX_IO 131072
static unsigned long mmio_base=0x0b000000;
module_param(mmio_base, ulong, 0444);
static char *name="nflasha";
module_param(name, charp, 0444);
static void __iomem *regs;
static int major;
static DEFINE_MUTEX(io_lock);
static void *bounce;
struct pf_disk { struct gendisk *disk; struct request_queue *queue; unsigned int selector; sector_t sectors; };
static struct pf_disk disks[33];
static unsigned int disk_count;

static void put64(unsigned int off, u64 value)
{ writel((u32)value, regs+off); writel((u32)(value>>32), regs+off+4); }
static u64 get64(unsigned int off)
{ u32 lo=readl(regs+off); return lo | ((u64)readl(regs+off+4)<<32); }
static int command(unsigned int op)
{
    u32 status, error;
    wmb(); writel(op, regs+0x14); status=readl(regs+0x2c); rmb();
    error=readl(regs+0x34);
    if (status!=1 || error) return error && error<=4095 ? -(int)error : -EIO;
    return 0;
}
static int transfer(struct pf_disk *pd, sector_t sector, unsigned int bytes, bool write)
{
    int err;
    if (!bytes || bytes>PF_MAX_IO || (bytes&511) || sector>pd->sectors || bytes/512>pd->sectors-sector)
        return -EINVAL;
    writel(pd->selector, regs+0x10); put64(0x18, sector);
    writel(bytes/512, regs+0x20); put64(0x24, virt_to_phys(bounce));
    err=command(write ? 3 : 2);
    if (!err && readl(regs+0x30)!=bytes) err=-EIO;
    return err;
}
static blk_qc_t pf_make_request(struct request_queue *q, struct bio *bio)
{
    struct pf_disk *pd=bio->bi_bdev->bd_disk->private_data;
    struct bio_vec bvec;
    struct bvec_iter iter;
    sector_t sector=bio->bi_iter.bi_sector;
    unsigned int op=bio_op(bio), position=0;
    bool write=op==REQ_OP_WRITE;
    int err=0;
    /* make_request bios are not bounded by queue_max_hw_sectors until split. */
    blk_queue_split(q, &bio, q->bio_split);
    if (op!=REQ_OP_READ && op!=REQ_OP_WRITE && op!=REQ_OP_FLUSH) { err=-EOPNOTSUPP; goto done; }
    if (bio->bi_iter.bi_size>PF_MAX_IO || (bio->bi_iter.bi_size&511) ||
        sector>pd->sectors || bio->bi_iter.bi_size/512>pd->sectors-sector) { err=-EINVAL; goto done; }
    mutex_lock(&io_lock);
    if (op==REQ_OP_FLUSH || (bio->bi_opf&REQ_PREFLUSH)) {
        writel(pd->selector, regs+0x10); err=command(4);
    }
    if (!err && bio->bi_iter.bi_size && op!=REQ_OP_FLUSH) {
        if (write) {
            bio_for_each_segment(bvec, bio, iter) {
                void *p=kmap(bvec.bv_page);
                memcpy(bounce+position, p+bvec.bv_offset, bvec.bv_len);
                kunmap(bvec.bv_page); position+=bvec.bv_len;
            }
        }
        err=transfer(pd, sector, bio->bi_iter.bi_size, write);
        if (!err && !write) {
            bio_for_each_segment(bvec, bio, iter) {
                void *p=kmap(bvec.bv_page);
                memcpy(p+bvec.bv_offset, bounce+position, bvec.bv_len);
                kunmap(bvec.bv_page); position+=bvec.bv_len;
            }
        }
    }
    mutex_unlock(&io_lock);
done:
    bio->bi_error=err; bio_endio(bio); return BLK_QC_T_NONE;
}
static const struct block_device_operations pf_ops={ .owner=THIS_MODULE };
static void cleanup(void)
{
    while (disk_count) {
        struct pf_disk *pd=&disks[--disk_count];
        del_gendisk(pd->disk); blk_cleanup_queue(pd->queue); put_disk(pd->disk);
    }
    if (major>0) unregister_blkdev(major, "sony-persistent-flash");
    major=0; kfree(bounce); bounce=NULL;
    if (regs) iounmap(regs);
    regs=NULL;
}
static int __init pf_init(void)
{
    unsigned int selector, found=0, count, boots;
    int err=-ENOMEM;
    if (strcmp(name, "nflasha") && strcmp(name, "nflashaB0") && strcmp(name, "nflashaB1")) return -EINVAL;
    regs=ioremap(mmio_base, 0x1000);
    if (!regs) return -ENOMEM;
    if (readl(regs)!=PF_MAGIC || readl(regs+4)!=1 || readl(regs+8)!=PF_MAX_IO) { err=-ENODEV; goto fail; }
    count=readl(regs+0x0c); boots=readl(regs+0x48);
    if (count>30 || (boots && boots!=2) || (strcmp(name,"nflasha") && (count || boots))) { err=-EINVAL; goto fail; }
    bounce=kmalloc(PF_MAX_IO, GFP_KERNEL);
    if (!bounce) goto fail;
    major=register_blkdev(0, "sony-persistent-flash");
    if (major<0) { err=major; major=0; goto fail; }
    for (selector=0; selector<=32; selector++) {
        struct pf_disk *pd=&disks[disk_count];
        struct gendisk *disk;
        writel(selector, regs+0x10); err=command(1);
        if (err==-ENODEV && selector) continue;
        if (err) goto fail;
        pd->sectors=get64(0x38);
        if (!pd->sectors) { err=-EINVAL; goto fail; }
        pd->queue=blk_alloc_queue(GFP_KERNEL);
        if (!pd->queue) { err=-ENOMEM; goto fail; }
        blk_queue_make_request(pd->queue, pf_make_request);
        blk_queue_logical_block_size(pd->queue, 512);
        blk_queue_max_hw_sectors(pd->queue, PF_MAX_IO/512);
        blk_queue_write_cache(pd->queue, true, true);
        disk=alloc_disk(1);
        if (!disk) { blk_cleanup_queue(pd->queue); err=-ENOMEM; goto fail; }
        pd->selector=selector; pd->disk=disk;
        disk->major=major; disk->first_minor=selector>30 ? selector+33 : (selector ? selector+128 : 0);
        disk->fops=&pf_ops; disk->queue=pd->queue; disk->private_data=pd;
        disk->flags|=GENHD_FL_NO_PART_SCAN;
        if (selector>30) snprintf(disk->disk_name, DISK_NAME_LEN, "nflashaB%u", selector-31);
        else if (selector) snprintf(disk->disk_name, DISK_NAME_LEN, "cnflasha%u", selector);
        else if (!strcmp(name,"nflasha")) strlcpy(disk->disk_name, "pnflasha", DISK_NAME_LEN);
        else strlcpy(disk->disk_name, name, DISK_NAME_LEN);
        set_capacity(disk, pd->sectors); add_disk(disk); disk_count++;
        if (selector) found++;
    }
    if (found!=count+boots) { err=-EINVAL; goto fail; }
    pr_info("sony_persistent_flash: real durable MMIO DMA, major=%d slices=%u base=%#lx\n",major,found,mmio_base);
    return 0;
fail:
    cleanup(); return err;
}
static void __exit pf_exit(void) { cleanup(); }
module_init(pf_init);
module_exit(pf_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Isolated functional persistent flash block adapter for Sony Linux 4.9");
