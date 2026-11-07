"""Finite private inputs for the explicit functional EE observer build; no VM entry."""
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
PROFILE = 'ee-normal-wake-cold-functional-v1'
CONTRACT = dict(profile=PROFILE, queue='0x80020002', ee_can_publish=False,
                publication_api=True, functional_model=True, max_seconds=120, copy_limit=12, taps=8)
PUBLIC = ('usb-ee-normal-cold.py', 'usb-ee-normal-cold.inc', 'usb-ee-zero-observe.inc',
          'ee-normal-wake-cold.c', 'ee-normal-wake-cold.h', 'ee-capability-input.c',
          'ee-capability-input.h', 'prepare-ee-normal-wake-cold.py', 'ee-capability-contract.py',
          '../../runtime/analysis/device-models/imaging-device.h')
SOURCES = {'callback': 'EE_NWC_CALLBACK', 'kerneldefault': 'EE_NWC_KERNELDEFAULT'}
KERNEL_UIPC = dict(bytes=76360, sha256='f0eb3a32a9d339066600e012aa3e91de31419c173e3fe5c1cc44aa9188763095',
                   vermagic='4.9.337-scel+ SMP preempt mod_unload aarch64')

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def plain(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError('EE private input must be a regular non-symlink file: ' + str(path))
    return path

def binding(role, path):
    path = plain(path)
    return dict(role=role, path=str(path), bytes=path.stat().st_size, sha256=digest(path))

def load_model(path):
    model = json.loads(plain(path).read_text())
    old_fields = {'schema', 'profile', 'generation', 'force_e0', 'be9bae_byte9', 'stable_state_hex', 'adc_hex'}
    if not old_fields <= model.keys() <= old_fields | {'admission_source', 'diagnostic_checkpoints'}:
        raise ValueError('EE functional model requires the exact finite initial-state/ADC fields')
    if type(model['schema']) is not int or model['schema'] != 1 or model['profile'] != PROFILE:
        raise ValueError('EE functional model explicit profile/schema mismatch')
    source = model.get('admission_source', 'callback')
    if type(source) is not str or source not in SOURCES:
        raise ValueError('EE functional admission_source is missing or unknown')
    model['admission_source'] = source
    if type(model.get('diagnostic_checkpoints', False)) is not bool:
        raise ValueError('EE diagnostic_checkpoints must be a strict boolean')
    model.setdefault('diagnostic_checkpoints', False)
    if type(model['generation']) is not int or not 0 < model['generation'] < 2**64:
        raise ValueError('EE functional model generation must be positive uint64')
    for key in ('force_e0', 'be9bae_byte9'):
        if type(model[key]) is not int or not 0 <= model[key] <= 255:
            raise ValueError('EE functional model byte out of range: ' + key)
    try:
        adc = bytes.fromhex(model['adc_hex'])
        state = bytes.fromhex(model['stable_state_hex'])
    except (ValueError, TypeError) as error:
        raise ValueError('EE functional model ADC/state hex invalid') from error
    if len(adc) != 48:
        raise ValueError('EE functional model requires two actual 24-byte ADC samples')
    return model, adc, state

def prepare(analysis, inputs):
    analysis = Path(analysis)
    if set(inputs) != {'backup', 'vendor', 'cp', 'model'}:
        raise ValueError('EE functional profile needs explicit backup/vendor/cp/model inputs')
    private = [binding('ee-private-' + name, inputs[name]) for name in ('backup', 'cp', 'model')]
    public = {name: digest(HERE / name) for name in PUBLIC}
    helper = runpy.run_path(str(HERE / 'prepare-ee-normal-wake-cold.py'))
    if private[0]['sha256'] != helper['BACKUP_SHA'] or private[1]['sha256'] != helper['CONTRACT']['CP_SHA']:
        raise ValueError('EE complete Backup/CP source identity mismatch')
    model, adc, state = load_model(inputs['model'])
    envelope = helper['prepare'](inputs['backup'], inputs['vendor'], model['generation'])
    rows = bytes.fromhex(envelope['rows_hex'])
    if len(state) != len(rows)//4:
        raise ValueError('EE functional stable state must be exactly 16 bytes per actual keymap row')
    envelope_path = analysis / 'private-ee-normal-cold-input.json'
    header_path = analysis / 'private-ee-normal-cold-input.h'
    payload = (json.dumps(envelope, indent=2) + '\n').encode()
    helper['private_write'](envelope_path, payload)
    def array(name, data):
        return 'static const uint8_t ' + name + '[]={' + ','.join(map(str, data)) + '};\n'
    header = helper['render_header'](envelope) + array('ee_cold_adc', adc) + array('ee_cold_state', state)
    header += ('#define EE_COLD_ADMISSION_SOURCE ' + SOURCES[model['admission_source']] + '\n'
               '#define EE_COLD_DIAGNOSTICS ' + str(int(model['diagnostic_checkpoints'])) + '\n'
               '#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 1\n')
    header += ('static const uint8_t ee_cold_force=' + str(model['force_e0']) + ',ee_cold_be9=' + str(model['be9bae_byte9']) + ';\n'
               'static const char ee_cold_input_sha256[]="' + hashlib.sha256(payload).hexdigest() + '";\n'
               'static const char ee_cold_model_sha256[]="' + private[2]['sha256'] + '";\n')
    helper['private_write'](header_path, header.encode('ascii'))
    private += [binding('ee-private-envelope', envelope_path), binding('ee-private-header', header_path)]
    if any(binding(item['role'], item['path']) != item for item in private):
        raise ValueError('EE private inputs changed during extraction')
    if {name: digest(HERE / name) for name in PUBLIC} != public:
        raise ValueError('EE source changed during private extraction')
    return dict(profile=PROFILE, admission_source=model['admission_source'], admission_version=1,
                diagnostic_checkpoints=model['diagnostic_checkpoints'], native_allocation_log_commit_required=True,
                native_allocation_log_commit_version=1,
                kernel_uipc=KERNEL_UIPC if model['admission_source']=='kerneldefault' else None,
                generation=model['generation'], public_sources=public, private_inputs=private,
                private_header=str(header_path.absolute()), rows_bytes=len(rows), model_defined=15,
                strict_can_publish=False, stage_actual=False, original_cp_history_verified=False)

def validate(analysis, contract):
    if (contract.get('native_allocation_log_commit_required') is not True or
            type(contract.get('native_allocation_log_commit_version')) is not int or contract['native_allocation_log_commit_version'] != 1 or
            type(contract.get('diagnostic_checkpoints')) is not bool or
            type(contract.get('admission_source')) is not str or contract.get('admission_source') not in SOURCES or
            type(contract.get('admission_version')) is not int or contract.get('admission_version') != 1 or
            type(contract.get('generation')) is not int or not 0 < contract.get('generation') < 2**64 or
            contract.get('kernel_uipc') != (KERNEL_UIPC if contract.get('admission_source')=='kerneldefault' else None) or
            contract.get('profile') != PROFILE or contract.get('strict_can_publish') is not False or
            contract.get('stage_actual') is not False or contract.get('model_defined') != 15 or
            contract.get('original_cp_history_verified') is not False or
            contract.get('public_sources') != {name: digest(HERE / name) for name in PUBLIC}):
        raise ValueError('EE functional source/profile identity drift')
    paths = contract.get('private_inputs', [])
    if len(paths) != 5 or {p['role'] for p in paths} != {'ee-private-' + n for n in ('backup', 'cp', 'model', 'envelope', 'header')}:
        raise ValueError('EE functional private input bindings missing')
    for item in paths:
        if binding(item['role'], item['path']) != item:
            raise ValueError('EE functional private input identity drift: ' + item['role'])
    byrole = {p['role']: Path(p['path']) for p in paths}
    analysis = Path(analysis).absolute()
    if (byrole['ee-private-header'] != analysis / 'private-ee-normal-cold-input.h' or
            byrole['ee-private-envelope'] != analysis / 'private-ee-normal-cold-input.json' or
            contract.get('private_header') != str(byrole['ee-private-header'])):
        raise ValueError('EE functional generated inputs escaped their fresh helper directory')
    for name in ('header', 'envelope'):
        if byrole['ee-private-' + name].stat().st_mode & 0o077:
            raise ValueError('EE functional generated input permissions are not private')
    model, _, state = load_model(byrole['ee-private-model'])
    if model['admission_source'] != contract['admission_source']:
        raise ValueError('EE functional admission source differs from prepared model')
    if ('#define EE_COLD_ADMISSION_SOURCE ' + SOURCES[model['admission_source']] + '\n') not in byrole['ee-private-header'].read_text():
        raise ValueError('EE functional admission header linkage drift')
    if model['diagnostic_checkpoints'] != contract['diagnostic_checkpoints']:
        raise ValueError('EE diagnostic option differs from prepared model')
    header = byrole['ee-private-header'].read_text()
    if (header.count('#define EE_COLD_DIAGNOSTICS ' + str(int(model['diagnostic_checkpoints'])) + '\n') != 1 or
            header.count('#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 1\n') != 1):
        raise ValueError('EE diagnostics/allocation log header linkage drift')
    if model['generation'] != contract.get('generation') or len(state) != contract['rows_bytes']//4:
        raise ValueError('EE functional input generation/size drift')
    return paths + [binding('ee-source-' + Path(name).name, HERE / name) for name in PUBLIC]


def allocation_log_commit_proven(contract):
    """Read actual bound build inputs/output; a bare manifest boolean is insufficient."""
    try:
        private = contract['ee_normal_cold']
        if (private.get('native_allocation_log_commit_required') is not True or
                type(private.get('native_allocation_log_commit_version')) is not int or
                private['native_allocation_log_commit_version'] != 1 or
                type(private.get('diagnostic_checkpoints')) is not bool or
                private.get('public_sources') != {name: digest(HERE / name) for name in PUBLIC}):
            return False
        pins = [p for p in private['private_inputs'] if p['role'] == 'ee-private-header']
        if len(pins) != 1 or binding('ee-private-header', pins[0]['path']) != pins[0]:
            return False
        header = plain(pins[0]['path'])
        if str(header) != private['private_header'] or header.stat().st_mode & 0o077:
            return False
        text = header.read_text()
        if (text.count('#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 1\n') != 1 or
                text.count('#define EE_COLD_DIAGNOSTICS ' + str(int(private['diagnostic_checkpoints'])) + '\n') != 1):
            return False
        command = contract.get('command', [])
        if (command.count(str(HERE / 'usb-start-observe.c')) != 1 or
                command.count('-DUSB_EE_NORMAL_COLD=1') != 1 or
                command.count('-DUSB_EE_NORMAL_COLD_INPUT="' + str(header) + '"') != 1 or
                any(arg.startswith('-DEE_COLD_') for arg in command) or
                contract.get('source_sha256') != digest(HERE / 'usb-start-observe.c') or
                contract.get('builder_sha256') != digest(HERE / 'usb-start-observe.py') or
                contract.get('ee_observer') != dict(CONTRACT, source_sha256=digest(HERE / 'usb-ee-zero-observe.inc'))):
            return False
        observer = plain(header.parent / 'root/simulation/usb-start-observe.so')
        image = observer.read_bytes()
        return (digest(observer) == contract.get('observer_sha256') and
                image[:6] == b'\x7fELF\x02\x01' and image[18:20] == b'\xb7\x00' and
                b'native_allocation_log_commit_required=1 native_allocation_log_commit_version=1' in image)
    except (OSError, ValueError, KeyError, TypeError):
        return False
