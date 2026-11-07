#!/usr/bin/env python3
"""UI controller for explicitly bound, local firmware development instances.

No instance creation, image copies, disk geometry inference or physical devices.
Core adapters opt in with FIRMWARE_DEVELOPMENT_API = 1 and consume one private
request file using --firmware-development-request. See the companion DESIGN.md.
"""
import argparse
import ast
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from urllib.parse import quote
import uuid

HERE = Path(__file__).resolve().parent
SCHEMA = 'a7c2.firmware-development.v1'
CONTEXT_SCHEMA = 'a7c2.firmware-development.context.v1'
LIMIT = 256 * 1024
ACTIONS = ('status', 'validate-package', 'plan', 'file-test', 'workspace-overwrite',
           'connect', 'disconnect', 'jiritsu', 'cold', 'hot', 'sequence', 'prepare-sd', 'update')
# These names are code, never context-supplied command lines or shell fragments.
CONTROLLERS = {
    'file-test': 'run-camera.py', 'workspace-overwrite': 'overwrite-images.py',
    'connect': 'usb_ui.py', 'disconnect': 'usb_ui.py', 'jiritsu': 'usb_jiritsu.py',
    'cold': 'boot-session.py', 'hot': 'boot-session.py', 'sequence': 'boot-session.py',
    'prepare-sd': 'sd-directory.py', 'update': 'boot-session.py',
}
STAGES = {
    'file-test': ('same_instance_root_route', 'appfw_readback', 'original_ap_test'),
    'workspace-overwrite': ('workspace_overwrite', 'persistent_writeback'),
    'connect': ('virtual_usb_connect',), 'disconnect': ('virtual_usb_disconnect',),
    'jiritsu': ('virtual_usb_jiritsu', 'same_instance_root_route'),
    'cold': ('original_init_cold', 'system_runtime', 'persistent_device'),
    'hot': ('retained_device_audit', 'retained_restore', 'system_runtime', 'persistent_device'),
    'sequence': ('original_init_cold', 'system_runtime', 'persistent_device',
                 'retained_device_audit', 'retained_restore'),
    'prepare-sd': ('virtual_sd_bodydata_readback',),
    'update': ('guest_sd_receiver', 'original_updater', 'persistent_writeback', 'updated_appfw_readback'),
}
PERSISTENT_STAGES = {'persistent_writeback', 'persistent_device', 'workspace_overwrite',
                     'virtual_sd_bodydata_readback', 'retained_device_audit'}
UPDATE_ACTIONS = {'validate-package', 'prepare-sd', 'update', '_inspect'}
RETAINED_PROFILE = 'persistent-flash-retained-upstream-host-v1'
RETAINED_QEMU_SHA = 'b4c697056f316de7a1d313df0e5fff7bc027f7164e5291561b79e505a61708f4'
RETAINED_SOURCE_SHA = 'e5e664b1727a2cc5fe898fefa438f356a513a1677f70842aafe0a4ad565c0d95'
RETAINED_SCOPE = 'declared fixed source-v4 topology only'
RETAINED_PROOF = HERE.parent / '2026-11-06-complete-boot-flow/retained-restore-validation.json'
RETAINED_REPORT = RETAINED_PROOF.with_name('RETAINED-RESTORE.md')


class Blocked(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def refuse(code, message):
    raise Blocked(code, message)


def path_checked(value, *, directory=False, private=False, missing=False):
    if not isinstance(value, (str, Path)) or not str(value) or any(ord(c) < 32 for c in str(value)):
        refuse('invalid_path', '路径为空或含控制字符')
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        refuse('invalid_path', '需要不含 .. 的绝对路径')
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            refuse('symlink_path', '路径包含符号链接：' + str(part))
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing:
            path_checked(str(path.parent), directory=True)
            return path
        raise
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        refuse('invalid_path_type', '需要普通目录或文件：' + str(path))
    if info.st_uid != os.geteuid() or (not directory and info.st_nlink != 1):
        refuse('unowned_path', '路径必须归当前用户所有且文件只有一个硬链接：' + str(path))
    if private and stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600):
        refuse('private_path_required', '上下文/记录需要 0600 文件、0700 目录：' + str(path))
    return path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            refuse('duplicate_json_key', 'JSON 字段重复：' + key)
        result[key] = value
    return result


