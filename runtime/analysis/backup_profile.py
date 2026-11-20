"""Explicit native Backup fixture/profile; no CP execution or capture claim."""
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shlex
import stat
import uuid

from sd_transport import directory, regular, digest_fd, identity

PROFILE = 'virtual-primary-v1'
SEED_SHA = '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
PRIMARY_SHA = 'a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977'
PRIMARY_BYTES = 0x15a8f8
ADF_PROFILE = 'virtual-source7-idle-v1'
INPUT_PROFILE = 'virtual-input-s0-v1'
OUTPUT_PROFILE = 'virtual-output-nochange-v1'
BB_SET_MODE_PROFILE = 'virtual-bb-still-target3-op0-v1'
IMAGING_CONNECT_PROFILE = 'virtual-imaging-out1-bb-in1-v1'
IMAGING_CONTROL_CONNECT_PROFILE = 'virtual-imaging-control0-bb-control0-v1'
IMAGING_ADF_CONNECT_PROFILE = 'virtual-imaging-audio0-adf-audio0-v1'
INFRABB_VEF_CONNECT_PROFILE = 'virtual-infrabb-out1-vef-in1-same-format-v1'
FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE = 'virtual-infrabb-control0-vef-control0-v1'
FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE = 'virtual-vef-out2-pinmem-in0-forward-format-v1'
FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE = 'virtual-vef-control0-pinmem-control0-v1'
FULL_PINMEM_PEER_CONNECTIONS_PROFILE = 'virtual-pinmem-scalar-adf-drawinfo-chain-v1'
FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE = 'virtual-adf-audio0-hdmi-audio0-v1'
FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE = 'virtual-pinmem-video0-hdmi-video0-initializing-v1'
FULL_PINMEM_OSD_CONNECTION_PROFILE = 'virtual-pinmem-osd0-osdpin-if0-ssos-v1'
FULL_CP302C_NO_TRANSITION_PROFILE = 'virtual-cp302c-current0-no-transition-v1'
FULL_CP302C_DIAGNOSTIC_PROFILE = 'diagnostic-cp302c-reply-only-v1'
FULL_CP_NOTIFICATION_CONTROL_PROFILE = 'virtual-cp-notification-mode0-v1'
FULL_CP_CAPTURE_FORMAT_PROFILE = 'diagnostic-cp402d-reply-only-v1'
FULL_CP_STARTUP_DIAGNOSTIC_PROFILE = 'diagnostic-cp-startup-controls-v1'
FULL_CP_EE_DIAGNOSTIC_PROFILE = 'diagnostic-cp-ee-controls-v1'
FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE = 'diagnostic-cp-movie-format-v1'
FULL_CP_OWNED_STATE_PROFILE = 'virtual-cp-owned-state-v1'
FUNCTIONAL_CAMERA_PROFILE = 'virtual-functional-camera-v1'
FUNCTIONAL_CAMERA_RAM_MEDIA_CANDIDATE = 'direct-bootin-ram-card-1g-v1'
FUNCTIONAL_CAMERA_RAM_BYTES = 1024**3
ADF_CONFLICTS = (
    'MENU_YC_INJECT','MENU_YC_UNCOMPRESSED','MENU_YC_INPUT_RAW','MENU_YC_INPUT_PNG',
    'MENU_PIPELINE_ENDPOINT','MENU_PIPELINE_VIRT','MENU_BB_READY_INJECT','MENU_BB_READY_LATE',
    'MENU_ACTIVATE_MODE','MENU_ACTIVATE_CAPTURED','MENU_CTOR_CENSUS','MENU_OPEN_SET','MENU_FORCE_SET',
    'MENU_BUILD_CONTROLLER','MENU_BUILD_CONTROLLER2','MENU_MENU_INIT','MENU_OPEN_SCREEN',
    'MENU_HONEST_ROUTING','MENU_ASYNC_SEND','MENU_SYNC_DIRECT','MENU_SYNC_MSG_HOOK',
    'MENU_PCIDMA_XFER','MENU_VPANEL','MENU_VIRTUAL_CP_SENDER','MENU_PCIE_IF','MENU_CP_EMULATION',
    'MENU_SEQ4BD_CREATE','MENU_DISPLAY_SETUP_REQUEST','MENU_APPLY_MENU','MENU_APPLY_SWEEP',
    'MENU_APPLY_TARGET','MENU_OPEN_SET_EXECUTE','MENU_BUILD2_THEN_INIT','MENU_FORCE_OPEN_AFTER',
    'MENU_FORCE_IN_FACTORY','MENU_INFRA_AVBBC','MENU_SEQ_EVENT','MENU_CP_EVENT_INJECT',
    'MENU_SUBSCRIPTION_EVENT','MENU_SUBSCRIPTION_SERVICE',
)
BB_MODE_CONFLICTS = tuple(dict.fromkeys((*ADF_CONFLICTS,
    'A7C2_NATURAL_IMAGING_PROFILE','A7C2_PREVIEW_PNG','A7C2_FULL_SYSTEM_PROFILE',
    'MENU_FRAME_INJECT','MENU_FRAME_INJECT_RAW','MENU_FRAME_INJECT_PNG',
    'MENU_FRAME_SOURCE_RAW','MENU_FRAME_SOURCE_PNG','MENU_FULL_SYSTEM',
    'MENU_VPANEL','MENU_PCIDMA_XFER','MENU_CP_EMULATION',
    'A7C2_CP_EMULATION','QEMU_SONY_RC','QEMU_SONY_SA_DATA_ONLY','QEMU_SONY_SA_REFERENCE_COMPLETE')))


def adf_proc_profile_fields(profile):
    """Intent only: independent guest timerfd control events, never native frequency."""
    if profile not in ('',ADF_PROFILE):
        raise ValueError('ADF proc path must be virtual-source7-idle-v1 or unset')
    return {'adf_proc_path_profile':profile or None,
            'adf_proc_path_protocol':'AP0323-path0-source7-idle-control-v1' if profile else None,
            'adf_proc_clock_policy':'virtual-source7-control-events-v1' if profile else None,
            'adf_proc_clock_period_ns':1000000 if profile else None,
            'adf_proc_original_cp_executed':False,'adf_proc_hardware_verified':False,
            'adf_proc_native_frequency_verified':False,'adf_proc_original_event_identity_verified':False,
            'adf_proc_frames_verified':False,'adf_proc_pcm_verified':False,
            'adf_proc_audio_output_verified':False,'adf_proc_capture_verified':False}


def adf_set_input_profile_fields(profile):
    """Intent only: metadata config retains the independent AB failure and shared clock."""
    if profile not in ('',INPUT_PROFILE):
        raise ValueError('ADF set input must be virtual-input-s0-v1 or unset')
    return {'adf_set_input_profile':profile or None,
            'adf_set_input_protocol':'AP0336-type0-input-config-S0-v1' if profile else None,
            'adf_set_input_clock_policy':'virtual-source7-control-events-v1' if profile else None,
            'adf_set_input_clock_period_ns':1000000 if profile else None,
            'adf_set_input_clock_generation':2 if profile else None,
            'adf_set_input_clock_sequence_start':5 if profile else None,
            'adf_set_input_clock_sequence_end':8 if profile else None,
            'adf_set_input_clock_counter_reset':False,
            'adf_set_input_engine_state':0 if profile else None,
            'adf_set_input_ab_opcode':0xab if profile else None,
            'adf_set_input_ab_status':1 if profile else None,
            'adf_set_input_aip_task_error':0x1004 if profile else None,
            'adf_set_input_glee_callback_metadata':0 if profile else None,
            'adf_set_input_completion_scope':'metadata-configuration-only' if profile else None,
            'adf_set_input_kikilog_padding_policy':'virtual-zero-last2' if profile else None,
            'adf_set_input_original_cp_executed':False,'adf_set_input_hardware_verified':False,
            'adf_set_input_native_frequency_verified':False,
            'adf_set_input_original_event_identity_verified':False,
            'adf_set_input_pcm_verified':False,'adf_set_input_frames_verified':False,
            'adf_set_input_ap_consumed':False,'adf_set_input_capture_verified':False}


def adf_set_output_profile_fields(profile):
    """Intent only: same-owner W0/O8 configuration, never native AP consumption."""
    if profile not in ('',OUTPUT_PROFILE):
        raise ValueError('ADF set output must be virtual-output-nochange-v1 or unset')
    fields={'profile':profile or None,
            'protocol':'AP032d-26B-output-nochange-W0-O8-v1',
            'request_bytes':26,'request_flags':0,
            'request_hex':'0d202d031a000180000001000101010100000000000000000000',
            'i2s_hex':'0100010101010000','hdmi_hex':'0000000000000000',
            'completion_scope':'virtualOutputConfigurationNoChange',
            'clock_policy':'virtual-source7-control-events-v1','clock_period_ns':1000000,
            'clock_generation':3,'clock_sequence_start':9,'clock_sequence_end':9,
            'output_owner':'same-Output60','old_mask':8,'target_mask':8,
            'prior_avio_stages':3,'prior_source_cache':255,
            'mask_rule':'W0/O8 yields 8 for every unknown SYSTEMSOUND predicate',
            'power_owner':'same-Glee','power20':0,'power22':0,
            'monitor_generation':2,'monitor_notify':2,'monitor_format_bytes':20,
            'monitor_format_hex':'0000000001000101010100000000000000000000',
            'monitor_prior_notifies':[1,4],'monitor_control13d':[1,0,0],
            'aip_business_generation':3,'aip_new_b0_commands':1,
            'disable_writes_total':21,'disable_readbacks_total':21,
            'avio_generation':2,'avio_jobs':1,'avio_job_hex':'0000080000000000616f6600',
            'avio_shadow_writes_added':0,
            'completion_order':'new-B0-before-AVIO-NoOp',
            'native_consumption_requires':'original-AP132d-reply-free'}
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'system_sound_snapshot_known','clock_counter_reset','original_cp_executed',
        'hardware_verified','audio_output_verified','native_frequency_verified',
        'original_event_identity_verified','pcm_verified','frames_verified',
        'ap_consumed','native_verified','capture_verified')})
    return {'adf_set_output_'+name:value for name,value in fields.items()}


def bb_set_mode_profile_fields(profile):
    if profile not in ('',BB_SET_MODE_PROFILE):
        raise ValueError('BB set mode must be virtual-bb-still-target3-op0-v1 or unset')
    selected=bool(profile)
    fields={
        'profile':profile or None,
        'request_bytes':10,
        'request_hex':'0d2010010a0001800000',
        'ap_input_u32':[2,0],
        'operation_mode':0,
        'initial_state_bytes':'0100000000000000000000000000000000000000000000000100000000000000',
        'state_source':'virtual public CP image initializer',
        'state_word0':1,
        'state_word6':1,
        'state_policy':'virtual-public-cp-image-initializer-prefix-audit-v1',
        'target_selection_policy':'state-word-1-operation-mode-0-first-generation-only',
        'target':3,
        'config_copy_bytes':1760,
        'config_initial_known_bytes':1565,
        'config_initial_unknown_bytes':195,
        'config_postprefix_known_bytes':4,
        'config_postprefix_unknown_bytes':1756,
        'work_queues':['queue3','queue4'],
        'outer_consumer_task':30,
        'inner_consumer_task':31,
        'internal_completion_events':[0x21a,0x21a],
        'unique_1110_reply_count':1,
        'tasklocal_consumer_policy':'virtual-tasklocal-generation1-only-v1',
    }
    fields={name:(value if selected else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'state_is_original_cp_live_state','original_cp_executed','live_cp_ram_read',
        'hardware_verified','hardware_mode_change_verified','native_mode_change_verified',
        'original_task_scheduler_verified','ap_consumed','frames_verified','capture_verified')})
    return {'bb_set_mode_'+name:value for name,value in fields.items()}


def imaging_pin_connection_profile_fields(profile):
    """Intent only: first control edge and SSYN configuration, never pixels."""
    if profile not in ('',IMAGING_CONNECT_PROFILE):
        raise ValueError('Imaging connection must be virtual-imaging-out1-bb-in1-v1 or unset')
    fields={
        'profile':profile or None,
        'source_pin':[0,2,1,0x90050004],
        'peer_pin':[0,1,1,0x9284074a],
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'sink_connected_marker_CP_VA':0x01acad10,'sink_connected_marker_value':1,
        'sink_connected_marker_initial_value_known':False,
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'dmm_unit':0x404,'dmm_owner_code':0x284,
        'dmm_owner_policy':'original-semantic-owner-code-not-service-SID',
        'dmm_allocate_message_bytes':216,'dmm_allocate_option':1,
        'dmm_operations':[0x20,0x25,0x24,0x23],'dmm_free_option':2,
        'buffer_bytes':80,'ssyn_header_hex':'06000000','ssyn_key':0,
        'format_payload_bytes':16,'format_payload_hex':'01000000000000008007000038040000',
        'format_notice_bytes':80,'format_notice_command':[0x1000,0x104,0x38,1],
        'config_after':[0,1,1920,1080,0],'config_semaphore':0x21,
        'config_lock_policy':'local-pthread-exclusion-not-original-semaphore-timing',
        'references_owner_open':[[1,0],[1,0],[1,1],[0,0]],
        'reference_stages':['creator-close','same-owner-transfer','consumer-open','consumer-Free'],
        'reference_policy':'same-owner-transfer-without-command21-share',
        'source_state_source':'public-InfraImaging-image-constructor',
        'mapping_profile':'virtual-pin-control-reserved-ram-v1',
        'completion_scope':'first-edge-control-and-SSYN-config-only',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_cp_ram_mapping_verified','original_task_scheduler_verified',
        'original_semaphore_timing_verified','hardware_verified','ap_consumed',
        'runtime_consumed','connection_verified','format_consumed','frames_verified','capture_verified')})
    return {'imaging_pin_connection_'+name:value for name,value in fields.items()}


def imaging_control_connection_profile_fields(profile):
    """Intent only: second type8 edge, preserving the consumed first-edge format."""
    if profile not in ('',IMAGING_CONTROL_CONNECT_PROFILE):
        raise ValueError('Imaging control connection must be virtual-imaging-control0-bb-control0-v1 or unset')
    fields={
        'profile':profile or None,
        'source_pin':[8,2,0,0x90050004],'peer_pin':[8,1,0,0x9284074a],
        'source_registry_count':6,'source_registry_slot':5,
        'sink_registry_count':21,'sink_registry_slot':8,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'sink_connected_marker_CP_VA':0x01acad0f,'sink_connected_marker_value':1,
        'sink_connected_marker_initial_value_known':False,
        'sink_posthook_mask':0x3fe,'sink_posthook_index':0,'sink_posthook_selected':False,
        'dmm_allocation_count':0,'ssyn_notice_count':0,'format_cache_write_count':0,
        'first_edge_profile':IMAGING_CONNECT_PROFILE,
        'first_edge_requires_ap_consumed':True,'first_edge_requires_clean':True,
        'first_edge_requires_marker_known':True,'first_edge_marker_value':1,
        'first_edge_requires_data_Free':True,'first_edge_requires_pool_released':True,
        'first_edge_dmm_counters_unchanged':True,'first_edge_payload_unchanged':True,
        'first_edge_cache_unchanged':True,'first_edge_marker_unchanged':True,
        'first_edge_config_after':[0,1,1920,1080,0],
        'completion_scope':'first-edge-prerequisite-and-zero-format-effects',
        'source_state_source':'public-InfraImaging-image-constructor',
        'mapping_profile':'virtual-pin-control-reserved-ram-v1',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_cp_ram_mapping_verified','live_cp_ram_read',
        'original_task_scheduler_verified','original_semaphore_timing_verified','hardware_verified',
        'ap_consumed','runtime_consumed','control_consumed','connection_verified',
        'frames_verified','capture_verified')})
    return {'imaging_control_connection_'+name:value for name,value in fields.items()}


