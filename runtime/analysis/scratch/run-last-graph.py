#!/usr/bin/env python3
"""Run one existing graph profile and retain its selected image; local VM only."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if sys.argv[1:] not in (['osd'], ['hdmi'], ['all'], ['cp-audit'], ['cp302c'], ['cp302c-diagnostic'], ['cp-notification'], ['cp-capture-format'], ['cp-startup-controls'], ['cp-ee-controls'], ['cp-movie-format']):
        raise ValueError('choose osd, hdmi, all, cp-audit, cp302c, cp302c-diagnostic, cp-notification, cp-capture-format, cp-startup-controls, cp-ee-controls or cp-movie-format')
    edge = sys.argv[1]
    combined = edge in ('cp-capture-format', 'cp-startup-controls', 'cp-ee-controls', 'cp-movie-format')
    kernel_receipts = edge in ('hdmi', 'all', 'cp-audit', 'cp302c', 'cp302c-diagnostic', 'cp-notification', 'cp-capture-format', 'cp-startup-controls', 'cp-ee-controls', 'cp-movie-format') and (BASE / 'scratch/hdmi-kernel-receipt-abi.json').is_file()
    regression_name = ('cp-movie-format-host-regression.json' if edge=='cp-movie-format' else
                       'cp-ee-controls-v2-host-regression.json' if edge=='cp-ee-controls' else
                       'cp-startup-controls-host-regression.json' if edge=='cp-startup-controls' else
                       'cp-capture-format-host-regression.json' if combined else
                       'cp-notification-host-regression.json' if edge == 'cp-notification' else
                       'cp302c-diagnostic-host-regression.json' if edge == 'cp302c-diagnostic' else
                       'cp302c-noconvert-host-regression.json' if edge == 'cp302c' else
                       'cp302c-audit-host-regression.json' if edge == 'cp-audit' else
                       'hdmi-kernel-receipt-host-regression.json' if kernel_receipts else
                       'hdmi-cp-backup-host-regression.json' if edge == 'hdmi' else 'final-graph-host-regression.json')
    abi_name = ('cp-movie-format-abi.json' if edge=='cp-movie-format' else
                'cp-ee-controls-v2-abi.json' if edge=='cp-ee-controls' else
                'cp-startup-controls-abi.json' if edge=='cp-startup-controls' else
                'cp-capture-format-abi.json' if combined else
                'cp-notification-abi.json' if edge == 'cp-notification' else
                'cp302c-diagnostic-abi.json' if edge == 'cp302c-diagnostic' else
                'cp302c-noconvert-abi.json' if edge == 'cp302c' else
                'cp302c-audit-abi.json' if edge == 'cp-audit' else
                'hdmi-kernel-receipt-abi.json' if kernel_receipts else
                'hdmi-cp-backup-abi.json' if edge == 'hdmi' else 'final-graph-abi.json')
    reg = json.loads((BASE / 'scratch' / regression_name).read_text())
    abi = json.loads((BASE / 'scratch' / abi_name).read_text())
    build = json.loads((BASE / 'observer-build-inputs.json').read_text())
    assert not reg['returncode'] and not abi['returncode'] and not reg['production_sources_changed'] and not reg['host_profile_sources_changed']
    assert sha(BASE / 'menu-observe.so') == abi['observer_sha256'] == build['observer_sha256']
    observer_sources = reg.get('observer_sources_before', {})
    if kernel_receipts and abi.get('host_socket_validation_sha256'):
        validation_path = BASE / 'scratch/hdmi-kernel-host-socket-validation.json'
        validation = json.loads(validation_path.read_text())
        assert sha(validation_path) == abi['host_socket_validation_sha256']
        assert validation['base_regression_sha256'] == sha(BASE / 'scratch' / regression_name)
        assert validation['returncode'] == 0 and type(validation['tests_passed']) is int and validation['tests_passed'] >= 69
        observer_sources = validation['observer_sources_after']
        assert set(observer_sources) == set(reg['observer_sources_before'])
    for name, digest in {**reg['production_sources_before'], **reg['host_profile_sources_before'],
                         **observer_sources}.items():
        assert sha(Path(name)) == digest, name
    assert {n: e['sha256'] for n, e in build['sources'].items()} == reg['production_sources_before']
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
    settings = json.loads((BASE / 'scratch/startup-intent-graph-batch-s4w0zdyv.json').read_text())['settings']
    settings['SEED_BACKUP'] = 'alllang'
    for name in ('A7C2_PINMEM_HDMI_VIDEO_CONNECT', 'MENU_PINMEM_HDMI_VIDEO_CONNECT', 'A7C2_PINMEM_OSD_CONNECT', 'MENU_PINMEM_OSD_CONNECT', 'A7C2_CP302C_NO_TRANSITION', 'MENU_CP302C_NO_TRANSITION', 'A7C2_CP302C_DIAGNOSTIC', 'MENU_CP302C_DIAGNOSTIC', 'A7C2_CP_NOTIFICATION_CONTROL', 'MENU_CP_NOTIFICATION_CONTROL', 'A7C2_CP_CAPTURE_FORMAT', 'MENU_CP_CAPTURE_FORMAT'):
        settings.pop(name, None)
    if edge in ('osd', 'all', 'cp-audit', 'cp302c', 'cp302c-diagnostic', 'cp-notification', 'cp-capture-format', 'cp-startup-controls', 'cp-ee-controls', 'cp-movie-format'):
        settings['A7C2_PINMEM_OSD_CONNECT'] = 'virtual-pinmem-osd0-osdpin-if0-ssos-v1'
    if edge in ('hdmi', 'all', 'cp-audit', 'cp302c', 'cp302c-diagnostic', 'cp-notification', 'cp-capture-format', 'cp-startup-controls', 'cp-ee-controls', 'cp-movie-format'):
        settings['A7C2_PINMEM_HDMI_VIDEO_CONNECT'] = 'virtual-pinmem-video0-hdmi-video0-initializing-v1'
    if edge == 'cp302c':
        settings['A7C2_CP302C_NO_TRANSITION'] = 'virtual-cp302c-current0-no-transition-v1'
    if edge in ('cp302c-diagnostic', 'cp-notification', 'cp-capture-format', 'cp-startup-controls', 'cp-ee-controls', 'cp-movie-format'):
        settings['A7C2_CP302C_DIAGNOSTIC'] = 'diagnostic-cp302c-reply-only-v1'
    if edge in ('cp-notification', 'cp-capture-format', 'cp-startup-controls', 'cp-ee-controls', 'cp-movie-format'):
        settings['A7C2_CP_NOTIFICATION_CONTROL'] = 'virtual-cp-notification-mode0-v1'
    if combined:
        settings['A7C2_CP_CAPTURE_FORMAT'] = ('diagnostic-cp-movie-format-v1' if edge=='cp-movie-format' else
                                             'diagnostic-cp-ee-controls-v1' if edge=='cp-ee-controls' else
                                             'diagnostic-cp-startup-controls-v1' if edge=='cp-startup-controls' else
                                             'diagnostic-cp402d-reply-only-v1')
    card = Path(tempfile.mkdtemp(prefix=edge + '-retained-image-', dir=BASE / 'directory-sd-tests'))
    (card / 'INPUT.BIN').write_bytes(('Virtual ' + edge + ' graph metadata; capture remains unverified.\n').encode('ascii'))
    intent = {'scope': edge + ' native diagnostic with exact selected image retained', 'settings': settings,
              'observer_sha256': build['observer_sha256'], 'source_count': len(build['sources']),
              'ABI_sha256': sha(BASE / 'scratch' / abi_name), 'regression_sha256': sha(BASE / 'scratch' / regression_name),
              'card': str(card), 'capture_verified': False}
    (BASE / 'scratch' / ('startup-intent-' + card.name + '.json')).write_text(json.dumps(intent, indent=2) + '\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_'))}
    env.update(settings)
    command = ['python3', '-B', str(BASE / 'check-natural-gtk-input.py'), '--candidate-build', str(stage),
               '--host-sd-dir', str(card), '--new-ui', '--firstboot', '--simplified-chinese', '--natural-shutter', '--export-sd']
    child = subprocess.Popen(command, cwd=BASE, env=env, stdout=subprocess.PIPE, text=True, bufsize=1)
    retained = False
    try:
        for line in child.stdout:
            print(line, end='', flush=True)
            if line.startswith('GTK_INPUT_RUN '):
                run = Path(line.split(None, 1)[1].strip())
                assert run.parent == BASE / 'menu-runs'
                manifest = json.loads((run / 'runtime-manifest.json').read_text())
                original = BASE / 'menu-initramfs.cpio'
                digest = manifest['files'][str(original)]
                assert sha(original) == digest
                target = run / 'selected-initramfs.cpio'
                assert not target.exists()
                shutil.copyfile(original, target)
                assert sha(target) == digest
                receipt = {'selected_initramfs_sha256': digest, 'bytes': target.stat().st_size,
                           'source_path': str(original), 'retained_path': str(target),
                           'same_run_manifest_sha256': sha(run / 'runtime-manifest.json'), 'capture_verified': False}
                (run / 'selected-initramfs-retention.json').write_text(json.dumps(receipt, indent=2) + '\n')
                print('SELECTED_INITRAMFS_RETAINED', digest, flush=True)
                retained = True
    except BaseException:
        child.terminate()
        child.wait(timeout=60)
        raise
    rc = child.wait()
    assert retained, 'run did not retain its selected image'
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