def read_json(value, *, private=True):
    path = path_checked(value, private=private)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or
                before.st_nlink != 1 or (private and stat.S_IMODE(before.st_mode) != 0o600) or
                before.st_size > LIMIT):
            refuse('invalid_json_file', 'JSON 必须是有界、当前用户所有的普通文件')
        raw = os.read(fd, LIMIT + 1)
        after = os.fstat(fd)
        if len(raw) > LIMIT or _identity(before) != _identity(after) or _identity(after) != _identity(path.lstat()):
            refuse('context_changed', 'JSON 在读取时发生变化或超出大小限制')
        result = json.loads(raw, object_pairs_hook=_pairs,
                            parse_constant=lambda _: refuse('invalid_json', 'JSON 非有限数值'))
        if not isinstance(result, dict):
            refuse('invalid_json', '需要 JSON object')
        return result
    finally:
        os.close(fd)


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    temporary = path.with_name(path.name + '.new-' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        temporary.unlink(missing_ok=True)


def load_context(value):
    context = read_json(value)
    if context.get('schema') != CONTEXT_SCHEMA:
        refuse('context_schema', '不支持的固件开发上下文版本')
    for key in ('runtime', 'workspace'):
        context[key] = str(path_checked(context.get(key), directory=True))
    if not isinstance(context.get('available_capabilities', {}), dict):
        refuse('capability_schema', 'available_capabilities 必须是 object')
    return context


def bind_instance(context):
    instance = context.get('instance_identity')
    if not isinstance(instance, dict):
        refuse('instance_not_bound', '主界面尚未绑定一个持久虚拟磁盘实例')
    if (not isinstance(instance.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', instance['id']) or
            type(instance.get('generation')) is not int or instance['generation'] < 0):
        refuse('instance_identity', '实例 ID 或 generation 无效')
    disk = path_checked(instance.get('disk'))
    info = disk.stat()
    if any(type(instance.get(key)) is not int or instance[key] != actual
           for key, actual in (('dev', info.st_dev), ('ino', info.st_ino), ('bytes', info.st_size))):
        refuse('instance_changed', '磁盘 inode/容量与上下文绑定不一致')
    if not re.fullmatch('[0-9a-f]{64}', str(instance.get('geometry_sha256', ''))):
        refuse('geometry_not_bound', '缺少官方 source geometry 的绑定摘要；不会推测分区或容量')
    path_checked(instance.get('manifest'), private=True)
    routes = context.get('routes', {})
    for route in ('root', 'bodydata'):
        if routes.get(route) != instance:
            refuse('route_instance_mismatch', 'root 与 BODYDATA 路线必须绑定同一实例及 generation')
    return instance


def controller_supported(path):
    # Opt-in is parsed without importing a core controller or triggering a VM.
    tree = ast.parse(path.read_text())
    return any(isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
               t.id == 'FIRMWARE_DEVELOPMENT_API' for t in node.targets) and
               isinstance(node.value, ast.Constant) and type(node.value.value) is int and node.value.value == 1
               for node in tree.body)


def validate_mode(args, target):
    if args.profile not in ('official', 'virtual-dev'):
        refuse('unknown_profile', '未知 profile；不会回退到 official 或冷启动')
    if args.virtual_dev_update != (args.profile == 'virtual-dev'):
        refuse('signature_scope', '虚拟开发更新必须同时指定 virtual-dev profile 与显式签名跳过')
    if args.virtual_dev_update and target not in UPDATE_ACTIONS:
        refuse('signature_scope', '签名跳过仅适用于本地虚拟 BODYDATA 校验/SD/更新')


def checked_binding(binding, *, private=False, expected_path=None):
    if (not isinstance(binding, dict) or set(binding) != {'path', 'sha256'} or
            not re.fullmatch('[0-9a-f]{64}', str(binding.get('sha256', '')))):
        refuse('sequence_binding', 'Sequence input requires exact path/SHA256 fields')
    path = path_checked(binding['path'], private=private)
    if expected_path is not None and path != expected_path:
        refuse('sequence_binding', 'Sequence input path differs from the fixed contract')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or
                private and stat.S_IMODE(info.st_mode) != 0o600):
            refuse('sequence_input_changed', 'Sequence input file identity/mode changed')
        before = _identity(info)
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if before != _identity(os.fstat(stream.fileno())) or before != _identity(path.lstat()):
            refuse('sequence_input_changed', 'Sequence input changed during readback')
    if actual != binding['sha256']:
        refuse('sequence_input_changed', 'Sequence input SHA256 differs: ' + str(path))
    return path


