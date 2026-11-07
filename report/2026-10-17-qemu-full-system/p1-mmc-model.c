#ifdef P1_MMC_QEMU
#include "qemu/osdep.h"
#include "exec/memattrs.h"
#include "migration/vmstate.h"
#endif
#include "p1-mmc-model.h"

void p1_mmc_reset(struct p1_mmc_model *state)
{
    if (state) {
        *state = (struct p1_mmc_model){0};
    }
}

static int p1_mmc_reject(struct p1_mmc_model *state, uint64_t address,
                         unsigned width, uint64_t value, int error)
{
    state->rejections++;
    if (state->phase == P1_MMC_FAULT) {
        return P1_MMC_LATCHED;
    }
    state->phase = P1_MMC_FAULT;
    state->first_address = address;
    state->first_value = value;
    state->first_width = width;
    state->first_error = error;
    return error;
}

int p1_mmc_read(struct p1_mmc_model *state, uint64_t address,
                unsigned width, uint64_t *value)
{
    if (!state || !value) {
        return P1_MMC_ARGUMENT;
    }
    if (state->phase == P1_MMC_FAULT) {
        return p1_mmc_reject(state, address, width, 0, P1_MMC_LATCHED);
    }
    if (width != 4) {
        return p1_mmc_reject(state, address, width, 0, P1_MMC_BAD_WIDTH);
    }
    if (address != P1_MMC_ID_ADDRESS) {
        return p1_mmc_reject(state, address, width, 0, P1_MMC_UNKNOWN);
    }
    *value = P1_MMC_ID_VALUE;
    state->phase = P1_MMC_IDENTIFIED;
    state->reads++;
    return P1_MMC_OK;
}

int p1_mmc_write(struct p1_mmc_model *state, uint64_t address,
                 unsigned width, uint64_t value)
{
    if (!state) {
        return P1_MMC_ARGUMENT;
    }
    int error = width != 4 ? P1_MMC_BAD_WIDTH :
                address != P1_MMC_ID_ADDRESS ? P1_MMC_UNKNOWN : P1_MMC_READ_ONLY;
    return p1_mmc_reject(state, address, width, value, error);
}

#ifdef P1_MMC_QEMU
/* One standalone page has priority over the old all-ones/RAM backing. */
typedef struct P1MmcQemu {
    MemoryRegion page;
    struct p1_mmc_model core;
} P1MmcQemu;

static MemTxResult p1_mmc_qemu_read(void *opaque, hwaddr offset,
                                  uint64_t *value, unsigned size,
                                  MemTxAttrs attrs)
{
    P1MmcQemu *state = opaque;
    *value = 0;
    int rc = p1_mmc_read(&state->core, P1_MMC_ID_ADDRESS + offset, size, value);
    (void)attrs;
    fprintf(stderr, "P1_MMC_READ address=0x%" PRIx64 " width=%u rc=%d value=0x%" PRIx64 "\n",
            P1_MMC_ID_ADDRESS + offset, size, rc, rc ? UINT64_C(0) : *value);
    return rc ? MEMTX_ERROR : MEMTX_OK;
}

static MemTxResult p1_mmc_qemu_write(void *opaque, hwaddr offset,
                                   uint64_t value, unsigned size,
                                   MemTxAttrs attrs)
{
    P1MmcQemu *state = opaque;
    int rc = p1_mmc_write(&state->core, P1_MMC_ID_ADDRESS + offset, size, value);
    (void)attrs;
    fprintf(stderr, "P1_MMC_WRITE address=0x%" PRIx64 " width=%u rc=%d value=0x%" PRIx64 "\n",
            P1_MMC_ID_ADDRESS + offset, size, rc, value);
    return MEMTX_ERROR;
}

static const MemoryRegionOps p1_mmc_qemu_ops = {
    .read_with_attrs = p1_mmc_qemu_read,
    .write_with_attrs = p1_mmc_qemu_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
};

static const VMStateDescription p1_mmc_no_migration = {
    .name = "p1-mmc-identification-only",
    .unmigratable = true,
};

static void p1_mmc_qemu_create(MemoryRegion *memory)
{
    const char *profile = g_getenv("QEMU_P1_MMC_BOOTSTRAP");
    if (!profile) {
        return;
    }
    if (strcmp(profile, P1_MMC_PROFILE) ||
        g_getenv("QEMU_SONY_MMC_TRACE") || g_getenv("QEMU_SONY_MEDIA_DETECT")) {
        error_report("invalid/conflicting P1 MMC identification profile");
        exit(1);
    }
    P1MmcQemu *state = g_new0(P1MmcQemu, 1);
    p1_mmc_reset(&state->core);
    memory_region_init_io(&state->page, NULL, &p1_mmc_qemu_ops, state,
                          "p1-mmc-identification-only", 0x1000);
    memory_region_add_subregion_overlap(memory, P1_MMC_ID_ADDRESS, &state->page, 10);
    vmstate_register(NULL, 0, &p1_mmc_no_migration, state);
    fprintf(stderr, "P1_MMC_CREATED profile=%s phys=0xf13b8000 bytes=0x1000 card=absent module_init_allowed=0\n",
            profile);
}
#endif
