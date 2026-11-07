#!/usr/bin/env python3
"""Device contracts with real libfdt and lightweight standalone host C fixtures.

Original driver read/write evidence and functional-model limits:
../2026-11-06-complete-boot-flow/usb-original-driver.md#source-v2-evidence
No test in this file starts QEMU or an original guest.
"""
import ctypes
import ctypes.util
from copy import deepcopy
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import unittest

import pytest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'usb-device-profile.py'))

# Source fixture: dwc3-of-cxd.c:396-471, cxd-phy.c:298-416, cxd-clk-gate.c:46-98.
PHY_HOST_TEST_C = r'''
#include <assert.h>
#include <string.h>
static void wr(SonyUsbPower *p, uint32_t a, uint32_t v)
{ assert(sony_usb_power_write(p, a, 4, v) == 0); }
static uint32_t rd(SonyUsbPower *p, uint32_t a)
{ uint32_t v; assert(sony_usb_power_read(p, a, 4, &v) == 0); return v; }
static void gates(SonyUsbPower *p, uint32_t omit)
{
    const uint32_t bits[] = {0x8000, 0x4000, 0x2000, 0x1000};
    for (unsigned i = 0; i < 4; i++) if (bits[i] != omit) wr(p, 0xf1388004, bits[i]);
}
static void prepare(SonyUsbPower *p, uint32_t omit_reset, int omit_config)
{
    const uint32_t bits[] = {0x800, 0x400, 0x200, 0x100};
    for (unsigned i = 0; i < 4; i++) if (bits[i] != omit_reset) wr(p, 0xf1388304, bits[i]);
    wr(p, 0xf1388308, 0x200);
    const uint32_t config[] = {0, 0, 0x100000};
    for (int i = 0; i < 3; i++) if (i != omit_config) wr(p, 0xf1080020, config[i]);
}
static void release(SonyUsbPower *p)
{
    const uint32_t bits[] = {0x800, 0x400, 0x200, 0x100};
    for (unsigned i = 0; i < 4; i++) {
        assert(!(rd(p, 0xf1080020) & SONY_USB_SRAM_DONE));
        wr(p, 0xf1388308, bits[i]);
    }
}
static void complete(SonyUsbPower *p)
{
    gates(p, 0); prepare(p, 0, -1); release(p);
    assert(sony_usb_sram_initialized(p));
    assert(rd(p, 0xf1080020) == (SONY_USB_PARA_SEL | SONY_USB_SRAM_DONE));
}
int main(void)
{
    SonyUsbPower p, saved;
    uint32_t value;
    sony_usb_power_init(&p);
    saved = p;
    for (unsigned i = 0; i < 1000; i++) assert(!rd(&p, 0xf1080020));
    assert(!memcmp(&p, &saved, sizeof p));
    wr(&p, 0xf1080020, SONY_USB_SRAM_DONE);
    assert(!rd(&p, 0xf1080020)); /* A guest write cannot publish hardware done. */
    for (unsigned i = 0; i < 4; i++) {
        sony_usb_power_init(&p); gates(&p, 0x1000u << i); prepare(&p, 0, -1); release(&p);
        assert(!sony_usb_sram_initialized(&p));
        sony_usb_power_init(&p); gates(&p, 0); prepare(&p, 0x100u << i, -1); release(&p);
        assert(!sony_usb_sram_initialized(&p));
    }
    for (int i = 0; i < 3; i++) {
        sony_usb_power_init(&p); gates(&p, 0); prepare(&p, 0, i); release(&p);
        assert(!sony_usb_sram_initialized(&p));
    }
    sony_usb_power_init(&p); gates(&p, 0); wr(&p, 0xf1388304, 0xf00);
    wr(&p, 0xf1080020, 0); wr(&p, 0xf1080020, 0); wr(&p, 0xf1080020, 0x100000);
    release(&p); assert(!sony_usb_sram_initialized(&p)); /* APB was never released. */
    sony_usb_power_init(&p); prepare(&p, 0, -1); gates(&p, 0); release(&p);
    assert(!sony_usb_sram_initialized(&p)); /* Late clock enables do not backfill setup. */
    for (unsigned i = 0; i < 4; i++) {
        sony_usb_power_init(&p); complete(&p);
        wr(&p, 0xf1388304, 0x100u << i);
        assert(!(rd(&p, 0xf1080020) & SONY_USB_SRAM_DONE));
        wr(&p, 0xf1388308, 0x100u << i);
        assert(!sony_usb_sram_initialized(&p));
        sony_usb_power_init(&p); complete(&p);
        wr(&p, 0xf1388008, 0x1000u << i);
        assert(!sony_usb_sram_initialized(&p));
        wr(&p, 0xf1388004, 0x1000u << i);
        assert(!sony_usb_sram_initialized(&p));
        complete(&p); /* Full reinitialization is required after clock loss. */
    }
    sony_usb_power_init(&p); complete(&p);
    wr(&p, 0xf1080020, rd(&p, 0xf1080020));
    assert(sony_usb_sram_initialized(&p)); /* RMW of the RO bit preserves state. */
    saved = p;
    for (unsigned i = 0; i < 1000; i++) assert(rd(&p, 0xf1080020) & SONY_USB_SRAM_DONE);
    assert(!memcmp(&p, &saved, sizeof p));
    assert(sony_usb_power_read(&p, 0xf1080024, 4, &value) == -EOPNOTSUPP && value == UINT32_MAX);
    assert(sony_usb_power_read(&p, 0xf1080020, 1, &value) == -EOPNOTSUPP);
    assert(sony_usb_power_write(&p, 0xf1388004, 4, 1) == -EOPNOTSUPP);
    assert(sony_usb_power_write(&p, 0xf1388304, 4, 1) == -EOPNOTSUPP);
    assert(sony_usb_power_write(&p, 0xf1080020, 4, 2) == -EOPNOTSUPP);
    assert(sony_usb_power_write(&p, 0xf10b7ffc, 4, 0x1234) == -EOPNOTSUPP);
    assert(!memcmp(&p, &saved, sizeof p));
    assert(sony_usb_power_write(&p, 0xf1080020, 4, rd(&p, 0xf1080020) | SONY_USB_EXT_LOAD_DONE) == -EAGAIN);
    assert(!memcmp(&p, &saved, sizeof p));
    assert(sony_usb_power_read(&p, SONY_USB_FW_BASE, 4, &value) == -ENODATA);
    assert(sony_usb_power_write(&p, SONY_USB_FW_BASE, 2, 0x1234) == -EOPNOTSUPP);
    assert(sony_usb_power_write(&p, SONY_USB_FW_BASE + 4, 4, 0x1234) == -EINVAL);
    assert(sony_usb_power_write(&p, SONY_USB_FW_BASE, 4, 0x10000) == -EOPNOTSUPP);
    assert(!memcmp(&p, &saved, sizeof p));
    for (unsigned i = 0; i < SONY_USB_FW_WORDS; i++) {
        uint32_t word = (i * 137u + 0x80eu) & 0xffffu;
        wr(&p, SONY_USB_FW_BASE + i * 4, word);
        assert(p.firmware_words == i + 1 && p.firmware[i] == word);
        assert(rd(&p, SONY_USB_FW_BASE + i * 4) == word);
        assert(sony_usb_power_read(&p, SONY_USB_FW_BASE + i * 4, 2, &value) == 0 && value == word);
        assert(sony_usb_power_read(&p, SONY_USB_FW_BASE + i * 4 + 2, 2, &value) == 0 && !value);
    }
    saved = p;
    assert(sony_usb_power_read(&p, SONY_USB_FW_BASE + 1, 2, &value) == -EOPNOTSUPP);
    assert(sony_usb_power_read(&p, SONY_USB_FW_BASE, 1, &value) == -EOPNOTSUPP);
    assert(sony_usb_power_read(&p, SONY_USB_FW_END, 4, &value) == -EOPNOTSUPP);
    assert(sony_usb_power_write(&p, SONY_USB_FW_BASE, 4, 0x80e) == -EINVAL);
    assert(!memcmp(&p, &saved, sizeof p));
    wr(&p, 0xf1080020, rd(&p, 0xf1080020) | SONY_USB_EXT_LOAD_DONE);
    assert(p.cfgr0 & SONY_USB_EXT_LOAD_DONE);
    assert(sony_usb_sram_initialized(&p)); /* Handoff is separate from UDC readiness. */
    wr(&p, 0xf1388008, 0x1000);
    assert(!p.firmware_words && !(p.cfgr0 & SONY_USB_EXT_LOAD_DONE));
    assert(sony_usb_power_read(&p, SONY_USB_FW_BASE, 4, &value) == -ENODATA);
    assert(sony_usb_power_write(&p, SONY_USB_FW_BASE, 4, 0x80e) == -EAGAIN);
    complete(&p);
    wr(&p, SONY_USB_FW_BASE, 0x80e);
    saved = p;
    assert(sony_usb_power_write(&p, 0xf1080020, 4, rd(&p, 0xf1080020) | SONY_USB_EXT_LOAD_DONE) == -EAGAIN);
    assert(!memcmp(&p, &saved, sizeof p));
    wr(&p, 0xf1388304, 0x100);
    assert(!p.firmware_words && !(p.cfgr0 & SONY_USB_EXT_LOAD_DONE));
    complete(&p);
    wr(&p, 0xf1080020, SONY_USB_PARA_SEL | SONY_USB_BYPASS);
    assert(!sony_usb_sram_initialized(&p));
    return 0;
}
'''