def imaging_adf_connection_profile_fields(profile):
    """Intent only: third type3 handshake preserves both prior edges and ADF history."""
    if profile not in ('',IMAGING_ADF_CONNECT_PROFILE):
        raise ValueError('Imaging ADF connection must be virtual-imaging-audio0-adf-audio0-v1 or unset')
    fields={
        'profile':profile or None,
        'source_pin':[3,2,0,0x90050004],'peer_pin':[3,1,0,0x9058003f],
        'source_registry_count':6,'source_registry_slot':4,
        'sink_registry_count':10,'sink_registry_slot':4,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'sink_callback_guard_type':5,'sink_callback_guard_direction':1,'sink_callback_guard_index':0,
        'sink_callback_guard_checked':True,'sink_callback_selected':False,
        'sink_connected_marker_write_count':0,'dmm_allocation_count':0,'ssyn_notice_count':0,
        'pcm_consumption_count':0,'new_b0_command_count':0,'source7_event_count':0,
        'avio_job_count':0,'format_cache_write_count':0,
        'first_edge_profile':IMAGING_CONNECT_PROFILE,'control_edge_profile':IMAGING_CONTROL_CONNECT_PROFILE,
        'first_edge_requires_ap_consumed':True,'first_edge_requires_clean':True,
        'first_edge_requires_marker_known':True,'first_edge_marker_value':1,
        'first_edge_requires_data_Free':True,'first_edge_requires_pool_released':True,
        'control_edge_requires_ap_consumed':True,'control_edge_requires_clean':True,
        'control_edge_requires_marker_known':True,'control_edge_marker_value':1,
        'predecessors_require_no_outstanding':True,'predecessor_histories_unchanged':True,
        'first_edge_config_after':[0,1,1920,1080,0],
        'completion_scope':'two-edge-prerequisites-and-zero-audio-format-effects',
        'source_state_source':'public-InfraImaging-image-constructor',
        'sink_state_source':'public-InfraADF-image-constructor',
        'mapping_profile':'virtual-pin-control-reserved-ram-v1',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_cp_ram_mapping_verified','live_cp_ram_read',
        'original_task_scheduler_verified','original_semaphore_timing_verified','hardware_verified',
        'ap_consumed','runtime_consumed','control_consumed','connection_verified',
        'callback_guard_verified','pcm_verified','audio_output_verified','frames_verified','capture_verified')})
    return {'imaging_adf_connection_'+name:value for name,value in fields.items()}


def infrabb_vef_connection_profile_fields(profile):
    """Intent only: fourth same-format edge, preserving all existing owners/history."""
    if profile not in ('',INFRABB_VEF_CONNECT_PROFILE):
        raise ValueError('InfraBB VEF connection must be virtual-infrabb-out1-vef-in1-same-format-v1 or unset')
    fields={
        'profile':profile or None,
        'source_pin':[0,2,1,0x9284074a],'peer_pin':[0,1,1,0x905a0048],
        'source_registry_count':21,'source_registry_slot':5,
        'sink_registry_count':16,'sink_registry_slot':1,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'sink_connected_marker_write_count':0,
        'first_edge_profile':IMAGING_CONNECT_PROFILE,'control_edge_profile':IMAGING_CONTROL_CONNECT_PROFILE,
        'audio_edge_profile':IMAGING_ADF_CONNECT_PROFILE,
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'predecessors_require_format_preserved':True,
        'predecessors_require_pool_retired':True,'predecessor_histories_unchanged':True,
        'first_edge_config_after':[0,1,1920,1080,0],
        'precondition_refusal_policy':'unadmitted-only-no-request-or-fault-until-predecessors-ready',
        'vef_current_info_bytes':20,'vef_current_info_hex':'0100000000000000010000008007000038040000',
        'vef_pin_index':1,'vef_ordinal':0,'vef_code':1,'vef_component':0,'vef_flags':0,
        'vef_width':1920,'vef_height':1080,
        'format_command_frame':0x2002,'format_command':0xf008,'format_command_bytes':36,
        'format_command_copy_bytes':20,'format_prepare_context':1,'format_command_initial_state':0,
        'format_execute_context':3,'format_execute_type':2,
        'format_execution_policy':'synchronous-context3-type2-not-RTOS-queued-task',
        'old_command_list_policy':'opaque-preserved','old_ordinal1_preserved':True,
        'nomem_history_preserved':True,'s0_ab_failure_history_preserved':True,
        'dmm_unit':0x404,'dmm_owner_code':0x284,
        'dmm_owner_policy':'original-semantic-owner-code-not-service-SID',
        'dmm_sender_policy':'virtual-service-senders-not-original-dynamic-type2a',
        'dmm_allocate_message_bytes':152,'dmm_allocate_option':1,'dmm_allocate_wait':0xffffffff,
        'dmm_creator':'VEF','dmm_creator_close_message_bytes':152,
        'dmm_consumer_message_bytes':216,'dmm_consumer_token':0x55,
        'dmm_open_option':0,'dmm_open_wait':0xffffffff,'dmm_free_option':0,
        'dmm_operations':[0x20,0x25,0x24,0x25,0x23],'dmm_share_count':0,
        'buffer_bytes':80,'ssyn_header_hex':'02000000','ssyn_entry_type':0,'ssyn_key':0,
        'format_payload_bytes':16,'format_payload_hex':'01000000000000008007000038040000',
        'format_notice_bytes':80,'format_notice_command':[0x1000,0x104,0x38,1],
        'format_notice_fields':['peer_pin','source_pin','unit','handle',0,0],
        'format_comparison_fields':['code_u8','component_u8','flags_u16','width_u32','height_u32'],
        'format_unused_payload_offset':4,'format_unused_payload_policy':'ignored-by-semantic-comparison',
        'format_digest_bytes':16,'format_policy':'fixed-known-same-format-only-reject-unknown-metadata',
        'different_format_policy':'fault-and-hold-mapped-buffer-without-Free-or-forward',
        'different_format_unimplemented':'rewrite-BB-table-then-forward-to-connected-BB-IN1-upstream-9005',
        'references_owner_open':[[1,1],[1,0],[1,0],[1,1],[1,0],[0,0]],
        'reference_stages':['allocate','creator-close','same-owner-transfer','consumer-open','consumer-close','consumer-Free'],
        'reference_policy':'same-owner-transfer-without-command21-share',
        'reply_publication_policy':'after-finite-format-Close-Free-before-AP-consumption',
        'source_state_source':'public-InfraBB-image-constructor',
        'sink_state_source':'public-InfraVEF-image-constructor',
        'mapping_profile':'virtual-pin-control-reserved-ram-v1',
        'completion_scope':'three-edge-prerequisites-and-same-format-metadata-only',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_cp_ram_mapping_verified','original_cp_page_tables_verified',
        'live_cp_ram_read','original_task_scheduler_verified','original_RTOS_timing_verified',
        'original_cp_command_list_verified','original_semaphore_timing_verified','hardware_verified',
        'ap_consumed','runtime_consumed','native_verified','connection_verified','format_consumed',
        'general_format_ready','cmos_verified','aip_clocks_verified','frames_verified','capture_verified')})
    return {'infrabb_vef_connection_'+name:value for name,value in fields.items()}


def infrabb_vef_control_connection_profile_fields(profile):
    """Intent only: fifth type8 edge, preserving the four consumed predecessors."""
    if profile not in ('',FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE):
        raise ValueError('InfraBB VEF control connection must be virtual-infrabb-control0-vef-control0-v1 or unset')
    fields={
        'profile':profile or None,
        'source_pin':[8,2,0,0x9284074a],'peer_pin':[8,1,0,0x905a0048],
        'source_registry_count':21,'source_registry_slot':9,'source_object_CP_VA':0x01789514,
        'sink_registry_count':16,'sink_registry_slot':14,'vef_current_ordinal':14,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'source_posthook_direction':2,'source_posthook_selected':False,
        'source_type8_marker_selected':False,'sink_connected_marker_write_count':0,
        'vef_posthook_allowed_ordinals':[1,2,3],'vef_posthook_selected':False,
        'dmm_allocation_count':0,'ssyn_notice_count':0,'format_cache_write_count':0,
        'vef_current_info_write_count':0,'f008_command_count':0,
        'source7_event_count':0,'clock_write_count':0,'mmio_write_count':0,'frame_count':0,
        'first_edge_profile':IMAGING_CONNECT_PROFILE,'control_edge_profile':IMAGING_CONTROL_CONNECT_PROFILE,
        'audio_edge_profile':IMAGING_ADF_CONNECT_PROFILE,'image_edge_profile':INFRABB_VEF_CONNECT_PROFILE,
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'predecessors_require_data_Free':True,
        'predecessors_require_pool_retired':True,'predecessors_require_format_preserved':True,
        'predecessor_histories_unchanged':True,'nomem_history_preserved':True,
        's0_ab_failure_history_preserved':True,'dmm_counters_unchanged':True,
        'backing_records_preserved':[0,1],'first_edge_config_after':[0,1,1920,1080,0],
        'precondition_refusal_policy':'unadmitted-only-no-request-or-fault-until-predecessors-ready',
        'source_state_source':'public-InfraBB-image-constructor',
        'sink_state_source':'public-InfraVEF-image-constructor',
        'registry_initial_state':'cold-disconnected-not-ready',
        'mapping_profile':'virtual-pin-control-reserved-ram-v1',
        'completion_scope':'four-edge-prerequisites-and-zero-format-effects',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_cp_ram_mapping_verified','original_cp_page_tables_verified',
        'live_cp_ram_read','original_task_scheduler_verified','original_RTOS_timing_verified',
        'original_semaphore_timing_verified','hardware_verified','ap_consumed','runtime_consumed',
        'native_verified','control_consumed','connection_verified','format_consumed',
        'general_format_ready','cmos_verified','frames_verified','capture_verified')})
    return {'infrabb_vef_control_connection_'+name:value for name,value in fields.items()}


def vef_pinmem_input_connection_profile_fields(profile):
    """Intent only: same-handle metadata propagation through the existing live caches."""
    if profile not in ('',FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE):
        raise ValueError('VEF PinMem input connection must be virtual-vef-out2-pinmem-in0-forward-format-v1 or unset')
    fields={
        'profile':profile or None,
        'source_pin':[0,2,2,0x905a0048],'peer_pin':[0,1,0,0x90590818],
        'source_registry_count':16,'source_registry_slot':9,
        'sink_registry_count':13,'sink_registry_slot':0,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'pinmem_record_index':0,'pinmem_record_raw_flags':3,'pinmem_record_code':1,
        'pinmem_record_component':1,'pinmem_record_width':1920,'pinmem_record_height':1080,
        'pinmem_record_source':'virtual-public-PinMem-constructor-projection',
        'ssyn_header_hex':'01000000','ssyn_entry_type':0,'ssyn_key':0,'buffer_bytes':80,
        'format_payload_bytes':16,'format_payload_hex':'01010300000000008007000038040000',
        'format_payload_fnv64':'37228cd728b41c0d',
        'dmm_unit':0x404,'dmm_operations':[0x20,0x21,0x23,0x24,0x25,0x24,0x25,0x24,0x23],
        'dmm_message_bytes':[152,152,152,152,152,216,216,216,216],
        'dmm_allocate_option':1,'dmm_allocate_wait':0xffffffff,
        'dmm_share_count':1,'dmm_creator_release_option':2,'dmm_free_option':2,
        'dmm_vef_open_wait':0,'dmm_bb_open_wait':0xffffffff,'dmm_imaging_open_wait':0,
        'dmm_consumer_token':0x55,
        'references_owner_open':[[1,1],[2,1],[1,0],[1,1],[1,0],[1,1],[1,0],[1,1],[0,0]],
        'reference_stages':['allocate','initial-share','creator-Free2','VEF-open','VEF-close',
                            'BB-open','BB-close','Imaging-open','Imaging-Free2'],
        'reference_policy':'one-initial-share-same-handle-forward-without-per-hop-share',
        'format_notice_count':3,'format_notice_bytes':80,
        'format_notice_command':[0x1000,0x104,0x38,1],
        'format_notice_edges':[
            [[0,1,0,0x90590818],[0,2,2,0x905a0048]],
            [[0,1,1,0x905a0048],[0,2,1,0x9284074a]],
            [[0,1,1,0x9284074a],[0,2,1,0x90050004]]],
        'format_handle_policy':'same-mapped-handle-for-all-three-consumers',
        'format_cache_policy':'update-existing-authoritative-VEF-BB-Imaging-live-caches',
        'vef_current_after_hex':'0100000000000000010103008007000038040000',
        'bb_expected_after_hex':'01010300000000008007000038040000',
        'imaging_config_after':[1,1,1920,1080,3],
        'runtime_status22_required':1,'runtime_status22_known_required':1,
        'runtime_status22_writer_generation_required':1,'runtime_status22_writes_required':1,
        'runtime_status22_source':'earlier-SetPath1-completion-writer-not-NoMem-state2',
        'first_edge_profile':IMAGING_CONNECT_PROFILE,'control_edge_profile':IMAGING_CONTROL_CONNECT_PROFILE,
        'audio_edge_profile':IMAGING_ADF_CONNECT_PROFILE,'image_edge_profile':INFRABB_VEF_CONNECT_PROFILE,
        'vef_control_edge_profile':FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE,
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'predecessors_require_pool_retired':True,
        'historical_first_fourth_commands_Free_AP_preserved':True,
        'nomem_history_preserved':True,'s0_ab_failure_history_preserved':True,
        'old_ordinal1_preserved':True,'foreign_speech_live_preserved':True,
        'precondition_refusal_policy':'unadmitted-only-no-request-or-fault-until-predecessors-ready',
        'partial_failure_policy':'fault-and-hold-live-buffer-and-current-cache-without-rollback',
        'mapping_profile':'virtual-pin-control-reserved-ram-v1',
        'buffer_physical_base':0x500000000,'buffer_cp_virtual_base':0x80000000,
        'buffer_pool_policy':'same-existing-pool-without-reset',
        'dispatch_policy':'exact-edge-before-legacy-VEF-send-enter-other-traffic-falls-through',
        'completion_scope':'five-edge-prerequisites-and-three-hop-format-metadata-only',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_cp_ram_mapping_verified','original_cp_page_tables_verified',
        'live_cp_ram_read','original_task_scheduler_verified','original_RTOS_timing_verified',
        'original_semaphore_timing_verified','hardware_verified','ap_consumed','runtime_consumed',
        'runtime_status22_verified','native_verified','connection_verified','format_consumed',
        'format_propagation_verified','general_format_ready','cmos_verified','frames_verified','capture_verified')})
    return {'vef_pinmem_input_connection_'+name:value for name,value in fields.items()}


