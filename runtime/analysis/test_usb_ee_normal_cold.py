"""Explicit EE NormalWake cold observer wiring: host build/gating only.

No VM, no disk and no private input ever enters the public tree; the enabled
build below consumes a clearly labeled synthetic host fixture, never a real
prepared private header. Nothing here proves original AP consumption.
"""
import importlib.util
import json
from pathlib import Path
import pytest
import shutil
import subprocess
import tempfile
import sony_usb_device as device

USB=Path(device.PRODUCT)/'source/usb-device'
ROOT=Path(device.PRODUCT).parents[1]
RESEARCH=ROOT/'final/a7c2-re/report/2026-10-17-qemu-full-system'

SYNTHETIC_INPUT='''/* Host-test synthetic input; never a private launch input. */
#include "ee-normal-wake-cold.h"
static const uint8_t ee_nwc_prepared_rows[128]={0};
static const struct ee_nwc_assets ee_nwc_prepared_assets={
 .pid=0,.generation=UINT64_C(7),
 .backup_sha256=EE_NWC_BACKUP_SHA,.cp_bank_sha256=EE_NWC_BANK_SHA,.cp_sha256=EE_NWC_CP_SHA,
 .cp_bank_offset=970752,.verified=1,.keymap_group=1,
 .rows=ee_nwc_prepared_rows,.rows_bytes=sizeof ee_nwc_prepared_rows,
 .backup_00030162={0},.policy_00030a01={0},.config_0092001c={0}};
static const uint8_t ee_cold_adc[48]={0};
static const uint8_t ee_cold_state[32]={0};
static const uint8_t ee_cold_force=0,ee_cold_be9=0;
static const char ee_cold_input_sha256[]="host-fixture-only";
static const char ee_cold_model_sha256[]="host-fixture-only";
#define EE_COLD_ADMISSION_SOURCE EE_NWC_CALLBACK
#define EE_COLD_DIAGNOSTICS 0
#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 1
'''


@pytest.fixture
def outside_product():
    """The build guard rejects private inputs inside the product tree; TMPDIR itself may sit inside it."""
    base=Path(tempfile.gettempdir()).resolve()
    if base==Path(device.PRODUCT) or base.is_relative_to(device.PRODUCT):base=Path('/tmp')
    scratch=Path(tempfile.mkdtemp(prefix='a7c2-ee-cold-test-',dir=base))
    yield scratch
    shutil.rmtree(scratch,ignore_errors=True)


def symbols(path,names):
    text=subprocess.run(['readelf','-Ws',str(path)],capture_output=True,text=True,check=True).stdout
    return {name for name in names if (' '+name+'\n') in text}


def test_default_off_build_links_no_ee_code(tmp_path):
    helpers=device.prepare_observer({'A7C2_SONY_USB_DEVICE':device.PROFILE},tmp_path)
    observer=helpers['usb-start-observe.so']
    assert 'usb-ee-native-pins.h' not in helpers
    image=observer.read_bytes()
    assert b'ee-normal-wake-cold-functional-v1' not in image
    assert b'native_allocation_log_commit_required=1' not in image
    assert not symbols(observer,('ee_nwc_create','ee_adc_consume','ee_cold_wait'))
    assert not list(tmp_path.glob('usb-ee-native-pins.h'))


