#!/usr/bin/env python3
"""Extract only the pinned original3006 route/module declarations; no execution."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

SHA256 = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
BIAS = 0x108000


def verify(path):
    with path.open('rb') as source:
        blob = source.read(18090881)
    if len(blob) != 18090880 or hashlib.sha256(blob).hexdigest() != SHA256:
        raise ValueError('unsupported CP identity')

    def region(address, size):
        raw = address - BIAS
        if not 0 < size or not 0 <= raw <= len(blob) - size:
            raise ValueError('range outside CP')
        return blob[raw:raw + size]

    def path_at(address, expected):
        count, = struct.unpack('<H', region(address, 2))
        result = list(struct.unpack('<' + 'H' * count, region(address + 2, count * 2)))
        if result != expected:
            raise ValueError('unexpected path')
        return result

    def transition(address, origin, target):
        current, to, pointer, count = struct.unpack('<4I', region(address, 16))
        if (current, to) != (origin, target) or not 0 < count <= 64:
            raise ValueError('unexpected transition declaration')
        words = struct.unpack('<' + 'H' * count, region(pointer, 2 * count))
        if not words[-1] & 0x8000:
            raise ValueError('missing final boundary')
        return {'from': current, 'to': to, 'sequence_cpva': f'{pointer:x}',
                'words': [f'{v:04x}' for v in words],
                'masks': [f'{v & 0x1fff:04x}' for v in words if v & 0x8000]}

    direct = transition(0xd96420, 0, 1)
    after = transition(0xd96430, 0x1b, 1)
    if direct['masks'] != ['037f'] or after['masks'] != ['013e', '0041', '0001']:
        raise ValueError('required-mask mismatch')
    variants = [transition(0xd94970 + i * 16, 0, 0x1b) for i in range(6)]
    if variants[0] != variants[5]:
        raise ValueError('shared0/5 sequence differs')
    pins = {
        'descriptor_broadcast_index': (0xb1f3b4, '130a00eb4303da82'),
        'requested_getter_index': (0xb1f3ce, '00eb4100008b7047'),
        'descriptor0301_getter2_P6': (0x4d7bda, '022047f2e0f2abf80600'),
        'descriptor0401_getter3_Pa': (0x4d7bee, '032047f2d6f2abf80a00'),
        'descriptor0301_parameter_work_source': (0x328792,
                                                'd8f80000c088abf80000abf80400'),
        'descriptor0301_save_prior_header': (0x328782, 'bbf80000'),
        'descriptor0301_parameter_getter': (0x8779f4, '42f65820c0f201207047'),
        'descriptor0301_periodic_copy': (0x8a6d8a,
                                        'b0b502af0c46014640f64c7294f81f5a204677f536ec84f81f5ab0bd'),
        'slot1_builder_full_request': (0x9925b0, '30680089a0825df8048bf0bd'),
        'slot1_publish_selector': (0x39e5a6, '207880f0010020709ce3'),
        'refresh_context_G': (0x4da064, '4ef6e879c0f27319'),
        'refresh_context_P': (0x4d9f28, '4ff65061'),
        'refresh_context_P_high': (0x4d9f36, 'c0f27211085c0c46'),
        'refresh_context_R8_P': (0x4d9f76, 'a046'),
        'refresh_primary': (0x4da08a,
                            'b7f08ef644f64061c9f8440048f8010000f5f67100f5f470c9f87010c9f89800'),
        'refresh_alternate': (0x4da24a,
                              'b7f0aef544f64061c9f8440048f8010000f5f67100f5f470c9f87010c9f89800'),
        'backup_init_fixed_window': (0x55dcc2, '4ff0806000f069f9'),
        'backup_init_header_pointer': (0x55dfb0, 'c0f2a7110860'),
        'backup_init_sections': (0x55dfce, '4ef6600200f58071c0f2a7121160'),
        'slot1_input_I_getter': (0xa96d5c, '47f27810c0f2101000687047'),
        'slot1_I_zero_mapping_leaf': (0xa548e2, '01207047'),
        'slot1_I_to_M': (0x9a749e,
                        '80b56f46eff05bfc012808d048b9adf019fa01460220002918bf012080bd012080bd002080bd'),
        'slot1_periodic_M_writer': (0x39ee4c,
                                   '08f227f3064647f66870c0f28b10d0f800b0066089f83260'),
        'slot1_completion_thunk': (0x637074, '826808461047'),
        'slot1_completion_occupancy_clear': (0x4de190,
                                          '02460d2a09d2bff35f8f4af61c000021c0f2a61040f822107047'),
    }
    for name, (address, expected) in pins.items():
        original = bytes.fromhex(expected)
        if region(address, len(original)) != original:
            raise ValueError(f'original instruction mismatch: {name}')
    banks = region(0x10fe9c8, 2 * 0x210)
    if region(0x1107178, 4) != bytes.fromhex('03000000'):
        raise ValueError('original I initializer differs')
    shadow_rows = []
    for address, expected in ((0xd530dc, (0x02a40000, 0x17929b0, 0x1200)),
                              (0xd53184, (0x02a4000e, 0x179d0b0, 0x700))):
        actual = struct.unpack('<3I', region(address, 12))
        if actual != expected:
            raise ValueError('original shadow registration row differs')
        shadow_rows.append({'id': f'{actual[0]:08x}', 'destination_cpva': f'{actual[1]:x}',
                            'capacity': actual[2], 'table_cpva': f'{address:x}'})
    return {'verified': True, 'scope': 'original ROM declarations, not runtime readiness',
            'cp_sha256': SHA256,
            'selector_0051001d_zero_path': path_at(0xeda184, [0x1b, 1]),
            'selector_0051001d_nonzero_path': path_at(0xeda18a, [1]),
            'direct': direct, 'after_1b': after, 'variants': variants,
            'descriptor_getters': {'0301': {'index': 2, 'root_offset': 6},
                                   '0401': {'index': 3, 'root_offset': 10}},
            'slot1': {'bank_base_cpva': '10fe9c8', 'selector_cpva': '1b15ff4',
                      'bank_size': 0x210, 'bank_count': 2, 'completion_offset': 0x14,
                      'original_file_banks_sha256': hashlib.sha256(banks).hexdigest(),
                      'original_file_bank_completion_bytes':
                          [banks[i * 0x210 + 0x14:i * 0x210 + 0x16].hex() for i in range(2)],
                      'refresh_call_cpvas': ['4da08a', '4da24a'],
                      'original_input_I': 3, 'periodic_derived_M_for_I3': 0,
                      'work_context_N_cpva': '1a6a85c', 'snapshot_root_D_cpva': '1734ed8',
                      'completion_words': ['637075', '0', '4de191', '0', '0'],
                      'completion_module': 1, 'occupancy_cpva': '1a6a820',
                      'refresh_conditions_always_true': False,
                      'runtime_initialization_or_completion_proven': False},
            'backup_loader': {'primary_window_cpva': '04000000',
                              'public_seed_to_runtime_window_binding_proven': False},
            'shadow_registration_rows': shadow_rows,
            'instruction_pins': {name: f'{address:x}' for name, (address, _) in pins.items()},
            'selected_variant_proven': False, 'required_consumers_completed': False,
            'cp3006_success_implemented': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path, default=Path(__file__).resolve().parents[2] /
                        'runtime/analysis/menu-root/cp/cpapp-b.bin')
    print(json.dumps(verify(parser.parse_args().cp), indent=2))
