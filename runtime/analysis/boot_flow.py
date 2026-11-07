"""Sony 2.01 route model and coverage gate; this module never boots or reads devices.

Collectors attest observations: artifact references do not authenticate content.
Evidence needs run/generation/binding_digest/source/source_class/artifacts;
artifacts are [{"path": ..., "sha256": ...}]. source is guest or host. Bindings'
source_class is one label or a stage->label map; private-device-dump stays distinct
from official assets. Missing backends are unknown, not failed reads.
"""
import copy
import hashlib
import json
import re

PROFILES = ('direct-bootin', 'original-init-cold', 'ram-hotboot', 'wbi-resume', 'sd-update')
LOADER_SHA256 = '9ad6bc5822a1a22e600e20a3b7b1dc42ffbfc9f7f9d90f7f3717b994c24d5ccf'
# Array order, not event_id order; original table 0xfe064538, selector 0xfe051230.
EVENT_MODES = (
    ('updater', 3), ('adjust', 5), ('wl_anki', 5), ('bis_1st', 12),
    ('bis_2nd', 12), ('ontimer', 9), ('ontimrz', 7), ('keychat', 7),
    ('lowbatt', 7), ('panlopn', 7), ('panlapo', 7), ('batt_in', 7),
    ('psw_off', 7), ('chg_app', 7), ('usbcoff', 7), ('rec_off', 7),
    ('reallow', 7), ('usbchrg', 6), ('hoff_en', 0), ('ddr_off', 14),
    ('bi_vali', 13), ('hotboot', 2), ('ssboot', 11), ('ss_bis', 11), ('cldboot', 1),
)
COLD_STAGES = ('kernel', 'kernelargs', 'ram_init', 'mounts', 'pivot_root', 'chroot',
               'old_root_unmounted', 'ram0_release', 'init2', 'bootin', 'im', 'ap')
STAGES = COLD_STAGES + ('cp', 'loader', 'wbi', 'ram_hotboot', 'watchdog', 'backend',
                        'pp', 'sd_receiver', 'sd_install', 'sd_readback', 'post_reset')
KINDS = ('guest_original', 'guest_adapter', 'host_observed', 'host_declared', 'host_functional')
STATUSES = ('passed', 'failed', 'unknown', 'skipped')


def _result(status, **values):
    return dict(status=status, missing=[], **values)


def select_route(predicates):
    """Model 0xfe051230, not execution. Absent/None predicates remain unknown."""
    names = dict(EVENT_MODES)
    if not isinstance(predicates, dict) or set(predicates) - names.keys():
        raise ValueError('Expected predicates keyed by official event names')
    if any(v is not None and type(v) is not bool for v in predicates.values()):
        raise ValueError('Predicates must be bool or None')

    def unknown(keys):
        return dict(status='unknown', mode=None, event=None, missing=list(keys))

    for group in (range(6), range(6, 17), range(21, 25)):
        for index in group:
            event, mode = EVENT_MODES[index]
            value = predicates.get(event)
            if value is None:
                return unknown([event])
            if not value:
                continue
            if 6 <= index <= 16:
                usb = predicates.get('usbchrg')
                if usb is None:
                    return unknown(['usbchrg'])
                if usb:
                    return _result('selected', mode=6, event=event)
                # Any false conjunct prevents the override, even if another is unknown.
                gate = {k: (not predicates[k] if predicates.get(k) is not None else None)
                        for k in ('keychat', 'lowbatt')}
                gate.update((k, predicates.get(k)) for k in ('hoff_en', 'ddr_off'))
                if not any(v is False for v in gate.values()):
                    missing = [k for k, v in gate.items() if v is None]
                    if missing:
                        return unknown(missing)
                    valid = predicates.get('bi_vali')
                    if valid is None:
                        return unknown(['bi_vali'])
                    mode = 13 if valid else 14
            return _result('selected', mode=mode, event=event)
    return _result('selected', mode=1, event='default')


