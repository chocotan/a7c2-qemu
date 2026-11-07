"""Bind the native diagnostic's actual execution to its limited boot coverage."""
import hashlib
import json
from pathlib import Path
import re

from boot_flow import evaluate, new_receipt, record_stage


def validate_profile(profile, require_full=False):
    if profile != 'direct-bootin':
        raise ValueError('The native probe executes direct-bootin only; use the full-system boot-session entry for the original boot chain')
    if require_full:
        raise ValueError('direct-bootin cannot satisfy full boot: loader, original init/chroot, CP and watchdog are not executed')


def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def begin(run, image, command, *, profile='direct-bootin'):
    validate_profile(profile)
    run, image = Path(run), Path(image)
    receipt = new_receipt(profile, bindings={
        'run': run.name, 'source_class': 'native-diagnostic-derived',
        'initramfs': {'path': str(image), 'sha256': sha256(image)},
        'command': [str(value) for value in command],
    })
    receipt['execution_limits'] = {
        'sony_loader_executed': False, 'original_ram_init_executed': False,
        'original_pivot_chroot_executed': False, 'original_init2_executed': False,
        'cp_image_executed': False, 'wbi_resume_executed': False,
        'ram_hotboot_executed': False, 'sd_updater_executed': False,
        'watchdog_verified': False,
    }
    save(run, receipt)
    return receipt


def evidence(receipt, artifact, *, source='guest', **fields):
    artifact = Path(artifact)
    return dict(run=receipt['bindings']['run'], generation=receipt['generation'],
                binding_digest=receipt['binding_digest'], source_class=receipt['bindings']['source_class'],
                source=source, artifacts=[{'path': artifact.name, 'sha256': sha256(artifact)}], **fields)


def save(run, receipt):
    data = {'schema': 1, 'receipt': receipt, 'coverage': evaluate(receipt)}
    path = Path(run) / 'boot-flow.json'
    temporary = path.with_suffix('.json.new')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)
    return data['coverage']


def finish(run, receipt, summary=None):
    """Use the full-console guest census, never requested flags or QEMU_BOOT_TYPE."""
    run = Path(run)
    console = run / 'console.log'
    if console.is_file():
        text = console.read_text(errors='replace').replace('\r', '')
        if 'Linux version ' in text:
            record_stage(receipt, 'kernel', execution_kind='guest_original', status='passed',
                         evidence=evidence(receipt, console))
        matches = re.findall(r'(?:^|\n)(?:\[[^\n]*?\]\s*)?Kernel command line:\s*([^\n]+)', text)
        if matches:
            record_stage(receipt, 'kernelargs', execution_kind='host_observed', status='passed',
                         evidence=evidence(receipt, console, cmdline=matches[-1].strip()))
        # diag.sh derives these counters from the complete guest observer log.
        returned = max([int(v) for v in re.findall(r'\breturn_asi=(\d+)', text)] or [0])
        entered = max([int(v) for v in re.findall(r'\benter_asi=(\d+)', text)] or [0])
        if entered and returned and summary and summary.get('appfw_init_entered') and summary.get('appfw_init_returned'):
            record_stage(receipt, 'ap', execution_kind='guest_original', status='passed',
                         evidence=evidence(receipt, console))
    return save(run, receipt)
