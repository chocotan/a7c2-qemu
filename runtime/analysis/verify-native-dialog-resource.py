"""Correlate the actual dialog module, original model input and displayed text."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from PIL import Image


def require(ok,why):
    if not ok:raise ValueError(why)


def verify(run):
    m=json.loads((run/'runtime-manifest.json').read_text());s=json.loads((run/'summary.json').read_text())
    console=(run/'console.log').read_bytes();text=console.decode(errors='replace')
    require(s.get('probe_collected') is True and Path(s['run']).resolve()==run.resolve(),'Completed run identity missing')
    require(m.get('input_key_mode')=='' and not m.get('infra_key_injection','') and
            m.get('dmm_unit_config_service') is True,'No-key diagnostic profile missing')
    require('Entering exception monitor.' not in text and 'OBS KEY_INJECT' not in text,'Guest exception or injected key')
    require(m['selected_initramfs_verified_files']['simulation/menu-observe.so']==m['compiled_observer']['observer_sha256'],
            'Actual observer image identity differs')
    require(m.get('original_libraries_unchanged') is True and
            m['selected_initramfs_verified_files'].get('usr/lib/appFw.so')=='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
            'Original appFw identity differs')
    b=re.search(r'OBSERVER_READY .*?base=(0x[0-9a-f]+)',text)
    require(b,'Original appFw mapping missing');base=int(b[1],16)
    rows=[(i,l,dict(re.findall(r'(\w+)=([^\s]+)',l))) for i,l in enumerate(text.splitlines())]
    capture=next(r for r in rows if r[1].startswith('OBS RESOURCE_DIALOG_GETTER_CAPTURED '))
    value=next(r for r in rows if r[0]>capture[0] and r[1].startswith('OBS RESOURCE_DIALOG_VALUE ') and
               r[2]['presenter']==capture[2]['presenter'] and r[2]['call']==capture[2]['call'])
    c,v=capture[2],value[2]
    require(c['screen']==v['screen']=='0x322' and c['index_known']=='1' and int(c['module_index'],0)==0x262,
            'Actual dialog module differs')
    require(int(c['getter_vtable'],0)-base==0x59128c0 and int(c['method'],0)-base==0x1882dc8 and
            int(c['method_appFw_offset'],0)==0x1882dc8,'Original caution module interface differs')
    require(int(v['text_resource'],0)==0x0200a73b and v['source']=='original-view-string-param',
            'Actual rendered text resource differs')
    block=re.search(r'^DIALOG_MODULE_262_INPUT_BEGIN\r?\n(.*?)^DIALOG_MODULE_262_INPUT_RC=(\d+)\r?$',text,re.M|re.S)
    require(block and block[2]=='0','Original predicate model readback missing')
    words=re.findall(r'^([0-9a-f]{16}):((?: [0-9a-f]{2}){4})\r?$',block[1],re.M)
    require(len(words)==1 and int(words[0][0],16)==base+0x7e80dd0 and
            int.from_bytes(bytes.fromhex(words[0][1]),'little')==2,'Original predicate model value/address differs')
    secondary=re.search(r'^DIALOG_MODULE_233_INPUT_BEGIN\r?\n(.*?)^DIALOG_MODULE_233_INPUT_RC=(\d+)\r?$',text,re.M|re.S)
    require(secondary and secondary[2]=='0','Original media-error model readback missing')
    words2=re.findall(r'^([0-9a-f]{16}):((?: [0-9a-f]{2}){4})\r?$',secondary[1],re.M)
    require(len(words2)==1 and int(words2[0][0],16)==base+0x7e80f50 and
            int.from_bytes(bytes.fromhex(words2[0][1]),'little')==1,'Original secondary predicate value/address differs')
    rgba=Image.open(run/'headless-osd-pixels-rgba4444-software.png').convert('RGBA')
    require(rgba.size==(640,480),'Frame geometry differs')
    digest=hashlib.sha256(rgba.tobytes()).hexdigest()
    require(digest=='3496a870d47c6019bd6f4068d9d518a6bbaab6878555ef820c04b278055bddf6',
            'Captured frame differs from the inspected error dialog')
    return {'run':run.name,'actual_dialog_resource_chain_verified':True,'screen':'0x322','module_index':'0x262',
            'text_resource':'0x0200a73b','getter_method_elf_va':'0x1882dc8','model_getter_elf_va':'0x28787f0',
            'model_data_elf_va':'0x7e80dd0','model_value':2,'model_name_and_natural_writer_verified':False,
            'model_name':'media_mount_state_slot1','model_id':'0xed1','secondary_model_name':'media_error_slot1',
            'secondary_model_id':'0xedd','secondary_model_value':1,'model_names_static_verified':True,
            'natural_writer_static_elf_va':'0x337ac38','runtime_mount_result_verified':False,'atomic_predicate_snapshot':False,
            'language_option_flags_used_as_storage_evidence':False,'filesystem_or_mount_error_proven':False,
            'console_sha256':hashlib.sha256(console).hexdigest(),'rgba_sha256':digest,
            'camera_startup_verified':False,'shooting_main_screen_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,StopIteration,TypeError) as error:
        proof={'actual_dialog_resource_chain_verified':False,'error':str(error) or type(error).__name__,
               'filesystem_or_mount_error_proven':False,'camera_startup_verified':False}
    (args.run/'dialog-resource-chain-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['actual_dialog_resource_chain_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