def test_ee_cold_profile_fails_closed_without_external_private_input(tmp_path):
    header=tmp_path/'input.h';header.write_text(SYNTHETIC_INPUT)
    profile={'A7C2_SONY_USB_DEVICE':device.PROFILE}
    for current in ({**profile,'A7C2_USB_EE_NORMAL_COLD':'1'},
                    {**profile,'A7C2_USB_EE_NORMAL_COLD':'2','A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)},
                    {**profile,'A7C2_USB_EE_NORMAL_COLD':'1','A7C2_USB_EE_NORMAL_COLD_INPUT':str(tmp_path/'absent.h')}):
        with pytest.raises(ValueError):device.prepare_observer(current,tmp_path/'gate')
    # A declared input without the explicit profile and an in-tree input are both refused.
    with pytest.raises(ValueError,match='without the explicit profile'):
        device.prepare_observer({**profile,'A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)},tmp_path/'gate')
    inside=USB/'ee-cold-private-input.h'
    inside.write_text(SYNTHETIC_INPUT)
    try:
        with pytest.raises(ValueError,match='outside the public product tree'):
            device.prepare_observer({**profile,'A7C2_USB_EE_NORMAL_COLD':'1','A7C2_USB_EE_NORMAL_COLD_INPUT':str(inside)},tmp_path/'gate')
    finally:
        inside.unlink()
    header.unlink()
    header.symlink_to(inside if inside.exists() else tmp_path/'gone')
    with pytest.raises(ValueError,match='regular non-symlink'):
        device.prepare_observer({**profile,'A7C2_USB_EE_NORMAL_COLD':'1','A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)},tmp_path/'gate')


def test_ee_cold_enabled_build_binds_input_path_and_links_symbols(tmp_path,outside_product):
    header=outside_product/'input.h';header.write_text(SYNTHETIC_INPUT);header.chmod(0o600)
    payload=tmp_path/'payload';payload.mkdir(exist_ok=True)
    helpers=device.prepare_observer({'A7C2_SONY_USB_DEVICE':device.PROFILE,'A7C2_USB_EE_NORMAL_COLD':'1',
                                     'A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)},payload)
    observer=helpers['usb-start-observe.so'];pins=helpers['usb-ee-native-pins.h']
    assert observer.is_file() and pins.is_file()
    image=observer.read_bytes()
    assert b'ee-normal-wake-cold-functional-v1' in image
    assert b'native_allocation_log_commit_required=1 native_allocation_log_commit_version=1' in image
    assert image[:6]==b'\x7fELF\x02\x01' and image[18:20]==b'\xb7\x00'
    # ee_nwc_*/ee_adc_* are the linked global service entry points; the static
    # adapter helpers (e.g. ee_cold_wait) are inlined at -O2 and need no symbol.
    assert {'ee_nwc_create','ee_nwc_destroy','ee_adc_consume'} <= symbols(observer,('ee_nwc_create','ee_nwc_destroy','ee_adc_consume','ee_cold_wait'))
    # The pins header binds the actual product native forwarder, not a fixture value.
    native=device.ANALYSIS/'menu-observe.so'
    assert ('"'+device.sha(native)+'"') in pins.read_text() and 'osal_free_msg' in pins.read_text()
    # A tampered synthetic contract marker is refused before any compiler runs.
    header.write_text(SYNTHETIC_INPUT.replace('#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 1','#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 2'))
    with pytest.raises(ValueError,match='hash-bound adapter contract'):
        device.prepare_observer({'A7C2_SONY_USB_DEVICE':device.PROFILE,'A7C2_USB_EE_NORMAL_COLD':'1',
                                 'A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)},tmp_path/'refused')


def test_ee_observer_modes_are_mutually_exclusive(tmp_path):
    """clang AArch64 syntax check only; the source #error fires before any input is read."""
    result=subprocess.run(['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu','-fsyntax-only',
                           '-DUSB_EE_ZERO_OBSERVER=1','-DUSB_EE_NORMAL_COLD=1',str(USB/'usb-start-observe.c')],
                          capture_output=True,text=True)
    assert result.returncode!=0 and 'mutually exclusive' in result.stderr


def test_source_origins_records_research_lineage():
    entry=json.loads((Path(device.PRODUCT)/'SOURCE-ORIGINS.json').read_text()).get('ee_normal_cold_observer_wiring_20261110')
    if entry is None:pytest.fail('SOURCE-ORIGINS lacks the EE cold wiring entry')
    if not RESEARCH.is_dir():pytest.skip('Research tree absent in this checkout')
    files=entry['files']
    for name,record in files.items():
        origin=ROOT/record['source']
        assert origin.is_file() and device.sha(origin)==record['original_sha256']
        product=USB/name
        assert product.is_file() and device.sha(product)==record['sha256']
        assert record.get('adapted') or device.sha(product)==record['original_sha256']
    assert entry['profile']==device.EE_COLD_MODE
    assert entry['default_off'] is True and entry['private_inputs_in_public_tree'] is False
    assert entry['original_ap_consumption_verified'] is False
