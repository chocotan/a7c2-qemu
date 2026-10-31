#!/usr/bin/env python3
"""Current-batch, same-run thirteen-edge content proof. API: evaluate(run, batch).

Read-only graph evidence only; capture/physical ASIC/original CP/RTOS stay false.
Run with Python -B so the unmodified legacy helper imports cannot write pyc files.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tarfile
import types

NATIVE = Path(__file__).resolve().parents[2]
RUNTIME = NATIVE / 'runtime/analysis'
MAX_JSON = 4 * 1024**2
MAX_LOG = 64 * 1024**2
MAX_SOURCE = 16 * 1024**2
SELECTED_QEMU_SHA256 = 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02'
READONLY_SCOPE_QEMU_SHA256 = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
PRODUCTION_QEMU_SHA256 = 'e23589c44386c19417551c982e394b7a4e779f8e68a72f2964b705aca1e96c0d'
ALLLANG_SHA256 = '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
PUBLIC_CP_SHA256 = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
# Explicit transitive source closure, including imports made by unchanged helpers.
FROZEN_DEPENDENCIES = (
    'report/functional-graph-evidence/check_graph.py',
    'report/functional-graph-evidence/test_graph.py',
    'report/functional-graph-evidence/README.md',
    'report/functional-camera-evidence/check_evidence.py',
    'report/functional-camera-evidence/check_face_source.py',
    'report/functional-camera-evidence/test_evidence.py',
    'report/native-card-write/check_writeback.py',
    'report/capture-evidence/check_evidence.py',
    'report/cp3006-start/verify_public_seed.py',
    'runtime/analysis/backup_profile.py',
    'runtime/analysis/initramfs_identity.py',
    'runtime/analysis/tts_dmm_evidence.py',
    'runtime/analysis/hdmi_upm_watch.py',
    'runtime/analysis/build-functional-camera-model.py',
    'runtime/analysis/functional_camera_broker.py',
    'runtime/analysis/functional_camera_runner.py',
    'runtime/analysis/snapshot-observer-sources.py',
    'runtime/analysis/scratch/validate-unified-camera.py',
    'runtime/analysis/scratch/evaluate-graph-batch-native.py',
    'runtime/analysis/scratch/evaluate-six-edges-native.py',
    'runtime/analysis/scratch/evaluate-five-edges-native.py',
    'runtime/analysis/scratch/verify_hdmi_edge.py',
    'runtime/analysis/scratch/test_verify_hdmi_edge.py',
    'runtime/analysis/scratch/verify_osd_edge.py',
)
UPM_FILES = ('hdmi-upm-watch-config.json', 'hdmi-upm-watch-events.jsonl',
             'hdmi-upm-watch-result.json', 'hdmi-upm-coordinator.json')
BROKER_RECEIPTS = 'functional-camera-broker-receipts.jsonl'
RUN_FILES = ('runtime-manifest.json', 'console.log', 'functional-camera-runner.json', BROKER_RECEIPTS) + UPM_FILES
WARNINGS = tuple(b'qemu-system-aarch64: warning: vvfat: host directory commit ' + state + b'\n'
                 for state in (b'pending', b'complete'))
# imaging-control-connection.c:195 emits this exact eleven-field literal.
IMAGING_CONTROL_COMMIT_TAG = b'OBS FULL_IMAGING_CONTROL_CONNECT_COMMIT '
IMAGING_CONTROL_COMMIT = (IMAGING_CONTROL_COMMIT_TAG +
    b'connections=1 source_state=0 peer_state=0 source_pending=0 marker_readback=1 posthook_no_format=1 '
    b'prior_data_edge_preserved=1 unique_reply=1 original_cp_executed=0 frames_verified=0 capture_verified=0')
# pin-registry-core.c: only the complete canonical slot-8 OSD Get COMMIT.
PINMEM_OSD_GET_COMMIT = re.compile(
    rb'OBS FULL_PINMEM_COMMIT tid=[1-9][0-9]{0,9} slot=8 type=1 dir=3 index=0 pin_state=1 '
    rb'owner=0x90590818 status=0 queries=[1-9][0-9]{0,19} reply=0x[1-9a-f][0-9a-f]{0,15} '
    rb'lease=[1-9][0-9]{0,19} request_free_rc=0 connect_performed=0 pixels_consumed=0 camera_startup_verified=0')
PIN_QUERY_GET = re.compile(
    rb'OBS PIN_QUERY tid=[1-9][0-9]{0,9} destination=0x[1-9a-f][0-9a-f]{0,7} '
    rb'source=0x[1-9a-f][0-9a-f]{0,7} bytes=48 raw=[0-9a-f]{96}')
# pin_registry_dispatch: complete VEF Get REQUEST printf; no suffix fields.
VEF_GET_REQUEST = re.compile(
    rb'OBS FULL_VEF_REQUEST tid=[1-9][0-9]{0,9} destination=0x905a0048 '
    rb'source=0x8[0-9a-f]{7} reply_destination=0x8[0-9a-f]{7} bytes=48 raw=[0-9a-f]{96}')
# vef-device.c: all sixteen full canonical keys and their actual registry slots.
VEF_GET_SLOTS = {key + (0x905a0048,): slot for slot, key in enumerate(
    tuple((0, 1, index) for index in range(7)) + tuple((0, 2, index) for index in range(7)) +
    ((8, 1, 0), (8, 2, 0)))}
# pinmem-osd-connection.c: complete create_format and wire_from printf bodies.
OSD_FORMAT_WRITTEN = re.compile(
    rb'OBS FULL_PINMEM_OSD_CONNECT_FORMAT_WRITTEN bank=[0-3] ordinal=[0-3] '
    rb'handle=0x[1-9a-f][0-9a-f]{0,7} unit=0xe1700 extent=256 '
    rb'physical=0x[1-9a-f][0-9a-f]{0,15} cp_alias=0x[1-9a-f][0-9a-f]{0,7} '
    rb'used=(?:0|[1-9][0-9]{0,2}) known=(?:0|[1-9][0-9]{0,2}) '
    rb'fnv=[0-9a-f]{16} known_fnv=[0-9a-f]{16} pixels=0')
OSD_DMM_MESSAGE = re.compile(
    rb'OBS FULL_PINMEM_OSD_CONNECT_DMM_(?:REQUEST|REPLY) pid=[1-9][0-9]{0,9} tid=[1-9][0-9]{0,9} '
    rb'source=0x[1-9a-f][0-9a-f]{0,7} destination=0x[1-9a-f][0-9a-f]{0,7} '
    rb'pointer=0x[1-9a-f][0-9a-f]{0,15} bytes=(?:40|152) raw=(?:[0-9a-f]{80}|[0-9a-f]{304}) '
    rb'virtual_local_transport=1 original_CP_executed=0 original_CP_pages_verified=0 frames_verified=0 capture_verified=0')
# pin_registry_dispatch: PinMem's complete successful 56-byte Get queue printf.
PINMEM_GET_REPLY_QUEUED = re.compile(
    rb'OBS FULL_PINMEM_REPLY_QUEUED tid=[1-9][0-9]{0,9} source=0x90590818 '
    rb'destination=0x8[0-9a-f]{7} reply=0x[1-9a-f][0-9a-f]{0,15} '
    rb'lease=[1-9][0-9]{0,19} bytes=56 raw=[0-9a-f]{112}')
# pin_registry_release uses this identical printf for these actual owner names.
REGISTRY_GET_FREE = re.compile(
    rb'OBS FULL_(?:INFRABB|INFRAIMAGING|VEF|PINMEM|SCALAR|ADF|DRAWINFO|HDMIPIN|OSDPIN)_NATIVE_REPLY_FREE '
    rb'tid=[1-9][0-9]{0,9} sender=[1-9][0-9]{0,9} waiter=[01] '
    rb'destination=0x[1-9a-f][0-9a-f]{0,7} expected=0x[1-9a-f][0-9a-f]{0,7} '
    rb'reply=0x[1-9a-f][0-9a-f]{0,15} lease=[1-9][0-9]{0,19} bytes=56 rc=0')
# hdmi-device.c: successful full_hdmi_release_reply; command/size/status are coupled.
HDMI_NATIVE_FREE = re.compile(
    rb'OBS FULL_HDMI_NATIVE_REPLY_FREE tid=[1-9][0-9]{0,9} sender=[1-9][0-9]{0,9} waiter=[01] '
    rb'destination=0x8[0-9a-f]{7} expected=0x8[0-9a-f]{7} '
    rb'reply=0x[1-9a-f][0-9a-f]{0,15} lease=[1-9][0-9]{0,19} '
    rb'(?:command=0x10a bytes=12 status=1|command=0x(?:101|117) bytes=12 status=0|'
    rb'command=0x20a bytes=16 status=0|command=0x201 bytes=20 status=0) rc=0')
RESOURCE_TTS_FIELDS = (
    rb'pid=[1-9][0-9]{0,9} tid=[1-9][0-9]{0,9} '
    rb'appfw_base=0x[1-9a-f][0-9a-f]{0,15} table_va=0x5f66b08 address=0x[1-9a-f][0-9a-f]{0,15} '
    rb'bytes=144 reads=144/144 unchanged=1 atomic_snapshot=0 '
    rb'raw_before=(?P<table>[0-9a-f]{288}) raw_after=(?P=table) ownership_verified=0')
SCALAR_TTS_TABLE = re.compile(rb'OBS FULL_SCALAR_CONNECT_RESOURCES_TTS_TABLE ' + RESOURCE_TTS_FIELDS)
UIPC_BOUNDARIES = {
    'FULL_HDMI_NATIVE_REPLY_FREE': ('HdmiNativeFree', HDMI_NATIVE_FREE),
    'FULL_SCALAR_CONNECT_RESOURCES_TTS_TABLE': ('ScalarTtsTable', SCALAR_TTS_TABLE),
    'FULL_PINMEM_COMMIT': ('PinMem', PINMEM_OSD_GET_COMMIT),
    'FULL_PINMEM_REPLY_QUEUED': ('PinMemGetReply', PINMEM_GET_REPLY_QUEUED),
    'PIN_QUERY': ('PinQuery', PIN_QUERY_GET),
    'FULL_PINMEM_OSD_CONNECT_FORMAT_WRITTEN': ('OsdFormat', OSD_FORMAT_WRITTEN),
    **{'FULL_PINMEM_OSD_CONNECT_DMM_' + kind: ('OsdDmm', OSD_DMM_MESSAGE) for kind in ('REQUEST', 'REPLY')},
    **{'FULL_' + owner + '_NATIVE_REPLY_FREE': ('RegistryGetFree', REGISTRY_GET_FREE) for owner in
       ('INFRABB', 'INFRAIMAGING', 'VEF', 'PINMEM', 'SCALAR', 'ADF', 'DRAWINFO', 'HDMIPIN', 'OSDPIN')},
}
# infrabb-registry.c: complete full-key table; no run/slot/offset selection.
INFRABB_GET_SLOTS = {key + (0x9284074a,): slot for slot, key in enumerate((
    (0, 1, 0), (0, 1, 1), (0, 1, 2), (0, 1, 3), (0, 2, 0), (0, 2, 1), (0, 2, 2), (0, 2, 3),
    (8, 1, 0), (8, 2, 0), (6, 2, 0),
    (0, 1, 10), (0, 1, 11), (0, 1, 12), (0, 1, 13), (0, 2, 10), (0, 2, 11), (0, 2, 12), (0, 2, 13),
    (8, 1, 10), (8, 2, 10)))}
# GPL cdev.c:100 + udif/macros.h; printk.c supplies the canonical timestamp.
UIPC_IOCTL_WARNING = re.compile(
    rb'\[( {0,4}[0-9]{1,11})\.([0-9]{6})\] UDIF: cdev_ioctl\(\) Line 100: uipc: warning ret = -1022\r\n')
GRAPH_ROOTS = ('FULL_IMAGING_', 'FULL_INFRABB_', 'FULL_INFRAIMAGING_', 'FULL_VEF_',
               'FULL_SCALAR_', 'FULL_ADF_', 'FULL_PINMEM_', 'FULL_HDMIPIN_',
               'FULL_HDMI_', 'FULL_OSDPIN_', 'FULL_DRAWINFO_')
# These producers emit a leading reason literal before any key=value fields.
GRAPH_BARE_REASONS = {
    'FULL_SCALAR_CONNECT_UNADMITTED': 'predecessor-or-new-cold-Get-free-not-ready',
    'FULL_ADF_CONNECT_UNADMITTED': 'predecessor-or-new-cold-Get-free-not-ready',
    'FULL_PINMEM_DRAWINFO_CONNECT_UNADMITTED': 'predecessor-or-new-cold-Get-free-not-ready',
    'FULL_PINMEM_HDMI_VIDEO_CONNECT_UNADMITTED': 'predecessor-canonical-Get-or-resource-guard-unavailable',
    'FULL_PINMEM_OSD_CONNECT_UNADMITTED': 'first10-AP-or-exact-retired-Get-or-pool-not-ready',
    'FULL_HDMI_VIDEO_STATE_PENDING': 'waiting-for-actual-UPM-and-condition-receive-free',
}


class SourceMissing(ValueError):
    pass


class UnjoinedRepairs(ValueError):
    def __init__(self, repairs):
        super().__init__('repaired record lacks an actual content-verifier join')
        self.repairs = [{'kind': r['kind'], 'parsed_line': r['parsed_line'],
                         'tag': r['repaired_record'].split(' ', 2)[1],
                         'repaired_record_sha256': r['repaired_record_sha256'],
                         **{k: r[k] for k in ('raw_record_start', 'raw_lf_line', 'raw_warning_start') if k in r}}
                        for r in repairs]


def require(ok, detail):
    if not ok:
        raise ValueError(str(detail))


def needed(ok, detail):
    if not ok:
        raise SourceMissing(str(detail))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def absolute(value):
    text = os.fspath(value)
    path = Path(text)
    require(path.is_absolute() and str(path) == text and '..' not in path.parts and path != Path('/'),
            'explicit canonical absolute path required')
    require(path.resolve() == path, 'symlinked input path')
    return path


def read(path, limit=MAX_SOURCE):
    """Bounded owned regular-file read; no symlink, hardlink or replacement."""
    path = absolute(path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        source = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    with os.fdopen(source, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and before.st_nlink == 1 and
                not before.st_mode & 0o022 and before.st_size <= limit, 'unsafe/oversized input: ' + str(path))
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(len(raw) == before.st_size and identity(before) == identity(after), 'changed/short input: ' + str(path))
        return raw


def object_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: require(False, 'nonfinite JSON value'))
    require(type(value) is dict, 'JSON object required')
    return value


def check_dependency_hashes(frozen):
    """Check the full closure before any content helper is imported or called."""
    hashes = {}
    for name in FROZEN_DEPENDENCIES:
        path = NATIVE / name
        expected = frozen.get(str(path))
        needed(expected is not None, 'inputs.json missing frozen dependency: ' + name)
        require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), 'bad dependency digest: ' + name)
        require(sha(read(path)) == expected, 'current/frozen dependency SHA differs: ' + name)
        hashes[name] = expected
    return hashes


def frozen_inputs(batch):
    batch = absolute(batch)
    if batch.name == 'ready.json':
        batch = batch.parent
    require(batch.is_dir() and batch.stat().st_uid == os.geteuid() and not batch.stat().st_mode & 0o022,
            'unsafe/missing completed batch directory')
    ready_raw, inputs_raw = read(batch / 'ready.json', MAX_JSON), read(batch / 'inputs.json', MAX_JSON)
    ready, inputs = object_json(ready_raw), object_json(inputs_raw)
    require(ready.get('capture_verified') is False and inputs.get('capture_verified') is False,
            'batch scope promoted capture')
    require(ready.get('inputs_sha256') == sha(inputs_raw), 'current ready/inputs SHA differs')
    groups = inputs.get('groups')
    require(type(groups) is dict and set(groups) == {'production', 'host', 'observer', 'test'}, 'frozen source groups differ')
    frozen = {}
    for group in groups.values():
        require(type(group) is dict and group, 'empty frozen source group')
        for name, digest in group.items():
            path = absolute(name)
            require(path.is_relative_to(NATIVE), 'frozen source outside native package')
            require(name not in frozen or frozen[name] == digest, 'conflicting frozen source digests')
            frozen[name] = digest
    dependencies = check_dependency_hashes(frozen)
    return batch, frozen, dependencies


def source_module(relative, frozen):
    """Compile exact frozen source, with its real __file__; never rewrite helpers."""
    require(sys.dont_write_bytecode, 'invoke with python3 -B; unchanged helper imports must not create bytecode')
    path = NATIVE / relative
    raw = read(path)
    require(frozen.get(str(path)) == sha(raw), 'unfrozen/changed imported source: ' + relative)
    module = types.ModuleType('_functional_graph_' + relative.replace('/', '_').replace('.', '_').replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def load_content_helpers(frozen):
    check_dependency_hashes(frozen)
    batch = source_module('runtime/analysis/scratch/evaluate-graph-batch-native.py', frozen)
    hdmi = source_module('runtime/analysis/scratch/verify_hdmi_edge.py', frozen)
    osd = source_module('runtime/analysis/scratch/verify_osd_edge.py', frozen)
    return batch, hdmi, osd


def check_qemu_files(reader, manifest, frozen=None):
    backup, files = manifest['backup_transport'], manifest['files']
    selected = backup.get('binary_sha256')
    require(selected in (SELECTED_QEMU_SHA256, READONLY_SCOPE_QEMU_SHA256) and
            files.get(backup.get('binary')) == selected,
            'selected candidate QEMU must be a0d or the exact readonly candidate; e235 is the production reference')
    reader.digest_binding(reader.read_absolute(backup['binary']), selected, 'actual selected candidate QEMU')
    if selected == READONLY_SCOPE_QEMU_SHA256 or manifest.get('readonly_scope_observer') is not None:
        reader.check_readonly_scope_observer(manifest, selected, frozen)
    production = RUNTIME.parent / 'sources/qemu-11.1.2/build-sony-ui/qemu-system-aarch64'
    reader.digest_binding(reader.read_absolute(production), PRODUCTION_QEMU_SHA256, 'unchanged production QEMU reference')
    return {'selected_candidate_sha256': selected, 'unchanged_production_sha256': PRODUCTION_QEMU_SHA256}


def check_current_batch(reader, run, batch, manifest):
    """Current receipts using shared pure readers; actual candidate and production differ.

    The capture checker's check_batch() historically conflated these two QEMUs.
    Its constants/functions are never altered, rebound, or text-transformed here.
    """
    ready_raw = reader.read(batch, 'ready.json', MAX_JSON)
    ready = reader.object_json(ready_raw)
    require(ready.get('capture_verified') is False, 'batch scope promoted capture')
    names = {'inputs.json': 'inputs_sha256', 'host-regression.json': 'regression_sha256',
             'abi.json': 'abi_sha256', 'inputs.tar.gz': 'all_input_archive_sha256',
             'functional-camera-model.so': 'functional_model_library_sha256',
             'functional-model-sources.tar.gz': 'functional_model_source_archive_sha256',
             'functional-camera-model-build.json': 'functional_model_build_receipt_sha256'}
    raw = {}
    for name, field in names.items():
        needed(field in ready, 'ready.json missing ' + field)
        raw[name] = reader.read(batch, name)
        reader.digest_binding(raw[name], ready[field], name)
    inputs, regression, abi, model = (reader.object_json(raw[name]) for name in
        ('inputs.json', 'host-regression.json', 'abi.json', 'functional-camera-model-build.json'))
    groups, frozen = reader.frozen_sources(inputs)
    reader.archive(raw['inputs.tar.gz'], {str(Path(name).relative_to(NATIVE)): digest for name, digest in frozen.items()})
    require(type(regression.get('returncode')) is int and regression['returncode'] == 0 and
            regression.get('capture_verified') is False and
            reader.typed_equal(regression.get('changed'), {key: [] for key in groups}) and
            regression.get('inputs_sha256') == sha(raw['inputs.json']), 'failed/changed frozen host regression')
    count = reader.uint(regression.get('tests_passed'), 1000000)
    require(count > 0, 'empty regression pass count')
    log = reader.read(batch, 'host-regression.log', MAX_LOG)
    reader.digest_binding(log, regression.get('log_sha256'), 'actual host regression log')
    require(re.search(rb'\b' + str(count).encode() + rb' passed\b', log), 'actual regression count/log differs')
    marker = 'PASS: constructor thread and application-init wrapper preserved behavior'
    media = abi.get('media_preload')
    require(type(abi.get('returncode')) is int and abi['returncode'] == 0 and abi.get('capture_verified') is False and
            abi.get('regression_sha256') == sha(raw['host-regression.json']) and marker in abi.get('stdout', '') and
            type(media) is dict and type(media.get('returncode')) is int and media['returncode'] == 0 and
            marker in media.get('stdout', '') and media.get('bind_now') is True,
            'both actual original-libc observer/media ABI executions required')
    build_raw = reader.read(run, 'observer-build-inputs.json', MAX_JSON)
    build = reader.object_json(build_raw)
    require(reader.typed_equal(build, manifest.get('compiled_observer')) and
            manifest.get('selected_observer_matches_build') is True, 'same-run observer build differs')
    sources = build.get('sources')
    require(type(sources) is dict and {name: row['sha256'] for name, row in sources.items()} == groups['production'] and
            type(abi.get('source_count')) is int and abi['source_count'] == len(sources) and
            abi.get('observer_sha256') == build.get('observer_sha256') and
            abi.get('source_archive_sha256') == build.get('source_archive_sha256'),
            'observer differs from exact current tested/ABI-bound production sources')
    observed_archive = reader.read(run, 'observer-build-sources.tar.gz')
    reader.digest_binding(observed_archive, build.get('source_archive_sha256'), 'same-run observer source archive')
    index = {row['archive_path']: row['sha256'] for row in sources.values()}
    require(len(index) == len(sources) and 'source-inputs.json' not in index,
            'duplicate/reserved observer archive source path')
    index_raw, member_count, archive_bytes = None, 0, 0
    with tarfile.open(fileobj=io.BytesIO(observed_archive), mode='r:gz') as archive:
        for member in archive:
            member_count += 1
            archive_bytes += member.size
            require(member_count <= 8192 and 0 <= member.size <= MAX_SOURCE and archive_bytes <= reader.MAX_FILE and
                    (member.isfile() or member.isdir() and member.size == 0), 'observer archive traversal exceeds bounds')
            if member.name == 'source-inputs.json':
                require(index_raw is None and member.isfile() and member.size <= MAX_JSON,
                        'observer archive source index ambiguous/oversized')
                with archive.extractfile(member) as item:
                    index_raw = item.read(MAX_JSON + 1)
    needed(index_raw is not None, 'observer archive source-inputs.json missing')
    require(reader.typed_equal(reader.object_json(index_raw), sources), 'archived observer index differs')
    index['source-inputs.json'] = sha(index_raw)
    reader.archive(observed_archive, index)
    selected, files = manifest.get('selected_initramfs_verified_files'), manifest.get('files')
    require(type(selected) is dict and type(files) is dict and manifest.get('original_libraries_unchanged') is True,
            'original selected library identity missing')
    for name, digest in {'simulation/menu-observe.so': abi['observer_sha256'],
                         'simulation/file-media-config.so': abi['media_preload_sha256']}.items():
        require(selected.get(name) == digest, 'selected observer/media differs: ' + name)
        reader.digest_binding(reader.read(RUNTIME / 'menu-root', name), digest, 'actual selected asset ' + name)
    require(files.get(str(RUNTIME / 'observer-build-inputs.json')) == sha(build_raw) and
            files.get(str(RUNTIME / 'menu-observe.so')) == abi['observer_sha256'], 'indexed observer/build differs')
    reader.digest_binding(reader.read(RUNTIME, 'menu-observe.so'), abi['observer_sha256'], 'actual observer')
    omissions = []
    for name, digest in groups['host'].items():
        if name in files:
            require(files[name] == digest, 'run/frozen host source differs: ' + name)
        else:
            require(Path(name).name == 'build-functional-camera-model.py', 'run host implementation not indexed: ' + name)
            omissions.append(name)
    for name, digest in files.items():
        if name in frozen:
            require(digest == frozen[name], 'manifest frozen source differs: ' + name)
    qemu = check_qemu_files(reader, manifest, frozen)
    require(model.get('profile') == 'virtual-functional-camera-v1' and model.get('capture_verified') is False and
            model.get('physical_asic_compatibility_verified') is False and model.get('sources'), 'host-model scope differs')
    for name, digest in model['sources'].items():
        require(frozen.get(str(NATIVE / reader.writeback.relative_path(name))) == digest, 'model source not frozen: ' + name)
    reader.archive(raw['functional-model-sources.tar.gz'], model['sources'])
    reader.digest_binding(raw['functional-model-sources.tar.gz'], model.get('source_archive_sha256'), 'model source archive')
    library = raw['functional-camera-model.so']
    reader.digest_binding(library, model.get('library_sha256'), 'actual model library')
    require(library[:7] == b'\x7fELF\x02\x01\x01' and len(library) >= 64 and
            struct.unpack_from('<H', library, 16)[0] == 3 and struct.unpack_from('<H', library, 18)[0] in (62, 183),
            'model must be a supported host ELF64 shared library')
    for name in ('functional-camera-model.so', 'functional-camera-model-build.json'):
        require(reader.read(RUNTIME, name) == raw[name], 'published runtime model/build differs: ' + name)
    work = NATIVE / reader.writeback.relative_path(model['work'])
    require(work.parent == RUNTIME / 'scratch' and work.name.startswith('functional-model-build-'), 'untrusted model work')
    compiled_raw = reader.read(work, 'compile.json', MAX_JSON)
    reader.digest_binding(compiled_raw, model.get('compile_receipt_sha256'), 'actual model compile receipt')
    compiled = reader.object_json(compiled_raw)
    require(type(compiled.get('returncode')) is int and compiled['returncode'] == 0 and
            {'-shared', '-fPIC', '-Wl,--no-undefined'} <= set(compiled.get('command', [])), 'actual model build failed')
    reader.digest_binding(reader.read(work, 'build.log'), compiled.get('log_sha256'), 'actual model compiler log')
    return {'batch': str(batch), 'ready_sha256': sha(ready_raw), 'tests_passed': count,
            'observer_sha256': abi['observer_sha256'], 'source_count': len(sources),
            'model_sha256': model['library_sha256'], 'model_build_sha256': sha(raw['functional-camera-model-build.json']),
            'model_source_archive_sha256': model['source_archive_sha256'], 'qemu_sha256': qemu['selected_candidate_sha256'],
            'unchanged_production_qemu_sha256': PRODUCTION_QEMU_SHA256,
            'host_build_source_index_omissions': omissions, 'current_frozen_sources_equal': True}, frozen


def check_production_sources(batch, frozen):
    inputs = object_json(read(batch / 'inputs.json', MAX_JSON))
    source_api = source_module('runtime/analysis/snapshot-observer-sources.py', frozen)
    actual = {str(path): sha(read(path)) for path in source_api.source_paths(RUNTIME)}
    require(actual == inputs['groups']['production'],
            'production group differs from actual current source_paths closure')
    for name in ('build-functional-camera-model.py', 'functional_camera_broker.py', 'functional_camera_runner.py'):
        path = str(RUNTIME / name)
        require(inputs['groups']['host'].get(path) == frozen[path], 'current functional host source group missing: ' + name)
    return {'production_source_count': len(actual), 'exact_current_source_paths_verified': True}


def check_graph_profiles(manifest, batch, hdmi, osd, profile):
    backup = manifest['backup_transport']
    for _, key, value, _, _ in batch.six.SPECS + batch.NEW:
        require(manifest.get(key + '_profile') == backup.get(key + '_profile') == value,
                'actual graph profile differs: ' + key)
        for suffix in ('capture_verified', 'native_verified', 'ap_consumed', 'connection_verified',
                       'connections_verified', 'frames_verified'):
            field = key + '_' + suffix
            if field in manifest or field in backup:
                require(manifest.get(field) is False and backup.get(field) is False, 'intent promoted graph proof: ' + field)
    for function, value in ((profile.pinmem_hdmi_video_connection_profile_fields, hdmi.PROFILE),
                            (profile.pinmem_osd_connection_profile_fields, osd.PROFILE)):
        for key, expected in function(value).items():
            require(key in manifest and key in backup and profile_value_equal(manifest[key], expected) and
                    profile_value_equal(backup[key], expected), 'typed graph intent differs: ' + key)
    return {'all_thirteen_profiles_verified': True, 'state_source': 'explicit-virtual-model-not-original-CP-RAM-RTOS'}


def profile_value_equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(actual) is list:
        return len(actual) == len(expected) and all(profile_value_equal(a, e) for a, e in zip(actual, expected))
    if type(actual) is dict:
        return actual.keys() == expected.keys() and all(profile_value_equal(actual[k], v) for k, v in expected.items())
    return actual == expected


def parse_record(line):
    """Validate fields after an exact producer-defined reason, retaining raw bytes."""
    match = re.fullmatch(rb'OBS ([A-Z][A-Z0-9_]*) ([^\r\n]+)\r?\n', line)
    require(match, 'incomplete/interleaved OBS record')
    tag = match[1].decode()
    tokens = match[2].decode('ascii', 'strict').split()
    if tokens and tokens[0] == GRAPH_BARE_REASONS.get(tag):
        tokens = tokens[1:]
    fields = {}
    for token in tokens:
        require(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*=[^\s=]+', token), 'malformed OBS field: ' + token)
        key, value = token.split('=', 1)
        require(key not in fields, 'duplicate OBS field: ' + key)
        fields[key] = value
    return tag, fields


def console_records(raw):
    """Separate exact host diagnostics, preserving all supplied guest payload bytes.

    A repaired record is provisional until a content verifier consumes that exact
    record. No historical digest, offset, inferred suffix or log is consulted.
    """
    require(type(raw) is bytes and len(raw) <= MAX_LOG, 'console read budget exceeded')
    output, repairs, raw_offset, parsed_line = [], [], 0, 0
    lines = raw.split(b'\n')
    lines = [line + b'\n' for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
    index = 0
    while index < len(lines):
        record, start, raw_lf_line = lines[index], raw_offset, index + 1
        raw_offset += len(lines[index]); index += 1
        pending = []
        match = re.match(rb'OBS ([A-Z][A-Z0-9_]*) ', record)
        tag = match[1].decode() if match else ''
        relevant = tag.startswith(GRAPH_ROOTS) or tag in ('PIN_QUERY', 'PIN_CONTROL_REQUEST')
        partial_commit_tag = any(record.endswith(w) and
            len(b'OBS ') < len(record) - len(w) < len(IMAGING_CONTROL_COMMIT_TAG) and
            IMAGING_CONTROL_COMMIT_TAG.startswith(record[:-len(w)]) for w in WARNINGS)
        # Unrelated diagnostics remain raw and cannot become graph evidence.
        while (relevant or partial_commit_tag) and any(record.endswith(w) for w in WARNINGS):
            warning = next(w for w in WARNINGS if record.endswith(w))
            position = start + len(record) - len(warning) + sum(r['removed_bytes'] for r in pending)
            needed(index < len(lines), 'console ends inside an OBS/host-warning interleaving')
            pending.append({'kind': 'exact-host-vvfat-diagnostic', 'raw_warning_start': position,
                            'raw_warning_end': position + len(warning), 'removed_bytes': len(warning),
                            'host_record': warning.decode().rstrip('\n'), 'guest_bytes_invented': False})
            record = record[:-len(warning)] + lines[index]
            raw_offset += len(lines[index]); index += 1
            require(len(record) <= 16384 and len(pending) <= 8, 'interleaving reconstruction budget exceeded')
        if partial_commit_tag:
            require(record in (IMAGING_CONTROL_COMMIT + b'\n', IMAGING_CONTROL_COMMIT + b'\r\n'),
                    'unproved imaging-control COMMIT producer literal after tag repair')
            tag, _ = parse_record(record)
            relevant = True
            for repair in pending:
                repair.update(cause='unknown', raw_record_start=start, raw_record_end=raw_offset,
                              raw_lf_line=raw_lf_line, raw_lf_end=index,
                              raw_record_hex=raw[start:raw_offset].hex(), raw_record_sha256=sha(raw[start:raw_offset]),
                              guest_payload_unchanged=True)
        if tag in ('FULL_SCALAR_CONNECT_RESOURCES_TTS_TABLE', 'FULL_HDMI_NATIVE_REPLY_FREE',
                   'FULL_PINMEM_REPLY_QUEUED'):
            boundary, grammar = UIPC_BOUNDARIES[tag]
            payload = record.partition(b'[')[0] if b'UDIF:' in record else record.rstrip(b'\r\n')
            require(grammar.fullmatch(payload),
                    f'unproved complete {boundary} record: malformed OBS field or suffix')
            fields = parse_record(payload + b'\r\n')[1]
            if boundary == 'ScalarTtsTable':
                base = int(fields['appfw_base'], 16)
                require(all(int(fields[name]) < 2**31 for name in ('pid', 'tid')) and
                        0x10000 <= base < 0x7ff0000000 and int(fields['address'], 16) == base + 0x5f66b08,
                        'ScalarTtsTable producer integer/address bounds differ')
            elif boundary == 'PinMemGetReply':
                require(int(fields['tid']) < 2**31 and int(fields['lease']) < 2**64 and
                        int(fields['destination'], 16) & 0xfffffff,
                        'PinMemGetReply producer integer/destination bounds differ')
            else:
                require(all(int(fields[name]) < 2**31 for name in ('tid', 'sender')) and int(fields['lease']) < 2**64 and
                        fields['destination'] == fields['expected'] and int(fields['destination'], 16) & 0xfffffff and
                        int(fields['waiter']) == int(fields['tid'] == fields['sender']),
                        'HdmiNativeFree successful producer integer/ownership bounds differ')
        host = b''
        if tag in UIPC_BOUNDARIES and b'UDIF:' in record:
            boundary, grammar = UIPC_BOUNDARIES[tag]
            guest, separator, kernel = record.partition(b'[')
            kernel = separator + kernel
            timestamp = UIPC_IOCTL_WARNING.fullmatch(kernel)
            require(grammar.fullmatch(guest) and timestamp and len(record) <= 1024,
                    f'unproved complete {boundary}/UIPC boundary: malformed OBS field or kernel')
            seconds, micros = int(timestamp[1]), int(timestamp[2])
            require(seconds * 10**6 + micros <= (2**64 - 1) // 1000 and
                    kernel.startswith(f'[{seconds:5d}.{micros:06d}] '.encode()), 'noncanonical kernel timestamp')
            fields = parse_record(guest + b'\r\n')[1]
            require(all(int(fields[name]) < 2**31 for name in ('pid', 'tid', 'sender') if name in fields) and
                    all(int(fields[name]) < 2**64 for name in ('queries', 'lease') if name in fields),
                    f'{boundary} producer integer bounds exceeded')
            if boundary == 'PinQuery':
                require(bytes.fromhex(fields['raw'])[4:8] == b'\xa0' * 4,
                        'PinQuery producer message marker differs')
            elif boundary == 'OsdFormat':
                require(int(fields['used']) <= 256 and int(fields['known']) <= 256,
                        'OsdFormat producer extent bounds exceeded')
            elif boundary == 'OsdDmm':
                require(len(bytes.fromhex(fields['raw'])) == int(fields['bytes']),
                        'OsdDmm complete source wire length differs')
            needed(index < len(lines), f'{boundary}/UIPC boundary lacks the original guest line ending')
            require(lines[index] == b'\r\n', f'{boundary}/UIPC boundary has a nonempty/interrupted guest suffix')
            kernel_start = start + len(guest) + sum(r['removed_bytes'] for r in pending)
            require(raw[kernel_start:raw_offset] == kernel and raw[raw_offset:raw_offset + 2] == b'\r\n',
                    f'raw {boundary}/UIPC boundary bytes differ')
            pending.append({'kind': f'complete-{boundary}-UIPC-boundary', 'raw_record_start': start,
                            'raw_kernel_start': kernel_start, 'raw_kernel_end': raw_offset,
                            'raw_guest_ending_start': raw_offset, 'raw_guest_ending_end': raw_offset + 2,
                            'kernel_record': kernel.decode().rstrip('\r\n'), 'removed_bytes': 0,
                            'framing_bytes_inserted': 0, 'guest_bytes_invented': False})
            original = raw[start:raw_offset]
            pending[-1].update(cause='unknown', raw_lf_line=raw_lf_line,
                               raw_record_hex=original.hex(), raw_record_sha256=sha(original),
                               kernel_raw_hex=kernel.hex(), kernel_sha256=sha(kernel),
                               guest_payload_unchanged=True)
            record, host = guest + lines[index], kernel
            raw_offset += len(lines[index]); index += 1
        # One complete guest record can immediately precede a complete host DFS record.
        marker = b'capture_verified=0SONY_DFS_REQUEST '
        if relevant and marker in record:
            require(record.count(marker) == 1, 'ambiguous complete DFS/guest join')
            split = record.index(marker) + len(b'capture_verified=0')
            guest, host = record[:split] + b'\r\n', record[split:]
            require(re.fullmatch(rb'SONY_DFS_REQUEST target=0x[0-9a-f]{8} generation=[1-9][0-9]* '
                                 rb'readback_request=0x[0-9a-f]{8} readback_ckstatus=0x[0-9a-f]{8} '
                                 rb'delay_ns=[0-9]+ virtual_selector=1 clocks_changed=0\r?\n', host),
                    'unproved complete host DFS record')
            pending.append({'kind': 'complete-guest-host-DFS-boundary', 'raw_record_start': start,
                            'host_record': host.decode().rstrip('\r\n'), 'removed_bytes': 0,
                            'framing_bytes_inserted': 2, 'guest_bytes_invented': False})
            record = guest
        if record.startswith(b'OBS '):
            if relevant or pending:
                parse_record(record)
                require(not pending or relevant, f'host repair outside graph content scope: {tag} raw_offset={start}')
        else:
            require(not pending, 'host diagnostic erased record framing')
        require(len(record) <= 16384, 'console record exceeds budget')
        for repair in pending:
            require(raw[repair['raw_warning_start']:repair['raw_warning_end']] in WARNINGS
                    if repair['kind'] == 'exact-host-vvfat-diagnostic' else True, 'raw host insertion bytes differ')
            repair.update(parsed_line=parsed_line + 1, repaired_record_sha256=sha(record.rstrip(b'\r\n')),
                          repaired_record=record.rstrip(b'\r\n').decode('ascii'))
        repairs += pending
        output.append(record)
        parsed_line += record.count(b'\n')
        if host:
            output.append(host)
            parsed_line += host.count(b'\n')
    return b''.join(output), repairs


def check_late_failures(log, first_graph_request):
    for row in log.records:
        if row['line'] >= first_graph_request and row['tag'].startswith(GRAPH_ROOTS):
            require(not row['tag'].endswith(('_UNSUPPORTED', '_UNADMITTED', '_FAULT', '_REFUSED', '_REJECT')),
                    'graph-phase failure/refusal retained: ' + row['tag'])


def check_role_messages(edge, identity):
    """Roles come from original native 64B messages, not a caller-authored census."""
    request = edge['REQUEST']
    original = bytes.fromhex(request['fields']['raw'])
    require(len(original) == 64, 'original native graph request must be complete 64B')
    roles = struct.unpack_from('<8I', original, 32)
    caller = struct.unpack_from('<I', original)[0]
    require(roles == tuple(edge['source_pin']) + tuple(edge['sink_pin']) and caller == edge['caller'],
            'graph roles differ from actual original message')
    producer = request['fields'].get('producer_tid', request['fields'].get('tid'))
    require(request['fields'].get('pid') == identity[0] and producer == identity[1], 'original AP owner differs')
    freed = edge['REPLY_FREE']
    require(freed['fields'].get('pid') == identity[0] and freed['fields'].get('tid') == identity[1] and
            freed['fields'].get('bytes') == '56' and freed['fields'].get('rc') == '0' and
            freed['fields'].get('ap_consumed') == '1', 'actual 56B original AP same-thread free missing')
    return {'source_pin': list(roles[:4]), 'peer_pin': list(roles[4:]), 'original_caller_sid': caller,
            'original_request_sha256': sha(original), 'original_AP_pid': int(identity[0]),
            'original_AP_tid': int(identity[1]), 'actual_AP_reply_free': freed}


def check_graph_content(log, run, batch, hdmi, osd):
    edges, identity, resources, early = batch.six.verify_graph(log)
    require(all(str(int(v)) == v and int(v) > 1 for v in identity), 'invalid actual original AP PID/TID')
    first = edges[0]['REQUEST']['line']
    check_late_failures(log, first)
    legacy = batch.verify_legacy(log, identity, first)
    added, previous = [], edges[-1]['REPLY_FREE']['line']
    for spec in batch.NEW[:-1]:
        edge = batch.verify_new_edge(log, spec, previous, identity, first)
        added.append(edge)
        previous = edge['REPLY_FREE']['line']
    video = hdmi.verify_hdmi_edge(log, previous, identity, first, run)
    osd_edge = osd.verify_osd_edge(log, video['REPLY_FREE']['line'], identity, first, batch)
    audio = batch.verify_new_edge(log, batch.NEW[-1], osd_edge['REPLY_FREE']['line'], identity, first)
    batch.verify_new_effects(log, added + [audio], identity)
    edges += added + [video, osd_edge, audio]
    require(len(edges) == 13 and len({e['prefix'] if 'prefix' in e else e['REQUEST']['tag'] for e in edges}) == 13,
            'requires thirteen distinct actual edge transactions')
    roles = [check_role_messages(e, identity) for e in edges]
    return {'edges': edges, 'roles': roles, 'identity': identity, 'resources': resources,
            'early_unadmitted_requests': early, 'legacy_histories': legacy,
            'full_input_audits': batch.verify_audits(log)}


def check_repaired_queries(log, repairs, proof, batch):
    """Join complete repaired BB queries through the unchanged Get body and free.

    Other owners must already occur in the actual graph content proof. The BB
    extension uses an isolated globals copy, as the existing OSD helper does.
    """
    joins = []
    for repair in repairs:
        if repair['kind'] not in ('complete-PinQuery-UIPC-boundary', 'exact-host-vvfat-diagnostic') or not repair['repaired_record'].startswith('OBS PIN_QUERY '):
            continue
        require(PIN_QUERY_GET.fullmatch(repair['repaired_record'].encode().rstrip(b'\r\n')),
                'repaired query differs from the complete original producer grammar')
        rows = [row for row in log.rows('PIN_QUERY') if row['line'] == repair['parsed_line'] and
                row['raw'] == repair['repaired_record']]
        require(len(rows) == 1, 'repaired query lost its exact parsed record')
        query = rows[0]
        if query['fields']['destination'] != '0x9284074a':
            continue
        wire = batch.raw_bytes(query, 48)
        key = struct.unpack_from('<3I', wire, 32) + (0x9284074a,)
        require(key in INFRABB_GET_SLOTS, 'repaired query has an unsupported canonical BB key')
        caller = struct.unpack_from('<I', wire)[0]
        require(caller >> 28 == 8 and caller & 0xfffffff, 'repaired query has a nonlocal/zero AP caller')
        before = min(batch.old.next_pin_send(log, query), proof['edges'][0]['REQUEST']['line'])
        def get_frame(length, opcode, kind, words, caller=0, opaque=bytes(4)):
            # BB sets reply_sid to its own SID in infrabb-registry.c.
            if length == 56 and opcode == 0x8000:
                caller = 0x9284074a
            return batch.old.frame_bytes(length, opcode, kind, words, caller, opaque)
        namespace = dict(batch.verify_get.__globals__, frame_bytes=get_frame,
                         OWNERS={**batch.OWNERS, key[3]: ('INFRABB', None)},
                         SLOTS={**batch.SLOTS, **INFRABB_GET_SLOTS})
        verify_get = types.FunctionType(batch.verify_get.__code__, namespace)
        content = verify_get(log, key, proof['identity'], caller, query['line'] - 1, before)
        require(content['original_AP_query'] is query, 'repaired query borrowed another Get record')
        joins.append(content)
    return joins


def check_repaired_vef_gets(log, repairs, proof, batch):
    """Consume repaired VEF requests using the unchanged canonical Get verifier."""
    joins = []
    for repair in repairs:
        if repair['kind'] != 'exact-host-vvfat-diagnostic' or not repair['repaired_record'].startswith('OBS FULL_VEF_REQUEST '):
            continue
        require(VEF_GET_REQUEST.fullmatch(repair['repaired_record'].encode()),
                'repaired VEF request differs from complete producer grammar')
        rows = [row for row in log.rows('FULL_VEF_REQUEST') if row['line'] == repair['parsed_line'] and
                row['raw'] == repair['repaired_record']]
        require(len(rows) == 1, 'repaired VEF request lost its exact parsed record')
        request = rows[0]
        require(parse_record(request['raw'].encode() + b'\r\n') == (request['tag'], request['fields']),
                'repaired VEF fields differ from actual record bytes')
        wire = batch.raw_bytes(request, 48)
        key = struct.unpack_from('<3I', wire, 32) + (0x905a0048,)
        require(key in VEF_GET_SLOTS, 'repaired VEF request has an unsupported canonical key')
        identity = proof['identity']
        require(len(identity) == 2 and all(str(int(value)) == value and 1 < int(value) < 2**31 for value in identity),
                'repaired VEF Get lacks a canonical original AP identity')
        edges = proof['edges']
        matches = [index for index in range(1, len(edges)) if
                   edges[index - 1]['REPLY_FREE']['line'] < request['line'] < edges[index]['REQUEST']['line']]
        require(len(matches) == 1, 'repaired VEF Get lacks one adjacent completed graph edge')
        index = matches[0]
        edge, predecessor = edges[index], edges[index - 1]
        ordered = batch.six.SPECS + batch.NEW
        specs = {spec[0]: spec for spec in ordered}
        adjacent = {(left[0] + '_REQUEST', right[0] + '_REQUEST') for left, right in zip(ordered, ordered[1:])}
        require((predecessor['REQUEST']['tag'], edge['REQUEST']['tag']) in adjacent,
                'repaired VEF Get canonical predecessor differs')
        require(key in (tuple(edge['source_pin']), tuple(edge['sink_pin'])),
                'repaired VEF Get key differs from actual adjacent edge roles')
        for anchor in (predecessor, edge):
            prefix = anchor['REQUEST']['tag'].removesuffix('_REQUEST')
            require(prefix in specs and (tuple(anchor['source_pin']), tuple(anchor['sink_pin'])) == specs[prefix][3:],
                    'repaired VEF Get adjacent edge is not canonical')
            require(anchor['REPLY_FREE']['tag'] == prefix + '_REPLY_FREE', 'repaired VEF Get adjacent AP free tag differs')
            for name in ('REQUEST', 'REPLY_FREE'):
                require(log.one(anchor[name]['tag']) is anchor[name], 'repaired VEF Get borrowed an adjacent edge record')
            check_role_messages(anchor, identity)
            _, caller = batch.old.request_bytes(anchor['REQUEST'], anchor['source_pin'], anchor['sink_pin'])
            require(caller == anchor['caller'] and anchor['REQUEST']['line'] < anchor['REPLY_FREE']['line'],
                    'repaired VEF Get adjacent original caller/order differs')
            batch.fields_equal(anchor['REPLY_FREE'], destination=hex(caller), expected=hex(caller), faults=0)
        caller = edge['caller']
        after, before = predecessor['REPLY_FREE']['line'], edge['REQUEST']['line']
        queries = [row for row in log.rows('PIN_QUERY') if after < row['line'] < request['line'] and
                   row['fields'].get('tid') == identity[1] and row['fields'].get('raw') == wire.hex()]
        require(len(queries) == 1, 'repaired VEF Get lacks one original AP query in its edge interval')
        before = min(before, batch.old.next_pin_send(log, queries[0]))
        namespace = dict(batch.verify_get.__globals__, SLOTS={**batch.SLOTS, **VEF_GET_SLOTS})
        verify_get = types.FunctionType(batch.verify_get.__code__, namespace)
        content = verify_get(log, key, identity, caller, after, before)
        require(content['request'] is request and content['original_AP_query'] is queries[0],
                'repaired VEF request borrowed another Get record')
        content.update(connection_prefix=edge['REQUEST']['tag'].removesuffix('_REQUEST'),
                       predecessor_AP_free_line=after, connection_request_line=edge['REQUEST']['line'])
        joins.append(content)
    return joins


def check_repaired_hdmi_frees(log, repairs, proof, batch):
    """Consume exact repaired HDMI configuration frees, never a graph/media ACK."""
    joins = []
    for repair in repairs:
        if not repair['repaired_record'].startswith('OBS FULL_HDMI_NATIVE_REPLY_FREE '):
            continue
        require(HDMI_NATIVE_FREE.fullmatch(repair['repaired_record'].encode()),
                'repaired HDMI free differs from complete producer grammar')
        rows = [row for row in log.rows('FULL_HDMI_NATIVE_REPLY_FREE') if
                row['line'] == repair['parsed_line'] and row['raw'] == repair['repaired_record']]
        require(len(rows) == 1, 'repaired HDMI free lost its exact parsed record')
        freed = rows[0]
        f = freed['fields']
        require(all(int(f[name]) < 2**31 for name in ('tid', 'sender')) and int(f['lease']) < 2**64 and
                int(f['destination'], 16) & 0xfffffff, 'repaired HDMI free producer integer bounds exceeded')
        tid, command = proof['identity'][1], int(f['command'], 16)
        batch.fields_equal(freed, tid=tid, sender=tid, waiter=1, rc=0, expected=f['destination'])
        require(freed['line'] < proof['edges'][0]['REQUEST']['line'], 'repaired HDMI free is not a pre-graph configuration')
        transaction = {}
        for name in ('REPLY_QUEUED', 'COMMIT', 'NATIVE_REPLY_FREE'):
            matches = [row for row in log.rows('FULL_HDMI_' + name) if row['fields'].get('lease') == f['lease']]
            require(len(matches) == 1, 'missing/duplicate repaired HDMI transaction ' + name)
            row = matches[0]
            batch.fields_equal(row, tid=tid, command=f['command'], reply=f['reply'], lease=f['lease'], status=f['status'])
            transaction[name] = row
        queued, commit = transaction['REPLY_QUEUED'], transaction['COMMIT']
        previous = max((row['line'] for row in log.rows('FULL_HDMI_REPLY_QUEUED') if row['line'] < queued['line']), default=0)
        requests = [row for row in log.rows('FULL_HDMI_REQUEST') if previous < row['line'] < queued['line']]
        require(len(requests) == 1, 'missing/duplicate original repaired HDMI request')
        request = requests[0]
        batch.fields_equal(request, tid=tid, source=f['destination'], destination='0x909a015a', command=f['command'])
        batch.fields_equal(queued, source='0x909a015a', destination=f['destination'], bytes=f['bytes'])
        batch.fields_equal(commit, request_free_rc=0, hdmi_output_verified=0, camera_startup_verified=0)
        require(request['line'] < queued['line'] < commit['line'] < freed['line'] and
                transaction['NATIVE_REPLY_FREE'] is freed, 'repaired HDMI request/queue/commit/native-free order differs')
        size = {0x10a: 12, 0x20a: 8, 0x101: 16, 0x201: 8, 0x117: 12}[command]
        wire = batch.raw_bytes(request, size)
        require(struct.unpack_from('<4H', wire) == (0x2500, command, size, 1), 'repaired HDMI original request envelope differs')
        reply = batch.raw_bytes(queued, int(f['bytes']))
        require(reply[:12] == struct.pack('<4HI', 0x2500, command | 0x8000, len(reply), 1, int(f['status'])),
                'repaired HDMI complete reply envelope/status differs')
        c = commit['fields']
        if command in (0x10a, 0x20a):
            value = wire[8] if command == 0x10a else 0
            readback = value if value < 6 else 0
            if command == 0x20a:
                readback = int(c['readback'])
                require(0 <= readback < 6, 'repaired HDMI definition readback out of bounds')
                batch.fields_equal(commit, known_before=1, readback_before=readback)
                require(reply[12:] == bytes([readback, 0, 0, 0]), 'repaired HDMI definition reply/readback differs')
            batch.fields_equal(commit, requested=value, known_after=1, readback=readback)
        elif command in (0x101, 0x201):
            resolution = wire[8:14] if command == 0x101 else reply[12:18]
            batch.fields_equal(commit, resolution=resolution.hex(), resolution_known=1)
            if command == 0x201:
                require(reply[18:] == bytes(2), 'repaired HDMI resolution reply padding differs')
        else:
            selector, rate, dp_selector, dp_rate = wire[8:]
            batch.fields_equal(commit, selector=selector, rate=rate, dp_selector=dp_selector, dp_rate=dp_rate,
                               dp_applied=0, matched=int(selector < 5), readback=rate if selector < 5 else 0)
            require(re.fullmatch('[0-9a-f]{10}', c['rates']) and re.fullmatch('(?:0|0x[1-9a-f][0-9a-f]?)', c['known_mask']),
                    'repaired HDMI rate cache encoding differs')
            mask = int(c['known_mask'], 0)
            require(mask < 32 and (selector >= 5 or mask & (1 << selector) and bytes.fromhex(c['rates'])[selector] == rate),
                    'repaired HDMI rate cache/readback differs')
        joins.append({'original_request': request, 'queued_reply': queued, 'commit': commit,
                      'actual_same_sender_free': freed, 'configuration_only': True,
                      'hdmi_output_verified': False, 'capture_verified': False})
    return joins


def check_repaired_resources(log, repairs, proof, batch):
    """Join sampled guards to Speech ownership and the completed native edge.

    HDMI progress can reserve again on another AP thread while event6 is pending;
    these are separate guard observations, not duplicate requests or new frees.
    """
    joins = []
    for prefix in ('FULL_VEF_PINMEM_INPUT_CONNECT', 'FULL_PINMEM_HDMI_VIDEO_CONNECT'):
        tags = tuple(prefix + suffix for suffix in ('_RESOURCE_DEPENDENCIES', '_RESOURCES_TTS_TABLE', '_RESOURCES_RESERVED'))
        wanted = {(r['parsed_line'], r['repaired_record']) for r in repairs
                  if r['repaired_record'].split(' ', 2)[1] in tags}
        if not wanted:
            continue
        edges = [e for e in proof['edges'] if e['REQUEST']['tag'] == prefix + '_REQUEST']
        require(len(edges) == 1, 'repaired resource lacks one completed native edge')
        edge = edges[0]
        for name in ('REQUEST', 'REPLY_FREE'):
            row = edge[name]
            require(log.rows(row['tag']) == [row], 'resource join lacks one exact original request/AP free')
        check_role_messages(edge, proof['identity'])
        rows = [r for r in log.records if r['tag'] in tags]
        require(all(sum((r['line'], r['raw']) == key for r in rows) == 1 for key in wanted),
                'repaired resource lost its exact parsed record')
        speech = proof['legacy_histories']['Speech']
        require(speech['ap_pid'] == int(proof['identity'][0]) and speech['initial_speech_lifecycle_verified'] is True and
                speech['resource_release_authorized'] is False, 'repaired resource lacks original Speech ownership')
        for tid in dict.fromkeys(r['fields'].get('tid') for r in rows):
            require(tid is not None and re.fullmatch('[1-9][0-9]*', tid) and 1 < int(tid) < 2**31,
                    'repaired resource thread is not canonical')
            thread = [r for r in rows if r['fields'].get('tid') == tid]
            require(len(thread) % 3 == 0 and [r['tag'] for r in thread] == list(tags) * (len(thread) // 3),
                    'missing/duplicate/out-of-order resource dependency/table/reservation')
            for index in range(0, len(thread), 3):
                dependencies, table, reserved = thread[index:index + 3]
                if not any((r['line'], r['raw']) in wanted for r in (dependencies, table, reserved)):
                    continue
                for row in (dependencies, table, reserved):
                    require(parse_record(row['raw'].encode() + b'\r\n') == (row['tag'], row['fields']),
                            'resource fields differ from actual record bytes')
                expected_dependencies = dict(pid=proof['identity'][0], tid=tid, accepted=1, proc_ap_consumed=1,
                    input_ap_consumed=1, output_ap_consumed=1, output_faults=0, current_request_retained_expected=1, capture_verified=0)
                require(set(dependencies['fields']) == set(expected_dependencies), 'resource dependency fields differ')
                batch.fields_equal(dependencies, **expected_dependencies)
                require(re.fullmatch(RESOURCE_TTS_FIELDS, table['raw'].split(' ', 2)[2].encode()),
                        'resource table differs from complete producer grammar')
                batch.fields_equal(table, pid=proof['identity'][0], tid=tid, appfw_base=speech['appfw_base'])
                base = int(table['fields']['appfw_base'], 16)
                require(0x10000 <= base < 0x7ff0000000 and int(table['fields']['address'], 16) == base + 0x5f66b08 and
                        sha(bytes.fromhex(table['fields']['raw_before'])) == speech['table_sha256'],
                        'resource table differs from original Speech bytes/address')
                pending = reserved['line'] > edge['REQUEST']['line']
                require(dependencies['line'] < table['line'] < reserved['line'], 'resource snapshot order differs')
                if prefix == 'FULL_VEF_PINMEM_INPUT_CONNECT':
                    anchor = proof['resources'][prefix]
                    require(not pending and tid == proof['identity'][1] and reserved == anchor,
                            'sixth resource is not the actual admitted guard')
                    allocations = 3
                else:
                    anchor = proof['edges'][9]['resources']
                    allocations = 4
                    if pending:
                        require(edge['EVENT6_ENQUEUED']['line'] < dependencies['line'] and
                                reserved['line'] < edge['PEER_REPLY']['line'], 'HDMI resource is outside pending event6')
                    else:
                        require(tid == proof['identity'][1] and edge['predecessor_free_line'] < dependencies['line'],
                                'HDMI cold resource owner/predecessor differs')
                batch.fields_equal(anchor, accepted=1, allocations=allocations, releases=allocations, control_live=0, control_faults=0)
                expected_resources = dict(tid=tid, accepted=1, dmm_enabled=1, dmm_bound=1, dmm_slots='1/1', dmm_opens='1/1',
                    dmm_handles='0x8400/0x8401', dmm_generations='1/1', dmm_epochs='1/2', dmm_creators='1/1',
                    dmm_allocation_count=2, dmm_lifecycle_changed=0, dmm_domain=2, foreign_speech_kept=1, data_frozen=0,
                    control_bound=1, control_live=0, control_faults=0, allocations=allocations, releases=allocations,
                    connection_started=1, connections=1, format_pending=0, blocked=0, format_consumed=1, buffer_released=1,
                    connection_reply_frees=1, connection_faults=0, vef_init=1, vef_owner='0x905a0048', vef_objects=16,
                    vef_pending=0, vef_live=0, vef_retained=0, vef_faults=0, pinmem_init=1, pinmem_owner='0x90590818',
                    pinmem_objects=13, pinmem_pending=int(pending), pinmem_live=0, pinmem_retained=0, pinmem_faults=0,
                    global_dmm_idle_verified=0, original_cp_executed=0, capture_verified=0)
                require(set(reserved['fields']) == set(expected_resources), 'resource reservation fields differ')
                batch.fields_equal(reserved, **expected_resources)
                joins.append({'prefix': prefix, 'pending_event6': pending, 'resource_dependencies': dependencies,
                              'table_snapshot': table, 'reservation': reserved, 'original_request': edge['REQUEST'],
                              'actual_AP_reply_free': edge['REPLY_FREE'], 'initial_Speech_table_sha256': speech['table_sha256'],
                              'resource_release_authorized': False, 'capture_verified': False})
    return joins


def check_repaired_adf_controls(log, repairs, proof, batch):
    """Consume two cold ADF effects through their real request/reply lifetimes.

    The legacy verifier never read these records. Source literals alone cannot
    join a repair: both original AP transactions and the intervening work must
    agree before any record is returned to bind_repairs().
    """
    targets = ('FULL_ADF_PROC_INPUT_QUEUED', 'FULL_ADF_SET_INPUT_HOTSHOE')
    wanted = [r for r in repairs if r['repaired_record'].split(' ', 2)[1] in targets]
    if not wanted:
        return []
    for repair in wanted:
        require(repair['kind'] == 'exact-host-vvfat-diagnostic', 'unsupported ADF repair kind')
        rows = [r for r in log.records if r['line'] == repair['parsed_line'] and
                r['raw'] == repair['repaired_record']]
        require(len(rows) == 1 and rows[0]['tag'] in targets, 'repaired ADF effect lost its exact parsed record')
    identity = proof['identity']
    require(len(identity) == 2 and all(type(v) is str and re.fullmatch('[1-9][0-9]*', v) and
            1 < int(v) < 2**31 for v in identity), 'ADF repair lacks a canonical original AP identity')
    first = proof['edges'][0]['REQUEST']['line']
    caller = proof['edges'][0]['caller']
    require(type(caller) is int and 0x80000000 < caller < 0x90000000, 'ADF repair lacks a local graph caller')
    zeros = ('original_cp_executed=0 hardware_verified=0 native_frequency_verified=0 '
             'original_event_identity_verified=0 pcm_verified=0 frames_verified=0 capture_verified=0')

    def exact(prefix, suffix, body, tid, scope):
        row = log.one(prefix + '_' + suffix)
        require(parse_record(row['raw'].encode('ascii') + b'\r\n') == (row['tag'], row['fields']),
                'ADF fields differ from actual record bytes')
        expected = f"OBS {prefix}_{suffix} {body} pid={identity[0]} tid={tid} scope={scope} {zeros}"
        require(row['raw'] == expected, 'ADF complete producer fields/suffix differ: ' + row['tag'])
        return row

    transactions = []
    for generation, prefix, scope, size, request_raw, reply_raw in (
            (1, 'FULL_ADF_PROC', 'virtualSource7ControlOnly', 12,
             '0d2023030c00018000000000', '0d2023130c00018000005800'),
            (2, 'FULL_ADF_SET_INPUT', 'virtualInputConfigurationS0', 14,
             '0d2036030e000180000200000000', '0d2036130c00018000005800')):
        request = log.one(prefix + '_REQUEST')
        queued = log.one(prefix + '_QUEUED')
        pointer, reply, worker = request['fields']['request'], queued['fields']['reply'], queued['fields']['tid']
        require(all(re.fullmatch('0x[1-9a-f][0-9a-f]{0,15}', v) for v in (pointer, reply)) and pointer != reply,
                'ADF request/reply allocations alias or exceed producer bounds')
        require(re.fullmatch('[1-9][0-9]*', worker) and 1 < int(worker) < 2**31 and worker != identity[1],
                'ADF work lacks its actual worker thread')
        request_tail = ('request_accepted=1 policy=virtual-source7-control-events-v1 policy_period_ns=1000000 normal_completion=0'
                        if generation == 1 else 'known_AB_failure_preserved=1 metadata_completion_only=1 normal_completion=0')
        queue_tail = 'events=4 queued=1' if generation == 1 else 'AB_status=1 AIP_task_rc=0x1004 metadata_completion=1'
        commit_tail = ' events=4 work_complete=1' if generation == 1 else ''
        free_tail = 'events=4' if generation == 1 else 'AB_status=1 AIP_task_rc=0x1004 metadata_completion_only=1'
        rows = {
            'request': exact(prefix, 'REQUEST', f'generation={generation} caller={hex(caller)} request={pointer} bytes={size} raw={request_raw} {request_tail}', identity[1], scope),
            'reply': exact(prefix, 'QUEUED', f'generation={generation} destination={hex(caller)} source=0x92840747 reply={reply} bytes=12 raw={reply_raw} {queue_tail}', worker, scope),
            'commit': exact(prefix, 'COMMIT', f'generation={generation} request={pointer} request_free_rc=0 retained_request=0 clean_completion=1 queued=1 ap_consumed=0{commit_tail}', worker, scope),
            'actual_AP_free': exact(prefix, 'REPLY_FREE', f'generation={generation} destination={hex(caller)} expected={hex(caller)} pointer={reply} kind=queued-reply rc=0 faults=0 retained=0 ap_consumed=1 {free_tail}', identity[1], scope),
        }
        require(batch.raw_bytes(rows['request'], size) == bytes.fromhex(request_raw) and
                batch.raw_bytes(rows['reply'], 12) == bytes.fromhex(reply_raw), 'ADF complete wire envelope differs')
        order = [r['line'] for r in rows.values()]
        require(order == sorted(set(order)) and order[-1] < first, 'ADF request/queue/commit/AP-free order differs')
        require(not any(r['tag'].startswith(prefix + '_') and
                (r['tag'] == prefix + '_PENDING' or r['tag'].endswith(('_FAULT', '_REFUSED', '_REJECT', '_UNSUPPORTED', '_RECOVERY_FREE')))
                for r in log.records), 'ADF fault or incomplete lifetime retained')
        events = log.rows(prefix + '_EVENT')
        require(len(events) == 4, 'ADF source7 event count differs')
        for index, event in enumerate(events):
            sequence = index + (1 if generation == 1 else 5)
            batch.fields_equal(event, pid=identity[0], tid=worker, generation=generation,
                event=sequence, hardware_counter=sequence, hardware_source=7, software_source=5,
                guest_timerfd_expirations=1, policy_period_ns=1000000, getter_advances=0)
            if generation == 1:
                batch.fields_equal(event, hardware_epoch=sequence, fb_counter=sequence, fb_epoch=sequence,
                                   cache_counter=sequence, cache_epoch=sequence)
            else:
                batch.fields_equal(event, epoch=sequence, subscriber='0x9058003f', sender='0x928c0786',
                                   queued=index + 1, consumed=index + 1)
            deadline, observed = (event['fields'][k] for k in ('deadline_ns', 'observed_ns'))
            require(all(re.fullmatch('(?:0|[1-9][0-9]*)', v) for v in (deadline, observed)) and
                    0 < int(deadline) <= int(observed) < 2**64, 'ADF timerfd deadline/observation differs')
        event_lines = [r['line'] for r in events]
        require(event_lines == sorted(set(event_lines)) and order[0] < event_lines[0] < event_lines[-1] < order[1],
                'ADF source7 event identity/order differs')
        rows.update(worker_tid=worker, events=events)
        transactions.append(rows)
    proc, input_ = transactions
    require(proc['actual_AP_free']['line'] < input_['request']['line'], 'SetInput preceded original AP0323 free')
    p, s = 'FULL_ADF_PROC', 'FULL_ADF_SET_INPUT'
    ps, ss = 'virtualSource7ControlOnly', 'virtualInputConfigurationS0'
    queued = exact(p, 'INPUT_QUEUED', 'generation=1 event=3 after_priority=4 selector=0 input_state=1 parameter=0 priority=2 registered=1 scheduler_consumed=0 next_source5_pass_required=1', proc['worker_tid'], ps)
    drained = exact(p, 'INPUT_DRAINED', 'generation=1 event=4 priority=2 scheduler_consumed=1 control30_consumed=1 callback_status=0 callbacks=1 control31_parameter=0 control31_callback=0 request=0 pending=0 submitted=0 registered=0 listener_removed=1 complete=1', proc['worker_tid'], ps)
    applied = log.one(p + '_APPLIED')
    batch.fields_equal(applied, pid=identity[0], tid=proc['worker_tid'], generation=1,
        input_complete=1, events=4, config_commits=1, inner_consumed=1, outer_status='0x580000')
    stages = log.rows(p + '_AVIO_STAGE')
    require(len(stages) == 3, 'ADF AVIO stage count differs')
    for index, stage in enumerate(stages):
        batch.fields_equal(stage, pid=identity[0], tid=proc['worker_tid'], generation=1,
            event=index + 1, stage=index, priority=4, consumed=index + 1, remaining=2 - index,
            output_finished=int(index == 2), callbacks=int(index == 2))
        require(proc['events'][index]['line'] < stage['line'] < proc['events'][index + 1]['line'],
                'ADF AVIO/source7 stage order differs')
    require(stages[-1]['line'] < queued['line'] < proc['events'][3]['line'] < drained['line'] <
            applied['line'] < proc['reply']['line'], 'ADF input queue was not drained on the next source5 pass')
    proc.update(input_queued=queued, input_drained=drained, applied=applied, avio_stages=stages)
    bodies = (
        ('DEPENDENCIES', 'generation=2 original_AP0323_reply_freed=1 same_hotshoe_owner=1 same_glee_owner=1 same_command_buffer=1 same_source7_clock=1 counter_before=4 epoch_before=4 capability_word7=0 capability_word8=1 output_target=8'),
        ('METADATA', 'generation=2 glee_callback_status=0 owner_request_generation=1 hotshoe_callback_running=1 queued_commands=3 active_cache=00020000 completion_mask_consumed=1 digital_pending=0 config_commits=1 inner_queued=1 inner_raw=042001840c00010000000000 AIP102_queued=0 outer_published=0'),
        ('GLEE', 'generation=2 same_initialized_owner=1 owner_request_generation=1 control30_notes=1 control0_callbacks=1 control1_type=0 control1_source=1 control1_callback=0 input_ring=0 kind_cache=0 power20=0 power21=0 power22=0 power_state=2 synchronous_reference_branch=1'),
        ('CONTROL102', 'generation=2 metadata_already_committed=1 control141_queries=2 control141_value=1 selector=2 source_parameters=3/0/0/0/0/0/0/1/0/0 queued=B8/03/02/11/B6/B7 command_count=9 body_bytes=132 control110_parameter=1 existing7c=1 opcode42_queued=0'),
        ('HOTSHOE', 'generation=2 owner_request_generation=1 callbacks=1 callback_returned=1 fifo_popped_before_callback=1 current_type_committed_after_callback=1 current_type=0 busy=0 fifo_count=0 asynchronous_power_work=0'),
    )
    callbacks = {suffix: exact(s, suffix, body, input_['worker_tid'], ss) for suffix, body in bodies}
    lines = [input_['request']['line']] + [r['line'] for r in callbacks.values()] + [input_['events'][0]['line']]
    require(lines == sorted(set(lines)), 'ADF callback/metadata/type-commit order differs')
    applied = log.one(s + '_APPLIED')
    batch.fields_equal(applied, pid=identity[0], tid=input_['worker_tid'], generation=2,
        metadata_cache='00020000', config_commits=1, hotshoe_callbacks=1, glee_callbacks=1,
        control1_readbacks=1, inner_consumed=1, outer_status='0x580000', AB_status=1,
        AIP_first_task_rc='0x1004', AIP_uninspected=7, AB_register_writes=0, hardware_audio_success=0)
    dispatches = log.rows(s + '_AIP_DISPATCH')
    require(len(dispatches) == 4, 'ADF known AB failure dispatch count differs')
    for index, dispatch in enumerate(dispatches):
        batch.fields_equal(dispatch, pid=identity[0], tid=input_['worker_tid'], generation=2,
            event=index + 5, dispatches=index + 1, commands_interpreted=9, AB_status=1,
            task_rc='0x1004' if index == 0 else 0, first_uninspected_preserved=7,
            snapshot_count=9 if index == 0 else 0, checked=2 if index == 0 else 0,
            cursor_words=6 if index == 0 else 0, failure_history_preserved=1, old_tail_rechecked=0, ring_read=9, ring_write=9)
        before = input_['events'][index + 1]['line'] if index < 3 else applied['line']
        require(input_['events'][index]['line'] < dispatch['line'] < before, 'ADF dispatch/event order differs')
    require(dispatches[-1]['line'] < applied['line'] < input_['reply']['line'], 'ADF reply preceded completed data work')
    input_.update(callbacks=callbacks, applied=applied, known_AB_failure_dispatches=dispatches)
    return [{'proc': proc, 'set_input': input_, 'source_references': {
                'runtime/analysis/device-models/adf-proc-device.c': ['event', 'backend', 'full_adf_proc_dispatch', 'full_adf_proc_release_reply', 'full_adf_proc_claim_input'],
                'runtime/analysis/device-models/adf-set-input-device.c': ['event', 'backend', 'glee_complete', 'hotshoe_complete', 'worker', 'full_adf_set_input_dispatch', 'full_adf_set_input_release_reply'],
                'runtime/analysis/device-models/adf-set-input-cold-owners.c': ['full_adf_hotshoe_set_type', 'full_adf_glee_input_control0'],
                'runtime/analysis/menu-observe.c': ['record']},
             'scope': 'cold virtual ADF control transactions; known AB failure retained',
             'capture_verified': False, 'physical_asic_compatibility_verified': False,
             'original_CP_executed': False, 'original_event_identity_verified': False}]


def bind_repairs(proof, repairs):
    consumed = set()
    def collect(value):
        if isinstance(value, dict):
            if {'line', 'tag', 'fields', 'raw'} <= value.keys():
                consumed.add((value['line'], value['raw']))
            for item in value.values():
                collect(item)
        elif isinstance(value, (tuple, list)):
            for item in value:
                collect(item)
    collect(proof)
    unjoined = [r for r in repairs if (r['parsed_line'], r['repaired_record']) not in consumed]
    if unjoined:
        raise UnjoinedRepairs(unjoined)
    for repair in repairs:
        repair['content_verifier_joined'] = True
    return repairs


def check_run_binding(reader, run, manifest, runner, raw_console, proof, build):
    require(build.get('qemu_sha256') in (SELECTED_QEMU_SHA256, READONLY_SCOPE_QEMU_SHA256),
            'run binding QEMU is not an admitted batch executable')
    require(runner.get('schema') == 'functional-camera-runner-v1' and
            runner.get('profile') == 'virtual-functional-camera-v1' and runner.get('phase') == 'closed' and
            runner.get('error') is None and runner.get('broker_started') is True and
            reader.typed_equal(runner, manifest.get('functional_camera_runtime')), 'runner not closed/same manifest')
    cleanup = runner.get('cleanup', {})
    require(all(cleanup.get(k) is True for k in ('safe_to_close', 'mailbox_detached', 'debugger_stopped',
                                               'protocol_physmode_restored', 'worker_stopped')) and
            cleanup.get('errors') == [] and runner.get('console_sha256_at_close') == sha(raw_console),
            'unsafe runner cleanup or different completed-run console')
    for key in ('capture_verified', 'physical_ASIC_compatibility_verified', 'original_CP_RAM_verified',
                'standalone_host_media_write'):
        require(runner.get(key) is False, 'runner scope promotion: ' + key)
    pid = int(proof['identity'][0])
    require(runner.get('mailbox_evidence', {}).get('mailbox', {}).get('pid') == pid, 'graph AP differs from current guest owner')
    artifact = runner.get('artifact', {})
    for key, value in (('library_sha256', build['model_sha256']), ('build_receipt_sha256', build['model_build_sha256']),
                       ('source_archive_sha256', build['model_source_archive_sha256']), ('qemu_sha256', build['qemu_sha256'])):
        require(artifact.get(key) == value, 'runner/current frozen batch differs: ' + key)
    config = proof['edges'][10]['native_UPM']['GDB_result']
    require(config.get('detached') is True, 'HDMI debugger not detached')
    watcher = object_json(read(run / UPM_FILES[0], MAX_JSON))
    info = run.stat()
    owner, handoff = runner.get('owner', {}), runner.get('debugger_handoff', {})
    qemu = handoff.get('qemu_identity', {})
    for value in (manifest.get('host_control_owner_pid'), watcher.get('owner_pid'), watcher.get('qemu_pid'),
                  owner.get('pid'), owner.get('ppid'), handoff.get('qemu_pid'), qemu.get('pid'), qemu.get('ppid')):
        require(type(value) is int and 1 < value < 2**31, 'invalid saved owner/QEMU PID')
    for value in (watcher.get('owner_starttime'), owner.get('starttime'), watcher.get('qemu_starttime'), qemu.get('starttime')):
        require(type(value) is int and 0 < value < 2**64, 'invalid saved owner/QEMU generation')
    require(watcher.get('run') == str(run) and watcher.get('run_device') == info.st_dev and
            watcher.get('run_inode') == info.st_ino and watcher.get('running_QEMU_sha256') == build['qemu_sha256'] and
            watcher['owner_pid'] == manifest['host_control_owner_pid'] and
            watcher['qemu_pid'] == handoff['qemu_pid'] == qemu['pid'] and
            watcher['qemu_starttime'] == qemu['starttime'] and watcher.get('qemu_exe') == qemu.get('exe'),
            'UPM/current run/QEMU identity or generation mismatch')
    same_owner = owner['pid'] == watcher['owner_pid']
    # menu_control launches the probe; the probe owns the runner, not its parent.
    require((same_owner and owner['starttime'] == watcher['owner_starttime'] or
             not same_owner and owner['ppid'] == watcher['owner_pid'] and
             watcher['owner_starttime'] <= owner['starttime']) and
            owner['starttime'] <= qemu['starttime'] and owner.get('exe') == watcher.get('owner_exe') and
            isinstance(owner.get('exe'), str) and Path(owner['exe']).is_absolute() and
            isinstance(qemu.get('exe'), str) and Path(qemu['exe']).is_absolute() and
            qemu['ppid'] != qemu['pid'] and (same_owner or qemu['ppid'] != watcher['owner_pid']),
            'UPM host-control/runner parent or process generation mismatch')
    require(handoff.get('debugger_quiesced') is True and
            reader.typed_equal(handoff.get('previous_hdmi_observer'), config), 'functional/UPM debugger handoff differs')
    sockets = handoff.get('sockets', {})
    gdb, qmp = sockets.get('hdmi-upm-gdb.sock', {}), sockets.get('hdmi-upm-control.sock', {})
    require(all(sockets.get(name, {}).get('path') == str(run / name)
                for name in ('hdmi-upm-gdb.sock', 'hdmi-upm-control.sock')) and
            gdb.get('device') == watcher.get('socket_device') == info.st_dev and
            gdb.get('inode') == watcher.get('socket_inode') and type(gdb.get('inode')) is int and
            gdb['inode'] > 0 and type(gdb.get('listener_inode')) is int and gdb['listener_inode'] > 0,
            'functional/UPM same-run debugger socket differs')
    broker_raw = read(run / BROKER_RECEIPTS, MAX_LOG)
    require(broker_raw.endswith(b'\n') and runner.get('broker_receipts') == str(run / BROKER_RECEIPTS),
            'missing/incomplete same-run broker binding')
    binding = object_json(broker_raw.split(b'\n', 1)[0])
    bound = binding.get('config', {})
    mailbox = runner.get('mailbox_evidence', {}).get('mailbox')
    require(binding.get('kind') == 'binding' and type(binding.get('event')) is int and binding['event'] == 1 and
            reader.typed_equal(binding.get('mailbox'), mailbox) and
            reader.typed_equal(binding.get('model_instance'), mailbox.get('nonce')) and
            bound.get('run') == str(run) and reader.typed_equal(bound.get('run_identity'), [info.st_dev, info.st_ino]) and
            reader.typed_equal(bound.get('owner'), owner) and reader.typed_equal(bound.get('qemu'), qemu) and
            bound.get('qemu_sha256') == build['qemu_sha256'] and
            reader.typed_equal(bound.get('gdb'), gdb) and reader.typed_equal(bound.get('qmp'), qmp),
            'actual broker/runner/run/QEMU binding differs')
    return {'original_AP_pid': pid, 'original_AP_tid': int(proof['identity'][1]),
            'host_control_identity': {key: watcher['owner_' + key] for key in ('pid', 'starttime', 'exe')},
            'runner_owner': owner, 'owner_relationship': 'same-process' if same_owner else 'direct-child',
            'qemu_identity': qemu, 'broker_binding_sha256': sha(broker_raw),
            'runner_closed_safely': True, 'same_run_UPM_receipts_verified': True,
            'console_sha256_at_close': sha(raw_console)}


def check_public_image(reader, run, manifest, hdmi):
    backup = manifest['backup_transport']
    require(backup.get('source_seed_sha256') == ALLLANG_SHA256 and
            sha(read(RUNTIME / 'menu-root/seed-backup.bin')) == ALLLANG_SHA256, 'public ALLLANG seed differs')
    pins = {'seed-backup.bin': ALLLANG_SHA256, 'cp/cpapp-b.bin': PUBLIC_CP_SHA256,
            **{'usr/kmod/' + name + '.ko': digest for name, digest in hdmi._watch().SHAS.items()},
            **reader.PUBLIC_LIBRARIES}
    selected = manifest['selected_initramfs_verified_files']
    require(all(name not in selected or selected[name] == digest for name, digest in pins.items()),
            'selected manifest conflicts with pinned original public bytes')
    expected = {**selected, **pins}
    for name, digest in reader.PUBLIC_LIBRARIES.items():
        reader.digest_binding(reader.read(RUNTIME / 'menu-root', name), digest, 'actual public original library ' + name)
    image = reader.source_module(RUNTIME / 'initramfs_identity.py')
    # The same anonymous bytes are hashed and parsed; no live-path second read.
    with reader.writeback.open_file(run, 'selected-initramfs.cpio', 1024**3) as source, reader.writeback.tempfile.TemporaryFile() as snapshot:
        before = os.fstat(source.fileno())
        space = os.fstatvfs(snapshot.fileno())
        require(space.f_bavail * space.f_frsize >= before.st_size + 1024**2, 'insufficient selected-image snapshot space')
        digest, count = hashlib.sha256(), 0
        for part in iter(lambda: source.read(1024**2), b''):
            count += len(part)
            require(count <= before.st_size and snapshot.write(part) == len(part), 'changed/short selected-image snapshot')
            digest.update(part)
        name = manifest.get('probe_args', {}).get('initramfs_file') or str(RUNTIME / 'menu-initramfs.cpio')
        require(count == before.st_size and reader.writeback.identity(before) == reader.writeback.identity(os.fstat(source.fileno())) and
                digest.hexdigest() == manifest['files'].get(name), 'actual selected image SHA differs')
        snapshot.flush()
        image.verify_image(Path('/proc/self/fd/' + str(snapshot.fileno())), expected)
    return {'selected_image_sha256': digest.hexdigest(), 'additional_public_bytes_verified': expected,
            'original_libraries_unchanged': True}


def evaluate(run, batch):
    """Return a serializable closed verdict; never invoke a VM/build/test/decoder."""
    result = {'schema': 'functional-graph-evidence-v1', 'scope': 'current-batch same-run virtual graph content only',
              'graph_verified': False, 'all_13_graph_edges_complete': False, 'capture_verified': False,
              'physical_asic_compatibility_verified': False, 'original_CP_executed': False,
              'original_CP_RAM_verified': False, 'original_RTOS_verified': False,
              'state_source': 'explicit-virtual-model-not-original-CP-RAM-RTOS',
              'verdict': 'SOURCE/TRACE_MISSING', 'native_verified_edge_numbers': [],
              'all_thirteen': {str(i): {'verified': False} for i in range(1, 14)},
              'evidence': {}, 'dependency_hashes': {}, 'missing': []}
    stage = 'inputs'
    try:
        run = absolute(run)
        require(run.is_dir() and run.stat().st_uid == os.geteuid() and not run.stat().st_mode & 0o022, 'unsafe/missing run directory')
        result['run'] = str(run)
        batch, frozen, result['dependency_hashes'] = frozen_inputs(batch)
        result['batch'] = str(batch)
        stage = 'current_batch'
        reader = source_module('report/functional-camera-evidence/check_evidence.py', frozen)
        manifest = object_json(read(run / 'runtime-manifest.json', MAX_JSON))
        reader.check_profile(manifest)
        build, checked = check_current_batch(reader, run, batch, manifest)
        require(checked == frozen, 'bootstrap/full frozen input sets differ')
        result['evidence']['batch'] = build
        result['evidence']['production_sources'] = check_production_sources(batch, frozen)
        stage = 'helper_sources'
        graph, hdmi, osd = load_content_helpers(frozen)
        profile = source_module('runtime/analysis/backup_profile.py', frozen)
        result['evidence']['graph_profiles'] = check_graph_profiles(manifest, graph, hdmi, osd, profile)
        stage = 'selected_public_image'
        result['evidence']['public_image'] = check_public_image(reader, run, manifest, hdmi)
        stage = 'same_run_files'
        originals = {name: read(run / name, MAX_LOG if name in ('console.log', BROKER_RECEIPTS) else MAX_JSON) for name in RUN_FILES}
        require(object_json(originals['runtime-manifest.json']) == manifest, 'manifest changed during batch check')
        result['evidence']['run_files_sha256'] = {name: sha(raw) for name, raw in originals.items()}
        stage = 'console_framing'
        parsed, repairs = console_records(originals['console.log'])
        log = graph.Log(parsed)
        result['evidence']['console'] = {'raw_sha256': sha(originals['console.log']), 'parsed_sha256': sha(parsed),
                                         'transport_interleavings': repairs, 'line_numbers_refer_to': 'parsed console'}
        stage = 'graph_content'
        proof = check_graph_content(log, run, graph, hdmi, osd)
        proof['repaired_early_BB_Get_joins'] = check_repaired_queries(log, repairs, proof, graph)
        proof['repaired_VEF_Get_joins'] = check_repaired_vef_gets(log, repairs, proof, graph)
        proof['repaired_HDMI_reply_free_joins'] = check_repaired_hdmi_frees(log, repairs, proof, graph)
        proof['repaired_resource_snapshot_joins'] = check_repaired_resources(log, repairs, proof, graph)
        proof['repaired_ADF_input_control_joins'] = check_repaired_adf_controls(log, repairs, proof, graph)
        bind_repairs(proof, repairs)
        stage = 'same_run_owner'
        runner = object_json(originals['functional-camera-runner.json'])
        result['evidence']['run_binding'] = check_run_binding(reader, run, manifest, runner, originals['console.log'], proof, build)
        stage = 'final_immutability'
        for name, raw in originals.items():
            require(read(run / name, MAX_LOG if name in ('console.log', BROKER_RECEIPTS) else MAX_JSON) == raw, 'same-run evidence changed: ' + name)
        require(check_dependency_hashes(frozen) == result['dependency_hashes'], 'dependency changed during verification')
        for name, digest in frozen.items():
            require(sha(read(Path(name))) == digest, 'frozen batch source changed during verification: ' + name)
        require(sha(read(batch / 'ready.json', MAX_JSON)) == build['ready_sha256'], 'completed batch ready changed')
        result['evidence']['content'] = proof
        result['all_thirteen'] = {str(i): {'verified': True, 'roles': role, 'transaction': edge}
                                  for i, (edge, role) in enumerate(zip(proof['edges'], proof['roles']), 1)}
        result.update(verdict='PASS', graph_verified=True, all_13_graph_edges_complete=True,
                      native_verified_edge_numbers=list(range(1, 14)))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError,
            UnicodeError, struct.error, tarfile.TarError, ImportError, SystemExit) as error:
        missing = isinstance(error, (SourceMissing, FileNotFoundError)) or type(error).__name__ == 'MissingEvidence'
        result['missing'].append({'code': 'SOURCE_MISSING' if stage in ('inputs', 'helper_sources') and missing else
                                  'TRACE_MISSING' if missing else 'EVIDENCE_INVALID',
                                  'stage': stage, 'detail': f'{type(error).__name__}: {error}'})
        if isinstance(error, UnjoinedRepairs):
            result['missing'][-1]['unjoined_repairs'] = error.repairs
        result['verdict'] = 'SOURCE/TRACE_MISSING' if missing else 'FAIL'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', help='absolute completed current functional run directory')
    parser.add_argument('batch', help='absolute completed immutable unified batch directory or ready.json')
    args = parser.parse_args()
    result = evaluate(args.run, args.batch)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result['graph_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
