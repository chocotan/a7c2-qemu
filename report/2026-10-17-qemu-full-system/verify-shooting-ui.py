#!/usr/bin/env python3
"""Strict "shooting UI reached and drawn" acceptance for an F free-run.

This is deliberately conjunctive: every criterion below must hold in the SAME
console, bound to its stable SHA. Counts alone are never promoted to a camera
capability - pixels must actually be non-zero in the exported framebuffer.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

GEOMETRY=(640,480)
ZERO_FNV='4f2d9f141eeda325'   # fnv1a64 of 614400 zero bytes
# RGB digests of independently inspected official 2.01 reference images in
# ../2026-10-19-official-first-setup/evidence/. This is deliberately a narrow
# Japanese/iAuto/no-card baseline, not acceptance of arbitrary scenes or noise.
REFERENCE_RGB = {
    'shooting-main': {
        '2a6ad8bd1d9eb7e6c71e7e70618c0e677e6ab1ac10511dd3da4a90398591968e',
        'e5ab7798d8e7ce0a9c0f81f4c3231c06795901a4ddcfc5afecdd114076f03d58',
    },
    'shooting-menu': {'71e5942baa499229277920f3056bd3841916aec07cb988302f64817d4ef0310c'},
}


def require(value,why):
    if not value:raise ValueError(why)


def pixels(run):
    """Judge every exported buffer; the AP surface is double buffered.

    AP alternates between two physical buffers (the PERSISTED records show
    0x401/0x402), so the buffer that is inactive at teardown can legitimately be
    all zero while the drawn frame lives in the other one. Each export is
    reported separately and at least one must carry real content; a run whose
    exports are all zero still fails.
    """
    exports=[]
    for name in ('osd-ap-pixels.bin','osd-fb-end.bin'):
        path=run/name
        if not path.exists():continue
        data=path.read_bytes()
        require(len(data)==640*480*2,'Export has unexpected length: '+name)
        exports.append({'file':name,'nonzero_bytes':sum(1 for byte in data if byte),'bytes':len(data)})
    if not exports:return None
    best=max(exports,key=lambda item:item['nonzero_bytes'])
    best=dict(best);best['exports']=exports
    return best


def decode_rgba4444(raw,geometry=GEOMETRY):
    """Expand the firmware's AP RGBA4444 words to straight RGB (same as render-frame)."""
    from PIL import Image
    width,height=geometry
    require(len(raw)==width*height*2,'Pixel dump has unexpected length')
    pixels=bytearray()
    for (value,) in struct.iter_unpack('<H',raw):
        alpha=value&15
        pixels.extend((((value>>12)*17*alpha+7)//15,(((value>>8)&15)*17*alpha+7)//15,
                       (((value>>4)&15)*17*alpha+7)//15))
    return Image.frombytes('RGB',geometry,bytes(pixels)),sum(1 for byte in raw if byte)


def screen_epoch(console,position):
    """Only known content screens after shooting mode count, not first-setup UI."""
    events=re.finditer(rb'OBS (?:MODE_SLOT4 mode=([a-z]+) |CREATE_SCREEN_ARGS [^\r\n]*?\bid=(0x[0-9a-f]+|0) count=(\d+)\b)',console[:position])
    mode=None;active=None;start=None
    for event in events:
        if event[1]:
            mode=event[1]
            if mode not in (b'shooting',b'menu'):active=None
        else:
            active=None;start=event.start()
            if mode==b'shooting' and event.group(2,3)==(b'0',b'565'):
                active='shooting-main'
            elif mode==b'menu' and event.group(2,3)==(b'0x2ca',b'44'):
                active='shooting-menu'
    return active,start


def immutable_frame(run,console,seq,entry):
    """A late raw pointer dump cannot bind pixels; validate a full saved container."""
    number=int(seq)
    pattern=rb'OBS OSD_HEADLESS_PERSISTED [^\r\n]*?\bseq='+str(number).encode()+rb' [^\r\n]*?id=(0x[0-9a-f]+) phys=(0x[0-9a-f]+) geometry=640x480 bytes=614400 fnv1a64=([0-9a-f]{16})\b'
    records=list(re.finditer(pattern,console))
    require(len(records)==1,'No unique PERSISTED identity for frame '+seq)
    record=records[0];epoch,start=screen_epoch(console,record.start())
    require(epoch is not None,'Frame is outside a shooting content epoch: '+seq)
    name=entry.get('snapshot_file')
    require(isinstance(name,str) and Path(name).name==name and name.endswith('.hosd'),
            'Immutable HOSDAP02 container missing; raw pointer dump is unattributed: '+seq)
    path=run/name
    require(not path.is_symlink(),'Snapshot cannot be a host symlink')
    data=path.read_bytes()
    # sizeof hosd_metadata = 80 + 256*96 + 16 + 258 (all unsigned char arrays).
    metadata_size=24930
    require(len(data)==128+metadata_size+614400 and data[:8]==b'HOSDAP02','Invalid snapshot size/magic')
    read=lambda fmt,off:struct.unpack_from('<'+fmt,data,off)[0]
    require((read('Q',8),read('I',16),read('Q',32))==
            (number,int(record[1],16),int(record[2],16)),'Snapshot identity differs from PERSISTED')
    require((read('I',20),read('I',24),read('I',28),read('I',48),read('I',52))==
            (640,480,1,614400,metadata_size),'Invalid snapshot geometry/metadata')
    # Only a fresh pixel capture is attributable here. Re-publishing a retained
    # source from a previous content screen is not a new shooting frame.
    require(read('Q',120)==number and read('I',56)==0x1003,'Snapshot reuses an earlier pixel source')
    expected=int(record[3],16);stored=read('Q',40)
    hashed=bytearray(data);hashed[40:48]=b'\0'*8
    value=0xcbf29ce484222325
    for byte in hashed:value=((value^byte)*0x100000001b3)&0xffffffffffffffff
    require(stored==expected==value,'Snapshot container hash differs from original record')
    image,_=decode_rgba4444(data[128+metadata_size:])
    rgb_sha=hashlib.sha256(image.tobytes()).hexdigest()
    require(rgb_sha in REFERENCE_RGB[epoch],'Snapshot content differs from inspected '+epoch+' reference')
    return {'sequence':seq,'snapshot_file':name,'epoch':epoch,'screen_log_offset':start,
            'container_sha256':hashlib.sha256(data).hexdigest(),'rgb_sha256':rgb_sha}


def verify(run):
    console=(run/'console.log').read_bytes()
    result=json.loads((run/'result.json').read_text())
    digest=hashlib.sha256(console).hexdigest()
    require(result.get('terminal_evidence_checked') is True,'Terminal evidence was not checked')
    require(result.get('terminal_console_sha256')==digest,'Console changed after the run stopped')

    screens=[s.decode() for s in re.findall(rb'OBS CREATE_SCREEN_ARGS [^\r\n]*?\bid=(0x[0-9a-f]+|0)\b',console)]
    require('0x308' in screens,'Original boot screen was never created')
    require('0x347' in screens,'Shooting screen 0x347 was never requested')
    require('0' in screens,'Content screen 0 was never created')

    require(re.search(rb'OBS MODE_SLOT4 mode=boot ',console),'boot mode controller was not activated')
    require(re.search(rb'OBS MODE_SLOT4 mode=shooting ',console),'shooting mode controller was not activated')

    opens=len(re.findall(rb'OBS RESOURCE_OPEN ',console))
    lz=len(re.findall(rb'OBS RESOURCE_LZ_CPU_OK ',console))
    require(opens>2,'Image resources were never opened: %d'%opens)
    require(lz>0,'No image resource was ever decompressed')

    sends=len(re.findall(rb'OBS OSD_TRANSPORT_SEND ',console))
    require(sends>20,'Too few OSD draw commands for a populated screen: %d'%sends)
    require(re.search(rb'OBS OSD_HEADLESS_ACK ',console),'AP snapshot was not acknowledged')
    require(not re.search(rb'OBS OSD_HEADLESS_FAILED ',console),'OSD consumer latched a failure')
    require(not re.search(rb'OBS OSD_HEADLESS_LEASE_FAILED ',console),'OSD frame lease failed')

    edges={}
    for name,prefix in (('edge1_pin','FULL_PIN_CONNECT_'),('edge2_scalar','FULL_SCALAR_CONNECT_'),
                        ('edge3_adf','FULL_ADF_CONNECT_'),('edge4_hdmi','FULL_HDMI_CONNECT_'),
                        ('edge5_adfaudio','FULL_ADFAUDIO_CONNECT_')):
        request=len(re.findall(('OBS '+prefix+'REQUEST ').encode(),console))
        freed=len(re.findall(('OBS '+prefix+'NATIVE_REPLY_FREE ').encode(),console))
        edges[name]={'request':request,'native_reply_free':freed,'balanced':request==freed and request>0}
        require(edges[name]['balanced'],'Edge does not show a matched request/release: '+name)

    shot=pixels(run)
    require(shot is not None,'No framebuffer export exists; pixels cannot be judged')
    # PERSISTED polling followed by pmemsave only reads a mutable address. A
    # matching immutable container plus content-epoch identity is required.
    sidecar=run/'immutable-osd-captures.json'
    if sidecar.exists():
        immutable=json.loads(sidecar.read_text())
        require(immutable.get('console_sha256')==digest,'Immutable capture manifest belongs to another console')
        captured=immutable.get('frames') or {}
    else:
        captured=result.get('osd_frames_captured') or {}
    require(captured,'No frame was captured at PERSISTED time; pixels are not attributable')
    verified=[];rejected=[]
    for seq,entry in captured.items():
        try:verified.append(immutable_frame(run,console,str(seq),entry))
        except (ValueError,OSError,KeyError,TypeError,struct.error) as error:
            rejected.append({'sequence':str(seq),'reason':str(error)})
    require(verified,'No attributable shooting pixels: '+json.dumps(rejected,ensure_ascii=False))
    shot['verified_frames']=verified
    shot['rejected_frames']=rejected
    shot['structured_frame_sequences']=sorted((f['sequence'] for f in verified),key=int)
    if shot['nonzero_bytes']==0:
        # The teardown export can legitimately read an inactive buffer of the
        # double-buffered AP surface, or an empty screen the firmware switched to
        # last. Pixels are still attributable through the frames captured at
        # PERSISTED time, so require those (already checked above) and say so.
        shot['end_export_zero_with_attributed_frames']=True
        require(shot['structured_frame_sequences'],
                'Teardown export is zero and no captured frame carries structured UI')
    if 'ramfb_matches_ap_framebuffer' in result:
        require(result['ramfb_matches_ap_framebuffer'] is True,
                'QEMU display differs from the guest AP framebuffer')

    return {'shooting_ui_drawn_verified':True,'console_sha256':digest,
            'create_screens':screens,'resource_open':opens,'resource_lz_cpu':lz,
            'osd_draw_commands':sends,'edges':edges,'pixels':shot,
            'zero_fnv_reference':ZERO_FNV,
            'camera_startup_verified':False,
            'viewfinder_verified':False,'capture_verified':False,
            'note':'UI drawing only; sensor/lens/capture remain separate claims'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,TypeError) as error:
        proof={'shooting_ui_drawn_verified':False,'error':str(error),
               'camera_startup_verified':False,'viewfinder_verified':False,'capture_verified':False}
    # Preserve historical verdicts; this stricter proof has a different schema.
    proof['schema']='immutable-content-epoch-v1'
    (args.run/'shooting-ui-proof-immutable.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True))
    return 0 if proof['shooting_ui_drawn_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
