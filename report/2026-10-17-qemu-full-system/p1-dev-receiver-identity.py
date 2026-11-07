#!/usr/bin/env python3
"""Exact, opt-in DEV identity adapter for the frozen P1 file-media C source.

No receiver writer or launch entry point. The existing derived receiver must
already pass its original four-byte inverse proof. Stock C is only read.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import stat

HERE = Path(__file__).resolve().parent
PROFILE = 'original-p1-virtual-dev-install-v1'
MODE = 'virtual-dev-sd-update-v1'
KINDS = ('version-only-2.02', 'fixed-system-file-v1')
SOURCE = 'simulation/p1-dev-file-media-config.c'
CONTRACT = 'simulation/p1-dev-file-media-contract.json'
RUNTIME_FILES = (SOURCE, CONTRACT)
STOCK_C = (24492, 'f0f359603d69b85b14acac6051809c0d61a8db722c04e7fd8f512b4d98add852')
STOCK_RECEIVER = (60600, '1a6a3226993ce7c25659bd58e20871d91869083b31440650eec555a06d592d2f')
DEV_RECEIVER = (60600, 'bfaf84e1f2c71056c450640f6752c6cd6c8f84004778506dd6d237ced0bd46f6')
INITIALIZE = (0xa758, 236, '18b3689b0fc5973c5a82aa5fb510ac03178dda5f1ee469bef3f0e7f506d03249')
LIBRARIES = {
    'libc-2.25.so': (1271648, '363b313d6b3f9b4c8b4d91ddcbdd5096970887fbbb543ebea1d1295ce4d65733'),
    'libdl-2.25.so': (10368, 'b525ab6ba51617ac0747ca7dc8b87dfa809d5b4b6b176fe7a01922296af4d97b'),
    'libpthread-2.25.so': (101888, 'a58f6f84efd89bef0d12028b974b5e3aca2a2804e922954283e8127d6d5a02fe'),
    'ld-2.25.so': (120616, 'ae69d962b3a819765bbd42c2077df52745de7ab6b0cf2052522737258875f2e6'),
}


def api(name):
    return runpy.run_path(str(HERE / name))


def facts(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def snapshot(path, expected=None):
    """Reuse the receiver's no-follow descriptor walk and race-checked read."""
    dev = api('dev-update-profile.py'); path = dev['_path'](path)
    parent = dev['_open_directory'](path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 16 * 1024**2:
                raise ValueError('DEV media ordinary source/input size differs: ' + str(path))
            data = dev['_read'](fd, info.st_size); row = facts(data)
            if expected is not None and (row['bytes'], row['sha256']) != expected:
                raise ValueError('DEV media exact input differs: ' + str(path))
            dev['_verify_source'](path, parent, fd, info, row['sha256'])
            return data, dict(path=str(path), **row)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def selection(*, profile, mode, install_kind, environment, authorization):
    expected = {'A7C2_FILE_MEDIA_TEST': '1', 'A7C2_P1_FILE_MEDIA_PROFILE': 'original-sd-v1',
                'A7C2_P1_DEV_INSTALL': install_kind}
    if (profile != PROFILE or mode != MODE or install_kind not in KINDS or environment != expected
            or not isinstance(authorization, str)
            or re.fullmatch(re.escape(PROFILE) + r' [0-9a-f]{64} [0-9a-f]{64}\n', authorization) is None):
        raise ValueError('Exact authorized DEV file-media profile/kind/environment required')
    return dict(profile=PROFILE, mode=MODE, install_kind=install_kind,
                environment=expected, authorization=authorization)


def runtime_texts(selected):
    selected = selection(**selected)
    return {'simulation/update-profile': MODE + '\n',
            'simulation/sd-read-profile': PROFILE + '\n',
            'simulation/dev-authorization': PROFILE + '\n',
            'simulation/install-authorization': selected['authorization'],
            'simulation/sd-read-env': ''.join(f'{k}={v}\n' for k, v in selected['environment'].items())}


def _render(stock, selected):
    """Only the exact stock C can produce this complete, reproducible DEV C."""
    selected = selection(**selected)
    if (len(stock), hashlib.sha256(stock).hexdigest()) != STOCK_C:
        raise ValueError('Unknown frozen file-media C version')
    old = ('"' + STOCK_RECEIVER[1] + '",236,').encode('ascii')
    if stock.count(old) != 1:
        raise ValueError('Frozen receiver guard occurrence differs')
    text = stock.replace(old, ('"' + DEV_RECEIVER[1] + '",236,').encode('ascii'))
    marker = b'    if (!test_mode()) { *__errno_location()=saved_errno; return; }\n'
    if text.count(marker) != 1:
        raise ValueError('Frozen file-media opt-in guard differs')
    checks = ['!p1_profile()', '!dev_install', 'strcmp(dev_install,"' + selected['install_kind'] + '")']
    for name, value in runtime_texts(selected).items():
        row = facts(value.encode('ascii'))
        checks.append(f'!hash_file("/{name}",{row["bytes"]},"{row["sha256"]}")')
    guard = ('    const char *dev_install=getenv("A7C2_P1_DEV_INSTALL");\n'
             '    if(' + ' ||\n       '.join(checks) + ') {\n'
             '        console_line("P1_DEV_MEDIA_PROFILE_FAILED");_exit(126);\n    }\n').encode('ascii')
    return text.replace(marker, marker + guard)


def derive(stock_source, original_receiver, derived_receiver, receiver_receipt, *, selected):
    stock, source_row = snapshot(stock_source, STOCK_C)
    original, original_row = snapshot(original_receiver, STOCK_RECEIVER)
    derived, derived_row = snapshot(derived_receiver, DEV_RECEIVER)
    dev = api('dev-update-profile.py')
    proof = dev['verify_derived_receiver'](derived_receiver, receiver_receipt)
    # Reuse the existing inverse validator; this adapter never writes receiver bytes.
    dev['_check_diff'](original, derived)
    offset, count, digest = INITIALIZE
    contract = api('p1-file-media-contract.py')
    for data in (original, derived):
        start = contract['va_offset'](data, offset, count)
        if hashlib.sha256(data[start:start + count]).hexdigest() != digest:
            raise ValueError('DEV receiver unchanged Initialize window differs')
    text = _render(stock, selected)
    return text, dict(schema='a7c2-p1-dev-file-media-derivation-v1', selection=selection(**selected),
        stock_source=source_row, original_receiver=original_row,
        receiver={k: v for k, v in derived_row.items() if k != 'path'}, inverse=proof,
        initialize=dict(va=offset, bytes=count, sha256=digest, unchanged=True),
        generated_source=facts(text), coverage=False, read_verified=False, bypass_executed=False,
        installation_verified=False, source_coverage_complete=False)


def _fresh(path, data):
    dev = api('dev-update-profile.py'); path = dev['_path'](path)
    parent = dev['_open_directory'](path.parent)
    try:
        fd = os.open(path.name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        try:
            dev['_write'](fd, data); os.fsync(fd)
            dev['_verify_directory'](path.parent, parent)
            os.fsync(parent)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def _json(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode('ascii')


def _derive(root, update, selected):
    return derive(HERE / 'file-media-config.c', update['original_files']['usr/lib/libsdfileinputupdaterapi.so']['path'],
                  Path(root) / 'usr/lib/libsdfileinputupdaterapi.so', update['receiver'], selected=selected)


def _link_inputs(root):
    return [snapshot(Path(root) / 'lib' / name, expected)[1] for name, expected in LIBRARIES.items()]


def compile_argv(source, root, compiler, linker):
    return [str(compiler), '--target=aarch64-linux-gnu', '-fuse-ld=lld', '--ld-path=' + str(linker), '-nostdlib', '-O2',
            '-mno-outline-atomics', '-Wl,--no-undefined', '-shared', '-fPIC', str(source),
            *[str(Path(root) / 'lib' / name) for name in LIBRARIES],
            '-o', str(Path(root) / 'simulation/file-media-config.so')]


def prepare(root, update, output, *, selected):
    root, output = Path(root), Path(output)
    if output != Path(update['output']) or root != output / 'root':
        raise ValueError('DEV media derivation requires the fresh U builder root')
    text, proof = _derive(root, update, selected)
    u = api('update-boot.py')
    clang = shutil.which('clang')
    lld = shutil.which('ld.lld')
    if not clang or not lld:
        raise ValueError('DEV media requires recorded clang and ld.lld')
    compiler, linker = [u['record'](Path(p).resolve(strict=True)) for p in (clang, lld)]
    source = output / 'p1-dev-file-media-config.c'
    _fresh(source, text); _fresh(root / SOURCE, text)
    return dict(proof=proof, source=u['record'](source), compiler=compiler, linker=linker,
                link_inputs=_link_inputs(root))


def seal(root, update, prepared, command, *, selected):
    """Bind the fresh compiler result; no hash supplied by a caller can select it."""
    hook = update['file_media']
    metadata = dict(schema='a7c2-p1-dev-file-media-build-v1', prepared=prepared, command=command,
                    source=hook['source'], output=hook['output'])
    hook['identity_adapter'] = metadata
    _fresh(Path(root) / CONTRACT, _json(metadata))
    _verify_build(root, update, selected=selected)
    return metadata


def _verify_build(root, update, *, selected):
    """Reconstruct the whole C, exact receiver inverse, compiler inputs and U/E DSO."""
    u = api('update-boot.py'); root = Path(root); hook = update['file_media']
    metadata = hook.get('identity_adapter')
    if (not isinstance(metadata, dict) or metadata.get('schema') != 'a7c2-p1-dev-file-media-build-v1'
            or set(metadata) != {'schema', 'prepared', 'command', 'source', 'output'}
            or hook.get('enabled') is not True or hook.get('executed') is not False):
        raise ValueError('DEV media requires the derived compiler/provenance contract')
    prepared = metadata['prepared']
    if set(prepared) != {'proof', 'source', 'compiler', 'linker', 'link_inputs'}:
        raise ValueError('DEV media generated-input set differs')
    text, proof = _derive(root, update, selected)
    if prepared['proof'] != proof or metadata['source'] != hook['source'] or prepared['source'] != hook['source']:
        raise ValueError('DEV media exact derivation/source contract differs')
    build_root = Path(update['output']) / 'root'
    source = Path(update['output']) / 'p1-dev-file-media-config.c'
    if Path(hook['source']['path']) != source or Path(hook['output']['path']) != build_root / 'simulation/file-media-config.so':
        raise ValueError('DEV media source/output escaped the fresh builder root')
    for path in (source, root / SOURCE):
        if snapshot(path)[0] != text:
            raise ValueError('DEV media whole generated C readback differs')
    if _link_inputs(build_root) != prepared['link_inputs']:
        raise ValueError('DEV media original link input drift')
    _link_inputs(root)
    for row in (prepared['compiler'], prepared['linker'], prepared['source'], hook['output']):
        if u['record'](row['path']) != row:
            raise ValueError('DEV media compiler/source/DSO producer identity drift')
    command = metadata['command']
    expected = compile_argv(source, build_root, prepared['compiler']['path'], prepared['linker']['path'])
    recorded, _ = u['checked_json'](Path(update['output']) / 'file-media-build.json')
    if (command.get('argv') != expected or command.get('rc') != 0 or command.get('timed_out') is not False
            or recorded != command or update['commands'].count(command) != 1):
        raise ValueError('DEV media exact compiler command/receipt differs')
    for name in ('stdout', 'stderr'):
        if u['record'](command[name]['path']) != command[name]:
            raise ValueError('DEV media compiler evidence drift')
    dso, _ = snapshot(root / 'simulation/file-media-config.so')
    if (metadata['output'] != hook['output'] or facts(dso) != {
            k: hook['output'][k] for k in ('bytes', 'sha256')}):
        raise ValueError('DEV media U/E full DSO binding differs')
    if (dso[:6] != b'\x7fELF\x02\x01' or dso[16:20] != b'\x03\x00\xb7\x00'
            or DEV_RECEIVER[1].encode('ascii') not in dso or STOCK_RECEIVER[1].encode('ascii') in dso
            or any(pin not in dso for pin in (INITIALIZE[2].encode('ascii'),
                   b'P1_BODY_IDENTITY_FAILED', b'P1_FILE_MEDIA_IDENTITY_FAILED',
                   b'P1_FILE_MEDIA_READBACK_FAILED', b'P1_DEV_MEDIA_PROFILE_FAILED'))):
        raise ValueError('DEV media compiled ELF/guard literals differ')
    if snapshot(root / CONTRACT)[0] != _json(metadata):
        raise ValueError('DEV media bootstrap/CPIO provenance contract differs')
    return metadata


def verify(root, update, *, selected):
    metadata = _verify_build(root, update, selected=selected)
    root = Path(root)
    for name, value in runtime_texts(selected).items():
        if snapshot(root / name)[0] != value.encode('ascii'):
            raise ValueError('DEV media runtime profile file differs: ' + name)
    return metadata


def observer_contract(initialization):
    """Label unchanged passive windows with the actual full receiver identity."""
    if initialization.get('schema') != 'p1-sd-initialize-passive-v1' or len(initialization.get('pins', [])) != 6:
        raise ValueError('Unknown original passive Initialize ABI')
    value = dict(initialization, pins=[dict(pin) for pin in initialization['pins']])
    receiver = [p for p in value['pins'] if p['path'] == '/usr/lib/libsdfileinputupdaterapi.so']
    if len(receiver) != 3 or any(p['sha256'] != STOCK_RECEIVER[1] for p in receiver):
        raise ValueError('Original passive receiver pin set differs')
    for pin in receiver:
        pin['sha256'] = DEV_RECEIVER[1]
    return value
