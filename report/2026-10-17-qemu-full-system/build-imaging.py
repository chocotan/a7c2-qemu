#!/usr/bin/env python3
"""Derive the full-dump observer without changing the official-route source."""
import hashlib
from pathlib import Path
import subprocess


def build(menu, root, output, observer_source=None, observer_sha256=None, *, lcd_pipeline_profile='strict', lcd_ram_snapshot=False, persistent_claim=False, usb_touch_profile=None, usb_touch_ap=None, usb_touch_cp=None):
    here=Path(__file__).resolve().parent
    if lcd_pipeline_profile not in ('strict','latency-v1','latency-v2','latency-v3'):
        raise ValueError('Unknown LCD pipeline profile')
    if (observer_source is None)!=(observer_sha256 is None):
        raise ValueError('Explicit observer source requires its expected SHA256')
    selected=Path(observer_source) if observer_source is not None else menu/'menu-observe.c'
    if selected.is_symlink() or not selected.is_file():
        raise ValueError('Expected an ordinary observer source file')
    source_bytes=selected.read_bytes();source_hash=hashlib.sha256(source_bytes).hexdigest()
    if observer_sha256 is not None and source_hash!=observer_sha256:
        raise ValueError('Explicit observer source SHA256 differs')
    source=source_bytes.decode('utf-8')
    import runpy
    touch_scope=runpy.run_path(str(here/"usb-touch-scope.py"))
    touch_receipt=touch_scope["prepare"](usb_touch_profile,usb_touch_ap,usb_touch_cp)
    if type(persistent_claim) is not bool or (persistent_claim and lcd_pipeline_profile!='strict'):
        raise ValueError('Persistent display claim requires the explicit strict-model cold profile')
    if persistent_claim:
        claim='hosd_claim("/tmp/headless-osd.claim", "/proc/modules", stat_queue, record)'
        if source.count(claim)!=1:raise ValueError('Persistent display claim source differs')
        source=source.replace(claim,'hosd_claim("/dev/qemu-simulation/headless-osd.claim", "/proc/modules", stat_queue, record)',1)
    pipeline_api=None
    ram_api=None
    if type(lcd_ram_snapshot) is not bool or (lcd_ram_snapshot and lcd_pipeline_profile!='latency-v3'):
        raise ValueError('LCD RAM snapshot requires the explicit latency-v3 profile')
    if lcd_ram_snapshot:
        import runpy
        ram_api=runpy.run_path(str(here/'lcd-ram-snapshot.py'))
        ram_api['validate_pinned'](menu)
    if lcd_pipeline_profile in ('latency-v1','latency-v2','latency-v3'):
        import runpy
        pipeline_api=runpy.run_path(str(here/'lcd-pipeline.py'))
        pipeline_api['validate'](menu,selected)
        pipeline_api['validate_scratch'](menu,root,output)
        if lcd_pipeline_profile=='latency-v2':
            pipeline_api['validate_v2'](menu,output)
        if lcd_pipeline_profile=='latency-v3':
            pipeline_api['validate_v3'](menu,output)
    changes=[
        ('    record("CREATE_SCREEN_ARGS ", text);',
         '    record("CREATE_SCREEN_ARGS ", text);\n'
         '    if (id==0x30c && appfw_base && getenv("FULLSYSTEM_INPUT_OBSERVE")) {\n'
         '        const volatile unsigned int *s=(const volatile unsigned int *)(appfw_base+0x7e5dd88UL);\n'
         '        char reason[192];\n'
         '        snprintf(reason,sizeof reason,"tid=%ld factor=%#x type=%#x next_reboot=%#x caller=%p",syscall(178),s[0],s[1],s[2],__builtin_return_address(0));\n'
         '        record("FULL_INPUT_SYSTEM_ERROR ",reason);\n'
         '    }'),
        ('#include "capid-service.h"', '#include "file-media-flush-hook.h"\n#include "imaging-device.h"\n#include "vdf-device.h"\n#include "audio-device.h"\n#include "hdmi-device.h"\n#include "vef-device.h"\n#include "pinmem-device.h"\n#include "pin-connection.h"\n#include "pin-buffer-owner.h"\nextern int strcmp(const char *, const char *);\n#include "capid-service.h"'),
        ('static const char *mirrored[] = {',
         'static const char *mirrored[] = { "FULL_CP_CONTROL_", "FULL_FILE_MEDIA_", "FULL_INFRABB_", "FULL_REMOTE_STATE_", "FULL_GUI_MODELS_", "FULL_INPUT_", "FULL_HDMI_CONNECT_", "FULL_ADFAUDIO_", "FULL_DMM_", "FULL_DIG_LEVEL_", "FULL_HDMIPIN_", "FULL_ADF_", "FULL_SCALAR_", "FULL_BACKUP_LOG_", "FULL_PINMEM_", "FULL_VEF_", "FULL_PIN_", "HDMI_PHOTO_REQUEST ", "FULL_HDMI_", "FULL_AUDIO_", "FULL_VDF_", "FULL_IMAGING_", "FULL_BUSPOWER_", "APPLOG ",'),
        ('    unsigned int observed = record_osd_transport("OSD_TRANSPORT_SEND ", id, message);\n'
         '    int result = real_send_msg(id, message);',
         '    extern int *__errno_location(void);\n'
         '    int cp_trace=id==0x90030001U && message && real_msg_size && real_get_source && getenv("FULLSYSTEM_INPUT_OBSERVE");\n'
         '    unsigned int cp_source=0,cp_bytes=0,cp_serial=0;\n'
         '    if (cp_trace) {\n'
         '        int saved_errno=*__errno_location(); static unsigned int cp_sequence;\n'
         '        cp_serial=__atomic_add_fetch(&cp_sequence,1,__ATOMIC_RELAXED);\n'
         '        cp_source=real_get_source(message); cp_bytes=real_msg_size(message);\n'
         '        unsigned int shown=cp_bytes<256?cp_bytes:256; char raw[513],line[800];\n'
         '        for (unsigned int i=0;i<shown;i++) snprintf(raw+2*i,3,"%02x",((const unsigned char *)message)[i]);\n'
         '        raw[2*shown]=0;\n'
         '        snprintf(line,sizeof line,"seq=%u tid=%ld destination=%#x source=%#x bytes=%u shown=%u raw=%s original_transport=1",\n'
         '            cp_serial,syscall(178),id,cp_source,cp_bytes,shown,raw);\n'
         '        record("FULL_CP_CONTROL_SEND ",line); *__errno_location()=saved_errno;\n'
         '    }\n'
         '    unsigned int observed = record_osd_transport("OSD_TRANSPORT_SEND ", id, message);\n'
         '    int result = real_send_msg(id, message);\n'
         '    if (cp_trace) {\n'
         '        int saved_errno=*__errno_location(); char line[224];\n'
         '        snprintf(line,sizeof line,"seq=%u tid=%ld destination=%#x source=%#x bytes=%u rc=%d transport_only=1",\n'
         '            cp_serial,syscall(178),id,cp_source,cp_bytes,result);\n'
         '        record("FULL_CP_CONTROL_RETURN ",line); *__errno_location()=saved_errno;\n'
         '    }'),
        ('    int result = real_rcv_msg_tmo(id, message, timeout);',
         '    int result = real_rcv_msg_tmo(id, message, timeout);\n'
         '    if (getenv("FULLSYSTEM_INPUT_OBSERVE") && id==0x5503e0 && !result && message && *message && real_msg_size && real_msg_size(*message)==32) {\n'
         '        const unsigned int *v=*message; char input[256];\n'
         '        snprintf(input,sizeof input,"tid=%ld queue=%#x message=%p code=%#x status=%d prev=%d repeat=%u from=%u inh=%u",\n'
         '                 syscall(178),id,*message,v[0],(int)v[2],(int)v[3],v[5],v[6],v[7]&255);\n'
         '        record("FULL_INPUT_RECEIVE ",input);\n'
         '    }'),
        ('    if (!version && message && real_msg_size) {',
         '    static unsigned int backup_log_sequence;\n'
         '    const char *backup_log_profile=getenv("FULLSYSTEM_BACKUP_LOG");\n'
         '    int sparse_backup=id==0x003e014d && backup_log_profile && !strcmp(backup_log_profile,"sampled");\n'
         '    unsigned int backup_log_n=sparse_backup?__atomic_add_fetch(&backup_log_sequence,1,__ATOMIC_RELAXED):0;\n'
         '    int backup_log_sample=!sparse_backup || backup_log_n<=8 || !(backup_log_n&(backup_log_n-1));\n'
         '    if (!version && message && real_msg_size && backup_log_sample) {'),
        ('            char line[72];','            char line[256];'),
        ('    if (result != 0 || trace_registration(id)) record("REG_SYNC ", text);',
         '    if (result != 0 || trace_registration(id)) record("REG_SYNC ", text);\n'
         '    if (id == 0x012282f6 || id == 0x012182ed) record("FULL_BUSPOWER_REGISTER ",text);'),
        ('record("REG_ASYNC ", text);',
         'record("REG_ASYNC ", text);\n'
         '    if (id == 0x012282f6 || id == 0x012182ed) record("FULL_BUSPOWER_REGISTER ",text);'),
        ('    int result = real_send_sync(id, message);',
         '    int result = real_send_sync(id, message);\n'
         '    if (sparse_backup && (backup_log_sample || result)) {\n'
         '        char sampled[200];\n'
         '        snprintf(sampled,sizeof sampled,"tid=%ld id=%#x request_index=%u sampled=%u original_transport=%d forwarded_once=1 message_unchanged=1",\n'
         '            syscall(178),id,backup_log_n,backup_log_sample,result);\n'
         '        record(result?"FULL_BACKUP_LOG_ERROR ":"FULL_BACKUP_LOG_SAMPLE ",sampled);\n'
         '    }\n'
         '    if (id == 0x012282f6) {\n'
         '        char result_text[128];\n'
         '        snprintf(result_text,sizeof result_text,"tid=%ld id=%#x original_transport=%d",syscall(178),id,result);\n'
         '        record("FULL_BUSPOWER_SYNC_RETURN ",result_text);\n    }'),
        ('int osal_free_msg(unsigned int id, void *message) {',
         'int osal_free_msg(unsigned int id, void *message) {\n'
         '    if (getenv("FULLSYSTEM_INPUT_OBSERVE") && id==0x5503e0 && message && real_msg_size && real_msg_size(message)==32) {\n'
         '        const unsigned int *v=message; char input[192];\n'
         '        snprintf(input,sizeof input,"tid=%ld queue=%#x message=%p code=%#x status=%d prev=%d",syscall(178),id,message,v[0],(int)v[2],(int)v[3]);\n'
         '        record("FULL_INPUT_FREE_ENTER ",input);\n'
         '    }\n'
         '    { int result;\n'
         '      if (full_dmm_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_dig_level_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_hdmi_pin_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_adf_connection_release(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_hdmi_connection_release(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_adf_audio_connection_release(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_adf_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_scalar_connection_release(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_infrabb_connection_release(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_scalar_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_infrabb_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_drawinfo_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_grm_pin_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_pin_connection_release(id,message,real_free_msg,record,&result)) {\n'
         '          if (!result) full_pin_format_persistent_log();\n'
         '          return result; } }\n'
         '    { int result;\n'
         '      if (full_pinmem_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_vef_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_hdmi_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_audio_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    { int result;\n'
         '      if (full_vdf_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'
         '    if (getenv("FULLSYSTEM_IMAGING_SERVICE")) {\n'
         '        int result;\n'
         '        if (full_imaging_release_reply(id,message,real_free_msg,record,&result)) return result;\n    }'),
        ('int osal_snd_msg(unsigned int id, void *message) {\n    if (!real_send_msg) __builtin_trap();',
         'int osal_snd_msg(unsigned int id, void *message) {\n    if (!real_send_msg) __builtin_trap();\n'
         '    full_file_media_before_send(id,real_dlsym,record);\n'
         '    if (id==0x9088076bu && getenv("FULLSYSTEM_GUI_MODELS") && real_msg_size)\n'
         '        return full_gui_models_dispatch(id,message,real_msg_size(message),real_free_msg,record);\n'
         '    if (id==0x92b4086fu && getenv("FULLSYSTEM_REMOTE_STATE") && real_msg_size && real_get_source)\n'
         '    {\n'
         '        unsigned int n=real_msg_size(message); char request[192];\n'
         '        snprintf(request,sizeof request,"tid=%ld source=%#x bytes=%u command=%#x caller=%p",syscall(178),real_get_source(message),n,n>=4?*(const unsigned int *)message:0,__builtin_return_address(0));\n'
         '        record("FULL_REMOTE_STATE_REQUEST ",request);\n'
         '        return full_remote_state_dispatch(id,message,n,real_get_source(message),real_free_msg,record);\n'
         '    }\n'
         # Observation only: the five CP-domain endpoints the AP sends to during boot. The kernel
         # drops them (no interchip sender), and the sending threads do not wait for a reply, so an
         # AP-side owner cannot unblock anything. Log them here to establish whether this route
         # even emits them; fall through so delivery semantics are unchanged.
         '    if (id==0x90280964u||id==0x92f00962u||id==0x92a007ecu||id==0x916c0738u||id==0x9101085cu) {\n'
         '        unsigned int n=real_msg_size?real_msg_size(message):0; char cp[224];\n'
         '        snprintf(cp,sizeof cp,"tid=%ld dest=%#x source=%#x bytes=%u w=%08x,%08x,%08x,%08x",syscall(178),id,real_get_source?real_get_source(message):0,n,\n'
         '                 (message&&n>=4)?((const unsigned int *)message)[0]:0,(message&&n>=8)?((const unsigned int *)message)[1]:0,\n'
         '                 (message&&n>=12)?((const unsigned int *)message)[2]:0,(message&&n>=16)?((const unsigned int *)message)[3]:0);\n'
         '        record("FULL_CP_TRACE ",cp);\n'
         '    }\n'
         '    if (message && real_msg_size && real_get_source && full_pin_request_visible(id,message,real_msg_size(message))) {\n'
         '        unsigned int n=real_msg_size(message),take=n<128?n:128;\n'
         '        char raw[257],line[480];\n'
         '        for (unsigned int i=0;i<take;i++) snprintf(raw+2*i,3,"%02x",((unsigned char *)message)[i]);\n'
         '        raw[2*take]=0;\n'
         '        snprintf(line,sizeof line,"tid=%ld destination=%#x source=%#x bytes=%u captured=%u raw=%s",syscall(178),id,real_get_source(message),n,take,raw);\n'
         '        record("FULL_PIN_REQUEST_OBSERVE ",line);\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_PIN_CONNECTION");\n'
         '        if (profile && !strcmp(profile,"control") && (id==0x905a0048U || id==0x90590818U)) {\n'
         '            if (pin_control_open_guest(1)!=1) { record("FULL_PIN_CONNECT_FAULT ","guest-control-backing-binding-failed");return -1021; }\n'
         '            struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '                real_send_msg,real_msg_size,real_get_source,record};\n'
         '            int result;\n'
         '            const char *format=getenv("FULLSYSTEM_PIN_FORMAT");\n'
         '            int mode=format && !strcmp(format,"cold")?2:1;\n'
         '            if (full_pin_connection_dispatch(id,message,&io,mode,&result)) return result;\n'
         '        }\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_DMM");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_dmm_dispatch(id,message,&io,profile && !strcmp(profile,"unit-size"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_DIG_LEVEL");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_dig_level_dispatch(id,message,&io,profile && !strcmp(profile,"virtual"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_ADF_CONNECTION");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_adf_connection_dispatch(id,message,&io,profile && !strcmp(profile,"control"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_HDMI_CONNECTION");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_hdmi_connection_dispatch(id,message,&io,profile && !strcmp(profile,"control"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_ADF_AUDIO_CONNECTION");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_adf_audio_connection_dispatch(id,message,&io,profile && !strcmp(profile,"control"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_SCALAR_CONNECTION");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_scalar_connection_dispatch(id,message,&io,profile && !strcmp(profile,"control"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_INFRABB_CONNECTION");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_infrabb_connection_dispatch(id,message,&io,profile && !strcmp(profile,"control"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_PINMEM_SERVICE");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_pinmem_dispatch(id,message,&io,profile && !strcmp(profile,"registry"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_SCALAR_SERVICE");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_scalar_dispatch(id,message,&io,profile && !strcmp(profile,"registry"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_INFRABB_SERVICE");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_infrabb_dispatch(id,message,&io,profile && !strcmp(profile,"registry"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_DRAWINFO_SERVICE");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_drawinfo_dispatch(id,message,&io,profile && !strcmp(profile,"registry"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_GRMPIN_SERVICE");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_grm_pin_dispatch(id,message,&io,profile && !strcmp(profile,"registry"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_ADF_SERVICE");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_adf_dispatch(id,message,&io,profile && !strcmp(profile,"registry"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_VEF_SERVICE");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_vef_dispatch(id,message,&io,profile && !strcmp(profile,"registry"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_HDMI_PIN_SERVICE");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_hdmi_pin_dispatch(id,message,&io,profile && !strcmp(profile,"registry"),&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_HDMI_SERVICE");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        int hdmi=profile && !strcmp(profile,"boot")?FULL_HDMI_BOOT:\n'
         '            profile && !strcmp(profile,"definition")?FULL_HDMI_DEFINITION:0;\n'
         '        if (full_hdmi_dispatch(id,message,&io,hdmi,&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_AUDIO_SERVICE");\n'
         '        const char *capabilities=getenv("FULLSYSTEM_AUDIO_CAPABILITIES");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        int audio=profile && !strcmp(profile,"boot")?FULL_AUDIO_BOOT:\n'
         '            profile && !strcmp(profile,"volume")?FULL_AUDIO_VOLUME:0;\n'
         '        int caps=capabilities && !strcmp(capabilities,"inputless")?FULL_AUDIO_CAPS_INPUTLESS:0;\n'
         '        if (full_audio_dispatch_capabilities(id,message,&io,audio,caps,&result)) return result;\n    }\n'
         '    {\n'
         '        const char *profile=getenv("FULLSYSTEM_VDF_SERVICE");\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_vdf_dispatch(id,message,&io,profile && !strcmp(profile,"timecode"),&result)) return result;\n    }\n'
         '    if (getenv("FULLSYSTEM_IMAGING_SERVICE")) {\n'
         '        struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if (full_imaging_dispatch(id,message,&io,&result)) return result;\n    }'),
        ('"    stp x29, x30, [sp, #-48]!\\n"\n'
         '"    mov x2, #0xaaaa\\n"\n'
         '"    movk x2, #0xaaab, lsl #16\\n"\n'
         '"    movk x2, #0xaaaa, lsl #32\\n"\n'
         '"    movk x2, #0xaaaa, lsl #48\\n"\n'
         '"    adrp x16, dep_wait_continue\\n"',
         '"    stp x29, x30, [sp, #-48]!\\n"\n'
         '"    mov x2, #-0x5555555555555556\\n"\n'
         '"    movk x2, #0xaaab\\n"\n'
         '"    mov x29, sp\\n"\n'
         '"    adrp x16, dep_wait_continue\\n"'),
        ('"    stp x29, x30, [sp, #-0x90]!\\n"\n'
         '"    mov x29, sp\\n"\n'
         '"    adrp x16, seq_run_continue\\n"\n'
         '"    ldr x16, [x16, #:lo12:seq_run_continue]\\n"\n'
         '"    br x16\\n"',
         '"    stp x29, x30, [sp, #-0x90]!\\n"\n'
         '"    mov x29, sp\\n"\n'
         '"    stp x19, x20, [sp, #0x10]\\n"\n'
         '"    adrp x16, seq_run_continue\\n"\n'
         '"    ldr x16, [x16, #:lo12:seq_run_continue]\\n"\n'
         '"    movz x20, #0x5638\\n"\n'
         '"    movk x20, #0x1bb, lsl #16\\n"\n'
         '"    add x20, x16, x20\\n"\n'
         '"    br x16\\n"'),
    ]
    for before,after in changes:
        if source.count(before)!=1:
            raise ValueError('Official observer source changed: ambiguous full-system hook')
        source=source.replace(before,after,1)
    source=source.replace('"FULL_INFRABB_",','"FULL_GRMPIN_", "FULL_DRAWINFO_", "FULL_INFRABB_",',1)
    source='#include "grm-pin-device.h"\n#include "drawinfo-device.h"\n#include "remote-state.h"\n'+source
    # Keep the new snapshot/format buffers off the universal free hot path.
    # This helper is reached only for an owned control reply after real free.
    source='#include "infrabb-device.h"\n#include "infrabb-connection.h"\n#include "gui-models.h"\n#include "hdmi-connection.h"\n#include "adf-audio-connection.h"\n#include "dmm-device.h"\n#include "dig-level-device.h"\n#include "hdmi-pin-device.h"\n#include "adf-connection.h"\n#include "adf-device.h"\n#include "scalar-device.h"\n#include "scalar-connection.h"\n#include "pin-request-observe.h"\nstatic void full_pin_format_persistent_log(void);\n'+source
    source+='''
static __attribute__((noinline)) void full_pin_format_persistent_log(void) {
    struct pin_connection_snapshot state; full_pin_connection_snapshot(&state);
    if (!state.format_consumed) return;
    struct pin_control_snapshot pool; pin_control_snapshot(&pool); char line[400];
    snprintf(line,sizeof line,"tid=%ld handle=%#x format_cpu_consumed=%u buffer_released=%u live=%u pin_index=%u ordinal=%u code=%u component=%u encoded_flags=%u width=%u height=%u camera_startup_verified=0",
        syscall(178),state.buffer_handle,state.format_consumed,state.buffer_released,pool.live,state.format_current.pin_index,state.format_current.ordinal,
        state.format_current.code,state.format_current.component,state.format_current.encoded_flags,state.format_current.width,state.format_current.height);
    record("FULL_PIN_FORMAT_PERSISTENT_READBACK ",line);
}
'''
    source=touch_scope["derive"](source,touch_receipt)
    output.mkdir(exist_ok=True)
    derived=output/'menu-observe.c'
    derived.write_text(source)
    # EBUSY (16) from the raster trylock is transient contention from another CPU
    # writer, not a missing resource. A single try made the consumer latch failure
    # and stop ACKing, so the fixture is derived with a bounded retry. Everything
    # else in the frozen snapshot stays byte-identical.
    osd_text=(menu/'headless-osd.c').read_text()
    include='#include "headless-osd.h"'
    if osd_text.count(include)!=1:raise ValueError('Ambiguous immutable OSD include anchor')
    osd_text=osd_text.replace(include,include+'\n#include "full-osd-snapshot.h"',1)
    persist='        ok = hosd_persist(path, snapshot, HOSD_BYTES) == 0;'
    if osd_text.count(persist)!=1:raise ValueError('Ambiguous immutable OSD lifecycle anchor')
    osd_text=osd_text.replace(persist,persist+'\n'
        '        /* Snapshot remains owned here. Diagnostics never change ok/ACK. */\n'
        '        int immutable_saved = ok ? full_osd_capture_owned(snapshot,HOSD_BYTES,o->log) : 0;',1)
    sampled='if (s->sequence <= 8 || !(s->sequence & (s->sequence - 1))) o->log("OSD_HEADLESS_PERSISTED ", text);'
    if osd_text.count(sampled)!=1:raise ValueError('Ambiguous immutable OSD identity record anchor')
    osd_text=osd_text.replace(sampled,
        'if (immutable_saved == FULL_OSD_COMMITTED || s->sequence <= 8 || !(s->sequence & (s->sequence - 1))) o->log("OSD_HEADLESS_PERSISTED ", text);',1)
    declare='extern int *__errno_location(void);'
    if osd_text.count(declare)!=1:raise ValueError('Ambiguous OSD errno declaration anchor')
    osd_text=osd_text.replace(declare,declare+'\nextern int usleep(unsigned int);',1)
    try_once='    if (ok) { phase = "raster-trylock"; status = api->try_raster(); raster = status == 0; ok = raster; }'
    if osd_text.count(try_once)!=1:raise ValueError('Ambiguous OSD raster trylock anchor')
    osd_text=osd_text.replace(try_once,
        '    if (ok) { phase = "raster-trylock";\n'
        '        /* Retry only EBUSY; any other status is a real failure. */\n'
        '        for (unsigned int attempt = 0; attempt < 200; ++attempt) {\n'
        '            status = api->try_raster();\n'
        '            if (status == 0 || status != 16) break;\n'
        '            usleep(2000);\n'
        '        }\n'
        '        raster = status == 0; ok = raster; }',1)
    # -1022 is OSAL "busy" (queue lock contention), not a missing endpoint: the
    # frozen snapshot only treats it as a timeout when no message was filled in,
    # so a busy receive that touched the pointer latched failure and stopped ACK.
    busy='    if (result == HOSD_TIMEOUT && !message && !s->pending) return 0;'
    if osd_text.count(busy)!=1:raise ValueError('Ambiguous OSD busy-receive anchor')
    osd_text=osd_text.replace(busy,
        '    /* Busy is transient contention: report no message this round and retry,\n'
        '     * releasing any handle the failed receive still handed back. */\n'
        '    if (result == HOSD_TIMEOUT) {\n'
        '        if (message) o->release(queue, message);\n'
        '        return 0;\n'
        '    }',1)
    pipeline=None
    if pipeline_api is not None:
        pipeline=pipeline_api['prepare'](menu,output,source,osd_text,profile=lcd_pipeline_profile)
        source=pipeline['sources']['menu-observe.c'].read_text()
        osd_text=pipeline['sources']['headless-osd.c'].read_text()
    ram_binding=None
    if lcd_ram_snapshot:
        ram_header=output/'headless-osd.h'
        ram_header.write_text(ram_api['path_header']((menu/'headless-osd.h').read_text()))
        ram_binding={'contract':ram_api['receipt'](),
                     'adapter_sha256':hashlib.sha256((here/'lcd-ram-snapshot.py').read_bytes()).hexdigest(),
                     'header_sha256':hashlib.sha256(ram_header.read_bytes()).hexdigest()}
    osd_derived=output/'headless-osd.c';osd_derived.write_text(osd_text)
    baseline=[osd_derived if name=='headless-osd.c' else
              pipeline['sources'][name] if pipeline is not None and name in pipeline['sources'] else menu/name for name in (
        'capid-service.c','sa-address-service.c','hdmi-format-service.c','dmm-service.c',
        'gpe-raster.c','gpe-sprite.c','sony-lz77.c','headless-osd.c')]
    if lcd_pipeline_profile=='latency-v3':
        baseline.append(pipeline['sources']['lcd-map-cache.c'])
    # Newer native snapshots have this owner; the frozen older snapshot does
    # not. Never fetch it from the concurrently edited official-route tree.
    if (menu/'infrabb-registry.c').is_file():
        baseline.append(menu/'infrabb-registry.c')
    libraries=[root/'lib'/name for name in
               ('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')]
    target=root/'simulation/menu-observe.so'
    subprocess.run(['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu',
        '-fuse-ld=lld','-nostdlib','-O2','-mno-outline-atomics','-shared','-fPIC','-DSYSTEM_SOUND_OWNER_LIBRARY',
        '-Wl,--no-undefined','-Wl,-soname,menu-observe.so',
        *([ram_api['COMPILE_DEFINE'],'-I',str(output)] if lcd_ram_snapshot else []),
        *(['-DHOSD_PATH="/dev/qemu-simulation/headless-osd-frame.bin"'] if persistent_claim else []),
        '-I',str(menu),'-I',str(here),
        *(['-I',str(touch_scope['MODEL_ROOT'])] if touch_receipt else []),
        str(derived),*([str(touch_scope['MODEL_ROOT']/name) for name in touch_receipt['model_sources'] if name.endswith('.c')] if touch_receipt else []),*[str(p) for p in baseline],str(here/'imaging-device.c'),str(here/'vdf-device.c'),str(here/'audio-device.c'),str(here/'hdmi-device.c'),
        str(here/'file-media-flush-hook.c'),str(here/'full-osd-snapshot.c'),str(here/'sound-table.c'),str(here/'system-sound-owner.c'),str(here/'audio-capabilities.c'),str(here/'vef-device.c'),
        str(here/'pin-registry-core.c'),str(here/'pinmem-device.c'),str(here/'scalar-device.c'),str(here/'scalar-connection.c'),str(here/'adf-device.c'),str(here/'adf-connection.c'),str(here/'hdmi-connection.c'),str(here/'adf-audio-connection.c'),str(here/'hdmi-pin-device.c'),str(here/'infrabb-connection.c'),str(here/'vef-bb-post.c'),str(here/'vef-bb-format.c'),
        str(here/'grm-pin-device.c'),str(here/'drawinfo-device.c'),str(here/'infrabb-device.c'),str(here/'dmm-device.c'),str(here/'dig-level-device.c'),str(here/'gui-models.c'),str(here/'remote-state.c'),
        str(here/'pin-buffer-owner.c'),str(here/'pin-buffer-guest.c'),str(here/'pin-buffer-wire.c'),str(here/'pin-connection.c'),str(here/'pin-format.c'),
        *[str(p) for p in libraries],'-o',str(target)],check=True)
    persistent_viewer_sha=None
    if persistent_claim:
        viewer=root/'simulation/ramfb-viewer'
        subprocess.run(['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu',
            '-fuse-ld=lld','-nostdlib','-O2','-mno-outline-atomics','-Wl,--no-undefined','-Wl,-e,_start',
            '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
            '-DHOSD_PATH="/dev/qemu-simulation/headless-osd-frame.bin"',
            '-I',str(menu),str(menu/'ramfb-viewer.c'),*[str(p) for p in libraries],'-o',str(viewer)],check=True)
        persistent_viewer_sha=hashlib.sha256(viewer.read_bytes()).hexdigest()
    reader=(menu/'menu-readmem.c').read_text()
    anchor='    if (argc >= 5) {'
    if reader.count(anchor)!=1:raise ValueError('Ambiguous absolute-follow reader adapter')
    reader=reader.replace(anchor,'    if (argc >= 5 && strcmp(argv[4], "-") != 0) {',1)
    reader_source=output/'menu-readmem.c';reader_source.write_text(reader)
    subprocess.run(['clang','--target=aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-O2',
        '-Wl,--no-undefined','-Wl,-e,_start','-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
        str(reader_source),*[str(p) for p in libraries],'-o',str(root/'simulation/menu-readmem')],check=True)
    inputs=[*baseline,*menu.glob('*.h')]
    if lcd_pipeline_profile=='latency-v3':
        inputs.append(pipeline['sources']['lcd-map-cache.h'])
    return {'baseline_sources':{'menu-observe.c':source_hash,**{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}},
            **({'usb_touch':touch_receipt} if touch_receipt is not None else {}),
            'observer_source_selection':'explicit-sha256-snapshot' if observer_source is not None else 'pinned-native-dependency',
            'observer_source_sha256':source_hash,
            'device_sources':{name:hashlib.sha256((here/name).read_bytes()).hexdigest()
                              for name in ('imaging-device.c','imaging-device.h','vdf-device.c','vdf-device.h','audio-device.c','audio-device.h',
                                           'file-media-flush-hook.c','file-media-flush-hook.h','full-osd-snapshot.c','full-osd-snapshot.h','guest-stat-compat.h',
                                           'sound-table.c','sound-table.h','system-sound-owner.c','system-sound-owner.h','hdmi-device.c','hdmi-device.h',
                                           'audio-capabilities.c','audio-capabilities.h','vef-device.c','vef-device.h',
                                           'pin-registry-core.c','pin-registry-core.h','pinmem-device.c','pinmem-device.h',
                                           'pin-buffer-owner.c','pin-buffer-owner.h','pin-buffer-guest.c','pin-buffer-wire.c','pin-buffer-wire.h',
                                           'pin-connection.c','pin-connection.h','pin-format.c','pin-format.h','scalar-device.c','scalar-device.h',
                                           'scalar-connection.c','scalar-connection.h','pin-request-observe.h','infrabb-connection.c','infrabb-connection.h','vef-bb-post.c','vef-bb-post.h','vef-bb-format.c','vef-bb-format.h','pin-buffer-owner.c','pin-buffer-owner.h','adf-device.c','adf-device.h',
                                           'pin-peer-connection.inc','adf-connection.c','adf-connection.h','hdmi-connection.c','hdmi-connection.h','adf-audio-connection.c','adf-audio-connection.h','hdmi-pin-device.c','hdmi-pin-device.h',
                                           'grm-pin-device.c','grm-pin-device.h','drawinfo-device.c','drawinfo-device.h','infrabb-device.c','infrabb-device.h','dmm-device.c','dmm-device.h','dig-level-device.c','dig-level-device.h','gui-models.c','gui-models.h','remote-state.c','remote-state.h')},
            'derived_source_sha256':hashlib.sha256(derived.read_bytes()).hexdigest(),
            'readmem_base_sha256':hashlib.sha256((menu/'menu-readmem.c').read_bytes()).hexdigest(),
            'readmem_derived_sha256':hashlib.sha256(reader_source.read_bytes()).hexdigest(),
            'headless_osd_base_sha256':hashlib.sha256((menu/'headless-osd.c').read_bytes()).hexdigest(),
            'headless_osd_derived_sha256':hashlib.sha256(osd_derived.read_bytes()).hexdigest(),
            'observer_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            **({'lcd_pipeline':pipeline['receipt']} if pipeline is not None else {}),
            **({'lcd_ram_snapshot':ram_binding} if ram_binding is not None else {}),
            **({'persistent_display_claim':{'path':'/dev/qemu-simulation/headless-osd.claim',
                'snapshot_path':'/dev/qemu-simulation/headless-osd-frame.bin','viewer_sha256':persistent_viewer_sha,
                'scope':'per-boot guest devtmpfs; exclusive queue/module and full snapshot/ACK checks unchanged; old disk artifacts preserved'}} if persistent_claim else {})}
