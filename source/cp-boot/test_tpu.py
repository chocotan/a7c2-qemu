# SPDX-License-Identifier: GPL-2.0-or-later
"""Deferred host tests for the TPU core and the actual QEMU adapter source.

The adapter uses a small QEMU API shim, not a VM or real QEMU acceptance.
Run only as part of the parent's consolidated batch, with TMPDIR explicitly
inside the project. This file has been authored without running its tests.
"""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
CFLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror",
          "-fsanitize=address,undefined"]


@pytest.fixture
def tpu_build_dir(tmp_path):
    tmpdir = os.environ.get("TMPDIR")
    assert tmpdir, "set TMPDIR to a project-owned directory before the batch"
    base = Path(tmpdir).resolve()
    assert base.is_relative_to(HERE.parents[3]), "TMPDIR must be inside this project"
    assert tmp_path.resolve().is_relative_to(base), "tmp_path must follow TMPDIR"
    return tmp_path


def _build_and_run(directory, name, sources):
    if shutil.which("cc") is None:
        pytest.skip("cc not available")
    exe = directory / name
    built = subprocess.run(
        ["cc", *CFLAGS, "-I", str(directory), "-I", str(HERE),
         "-o", str(exe), *map(str, sources)],
        capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "ALL" in ran.stdout and "CHECKS PASSED" in ran.stdout, ran.stdout


def test_tpu_core_host_selftest(tpu_build_dir):
    _build_and_run(tpu_build_dir, "test-tpu", [HERE / "tpu.c", HERE / "test-tpu.c"])


QEMU_SHIM = r"""
#ifndef TPU_QEMU_TEST_SHIM_H
#define TPU_QEMU_TEST_SHIM_H
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

typedef uint64_t hwaddr;
#define HWADDR_PRIx PRIx64
typedef struct MemTxAttrs { unsigned unused; } MemTxAttrs;
typedef enum MemTxResult { MEMTX_OK, MEMTX_ERROR } MemTxResult;
typedef struct MemoryRegionOps {
    MemTxResult (*read_with_attrs)(void *, hwaddr, uint64_t *, unsigned, MemTxAttrs);
    MemTxResult (*write_with_attrs)(void *, hwaddr, uint64_t, unsigned, MemTxAttrs);
    int endianness;
    struct {
        unsigned min_access_size, max_access_size;
        bool unaligned;
        bool (*accepts)(void *, hwaddr, unsigned, bool, MemTxAttrs);
    } valid;
    struct { unsigned min_access_size, max_access_size; bool unaligned; } impl;
} MemoryRegionOps;
typedef struct MemoryRegion {
    const MemoryRegionOps *ops;
    void *opaque;
    uint64_t size;
} MemoryRegion;
typedef void (*gpio_handler)(void *, int, int);
typedef struct DeviceState {
    gpio_handler inputs[2];
    const char *input_names[2];
    int input_counts[2];
    unsigned input_total;
} DeviceState;
typedef struct SysBusDevice {
    DeviceState parent_obj;
    MemoryRegion *mmio;
} SysBusDevice;
typedef struct Error { const char *message; } Error;
typedef struct Property { const char *name; size_t offset; uint32_t value; } Property;
typedef struct VMStateDescription { const char *name; bool unmigratable; } VMStateDescription;
typedef struct DeviceClass {
    void (*realize)(DeviceState *, Error **);
    void (*reset)(DeviceState *);
    const Property *properties;
    const VMStateDescription *vmsd;
    const char *desc;
} DeviceClass;
typedef DeviceClass ObjectClass;
typedef struct TypeInfo {
    const char *name, *parent;
    size_t instance_size;
    void (*class_init)(ObjectClass *, const void *);
} TypeInfo;
static const TypeInfo *registered_type;
#define TYPE_SYS_BUS_DEVICE "sysbus-device"
#define DEVICE_LITTLE_ENDIAN 0
#define OBJECT(x) ((void *)(x))
#define SYS_BUS_DEVICE(x) ((SysBusDevice *)(x))
#define DEVICE_CLASS(x) ((DeviceClass *)(x))
#define OBJECT_DECLARE_SIMPLE_TYPE(T, C) \
    typedef struct T T; \
    static inline T *C(void *obj) { return (T *)obj; }
#define DEFINE_PROP_UINT32(n, T, f, d) { (n), offsetof(T, f), (d) }
#define type_init(fn) static void (*const registered_init)(void) = (fn);

static inline void memory_region_init_io(MemoryRegion *r, void *owner,
    const MemoryRegionOps *ops, void *opaque, const char *name, uint64_t size)
{
    (void)owner; (void)name;
    r->ops = ops; r->opaque = opaque; r->size = size;
}
static inline void sysbus_init_mmio(SysBusDevice *s, MemoryRegion *r)
{
    s->mmio = r;
}
static inline void qdev_init_gpio_in_named(DeviceState *dev, gpio_handler fn,
                                          const char *name, int count)
{
    unsigned i = dev->input_total++;
    assert(i < 2);
    dev->inputs[i] = fn;
    dev->input_names[i] = name;
    dev->input_counts[i] = count;
}
static inline void error_setg(Error **errp, const char *message)
{
    static Error error;
    error.message = message;
    if (errp) { *errp = &error; }
}
static inline void device_class_set_legacy_reset(DeviceClass *dc,
                                                void (*fn)(DeviceState *))
{
    dc->reset = fn;
}
static inline void device_class_set_props(DeviceClass *dc, const Property *props)
{
    dc->properties = props;
}
static inline void type_register_static(const TypeInfo *info)
{
    registered_type = info;
}
#endif
"""

QEMU_TEST = r"""
#include "tpu-qemu.c"

int main(void)
{
    CpTpuState banks[TPU_BANK_COUNT] = {0};
    CpTpuState bad_bank = {0};
    DeviceClass dc = {0};
    MemTxAttrs attrs = {0};
    Error *error = NULL;
    uint64_t value;
    struct tpu before;

    registered_init();
    assert(registered_type == &tpu_type);
    assert(strcmp(tpu_type.name, "a7c2-cp-tpu") == 0);
    tpu_type.class_init(&dc, NULL);
    assert(dc.realize == tpu_realize && dc.reset == tpu_device_reset);
    assert(dc.vmsd == &tpu_vmstate && dc.vmsd->unmigratable);
    assert(strcmp(dc.vmsd->name, "a7c2-cp-tpu") == 0);
    assert(strcmp(dc.properties[0].name, "bank") == 0);
    assert(dc.properties[0].offset == offsetof(CpTpuState, bank));
    assert(dc.properties[0].value == 0);
    assert(tpu_ops.valid.min_access_size == 2 && tpu_ops.valid.max_access_size == 4);
    assert(tpu_ops.impl.min_access_size == 2 && tpu_ops.impl.max_access_size == 4);
    assert(!tpu_ops.valid.unaligned && !tpu_ops.impl.unaligned);
    assert(tpu_ops.valid.accepts == tpu_accepts);

    for (unsigned i = 0; i < TPU_BANK_COUNT; i++) {
        CpTpuState *s = &banks[i];
        DeviceState *dev = (DeviceState *)s;
        s->bank = i;
        dc.realize(dev, &error);
        assert(error == NULL);
        assert(s->regs.size == 0x1000 && s->regs.ops == &tpu_ops);
        assert(s->parent_obj.mmio == &s->regs && s->regs.opaque == s);
        assert(dev->input_total == 2);
        assert(strcmp(dev->input_names[0], "clock-enable") == 0);
        assert(strcmp(dev->input_names[1], "reset") == 0);
        assert(dev->input_counts[0] == 1 && dev->input_counts[1] == 1);
        assert(!s->state.clock_enabled && !s->state.reset_held);
        value = UINT64_C(0xdeadbeefcafebabe);
        assert(tpu_mmio_read(s, 0, &value, 2, attrs) == MEMTX_ERROR);
        assert(value == UINT64_C(0xdeadbeefcafebabe));
        assert(tpu_mmio_write(s, 0, 0xabcd, 2, attrs) == MEMTX_ERROR);
        dev->inputs[0](s, 0, 1);
        for (hwaddr offset = 0; offset <= 0x34; offset += 4) {
            assert(tpu_accepts(s, offset, 2, false, attrs));
            assert(tpu_accepts(s, offset, 4, false, attrs));
            assert(tpu_mmio_read(s, offset, &value, 2, attrs) == MEMTX_OK && value == 0);
            assert(tpu_mmio_read(s, offset, &value, 4, attrs) == MEMTX_OK && value == 0);
            if (offset != TPU_REG_STATUS) {
                uint16_t data = 0xa500u | (offset << 1);
                assert(tpu_mmio_write(s, offset, data, 2, attrs) == MEMTX_OK);
                assert(tpu_mmio_read(s, offset, &value, 2, attrs) == MEMTX_OK && value == data);
                assert(tpu_mmio_read(s, offset, &value, 4, attrs) == MEMTX_OK && value == data);
            }
            memcpy(&before, &s->state, sizeof(before));
            assert(!tpu_accepts(s, offset, 4, true, attrs));
            assert(tpu_mmio_write(s, offset, 0x1234, 4, attrs) == MEMTX_ERROR);
            assert(memcmp(&before, &s->state, sizeof(before)) == 0);
        }
        assert(tpu_mmio_write(s, TPU_REG_STATUS, 0x80, 2, attrs) == MEMTX_ERROR);
        assert(tpu_mmio_write(s, 0, 0x10000, 2, attrs) == MEMTX_ERROR);
        assert(tpu_mmio_write(s, 0x18, 0x100 + i, 2, attrs) == MEMTX_OK);
    }

    CpTpuState *s = &banks[0];
    DeviceState *dev = (DeviceState *)s;
    memcpy(&before, &s->state, sizeof(before));
    for (unsigned size = 0; size <= 8; size++) {
        if (size == 2 || size == 4) { continue; }
        value = UINT64_MAX;
        assert(!tpu_accepts(s, 0, size, false, attrs));
        assert(!tpu_accepts(s, 0, size, true, attrs));
        assert(tpu_mmio_read(s, 0, &value, size, attrs) == MEMTX_ERROR);
        assert(value == UINT64_MAX);
        assert(tpu_mmio_write(s, 0, 1, size, attrs) == MEMTX_ERROR);
    }
    static const hwaddr bad_offsets[] = {
        1, 2, 3, 6, 0x12, 0x36, 0x38, 0x3c, 0xffc, 0x1000,
        UINT64_C(0x100000000), UINT64_MAX,
    };
    for (unsigned i = 0; i < sizeof(bad_offsets) / sizeof(bad_offsets[0]); i++) {
        for (unsigned size = 2; size <= 4; size += 2) {
            hwaddr offset = bad_offsets[i];
            value = UINT64_MAX;
            assert(!tpu_accepts(s, offset, size, false, attrs));
            assert(tpu_mmio_read(s, offset, &value, size, attrs) == MEMTX_ERROR);
            assert(value == UINT64_MAX);
            assert(tpu_mmio_write(s, offset, 1, size, attrs) == MEMTX_ERROR);
        }
    }
    dev->inputs[0](s, 0, 2);
    dev->inputs[0](s, 0, -1);
    dev->inputs[0](s, 1, 0);
    dev->inputs[1](s, 0, 2);
    dev->inputs[1](s, 0, -1);
    dev->inputs[1](s, 1, 1);
    assert(memcmp(&before, &s->state, sizeof(before)) == 0);
    assert(tpu_mmio_write(s, TPU_REG_ENABLE, 0xa501, 2, attrs) == MEMTX_OK);
    assert(tpu_mmio_read(s, TPU_REG_ENABLE, &value, 4, attrs) == MEMTX_OK && value == 0xa501);
    assert(tpu_mmio_write(s, TPU_REG_CLEAR, 0x3f, 2, attrs) == MEMTX_OK);
    for (unsigned size = 2; size <= 4; size += 2) {
        value = UINT64_MAX;
        assert(tpu_mmio_read(s, TPU_REG_STATUS, &value, size, attrs) == MEMTX_ERROR);
        assert(value == UINT64_MAX);
        assert(tpu_mmio_read(s, TPU_REG_COUNTER, &value, size, attrs) == MEMTX_ERROR);
        assert(value == UINT64_MAX);
    }
    assert(tpu_mmio_write(s, TPU_REG_COUNTER, 0, 2, attrs) == MEMTX_ERROR);
    assert(tpu_mmio_write(s, TPU_REG_ENABLE, 0xa500, 2, attrs) == MEMTX_OK);
    assert(tpu_mmio_read(s, TPU_REG_STATUS, &value, 2, attrs) == MEMTX_ERROR);
    dev->inputs[0](s, 0, 0);
    assert(tpu_mmio_read(s, TPU_REG_ENABLE, &value, 2, attrs) == MEMTX_ERROR);
    assert(tpu_mmio_write(s, 0, 0, 2, attrs) == MEMTX_ERROR);
    dev->inputs[0](s, 0, 1);
    assert(tpu_mmio_read(s, 0x18, &value, 4, attrs) == MEMTX_OK && value == 0x100);
    dev->inputs[1](s, 0, 1);
    assert(s->state.reset_held && s->state.clock_enabled && !s->state.runtime_unmodeled);
    assert(tpu_mmio_read(s, 0, &value, 2, attrs) == MEMTX_ERROR);
    assert(tpu_mmio_write(s, 0, 1, 2, attrs) == MEMTX_ERROR);
    dev->inputs[1](s, 0, 0);
    for (hwaddr offset = 0; offset <= 0x34; offset += 4) {
        assert(tpu_mmio_read(s, offset, &value, 4, attrs) == MEMTX_OK && value == 0);
    }
    for (unsigned i = 1; i < TPU_BANK_COUNT; i++) {
        assert(tpu_mmio_read(&banks[i], 0x18, &value, 4, attrs) == MEMTX_OK && value == 0x100 + i);
    }
    dc.reset(dev);
    assert(!s->state.clock_enabled && !s->state.reset_held && !s->state.runtime_unmodeled);
    bad_bank.bank = TPU_BANK_COUNT;
    dc.realize((DeviceState *)&bad_bank, &error);
    assert(error != NULL && bad_bank.parent_obj.parent_obj.input_total == 0);
    assert(bad_bank.parent_obj.mmio == NULL);
    puts("TPU QEMU shim: ALL CHECKS PASSED");
    return 0;
}
"""


def test_tpu_qemu_adapter_with_host_shim(tpu_build_dir):
    """Exercise the actual adapter callbacks; this is not QEMU acceptance."""
    (tpu_build_dir / "tpu-qemu-shim.h").write_text(QEMU_SHIM, encoding="ascii")
    for name in ("qemu/osdep.h", "qemu/module.h", "hw/core/sysbus.h",
                 "hw/core/qdev-properties.h", "qapi/error.h", "migration/vmstate.h"):
        header = tpu_build_dir / name
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_text('#include "tpu-qemu-shim.h"\n', encoding="ascii")
    harness = tpu_build_dir / "test-tpu-qemu.c"
    harness.write_text(QEMU_TEST, encoding="ascii")
    _build_and_run(tpu_build_dir, "test-tpu-qemu", [HERE / "tpu.c", harness])