# Original helper: usb_otg.c:301-304; prior real guest fault opcode 39400002 (LDRB).
MMIO_HOST_TEST_C = r'''
#include "sony-dwc3.h"
#include <assert.h>
#include <errno.h>
#include <string.h>
static SonyDWC3 s, saved;
static unsigned calls;
static void error(void *o, const char *w, int e, uint64_t a)
{ (void)o; (void)w; (void)e; (void)a; calls++; }
int main(void)
{
    SonyDWC3Ops ops = {.error = error};
    sony_dwc3_init(&s, &ops, 0);
    s.event_count = 8; s.event_pos = 12; s.dma_bytes = 123;
    s.events_written = 17; s.regs[SDWC_CMD(2)/4] = SDWC_CMDACT | SDWC_CMDIOC;
    saved = s;
    const uint32_t addresses[] = {0, 4, SDWC_GSNPSID, 0xc140, 0xc144, 0xc148,
                                  0xc14c, 0xc150, 0xc154, 0xc158, 0xc15c};
    const uint32_t expected[] = {0x01000040, 0, 0x5533290a, 0x40404000, 1u << 15,
                                 0, (16u << 18) | (32u << 12) | 4u, 0, 0, 0, 0x04000400};
    uint32_t value;
    for (unsigned i = 0; i < sizeof addresses/sizeof *addresses; i++) {
        for (unsigned size = 1; size <= 4; size *= 2) {
            for (unsigned lane = 0; lane + size <= 4; lane += size) {
                assert(sony_dwc3_read(&s, addresses[i]+lane, size, &value) == 0);
                uint32_t mask = UINT32_MAX >> ((4-size)*8);
                assert(value == ((expected[i] >> (lane*8)) & mask));
                assert(!memcmp(&s, &saved, sizeof s));
            }
        }
    }
    assert(calls == 0); /* No DMA, events, ack, command or error side effects. */
    assert(!sony_dwc3_ready(&s));
    const uint32_t invalid[] = {1, 2, 3, SDWC_MMIO_SIZE-1, UINT32_MAX};
    for (unsigned i = 0; i < sizeof invalid/sizeof *invalid; i++) {
        assert(sony_dwc3_read(&s, invalid[i], 4, &value) == -EOPNOTSUPP);
        assert(value == UINT32_MAX);
    }
    assert(sony_dwc3_read(&s, 1, 2, &value) == -EOPNOTSUPP);
    assert(sony_dwc3_read(&s, 3, 2, &value) == -EOPNOTSUPP);
    assert(sony_dwc3_read(&s, 0, 3, &value) == -EOPNOTSUPP);
    assert(sony_dwc3_read(&s, 0, 8, &value) == -EOPNOTSUPP);
    assert(sony_dwc3_read(&s, 8, 1, &value) == -EOPNOTSUPP);
    assert(sony_dwc3_read(&s, 0x9000, 4, &value) == -EOPNOTSUPP);
    assert(sony_dwc3_read(&s, 0x44, 4, &value) == -EOPNOTSUPP); /* No xHCI USBSTS engine. */
    for (unsigned size = 1; size <= 2; size++) {
        assert(sony_dwc3_read(&s, SDWC_GEVNTCOUNT, size, &value) == -EOPNOTSUPP);
        assert(sony_dwc3_write(&s, SDWC_GEVNTCOUNT, size, 4) == -EOPNOTSUPP);
        assert(sony_dwc3_write(&s, SDWC_CMD(2), size, SDWC_CMDACT | 8) == -EOPNOTSUPP);
        assert(sony_dwc3_write(&s, SDWC_DCTL, size, SDWC_SOFTRST) == -EOPNOTSUPP);
    }
    for (unsigned size = 1; size <= 4; size *= 2) {
        assert(sony_dwc3_write(&s, 0, size, 0) == -EOPNOTSUPP);
    }
    assert(sony_dwc3_read(&s, SDWC_GEVNTCOUNT, 4, &value) == 0 && value == 8);
    assert(sony_dwc3_read(&s, SDWC_GEVNTCOUNT, 4, &value) == 0 && value == 8);
    assert(s.event_count == saved.event_count && s.event_pos == saved.event_pos);
    assert(s.dma_bytes == saved.dma_bytes && s.events_written == saved.events_written);
    assert(s.cable_generation == saved.cable_generation);
    assert(s.regs[SDWC_CMD(2)/4] == saved.regs[SDWC_CMD(2)/4]);
    assert(s.regs[SDWC_DCTL/4] == saved.regs[SDWC_DCTL/4]);
    assert(s.regs[0] == expected[0] && !s.regs[1]);
    assert(calls > 0 && !sony_dwc3_ready(&s));
    assert(sony_dwc3_read(&s, SDWC_LU1LFPSRXTIM0, 4, &value) == 0 && !value);
    assert(sony_dwc3_write(&s, SDWC_LU1LFPSRXTIM0, 4, 0x1f00) == 0);
    assert(sony_dwc3_read(&s, SDWC_LU1LFPSRXTIM0, 4, &value) == 0 && value == 0x1f00);
    assert(sony_dwc3_read(&s, SDWC_LU1LFPSRXTIM0, 2, &value) == -EOPNOTSUPP);
    assert(sony_dwc3_write(&s, SDWC_LU1LFPSRXTIM0, 2, 0) == -EOPNOTSUPP);
    assert(sony_dwc3_read(&s, SDWC_LU1LFPSRXTIM0 + 4, 4, &value) == -EOPNOTSUPP);
    assert(sony_dwc3_read(&s, SDWC_LU1LFPSRXTIM0 + 0x80, 4, &value) == -EOPNOTSUPP);
    assert(s.dma_bytes == saved.dma_bytes && s.events_written == saved.events_written);
    assert(!sony_dwc3_ready(&s));
    sony_dwc3_reset(&s);
    assert(sony_dwc3_read(&s, SDWC_LU1LFPSRXTIM0, 4, &value) == 0 && !value);
    return 0;
}
'''


