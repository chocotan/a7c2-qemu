#!/usr/bin/env python3
"""One local functional-profile acceptance attempt, preserving tested artifacts."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading

BASE = Path(__file__).resolve().parents[1]
BATCH = BASE / 'scratch/unified-camera-3lbiw8e9'
INTENT = BASE / 'scratch/functional-language-consume-plan-nush6b02/intent.json'
sys.path.insert(0, str(BASE))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    ready = json.loads((BATCH / 'ready.json').read_text())
    inputs = json.loads((BATCH / 'inputs.json').read_text())
    abi = json.loads((BATCH / 'abi.json').read_text())
    regression = json.loads((BATCH / 'host-regression.json').read_text())
    assert not regression['returncode'] and not abi['returncode'] and not abi['media_preload']['returncode']
    assert not any(regression['changed'].values())
    for key, path in [('inputs_sha256', 'inputs.json'), ('regression_sha256', 'host-regression.json'), ('abi_sha256', 'abi.json')]:
        assert ready[key] == sha(BATCH / path)
    for group in inputs['groups'].values():
        for path, digest in group.items():
            assert sha(Path(path)) == digest, path
    assert sha(BASE / 'menu-observe.so') == abi['observer_sha256']
    assert sha(BASE / 'observer-build-sources.tar.gz') == abi['source_archive_sha256']
    assert sha(BASE / 'functional-camera-model.so') == ready['functional_model_library_sha256']
    stage = (BASE / '../../source/build/qemu-SRBXNK').resolve()
    assert sha(stage / 'build/qemu-system-aarch64') == 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02'
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            if Path(os.readlink(proc / 'exe')).name.startswith('qemu-system-'):
                command = (proc / 'cmdline').read_bytes()
                assert bytes(str(BASE.parents[4]), 'utf-8') not in command and b'qemu-SRBXNK' not in command, ('project VM already running', proc.name)
        except OSError:
            pass
    prepared = subprocess.run(['bash', str(BASE / 'prepare-menu-initramfs.sh')], cwd=BASE,
                              capture_output=True, text=True, timeout=180)
    print(prepared.stdout, end='', flush=True)
    if prepared.returncode:
        print(prepared.stderr, file=sys.stderr)
        return prepared.returncode
    assert sha(BASE / 'menu-observe.so') == abi['observer_sha256']
    assert sha(BASE / 'observer-build-sources.tar.gz') == abi['source_archive_sha256']
    intent = json.loads(INTENT.read_text())
    settings = intent['settings']
    card = Path(intent['card'])
    assert card.is_dir() and not card.is_symlink() and not any(card.iterdir())
    settings['SEED_BACKUP'] = 'alllang'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_'))}
    env.update(settings)
    hdmi = load('current_functional_hdmi_observer', BASE / 'scratch/run-hdmi-observed.py')
    command = ['python3', '-B', '-u', '-c', r'''
import importlib.util,sys
from pathlib import Path
base=Path(sys.argv[1]);sys.path.insert(0,str(base));sys.argv=sys.argv[2:]
spec=importlib.util.spec_from_file_location('current_natural_gtk',base/'check-natural-gtk-input.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
marker="spec=importlib.util.spec_from_file_location('gtk_real_entry'"
assert m.DRIVER.count(marker)==1
patch=''' + '"""' + r'''
original_functional_vm_init=VM.__init__
def tested_functional_vm_init(self,*args,**kwargs):
 original_functional_vm_init(self,*args,**kwargs)
 self.command=['bash','-c','SKIP_REBUILD=1 exec bash "$1"','--',str(Path.cwd()/'run-menu-probe.sh')]
VM.__init__=tested_functional_vm_init
''' + '"""' + r'''
m.DRIVER=m.DRIVER.replace(marker,patch+marker)
m.main()
''', str(BASE), 'check-natural-gtk-input.py', '--candidate-build', str(stage),
               '--host-sd-dir', str(card), '--new-ui', '--firstboot', '--simplified-chinese', '--natural-shutter', '--export-sd']
    done = threading.Event()
    thread = None
    result = {'armed': False, 'capture_verified': False}
    child = subprocess.Popen(command, cwd=BASE, env=env, stdout=subprocess.PIPE, text=True, bufsize=1)
    run = None
    try:
        for line in child.stdout:
            print(line, end='', flush=True)
            if line.startswith('GTK_INPUT_RUN '):
                assert run is None
                run = Path(line.split(None, 1)[1].strip())
                assert run.parent == BASE / 'menu-runs'
                manifest = json.loads((run / 'runtime-manifest.json').read_text())
                original = BASE / 'menu-initramfs.cpio'
                digest = manifest['files'][str(original)]
                assert sha(original) == digest
                target = run / 'selected-initramfs.cpio'
                with original.open('rb') as source, target.open('xb') as dest:
                    shutil.copyfileobj(source, dest)
                assert sha(target) == digest
                (run / 'selected-initramfs-retention.json').open('x').write(json.dumps({
                    'selected_initramfs_sha256': digest, 'bytes': target.stat().st_size,
                    'source_path': str(original), 'retained_path': str(target),
                    'batch': str(BATCH), 'batch_ready_sha256': sha(BATCH / 'ready.json'),
                    'capture_verified': False}, indent=2) + '\n')
                print('SELECTED_INITRAMFS_RETAINED', digest, flush=True)
                thread = threading.Thread(target=hdmi.observe, args=(run, done, result), daemon=False)
                thread.start()
        rc = child.wait()
    finally:
        done.set()
        if thread is not None:
            thread.join(timeout=35)
            if thread.is_alive():
                raise RuntimeError('Native HDMI observer cleanup unconfirmed; retain VM owner')
    if run is not None:
        (run / 'functional-acceptance-launch.json').open('x').write(json.dumps({
            'scope': 'one original natural UI functional-profile acceptance attempt', 'batch': str(BATCH),
            'batch_ready_sha256': sha(BATCH / 'ready.json'), 'returncode': rc,
            'tested_observer_sha256': abi['observer_sha256'], 'capture_verified': False}, indent=2) + '\n')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
