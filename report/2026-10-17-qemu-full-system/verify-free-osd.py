#!/usr/bin/env python3
"""Verify a free-running F observation advanced past the boot screen.

This reads only F's own run directory. It does not import DS results, does not
accept a constructed layout image as firmware pixels, and never claims a main
screen, viewfinder or capture without the original calls that produce them.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

# Screen ids observed in original firmware logs for this boot path.
BOOT_SCREEN='0x308'
SHOOTING_SCREEN='0x347'
TRANSITION_SCREEN='0x343'
CONTENT_SCREEN='0'


def screens(console):
    return [v.decode() for v in re.findall(
        rb'OBS CREATE_SCREEN_ARGS [^\r\n]*\bid=(0x[0-9a-f]+|0)\b',console)]


def verify(run):
    console=(run/'console.log').read_bytes()
    result=json.loads((run/'result.json').read_text())
    identity=json.loads((run/'inputs.json').read_text())
    experiment=identity['experiment']
    digest=hashlib.sha256(console).hexdigest()
    if result.get('terminal_evidence_checked') is not True or result.get('terminal_console_sha256')!=digest:
        raise ValueError('Run did not stop with a checked, stable console')
    forced=[name for name in ('until_vdf_request','until_evf_subscription','until_pin_request',
            'until_pin_peer_request','until_pin_format_block','until_pin_format_consumed',
            'until_scalar_get','until_scalar_connection','until_adf_get','until_adf_connection',
            'until_hdmi_pin_get') if experiment.get(name)]
    if forced:raise ValueError('Free-run criterion violated; --until-* was enabled: '+','.join(forced))
    order=screens(console)
    if BOOT_SCREEN not in order:raise ValueError('Original boot screen was never created')
    passed_shooting=SHOOTING_SCREEN in order
    shooting_index=order.index(SHOOTING_SCREEN) if passed_shooting else -1
    later=[s for s in order[shooting_index+1:]] if passed_shooting else []
    commands=len(re.findall(rb'OBS OSD_TRANSPORT_SEND ',console))
    replies=re.findall(rb'OBS OSD_TRANSPORT_RECEIVE [^\r\n]*endpoint=0x8288076c source=0x8280074d bytes=8 shown=8 payload=(0360[0-9a-f]{12})',console)
    forced_apply=[marker for marker in (b'MENU_FORCE_SET',b'MENU_FORCE_IN_FACTORY',b'FACTORY_HOOK')
                  if re.search(rb'OBS OBSERVER_READY [^\r\n]*'+marker+rb'=(?!\(unset\))',console)]
    return {'console_sha256':digest,'state':result.get('state'),
            'create_screens':order,'boot_screen_created':True,
            'shooting_screen_requested':passed_shooting,
            'screens_after_shooting':later,
            'transition_screen_seen':TRANSITION_SCREEN in later,
            'content_screen_seen':CONTENT_SCREEN in later,
            'osd_command_count':commands,'osd_original_6003_receives':len(replies),
            'forced_apply_markers':[m.decode() for m in forced_apply],
            'camera_startup_verified':False,'visible_pixels_verified':False,
            'viewfinder_verified':False,'capture_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,TypeError) as error:
        proof={'boot_screen_created':False,'shooting_screen_requested':False,'error':str(error),
               'camera_startup_verified':False,'visible_pixels_verified':False}
    (args.run/'free-osd-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof.get('boot_screen_created') else 1


if __name__=='__main__':raise SystemExit(main())
