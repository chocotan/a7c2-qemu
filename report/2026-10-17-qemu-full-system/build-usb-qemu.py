#!/usr/bin/env python3
"""Build an isolated full-dump QEMU layer; never install into the menu runtime."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import runpy

HERE=Path(__file__).resolve().parent
RUNTIME=HERE/'runtime'


def main():
    lock=(RUNTIME/'.usb-build.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    menu=runpy.run_path(str(HERE/'native-input.py'))['resolve']()
    inputs=json.loads((menu/'snapshot.json').read_text())
    work=RUNTIME/'usb-build';work.mkdir(exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='build-',dir=work));package=stage/'native-input'
    board_source=(HERE/'usb-qemu-board.py').read_bytes()
    frozen_patcher=stage/'usb-qemu-board.py'
    frozen_patcher.write_bytes(board_source)
    for item in inputs['files']:
        if item['role']!='public-source':continue
        relative=Path(item['path']);source=menu/relative
        target=package/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target);target.chmod(item['mode']|0o200)
    build=package/'build-qemu.sh';text=build.read_text()
    anchor='mkdir -p "$stage/build" "$stage/tmp" "$stage/cache"'
    if text.count(anchor)!=1:raise ValueError('Base build hook changed')
    build.write_text(text.replace(anchor,'python3 "$FULL_USB_PATCHER" "$src"\n'+anchor,1))
    env={**os.environ,'FULL_USB_PATCHER':str(frozen_patcher)}
    archive=menu/'source/vendor/qemu-11.1.2.tar.xz'
    subprocess.run(['bash',str(build),str(archive)],env=env,check=True)
    source=package/'runtime/sources/qemu-11.1.2/build-sony-ui/qemu-system-aarch64'
    subprocess.run(['python3','-B',str(HERE/'test-usb-qemu.py'),str(source)],check=True)
    subprocess.run(['python3','-B','-m','unittest','-v','test-media-detect'],cwd=HERE,
                   env={**os.environ,'QEMU_MEDIA_TEST_BINARY':str(source)},check=True)
    target=RUNTIME/'usb-qemu';target.mkdir(exist_ok=True)
    temporary=target/'qemu-system-aarch64.new'
    shutil.copy2(source,temporary);temporary.replace(target/'qemu-system-aarch64')
    manifest={'base_manifest_sha256':hashlib.sha256((menu/'source/manifest.json').read_bytes()).hexdigest(),
              'native_dependency_snapshot':menu.name,
              'board_layer_sha256':hashlib.sha256(board_source).hexdigest(),
              'program_sha256':hashlib.sha256((target/'qemu-system-aarch64').read_bytes()).hexdigest(),
              'profile':'upstream-DWC3-host-core-only-no-gadget-or-connection-proof',
              'stage':stage.relative_to(HERE).as_posix()}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('FULL_USB_QEMU_BUILT_SEPARATELY',manifest['program_sha256'],flush=True)


if __name__=='__main__':main()