class HostCModels(unittest.TestCase):
    def compile_run(self, source, *, core=False):
        with tempfile.TemporaryDirectory(prefix='usb-model-host-') as name:
            root = Path(name)
            path = root / 'test.c'; path.write_text(source)
            command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                       '-O1', '-fsanitize=undefined', '-I', str(HERE / 'usb-gadget'), str(path)]
            if core:
                command.append(str(HERE / 'usb-gadget/sony-dwc3.c'))
            command += ['-o', str(root / 'test')]
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=25)
            subprocess.run([str(root / 'test')], check=True, capture_output=True, text=True, timeout=10)

    def test_phy_sequence_reset_clock_loss_and_unknown_rejection(self):
        self.compile_run(API['PHY_MODEL_C'] + PHY_HOST_TEST_C)

    def test_generated_power_callbacks_consume_the_same_state_machine(self):
        callbacks = '#define SONY_USB_POWER_CALLBACKS' + API['PLATFORM_C'].split(
            '#define SONY_USB_POWER_CALLBACKS', 1)[1].split('#undef SONY_USB_POWER_CALLBACKS', 1)[0]
        prefix = r'''
#include <stdio.h>
#include <inttypes.h>
#include <assert.h>
typedef uint64_t hwaddr;
typedef int MemTxResult;
typedef int MemTxAttrs;
#define HWADDR_PRIx PRIx64
#define MEMTX_OK 0
#define MEMTX_ERROR 1
typedef struct SonyUsbPlatform { SonyUsbPower power; } SonyUsbPlatform;
static MemTxResult sony_usb_bad(hwaddr a, unsigned n, bool write)
{ (void)a; (void)n; (void)write; return MEMTX_ERROR; }
#pragma GCC diagnostic ignored "-Wunused-parameter"
'''
        fixture = r'''
int main(void)
{
    SonyUsbPlatform p;
    uint64_t value;
    sony_usb_power_init(&p.power);
    assert(sony_usb_clock_write(&p, 4, 0xf000, 4, 0) == MEMTX_OK);
    assert(sony_usb_clock_read(&p, 0, &value, 4, 0) == MEMTX_OK && value == 0xf000);
    assert(sony_usb_reset_write(&p, 4, 0xf00, 4, 0) == MEMTX_OK);
    assert(sony_usb_reset_write(&p, 8, 0x200, 4, 0) == MEMTX_OK);
    assert(sony_usb_reset_read(&p, 0, &value, 4, 0) == MEMTX_OK && value == 0xd00);
    assert(sony_usb_phy_write(&p, 0x20, 0, 4, 0) == MEMTX_OK);
    assert(sony_usb_phy_write(&p, 0x20, 0, 4, 0) == MEMTX_OK);
    assert(sony_usb_phy_write(&p, 0x20, 0x100000, 4, 0) == MEMTX_OK);
    assert(sony_usb_phy_read(&p, 0x20, &value, 4, 0) == MEMTX_OK && value == 0x100000);
    assert(sony_usb_reset_write(&p, 8, 0xf00, 4, 0) == MEMTX_OK);
    assert(sony_usb_phy_read(&p, 0x20, &value, 4, 0) == MEMTX_OK && value == 0x140000);
    assert(sony_usb_clock_write(&p, 8, 0x1000, 4, 0) == MEMTX_OK);
    assert(sony_usb_phy_read(&p, 0x20, &value, 4, 0) == MEMTX_OK && value == 0x100000);
    assert(sony_usb_phy_read(&p, 0x20, &value, 1, 0) == MEMTX_ERROR && value == UINT32_MAX);
    assert(sony_usb_phy_write(&p, 0x24, 0, 4, 0) == MEMTX_ERROR);
    assert(sony_usb_clock_write(&p, 4, 1, 4, 0) == MEMTX_ERROR);
    sony_usb_power_init(&p.power);
    assert(sony_usb_cr_write(&p, 0x18000, 0x80e, 4, 0) == MEMTX_ERROR);
    assert(sony_usb_cr_read(&p, 0x18000, &value, 2, 0) == MEMTX_ERROR);
    assert(sony_usb_clock_write(&p, 4, 0xf000, 4, 0) == MEMTX_OK);
    assert(sony_usb_reset_write(&p, 4, 0xf00, 4, 0) == MEMTX_OK);
    assert(sony_usb_reset_write(&p, 8, 0x200, 4, 0) == MEMTX_OK);
    assert(sony_usb_phy_write(&p, 0x20, 0, 4, 0) == MEMTX_OK);
    assert(sony_usb_phy_write(&p, 0x20, 0, 4, 0) == MEMTX_OK);
    assert(sony_usb_phy_write(&p, 0x20, 0x100000, 4, 0) == MEMTX_OK);
    assert(sony_usb_reset_write(&p, 8, 0xf00, 4, 0) == MEMTX_OK);
    for (unsigned i = 0; i < SONY_USB_FW_WORDS; i++) {
        assert(sony_usb_cr_write(&p, 0x18000 + i * 4, i ^ 0x80e, 4, 0) == MEMTX_OK);
        assert(sony_usb_cr_read(&p, 0x18000 + i * 4, &value, 4, 0) == MEMTX_OK && value == (i ^ 0x80e));
    }
    assert(sony_usb_phy_write(&p, 0x20, 0x160000, 4, 0) == MEMTX_OK);
    assert(p.power.cfgr0 & SONY_USB_EXT_LOAD_DONE);
    return 0;
}
'''
        self.compile_run(API['PHY_MODEL_C'] + prefix + callbacks + fixture)

    def test_derived_gpio_source_contract_keeps_fresh3_identity(self):
        contract = json.loads((HERE / 'usb-gpio-source-contract.json').read_text())
        frozen = json.loads((HERE / contract['base_fixture']).read_text())
        self.assertEqual(contract['schema'], 'a7c2.usb-gpio-source-contract.v1')
        self.assertEqual(contract['fresh3_public_profile_sha256'], frozen['public_sha256']['usb-device-profile.py'])
        self.assertEqual(contract['base_public_profile_sha256'], '8a72804dcbc032953149b19c0dcc910558a7c9d3a44da4e6d45f5234e30ef6d2')
        self.assertEqual(contract['base_provider_sha256'], frozen['source_sha256']['hw/arm/sony-usb-device-platform.inc'])
        # This receipt freezes the earlier GPIO source; fresh topology is bound per launch.
        self.assertEqual(contract['public_profile_sha256'], '9c520bf67b088b1c8d680a0884ddd1680dbe90fa75c7076e423fd75f215d47db')
        self.assertEqual(contract['provider_sha256'], API['sha'](API['PLATFORM_C'].encode()))
        generation = json.loads((HERE / 'usb-generation-source-contract.json').read_text())
        self.assertEqual(generation['schema'], 'a7c2.usb-generation-source-delta.v1')
        self.assertEqual(generation['parent_fixture'], contract['base_fixture'])
        self.assertEqual(generation['parent_sha256'], API['sha']((HERE / contract['base_fixture']).read_bytes()))
        self.assertEqual(set(generation['public_sha256']), {
            'usb-gadget/sony-dwc3.c', 'usb-gadget/sony-dwc3.h',
            'usb-gadget/sony-dwc3-bridge.c', 'usb-gadget/sony-dwc3-bridge.h'})
        for name, expected in frozen['public_sha256'].items():
            if name != 'usb-device-profile.py':
                expected = generation['public_sha256'].get(name, expected)
                self.assertEqual(expected, API['sha']((HERE / name).read_bytes()))
        self.assertEqual(contract['allowed_rdata_change_mask'], '0x00040000')
        self.assertFalse(contract['c1_generates_irq'])
        self.assertFalse(contract['original_guest_driver_reverified'])
        self.assertFalse(contract['original_ap_reverified'])

    def test_shared_gpio_c1_helper_rmw_vbus_and_irq_isolation(self):
        platform = API['PLATFORM_C']
        gpio = platform.split('#include "hw/core/irq.h"\n', 1)[1].split('#define SONY_USB_POWER_CALLBACKS', 1)[0]
        power = '#define SONY_USB_POWER_CALLBACKS' + platform.split(
            '#define SONY_USB_POWER_CALLBACKS', 1)[1].split('#undef SONY_USB_POWER_CALLBACKS', 1)[0]
        vbus = 'static void sony_usb_vbus_request' + platform.split(
            'static void sony_usb_vbus_request', 1)[1].split('static void sony_usb_platform_create', 1)[0]
        prefix = r'''
#include <assert.h>
#include <stdio.h>
#include <inttypes.h>
#include <string.h>
typedef uint64_t hwaddr;
typedef int MemTxResult;
typedef int MemTxAttrs;
typedef int MemoryRegion;
typedef struct Irq { int level; unsigned changes, pulses; } Irq;
typedef Irq *qemu_irq;
#define HWADDR_PRIx PRIx64
#define MEMTX_OK 0
#define MEMTX_ERROR 1
#define LOG_GUEST_ERROR 1
#define qemu_log_mask(...) ((void)0)
static void qemu_set_irq(qemu_irq irq, int level)
{ irq->level = level; irq->changes++; }
static void qemu_irq_pulse(qemu_irq irq) { irq->pulses++; }
#pragma GCC diagnostic ignored "-Wunused-parameter"
'''
        fixture = r'''
#define GPIO_BASE 0xf102e000u
static uint32_t gpio_read(SonyUsbPlatform *p, uint32_t address)
{
    uint64_t value;
    assert(sony_usb_gpio_read(p, address - GPIO_BASE, &value, 4, 0) == MEMTX_OK);
    return value;
}
static void pad_write(SonyUsbPlatform *p, uint32_t value)
{
    assert(sony_usb_gpio_write(p, 0xf102e010u - GPIO_BASE, value, 4, 0) == MEMTX_OK);
    assert(gpio_read(p, 0xf102e010u) == value);
}
int main(void)
{
    Irq irq = {0}, controller = {0};
    SonyUsbPlatform p = { .vbus_irq = &irq, .controller_vbus = &controller }, saved;
    sony_usb_power_init(&p.power);
    assert(gpio_read(&p, 0xf102e010u) == 0); /* No invented C1 press or default release. */
    const uint32_t other = 0xa5a25a5au & ~(SONY_USB_VBUS_INPUT | SONY_USB_C1_INPUT);
    p.gpio_regs[4] = other | SONY_USB_VBUS_INPUT | SONY_USB_C1_INPUT;
    assert(gpio_read(&p, 0xf102e010u) == other); /* Preserve backing except owned inputs. */
    pad_write(&p, other | SONY_USB_C1_INPUT);
    assert(p.c1_input && !p.present && !p.generation && p.reads == 3);
    assert(!irq.pulses && !controller.changes);
    for (unsigned i = 0; i < 32; i++) {
        if (i == 18) continue;
        saved = p;
        assert(sony_usb_gpio_write(&p, 0x10, (other | SONY_USB_C1_INPUT) ^ (1u << i), 4, 0) == MEMTX_ERROR);
        assert(!memcmp(&p, &saved, sizeof p));
    }
    saved = p;
    assert(sony_usb_gpio_write(&p, 0x10, (1ull << 32) | other | SONY_USB_C1_INPUT, 4, 0) == MEMTX_ERROR);
    assert(!memcmp(&p, &saved, sizeof p));
    for (unsigned n = 1; n <= 8; n *= 2) {
        if (n == 4) continue;
        assert(sony_usb_gpio_write(&p, 0x10, other, n, 0) == MEMTX_ERROR);
        assert(!memcmp(&p, &saved, sizeof p));
    }
    for (unsigned off = 0x14; off <= 0x1c; off += 4) {
        assert(sony_usb_gpio_write(&p, off, 0, 4, 0) == MEMTX_ERROR);
        assert(!memcmp(&p, &saved, sizeof p));
    }
    uint64_t value;
    const unsigned invalid[] = {1, 0xc, 0x1c, 0x2c, 0x3c, 0x4c, 0x50, 0xffc};
    for (unsigned i = 0; i < sizeof invalid / sizeof *invalid; i++) {
        assert(sony_usb_gpio_read(&p, invalid[i], &value, 4, 0) == MEMTX_ERROR);
        assert(sony_usb_gpio_write(&p, invalid[i], 0, 4, 0) == MEMTX_ERROR);
        assert(!memcmp(&p, &saved, sizeof p));
    }
    /* DIR/INEN/PORTSEL/WDATA retain direct/set/clear and read alias behavior. */
    const unsigned regs[] = {0, 0x20, 0x30, 0x40};
    for (unsigned i = 0; i < sizeof regs / sizeof *regs; i++) {
        assert(sony_usb_gpio_write(&p, regs[i], 0x12340000, 4, 0) == MEMTX_OK);
        assert(sony_usb_gpio_write(&p, regs[i] + 4, 0x80, 4, 0) == MEMTX_OK);
        assert(sony_usb_gpio_write(&p, regs[i] + 8, 0x40000, 4, 0) == MEMTX_OK);
        for (unsigned lane = 0; lane <= 8; lane += 4)
            assert(gpio_read(&p, GPIO_BASE + regs[i] + lane) == 0x12300080);
    }
    assert(sony_usb_int_write(&p, 0x20, SONY_USB_C1_INPUT, 4, 0) == MEMTX_OK);
    assert(sony_usb_int_write(&p, 0x30, SONY_USB_C1_INPUT, 4, 0) == MEMTX_OK);
    assert(sony_usb_int_read(&p, 0x20, &value, 4, 0) == MEMTX_OK && value == SONY_USB_C1_INPUT);
    sony_usb_vbus_request(&p, 0, 1);
    assert(p.generation == 1 && !p.reads && p.c1_input && !irq.pulses);
    assert(controller.level == 1 && controller.changes == 1);
    uint32_t before = gpio_read(&p, 0xf102e010u);
    assert(before == (other | SONY_USB_C1_INPUT | SONY_USB_VBUS_INPUT) && p.reads == 1);
    pad_write(&p, before & ~SONY_USB_C1_INPUT);
    assert(!p.c1_input && !irq.pulses && p.generation == 1 && controller.changes == 1);
    saved = p;
    assert(sony_usb_gpio_write(&p, 0x10, other, 4, 0) == MEMTX_ERROR); /* Cannot clear VBUS. */
    assert(!memcmp(&p, &saved, sizeof p));
    pad_write(&p, before);
    assert(sony_usb_clock_write(&p, 4, 0xf000, 4, 0) == MEMTX_OK);
    assert(sony_usb_clock_write(&p, 8, 0xf000, 4, 0) == MEMTX_OK);
    assert(sony_usb_reset_write(&p, 4, 0xf00, 4, 0) == MEMTX_OK);
    assert(sony_usb_reset_write(&p, 8, 0xf00, 4, 0) == MEMTX_OK);
    assert(gpio_read(&p, 0xf102e010u) == before && p.c1_input && p.generation == 1);
    sony_usb_vbus_request(&p, 0, 0);
    assert(p.generation == 2 && !p.reads && p.c1_input && !irq.pulses);
    assert(gpio_read(&p, 0xf102e010u) == (other | SONY_USB_C1_INPUT));
    assert(sony_usb_int_write(&p, 0x24, SONY_USB_VBUS_INPUT, 4, 0) == MEMTX_OK);
    assert(sony_usb_int_write(&p, 0x34, SONY_USB_VBUS_INPUT, 4, 0) == MEMTX_OK);
    sony_usb_vbus_request(&p, 0, 1);
    assert(irq.pulses == 1 && p.generation == 3 && p.c1_input);
    sony_usb_vbus_request(&p, 0, 1);
    assert(irq.pulses == 1 && p.generation == 3);
    pad_write(&p, other | SONY_USB_VBUS_INPUT);
    assert(irq.pulses == 1 && !p.c1_input);
    assert(sony_usb_int_write(&p, 0x14, SONY_USB_VBUS_INPUT, 4, 0) == MEMTX_OK);
    sony_usb_vbus_request(&p, 0, 0);
    assert(irq.pulses == 1 && p.generation == 4 && !p.c1_input);
    assert(gpio_read(&p, 0xf102e010u) == other);
    assert(sony_usb_int_write(&p, 0x18, SONY_USB_VBUS_INPUT, 4, 0) == MEMTX_OK);
    sony_usb_vbus_request(&p, 0, 1);
    sony_usb_vbus_request(&p, 0, 0);
    assert(irq.pulses == 3 && p.generation == 6 && !p.c1_input);
    assert(p.gpio_regs[4] == (other | SONY_USB_VBUS_INPUT | SONY_USB_C1_INPUT));
    return 0;
}
'''
        # Unused power callbacks are compiled too, exactly as generated for QEMU.
        prefix += '\n#pragma GCC diagnostic ignored "-Wunused-function"\n'
        self.compile_run(API['PHY_MODEL_C'] + prefix + gpio + power + vbus + fixture)

    def test_capability_lanes_do_not_consume_mmio_side_effects(self):
        self.compile_run(MMIO_HOST_TEST_C, core=True)
        source = (HERE / 'usb-gadget/sony-dwc3.c').read_text()
        ops = source.split('static const MemoryRegionOps qemu_dwc3_ops = {', 1)[1].split('};', 1)[0]
        self.assertIn('.valid.min_access_size = 1', ops)
        self.assertIn('.impl.min_access_size = 1', ops)
        self.assertIn('.valid.unaligned = false', ops)
        self.assertIn('.impl.unaligned = false', ops)