def resolve_resume(route, ld_read, ld, h, retained_ram_bound=False):
    """ld_read: observed read success bool/None; ld: uint32; h: observed H bit0.

    mode11 skips p5 only when the observed read succeeded, ld is 1/2 and H is
    true (0xfe051198). False ld_read means an actual failed read; use None for
    an unavailable backend. A selected path does not prove its execution.
    """
    if any(v is not None and type(v) is not bool for v in (ld_read, h)):
        raise ValueError('ld_read and h must be bool or None')
    if ld is not None and (type(ld) is not int or not 0 <= ld <= 0xffffffff):
        raise ValueError('ld must be uint32 or None')
    if type(retained_ram_bound) is not bool:
        raise ValueError('retained_ram_bound must be bool')
    path, missing = None, []
    if not isinstance(route, dict):
        raise ValueError('Expected selector route')
    mode = route.get('mode') if route.get('status') == 'selected' else None
    if mode is not None and type(mode) is not int:
        raise ValueError('Route mode must be an integer')
    if mode == 2:
        path = 'ram-hotboot'
    elif mode == 11:
        if ld_read is None:
            missing = ['ld_read']
        elif ld_read is False or (ld is not None and ld not in (1, 2)) or h is False:
            path = 'wbi-resume'
        elif ld is None or h is None:
            missing = [k for k, v in (('ld', ld), ('h', h)) if v is None]
        else:
            path = 'ram-hotboot'
    elif mode == 1:
        path = 'cold'
    else:
        missing = ['route' if mode is None else 'mode_resume_semantics']
    if path == 'ram-hotboot' and not retained_ram_bound:
        missing = ['retained_ram_bound']
    return dict(status='unknown' if missing else 'resolved', path=path, missing=missing)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _binding(receipt):
    return {k: receipt[k] for k in ('profile', 'bindings', 'kernel_cmdline', 'generation')}


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Expected lowercase SHA256')


def _source_class(receipt, stage):
    value = receipt['bindings']['source_class']
    if isinstance(value, dict) and stage not in value:
        raise ValueError('Missing source_class for stage: ' + stage)
    return value[stage] if isinstance(value, dict) else value


def new_receipt(profile, *, bindings, kernel_cmdline=None, generation=0):
    """bindings needs run, source_class (label or stage map), and selected inputs."""
    if profile not in PROFILES or type(generation) is not int or generation < 0:
        raise ValueError('Invalid boot profile or generation')
    if not isinstance(bindings, dict) or not isinstance(bindings.get('run'), str) or not bindings['run'].strip():
        raise ValueError('bindings.run is required')
    classes = bindings.get('source_class')
    labels = list(classes.values()) if isinstance(classes, dict) else [classes]
    if not labels or any(not isinstance(v, str) or not v.strip() for v in labels):
        raise ValueError('bindings.source_class is required')
    if isinstance(classes, dict) and set(classes) - set(STAGES):
        raise ValueError('Unknown source_class stage')
    if kernel_cmdline is not None and not isinstance(kernel_cmdline, str):
        raise ValueError('kernel_cmdline must be a string or None')
    receipt = dict(profile=profile, bindings=copy.deepcopy(bindings), generation=generation,
                   kernel_cmdline=kernel_cmdline, stages=[])
    receipt['binding_digest'] = _digest(_binding(receipt))
    return receipt


def _check_record(receipt, record):
    if record['stage'] not in STAGES or record['execution_kind'] not in KINDS or record['status'] not in STATUSES:
        raise ValueError('Invalid stage, execution kind or status')
    evidence = record['evidence']
    if (not isinstance(evidence, dict) or evidence.get('run') != receipt['bindings']['run'] or
            type(evidence.get('generation')) is not int or evidence['generation'] != receipt['generation'] or
            evidence.get('binding_digest') != receipt['binding_digest']):
        raise ValueError('Evidence run/generation/binding mismatch')
    if evidence.get('source_class') != _source_class(receipt, record['stage']):
        raise ValueError('Evidence source_class mismatch')
    kind, source = record['execution_kind'], evidence.get('source')
    if source not in ('guest', 'host') or (kind.startswith('guest_') and source != 'guest') or (
            kind in ('host_declared', 'host_functional') and source != 'host'):
        raise ValueError('Execution kind contradicts evidence source')
    if record['status'] == 'passed':
        artifacts = evidence.get('artifacts')
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError('Passed stages need hashed artifact references')
        for artifact in artifacts:
            if not isinstance(artifact, dict) or not isinstance(artifact.get('path'), str) or not artifact['path'].strip():
                raise ValueError('Artifact path is required')
            _sha(artifact.get('sha256'))
    for key in ('input_sha256', 'output_sha256'):
        if record.get(key) is not None:
            _sha(record[key])