def sequence_capability(context, instance):
    """Read only the explicitly published fixed QEMU roundtrip contract."""
    capability = context.get('available_capabilities', {}).get('sequence')
    if not isinstance(capability, dict) or capability.get('available') is not True:
        refuse('required_stage_unavailable', 'Main-owned sequence capability is unavailable')
    if capability.get('contract') != SCHEMA or capability.get('instance_identity') != instance:
        refuse('capability_instance_mismatch', 'Sequence capability contract/instance/generation mismatch')
    audit = capability.get('retained_audit', {})
    if (not isinstance(audit, dict) or any(audit.get(k) is not True for k in
            ('complete', 'compatible', 'external_state_verified')) or audit.get('instance_identity') != instance):
        refuse('retained_audit_required', 'Sequence requires the explicitly bound declared-topology audit')
    fields = {'available', 'contract', 'instance_identity', 'runtime_analysis', 'cold_manifest',
              'combo_manifest', 'origin_qemu_build', 'backend_source', 'persistent_module', 'retained_audit'}
    if set(capability) != fields:
        refuse('sequence_capability_fields', 'Sequence capability has missing or unexpected fields')
    expected = {'profile': RETAINED_PROFILE, 'qemu_sha256': RETAINED_QEMU_SHA,
                'source_tree_sha256': RETAINED_SOURCE_SHA, 'scope': RETAINED_SCOPE}
    if any(audit.get(k) != v for k, v in expected.items()):
        refuse('retained_audit_scope', 'Only the fixed upstream-host QEMU declared topology is admitted')
    evidence = checked_binding({'path': audit.get('evidence'), 'sha256': audit.get('evidence_sha256')}, private=True)
    proof = read_json(RETAINED_PROOF, private=False)
    if (evidence.read_bytes() != RETAINED_PROOF.read_bytes() or
            proof.get('profile') != RETAINED_PROFILE or
            any(proof.get(k) is not True for k in ('original_ap_retained_verified', 'declared_topology_audit_verified',
                'same_kernel_ram_canary_ap_viewer_pid_and_flocks', 'four_disk_phase_bindings_verified',
                'source_and_target_normal_qmp_exit')) or any(proof.get(k) is not False for k in
                ('full_device_audit_complete', 'sony_wbi_verified', 'hardware_hotboot_verified',
                 'full_boot_verified', 'capture_verified', 'ui_hot_enabled'))):
        refuse('retained_audit_proof', 'Audit must reference the exact fixed actual proof with its limits')
    report = path_checked(RETAINED_REPORT)
    if RETAINED_QEMU_SHA not in report.read_text():
        refuse('retained_audit_proof', 'Fixed report does not bind the retained binary')
    analysis = path_checked(capability['runtime_analysis'], directory=True)
    if analysis != Path(context['runtime']) / 'analysis':
        refuse('sequence_runtime', 'Sequence runtime_analysis must belong to the explicit current runtime')
    checked_binding(capability['cold_manifest'], private=True)
    checked_binding(capability['combo_manifest'])
    checked_binding(capability['backend_source'], expected_path=HERE / 'retained-camera-test.py')
    checked_binding(capability['persistent_module'])
    path_checked(capability['origin_qemu_build'], directory=True)
    return capability