def vef_pinmem_control_connection_profile_fields(profile):
    """Intent only: exact type8 edge consuming event8 and preserving all live format caches."""
    if profile not in ('',FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE):
        raise ValueError('VEF PinMem control connection must be virtual-vef-control0-pinmem-control0-v1 or unset')
    fields={
        'profile':profile or None,
        'source_pin':[8,2,0,0x905a0048],'peer_pin':[8,1,0,0x90590818],
        'source_registry_count':16,'source_registry_slot':15,
        'sink_registry_count':13,'sink_registry_slot':12,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'source_event':8,'event_parameter_bytes':32,'event_parameter_pointer_offset':0,
        'event_pointer_policy':'virtual-token-bound-to-owned-72B-message',
        'event_peer_check':'saved-original-full-peer-key-must-equal-reply-peer-key',
        'source_posthook_ordinal':15,'source_posthook_allowed_ordinals':[1,2,3],
        'source_posthook_selected':False,'sink_manager':'VDF::VdfRawPinManager',
        'sink_manager_callback_raw':0x5d6a86,'sink_manager_callback_hex':'00207047',
        'sink_manager_callback_expected_return':0,
        'connected_marker_write_count':0,'dmm_command_count':0,'ssyn_notice_count':0,
        'format_cache_write_count':0,'current_info_write_count':0,'f008_command_count':0,
        'clock_write_count':0,'mmio_write_count':0,'frame_count':0,
        'input_edge_profile':FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE,
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'predecessors_require_pool_retired':True,
        'predecessor_histories_unchanged':True,'imaging_config_preserved':[1,1,1920,1080,3],
        'nomem_history_preserved':True,'s0_ab_failure_history_preserved':True,
        'old_ordinal1_preserved':True,'foreign_speech_live_preserved':True,
        'precondition_refusal_policy':'unadmitted-only-no-request-or-fault-until-predecessors-ready',
        'dispatch_policy':'exact-edge-before-legacy-VEF-send-enter-other-traffic-falls-through',
        'completion_scope':'six-edge-prerequisites-and-event8-control-no-format-side-effects',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_cp_ram_mapping_verified','original_cp_page_tables_verified',
        'original_event_pointer_verified','original_task_scheduler_verified','original_RTOS_timing_verified',
        'original_semaphore_timing_verified','hardware_verified','ap_consumed','runtime_consumed',
        'native_verified','event8_consumed','connection_verified','format_consumed',
        'general_format_ready','cmos_verified','frames_verified','capture_verified')})
    return {'vef_pinmem_control_connection_'+name:value for name,value in fields.items()}


def pinmem_peer_connections_profile_fields(profile):
    """Intent only: three finite PinMem metadata edges sharing the same event6 consumer."""
    if profile not in ('',FULL_PINMEM_PEER_CONNECTIONS_PROFILE):
        raise ValueError('PinMem peer connections must be virtual-pinmem-scalar-adf-drawinfo-chain-v1 or unset')
    fields={
        'profile':profile or None,'predecessor_profile':FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE,
        'edges':[
            {'source_pin':[0,2,1,0x90590818],'peer_pin':[0,1,4,0x91670464],
             'source_slot':4,'peer_slot':4,'peer_count':10,'profile':'virtual-pinmem-out1-scalar-in4-v1'},
            {'source_pin':[0,2,2,0x90590818],'peer_pin':[0,1,0,0x9058003f],
             'source_slot':5,'peer_slot':0,'peer_count':10,'profile':'virtual-pinmem-out2-adf-in0-v1'},
            {'source_pin':[6,2,0,0x90590818],'peer_pin':[6,1,0,0x928d0783],
             'source_slot':10,'peer_slot':1,'peer_count':2,'profile':'virtual-pinmem-drawinfo0-drawinfo-in0-v1'}],
        'source_registry_count':13,'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,
        'unique_reply_count':3,'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'source_event':6,'event_parameter_bytes':12,'event_parameter_pointer_offset':0,
        'event_pointer_policy':'virtual-token-bound-to-owned-reply-inner-header',
        'saved_request_policy':'owned-original-64B-copy-phase1-wait6-full-peer-check',
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'predecessors_require_pool_retired':True,
        'dmm_command_count':0,'ssyn_notice_count':0,'format_cache_write_count':0,
        'marker_write_count':0,'clock_write_count':0,'mmio_write_count':0,'frame_count':0,
        'imaging_config_preserved':[1,1,1920,1080,3],
        'precondition_refusal_policy':'unadmitted-only-until-actual-predecessor-AP-consumption',
        'dispatch_policy':'exact-edges-before-legacy-PinMem-send-enter-other-traffic-falls-through',
        'completion_scope':'three-event6-metadata-connections-without-format-effects',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_event_pointer_verified','original_task_scheduler_verified',
        'original_RTOS_timing_verified','hardware_verified','ap_consumed','runtime_consumed',
        'native_verified','event6_consumed','connections_verified','format_consumed',
        'general_format_ready','cmos_verified','frames_verified','capture_verified')})
    return {'pinmem_peer_connections_'+name:value for name,value in fields.items()}


def adf_hdmi_audio_connection_profile_fields(profile):
    """Intent only: connected=true has the same shared-byte effect in all HDMI states."""
    if profile not in ('',FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE):
        raise ValueError('ADF HDMI audio connection must be virtual-adf-audio0-hdmi-audio0-v1 or unset')
    fields={
        'profile':profile or None,'predecessor_profile':FULL_PINMEM_PEER_CONNECTIONS_PROFILE,
        'source_pin':[5,2,0,0x9058003f],'peer_pin':[5,1,0,0x909a015a],
        'source_registry_count':10,'source_registry_slot':9,'sink_registry_count':2,'sink_registry_slot':1,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'hdmi_singleton_pointer_CP_VA':0x01791f04,'audio_connected_byte_offset':0x60,
        'audio_connected_write_value':1,'audio_connected_old_value_known':False,
        'audio_connected_write_count':1,'shared_audio_connected_readback_required':True,
        'sink_posthook_state_policy':'same-connected-true-effect-in-all-ten-HDMI-states',
        'sink_posthook_return_meaning':'no-next-state-not-protocol-status',
        'source_special_callback_selected':False,
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'unhandled_video_OSD_edges_may_remain_refused':True,
        'dmm_command_count':0,'ssyn_notice_count':0,'format_cache_write_count':0,
        'clock_write_count':0,'mmio_write_count':0,'frame_count':0,
        'imaging_config_preserved':[1,1,1920,1080,3],
        'precondition_refusal_policy':'unadmitted-only-until-actual-predecessor-AP-consumption',
        'completion_scope':'audio-pin-control-and-one-shared-connected-byte-only',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_cp_pointer_verified','original_task_scheduler_verified',
        'original_RTOS_timing_verified','hardware_verified','ap_consumed','runtime_consumed',
        'native_verified','connection_verified','audio_connected_verified','format_consumed',
        'hdmi_current_state_verified','pcm_verified','cmos_verified','frames_verified','capture_verified')})
    return {'adf_hdmi_audio_connection_'+name:value for name,value in fields.items()}


def pinmem_hdmi_video_connection_profile_fields(profile):
    """Intent only: finite Initializing history; real receive/free gates completion."""
    if profile not in ('',FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE):
        raise ValueError('PinMem HDMI video connection must be virtual-pinmem-video0-hdmi-video0-initializing-v1 or unset')
    fields={
        'profile':profile or None,'predecessor_profile':FULL_PINMEM_PEER_CONNECTIONS_PROFILE,
        'source_pin':[4,2,0,0x90590818],'peer_pin':[4,1,0,0x909a015a],
        'source_registry_count':13,'source_registry_slot':7,'sink_registry_count':2,'sink_registry_slot':0,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'source_event':6,'event_parameter_bytes':12,'saved_request_bytes':64,
        'source_gate_initial_value':0,'source_gate_source':'public-VideoRawManager-constructor-before-any-PinMem-input',
        'source_gate_unknown_policy':'refused-no-F01F-write',
        'hdmi_state_source':'owner-init-before-any-HDMI-input-never-forced-at-Connect',
        'hdmi_state_scope':'finite-virtual-Initializing-to-HPD-low',
        'hdmi_live_prefix_commands':[0x0102,0x0109,0x0127],
        'hdmi_live_prefix_payload_policy':'actual-owned-message-queue-not-caller-supplied',
        'hdmi_existing_config_replay_count':8,
        'condition_source_sid':0x91ca0816,'condition_payload_bytes':20,
        'condition_payload_words':['2','dynamic-condition-id','1','0','0'],
        'condition_ids':[0,0x17,0x16,0x15,0x14,0x13,0x12,0x11,0x23,0x22,0x21,0x30],
        'condition_batch_count':2,'condition_message_count':24,
        'condition_destination_policy':'actual-registered-condition-queue',
        'upm_destination_sid':0x80920572,'upm_message_count':2,'upm_message_bytes':16,
        'upm_ack_count':0,
        'notification_consumption_policy':'original-successful-receive-and-same-receiver-thread-real-free',
        'send_or_provider_cleanup_counts_as_consumption':False,
        'driver_initialization_bytes':18,'driver_config_bytes':36,'driver_job_count':6,
        'driver_policy_slot':4,'driver_policy_row':0,'driver_completion_bytes':12,
        'completion_policy':'unique-AP-reply-only-after-all-condition-UPM-and-driver-readiness-consumed',
        'pending_policy':'retain-owned-request-no-AP-ACK',
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'get_prerequisite':'exact-source-and-peer-full-key-replies-freed',
        'audio_edge_required':False,'osd_edge_required':False,
        'dmm_command_count':0,'frame_count':0,'diagnostics_policy':'masked-optional-no-GUI-or-hardware-readiness',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_cp_pointer_verified','original_event_pointer_verified',
        'original_task_scheduler_verified','original_RTOS_timing_verified','hardware_verified',
        'ap_consumed','runtime_consumed','native_verified','connection_verified',
        'conditions_consumed','upm_consumed','hdmi_current_state_original_verified',
        'format_consumed','general_format_ready','cmos_verified','frames_verified','pcm_verified','capture_verified')})
    return {'pinmem_hdmi_video_connection_'+name:value for name,value in fields.items()}


def pinmem_osd_connection_profile_fields(profile):
    """Intent only: a separate virtual E1700 pool with persistent metadata references."""
    if profile not in ('',FULL_PINMEM_OSD_CONNECTION_PROFILE):
        raise ValueError('PinMem OSD connection must be virtual-pinmem-osd0-osdpin-if0-ssos-v1 or unset')
    fields={
        'profile':profile or None,'predecessor_profile':FULL_PINMEM_PEER_CONNECTIONS_PROFILE,
        'source_pin':[1,3,0,0x90590818],'peer_pin':[1,3,0,0x9080003b],
        'source_registry_count':13,'source_registry_slot':8,'sink_registry_count':1,'sink_registry_slot':0,
        'direction3_policy':'source-supported-only-exact-PinMem-and-OSD-service-keys',
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'source_event':6,'event_parameter_bytes':12,'saved_request_bytes':64,
        'pool_unit':0xe1700,'pool_slots':16,'pool_extent_bytes':256,'pool_backing_bytes':4096,
        'pool_capacity_policy':'explicit-virtual-capacity-not-original-allocator-capacity',
        'resource_banks':[
            {'tag':0,'count':4,'payload_bytes':64},
            {'tag':0x101,'count':4,'payload_bytes':16},
            {'tag':0x100,'count':4,'payload_bytes':128},
            {'tag':0x102,'count':4,'payload_bytes':32}],
        'connected_live_resources':16,'connected_owner_references':32,'connected_open_references':32,
        'reference_policy':'persistent-creator-and-consumer-no-premature-Free',
        'dmm_commands':[0x20,0x21,0x24],'dmm_command_count':48,
        'peer_dmm_request_bytes':40,'pinmem_dmm_request_bytes':152,
        'notice_count':16,'notice_bytes':80,'notice_command':[0x1000,0x0102],
        'notice_descriptor_policy':'receiver-first-producer-second-type1-direction3-index0-service-SIDs-swapped',
        'pinmem_numeric_version':0x01000000,'pinmem_version_le':[0,0,0,1],
        'peer_numeric_version':1,'peer_version_le':[1,0,0,0],'peer_header_flags':3,
        'unknown_payload_bytes':{'tag100':121,'tag101':2,'tag102':6},
        'unknown_byte_policy':'virtual-A5-with-known-mask-zero-not-original-stack-bytes',
        'initial_inactive_row_count':5,'inactive_tag100_backing_count_after':0,
        'inactive_tag100_cached_count_after':1,'inactive_update_notice_count':0,
        'inactive_update_share_count':0,'inactive_update_open_count':0,
        'metadata_readiness_policy':'all-four-tag101-and-tag102-banks-only',
        'diagnostics_policy':'masked-optional-no-GUI-or-GPE-readiness',
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'get_prerequisite':'exact-source-and-peer-cold-full-key-replies-freed',
        'hdmi_video_edge_required':False,'audio_edge_required':False,
        'predecessor_three_format_caches_preserved':True,'predecessor_histories_preserved':True,
        'old_dmm_pool_extra_operations':0,'foreign_speech_live_preserved':True,
        'completion_scope':'bidirectional-metadata-and-event6-no-graphics-or-frames',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'original_cp_executed','original_cp_pages_verified','original_allocator_capacity_verified',
        'original_event_pointer_verified','original_task_scheduler_verified','original_RTOS_timing_verified',
        'hardware_verified','ap_consumed','runtime_consumed','native_verified','connection_verified',
        'metadata_ready','format_consumed','general_format_ready','gpe_ready','cmos_verified',
        'frames_verified','pcm_verified','capture_verified')})
    return {'pinmem_osd_connection_'+name:value for name,value in fields.items()}


def cp302c_no_transition_profile_fields(profile):
    """Intent only: source-supported current0/no3041 branch, never mode readiness."""
    if profile not in ('',FULL_CP302C_NO_TRANSITION_PROFILE):
        raise ValueError('CP302c NO-TRANSITION must be virtual-cp302c-current0-no-transition-v1 or unset')
    fields={
        'profile':profile or None,
        'protocol':'CP302c-F0-event17-current0-no3041-no-transition-v1',
        'no_transition_branch_supported':True,
        'request_bytes':24,'response_bytes':12,'request_command':0x302c,
        'source_event':0x17,'query_command':0x3041,'query_record_present':False,
        'source_branch':{'outer':0xb1ffba,'query':0xb1f140,
                         'reject_handler':0x4b4b00,'reply_constructor':0xb22788},
        'branch_policy':'outer-query-not-admissible-before-observer',
        'response_type':1,'response_command':0x302c,'response_status':0xf000,
        'response_status_meaning':'positive-NO-TRANSITION-reply','AP_result':0,
        'cookie_policy':'echo-owned-request-cookie','origin_policy':'echo-incoming-origin',
        'ignored_reply_byte1_policy':'unknown-source-byte-virtual-padding-zero',
        'ignored_reply_byte1_virtual_padding':0,
        'ctor_initial_current':0,
        'current_validity_policy':'source-derived-explicit-clear-not-live-CP-RAM',
        'current_history_policy':'actual-3007-predecessors-and-strict-prefix-proof-in-C',
        'predecessor_connection_count':13,
        'predecessor_profiles':{
            'pinmem_hdmi_video':FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE,
            'pinmem_osd':FULL_PINMEM_OSD_CONNECTION_PROFILE,
            'adf_hdmi_audio':FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE,
            'cp_background':'virtual-mode3-cold-v1'},
        'predecessor_policy':'all-13-actual-AP-consumed-clean-no-outstanding-not-flags-only',
        'mode_3041_start_count':0,'module_mask_update_count':0,
        'current_mode_commit_count':0,'EE_ready_write_count':0,
        'completion_scope':'dedicated-12B-type1-302c-NO-TRANSITION-reply-only',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'normal_3041_transition_supported','original_CP_executed','ignored_reply_byte1_known',
        'native_verified','original_AP_consumed','branch_consumed','mode_transition_verified',
        'module_completion_verified','EE_verified','hardware_ready','frames_verified','capture_verified')})
    return {'cp302c_no_transition_'+name:value for name,value in fields.items()}