def record_stage(receipt, stage, *, execution_kind, status, evidence,
                 input_sha256=None, output_sha256=None):
    """Append without erasing failures. A later same-generation observation may retry."""
    if receipt['binding_digest'] != _digest(_binding(receipt)):
        raise ValueError('Receipt bindings changed')
    record = dict(stage=stage, execution_kind=execution_kind, status=status,
                  evidence=copy.deepcopy(evidence), input_sha256=input_sha256, output_sha256=output_sha256)
    _check_record(receipt, record)
    receipt['stages'].append(record)


def evaluate(receipt):
    """Revalidate persisted records; return explicit blockers for the final exit gate."""
    blockers, latest = [], {}
    try:
        validated = new_receipt(**_binding(receipt))
        if validated['binding_digest'] != receipt['binding_digest']:
            raise ValueError('Receipt bindings changed')
        if not isinstance(receipt['stages'], list):
            raise ValueError('Invalid stages')
        for record in receipt['stages']:
            _check_record(receipt, record)
            latest[record['stage']] = record
    except (KeyError, TypeError, ValueError) as error:
        blockers.append('invalid receipt: ' + str(error))
        latest = {}
    if not isinstance(receipt, dict):
        receipt = {}
    verified = {}
    for stage in STAGES:
        item = latest.get(stage, {})
        kind, evidence = item.get('execution_kind'), item.get('evidence', {})
        original = kind == 'guest_original' and evidence.get('source') == 'guest'
        allowed = (original or stage == 'backend' and kind == 'guest_adapter' or
                   stage in ('old_root_unmounted', 'ram0_release') and kind == 'host_observed' and evidence.get('source') == 'guest')
        if stage == 'kernelargs':
            observed = evidence.get('cmdline')
            allowed = ((original or kind == 'host_observed' and evidence.get('source') == 'guest') and
                       isinstance(observed, str) and bool(observed.strip()) and
                       receipt.get('kernel_cmdline') in (None, observed))
        verified[stage] = not blockers and item.get('status') == 'passed' and allowed
    cold_missing = [s for s in COLD_STAGES if not verified[s]]
    profile = receipt.get('profile')
    if profile not in PROFILES:
        profile = None
    required = ('kernel', 'kernelargs', 'bootin', 'im', 'ap', 'loader', 'cp', 'watchdog', 'backend')
    required += {'original-init-cold': COLD_STAGES, 'ram-hotboot': ('ram_hotboot',),
                 'wbi-resume': ('wbi',),
                 'sd-update': COLD_STAGES + ('sd_receiver', 'sd_install', 'sd_readback', 'post_reset')}.get(profile, ())
    blockers += [s + ': missing original execution or verified observation' for s in dict.fromkeys(required) if not verified[s]]
    if profile == 'direct-bootin':
        blockers.append('direct-bootin is a diagnostic profile')
    cmdline = latest.get('kernelargs', {}).get('evidence', {}).get('cmdline')
    if isinstance(cmdline, str) and '__boottime___udif_init_udif_wdt' in cmdline:
        blockers.append('watchdog initialization is bypassed in observed kernelargs')
    install = latest.get('sd_install', {})
    binding = receipt.get('bindings')
    return dict(source_class=copy.deepcopy(binding.get('source_class') if isinstance(binding, dict) else None),
                stage_verified=verified, ap_verified=verified['ap'],
                cold_guest_chain_verified=not cold_missing and profile in ('original-init-cold', 'sd-update'),
                cold_chain_blockers=cold_missing, full_boot_verified=not blockers, blockers=blockers,
                host_functional_install_verified=bool(install.get('status') == 'passed' and
                    install.get('execution_kind') == 'host_functional' and not any(
                        b.startswith('invalid receipt:') for b in blockers)))
