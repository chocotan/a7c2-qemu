#!/usr/bin/env python3
"""Layer a fixed-address upstream host DWC3 experiment on the pinned base."""
import hashlib
import json
from pathlib import Path
import sys


def patch(source):
    path=source/'hw/arm/virt.c'
    text=path.read_text()
    anchor='    create_msi_controller(vms);'
    if text.count(anchor)!=1:raise ValueError('Ambiguous Sony USB board insertion')
    addition='''    /* Full-dump-only upstream DWC3 host/capability experiment.
     * No host USB passthrough, gadget implementation or ready injection. */
    if (g_getenv("QEMU_SONY_USB_DWC3")) {
        DeviceState *usb = qdev_new("usb_dwc3");
        SysBusDevice *sbd = SYS_BUS_DEVICE(usb);
        sysbus_realize_and_unref(sbd, &error_fatal);
        memory_region_add_subregion_overlap(sysmem, 0xf10c0000,
                                             sysbus_mmio_get_region(sbd, 0), 2);
    }
'''
    # Full-dump-only media insert-detect register experiment. The retail driver reads
    # one 4-byte register at 0xF1388F44 (mcmnd_insmedia_arch_init) and tests bit 24;
    # the generic catch-all answers 0xFFFFFFFF there, so this overlay lets a run state
    # the detect value explicitly instead of guessing the polarity.
    detect='''/* Full-dump-only experiment: media insert-detect register value, never a fake ACK. */
typedef struct SonyMediaDetectState {
    MemoryRegion mmio;
    uint32_t value;
    uint64_t reads;
    uint64_t writes;
} SonyMediaDetectState;

static uint64_t sony_media_detect_read(void *opaque, hwaddr offset, unsigned size)
{
    SonyMediaDetectState *s = opaque;
    uint64_t value = (s->value >> (offset * 8)) & (UINT64_MAX >> (64 - size * 8));
    s->reads++;
    if (s->reads <= 8 || !(s->reads & (s->reads - 1))) {
        fprintf(stderr, "SONY_MEDIA_DETECT_READ count=%" PRIu64
                " offset=%" HWADDR_PRIx " size=%u value=0x%08x\\n",
                s->reads, offset, size, (unsigned)value);
    }
    return value;
}

static void sony_media_detect_write(void *opaque, hwaddr offset, uint64_t value, unsigned size)
{
    SonyMediaDetectState *s = opaque;
    if (++s->writes <= 8) {
        fprintf(stderr, "SONY_MEDIA_DETECT_WRITE_IGNORED offset=%" HWADDR_PRIx
                " size=%u value=%" PRIx64 "\\n", offset, size, value);
    }
}

static const MemoryRegionOps sony_media_detect_ops = {
    .read = sony_media_detect_read,
    .write = sony_media_detect_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid.min_access_size = 1,
    .valid.max_access_size = 4,
    .impl.min_access_size = 1,
    .impl.max_access_size = 4,
};

'''
    mmc_trace=r'''/* Full-dump-only IPSXWRP register-file probe: records original driver accesses
 * in order and answers a settable reset value. It is not a card model: no
 * command, data or interrupt behaviour is emulated here. */
typedef struct SonyMmcTraceState {
    MemoryRegion mmio;
    uint64_t reads;
    uint64_t writes;
    uint32_t reset;
    hwaddr base;
} SonyMmcTraceState;

static uint64_t sony_mmc_trace_read(void *opaque, hwaddr offset, unsigned size)
{
    SonyMmcTraceState *s = opaque;
    s->reads++;
    if (s->reads <= 512) {
        /* The base must be logged: this window is a shared SCU block that
         * hwtimer/USB/MMC all touch, so an offset alone cannot be attributed. */
        fprintf(stderr, "SONY_MMC_TRACE_READ base=0x%" HWADDR_PRIx
                " n=%" PRIu64 " off=0x%" HWADDR_PRIx " size=%u\n",
                s->base, s->reads, offset, size);
    }
    return s->reset;
}

static void sony_mmc_trace_write(void *opaque, hwaddr offset, uint64_t value, unsigned size)
{
    SonyMmcTraceState *s = opaque;
    s->writes++;
    if (s->writes <= 512) {
        fprintf(stderr, "SONY_MMC_TRACE_WRITE base=0x%" HWADDR_PRIx
                " n=%" PRIu64 " off=0x%" HWADDR_PRIx " size=%u value=0x%" PRIx64 "\n",
                s->base, s->writes, offset, size, value);
    }
}

static const MemoryRegionOps sony_mmc_trace_ops = {
    .read = sony_mmc_trace_read,
    .write = sony_mmc_trace_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid.min_access_size = 1,
    .valid.max_access_size = 8,
    .impl.min_access_size = 1,
    .impl.max_access_size = 8,
};

'''
    detect_insert='''    {
        const char *detect = g_getenv("QEMU_SONY_MEDIA_DETECT");
        if (detect && *detect) {
            SonyMediaDetectState *s = g_new0(SonyMediaDetectState, 1);
            s->value = g_ascii_strtoull(detect, NULL, 0);
            memory_region_init_io(&s->mmio, NULL, &sony_media_detect_ops, s,
                                  "sony-media-detect", 4);
            memory_region_add_subregion_overlap(sysmem, 0xf1388f44, &s->mmio, 4);
            fprintf(stderr, "SONY_MEDIA_DETECT_CREATED phys=0xf1388f44 bytes=4 value=0x%08x\\n", s->value);
        }
    }
'''
    trace_insert=r'''    {
        /* MMC0/MMC1 UDIF windows (platform.c). QEMU virt RAM covers these
         * physical addresses, so an explicit overlap is required for the
         * original driver to reach a device instead of RAM contents. */
        const char *mmc = g_getenv("QEMU_SONY_MMC_TRACE");
        if (mmc && *mmc) {
            /* 0xf1388000 is what mmc_hw_ipsxwrp_init itself ioremaps (size
             * 0x33000); the 0xf10d*000 windows come from udif_devices and are
             * covered too so the trace settles which one the driver touches.
             * Priority 3 keeps the 4-byte media-detect register visible. */
            static const hwaddr bases[3] = { 0xf1388000, 0xf10d2000, 0xf10d4000 };
            static const hwaddr sizes[3] = { 0x33000, 0x2000, 0x2000 };
            for (unsigned i = 0; i < 3; ++i) {
                SonyMmcTraceState *s = g_new0(SonyMmcTraceState, 1);
                s->reset = (uint32_t)g_ascii_strtoull(mmc, NULL, 0);
                s->base = bases[i];
                memory_region_init_io(&s->mmio, NULL, &sony_mmc_trace_ops, s,
                                      "sony-mmc-trace", sizes[i]);
                memory_region_add_subregion_overlap(sysmem, bases[i], &s->mmio, 3);
                fprintf(stderr, "SONY_MMC_TRACE_CREATED phys=0x%" HWADDR_PRIx
                        " bytes=0x%" HWADDR_PRIx " reset=0x%08x\n",
                        bases[i], sizes[i], s->reset);
            }
        }
    }
'''
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    text=text.replace(anchor,addition+detect_insert+trace_insert+anchor,1)
    # Definitions must precede their use: place them just before machvirt_init.
    define_anchor='static void machvirt_init(MachineState *machine)'
    if text.count(define_anchor)!=1:
        raise ValueError('Ambiguous machvirt_init definition point')
    text=text.replace(define_anchor,detect+mmc_trace+define_anchor,1)
    path.write_text(text)
    config=source/'configs/devices/aarch64-softmmu/default.mak'
    before_config=hashlib.sha256(config.read_bytes()).hexdigest()
    with config.open('a') as out:out.write('\n# Explicit full-dump host DWC3 model\nCONFIG_USB_DWC3=y\n')
    records={str(p.relative_to(source)):{'before':old,'after':hashlib.sha256(p.read_bytes()).hexdigest()}
             for p,old in ((path,before),(config,before_config))}
    (source.parent/'full-usb-source-delta.json').write_text(json.dumps(records,indent=2)+'\n')


if __name__=='__main__':patch(Path(sys.argv[1]))