def live_module():
    spec = importlib.util.spec_from_file_location('_retained_camera_live', HERE / 'retained-camera-live.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hot_capability(context, instance):
    """Main publishes this only after reviewing a closed actual live-owner run."""
    capability = context.get('available_capabilities', {}).get('hot')
    fields = {'available', 'contract', 'instance_identity', 'retained_audit', 'backend_source',
              'live_owner', 'live_validation'}
    if not isinstance(capability, dict) or set(capability) != fields:
        refuse('live_owner_required', 'Hot requires an explicit live owner and reviewed actual live validation')
    if (capability.get('available') is not True or capability.get('contract') != SCHEMA or
            capability.get('instance_identity') != instance):
        refuse('capability_instance_mismatch', 'Hot capability contract/instance/generation mismatch')
    sequence = sequence_capability(context, instance)
    if capability['retained_audit'] != sequence['retained_audit']:
        refuse('retained_audit_scope', 'Live hot must retain the fixed declared-topology audit')
    checked_binding(capability['backend_source'], expected_path=HERE / 'retained-camera-live.py')
    proof = read_json(checked_binding(capability['live_validation'], private=True))
    if (proof.get('schema') != 'a7c2-retained-camera-live-v1' or proof.get('status') != 'passed' or
            proof.get('actual_content_verified') is not True or proof.get('owners_closed') is not True or
            proof.get('instance_identity') != instance or proof.get('profile') != RETAINED_PROFILE or
            proof.get('qemu_sha256') != RETAINED_QEMU_SHA or proof.get('source_tree_sha256') != RETAINED_SOURCE_SHA or
            any(proof.get(k) is not False for k in ('full_boot_verified', 'full_device_audit_complete',
                'sony_wbi_verified', 'hardware_hotboot_verified', 'capture_verified', 'ui_hot_enabled',
                'gui_owner_switch_verified'))):
        refuse('live_actual_validation_required', 'Hot needs a main-reviewed actual closed live run with its limits')
    backend = live_module()
    if proof.get('source_bindings') != backend.SOURCE_BINDINGS:
        refuse('live_source_changed', 'Reviewed live run used different backend sources')
    backend.inspect_owner(capability['live_owner'], instance)
    return capability


def plan(context, args, *, support=controller_supported):
    target = args.target if args.action == 'plan' else args.action
    validate_mode(args, target)
    if target not in CONTROLLERS:
        refuse('unknown_action', '不支持的执行动作')
    instance = bind_instance(context)
    capabilities = context.get('available_capabilities', {})
    capability = capabilities.get(target)
    if not isinstance(capability, dict) or capability.get('available') is not True:
        detail = capability.get('blocked_reason') if isinstance(capability, dict) else None
        refuse('required_stage_unavailable', str(detail or f'{target}：持久实例的后端阶段尚未接入'))
    if capability.get('instance_identity') != instance:
        refuse('capability_instance_mismatch', '执行能力没有绑定当前实例及 generation')
    if capability.get('contract') != SCHEMA:
        refuse('controller_contract', '后端尚未提供固件开发请求/回执契约')
    if target in ('hot', 'sequence'):
        audit = capability.get('retained_audit', {})
        if (audit.get('complete') is not True or audit.get('compatible') is not True or
                audit.get('external_state_verified') is not True or
                audit.get('instance_identity') != instance):
            refuse('retained_audit_required', '热启动需要完整 retained 设备/外部状态审计；不回退冷启动')
        path_checked(audit.get('evidence'), private=True)
    if target == 'sequence':
        sequence_capability(context, instance)
    elif target == 'hot':
        hot_capability(context, instance)
    controller = path_checked(str(HERE / CONTROLLERS[target]))
    if not support(controller):
        refuse('controller_not_integrated', controller.name + ' 尚未接入同一持久实例协议；保留原诊断入口')
    return {'target': target, 'controller': str(controller), 'instance_identity': instance,
            'required_stages': list(STAGES[target]), 'profile': args.profile,
            'signature_policy': 'virtual-device-only-bypass' if args.virtual_dev_update else 'verify-official',
            'cold_fallback_allowed': False, 'host_functional_fallback_allowed': False,
            'source_mutation_allowed': False}


def status_fields(context):
    runtime = context.get('runtime_state', {})
    if not isinstance(runtime, dict):
        runtime = {}
    instance = context.get('instance_identity') or {}
    sha = runtime.get('actual_ap_sha256', '')
    return {'instance': str(instance.get('id', '未绑定')), 'generation': str(instance.get('generation', '未知')),
            'disk': str(instance.get('disk', '未绑定')),
            'ap_sha': sha[:12] if isinstance(sha, str) and re.fullmatch('[0-9a-f]{64}', sha) else '未观测',
            'wbi': str(runtime.get('wbi_state', '未观测')),
            'changed_persistent': str(runtime.get('changed_persistent', '未观测')),
            'runtime': context['runtime'], 'workspace': context['workspace']}


def new_job(context, args):
    parent = Path(context['workspace'])
    for name in ('.a7c2', 'firmware-development', 'runs'):
        parent = parent / name
        if not parent.exists():
            parent.mkdir(mode=0o700)
        path_checked(str(parent), directory=True, private=True)
    directory = parent / ('job-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    result = {'schema': SCHEMA, 'job_id': directory.name, 'run_id': directory.name,
              'action': args.action, 'profile': args.profile, 'status': 'running',
              'created_ns': time.time_ns(), 'physical_devices_used': False,
              'result_path': str(directory / 'result.json'), 'record_dir': str(directory),
              'first_error_path': '', **status_fields(context)}
    write_json(directory / 'result.json', result)
    return directory, result


@contextmanager
def instance_lock(directory, instance):
    # Controller must still take its native lifecycle lock and revalidate identity.
    name = hashlib.sha256(instance['disk'].encode()).hexdigest()
    path = directory.parent.parent / ('instance-' + name + '.lock')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode) != 0o600):
            refuse('instance_lock_invalid', '固件开发实例锁无效')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            refuse('instance_busy', '该实例已有固件开发任务')
        yield
    finally:
        os.close(fd)


