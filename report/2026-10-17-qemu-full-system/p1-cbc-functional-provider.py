#!/usr/bin/env python3
"""Explicit stock-only P1 CBC build API; never starts a guest or opens a disk."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import struct

HERE = Path(__file__).resolve().parent
PROFILE = 'virtual-p1-cbc-scramble-v1'
ENV = 'A7C2_P1_CBC_PROFILE'
BODY_SHA = 'eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'
KEY_SHA = 'b869168a196223e2866c570590f446ee35152090f55485c603d69c6a75a049a3'
CRYPTO_SHA = 'df69906d5f63a3afe9b7872e41cab741c346630e53ebcaadb86e457f0b803726'
ASSETS = ('profile', 'manifest', 'source-receipt', 'code-receipt', 'env')
RUNTIME = tuple('simulation/p1-cbc-model/' + n for n in ASSETS)
SOURCES = ('p1-cbc-functional-provider.py', 'p1_cbc_provider.inc', 'p1_cbc_stream.c',
           'p1_cbc_stream.h', 'p1_cbc_core.c', 'p1_cbc_core.h', 'p1_cbc_known_k8.inc',
           'p1_cbc_stock_limits.h', 'p1-cbc-guest-abi/openssl/crypto.h',
           'p1-cbc-guest-abi/openssl/evp.h', 'p1-sd-read-probe.py',
           'p1-trust-key.inc', 'p1-trust-key.c', 'p1-trust-key.h')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def record(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('P1 CBC input must be a regular file: ' + str(path))
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(fd)
        if any(getattr(before, k) != getattr(after, k) for k in
               ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_nlink', 'st_mtime_ns', 'st_ctime_ns')):
            raise ValueError('P1 CBC input changed while hashing: ' + str(path))
        return dict(bytes=before.st_size, sha256=digest)
    finally:
        os.close(fd)


def selection(profile=None):
    if profile is None:
        return None
    if profile != PROFILE:
        raise ValueError('Only the explicit stock P1 CBC profile is supported')
    return dict(profile=PROFILE)


def effective_env(chosen=None, inherited=None):
    result = dict(inherited or {})
    result.pop(ENV, None)
    if chosen is not None:
        if chosen != selection(PROFILE):
            raise ValueError('Exact explicit P1 CBC selection required')
        result[ENV] = PROFILE
    return result


def sd_api():
    return runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))


def package_contract(path):
    actual = record(path)
    if actual != dict(bytes=1139929560, sha256=BODY_SHA):
        raise ValueError('Only exact official stock 2.01 BODYDATA is admitted')
    rows = []
    with Path(path).open('rb') as stream:
        if stream.read(8) != b'\x89UFU\r\n\x1a\n':
            raise ValueError('Invalid stock UFU magic')
        for _ in range(100):
            start = stream.tell()
            header = stream.read(8)
            if not header:
                break
            if len(header) != 8:
                raise ValueError('Short stock UFU header')
            size, kind = struct.unpack('>I4s', header)
            offset = stream.tell()
            if size > actual['bytes'] - offset:
                raise ValueError('UFU chunk exceeds full file')
            rows.append(dict(kind=kind.decode('ascii'), header=start, offset=offset, bytes=size))
            stream.seek(size, 1)
        else:
            raise ValueError('UFU chunk budget exceeded')
        if stream.tell() != actual['bytes']:
            raise ValueError('Stock UFU total differs')
    fdat = [r for r in rows if r['kind'] == 'FDAT']
    if len(fdat) != 1 or (fdat[0]['offset'], fdat[0]['bytes']) != (188, 1139929360):
        raise ValueError('Unknown stock FDAT layout')
    if [r['kind'] for r in rows] != ['DATV', 'PROV', 'UDID', 'FDAT', 'DEND']:
        raise ValueError('Unknown stock UFU chunk sequence')
    return dict(**actual, ufu=rows, fdat_offset=188, fdat_bytes=1139929360,
                footer_bytes=272, payload_bytes=1139929088, outer_ecb_bytes=512,
                cbc_bytes=1139928576)


def patch_once(text, replacements):
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError('Unknown P1 source anchor: ' + old[:100])
        text = text.replace(old, new)
    return text


def wrapper_source(text):
    def guarded(call):
        return 'if(!trust_internal){trust_internal=1;' + call + ';trust_internal=0;}'
    return patch_once(text, [
        ('static void passive_packet(', '#include "p1_cbc_provider.inc"\nstatic void passive_packet('),
        ('int rc=fn(sid,out,bytes,wait),error=*__errno_location();',
         'int rc=fn(sid,out,bytes,wait),error=*__errno_location();\n    ' + guarded('p1_fc_allocate(sid,out,bytes,wait,rc,caller)')),
        ('    *__errno_location()=saved;\n    int rc=modeled?0:fn(sid,message),error=*__errno_location();',
         '    int cbc=P1_NS_PASS;\n    ' + guarded('cbc=p1_fc_sync(sid,message,caller)') + '\n'
         '    *__errno_location()=saved;\n    int rc=cbc==P1_NS_REJECT?-1:cbc==P1_NS_MODEL?0:modeled?0:fn(sid,message);\n'
         '    int error=cbc==P1_NS_REJECT?71:*__errno_location();\n    ' + guarded('p1_fc_after_sync(sid,message,rc)')),
        ('        if(!known)passive_log("request-reject",', '        if(!known && !p1_fc.mode)passive_log("request-reject",'),
        ('    if(passive)passive_packet("after",rc,error,caller);',
         '    if(passive && cbc==P1_NS_PASS)passive_packet("after",rc,error,caller);'),
        ('    *__errno_location()=saved;int rc=fn(sid,message),error=*__errno_location();',
         '    ' + guarded('p1_fc_free(sid,message,caller)') + '\n    *__errno_location()=saved;int rc=fn(sid,message),error=*__errno_location();'),
        ('    passive_copy(0,dest,source,n,caller,0,saved);',
         '    passive_copy(0,dest,source,n,caller,0,saved);\n    ' + guarded('p1_fc_before_copy(dest,source,n,caller)')),
        ('    passive_copy(1,dest,source,n,caller,rc,error);',
         '    passive_copy(1,dest,source,n,caller,rc,error);\n    ' + guarded('p1_fc_after_copy(dest,source,n,rc,caller)'))])


def bootstrap_source(text, chosen=None):
    if chosen is None:
        return text
    effective_env(chosen)
    anchor = '    [ -z "$path$bytes$hash$rest" ] && [ "$binding_count" -eq "$binding_expected" ] || return 125\n'
    return patch_once(text, [
        ('#!/bin/sh\n', '#!/bin/sh\nunset ' + ENV + '\n'),
        (anchor, anchor + '    [ -f /simulation/p1-cbc-model/env ] && [ ! -L /simulation/p1-cbc-model/env ] || return 125\n'
         '    [ "$(/bin/busybox wc -c < /simulation/p1-cbc-model/env)" -eq ' + str(len(ENV + '=' + PROFILE + '\n')) + ' ] || return 125\n'
         '    [ "$(/bin/busybox cat /simulation/p1-cbc-model/env)" = ' + ENV + '=' + PROFILE + ' ] || return 125\n'
         '    export ' + ENV + '=' + PROFILE + '\n')])


def _source_receipt(package, trust, bootstrap):
    # Logical relative names make the compiled receipt portable between checkout paths.
    key_text = (HERE / 'p1_cbc_known_k8.inc').read_text(encoding='ascii')
    key = bytes(int(n, 0) for n in re.findall(r'0x[0-9a-f]+', key_text))
    if len(key) != 32 or sha(key) != KEY_SHA:
        raise ValueError('Fixed public vendor k8 constant differs')
    return dict(schema='p1-cbc-source-receipt-v1', sources={n: record(HERE / n) for n in SOURCES},
                inputs=dict(package={k: package[k] for k in ('bytes', 'sha256')},
                            guest_files=trust['files'], bootstrap=bootstrap),
                key_source='fixed-public-vendor-k8', key_sha256=KEY_SHA)


def runtime_header(assets):
    tags = [('MANIFEST', 'manifest'), ('SOURCE', 'source-receipt'), ('CODE', 'code-receipt')]
    return '#ifndef P1_CBC_RUNTIME_BINDING_H\n#define P1_CBC_RUNTIME_BINDING_H\n' + ''.join(
        '#define P1_MODEL_' + tag + '_SHA "' + assets[name]['sha256'] + '"\n'
        '#define P1_MODEL_' + tag + '_BYTES ' + str(assets[name]['bytes']) + 'ul\n'
        for tag, name in tags) + '#endif\n'


def prepare(root, output, *, profile, package_source):
    """Validate actual stock inputs and write five assets plus a per-build compiled pin."""
    chosen = selection(profile)
    if chosen is None or package_source is None:
        raise ValueError('Explicit P1 CBC profile and actual package source required')
    root, output = Path(root), Path(output)
    sd = sd_api()
    package = package_contract(package_source)
    trust, initializer = sd['trust_contract'](root), sd['initialize_contract'](root)
    if (len(trust['passive']['windows']) != 4 or
            trust['passive']['log_budget'] != dict(total=128, pin_identity=32, observations=96)):
        raise ValueError('Original P1 passive pins or budget differ')
    base = (root / 'init').read_text(encoding='ascii')
    bootstrap = bootstrap_source(base, chosen)
    source_data = encoded(_source_receipt(package, trust, record(root / 'init')))
    code_data = encoded(dict(trust=trust, initializer=initializer))
    manifest = encoded(dict(schema='p1-cbc-fixed-functional-manifest-v1', profile=PROFILE,
        enabled_by_default=False, body_sha256=BODY_SHA, key_sha256=KEY_SHA, crypto_sha256=CRYPTO_SHA,
        package=package, source_receipt_sha256=sha(source_data), code_receipt_sha256=sha(code_data),
        first_bytes=512, next_bytes=1024, max_streams=1, max_other_outstanding_per_thread=1,
        status_success=1, status_source='model-defined; original init accepts nonzero',
        provenance='host-functional-model', physical_asic_compatible=False,
        signature_verified=False, installed=False))
    data = {'manifest': manifest, 'source-receipt': source_data, 'code-receipt': code_data,
            'profile': (PROFILE + '\n' + sha(manifest) + '\n').encode('ascii'),
            'env': (ENV + '=' + PROFILE + '\n').encode('ascii')}
    directory = root / 'simulation/p1-cbc-model'
    directory.mkdir(parents=True, exist_ok=False)
    build = output / 'p1-cbc'
    build.mkdir(parents=True, exist_ok=False)
    for name, content in data.items():
        (directory / name).write_bytes(content)
    assets = {n: dict(bytes=len(b), sha256=sha(b)) for n, b in data.items()}
    (build / 'p1_cbc_runtime_binding.h').write_text(runtime_header(assets), encoding='ascii')
    (root / 'init').write_text(bootstrap, encoding='ascii')
    if record(package_source) != {k: package[k] for k in ('bytes', 'sha256')}:
        raise ValueError('P1 CBC package changed during preparation')
    return dict(schema='p1-cbc-build-v1', selection=chosen, assets=assets,
                manifest=json.loads(manifest), source_receipt=json.loads(source_data),
                code_receipt=json.loads(code_data), build_directory=str(build),
                package_source=dict(path=str(Path(package_source)), **record(package_source)),
                bootstrap=record(root / 'init'), runtime_files=list(RUNTIME),
                signature_verified=False, installed=False, guest_executed=False)


def validate(value):
    if not isinstance(value, dict) or value.get('schema') != 'p1-cbc-build-v1':
        raise ValueError('Prepared P1 CBC build required')
    effective_env(value.get('selection'))
    if value.get('selection') != selection(PROFILE) or value.get('runtime_files') != list(RUNTIME):
        raise ValueError('P1 CBC selection/assets differ')
    assets = value['assets']
    for name, key in [('manifest', 'manifest'), ('source-receipt', 'source_receipt'), ('code-receipt', 'code_receipt')]:
        data = encoded(value[key])
        if assets.get(name) != dict(bytes=len(data), sha256=sha(data)):
            raise ValueError('P1 CBC compiled receipt differs: ' + name)
    m = value['manifest']
    expected = dict(profile=PROFILE, body_sha256=BODY_SHA, key_sha256=KEY_SHA, crypto_sha256=CRYPTO_SHA,
                    enabled_by_default=False, first_bytes=512, next_bytes=1024, max_streams=1,
                    source_receipt_sha256=assets['source-receipt']['sha256'],
                    code_receipt_sha256=assets['code-receipt']['sha256'])
    if any(m.get(k) != v for k, v in expected.items()):
        raise ValueError('P1 CBC fixed model fields differ')
    for name, data in [('profile', (PROFILE + '\n' + assets['manifest']['sha256'] + '\n').encode('ascii')),
                       ('env', (ENV + '=' + PROFILE + '\n').encode('ascii'))]:
        if assets.get(name) != dict(bytes=len(data), sha256=sha(data)):
            raise ValueError('P1 CBC fixed marker/environment differs')
    if value['source_receipt']['sources'] != {n: record(HERE / n) for n in SOURCES}:
        raise ValueError('P1 CBC canonical source receipt drift')
    header = Path(value['build_directory']) / 'p1_cbc_runtime_binding.h'
    if header.is_symlink() or header.read_text(encoding='ascii') != runtime_header(assets):
        raise ValueError('P1 CBC fixed compiled pin differs')
    return value


def compile_inputs(root, value):
    validate(value)
    root = Path(root)
    return ['-I', Path(value['build_directory']), '-I', HERE / 'p1-cbc-guest-abi',
            HERE / 'p1_cbc_core.c', HERE / 'p1_cbc_stream.c',
            root / 'usr/lib/libcrypto.so.1.1', root / 'lib/libpthread-2.25.so']


def extra_bindings(root, value=None):
    if value is None:
        return []
    validate(value)
    return [dict(path=str(Path(root) / n), **record(Path(root) / n)) for n in RUNTIME]


def finish(root, output, value):
    """Bind the actual generated observer after its successful native build."""
    validate(value)
    root, output = Path(root), Path(output)
    value['observer'] = record(root / 'simulation/p1-sd-observer.so')
    value['observer_source'] = record(output / 'p1-sd-observer.c')
    return value


def preflight(root, value=None, *, rows=None, cpio_path=None, cpio_bindings=None):
    """Rehash stock/source/root/audit and stream actual concatenated gzip/newc bytes."""
    if value is None:
        return None
    validate(value)
    root, sd = Path(root), sd_api()
    if package_contract(value['package_source']['path']) != value['manifest']['package']:
        raise ValueError('P1 CBC actual stock package drift')
    code = dict(trust=sd['trust_contract'](root), initializer=sd['initialize_contract'](root))
    if code != value['code_receipt'] or code['trust']['files'] != value['source_receipt']['inputs']['guest_files']:
        raise ValueError('P1 CBC original helper/initializer ABI drift')
    for name in ASSETS:
        if record(root / 'simulation/p1-cbc-model' / name) != value['assets'][name]:
            raise ValueError('P1 CBC root asset drift: ' + name)
    for name, expected in [('init', value['bootstrap']), ('simulation/p1-sd-observer.so', value['observer'])]:
        if record(root / name) != expected:
            raise ValueError('P1 CBC bootstrap/observer drift: ' + name)
    if rows is None or cpio_path is None or cpio_bindings is None:
        raise ValueError('P1 CBC requires full audit rows and actual CPIO streaming readback')
    paths = [r['path'] for r in rows]
    required = list(RUNTIME) + ['simulation/p1-sd-observer.so']
    for name in required:
        expected = dict(path=str(root / name), **record(root / name))
        if paths.count(expected['path']) != 1 or expected not in rows:
            raise ValueError('P1 CBC audit row missing or duplicate: ' + name)
    for name, text in sd['binding_texts'](root, rows).items():
        if (root / name).is_symlink() or (root / name).read_bytes() != text.encode('ascii'):
            raise ValueError('P1 CBC full audit/count drift')
    for name in list(RUNTIME) + ['init', 'simulation/p1-sd-observer.so', 'simulation/sd-read-bindings', 'simulation/sd-read-binding-count']:
        p = root / name
        expected = dict(mode=p.lstat().st_mode, **record(p))
        if cpio_bindings.get(name) != expected:
            raise ValueError('P1 CBC exact root/CPIO binding missing: ' + name)
    sd['cpio_readback'](cpio_path, cpio_bindings)
    return value