def cp302c_diagnostic_profile_fields(profile):
    """Diagnostic intent only: unknown current/history, with no source-equivalence claim."""
    if profile not in ('',FULL_CP302C_DIAGNOSTIC_PROFILE):
        raise ValueError('CP302c diagnostic must be diagnostic-cp302c-reply-only-v1 or unset')
    fields={
        'profile':profile or None,
        'protocol':'CP302c-diagnostic-reply-only-v1',
        'diagnostic_only':1,'no_transition':0,
        'request_bytes':24,'response_bytes':12,'request_command':0x302c,
        'source_event':0x17,'query_command':0x3041,'query_record_present':False,
        'response_type':1,'response_command':0x302c,'response_status':0xf000,'AP_result':0,
        'response_status_meaning':'diagnostic-positive-reply-no-source-branch-equivalence',
        'cookie_policy':'echo-owned-request-cookie','origin_policy':'echo-incoming-origin',
        'ignored_reply_byte1_policy':'unknown-source-byte-virtual-padding-zero',
        'ignored_reply_byte1_virtual_padding':0,
        'current':None,'history':None,
        'current_validity_policy':'unknown-never-inferred-from-public-initializer',
        'current_history_policy':'unknown-after-actual-3007-and-full-13-consumed',
        'prefix_policy':'unknown-prefix-audited-only-for-diagnostic-transport',
        'predecessor_connection_count':13,
        'predecessor_profiles':{
            'pinmem_hdmi_video':FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE,
            'pinmem_osd':FULL_PINMEM_OSD_CONNECTION_PROFILE,
            'adf_hdmi_audio':FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE,
            'cp_background':'virtual-mode3-cold-v1'},
        'predecessor_policy':'actual-3007-reply-free-and-all-13-AP-consumed-clean-no-outstanding',
        'mode_3041_start_count':0,'module_mask_update_count':0,
        'current_mode_commit_count':0,'EE_ready_write_count':0,
        'native_consumption_requires':'original-AP302c-reply-free',
        'completion_scope':'diagnostic-12B-type1-302c-reply-only',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'no_transition_branch_supported','normal_3041_transition_supported',
        'source_branch_equivalent','original_CP_executed','original_initializer_verified',
        'live_CP_RAM_read','source_history_equivalent','source_prefix_equivalent',
        'current_known','history_known','ignored_reply_byte1_known',
        'transport_verified','native_verified','original_AP_consumed','branch_consumed',
        'mode_transition_verified','module_completion_verified','EE_verified',
        'hardware_ready','frames_verified','capture_verified')})
    return {'cp302c_diagnostic_'+name:value for name,value in fields.items()}


def cp_notification_control_profile_fields(profile):
    """Finite virtual mode0 intent; original CP current/history remain unknown."""
    if profile not in ('',FULL_CP_NOTIFICATION_CONTROL_PROFILE):
        raise ValueError('CP notification control must be virtual-cp-notification-mode0-v1 or unset')
    fields={
        'profile':profile or None,
        'protocol':'CP4073-same-mode0-virtual-owned-policy-v1',
        'request_type':5,'request_command':0x4073,'request_bytes':12,
        'response_type':1,'response_command':0x4073,'response_bytes':12,
        'response_status':0xf000,'AP_result':0,
        'AP_source':0x80020002,'source_owner':0x90030001,
        'mode':0,'old_mode':0,'initial_notification_mode':0,
        'notification_mode_policy':'explicit-virtual-owned-mode0-not-original-CP-RAM',
        'current':None,'history':None,
        'predecessor_diagnostic_profile':FULL_CP302C_DIAGNOSTIC_PROFILE,
        'predecessor_connection_count':13,
        'predecessor_policy':'actual-diagnostic-302c-original-AP-reply-free-and-all-13-clean-in-C',
        'cookie_policy':'echo-owned-request-cookie',
        'ignored_reply_byte1_policy':'unknown-source-byte-virtual-padding-zero',
        'd018_command':0xd018,'d018_source':0x90030001,'d018_destination':0x90040193,
        'd018_bytes':12,'d018_sticky_modeled':True,'d013_registered':False,
        'd018_completion_policy':'finite-virtual-consumer-sticky-readback-before-4073-ACK',
        'completion_scope':'one-12B-type5-4073-same-mode0-request-only',
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'mode_change_0_or_2_supported','mode1_2040_supported',
        'original_CP_executed','original_CP_RAM_verified','current_known','history_known',
        'native_verified','runtime_verified','transport_verified','original_AP_consumed',
        'd018_native_consumption','d018_runtime_verified','ignored_reply_byte1_known',
        'mode_transition_verified','EE_verified','hardware_ready','frames_verified','capture_verified')})
    return {'cp_notification_control_'+name:value for name,value in fields.items()}


def cp_capture_format_profile_fields(profile):
    """Diagnostic reply transport; original format processing remains blocked."""
    if profile not in ('',FULL_CP_CAPTURE_FORMAT_PROFILE,FULL_CP_STARTUP_DIAGNOSTIC_PROFILE,FULL_CP_EE_DIAGNOSTIC_PROFILE,FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE,FULL_CP_OWNED_STATE_PROFILE):
        raise ValueError('CP capture format must select an exact declared profile or unset')
    owned = profile == FULL_CP_OWNED_STATE_PROFILE
    movie = profile in (FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE,FULL_CP_OWNED_STATE_PROFILE)
    ee = movie or profile == FULL_CP_EE_DIAGNOSTIC_PROFILE
    startup = ee or profile == FULL_CP_STARTUP_DIAGNOSTIC_PROFILE
    fields={
        'profile':profile or None,
        'protocol':'CP402d-diagnostic-reply-only-v1','diagnostic_only':1,
        'request_type':5,'request_command':0x402d,'request_bytes':24,
        'observed_request_hex':'05002d402700008002000101010101000101010101000000',
        'AP_source':0x80020002,'CP_target':0x90030001,
        'predecessor_profile':FULL_CP_NOTIFICATION_CONTROL_PROFILE,
        'predecessor_policy':'actual-4073-original-AP-reply-free-and-finite-virtual-sticky-proof-in-C',
        'virtual_config_owner':False,
        'initial_state_policy':'unknown-format-selectors-no-business-initialization',
        'current':None,'history':None,
        'response_type':1,'response_command':0x402d,'response_bytes':12,
        'response_status':0xf000,'AP_result':0,'cookie_policy':'echo-owned-request-cookie',
        'origin_policy':'original-AP-request-source',
        'response_fields_policy':'diagnostic-wire-only-not-source-business-equivalence',
        'completion_scope':('diagnostic-CP402d-startup-EE-and-movie-format-control-transport-only' if movie else
                            'diagnostic-CP402d-startup-and-EE-control-transport-only' if ee else
                            'diagnostic-CP402d-and-startup-control-transport-only' if startup else
                            'diagnostic-CP402d-transport-only'),
        'startup_diagnostic_profile':FULL_CP_STARTUP_DIAGNOSTIC_PROFILE if startup else None,
        'startup_commands':([{'command':0x4014,'request_bytes':24,'response_bytes':12},
                             {'command':0x40c8,'request_bytes':328,'response_bytes':12},
                             {'command':0x4057,'request_bytes':12,'response_bytes':12}]
                            if startup else []),
        'ee_diagnostic_profile':FULL_CP_EE_DIAGNOSTIC_PROFILE if ee else None,
        'ee_control_commands':([{'command':0x409d,'request_type':5,'request_bytes':12,'response_bytes':12},
                                {'command':0x4072,'request_type':5,'request_bytes':12,'response_bytes':0},
                                {'command':0x3012,'request_type':0,'request_bytes':24,'response_bytes':12}]
                               if ee else []),
        'owned_state_profile':FULL_CP_OWNED_STATE_PROFILE if owned else None,
        'owned_state_provider_policy':'actual-consumed-inputs-only-no-defaults-no-secondary-fallback' if owned else None,
        'owned_state_constructor_known_fields':0 if owned else None,
        'owned_state_property_input_policy':'explicit-public-CP-initial-stage-before-freeze' if owned else None,
        'owned_state_property_stage_sha256':PRIMARY_SHA if owned else None,
        'owned_state_parameter_local_store_bytes':694 if owned else None,
        'owned_state_parameter_default_store_bytes':2223 if owned else None,
        'owned_state_parameter_initial_local_known_bytes':2913 if owned else None,
        'owned_state_override_input_policy':'owned-d64-copy-then-explicit-bank0-binding' if owned else None,
        'owned_state_full_blocks':76 if owned else None,
        'owned_state_shadow_policy':'advance-only-after-original-notification-receive-and-free' if owned else None,
        'movie_format_profile':FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE if movie else None,
        'movie_format_command':0x4000 if movie else None,
        'movie_format_request_type':5 if movie else None,
        'movie_format_request_bytes':20 if movie else None,
        'movie_format_body_hex':'050100000000000000000100' if movie else None,
        'movie_format_response_bytes':12 if movie else None,
        'movie_format_predecessor_policy':'actual-409d-original-free-pair-and-clean-cohort-in-C' if movie else None,
        'movie_format_before_oneway_4072':True if movie else None,
        'ee_predecessor_policy':('same-PID-original-free-pairs-with-own-sender-waiter-match-not-current-TID'
                                 if ee else None),
    }
    fields={name:(value if profile else None) for name,value in fields.items()}
    fields.update({name:False for name in (
        'data_reply_3003_supported','snapshot_2040_supported',
        'original_CP_executed','original_CP_RAM_verified','live_CP_RAM_read',
        'original_initializer_verified','current_known','history_known',
        'native_verified','runtime_verified','transport_verified','semantic_verified',
        'source_dependencies_closed','source_branch_equivalent','business_applied',
        'pending_complete','generation_advanced','published',
        'original_AP_consumed','EE_verified','hardware_ready','frames_verified','capture_verified')})
    return {'cp_capture_format_'+name:value for name,value in fields.items()}