def checked_package(value):
    path = path_checked(value)
    if not 8 <= path.stat().st_size <= 2 * 1024 ** 3:
        refuse('package_size', 'BODYDATA 包大小不在 8 B 至 2 GiB 范围内')
    return path


def signature_policy(inspection, virtual_dev):
    if inspection.get('outer_crc_valid') is not True:
        refuse('package_crc', 'UFU CRC 尚未验证')
    signature = inspection.get('signature', {}).get('status')
    if signature != 'valid' and not virtual_dev:
        refuse('signature_not_verified', '官方更新要求有效签名，当前结果：' + str(signature))
    return {'observed': signature, 'bypassed': bool(virtual_dev and signature != 'valid'),
            'scope': 'local-virtual-device' if virtual_dev else 'official'}


def update_module():
    spec = importlib.util.spec_from_file_location('_firmware_dev_update', HERE / 'virtual-update.py')
    update = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(update)
    return update


def inspect_package(context, args, output):
    package = checked_package(args.package)
    update = update_module()
    output.mkdir(mode=0o700)
    source = update._Source(package)
    try:
        fd = update.FAT.secure_open(output, directory=True)
        try:
            inspected = update._inspect_package(source, fd)
        finally:
            os.close(fd)
        write_json(output / 'ufu-inspection.json', inspected)
        policy = signature_policy(inspected, args.virtual_dev_update)
        fwtool = path_checked(context.get('package_tools', {}).get('fwtool_dir'), directory=True)
        decoded_dir = output / 'decoded'
        decoded_dir.mkdir(mode=0o700)
        decoded = update.decode_package(package, decoded_dir, fwtool_dir=fwtool)
        if decoded.get('package', {}).get('sha256') != inspected['sha256']:
            refuse('package_changed', 'FDAT 解码与 UFU 校验不是同一包')
        source.verify()
        if decoded.get('header_crc_valid') is not True or decoded.get('block_checksums_valid') is not True:
            refuse('fdat_not_verified', 'FDAT header 或解密块校验未通过')
        result = {'status': 'completed', 'message': 'UFU/FDAT CRC、解密块和签名策略已校验',
                  'inspection': decoded, 'signature_policy': policy, 'package_sha256': inspected['sha256'],
                  'guest_original_install_verified': False, 'package_validation_only': True}
        write_json(output / 'inspection.json', result)
        return result
    finally:
        source.close()


def crypto_python(context):
    value = context.get('package_tools', {}).get('python', sys.executable)
    if not isinstance(value, str) or not re.fullmatch(r'python(?:3(?:\.\d+)?)?', Path(value).name):
        refuse('crypto_python', '包工具必须使用明确的 Python 解释器')
    # A trusted main-owned context may name a venv interpreter symlink.
    resolved = Path(value).resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        refuse('crypto_python', '包工具 Python 不可执行')
    return str(resolved)


def run_logged(argv, log, runner):
    with log.open('x', encoding='utf-8') as stream:
        os.chmod(log, 0o600)
        # No shell, timeout, signals or process-group termination: owner cleanup is
        # the core controller's job even if the UI stops observing.
        return runner(argv, stdout=stream, stderr=subprocess.STDOUT, check=False)


