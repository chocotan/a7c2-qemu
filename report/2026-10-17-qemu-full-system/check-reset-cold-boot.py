#!/usr/bin/env python3
"""Boot an isolated copy of a real UI-reset workspace through the normal launcher.

Capture the original shooting screen for separate human value review. No setting
bytes or first-setup flags are changed; navigation uses the existing explicit map.
"""
import argparse
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile
import time

HERE=Path(__file__).resolve().parent
UI=runpy.run_path(str(HERE/'check-config-value-roundtrip.py'))
API=runpy.run_path(str(HERE/'workspace-config.py'))
SD=runpy.run_path(str(HERE/'sd-directory.py'))


def tree(path):
    return {str(p.relative_to(path)):UI['sha'](p) for p in sorted(path.rglob('*')) if p.is_file()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-ui-result',type=Path,required=True)
    args=parser.parse_args()
    source=args.from_ui_result.resolve(strict=True)
    if not source.is_relative_to((HERE/'runtime/analysis').resolve()):raise ValueError('owned UI evidence required')
    original=json.loads(source.read_text());review=json.loads((source.parent/'independent-review.json').read_text())
    if not original['verified'] or not review['verified'] or review['original_result_sha256']!=UI['sha'](source):
        raise ValueError('independently reviewed real UI reset required')
    source_ws=Path(original['workspace']);reference=API['official_reference'](Path(original['next_prepared_runtime']))
    out=Path(tempfile.mkdtemp(prefix='reset-cold-boot-',dir=HERE/'runtime/analysis'));workspace=out/'workspace'
    (workspace/'.a7c2').mkdir(parents=True,mode=0o700)
    before=tree(source_ws/'.a7c2/config')
    with API['locked'](source_ws) as store:
        current=store.current(reference)
        if current['identity']!=original['reset_generation'] or current['state']!='reset':raise ValueError('source no longer selects UI reset')
        shutil.copytree(source_ws/'.a7c2/config',workspace/'.a7c2/config')
    shutil.copytree(source_ws/'SD',workspace/'SD');sd_before=SD['directory_tree'](workspace/'SD')
    env={**os.environ,'WINIT_X11_SCALE_FACTOR':'1','LIBGL_ALWAYS_SOFTWARE':'1'};env.pop('WAYLAND_DISPLAY',None)
    record={'schema':'reset-cold-boot-v1','verified':False,'scope':'original firmware cold boot of a copied real UI reset selection and combined save',
            'source_result':str(source),'source_result_sha256':UI['sha'](source),'workspace':str(workspace),
            'reset_generation':current['identity'],'value_review_pending':True}
    sources=['check-reset-cold-boot.py','check-config-value-roundtrip.py','start-official-camera.py','run-camera.py',
             'run-full-system.py','workspace-config.py','screens.json','screen-map.py']
    source_hashes={name:UI['sha'](HERE/name) for name in sources};server=session=None
    try:
        server=UI['start_display'](out,env)
        session=UI['Session'](workspace,out,env,'reset-boot',attach_sd=True).launch();session.wait_markers(90)
        UI['drive_first_setup'](session,record)
        end=time.monotonic()+60
        while not re.search(r'FILE_MEDIA_FSYS op=Mount path=/nondev/rm2 flags=0x300 drive=\d+ result=0(?:\s|$)',
                            (session.run/'console.log').read_text(errors='replace')):
            if time.monotonic()>end:raise TimeoutError('original SD mount')
            time.sleep(.3)
        frame=session.frame()
        if frame is None:raise RuntimeError('no stable original frame')
        (out/'shooting.ppm').write_bytes(frame.read_bytes())
        from PIL import Image
        Image.open(frame).save(out/'shooting.png')
        runtime=session.run.parents[2];load=json.loads((runtime.parent/'config-load.json').read_text())
        assert load['generation']==original['reset_generation']
        assert not (runtime/'analysis/config-generation.json').exists()
        session.close();record['launcher_rc']=session.proc.returncode;record['run']=str(session.run)
        result=json.loads((session.run/'result.json').read_text());assert result['state']=='observation-completed'
        saved=json.loads((session.run/'workspace-config-save.json').read_text())
        with API['locked'](workspace) as store:
            now=store.current(reference);assert now['state']=='backup' and now['identity']==saved['generation']
            for local,remote in API['PUBLISH']['TARGETS']:
                data=(session.run/local).read_bytes();API['PUBLISH']['BACKUP']['validate'](data,reference)
                assert now['files'][remote]==data
        assert SD['directory_tree'](workspace/'SD')==sd_before
        assert tree(source_ws/'.a7c2/config')==before
        assert source_hashes=={name:UI['sha'](HERE/name) for name in sources}
        record.update(observation_completed=True,shooting_frame_sha256=UI['sha'](out/'shooting.ppm'),
                      saved_generation=now['identity'],sd_preserved=True,source_workspace_unchanged=True,
                      source_unchanged=True,source_hashes=source_hashes)
    except BaseException as error:
        record['error']=repr(error);raise
    finally:
        if session is not None:record['cleanup']=session.cleanup()
        if server is not None and server.poll() is None:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
        (out/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        print('RESET_COLD_BOOT_CHECK',out,flush=True)


if __name__=='__main__':main()