class DeviceProfile(unittest.TestCase):
    def setUp(self):
        library = os.environ.get('A7C2_LIBFDT') or ctypes.util.find_library('fdt')
        if not library:
            candidate = HERE.parents[1] / 'runtime/sources/qemu-tools/usr/lib/libfdt.so.1'
            library = str(candidate.resolve()) if candidate.is_file() else 'libfdt.so.1'
        self.fdt = ctypes.CDLL(library)
        self.fdt.fdt_getprop.restype = ctypes.c_void_p
        self.buf = ctypes.create_string_buffer(65536)
        self.assertEqual(self.fdt.fdt_create_empty_tree(self.buf, len(self.buf)), 0)
        for key, value in ((b'compatible', b'linux,dummy-virt\0'),
                           (b'#address-cells', API['U32'](2)), (b'#size-cells', API['U32'](2))):
            self.assertEqual(self.fdt.fdt_setprop(self.buf, 0, key, value, len(value)), 0)
        gic = self.fdt.fdt_add_subnode(self.buf, 0, b'intc@8000000')
        value = API['U32'](1)
        self.assertEqual(self.fdt.fdt_setprop(self.buf, gic, b'phandle', value, len(value)), 0)

    def prop(self, path, name):
        node = self.fdt.fdt_path_offset(self.buf, path.encode())
        self.assertGreaterEqual(node, 0)
        n = ctypes.c_int()
        ptr = self.fdt.fdt_getprop(self.buf, node, name.encode(), ctypes.byref(n))
        self.assertTrue(ptr)
        return ctypes.string_at(ptr, n.value)

    def test_original_resources_and_real_extcon_phandle(self):
        API['add_nodes'](self.fdt, self.buf)
        path = '/soc/usbs@f1080000/usb@f10c0000'
        self.assertEqual(self.prop('/soc', 'compatible'), b'simple-bus\0')
        self.assertEqual(self.prop('/soc', '#address-cells'), API['U32'](2))
        self.assertEqual(self.prop('/soc', '#size-cells'), API['U32'](2))
        self.assertEqual(self.prop('/soc', 'ranges'), b'')
        self.assertLess(self.fdt.fdt_path_offset(self.buf, b'/sony-usb@f1080000'), 0)
        self.assertEqual(self.prop(path, 'reg'), API['REG'](0xf10c0000, 0x11000))
        self.assertEqual(self.prop(path, 'interrupts'), API['U32'](0, 184, 4))
        self.assertEqual(self.prop(path, 'interrupt-parent'), API['U32'](1))
        self.assertEqual(self.prop(path, 'dr_mode'), b'otg\0')
        self.assertEqual(self.prop(path, 'extcon'), self.prop('/fusb_otg', 'phandle'))
        self.assertEqual(self.prop('/sony-usb-clock', 'compatible'), b'cxd,900xx-clock\0')
        self.assertEqual(self.prop('/sony-usb-clock', '#clock-cells'), API['U32'](1))
        clock = self.prop('/sony-usb-clock', 'phandle')
        self.assertEqual(self.prop('/soc/usbs@f1080000', 'clocks'),
                         b''.join(clock + API['U32'](i) for i in (19, 18, 17, 16)))
        self.assertEqual(self.prop('/sony-usb-scu@f1388000/rst@300', 'reg'), API['REG'](0x300, 0x80))
        with self.assertRaisesRegex(ValueError, 'collision|already exists'):
            API['add_nodes'](self.fdt, self.buf)

    def soc(self, name=b'soc', **changes):
        node = self.fdt.fdt_add_subnode(self.buf, 0, name)
        values = {'compatible': b'simple-bus\0', '#address-cells': API['U32'](2),
                  '#size-cells': API['U32'](2), 'ranges': b''}
        values.update(changes)
        for key, value in values.items():
            if value is not None:
                self.assertEqual(self.fdt.fdt_setprop(self.buf, node, key.encode(), value, len(value)), 0)
        return node

    def test_exact_existing_soc_is_reused_without_changing_properties(self):
        self.soc()
        API['add_nodes'](self.fdt, self.buf)
        self.assertEqual(self.prop('/soc', 'compatible'), b'simple-bus\0')
        self.assertEqual(self.prop('/soc/usbs@f1080000', 'reg'),
                         API['REG'](0xf1080000, 0x1000) + API['REG'](0xf10a0000, 0x1c000))

    def test_unknown_soc_and_resource_collisions_fail_before_any_mutation(self):
        for case in ('compatible', 'cells', 'ranges', 'extra', 'missing', 'child', 'unit-name', 'legacy', 'clock'):
            with self.subTest(case=case):
                self.setUp()
                if case in ('legacy', 'clock'):
                    self.fdt.fdt_add_subnode(self.buf, 0, b'sony-usb@f1080000' if case == 'legacy' else b'sony-usb-clock')
                else:
                    changes = {'compatible': b'unknown\0'} if case == 'compatible' else (
                        {'#address-cells': API['U32'](1)} if case == 'cells' else (
                        {'ranges': API['U32'](0)} if case == 'ranges' else (
                        {'status': b'okay\0'} if case == 'extra' else (
                        {'ranges': None} if case == 'missing' else {}))))
                    soc = self.soc(b'soc@0' if case == 'unit-name' else b'soc', **changes)
                    if case == 'child':
                        self.fdt.fdt_add_subnode(self.buf, soc, b'unknown@0')
                before = self.buf.raw
                with self.assertRaises(ValueError):
                    API['add_nodes'](self.fdt, self.buf)
                self.assertEqual(self.buf.raw, before)

    def test_host_cannot_select_device_resources(self):
        for mode, controller in [('off', 'sony-device'), ('regs', 'sony-device'), ('full', 'upstream-host')]:
            with self.subTest(mode=mode, controller=controller), self.assertRaises(ValueError):
                API['add_nodes'](self.fdt, self.buf, mode, controller)

    def test_missing_gic_and_wrong_board_fail_before_mutation(self):
        n = self.fdt.fdt_path_offset(self.buf, b'/intc@8000000')
        self.fdt.fdt_del_node(self.buf, n)
        with self.assertRaisesRegex(ValueError, 'GIC'):
            API['add_nodes'](self.fdt, self.buf)
        self.assertLess(self.fdt.fdt_path_offset(self.buf, b'/fusb_otg'), 0)

    def test_explicit_launch_bindings_and_stale_socket_rejection(self):
        with tempfile.TemporaryDirectory(prefix='usb-device-') as name:
            root = Path(name)
            env = API['launch_environment'](root, 'a' * 64)
            self.assertEqual(env['QEMU_FULL_USB_CONTROLLER'], 'sony-device')
            self.assertEqual(env['QEMU_SONY_USB_QMP_HOST_PATH'], str(root / 'qmp.sock'))
            self.assertEqual(env['QEMU_SONY_USB_BACKEND_SOCKET'], '/out/usb-endpoint.sock')
            with self.assertRaises(ValueError):
                API['launch_environment'](root, 'short')
            root.chmod(0o777)
            with self.assertRaises(ValueError):
                API['launch_environment'](root, 'a' * 64)
            root.chmod(0o700)
            with socket.socket(socket.AF_UNIX) as sock:
                sock.bind(str(root / 'qmp.sock'))
                with self.assertRaisesRegex(ValueError, 'existed'):
                    API['launch_environment'](root, 'a' * 64)

    def test_copied_launcher_preserves_host_call_and_whitelists_bindings(self):
        text = ('from pathlib import Path\n'
                'runpy.run_path(sys.argv[7])["add_nodes"](fdt,buffer,sys.argv[6],sys.argv[8])\n'
                'bootfs="$analysis_dir/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked"\n')
        updated = API['adapt_script'](text)
        self.assertEqual(API['adapt_script'](updated), updated)
        self.assertIn('else sys.argv[7]', updated)
        for key in ('QEMU_SONY_USB_RUN_ID', 'QEMU_SONY_USB_LEASE',
                    'QEMU_SONY_USB_QMP_HOST_PATH', 'QEMU_SONY_USB_BACKEND_SOCKET'):
            self.assertIn(key, updated)
        self.assertIn('--setenv "$usb_binding" "${!usb_binding}"', updated)
        with self.assertRaises(ValueError):
            API['adapt_script']('# unknown launcher\n')

    def test_source_delta_is_separate_and_has_no_ready_injection(self):
        with tempfile.TemporaryDirectory() as name:
            scratch = Path(name)
            source = scratch / 'qemu'
            (source / 'hw/arm').mkdir(parents=True)
            (source / 'hw/usb').mkdir()
            for name in ('sony-dwc3.c', 'sony-dwc3.h', 'sony-dwc3-bridge.c', 'sony-dwc3-bridge.h'):
                data = (HERE / 'usb-gadget' / name).read_bytes()
                if name == 'sony-dwc3.c':
                    data = b'#define SONY_DWC3_QEMU 1\n' + data
                (source / 'hw/usb' / name).write_bytes(data)
            board = source / 'hw/arm/virt.c'
            board.write_text('#include "hw/arm/virt.h"\nvoid board(void) {\n    create_msi_controller(vms);\n}\n')
            result = API['patch_source'](source, scratch)
            self.assertFalse(result['export_allowed'])
            self.assertFalse(result['phy_sram_supported'])
            self.assertEqual(result['phy_sram_init_model'], 'clock-reset-config-sequence-v1')
            self.assertFalse(result['vbus_kernel_event_delivered'])
            generated = board.read_text()
            self.assertIn('sony_usb_platform_create(sysmem, usb, vms->gic)', generated)
            self.assertIn('qdev_get_gpio_in(vms->gic, 184)', generated)
            self.assertIn('QEMU_SONY_USB_DWC3', generated)
            self.assertEqual(set(result['files']), {'hw/arm/virt.c', 'hw/arm/sony-usb-device-platform.inc'})
            with self.assertRaises(ValueError):
                API['patch_source'](source, scratch)
            with self.assertRaises(ValueError):
                API['patch_source'](source, source)