def functional_camera_profile_fields(profile):
    """Declared software-hardware policy, never evidence of a captured file."""
    if profile not in ('', FUNCTIONAL_CAMERA_PROFILE):
        raise ValueError('Functional camera must select virtual-functional-camera-v1 or unset')
    fields = {
        'profile': profile or None,
        'abi_version': 1,
        'hardware_policy': 'explicit-software-model-not-Sony-physical-ASIC',
        'image_bus': 'virtual-RGB888-top-row-first',
        'vdf_path_policy': 'canonical-0138-single-RGB-sink-readback-before-1138',
        'vdf_virtual_endpoint': 0x90590819,
        'vdf_virtual_completion_mask': 1,
        'zebra_policy': 'original-0153-disabled-pass-through-RGB-sink-readback-before-1153',
        'zebra_enabled_supported': False,
        'layout_policy': 'original-014c-initial-case0-full-RGB-passthrough-readback-before-114c',
        'startup_layout_policy': 'guest-local-canonical-initial-register-stage-before-active-route',
        'startup_layout_stage_only': True,
        'startup_layout_frame_completion': False,
        'layout_virtual_area_order': 'x-y-width-height',
        'layout_virtual_zero_output': 'full-frame-pass-through',
        'layout_supported_rgb_geometry': [640, 480, 1920],
        'layout_initial_body_hex': '07010100000000008002e0010000000000000000000000000300000000000000',
        'display_config_policy': 'original-display-controls-plus-functional-0170-three-boolean-RGB-identity-readback-before-independent-reply',
        'display_config_commands': [0x141, 0x152, 0x162, 0x163, 0x170],
        'peaking_enabled_supported': False,
        'display_flag_enabled_supported': False,
        'display_bit_width_policy': 'original-015e-selector0-virtual-RGB888-readback-before-115e',
        'display_bit_width_commands': [0x15e],
        'display_bit_width_supported_selectors': [0],
        'display_bit_width_selector_mapping': 'explicit-software-only-physical-selector-meaning-unverified',
        'display_bit_width_physical_mapping_verified': False,
        'still_format_policy': 'original402d-observed-L-Fine-dual-slot-RGB-identity-readback-before-echo-f000',
        'still_format_commands': [0x402d],
        'still_format_request_bytes': 24,
        'still_format_canonical16_hex': '02000001000100000001000100000000',
        'still_format_opaque_tail_policy': 'preserve-original22-23-not-consumed-canonical-tail-zero',
        'still_format_initial_diagnostic_policy': 'preserved-one-shot-before-functional-model-active',
        'still_format_physical_selector_mapping_verified': False,
        'startup_control_policy': 'original4014-observed-and4057-load-current-virtual-config-before-echo-f000',
        'startup_control_commands': [0x4014, 0x4057],
        'startup_control_canonical_layout': 'cmd16-length16-body16-reserved4-current-config40-FNV64',
        'startup_control_config_fingerprint': 'actual-STATE128-bytes8:48-FNV1a64',
        'startup_control_settings_policy': 'request0-independent-current-config40-checkpoint-no-MR-profile',
        'startup_control_initial_diagnostic_policy': 'preserved-one-shot-before-functional-successor',
        'startup_control_physical_mapping_verified': False,
        'bb_startup_config_policy': 'initial-C-config-banks-RGB-readback-before-independent-reply',
        'bb_startup_config_commands': [0x111, 0x166, 0x167, 0x15f, 0x128],
        'bb_startup_neutral_only': False,
        'bb_startup_other_commands_neutral_only': True,
        'bb_startup_0166_observed_initial_body_hex': '00010000000000000000000008000000070000000100000001000000',
        'bb_startup_0166_identity_policy': 'explicit-neutral-or-exact-observed-initial-tuple-RGB-identity',
        'bb_startup_gain_nonzero_supported': False,
        'bb_startup_interval_enabled_supported': False,
        'histogram_policy': 'first-enabled-mode1-RGB-u8-peak-YRGB-before-1148-and-210c',
        'histogram_commands': [0x148],
        'histogram_channels': ['virtual-Y', 'R', 'G', 'B'],
        'histogram_bins_per_channel': 256,
        'histogram_value_format': 'u8-peak-height-255',
        'histogram_luma_formula': '(77R+150G+29B+128)>>8',
        'histogram_normalization_formula': '(count*255+peak/2)/peak',
        'histogram_notification_selector': 1,
        'histogram_notification_logical_bytes': 1034,
        'histogram_mode0_supported': False,
        'histogram_reenable_supported': False,
        'histogram_continuous_supported': False,
        'transport': 'owned-pagemap-16-page-mailbox-private-Unix-GDB-v1',
        'backend_initialization': 'actual-original-request-INIT-before-start-reply',
        'cp_background_start_policy': 'original-3006-pending-all13-free-model-INIT-STATE-readback-before-independent-reply',
        'cp_background_start_native_commands': [0x3006],
        'cp_background_start_deferred_until': 'same-run-all13-original-free-and-actual-debugger-handoff',
        'cp_parameter_bank_policy': 'full190-opaque-bank-4151u32-fps-configure-live-State128-independent-readback-v1',
        'cp_parameter_bank_opcode': 20,
        'cp_parameter_bank_native_commands': [0x4063],
        'cp_parameter_bank_bytes': 2564,
        'cp_parameter_bank_slots': 190,
        'cp_parameter_bank_result_bytes': 2756,
        'cp_parameter_bank_fps_input_offset': 0x86c,
        'cp_parameter_bank_reply_policy': 'oneway-original-request-free-no-ACK-no-notification',
        'cp_parameter_bank_physical_semantics_verified': False,
        'cp_crank_control_policy': 'active-config-crank-mode0-v1',
        'cp_crank_control_opcode': 21,
        'cp_crank_control_native_commands': [0x409d],
        'cp_crank_control_bytes': 12,
        'cp_crank_control_result_bytes': 208,
        'cp_crank_control_supported_modes': [0],
        'cp_crank_control_input_policy': 'full-original12-byte1-cookie-opaque-body4zero',
        'cp_crank_control_bank_policy': 'current-committed-instance-bank-generation-once',
        'cp_crank_control_state_policy': 'live-State128-config-generation-plus-one-all-other-bytes-preserved',
        'cp_crank_control_reply_policy': 'independent-type1-409d-echo-cookie-f000-original-receive-free',
        'cp_crank_control_initial_diagnostic_policy': 'preserved-strict-initial409d-before-functional-bank',
        'cp_crank_control_frame_production_supported': False,
        'cp_crank_control_physical_semantics_verified': False,
        'cp_movie_format_policy': 'active-config-movie-format5-rate1-0-v1',
        'cp_movie_format_opcode': 22,
        'cp_movie_format_native_commands': [0x4000],
        'cp_movie_format_bytes': 20,
        'cp_movie_format_result_bytes': 240,
        'cp_movie_format_input_policy': 'full-original20-byte1-cookie-byte11-byte19-opaque',
        'cp_movie_format_mapping': 'format5-rate1,0-to-current-Config48-RGB888-H264-bankFPS',
        'cp_movie_format_bank_policy': 'current-committed-instance-bank-crank-pair-once',
        'cp_movie_format_state_policy': 'live-State128-config-generation-plus-one-all-other-bytes-preserved',
        'cp_movie_format_reply_policy': 'independent-type1-4000-echo-cookie-f000-original-receive-free',
        'cp_movie_format_initial_diagnostic_policy': 'preserved-strict-initial4000-before-functional-bank',
        'cp_movie_format_frame_production_supported': False,
        'cp_movie_format_physical_semantics_verified': False,
        'cp_ou_crank_control_policy': 'active-config-ou-crank-mode0-v1',
        'cp_ou_crank_control_opcode': 23,
        'cp_ou_crank_control_native_commands': [0x4072],
        'cp_ou_crank_control_bytes': 12,
        'cp_ou_crank_control_result_bytes': 224,
        'cp_ou_crank_control_supported_modes': [0],
        'cp_ou_crank_control_input_policy': 'full-original12-byte1-cookie-opaque-body4zero',
        'cp_ou_crank_control_bank_policy': 'current-committed-instance-bank-crank-movie-tuple-once',
        'cp_ou_crank_control_state_policy': 'live-State128-config-generation-plus-one-all-other-bytes-preserved',
        'cp_ou_crank_control_reply_policy': 'none-oneway-original-sender-request-free-only',
        'cp_ou_crank_control_initial_diagnostic_policy': 'preserved-strict-initial4072-before-functional-bank',
        'cp_ou_crank_control_frame_production_supported': False,
        'cp_ou_crank_control_physical_semantics_verified': False,
        'bb_timecode_control_policy': 'virtual-bb-timecode-controls-v1',
        'bb_timecode_control_native_commands': [1024, 1025, 1026],
        'bb_timecode_control_request_bytes': 10,
        'bb_timecode_control_reply_bytes': 12,
        'bb_timecode_control_state_bytes': 48,
        'bb_timecode_control_input_policy': 'exact200d10-8001-bool0,1-byte9zero-original-local-source',
        'bb_timecode_control_state_policy': 'owned3bool-knownmask-generation-independent-State48-v1',
        'bb_timecode_control_reply_policy': 'independent200d-command-plus1000-plain0-after-state-readback-and-original-request-free',
        'bb_timecode_control_retirement_policy': 'actual-original-receive-and-same-sender-free-before-next-transaction',
        'bb_timecode_control_fifo_policy': 'explicit-single-pending-actual-source-sender-lease-no-original-RTOS-identity-claim',
        'bb_timecode_control_original_fifo_identity_verified': False,
        'bb_timecode_control_frame_production_supported': False,
        'bb_timecode_control_physical_semantics_verified': False,
        'bb_timecode_preset_policy': 'virtual-bb-timecode-presets-v1',
        'bb_timecode_preset_native_commands': [1034, 1033],
        'bb_timecode_preset_request_sizes': {'0x040a': 12, '0x0409': 10},
        'bb_timecode_preset_reply_bytes': 12,
        'bb_timecode_preset_state_bytes': 48,
        'bb_timecode_preset_input_policy': 'exact200d-040a12-raw4u8-040910-LE16enum0,1-8001-original-local-source',
        'bb_timecode_preset_state_policy': 'owned-raw4-wire-selector-knownmask-generation-independent-PresetState48-v1',
        'bb_timecode_preset_reply_policy': 'independent200d-140a,1409-plain0-after-state-readback-and-original-request-free',
        'bb_timecode_preset_retirement_policy': 'actual-original-receive-and-same-sender-free-before-next-transaction',
        'bb_timecode_preset_predecessor_policy': 'actual-three-TC-COMMITs-before040a-actual040a-COMMIT-before0409',
        'bb_timecode_preset_native_CP_verified': False,
        'bb_timecode_preset_frame_production_supported': False,
        'bb_timecode_preset_physical_semantics_verified': False,
        'cp_face_dmm_policy': 'original-five-callsite-byte-pins-owned-backing-receive-free-before-ledger',
        'cp_face_dmm_units': [0x1d9, 0x1da, 0x1db],
        'cp_face_dmm_commands': [0x20, 0x21, 0x23, 0x24, 0x25],
        'cp_face_dmm_software_iova': [0x70000000, 0x70100000, 0x70200000],
        'cp_face_dmm_iova_policy': 'software-only-no-implicit-AP-physical-translation',
        'cp_face_dmm_lifecycle': 'one-creator-lifecycle-per-unit-per-process-no-wire-wrap',
        'cp_face_dmm_segment_query_supported': False,
        'cp_face_dmm_transfer_content_policy': 'saved-AP-lease-disjoint-proof-full-write-independent-readback-release-before-content-complete',
        'cp_face_dmm_transfer_sdk48_decode': 'class1-two-stable-eight-byte-descriptors-preserve-callback-context-result-padding',
        'cp_face_dmm_transfer_source_policy': 'required-native-pinned-span-no-default-provider',
        'cp_face_dmm_original_completion_transport_supported': False,
        'cp_face_dmm_ap_observer_policy': 'passive-original-code-pinned-send-receive-free-record-no-pin-no-byte-capability',
        'cp_face_dmm_ap_observer_commands': [0x20, 0x21, 0x23, 0x24, 0x25],
        'cp_face_dmm_ap_observer_units': [0x1d9, 0x1da, 0x1db, 0x1dc],
        'cp_face_dmm_ap_observer_kernel_2a_observed': False,
        'cp_face_dmm_sdk_observer_policy': 'passive-original-valloc48-sync-enter-return-free-no-callback-no-result-write',
        'cp_face_dmm_sdk_literal_result_observed': False,
        'cp_face_dmm_native_ap_provider_policy': 'required-original-owner-open-close-free-tickets-mapping-writer-no-default-backend',
        'cp_face_dmm_native_birth_proc_policy': 'original20-free0-two-complete-proc-reads-diagnostic-no-atomicity',
        'cp_face_dmm_functional_source_snapshot_policy': 'original-owner-open-paused-CPU-AS-full-source-read-retained-readback-no-global-writer-claim',
        'cp_face_dmm_interchip_transfer_supported': False,
        'control_predecessor': FULL_CP_OWNED_STATE_PROFILE,
        'xsync_capability_policy': 'virtual-one-model-frame-period-from-State128-fps-canonical-AP-pair',
        'xsync_clock_source': 'State128.fps',
        'xsync_readout_frame_periods': 1,
        'xsync_current_exposure_independent': True,
        'xsync_noncanonical_clock_policy': 'reject-before-mode1-ACK',
        'xsync_canonical_clock_rates': [1, 2, 4, 5, 6, 8, 10, 13, 15, 20, 25, 30, 40, 45, 50, 60, 80, 90, 100],
        'xsync_flash_trigger_supported': False,
        'still_max_geometry': [8192, 8192],
        'video_max_geometry': [1920, 1080],
        'video_codec': 'H264',
        'first_video_acceptance_audio': 'original-AudioRecording-Off',
        'media_output_policy': 'original-MPR-Fsys-only-no-host-media-file',
        'strict_profile_policy': 'separate-and-unchanged',
        'capture_requires': ['original-AP-request', 'actual-virtual-CMOS-frame',
                             'actual-encoder-consumption', 'original-MPR-Fsys-write',
                             'virtual-SD-readback', 'independent-decode'],
    }
    fields = {name: (value if profile else None) for name, value in fields.items()}
    fields.update({name: False for name in (
        'physical_ASIC_compatibility_verified', 'original_CP_executed',
        'original_CP_RAM_verified', 'original_VDF_selector_verified', 'original_VDF_CP_FIFO_verified',
        'original_Zebra_gate_verified', 'original_VDF_area_order_verified',
        'original_VDF_layout_hardware_verified', 'original_Peaking_operator_verified',
        'original_0162_feature_verified', 'original_BB_C_configuration_work_verified',
        'original_BB_C_configuration_units_verified', 'original_Histogram_bin_semantics_verified',
        'original_Histogram_physical_callback_verified', 'histogram_UI_applied_verified',
        'original_Xsync_state_producer_verified', 'physical_Xsync_capability_verified',
        'cp_background_start_original_modules_verified',
        'cp_face_dmm_original_AP_consumption_verified', 'cp_face_dmm_physical_bank_verified',
        'cp_face_dmm_native_ap_backend_verified', 'cp_face_dmm_native_birth_complete_verified',
        'cp_face_dmm_functional_source_snapshot_verified', 'cp_face_dmm_original_global_writer_exclusion_verified',
        'backend_readiness_verified',
        'original_AP_consumption_verified', 'frame_consumption_verified',
        'original_MPR_Fsys_write_verified', 'standalone_host_media_write',
        'capture_verified')})
    return {'functional_camera_' + name: value for name, value in fields.items()}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_build(native, build):
    product=Path(native).resolve().parents[1]
    hardware=product/'report/virtual-pcidma'
    stage=load_module('backup_hardware_inputs',hardware/'stage_hardware.py')
    build=Path(build)
    if not build.is_absolute():
        raise ValueError('Backup build must be an explicit absolute stage directory')
    build=build.resolve()
    receipt=json.loads((build/'pci-hardware-build.json').read_text())
    if not isinstance(receipt,dict) or receipt.get('scope')!='default-off PCI/ATU hardware in native GTK/USB/directory-SD build':
        raise ValueError('Backup requires a combined native build')
    binary=build/'build/qemu-system-aarch64'
    if not binary.is_file() or sha(binary)!=receipt.get('binary_sha256'):
        raise ValueError('Backup candidate binary identity differs')
    for field, root, names in (
            ('model_source_sha256',hardware/'hardware',stage.MODEL_FILES),
            ('board_source_sha256',hardware/'hardware',stage.FRAGMENTS),
            ('atu_source_sha256',hardware.parent/'virtual-atu/hardware',stage.ATU_FILES)):
        expected=receipt.get(field,{})
        if set(expected)!=set(names) or any(sha(root/name)!=expected[name] for name in names):
            raise ValueError('Backup candidate does not contain current reviewed sources: '+field)
    return build,binary,receipt


def validate_functional_camera_media(env):
    """Validate intent only; prepare_profile must bind real files before admission."""
    media = env.get('A7C2_FUNCTIONAL_CAMERA_MEDIA', '')
    if media not in ('', FUNCTIONAL_CAMERA_RAM_MEDIA_CANDIDATE):
        raise ValueError('A7C2_FUNCTIONAL_CAMERA_MEDIA must be direct-bootin-ram-card-1g-v1 or unset')
    if env.get('MENU_FUNCTIONAL_CAMERA_MEDIA'):
        raise ValueError('MENU_FUNCTIONAL_CAMERA_MEDIA is not a supported guest override')
    if media:
        if (env.get('A7C2_FUNCTIONAL_CAMERA') != FUNCTIONAL_CAMERA_PROFILE or
                env.get('A7C2_CP_CAPTURE_FORMAT') != FULL_CP_OWNED_STATE_PROFILE or
                env.get('A7C2_BACKUP_SYNC') != PROFILE or not env.get('A7C2_BACKUP_BUILD') or
                env.get('A7C2_BOOT_PROFILE', 'direct-bootin') != 'direct-bootin' or
                env.get('SEED_BACKUP', 'alllang') != 'alllang'):
            raise ValueError('Functional camera RAM-card requires direct-bootin, public ALLLANG, explicit Backup build and owned-state functional chain')
        combined = env.get('A7C2_SETTINGS_RESTART_PROFILE') == 'functional-ram-card-independent-internal-v1'
        conflicts = (*BB_MODE_CONFLICTS, 'A7C2_DIRECTORY_SD', 'A7C2_DIRECTORY_SD_PROFILE',
                     'A7C2_DIRECTORY_SD_FD', 'A7C2_HOST_SD', 'A7C2_HOST_SD_FD',
                     'A7C2_SD_SPARSE', 'A7C2_SD_HOTPLUG', 'MENU_USB_NET',
                     'A7C2_USB_NET', 'QEMU_SONY_USB_NET', 'A7C2_USB_NET_SELFTEST',
                     'QEMU_NATIVE_AP_CP_LINK', 'QEMU_NATIVE_LINK_DIR',
                     'MENU_KERNEL_SCRIPT', 'MENU_DTB',
                     *(() if combined else ('QEMU_SYSTEM_DIR', 'QEMU_SYSTEM_BINARY')),
                     'A7C2_RAM_WINDOW', 'A7C2_RAM_RESTORE_STREAM')
        if any(env.get(name) for name in conflicts):
            raise ValueError('Functional camera RAM-card conflicts with other media, launch overrides, RAM restore or diagnostic modes')
    return media or None


