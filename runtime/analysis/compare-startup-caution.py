"""Compare identical-image boot observations with and without automatic MENU."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def require(ok,why):
    if not ok:raise ValueError(why)


def compare(baseline,control):
    b=json.loads((baseline/'runtime-manifest.json').read_text())
    c=json.loads((control/'runtime-manifest.json').read_text())
    sb=json.loads((baseline/'summary.json').read_text())
    sc=json.loads((control/'summary.json').read_text())
    require(sb.get('probe_collected') is True and sc.get('probe_collected') is True,'Both captures must complete')
    require(Path(sb['run']).resolve()==baseline.resolve() and Path(sc['run']).resolve()==control.resolve(),'Run identity differs')
    require(b['input_key_mode']=='pressrelease' and c['input_key_mode']=='','Expected only automatic MENU removal')
    require(not b.get('infra_key_injection','') and not c.get('infra_key_injection',''),'Additional InfraInput injection invalidates the comparison')
    require(b['probe_args']==c['probe_args'],'Guest launch options differ')
    require(b['files'][sb['input_image']]==c['files'][sc['input_image']],'Selected initramfs bytes differ')
    require(b['compiled_observer']['observer_sha256']==c['compiled_observer']['observer_sha256'],'Compiled observer differs')
    require(b['selected_initramfs_verified_files']==c['selected_initramfs_verified_files'],'Selected guest identity set differs')
    keys=('boot_type','settle_seconds','vdf_config_service','hdmi_boot_config_service','audio_boot_config_service',
          'audio_capabilities_profile','system_sound_owner','digital_level_profile','panel_reverse_profile',
          'dmm_unit_config_service','pin_registry_service','pin_control_memory','pin_buffer_selftest',
          'pin_connection_mode','trace_mutex')
    require(all(b.get(k)==c.get(k) for k in keys),'Recorded boot profile differs beyond MENU injection')
    first=(baseline/'console.log').read_bytes();second=(control/'console.log').read_bytes()
    require(b'Entering exception monitor.' not in first+second,'Guest exception invalidates boot comparison')
    require(b'OBS KEY_INJECT MENU ON sent through App::input_infra_callback' in first and
            b'OBS KEY_INJECT' not in second,'Automatic key evidence differs')
    require(re.findall(rb'POWER_ON_RECORD_OK [^\r\n]+',first)==re.findall(rb'POWER_ON_RECORD_OK [^\r\n]+',second),
            'Actual power-on record differs')
    launch=rb"/usr/bin/bootin\.elf 'target=qemu ' dmode=3"
    require(re.search(launch,first) and re.search(launch,second),'Actual boot launch command differs')
    from PIL import Image
    p=Image.open(baseline/'headless-osd-pixels-rgba4444-software.png').convert('RGBA')
    q=Image.open(control/'headless-osd-pixels-rgba4444-software.png').convert('RGBA')
    require(p.size==q.size==(640,480),'Capture geometry differs')
    require(p.getextrema()!=((0,0),)*4 and q.getextrema()!=((0,0),)*4,'Transparent frame is not an error-page comparison')
    equal=p.tobytes()==q.tobytes()
    caution={}
    text=second.decode(errors='replace')
    for name in ('CAUTION_GROUP','CAUTION_SELECTED_ID','CAUTION_SELECTOR','CAUTION_B1C_INPUT','CAUTION_B1D_INPUT'):
        block=re.search(r'^'+name+r'_BEGIN\r?\n(.*?)^'+name+r'_RC=(\d+)\r?$',text,re.M|re.S)
        require(block and block[2]=='0',name+' readback missing')
        rows=re.findall(r'^[0-9a-f]{16}:((?: [0-9a-f]{2}){4})\r?$',block[1],re.M)
        require(len(rows)==1,name+' readback ambiguous')
        caution[name]=int.from_bytes(bytes.fromhex(rows[0]),'little')
    return {'baseline':baseline.name,'control':control.name,'identical_guest_image_and_recorded_profile':True,
            'automatic_menu_removed':True,'same_visible_rgba_frame':equal,'control_caution_models':caution,
            'startup_list_semantics':'language availability, not storage-error predicates',
            'baseline_console_sha256':hashlib.sha256(first).hexdigest(),'control_console_sha256':hashlib.sha256(second).hexdigest(),
            'control_rgba_sha256':hashlib.sha256(q.tobytes()).hexdigest(),
            'sd_or_mount_failure_proven':False,'boot_record_correctness_proven':False,'shooting_main_screen_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('baseline',type=Path);parser.add_argument('control',type=Path)
    args=parser.parse_args()
    try:proof=compare(args.baseline,args.control)
    except (OSError,ValueError,KeyError,TypeError) as error:
        proof={'identical_guest_image_and_recorded_profile':False,'error':str(error) or type(error).__name__,
               'sd_or_mount_failure_proven':False,'shooting_main_screen_verified':False}
    (args.control/'startup-menu-comparison-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['identical_guest_image_and_recorded_profile'] else 1


if __name__=='__main__':raise SystemExit(main())