def validate_in_subprocess(context, args, directory, runner):
    checked_package(args.package)
    argv = [crypto_python(context), '-B', str(HERE / 'firmware-development.py'), '_inspect',
            '--context', str(args.context), '--package', str(args.package), '--profile', args.profile]
    if args.virtual_dev_update:
        argv.append('--virtual-dev-update')
    log = directory / 'package-tool.log'
    completed = run_logged(argv, log, runner)
    lines = log.read_text(encoding='utf-8') if log.stat().st_size <= LIMIT else ''
    try:
        child = json.loads(lines)
    except ValueError:
        refuse('package_tool_receipt', '包校验子进程没有返回有界 JSON 回执；详见 package-tool.log')
    if not isinstance(child, dict) or child.get('schema') != SCHEMA or child.get('action') != '_inspect':
        refuse('package_tool_receipt', '包校验子进程回执身份不一致')
    if completed.returncode or child.get('status') != 'completed':
        reason = child.get('blocked_reason', {})
        refuse(str(reason.get('code', 'package_validation_failed')), str(reason.get('detail', child.get('message', '包校验失败'))))
    if not re.fullmatch('[0-9a-f]{64}', str(child.get('package_sha256', ''))):
        refuse('package_tool_receipt', '包校验子进程缺少 SHA256')
    child_path = path_checked(child.get('result_path'), private=True)
    if not child_path.is_relative_to(directory.parent) or read_json(child_path) != child:
        refuse('package_tool_receipt', '包校验成功回执必须对应本工作目录中的原始持久记录')
    return child


def verified_receipt(receipt, request, directory, returncode):
    if (receipt.get('schema') != SCHEMA or
            any(receipt.get(key) != request[key] for key in ('job_id', 'run_id', 'instance_identity', 'action'))):
        refuse('receipt_binding', '控制器回执与任务/实例/generation 不一致')
    if receipt.get('status') == 'blocked':
        reason = receipt.get('blocked_reason', {})
        refuse(str(reason.get('code', 'controller_blocked')), str(reason.get('detail', '后端拒绝执行')))
    if returncode != 0 or receipt.get('status') != 'completed':
        refuse('controller_failed', '控制器没有完成执行，退出码：' + str(returncode))
    stages = receipt.get('stages', {})
    for stage in request['required_stages']:
        evidence = stages.get(stage, {})
        kind = 'persistent_device' if stage in PERSISTENT_STAGES else 'guest_original'
        if evidence.get('verified') is not True or evidence.get('execution_kind') != kind:
            refuse('required_stage_unverified', stage + ' 尚未实际消费/验证；不会启用替代后端')
        evidence_path = path_checked(evidence.get('path'), private=True)
        if not evidence_path.is_relative_to(directory):
            refuse('evidence_scope', '证据必须来自本次 job 目录')
        with evidence_path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if evidence.get('sha256') != actual:
            refuse('evidence_hash', stage + ' 的证据摘要不一致')
        if request['action'] in ('sequence', 'hot'):
            contents = read_json(evidence_path)
            if (any(contents.get(key) != request[key] for key in ('schema', 'job_id', 'run_id', 'instance_identity', 'action')) or
                    contents.get('stage') != stage or contents.get('verified') is not True or
                    any(contents.get(key) is not False for key in
                        ('sony_wbi_verified', 'hardware_hotboot_verified', 'capture_verified'))):
                refuse('required_stage_unverified', stage + ' 的阶段内容未绑定本次 sequence 或越出范围')
    return receipt


