"""Verify the observed cold 032a route/control transaction and original waiter."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import struct

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'device-models/verify-system-sound-config.py'))


def verify(run):
    sound = API['verify'](run,native=True)
    console = (run/'console.log').read_bytes()
    lines,_ = API['observer_lines'](console,deduplicate=False)
    records = [(i,l,dict(re.findall(r'(\w+)=([^\s]+)',l))) for i,l in enumerate(lines)]
    request = next(r for r in records if r[1].startswith('OBS FULL_AUDIO_REQUEST ') and r[2]['command']=='0x32a')
    API['require'](bytes.fromhex(request[2]['raw'])==bytes.fromhex('0d202a030a0001800700'),
                   'Observed cold path request differs')
    _,reply,commit = API['received'](records,request)
    fields = {'masked_path':7,'previous_path':0,'cached_path':7,'path_readback':7,
              'control_op':0x127,'control_argument':0,'control_consumed':1,
              'register_before':0,'register_after':1,'register_readback':1,
              'request_active':0,'deferred_callback':0,'applied':1}
    API['require'](all(int(commit[k],0)==v for k,v in fields.items()),'Actual route/control readback differs')
    API['require'](len(reply)==12 and struct.unpack_from('<I',reply,8)[0]==0x580000,
                   'Route completion domain differs')
    return {'run':run.name,'system_sound_path_verified':True,'scope':'cold-idle-route-control',
            'caller_tid':int(request[2]['tid']),'route':7,'control_op':'0x127','control_argument':0,
            'virtual_register_bit0':1,'source_memory_verified':sound['system_sound_memory_verified'],
            'console_sha256':hashlib.sha256(console).hexdigest(),'hardware_mmio_executed':False,
            'active_request_deferred_callback_verified':False,'audio_output_verified':False,
            'camera_startup_verified':False,'pixels_consumed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path)
    args=parser.parse_args()
    try:
        proof=verify(args.run)
    except (OSError,ValueError,KeyError,StopIteration,TypeError) as error:
        proof={'run':args.run.name,'system_sound_path_verified':False,
               'error':str(error) or type(error).__name__,'audio_output_verified':False,
               'camera_startup_verified':False,'pixels_consumed':False}
    (args.run/'audio-path-native-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True))
    return 0 if proof['system_sound_path_verified'] else 1


if __name__=='__main__':
    raise SystemExit(main())