@pytest.fixture
def persistent_launch(tmp_path, monkeypatch):
    # Reuse the real persistent prepare API, tiny disk and lease, never a VM.
    helper = runpy.run_path(str(HERE / 'test-persistent-boot.py'))['prepared_launch'].__wrapped__
    monkeypatch.setitem(helper.__globals__, 'API', API['PERSISTENT'])
    fixture = helper(tmp_path, monkeypatch)
    launch = fixture.launch
    production = fixture.qemu_build.parent
    binary = Path(launch['qemu_binary'])
    model = {}
    for name in ('sony-dwc3.c', 'sony-dwc3.h', 'sony-dwc3-bridge.c', 'sony-dwc3-bridge.h'):
        data = (HERE / 'usb-gadget' / name).read_bytes()
        model['hw/usb/' + name] = API['sha']((b'#define SONY_DWC3_QEMU 1\n' if name == 'sony-dwc3.c' else b'') + data)
    provider = API['sha'](API['PLATFORM_C'].encode())
    combined = dict(schema='a7c2.persistent-usb-source.v1', provider_sha256=provider,
        model_source_sha256=model, files={'hw/arm/virt.c': {'after': 'd' * 64}})
    deltas = {}
    for name in ('dwc3-model-delta.json', 'usb-device-source-delta.json',
                 'persistent-flash-model-delta.json', 'persistent-usb-source-delta.json'):
        path = production / name
        path.write_text(json.dumps(combined if name.startswith('persistent-usb') else {'delta': name}))
        deltas[name] = API['COLD']['digest'](path)
    fixture.production = dict(status='compiled', board_profile=API['PERSISTENT']['PROFILE'],
        test_fixture_only=False, binary=str(binary), qemu_binary_sha256=launch['qemu_sha256'],
        usb_device_profile=API['PROFILE'], usb_source_sha256={**model, 'hw/arm/sony-usb-device-platform.inc': provider},
        board_source_sha256='d' * 64, source_deltas_sha256=deltas,
        all_source_delta_sha256=deltas['persistent-usb-source-delta.json'],
        source_delta_sha256=deltas['persistent-flash-model-delta.json'])
    bind_production(fixture)
    fixture.prepare_calls = []

    def prepare_only(command, **kwargs):
        assert kwargs['env']['QEMU_PREPARE_ONLY'] == '1'
        fixture.prepare_calls.append((command, kwargs))
        Path(launch['dtb']).write_bytes(b'new-usb-device-dtb')
        cmdline = Path(launch['cmdline_file'])
        replacement = cmdline.with_suffix('.new')
        replacement.write_bytes(cmdline.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(cmdline)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(API['subprocess'], 'run', prepare_only)
    return fixture


def bind_production(fixture):
    path = fixture.qemu_build.parent / 'qemu-result.json'
    path.write_text(json.dumps(fixture.production))
    fixture.launch['template_inputs'] = [
        API['COLD']['binding'](path, row['role']) if row['path'] == str(path) else row
        for row in fixture.launch['template_inputs']]


def assert_not_prepared(fixture):
    assert fixture.prepare_calls == []
    assert not Path(fixture.launch['script']).with_name('qemu-kernel-usb-device.sh').exists()
    assert not (Path(fixture.launch['qmp_socket']).parent.parent / 'usb-prepare.stdout').exists()


def test_usb_prepare_rebinds_real_assets_and_passes_persistent_leased_validator(persistent_launch, monkeypatch):
    fixture = persistent_launch
    original = deepcopy(fixture.launch)
    binding = API['COLD']['binding']
    reads = []

    def actual_binding(path, role):
        row = binding(path, role)
        assert set(row) == {'path', 'role', 'bytes', 'sha256', 'mode', 'device', 'inode'}
        reads.append(row)
        return row

    monkeypatch.setitem(API['COLD'], 'binding', actual_binding)
    monkeypatch.setitem(API['COLD']['recheck'].__globals__, 'binding', actual_binding)
    result = API['prepare_launch'](fixture.launch, lease='b' * 64)
    assert fixture.launch == original
    assert len(fixture.prepare_calls) == 1
    command, kwargs = fixture.prepare_calls[0]
    assert kwargs['timeout'] == 55 and kwargs['check'] is True
    assert command[1] == result['script']
    assert result['env']['QEMU_SONY_USB_LEASE'] == 'b' * 64
    assert result['env']['QEMU_SONY_USB_RUN_ID'] == Path(original['qmp_socket']).parent.name
    assert result['env']['QEMU_SONY_USB_QMP_HOST_PATH'] == original['qmp_socket']
    assert result['script_sha256'] == API['COLD']['digest'](result['script'])
    assert Path(result['script']).stat().st_mode & 0o777 == 0o700
    assert not result['guest_started'] and not result['guest_descriptor_ready'] and not result['export_allowed']
    for key in ('qmp_socket', 'qmp_parent', 'instance', 'cmdline', *API['PERSISTENT']['IDENTITY_FIELDS']):
        assert result[key] == original[key]
    delta = result['usb_device_delta']
    assert 'b' * 64 not in json.dumps(delta)
    assert delta['script_before']['sha256'] == original['script_sha256']
    assert delta['script_after']['sha256'] == result['script_sha256']
    assert delta['dtb_before']['sha256'] != delta['dtb_after']['sha256']
    assert delta['cmdline_before']['sha256'] == delta['cmdline_after']['sha256']
    assert delta['cmdline_before']['inode'] != delta['cmdline_after']['inode']
    assert delta['cmdline_bytes_unchanged'] is True
    assert delta['topology'] == '/soc/usbs@f1080000/usb@f10c0000'
    assert delta['profile_source'] == binding(HERE / 'usb-device-profile.py', 'usb-device-profile-source')
    assert delta['profile_source'] in result['template_inputs']
    paths = {original['dtb'], original['cmdline_file']}
    for old, new in zip(original['launch_inputs'], result['launch_inputs']):
        assert new == (binding(old['path'], old['role']) if old['path'] in paths else old)
        assert new['role'] == old['role']
    assert result['template_inputs'][:len(original['template_inputs'])] == original['template_inputs']
    assert {r['path'] for r in original['template_inputs'] + original['launch_inputs']} <= {r['path'] for r in reads}
    # The old unchanged receipt really fails against the newly generated DTB.
    with pytest.raises(API['PERSISTENT']['IdentityMismatch'], match='launch asset'):
        with API['PERSISTENT']['leased_launch'](original):
            pytest.fail('stale DTB binding yielded')
    with API['PERSISTENT']['leased_launch'](result) as bound:
        assert bound['pass_fds'] == (bound['fd'],)
        assert bound['env']['QEMU_SONY_USB_LEASE'] == 'b' * 64
        assert int(bound['env']['PERSISTENT_DISK_INO']) == fixture.disk.stat().st_ino


def test_usb_generation_is_bound_by_real_preparation(persistent_launch):
    fixture = persistent_launch
    fixture.launch['env']['QEMU_TRACE_FLAGS'] = 'guest_errors'
    fixture.production['generation_observer_release'] = runpy.run_path(str(HERE / 'usb-generation-build.py'))['source_contract']()
    bind_production(fixture)
    result = API['prepare_launch'](fixture.launch, lease='b' * 64, observe_generation=True)
    script = Path(result['script']).read_text()
    assert script.count('display_args+=(-global sony-dwc3-gadget.generation-observe=on)') == 1
    assert result['script_sha256'] == API['COLD']['digest'](result['script'])
    assert result['usb_device_delta']['generation_observe'] is True
    assert result['launch_adaptations']['usb_generation_observe'] is True
    with API['PERSISTENT']['leased_launch'](result) as bound:
        assert bound['env']['QEMU_TRACE_FLAGS'] == 'guest_errors'
        assert bound['pass_fds'] == (bound['fd'],)


def test_usb_generation_rejects_unreviewed_binary(persistent_launch):
    fixture = persistent_launch
    fixture.launch['env']['QEMU_TRACE_FLAGS'] = 'guest_errors'
    with pytest.raises(ValueError, match='reviewed binary release'):
        API['prepare_launch'](fixture.launch, lease='b' * 64, observe_generation=True)
    assert_not_prepared(fixture)


def test_usb_generation_rejects_missing_log_sink(persistent_launch):
    fixture = persistent_launch
    fixture.launch['env']['QEMU_TRACE_FLAGS'] = 'unimp'
    with pytest.raises(ValueError, match='guest_errors'):
        API['prepare_launch'](fixture.launch, lease='b' * 64, observe_generation=True)
    assert_not_prepared(fixture)


@pytest.mark.parametrize('asset', ('dtb', 'cmdline_file', 'current-kernel', 'installed-disk-kernel', 'boot-handoff', 'qemu'))
@pytest.mark.parametrize('drift', ('sha', 'mode', 'inode'))
def test_usb_prepare_rejects_baseline_asset_drift_before_creating(persistent_launch, asset, drift):
    fixture = persistent_launch
    launch = fixture.launch
    if asset == 'current-kernel':
        path = Path(launch['actual_kernel']['path'])
    elif asset == 'installed-disk-kernel':
        path = Path(next(r['path'] for r in launch['launch_inputs'] if r['role'] == asset))
    elif asset == 'boot-handoff':
        path = Path(launch['runtime_analysis']) / 'boot-handoff.bin'
    else:
        path = Path(launch['qemu_binary' if asset == 'qemu' else asset])
    if drift == 'sha':
        path.write_bytes(b'x' * path.stat().st_size)
    elif drift == 'mode':
        path.chmod((path.stat().st_mode & 0o777) ^ 0o100)
    else:
        new = path.with_name(path.name + '.replacement')
        new.write_bytes(path.read_bytes())
        new.chmod(path.stat().st_mode & 0o777)
        new.replace(path)
    with pytest.raises(ValueError):
        API['prepare_launch'](launch, lease='b' * 64)
    assert_not_prepared(fixture)


@pytest.mark.parametrize('key', ('dtb', 'cmdline_file'))
def test_usb_prepare_does_not_launder_wrong_baseline_hash(persistent_launch, key):
    fixture = persistent_launch
    path = fixture.launch[key]
    fixture.launch['launch_inputs'] = [dict(row, sha256='0' * 64) if row['path'] == path else row
                                       for row in fixture.launch['launch_inputs']]
    with pytest.raises(ValueError, match='Source changed'):
        API['prepare_launch'](fixture.launch, lease='b' * 64)
    assert_not_prepared(fixture)


@pytest.mark.parametrize('case', ('started', 'foreign-script', 'script-drift', 'foreign-command', 'missing-dtb-row', 'legacy-fresh3', 'legacy-persistent'))
def test_usb_prepare_rejects_foreign_or_incomplete_launch_before_creating(persistent_launch, case):
    fixture = persistent_launch
    launch = fixture.launch
    if case == 'started':
        launch['guest_started'] = True
    elif case in ('foreign-script', 'script-drift'):
        Path(launch['script']).write_text('# foreign launcher\n')
        if case == 'foreign-script':
            launch['script_sha256'] = API['COLD']['digest'](launch['script'])
    elif case == 'foreign-command':
        launch['command'][1] = '/foreign.sh'
    elif case == 'missing-dtb-row':
        launch['launch_inputs'] = [r for r in launch['launch_inputs'] if r['path'] != launch['dtb']]
    elif case == 'legacy-persistent':
        launch.pop('partition_bindings')
    else:
        launch['profile'] = 'virtual-functional-sony-usb-device-v1'
    with pytest.raises(ValueError):
        API['prepare_launch'](launch, lease='b' * 64)
    assert_not_prepared(fixture)


@pytest.mark.parametrize('case', ('usb-profile', 'old-board', 'binary-variant', 'binary-sha', 'fixture',
    'missing-usb-source', 'wrong-usb-source', 'missing-combination', 'null-combination',
    'board-source', 'system-dir', 'delta-hash', 'delta-file', 'combined-source'))
def test_usb_prepare_requires_bound_persistent_usb_combination(persistent_launch, case):
    fixture = persistent_launch
    production = fixture.production
    if case == 'usb-profile':
        production.pop('usb_device_profile')
    elif case == 'old-board':
        production['board_profile'] = 'upstream-host'
    elif case == 'binary-variant':
        production['binary'] += '.other'
    elif case == 'binary-sha':
        production['qemu_binary_sha256'] = '0' * 64
    elif case == 'fixture':
        production['test_fixture_only'] = True
    elif case == 'missing-usb-source':
        production.pop('usb_source_sha256')
    elif case == 'wrong-usb-source':
        production['usb_source_sha256']['hw/usb/sony-dwc3.c'] = '0' * 64
    elif case == 'missing-combination':
        production.pop('source_deltas_sha256')
    elif case == 'null-combination':
        production['source_deltas_sha256'] = None
    elif case == 'board-source':
        production.pop('board_source_sha256')
    elif case == 'system-dir':
        fixture.launch['env']['QEMU_SYSTEM_DIR'] += '.other'
    elif case == 'delta-hash':
        production['all_source_delta_sha256'] = '0' * 64
    elif case == 'delta-file':
        (fixture.qemu_build.parent / 'usb-device-source-delta.json').write_text('changed')
    else:
        path = fixture.qemu_build.parent / 'persistent-usb-source-delta.json'
        combined = json.loads(path.read_text())
        combined['provider_sha256'] = '0' * 64
        path.write_text(json.dumps(combined))
        production['source_deltas_sha256'][path.name] = API['COLD']['digest'](path)
        production['all_source_delta_sha256'] = production['source_deltas_sha256'][path.name]
    bind_production(fixture)
    with pytest.raises(ValueError):
        API['prepare_launch'](fixture.launch, lease='b' * 64)
    assert_not_prepared(fixture)


@pytest.mark.parametrize('changed', ('cmdline-bytes', 'cmdline-newline', 'original-script', 'new-script', 'qemu', 'other-asset', 'source-delta'))
def test_usb_prepare_rejects_unexpected_prepare_only_mutation(persistent_launch, monkeypatch, changed):
    fixture = persistent_launch
    prepare = API['subprocess'].run

    def mutate(command, **kwargs):
        result = prepare(command, **kwargs)
        if changed.startswith('cmdline'):
            path = Path(fixture.launch['cmdline_file'])
            path.write_bytes(path.read_bytes() + (b' unexpected=1' if changed == 'cmdline-bytes' else b'\n'))
        elif changed == 'original-script':
            Path(fixture.launch['script']).write_text('changed')
        elif changed == 'new-script':
            Path(command[1]).write_text('changed')
        elif changed == 'qemu':
            Path(fixture.launch['qemu_binary']).write_bytes(b'changed')
        elif changed == 'other-asset':
            (Path(fixture.launch['runtime_analysis']) / 'boot-handoff.bin').chmod(0o700)
        else:
            (fixture.qemu_build.parent / 'usb-device-source-delta.json').write_bytes(b'changed')
        return result

    monkeypatch.setattr(API['subprocess'], 'run', mutate)
    with pytest.raises(ValueError):
        API['prepare_launch'](fixture.launch, lease='b' * 64)
    assert len(fixture.prepare_calls) == 1


@pytest.mark.parametrize('changed', ('partition', 'kernel', 'new-script-mode', 'combo-receipt-mode', 'profile-source'))
def test_adapted_launch_retains_persistent_and_new_binding_guards(persistent_launch, changed):
    fixture = persistent_launch
    result = API['prepare_launch'](fixture.launch, lease='b' * 64)
    if changed == 'partition':
        with API['PERSISTENT']['DISK']['lease'](fixture.instance) as leased:
            row = result['partition_bindings'][0]
            os.pwrite(leased['fd'], b'changed', row['offset'])
            os.fdatasync(leased['fd'])
    elif changed == 'kernel':
        Path(result['actual_kernel']['path']).write_bytes(b'changed')
    elif changed == 'new-script-mode':
        Path(result['script']).chmod(0o600)
    elif changed == 'combo-receipt-mode':
        (fixture.qemu_build.parent / 'usb-device-source-delta.json').chmod(0o700)
    else:
        row = next(row for row in result['template_inputs'] if row['role'] == 'usb-device-profile-source')
        row['sha256'] = '0' * 64
    with pytest.raises(ValueError):
        with API['PERSISTENT']['leased_launch'](result):
            pytest.fail('mutated adapted launch yielded')


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, *sys.argv[1:]]))