def _bound_profile_input(path, *, retain=False, expected_bytes=None, single_link=False):
    """Read/hash an owned regular input through one descriptor, preserving its identity."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Functional camera inputs require absolute source paths')
    with directory(path.parent) as parent:
        fd = regular(parent, path.name)
        try:
            before = os.fstat(fd)
            if expected_bytes is not None and before.st_size != expected_bytes:
                raise ValueError(f'Functional camera input size differs: expected {expected_bytes} bytes')
            if single_link and (before.st_nlink != 1 or before.st_mode & 0o022):
                raise ValueError('Functional camera card seed requires one link and private write permissions')
            raw = None
            if retain:
                with os.fdopen(os.dup(fd), 'rb') as stream:
                    raw = stream.read()
                digest = hashlib.sha256(raw).hexdigest()
            else:
                digest = digest_fd(fd)
            if identity(before) != identity(os.fstat(fd)):
                raise ValueError('Functional camera profile input changed while reading')
            proof = {'path': str(path), 'bytes': before.st_size,
                     'sha256': digest, 'identity': list(identity(before))}
            return proof, raw
        finally:
            os.close(fd)


# Admission: scratch/a7c2-ram-dir-unblock-20261115-candidate1/trusted-execution-contract.md.
# Requires an isolated single-user owner; hostile same-UID replacement is outside that contract.
_RAM_DIRECTORY_CREATION_BLOCKED = None
_RAM_DIRECTORY_CREATION_CANDIDATE = 'private-random128-fd-directory-v1'


class _RamProfileOutput:
    """Descriptor-bound derivation retained through the caller's explicit lease."""

    @staticmethod
    def _create_directory(parent_fd, *, candidate=None):
        if candidate not in (None, _RAM_DIRECTORY_CREATION_CANDIDATE):
            raise ValueError('Functional camera directory creation candidate differs')
        if _RAM_DIRECTORY_CREATION_BLOCKED is not None and candidate is None:
            raise ValueError(_RAM_DIRECTORY_CREATION_BLOCKED)
        parent = os.fstat(parent_fd)
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or
                stat.S_IMODE(parent.st_mode) != 0o700):
            raise ValueError('Functional camera creation parent requires owned 0700 directory FD')
        for attempt in range(8):
            name = 'profile-' + secrets.token_hex(16)
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                break
            except FileExistsError:
                continue
        else:
            raise ValueError('Functional camera directory creation exhausted collision retries')
        # shortcut: mkdir has no returned FD; a same-UID swap before this stat is undetectable,
        # require an isolated creation owner if hostile same-UID writers enter the threat model.
        created = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=parent_fd)
        try:
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            held = os.fstat(fd)
            if (not stat.S_ISDIR(held.st_mode) or held.st_uid != os.geteuid() or
                    stat.S_IMODE(held.st_mode) != 0o700 or
                    (created.st_dev, created.st_ino, created.st_mode, created.st_uid) !=
                    (held.st_dev, held.st_ino, held.st_mode, held.st_uid) or
                    (named.st_dev, named.st_ino, named.st_mode, named.st_uid) !=
                    (held.st_dev, held.st_ino, held.st_mode, held.st_uid) or os.listdir(fd)):
                raise ValueError('Functional camera newly opened directory identity differs')
            checked_parent = os.fstat(parent_fd)
            if ((checked_parent.st_dev, checked_parent.st_ino, checked_parent.st_mode, checked_parent.st_uid) !=
                    (parent.st_dev, parent.st_ino, parent.st_mode, parent.st_uid)):
                raise ValueError('Functional camera creation parent changed')
            os.fsync(parent_fd)
            return name, fd
        except BaseException:
            os.close(fd)
            # Unknown/rebound directories are evidence, never removed by path.
            raise

    @staticmethod
    def consumer_environment(output=None, environment=None, owner=None):
        if (not isinstance(owner, _RamProfileLease) or not owner.active or
                not isinstance(output, _RamProfileOutput) or type(environment) is not dict):
            raise ValueError('Functional camera consumer handoff refused: no caller-held exact FD binding')
        return owner.adopt(output, environment)

    def __init__(self, stack, parent):
        self.parent = Path(parent).absolute()
        with directory(self.parent.parent) as ancestor:
            try:
                os.mkdir(self.parent.name, mode=0o700, dir_fd=ancestor)
            except FileExistsError:
                pass
            self.parent_fd = os.open(self.parent.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                     dir_fd=ancestor)
        stack.callback(os.close, self.parent_fd)
        held_parent = os.fstat(self.parent_fd)
        if held_parent.st_uid != os.geteuid() or held_parent.st_mode & 0o022:
            raise ValueError('Functional camera output parent requires private write permissions')
        self.parent_identity = (held_parent.st_dev, held_parent.st_ino, held_parent.st_mode, held_parent.st_uid)
        created_name, self.fd = self._create_directory(self.parent_fd)
        self.output = self.parent / created_name
        stack.callback(os.close, self.fd)
        held = os.fstat(self.fd)
        self.directory_identity = (held.st_dev, held.st_ino, held.st_mode, held.st_uid)
        self.pinned = Path(f'/proc/self/fd/{self.fd}')
        self.files = {}
        self.stack = stack
        self.sparse = None
        self.check()

    def _name(self, path):
        path = Path(path)
        if path.parent != self.pinned or path.name not in (
                'source-board.dtb', 'official-board.dtb', 'board-ram-backup.dtb',
                'iomap-board-proof.json'):
            raise ValueError('Functional camera iomap path escaped fixed output directory')
        return path.name

    def write(self, name, raw):
        fd = regular(self.fd, name, os.O_RDWR | os.O_CREAT | os.O_EXCL)
        self.stack.callback(os.close, fd)
        with os.fdopen(os.dup(fd), 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        expected = hashlib.sha256(raw).hexdigest()
        before = identity(os.fstat(fd))
        if os.fstat(fd).st_size != len(raw) or digest_fd(fd) != expected:
            raise ValueError('Functional camera derived file readback differs')
        if identity(os.fstat(fd)) != before:
            raise ValueError('Functional camera derived file identity changed')
        self.files[name] = (fd, before, expected)
        self.read(name)
        return len(raw)

    def copy_seed(self, source_proof, *, parallel_peak_bytes=None):
        """Copy a fully bound input; both source and independent clone are read back."""
        from functional_ram_initramfs import fat16
        from sd_transport import check_space, FREE_SPACE_FLOOR
        import sparse_seed

        if type(parallel_peak_bytes) is not int or parallel_peak_bytes < 0:
            raise ValueError('Functional RAM seed requires declared parallel peak bytes, including zero')
        peak = FUNCTIONAL_CAMERA_RAM_BYTES + sparse_seed.MAX_DATA + 32 * 1024**2 + parallel_peak_bytes
        check_space(self.fd, FREE_SPACE_FLOOR + peak)
        storage = dict(owner=dict(uid=os.geteuid(), pid=os.getpid()),
                       purpose='Independent functional RAM-card seed and lossless sparse packaging',
                       peak_new_bytes=peak, parallel_peak_bytes=parallel_peak_bytes,
                       reserve_bytes=FREE_SPACE_FLOOR,
                       available_before=os.fstatvfs(self.fd).f_bavail * os.fstatvfs(self.fd).f_frsize,
                       retained_reason='Unconsumed candidate or original derivation failure',
                       next_consumer='FD-bound functional RAM-card owner after all admission gates pass',
                       reclaim_when='Owner confirms consumer exit and no references; preserve any unique failure evidence',
                       reclaimed_bytes=0, state='creating', fsck_verified=False,
                       guest_consumption_verified=False, capture_verified=False)
        self.write('storage-initial.json', (json.dumps(storage, indent=2) + '\n').encode())
        original = None
        try:
            source_path = Path(source_proof['path'])
            if not source_path.is_absolute() or '..' in source_path.parts:
                raise ValueError('Functional camera RAM seed requires an absolute source without traversal')
            with directory(source_path.parent) as source_parent:
                source_fd = regular(source_parent, source_path.name)
                try:
                    before = os.fstat(source_fd)
                    if (before.st_size != FUNCTIONAL_CAMERA_RAM_BYTES or before.st_nlink != 1 or
                            before.st_mode & 0o022 or list(identity(before)) != source_proof['identity'] or
                            digest_fd(source_fd) != source_proof['sha256']):
                        raise ValueError('Functional camera RAM seed identity changed before copy')
                    fcntl.flock(source_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    source_fat = fat16(source_fd, before.st_size)
                    name = 'media-camera.fat'
                    writer = regular(self.fd, name, os.O_RDWR | os.O_CREAT | os.O_EXCL)
                    self.stack.callback(os.close, writer)
                    os.fchmod(writer, 0o600)
                    os.ftruncate(writer, FUNCTIONAL_CAMERA_RAM_BYTES)
                    for offset in range(0, FUNCTIONAL_CAMERA_RAM_BYTES, 4 * 1024**2):
                        check_space(self.fd, FREE_SPACE_FLOOR + peak - offset)
                        count = min(4 * 1024**2, FUNCTIONAL_CAMERA_RAM_BYTES - offset)
                        raw = os.pread(source_fd, count, offset)
                        if len(raw) != count:
                            raise ValueError('Functional camera RAM seed truncated during copy')
                        if any(raw) and os.pwrite(writer, raw, offset) != count:
                            raise OSError('Short functional RAM-card clone write')
                    os.fsync(writer)
                    held = os.fstat(writer)
                    if (held.st_nlink != 1 or stat.S_IMODE(held.st_mode) != 0o600 or
                            identity(before) != identity(os.fstat(source_fd)) or
                            before.st_mode != os.fstat(source_fd).st_mode or
                            before.st_nlink != os.fstat(source_fd).st_nlink or
                            identity(before) != identity(os.stat(source_path.name, dir_fd=source_parent,
                                                               follow_symlinks=False)) or
                            digest_fd(source_fd) != source_proof['sha256'] or
                            digest_fd(writer) != source_proof['sha256'] or
                            fat16(writer, held.st_size) != source_fat):
                        raise ValueError('Functional camera RAM seed source/clone readback differs')
                    readonly = regular(self.fd, name)
                    self.stack.callback(os.close, readonly)
                    if identity(os.fstat(readonly)) != identity(held):
                        raise ValueError('Functional camera RAM seed clone rebound')
                    # Linux flock follows the inherited open-file description, like the disk lease.
                    fcntl.flock(readonly, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.files[name] = (readonly, identity(held), source_proof['sha256'])
                    self.read(name, retain=False)
                finally:
                    os.close(source_fd)
            packaged = sparse_seed.build(self.output / name, self.pinned / 'ram-card-sparse',
                                         source_fd=readonly)
            if (packaged['sha256'] != source_proof['sha256'] or
                    packaged['bytes'] != FUNCTIONAL_CAMERA_RAM_BYTES or
                    packaged.get('representation_only') is not True or packaged.get('physical_device') is not False):
                raise ValueError('Functional camera sparse seed identity differs')
            sparse_fd = os.open('ram-card-sparse', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                                os.O_CLOEXEC, dir_fd=self.fd)
            self.stack.callback(os.close, sparse_fd)
            expected = {row['file']: (row['length'], row['sha256']) for row in packaged['chunks']}
            metadata_bytes = {
                'manifest.json': (json.dumps(packaged, indent=2) + '\n').encode(),
                'identity.txt': f"{packaged['bytes']} {packaged['sha256']}\n".encode('ascii'),
                'chunks.txt': ''.join(f"{row['offset']} {row['length']} {row['file']} {row['sha256']}\n"
                                      for row in packaged['chunks']).encode('ascii'),
                'zero.bin': bytes(sparse_seed.BLOCK),
            }
            expected.update({filename: (len(raw), hashlib.sha256(raw).hexdigest())
                             for filename, raw in metadata_bytes.items()})
            self.sparse = dict(fd=sparse_fd, directory=(os.fstat(sparse_fd).st_dev, os.fstat(sparse_fd).st_ino),
                               files=expected)
            self.check()
            os.fsync(sparse_fd)
            os.fsync(self.fd)
            storage.update(state='seed-and-sparse-readback-verified', fat16=source_fat,
                           seed_sha256=source_proof['sha256'],
                           sparse_manifest_sha256=expected['manifest.json'][1])
            return dict(path=str(self.output / name), bytes=FUNCTIONAL_CAMERA_RAM_BYTES,
                        sha256=source_proof['sha256'], identity=list(self.files[name][1])), dict(
                            path=str(self.output / 'ram-card-sparse'),
                            manifest_sha256=expected['manifest.json'][1],
                            bytes=packaged['bytes'], data_bytes=packaged['data_bytes'],
                            source_sha256=packaged['sha256'], representation_only=True,
                            fsck_verified=False, guest_consumption_verified=False)
        except BaseException as error:
            original = error
            storage.update(state='failed', error=f'{type(error).__name__}: {error}')
            raise
        finally:
            try:
                files = []
                for filename in os.listdir(self.fd):
                    info = os.stat(filename, dir_fd=self.fd, follow_symlinks=False)
                    files.append(dict(path=filename, bytes=info.st_size,
                                      allocated_bytes=info.st_blocks * 512,
                                      device=info.st_dev, inode=info.st_ino))
                    if filename == 'ram-card-sparse':
                        sparse_fd = os.open(filename, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                                            os.O_CLOEXEC, dir_fd=self.fd)
                        try:
                            for chunk in os.listdir(sparse_fd):
                                child = os.stat(chunk, dir_fd=sparse_fd, follow_symlinks=False)
                                files.append(dict(path=filename + '/' + chunk, bytes=child.st_size,
                                                  allocated_bytes=child.st_blocks * 512,
                                                  device=child.st_dev, inode=child.st_ino))
                        finally:
                            os.close(sparse_fd)
                storage.update(files=files, allocated_bytes=sum(item['allocated_bytes'] for item in files),
                               accounting='storage.json and later profile-derived files excluded',
                               available_after=os.fstatvfs(self.fd).f_bavail * os.fstatvfs(self.fd).f_frsize)
                self.write('storage.json', (json.dumps(storage, indent=2) + '\n').encode())
            except BaseException as storage_error:
                if original is not None:
                    original.add_note('RAM-card storage receipt failed: ' + str(storage_error))
                else:
                    raise

    def read(self, name, *, retain=True):
        fd, expected_identity, expected_digest = self.files[name]
        observed = regular(self.fd, name)
        try:
            before = os.fstat(observed)
            if (identity(before) != expected_identity or
                    identity(os.fstat(fd)) != expected_identity or
                    before.st_mode & 0o022):
                raise ValueError('Functional camera derived file identity changed')
            raw = None
            if retain:
                with os.fdopen(os.dup(observed), 'rb') as stream:
                    raw = stream.read()
                observed_digest = hashlib.sha256(raw).hexdigest()
            else:
                observed_digest = digest_fd(observed)
            if (observed_digest != expected_digest or
                    identity(os.fstat(observed)) != expected_identity or
                    identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False)) != expected_identity):
                raise ValueError('Functional camera derived file readback differs')
            return raw
        finally:
            os.close(observed)

    def iomap_path(self, value):
        owner = self

        class FixedPath(type(Path())):
            def open(self, *args, **kwargs):
                raise ValueError('Functional camera iomap requires checked fixed-directory I/O')

            def read_bytes(self):
                return owner.read(owner._name(self))

            def write_bytes(self, raw):
                return owner.write(owner._name(self), raw)

            def write_text(self, text, encoding=None, errors=None, newline=None):
                if newline is not None:
                    raise ValueError('Functional camera iomap newline override refused')
                owner.write(owner._name(self), text.encode(encoding or 'utf-8', errors or 'strict'))
                return len(text)

            def exists(self):
                name = owner._name(self)
                try:
                    os.stat(name, dir_fd=owner.fd, follow_symlinks=False)
                    return True
                except FileNotFoundError:
                    return False

        self._name(value)
        return FixedPath(value)

    def check(self):
        # Names are checked only for rebinding; file I/O remains relative to the held FD.
        with directory(self.parent) as public_parent:
            for parent_fd in (public_parent, self.parent_fd):
                parent = os.fstat(parent_fd)
                if ((parent.st_dev, parent.st_ino, parent.st_mode, parent.st_uid) != self.parent_identity):
                    raise ValueError('Functional camera output parent changed')
            named = os.stat(self.output.name, dir_fd=public_parent, follow_symlinks=False)
            held = os.fstat(self.fd)
            if ((named.st_dev, named.st_ino, named.st_mode, named.st_uid) != self.directory_identity or
                    (held.st_dev, held.st_ino, held.st_mode, held.st_uid) != self.directory_identity):
                raise ValueError('Functional camera output directory changed')
            for name in self.files:
                self.read(name, retain=False)
            if self.sparse is not None:
                sparse = self.sparse
                held = os.fstat(sparse['fd'])
                named = os.stat('ram-card-sparse', dir_fd=self.fd, follow_symlinks=False)
                if (not stat.S_ISDIR(named.st_mode) or named.st_uid != os.geteuid() or
                        stat.S_IMODE(named.st_mode) != 0o700 or
                        (held.st_dev, held.st_ino) != sparse['directory'] or
                        (named.st_dev, named.st_ino) != sparse['directory'] or
                        set(os.listdir(sparse['fd'])) != set(sparse['files'])):
                    raise ValueError('Functional camera sparse directory identity changed')
                for name, (size, expected) in sparse['files'].items():
                    observed = regular(sparse['fd'], name)
                    try:
                        before = os.fstat(observed)
                        if (before.st_size != size or before.st_nlink != 1 or before.st_mode & 0o022 or
                                digest_fd(observed) != expected or
                                identity(before) != identity(os.fstat(observed)) or
                                identity(before) != identity(os.stat(name, dir_fd=sparse['fd'], follow_symlinks=False))):
                            raise ValueError('Functional camera sparse seed file changed')
                    finally:
                        os.close(observed)

    def publish(self, text):
        pending = '.backup-profile.pending.json'
        name = 'backup-profile.json'
        self.write(pending, text.encode('utf-8'))
        self.check()
        fd, _, digest = self.files[pending]
        try:
            os.link(f'/proc/self/fd/{fd}', name, dst_dir_fd=self.fd, follow_symlinks=True)
            current = identity(os.fstat(fd))
            self.files[pending] = self.files[name] = (fd, current, digest)
            os.fsync(self.fd)
            self.check()
        except BaseException:
            try:
                named = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                held = os.fstat(fd)
                if (named.st_dev, named.st_ino) == (held.st_dev, held.st_ino):
                    os.unlink(name, dir_fd=self.fd)
            raise


class _RamProfileLease:
    """The caller retains this owner until all consumers have actually exited."""

    def __init__(self, stack, parallel_peak_bytes):
        self.stack = stack
        self.parallel_peak_bytes = parallel_peak_bytes
        self.active = True
        self.output = None
        self.binding = None
        self.public_fds = []
        self.cleanup_errors = []

    def _close_public_fds(self, exc_type, original, traceback):
        # Private anchors remain locked until all public numbers have been checked.
        for fd, anchor, stamp in self.public_fds:
            try:
                if identity(os.fstat(anchor)) != stamp:
                    raise ValueError('Private anchor identity changed')
                fcntl.flock(anchor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if identity(os.fstat(fd)) != stamp:
                    raise ValueError('FD identity changed')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException as error:
                self.cleanup_errors.append(
                    f'RAM-card public FD {fd} cleanup refused; number left untouched: '
                    f'{type(error).__name__}: {error}')
                continue
            try:
                os.close(fd)
            except BaseException as error:
                self.cleanup_errors.append(
                    f'RAM-card public FD {fd} close failed: {type(error).__name__}: {error}')
        if self.cleanup_errors:
            if original is not None:
                for error in self.cleanup_errors:
                    original.add_note(error)
            else:
                raise ValueError('\n'.join(self.cleanup_errors))
        return False

    def adopt(self, output, environment):
        if self.output is not None or 'media-camera.fat' not in output.files or output.sparse is None:
            raise ValueError('Functional camera lease requires a single verified independent RAM seed')
        seed = output.files['media-camera.fat'][0]
        receipt = regular(output.fd, 'backup-profile.json')
        output.stack.callback(os.close, receipt)
        # Only duplicates are exposed. Original producer FDs are private anchors,
        # so their ordinary ExitStack callbacks can never close a reused public FD.
        output.stack.push(self._close_public_fds)
        for anchor in (seed, output.fd, receipt):
            fcntl.flock(anchor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stamp = identity(os.fstat(anchor))
            fd = os.dup(anchor)
            self.public_fds.append((fd, anchor, stamp))
        triple = tuple(fd for fd, _, _ in self.public_fds)
        env = dict(environment)
        env.update(A7C2_RAM_CARD_SEED_FD=str(triple[0]), A7C2_RAM_CARD_DIRECTORY_FD=str(triple[1]),
                   A7C2_RAM_CARD_RECEIPT_FD=str(triple[2]))
        self.output = output
        self.triple = triple
        self.environment = tuple(sorted(env.items()))
        self.binding = dict(fd=triple[0], dir_fd=triple[1], receipt_fd=triple[2],
                            pass_fds=triple, environment=env, verify=self.verify,
                            cleanup_errors=self.cleanup_errors,
                            host_fd_binding_verified=True, consumer_endpoint_verified=False,
                            guest_consumption_verified=False, capture_verified=False)
        self.verify()
        # Do not close producer FDs when prepare_profile's local ExitStack exits.
        self.stack.enter_context(output.stack.pop_all())
        return self.binding

    def verify(self):
        if not self.active or self.output is None or self.binding is None:
            raise ValueError('Functional camera consumer lease is closed or unbound')
        if (tuple(sorted(self.binding['environment'].items())) != self.environment or
                (self.binding['fd'], self.binding['dir_fd'], self.binding['receipt_fd']) != self.triple or
                self.binding['pass_fds'] != self.triple):
            raise ValueError('Functional camera FD/environment handoff changed')
        for fd, anchor, stamp in self.public_fds:
            if identity(os.fstat(anchor)) != stamp:
                raise ValueError('Functional camera private anchor identity changed')
            fcntl.flock(anchor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if identity(os.fstat(fd)) != stamp:
                raise ValueError('Functional camera inherited FD identity changed')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        seed, _, receipt = self.triple
        for fd in (seed, receipt):
            if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY:
                raise ValueError('Functional camera consumer input FD is not read-only')
        info = os.fstat(seed)
        if (info.st_size != FUNCTIONAL_CAMERA_RAM_BYTES or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('Functional camera consumer seed permissions/capacity changed')
        self.output.check()
        receipt_before = identity(os.fstat(receipt))
        digest = hashlib.sha256()
        offset = 0
        while True:
            raw = os.pread(receipt, 1024**2, offset)
            if not raw:
                break
            digest.update(raw)
            offset += len(raw)
        if (digest.hexdigest() != self.output.files['backup-profile.json'][2] or
                identity(os.fstat(receipt)) != receipt_before or
                receipt_before != self.output.files['backup-profile.json'][1]):
            raise ValueError('Functional camera receipt FD readback differs')
        return dict(host_fd_binding_verified=True, consumer_endpoint_verified=False,
                    guest_consumption_verified=False, capture_verified=False)


@contextmanager
def ram_profile_lease(native, env, output_parent=None, *, parallel_peak_bytes=None, model_base=None):
    """Yield environment + pass_fds; owner must retain this through consumer exit.

    This prepares host inputs only; top-level probe and guest acceptance stay gated.
    Pass the triple unchanged with Popen(pass_fds=...). Host consumers must not
    reopen original paths; after verification, bwrap may bind those exact FD inodes
    as read-only sandbox paths. Consumers must not close/unlock borrowed FDs.
    """
    if not validate_functional_camera_media(env):
        raise ValueError('Functional camera RAM lease requires explicit RAM media intent')
    if type(parallel_peak_bytes) is not int or parallel_peak_bytes < 0:
        raise ValueError('Functional RAM lease requires declared parallel peak bytes, including zero')
    native = Path(native)
    if (not native.is_absolute() or '..' in native.parts or native.resolve() != native or
            len(native.parents) < 2):
        raise ValueError('Functional RAM lease requires an absolute product runtime without symlinks')
    product = native.parents[1]
    parent = Path(output_parent) if output_parent is not None else native / 'functional-camera-profiles'
    seed = Path(env.get('A7C2_SD_IMAGE') or native / 'menu-root/simulation/media-camera.fat')
    if product == Path('/') or any(not path.is_absolute() or '..' in path.parts or
                                   path == product or not path.is_relative_to(product)
                                   for path in (parent, seed)):
        raise ValueError('Functional RAM-card seed and output must stay inside this product')
    with ExitStack() as stack:
        owner = _RamProfileLease(stack, parallel_peak_bytes)
        try:
            model_options = {} if model_base is None else {'_model_base': model_base}
            binding = prepare_profile(native, env, output_parent, _consumer_owner=owner, **model_options)
            yield binding
        except BaseException as error:
            if owner.output is not None:
                try:
                    owner.verify()
                except BaseException as check_error:
                    error.add_note('RAM-card lease final verification failed: ' + str(check_error))
            raise
        else:
            owner.verify()
        finally:
            owner.active = False


def prepare_profile(native, env, output_parent=None, *, _consumer_owner=None, _model_base=None):
    ram_media = validate_functional_camera_media(env)
    if _model_base is not None and _consumer_owner is None:
        raise ValueError('Alternate model requires a live RAM-card lease')
    if _consumer_owner is not None and (not ram_media or
            not isinstance(_consumer_owner, _RamProfileLease) or not _consumer_owner.active):
        raise ValueError('Functional camera consumer handoff requires a live RAM-card lease')
    native=Path(native).resolve()
    dfs=env.get('MENU_DFS_SELECTOR','')
    if dfs not in ('','virtual-selector-v1') or (dfs and env.get('MENU_TCIN_DETECT')!='virtual-inactive-v1'):
        raise ValueError('DFS selector requires the explicit TCIN inactive profile')
    vef=env.get('MENU_VEF_PATH','')
    if vef not in ('','virtual-nomem-v1') or (vef and dfs!='virtual-selector-v1'):
        raise ValueError('VEF NoMem requires the explicit DFS selector profile')
    adf=env.get('MENU_ADF_PROC_PATH','')
    if adf not in ('',ADF_PROFILE) or (adf and (
            vef!='virtual-nomem-v1' or any(env.get(name)!=value for name,value in (
                ('MENU_AUDIO_BOOT_CONFIG','1'),('MENU_PIN_REGISTRY','1'),
                ('MENU_PIN_CONTROL_MEMORY','1'),('MENU_PIN_CONNECTION','cold'))) or
            any(env.get(name) for name in ADF_CONFLICTS))):
        raise ValueError('ADF source7 Idle requires guarded VEF NoMem/native resources without frame or ready injection')
    adf_input=env.get('MENU_ADF_SET_INPUT','')
    if adf_input not in ('',INPUT_PROFILE) or (adf_input and adf!=ADF_PROFILE):
        raise ValueError('ADF set input requires the explicit guarded ADF source7 Idle profile')
    adf_output=env.get('MENU_ADF_SET_OUTPUT','')
    if adf_output not in ('',OUTPUT_PROFILE) or (adf_output and (
            adf_input!=INPUT_PROFILE or (env.get('MENU_USB_NET') and
            env.get('A7C2_DIRECTORY_SD_PROFILE')!='directory-vvfat-256gb-v1'))):
        raise ValueError('ADF set output requires the explicit guarded ADF set input and directory SD profiles')
    bb_set_mode=env.get('MENU_BB_SET_MODE','')
    if bb_set_mode not in ('',BB_SET_MODE_PROFILE) or (bb_set_mode and (
            env.get('A7C2_BB_SET_MODE')!=BB_SET_MODE_PROFILE or
            (not ram_media and env.get('A7C2_DIRECTORY_SD_PROFILE')!='directory-vvfat-256gb-v1') or
            adf_output!=OUTPUT_PROFILE or adf_input!=INPUT_PROFILE or adf!=ADF_PROFILE or
            vef!='virtual-nomem-v1' or dfs!='virtual-selector-v1' or
            env.get('MENU_TCIN_DETECT')!='virtual-inactive-v1' or
            env.get('SEED_BACKUP','alllang')!='alllang' or
            any(env.get(name) for name in BB_MODE_CONFLICTS))):
        raise ValueError('BB set mode requires the complete guarded ADF/Backup public directory profile')
    imaging_connect=env.get('MENU_IMAGING_CONNECT','')
    if imaging_connect not in ('',IMAGING_CONNECT_PROFILE) or (imaging_connect and (
            env.get('A7C2_IMAGING_CONNECT')!=IMAGING_CONNECT_PROFILE or
            bb_set_mode!=BB_SET_MODE_PROFILE or any(env.get(name)!=value for name,value in (
                ('MENU_PIN_REGISTRY','1'),('MENU_PIN_CONTROL_MEMORY','1'),
                ('MENU_PIN_CONNECTION','cold'))))):
        raise ValueError('Imaging connection requires the exact guarded BB set mode and pin profiles')
    imaging_control_connect=env.get('MENU_IMAGING_CONTROL_CONNECT','')
    if imaging_control_connect not in ('',IMAGING_CONTROL_CONNECT_PROFILE) or (imaging_control_connect and (
            env.get('A7C2_IMAGING_CONTROL_CONNECT')!=IMAGING_CONTROL_CONNECT_PROFILE or
            imaging_connect!=IMAGING_CONNECT_PROFILE)):
        raise ValueError('Imaging control connection requires the exact guarded first imaging connection profile')
    imaging_adf_connect=env.get('MENU_IMAGING_ADF_CONNECT','')
    if imaging_adf_connect not in ('',IMAGING_ADF_CONNECT_PROFILE) or (imaging_adf_connect and (
            env.get('A7C2_IMAGING_ADF_CONNECT')!=IMAGING_ADF_CONNECT_PROFILE or
            imaging_control_connect!=IMAGING_CONTROL_CONNECT_PROFILE)):
        raise ValueError('Imaging ADF connection requires the exact guarded second imaging control connection profile')
    infrabb_vef_connect=env.get('MENU_INFRABB_VEF_CONNECT','')
    if infrabb_vef_connect not in ('',INFRABB_VEF_CONNECT_PROFILE) or (infrabb_vef_connect and (
            env.get('A7C2_INFRABB_VEF_CONNECT')!=INFRABB_VEF_CONNECT_PROFILE or
            imaging_adf_connect!=IMAGING_ADF_CONNECT_PROFILE)):
        raise ValueError('InfraBB VEF connection requires the exact guarded third imaging ADF connection profile')
    infrabb_vef_control_connect=env.get('MENU_INFRABB_VEF_CONTROL_CONNECT','')
    if infrabb_vef_control_connect not in ('',FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE) or (infrabb_vef_control_connect and (
            env.get('A7C2_INFRABB_VEF_CONTROL_CONNECT')!=FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE or
            infrabb_vef_connect!=INFRABB_VEF_CONNECT_PROFILE)):
        raise ValueError('InfraBB VEF control connection requires the exact guarded fourth InfraBB VEF connection profile')
    vef_pinmem_input_connect=env.get('MENU_VEF_PINMEM_INPUT_CONNECT','')
    if vef_pinmem_input_connect not in ('',FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE) or (vef_pinmem_input_connect and (
            env.get('A7C2_VEF_PINMEM_INPUT_CONNECT')!=FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE or
            infrabb_vef_control_connect!=FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE or
            env.get('SEED_BACKUP')!='alllang')):
        raise ValueError('VEF PinMem input connection requires the exact guarded fifth InfraBB VEF control connection profile')
    vef_pinmem_control_connect=env.get('MENU_VEF_PINMEM_CONTROL_CONNECT','')
    if vef_pinmem_control_connect not in ('',FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE) or (vef_pinmem_control_connect and (
            env.get('A7C2_VEF_PINMEM_CONTROL_CONNECT')!=FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE or
            vef_pinmem_input_connect!=FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE)):
        raise ValueError('VEF PinMem control connection requires the exact guarded sixth VEF PinMem input connection profile')
    pinmem_peers=env.get('MENU_PINMEM_PEER_CONNECT','')
    if pinmem_peers not in ('',FULL_PINMEM_PEER_CONNECTIONS_PROFILE) or (pinmem_peers and (
            env.get('A7C2_PINMEM_PEER_CONNECT')!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE or
            vef_pinmem_control_connect!=FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE)):
        raise ValueError('PinMem peer connections require the exact guarded seventh VEF PinMem control connection profile')
    pinmem_hdmi_video_connect=env.get('MENU_PINMEM_HDMI_VIDEO_CONNECT','')
    if pinmem_hdmi_video_connect not in ('',FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE) or (pinmem_hdmi_video_connect and (
            env.get('A7C2_PINMEM_HDMI_VIDEO_CONNECT')!=FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE or
            pinmem_peers!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE)):
        raise ValueError('PinMem HDMI video connection requires the exact guarded PinMem peer connection chain')
    pinmem_osd_connect=env.get('MENU_PINMEM_OSD_CONNECT','')
    if pinmem_osd_connect not in ('',FULL_PINMEM_OSD_CONNECTION_PROFILE) or (pinmem_osd_connect and (
            env.get('A7C2_PINMEM_OSD_CONNECT')!=FULL_PINMEM_OSD_CONNECTION_PROFILE or
            pinmem_peers!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE)):
        raise ValueError('PinMem OSD connection requires the exact guarded PinMem peer connection chain')
    adf_hdmi_audio_connect=env.get('MENU_ADF_HDMI_AUDIO_CONNECT','')
    if adf_hdmi_audio_connect not in ('',FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE) or (adf_hdmi_audio_connect and (
            env.get('A7C2_ADF_HDMI_AUDIO_CONNECT')!=FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE or
            pinmem_peers!=FULL_PINMEM_PEER_CONNECTIONS_PROFILE)):
        raise ValueError('ADF HDMI audio connection requires the exact guarded PinMem peer connection chain')
    cp302c_no_transition=env.get('MENU_CP302C_NO_TRANSITION','')
    if (cp302c_no_transition not in ('',FULL_CP302C_NO_TRANSITION_PROFILE) or
            env.get('A7C2_CP302C_NO_TRANSITION','')!=cp302c_no_transition or (cp302c_no_transition and (
            pinmem_hdmi_video_connect!=FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE or
            pinmem_osd_connect!=FULL_PINMEM_OSD_CONNECTION_PROFILE or
            adf_hdmi_audio_connect!=FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE or
            env.get('MENU_CP_BACKGROUND')!='virtual-mode3-cold-v1'))):
        raise ValueError('CP302c NO-TRANSITION requires the exact guarded full 13-connection chain and CP3007 profile')
    cp302c_diagnostic=env.get('MENU_CP302C_DIAGNOSTIC','')
    if (cp302c_diagnostic not in ('',FULL_CP302C_DIAGNOSTIC_PROFILE) or
            env.get('A7C2_CP302C_DIAGNOSTIC','')!=cp302c_diagnostic or (cp302c_diagnostic and (
            cp302c_no_transition or
            pinmem_hdmi_video_connect!=FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE or
            pinmem_osd_connect!=FULL_PINMEM_OSD_CONNECTION_PROFILE or
            adf_hdmi_audio_connect!=FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE or
            env.get('MENU_CP_BACKGROUND')!='virtual-mode3-cold-v1'))):
        raise ValueError('CP302c diagnostic requires the exact guarded full 13-connection chain and CP3007 profile, exclusive of NO-TRANSITION')
    cp_notification_control=env.get('MENU_CP_NOTIFICATION_CONTROL','')
    if (cp_notification_control not in ('',FULL_CP_NOTIFICATION_CONTROL_PROFILE) or
            env.get('A7C2_CP_NOTIFICATION_CONTROL','')!=cp_notification_control or
            (cp_notification_control and cp302c_diagnostic!=FULL_CP302C_DIAGNOSTIC_PROFILE)):
        raise ValueError('CP notification control requires the exact paired mode0 profile and guarded CP302c diagnostic predecessor')
    cp_capture_format=env.get('MENU_CP_CAPTURE_FORMAT','')
    if (cp_capture_format not in ('',FULL_CP_CAPTURE_FORMAT_PROFILE,FULL_CP_STARTUP_DIAGNOSTIC_PROFILE,FULL_CP_EE_DIAGNOSTIC_PROFILE,FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE,FULL_CP_OWNED_STATE_PROFILE) or
            env.get('A7C2_CP_CAPTURE_FORMAT','')!=cp_capture_format or
            (cp_capture_format and cp_notification_control!=FULL_CP_NOTIFICATION_CONTROL_PROFILE)):
        raise ValueError('CP capture format requires the exact paired profile and guarded CP notification mode0 predecessor')
    functional_camera = env.get('MENU_FUNCTIONAL_CAMERA', '')
    if (functional_camera not in ('', FUNCTIONAL_CAMERA_PROFILE) or
            env.get('A7C2_FUNCTIONAL_CAMERA', '') != functional_camera or
            (functional_camera and cp_capture_format != FULL_CP_OWNED_STATE_PROFILE)):
        raise ValueError('Functional camera requires the exact paired profile and owned-state full-connection predecessor')
    required={'A7C2_BACKUP_SYNC':PROFILE,'MENU_CP_BACKGROUND':'virtual-mode3-cold-v1',
              'MENU_UDATE_DISTRIBUTION':'virtual-roundtrip-v1','MENU_TOUCH_PANEL':'virtual-config-v1'}
    if not ram_media:
        required['A7C2_DIRECTORY_SD_PROFILE']='directory-vvfat-256gb-v1'
    if any(env.get(k)!=v for k,v in required.items()):
        raise ValueError('Backup requires the complete natural CP3007/UDATE/touch/directory profile')
    if (env.get('A7C2_NATURAL_IMAGING_PROFILE') or env.get('MENU_VPANEL')=='1' or
            env.get('MENU_PCIDMA_XFER')=='1' or env.get('QEMU_CPU_COUNT','1')!='1'):
        raise ValueError('Backup profile conflicts with imaging, diagnostic pattern DMA or SMP2')
    build,binary,receipt=validate_build(native,env.get('A7C2_BACKUP_BUILD',''))
    if ram_media:
        from functional_camera_runner import validate_artifact
        validate_artifact(native if _model_base is None else _model_base, binary,
                          scope_build_receipt=env.get('A7C2_SCOPE_OBSERVER_BUILD') or None)
    seed=native/'menu-root/seed-backup.bin'
    if ram_media:
        source_backup_seed, data = _bound_profile_input(seed, retain=True, expected_bytes=2390264)
    else:
        with seed.open('rb') as stream: data=stream.read(2390265)
    if len(data)!=2390264 or hashlib.sha256(data).hexdigest()!=SEED_SHA:
        raise ValueError('Backup fixture source is not the pinned official ALLLANG seed')
    primary=data[0xed000:]
    if len(primary)!=PRIMARY_BYTES or hashlib.sha256(primary).hexdigest()!=PRIMARY_SHA:
        raise ValueError('Public Backup primary projection differs')
    source = native/'qemu-kernel-probe.sh' if ram_media else Path(env['MENU_KERNEL_SCRIPT'])
    official=native/'unpacked/firmware.tar_unpacked/0800_appli/setting/cxd90057.dtb'
    media_fields = {}
    if ram_media:
        media_seed, _ = _bound_profile_input(
            env.get('A7C2_SD_IMAGE') or native/'menu-root/simulation/media-camera.fat',
            expected_bytes=FUNCTIONAL_CAMERA_RAM_BYTES, single_link=True)
        source_script, script_raw = _bound_profile_input(source, retain=True)
        source_board, board_raw = _bound_profile_input(native/'qemu-virt-board/virt-packed.dtb', retain=True)
        official_board, official_raw = _bound_profile_input(official, retain=True)
        source_binary, _ = _bound_profile_input(binary)
        if source_binary['sha256'] != receipt['binary_sha256']:
            raise ValueError('Functional camera QEMU binary changed after build validation')
        script = script_raw.decode('utf-8')
        anchor = 'project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"'
        if script.count(anchor) != 1:
            raise ValueError('Functional camera baseline launcher root anchor changed')
        script = script.replace(anchor, 'project_dir=' + shlex.quote(str(native.parent)), 1)
        media_fields = {'schema':'a7c2-functional-camera-ram-media-v1',
                        'physical_compatible':False,'media_profile': ram_media, 'media_seed_source': media_seed['path'],
                        'media_seed_bytes': media_seed['bytes'], 'media_seed_sha256': media_seed['sha256'],
                        'media_seed_identity': media_seed['identity'],
                        'source_backup_seed': source_backup_seed,
                        'source_script': source_script, 'source_board': source_board,
                        'official_board': official_board, 'source_binary': source_binary,
                        'consumer_handoff': 'refused-path-only-no-caller-held-fds',
                        'consumer_binding_verified': False,
                        'usb_ethernet_added': False, 'directory_sd_added': False}
    else:
        script=source.read_text()
    bind='    --bind "$output_dir" /out \\\n'
    gates='    "${timer_environment[@]}" \\\n'
    if script.count(bind)!=1 or script.count(gates)!=1:
        raise ValueError('Backup profile launcher anchors changed')
    with ExitStack() as stack:
        output_guard = None
        if ram_media:
            parent = Path(output_parent) if output_parent is not None else native/'functional-camera-profiles'
            output_guard = _RamProfileOutput(stack, parent)
            output = output_guard.output
            if _consumer_owner is not None:
                cloned_seed, sparse_proof = output_guard.copy_seed(
                    media_seed, parallel_peak_bytes=_consumer_owner.parallel_peak_bytes)
                media_fields.update(media_seed_origin=media_seed,
                                    media_seed_source=cloned_seed['path'],
                                    media_seed_bytes=cloned_seed['bytes'],
                                    media_seed_sha256=cloned_seed['sha256'],
                                    media_seed_identity=cloned_seed['identity'],
                                    sparse_seed=sparse_proof,
                                    consumer_handoff='caller-held-fd-lease-v1')
            board_source = output_guard.pinned/'source-board.dtb'
            official = output_guard.pinned/'official-board.dtb'
            output_guard.write(board_source.name, board_raw)
            output_guard.write(official.name, official_raw)
        else:
            output=source.parent
            board_source=Path(env['MENU_DTB'])
        fixture=output/'backup-primary.bin'
        if ram_media:
            output_guard.write(fixture.name, primary)
            if output_guard.files[fixture.name][2] != PRIMARY_SHA:
                raise ValueError('Backup fixture writeback differs')
        else:
            with fixture.open('xb') as stream: stream.write(primary)
            if sha(fixture)!=PRIMARY_SHA: raise ValueError('Backup fixture writeback differs')
        script=script.replace(bind,bind+'    --ro-bind '+shlex.quote(str(fixture))+' /backup-primary.bin \\\n',1)
        flags=('QEMU_SONY_PCIE_PEER_TEST','QEMU_SONY_PCIE_SCU_TEST','QEMU_SONY_CCF_TEST',
               'QEMU_SONY_PHY_INIT_TEST','QEMU_SONY_BACKUP_TEST','QEMU_SONY_DMA330')
        if dfs:flags+=('QEMU_SONY_DFS_TEST',)
        script=script.replace(gates,gates+''.join('    --setenv '+flag+' 1 \\\n' for flag in flags)+
                              '    --setenv QEMU_SONY_BACKUP_FILE /backup-primary.bin \\\n',1)
        board=output/('board-ram-backup.dtb' if ram_media else 'board-usb-backup.dtb')
        iomap=load_module('backup_iomap_board',native.parents[1]/'report/virtual-pcidma/iomap_board.py')
        if ram_media:
            # iomap uses Path.write_bytes/write_text; constrain those writes too.
            original_path = iomap.Path
            iomap.Path = output_guard.iomap_path
            try:
                derived = iomap.prepare(board_source, output_guard.pinned/board.name, official,
                                        all_pcie_wrappers=True, ccf_provider=True, phy_upload=True,
                                        dma_window=True, backup_control=True)
            finally:
                iomap.Path = original_path
            if derived is None or str(derived) != str(output_guard.pinned/board.name):
                raise ValueError('Functional camera iomap returned an unexpected output path')
            output_guard.read(board.name)
            output_guard.read('iomap-board-proof.json')
        else:
            iomap.prepare(board_source,board,official,all_pcie_wrappers=True,
                          ccf_provider=True,phy_upload=True,dma_window=True,backup_control=True)
        launcher=output/('kernel-ram-backup.sh' if ram_media else 'kernel-directory-backup.sh')
        if ram_media:
            output_guard.write(launcher.name, script.encode('utf-8'))
            script_sha = output_guard.files[launcher.name][2]
            board_sha = output_guard.files[board.name][2]
        else:
            with launcher.open('x') as stream: stream.write(script)
            if launcher.read_text() != script:
                raise ValueError('Backup profile launcher writeback differs')
            script_sha, board_sha = sha(launcher), sha(board)
        proof={'profile':PROFILE,'binary':str(binary),'binary_sha256':receipt['binary_sha256'],
               'source_seed_sha256':SEED_SHA,'fixture_sha256':PRIMARY_SHA,'fixture_bytes':PRIMARY_BYTES,
               **media_fields,
               'fixture':str(fixture),'derived_script_sha256':script_sha,'derived_board_sha256':board_sha,
               'hardware_flags':list(flags),'dfs_selector_profile':dfs or None,
               'vef_path_profile':vef or None,
               **adf_proc_profile_fields(adf),
               **adf_set_input_profile_fields(adf_input),
               **adf_set_output_profile_fields(adf_output),
               **bb_set_mode_profile_fields(bb_set_mode),
               **imaging_pin_connection_profile_fields(imaging_connect),
               **imaging_control_connection_profile_fields(imaging_control_connect),
               **imaging_adf_connection_profile_fields(imaging_adf_connect),
               **infrabb_vef_connection_profile_fields(infrabb_vef_connect),
               **infrabb_vef_control_connection_profile_fields(infrabb_vef_control_connect),
               **vef_pinmem_input_connection_profile_fields(vef_pinmem_input_connect),
               **vef_pinmem_control_connection_profile_fields(vef_pinmem_control_connect),
               **pinmem_peer_connections_profile_fields(pinmem_peers),
               **pinmem_hdmi_video_connection_profile_fields(pinmem_hdmi_video_connect),
               **pinmem_osd_connection_profile_fields(pinmem_osd_connect),
               **adf_hdmi_audio_connection_profile_fields(adf_hdmi_audio_connect),
               **cp302c_no_transition_profile_fields(cp302c_no_transition),
               **cp302c_diagnostic_profile_fields(cp302c_diagnostic),
               **cp_notification_control_profile_fields(cp_notification_control),
               **cp_capture_format_profile_fields(cp_capture_format),
               **functional_camera_profile_fields(functional_camera),
               'dfs_actual_clock_changes':False,
               'initial_source':'conditional public second BK4, unmodified',
               'original_bootloader_executed':False,'original_cp_executed':False,'capture_verified':False}
        if ram_media:
            for source_input in (media_seed, source_backup_seed, source_script, source_board, official_board, source_binary):
                current, _ = _bound_profile_input(source_input['path'])
                if current != source_input:
                    raise ValueError('Functional camera profile source changed during derivation')
        receipt_path = output/'backup-profile.json'
        receipt_text = json.dumps(proof,indent=2)+'\n'
        result = {'MENU_KERNEL_SCRIPT':str(launcher),'MENU_DTB':str(board),
                  'QEMU_SYSTEM_DIR':str(binary.parent),'QEMU_SYSTEM_BINARY':binary.name,
                  'QEMU_SONY_PCIDMA':'1','MENU_BACKUP_SYNC':PROFILE,
                  'MENU_BACKUP_PROFILE_RECEIPT':str(receipt_path),'SEED_BACKUP':'alllang'}
        if ram_media:
            result['A7C2_SD_IMAGE'] = media_fields['media_seed_source']
            output_guard.publish(receipt_text)
            return output_guard.consumer_environment(output_guard, result, _consumer_owner)
        else:
            with receipt_path.open('x') as stream:
                stream.write(receipt_text)
            if receipt_path.read_text() != receipt_text:
                raise ValueError('Backup profile receipt writeback differs')
        return result
