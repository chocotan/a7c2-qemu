"""Explicit native Backup fixture/profile; no CP execution or capture claim."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex

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
        'display_config_policy': 'original-0141-refresh-0152-disabled-and-0162-off-RGB-readback-before-independent-reply',
        'display_config_commands': [0x141, 0x152, 0x162],
        'peaking_enabled_supported': False,
        'display_flag_enabled_supported': False,
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


def prepare_profile(native, env):
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
            env.get('A7C2_DIRECTORY_SD_PROFILE')!='directory-vvfat-256gb-v1' or
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
              'MENU_UDATE_DISTRIBUTION':'virtual-roundtrip-v1','MENU_TOUCH_PANEL':'virtual-config-v1',
              'A7C2_DIRECTORY_SD_PROFILE':'directory-vvfat-256gb-v1'}
    if any(env.get(k)!=v for k,v in required.items()):
        raise ValueError('Backup requires the complete natural CP3007/UDATE/touch/directory profile')
    if (env.get('A7C2_NATURAL_IMAGING_PROFILE') or env.get('MENU_VPANEL')=='1' or
            env.get('MENU_PCIDMA_XFER')=='1' or env.get('QEMU_CPU_COUNT','1')!='1'):
        raise ValueError('Backup profile conflicts with imaging, diagnostic pattern DMA or SMP2')
    build,binary,receipt=validate_build(native,env.get('A7C2_BACKUP_BUILD',''))
    seed=native/'menu-root/seed-backup.bin'
    with seed.open('rb') as stream: data=stream.read(2390265)
    if len(data)!=2390264 or hashlib.sha256(data).hexdigest()!=SEED_SHA:
        raise ValueError('Backup fixture source is not the pinned official ALLLANG seed')
    primary=data[0xed000:]
    if len(primary)!=PRIMARY_BYTES or hashlib.sha256(primary).hexdigest()!=PRIMARY_SHA:
        raise ValueError('Public Backup primary projection differs')
    source=Path(env['MENU_KERNEL_SCRIPT'])
    script=source.read_text()
    bind='    --bind "$output_dir" /out \\\n'
    gates='    "${timer_environment[@]}" \\\n'
    if script.count(bind)!=1 or script.count(gates)!=1:
        raise ValueError('Backup profile launcher anchors changed')
    output=source.parent
    fixture=output/'backup-primary.bin'
    with fixture.open('xb') as stream: stream.write(primary)
    if sha(fixture)!=PRIMARY_SHA: raise ValueError('Backup fixture writeback differs')
    script=script.replace(bind,bind+'    --ro-bind '+shlex.quote(str(fixture))+' /backup-primary.bin \\\n',1)
    flags=('QEMU_SONY_PCIE_PEER_TEST','QEMU_SONY_PCIE_SCU_TEST','QEMU_SONY_CCF_TEST',
           'QEMU_SONY_PHY_INIT_TEST','QEMU_SONY_BACKUP_TEST','QEMU_SONY_DMA330')
    if dfs:flags+=('QEMU_SONY_DFS_TEST',)
    script=script.replace(gates,gates+''.join('    --setenv '+flag+' 1 \\\n' for flag in flags)+
                          '    --setenv QEMU_SONY_BACKUP_FILE /backup-primary.bin \\\n',1)
    board=output/'board-usb-backup.dtb'
    iomap=load_module('backup_iomap_board',native.parents[1]/'report/virtual-pcidma/iomap_board.py')
    official=native/'unpacked/firmware.tar_unpacked/0800_appli/setting/cxd90057.dtb'
    iomap.prepare(env['MENU_DTB'],board,official,all_pcie_wrappers=True,
                  ccf_provider=True,phy_upload=True,dma_window=True,backup_control=True)
    launcher=output/'kernel-directory-backup.sh'
    with launcher.open('x') as stream: stream.write(script)
    proof={'profile':PROFILE,'binary':str(binary),'binary_sha256':receipt['binary_sha256'],
           'source_seed_sha256':SEED_SHA,'fixture_sha256':PRIMARY_SHA,'fixture_bytes':PRIMARY_BYTES,
           'fixture':str(fixture),'derived_script_sha256':sha(launcher),'derived_board_sha256':sha(board),
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
    (output/'backup-profile.json').write_text(json.dumps(proof,indent=2)+'\n')
    return {'MENU_KERNEL_SCRIPT':str(launcher),'MENU_DTB':str(board),
            'QEMU_SYSTEM_DIR':str(binary.parent),'QEMU_SYSTEM_BINARY':binary.name,
            'QEMU_SONY_PCIDMA':'1','MENU_BACKUP_SYNC':PROFILE,
            'MENU_BACKUP_PROFILE_RECEIPT':str(output/'backup-profile.json'),'SEED_BACKUP':'alllang'}
