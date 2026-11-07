#!/usr/bin/env python3
"""Host-only callback/kernel wrapper regression; synthetic inputs, no VM or disk image.

Run directly with --output DIR to keep all compiler/runtime logs, or with pytest.
The existing callback harness/fixture and current production wrappers are compiled.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
HOST_TRACE_HASHES = {name: hashlib.sha256(('USB EE HostFixture ' + name).encode()).hexdigest()
                     for name in ('envelope', 'model')}


def trace_fixture_header():
    original = runpy.run_path(str(HERE / 'test-usb-ee-normal-cold.py'))['fixture_header']()
    return original.replace('host-fixture-only', HOST_TRACE_HASHES['envelope']).replace(
        'host-model-fixture-only', HOST_TRACE_HASHES['model'])


KERNEL_CASES = (
    'complete', 'missing-prime-free', 'unknown-prime-source', 'empty-prime-size',
    'wrong-fd', 'private-map', 'unverified-abi', 'stale-prime-epoch', 'conflicting-receiver',
    'wrong-borrow-pointer', 'short-received-size', 'failed-native-free', 'short-allocation',
    'failed-allocation', 'failed-send', 'duplicate-receive', 'reuse-before-free-return',
    'wrong-borrow-pid', 'wrong-borrow-generation', 'allocation-outside-map',
    'wrong-model-consumer', 'wrong-waiter', 'wrong-received-source', 'changed-init',
    'missing-whole-reader', 'header-before-map', 'payload-after-map', 'target-registration',
    'changing-runtime-pointer-and-count', 'changing-padding', 'changing-stable-snapshot',
    'changed-bound-pid', 'changed-bound-generation', 'changed-bound-abi',
)


def verify_json(out, original):
    """Only extraction and the two fixed asset hashes are mocked for synthetic banks."""
    model = runpy.run_path(str(HERE / 'usb-ee-normal-cold.py'))
    helper = original['PREPARE']
    rows = bytearray(128)
    for off in (0, 64):
        struct.pack_into('<I', rows, off + 4, 1)
    result = dict(backup_sha256=helper['BACKUP_SHA'], cp_bank_sha256=helper['BANK_SHA'],
                  cp_bank_offset=970752, backup_bytes=123, unknown=[],
                  records={0x1120000: b'BIN!' + bytes(12) + struct.pack('<II', 1, 128) + rows,
                           0x30162: bytes(64), 0x30a01: bytes(4)})
    envelope = helper['make_envelope'](result, b'\x0c\0\0\0', 7)
    backup, cp = out / 'fixture-backup', out / 'fixture-cp'
    backup.write_bytes(b'synthetic host fixture only')
    cp.write_bytes(b'synthetic host fixture only')
    real_digest, real_runpy = model['digest'], runpy.run_path

    def fixture_digest(path):
        if Path(path) == backup:
            return helper['BACKUP_SHA']
        if Path(path) == cp:
            return helper['CONTRACT']['CP_SHA']
        return real_digest(path)

    def fixture_runpy(path, *args, **kwargs):
        api = real_runpy(path, *args, **kwargs)
        if Path(path).name == 'prepare-ee-normal-wake-cold.py':
            api['prepare'] = lambda *a: envelope
        return api

    adc = bytearray(48)
    adc[0] = adc[46] = 150
    base = dict(schema=1, profile=model['PROFILE'], generation=7, force_e0=0,
                be9bae_byte9=0, stable_state_hex='00' * 32, adc_hex=adc.hex())
    rejected = []

    def reject(label, operation):
        try:
            operation()
        except ValueError:
            rejected.append(label)
        else:
            raise AssertionError('invalid JSON accepted: ' + label)

    # Keep the mock during validation too: stored bindings still use the fixture hashes.
    with patch.dict(model['prepare'].__globals__, digest=fixture_digest), patch.object(runpy, 'run_path', fixture_runpy):
        prepared = {}
        for source in (None, 'callback', 'kerneldefault'):
            work = out / ('manifest-' + (source or 'legacy'))
            work.mkdir()
            path = work / 'model.json'
            value = dict(base) if source is None else dict(base, admission_source=source)
            path.write_text(json.dumps(value))
            contract = model['prepare'](work, dict(backup=backup, cp=cp, vendor=out, model=path))
            manifest = work / 'prepared.json'
            manifest.write_text(json.dumps(contract, indent=2) + '\n')
            loaded = json.loads(manifest.read_text())
            model['validate'](work, loaded)
            assert loaded['admission_source'] == (source or 'callback')
            assert loaded['kernel_uipc'] == (model['KERNEL_UIPC'] if source == 'kerneldefault' else None)
            assert loaded['stage_actual'] is False and loaded['strict_can_publish'] is False
            prepared[source] = (work, loaded)
        path = out / 'invalid-model.json'
        for label, source in (('unknown', 'wrong'), ('null', None), ('bool', True),
                              ('int', 1), ('list', []), ('object', {})):
            path.write_text(json.dumps(dict(base, admission_source=source)))
            reject('model-source-' + label, lambda: model['load_model'](path))
        work, contract = prepared['kerneldefault']
        mutations = [('missing-source', 'admission_source', None),
                     ('missing-version', 'admission_version', None),
                     ('bool-version', 'admission_version', True),
                     ('string-version', 'admission_version', '1'),
                     ('unknown-version', 'admission_version', 2),
                     ('bool-generation', 'generation', True),
                     ('string-generation', 'generation', '7'),
                     ('zero-generation', 'generation', 0)]
        for label, key, value in mutations:
            bad = copy.deepcopy(contract)
            if label.startswith('missing-'):
                del bad[key]
            else:
                bad[key] = value
            reject(label, lambda: model['validate'](work, bad))
        bad = dict(contract, admission_source='callback', kernel_uipc=None)
        reject('model-source-linkage', lambda: model['validate'](work, bad))
        header = Path(contract['private_header'])
        saved = header.read_bytes()
        header.write_bytes(saved.replace(b'EE_COLD_ADMISSION_SOURCE EE_NWC_KERNELDEFAULT',
                                         b'EE_COLD_ADMISSION_SOURCE EE_NWC_CALLBACK'))
        bad = copy.deepcopy(contract)
        for item in bad['private_inputs']:
            if item['role'] == 'ee-private-header':
                item.update(model['binding'](item['role'], header))
        try:
            reject('header-source-linkage', lambda: model['validate'](work, bad))
        finally:
            header.write_bytes(saved)
        model['validate'](work, contract)
    assert len(rejected) == 16
    (out / 'json-rejections.json').write_text(json.dumps(rejected, indent=2) + '\n')
    return rejected


def verify_host(out):
    out = Path(out).resolve()
    out.mkdir(exist_ok=False)
    original = runpy.run_path(str(HERE / 'test-usb-ee-normal-cold.py'))
    (out / 'input.h').write_text(trace_fixture_header())
    callback = original['HARNESS'].replace(
        'assert(p==message);return mode==5?11:12;',
        'assert(p==message||(mode==6&&p==message+1));return mode==5?11:12;')
    (out / 'callback.c').write_text(callback)
    observer = (HERE / 'usb-ee-zero-observe.inc').read_text()
    wait = 'static uintptr_t fixture_target_wait(' + observer.split('static uintptr_t ee_wait(', 1)[1].split('\n#ifndef USB_OBSERVE_HOST_TEST', 1)[0]
    caller = '(uintptr_t)__builtin_return_address(0)'
    assert wait.count(caller) == 1
    # Only the caller PC is supplied; admission, native call, errno and return use the real body.
    (out / 'fixture-target-wait.inc').write_text(wait.replace(caller, '(app_base+0x35492cc)'))
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1', PYTHONDONTWRITEBYTECODE='1')
    commands = []

    def run(name, args, timeout=40):
        args = list(map(str, args))
        result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=timeout)
        (out / (name + '.stdout')).write_text(result.stdout)
        (out / (name + '.stderr')).write_text(result.stderr)
        commands.append(dict(name=name, command=args, returncode=result.returncode))
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        if result.returncode:
            raise AssertionError(name + ': ' + result.stdout + result.stderr)

    core = [HERE / 'ee-normal-wake-cold.c', HERE / 'ee-capability-input.c']
    common = ['-std=gnu11', '-pthread', '-Wall', '-Wextra', '-Werror',
              '-Wno-unused-function', '-Wno-unused-variable', '-Wno-misleading-indentation',
              '-Wno-missing-field-initializers', '-I', HERE, '-I', out,
              '-DUSB_EE_NORMAL_COLD_INPUT="' + str(out / 'input.h') + '"']
    for kind, flags in [('strict', ['-O2', '-fstrict-aliasing']),
                        ('asan', ['-O1', '-g', '-fsanitize=address,undefined',
                                  '-fno-omit-frame-pointer', '-no-pie'])]:
        binary = out / ('core-' + kind)
        run('build-core-' + kind, ['cc', *common, *flags, *core, HERE / 'test-ee-normal-wake-cold.c', '-o', binary])
        run('run-core-' + kind, [binary])
        for family, source, modes, define in [
            ('callback', out / 'callback.c', range(12), []),
            ('kernel', HERE / 'test-usb-ee-kernelqueue.c', range(len(KERNEL_CASES)),
             ['-DEE_COLD_ADMISSION_SOURCE=EE_NWC_KERNELDEFAULT']),
        ]:
            binary = out / (family + '-' + kind)
            run('build-' + family + '-' + kind,
                ['cc', *common, *flags, *define, source, *core, '-ldl', '-o', binary])
            for mode in modes:
                name = f'{family}-{kind}-{mode}'
                run(name, [binary, out / (name + '.log'), mode], 10)
        trace = (out / f'kernel-{kind}-0.log').read_text()
        for value in ('source_class=kerneldefault', 'registration=not_applicable',
                      'model-owned-native-cpu-copy', 'actual_wire=0600a3200000000000000000',
                      'raw=unavailable', 'retired=1', 'strict_can_publish=0'):
            assert value in trace, value
        negative = (out / f'kernel-{kind}-27.log').read_text()
        assert 'QUEUE_RETURN' in negative and 'callback=0x3344 context=0x5566' in negative
        assert 'FUNCTIONAL_ARM' in negative and 'WAIT_RETURN' in negative
        assert 'FUNCTIONAL_ALLOCATE_ENTER' not in negative and 'retired=1' not in negative
    # Existing extracted queue wrapper also checks saturation, four arguments and errno.
    suite = original['FunctionalAdapter']('test_foreign_queue_actual_c_arguments_errno_once_bound_and_no_admission')
    suite.test_foreign_queue_actual_c_arguments_errno_once_bound_and_no_admission()
    rejected = verify_json(out, original)
    summary = dict(host_only=True, vm_started=False, guest_executed=False, cold_build_executed=False,
                   private_disk_access=False, stage_actual=False, strict_can_publish=False,
                   root_verified=False, ep0_enumeration_verified=False,
                   original_cp_history_verified=False, physical_compatibility_verified=False,
                   core_configurations=2, callback_cases_per_configuration=12,
                   kernel_cases_per_configuration=len(KERNEL_CASES), kernel_cases=KERNEL_CASES,
                   fork_held_lock=True, cross_thread_free=True, pre_free_index_generation=True,
                   ordinary_payload_unknown=True, target_registration_rejected=True,
                   target_wait_return_errno_forwarded=True, foreign_queue_wrapper_passed=True,
                   synthetic_json_fixture=True, prepared_roundtrip=['legacy', 'callback', 'kerneldefault'],
                   typed_json_rejections=len(rejected), commands=len(commands))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    return summary


class KernelQueueHost(unittest.TestCase):
    def test_current_wrapper_strict_asan_and_json(self):
        with tempfile.TemporaryDirectory() as folder:
            verify_host(Path(folder) / 'host')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='fresh host output directory; retains negative logs')
    args = parser.parse_args()
    if args.output:
        verify_host(args.output)
    else:
        unittest.main(argv=[__file__], verbosity=2)
