#!/usr/bin/env python3
"""Start the verified, bounded A7C II menu capture profile."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from headless_osd_capture import decode_export, HEADER, METADATA
from backup_profile import (ADF_PROFILE, INPUT_PROFILE, OUTPUT_PROFILE, BB_SET_MODE_PROFILE,
                            IMAGING_CONNECT_PROFILE, IMAGING_CONTROL_CONNECT_PROFILE, IMAGING_ADF_CONNECT_PROFILE,
                            INFRABB_VEF_CONNECT_PROFILE, FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE,
                            FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE, FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE,
                            FULL_PINMEM_PEER_CONNECTIONS_PROFILE, FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE,
                            FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE, FULL_PINMEM_OSD_CONNECTION_PROFILE,
                            FULL_CP302C_NO_TRANSITION_PROFILE, FULL_CP302C_DIAGNOSTIC_PROFILE,
                            FULL_CP_NOTIFICATION_CONTROL_PROFILE, FULL_CP_CAPTURE_FORMAT_PROFILE, FULL_CP_STARTUP_DIAGNOSTIC_PROFILE, FULL_CP_EE_DIAGNOSTIC_PROFILE, FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE, FULL_CP_OWNED_STATE_PROFILE,
                            FUNCTIONAL_CAMERA_PROFILE,
                            ADF_CONFLICTS, BB_MODE_CONFLICTS)

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]


def profile_environment(current, menu_key=False, natural_boot=False):
    cp_background=current.get('A7C2_CP_BACKGROUND','')
    if cp_background not in ('','virtual-mode3-cold-v1'):
        raise ValueError('A7C2_CP_BACKGROUND must be virtual-mode3-cold-v1 or unset')
    if cp_background and not natural_boot:
        raise ValueError('A7C2_CP_BACKGROUND requires the natural boot profile')
    udate=current.get('A7C2_UDATE_DISTRIBUTION','')
    if udate not in ('','virtual-roundtrip-v1'):
        raise ValueError('A7C2_UDATE_DISTRIBUTION must be virtual-roundtrip-v1 or unset')
    if udate and (not natural_boot or cp_background!='virtual-mode3-cold-v1'):
        raise ValueError('A7C2_UDATE_DISTRIBUTION requires natural boot and virtual-mode3-cold-v1')
    touch_panel=current.get('A7C2_TOUCH_PANEL','')
    if touch_panel not in ('','virtual-config-v1'):
        raise ValueError('A7C2_TOUCH_PANEL must be virtual-config-v1 or unset')
    if touch_panel and (not natural_boot or cp_background!='virtual-mode3-cold-v1' or
                        udate!='virtual-roundtrip-v1'):
        raise ValueError('A7C2_TOUCH_PANEL requires natural boot, CP3007 and UDATE')
    imaging_profile = current.get('A7C2_NATURAL_IMAGING_PROFILE', '')
    if imaging_profile not in ('', '1'):
        raise ValueError('A7C2_NATURAL_IMAGING_PROFILE must be 1 or unset')
    if imaging_profile and not natural_boot:
        raise ValueError('A7C2_NATURAL_IMAGING_PROFILE requires the natural boot profile')
    if touch_panel and imaging_profile:
        raise ValueError('A7C2_TOUCH_PANEL cannot be combined with the imaging profile')
    sparse_sd=current.get('A7C2_SD_SPARSE','')
    host_sd=current.get('A7C2_HOST_SD','')
    directory_sd=current.get('A7C2_DIRECTORY_SD','')
    backup_sync=current.get('A7C2_BACKUP_SYNC','')
    if backup_sync not in ('','virtual-primary-v1'):
        raise ValueError('A7C2_BACKUP_SYNC must be virtual-primary-v1 or unset')
    if backup_sync and (not natural_boot or not directory_sd or imaging_profile or
            cp_background!='virtual-mode3-cold-v1' or udate!='virtual-roundtrip-v1' or
            touch_panel!='virtual-config-v1' or not current.get('A7C2_BACKUP_BUILD')):
        raise ValueError('Backup requires natural directory SD, CP3007/UDATE/touch and explicit combined build')
    tcin=current.get('A7C2_TCIN_DETECT','')
    if tcin not in ('','virtual-inactive-v1'):
        raise ValueError('A7C2_TCIN_DETECT must be virtual-inactive-v1 or unset')
    if tcin and backup_sync!='virtual-primary-v1':
        raise ValueError('TCIN inactive configuration requires the guarded natural Backup profile')
    dfs=current.get('A7C2_DFS_SELECTOR','')
    if dfs not in ('','virtual-selector-v1'):
        raise ValueError('A7C2_DFS_SELECTOR must be virtual-selector-v1 or unset')
    if dfs and tcin!='virtual-inactive-v1':
        raise ValueError('DFS selector requires the guarded TCIN inactive profile')
    vef_path=current.get('A7C2_VEF_PATH','')
    if vef_path not in ('','virtual-nomem-v1'):
        raise ValueError('A7C2_VEF_PATH must be virtual-nomem-v1 or unset')
    if vef_path and dfs!='virtual-selector-v1':
        raise ValueError('VEF NoMem requires the guarded DFS selector profile')
    adf_proc_path=current.get('A7C2_ADF_PROC_PATH','')
    if adf_proc_path not in ('',ADF_PROFILE):
        raise ValueError('A7C2_ADF_PROC_PATH must be virtual-source7-idle-v1 or unset')
    if adf_proc_path and (vef_path!='virtual-nomem-v1' or
            any(current.get(name) for name in ADF_CONFLICTS) or
            current.get('SEED_BACKUP','') not in ('','alllang')):
        raise ValueError('ADF source7 Idle requires guarded VEF NoMem/public ALLLANG without frame or ready injection')
    adf_set_input=current.get('A7C2_ADF_SET_INPUT','')
    if adf_set_input not in ('',INPUT_PROFILE):
        raise ValueError('A7C2_ADF_SET_INPUT must be virtual-input-s0-v1 or unset')
    if adf_set_input and adf_proc_path!=ADF_PROFILE:
        raise ValueError('ADF set input requires the explicit guarded ADF source7 Idle profile')
    adf_set_output=current.get('A7C2_ADF_SET_OUTPUT','')
    if adf_set_output not in ('',OUTPUT_PROFILE):
        raise ValueError('A7C2_ADF_SET_OUTPUT must be virtual-output-nochange-v1 or unset')
    if adf_set_output and (adf_set_input!=INPUT_PROFILE or current.get('MENU_USB_NET')):
        raise ValueError('ADF set output requires the explicit guarded ADF set input profile without USB network')
    bb_set_mode=current.get('A7C2_BB_SET_MODE','')
    if bb_set_mode not in ('',BB_SET_MODE_PROFILE):
        raise ValueError('A7C2_BB_SET_MODE must be virtual-bb-still-target3-op0-v1 or unset')
    if bb_set_mode and (not natural_boot or not directory_sd or host_sd or sparse_sd or imaging_profile or
            backup_sync!='virtual-primary-v1' or not current.get('A7C2_BACKUP_BUILD') or
            cp_background!='virtual-mode3-cold-v1' or udate!='virtual-roundtrip-v1' or
            touch_panel!='virtual-config-v1' or tcin!='virtual-inactive-v1' or
            dfs!='virtual-selector-v1' or vef_path!='virtual-nomem-v1' or
            adf_proc_path!=ADF_PROFILE or adf_set_input!=INPUT_PROFILE or
            adf_set_output!=OUTPUT_PROFILE or current.get('SEED_BACKUP','alllang')!='alllang' or
            current.get('MENU_USB_NET') or any(current.get(name) for name in BB_MODE_CONFLICTS)):
        raise ValueError('BB set mode requires the guarded public Backup/ADF chain and directory SD without imaging/conflicts')
    imaging_connect=current.get('A7C2_IMAGING_CONNECT','')
    if imaging_connect not in ('',IMAGING_CONNECT_PROFILE) or (imaging_connect and
            bb_set_mode!=BB_SET_MODE_PROFILE):
        raise ValueError('A7C2_IMAGING_CONNECT requires virtual-imaging-out1-bb-in1-v1 and the exact guarded BB profile')
    imaging_control_connect=current.get('A7C2_IMAGING_CONTROL_CONNECT','')
    if imaging_control_connect not in ('',IMAGING_CONTROL_CONNECT_PROFILE) or (imaging_control_connect and
            imaging_connect!=IMAGING_CONNECT_PROFILE):
        raise ValueError('A7C2_IMAGING_CONTROL_CONNECT requires virtual-imaging-control0-bb-control0-v1 and the exact first imaging connection profile')
    imaging_adf_connect=current.get('A7C2_IMAGING_ADF_CONNECT','')
    if imaging_adf_connect not in ('',IMAGING_ADF_CONNECT_PROFILE) or (imaging_adf_connect and
            imaging_control_connect!=IMAGING_CONTROL_CONNECT_PROFILE):
        raise ValueError('A7C2_IMAGING_ADF_CONNECT requires virtual-imaging-audio0-adf-audio0-v1 and the exact second imaging control connection profile')
    infrabb_vef_connect=current.get('A7C2_INFRABB_VEF_CONNECT','')
    if infrabb_vef_connect not in ('',INFRABB_VEF_CONNECT_PROFILE) or (infrabb_vef_connect and
            imaging_adf_connect!=IMAGING_ADF_CONNECT_PROFILE):
        raise ValueError('A7C2_INFRABB_VEF_CONNECT requires virtual-infrabb-out1-vef-in1-same-format-v1 and the exact third imaging ADF connection profile')
    infrabb_vef_control_connect=current.get('A7C2_INFRABB_VEF_CONTROL_CONNECT','')
    if infrabb_vef_control_connect not in ('',FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE) or (infrabb_vef_control_connect and
            infrabb_vef_connect!=INFRABB_VEF_CONNECT_PROFILE):
        raise ValueError('A7C2_INFRABB_VEF_CONTROL_CONNECT requires virtual-infrabb-control0-vef-control0-v1 and the exact fourth InfraBB VEF connection profile')
    vef_pinmem_input_connect=current.get('A7C2_VEF_PINMEM_INPUT_CONNECT','')
    if vef_pinmem_input_connect not in ('',FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE) or (vef_pinmem_input_connect and (
            infrabb_vef_control_connect!=FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE or
            current.get('SEED_BACKUP')!='alllang')):
        raise ValueError('A7C2_VEF_PINMEM_INPUT_CONNECT requires virtual-vef-out2-pinmem-in0-forward-format-v1 and the exact fifth InfraBB VEF control connection profile')
    vef_pinmem_control_connect=current.get('A7C2_VEF_PINMEM_CONTROL_CONNECT','')
    if vef_pinmem_control_connect not in ('',FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE) or (vef_pinmem_control_connect and
            vef_pinmem_input_connect!=FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE):
        raise ValueError('A7C2_VEF_PINMEM_CONTROL_CONNECT requires virtual-vef-control0-pinmem-control0-v1 and the exact sixth VEF PinMem input connection profile')
    pinmem_peers=current.get('A7C2_PINMEM_PEER_CONNECT','')
    if pinmem_peers not in ('',FULL_PINMEM_PEER_CONNECTIONS_PROFILE) or (pinmem_peers and
            vef_pinmem_control_connect!=FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE):
        raise ValueError('A7C2_PINMEM_PEER_CONNECT requires virtual-pinmem-scalar-adf-drawinfo-chain-v1 and the exact seventh VEF PinMem control connection profile')
    pinmem_hdmi_video_connect=current.get('A7C2_PINMEM_HDMI_VIDEO_CONNECT','')
    if pinmem_hdmi_video_connect not in ('',FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE) or (pinmem_hdmi_video_connect and
            pinmem_peers!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE):
        raise ValueError('A7C2_PINMEM_HDMI_VIDEO_CONNECT requires virtual-pinmem-video0-hdmi-video0-initializing-v1 and the exact PinMem peer connection chain')
    pinmem_osd_connect=current.get('A7C2_PINMEM_OSD_CONNECT','')
    if pinmem_osd_connect not in ('',FULL_PINMEM_OSD_CONNECTION_PROFILE) or (pinmem_osd_connect and
            pinmem_peers!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE):
        raise ValueError('A7C2_PINMEM_OSD_CONNECT requires virtual-pinmem-osd0-osdpin-if0-ssos-v1 and the exact PinMem peer connection chain')
    adf_hdmi_audio_connect=current.get('A7C2_ADF_HDMI_AUDIO_CONNECT','')
    if adf_hdmi_audio_connect not in ('',FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE) or (adf_hdmi_audio_connect and
            pinmem_peers!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE):
        raise ValueError('A7C2_ADF_HDMI_AUDIO_CONNECT requires virtual-adf-audio0-hdmi-audio0-v1 and the exact PinMem peer connection chain')
    cp302c_no_transition=current.get('A7C2_CP302C_NO_TRANSITION','')
    if cp302c_no_transition not in ('',FULL_CP302C_NO_TRANSITION_PROFILE) or (cp302c_no_transition and (
            pinmem_hdmi_video_connect!=FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE or
            pinmem_osd_connect!=FULL_PINMEM_OSD_CONNECTION_PROFILE or
            adf_hdmi_audio_connect!=FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE or
            cp_background!='virtual-mode3-cold-v1')):
        raise ValueError('A7C2_CP302C_NO_TRANSITION requires virtual-cp302c-current0-no-transition-v1 and the exact guarded full 13-connection chain and CP3007 profile')
    cp302c_diagnostic=current.get('A7C2_CP302C_DIAGNOSTIC','')
    diagnostic_guest=current.get('MENU_CP302C_DIAGNOSTIC','')
    if (cp302c_diagnostic not in ('',FULL_CP302C_DIAGNOSTIC_PROFILE) or
            diagnostic_guest not in ('',FULL_CP302C_DIAGNOSTIC_PROFILE) or
            ((cp302c_diagnostic or diagnostic_guest) and
             (cp302c_no_transition or current.get('MENU_CP302C_NO_TRANSITION'))) or
            (cp302c_diagnostic and (
            pinmem_hdmi_video_connect!=FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE or
            pinmem_osd_connect!=FULL_PINMEM_OSD_CONNECTION_PROFILE or
            adf_hdmi_audio_connect!=FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE or
            cp_background!='virtual-mode3-cold-v1'))):
        raise ValueError('A7C2_CP302C_DIAGNOSTIC requires diagnostic-cp302c-reply-only-v1 and the exact guarded full 13-connection chain and CP3007 profile, exclusive of NO-TRANSITION')
    cp_notification_control=current.get('A7C2_CP_NOTIFICATION_CONTROL','')
    notification_guest=current.get('MENU_CP_NOTIFICATION_CONTROL','')
    if (cp_notification_control not in ('',FULL_CP_NOTIFICATION_CONTROL_PROFILE) or
            notification_guest not in ('',cp_notification_control) or
            (cp_notification_control and (not natural_boot or
            cp302c_diagnostic!=FULL_CP302C_DIAGNOSTIC_PROFILE or
            diagnostic_guest not in ('',cp302c_diagnostic)))):
        raise ValueError('A7C2_CP_NOTIFICATION_CONTROL requires the exact mode0 profile and guarded CP302c diagnostic predecessor')
    cp_capture_format=current.get('A7C2_CP_CAPTURE_FORMAT','')
    capture_format_guest=current.get('MENU_CP_CAPTURE_FORMAT','')
    if (cp_capture_format not in ('',FULL_CP_CAPTURE_FORMAT_PROFILE,FULL_CP_STARTUP_DIAGNOSTIC_PROFILE,FULL_CP_EE_DIAGNOSTIC_PROFILE,FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE,FULL_CP_OWNED_STATE_PROFILE) or
            capture_format_guest not in ('',cp_capture_format) or
            (cp_capture_format and (not natural_boot or
            cp_notification_control!=FULL_CP_NOTIFICATION_CONTROL_PROFILE))):
        raise ValueError('A7C2_CP_CAPTURE_FORMAT requires the exact profile and guarded CP notification mode0 predecessor')
    functional_camera = current.get('A7C2_FUNCTIONAL_CAMERA', '')
    functional_guest = current.get('MENU_FUNCTIONAL_CAMERA', '')
    if (functional_camera not in ('', FUNCTIONAL_CAMERA_PROFILE) or
            functional_guest not in ('', functional_camera) or
            (functional_camera and (not natural_boot or not directory_sd or
             cp_capture_format != FULL_CP_OWNED_STATE_PROFILE))):
        raise ValueError('A7C2_FUNCTIONAL_CAMERA requires the exact functional profile, natural directory-SD boot and owned-state predecessor')
    if current.get('A7C2_BACKUP_BUILD') and not backup_sync:
        raise ValueError('A7C2_BACKUP_BUILD requires the explicit Backup profile')
    if directory_sd:
        if (not natural_boot or not Path(directory_sd).is_absolute() or host_sd or sparse_sd or
                current.get('A7C2_SD_IMAGE') or imaging_profile or current.get('A7C2_SD_HOTPLUG') or
                current.get('A7C2_PREVIEW_PNG')):
            raise ValueError('Directory SD requires natural boot, absolute path and no other media profile')
    if host_sd not in ('','256gb'):
        raise ValueError('A7C2_HOST_SD must be 256gb or unset')
    if host_sd and (not natural_boot or sparse_sd or current.get('A7C2_SD_IMAGE') or
                    imaging_profile or current.get('A7C2_SD_HOTPLUG') or current.get('A7C2_PREVIEW_PNG')):
        raise ValueError('Host SD requires natural boot without RAM card/seed/imaging/hotplug/preview')
    if sparse_sd not in ('','10g-empty'):
        raise ValueError('A7C2_SD_SPARSE must be 10g-empty or unset')
    if sparse_sd and (not natural_boot or current.get('A7C2_SD_IMAGE') or current.get('A7C2_NATURAL_IMAGING_PROFILE')):
        raise ValueError('Sparse 10GiB SD requires natural boot without an image seed or imaging profile')
    if imaging_profile and (current.get('A7C2_PREVIEW_PNG') or current.get('MENU_USB_NET') == '1'):
        raise ValueError('Natural imaging is incompatible with PNG preview and USB network profiles')
    # Prior research switches must not silently change the one-click baseline.
    env = {key: value for key, value in current.items()
           if not key.startswith(('MENU_', 'QEMU_', 'SONY_'))
           and key not in ('SKIP_REBUILD', 'SEED_BACKUP', 'PRELOAD_ALL', 'CPIO_PAD_BYTES')}
    if natural_boot:
        if current.get('A7C2_JPEG_REQUEST_TRACE') not in (None, '', '1'):
            raise ValueError('A7C2_JPEG_REQUEST_TRACE must be 1 or unset')
        if current.get('A7C2_NATURAL_START_TRACE') not in (None, '', '1'):
            raise ValueError('A7C2_NATURAL_START_TRACE must be 1 or unset')
        if current.get('A7C2_INPUT_ROUTE_TRACE') not in (None, '', '1'):
            raise ValueError('A7C2_INPUT_ROUTE_TRACE must be 1 or unset')
        detail=current.get('A7C2_INPUT_ROUTE_DETAIL','')
        if detail not in ('', '1', 'canonical', 'target', 'handlers', 'flow'):
            raise ValueError('A7C2_INPUT_ROUTE_DETAIL must be 1, canonical, target, handlers, flow or unset')
        if detail and current.get('A7C2_INPUT_ROUTE_TRACE') != '1':
            raise ValueError('A7C2_INPUT_ROUTE_DETAIL requires A7C2_INPUT_ROUTE_TRACE=1')
        env.update(MENU_HEADLESS_OSD='1',MENU_SOFTWARE_LZ77='1',MENU_GPE_RGBA4444='1',
                   MENU_LIVE_APP_INPUT='1',MENU_GUI_MODELS='virtual-inline-v1',MENU_LANGUAGE_FONTS='1',
                   MENU_FRAME_OBSERVE='1',MENU_OSD_OBSERVE='1',MENU_RM_FILE='1',
                   MENU_DMM_UNIT_CONFIG='1',MENU_PANEL_REVERSE='virtual',MENU_DIG_LEVEL='virtual',
                   MENU_AUDIO_BOOT_CONFIG='1',MENU_PIN_CONTROL_MEMORY='1',MENU_PIN_CONNECTION='cold',
                   MENU_PIN_REGISTRY='1',MENU_HDMI_BOOT_CONFIG='1',MENU_VDF_CONFIG='1',
                   MENU_CP_RELEASE_SERVICE='1',MENU_CP_TIME_SERVICE='1',MENU_CRYPT_LIB='1',
                   MENU_BUSPOWER='1',MENU_DATE_SERVICE='1',QEMU_BOOT_TYPE='1',MENU_SETTLE_SECONDS='20')
        if current.get('A7C2_JPEG_REQUEST_TRACE') == '1':env['MENU_JPEG_REQUEST_TRACE']='1'
        if current.get('A7C2_NATURAL_START_TRACE') == '1':env['MENU_NATURAL_START_TRACE']='1'
        if current.get('A7C2_INPUT_ROUTE_TRACE') == '1':env['MENU_INPUT_ROUTE_TRACE']='1'
        if sparse_sd:env['A7C2_SD_SPARSE']=sparse_sd
        # The controller, not caller environment, owns and forwards the pinned media fd.
        env.pop('A7C2_HOST_SD_FD',None)
        env.pop('A7C2_DIRECTORY_SD_FD',None)
        env.pop('A7C2_DIRECTORY_SD_PROFILE',None)
        if imaging_profile:
            pcidma=(BASE/'../../source/build/qemu-pcidma-work/build').resolve()
            board=(BASE/'qemu-virt-board/virt-pcidma.dtb').resolve()
            if not (pcidma/'qemu-system-aarch64').is_file() or not board.is_file():
                raise ValueError('Natural imaging needs the verified local QEMU build and board')
            # Fixed experimental profile: caller-supplied research paths and
            # incompatible SA/data-only switches remain scrubbed.
            env.update(MENU_YC_INJECT='1',MENU_YC_UNCOMPRESSED='1',MENU_YC_INJECT_DELAY='45',
                       MENU_SETTLE_SECONDS='120',MENU_NATURAL_START_TRACE='1',MENU_JPEG_REQUEST_TRACE='1',
                       MENU_LOAD_PCIEATU='1',MENU_EXTRA_MODULES='safe',MENU_VPANEL='1',
                       MENU_DTB=str(board),A7C2_RESIZE_WATCH='1',A7C2_EE_PASSIVE_SNAPSHOT='1',
                       A7C2_FSYS_ASYNC_OBSERVE='1',QEMU_CPU_COUNT='2',QEMU_SONY_RC='1',
                       QEMU_SONY_GIC_HANDOFF='1',QEMU_SONY_SA_REFERENCE_COMPLETE='1',
                       QEMU_SONY_PCIDMA='1',QEMU_SYSTEM_DIR=str(pcidma),
                       QEMU_SYSTEM_BINARY='qemu-system-aarch64')
        if current.get('A7C2_PREVIEW_PNG'):
            if current.get('MENU_USB_NET') == '1':
                raise ValueError('PNG preview cannot use the separate USB network QEMU profile')
            png=Path(current['A7C2_PREVIEW_PNG']).resolve()
            pcidma=(BASE/'../../source/build/qemu-pcidma-work/build').resolve()
            board=(BASE/'qemu-virt-board/virt-pcidma.dtb').resolve()
            if not png.is_file() or not (pcidma/'qemu-system-aarch64').is_file() or not board.is_file():
                raise ValueError('PNG preview needs an existing PNG and the local PCI DMA QEMU build/board')
            env.update(MENU_YC_INJECT='1',MENU_YC_INPUT_PNG=str(png),MENU_YC_INJECT_DELAY='45',
                       MENU_LOAD_PCIEATU='1',MENU_EXTRA_MODULES='safe',MENU_VPANEL='1',
                       QEMU_SONY_PCIDMA='1',QEMU_SYSTEM_DIR=str(pcidma),
                       QEMU_SYSTEM_BINARY='qemu-system-aarch64',MENU_DTB=str(board))
        # Default hotplug applies only to the compatible one-card RM2 backend.
        if (current.get('MENU_RM_SLOT1') != '1' and not directory_sd and not host_sd and
                not sparse_sd and not imaging_profile and not current.get('A7C2_PREVIEW_PNG')):
            env.setdefault('A7C2_SD_HOTPLUG', '1')
        if cp_background:env['MENU_CP_BACKGROUND']=cp_background
        if udate:env['MENU_UDATE_DISTRIBUTION']=udate
        if touch_panel:env['MENU_TOUCH_PANEL']=touch_panel
        if tcin:env['MENU_TCIN_DETECT']=tcin
        if dfs:env['MENU_DFS_SELECTOR']=dfs
        if vef_path:env['MENU_VEF_PATH']=vef_path
        if adf_proc_path:env['MENU_ADF_PROC_PATH']=adf_proc_path
        if adf_set_input:env['MENU_ADF_SET_INPUT']=adf_set_input
        if adf_set_output:env['MENU_ADF_SET_OUTPUT']=adf_set_output
        if bb_set_mode:env['MENU_BB_SET_MODE']=bb_set_mode
        if imaging_connect:env['MENU_IMAGING_CONNECT']=imaging_connect
        if imaging_control_connect:env['MENU_IMAGING_CONTROL_CONNECT']=imaging_control_connect
        if imaging_adf_connect:env['MENU_IMAGING_ADF_CONNECT']=imaging_adf_connect
        if infrabb_vef_connect:env['MENU_INFRABB_VEF_CONNECT']=infrabb_vef_connect
        if infrabb_vef_control_connect:env['MENU_INFRABB_VEF_CONTROL_CONNECT']=infrabb_vef_control_connect
        if vef_pinmem_input_connect:
            env['MENU_VEF_PINMEM_INPUT_CONNECT']=vef_pinmem_input_connect
            env['SEED_BACKUP']='alllang'
        if vef_pinmem_control_connect:
            env['MENU_VEF_PINMEM_CONTROL_CONNECT']=vef_pinmem_control_connect
        if pinmem_peers:env['MENU_PINMEM_PEER_CONNECT']=pinmem_peers
        if pinmem_hdmi_video_connect:env['MENU_PINMEM_HDMI_VIDEO_CONNECT']=pinmem_hdmi_video_connect
        if pinmem_osd_connect:env['MENU_PINMEM_OSD_CONNECT']=pinmem_osd_connect
        if adf_hdmi_audio_connect:env['MENU_ADF_HDMI_AUDIO_CONNECT']=adf_hdmi_audio_connect
        if cp302c_no_transition:env['MENU_CP302C_NO_TRANSITION']=cp302c_no_transition
        if cp302c_diagnostic:env['MENU_CP302C_DIAGNOSTIC']=cp302c_diagnostic
        if cp_notification_control:env['MENU_CP_NOTIFICATION_CONTROL']=cp_notification_control
        if cp_capture_format:env['MENU_CP_CAPTURE_FORMAT']=cp_capture_format
        if functional_camera:
            env.update(MENU_FUNCTIONAL_CAMERA=functional_camera,
                       MENU_JPEG_REQUEST_TRACE='1', A7C2_FSYS_ASYNC_OBSERVE='1')
        # Single-slot diagnostic: keep the RM1 mapping opt-in and explicit
        # instead of silently inheriting other research switches.
        if current.get('MENU_RM_SLOT1')=='1':env['MENU_RM_SLOT1']='1'
        # Isolated USB-Ethernet link and its derived kernel script/DTB are also
        # opt-in; the default camera run keeps -nic none and the shipped DTB.
        for name in ('MENU_USB_NET', 'MENU_KERNEL_SCRIPT', 'MENU_DTB', 'MENU_CAPTURE_GATES',
                     'MENU_BACKUP_SAVE'):
            if current.get(name):
                env[name] = current[name]
        # QEMU_* is scrubbed for safety as well, so the isolated-USB run must name
        # its candidate build explicitly; otherwise the shipped build is used and
        # `-device usb-net` finds no usb-bus.
        if current.get('MENU_USB_NET') == '1' and current.get('QEMU_SYSTEM_DIR'):
            env['QEMU_SYSTEM_DIR'] = current['QEMU_SYSTEM_DIR']
            env.setdefault('QEMU_SYSTEM_BINARY', current.get('QEMU_SYSTEM_BINARY', 'qemu-system-aarch64'))
        return env
    env.update(MENU_HEADLESS_OSD='1', MENU_SOFTWARE_LZ77='1', MENU_GPE_RGBA4444='1',
               MENU_LANGUAGE_FONTS='1',
               MENU_APPLY_MENU='1', MENU_FRAME_OBSERVE='1', MENU_OSD_OBSERVE='1',
               MENU_CTOR_CENSUS='1', MENU_OPEN_SET='0x308', MENU_OPEN_SET_LOG_ONLY='1',
               MENU_MODE_SENTINELS='1', MENU_SETTLE_SECONDS='8', QEMU_BOOT_TYPE='1', MENU_DATE_SERVICE='1')
    # Same opt-in forwarding for the non-natural profile: without it the isolated
    # USB run silently falls back to the shipped build (no sysbus xHCI).
    for name in ('MENU_USB_NET', 'MENU_KERNEL_SCRIPT', 'MENU_DTB', 'MENU_CAPTURE_GATES',
                 'MENU_BACKUP_SAVE'):
        if current.get(name):
            env[name] = current[name]
    if current.get('MENU_USB_NET') == '1' and current.get('QEMU_SYSTEM_DIR'):
        env['QEMU_SYSTEM_DIR'] = current['QEMU_SYSTEM_DIR']
        env.setdefault('QEMU_SYSTEM_BINARY', current.get('QEMU_SYSTEM_BINARY', 'qemu-system-aarch64'))
    if menu_key:
        env.update(MENU_KEY_INJECT='0x1ab,0,1,0,1,0.05,0', MENU_KEY_POST_WAIT='2')
    return env


def result_directory(output, runs):
    decoder = json.JSONDecoder()
    for match in reversed(list(re.finditer(r'^\{', output, re.MULTILINE))):
        try:
            info, _ = decoder.raw_decode(output[match.start():])
        except ValueError:
            continue
        if isinstance(info, dict) and info.get('probe_collected') is True and isinstance(info.get('run'), str):
            run = Path(info['run']).resolve()
            if run.parent != runs.resolve():
                raise ValueError('运行结果不在本项目 menu-runs 目录中')
            return run
    raise ValueError('未取得本次运行的结果目录；请检查上方启动日志')


def verify_snapshot(run):
    from PIL import Image
    raw, info = decode_export((run / 'console.log').read_bytes())
    if (run / 'headless-osd-frame.bin').read_bytes() != raw:
        raise ValueError('保存的快照与原始导出不一致')
    if (run / 'headless-osd-pixels.bin').read_bytes() != raw[HEADER + METADATA:]:
        raise ValueError('保存的像素与提交容器不一致')
    image = run / 'headless-osd-pixels-rgba4444-software.png'
    with Image.open(image) as picture:
        if picture.size != (640, 480) or picture.convert('RGB').getcolors(maxcolors=2) is not None:
            raise ValueError('本次画面为空或仅为纯色；未将其视为菜单成功')
    return image, info


def main():
    parser = argparse.ArgumentParser(description='一键启动隔离QEMU、采集并打开已验证菜单快照；完成后自动关闭VM。不是常驻交互窗口。')
    parser.add_argument('--menu-key', action='store_true', help='追加已验证的 MENU/返回短按；可能退出当前菜单')
    parser.add_argument('--no-open', action='store_true', help='仅保存快照，不调用桌面图片查看器')
    args = parser.parse_args()
    for command in ('bash', 'flock', 'clang', 'cpio', 'bwrap'):
        if not shutil.which(command):
            parser.error('缺少依赖：' + command)
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        parser.error('需要已安装的 Python Pillow 才能验证和显示快照')
    print('启动 A7C II 菜单实验：重建 → 隔离运行 → 校验快照 → 关闭 VM。', flush=True)
    print('仅 AP 软件输出；常驻原生窗口请使用 start-a7c2-native.sh。', flush=True)
    lines = []
    with subprocess.Popen(['bash', str(BASE / 'run-menu-probe.sh')], cwd=ROOT,
                          env=profile_environment(os.environ, args.menu_key),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
        for line in process.stdout:
            print(line, end='', flush=True)
            lines.append(line)
        code = process.wait()
    if code:
        return code if code > 0 else 1
    try:
        run = result_directory(''.join(lines), BASE / 'menu-runs')
        image, info = verify_snapshot(run)
    except (OSError, ValueError, IndexError) as error:
        print('快照验收失败：' + str(error), file=sys.stderr)
        return 1
    print(f'\n已验证本次提交：事务 {info["sequence"]}，像素来源 {info["pixel_source_seq"]}')
    print(f'图片：{image}\n日志与元数据：{run}')
    print('VM 已退出；此入口用于复现快照，不提供实时相机操作。')
    if not args.no_open and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) and shutil.which('xdg-open'):
        subprocess.Popen(['xdg-open', str(image)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
