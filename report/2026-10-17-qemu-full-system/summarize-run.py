#!/usr/bin/env python3
"""One-page evidence summary for an F free-run console.

Reads only the run directory. It never promotes a component to a camera
capability: pixels, viewfinder and capture stay explicit separate flags.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

CHECKS=(
    ('boot_sentinel', rb'OBS CREATE_SCREEN_SENTINEL '),
    ('osd_persisted', rb'OBS OSD_HEADLESS_PERSISTED '),
    ('osd_ack', rb'OBS OSD_HEADLESS_ACK '),
    ('osd_failed', rb'OBS OSD_HEADLESS_FAILED '),
    ('osd_lease_failed', rb'OBS OSD_HEADLESS_LEASE_FAILED '),
    ('imaging_request', rb'OBS FULL_IMAGING_REQUEST '),
    ('audio_request', rb'OBS FULL_AUDIO_REQUEST '),
    ('audio_applied_25', rb'applied=25 '),
    ('sound_path_32a', rb'FULL_AUDIO_SOUND_PATH '),
    ('panel_reverse_119', rb'FULL_AUDIO_PANEL_REVERSE '),
    ('beep_0347', rb'FULL_AUDIO_BEEP_VOLUME '),
    ('dig_level_request', rb'OBS FULL_DIG_LEVEL_REQUEST '),
    ('dmm_request', rb'OBS FULL_DMM_REQUEST '),
    ('hdmi_pin_commit', rb'OBS FULL_HDMIPIN_COMMIT '),
    ('edge1_pin', rb'OBS FULL_PIN_CONNECT_'),
    ('edge2_scalar', rb'OBS FULL_SCALAR_CONNECT_'),
    ('edge3_adf', rb'OBS FULL_ADF_CONNECT_'),
    ('edge4_hdmi', rb'OBS FULL_HDMI_CONNECT_'),
    ('edge5_adfaudio', rb'OBS FULL_ADFAUDIO_CONNECT_'),
    ('resource_lz_cpu', rb'OBS RESOURCE_LZ_CPU_OK '),
    ('resource_open', rb'OBS RESOURCE_OPEN '),
    ('view_content_item', rb'OBS VIEW_CONTENT_ITEM '),
    ('skip_snd_86f', rb'Skip snd to 0x86f'),
)


def summary(run):
    console=(run/'console.log').read_bytes()
    identity=json.loads((run/'inputs.json').read_text()) if (run/'inputs.json').exists() else {}
    result=json.loads((run/'result.json').read_text()) if (run/'result.json').exists() else {}
    counts={name:len(re.findall(pattern,console)) for name,pattern in CHECKS}
    screens=[s.decode() for s in re.findall(rb'OBS CREATE_SCREEN_ARGS [^\r\n]*?\bid=(0x[0-9a-f]+|0)\b',console)]
    persisted=re.findall(rb'OBS OSD_HEADLESS_PERSISTED [^\r\n]*?fnv1a64=([0-9a-f]{16})',console)
    unanswered={}
    for family in ('PIN','SCALAR','ADF','HDMI','ADFAUDIO'):
        base='FULL_'+family+'_CONNECT_' if family not in ('PIN','SCALAR','ADF') else {
            'PIN':'FULL_PIN_CONNECT_','SCALAR':'FULL_SCALAR_CONNECT_','ADF':'FULL_ADF_CONNECT_'}[family]
        request=len(re.findall(('OBS '+base+'REQUEST ').encode(),console))
        freed=len(re.findall(('OBS '+base+'NATIVE_REPLY_FREE ').encode(),console))
        if request or freed:unanswered[family]={'request':request,'native_reply_free':freed,
                                                'balanced':request==freed}
    skip={}
    for target in re.findall(rb'Skip snd to (0x[0-9a-f]+)',console):
        key=target.decode();skip[key]=skip.get(key,0)+1
    digest=hashlib.sha256(console).hexdigest()
    return {
        'run':run.name,'console_sha256':digest,'console_bytes':len(console),
        'state':result.get('state'),'terminal_matches_result':
            result.get('terminal_console_sha256') in (None,digest),
        'create_screens':screens,
        'shooting_screen_0x347':'0x347' in screens,
        'content_screen_seen':'0' in screens,
        'checks':counts,
        'osd_pixel_fnv1a64':persisted[-1].decode() if persisted else None,
        'all_zero_fnv1a64_reference':'4f2d9f141eeda325',
        'edge_reply_balance':unanswered,
        'skip_snd_targets_top':dict(sorted(skip.items(),key=lambda kv:-kv[1])[:8]),
        'osd_consumer_healthy':counts['osd_failed']==0 and counts['osd_lease_failed']==0,
        # Rasterisation gate: a screen can exist while no image resource was ever
        # opened, in which case nothing is drawn and 0x347 is never requested.
        'reached_rasterisation':counts['resource_open']>2 and counts['resource_lz_cpu']>0,
        'visible_pixels_verified':False,'viewfinder_verified':False,
        'capture_verified':False,'camera_startup_verified':False,
        'note':'component counts only; pixels/camera claims stay false',
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    value=summary(args.run)
    (args.run/'evidence-summary.json').write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps(value,sort_keys=True,indent=1))


if __name__=='__main__':raise SystemExit(main())