def dispatch(args, *, runner=subprocess.run, support=controller_supported):
    result = {'schema': SCHEMA, 'action': args.action, 'status': 'blocked',
              'message': '', 'first_error_path': '', 'result_path': '', 'record_dir': ''}
    directory = None
    try:
        context = load_context(args.context)
        result.update(status_fields(context))
        validate_mode(args, args.target if args.action == 'plan' else args.action)
        if args.action == 'status':
            result.update(status='ready', message='已读取主界面显式上下文；未启动虚拟机')
            try:
                bind_instance(context)
            except Blocked as error:
                result.update(status='blocked', blocked_reason={'code': error.code, 'detail': str(error)}, message=str(error))
            return result
        if args.action == 'plan':
            result.update(plan=plan(context, args, support=support), status='planned', message='执行计划已就绪；尚未执行')
            return result
        directory, result = new_job(context, args)
        if args.action == '_inspect':
            result.update(inspect_package(context, args, directory / 'package'))
        elif args.action == 'validate-package':
            child = validate_in_subprocess(context, args, directory, runner)
            result.update(status='completed', message=child['message'], inspection_result=child,
                          package_sha256=child['package_sha256'])
        else:
            execution = plan(context, args, support=support)
            request = {**execution, 'schema': SCHEMA, 'job_id': result['job_id'], 'run_id': result['run_id'],
                       'action': args.action, 'context_path': str(args.context), 'runtime': context['runtime'],
                       'workspace': context['workspace'], 'output_dir': str(directory),
                       'controller_result': str(directory / 'controller-result.json'),
                       'virtual_dev_update': args.virtual_dev_update}
            if args.action in ('prepare-sd', 'update'):
                request['package'] = str(checked_package(args.package))
                inspection = validate_in_subprocess(context, args, directory, runner)
                request['package_sha256'] = inspection['package_sha256']
                request['package_validation_result'] = inspection['result_path']
            if args.action in ('cold', 'sequence', 'hot'):
                request['boot_profile'] = {'cold': 'original-init-cold', 'sequence': 'qemu-retained-roundtrip',
                                           'hot': 'qemu-live-retained-roundtrip'}[args.action]
            write_json(directory / 'request.json', request)
            argv = [sys.executable, '-B', execution['controller'], '--firmware-development-request',
                    str(directory / 'request.json')]
            with instance_lock(directory, execution['instance_identity']):
                current = load_context(args.context)
                if current != context or bind_instance(current) != execution['instance_identity']:
                    refuse('context_changed', '执行前上下文代发生变化，请刷新')
                completed = run_logged(argv, directory / 'controller.log', runner)
                receipt = verified_receipt(read_json(request['controller_result']), request, directory, completed.returncode)
            result.update(status='completed', message='后端所需阶段已完成并绑定本次实例', controller_receipt=receipt)
    except (OSError, ValueError, RuntimeError, SyntaxError, KeyError, TypeError, ImportError, subprocess.SubprocessError) as error:
        result.update(status='blocked' if isinstance(error, Blocked) else 'failed', message=str(error),
                      blocked_reason={'code': getattr(error, 'code', 'backend_error'), 'detail': str(error)})
        if directory is not None:
            error_path = directory / 'first-error.json'
            write_json(error_path, {'type': type(error).__name__, **result['blocked_reason']})
            result['first_error_path'] = str(error_path)
    if directory is not None:
        result['finished_ns'] = time.time_ns()
        write_json(directory / 'result.json', result)
    return result


def human(result):
    fields = {'action': result['action'], 'status': result['status'], 'message': result.get('message', ''),
              'blocked_code': result.get('blocked_reason', {}).get('code', '')}
    for key in ('instance', 'generation', 'disk', 'ap_sha', 'wbi', 'changed_persistent', 'runtime', 'workspace',
                'job_id', 'run_id', 'first_error_path', 'result_path', 'record_dir'):
        fields[key] = result.get(key, '')
    return 'FIRMWARE_DEV_V1\n' + ''.join(key + '=' + quote(str(value), safe='') + '\n' for key, value in fields.items()) + 'END\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=(*ACTIONS, '_inspect'))
    parser.add_argument('--context', type=Path, required=True, help='main-owned 0600 explicit context JSON')
    parser.add_argument('--human', action='store_true', help='bounded percent-encoded keyline UI protocol')
    parser.add_argument('--profile', default='official')
    parser.add_argument('--target', choices=tuple(CONTROLLERS), default='cold', help='plan only')
    parser.add_argument('--package', type=Path)
    parser.add_argument('--virtual-dev-update', action='store_true')
    args = parser.parse_args(argv)
    result = dispatch(args)
    print(human(result) if args.human else json.dumps(result, ensure_ascii=False, allow_nan=False), end='\n')
    return 0 if result['status'] in ('ready', 'planned', 'completed') else 2


if __name__ == '__main__':
    raise SystemExit(main())
