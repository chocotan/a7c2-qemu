#!/usr/bin/env python3
"""Run a bounded camera-application probe in the isolated Sony-kernel VM."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import runpy
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import signal
import sys
from contextlib import nullcontext
from gpe_captures import raster_sources
from headless_osd_capture import capture as capture_headless_osd
from initramfs_identity import verify_image
from language_fonts import FONT_GUEST, FONT_SPECS
from backup_profile import (ADF_PROFILE, INPUT_PROFILE, OUTPUT_PROFILE, BB_SET_MODE_PROFILE,
                            IMAGING_CONNECT_PROFILE, IMAGING_CONTROL_CONNECT_PROFILE, IMAGING_ADF_CONNECT_PROFILE,
                            INFRABB_VEF_CONNECT_PROFILE, FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE,
                            FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE, FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE,
                            FULL_PINMEM_PEER_CONNECTIONS_PROFILE, FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE,
                            FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE, FULL_PINMEM_OSD_CONNECTION_PROFILE,
                            FULL_CP302C_NO_TRANSITION_PROFILE, FULL_CP302C_DIAGNOSTIC_PROFILE,
                            FULL_CP_NOTIFICATION_CONTROL_PROFILE, FULL_CP_CAPTURE_FORMAT_PROFILE, FULL_CP_STARTUP_DIAGNOSTIC_PROFILE, FULL_CP_EE_DIAGNOSTIC_PROFILE, FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE, FULL_CP_OWNED_STATE_PROFILE,
                            FUNCTIONAL_CAMERA_PROFILE,
                            ADF_CONFLICTS, BB_MODE_CONFLICTS, adf_proc_profile_fields,
                            adf_set_input_profile_fields, adf_set_output_profile_fields,
                            bb_set_mode_profile_fields, imaging_pin_connection_profile_fields,
                            imaging_control_connection_profile_fields, imaging_adf_connection_profile_fields,
                            infrabb_vef_connection_profile_fields, infrabb_vef_control_connection_profile_fields,
                            vef_pinmem_input_connection_profile_fields, vef_pinmem_control_connection_profile_fields,
                            pinmem_peer_connections_profile_fields, adf_hdmi_audio_connection_profile_fields,
                            pinmem_hdmi_video_connection_profile_fields, pinmem_osd_connection_profile_fields,
                            cp302c_no_transition_profile_fields, cp302c_diagnostic_profile_fields,
                            cp_notification_control_profile_fields, cp_capture_format_profile_fields,
                            functional_camera_profile_fields)

def diagnostic_done(console, marker):
    clean = console.replace(b'\r\n', b'\n')
    clean = re.sub(rb'\[\s*\d+\.\d+\] (?:UDIF:|\[K\])[^\n]*\n', b'', clean)
    return b'\n' + marker.encode() + b'\n' in clean

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--load-ipc", action="store_true", help="load original IPC kernel modules")
parser.add_argument("--bootin", action="store_true", help="use the normal boot manager")
parser.add_argument("--bootall", action="store_true", help="request all im.elf startup phases")
parser.add_argument("--seed-backup", action="store_true", help="load update defaults into the guest Backup driver")
parser.add_argument("--load-dmm", action="store_true", help="load original shared-memory manager")
parser.add_argument("--menu-target", action="store_true", help="use the copied qemu registry with ten filtered services, including media power")
parser.add_argument("--sony-timers", action="store_true", help="use the custom QEMU timer model")
parser.add_argument("--observe", action="store_true", help="log library loads and use ordinary test thread scheduling")
parser.add_argument("--load-power", action="store_true", help="attempt original power-management driver initialization")
parser.add_argument("--initramfs", action="store_true", help="use raw cpio test root and original workspace reservations")
parser.add_argument("--initramfs-file", type=Path, help="select a separately generated cpio experiment")
parser.add_argument("--no-cp-updater", action="store_true", help="report unavailable virtual CP updater transport as an error")
parser.add_argument("--load-kikilog", action="store_true", help="load the original KikiLog driver before its userspace library")
parser.add_argument("--seed-power-on", action="store_true", help="prepare the virtual loader boot-type record using native Backup API")
parser.add_argument("--transport-errors", action="store_true", help="negative control: copied IPC module returns -1021 when the public transport callback is absent")
parser.add_argument("--capid-service", action="store_true", help="emulate capture-ID table storage and its verified CP protocols; image capture remains unavailable")
parser.add_argument("--sa-address-service", action="store_true", help="apply the original av-cam SA address mappings in the virtual transport")
parser.add_argument("--hdmi-format-service", action="store_true", help="emulate the verified HDMI audio format parameter and completion, without physical audio output")
parser.add_argument("--hdmi-photo-service", action="store_true", help="emulate premium-photo parameter and desired output preset 6, without a physical HDMI link")
parser.add_argument("--dmm-service", action="store_true", help="reserve a virtual CP pool for the verified 0x63a DMM unit lifecycle")
parser.add_argument("--software-gpe", action="store_true", help="execute verified uniform fills in real bitmap memory; other raster operations remain unsupported")
parser.add_argument("--headless-osd", action="store_true", default=os.environ.get('MENU_HEADLESS_OSD') == '1',
                    help="consume AP RGBA4444 frames to bounded guest snapshots; no CP compositor/panel (default off)")
parser.add_argument("--native-display", choices=('none', 'gtk', 'sdl'),
                    default=os.environ.get('QEMU_NATIVE_DISPLAY', 'none') if os.environ.get('MENU_NATIVE_WINDOW') == '1' else None,
                    help="enable standard ramfb and guest snapshot bridge (none permits QMP screendump)")
parser.add_argument("--firmware-identity", action="store_true", help="supply verified selected-FDAT identity files on virtual RAM storage; no real base-updater partition")
parser.add_argument("--display-info-service", action="store_true", help="return the verified panel/EVF info protocol for explicitly configured 640x480 virtual displays")
args = parser.parse_args()
input_key_mode = os.environ.get('MENU_INJECT_KEY', '')
live_key_file = os.environ.get('MENU_LIVE_KEY_FILE')
if live_key_file not in (None, '', '/tmp/menu-key.request'):
    parser.error('MENU_LIVE_KEY_FILE must be /tmp/menu-key.request or unset')
dig_level_mode = os.environ.get('MENU_DIG_LEVEL', '')
panel_reverse_mode = os.environ.get('MENU_PANEL_REVERSE', '')
if panel_reverse_mode not in ('', 'virtual'):
    parser.error('MENU_PANEL_REVERSE must be virtual or unset')
if panel_reverse_mode and (not args.observe or any(os.environ.get(name) for name in
        ('MENU_HONEST_ROUTING', 'MENU_ASYNC_SEND', 'MENU_PIPELINE_VIRT'))):
    parser.error('MENU_PANEL_REVERSE requires --observe without experimental send-GOT hooks')
if dig_level_mode not in ('', 'virtual'):
    parser.error('MENU_DIG_LEVEL must be virtual or unset')
if dig_level_mode and (not args.observe or any(os.environ.get(name) for name in
        ('MENU_HONEST_ROUTING', 'MENU_ASYNC_SEND', 'MENU_PIPELINE_VIRT'))):
    parser.error('MENU_DIG_LEVEL requires --observe without experimental send-GOT hooks')
if os.environ.get('MENU_SEQ4BD_CREATE'):
    parser.error('MENU_SEQ4BD_CREATE is retired: the NULL-payload constructor call is invalid')
if os.environ.get('MENU_CP_EMULATION'):
    parser.error('MENU_CP_EMULATION is retired: generic ACKs and 0x1118 frame notifications violate the original protocol')
if os.environ.get('MENU_LIVEVIEW_TRACE', '') not in ('', '1'):
    parser.error('MENU_LIVEVIEW_TRACE must be 1 or unset')
if os.environ.get('MENU_LIVEVIEW_TRACE') and not (args.initramfs and args.observe):
    parser.error('MENU_LIVEVIEW_TRACE requires --initramfs --observe')
if os.environ.get('MENU_JPEG_REQUEST_TRACE', '') not in ('', '1'):
    parser.error('MENU_JPEG_REQUEST_TRACE must be 1 or unset')
if os.environ.get('MENU_JPEG_REQUEST_TRACE') and not (args.initramfs and args.observe):
    parser.error('MENU_JPEG_REQUEST_TRACE requires --initramfs --observe')
if os.environ.get('MENU_INPUT_ROUTE_TRACE', '') not in ('', '1'):
    parser.error('MENU_INPUT_ROUTE_TRACE must be 1 or unset')
if os.environ.get('MENU_INPUT_ROUTE_TRACE') and not (args.initramfs and args.observe):
    parser.error('MENU_INPUT_ROUTE_TRACE requires --initramfs --observe')
input_route_detail = os.environ.get('A7C2_INPUT_ROUTE_DETAIL', '')
if input_route_detail not in ('', '1', 'canonical', 'target', 'handlers', 'flow'):
    parser.error('A7C2_INPUT_ROUTE_DETAIL must be 1, canonical, target, handlers, flow or unset')
if input_route_detail and os.environ.get('MENU_INPUT_ROUTE_TRACE') != '1':
    parser.error('A7C2_INPUT_ROUTE_DETAIL requires MENU_INPUT_ROUTE_TRACE=1')
if input_route_detail and not (args.initramfs and args.observe):
    parser.error('A7C2_INPUT_ROUTE_DETAIL requires --initramfs --observe')
if os.environ.get('A7C2_FSYS_ASYNC_OBSERVE', '') not in ('', '1'):
    parser.error('A7C2_FSYS_ASYNC_OBSERVE must be 1 or unset')
if os.environ.get('MENU_DISPLAY_SETUP_REQUEST'):
    parser.error('MENU_DISPLAY_SETUP_REQUEST is unnecessary: original display_setup runs naturally; use MENU_LIVEVIEW_TRACE=1')
yc_inject = os.environ.get('MENU_YC_INJECT', '')
yc_uncompressed = os.environ.get('MENU_YC_UNCOMPRESSED', '')
if yc_uncompressed not in ('', '1'):
    parser.error('MENU_YC_UNCOMPRESSED must be 1 or unset')
if yc_uncompressed and (yc_inject != '1' or any(os.environ.get(name) for name in
        ('MENU_YC_INPUT_PNG','MENU_YC_INPUT_RAW','A7C2_PREVIEW_PNG'))):
    parser.error('MENU_YC_UNCOMPRESSED requires YC injection without PNG/raw input')
yc_ownership_observe = os.environ.get('A7C2_YC_OWNERSHIP_OBSERVE', '')
if yc_ownership_observe not in ('', '1'):
    parser.error('A7C2_YC_OWNERSHIP_OBSERVE must be 1 or unset')
if yc_ownership_observe and not yc_uncompressed:
    parser.error('A7C2_YC_OWNERSHIP_OBSERVE requires the uncompressed diagnostic source')
yc_survey = os.environ.get('MENU_YC_SURVEY', '')
if yc_survey not in ('', '1'):
    parser.error('MENU_YC_SURVEY must be 1 or unset')
if yc_survey == '1' and not (args.initramfs and args.load_ipc and args.load_dmm):
    parser.error('MENU_YC_SURVEY requires --initramfs --load-ipc --load-dmm (original dmm.ko)')
if yc_survey == '1' and yc_inject == '1':
    parser.error('MENU_YC_SURVEY and MENU_YC_INJECT are mutually exclusive')
vpanel = os.environ.get('MENU_VPANEL', '')
if vpanel not in ('', '1'):
    parser.error('MENU_VPANEL must be 1 or unset')
if vpanel == '1' and not (args.initramfs and args.load_ipc):
    parser.error('MENU_VPANEL requires --initramfs --load-ipc')
if yc_inject not in ('', '1'):
    parser.error('MENU_YC_INJECT must be 1 or unset')
yc_inject_delay = os.environ.get('MENU_YC_INJECT_DELAY', '120')
if yc_inject == '1':
    try:
        yc_inject_delay = int(yc_inject_delay)
    except ValueError:
        parser.error('MENU_YC_INJECT_DELAY must be an integer seconds value')
    if not 0 <= yc_inject_delay <= 600:
        parser.error('MENU_YC_INJECT_DELAY must be within 0..600')
    if not (args.initramfs and args.load_ipc and args.load_dmm):
        parser.error('MENU_YC_INJECT requires --initramfs --load-ipc --load-dmm (original dmm.ko)')
if input_key_mode not in ('', 'press', 'pressrelease','confirm-pressrelease','language-pressrelease','auto-firstboot'):
    parser.error('MENU_INJECT_KEY must be press, pressrelease, confirm-pressrelease, language-pressrelease or auto-firstboot')
for setting in ('MENU_VDF_CONFIG', 'MENU_HDMI_BOOT_CONFIG', 'MENU_AUDIO_BOOT_CONFIG', 'MENU_DMM_UNIT_CONFIG', 'MENU_PIN_REGISTRY',
                'MENU_PIN_CONTROL_MEMORY', 'MENU_PIN_BUFFER_SELFTEST','MENU_RM_FILE'):
    if os.environ.get(setting, '') not in ('', '1'):
        parser.error(f'{setting} must be 1 or unset')
    if setting in ('MENU_VDF_CONFIG', 'MENU_HDMI_BOOT_CONFIG', 'MENU_AUDIO_BOOT_CONFIG', 'MENU_DMM_UNIT_CONFIG', 'MENU_PIN_REGISTRY','MENU_RM_FILE') and os.environ.get(setting) == '1' and any(os.environ.get(name) for name in
            ('MENU_HONEST_ROUTING', 'MENU_ASYNC_SEND', 'MENU_PIPELINE_VIRT')):
        parser.error(f'{setting} cannot share the experimental send-GOT hooks')
if os.environ.get('MENU_NATURAL_START_TRACE', '') not in ('', '1'):
    parser.error('MENU_NATURAL_START_TRACE must be 1 or unset')
if os.environ.get('MENU_NATURAL_START_TRACE') and not (args.initramfs and args.observe):
    parser.error('MENU_NATURAL_START_TRACE requires --initramfs --observe')
if os.environ.get('MENU_RUN_I_GATE') and not os.environ.get('MENU_ENTRY_PROBES'):
    parser.error('MENU_RUN_I_GATE requires MENU_ENTRY_PROBES')
pin_control_memory = os.environ.get('MENU_PIN_CONTROL_MEMORY') == '1'
rm_file = os.environ.get('MENU_RM_FILE')=='1'
sd_sparse=os.environ.get('A7C2_SD_SPARSE','')
if sd_sparse not in ('','10g-empty'):
    parser.error('A7C2_SD_SPARSE must be 10g-empty or unset')
if sd_sparse and (not rm_file or not args.initramfs or not args.observe or
                  os.environ.get('A7C2_SD_IMAGE') or os.environ.get('A7C2_SD_HOTPLUG')):
    parser.error('Sparse SD requires original RM file backend/initramfs/observer, without a seed or hotplug')
# Single physical slot: report the one virtual card on logical RM1 instead of RM2.
rm_slot1 = os.environ.get('MENU_RM_SLOT1')=='1'
virtual_hci=os.environ.get('A7C2_VIRTUAL_HCI','')
queue_debug_option=os.environ.get('A7C2_QUEUE_WATCH','')
if queue_debug_option not in ('','0','1'):parser.error('A7C2_QUEUE_WATCH must be 0/1 or unset')
resize_mmio_watch=os.environ.get('A7C2_RESIZE_WATCH','')
if resize_mmio_watch not in ('','0','1'):parser.error('A7C2_RESIZE_WATCH must be 0/1 or unset')
resize_mmio_watch=resize_mmio_watch=='1'
media_predicate_observe=os.environ.get('A7C2_MEDIA_PREDICATE_WATCH','')
if media_predicate_observe not in ('','0','1'):parser.error('A7C2_MEDIA_PREDICATE_WATCH must be 0/1 or unset')
media_predicate_observe=media_predicate_observe=='1'
media_init_watch=os.environ.get('A7C2_MEDIA_INIT_WATCH','')
if media_init_watch not in ('','0','1'):parser.error('A7C2_MEDIA_INIT_WATCH must be 0/1 or unset')
media_init_watch=media_init_watch=='1'
if media_init_watch and (media_predicate_observe or queue_debug_option=='1'):
    parser.error('Pre-init media observation requires an isolated debug mode')
if media_predicate_observe and queue_debug_option=='1':
    parser.error('Media predicate and queue observation modes are mutually exclusive')
if resize_mmio_watch and (queue_debug_option=='1' or media_predicate_observe or media_init_watch or yc_inject!='1'):
    parser.error('Resize watch requires an isolated YC injection debug mode')
request_queue_gdb=queue_debug_option=='1' or media_predicate_observe or media_init_watch or resize_mmio_watch
if resize_mmio_watch and (not args.initramfs or not args.observe or os.environ.get('QEMU_SONY_PCIDMA') != '1'):
    parser.error('Resize watch requires a verified initramfs/observer and the isolated PCI DMA model')
if yc_uncompressed and not resize_mmio_watch:
    parser.error('MENU_YC_UNCOMPRESSED requires A7C2_RESIZE_WATCH=1 for original format verification')
if request_queue_gdb and not resize_mmio_watch and (not args.initramfs or not args.observe or args.native_display is None or
        not os.environ.get('MENU_CONTROL_FD') or
        any(os.environ.get(name)!='1' for name in
            (() if resize_mmio_watch else ('A7C2_MODE_READBACK',) if media_predicate_observe or media_init_watch else
             ('A7C2_CAPTURE_POWER','A7C2_TEST_APO_CANCEL','A7C2_MODE_READBACK')))):
    parser.error('Queue watch requires owned native live original-power/readback experiment')
if os.environ.get('A7C2_TEST_APO_CANCEL')=='1' and os.environ.get('A7C2_CAPTURE_POWER')!='1':
    parser.error('APO cancellation request probe requires original power observation')
if virtual_hci not in ('','virtual-rom-v1'):
    parser.error('A7C2_VIRTUAL_HCI must be virtual-rom-v1 or unset')
if virtual_hci and not (args.initramfs and args.observe):
    parser.error('Virtual HCI requires --initramfs --observe')
gui_models = os.environ.get('MENU_GUI_MODELS','')
cp_background=os.environ.get('MENU_CP_BACKGROUND','')
if cp_background not in ('','virtual-mode3-cold-v1'):
    parser.error('MENU_CP_BACKGROUND must be virtual-mode3-cold-v1 or unset')
if cp_background and (not args.initramfs or not args.observe or any(os.environ.get(name) for name in
        ('MENU_HONEST_ROUTING','MENU_ASYNC_SEND','MENU_PIPELINE_VIRT'))):
    parser.error('MENU_CP_BACKGROUND requires initramfs/observe and no experimental send-GOT hooks')
udate_distribution=os.environ.get('MENU_UDATE_DISTRIBUTION','')
if udate_distribution not in ('','virtual-roundtrip-v1'):
    parser.error('MENU_UDATE_DISTRIBUTION must be virtual-roundtrip-v1 or unset')
if udate_distribution and (not args.initramfs or not args.observe or
                           cp_background!='virtual-mode3-cold-v1' or
                           any(os.environ.get(name) for name in
                               ('MENU_HONEST_ROUTING','MENU_ASYNC_SEND','MENU_PIPELINE_VIRT'))):
    parser.error('MENU_UDATE_DISTRIBUTION requires CP3007, initramfs/observe and no experimental send-GOT hooks')
udate_kernel_module=Path(__file__).resolve().parent/'menu-root/simulation/sony_udate_distribution.ko'
udate_kernel_receipt=Path(__file__).resolve().parent/'../../report/virtual-cp/udate-distribution/verification.json'
if udate_distribution and (not udate_kernel_module.is_file() or not udate_kernel_receipt.is_file()):
    parser.error('MENU_UDATE_DISTRIBUTION requires build-observers.sh and the kernel ABI receipt')
if udate_distribution and any(os.environ.get(name)=='1' for name in
                              ('MENU_VPANEL','MENU_VIRTUAL_CP_SENDER','MENU_PCIE_IF')):
    parser.error('MENU_UDATE_DISTRIBUTION conflicts with the selected public sender owner')
touch_panel=os.environ.get('MENU_TOUCH_PANEL','')
if touch_panel not in ('','virtual-config-v1'):
    parser.error('MENU_TOUCH_PANEL must be virtual-config-v1 or unset')
if touch_panel and (not args.initramfs or not args.observe or
                    cp_background!='virtual-mode3-cold-v1' or
                    udate_distribution!='virtual-roundtrip-v1' or
                    any(os.environ.get(name) for name in
                        ('MENU_HONEST_ROUTING','MENU_ASYNC_SEND','MENU_PIPELINE_VIRT','MENU_PIPELINE_ENDPOINT'))):
    parser.error('MENU_TOUCH_PANEL requires CP3007+UDATE, initramfs/observe and no experimental send hooks')
backup_sync=os.environ.get('MENU_BACKUP_SYNC','')
if backup_sync not in ('','virtual-primary-v1'):
    parser.error('MENU_BACKUP_SYNC must be virtual-primary-v1 or unset')
if backup_sync and (touch_panel!='virtual-config-v1' or not args.load_ipc or not args.seed_backup or
        os.environ.get('A7C2_DIRECTORY_SD_PROFILE')!='directory-vvfat-256gb-v1' or
        os.environ.get('QEMU_SONY_PCIDMA')!='1' or os.environ.get('MENU_PCIDMA_XFER')=='1'):
    parser.error('Backup requires the guarded native directory profile and no diagnostic pattern DMA')
tcin_detect=os.environ.get('MENU_TCIN_DETECT','')
if tcin_detect not in ('','virtual-inactive-v1') or (tcin_detect and backup_sync!='virtual-primary-v1'):
    parser.error('TCIN inactive configuration requires the explicit guarded Backup profile')
dfs_selector=os.environ.get('MENU_DFS_SELECTOR','')
if dfs_selector not in ('','virtual-selector-v1') or (dfs_selector and tcin_detect!='virtual-inactive-v1'):
    parser.error('DFS selector requires the explicit TCIN inactive profile')
vef_path_profile=os.environ.get('MENU_VEF_PATH','')
if vef_path_profile not in ('','virtual-nomem-v1') or (vef_path_profile and (
        dfs_selector!='virtual-selector-v1' or not args.dmm_service or
        any(os.environ.get(name)!=value for name,value in (
            ('MENU_PIN_REGISTRY','1'),('MENU_PIN_CONTROL_MEMORY','1'),('MENU_PIN_CONNECTION','cold'))) or
        any(os.environ.get(name) for name in (
            'MENU_YC_INJECT','MENU_YC_UNCOMPRESSED','MENU_PIPELINE_ENDPOINT','MENU_PIPELINE_VIRT',
            'MENU_BB_READY_INJECT','MENU_BB_READY_LATE','MENU_ACTIVATE_MODE','MENU_ACTIVATE_CAPTURED',
            'MENU_CTOR_CENSUS','MENU_OPEN_SET','MENU_FORCE_SET','MENU_BUILD_CONTROLLER',
            'MENU_BUILD_CONTROLLER2','MENU_MENU_INIT','MENU_OPEN_SCREEN')))):
    parser.error('VEF NoMem requires the guarded DFS/native resource profile without frame or ready injection')
adf_proc_path_profile=os.environ.get('MENU_ADF_PROC_PATH','')
if adf_proc_path_profile not in ('',ADF_PROFILE) or (adf_proc_path_profile and (
        vef_path_profile!='virtual-nomem-v1' or not args.sony_timers or args.native_display is None or
        os.environ.get('MENU_AUDIO_BOOT_CONFIG')!='1' or os.environ.get('SEED_BACKUP')!='alllang' or
        any(os.environ.get(name) for name in ADF_CONFLICTS))):
    parser.error('ADF source7 Idle requires guarded VEF NoMem/native timers/public ALLLANG without frame or ready injection')
adf_set_input_profile=os.environ.get('MENU_ADF_SET_INPUT','')
if adf_set_input_profile not in ('',INPUT_PROFILE) or (adf_set_input_profile and
        adf_proc_path_profile!=ADF_PROFILE):
    parser.error('ADF set input requires the explicit guarded ADF source7 Idle profile')
adf_set_output_profile=os.environ.get('MENU_ADF_SET_OUTPUT','')
if adf_set_output_profile not in ('',OUTPUT_PROFILE) or (adf_set_output_profile and (
        adf_set_input_profile!=INPUT_PROFILE or (os.environ.get('MENU_USB_NET') and
        os.environ.get('A7C2_DIRECTORY_SD_PROFILE')!='directory-vvfat-256gb-v1'))):
    parser.error('ADF set output requires the explicit guarded ADF set input and directory SD profiles')
bb_set_mode_profile=os.environ.get('MENU_BB_SET_MODE','')
font_option=os.environ.get('MENU_LANGUAGE_FONTS','')
if font_option not in ('','0','1'):
    parser.error('MENU_LANGUAGE_FONTS must be 0, 1 or unset')
language_fonts=font_option=='1'
if language_fonts and not args.initramfs:
    parser.error('MENU_LANGUAGE_FONTS requires --initramfs')
if bb_set_mode_profile not in ('',BB_SET_MODE_PROFILE) or (bb_set_mode_profile and (
        os.environ.get('A7C2_BB_SET_MODE')!=BB_SET_MODE_PROFILE or
        backup_sync!='virtual-primary-v1' or cp_background!='virtual-mode3-cold-v1' or
        udate_distribution!='virtual-roundtrip-v1' or touch_panel!='virtual-config-v1' or
        tcin_detect!='virtual-inactive-v1' or dfs_selector!='virtual-selector-v1' or
        vef_path_profile!='virtual-nomem-v1' or adf_proc_path_profile!=ADF_PROFILE or
        adf_set_input_profile!=INPUT_PROFILE or adf_set_output_profile!=OUTPUT_PROFILE or
        os.environ.get('SEED_BACKUP')!='alllang' or
        os.environ.get('A7C2_DIRECTORY_SD_PROFILE')!='directory-vvfat-256gb-v1' or
        not args.initramfs or not args.observe or not args.load_ipc or not args.seed_backup or
        not args.load_dmm or not args.dmm_service or not args.sony_timers or args.native_display is None or
        os.environ.get('QEMU_CPU_COUNT','1')!='1' or
        any(os.environ.get(name) for name in BB_MODE_CONFLICTS))):
    parser.error('BB set mode requires the complete public Backup/ADF directory profile without imaging or injection')
imaging_pin_connection_profile=os.environ.get('MENU_IMAGING_CONNECT','')
if imaging_pin_connection_profile not in ('',IMAGING_CONNECT_PROFILE) or (imaging_pin_connection_profile and (
        os.environ.get('A7C2_IMAGING_CONNECT')!=IMAGING_CONNECT_PROFILE or
        bb_set_mode_profile!=BB_SET_MODE_PROFILE or any(os.environ.get(name)!=value for name,value in (
            ('MENU_PIN_REGISTRY','1'),('MENU_PIN_CONTROL_MEMORY','1'),('MENU_PIN_CONNECTION','cold'))))):
    parser.error('Imaging connection requires the exact guarded BB set mode and pin profiles')
imaging_control_connection_profile=os.environ.get('MENU_IMAGING_CONTROL_CONNECT','')
if imaging_control_connection_profile not in ('',IMAGING_CONTROL_CONNECT_PROFILE) or (imaging_control_connection_profile and (
        os.environ.get('A7C2_IMAGING_CONTROL_CONNECT')!=IMAGING_CONTROL_CONNECT_PROFILE or
        imaging_pin_connection_profile!=IMAGING_CONNECT_PROFILE)):
    parser.error('Imaging control connection requires the exact guarded first imaging connection profile')
imaging_adf_connection_profile=os.environ.get('MENU_IMAGING_ADF_CONNECT','')
if imaging_adf_connection_profile not in ('',IMAGING_ADF_CONNECT_PROFILE) or (imaging_adf_connection_profile and (
        os.environ.get('A7C2_IMAGING_ADF_CONNECT')!=IMAGING_ADF_CONNECT_PROFILE or
        imaging_control_connection_profile!=IMAGING_CONTROL_CONNECT_PROFILE)):
    parser.error('Imaging ADF connection requires the exact guarded second imaging control connection profile')
infrabb_vef_connection_profile=os.environ.get('MENU_INFRABB_VEF_CONNECT','')
if infrabb_vef_connection_profile not in ('',INFRABB_VEF_CONNECT_PROFILE) or (infrabb_vef_connection_profile and (
        os.environ.get('A7C2_INFRABB_VEF_CONNECT')!=INFRABB_VEF_CONNECT_PROFILE or
        imaging_adf_connection_profile!=IMAGING_ADF_CONNECT_PROFILE)):
    parser.error('InfraBB VEF connection requires the exact guarded third imaging ADF connection profile')
infrabb_vef_control_connection_profile=os.environ.get('MENU_INFRABB_VEF_CONTROL_CONNECT','')
if infrabb_vef_control_connection_profile not in ('',FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE) or (infrabb_vef_control_connection_profile and (
        os.environ.get('A7C2_INFRABB_VEF_CONTROL_CONNECT')!=FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE or
        infrabb_vef_connection_profile!=INFRABB_VEF_CONNECT_PROFILE)):
    parser.error('InfraBB VEF control connection requires the exact guarded fourth InfraBB VEF connection profile')
vef_pinmem_input_connection_profile=os.environ.get('MENU_VEF_PINMEM_INPUT_CONNECT','')
if vef_pinmem_input_connection_profile not in ('',FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE) or (vef_pinmem_input_connection_profile and (
        os.environ.get('A7C2_VEF_PINMEM_INPUT_CONNECT')!=FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE or
        infrabb_vef_control_connection_profile!=FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE)):
    parser.error('VEF PinMem input connection requires the exact guarded fifth InfraBB VEF control connection profile')
vef_pinmem_control_connection_profile=os.environ.get('MENU_VEF_PINMEM_CONTROL_CONNECT','')
if vef_pinmem_control_connection_profile not in ('',FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE) or (vef_pinmem_control_connection_profile and (
        os.environ.get('A7C2_VEF_PINMEM_CONTROL_CONNECT')!=FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE or
        vef_pinmem_input_connection_profile!=FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE)):
    parser.error('VEF PinMem control connection requires the exact guarded sixth VEF PinMem input connection profile')
pinmem_peer_connections_profile=os.environ.get('MENU_PINMEM_PEER_CONNECT','')
if pinmem_peer_connections_profile not in ('',FULL_PINMEM_PEER_CONNECTIONS_PROFILE) or (pinmem_peer_connections_profile and (
        os.environ.get('A7C2_PINMEM_PEER_CONNECT')!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE or
        vef_pinmem_control_connection_profile!=FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE)):
    parser.error('PinMem peer connections require the exact guarded seventh VEF PinMem control connection profile')
pinmem_hdmi_video_connection_profile=os.environ.get('MENU_PINMEM_HDMI_VIDEO_CONNECT','')
if pinmem_hdmi_video_connection_profile not in ('',FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE) or (pinmem_hdmi_video_connection_profile and (
        os.environ.get('A7C2_PINMEM_HDMI_VIDEO_CONNECT')!=FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE or
        pinmem_peer_connections_profile!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE)):
    parser.error('PinMem HDMI video connection requires the exact guarded PinMem peer connection chain')
pinmem_osd_connection_profile=os.environ.get('MENU_PINMEM_OSD_CONNECT','')
if pinmem_osd_connection_profile not in ('',FULL_PINMEM_OSD_CONNECTION_PROFILE) or (pinmem_osd_connection_profile and (
        os.environ.get('A7C2_PINMEM_OSD_CONNECT')!=FULL_PINMEM_OSD_CONNECTION_PROFILE or
        pinmem_peer_connections_profile!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE)):
    parser.error('PinMem OSD connection requires the exact guarded PinMem peer connection chain')
adf_hdmi_audio_connection_profile=os.environ.get('MENU_ADF_HDMI_AUDIO_CONNECT','')
if adf_hdmi_audio_connection_profile not in ('',FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE) or (adf_hdmi_audio_connection_profile and (
        os.environ.get('A7C2_ADF_HDMI_AUDIO_CONNECT')!=FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE or
        pinmem_peer_connections_profile!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE)):
    parser.error('ADF HDMI audio connection requires the exact guarded PinMem peer connection chain')
cp302c_no_transition_profile=os.environ.get('MENU_CP302C_NO_TRANSITION','')
if (cp302c_no_transition_profile not in ('',FULL_CP302C_NO_TRANSITION_PROFILE) or
        os.environ.get('A7C2_CP302C_NO_TRANSITION','')!=cp302c_no_transition_profile or (cp302c_no_transition_profile and (
        pinmem_hdmi_video_connection_profile!=FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE or
        pinmem_osd_connection_profile!=FULL_PINMEM_OSD_CONNECTION_PROFILE or
        adf_hdmi_audio_connection_profile!=FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE or
        cp_background!='virtual-mode3-cold-v1'))):
    parser.error('CP302c NO-TRANSITION requires the exact guarded full 13-connection chain and CP3007 profile')
cp302c_diagnostic_profile=os.environ.get('MENU_CP302C_DIAGNOSTIC','')
if (cp302c_diagnostic_profile not in ('',FULL_CP302C_DIAGNOSTIC_PROFILE) or
        os.environ.get('A7C2_CP302C_DIAGNOSTIC','')!=cp302c_diagnostic_profile or (cp302c_diagnostic_profile and (
        os.environ.get('MENU_CP302C_NO_TRANSITION') or os.environ.get('A7C2_CP302C_NO_TRANSITION') or
        pinmem_hdmi_video_connection_profile!=FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE or
        pinmem_osd_connection_profile!=FULL_PINMEM_OSD_CONNECTION_PROFILE or
        adf_hdmi_audio_connection_profile!=FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE or
        cp_background!='virtual-mode3-cold-v1'))):
    parser.error('CP302c diagnostic requires the exact guarded full 13-connection chain and CP3007 profile, exclusive of NO-TRANSITION')
cp_notification_control_profile=os.environ.get('MENU_CP_NOTIFICATION_CONTROL','')
if (cp_notification_control_profile not in ('',FULL_CP_NOTIFICATION_CONTROL_PROFILE) or
        os.environ.get('A7C2_CP_NOTIFICATION_CONTROL','')!=cp_notification_control_profile or
        (cp_notification_control_profile and cp302c_diagnostic_profile!=FULL_CP302C_DIAGNOSTIC_PROFILE)):
    parser.error('CP notification control requires the exact paired mode0 profile and guarded CP302c diagnostic predecessor')
cp_capture_format_profile=os.environ.get('MENU_CP_CAPTURE_FORMAT','')
if (cp_capture_format_profile not in ('',FULL_CP_CAPTURE_FORMAT_PROFILE,FULL_CP_STARTUP_DIAGNOSTIC_PROFILE,FULL_CP_EE_DIAGNOSTIC_PROFILE,FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE,FULL_CP_OWNED_STATE_PROFILE) or
        os.environ.get('A7C2_CP_CAPTURE_FORMAT','')!=cp_capture_format_profile or
        (cp_capture_format_profile and cp_notification_control_profile!=FULL_CP_NOTIFICATION_CONTROL_PROFILE)):
    parser.error('CP capture format requires the exact paired profile and guarded CP notification mode0 predecessor')
functional_camera_profile = os.environ.get('MENU_FUNCTIONAL_CAMERA', '')
if (functional_camera_profile not in ('', FUNCTIONAL_CAMERA_PROFILE) or
        os.environ.get('A7C2_FUNCTIONAL_CAMERA', '') != functional_camera_profile or
        (functional_camera_profile and cp_capture_format_profile != FULL_CP_OWNED_STATE_PROFILE)):
    parser.error('Functional camera requires the exact paired profile and owned-state full-connection predecessor')
if gui_models not in ('','virtual-inline-v1'):
    parser.error('MENU_GUI_MODELS must be virtual-inline-v1 or unset')
if gui_models and (os.environ.get('MENU_HEADLESS_OSD')!='1' or not args.observe or not args.initramfs):
    parser.error('MENU_GUI_MODELS requires --initramfs --observe and MENU_HEADLESS_OSD=1')
if rm_file and (not (args.initramfs and args.observe) or os.environ.get('MENU_MEDIA_SELFTEST')=='1'):
    parser.error('MENU_RM_FILE requires --initramfs --observe and cannot run with MENU_MEDIA_SELFTEST')
if os.environ.get('A7C2_FSYS_ASYNC_OBSERVE')=='1' and not rm_file:
    parser.error('A7C2_FSYS_ASYNC_OBSERVE requires MENU_RM_FILE=1')
dmm_unit_config = os.environ.get('MENU_DMM_UNIT_CONFIG') == '1'
if dmm_unit_config and not (args.initramfs and args.observe):
    parser.error('MENU_DMM_UNIT_CONFIG requires --initramfs --observe')
audio_boot_config = os.environ.get('MENU_AUDIO_BOOT_CONFIG') == '1'
if audio_boot_config and not (args.initramfs and args.sony_timers and args.observe):
    parser.error('MENU_AUDIO_BOOT_CONFIG requires --initramfs --sony-timers --observe')
pin_buffer_selftest = os.environ.get('MENU_PIN_BUFFER_SELFTEST') == '1'
pin_connection_mode = os.environ.get('MENU_PIN_CONNECTION', '')
if pin_connection_mode not in ('', 'cold'):
    parser.error('MENU_PIN_CONNECTION must be cold or unset')
if pin_control_memory and not (args.initramfs and args.sony_timers):
    parser.error('MENU_PIN_CONTROL_MEMORY requires --initramfs --sony-timers')
if pin_buffer_selftest and not pin_control_memory:
    parser.error('MENU_PIN_BUFFER_SELFTEST requires MENU_PIN_CONTROL_MEMORY')
if pin_connection_mode and (not pin_control_memory or os.environ.get('MENU_PIN_REGISTRY') != '1'):
    parser.error('MENU_PIN_CONNECTION requires MENU_PIN_CONTROL_MEMORY and MENU_PIN_REGISTRY')
if pin_connection_mode and pin_buffer_selftest:
    parser.error('MENU_PIN_CONNECTION and MENU_PIN_BUFFER_SELFTEST must use separate VMs')
if args.native_display is not None and args.native_display not in ('none', 'gtk', 'sdl'):
    parser.error('QEMU_NATIVE_DISPLAY must be none, gtk or sdl')
if args.native_display is not None and not (args.headless_osd and args.initramfs):
    parser.error('--native-display requires --headless-osd --initramfs')
if args.initramfs_file and not args.initramfs:
    parser.error('--initramfs-file requires --initramfs')
if args.capid_service and not (args.observe and args.seed_backup):
    parser.error('--capid-service requires --observe --seed-backup')
if args.sa_address_service and not args.observe:
    parser.error('--sa-address-service requires --observe')
if args.hdmi_format_service and not args.observe:
    parser.error('--hdmi-format-service requires --observe')
if args.hdmi_photo_service and not args.observe:
    parser.error('--hdmi-photo-service requires --observe')
if args.dmm_service and not (args.observe and args.initramfs and args.load_dmm):
    parser.error('--dmm-service requires --observe --initramfs --load-dmm')
if args.software_gpe and not (args.observe and args.initramfs):
    parser.error('--software-gpe requires --observe --initramfs')
if args.headless_osd and not (args.software_gpe and args.load_ipc and os.environ.get('MENU_GPE_RGBA4444') == '1'):
    parser.error('--headless-osd requires --software-gpe --load-ipc and MENU_GPE_RGBA4444=1')
if args.firmware_identity and not args.initramfs:
    parser.error('--firmware-identity requires --initramfs')
if args.display_info_service and not args.observe:
    parser.error('--display-info-service requires --observe')
boot_type = int(os.environ.get('QEMU_BOOT_TYPE', '1'), 0)
if not 1 <= boot_type <= 8:
    parser.error('QEMU_BOOT_TYPE must be between 1 and 8')
base = Path(__file__).resolve().parent
sd_seed=Path(os.environ['A7C2_SD_IMAGE']).absolute() if os.environ.get('A7C2_SD_IMAGE') else None
sd_seed_bytes=sd_seed_sha256=None
host_sd_fd=None
directory_sd_fd=None
host_sd_export_verified=[False]
if os.environ.get('A7C2_HOST_SD'):
    if (os.environ.get('A7C2_HOST_SD')!='256gb' or not rm_file or not args.initramfs or
            not args.observe or sd_sparse or sd_seed or os.environ.get('A7C2_SD_HOTPLUG') or
            not os.environ.get('A7C2_HOST_SD_FD','').isdecimal()):
        parser.error('Host SD requires256gb original RM profile and controller-owned disk fd')
    import stat
    host_sd_fd=int(os.environ['A7C2_HOST_SD_FD'])
    if host_sd_fd<40:parser.error('Host SD fd is not controller-owned')
    info=os.fstat(host_sd_fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or info.st_size!=256000000000:
        parser.error('Host SD fd must pin the owned regular256GB disk')
elif os.environ.get('A7C2_HOST_SD_FD'):
    parser.error('Unrequested host SD fd')
if os.environ.get('A7C2_DIRECTORY_SD'):
    if (os.environ.get('A7C2_DIRECTORY_SD_PROFILE')!='directory-vvfat-256gb-v1' or
            not Path(os.environ['A7C2_DIRECTORY_SD']).is_absolute() or
            not rm_file or not args.initramfs or not args.observe or sd_sparse or sd_seed or
            os.environ.get('A7C2_SD_HOTPLUG') or host_sd_fd is not None or
            not os.environ.get('A7C2_DIRECTORY_SD_FD','').isdecimal()):
        parser.error('Directory SD requires the pinned 256GB directory profile and no other media')
    import stat
    directory_sd_fd=int(os.environ['A7C2_DIRECTORY_SD_FD'])
    if directory_sd_fd<40:parser.error('Directory SD fd is not controller-owned')
    info=os.fstat(directory_sd_fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o022:
        parser.error('Directory SD fd must pin an owned directory')
elif os.environ.get('A7C2_DIRECTORY_SD_FD'):
    parser.error('Unrequested directory SD fd')
if sd_seed:
    from sd_transport import card_source,digest_fd
    with card_source(sd_seed) as source_fd:
        sd_seed_bytes=os.fstat(source_fd).st_size
        sd_seed_sha256=digest_fd(source_fd)
if language_fonts and any(not (base/'menu-root'/FONT_GUEST/name).is_file() for name in FONT_SPECS):
    parser.error('Missing official Chinese fonts; install with prepare-assets.py --install-language-fonts --firmware-root ORIGINAL --runtime RUNTIME')
lock_path = base / '.menu-probe.lock'
inherited_lock = os.environ.get('MENU_PROBE_LOCK_FD')
if inherited_lock is None:
    lock = lock_path.open('a')
else:
    if not inherited_lock.isdecimal() or int(inherited_lock) < 3:
        raise RuntimeError('Invalid inherited probe lock descriptor')
    lock = os.fdopen(int(inherited_lock), 'a')
    actual, expected = os.fstat(lock.fileno()), lock_path.stat()
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        raise RuntimeError('Inherited descriptor does not refer to the probe lock')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
runs = base / 'menu-runs'
runs.mkdir(exist_ok=True)
out = Path(tempfile.mkdtemp(prefix='run-', dir=runs))
(base / 'latest-menu-run.txt').write_text(str(out) + '\n')
live_fd = os.environ.get('MENU_CONTROL_FD')
late_passive=os.environ.get('A7C2_EE_PASSIVE_AFTER_SHUTTER','')
if late_passive not in ('','1') or (late_passive and (not live_fd or
        os.environ.get('A7C2_EE_PASSIVE_SNAPSHOT')!='1')):
    parser.error('Late passive sampling requires the live channel and explicit passive snapshot profile')
still_passive=os.environ.get('A7C2_EE_PASSIVE_ON_STILL_ENTRY','')
if still_passive not in ('','1') or (still_passive and (not live_fd or
        os.environ.get('A7C2_EE_PASSIVE_SNAPSHOT')!='1' or
        os.environ.get('MENU_NATURAL_START_TRACE')!='1' or not dfs_selector)):
    parser.error('Still-entry passive sampling requires the live DFS natural trace and passive profile')
env = dict(os.environ, QEMU_TIMEOUT_SECONDS="0" if live_fd else "180", QEMU_TRACE_FLAGS="cpu_reset,guest_errors,unimp",
           QEMU_OUTPUT_DIR=str(out), SONY_DMM_SERVICE='1' if args.dmm_service else '0')
env['QEMU_PIN_CONTROL_MEMORY'] = '1' if pin_control_memory else '0'
env['QEMU_SYSTEM_SOUND_OWNER'] = '1' if audio_boot_config else '0'
if pinmem_hdmi_video_connection_profile and request_queue_gdb:
    parser.error('HDMI native consumer observation requires its own isolated debug channel')
env['QEMU_HDMI_UPM_GDB'] = '1' if pinmem_hdmi_video_connection_profile and (live_fd or functional_camera_profile) else '0'
if functional_camera_profile:
    # The broker owns orderly shutdown; the wrapper's timeout must not kill its VM.
    env.update(QEMU_UI_LIVE='1', QEMU_TIMEOUT_SECONDS='0')
if args.native_display is not None:
    env.update(MENU_NATIVE_WINDOW='1', QEMU_NATIVE_DISPLAY=args.native_display)
if live_fd:
    env['QEMU_UI_LIVE'] = '1'
    if request_queue_gdb:env['QEMU_REQUEST_QUEUE_GDB']='1'
if resize_mmio_watch:
    env['QEMU_REQUEST_QUEUE_GDB']='1'
    env['QEMU_RESIZE_OBSERVE']='1'
if resize_mmio_watch or functional_camera_profile:
    def stop_live(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop_live)
# Must be set before QEMU starts: the guest setup lines below run after the VM is already up.
if os.environ.get("MENU_EXTRA_CMDLINE"):
    env["QEMU_EXTRA_CMDLINE"] = os.environ["MENU_EXTRA_CMDLINE"]
if args.sony_timers:
    env['SONY_TIMER_MODEL'] = '1'
    env.setdefault('QEMU_SYSTEM_DIR', str(base.parent / 'sources/qemu-11.1.2/build-sony-ui'))
    env.setdefault('QEMU_SYSTEM_BINARY', 'qemu-system-aarch64')
# The isolated-USB derivation reuses this launcher with an extended script and a
# derived DTB; the defaults below keep every other run byte-identical.
kernel_script = Path(os.environ.get('MENU_KERNEL_SCRIPT', str(base / "qemu-kernel-probe.sh")))
board_dtb = Path(os.environ.get('MENU_DTB', str(base / "qemu-virt-board/virt-packed.dtb")))
command = ["bash", str(kernel_script), "4096",
           str(board_dtb), "1", "1",
           str(args.initramfs_file or base / ("menu-initramfs.cpio" if args.initramfs else "menu-root.ext2"))]
overwrite_manifest=None
overwrite_directory=Path(os.environ.get('A7C2_OVERWRITE_DIR',str(base.parent.parent/'overwrite'))).absolute()
if os.path.lexists(overwrite_directory):
    if not args.initramfs:
        raise RuntimeError('overwrite directory requires raw initramfs mode')
    if overwrite_directory.is_symlink() or not overwrite_directory.is_dir():
        raise ValueError('overwrite must be an ordinary directory')
    if any(overwrite_directory.iterdir()):
        from firmware_overlay import build_overlay_initramfs
        selected=out/'overwrite-initramfs.cpio'
        overwrite_manifest=build_overlay_initramfs(Path(command[-1]),overwrite_directory,selected)
        (out/'overwrite-manifest.json').write_text(json.dumps(overwrite_manifest,indent=2)+'\n')
        command[-1]=str(selected)
settings_restore_manifest=None
settings_persist=os.environ.get('A7C2_SETTINGS_PERSIST')=='1'
if os.environ.get('A7C2_SETTINGS_RESTORE'):
    if not settings_persist or not args.initramfs:
        raise ValueError('Settings restore requires the explicit persistent raw-initramfs profile')
    from settings_instance import stage_restore
    selected,settings_restore_manifest=stage_restore(os.environ['A7C2_SETTINGS_RESTORE'],
        os.environ.get('A7C2_SETTINGS_RESTORE_SHA'),Path(command[-1]),out)
    command[-1]=str(selected)
    (out/'settings-restore-manifest.json').write_text(json.dumps(settings_restore_manifest,indent=2)+'\n')

def sha256_file(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()

backup_profile_receipt=None
if backup_sync:
    from backup_profile import (validate_build,PRIMARY_SHA,PRIMARY_BYTES,cp302c_diagnostic_profile_fields,
                                cp_notification_control_profile_fields,cp_capture_format_profile_fields,
                                functional_camera_profile_fields)
    selected_build,selected_binary,selected_receipt=validate_build(base,os.environ.get('A7C2_BACKUP_BUILD',''))
    profile_path=Path(os.environ['MENU_BACKUP_PROFILE_RECEIPT'])
    backup_profile_receipt=json.loads(profile_path.read_text())
    active_binary=(Path(env['QEMU_SYSTEM_DIR'])/env.get('QEMU_SYSTEM_BINARY','qemu-system-aarch64')).resolve()
    if (active_binary!=selected_binary or backup_profile_receipt.get('profile')!=backup_sync or
            backup_profile_receipt.get('binary_sha256')!=selected_receipt['binary_sha256'] or
            backup_profile_receipt.get('derived_script_sha256')!=sha256_file(kernel_script) or
            backup_profile_receipt.get('derived_board_sha256')!=sha256_file(board_dtb) or
            backup_profile_receipt.get('fixture_sha256')!=PRIMARY_SHA or
            backup_profile_receipt.get('fixture_bytes')!=PRIMARY_BYTES or
            any(type(backup_profile_receipt.get(name)) is not type(value) or
                backup_profile_receipt.get(name)!=value for name,value in
                adf_proc_profile_fields(adf_proc_path_profile).items()) or
            any(type(backup_profile_receipt.get(name)) is not type(value) or
                backup_profile_receipt.get(name)!=value for name,value in
                adf_set_input_profile_fields(adf_set_input_profile).items()) or
            any(type(backup_profile_receipt.get(name)) is not type(value) or
                backup_profile_receipt.get(name)!=value for name,value in
                adf_set_output_profile_fields(adf_set_output_profile).items()) or
            any(type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                bb_set_mode_profile_fields(bb_set_mode_profile).items()) or
            any(type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                imaging_pin_connection_profile_fields(imaging_pin_connection_profile).items()) or
            any(type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                imaging_control_connection_profile_fields(imaging_control_connection_profile).items()) or
            any(type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                imaging_adf_connection_profile_fields(imaging_adf_connection_profile).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                infrabb_vef_connection_profile_fields(infrabb_vef_connection_profile).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                infrabb_vef_control_connection_profile_fields(infrabb_vef_control_connection_profile).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                vef_pinmem_input_connection_profile_fields(vef_pinmem_input_connection_profile).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                vef_pinmem_control_connection_profile_fields(vef_pinmem_control_connection_profile).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                pinmem_peer_connections_profile_fields(pinmem_peer_connections_profile).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                pinmem_hdmi_video_connection_profile_fields(pinmem_hdmi_video_connection_profile).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                pinmem_osd_connection_profile_fields(pinmem_osd_connection_profile).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                adf_hdmi_audio_connection_profile_fields(adf_hdmi_audio_connection_profile).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                cp302c_no_transition_profile_fields(cp302c_no_transition_profile).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                cp302c_diagnostic_profile_fields(os.environ.get('MENU_CP302C_DIAGNOSTIC','')).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                cp_notification_control_profile_fields(os.environ.get('MENU_CP_NOTIFICATION_CONTROL','')).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                cp_capture_format_profile_fields(os.environ.get('MENU_CP_CAPTURE_FORMAT','')).items()) or
            any(name not in backup_profile_receipt or type(backup_profile_receipt.get(name)) is not type(value) or
                json.dumps(backup_profile_receipt.get(name))!=json.dumps(value) for name,value in
                functional_camera_profile_fields(os.environ.get('MENU_FUNCTIONAL_CAMERA','')).items()) or
            sha256_file(Path(backup_profile_receipt['fixture']))!=PRIMARY_SHA or
            json.loads(udate_kernel_receipt.read_text()).get('backup_default_off') is not True or
            overwrite_manifest or settings_restore_manifest):
        raise ValueError('Backup profile identity/admission mismatch; current fixture requires a fresh ALLLANG instance')

functional_camera = None
if functional_camera_profile:
    from functional_camera_runner import prepare as prepare_functional_camera
    functional_camera = prepare_functional_camera(functional_camera_profile, base, out,
        Path(env['QEMU_SYSTEM_DIR']) / env.get('QEMU_SYSTEM_BINARY', 'qemu-system-aarch64'))

cp_background_identity=None
if cp_background:
    from initramfs_identity import verify_image
    cp_background_identity=verify_image(Path(command[-1]),{
        'cp/cpapp-b.bin':'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'})

manifest = {'probe_args': vars(args).copy(), 'settle_seconds': int(os.environ.get('MENU_SETTLE_SECONDS', '90')),
            'backup_sync_profile':backup_sync or None,
            'backup_transport':backup_profile_receipt,
            'backup_original_cp_executed':False,
            'backup_dma_verified':False,
            'qemu_cpu_count':int(os.environ.get('QEMU_CPU_COUNT','1')),
            'rc_board_profile':os.environ.get('QEMU_SONY_RC')=='1',
            'gic_loader_handoff':os.environ.get('QEMU_SONY_GIC_HANDOFF')=='1',
            'ee_passive_snapshot':os.environ.get('A7C2_EE_PASSIVE_SNAPSHOT')=='1',
            'ee_passive_after_shutter':late_passive=='1',
            'ee_passive_on_still_entry':still_passive=='1',
            'sa_reference_data_only':os.environ.get('QEMU_SONY_SA_DATA_ONLY')=='1',
            'sa_reference_completion':os.environ.get('QEMU_SONY_SA_REFERENCE_COMPLETE')=='1',
            'sa_reference_layout':'Y0 Cb Y1 Cr, adjacent-row half-up chroma mean; silicon unverified' if any(
                os.environ.get(key)=='1' for key in ('QEMU_SONY_SA_DATA_ONLY','QEMU_SONY_SA_REFERENCE_COMPLETE')) else None,
            'sa_completion_factor_hardware_verified':False,
            'sa_reference_completion_protocol':'virtual group0 bit0 after verified RAM conversion' if os.environ.get('QEMU_SONY_SA_REFERENCE_COMPLETE')=='1' else None,
            'liveview_trace': os.environ.get('MENU_LIVEVIEW_TRACE') == '1',
            'jpeg_request_trace': os.environ.get('MENU_JPEG_REQUEST_TRACE') == '1',
            'input_route_trace': os.environ.get('MENU_INPUT_ROUTE_TRACE') == '1',
            'input_route_detail_trace': input_route_detail or None,
            'natural_start_trace': os.environ.get('MENU_NATURAL_START_TRACE') == '1',
            'natural_imaging_profile': os.environ.get('A7C2_NATURAL_IMAGING_PROFILE') == '1',
            'yc_ownership_observe': bool(yc_ownership_observe),
            'yc_inject': yc_inject_delay if yc_inject == '1' else None,
            'vpanel': vpanel == '1' or None,
            'overwrite':overwrite_manifest,
            'settings_persist':settings_persist,'settings_restore':settings_restore_manifest,
            'custom_fixed_address_probe_compatibility_verified':False if overwrite_manifest else None,
            'boot_type': boot_type, 'files': {}, 'original_libraries_unchanged': False,
            'vdf_config_service': os.environ.get('MENU_VDF_CONFIG') == '1',
            'hdmi_boot_config_service': os.environ.get('MENU_HDMI_BOOT_CONFIG') == '1',
            'audio_boot_config_service': os.environ.get('MENU_AUDIO_BOOT_CONFIG') == '1',
            'audio_capabilities_profile': 'inputless' if os.environ.get('MENU_AUDIO_BOOT_CONFIG') == '1' else None,
            'system_sound_owner': audio_boot_config,
            'digital_level_profile': dig_level_mode,
            'panel_reverse_profile': panel_reverse_mode,
            'power_notice_observe':os.environ.get('A7C2_CAPTURE_POWER')=='1',
            'apo_cancel_request_probe':os.environ.get('A7C2_TEST_APO_CANCEL')=='1',
            'request_queue_gdb':request_queue_gdb,
            'resize_mmio_watch':resize_mmio_watch,
            'usb_network_profile': 'isolated-usb-ethernet-v1' if os.environ.get('MENU_USB_NET') == '1' else None,
            'usb_network_selftest': os.environ.get('A7C2_USB_NET_SELFTEST') == '1',
            'media_predicate_observe':media_predicate_observe,
            'media_init_watch':media_init_watch,
            'input_event32_observe':os.environ.get('A7C2_CAPTURE_INPUT_EVENTS')=='1',
            'mode_state_readback':os.environ.get('A7C2_MODE_READBACK')=='1',
            'input_route':'legacy-file' if os.environ.get('MENU_LIVE_KEY_FILE') else 'app32' if os.environ.get('MENU_LIVE_APP_INPUT')=='1' else 'infra20',
            'dmm_unit_config_service': dmm_unit_config,
            'rm_file_profile': ('virtual-rm1-mmc-file-v1' if rm_slot1 else 'virtual-rm2-mmc-file-v1') if rm_file else None,
            'gui_model_store_profile': gui_models or None,
            'cp_background_profile':cp_background or None,
            'cp_background_asset_identity':cp_background_identity,
            'cp_background_model_mode':3 if cp_background else None,
            'cp_background_request_completion_mode':0 if cp_background else None,
            'cp_background_unselected_modules_completed':False,
            'cp_background_hardware_ready':False,
            'udate_distribution_profile':udate_distribution or None,
            'udate_distribution_protocol':'kernel-public-roundtrip-v1' if udate_distribution else None,
            'udate_distribution_source_clock':'original-kernel-timer-reads' if udate_distribution else None,
            'udate_distribution_kernel':{
                'module':'simulation/sony_udate_distribution.ko',
                'sha256':sha256_file(udate_kernel_module),
                'receipt':json.loads(udate_kernel_receipt.read_text())
            } if udate_distribution else None,
            'udate_distribution_original_cp_executed':False,
            'udate_distribution_hardware_ready':False,
            'touch_panel_profile':touch_panel or None,
            'tcin_detect_profile':tcin_detect or None,
            'dfs_selector_profile':dfs_selector or None,
            'vef_path_profile':vef_path_profile or None,
            **adf_proc_profile_fields(adf_proc_path_profile),
            **adf_set_input_profile_fields(adf_set_input_profile),
            **adf_set_output_profile_fields(adf_set_output_profile),
            **bb_set_mode_profile_fields(bb_set_mode_profile),
            **imaging_pin_connection_profile_fields(imaging_pin_connection_profile),
            **imaging_control_connection_profile_fields(imaging_control_connection_profile),
            **imaging_adf_connection_profile_fields(imaging_adf_connection_profile),
            **infrabb_vef_connection_profile_fields(infrabb_vef_connection_profile),
            **infrabb_vef_control_connection_profile_fields(infrabb_vef_control_connection_profile),
            **vef_pinmem_input_connection_profile_fields(vef_pinmem_input_connection_profile),
            **vef_pinmem_control_connection_profile_fields(vef_pinmem_control_connection_profile),
            **pinmem_peer_connections_profile_fields(pinmem_peer_connections_profile),
            **pinmem_hdmi_video_connection_profile_fields(pinmem_hdmi_video_connection_profile),
            **pinmem_osd_connection_profile_fields(pinmem_osd_connection_profile),
            **adf_hdmi_audio_connection_profile_fields(adf_hdmi_audio_connection_profile),
            **cp302c_no_transition_profile_fields(cp302c_no_transition_profile),
            **cp302c_diagnostic_profile_fields(cp302c_diagnostic_profile),
            **cp_notification_control_profile_fields(cp_notification_control_profile),
            **cp_capture_format_profile_fields(cp_capture_format_profile),
            **functional_camera_profile_fields(functional_camera_profile),
            'vef_path_protocol':'AP0149-path1-native-empty-v1' if vef_path_profile else None,
            'vef_path_original_cp_executed':False,
            'vef_path_frames_verified':False,
            'vef_path_global_dmm_idle_verified':False,
            'vef_path_hardware_verified':False,
            'vef_path_nonempty_release_supported':False,
            'dfs_selector_register_base':'0xf1388f50' if dfs_selector else None,
            'dfs_selector_initial_mode_policy':0 if dfs_selector else None,
            'dfs_actual_clock_changes':False,
            'dfs_silicon_timing_verified':False,
            'tcin_detect_protocol':'AP0429-inactive-disable-config-v1' if tcin_detect else None,
            'tcin_original_cp_executed':False,
            'tcin_hardware_verified':False,
            'tcin_enable_and_active_disable_supported':False,
            'touch_panel_protocol':'AP0146-DevPanelBody-virtual-config-v1' if touch_panel else None,
            'touch_panel_original_cp_executed':False,
            'touch_panel_f02f_transport_verified':False,
            'touch_panel_control_result_verified':False,
            'touch_panel_hardware_ready':False,
            'official_chinese_fonts': {name:{'bytes':size,'sha256':digest,'source_class':'sony_original'}
                                       for name,(size,digest) in FONT_SPECS.items()} if language_fonts else None,
            'gui_model_store_cp_subscriptions_implemented': False,
            'gui_model_store_exposure_fixture': {'f_number':[4,1],'seconds':[1,125],'iso':100} if gui_models else None,
            'rm_file_image_bytes': (256000000000 if host_sd_fd is not None or directory_sd_fd is not None else 10*1024*1024*1024 if sd_sparse else sd_seed_bytes or (base/'menu-root/simulation/media-camera.fat').stat().st_size) if rm_file else None,
            'host_sd_profile':'host-file-usb-256gb-v1' if host_sd_fd is not None else None,
            'directory_sd_profile':'directory-vvfat-256gb-v1' if directory_sd_fd is not None else None,
            'sd_sparse_profile':sd_sparse or None,
            'virtual_sd_seed':str(sd_seed) if sd_seed else None,
            'virtual_hci_profile':virtual_hci or None,
            'host_control_owner_pid':os.getpid() if resize_mmio_watch and not live_fd else int(os.environ.get('MENU_CONTROL_OWNER_PID','0')),
            'rm_file_global_dummy_nand_unsupported': rm_file,
            'standalone_fsys_camera_mount_flags': 0x100 if os.environ.get('MENU_MEDIA_SELFTEST')=='1' else None,
            'standalone_rm_queue_transport_test': os.environ.get('MENU_MEDIA_SELFTEST')=='1',
            'pin_registry_service': os.environ.get('MENU_PIN_REGISTRY') == '1',
            'pin_control_memory': pin_control_memory, 'pin_buffer_selftest': pin_buffer_selftest,
            'pin_connection_mode': pin_connection_mode,
            'input_key_mode': input_key_mode,
            'live_app_input': os.environ.get('MENU_LIVE_APP_INPUT')=='1',
            'live_key_file': live_key_file or None,
            'infra_key_injection': os.environ.get('MENU_KEY_INJECT',''),
            'infra_key_queue': os.environ.get('MENU_KEY_QUEUE','0x807a0020') if os.environ.get('MENU_KEY_INJECT') else None,
            'infra_key_source': os.environ.get('MENU_KEY_SRC','0x92840747') if os.environ.get('MENU_KEY_INJECT') else None,
            'trace_mutex': os.environ.get('MENU_TRACE_MUTEX') == '1'}
manifest['probe_args']['initramfs_file'] = str(args.initramfs_file) if args.initramfs_file else None
if functional_camera is not None:
    manifest['functional_camera_runtime'] = functional_camera.receipt('preflight')
for path in [Path(command[-1]), base / 'qemu-menu-probe.py', base / 'backup_profile.py',
             base / 'menu-observe.c', base / 'menu-observe.so',
             base / 'menu-regs.c', base / 'menu-root/simulation/menu-regs', base / 'menu-readmem.c',
             base / 'capid-service.c', base / 'capid-service.h',
             base / 'infrabb-registry.c', base / 'infrabb-registry.h',
             base / 'drawinfo-registry.h',
             base / 'dig-level-device.c', base / 'dig-level-device.h',
             base / 'dmm-unit-config.c', base / 'dmm-unit-config.h',
             base / 'rm-file-device.c',base / 'rm-file-device.h',
             base / 'gui-model-wire.c',base / 'gui-model-wire.h',
             base / 'gui-model-store.c',base / 'gui-model-store.h',
             base / 'gui_model_capture.py',base / 'menu_live.py',base / 'media_state_readback.py',
             base.parent.parent / 'report/camera-input-coverage/input_bindings.py',
             base / 'wifi_toggle.py',base / 'ethernet_peer.py',base / 'menu_control.py',base / 'usb_network.py',
             base / 'ee_entry_snapshot.py',
             base / 'sd_hotplug.py',base / 'sd-hotplug-runtime.c',base / 'sd-hotplug-runtime.h',base / 'sd-state.c',base / 'sd-state.h',
             base / 'instance_lifecycle.py',base / 'setting_store.py',
             base / 'settings_checkpoint.py',base / 'settings_instance.py',base / 'user-settings-checkpoint.c',
             kernel_script,board_dtb,
             base / 'media_predicate_watch.py',
             base / 'media_initial_write.py',
             base / 'request_queue_watch.py', base / 'resize_mmio_watch.py', base / 'check-natural-gtk-input.py',
             base / 'language_fonts.py',base / 'prepare-assets.py',
             base / 'firmware_overlay.py',base / 'camera_ui.py',base / 'bodydata-launch.py',
             *(base/'menu-root'/FONT_GUEST/name for name in FONT_SPECS),
             base / 'inject-key.c',base / 'menu-root/simulation/inject-key',
             base / 'fsys-file-test.c', base / 'file-media-config.c',
             base / 'menu-root/simulation/fsys-file-test', base / 'menu-root/simulation/file-media-config.so',
             base / 'menu-root/simulation/media-template.fat',
             base / 'menu-root/simulation/media-camera.fat',
             base / 'menu-root/simulation/menu-readmem',
             base / 'sd-window-export.c',base / 'sd_transport.py',
             base / 'sd_flush_barrier.py',base / 'sd_export_lifecycle.py',
             base / 'menu-root/simulation/sd-window-export',
             base / 'native-pin-control-region.py', base / 'menu-root/simulation/pin-control-probe',
             base / 'snapshot-observer-sources.py', base / 'observer-build-inputs.json',
             base / 'initramfs_identity.py',
             base / 'native_smp.py',base / 'native_rc_board.py',base / 'boot_irq_diagnostics.py',
             base / 'rc_reference_evidence.py',base / 'build-rc-reference.sh',
             base / 'sa_job_evidence.py',
             base / 'sa_mmu.py',base / 'sa_program_evidence.py',base / 'sa_data_evidence.py',
             base / 'sa_completion_evidence.py',
             base / 'native-sound-region.py', base / 'menu-root/cp/SysSound.bin',
             base / 'menu-root/simulation/system-sound-owner',
             base / 'device-models/UPSTREAM-COPY.json',
             *(path for path in sorted((base / 'device-models').iterdir())
               if path.suffix in ('.c', '.h', '.inc', '.py')),
             base / 'sa-address-service.c', base / 'menu-root/system/av-cam.bin',
             base / 'hdmi-format-service.c', base / 'hdmi-format-service.h',
             base / 'dmm-service.c', base / 'dmm-service.h', base / 'menu-root/cp/DmmCfg.bin',
             base / 'gpe-raster.c', base / 'headless-osd.c', base / 'headless-osd.h',
             base / 'headless-osd-export.c', base / 'headless_osd_capture.py',
             base / 'ramfb-viewer.c', base / 'menu-root/simulation/ramfb-viewer',
             base / 'mutex-trace.c', base / 'menu-root/simulation/mutex-trace.so',
             base / 'guest-overlay/simulation/input-state.sh',
             base / 'menu-root/simulation/headless-osd-export',
             base / 'menu-root/simulation/gui-model-export',
             base / 'firmware-identity.json', base / 'menu-root/simulation/firmware-identity.fat',
             base / 'menu-root/simulation/firmware-version.dat4',
             base / 'qemu-kernel-probe.sh', base / 'menu-root/usr/lib/libmpr.so',
             base / 'menu-root/cp/cpapp-b.bin', base / 'menu-root/simulation/seed-power-on',
             base / 'seed-power-on.c', base / 'menu-root/simulation/libIMDB.so',
             base / 'seed-date-clock.c', base / 'menu-root/simulation/seed-date-clock',
             base / 'menu-root/simulation/osal-uipc-transport-errors.ko',
             base / 'menu-root/simulation/sony_virtual_cp_send.ko',
             base / 'menu-root/usr/lib/appFw.so', base / 'menu-root/usr/lib/libObj.so',
             base / 'menu-root/usr/lib/libgpe.so', base / 'menu-root/usr/lib/libupdaterufp.so',
             Path(env.get('QEMU_SYSTEM_DIR', str(base.parent / 'sources/qemu-11.1.2/build-sony-ui'))) / env.get('QEMU_SYSTEM_BINARY', 'qemu-system-aarch64')]:
    if path.is_file():
        manifest['files'][str(path)] = sha256_file(path)
if functional_camera is not None:
    for path in (base/'functional_camera_runner.py', base/'functional_camera_broker.py',
                 base/'start-menu.py',
                 base/'build-functional-camera-model.py',
                 base/'functional-camera-bridge.c', base/'functional-camera-bridge.h',
                 base/'functional-camera-abi.h', base/'functional-camera-model.so',
                 base/'functional-camera-model-build.json',
                 base/'menu-root/usr/lib/libInfraAvbbc.so',
                 base/'menu-root/usr/lib/dataflowInfraFramework.so'):
        manifest['files'][str(path)] = sha256_file(path)
if udate_distribution:
    for path in (udate_kernel_module, udate_kernel_receipt,
                 base/'../../report/virtual-cp/udate-distribution/client.c',
                 base/'../../report/virtual-cp/udate-distribution/backup-endpoint.c',
                 base/'../../report/virtual-cp/udate-distribution/backup-pci.c',
                 base/'../../report/virtual-cp/udate-distribution/test_backup_endpoint.c',
                 base/'../../report/virtual-cp/udate-distribution/test_backup_pci.c',
                 base/'../../report/virtual-cp/udate-distribution/descriptor.S',
                 base/'../../report/virtual-cp/udate-distribution/build.sh',
                 base/'../../report/virtual-cp/udate-distribution/check_client.py',
                 base/'../../report/virtual-cp/udate-distribution/test_client.c',
                 base/'../../report/virtual-cp/udate-distribution/test_udate_kernel.py'):
        manifest['files'][str(path)] = sha256_file(path)
build_inputs = json.loads((base / 'observer-build-inputs.json').read_text())
archive = base / 'observer-build-sources.tar.gz'
if build_inputs['observer_sha256'] != sha256_file(base / 'menu-observe.so') or \
        build_inputs['source_archive_sha256'] != sha256_file(archive):
    raise RuntimeError('Observer build artifacts differ; rebuild before launching')
manifest['compiled_observer'] = build_inputs
(out / 'observer-build-inputs.json').write_bytes((base / 'observer-build-inputs.json').read_bytes())
(out / 'observer-build-sources.tar.gz').write_bytes(archive.read_bytes())
identity = json.loads((base / 'runtime-manifest.json').read_text())
for library in ('usr/lib/appFw.so', 'usr/lib/libObj.so'):
    if manifest['files'][str(base / 'menu-root' / library)] != identity[library]:
        raise RuntimeError('Original library identity changed: ' + library)
if args.initramfs:
    expected_guest = {library: identity[library] for library in ('usr/lib/appFw.so', 'usr/lib/libObj.so')}
    expected_guest['simulation/menu-observe.so'] = build_inputs['observer_sha256']
    expected_guest['simulation/pin-control-probe'] = build_inputs['pin_control_probe_sha256']
    if udate_distribution:
        expected_guest['simulation/sony_udate_distribution.ko'] = manifest['files'][str(udate_kernel_module)]
    if resize_mmio_watch:
        from resize_mmio_watch import KERNEL_SHA
        expected_guest['system/av-cam.bin'] = KERNEL_SHA
    if yc_inject == '1':
        expected_guest['simulation/yc_inject.ko'] = sha256_file(base/'menu-root/simulation/yc_inject.ko')
        if yc_ownership_observe:
            from yc_ownership_evidence import verify_build as verify_ownership_build
            manifest['yc_ownership_build'] = verify_ownership_build(
                base/'../../report/virtual-cp/yc-inject', base/'menu-root/simulation/yc_inject.ko')
        manifest['yc_input_mode'] = 'uncompressed-neutral-test' if yc_uncompressed else 'luma-transport-diagnostic'
    if os.environ.get('MENU_YC_INPUT_RAW'):
        expected_guest['simulation/yc-input.gray'] = sha256_file(Path(os.environ['MENU_YC_INPUT_RAW']))
        manifest['yc_input_sha256'] = expected_guest['simulation/yc-input.gray']
    if virtual_hci:
        for name in ('virtual-hci','start-bt-virtual.sh'):
            expected_guest['simulation/'+name]=sha256_file(base/'menu-root/simulation'/name)
        expected_guest['usr/bin/bsa_server']='4e2c75171967ceaf99ddc5f63dde64a905035802c39da16d8b4f2cb560a230ea'
    if sd_seed:
        expected_guest['simulation/sd-card.fat']=sd_seed_sha256
        manifest['virtual_sd_seed_sha256']=expected_guest['simulation/sd-card.fat']
    if language_fonts:
        for name,(size,digest) in FONT_SPECS.items():
            expected_guest[FONT_GUEST+'/'+name]=digest
    if gui_models:
        expected_guest['simulation/gui-model-export']=manifest['files'][str(base/'menu-root/simulation/gui-model-export')]
    if live_fd or args.headless_osd:
        expected_guest['simulation/headless-osd-export']=manifest['files'][str(base/'menu-root/simulation/headless-osd-export')]
    if live_fd or os.environ.get('MENU_KEY_INJECT'):
        expected_guest['simulation/inject-key']=manifest['files'][str(base/'menu-root/simulation/inject-key')]
    if dmm_unit_config:
        for name in ('usr/lib/libInfraMediaMount.so','usr/lib/libInfraMediaCommon.so',
                     'usr/lib/libInfraMediaConfig.so','usr/lib/libMWF.so'):
            expected_guest[name]=sha256_file(base/'menu-root'/name)
    if audio_boot_config:
        sound_api = runpy.run_path(str(base / 'native-sound-region.py'))
        if sha256_file(base / 'menu-root/cp/SysSound.bin') != sound_api['SOURCE_SHA256']:
            raise RuntimeError('Original SysSound identity differs')
        expected_guest['cp/SysSound.bin'] = sound_api['SOURCE_SHA256']
        expected_guest['simulation/system-sound-owner'] = build_inputs['system_sound_owner_sha256']
    if os.environ.get('MENU_MEDIA_SELFTEST')=='1' or rm_file:
        for name in ('simulation/fsys-file-test','simulation/file-media-config.so','simulation/media-template.fat'):
            expected_guest[name]=manifest['files'][str(base/'menu-root'/name)]
        if rm_file:
            expected_guest['simulation/media-camera.fat']=manifest['files'][str(base/'menu-root/simulation/media-camera.fat')]
            expected_guest['simulation/sd-window-export']=manifest['files'][str(base/'menu-root/simulation/sd-window-export')]
            if host_sd_fd is not None or directory_sd_fd is not None:
                for name in ('host-sd-probe','host-block-sd.so'):
                    expected_guest['simulation/'+name]=sha256_file(base/'menu-root/simulation'/name)
            if sd_sparse:
                expected_guest['simulation/sd-sparse']=sha256_file(base/'menu-root/simulation/sd-sparse')
            if settings_persist:
                expected_guest['simulation/user-settings-checkpoint']=sha256_file(base/'menu-root/simulation/user-settings-checkpoint')
        for name in ('usr/lib/libInfraFsys.so','usr/lib/libInfraMediaCommon.so','usr/lib/libMWF.so',
                     'usr/lib/libbackup.so','usr/lib/libosal_uipc.so','usr/lib/libosal_utm.so'):
            expected_guest[name]=sha256_file(base/'menu-root'/name)
    for library in ('usr/lib/libgpe.so', 'usr/lib/libmpr.so', 'cp/DmmCfg.bin', 'cp/cpapp-b.bin',
                    'simulation/menu-regs', 'simulation/menu-readmem'):
        expected_guest[library] = manifest['files'][str(base / 'menu-root' / library)]
    if functional_camera is not None:
        for library in ('usr/lib/libInfraAvbbc.so','usr/lib/dataflowInfraFramework.so'):
            expected_guest[library]=sha256_file(base/'menu-root'/library)
    if overwrite_manifest:
        expected_guest.update({entry['path']:entry['new_sha256'] for entry in overwrite_manifest['entries']})
    if settings_restore_manifest:
        expected_guest.update({entry['path']:entry['new_sha256'] for entry in settings_restore_manifest['entries']})
    if udate_distribution and expected_guest['simulation/sony_udate_distribution.ko'] != json.loads(udate_kernel_receipt.read_text())['sha256']:
        raise RuntimeError('UDATE kernel module differs from its ABI receipt; overlay replacement is not admitted')
    manifest['selected_initramfs_verified_files'] = verify_image(
        Path(command[-1]), expected_guest,
        forbidden=('simulation/yc-input-uncompressed','simulation/yc-ownership-observe',
                   'tmp/sd10g.ready','tmp/sony-sd10g/card.img') +
                  (() if os.environ.get('MENU_YC_INPUT_RAW') else ('simulation/yc-input.gray',)))
    manifest['original_libraries_unchanged'] = not overwrite_manifest or not any(
        entry['path'].startswith(('usr/lib/','lib/')) and entry['new_sha256']!=entry['old_sha256']
        for entry in overwrite_manifest['entries'])
    manifest['selected_observer_matches_build'] = expected_guest['simulation/menu-observe.so']==build_inputs['observer_sha256']
    if udate_distribution and not manifest['selected_observer_matches_build']:
        raise RuntimeError('UDATE distribution requires the current observer build; overlay replacement is not admitted')
elif args.observe:
    raise RuntimeError('Observer identity requires a verified raw initramfs; use --initramfs')
if (args.dmm_service or dmm_unit_config) and manifest['files'][str(base / 'menu-root/cp/DmmCfg.bin')] != 'd3466cee62fd86d927236a2c6c37dd633f76cdc181b4ad07a9863696aab76660':
    raise RuntimeError('CP DMM config differs from the verified two-slot model')
if args.software_gpe and manifest['files'][str(base / 'menu-root/usr/lib/libgpe.so')] != '80fc6236379933f80c2689aa002e0cf39483da8d45e876705d2a427cd1a2a7d1':
    raise RuntimeError('GPE library differs from the verified worker/GOT layout')
if manifest['rc_board_profile']:
    binary=Path(env['QEMU_SYSTEM_DIR'])/env.get('QEMU_SYSTEM_BINARY','qemu-system-aarch64')
    receipt=json.loads((binary.parent.parent/'rc-reference-build.json').read_text())
    if receipt['binary_sha256']!=sha256_file(binary):
        raise RuntimeError('RC reference binary differs from build receipt')
    for name,digest in receipt['sources'].items():
        if Path(name).name!=name or sha256_file(base/'device-models'/name)!=digest:
            raise RuntimeError('RC reference source differs from build receipt: '+name)
    manifest['rc_reference_build']=receipt
    (out/'rc-reference-build.json').write_text(json.dumps(receipt,indent=2)+'\n')
(out / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
with (out / "console.log").open("a" if live_fd else "w") as console:
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=console,
                            stderr=subprocess.STDOUT, env=env,
                            pass_fds=tuple(fd for fd in (host_sd_fd,directory_sd_fd) if fd is not None))
    early_media_watch=None
    try:
        if media_init_watch:
            from media_initial_write import EarlyWatch
            early_media_watch=EarlyWatch(out,manifest['host_control_owner_pid'],proc)
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(15)
            deadline = time.monotonic() + 8
            while True:
                try:
                    from menu_live import connect_in_run
                    connect_in_run(sock, out, 'qmp.sock')
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    if proc.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("QMP unavailable; inspect console.log")
                    time.sleep(0.1)
            with sock.makefile("rwb") as stream:
                if "QMP" not in json.loads(stream.readline()):
                    raise RuntimeError("Unexpected QMP greeting")

                def qmp(name, arguments=None):
                    # Centralize every quit, including startup-exception paths.
                    with (functional_camera.qmp_command(name) if functional_camera is not None else nullcontext()):
                        if name == 'quit' and early_media_watch is not None:
                            from media_initial_write import guard_shutdown
                            guard_shutdown(early_media_watch,proc,out)
                        if name == 'quit' and (host_sd_fd is not None or directory_sd_fd is not None):
                            from host_sd_guard import guard_shutdown as guard_host_sd
                            guard_host_sd(proc,out,host_sd_export_verified[0])
                            if proc.poll() is not None:
                                raise RuntimeError('QEMU exited before guarded quit; no quit command sent')
                        message = {"execute": name}
                        if arguments:
                            message['arguments'] = arguments
                        stream.write((json.dumps(message) + "\n").encode())
                        stream.flush()
                        while True:
                            result = json.loads(stream.readline())
                            if "error" in result:
                                raise RuntimeError(result["error"])
                            if "return" in result:
                                return result

                qmp("qmp_capabilities")
                if functional_camera is not None:
                    functional_camera.start(proc)
                deadline = time.monotonic() + 25
                while b"/ #" not in (out / "console.log").read_bytes():
                    if proc.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Merged filesystem did not reach shell")
                    time.sleep(0.1)
                # Verify serial input before a debugger can stop any secondary CPU.
                from menu_live import serial_command
                try:
                    (out/'boot-serial-roundtrip.log').write_bytes(
                        serial_command(proc,out/'console.log',':',timeout=15))
                except TimeoutError:
                    from boot_irq_diagnostics import capture
                    capture(qmp,out)
                    raise
                if manifest['qemu_cpu_count']==2:
                    from boot_irq_diagnostics import capture
                    capture(qmp,out)
                if resize_mmio_watch:
                    from request_queue_watch import QueueWatch
                    early_media_watch=QueueWatch(out,0,manifest['host_control_owner_pid'],'resize',autostart=False)
                    early_media_watch.start()
                setup = ["mount -t proc proc /proc", "mount -t sysfs sysfs /sys",
                         "mount -t tmpfs tmpfs /tmp", "mount -t tmpfs tmpfs /setting",
                         "mount -t tmpfs tmpfs /tmp_wbshd",
                         "export PATH=/bin:/sbin:/usr/bin:/usr/sbin",
                         "export LD_LIBRARY_PATH=/usr/lib:/lib",
                         "mkdir -p /dev/cgroup", "mount -t cgroup -o cpuset nodev /dev/cgroup",
                         "for group in cpu0 cpu1 cpu2 cpu3rt cpu0_1 cpu0_1_2 cpu0_1_2_3rt; do mkdir -p /dev/cgroup/$group; echo 0 > /dev/cgroup/$group/cpuset.mems; echo 0 > /dev/cgroup/$group/cpuset.cpus; done",
                         "echo MENU_ROOT_READY", "ls -l /usr/bin/im.elf /usr/lib/appFw.so"]
                if manifest['qemu_cpu_count']==2:
                    setup += ['echo 1 > /dev/cgroup/cpu1/cpuset.cpus',
                              'for group in cpu0_1 cpu0_1_2 cpu0_1_2_3rt; do echo 0-1 > /dev/cgroup/$group/cpuset.cpus; done']
                if language_fonts:
                    setup += ['mkdir -p /tmp/images',f'cp -a /{FONT_GUEST}/. /tmp/images/']
                    for name in FONT_SPECS:
                        setup += [f'/usr/bin/openssl dgst -sha256 /tmp/images/{name}']
                if args.load_ipc:
                    setup += ["insmod /kmod/devno.ko", "insmod /usr/kmod/osal_utm.ko",
                              "insmod " + ("/simulation/osal-uipc-transport-errors.ko" if args.transport_errors else "/usr/kmod/osal_uipc.ko"), "ls -l /dev/uipc"]
                    # dma330 (UDIF PL330 memory/peri DMA) is loaded first by the real initrc
                    # (insmod_drv1) with phy_inst_area; the probe list omitted it, so ldec/liro
                    # failed on dma330_mem_transfer_async. Load it early like the initrc does.
                    setup += ["insmod /kmod/dma330.ko phy_inst_area=0x4102E4000 && echo MOD_OK dma330 || echo MOD_FAIL dma330"]
                if udate_distribution:
                    if not args.load_ipc:
                        parser.error('MENU_UDATE_DISTRIBUTION requires --load-ipc for the kernel public endpoint')
                    backup_parameter=' backup_model=1' if backup_sync else ''
                    setup += ['insmod /simulation/sony_udate_distribution.ko'+backup_parameter+
                              ' && echo UDATE_K_MOD_OK || { echo UDATE_K_MOD_FAIL; exit 1; }']
                if os.environ.get("MENU_VIRTUAL_CP_SENDER") == '1':
                    if not args.load_ipc:
                        parser.error('MENU_VIRTUAL_CP_SENDER requires --load-ipc (osal_reg_public)')
                    # Capture-only virtual-CP bring-up tap: register a custom remote sender so
                    # AP->CP queue sends become visible instead of "No snd_msg registered".
                    setup += ["insmod /simulation/sony_virtual_cp_send.ko && echo VIRTUAL_CP_SENDER_MOD_OK || echo VIRTUAL_CP_SENDER_MOD_FAIL"]
                if os.environ.get("MENU_PCIDMA_XFER") == '1':
                    # Original PCI DMA API transfer diagnostic (pcidma-client): 256B AP->PCI->AP
                    # round-trip via the original pcidma_transfer_async against the modeled engine.
                    setup += ["insmod /simulation/sony_pcidma_xfer.ko && echo PCIDMA_XFER_MOD_OK || echo PCIDMA_XFER_MOD_FAIL"]
                if vpanel == '1':
                    # Virtual panel backend (report/virtual-cp/vpanel): answers the original
                    # 200d:0118 panel-out request with a contract 200d:1118 completion after
                    # applying the config to a virtual panel state. Device model, not hardware;
                    # owns the single osal_reg_public sender slot like the retired capture tap.
                    setup += ["insmod /simulation/vpanel.ko && echo VPANEL_MOD_OK || echo VPANEL_MOD_FAIL"]
                if os.environ.get('MENU_LOAD_PCIEATU') == '1':
                    # pcieatu alone (NOT pcie-if): liro needs pciatu_map/unmap to load av-cam;
                    # pcie-if would grab the osal_reg_public sender slot that vpanel/capture use.
                    setup += ["insmod /usr/kmod/pcieatu.ko && echo PCIEATU_MOD_OK || echo PCIEATU_MOD_FAIL"]
                if os.environ.get("MENU_PCIE_IF") == '1':
                    # Original CP interface drivers: pcieatu (ATU map) then pcie-if (remote queue
                    # sender via pcidma_transfer_async). With QEMU_SONY_PCIDMA=1 the PCIe model is
                    # present so pcieatu's udm_pciatu thread no longer null-derefs. AP->CP messages
                    # then go via the REAL PCI DMA path instead of the capture tap.
                    setup += ["insmod /usr/kmod/pcieatu.ko && echo PCIEATU_MOD_OK || echo PCIEATU_MOD_FAIL",
                              "insmod /usr/kmod/pcie-if.ko && echo PCIE_IF_MOD_OK || echo PCIE_IF_MOD_FAIL"]
                extra_module_setup = []
                if os.environ.get("MENU_EXTRA_MODULES"):
                    # The real /sbin/initrc/insmod_drv2 loads 38 modules; the probe used to load 10.
                    # These files are present in the test root but were never insmod-ed. The PCIe/CP
                    # transport modules go last so a fault there cannot hide the other results.
                    modules = ["input", "ldec", "icdt", "ioexp", "indctr", "udate",
                               "usb_portMonitor", "usbg_sen", "usb_extcmd", "mcmn_drv",
                               "codec_drv", "mmc_drv", "ms_drv", "nvme-core", "nvme", "compass"]
                    if os.environ["MENU_EXTRA_MODULES"] not in ("safe", "no-pcie"):
                        # pcieatu's udm_pciatu thread null-derefs without a PCIe model, so the
                        # transport trio only goes in when explicitly requested.
                        modules += ["pci_ep_cp", "pcieatu", "pcie-if"]
                    setup += ["echo set > /proc/udm/drivers", "echo UPM_DRIVER_SET_RC=$?"]
                    for module in modules:
                        skip = {"usb_portMonitor": "missing-USB-core-null-vbus",
                                "mmc_drv": "unmapped-MMC-controller-read32",
                                "ms_drv": "Sony-MS-controller-not-modeled"}.get(module)
                        if os.environ["MENU_EXTRA_MODULES"] == "safe" and skip:
                            extra_module_setup.append("echo MOD_SKIP %s %s" % (module, skip))
                            continue
                        extra_module_setup.append("insmod /usr/kmod/%s.ko >/dev/null 2>&1 && echo MOD_OK %s || echo MOD_FAIL %s" % (module, module, module))
                if args.sony_timers:
                    setup += ["insmod /usr/kmod/utimer.ko"]
                if args.seed_backup:
                    setup += ["cp /seed-backup.bin /setting/Backup.bin",
                              # Backup_save=1 lets the original driver commit a
                              # changed setting set back to /setting/Backup.bin;
                              # only an opt-in run may write the persisted state.
                              "insmod /usr/kmod/backup.ko Backup_load=1 Backup_save=%d"
                              % (1 if os.environ.get('MENU_BACKUP_SAVE') == '1' else 0),
                              "ls -l /dev/mem /dev/backup", "insmod /usr/kmod/stream.ko",
                              "insmod /usr/kmod/stream2.ko"]
                if args.load_dmm:
                    setup += ["cp -a /seed-setting/. /setting/",
                              "insmod /usr/kmod/osal_ulogio.ko ulogio_initfile=/setting/ulogio.bin",
                              "insmod /usr/kmod/dmm.ko DmmConfig=/setting/DmmCfg.bin",
                              "insmod /usr/kmod/grm_ma.ko"]
                # input/ioexp/udate and peers import Backup_*; icdt also follows DMM in initrc.
                setup += extra_module_setup
                if yc_inject == '1':
                    if yc_uncompressed:
                        setup += ['touch /simulation/yc-input-uncompressed']
                    if yc_ownership_observe:
                        setup += ['touch /simulation/yc-ownership-observe']
                    # YC IN1 injection experiment (report/virtual-cp/yc-inject): delayed insmod so
                    # av-cam's VDT service can register 0x827e073f during imaging init first.
                    # YCIN_* printk lines land in console.log; insmod rc only proves init returned,
                    # never av-cam consumption of the synthetic frame.
                    setup += ["(sleep %d; if mkdir /tmp/yc_inject.lock 2>/dev/null; then insmod /simulation/yc_inject.ko && echo YC_INJECT_MOD_OK || echo YC_INJECT_MOD_FAIL; fi) &" % yc_inject_delay]
                    # Read-only follow-up: did av-cam's service thread drain the injected message?
                    setup += ["(sleep %d; if [ ! -f /tmp/yc_stat.done ]; then touch /tmp/yc_stat.done; insmod /simulation/yc_stat.ko && echo YC_STAT_MOD_OK || echo YC_STAT_MOD_FAIL; fi) &" % (yc_inject_delay + 60)]
                    # Thread-level truth for the activation question: does any VDT/imaging
                    # service thread exist at all in this guest?
                    setup += ["(sleep %d; ps; echo YC_PS_DONE) &" % (yc_inject_delay + 70)]
                if yc_survey == '1':
                    # DMM pool survey (yc_survey.ko): which unit type allocates into a
                    # cacheable memrsv pool, so av-cam's arch_phys_to_cache accepts it.
                    try:
                        yc_survey_delay = int(yc_inject_delay)
                    except ValueError:
                        parser.error('MENU_YC_INJECT_DELAY must be an integer seconds value')
                    if not 0 <= yc_survey_delay <= 600:
                        parser.error('MENU_YC_INJECT_DELAY must be within 0..600')
                    setup += ["(sleep %d; if [ ! -f /tmp/yc_survey.done ]; then touch /tmp/yc_survey.done; insmod /simulation/yc_survey.ko && echo YC_SURVEY_MOD_OK || echo YC_SURVEY_MOD_FAIL; fi) &" % yc_survey_delay]
                if args.firmware_identity:
                    setup += ["mkdir -p /setting/updater /mnt",
                              "cp /simulation/firmware-version.dat4 /setting/updater/dat4",
                              "mknod /dev/ram1 b 1 1", "ln -s /dev/ram1 /dev/nflasha1",
                              "dd if=/simulation/firmware-identity.fat of=/dev/ram1 bs=4096",
                              "echo VIRTUAL_FIRMWARE_IDENTITY_FILES_READY"]
                if args.seed_power_on:
                    setup += [f"/simulation/seed-power-on {boot_type}",
                              "echo POWER_ON_SEED_STATUS=$?"]
                if args.load_power:
                    setup += ["insmod /usr/kmod/upm.ko"]
                if os.environ.get('MENU_DATE_SERVICE') == '1':
                    # The native date/settings API is served by this original driver.
                    setup += ["if { test -d /sys/module/udate || insmod /usr/kmod/udate.ko; } && /simulation/seed-date-clock; then touch /tmp/date-clock.ready; echo DATE_CLOCK_INIT_OK; else echo DATE_CLOCK_INIT_FAILED; fi"]
                if audio_boot_config:
                    setup += ["mkdir -p /log/qemu; if /simulation/system-sound-owner; then touch /tmp/system-sound.ready; echo SYSTEM_SOUND_INIT_OK; else echo SYSTEM_SOUND_INIT_FAILED; fi"]
                if args.load_kikilog:
                    setup += ["insmod /usr/kmod/kikilog.ko", "ls -l /dev/usb/kikilog"]
                if args.no_cp_updater:
                    setup += ["export QEMU_NO_CP_UPDATER=1"]
                if args.capid_service:
                    setup += ["export QEMU_CAPID_SERVICE=1"]
                if args.sa_address_service:
                    setup += ["export QEMU_SA_ADDRESS_SERVICE=1"]
                if args.hdmi_format_service:
                    setup += ["export QEMU_HDMI_FORMAT_SERVICE=1"]
                if args.hdmi_photo_service:
                    setup += ["export QEMU_HDMI_PHOTO_SERVICE=1"]
                if args.dmm_service:
                    setup += ["export QEMU_DMM_SERVICE=1"]
                if args.software_gpe:
                    setup += ["export QEMU_SOFTWARE_GPE=1"]
                if args.headless_osd:
                    setup += ["export MENU_HEADLESS_OSD=1"]
                if args.native_display is not None:
                    setup += ["/simulation/ramfb-viewer >/dev/null &",
                              "echo RAMFB_VIEWER_PID=$!"]
                if os.environ.get("MENU_GPE_RGBA4444"):
                    setup += ["export QEMU_GPE_RGBA4444=1"]
                if args.display_info_service:
                    setup += ["export QEMU_DISPLAY_INFO_SERVICE=1"]
                if os.environ.get("MENU_BB_READY_LATE"):
                    # Experiment E2 (screen-blocker/REPORT.md): hold the single 0x2003/0x8201
                    # fulfilment until after the cold-boot chain and an injected key.
                    setup += ["export MENU_BB_READY_LATE=1"]
                if os.environ.get("MENU_SUBSCRIPTION_SERVICE"):
                    setup += ["export QEMU_SUBSCRIPTION_SERVICE=1"]
                if os.environ.get("MENU_SUBSCRIPTION_EVENT"):
                    setup += ["export QEMU_SUBSCRIPTION_EVENT=1"]
                if os.environ.get("MENU_SCREEN_REGISTRY"):
                    setup += ["export MENU_SCREEN_REGISTRY=1"]
                if os.environ.get("MENU_SYNC_DIRECT"):
                    setup += ["export MENU_SYNC_DIRECT=1"]
                if os.environ.get("MENU_ENTRY_PROBES"):
                    setup += ["export MENU_ENTRY_PROBES=1"]
                if os.environ.get("MENU_LIVEVIEW_TRACE") == '1':
                    setup += ["export MENU_LIVEVIEW_TRACE=1"]
                if os.environ.get('MENU_NATURAL_START_TRACE') == '1':
                    setup += ["export MENU_NATURAL_START_TRACE=1"]
                if os.environ.get("MENU_JPEG_REQUEST_TRACE") == '1':
                    setup += ["export MENU_JPEG_REQUEST_TRACE=1"]
                if os.environ.get('MENU_INPUT_ROUTE_TRACE') == '1':
                    setup += ['export MENU_INPUT_ROUTE_TRACE=1']
                if input_route_detail:
                    setup += [f'export MENU_INPUT_ROUTE_DETAIL={input_route_detail}']
                if media_init_watch:
                    setup += ['export MENU_MEDIA_INIT_WATCH=1']
                if os.environ.get('A7C2_CAPTURE_POWER')=='1':
                    setup += ['export MENU_POWER_OBSERVE=1']
                if os.environ.get('A7C2_CAPTURE_INPUT_EVENTS')=='1':
                    setup += ['export MENU_OBSERVE_INPUT=1']
                if os.environ.get('A7C2_OSD_SUBMIT_TRACE')=='1':
                    setup += ['export MENU_OSD_SUBMIT_TRACE=1']
                if os.environ.get('A7C2_OSD_META_PIXELS')=='1':
                    setup += ['export MENU_OSD_META_PIXELS=1']
                if os.environ.get("MENU_RUN_I_GATE"):
                    setup += ["export MENU_RUN_I_GATE=1"]
                if input_key_mode:
                    setup += ["export MENU_INJECT_KEY=%s" % input_key_mode]
                if os.environ.get('MENU_KEY_INJECT') or os.environ.get('MENU_LIVE_APP_INPUT')=='1':
                    setup += ['export MENU_OBSERVE_INPUT=1']
                if live_key_file:
                    setup += ['export MENU_LIVE_KEY_FILE=/tmp/menu-key.request',
                              'export MENU_OBSERVE_INPUT=1']
                if rm_file:
                    setup += ['export MENU_RM_FILE=1']
                if gui_models:
                    setup += ['export MENU_GUI_MODELS=virtual-inline-v1']
                if cp_background:
                    setup += ['export MENU_CP_BACKGROUND=virtual-mode3-cold-v1']
                if touch_panel:
                    setup += ['export MENU_TOUCH_PANEL=virtual-config-v1']
                if tcin_detect:
                    setup += ['export MENU_TCIN_DETECT=virtual-inactive-v1']
                if vef_path_profile:
                    setup += ['export MENU_VEF_PATH=virtual-nomem-v1']
                if adf_proc_path_profile:
                    setup += ['export MENU_ADF_PROC_PATH=virtual-source7-idle-v1']
                if adf_set_input_profile:
                    setup += ['export MENU_ADF_SET_INPUT=virtual-input-s0-v1']
                if adf_set_output_profile:
                    # Admission above validated these markers; their services remain kernel/QEMU-owned.
                    setup += ['export MENU_BACKUP_SYNC=virtual-primary-v1',
                              'export MENU_UDATE_DISTRIBUTION=virtual-roundtrip-v1',
                              'export MENU_DFS_SELECTOR=virtual-selector-v1',
                              'export MENU_PIN_CONTROL_MEMORY=1',
                              'export MENU_ADF_SET_OUTPUT=virtual-output-nochange-v1']
                if bb_set_mode_profile:
                    setup += ['export MENU_BB_SET_MODE=virtual-bb-still-target3-op0-v1']
                if (imaging_pin_connection_profile and imaging_pin_connection_profile==IMAGING_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONNECT')==IMAGING_CONNECT_PROFILE and
                        bb_set_mode_profile==BB_SET_MODE_PROFILE):
                    setup += ['export MENU_IMAGING_CONNECT=virtual-imaging-out1-bb-in1-v1']
                if (imaging_control_connection_profile and imaging_control_connection_profile==IMAGING_CONTROL_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONTROL_CONNECT')==IMAGING_CONTROL_CONNECT_PROFILE and
                        imaging_pin_connection_profile==IMAGING_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONNECT')==IMAGING_CONNECT_PROFILE and
                        bb_set_mode_profile==BB_SET_MODE_PROFILE):
                    setup += ['export MENU_IMAGING_CONTROL_CONNECT=virtual-imaging-control0-bb-control0-v1']
                if (imaging_adf_connection_profile and imaging_adf_connection_profile==IMAGING_ADF_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_ADF_CONNECT')==IMAGING_ADF_CONNECT_PROFILE and
                        imaging_control_connection_profile==IMAGING_CONTROL_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONTROL_CONNECT')==IMAGING_CONTROL_CONNECT_PROFILE and
                        imaging_pin_connection_profile==IMAGING_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONNECT')==IMAGING_CONNECT_PROFILE and
                        bb_set_mode_profile==BB_SET_MODE_PROFILE):
                    setup += ['export MENU_IMAGING_ADF_CONNECT=virtual-imaging-audio0-adf-audio0-v1']
                if (infrabb_vef_connection_profile==INFRABB_VEF_CONNECT_PROFILE and
                        os.environ.get('A7C2_INFRABB_VEF_CONNECT')==INFRABB_VEF_CONNECT_PROFILE and
                        imaging_adf_connection_profile==IMAGING_ADF_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_ADF_CONNECT')==IMAGING_ADF_CONNECT_PROFILE and
                        imaging_control_connection_profile==IMAGING_CONTROL_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONTROL_CONNECT')==IMAGING_CONTROL_CONNECT_PROFILE and
                        imaging_pin_connection_profile==IMAGING_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONNECT')==IMAGING_CONNECT_PROFILE and
                        bb_set_mode_profile==BB_SET_MODE_PROFILE):
                    setup += ['export MENU_INFRABB_VEF_CONNECT=virtual-infrabb-out1-vef-in1-same-format-v1']
                if (infrabb_vef_control_connection_profile==FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE and
                        os.environ.get('A7C2_INFRABB_VEF_CONTROL_CONNECT')==FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE and
                        infrabb_vef_connection_profile==INFRABB_VEF_CONNECT_PROFILE and
                        os.environ.get('A7C2_INFRABB_VEF_CONNECT')==INFRABB_VEF_CONNECT_PROFILE and
                        imaging_adf_connection_profile==IMAGING_ADF_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_ADF_CONNECT')==IMAGING_ADF_CONNECT_PROFILE and
                        imaging_control_connection_profile==IMAGING_CONTROL_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONTROL_CONNECT')==IMAGING_CONTROL_CONNECT_PROFILE and
                        imaging_pin_connection_profile==IMAGING_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONNECT')==IMAGING_CONNECT_PROFILE and
                        bb_set_mode_profile==BB_SET_MODE_PROFILE):
                    setup += ['export MENU_INFRABB_VEF_CONTROL_CONNECT=virtual-infrabb-control0-vef-control0-v1']
                if (vef_pinmem_input_connection_profile==FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE and
                        os.environ.get('A7C2_VEF_PINMEM_INPUT_CONNECT')==FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE and
                        infrabb_vef_control_connection_profile==FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE and
                        os.environ.get('A7C2_INFRABB_VEF_CONTROL_CONNECT')==FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE and
                        infrabb_vef_connection_profile==INFRABB_VEF_CONNECT_PROFILE and
                        os.environ.get('A7C2_INFRABB_VEF_CONNECT')==INFRABB_VEF_CONNECT_PROFILE and
                        imaging_adf_connection_profile==IMAGING_ADF_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_ADF_CONNECT')==IMAGING_ADF_CONNECT_PROFILE and
                        imaging_control_connection_profile==IMAGING_CONTROL_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONTROL_CONNECT')==IMAGING_CONTROL_CONNECT_PROFILE and
                        imaging_pin_connection_profile==IMAGING_CONNECT_PROFILE and
                        os.environ.get('A7C2_IMAGING_CONNECT')==IMAGING_CONNECT_PROFILE and
                        bb_set_mode_profile==BB_SET_MODE_PROFILE):
                    setup += ['export MENU_VEF_PINMEM_INPUT_CONNECT=virtual-vef-out2-pinmem-in0-forward-format-v1']
                if (vef_pinmem_control_connection_profile==FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE and
                        os.environ.get('A7C2_VEF_PINMEM_CONTROL_CONNECT')==FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE and
                        'export MENU_VEF_PINMEM_INPUT_CONNECT='+FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE in setup):
                    setup += ['export MENU_VEF_PINMEM_CONTROL_CONNECT=virtual-vef-control0-pinmem-control0-v1']
                if (pinmem_peer_connections_profile==FULL_PINMEM_PEER_CONNECTIONS_PROFILE and
                        os.environ.get('A7C2_PINMEM_PEER_CONNECT')==FULL_PINMEM_PEER_CONNECTIONS_PROFILE and
                        'export MENU_VEF_PINMEM_CONTROL_CONNECT='+FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE in setup):
                    setup += ['export MENU_PINMEM_PEER_CONNECT=virtual-pinmem-scalar-adf-drawinfo-chain-v1']
                if (pinmem_hdmi_video_connection_profile==FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE and
                        os.environ.get('A7C2_PINMEM_HDMI_VIDEO_CONNECT')==FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE and
                        'export MENU_PINMEM_PEER_CONNECT='+FULL_PINMEM_PEER_CONNECTIONS_PROFILE in setup):
                    setup += ['export MENU_PINMEM_HDMI_VIDEO_CONNECT='+FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE]
                if (pinmem_osd_connection_profile==FULL_PINMEM_OSD_CONNECTION_PROFILE and
                        os.environ.get('A7C2_PINMEM_OSD_CONNECT')==FULL_PINMEM_OSD_CONNECTION_PROFILE and
                        'export MENU_PINMEM_PEER_CONNECT='+FULL_PINMEM_PEER_CONNECTIONS_PROFILE in setup):
                    setup += ['export MENU_PINMEM_OSD_CONNECT='+FULL_PINMEM_OSD_CONNECTION_PROFILE]
                if (adf_hdmi_audio_connection_profile==FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE and
                        os.environ.get('A7C2_ADF_HDMI_AUDIO_CONNECT')==FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE and
                        'export MENU_PINMEM_PEER_CONNECT='+FULL_PINMEM_PEER_CONNECTIONS_PROFILE in setup):
                    setup += ['export MENU_ADF_HDMI_AUDIO_CONNECT=virtual-adf-audio0-hdmi-audio0-v1']
                if (cp302c_no_transition_profile==FULL_CP302C_NO_TRANSITION_PROFILE and
                        os.environ.get('A7C2_CP302C_NO_TRANSITION')==FULL_CP302C_NO_TRANSITION_PROFILE and
                        not os.environ.get('MENU_CP302C_DIAGNOSTIC') and
                        not os.environ.get('A7C2_CP302C_DIAGNOSTIC') and
                        'export MENU_CP_BACKGROUND=virtual-mode3-cold-v1' in setup and
                        'export MENU_PINMEM_HDMI_VIDEO_CONNECT='+FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE in setup and
                        'export MENU_PINMEM_OSD_CONNECT='+FULL_PINMEM_OSD_CONNECTION_PROFILE in setup and
                        'export MENU_ADF_HDMI_AUDIO_CONNECT='+FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE in setup):
                    setup += ['export MENU_CP302C_NO_TRANSITION='+FULL_CP302C_NO_TRANSITION_PROFILE]
                if (cp302c_diagnostic_profile=='diagnostic-cp302c-reply-only-v1' and
                        os.environ.get('A7C2_CP302C_DIAGNOSTIC')=='diagnostic-cp302c-reply-only-v1' and
                        not os.environ.get('MENU_CP302C_NO_TRANSITION') and
                        not os.environ.get('A7C2_CP302C_NO_TRANSITION') and
                        'export MENU_CP_BACKGROUND=virtual-mode3-cold-v1' in setup and
                        'export MENU_PINMEM_HDMI_VIDEO_CONNECT='+FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE in setup and
                        'export MENU_PINMEM_OSD_CONNECT='+FULL_PINMEM_OSD_CONNECTION_PROFILE in setup and
                        'export MENU_ADF_HDMI_AUDIO_CONNECT='+FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE in setup):
                    setup += ['export MENU_CP302C_DIAGNOSTIC=diagnostic-cp302c-reply-only-v1']
                if (cp_notification_control_profile=='virtual-cp-notification-mode0-v1' and
                        os.environ.get('A7C2_CP_NOTIFICATION_CONTROL')=='virtual-cp-notification-mode0-v1' and
                        'export MENU_CP302C_DIAGNOSTIC=diagnostic-cp302c-reply-only-v1' in setup):
                    setup += ['export MENU_CP_NOTIFICATION_CONTROL=virtual-cp-notification-mode0-v1']
                if (cp_capture_format_profile in ('diagnostic-cp402d-reply-only-v1','diagnostic-cp-startup-controls-v1','diagnostic-cp-ee-controls-v1','diagnostic-cp-movie-format-v1','virtual-cp-owned-state-v1') and
                        os.environ.get('A7C2_CP_CAPTURE_FORMAT')==cp_capture_format_profile and
                        'export MENU_CP_NOTIFICATION_CONTROL=virtual-cp-notification-mode0-v1' in setup):
                    setup += ['export MENU_CP_CAPTURE_FORMAT='+cp_capture_format_profile]
                if (functional_camera_profile == FUNCTIONAL_CAMERA_PROFILE and
                        os.environ.get('A7C2_FUNCTIONAL_CAMERA') == FUNCTIONAL_CAMERA_PROFILE and
                        'export MENU_CP_CAPTURE_FORMAT='+FULL_CP_OWNED_STATE_PROFILE in setup):
                    setup += ['export MENU_FUNCTIONAL_CAMERA='+FUNCTIONAL_CAMERA_PROFILE]
                if os.environ.get("MENU_VDF_CONFIG") == "1":
                    setup += ["export MENU_VDF_CONFIG=1"]
                if os.environ.get("MENU_HDMI_BOOT_CONFIG") == "1":
                    setup += ["export MENU_HDMI_BOOT_CONFIG=1"]
                if os.environ.get("MENU_AUDIO_BOOT_CONFIG") == "1":
                    setup += ["export MENU_AUDIO_BOOT_CONFIG=1"]
                if dig_level_mode:
                    setup += ["export MENU_DIG_LEVEL=virtual"]
                if panel_reverse_mode:
                    setup += ["export MENU_PANEL_REVERSE=virtual"]
                if dmm_unit_config:
                    setup += ["export MENU_DMM_UNIT_CONFIG=1"]
                if os.environ.get("MENU_PIN_REGISTRY") == "1":
                    setup += ["export MENU_PIN_REGISTRY=1"]
                if pin_connection_mode:
                    setup += ["mkdir -p /log/qemu", "export MENU_PIN_CONNECTION=cold"]
                if os.environ.get("MENU_ASSERT_PROBE"):
                    setup += ["export MENU_ASSERT_PROBE=1"]
                if os.environ.get("MENU_OPTION_PROBES"):
                    setup += ["export MENU_OPTION_PROBES=1"]
                if os.environ.get("MENU_CP_TIME_SERVICE"):
                    setup += ["export MENU_CP_TIME_SERVICE=1"]
                if os.environ.get("MENU_CRYPT_LIB"):
                    setup += ["export MENU_CRYPT_LIB=1"]
                if os.environ.get("MENU_SYNC_MSG_HOOK"):
                    setup += ["export MENU_SYNC_MSG_HOOK=1"]
                if os.environ.get("MENU_SYNC_CALL_PROBE"):
                    setup += ["export MENU_SYNC_CALL_PROBE=1"]
                if os.environ.get("MENU_BUSPOWER"):
                    setup += ["export MENU_BUSPOWER=1"]
                if os.environ.get("MENU_REG_SILENT"):
                    setup += ["export MENU_REG_SILENT=1"]
                if os.environ.get("MENU_PIPELINE_ENDPOINT"):
                    setup += ["export MENU_PIPELINE_ENDPOINT=1"]
                if os.environ.get("MENU_PIPELINE_VIRT"):
                    setup += ["export MENU_PIPELINE_VIRT=1"]
                if os.environ.get("MENU_PIPELINE_SRC"):
                    setup += ["export MENU_PIPELINE_SRC=%s" % os.environ["MENU_PIPELINE_SRC"]]
                if os.environ.get("MENU_APPLY_SWEEP"):
                    setup += ["export MENU_APPLY_SWEEP=%s" % os.environ["MENU_APPLY_SWEEP"]]
                if os.environ.get("MENU_APPLY_TARGET"):
                    setup += ["export MENU_APPLY_TARGET=%s" % os.environ["MENU_APPLY_TARGET"]]
                if os.environ.get("MENU_INFRA_AVBBC"):
                    setup += ["export MENU_INFRA_AVBBC=1"]
                if os.environ.get("MENU_HONEST_ROUTING"):
                    setup += ["export MENU_HONEST_ROUTING=%s" % os.environ["MENU_HONEST_ROUTING"]]
                if os.environ.get("MENU_QUEUE_STACKS"):
                    setup += ["export MENU_QUEUE_STACKS=1"]
                if os.environ.get("MENU_ASYNC_SEND"):
                    setup += ["export MENU_ASYNC_SEND=1"]
                if os.environ.get("MENU_CP_RELEASE_SERVICE"):
                    setup += ["export MENU_CP_RELEASE_SERVICE=1"]
                if os.environ.get("MENU_CTOR_CENSUS"):
                    setup += ["export MENU_CTOR_CENSUS=1"]
                if os.environ.get("MENU_OSD_OBSERVE") or os.environ.get("MENU_SOFTWARE_LZ77"):
                    setup += ["export MENU_OSD_OBSERVE=1"]
                if os.environ.get("MENU_SOFTWARE_LZ77"):
                    setup += ["export QEMU_SOFTWARE_LZ77=1"]
                if os.environ.get("MENU_FRAME_OBSERVE") or os.environ.get("MENU_APPLY_MENU"):
                    setup += ["export MENU_FRAME_OBSERVE=1"]
                if os.environ.get("MENU_APPLY_MENU"):
                    setup += ["export MENU_APPLY_MENU=1"]
                if os.environ.get("MENU_ACTIVATE_CAPTURED"):
                    setup += ["export MENU_ACTIVATE_CAPTURED=" + os.environ["MENU_ACTIVATE_CAPTURED"]]
                if os.environ.get("MENU_OPEN_SET"):
                    setup += ["export MENU_OPEN_SET=" + os.environ["MENU_OPEN_SET"]]
                if os.environ.get("MENU_OPEN_SET_LOG_ONLY"):
                    setup += ["export MENU_OPEN_SET_LOG_ONLY=1"]
                if os.environ.get("MENU_OPEN_SET_EXECUTE"):
                    setup += ["export MENU_OPEN_SET_EXECUTE=1"]
                if os.environ.get("MENU_UI_THREAD_ONLY"):
                    setup += ["export MENU_UI_THREAD_ONLY=1"]
                if os.environ.get("MENU_BUILD2_THEN_INIT"):
                    setup += ["export MENU_BUILD2_THEN_INIT=1"]
                if os.environ.get("MENU_BUILD_CONTROLLER2"):
                    setup += ["export MENU_BUILD_CONTROLLER2=" + os.environ["MENU_BUILD_CONTROLLER2"]]
                if os.environ.get("MENU_MODE_SENTINELS"):
                    setup += ["export MENU_MODE_SENTINELS=1"]
                if os.environ.get("MENU_MODE_SLOTS"):
                    setup += ["export MENU_MODE_SLOTS=1"]
                if os.environ.get("MENU_ACTIVATE_MODE"):
                    setup += ["export MENU_ACTIVATE_MODE=" + os.environ["MENU_ACTIVATE_MODE"]]
                if os.environ.get("MENU_FORCE_OPEN_AFTER"):
                    setup += ["export MENU_FORCE_OPEN_AFTER=1"]
                if os.environ.get("MENU_FORCE_IN_FACTORY"):
                    setup += ["export MENU_FORCE_IN_FACTORY=1"]
                if os.environ.get("MENU_STDIO_KMSG"):
                    setup += ["export MENU_STDIO_KMSG=1"]
                if os.environ.get("MENU_INIT_LOG_ONLY"):
                    setup += ["export MENU_INIT_LOG_ONLY=1"]
                if os.environ.get("MENU_BUILD_CONTROLLER"):
                    setup += ["export MENU_BUILD_CONTROLLER=" + os.environ["MENU_BUILD_CONTROLLER"]]
                if os.environ.get("MENU_OPEN_SCREEN"):
                    setup += ["export MENU_OPEN_SCREEN=1"]
                if os.environ.get("MENU_MENU_INIT"):
                    setup += ["export MENU_MENU_INIT=1"]
                if os.environ.get("MENU_INIT_SELECTOR"):
                    setup += ["export MENU_INIT_SELECTOR=" + os.environ["MENU_INIT_SELECTOR"]]
                if os.environ.get("MENU_FORCE_SET"):
                    setup += ["export MENU_FORCE_SET=" + os.environ["MENU_FORCE_SET"]]
                if os.environ.get("MENU_FACTORY_HOOK"):
                    setup += ["export MENU_FACTORY_HOOK=1"]
                if os.environ.get("MENU_UX_NOTIFY_DRAW"):
                    setup += ["export MENU_UX_NOTIFY_DRAW=1"]
                if os.environ.get("MENU_TASK_MAIN_EVENTS"):
                    setup += ["export MENU_TASK_MAIN_EVENTS=1"]
                if os.environ.get("MENU_SEQ_EVENT"):
                    setup += ["export MENU_SEQ_EVENT=1"]
                if os.environ.get("MENU_SEQ_EVENT_SEL"):
                    setup += ["export MENU_SEQ_EVENT_SEL=" + os.environ["MENU_SEQ_EVENT_SEL"]]
                if os.environ.get("MENU_DISPLAY_SIZE"):
                    setup += [f"export QEMU_DISPLAY_SIZE={os.environ['MENU_DISPLAY_SIZE']}"]
                if os.environ.get("MENU_DISPLAY_ASPECT"):
                    setup += [f"export QEMU_DISPLAY_ASPECT={os.environ['MENU_DISPLAY_ASPECT']}"]
                if args.menu_target:
                    setup += ["export LD_LIBRARY_PATH=/simulation:/usr/lib:/lib",
                              "ls -l /simulation/libIMDB.so",
                              "unset LD_DEBUG"]
                if args.observe:
                    setup += ["MENU_OBSERVE_SELFTEST=1 LD_PRELOAD=/simulation/menu-observe.so /simulation/check-menu-observe",
                              "echo OBSERVER_CHECK_STATUS=$?", "/simulation/menu-regs --selftest", "echo REGS_SELFTEST_STATUS=$?", "rm -f /tmp/menu-load.log",
                              "rm -f /tmp/gpe-requests.bin",
                              "/simulation/menu-readmem /usr/lib/appFw.so 0 16 > /tmp/readmem-check.txt",
                              "/simulation/menu-readmem /usr/lib/appFw.so 0 4097; bad=$?; /simulation/menu-readmem /proc/self/mem 0 4 libc-2.25.so > /tmp/readmem-module-check.txt; mapped=$?; if [ $bad -eq 2 ] && [ $mapped -eq 0 ] && grep -q 'bytes=16' /tmp/readmem-check.txt && grep -q '7f 45 4c 46' /tmp/readmem-module-check.txt; then echo READMEM_CHECK_PASS; else echo READMEM_CHECK_FAILED; fi"]
                if live_fd:
                    # Research logs are unbounded; the live UI only needs immutable OSD exports.
                    setup += ["rm -f /tmp/menu-load.log /tmp/gpe-requests.bin /tmp/im.log",
                              "ln -s /dev/null /tmp/menu-load.log; ln -s /dev/null /tmp/gpe-requests.bin"]
                    if not virtual_hci:setup += ['ln -s /dev/null /tmp/im.log']
                preloads = []
                if virtual_hci:
                    setup += ['cp /simulation/start-bt-virtual.sh /usr/bin/startBTCore.sh',
                              '/usr/bin/openssl dgst -sha256 /usr/bin/startBTCore.sh']
                media_selftest = os.environ.get('MENU_MEDIA_SELFTEST') == '1'
                if media_selftest:
                    if live_fd or args.native_display is not None or args.headless_osd:
                        raise RuntimeError('Media selftest requires an exclusive non-display guest')
                if media_selftest or rm_file:
                    if os.environ.get('A7C2_SD_HOTPLUG')=='1':
                        setup += ['export A7C2_SD_HOTPLUG=1']
                    if os.environ.get('A7C2_FSYS_CONTENT_OBSERVE')=='1':
                        setup += ['export A7C2_FSYS_CONTENT_OBSERVE=1']
                    if os.environ.get('A7C2_FSYS_ASYNC_OBSERVE')=='1':
                        setup += ['export A7C2_FSYS_ASYNC_OBSERVE=1']
                    if rm_file and rm_slot1:
                        setup += ['export MENU_RM_FILE_SLOT=0']
                    setup += ['export A7C2_FILE_MEDIA_TEST=1']
                    if host_sd_fd is not None or directory_sd_fd is not None:
                        setup += ['for m in scsi_mod sd_mod usb-storage xhci-hcd xhci-plat-hcd; do '
                                  'insmod /usr/kmod/$m.ko 2>/dev/null || true; done',
                                  'sleep 3; test -b /dev/sda && : > /image_mmca && '
                                  'mount -o bind /dev/sda /image_mmca && '
                                  '/simulation/host-sd-probe sync && echo ready > /tmp/host-sd.ready',
                                  'export A7C2_HOST_BLOCK_SD=1']
                        preloads.append('/simulation/host-block-sd.so')
                    elif sd_sparse:
                        setup += ['export MENU_RM_SPARSE=10g-empty',
                                  'mkdir /tmp/sony-sd10g && '
                                  'mount -t tmpfs -o size=512m tmpfs /tmp/sony-sd10g && '
                                  '/simulation/sd-sparse create && : > /image_mmca && '
                                  'mount -o bind /tmp/sony-sd10g/card.img /image_mmca && '
                                  'echo ready > /tmp/sd10g.ready']
                    else:
                        setup += ['cp /simulation/'+('sd-card.fat' if sd_seed else 'media-camera.fat' if rm_file else 'media-template.fat')+' /image_mmca']
                    preloads.append('/simulation/file-media-config.so')
                if os.environ.get('MENU_TRACE_MUTEX') == '1':
                    setup += ['export MUTEX_TRACE_CONSOLE=1']
                    preloads.append('/simulation/mutex-trace.so')
                if args.observe:
                    preloads.append('/simulation/menu-observe.so')
                prefix = 'LD_PRELOAD=' + ':'.join(preloads) + ' ' if preloads else ''
                if sd_sparse:
                    prefix = 'test -f /tmp/sd10g.ready && ' + prefix
                if host_sd_fd is not None or directory_sd_fd is not None:
                    prefix = 'test -f /tmp/host-sd.ready && ' + prefix
                if os.environ.get('MENU_DATE_SERVICE') == '1':
                    prefix = 'test -f /tmp/date-clock.ready && ' + prefix
                if audio_boot_config:
                    prefix = 'test -f /tmp/system-sound.ready && ' + prefix
                if media_selftest:
                    setup += ['(' + prefix + '/simulation/fsys-file-test front-owner && ' + prefix +
                              '/simulation/fsys-file-test queue && ' + prefix +
                              '/simulation/fsys-file-test queue-idle && ' + prefix + '/simulation/fsys-file-test && ' + prefix +
                              '/simulation/fsys-file-test verify; echo $? > /tmp/media-test.rc) > /tmp/media-test.log 2>&1 &']
                elif args.bootin:
                    setup += [prefix + "/usr/bin/bootin.elf 'target=qemu ' dmode=3 > /tmp/im.log 2>&1 &"]
                else:
                    options = ' target=qemu' + (' bootall' if args.bootall else '')
                    setup += [prefix + "/usr/bin/im.elf" + options + " > /tmp/im.log 2>&1 &"]
                setup += ["echo IM_LAUNCH_PID=$!"]
                proc.stdin.write(("\n".join(setup) + "\n").encode())
                proc.stdin.flush()
                if media_selftest:
                    from menu_live import serial_command
                    result = serial_command(proc, out / 'console.log',
                        'while [ ! -f /tmp/media-test.rc ]; do sleep 1; done; cat /tmp/media-test.log; test "$(cat /tmp/media-test.rc)" = 0', timeout=90)
                    if b'FSYS_FILE_TEST_DONE result=0 verify_only=1 mount_flags=0x100' not in result:
                        raise RuntimeError('Original Fsys verification marker missing')
                    if (b'RM_QUEUE_TRANSPORT_PASS bytes=32 scope=transport_only_not_media_ready' not in result or
                            result.count(b'RM_QUEUE_IDLE_PASS')!=2):
                        raise RuntimeError('Original RM queue transport/cleanup test marker missing')
                    if not re.search(rb'FRONT_OWNER_RESULT allocation_rc=0 size=7 source=0x8028017c content=1 free_rc=0 scope=allocation_only_not_media_notification\r?\n',result):
                        raise RuntimeError('Original Front allocation/source/free readback marker missing')
                    qmp('pmemsave', {'val': 0x41e600000, 'size': 0x400000, 'filename': '/out/media-disk.img'})
                    qmp('quit')
                    print('FSYS_MEDIA_IMAGE_CAPTURED ' + str(out / 'media-disk.img'), flush=True)
                    raise SystemExit(0)
                settle = int(os.environ.get("MENU_SETTLE_SECONDS", "90"))
                settle_deadline = time.monotonic() + settle
                crashed_during_settle = False
                # Candidate raster from an earlier run. Address stability and pixel format remain
                # unverified; these memory samples alone do not prove a displayed frame.
                screen_dumps = 0
                next_screen_dump = time.monotonic() + 10
                ulog_dump_at = yc_inject == '1'
                while time.monotonic() < settle_deadline:
                    if functional_camera is not None:
                        functional_camera.check()
                    if manifest['rc_board_profile']:
                        # Data/job evidence must not depend on the later YCSTAT timer.
                        observed=(out/'console.log').read_text(errors='replace')
                        from rc_reference_evidence import capture
                        capture(qmp,out,observed)
                        from sa_job_evidence import capture as capture_sa
                        if not manifest.get('sa_reference_completion') or not (out/'sa2-job-readback.json').exists():
                            capture_sa(qmp,out,observed)
                        if manifest['sa_reference_data_only']:
                            from sa_data_evidence import capture as capture_nv12
                            capture_nv12(qmp,out)
                    if ulog_dump_at and b'YCSTAT:' in (out / 'console.log').read_bytes():
                        ulog_dump_at = None
                        # av-cam runtime logs (RcvPrm, errors) live in the ulogio workspace, not
                        # the console. Dump right after the queue-stat marker (guest is provably
                        # alive then; its power sequence ends the VM at a variable wall time).
                        qmp('pmemsave', {'val': 0x405000000, 'size': 0x800000, 'filename': '/out/menu-ulogio.bin'})
                        # 0x639 output pool ground truth: if YUV_CONV really converts, av-cam
                        # allocates a 0x639 unit (survey: pool at 0x4f8500000, 0x1518000/slot)
                        # and writes the NV12 result there. Dump 4 slots; content check is
                        # host-side (zeros = conversion never ran).
                        qmp('pmemsave', {'val': 0x4f8500000, 'size': 0x5460000, 'filename': '/out/nv12-pool.bin'})
                        # Observer memory log (record() buffer, phys 0x4102d0000): carries the
                        # non-mirrored prefixes (SA_ADDRESS_REQUEST etc.) that never reach console.
                        qmp('pmemsave', {'val': 0x4102d0000, 'size': 0x10000, 'filename': '/out/menu-loader.bin'})
                        # Ground truth for the injected SSYC/frame: the DMM unit's real address
                        # comes from the op2a reply logged in this run (NOT the constant field
                        # in the alloc reply). Dump the first pages so host-side analysis sees
                        # exactly what av-cam's open would read.
                        console = (out / 'console.log').read_bytes()
                        unit = re.search(rb'YCIN_DMM: op2a handle=\S+ segs=\d+ addr=(0x[0-9a-f]+) len=(0x[0-9a-f]+)', console)
                        if unit:
                            qmp('pmemsave', {'val': int(unit.group(1), 16), 'size': 0x2000,
                                             'filename': '/out/yc-unit.bin'})
                        if os.environ.get('MENU_YC_INPUT_RAW') or yc_uncompressed:
                            pixel_type = b'431' if yc_uncompressed else b'643'
                            pixel = re.search(rb'YCIN_DMM: type=0x'+pixel_type+rb' handle=(0x[0-9a-f]+) addr=(0x[0-9a-f]+) len=(0x[0-9a-f]+)', console)
                            pixel_bytes = 1920*1080*5//2 if yc_uncompressed else 1920*1080
                            if (pixel and int(pixel.group(3),16) >= pixel_bytes and
                                    0x400000000 <= int(pixel.group(2),16) <= 0x500000000-pixel_bytes):
                                qmp('pmemsave', {'val': int(pixel.group(2), 16), 'size': pixel_bytes,
                                                 'filename': '/out/yc-pixel-readback.bin'})
                                (out/'yc-pixel-readback.json').write_text(json.dumps(dict(
                                    unit_type=int(pixel_type,16),handle=int(pixel.group(1),16),
                                    physical_address=int(pixel.group(2),16),bytes=pixel_bytes))+'\n')
                        if manifest['rc_board_profile']:
                            from rc_reference_evidence import capture
                            capture(qmp,out,console.decode(errors='replace'))
                            from boot_irq_diagnostics import gic_state
                            (out/'rc-gic-state.json').write_text(json.dumps(gic_state(qmp),indent=2)+'\n')
                            from sa_job_evidence import capture as capture_sa
                            if not manifest.get('sa_reference_completion') or not (out/'sa2-job-readback.json').exists():
                                capture_sa(qmp,out,console.decode(errors='replace'))
                    if audio_boot_config and re.search(rb'(?:^|\n)SYSTEM_SOUND_INIT_FAILED\r?\n', (out / 'console.log').read_bytes()):
                        raise RuntimeError('System sound backing initialization failed; application not started')
                    if re.search(rb'(?:^|\n)DATE_CLOCK_INIT_FAILED\r?\n', (out / 'console.log').read_bytes()):
                        raise RuntimeError('Original date clock initialization failed; application not started')
                    if b'Exception>' in (out / "console.log").read_bytes():
                        crashed_during_settle = True
                        break
                    if time.monotonic() >= next_screen_dump and screen_dumps < 10:
                        qmp('pmemsave', {'val': 0x43a7b4100, 'size': 640 * 480 * 2,
                                         'filename': f'/out/screen-{screen_dumps:02d}.bin'})
                        # Opaque bytes only until pixel channel order and actual OSD submission agree.
                        matches = re.findall(rb'OBS FRAME_BUFFERS call=(\d+) width=(\d+) height=(\d+) bmp_format=(\d+) on=(0x[0-9a-f]+) off=(0x[0-9a-f]+)',
                                             (out / 'console.log').read_bytes())
                        if matches:
                            frame, width, height, fmt = map(int, matches[-1][:4])
                            bpp = {1: 2, 7: 2, 2: 4, 8: 4}.get(fmt, 0)
                            size = width * height * bpp
                            if 0 < width <= 8192 and 0 < height <= 8192 and 0 < size <= 0x1000000:
                                qmp('stop')
                                try:
                                    for role, raw_address in zip(('on', 'off'), matches[-1][4:]):
                                        address = int(raw_address, 16)
                                        if not 0x430400000 <= address <= 0x500000000 - size:
                                            continue
                                        name = f'framebuffer-{role}-{screen_dumps:02d}'
                                        qmp('pmemsave', {'val': address, 'size': size, 'filename': f'/out/{name}.bin'})
                                        (out / f'{name}.json').write_text(json.dumps({
                                            'source': 'observed GRM descriptor; scanout not verified',
                                            'frame_call': frame, 'role': role, 'address': hex(address),
                                            'width': width, 'height': height, 'row_pixels': width,
                                            'bmp_format': fmt, 'bytes': size, 'channel_order_verified': False,
                                            'descriptor_may_have_changed_since_log': True,
                                        }, indent=2) + '\n')
                                finally:
                                    qmp('cont')
                        print(f"SCREEN_DUMP {screen_dumps}", flush=True)
                        screen_dumps += 1
                        next_screen_dump = time.monotonic() + 15
                    time.sleep(1.0)
                if functional_camera is not None and not crashed_during_settle:
                    functional_camera.check()
                if manifest['rc_board_profile']:
                    qmp('pmemsave', {'val':0x405000000,'size':0x800000,'filename':'/out/menu-ulogio.bin'})
                    from boot_irq_diagnostics import gic_state
                    (out/'rc-gic-state.json').write_text(json.dumps(gic_state(qmp),indent=2)+'\n')
                if manifest['natural_start_trace'] and not crashed_during_settle:
                    im_log=serial_command(proc,out/'console.log',
                        "echo IM_LOG_TAIL_BEGIN; /bin/busybox tail -120 /tmp/im.log; echo IM_LOG_TAIL_END",timeout=20)
                    (out/'im-log-tail.txt').write_bytes(im_log)
                if manifest['ee_passive_snapshot'] and not crashed_during_settle:
                    from ee_entry_snapshot import collect_passive
                    passive=collect_passive(lambda command:serial_command(proc,out/'console.log',command,timeout=15),out)
                    print('EE_PASSIVE_SNAPSHOT',json.dumps(dict(app_pid=passive.get('app_pid'),available=passive.get('available',True),
                        reason=passive.get('reason'),cells=passive.get('cells',[]),
                        sampled_threads=passive.get('sampled_threads',0),current_blocker_proven=False)),flush=True)
                    if not passive.get('available',True):
                        inventory=serial_command(proc,out/'console.log',
                            'for c in /proc/[0-9]*/comm; do n=$(cat "$c" 2>/dev/null); case "$n" in '
                            '*bootin*|*im.elf*|*AppFw*) p=${c%/comm}; echo AP_ABSENT_PROCESS=$p name=$n; '
                            'cat "$p/maps";; esac; done; true',timeout=20)
                        (out/'ap-absent-process-maps.txt').write_bytes(inventory)
                if crashed_during_settle:
                    if manifest['rc_board_profile']:
                        from rc_reference_evidence import capture,verify_after_crash
                        capture(qmp,out,(out/'console.log').read_text(errors='replace'))
                        (out/'rc-reference-output-proof.json').write_text(json.dumps(verify_after_crash(out),indent=2)+'\n')
                    qmp('pmemsave', {'val': 0x405000000, 'size': 0x800000,
                                     'filename': '/out/menu-ulogio.bin'})
                    qmp('pmemsave', {'val': 0x4102bb400, 'size': 0x8000,
                                     'filename': '/out/menu-monitor.bin'})
                    qmp('pmemsave', {'val': 0x4102d0000, 'size': 0x10000,
                                     'filename': '/out/menu-loader.bin'})
                    import re as _re
                    _m = _re.search(rb'stackpage: ([0-9a-f]+)', (out / "console.log").read_bytes())
                    if _m:
                        _va = int(_m.group(1), 16)
                        _phys = _va - 0xffffffc000000000 + 0x400000000
                        if 0 < _phys < 0x800000000:
                            qmp('pmemsave', {'val': _phys & ~0xFFF, 'size': 0x4000,
                                             'filename': '/out/crash-stack.bin'})
                            print(f"CRASH_STACK_DUMPED va={hex(_va)} phys={hex(_phys)}", flush=True)
                    print("GUEST_CRASHED_DURING_SETTLE_DUMPS_CAPTURED", flush=True)
                    # Ask the Sony exception monitor for registers and a backtrace
                    # before quitting: the console capture keeps the answer.
                    try:
                        proc.stdin.write(b'help\nbt\nregs\n')
                        proc.stdin.flush()
                        time.sleep(6)
                    except Exception:
                        pass
                    qmp('quit')
                    raise RuntimeError("guest exception monitor during settle")
                if os.environ.get('MENU_DATE_SERVICE') == '1' and not re.search(
                        rb'(?:^|\n)DATE_CLOCK_INIT_OK\r?\n', (out / 'console.log').read_bytes()):
                    raise RuntimeError('Original date clock verification marker missing')
                if language_fonts:
                    font_console=(out/'console.log').read_bytes()
                    for name,(_,digest) in FONT_SPECS.items():
                        actual=re.findall(rb'\(/tmp/images/'+re.escape(name.encode())+rb'\)= ([0-9a-f]{64})\r?$',font_console,re.M)
                        if not actual or any(value.decode()!=digest for value in actual):
                            raise RuntimeError('Guest Chinese font content readback failed: '+name)
                if live_fd:
                    from menu_live import run_live,display_snapshot_message,serial_command,netdev_socket_alias
                    hci_diagnostic=('cat /tmp/virtual-hci.pid /tmp/bsa-virtual.pid; ls -l /tmp_bt; dd if=/tmp/virtual-hci.log bs=1 count=65536; dd if=/tmp/bsa-virtual.log bs=1 count=65536; '
                        'for m in /proc/[0-9]*/maps; do if grep -q /usr/lib/libInfraBluetooth.so "$m"; then p=${m%/maps}; echo BT_MGT_PID=${p##*/}; /simulation/menu-readmem "$p/mem" 0x34509 1 libInfraBluetooth.so; fi; done; '
                        'ls -l /tmp/im.log; grep -E "startBTCore|symbol lookup|error while loading|Permission denied|Segmentation|not found" /tmp/im.log; '
                        '/usr/bin/openssl dgst -sha256 /usr/bin/startBTCore.sh; cat /usr/bin/startBTCore.sh; '
                        'for f in /tmp/bt-launch-*.log; do echo BT_LAUNCH_LOG=$f; cat "$f"; done; true')
                    if virtual_hci:
                        (out/'virtual-hci-startup.txt').write_bytes(serial_command(proc,out/'console.log',hci_diagnostic))
                    if os.environ.get('A7C2_CAPTURE_INPUT_TABLES')=='1':
                        diagnostic="for t in /proc/[0-9]*/task/[0-9]*; do c=$(cat $t/comm 2>/dev/null); echo INPUT_TASK tid=${t##*/} name=$c; case $c in *Input*|*input*) /simulation/input-table ${t##*/};; esac; done"
                        (out/'input-contexts.txt').write_bytes(serial_command(proc,out/'console.log',diagnostic,timeout=120))
                    display_sequence=[0]
                    last_sd_export_sha=[None]
                    pending_sd_sequence=[None]
                    apo_cancel_requested=[False]
                    media_state_readback_done=[False]
                    usb_net_done=[False]
                    ee_snapshot_done=[False]
                    def capture_native_display():
                        if functional_camera is not None:
                            functional_camera.check()
                        if os.environ.get('MENU_YC_INPUT_RAW'):
                            from menu_live import snapshot_message, verified_yc_preview
                            data=serial_command(proc,out/'console.log','/simulation/headless-osd-export')
                            return snapshot_message(data, preview=verified_yc_preview(out))
                        if os.environ.get('A7C2_MODE_READBACK')=='1':
                            command=('for m in /proc/[0-9]*/maps; do '
                                'if /bin/busybox grep -q /usr/lib/appFw.so "$m" 2>/dev/null; then '
                                'p=${m%/maps}; echo MODE_STATE_PID=${p##*/}; '
                                'echo MODE_DIAL; /simulation/menu-readmem "$p/mem" 0x7ee4750 4 appFw.so; '
                                'echo MODE_SWITCH; /simulation/menu-readmem "$p/mem" 0x7ee4778 4 appFw.so; fi; done; true')
                            data=serial_command(proc,out/'console.log',command)
                            (out/('mode-state-%04d.txt'%(display_sequence[0]+1))).write_bytes(data)
                        if os.environ.get('A7C2_TEST_APO_CANCEL')=='1' and not apo_cancel_requested[0]:
                            text=(out/'console.log').read_text(errors='replace')
                            if re.search(r'OBS POWER_NOTICE .*cmd=0x920143 .*word4=0x8\b',text):
                                apo_cancel_requested[0]=True
                                proof={'ok':False,'request_only':True,'original_APO1_observed':True,
                                       'command':0x00920142,'destination':0x80920021,'factor':8,
                                       'original_kernel_cancel_and_UI_transition_require_review':True}
                                (out/'apo-cancel-request-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
                                data=serial_command(proc,out/'console.log','/simulation/inject-key --cancel-apo1')
                                (out/'apo-cancel-request.txt').write_bytes(data)
                        qmp('screendump',{'filename':'/out/ui-display.ppm'})
                        display_sequence[0]+=1
                        return display_snapshot_message(out/'ui-display.ppm',display_sequence[0])
                    def export_virtual_sd():
                        if functional_camera is not None:
                            functional_camera.check()
                        if early_media_watch is not None:
                            cleanup=early_media_watch.stop()
                            (out/'media-init-debug-cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n')
                            if not cleanup.get('safe_to_close'):
                                raise RuntimeError('Pre-init debugger CPU resume unconfirmed; retain VM')
                        if request_queue_gdb:
                            from request_queue_watch import resume_debug_cpu
                            cpu=resume_debug_cpu(qmp)
                            (out/'queue-debug-cpu-resume.json').write_text(json.dumps(cpu,indent=2)+'\n')
                        from sd_transport import export_card,directory,report
                        from sd_export_lifecycle import export_with_flush_lifecycle
                        from sd_flush_barrier import cancel_resume
                        if os.environ.get('A7C2_EE_ENTRY_SNAPSHOT') == '1' and not ee_snapshot_done[0]:
                            ee_snapshot_done[0] = True
                            try:
                                from ee_entry_snapshot import collect
                                evidence = collect(lambda diagnostic: serial_command(
                                    proc, out/'console.log', diagnostic, timeout=30),
                                    (out/'console.log').read_bytes(), out)
                                print('EE_ENTRY_SNAPSHOT', json.dumps(
                                    {'ok': evidence['ok'], 'directory': evidence['snapshot_dir'],
                                     'threads': evidence['thread_count']}), flush=True)
                            except Exception as error:
                                (out/'ee-entry-snapshot-error.json').write_text(json.dumps(
                                    {'error': f'{type(error).__name__}: {error}',
                                     'capture_verified': False}, indent=2)+'\n')
                                if getattr(proc, '_menu_serial_desynchronized', False):
                                    raise
                        def barrier_serial(command,*,timeout=10,cleanup=False):
                            # Only trusted SD management commands reach this closure; preserve recovery after AP faults.
                            return serial_command(proc,out/'console.log',command,timeout=timeout,allow_faulted_cleanup=True)
                        if pending_sd_sequence[0] is not None:
                            cancel_resume(barrier_serial,pending_sd_sequence[0])
                            pending_sd_sequence[0]=None
                        if virtual_hci:
                            try:(out/'virtual-hci-before-save.txt').write_bytes(serial_command(proc,out/'console.log',hci_diagnostic))
                            except Exception as error:(out/'virtual-hci-before-save-error.txt').write_text(str(error)+'\n')
                        if os.environ.get('A7C2_CAPTURE_POWER_STACK')=='1':
                            observed=re.findall(r'OBS CREATE_SCREEN_UI_THREAD pid=(\d+) tid=(\d+)',(out/'console.log').read_text(errors='replace'))
                            if observed:
                                pid,tid=map(int,observed[-1])
                                from request_queue_watch import sequence_stack_command
                                command=sequence_stack_command(pid,tid)
                            else:command='echo POWER_SEQUENCE_STACK_UNAVAILABLE_NO_OBSERVED_UI; true'
                            data=serial_command(proc,out/'console.log',command,timeout=120,allow_faulted_cleanup=True)
                            (out/('power-wait-stack-%d.txt'%time.monotonic_ns())).write_bytes(data)
                        if os.environ.get('MENU_CAPTURE_GATES') == '1':
                            # Read the original capture-gate cells after the body
                            # controls ran. Observation only: nothing is cleared.
                            try:
                                import capture_gate_readback as gates
                                parts = []
                                for diagnostic in gates.commands((out/'console.log').read_bytes()):
                                    parts.append(serial_command(proc, out/'console.log',
                                                                diagnostic, timeout=30))
                                (out/'capture-gates.txt').write_bytes(b'\n'.join(parts))
                                parsed = gates.parse(parts)
                                (out/'capture-gates.json').write_text(json.dumps(parsed, indent=2)+'\n')
                                print('CAPTURE_GATES', json.dumps(
                                    {'reads': len(parsed['reads'])}, ), flush=True)
                            except (OSError, RuntimeError, ValueError) as error:
                                (out/'capture-gates-error.json').write_text(
                                    json.dumps({'error': str(error)}, indent=2)+'\n')
                        sequence=time.monotonic_ns()
                        pending_sd_sequence[0]=sequence
                        def download(request):
                            args=dict(request['arguments'])
                            match=re.fullmatch(r'/proc/'+str(os.getpid())+r'/fd/(\d+)',args['filename'])
                            if request['execute']!='pmemsave' or not match:
                                raise ValueError('Unexpected SD QMP request')
                            descriptor=int(match[1]);opened=os.fstat(descriptor)
                            path=Path(os.readlink(args['filename']))
                            relative=path.relative_to(out)
                            named=path.stat(follow_symlinks=False)
                            if path.is_symlink() or (named.st_dev,named.st_ino)!=(opened.st_dev,opened.st_ino):
                                raise ValueError('SD output inode changed')
                            args['filename']='/out/'+relative.as_posix()
                            return qmp('pmemsave',args)
                        def export_once(flush_and_stop):
                            if directory_sd_fd is not None:
                                from directory_snapshot import snapshot, read_commit_status
                                opened=os.fstat(directory_sd_fd)
                                return snapshot({'fd':directory_sd_fd,'device':opened.st_dev,'inode':opened.st_ino,
                                                 'path':os.environ['A7C2_DIRECTORY_SD']},
                                    quiesce=flush_and_stop,guest_sync=lambda:barrier_serial('/simulation/host-sd-probe sync',timeout=90),
                                    original_mount=lambda:b'HOST_BLOCK_SD_STAGE name=PFDRV_mount caller=Fsys+0x80f54 result=0 ' in (out/'console.log').read_bytes(),
                                    commit_status=lambda:read_commit_status(out/'console.log'))
                            if host_sd_fd is not None:
                                from host_sd_snapshot import snapshot
                                opened=os.fstat(host_sd_fd)
                                return snapshot({'fd':host_sd_fd,'device':opened.st_dev,'inode':opened.st_ino},
                                    quiesce=flush_and_stop,guest_sync=lambda:barrier_serial('/simulation/host-sd-probe sync',timeout=90))
                            return export_card(out,manifest['rm_file_image_bytes'],
                                serial_command=lambda c:barrier_serial(c,timeout=90),qmp=download,
                                expected_old_sha256=last_sd_export_sha[0],quiesce=flush_and_stop,sparse=bool(sd_sparse))
                        def publish_final(result):
                            if result.get('flush_lifecycle',{}).get('ok'):pending_sd_sequence[0]=None
                            if result.get('card_published'):last_sd_export_sha[0]=result['sha256']
                            if directory_sd_fd is not None:
                                # export_card() creates SD for the old image path;
                                # directory snapshots publish the same private report directory.
                                (out/'SD').mkdir(mode=0o700,exist_ok=True)
                            with directory(out/'SD') as parent:report(parent,result)
                        result=export_with_flush_lifecycle(export_once,barrier_serial,sequence,publish_final)
                        if host_sd_fd is not None or directory_sd_fd is not None:host_sd_export_verified[0]=bool(result.get('ok'))
                        if early_media_watch is not None:
                            result['initialization_observation']=cleanup
                        if (os.environ.get('A7C2_MEDIA_STATE_READBACK')=='1' and
                                not media_state_readback_done[0] and result.get('ok') and
                                result.get('flush_lifecycle',{}).get('resumed')):
                            media_state_readback_done[0]=True
                            # Capture AFTER the card has been published and thawed;
                            # a diagnostic failure must never interrupt STOP/CONT.
                            try:
                                from media_state_readback import command,parse
                                diagnostic=command((out/'console.log').read_bytes())
                                data=serial_command(proc,out/'console.log',diagnostic,timeout=30)
                                (out/'media-state-readback.txt').write_bytes(data)
                                (out/'media-state-readback.json').write_text(json.dumps(parse(data),indent=2)+'\n')
                            except (OSError,RuntimeError,ValueError) as error:
                                (out/'media-state-readback-error.json').write_text(json.dumps(
                                    {'error':str(error),'capture_verified':False,
                                     'completed_sd_export':result})+'\n')
                                # A timed-out serial transaction is not safe to
                                # follow with another command. Surface the error
                                # to run_live's retained SD/fault recovery path.
                                if isinstance(error,(OSError,RuntimeError)):
                                    raise
                        if (os.environ.get('MENU_USB_NET')=='1'
                                and os.environ.get('A7C2_USB_NET_SELFTEST')=='1' and result.get('ok')
                                and not usb_net_done[0]
                                and not (out/'wifi-state.json').exists()):
                            # Isolated USB Ethernet acceptance inside the real camera
                            # run. This lives in the SD-export entry point, so nothing
                            # here may escape as an export failure.
                            usb_net_done[0] = True
                            alias = None
                            try:
                                from ethernet_peer import EthernetPeer
                                configure = serial_command(proc, out/'console.log',
                                    'for m in mii usbnet cdc_ether rndis_host xhci-hcd xhci-plat-hcd; '
                                    'do /sbin/insmod /usr/kmod/$m.ko 2>/dev/null; done; sleep 3; '
                                    'ifconfig usb0 10.0.0.2 netmask 255.255.255.0 up; '
                                    'ifconfig usb0; true', timeout=60)
                                socket_path, alias = netdev_socket_alias(out)
                                peer = EthernetPeer(socket_path)
                                peer.start()
                                host_ping = (peer.ping_guest(timeout=10)
                                             if peer.arp_resolve(timeout=10) else None)
                                guest = serial_command(proc, out/'console.log',
                                    'ping -c 2 -W 2 10.0.0.1; true', timeout=30)
                                import re as _re
                                stats = _re.search(rb'(\d+) packets transmitted, (\d+) packets received', guest)
                                peer.stop()
                                alias.unlink(missing_ok=True)
                                usb = {'scope': 'isolated original-kernel USB Ethernet ICMP in a camera run',
                                       'configured': b'10.0.0.2' in configure,
                                       'host_ping': host_ping,
                                       'guest_transmitted': int(stats[1]) if stats else None,
                                       'guest_received': int(stats[2]) if stats else None,
                                       'peer_frames_in': peer.frames_in,
                                       'peer_frames_out': peer.frames_out,
                                       'capture_verified': False}
                                usb['ok'] = bool(usb['configured'] and host_ping and usb['guest_received'])
                                (out/'usb-net-icmp.json').write_text(json.dumps(usb, indent=2)+'\n')
                                print('USB_NET_ICMP', json.dumps(usb), flush=True)
                            except Exception as error:
                                if alias is not None:
                                    alias.unlink(missing_ok=True)
                                (out/'usb-net-icmp-error.json').write_text(json.dumps(
                                    {'error': f'{type(error).__name__}: {error}'}, indent=2)+'\n')
                        return result
                    wifi = None
                    sd_card = None
                    if os.environ.get('A7C2_SD_HOTPLUG') == '1' and rm_file:
                        from sd_hotplug import SDHotplug
                        sd_card = SDHotplug(lambda diagnostic: serial_command(
                            proc, out/'console.log', diagnostic, timeout=30), out)
                    if os.environ.get('MENU_USB_NET') == '1':
                        # The isolated USB-Ethernet switch the UI toggles. The link
                        # object decides success from real evidence (guest address
                        # plus a matching host echo reply), never from an exit code.
                        from ethernet_peer import EthernetPeer
                        from wifi_toggle import WifiLink
                        def wifi_peer_factory():
                            socket_path, alias = netdev_socket_alias(out)
                            peer = EthernetPeer(socket_path)
                            original_stop = peer.stop
                            def stop_and_clear():
                                try: original_stop()
                                finally: alias.unlink(missing_ok=True)
                            peer.stop = stop_and_clear
                            return peer
                        wifi = WifiLink(lambda command, timeout=90: serial_command(
                                            proc, out/'console.log', command, timeout=timeout),
                                        wifi_peer_factory)
                    try:
                        def export_with_settings():
                            if functional_camera is not None:
                                functional_camera.check()
                            ownership = {}
                            if yc_ownership_observe:
                                from yc_ownership_evidence import verify as verify_ownership
                                ownership['yc_ownership_observation'] = verify_ownership(out)
                            if not settings_persist:return {**export_virtual_sd(), **ownership}
                            from settings_checkpoint import snapshot as snapshot_settings
                            saved_settings=snapshot_settings(lambda command,timeout=90:
                                serial_command(proc,out/'console.log',command,timeout=timeout),qmp,out)
                            exported=export_virtual_sd()
                            return {**exported,'settings':saved_settings, **ownership}
                        run_live(proc, out, int(live_fd),
                                 display_capture=capture_native_display if args.native_display is not None else None,
                                 sd_export=export_with_settings if rm_file else None,
                                 network=wifi, sd_card=sd_card)
                    finally:
                        if functional_camera is not None:
                            functional_camera.guard_shutdown(proc, sys.exc_info()[1])
                        if wifi is not None:
                            wifi.close()
                        if early_media_watch is not None:
                            from media_initial_write import guard_shutdown
                            guard_shutdown(early_media_watch,proc,out)
                        if host_sd_fd is not None or directory_sd_fd is not None:
                            from host_sd_guard import guard_shutdown as guard_host_sd
                            guard_host_sd(proc,out,host_sd_export_verified[0])
                        if proc.poll() is None:
                            qmp('quit')
                    raise SystemExit(0)
                # Optional key injection: MENU_KEY_INJECT="key_code,sub,press_status,ex,from[,hold_seconds[,release_status]]"
                # Multiple shots separated by ';' are injected in sequence with a pause between them.
                inject = os.environ.get("MENU_KEY_INJECT", "")
                static_injection = None
                if inject:
                    from menu_live import inject_key_tool
                    queue = os.environ.get("MENU_KEY_QUEUE", "0x807a0020")
                    src = os.environ.get("MENU_KEY_SRC", "0x92840747")
                    app32 = os.environ.get('MENU_LIVE_APP_INPUT') == '1'
                    tool = inject_key_tool(queue, src, app32)
                    shot = []
                    expected_sends = 0
                    for shot_index, spec in enumerate(inject.split(";")):
                        parts = spec.split(",")
                        if len(parts) not in (5, 6, 7):
                            raise SystemExit("MENU_KEY_INJECT expects key_code,sub,press_status,ex,from[,hold_seconds[,release_status]] per shot, ';'-separated")
                        shot.append("echo INJECT_SHOT_BEGIN=%d" % shot_index)
                        shot.append("%s %s %s %s %s %s %s %s" % (tool, queue, src, *parts[:5]))
                        expected_sends += 1
                        if len(parts) >= 6:
                            release_status = parts[6] if len(parts) == 7 else "0x7fffffff"
                            shot += ["sleep %s" % parts[5],
                                     "%s %s %s %s %s %s %s %s" % (tool, queue, src, parts[0], parts[1], release_status, parts[3], parts[4])]
                            expected_sends += 1
                        shot.append("sleep %s" % os.environ.get("MENU_KEY_POST_WAIT", "8"))
                    static_injection = {'route': 'app32' if app32 else 'infra20',
                                        'expected_records': expected_sends}
                    proc.stdin.write(("\n".join(shot) + "\n").encode())
                    proc.stdin.flush()
                # Optional CP event injection: MENU_CP_EVENT_INJECT="frame,code,sub,param[,wait_seconds]"
                # Multiple events separated by ';' are delivered to the dataflow CP port in order.
                cp_events = os.environ.get("MENU_CP_EVENT_INJECT", "")
                if cp_events:
                    cp_queue = os.environ.get("MENU_CP_EVENT_QUEUE", "0x81cf618b")
                    cp_src = os.environ.get("MENU_CP_EVENT_SRC", "0x81cf618a")
                    shot = []
                    for shot_index, spec in enumerate(cp_events.split(";")):
                        parts = spec.split(",")
                        if len(parts) not in (4, 5):
                            raise SystemExit("MENU_CP_EVENT_INJECT expects frame,code,sub,param[,wait_seconds] per shot, ';'-separated")
                        if shot_index:
                            shot.append("sleep %s" % (parts[4] if len(parts) == 5 else "3"))
                        shot.append("echo CP_EVENT_SHOT_BEGIN=%d" % shot_index)
                        shot.append("/simulation/inject-cp-event %s %s %s %s %s %s" % (cp_queue, cp_src, *parts[:4]))
                    shot.append("sleep %s" % os.environ.get("MENU_CP_EVENT_POST_WAIT", "10"))
                    proc.stdin.write(("\n".join(shot) + "\n").encode())
                    proc.stdin.flush()
                diagnostic = ["/bin/busybox sh /simulation/diag.sh"]  # baked-in script: giant one-liners get silently truncated when the guest tty input queue overruns
                if pin_buffer_selftest:
                    diagnostic += ["mkdir -p /log/qemu; /simulation/pin-control-probe; echo PIN_CONTROL_PROBE_RC=$?"]
                if args.headless_osd:
                    diagnostic += ["/simulation/headless-osd-export; echo HEADLESS_OSD_EXPORT_RC=$?"]
                if args.native_display is not None:
                    diagnostic += ["cat /tmp/ramfb-viewer.log /tmp/ramfb-viewer.status"]
                if os.environ.get('MENU_INPUT_STATE') == '1':
                    diagnostic += ["/bin/busybox sh /simulation/input-state.sh; echo INPUT_STATE_STATUS=$?"]
                if os.environ.get('MENU_QUEUE_STACKS') == '1':
                    # Include original pool workers: Common can await their completion tokens.
                    diagnostic += ["p=; for c in /proc/[0-9]*; do /bin/busybox grep -q /usr/lib/appFw.so $c/smaps 2>/dev/null && p=$c; done; echo QPID=$p; for t in $p/task/[0-9]*; do co=$(/bin/busybox cat $t/comm 2>/dev/null); case \"$co\" in SeqQueue*|SeqThreadPool*|CameraBackgroun) echo QTASK ${t##*/} $co; case \"$co\" in SeqQueueStillCa) /simulation/menu-regs ${t##*/} --stillca;; *) /simulation/menu-regs ${t##*/};; esac;; esac; done; echo QSTACKS_DONE"]
                if dmm_unit_config:
                    diagnostic += ["echo MAIN_IMAGE_UNIT_SIZE_BEGIN; p=; for c in /proc/[0-9]*; do /bin/busybox grep -q /usr/lib/appFw.so $c/smaps 2>/dev/null && p=$c; done; /simulation/menu-readmem $p/mem 0x7ecfbf0 4 appFw.so; echo MAIN_IMAGE_UNIT_SIZE_RC=$?"]
                    for label,address in (('CAUTION_GROUP',0x7e68b50),('CAUTION_SELECTED_ID',0x7e68bc8),
                                          ('CAUTION_SELECTOR',0x7e72080),('CAUTION_B1C_INPUT',0x7ecc6c8),
                                          ('CAUTION_B1D_INPUT',0x7ecc6e0)):
                        diagnostic += [f"echo {label}_BEGIN; /simulation/menu-readmem $p/mem {address:#x} 4 appFw.so; echo {label}_RC=$?"]
                    for label,address in (('DIALOG_MODULE_262_INPUT',0x7e80dd0),('DIALOG_MODULE_233_INPUT',0x7e80f50)):
                        diagnostic += [f"echo {label}_BEGIN; /simulation/menu-readmem $p/mem {address:#x} 4 appFw.so; echo {label}_RC=$?"]
                    for label,address in (('MEDIA_MOUNT_ERROR_SLOT1',0x7ee5fa0),('MEDIA_MOUNT_ERROR_SLOT2',0x7ee5fb8)):
                        diagnostic += [f"echo {label}_BEGIN; /simulation/menu-readmem $p/mem {address:#x} 4 appFw.so; echo {label}_RC=$?"]
                    for label,address,size in (('FIRSTBOOT_DATE_STATUS',0x7e5df40,4),('FIRSTBOOT_FORCE_CLOCK',0x7eda8d0,1),
                                               ('SELF_DIAGNOSIS_STATUS',0x7ee5b10,0x240)):
                        diagnostic += [f"echo {label}_BEGIN; /simulation/menu-readmem $p/mem {address:#x} {size} appFw.so; echo {label}_RC=$?"]
                    diagnostic += ["echo BOOT_CURRENT_SEQUENCE_RAW_BEGIN; /simulation/menu-readmem $p/mem 0x910a4a0 136 appFw.so follow; echo BOOT_CURRENT_SEQUENCE_RAW_RC=$?"]
                if os.environ.get('MENU_THREAD_NAMES') == '1':
                    # Read-only: list every thread of the app process with its pthread name, so a
                    # library worker (e.g. OPTION_INSTALLER_MAIN_THREAD) can be proven to exist.
                    diagnostic += ["p=; for c in /proc/[0-9]*; do /bin/busybox grep -q /usr/lib/appFw.so $c/smaps 2>/dev/null && p=$c; done; echo THREADS_PID=$p; for t in $p/task/[0-9]*; do echo THREAD ${t##*/} $(/bin/busybox cat $t/comm 2>/dev/null); done; echo THREADS_DONE"]
                if os.environ.get('MENU_ALL_STACKS') == '1':
                    # Read-only: walk every thread of the app process, ptrace-stop briefly, print frame chain.
                    # Used to see where the sequence scheduler thread sits (0x3209d48 loop vs. a run body).
                    diagnostic += ['p=; for c in /proc/[0-9]*; do /bin/busybox grep -q /usr/lib/appFw.so $c/smaps 2>/dev/null && p=$c; done; echo ALLSTACK_PID=$p; for t in $p/task/[0-9]*; do echo ALLSTACK_TID=${t##*/}; /simulation/menu-regs ${t##*/}; done; echo ALLSTACK_STATUS=$?']
                if os.environ.get('MENU_UI_STACK') == '1':
                    # Explicit diagnostic: briefly ptrace-stop this guest UI thread,
                    # read its registers/frame chain, then detach without writing it.
                    diagnostic += ["tid=$(/bin/busybox sed -n '/FRAME_DRAW_ENTER call=1 tid=/{s/.* tid=\\([0-9]*\\).*/\\1/;p;q;}' /tmp/menu-load.log); echo BOOT_UI_TID=$tid; test -n \"$tid\" && /simulation/menu-regs \"$tid\"; echo BOOT_UI_STACK_STATUS=$?"]
                # Earlier queued key commands can emit prompts; only our own marker proves completion.
                prompt_deadline = time.monotonic() + int(os.environ.get("MENU_DIAG_TIMEOUT", "240"))
                for diagnostic_index, line in enumerate(diagnostic):
                    marker = f"MENU_DIAG_COMMAND_DONE_{diagnostic_index}"
                    proc.stdin.write((line + "\nprintf '\\n" + marker + "\\n'\n").encode())
                    proc.stdin.flush()
                    while not diagnostic_done((out / "console.log").read_bytes(), marker):
                        if b'Exception>' in (out / "console.log").read_bytes():
                            # Guest hit the Sony exception monitor before diag completed:
                            # capture the crash-state memory for offline analysis.
                            qmp('pmemsave', {'val': 0x405000000, 'size': 0x800000,
                                             'filename': '/out/menu-ulogio.bin'})
                            qmp('pmemsave', {'val': 0x4102bb400, 'size': 0x8000,
                                             'filename': '/out/menu-monitor.bin'})
                            print("GUEST_CRASH_DUMPS_CAPTURED", flush=True)
                            try:
                                proc.stdin.write(b'help\nbt\nregs\n')
                                proc.stdin.flush()
                                time.sleep(6)
                            except (OSError, BrokenPipeError):
                                pass
                            qmp('quit')
                            raise RuntimeError("guest exception monitor before diagnostics")
                        if time.monotonic() > prompt_deadline:
                            raise RuntimeError("diagnostic command timed out waiting for completion marker: " + line[:60])
                        time.sleep(0.5)
                proc.stdin.flush()
                deadline = time.monotonic() + int(os.environ.get("MENU_DIAG_TIMEOUT", "120"))
                while b"\nMENU_PROBE_FINISHED" not in (out / "console.log").read_bytes():
                    captured = (out / "console.log").read_bytes()
                    if b'Exception>' in captured:
                        if args.dmm_service:
                            qmp('pmemsave', {'val': 0x41e000000, 'size': 0x100000,
                                             'filename': '/out/cp-dmm-pool.bin'})
                        qmp('pmemsave', {'val': 0x405000000, 'size': 0x800000,
                                         'filename': '/out/menu-ulogio.bin'})
                        qmp('pmemsave', {'val': 0x4102d0000, 'size': 0x10000,
                                         'filename': '/out/menu-loader.bin'})
                        data = (out / 'menu-loader.bin').read_bytes()
                        count = int.from_bytes(data[:4], 'little')
                        (out / 'loader.txt').write_text(data[8:8 + min(count, 65528)].decode(errors='replace'))
                        if args.software_gpe:
                            fills = re.findall(r'GPE_SOFTWARE_FILL sequence=(\d+) address=(0x[0-9a-f]+) bytes=(\d+) width=(\d+) height=(\d+) format=(\d+) result=0',
                                               (out / 'loader.txt').read_text())
                            if fills:
                                sequence, address, size, width, height, fmt = fills[0]
                                qmp('pmemsave', {'val': int(address, 16), 'size': int(size), 'filename': '/out/gpe-first-fill.bin'})
                                (out / 'gpe-first-fill.json').write_text(json.dumps({'address': address, 'bytes': int(size),
                                    'width': int(width), 'height': int(height), 'format': int(fmt),
                                    'source': 'original UX uniform fill, not a rendered menu'}, indent=2) + '\n')
                        (out / 'summary.json').write_text(json.dumps({
                            'run': str(out), 'input_image': command[-1],
                            'probe_collected': False, 'guest_exception': True,
                            'loader_log_bytes': count, 'loader_log_truncated': count > 65528,
                            'loader_window_covers_first_64KiB_only': True,
                            'visible_menu_verified': False,
                        }, indent=2) + '\n')
                        before = len(captured)
                        proc.stdin.write(b'exit\ncat /tmp/menu-load.log\necho FAILED_RUN_LOG_COLLECTED\n')
                        proc.stdin.flush()
                        recovery_deadline = time.monotonic() + 5
                        while time.monotonic() < recovery_deadline:
                            recovered = (out / 'console.log').read_bytes()[before:]
                            if b'\nFAILED_RUN_LOG_COLLECTED' in recovered:
                                (out / 'failure-loader-console.txt').write_bytes(recovered)
                                break
                            time.sleep(0.1)
                        qmp('quit')
                        raise RuntimeError('Guest entered Sony exception monitor; see console.log')
                    if time.monotonic() > deadline:
                        raise RuntimeError("Probe did not finish; inspect guest crash/output")
                    time.sleep(0.1)
                if args.headless_osd:
                    try:
                        info = capture_headless_osd((out / 'console.log').read_bytes(), out)
                        print(f"HEADLESS_OSD_CAPTURE seq={info['sequence']} sha256={info['sha256']}", flush=True)
                    except (ValueError, IndexError) as error:
                        (out / 'headless-osd-error.txt').write_text(str(error) + '\n')
                        print(f"HEADLESS_OSD_CAPTURE_FAILED {error}", flush=True)
                if args.seed_backup:
                    qmp('stop')
                    if args.software_gpe:
                        sources = raster_sources((out / 'console.log').read_text(errors='replace'))
                        captured_sources, used_bytes = [], 0
                        for source in sources:
                            if len(captured_sources) >= 64 or used_bytes + source['bytes'] > 0x2000000:
                                continue
                            name = f"raster-source-{source['address']:x}-f{source['format']}-s{source['row_pixels']}.bin"
                            qmp('pmemsave', {'val': source['address'], 'size': source['bytes'], 'filename': '/out/' + name})
                            captured_sources.append(dict(source, filename=name))
                            used_bytes += source['bytes']
                        (out / 'raster-sources.json').write_text(json.dumps({
                            'source': 'post-diagnostic snapshot; allocation may have been reused since draw request',
                            'captured': captured_sources, 'dropped': len(sources) - len(captured_sources),
                            'bytes': used_bytes, 'channel_order_verified': False,
                        }, indent=2) + '\n')
                        print(f"RASTER_SOURCES captured={len(captured_sources)} dropped={len(sources)-len(captured_sources)} bytes={used_bytes}", flush=True)
                    if args.capid_service:
                        qmp('pmemsave', {'val': 0x4102e0000, 'size': 0x4014, 'filename': '/out/capid-table.bin'})
                    qmp('pmemsave', {'val': 0x4102bb400, 'size': 0x8000, 'filename': '/out/menu-monitor.bin'})
                    qmp('pmemsave', {'val': 0x405000000, 'size': 0x800000, 'filename': '/out/menu-ulogio.bin'})
                    qmp('pmemsave', {'val': 0x4102d0000, 'size': 0x10000,
                                     'filename': '/out/menu-loader.bin'})
                if args.native_display is not None:
                    try:
                        qmp('screendump', {'filename': '/out/ramfb-screen.ppm'})
                        print('RAMFB_SCREENDUMP ramfb-screen.ppm (pixel comparison still required)', flush=True)
                    except RuntimeError as error:
                        (out / 'ramfb-screen-error.txt').write_text(str(error) + '\n')
                        print(f'RAMFB_SCREENDUMP_FAILED {error}', flush=True)
                if pin_control_memory:
                    qmp('pmemsave', {'val': 0x500000000, 'size': 8192, 'filename': '/out/pin-control-ram.bin'})
                if audio_boot_config:
                    if not re.search(rb'(?:^|\n)SYSTEM_SOUND_INIT_OK\r?\n', (out / 'console.log').read_bytes()):
                        raise RuntimeError('System sound initialization marker missing')
                    qmp('pmemsave', {'val': sound_api['API']['PHYSICAL'], 'size': sound_api['API']['CAPACITY'],
                                    'filename': '/out/system-sound-ram.bin'})
                    sound = (base / 'menu-root/cp/SysSound.bin').read_bytes()
                    if (out / 'system-sound-ram.bin').read_bytes() != sound + bytes(sound_api['API']['CAPACITY'] - len(sound)):
                        raise RuntimeError('System sound QMP bytes/padding differ from original source')
                    print('SYSTEM_SOUND_QMP_CONTENT_PASS', flush=True)
                if pin_connection_mode and re.search(rb'^OBS FULL_PIN_(?:CONNECT|FORMAT)_FAULT ',
                                                     (out / 'console.log').read_bytes(), re.M):
                    raise RuntimeError('Pin connection/format ownership fault; see captured RAM and console')
                if pin_buffer_selftest:
                    console = (out / 'console.log').read_bytes()
                    probe_lines = re.findall(rb'^FULL_PIN_CONTROL_PROBE_PASS ([^\r\n]+)', console, re.M)
                    codes = re.findall(rb'^PIN_CONTROL_PROBE_RC=(\d+)\r?$', console, re.M)
                    if len(probe_lines) != 1 or codes != [b'0']:
                        raise RuntimeError('Pin-control backing probe did not pass')
                    physical = (out / 'pin-control-ram.bin').read_bytes()
                    expected = b'SSYN\x00\x00\x00\x01' + bytes(8192 - 8)
                    if physical != expected:
                        raise RuntimeError('QMP pin-control RAM differs from the guest write/readback')
                    fields = dict(re.findall(rb'(\w+)=([^\s]+)', probe_lines[0]))
                    digest = 0xcbf29ce484222325
                    for byte in physical:
                        digest = ((digest ^ byte) * 0x100000001b3) & 0xffffffffffffffff
                    if fields.get(b'full_fnv64') != f'{digest:016x}'.encode():
                        raise RuntimeError('Guest and QMP pin-control digests differ')
                    proof = {'pin_control_backing_verified': True, 'physical': '0x500000000',
                             'capacity': len(physical), 'qmp_sha256': hashlib.sha256(physical).hexdigest(),
                             'guest_qmp_fnv64': f'{digest:016x}',
                             'dtb_sha256': sha256_file(out / 'virt.dtb'),
                             'console_sha256': hashlib.sha256(console).hexdigest(),
                             'camera_startup_verified': False, 'pixels_consumed': False}
                    (out / 'pin-control-backing-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
                    print('PIN_CONTROL_GUEST_QMP_BACKING_PASS', flush=True)
                qmp("quit")
        proc.wait(timeout=5)
    finally:
        if functional_camera is not None:
            functional_camera.guard_shutdown(proc, sys.exc_info()[1])
        if early_media_watch is not None:
            from media_initial_write import guard_shutdown
            guard_shutdown(early_media_watch,proc,out)
        if host_sd_fd is not None or directory_sd_fd is not None:
            from host_sd_guard import guard_shutdown as guard_host_sd
            guard_host_sd(proc,out,host_sd_export_verified[0])
        if proc.poll() is None:
            if host_sd_fd is not None or directory_sd_fd is not None:
                try:qmp('quit')
                except Exception as error:
                    (out/'host-sd-quit-error.json').write_text(json.dumps({'error':str(error),
                        'force_kill_authorized':False})+'\n')
                    raise RuntimeError('Host-backed SD QMP quit failed; retain VM, do not terminate sandbox') from error
            else:proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if host_sd_fd is not None or functional_camera is not None:
                    raise RuntimeError('Owned camera VM still running; retain lease, never SIGKILL')
                proc.kill()
                proc.wait(timeout=5)
def convert_screens(run_dir):
    """Candidate RGB565 interpretations only: neither display use nor pixel format is verified."""
    try:
        from PIL import Image
    except Exception:
        return []
    written = []
    for path in sorted(run_dir.glob('screen-*.bin')):
        raw = path.read_bytes()
        if len(raw) < 640 * 480 * 2:
            continue
        for order in ('little', 'big'):
            image = Image.new('RGB', (640, 480))
            pixels = image.load()
            for index in range(640 * 480):
                value = int.from_bytes(raw[index * 2:index * 2 + 2], order)
                pixels[index % 640, index // 640] = (
                    ((value >> 11) & 0x1F) * 255 // 31,
                    ((value >> 5) & 0x3F) * 255 // 63,
                    (value & 0x1F) * 255 // 31)
            target = path.with_name(path.stem + f'-candidate-rgb565-{order}.png')
            image.save(target)
            written.append((target, image.getcolors(maxcolors=65536) or []))
    if os.environ.get('MENU_GPE_RGBA4444'):
        pixel_sources = [(path, path.with_suffix('.json')) for path in sorted(run_dir.glob('framebuffer-*.bin'))]
        committed = run_dir / 'headless-osd-pixels.bin'
        if committed.exists():
            pixel_sources.append((committed, run_dir / 'headless-osd-frame.json'))
        for path, metadata_path in pixel_sources:
            metadata = json.loads(metadata_path.read_text())
            width, height, stride = metadata['width'], metadata['height'], metadata['row_pixels']
            raw = path.read_bytes()
            if metadata['bmp_format'] not in (1, 7) or not (0 < width <= stride <= 16384 and 0 < height <= 8192):
                continue
            if len(raw) < ((height - 1) * stride + width) * 2:
                continue
            rgba = bytearray(width * height * 4)
            for y in range(height):
                for x in range(width):
                    offset = (y * stride + x) * 2
                    value = raw[offset] | raw[offset + 1] << 8
                    i = (y * width + x) * 4
                    rgba[i:i + 4] = bytes(((value >> 12) * 17, (value >> 8 & 15) * 17,
                                            (value >> 4 & 15) * 17, (value & 15) * 17))
            image = Image.frombytes('RGBA', (width, height), bytes(rgba))
            target = path.with_name(path.stem + '-rgba4444-software.png')
            image.save(target)
            target.with_suffix('.json').write_text(json.dumps(dict(metadata,
                raw_capture=path.name, decoder='experimental RGBA4444 software model; not hardware format proof'), indent=2) + '\n')
            written.append((target, image.getcolors(maxcolors=65536) or []))
    return written

screens = convert_screens(out)
for target, colors in screens:
    flat = sorted(colors, key=lambda item: -item[0])[:3]
    print(f"SCREEN_PNG {target.name} distinct={len(colors)} top={[(count, '#' + ''.join(f'{v:02x}' for v in color)) for count, color in flat]}", flush=True)

text = (out / 'console.log').read_text(errors='replace')
yc_input_proof = None
if os.environ.get('MENU_YC_INPUT_RAW'):
    source = Path(os.environ['MENU_YC_INPUT_RAW']).read_bytes()
    value = 0xcbf29ce484222325
    for byte in source:
        value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    observed = re.search(r'YCIN_INPUT: PNG luma readback bytes=(\d+) fnv64=([0-9a-f]{16})', text)
    readback = out / 'yc-pixel-readback.bin'
    guest_log = (out / 'menu-ulogio.bin').read_bytes() if (out / 'menu-ulogio.bin').exists() else b''
    completed = len(re.findall(rb'flow\[1\]CMP\(0x[0-9A-Fa-f]+\)[^\x00\n]{0,280}?size=2073600\) diff=0', guest_log))
    yc_input_proof = dict(source_sha256=hashlib.sha256(source).hexdigest(),
                          guest_fnv64=observed.group(2) if observed else None,
                          expected_fnv64=f'{value:016x}',
                          pixel_readback_sha256=sha256_file(readback) if readback.exists() else None,
                          rdimg_completed=completed,
                          out1_deliveries=text.count('YCIN_VDT_REPLY: OUT1 frame delivery'),
                          module_init_completed='YCIN_INIT_DONE: 3 frames queued' in text and
                              'YCIN_INIT_FAILED:' not in text)
    yc_input_proof['verified'] = (len(source) == 1920 * 1080 and observed is not None and
        int(observed.group(1)) == len(source) and observed.group(2) == yc_input_proof['expected_fnv64'] and
        yc_input_proof['pixel_readback_sha256'] == yc_input_proof['source_sha256'] and
        completed > 0 and yc_input_proof['out1_deliveries'] > 0 and yc_input_proof['module_init_completed'])
    (out / 'yc-input-proof.json').write_text(json.dumps(yc_input_proof, indent=2) + '\n')
    if yc_input_proof['verified'] and (out / 'headless-osd-frame.bin').exists():
        from menu_live import snapshot_message
        import base64
        composite = snapshot_message((out / 'console.log').read_bytes(), preview=source)
        (out / 'yc-preview.png').write_bytes(base64.b64decode(composite['png']))
        (out / 'yc-preview.json').write_text(json.dumps(composite['info'], indent=2) + '\n')
loader = out / 'menu-loader.bin'
loads = ''
if loader.exists():
    data = loader.read_bytes()
    count = int.from_bytes(data[:4], 'little')
    loads = data[8:8 + min(count, 65528)].decode(errors='replace')
    (out / 'loader.txt').write_text(loads)
def census(name, default=0):
    """Read a guest-side counter from the diag output. The kernel console can inject its own text
    into the middle of a guest line (including between 'name=' and the digits), so every occurrence
    is scanned and the diag script prints the whole block twice as insurance."""
    values = [int(found.group(1)) for found in re.finditer(r'\b' + re.escape(name) + r'=(\d+)', text)]
    return max(values) if values else default


summary = {'run': str(out), 'probe_collected': True,
           'input_image': command[-1],
           'cp_updater_transport_unavailable': args.no_cp_updater,
           'original_kikilog_requested': args.load_kikilog,
           'virtual_capid_service': args.capid_service,
           'virtual_sa_address_service': args.sa_address_service,
           'virtual_hdmi_audio_parameter': args.hdmi_format_service,
           'virtual_hdmi_photo_parameter': args.hdmi_photo_service,
           'virtual_cp_dmm_pool': args.dmm_service,
           'software_pixel_model': 'experimental straight RGBA4444/source-over/nearest; not hardware-bit-exact' if os.environ.get('MENU_GPE_RGBA4444') else 'limited verified operations',
           'software_lz77_requested': bool(os.environ.get('MENU_SOFTWARE_LZ77')),
           'natural_imaging_profile': manifest['natural_imaging_profile'],
           'loader_log_bytes': count if loader.exists() else 0,
           'loader_log_truncated': count > 65528 if loader.exists() else False,
           # The guest keeps the whole observer log in /tmp/menu-load.log and diag.sh counts
           # it there, so the census numbers below are the authoritative source. The 64 KiB
           # memory window (loader.txt) only holds the FIRST 64 KiB of records and must not be
           # used to conclude that a late event (appFw init) never happened.
           'lifecycle_evidence_source': 'guest census of the full log (/tmp/menu-load.log) via diag.sh',
           'loader_window_covers_first_64KiB_only': True,
           'appfw_library_loaded': census('appfw_loaded') > 0,
           'appfw_init_symbol_resolved': census('resolved_asi') > 0,
           'appfw_init_entered': census('enter_asi') > 0,
           'appfw_init_returned': census('return_asi') > 0,
           'appfw_init_return_semantics': 'opaque thread handle, not an error code',
           'uxengine_init2_entered': census('ux2_enter') > 0,
           'uxengine_init2_returned': census('ux2_return') > 0,
           'uxengine_init2_hook_installed': census('ux2_hook') > 0,
           'uxengine_init2_census': {'enter': census('ux2_enter'), 'return': census('ux2_return'),
                                     'hook': census('ux2_hook')},
           'gui_library_loaded': census('gui_loaded') > 0,
           'crypt_library_loaded': census('crypt_lib_ok') > 0,
           'natural_start_observation': {
               'requested': manifest['natural_start_trace'],
               'mode_transition_hits': census('natural_mode'),
               'enter_rec_still_hits': census('natural_enter_still'),
               'run_i_return_hits': census('natural_run_i_ret'),
               'generic_jpeg_request_hits': census('generic_jpeg_request'),
               'upm_model_error_hits': census('upm_model_error'),
               'boot_fatal_409_hits': census('boot_fatal_409'),
               'boot_fatal_common_hits': census('boot_fatal_common'),
               'cp_release_successful_replies': census('cp_release_ok'),
               'still_capture_verified': False},
           'visible_menu_verified': False,
           'initialization_logs': str(out / 'loader.txt'),
           'full_guest_log_excerpts': str(out / 'console.log')}
if functional_camera is not None:
    summary['functional_camera_runtime'] = functional_camera.receipt('closed')
if yc_input_proof is not None:
    summary['yc_input'] = yc_input_proof
if yc_ownership_observe:
    from yc_ownership_evidence import verify as verify_ownership
    summary['yc_ownership_observation'] = verify_ownership(out)
if yc_uncompressed:
    from yc_image_input import uncompressed_proof
    summary['yc_uncompressed_source'] = uncompressed_proof(out,text)
    (out/'yc-uncompressed-proof.json').write_text(json.dumps(summary['yc_uncompressed_source'],indent=2)+'\n')
if manifest['rc_board_profile']:
    from rc_reference_evidence import verify
    summary['rc_reference_output']=verify(out)
    (out/'rc-reference-output-proof.json').write_text(json.dumps(summary['rc_reference_output'],indent=2)+'\n')
if manifest['sa_reference_data_only']:
    from sa_data_evidence import verify as verify_nv12
    summary['sa_reference_data_only']=verify_nv12(out)
    (out/'sa-reference-data-proof.json').write_text(json.dumps(summary['sa_reference_data_only'],indent=2)+'\n')
if manifest['sa_reference_completion']:
    from sa_completion_evidence import verify as verify_sa_completion
    summary['sa_reference_completion']=verify_sa_completion(out)
    (out/'sa-reference-completion-proof.json').write_text(json.dumps(summary['sa_reference_completion'],indent=2)+'\n')
if resize_mmio_watch:
    from resize_mmio_watch import observation_error
    resize_error=observation_error(out)
    result_path=out/'resize-watch-result.json'
    summary['resize_observation']=json.loads(result_path.read_text()) if result_path.exists() else None
    summary['resize_observation_error']=resize_error
if static_injection is not None:
    expected = f"result=0 bytes={32 if static_injection['route'] == 'app32' else 20}".encode()
    sends = [line for line in (out/'console.log').read_bytes().splitlines() if b'INJECT_KEY_SEND' in line]
    injection_proof = {**static_injection,
                       'ok': len(sends) == static_injection['expected_records'] and all(expected in line for line in sends),
                       'successful_submissions': sum(expected in line for line in sends),
                       'consumer_verified': False,
                       'scope': 'injector submission only; not original consumer or capture',
                       'send_lines': [line.decode('utf-8', 'replace') for line in sends]}
    summary['static_key_injection'] = injection_proof
    (out/'static-key-injection.json').write_text(json.dumps(injection_proof, indent=2)+'\n')
(out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
print('Capture completion does not establish a rendered menu.')
if yc_ownership_observe and not summary['yc_ownership_observation']['verified']:
    raise RuntimeError('Requested DMM ownership observation failed; no retirement conclusion')
if static_injection is not None and not injection_proof['ok']:
    raise RuntimeError('Static key injection submission failed or returned nonzero')
if yc_input_proof is not None and not yc_input_proof['verified']:
    raise RuntimeError('YC PNG input did not pass guest byte readback and original RDIMG consumption checks')
if yc_uncompressed and not summary['yc_uncompressed_source']['verified']:
    raise RuntimeError('Uncompressed YC source did not pass byte readback, original RDIMG and RC format checks')
if resize_mmio_watch and resize_error is not None:
    raise RuntimeError('Requested RC kernel observation failed: ' + resize_error)
