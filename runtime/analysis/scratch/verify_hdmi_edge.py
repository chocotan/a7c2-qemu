#!/usr/bin/env python3
"""Read-only HDMI11 content checks, using the existing checker's Log interface.

verify_hdmi_effects(log) checks actual virtual-owner effects (also host C traces).
verify_hdmi_upm(log, run) independently joins the two real kernel retirements;
it deliberately does not assert that conditions or the AP edge completed.
verify_hdmi_edge(log, previous_free, identity, first_graph_request, run) requires
both, plus constructor and canonical Get retirements. The outer verifier owns
build/source identity, prior edges, resource locks, SD, and whole-run cleanup.
Only delayed kind-2 free notes require this helper's same-run frozen-source join;
standalone effects/condition checks without run keep strict console ordering.
Gate-v2 requires keyword gate_v2_trust with caller-bound plan/intent/parent references;
these hashes must come from the next once tool after its complete cohort readback.
No function writes an artifact, starts a process, or accesses a VM/socket.
"""
# SPDX-License-Identifier: MIT
import hashlib
import importlib.util
import io
from pathlib import Path
import re
import struct
import tarfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace

BASE = Path(__file__).resolve().parents[1]
PREFIX = 'FULL_PINMEM_HDMI_VIDEO_CONNECT'
STATE = 'FULL_HDMI_VIDEO_STATE'
PROFILE = 'virtual-pinmem-video0-hdmi-video0-initializing-v1'
S = (4, 2, 0, 0x90590818)
P = (4, 1, 0, 0x909a015a)
TOKEN = 0x504d4000
UPM = 0x80920572
CONDITION_SOURCE = 0x91ca0816
CONDITION_SID = 0x802a0116
IDS = (0, 0x17, 0x16, 0x15, 0x14, 0x13, 0x12, 0x11, 0x23, 0x22, 0x21, 0x30)
_WATCH = None
MAX_RETAINED_IMAGE = 768 * 1024**2
RUN_BINDINGS = {
    'source-snapshot-run-binding.json': ('functional-source-snapshot-run-v1',),
    'readonly-scope-run-binding.json': ('functional-M-v2-run-v2', 'functional-M-v3-run-v3',
                                      'functional-shutter-gate-v1-run-v1', 'functional-shutter-gate-v2-run-v1'),
}
RUN_FALSE_FIELDS = ('capture_verified', 'native_verified', 'native_AP_provider',
                    'physical_asic_compatibility_verified', 'original_Fsys_save_verified')
SCOPE_FALSE_FIELDS = RUN_FALSE_FIELDS + ('sony_branch_verified', 'sony_store_verified',
    'original_poweron_or_late_runtime_verified', 'cap', 'physical', 'branchretirement', 'storecompletion')
SCOPE_PLAN_FIELDS = ('nonce', 'batch', 'batch_ready_sha256', 'runtime_ready', 'parent_readback',
    'fresh_guest', 'runtime_assets_sha256', 'scope_observer_expected', 'synthetic_fixture_manifest', 'actual_api_contract')
SCOPE_SOURCE_NAMES = ('scope-observer.c', 'late-sites.inc', 'build-plugin.sh', 'log-schema-v2.json',
    'source-contract-v2.json', 'check_run_context_v2.py', 'check_run_context.py',
    'integration/scope_trace_checks_v2.py', 'integration/scope_trace_checks.py')
SCOPE_SOURCE_NAMES_V3 = ('scope-observer.c', 'late-sites.inc', 'build-plugin.sh', 'log-schema-v3.json',
    'source-contract-v3.json', 'check_run_context_v3.py', 'check_run_context.py',
    'integration/scope_trace_checks_v3.py', 'integration/scope_trace_checks.py')
SCOPE_BINDING_VERSIONS = {'functional-M-v2-run-v2': 2, 'functional-M-v3-run-v3': 3}
SHUTTER_GATE_RUN = 'functional-shutter-gate-v1-run-v1'
SHUTTER_GATE_PROFILE = 'qemu-readonly-shutter-gate-v1'
SHUTTER_GATE_COMPONENT = 'report/2026-10-31-qemu-shutter-gate-observer-v1'
SHUTTER_GATE_PLAN_FIELDS = SCOPE_PLAN_FIELDS + ('shutter_gate_reader_expected',)
SHUTTER_GATE_FALSE_FIELDS = SCOPE_FALSE_FIELDS + ('runtime_verified', 'originalMain',
    'Main_identity_verified', 'AP_identity_verified', 'branch_edge_verified', 'retirement',
    'instruction_retirement_verified', 'invocation_pairing_verified')
SHUTTER_GATE_READER_FIELDS = ('qemu_sha256', 'library_sha256', 'source_sha256',
    'fixture_source_sha256', 'qemu_header_sha256', 'observer_sha256', 'Main_source_sha256',
    'original_appfw_sha256', 'trace_schema_sha256', 'build_receipt_sha256', 'readonly_import_audit_sha256')
SHUTTER_GATE_SOURCE_NAMES = ('scope-observer.c', 'build-plugin.sh', 'build-runtime.py',
    'log-schema-shutter-gate-v1.json', 'source-contract-shutter-gate-v1.json',
    'check_shutter_gate_v1.py', 'integration/shutter_gate_trace_checks_v1.py')
SHUTTER_GATE_FIXTURE_NAMES = ('integration/fixture.S', 'integration/link.ld', 'integration/run_fixture.py',
    'integration/test_fixture_driver.py', 'integration/test_actual_scope_plugin.py',
    'integration/test_shutter_gate_trace_checks_v1.py', 'integration/shutter_gate_trace_checks_v1.py')
SHUTTER_GATE_V2_RUN = 'functional-shutter-gate-v2-run-v1'
SHUTTER_GATE_V2_LEGACY_DEFAULT_SHA = 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02'
SHUTTER_GATE_V2_PROFILE = 'qemu-readonly-shutter-gate-v2'
SHUTTER_GATE_V2_COMPONENT = 'report/2026-11-02-qemu-shutter-gate-observer-v2'
SHUTTER_GATE_V2_SOURCE_NAMES = ('scope-observer.c', 'build-plugin.sh', 'build-runtime.py',
    'log-schema-shutter-gate-v2.json', 'source-contract-shutter-gate-v2.json',
    'check_shutter_gate_v2.py', 'integration/shutter_gate_trace_checks_v2.py')
SHUTTER_GATE_V2_FIXTURE_NAMES = ('integration/fixture.S', 'integration/link.ld', 'integration/run_fixture.py',
    'integration/test_fixture_driver.py', 'integration/test_actual_scope_plugin.py',
    'integration/test_shutter_gate_trace_checks_v2.py', 'integration/shutter_gate_trace_checks_v2.py')
SHUTTER_GATE_API_CASES = ('original_entry', 'existing_main_stub_entry', 'one_byte_gate_mutation', 'short_tb')
PIN_PEER_RUNTIME_READY_SHA = '9041c1f61dfa111c5e0d7d38b00b3f98701ec8b2272841813c3e009ceb3a5844'
PIN_PEER_PARENT_READBACK_SHA = 'ec390649f007592ba10b56bf167a289975ef1ad3845d06c492669738524172ca'
PIN_PEER_SOURCE_APPROVAL_SHA = '8daa0ce8a967ed0d73f69299de1186b9c5710beb8ec17835cd3118b574706c6f'
PIN_PEER_CANDIDATE_SHA = '09cba2fdaac0f56918dc85e0662fbfd5a7673f79aaad20be2b2d02706e74f279'
SHUTTER_GATE_ALIASES = frozenset(('source_root', 'Source_root', 'root', 'sourceDependencyFrozen',
    'schema_sha256', 'log_schema_sha256', 'v3_schema_sha256'))


class _ImageBytes:
    """Let the existing newc verifier consume the exact bytes already hashed."""
    def __init__(self, raw):
        self.raw = raw

    def open(self, mode):
        require(mode == 'rb', 'condition image reader is read-only')
        return io.BytesIO(self.raw)

    def stat(self):
        return SimpleNamespace(st_size=len(self.raw))


# Exact reviewed ledger, receive/free hooks and linking recipe; new versions need review.
CONDITION_LEDGER_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': '9d880941dbb3c8b58b9d020563a006fc216a6a69a9ce6281ec73dd627fe711c4',
    'build-observers.sh': 'a9f33123ee99178589dc73377b378f90bfc2c053e43b582870709e495f75bd1d',
}


SOURCE_SETS = (CONDITION_LEDGER_SOURCES, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': '370909f58d73951d6be4bbb54adaab9e3e45cf97eaebc94e02abbbd4d3f86b59',
    'build-observers.sh': 'b023e1b2b2b10e53ef8dcc4c7ddde1d8e49eede62e404cbcf5ca0d5ce790c45f',
}, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': 'ccac63643d3ea5b2a57e09c3d4c74812c6812e92ecbbd9bfc22ec953d310d8b3',
    'build-observers.sh': 'f6dd02116c51456b056e90939de45cfc46abc28e4311f0edac38ca41ad5394d8',
}, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': '68006c1667712c76af96b08d042e37cd888ebf7a98cafd63630fe8943e161009',
    'build-observers.sh': 'f6dd02116c51456b056e90939de45cfc46abc28e4311f0edac38ca41ad5394d8',
}, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': '2b399aa1191ecd3882c13b2729c1ac639d03c2187414025673a09d153af241af',
    'build-observers.sh': 'f6dd02116c51456b056e90939de45cfc46abc28e4311f0edac38ca41ad5394d8',
}, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': '56c8158267f1281e5ee13f0a8f653d20f2189769d7f5df4c65efa08ff20ede1f',
    'build-observers.sh': 'f6dd02116c51456b056e90939de45cfc46abc28e4311f0edac38ca41ad5394d8',
}, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': 'a1916f6504931eb8683fb1723f2ec0bc9f59e2908c5c0866d9f8b56b07c56adc',
    'build-observers.sh': 'f6dd02116c51456b056e90939de45cfc46abc28e4311f0edac38ca41ad5394d8',
}, {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': 'a1916f6504931eb8683fb1723f2ec0bc9f59e2908c5c0866d9f8b56b07c56adc',
    'build-observers.sh': '0f894c14659617d92e1af00b5864ca953a1fd619e75f882f39b4691dbdeb3a15',
}, {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': 'a1916f6504931eb8683fb1723f2ec0bc9f59e2908c5c0866d9f8b56b07c56adc',
    'build-observers.sh': '49993d6ccd614d00dfdfd57c4c8dc633f5ebffcfcb325dce3b73df760afac7ed',
}, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': '8731af154b460c2219cf31f6b110210d9ebb264c6f6e931555818f1941d0b842',
    'build-observers.sh': 'daac9dd3ddaa08d4f6deb0f75bc1dc70c4d82663d185d9f3f135966eae7ac964',
}, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': '8731af154b460c2219cf31f6b110210d9ebb264c6f6e931555818f1941d0b842',
    'build-observers.sh': '4e7b97f488fbb1e91e249720a00ec668f16555f57193288332c517fb197a7593',
}, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': '8731af154b460c2219cf31f6b110210d9ebb264c6f6e931555818f1941d0b842',
    'build-observers.sh': 'd9a6136ba19493fc4d794f3b7f0a8be47b846cf6d9c501b1f14c033d903f23b3',
}, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': 'df698a99b6c559fd3f850c4964eb28e558e32c6255d12fb2242d259157621af5',
    'build-observers.sh': 'd9a6136ba19493fc4d794f3b7f0a8be47b846cf6d9c501b1f14c033d903f23b3',
}, {
    **CONDITION_LEDGER_SOURCES,
    'menu-observe.c': 'df698a99b6c559fd3f850c4964eb28e558e32c6255d12fb2242d259157621af5',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
})


# Separate exact revision; the historical SOURCE_SETS AST stays frozen.
FOCUS_RESET_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': 'd0019703c78e6d7f9a834e0c262cfad595cd3da6684fa5de43ad26f40d5ea871',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


FOCUS_RESET_ZERO_INIT_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': '3af8ebdb96cfb65ce9c1553fedfa8006920269183468f82c4991f20471a1dbf7',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


SCENE_FOCUS_MIRROR_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': 'ddcbf279cfe8b0b9c065227472a97090013cb1affee9d5676bce9b19fb176106',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


HUTI_FOCUS_QUERY_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': '97d22e4722f41e136f21e1ffe872805a1dd7941a78c3a1c8c03be2fd9cd8f784',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


PKNP_VDF163_DISPATCH_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': 'fc8198547bd98d960deff68cbe63089523d5913113a71b41c3626b21c66e5593',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


OV45_HDMI_SIGNAL_MODE_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': 'c200237a3613c1bcbd626b5d1c874426c3c5f16d7ff2216f95506291cdde9d4d',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


E6U_HDMI_INITIAL_PREFIX_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': 'f65f68470f83c0ee8f8ec0757cf948184c0a090ad0632364db505f7a4a1699ba',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


GKH1_CP4073_ZERO_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': '43712beef87dcc5eb022d53dec7c5daa7ce043b83a1a8b48de4ed7152d86f71a',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


GKH1_CP4073_ZERO_RETIRE_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': 'c75fd58e246e86d80bd5f452fed67fc9ac37d8d715bfe16786ba425d70318354',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


VDF170_EFRAMING_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': '417cc5553f365d2452f1e8f6a943f8dfbf9b23f2b516a5b9e71174c8a381ad61',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


ZQ6_CP_PARAMETER_BANK_CONDITION_SOURCES = {
    'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2',
    'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722',
    'menu-observe.c': 'fbc8122dd76651aac22045ba850fe9f3a00588d0e5fcb6d456775259c24fa3b7',
    'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef',
}


QR5_NATIVE_EVIDENCE_CONDITION_SOURCES = {'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2', 'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722', 'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef', 'menu-observe.c': '3d5153a54747b2b5016ac71a037243b86bd9c2a738a1cd3c1913451395f2ad3c', 'device-models/functional-camera-control.c': 'd937099ad6a791fac6d9db6e0e7835482db5e18d6426dd6ed86c4bae3ddec0f4', 'device-models/functional-camera-control.h': '1d4532ade1069242de967ea301c57111f24d3fc8dae8b66e7830758c6d3d688e', 'functional-camera-bridge.c': 'a3d620be6c66fb5c0e72070fa0e55177899585d0c1723fc4f379cd98f3e1601b', 'functional-camera-bridge.h': '16fdf80631293854e88856557ef98fdf2f6a6c3a6eb4fed95fb3c23fdad90132', 'functional-camera-abi.h': '2ecc4f60bb415a4d23d3549769ce61c2b6caaf3ec13bd4282809014dada4ff72', 'functional_camera_broker.py': '642863b21f489c825df77194a5577a86eac1969768488272fe512090bbe76091', 'backup_profile.py': '4fcb7627f2262b7c77b145f12e8ae4bd6a7697c379b67cce363e2e83434735f1'}


JKY_CP_MOVIE_FORMAT_CONDITION_SOURCES = {'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2', 'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722', 'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef', 'menu-observe.c': 'dfcb9bffcf4e25a95d2163c4d90e395db90f513f007e93cea3140e76d4b7c96d', 'device-models/functional-camera-control.c': '994a32f29b3a019dec8a3906d7d6f11f12c24b4dbc62c197ec03abc99a109aff', 'device-models/functional-camera-control.h': 'eac1424b0e6fb5123bd420b422b1f924e579e1951df0b8b133bb9f55b1242b0c', 'functional-camera-bridge.c': '7389591af400de414ca19ff99fb22391b73a38225756e7b6c057a36a547fbd44', 'functional-camera-bridge.h': '00858396997b5bbad82e9b3569064383816f8ae5bdaaa5f5ac6512e08fe9f04e', 'functional-camera-abi.h': '999de8ca662fd71eee32927cb1d211799a345357ca1d6aa98582d0b444f47e32', 'functional_camera_broker.py': '3fdd5847b535bd4f527bb33eda910d6effef519009d0a5cb253731080ce7b050', 'backup_profile.py': '4fcb7627f2262b7c77b145f12e8ae4bd6a7697c379b67cce363e2e83434735f1'}


EHG_CP_OU_CRANK_CONDITION_SOURCES = {'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2', 'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722', 'build-observers.sh': 'f5c3dbe9c84e0aea94f6d59c46eaf17294d211021d64b5aae39d523759328cef', 'menu-observe.c': '7e5ac74b26a37b69e61dd02ce6d2ecbdcd68327f92e40bec907953793f9d7ab4', 'device-models/functional-camera-control.c': '0ff483dff256d90a6c359022f1bf9b341df1500813020327e7b87ee3d14a0361', 'device-models/functional-camera-control.h': 'e09b1cd0cbb196d27f29ede7966f02f835e543ebf83eb99cbf9de3648f780826', 'functional-camera-bridge.c': '5a80426bbf01eac364a290f8a3f262e67083bf50391cb4874065003ef1666310', 'functional-camera-bridge.h': '3b0e8a4139597562eb2258eace9a4618121964516608713cc1d8009c7426ec9d', 'functional-camera-abi.h': '587775a58b59dbbfe9938d0eeb8e2875050f22e680b90c6e5c0ab14b41168b77', 'functional_camera_broker.py': '8a4cbb5a5908b6cff8e6c7720b9eceed8abdd59dcace58d4857f75937716ad39', 'backup_profile.py': '33e0ce4dbfdf04ee5221f0964950b6df8780dc0ff5d56792c072c956d437cc06'}


MOF_BB_TIMECODE_CONDITION_SOURCES = {'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2', 'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722', 'build-observers.sh': 'd8a80b4e6bdc4eb89b85184a8a38284d485c2c7d86b619a65e4e4dd5d6f7cefe', 'menu-observe.c': 'ad3c3664719d7a5691899d180079e1c825acd50e2c6d1cb186bb9681e0ffd251', 'device-models/functional-camera-control.c': '0ff483dff256d90a6c359022f1bf9b341df1500813020327e7b87ee3d14a0361', 'device-models/functional-camera-control.h': 'e09b1cd0cbb196d27f29ede7966f02f835e543ebf83eb99cbf9de3648f780826', 'functional-camera-bridge.c': '5a80426bbf01eac364a290f8a3f262e67083bf50391cb4874065003ef1666310', 'functional-camera-bridge.h': '3b0e8a4139597562eb2258eace9a4618121964516608713cc1d8009c7426ec9d', 'functional-camera-abi.h': '587775a58b59dbbfe9938d0eeb8e2875050f22e680b90c6e5c0ab14b41168b77', 'functional_camera_broker.py': '8a4cbb5a5908b6cff8e6c7720b9eceed8abdd59dcace58d4857f75937716ad39', 'backup_profile.py': '8908d3b1d7fc022fa2d01e90ae9eff21ddd8f5003d244d3b1ab9f00e555cfc96', 'device-models/bb-timecode-control.c': 'e1f5f01dde35c50abc3e6953d67d80a206ffead5f16d7c158d7ceca66003643f', 'device-models/bb-timecode-control.h': '643c9042bca243784fae8cf66c60b7d10b36f57498d2775431558f94034d3ae5'}


YVO_BB_TIMECODE_PRESET_CONDITION_SOURCES = {'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2', 'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722', 'build-observers.sh': 'd8a80b4e6bdc4eb89b85184a8a38284d485c2c7d86b619a65e4e4dd5d6f7cefe', 'menu-observe.c': '4899afd97aaea06b272a3ec3927b92d2ab482ca9b42a04769cafbe7bac0541e4', 'device-models/functional-camera-control.c': '0ff483dff256d90a6c359022f1bf9b341df1500813020327e7b87ee3d14a0361', 'device-models/functional-camera-control.h': 'e09b1cd0cbb196d27f29ede7966f02f835e543ebf83eb99cbf9de3648f780826', 'functional-camera-bridge.c': '5a80426bbf01eac364a290f8a3f262e67083bf50391cb4874065003ef1666310', 'functional-camera-bridge.h': '3b0e8a4139597562eb2258eace9a4618121964516608713cc1d8009c7426ec9d', 'functional-camera-abi.h': '587775a58b59dbbfe9938d0eeb8e2875050f22e680b90c6e5c0ab14b41168b77', 'functional_camera_broker.py': '8a4cbb5a5908b6cff8e6c7720b9eceed8abdd59dcace58d4857f75937716ad39', 'backup_profile.py': 'b3ecae92a27b9b26508dbd6f16e09af75ff72f05356148a570c166bb5b75dd5f', 'device-models/bb-timecode-control.c': '86d43948fc354599a8d215889844c73733df7c21a9b66cc55f4790958c11f1f6', 'device-models/bb-timecode-control.h': '543bcce45e95a298938c2f7867a7122617b8e60c1d8c40ea399bcb09177307d3'}


def require(value, reason):
    if not value:
        raise ValueError('HDMI11: ' + str(reason))


PRODUCT_DEVELOPMENT_20261108_SOURCES = {'device-models/hdmi-video-state.c': '20c4ff7cd1eca684748ab3f16c55d990dbdd3fa51fe7c85fae6399c99bef32a2', 'device-models/hdmi-video-state.h': 'ae0b6d9beebca768954440a1b86e62bc336d16ccad3c45c1348b2ba03afcd722', 'build-observers.sh': 'd8a80b4e6bdc4eb89b85184a8a38284d485c2c7d86b619a65e4e4dd5d6f7cefe', 'menu-observe.c': 'e2744ae3cf3124e87ab0234309eec302806a515560bbd57bf6d02a96ef106411', 'device-models/functional-camera-control.c': '0ff483dff256d90a6c359022f1bf9b341df1500813020327e7b87ee3d14a0361', 'device-models/functional-camera-control.h': 'e09b1cd0cbb196d27f29ede7966f02f835e543ebf83eb99cbf9de3648f780826', 'functional-camera-bridge.c': '5a80426bbf01eac364a290f8a3f262e67083bf50391cb4874065003ef1666310', 'functional-camera-bridge.h': '3b0e8a4139597562eb2258eace9a4618121964516608713cc1d8009c7426ec9d', 'functional-camera-abi.h': '587775a58b59dbbfe9938d0eeb8e2875050f22e680b90c6e5c0ab14b41168b77', 'functional_camera_broker.py': '8a4cbb5a5908b6cff8e6c7720b9eceed8abdd59dcace58d4857f75937716ad39', 'backup_profile.py': 'b3ecae92a27b9b26508dbd6f16e09af75ff72f05356148a570c166bb5b75dd5f', 'device-models/bb-timecode-control.c': '86d43948fc354599a8d215889844c73733df7c21a9b66cc55f4790958c11f1f6', 'device-models/bb-timecode-control.h': '543bcce45e95a298938c2f7867a7122617b8e60c1d8c40ea399bcb09177307d3', 'observer-process-scope.h': 'd4d96df4991d0518ddff58705cde989855c2717b7e7d2f1b11ea55188a1cf97b'}


def _condition_source_set(sources):
    current=PRODUCT_DEVELOPMENT_20261108_SOURCES
    row=sources.get(str((BASE/'menu-observe.c').resolve()),{})
    if row.get('sha256')==current['menu-observe.c']:
        require(all(str((BASE/name).resolve()) in sources for name in current),
                'missing YVO BB-timecode preset condition source member in product development tuple')
        selected={name:sources[str((BASE/name).resolve())]['sha256'] for name in current}
        require(selected==current,'unreviewed YVO BB-timecode preset condition source tuple in product development')
        return selected
    selected = {name: sources[str(BASE / name)]['sha256'] for name in CONDITION_LEDGER_SOURCES}
    if selected['menu-observe.c'] == YVO_BB_TIMECODE_PRESET_CONDITION_SOURCES['menu-observe.c']:
        require(all(str((BASE / name).resolve()) in sources for name in YVO_BB_TIMECODE_PRESET_CONDITION_SOURCES),
                'missing YVO BB-timecode preset condition source member')
        selected = {name: sources[str((BASE / name).resolve())]['sha256']
                    for name in YVO_BB_TIMECODE_PRESET_CONDITION_SOURCES}
        require(selected == YVO_BB_TIMECODE_PRESET_CONDITION_SOURCES,
                'unreviewed YVO BB-timecode preset condition source tuple')
        return selected
    if selected['menu-observe.c'] == MOF_BB_TIMECODE_CONDITION_SOURCES['menu-observe.c']:
        require(all(str(BASE / name) in sources for name in MOF_BB_TIMECODE_CONDITION_SOURCES),
                'missing MOF BB-timecode condition source member')
        selected = {name: sources[str(BASE / name)]['sha256']
                    for name in MOF_BB_TIMECODE_CONDITION_SOURCES}
        require(selected == MOF_BB_TIMECODE_CONDITION_SOURCES,
                'unreviewed MOF BB-timecode condition source tuple')
        return selected
    if selected['menu-observe.c'] == EHG_CP_OU_CRANK_CONDITION_SOURCES['menu-observe.c']:
        require(all(str(BASE / name) in sources for name in EHG_CP_OU_CRANK_CONDITION_SOURCES),
                'missing EHG OU-crank condition source member')
        selected = {name: sources[str(BASE / name)]['sha256']
                    for name in EHG_CP_OU_CRANK_CONDITION_SOURCES}
        require(selected == EHG_CP_OU_CRANK_CONDITION_SOURCES,
                'unreviewed EHG OU-crank condition source tuple')
        return selected
    if selected['menu-observe.c'] == JKY_CP_MOVIE_FORMAT_CONDITION_SOURCES['menu-observe.c']:
        require(all(str(BASE / name) in sources for name in JKY_CP_MOVIE_FORMAT_CONDITION_SOURCES),
                'missing JKY movie-format condition source member')
        selected = {name: sources[str(BASE / name)]['sha256']
                    for name in JKY_CP_MOVIE_FORMAT_CONDITION_SOURCES}
        require(selected == JKY_CP_MOVIE_FORMAT_CONDITION_SOURCES,
                'unreviewed JKY movie-format condition source tuple')
        return selected
    if selected['menu-observe.c'] == QR5_NATIVE_EVIDENCE_CONDITION_SOURCES['menu-observe.c']:
        require(all(str(BASE / name) in sources for name in QR5_NATIVE_EVIDENCE_CONDITION_SOURCES),
                'missing QR5 native condition source member')
        selected = {name: sources[str(BASE / name)]['sha256']
                    for name in QR5_NATIVE_EVIDENCE_CONDITION_SOURCES}
        require(selected == QR5_NATIVE_EVIDENCE_CONDITION_SOURCES,
                'unreviewed QR5 native condition source tuple')
        return selected
    require(selected in SOURCE_SETS or selected == FOCUS_RESET_CONDITION_SOURCES or
            selected == FOCUS_RESET_ZERO_INIT_CONDITION_SOURCES or selected == SCENE_FOCUS_MIRROR_CONDITION_SOURCES or
            selected == HUTI_FOCUS_QUERY_CONDITION_SOURCES or selected == PKNP_VDF163_DISPATCH_CONDITION_SOURCES or
            selected == OV45_HDMI_SIGNAL_MODE_CONDITION_SOURCES or selected == E6U_HDMI_INITIAL_PREFIX_CONDITION_SOURCES or
            selected == GKH1_CP4073_ZERO_CONDITION_SOURCES or selected == GKH1_CP4073_ZERO_RETIRE_CONDITION_SOURCES or
            selected == VDF170_EFRAMING_CONDITION_SOURCES or selected == ZQ6_CP_PARAMETER_BANK_CONDITION_SOURCES,
            'unreviewed condition ledger/hook source set')
    return selected


def eq(record, **expected):
    for key, value in expected.items():
        require(record['fields'].get(key) == str(value),
                (record['tag'], record['line'], key, record['fields'].get(key), value))
    return record


def number(row, key):
    return int(row['fields'][key], 0)


def one(log, tag):
    rows = log.rows(tag)
    require(len(rows) == 1, (tag, 'expected exactly one record', len(rows)))
    return rows[0]


def raw(row, size):
    eq(row, bytes=size)
    data = bytes.fromhex(row['fields']['raw'])
    require(len(data) == size and data.hex() == row['fields']['raw'], 'noncanonical/incomplete raw bytes')
    return data


def frame(size, command, flags, words, caller=0, opaque=bytes(4)):
    result = bytearray(size)
    struct.pack_into('<IIHHII', result, 0, caller, 0xa0a0a0a0, 1, size, 24, size)
    result[20:24] = opaque
    struct.pack_into('<4H', result, 24, 0x1000, command, size - 24, flags)
    struct.pack_into('<' + 'I' * len(words), result, 32, *words)
    return bytes(result)


def fnv(data):
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return f'{value:016x}'


def _watch():
    global _WATCH
    if _WATCH is None:
        spec = importlib.util.spec_from_file_location('_hdmi11_receipt_reader', BASE / 'hdmi_upm_watch.py')
        _WATCH = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_WATCH)
    return _WATCH


def _kind(log, suffix, kind):
    return [r for r in log.rows(STATE + '_' + suffix) if r['fields'].get('kind') == str(kind)]


def _condition_binding_name(run):
    names = [name for name in RUN_BINDINGS if (run / name).exists() or (run / name).is_symlink()]
    require(len(names) == 1, 'condition source/run binding missing or ambiguous')
    return names[0]


def _condition_binding(graph, run, observer):
    name = _condition_binding_name(run)
    original = graph.read(run / name, graph.MAX_JSON)
    binding = graph.object_json(original)
    require(binding.get('schema') in RUN_BINDINGS[name] and binding.get('run') == str(run) and
            binding.get('observer_sha256') == observer, 'condition source/run binding differs')
    require(type(binding.get('nonce')) is int and 0 < binding['nonce'] < 2**64,
            'condition source/run nonce invalid')
    for key in ('batch_ready_sha256', 'observer_sha256', 'guest_sha256', 'intent_sha256', 'launch_binding_sha256'):
        digest = binding.get(key)
        require(type(digest) is str and len(digest) == 64 and set(digest) <= set('0123456789abcdef'),
                'condition source/run digest invalid: ' + key)
    require(binding.get('claimed_fault_result') == 'FAIL' and
            all(binding.get(key) is False for key in RUN_FALSE_FIELDS), 'condition source/run scope promoted')
    graph.absolute(binding['batch'])
    return name, binding, original


def _condition_scope_binding(graph, reader, run, binding, manifest, build, tested, *, gate_v2_trust=None):
    """Provenance only; AP transactions still require the original content checks."""
    if binding['schema'] == SHUTTER_GATE_V2_RUN:
        return _condition_shutter_gate_binding(graph, reader, run, binding, manifest, build, tested,
                                               gate_v2_trust=gate_v2_trust)
    require(gate_v2_trust is None, 'gate v2 trust cannot authorize another run schema')
    if binding['schema'] == SHUTTER_GATE_RUN:
        return _condition_shutter_gate_binding(graph, reader, run, binding, manifest, build, tested)
    version = SCOPE_BINDING_VERSIONS[binding['schema']]
    fields = SCOPE_PLAN_FIELDS + ('observer_sha256', 'guest_sha256', 'candidate_qemu', 'card')
    required = set(fields) | set(SCOPE_FALSE_FIELDS) | {
        'schema', 'run', 'intent_sha256', 'launch_binding_sha256', 'claimed_fault_result', 'popen_live_sha256'}
    require(set(binding) == required and all(binding.get(k) is False for k in SCOPE_FALSE_FIELDS),
            'condition scope binding fields/claims differ')
    snapshots = {}

    def receipt(path, digest):
        path = graph.absolute(path)
        original = graph.read(path, graph.MAX_JSON)
        require(graph.sha(original) == digest, 'condition scope receipt digest differs: ' + str(path))
        snapshots[path] = original
        return graph.object_json(original)

    fresh_ref = binding['fresh_guest']
    require(type(fresh_ref) is dict and set(fresh_ref) == {'path', 'sha256'} and
            Path(fresh_ref['path']).name == 'fresh-public-guest.json', 'condition fresh guest reference differs')
    fresh = receipt(fresh_ref['path'], fresh_ref['sha256'])
    work = graph.absolute(fresh_ref['path']).parent
    intent = receipt(work / 'intent.json', binding['intent_sha256'])
    launch = receipt(work / 'launch-binding.json', binding['launch_binding_sha256'])
    require(intent.get('schema') == f'functional-M-v{version}-intent-v{version}' and
            launch.get('schema') == f'functional-M-v{version}-launch-v{version}' and
            all(reader.typed_equal(binding[key], intent.get(key)) and
                reader.typed_equal(binding[key], launch.get(key)) for key in fields) and
            launch.get('intent_sha256') == binding['intent_sha256'] and
            intent.get('plan') == launch.get('plan') == str(work / 'plan.json') and
            intent.get('plan_sha256') == launch.get('plan_sha256') and
            all(row.get('claimed_fault_result') == 'FAIL' and all(row.get(k) is False for k in SCOPE_FALSE_FIELDS)
                for row in (intent, launch)), 'condition scope intent/launch provenance differs')
    guest_source = graph.absolute(intent['guest_image'])
    require(manifest.get('probe_args', {}).get('initramfs_file') == str(guest_source) and
            manifest['files'].get(str(guest_source)) == binding['guest_sha256'] and
            fresh.get('guest_image') == str(guest_source) and fresh.get('guest_sha256') == binding['guest_sha256'] and
            fresh.get('ready_sha256') == binding['batch_ready_sha256'] and
            fresh.get('runtime_ready_sha256') == binding['runtime_ready']['sha256'] and
            type(fresh.get('returncode')) is int and fresh['returncode'] == 0 and
            fresh.get('compiled3_unchanged') is True and fresh.get('capture_verified') is False and
            reader.typed_equal(fresh.get('compiled_before'), fresh.get('compiled_after')) and
            fresh.get('compiled_before', {}).get(str(BASE / 'menu-observe.so')) == binding['observer_sha256'],
            'condition scope selected guest/frozen observer differs')
    expected = binding['scope_observer_expected']
    source_names = SCOPE_SOURCE_NAMES_V3 if version == 3 else SCOPE_SOURCE_NAMES
    require(type(expected.get('source_sha256')) is dict and set(expected['source_sha256']) == set(source_names),
            'condition scope source set differs')
    scope = manifest.get('readonly_scope_observer', {})
    plan_binding = {key: binding[key] for key in SCOPE_PLAN_FIELDS}
    metadata_fields = ('profile', 'build_receipt', 'build_receipt_sha256', 'library_sha256', 'qemu_sha256',
        'qemu_header_sha256', 'source_sha256', 'identity_binding', 'capture_verified',
        'physical_asic_compatibility_verified', 'trace_schema', 'trace_schema_sha256', 'source_contract_sha256')
    require(set(scope) == set(metadata_fields) | {'library', 'log', 'plan_binding'} and
            all(reader.typed_equal(scope.get(key), expected.get(key)) for key in metadata_fields
                if key not in ('identity_binding', 'capture_verified', 'physical_asic_compatibility_verified')),
            'condition scope complete metadata/expected identity differs')
    require(reader.typed_equal(scope, dict(expected['build_metadata'],
                library=str(run / 'readonly-scope-observer.so'), log=str(run / 'readonly-scope-trace.log'),
                plan_binding=plan_binding)) and
            scope.get('profile') == f'qemu-readonly-scope-v{version}' and
            scope.get('trace_schema') == f'readonly_scope_v{version}' and
            scope.get('identity_binding') == 'unverified' and scope.get('capture_verified') is False and
            scope.get('physical_asic_compatibility_verified') is False and
            reader.typed_equal(scope.get('source_sha256'), expected['source_sha256']) and
            manifest['selected_initramfs_verified_files'].get('usr/lib/appFw.so') == expected['original_appfw_sha256'] and
            expected['Main_source_sha256'] == build['sources'][str(BASE / 'menu-observe.c')]['sha256'],
            'condition scope actual manifest/module source differs')
    frozen = {}
    for group in tested['groups'].values():
        for name, digest in group.items():
            require(name not in frozen or frozen[name] == digest, 'condition scope frozen source conflict')
            frozen[name] = digest
    root = graph.absolute(expected['source_root'])
    source_component = ('report/2026-10-31-qemu-M-writer-observer-v3' if version == 3 else
                        'report/2026-10-30-qemu-readonly-scope-observer')
    require(root == graph.NATIVE / source_component and
            frozen.get(str(BASE / 'functional_camera_runner.py')) == expected['functional_runner_source_sha256'],
            'condition scope source root/runner differs')
    for name, digest in expected['source_sha256'].items():
        path = graph.absolute(root / name)
        require(path.is_relative_to(root) and frozen.get(str(path)) == digest,
                'condition scope module source is not frozen: ' + name)
        original = graph.read(path)
        require(graph.sha(original) == digest, 'condition scope module source differs: ' + name)
        snapshots[path] = original
    candidate = binding['candidate_qemu']
    require(type(candidate) is dict and set(candidate) == {'path', 'sha256'} and
            str(graph.absolute(candidate['path'])) == manifest['backup_transport']['binary'] and
            candidate['sha256'] == manifest['backup_transport']['binary_sha256'] == expected['qemu_sha256'] and
            manifest['files'].get(candidate['path']) == candidate['sha256'], 'condition scope selected QEMU differs')
    live = receipt(run / 'readonly-scope-popen-live.json', binding['popen_live_sha256'])
    info = run.stat()
    context = dict(schema=f'functional-M-v{version}-live-context-v{version}', run=str(run), run_device=info.st_dev, run_inode=info.st_ino,
        **{key: binding[key] for key in ('nonce', 'batch', 'batch_ready_sha256', 'intent_sha256',
                                       'launch_binding_sha256', 'candidate_qemu', 'card')}, scope=plan_binding)
    require(live.get('schema') == f'functional-M-v{version}-popen-live-v{version}' and
            reader.typed_equal(live.get('context'), context) and
            all(live.get(key) is False for key in SCOPE_FALSE_FIELDS), 'condition scope same-run Popen context differs')
    return guest_source, snapshots


def _condition_shutter_gate_binding(graph, reader, run, binding, manifest, build, tested, *, gate_v2_trust=None):
    """Provenance for the independent observer; never interpret its raw sites as UPM proof."""
    gate_v2 = binding['schema'] == SHUTTER_GATE_V2_RUN
    require(gate_v2 or binding['schema'] == SHUTTER_GATE_RUN, 'shutter gate exact run schema required')
    require(gate_v2 or gate_v2_trust is None, 'gate v2 trust cannot authorize gate v1')
    generation, profile_name, component, trace_name, source_names, fixture_names = (
        ('functional-shutter-gate-v2', SHUTTER_GATE_V2_PROFILE, SHUTTER_GATE_V2_COMPONENT,
         'readonly_shutter_gate_v2', SHUTTER_GATE_V2_SOURCE_NAMES, SHUTTER_GATE_V2_FIXTURE_NAMES) if gate_v2 else
        ('functional-shutter-gate-v1', SHUTTER_GATE_PROFILE, SHUTTER_GATE_COMPONENT,
         'readonly_shutter_gate_v1', SHUTTER_GATE_SOURCE_NAMES, SHUTTER_GATE_FIXTURE_NAMES))
    fields = SHUTTER_GATE_PLAN_FIELDS + ('observer_sha256', 'guest_sha256', 'candidate_qemu', 'card')
    required = set(fields) | set(SHUTTER_GATE_FALSE_FIELDS) | {
        'schema', 'run', 'intent_sha256', 'launch_binding_sha256', 'claimed_fault_result', 'popen_live_sha256'}
    require(set(binding) == required and all(binding.get(k) is False for k in SHUTTER_GATE_FALSE_FIELDS),
            'shutter gate run fields/claims differ')
    snapshots = {}

    def receipt(path, digest=None):
        path = graph.absolute(path)
        original = graph.read(path, graph.MAX_JSON)
        require(digest is None or graph.sha(original) == digest, 'shutter gate receipt digest differs: ' + str(path))
        require(path not in snapshots or snapshots[path] == original, 'shutter gate receipt changed: ' + str(path))
        snapshots[path] = original
        return reader.object_json(original)

    def reference(value):
        require(type(value) is dict and set(value) == {'path', 'sha256'} and
                type(value['sha256']) is str and len(value['sha256']) == 64 and
                set(value['sha256']) <= set('0123456789abcdef'), 'shutter gate exact receipt reference required')
        return receipt(value['path'], value['sha256'])

    if gate_v2:
        require(type(gate_v2_trust) is dict and set(gate_v2_trust) == {'plan', 'intent', 'parent_readback'},
                'gate v2 requires caller-bound immutable plan/intent/parent references')
        work = graph.absolute(gate_v2_trust['plan']['path']).parent
        require(gate_v2_trust['plan']['path'] == str(work / 'plan.json') and
                gate_v2_trust['intent']['path'] == str(work / 'intent.json') and
                gate_v2_trust['intent']['sha256'] == binding['intent_sha256'] and
                reader.typed_equal(gate_v2_trust['parent_readback'], binding['parent_readback']),
                'gate v2 external trust and same-run references differ')
        # Future digests are supplied after cohort completion, never embedded in its own helper source.
        for value in gate_v2_trust.values():
            reference(value)
    fresh_ref = binding['fresh_guest']
    fresh = reference(fresh_ref)
    if not gate_v2:
        work = graph.absolute(fresh_ref['path']).parent
    require(fresh_ref['path'] == str(work / 'fresh-public-guest.json'), 'shutter gate fresh guest path differs')
    intent = receipt(work / 'intent.json', binding['intent_sha256'])
    launch = receipt(work / 'launch-binding.json', binding['launch_binding_sha256'])
    plan = receipt(work / 'plan.json', intent['plan_sha256'])
    require(intent.get('schema') == generation + '-intent-v1' and
            launch.get('schema') == generation + '-launch-v1' and
            plan.get('schema') == generation + '-plan-v1' and
            intent.get('plan') == launch.get('plan') == str(work / 'plan.json') and
            intent['plan_sha256'] == launch.get('plan_sha256') and
            launch.get('intent_sha256') == binding['intent_sha256'] and
            all(reader.typed_equal(binding[key], row.get(key)) for row in (intent, launch) for key in fields) and
            all(row.get('claimed_fault_result') == 'FAIL' and
                all(row.get(k) is False for k in SHUTTER_GATE_FALSE_FIELDS) for row in (plan, intent, launch)),
            'shutter gate plan/intent/launch provenance differs')
    if gate_v2:
        require(intent['plan_sha256'] == gate_v2_trust['plan']['sha256'] and
                all(reader.typed_equal(plan.get(key), binding[key]) for key in fields),
                'gate v2 bound plan provenance differs')
        for row in (plan, intent, launch, fresh):
            _gate_v2_unpromoted(row)
    plan_fields = ('nonce', 'batch', 'batch_ready_sha256', 'runtime_ready', 'parent_readback',
                   'fresh_guest', 'runtime_assets_sha256', 'actual_api_contract', 'candidate_qemu', 'card')
    require(all(reader.typed_equal(plan.get(key), binding[key]) for key in plan_fields) and
            reader.typed_equal(plan.get('actual_api_manifest'), binding['synthetic_fixture_manifest']),
            'shutter gate plan generation differs')
    guest_source = graph.absolute(intent['guest_image'])
    require(plan.get('guest_image') == str(guest_source) and
            manifest.get('probe_args', {}).get('initramfs_file') == str(guest_source) and
            manifest['files'].get(str(guest_source)) == binding['guest_sha256'] and
            fresh.get('guest_image') == str(guest_source) and fresh.get('guest_sha256') == binding['guest_sha256'] and
            fresh.get('ready_sha256') == binding['batch_ready_sha256'] and
            fresh.get('runtime_ready_sha256') == binding['runtime_ready']['sha256'] and
            type(fresh.get('returncode')) is int and fresh['returncode'] == 0 and
            fresh.get('compiled3_unchanged') is True and fresh.get('capture_verified') is False and
            reader.typed_equal(fresh.get('compiled_before'), fresh.get('compiled_after')) and
            fresh.get('compiled_before', {}).get(str(BASE / 'menu-observe.so')) == binding['observer_sha256'],
            'shutter gate selected guest/frozen observer differs')
    batch = graph.absolute(binding['batch'])
    runtime = reference(binding['runtime_ready'])
    parent = reference(binding['parent_readback'])
    pin_peer = not gate_v2 and (Path(binding['runtime_ready']['path']).name == 'pin-peer-release-generation-runtime-ready.json' or
                'source19' in runtime or 'source19' in parent)
    runtime_name, runtime_status, parent_status = (
        ('readonly-shutter-gate-v2-runtime-ready.json', 'PASS_NEW_OFFLINE_SHUTTER_GATE_V2_SUPPLEMENT',
         'PASS_OFFLINE_SHUTTER_GATE_V2_COHORT_READBACK') if gate_v2 else
        ('pin-peer-release-generation-runtime-ready.json', 'PASS_NEW_OFFLINE_PIN_PEER_RELEASE_GENERATION_SUPPLEMENT',
         'PASS_OFFLINE_PIN_PEER_RELEASE_GENERATION_COHORT_READBACK') if pin_peer else
        ('readonly-shutter-gate-v1-runtime-ready.json', 'PASS_NEW_OFFLINE_SHUTTER_GATE_V1_SUPPLEMENT',
         'PASS_OFFLINE_SHUTTER_GATE_V1_COHORT_READBACK'))
    require(binding['runtime_ready']['path'] == str(batch / runtime_name) and
            runtime.get('status') == runtime_status and parent.get('status') == parent_status and
            reader.typed_equal(runtime.get('offline_readback'), binding['parent_readback']) and
            reader.typed_equal(binding['actual_api_contract'], binding['parent_readback']) and
            reader.typed_equal(runtime.get('generic_ready'),
                dict(path=str(batch / 'ready.json'), sha256=binding['batch_ready_sha256'])) and
            parent.get('batch') == str(batch) and parent.get('ready_sha256') == binding['batch_ready_sha256'],
            'shutter gate runtime-ready/offline parent generation differs')
    for row in (runtime, parent):
        require(reader.typed_equal(row.get('launch_runtime_preflight'),
                    dict(passed=False, inspected=False, launch_authorized=False)) and
                all(row.get(k) is False for k in ('runtime_verified', 'capture_verified', 'physical',
                    'physical_asic_compatibility_verified', 'originalMain', 'retirement',
                    'instruction_retirement_verified', 'Main_identity_verified', 'AP_identity_verified',
                    'branch_edge_verified', 'invocation_pairing_verified', 'original_camera_VM_started',
                    'originalUI_onceplan_prepared', 'intent_published', 'card_prepared')),
                'shutter gate offline parent promotes runtime claims')
    for row in (plan, intent, launch, runtime, parent):
        require(not SHUTTER_GATE_ALIASES & row.keys(), 'shutter gate external schema/root alias')
    expected = binding['scope_observer_expected']
    projection = binding['shutter_gate_reader_expected']
    expected_keys = set(SHUTTER_GATE_READER_FIELDS) | {'profile', 'trace_schema', 'source_contract_sha256',
        'build_receipt', 'library_source', 'build_metadata', 'functional_runner_source_sha256'}
    require(type(expected) is dict and set(expected) == expected_keys and type(projection) is dict and
            set(projection) == set(SHUTTER_GATE_READER_FIELDS) and
            reader.typed_equal(projection, {key: expected[key] for key in SHUTTER_GATE_READER_FIELDS}) and
            reader.typed_equal(projection, parent.get('expected_original_run_assets')) and
            reader.typed_equal(projection, runtime.get('expected_original_run_assets')) and
            not SHUTTER_GATE_ALIASES & expected.keys() and
            expected.get('profile') == profile_name and expected.get('trace_schema') == trace_name,
            'shutter gate exact independent reader/parent operands differ')
    fixture = reference(binding['synthetic_fixture_manifest'])
    api_key, build_key = ('gate_v2_actual_api', 'gate_v2_build_receipt') if gate_v2 else ('gate_actual_api', 'gate_build_receipt')
    require(reader.typed_equal(parent.get(api_key, {}).get('manifest'), binding['synthetic_fixture_manifest']) and
            not SHUTTER_GATE_ALIASES & fixture.keys() and
            fixture.get('status') == ('PASS_SELF_OWNED_QEMU_SHUTTER_GATE_V2_FIXTURE' if gate_v2 else
                                      'PASS_SELF_OWNED_QEMU_SHUTTER_GATE_V1_FIXTURE') and fixture.get('failure') is None and
            fixture.get('profile') == profile_name and fixture.get('trace_schema') == trace_name and
            fixture.get('trace_schema_sha256') == projection['trace_schema_sha256'] and
            reader.typed_equal(fixture.get('fixture_source_sha256'), projection['fixture_source_sha256']) and
            all(reader.typed_equal(fixture.get('inputs', {}).get('source:' + name),
                    dict(path=str(graph.NATIVE / component / name), sha256=value))
                for name, value in projection['source_sha256'].items()) and
            all(reader.typed_equal(fixture.get('inputs', {}).get('fixture-source:' + name),
                    dict(path=str(graph.NATIVE / component / name), sha256=value))
                for name, value in projection['fixture_source_sha256'].items()) and
            set(fixture.get('variants', {})) == {'original_entry', 'existing_main_stub_entry', 'one_byte_gate_mutation', 'short_tb'} and
            all(fixture.get(k) is False for k in ('capture_verified', 'physical_asic_compatibility_verified',
                'Main_identity_verified', 'AP_identity_verified', 'instruction_retirement_verified',
                'branch_edge_verified', 'retirement')), 'shutter gate actualAPI manifest differs')
    frozen = {}
    require(set(tested['groups']) == {'production', 'host', 'observer', 'test'}, 'shutter gate source groups differ')
    for group in tested['groups'].values():
        for name, digest in group.items():
            require(name not in frozen or frozen[name] == digest, 'shutter gate frozen source conflict')
            frozen[name] = digest
    if gate_v2:
        _condition_shutter_gate_v2_cohort(graph, reader, binding, plan, runtime, parent, build,
                                         tested, frozen, receipt, reference, snapshots)
        require(manifest['selected_initramfs_verified_files'].get('simulation/file-media-config.so') == parent['media_sha256'],
                'gate v2 selected original-media ABI differs')
    else:
        require(len(frozen) == parent.get('all_source_members_verified') == 1193 and
                len(tested['modules']) == len(set(tested['modules'])) == 242 and set(tested['modules']) <= frozen.keys(),
                'shutter gate complete source1193/modules242 closure differs')
    if pin_peer:
        require(binding['runtime_ready']['sha256'] == PIN_PEER_RUNTIME_READY_SHA and
                binding['parent_readback']['sha256'] == PIN_PEER_PARENT_READBACK_SHA,
                'pin peer reviewed runtime-ready/parent generation differs')
        approval_ref, candidate_ref = runtime.get('parent_approval'), runtime.get('candidate_manifest')
        require(type(approval_ref) is dict and approval_ref.get('sha256') == PIN_PEER_SOURCE_APPROVAL_SHA and
                reader.typed_equal(approval_ref, parent.get('parent_approval')) and
                reader.typed_equal(approval_ref, plan.get('source_approval')) and
                type(candidate_ref) is dict and candidate_ref.get('sha256') == PIN_PEER_CANDIDATE_SHA and
                reader.typed_equal(candidate_ref, parent.get('candidate_manifest')),
                'pin peer exact source19 approval/candidate references differ')
        approval, candidate = reference(approval_ref), reference(candidate_ref)
        require(approval.get('status') == 'PARENT_APPROVED_PIN_PEER_FIXTURE_CLOSURE_EXACT_NINETEEN_SOURCE_COHORT_ONLY' and
                candidate.get('status') == 'PARENT_APPROVED_NINETEEN_EXISTING_SOURCE_FIXTURE_CLOSURE_NOT_TESTED' and
                all(row.get('approved') is True and row.get('source_install_approved') is True for row in (approval, candidate)) and
                approval.get('native_root') == str(graph.NATIVE) and
                (approval.get('source_count'), approval.get('changed_count'), approval.get('unchanged_count')) == (1193, 19, 1174) and
                candidate.get('source_count_unchanged_expected') == 1193 and candidate.get('modules_unchanged_expected') == 242 and
                approval.get('added') == approval.get('removed') == candidate.get('added_sources') == candidate.get('removed_sources') == [] and
                reader.typed_equal(approval.get('candidate_manifest'), candidate_ref) and
                reader.typed_equal(approval.get('sources'), candidate.get('changed_existing_files')),
                'pin peer approved nineteen-source cohort differs')
        inventory = dict(approval['baseline_source_sha256'])
        source19 = {}
        require(len(inventory) == 1193 and len(approval['sources']) == 19, 'pin peer baseline/source19 count differs')
        for entry in approval['sources']:
            name = entry['path']
            path = graph.absolute(graph.NATIVE / name)
            require(path.is_relative_to(BASE) and name not in source19 and
                    inventory.get(str(path)) == entry['before_sha256'], 'pin peer source19 baseline/path differs')
            source19[name] = dict(before_sha256=entry['before_sha256'], after_sha256=entry['candidate_sha256'],
                before_bytes=entry['before_bytes'], after_bytes=entry['candidate_bytes'], mode=entry['mode'])
            inventory[str(path)] = entry['candidate_sha256']
        full = parent.get('full_inventory', {})
        require(reader.typed_equal(frozen, inventory) and
                reader.typed_equal(full.get('source_sha256'), inventory) and
                reader.typed_equal(full.get('modules'), tested['modules']) and
                reader.typed_equal(full.get('groups'), {key: sorted(value) for key, value in tested['groups'].items()}) and
                full.get('source_count') == 1193 and full.get('module_count') == 242 and
                all(reader.typed_equal(row.get('source19'), source19) and row.get('changed_source_count') == 19 and
                    row.get('unchanged_source_count') == 1174 for row in (runtime, parent, full)) and
                runtime.get('source_count') == 1193 and runtime.get('module_count') == 242 and
                parent.get('observer_sha256') == binding['observer_sha256'] and
                parent.get('observer_archive_members_verified') == len(build['sources']) + 1,
                'pin peer source19/source1193/modules242 generation differs')
        legacy_assets, gate_assets = parent['legacy_runtime_assets_sha256'], parent['gate_added_runtime_assets_sha256']
        require(len(legacy_assets) == 13 and len(gate_assets) == 4 and not legacy_assets.keys() & gate_assets.keys() and
                reader.typed_equal(binding['runtime_assets_sha256'], dict(legacy_assets, **gate_assets)) and
                reader.typed_equal(binding['runtime_assets_sha256'], approval.get('protected_runtime_assets_sha256')) and
                all(all(row.get(key) is False for key in ('cap', 'native_CP_verified',
                    'original_poweron_or_late_runtime_verified', 'original_M_producer_runtime_verified')) for row in (runtime, parent)),
                'pin peer protected assets/offline claims differ')
        ready = receipt(batch / 'ready.json', binding['batch_ready_sha256'])
        regression = receipt(batch / 'host-regression.json', ready['regression_sha256'])
        require(reader.typed_equal(receipt(batch / 'inputs.json', ready['inputs_sha256']), tested) and
                ready.get('capture_verified') is False and type(regression.get('returncode')) is int and
                regression['returncode'] == 0 and
                all(type(parent.get(key)) is int and parent[key] == regression.get(key) for key in ('tests_passed', 'subtests_passed')) and
                parent['tests_passed'] > 0 and parent['subtests_passed'] > 0,
                'pin peer complete ready/regression generation differs')
        coverage = parent.get('host_junit_coverage', {})
        require(reader.typed_equal(runtime.get('host_junit'), coverage.get('junit')) and
                coverage.get('actual_testcases') == coverage.get('actual_pytest_tests_passed') == parent['tests_passed'] and
                coverage.get('actual_pytest_subtests_passed') == parent['subtests_passed'] and
                set(coverage.get('modules', {})) == set(tested['modules']) and
                all(type(value) is int and value > 0 for value in coverage['modules'].values()) and
                sum(coverage['modules'].values()) == parent['tests_passed'], 'pin peer full host module coverage differs')
        cases = ['original_entry', 'existing_main_stub_entry', 'one_byte_gate_mutation', 'short_tb']
        require(runtime.get('actualAPI_cases') == cases and set(parent.get('gate_actual_api', {}).get('cases', {})) == set(cases) and
                all(runtime.get(key) is True for key in ('v2_actualAPI_compatibility_verified',
                    'v3_actualAPI_compatibility_verified', 'synthetic_shutter_gate_API_verified')) and
                set(parent.get('dual_actual_api', {})) == {'2', '3'} and
                all(reader.typed_equal(fixture.get('inputs', {}).get(key), value) for key, value in (
                    ('qemu', binding['candidate_qemu']), ('receipt', parent['gate_build_receipt']),
                    ('plugin', dict(path=expected['library_source'], sha256=projection['library_sha256'])),
                    ('schema', dict(path=str(graph.NATIVE / SHUTTER_GATE_COMPONENT / 'log-schema-shutter-gate-v1.json'),
                                    sha256=projection['trace_schema_sha256'])))), 'pin peer actualAPI generation/assets differ')
        for version, api in parent['dual_actual_api'].items():
            actual = reference(api['manifest'])
            require(actual.get('status') == api.get('actual_api_contract', {}).get('status') ==
                        f'PASS_SELF_OWNED_QEMU_SCOPE_V{version}_FIXTURE' and actual.get('failure') is None and
                    actual.get('profile') == f'qemu-readonly-scope-v{version}' and actual.get('trace_schema') == f'readonly_scope_v{version}' and
                    set(actual.get('variants', {})) == set(api['actual_api_contract']['cases']) == set(api.get('cases', {})) and
                    reader.typed_equal(actual.get('inputs'), api.get('inputs')) and
                    reader.typed_equal(actual.get('inputs', {}).get('qemu'), binding['candidate_qemu']) and
                    all(actual.get(key) is False for key in ('capture_verified', 'physical', 'cap', 'instruction_retirement_verified')),
                    'pin peer legacy actualAPI receipt differs: ' + version)
    root = graph.NATIVE / component
    for key, names in (('source_sha256', source_names),
                       ('fixture_source_sha256', fixture_names)):
        sources = expected[key]
        require(type(sources) is dict and set(sources) == set(names), 'shutter gate exact source7/fixture7 roles differ')
        for name, digest in sources.items():
            path = graph.absolute(root / name)
            original = graph.read(path)
            require(frozen.get(str(path)) == digest == graph.sha(original),
                    'shutter gate actual/frozen source differs: ' + name)
            snapshots[path] = original
    for name in ('functional_camera_runner.py', 'scope_observer_profile.py'):
        path = BASE / name
        original = graph.read(path)
        require(frozen.get(str(path)) == graph.sha(original), 'shutter gate actual/frozen host source differs: ' + name)
        snapshots[path] = original
    require(expected['functional_runner_source_sha256'] == frozen[str(BASE / 'functional_camera_runner.py')] and
            expected['observer_sha256'] == binding['observer_sha256'] and
            expected['Main_source_sha256'] == build['sources'][str(BASE / 'menu-observe.c')]['sha256'] and
            manifest['selected_initramfs_verified_files'].get('usr/lib/appFw.so') == expected['original_appfw_sha256'],
            'shutter gate Main/runner/appFw operands differ')
    driver = graph.absolute(plan['driver'])
    require(driver == BASE / 'scratch/run-functional-current-batch.py' and
            all(row.get('driver') == str(driver) and row.get('driver_sha256') == plan['driver_sha256'] for row in (intent, launch)) and
            graph.sha(graph.read(driver)) == plan['driver_sha256'], 'shutter gate original UI driver differs')
    snapshots[driver] = graph.read(driver)
    candidate = binding['candidate_qemu']
    require(type(candidate) is dict and set(candidate) == {'path', 'sha256'} and
            str(graph.absolute(candidate['path'])) == manifest['backup_transport']['binary'] and
            candidate['sha256'] == manifest['backup_transport']['binary_sha256'] == expected['qemu_sha256'] and
            manifest['files'].get(candidate['path']) == candidate['sha256'], 'shutter gate selected QEMU differs')
    profile = graph.source_module('runtime/analysis/scope_observer_profile.py', frozen)
    metadata = profile.validate_build(graph.NATIVE, expected['build_receipt'], candidate['path'])
    require(reader.typed_equal(expected['build_metadata'], metadata) and
            expected['library_source'] == metadata['library'] and
            all(reader.typed_equal(expected[key], metadata[key]) for key in
                ('profile', 'trace_schema', 'trace_schema_sha256', 'source_contract_sha256', 'source_sha256',
                 'fixture_source_sha256', 'build_receipt', 'build_receipt_sha256', 'qemu_sha256',
                 'qemu_header_sha256', 'library_sha256', 'readonly_import_audit_sha256')) and
            reader.typed_equal(runtime.get(build_key), parent.get(build_key)) and
            reader.typed_equal(plan.get('scope_build'), parent.get(build_key)) and
            reader.typed_equal(plan['scope_build'], dict(path=metadata['build_receipt'], sha256=metadata['build_receipt_sha256'])),
            'shutter gate complete actual build metadata differs')
    scope = manifest.get('readonly_scope_observer')
    plan_binding = {key: binding[key] for key in SHUTTER_GATE_PLAN_FIELDS}
    require(reader.typed_equal(scope, dict(metadata, library=str(run / 'readonly-scope-observer.so'),
                log=str(run / 'readonly-scope-trace.log'), plan_binding=plan_binding)),
            'shutter gate complete manifest metadata/plan binding differs')
    receipt(metadata['build_receipt'], metadata['build_receipt_sha256'])
    plugin_work = graph.absolute(metadata['build_receipt']).parent
    audit_path = graph.absolute(candidate['path']).parents[1] / 'binary-static-audit.json'
    audit = receipt(audit_path, metadata['candidate_static_audit_sha256'])
    require(audit.get('binary') == candidate['path'] and audit.get('binary_sha256') == candidate['sha256'] and
            audit.get('missing_required_exports') == [] and
            reader.typed_equal(audit.get('protected_binaries_unchanged'), dict(candidate=True, production=True)) and
            all(audit.get(k) is False for k in ('runtime_library_closure_verified', 'plugin_runtime_verified',
                'capture_verified', 'physical_asic_compatibility_verified')), 'shutter gate candidate static audit differs')
    for path, digest in ((plugin_work / 'plugin-build-command.json', metadata['plugin_build_command_sha256']),
                         (plugin_work / 'readonly-import-audit.json', metadata['readonly_import_audit_sha256'])):
        receipt(path, digest)
    for path, digest in ((Path(metadata['library']), metadata['library_sha256']),
                         (run / 'readonly-scope-observer.so', metadata['library_sha256'])):
        original = graph.read(path)
        require(graph.sha(original) == digest, 'shutter gate actual library differs')
        snapshots[path] = original
    assets = binding['runtime_assets_sha256']
    merged_assets = dict(parent['legacy_runtime_assets_sha256'], **parent['gate_added_runtime_assets_sha256'])
    if gate_v2:
        merged_assets.update(parent['gate_v2_added_runtime_assets_sha256'])
    require(reader.typed_equal(assets, merged_assets) and
            all(assets.get(str(path)) == digest for path, digest in (
                (audit_path, metadata['candidate_static_audit_sha256']),
                (plugin_work / 'plugin-build-command.json', metadata['plugin_build_command_sha256']),
                (plugin_work / 'readonly-import-audit.json', metadata['readonly_import_audit_sha256']),
                (Path(metadata['build_receipt']), metadata['build_receipt_sha256']),
                (Path(metadata['library']), metadata['library_sha256']))), 'shutter gate runtime audit assets differ')
    if gate_v2:
        require(reader.typed_equal(parent['gate_v2_added_runtime_assets_sha256'], {
            str(plugin_work / 'plugin-build-command.json'): metadata['plugin_build_command_sha256'],
            str(plugin_work / 'readonly-import-audit.json'): metadata['readonly_import_audit_sha256'],
            metadata['build_receipt']: metadata['build_receipt_sha256'],
            metadata['library']: metadata['library_sha256']}), 'gate v2 added assets are not its exact four build roles')
    for path, digest in ((Path(metadata['build_receipt']), metadata['build_receipt_sha256']),
                         (run / 'readonly-scope-observer.so', metadata['library_sha256']),
                         *((root / name, value) for name, value in expected['source_sha256'].items())):
        require(manifest['files'].get(str(path)) == digest, 'shutter gate actual manifest files differ')
    info = run.stat()
    context = dict(schema=generation + '-live-context-v1', run=str(run),
        run_device=info.st_dev, run_inode=info.st_ino, scope=plan_binding,
        **{key: binding[key] for key in ('nonce', 'batch', 'batch_ready_sha256', 'intent_sha256',
                                       'launch_binding_sha256', 'candidate_qemu', 'card')})
    live = receipt(run / 'readonly-scope-popen-live.json', binding['popen_live_sha256'])
    ancestry = receipt(run / 'readonly-scope-live-ancestry.json')
    callback = receipt(run / 'readonly-scope-popen-exit-binding.json')
    exited = receipt(run / 'readonly-scope-exit.json')
    trace_path = run / 'readonly-scope-trace.log'
    trace = graph.read(trace_path, 233472 if gate_v2 else 200704)
    snapshots[trace_path] = trace
    if gate_v2:
        checks = graph.source_module(component + '/integration/shutter_gate_trace_checks_v2.py', frozen)
        checks.parse_trace(trace, reader.object_json(snapshots[root / 'log-schema-shutter-gate-v2.json']))
    require(set(exited) == {'profile', 'run', 'owned_wrapper_pid', 'returncode', 'log_available',
                'log_sha256', 'library_sha256', 'capture_verified', 'physical_asic_compatibility_verified'} and
            exited.get('log_sha256') == graph.sha(trace), 'shutter gate original exit/trace bytes differ')
    popen_keys = ({'schema', 'context', 'wrapper', 'owner', 'control', 'actual_Popen_pid', 'birth_sample',
                   'launch_policy', 'control_mode', 'probe_source_sha256'},
                  {'schema', 'context', 'chain', 'qemu', 'wrapper', 'owner', 'control', 'launch_owner',
                   'execution', 'control_mode', 'popen_live_sha256', 'run_binding_sha256', 'captured_while_alive'},
                  {'schema', 'context', 'wrapper', 'actual_Popen_pid', 'returncode', 'popen_live_sha256',
                   'ancestry_sha256', 'original_exit_sha256'})
    for row, keys in zip((live, ancestry, callback), popen_keys):
        require(set(row) == keys | set(SHUTTER_GATE_FALSE_FIELDS), 'shutter gate exact Popen receipt fields differ')
    for row, schema in ((live, generation + '-popen-live-v1'),
                        (ancestry, generation + '-live-ancestry-v1'),
                        (callback, generation + '-popen-exit-v1')):
        require(row.get('schema') == schema and reader.typed_equal(row.get('context'), context) and
                all(row.get(k) is False for k in SHUTTER_GATE_FALSE_FIELDS), 'shutter gate same-run Popen context differs')
    chain = ancestry.get('chain')
    require(type(chain) is list and 2 <= len(chain) <= 16, 'shutter gate saved Popen ancestry missing')
    for node in [*chain, live['wrapper'], live['owner'], live['control'], ancestry['launch_owner']]:
        require(type(node) is dict and set(node) == {'pid', 'ppid', 'starttime', 'exe'} and
                all(type(node[k]) is int and node[k] > 0 for k in ('pid', 'ppid', 'starttime')) and
                type(node['exe']) is str and Path(node['exe']).is_absolute(), 'shutter gate saved Popen generation invalid')
    require(len({node['pid'] for node in chain}) == len(chain) and
            reader.typed_equal(chain[0], ancestry.get('qemu')) and
            reader.typed_equal(chain[-1], ancestry['launch_owner']) and
            all(child['ppid'] == parent_node['pid'] and child['starttime'] >= parent_node['starttime']
                for child, parent_node in zip(chain, chain[1:])) and
            live['owner'] in chain and live['control'] in chain and
            any(all(node[k] == live['wrapper'][k] for k in ('pid', 'ppid', 'starttime')) for node in chain) and
            reader.typed_equal(ancestry.get('execution', {}).get('birth'), live.get('birth_sample')) and
            reader.typed_equal(ancestry.get('execution', {}).get('policy'), live.get('launch_policy')) and
            ancestry.get('execution', {}).get('dual_read_stable') is True and
            type(ancestry['execution'].get('actual_Popen_pid')) is int and
            ancestry['execution']['actual_Popen_pid'] == live['actual_Popen_pid'] and
            reader.typed_equal(live.get('birth_sample', {}).get('identity'), live['wrapper']),
            'shutter gate saved Popen ancestry/exec links differ')
    require(type(live.get('actual_Popen_pid')) is int and live['actual_Popen_pid'] > 1 and
            type(callback.get('actual_Popen_pid')) is int and type(exited.get('owned_wrapper_pid')) is int and
            live['actual_Popen_pid'] == live['wrapper']['pid'] == callback.get('actual_Popen_pid') == exited.get('owned_wrapper_pid') and
            reader.typed_equal(callback.get('wrapper'), live['wrapper']) and
            all(reader.typed_equal(ancestry.get(key), live.get(key)) for key in ('wrapper', 'owner', 'control', 'control_mode')) and
            reader.typed_equal(ancestry.get('launch_owner'), launch.get('launch_owner')) and
            ancestry.get('captured_while_alive') is True and
            ancestry.get('run_binding_sha256') == graph.sha(graph.read(run / 'readonly-scope-run-binding.json', graph.MAX_JSON)) and
            ancestry.get('popen_live_sha256') == callback.get('popen_live_sha256') == binding['popen_live_sha256'] and
            callback.get('ancestry_sha256') == graph.sha(snapshots[run / 'readonly-scope-live-ancestry.json']) and
            callback.get('original_exit_sha256') == graph.sha(snapshots[run / 'readonly-scope-exit.json']) and
            type(callback.get('returncode')) is int and type(exited.get('returncode')) is int and
            callback['returncode'] == exited['returncode'] and exited.get('profile') == profile_name and
            exited.get('run') == str(run) and exited.get('library_sha256') == metadata['library_sha256'] and
            live.get('probe_source_sha256') == graph.sha(graph.read(BASE / 'qemu-menu-probe.py')) and
            exited.get('log_available') is True and
            exited.get('capture_verified') is False and exited.get('physical_asic_compatibility_verified') is False,
            'shutter gate actual Popen generation/exit links differ')
    if gate_v2:
        for row in (live, ancestry, callback, exited):
            _gate_v2_unpromoted(row)
        require(exited['returncode'] == 0 and b'scope_observer_host_error' not in trace,
                'gate v2 requires original normal owned exit, preserves failed returncode')
    return guest_source, snapshots


def _gate_v2_unpromoted(value):
    """Reject known claims anywhere in a new receipt, including unused JSON subtrees."""
    pending = [value]
    claims = set(SHUTTER_GATE_FALSE_FIELDS) | {'capture', 'physical_asic_verified',
        'native_CP_verified', 'original_M_producer_runtime_verified', 'PID_TID_uniqueness_verified',
        'address_space_uniqueness_verified', 'original_store_or_return_verified', 'same_press_submit_verified'}
    while pending:
        item = pending.pop()
        if type(item) is dict:
            require(not SHUTTER_GATE_ALIASES & item.keys(), 'gate v2 external schema/root alias')
            require(all(value is False for key, value in item.items() if key in claims),
                    'gate v2 receipt promotes an identity/runtime/capture claim')
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)


def _condition_shutter_gate_v2_cohort(graph, reader, binding, plan, runtime, parent, build,
                                      tested, frozen, receipt, reference, snapshots):
    """New immutable cohort operands; no future digest or historical count is a source constant."""
    require(runtime.get('schema') == 'functional-shutter-gate-v2-runtime-ready-v1' and
            parent.get('schema') == 'functional-shutter-gate-v2-cohort-readback-v1' and
            runtime.get('batch') == binding['batch'], 'gate v2 exact offline schemas/batch differ')
    for row in (binding, plan, runtime, parent, tested):
        _gate_v2_unpromoted(row)
    batch = graph.absolute(binding['batch'])
    ready = receipt(batch / 'ready.json', binding['batch_ready_sha256'])
    require(reader.typed_equal(receipt(batch / 'inputs.json', ready['inputs_sha256']), tested),
            'gate v2 ready/input source maps differ')
    _gate_v2_unpromoted(ready)
    full = parent.get('full_inventory', {})
    modules = tested.get('modules')
    require(type(modules) is list and modules and all(type(name) is str for name in modules) and
            len(modules) == len(set(modules)) and set(modules) <= frozen.keys() and
            all(type(group) is dict and group for group in tested['groups'].values()) and
            reader.typed_equal(full.get('source_sha256'), frozen) and
            reader.typed_equal(full.get('groups'), {key: sorted(group) for key, group in tested['groups'].items()}) and
            reader.typed_equal(full.get('modules'), modules), 'gate v2 full frozen source/module maps differ')
    for row in (runtime, parent, full):
        require(type(row.get('source_count')) is int and row['source_count'] == len(frozen) > 0 and
                type(row.get('module_count')) is int and row['module_count'] == len(modules),
                'gate v2 real source/module counts differ')
    require(type(parent.get('all_source_members_verified')) is int and
            parent['all_source_members_verified'] == len(frozen) and
            parent.get('source_inventory_sha256') == ready['inputs_sha256'] and
            parent.get('source_archive_sha256') == ready['all_input_archive_sha256'] and
            parent.get('observer_archive_members_verified') == len(build['sources']) + 1 and
            parent.get('observer_sha256') == binding['observer_sha256'], 'gate v2 source/archive counts differ')
    for name, digest in frozen.items():
        path = graph.absolute(name)
        require(path.is_relative_to(graph.NATIVE) and type(digest) is str and len(digest) == 64 and
                set(digest) <= set('0123456789abcdef'), 'gate v2 frozen source path/digest invalid')
        original = graph.read(path)
        require(graph.sha(original) == digest, 'gate v2 actual/frozen source differs: ' + name)
        snapshots[path] = original
    required_sources = tuple(graph.FROZEN_DEPENDENCIES) + tuple('runtime/analysis/' + name for name in (
        'scratch/verify_hdmi_edge.py', 'scratch/test_verify_hdmi_edge.py',
        'scratch/validate-unified-camera.py', 'scope_observer_profile.py', 'hdmi_upm_watch.py'))
    for name in required_sources:
        require(str(graph.NATIVE / name) in frozen, 'gate v2 cohort omits its consumer/host source: ' + name)
    archive_path = batch / 'inputs.tar.gz'
    archive = graph.read(archive_path, reader.MAX_FILE)
    require(graph.sha(archive) == ready['all_input_archive_sha256'], 'gate v2 full source archive digest differs')
    reader.archive(archive, {str(Path(name).relative_to(graph.NATIVE)): digest for name, digest in frozen.items()})
    snapshots[archive_path] = archive
    regression = receipt(batch / 'host-regression.json', ready['regression_sha256'])
    require(type(regression.get('returncode')) is int and regression['returncode'] == 0 and
            regression.get('inputs_sha256') == ready['inputs_sha256'] and
            regression.get('capture_verified') is False and
            reader.typed_equal(regression.get('changed'), {key: [] for key in tested['groups']}) and
            all(type(parent.get(key)) is int and parent[key] > 0 and
                type(regression.get(key)) is int and parent[key] == regression[key]
                for key in ('tests_passed', 'subtests_passed')), 'gate v2 full regression differs')
    log_path = batch / 'host-regression.log'
    log = graph.read(log_path, graph.MAX_LOG)
    require(graph.sha(log) == regression['log_sha256'] and
            re.findall(rb'\b(\d+) passed\b', log) == [str(parent['tests_passed']).encode()] and
            re.findall(rb'\b(\d+) subtests passed\b', log) == [str(parent['subtests_passed']).encode()] and
            not re.search(rb'\b[1-9][0-9]* (failed|errors?|skipped|xfailed|xpassed|deselected)\b', log),
            'gate v2 original regression log/counts differ')
    snapshots[log_path] = log
    coverage = parent.get('host_junit_coverage', {})
    require(reader.typed_equal(runtime.get('host_junit'), coverage.get('junit')) and
            coverage.get('junit', {}).get('path') == str(batch / 'host-regression.junit.xml') and
            set(coverage.get('modules', {})) == set(modules) == set(coverage.get('module_classnames', {})) and
            all(type(value) is int and value > 0 for value in coverage['modules'].values()) and
            all(type(coverage.get(key)) is int for key in
                ('actual_testcases', 'actual_pytest_tests_passed', 'actual_pytest_subtests_passed')) and
            sum(coverage['modules'].values()) == coverage.get('actual_testcases') ==
                coverage.get('actual_pytest_tests_passed') == parent['tests_passed'] and
            coverage.get('actual_pytest_subtests_passed') == parent['subtests_passed'],
            'gate v2 complete host module coverage differs')
    junit_ref = coverage['junit']
    require(type(junit_ref) is dict and set(junit_ref) == {'path', 'sha256'}, 'gate v2 exact junit reference required')
    junit_path = graph.absolute(junit_ref['path'])
    junit = graph.read(junit_path, graph.MAX_LOG)
    require(graph.sha(junit) == junit_ref['sha256'] and b'<!DOCTYPE' not in junit and b'<!ENTITY' not in junit,
            'gate v2 junit bytes differ')
    snapshots[junit_path] = junit
    cases = list(ET.fromstring(junit).iter('testcase'))
    classnames = coverage['module_classnames']
    require(all(type(value) is str and value for value in classnames.values()) and
            len(set(classnames.values())) == len(modules), 'gate v2 explicit module classnames invalid')
    counts = dict.fromkeys(modules, 0)
    for case in cases:
        matches = [name for name, prefix in classnames.items()
                   if case.get('classname') == prefix or case.get('classname', '').startswith(prefix + '.')]
        require(len(matches) == 1 and not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped')),
                'gate v2 junit unknown/failed/skipped module')
        counts[matches[0]] += 1
    require(len(cases) == parent['tests_passed'] and reader.typed_equal(counts, coverage['modules']),
            'gate v2 actual junit/module counts differ')
    abi = receipt(batch / 'abi.json', ready['abi_sha256'])
    marker = 'PASS: constructor thread and application-init wrapper preserved behavior'
    media = abi.get('media_preload', {})
    require(type(abi.get('returncode')) is int and abi['returncode'] == 0 and abi.get('capture_verified') is False and
            abi.get('regression_sha256') == ready['regression_sha256'] and marker in abi.get('stdout', '') and
            type(media.get('returncode')) is int and media['returncode'] == 0 and media.get('bind_now') is True and
            marker in media.get('stdout', '') and abi.get('observer_sha256') == binding['observer_sha256'] and
            abi.get('source_archive_sha256') == build['source_archive_sha256'] and
            type(abi.get('source_count')) is int and abi['source_count'] == len(build['sources']) and
            abi.get('media_preload_sha256') == parent.get('media_sha256'), 'gate v2 both original ABIs required')
    command = abi.get('command')
    media_path = BASE / 'menu-root/simulation/file-media-config.so'
    require(type(command) is list and command and all(type(arg) is str for arg in command) and
            sum(arg.startswith('LD_PRELOAD=') for arg in command) == 1 and
            reader.typed_equal(media.get('command'), [arg.replace('LD_PRELOAD=', 'LD_PRELOAD=' + str(media_path) + ':')
                if arg.startswith('LD_PRELOAD=') else arg for arg in command]),
            'gate v2 original observer/media ABI commands differ')
    for key, length in (('legacy_runtime_assets_sha256', 13), ('gate_added_runtime_assets_sha256', 4),
                        ('gate_v2_added_runtime_assets_sha256', 4)):
        require(type(parent.get(key)) is dict and len(parent[key]) == length and
                all(reader.typed_equal(row.get(key), parent[key]) for row in (runtime, plan)),
                'gate v2 protected asset roles differ: ' + key)
    legacy, gate, added = (parent[key] for key in ('legacy_runtime_assets_sha256',
        'gate_added_runtime_assets_sha256', 'gate_v2_added_runtime_assets_sha256'))
    require(not legacy.keys() & gate.keys() and not added.keys() & (legacy.keys() | gate.keys()),
            'gate v2 asset generations overlap')
    assets = dict(legacy, **gate, **added)
    require(reader.typed_equal(binding['runtime_assets_sha256'], assets) and
            all(reader.typed_equal(row.get('protected_runtime_assets_sha256'), assets) for row in (plan, runtime, parent)),
            'gate v2 full protected assets differ')
    protected = parent.get('protected_qemu', {})
    require(set(protected) == {'readonly_candidate', 'production', 'legacy_default'} and
            reader.typed_equal(protected['readonly_candidate'], binding['candidate_qemu']) and
            protected['production'].get('sha256') == graph.PRODUCTION_QEMU_SHA256 and
            protected['legacy_default'].get('sha256') == SHUTTER_GATE_V2_LEGACY_DEFAULT_SHA and
            all(reader.typed_equal(row.get('protected_qemu'), protected) for row in (plan, runtime)),
            'gate v2 protected candidate/production differ')
    for value in (*protected.values(), *(dict(path=name, sha256=digest) for name, digest in assets.items())):
        require(type(value) is dict and set(value) == {'path', 'sha256'}, 'gate v2 exact protected asset reference required')
        path = graph.absolute(value['path'])
        original = graph.read(path, reader.MAX_FILE)
        require(graph.sha(original) == value['sha256'], 'gate v2 protected asset bytes differ: ' + str(path))
        snapshots[path] = original
    _condition_shutter_gate_v2_apis(graph, reader, binding, plan, runtime, parent, frozen,
                                  receipt, reference, snapshots)


def _condition_shutter_gate_v2_apis(graph, reader, binding, plan, runtime, parent, frozen,
                                    receipt, reference, snapshots):
    """Consume four exact fixture generations using frozen, read-only operand checkers."""
    require(set(parent.get('dual_actual_api', {})) == {'2', '3'}, 'gate v2 legacy dual actualAPI missing')
    rows = {'scope2': parent['dual_actual_api']['2'], 'scope3': parent['dual_actual_api']['3'],
            'gate1': parent['gate_actual_api'], 'gate2': parent['gate_v2_actual_api']}
    refs = {key: row['manifest'] for key, row in rows.items()}
    builds = parent.get('observer_builds', {})
    require(set(builds) == set(rows) and
            all(reader.typed_equal(row.get('cohort_actual_api_manifests'), refs) and
                reader.typed_equal(row.get('observer_builds'), builds) for row in (plan, runtime)) and
            reader.typed_equal(builds['gate1'], parent['gate_build_receipt']) and
            reader.typed_equal(builds['gate2'], parent['gate_v2_build_receipt']) and
            reader.typed_equal(refs['gate2'], binding['synthetic_fixture_manifest']) and
            runtime.get('actualAPI_cases') == list(SHUTTER_GATE_API_CASES) and
            all(runtime.get(key) is True for key in ('v2_actualAPI_compatibility_verified',
                'v3_actualAPI_compatibility_verified', 'synthetic_shutter_gate_API_verified',
                'synthetic_shutter_gate_v2_API_verified')), 'gate v2 four API/build references differ')
    profile = graph.source_module('runtime/analysis/scope_observer_profile.py', frozen)
    specs = (
        ('scope2', 'report/2026-10-30-qemu-readonly-scope-observer', 'qemu-readonly-scope-v2',
         'readonly_scope_v2', 'log-schema-v2.json', 'integration/scope_trace_checks_v2.py', 2),
        ('scope3', 'report/2026-10-31-qemu-M-writer-observer-v3', 'qemu-readonly-scope-v3',
         'readonly_scope_v3', 'log-schema-v3.json', 'integration/scope_trace_checks_v3.py', 3),
        ('gate1', SHUTTER_GATE_COMPONENT, SHUTTER_GATE_PROFILE, 'readonly_shutter_gate_v1',
         'log-schema-shutter-gate-v1.json', 'integration/shutter_gate_trace_checks_v1.py', 1),
        ('gate2', SHUTTER_GATE_V2_COMPONENT, SHUTTER_GATE_V2_PROFILE, 'readonly_shutter_gate_v2',
         'log-schema-shutter-gate-v2.json', 'integration/shutter_gate_trace_checks_v2.py', 2))
    for key, component, expected_profile, trace_schema, schema_name, parser_name, version in specs:
        api = rows[key]
        actual = reference(refs[key])
        _gate_v2_unpromoted(actual)
        root = graph.NATIVE / component
        require(Path(refs[key]['path']).name == 'manifest.json' and
                actual.get('status') == ('PASS_SELF_OWNED_QEMU_SHUTTER_GATE_V%d_FIXTURE' if key in ('gate1', 'gate2')
                                         else 'PASS_SELF_OWNED_QEMU_SCOPE_V%d_FIXTURE') % version and
                actual.get('profile') == expected_profile and actual.get('trace_schema') == trace_schema and
                actual.get('failure') is None, 'gate v2 actualAPI schema/status differs: ' + key)
        metadata = profile.validate_build(graph.NATIVE, builds[key]['path'], binding['candidate_qemu']['path'])
        require(metadata['profile'] == expected_profile and metadata['build_receipt_sha256'] == builds[key]['sha256'] and
                binding['runtime_assets_sha256'].get(metadata['build_receipt']) == builds[key]['sha256'] and
                binding['runtime_assets_sha256'].get(metadata['library']) == metadata['library_sha256'],
                'gate v2 actualAPI build is outside bound protected assets: ' + key)
        receipt(builds[key]['path'], builds[key]['sha256'])
        helper = graph.source_module(component + '/integration/run_fixture.py', frozen)
        checks = graph.source_module(component + '/' + parser_name, frozen)
        fixtures = actual.get('fixture_source_sha256')
        require(type(fixtures) is dict and set(fixtures) == set(helper.FIXTURE_SOURCE_NAMES) and
                set(metadata['source_sha256']) == set(helper.RUNTIME_SOURCES) and
                all(frozen.get(str(root / name)) == digest for values in (fixtures, metadata['source_sha256'])
                    for name, digest in values.items()), 'gate v2 actualAPI frozen source/fixture roles differ: ' + key)
        if key in ('gate1', 'gate2'):
            expected_inputs, declaration = helper.validate_assets(Path(binding['candidate_qemu']['path']),
                Path(metadata['library']), root / schema_name, Path(builds[key]['path']), fixtures)
            expected_inputs['fixture_sources_file'] = dict(path=str(root / 'integration/fixture-source-pins.json'),
                sha256=graph.sha(graph.read(root / 'integration/fixture-source-pins.json')))
            expected_cases = SHUTTER_GATE_API_CASES
        else:
            validate = helper.validate_v2_assets if key == 'scope2' else helper.validate_v3_assets
            expected_inputs = validate(Path(binding['candidate_qemu']['path']), Path(metadata['library']),
                root / schema_name, Path(builds[key]['path']), fixture_source_sha256=fixtures)
            declaration = reader.object_json(graph.read(root / schema_name))
            expected_cases = ('anchor', 'one_byte_mutation', 'wrong_lr_only', 'producer',
                              'producer_corrupt', 'producer_short_tb')
            if key == 'scope3':
                expected_cases = ('anchor', 'one_byte_mutation', 'wrong_lr_only', 'producer',
                                  'producer_reverse_order', 'producer_corrupt', 'producer_short_tb')
        require(reader.typed_equal(actual.get('inputs'), expected_inputs) and
                set(actual.get('variants', {})) == set(api.get('cases', {})) == set(expected_cases),
                'gate v2 actualAPI input/case closure differs: ' + key)
        for value in expected_inputs.values():
            path = graph.absolute(value['path'])
            original = graph.read(path, reader.MAX_FILE)
            require(graph.sha(original) == value['sha256'], 'gate v2 actualAPI input changed: ' + str(path))
            snapshots[path] = original
        folder = graph.absolute(refs[key]['path']).parent
        require(reader.typed_equal(actual.get('fixture_source_snapshots'), helper.verify_fixture_snapshots(folder, fixtures)),
                'gate v2 actualAPI fixture snapshots differ: ' + key)
        table = actual.get('artifacts')
        require(type(table) is dict and 0 < len(table) <= 4096, 'gate v2 actualAPI artifact ledger missing')
        data, total = {}, 0
        for name, item in table.items():
            path = graph.absolute(folder / name)
            require(type(name) is str and str(path.relative_to(folder)) == name and name != 'manifest.json' and
                    type(item) is dict and set(item) == {'sha256', 'bytes'} and type(item['bytes']) is int,
                    'gate v2 actualAPI artifact path/entry invalid')
            raw = graph.read(path, reader.MAX_FILE)
            total += len(raw)
            require(len(raw) == item['bytes'] and graph.sha(raw) == item['sha256'] and total <= reader.MAX_FILE,
                    'gate v2 actualAPI artifact bytes differ: ' + name)
            data[name] = raw
            snapshots[path] = raw
            if name.endswith('.json'):
                reader.object_json(raw)
        actual_names = set()
        for path in folder.rglob('*'):
            graph.absolute(path)
            require(path.is_file() or path.is_dir(), 'gate v2 actualAPI nonregular artifact')
            if path.is_file():
                actual_names.add(str(path.relative_to(folder)))
        require(actual_names == set(table) | {'manifest.json'}, 'gate v2 actualAPI artifact inventory differs')
        commands = actual.get('commands')
        require(type(commands) is list and all(type(row) is dict for row in commands),
                'gate v2 actualAPI commands missing')
        command_map = {row['directory']: row for row in commands}
        expected_directories = []
        for case in expected_cases:
            if case not in ('short_tb', 'producer_short_tb'):
                expected_directories.append('build/' + case)
            expected_directories.extend('cases/' + case + '-' + mode for mode in ('baseline', 'plugin'))
        expected_directories.extend(('cases/missing_log_argument', 'cases/existing_log'))
        require([row['directory'] for row in commands] == expected_directories and len(command_map) == len(commands),
                'gate v2 actualAPI command sequence differs')
        for directory, row in command_map.items():
            fields = {'command', 'directory', 'limit_seconds', 'returncode', 'owned_pid_unreaped'}
            if key in ('gate1', 'gate2'):
                fields |= {'outer_timeout', 'payload_argv'}
                require(row.get('outer_timeout') is False, 'gate v2 gate actualAPI outer timeout evidence differs')
            require(set(row) == fields and type(row.get('command')) is list and row['command'] and
                    all(type(arg) is str for arg in row['command']) and
                    row.get('owned_pid_unreaped') is None and type(row.get('returncode')) is int and
                    type(row.get('limit_seconds')) is int and
                    row['limit_seconds'] == (60 if directory.startswith('build/') else 30) and
                    directory + '/stdout.bin' in data and directory + '/stderr.bin' in data,
                    'gate v2 actualAPI timeout/command evidence differs')
            is_gate = key in ('gate1', 'gate2')
            negative = directory in ('cases/missing_log_argument', 'cases/existing_log')
            case = directory.removeprefix('build/') if directory.startswith('build/') else (
                ('original_entry' if is_gate else 'anchor') if negative else
                directory.removeprefix('cases/').rsplit('-', 1)[0])
            short = case in ('short_tb', 'producer_short_tb')
            build_case = ('original_entry' if is_gate else 'producer') if short else case
            if directory.startswith('build/'):
                payload = [helper.tool('clang'), '--target=aarch64-linux-gnu', '-march=armv8-a', '-fuse-ld=lld',
                    '-nostdlib', '-static', '-no-pie', '-x', 'assembler-with-cpp']
                if is_gate:
                    payload += ['-DFIXTURE_STUB=%d' % (case == 'existing_main_stub_entry'),
                        '-DFIXTURE_MUTATED=%d' % (case == 'one_byte_gate_mutation')]
                else:
                    payload += ['-DFIXTURE_MUTATED=%d' % (case == 'one_byte_mutation'),
                        '-DFIXTURE_WRONG_LR_ONLY=%d' % (case == 'wrong_lr_only'),
                        '-DFIXTURE_PRODUCER=%d' % case.startswith('producer'),
                        ('-DFIXTURE_PRODUCER_MUTATED=%d' if key == 'scope2' else
                         '-DFIXTURE_PRODUCER2_MUTATED=%d') % (case == 'producer_corrupt')]
                    if key == 'scope3':
                        payload += ['-DFIXTURE_PRODUCER_REVERSE=%d' % (case == 'producer_reverse_order')]
                payload += ['/src/fixture.S', '-Wl,-T,/src/link.ld,-z,max-page-size=4096,--build-id=none',
                    '-Wl,-Map,/out/fixture.map', '-o', '/out/fixture.elf']
                mounts = [(folder / 'inputs', '/src')]
            else:
                arguments = [] if directory == 'cases/missing_log_argument' else (
                    ['log=/out/plugin.log'] if directory.endswith('-plugin') or directory == 'cases/existing_log' else None)
                payload = helper.vm_command(arguments, short) if is_gate else helper.vm_command(
                    arguments, case.startswith('producer'), short)
                mounts = [(Path(binding['candidate_qemu']['path']), '/qemu'), (Path(metadata['library']), '/observer.so'),
                    (folder / ('build/' + build_case + '/fixture.elf'), '/in/fixture.elf')]
            command = helper.sandbox(folder / directory, mounts) + [helper.tool('timeout'), '--signal=TERM',
                '--verbose', str(row['limit_seconds']) + 's'] + payload
            require(reader.typed_equal(row['command'], command) and
                    (not is_gate or reader.typed_equal(row['payload_argv'], payload)),
                    'gate v2 actualAPI complete sandbox/timeout/payload argv differs')
            if directory not in ('cases/missing_log_argument', 'cases/existing_log'):
                require(row['returncode'] == 0 and b'scope_observer_host_error' not in data[directory + '/stderr.bin'],
                        'gate v2 actualAPI original command failed')
        for case in expected_cases:
            item = actual['variants'][case]
            is_gate = key in ('gate1', 'gate2')
            build_case = ('original_entry' if is_gate else 'producer') if case in ('short_tb', 'producer_short_tb') else case
            elf_name = 'build/' + build_case + '/fixture.elf'
            require(graph.sha(data[elf_name]) == item['elf_sha256'] and item.get('program_baseline_equal') is True and
                    item.get('guest_selfcheck_and_code_readback_exact') is True, 'gate v2 fixture baseline/ELF differs')
            consoles = {}
            for mode in ('baseline', 'plugin'):
                directory = 'cases/' + case + '-' + mode
                saved = item['runs'][mode]
                require(saved.get('console') == directory + '/console.bin' and type(saved.get('returncode')) is int and
                        saved['returncode'] == command_map[directory]['returncode'] == 0 and
                        saved.get('plugin_log') == (directory + '/plugin.log' if mode == 'plugin' else None),
                        'gate v2 actualAPI run paths/returncode differ')
                consoles[mode] = data[directory + '/console.bin']
            require(consoles['baseline'] == consoles['plugin'], 'gate v2 actualAPI whole baseline console differs')
            raw = data['cases/' + case + '-plugin/plugin.log']
            if is_gate:
                sections = helper.elf_layout(data[elf_name], case)
                operands, boundary = helper.check_console(consoles['baseline'], sections, case)
                operand_name = 'cases/' + case + '-baseline/independent-operands.json'
                require(item.get('elf') == elf_name and item.get('expected_operands') == operand_name and
                        graph.sha(data[operand_name]) == item.get('expected_operands_sha256') and
                        reader.typed_equal(reader.object_json(data[operand_name]), operands) and
                        reader.typed_equal(item.get('boundary_metadata'), boundary) and
                        reader.typed_equal(reader.object_json(data['cases/' + case + '-baseline/boundary-metadata.json']), boundary) and
                        item.get('trace_adapter') == ('shutter_gate_trace_checks_v%d.assert_shutter_gate_trace_v%d' % (version, version)),
                        'gate v2 independent pre-LDR operands/adapter differ')
                assertion = checks.assert_shutter_gate_trace_v2 if key == 'gate2' else checks.assert_shutter_gate_trace_v1
                parsed = assertion(raw, declaration, operands)
                counters = helper.check_trace_counters(parsed, operands, boundary)
                require(reader.typed_equal(counters, item.get('actual_callback_counts')) and
                        item.get('trace_sha256') == graph.sha(raw) and
                        reader.typed_equal(api['cases'][case], dict(trace_sha256=graph.sha(raw), rows=len(parsed['rows']),
                            actual_callback_counts=counters, independent_console_operands=True)),
                        'gate v2 actualAPI raw trace/case readback differs')
            else:
                mutated, wrong, producer, corrupt, short = (case == 'one_byte_mutation', case == 'wrong_lr_only',
                    case in ('producer', 'producer_corrupt', 'producer_short_tb', 'producer_reverse_order'),
                    case == 'producer_corrupt', case == 'producer_short_tb')
                sections = helper.elf_layout(data[elf_name], mutated, producer, corrupt)
                producers = {}
                if producer:
                    args = (consoles['baseline'], sections, corrupt, short)
                    if key == 'scope3':
                        args += (case == 'producer_reverse_order',)
                    producers, _ = helper.check_producer_console(*args)
                else:
                    require(consoles['baseline'] == helper.expected_console(sections, mutated, wrong),
                            'gate v2 legacy independent baseline differs')
                entries = helper.scope_expectations(consoles['baseline'], producer) if not (mutated or wrong or short) else {}
                base = None if mutated or short else helper.BASE
                other = 0 if base is None else 17 if wrong else 16
                if key == 'scope2':
                    checks.assert_scope_trace_v2(raw, entries, base, other, expected_producers=producers,
                                                producer_base=helper.BASE if producers else None)
                else:
                    checks.assert_scope_trace_v3(raw, entries, base, other, expected_producers=producers,
                        producer_base=helper.BASE if producer and not short else None,
                        producer2_base=helper.BASE if producer and not short and not corrupt else None)
        require(set(actual.get('startup_negatives', {})) == {'missing_log_argument', 'existing_log'},
                'gate v2 actualAPI startup refusals missing')
        for name in ('missing_log_argument', 'existing_log'):
            row = command_map['cases/' + name]
            require(0 < row['returncode'] < 124 and b'scope_observer_host_error' in data['cases/' + name + '/stderr.bin'] and
                    b'timeout: sending signal' not in data['cases/' + name + '/stderr.bin'] and
                    not data.get('cases/' + name + '/console.bin', b'') and
                    type(actual['startup_negatives'][name].get('returncode')) is int and
                    actual['startup_negatives'][name]['returncode'] == row['returncode'] and
                    actual['startup_negatives'][name].get('guest_started') is False,
                    'gate v2 actualAPI startup refusal differs')
            if name == 'existing_log':
                sentinel = b'exclusive-shutter-gate-log-sentinel\n' if key in ('gate1', 'gate2') else b'exclusive-log-sentinel\n'
                require(data['cases/existing_log/plugin.log'] == sentinel, 'gate v2 startup sentinel changed')
            else:
                require('cases/missing_log_argument/plugin.log' not in data, 'gate v2 refused startup gained a log')


def _condition_source_proof(log, run, *, gate_v2_trust=None):
    """Read the actual evidence, never a caller-supplied approval or current C shape."""
    graph_path = BASE.parents[1] / 'report/functional-graph-evidence/check_graph.py'
    spec = importlib.util.spec_from_file_location('_hdmi11_source_reader', graph_path)
    graph = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graph)
    run = graph.absolute(run)
    modules = ('report/functional-camera-evidence/check_evidence.py',
               'runtime/analysis/scratch/evaluate-five-edges-native.py',
               'runtime/analysis/initramfs_identity.py')
    frozen = {str(graph.NATIVE / name): graph.sha(graph.read(graph.NATIVE / name)) for name in modules}
    reader, legacy, image = [graph.source_module(name, frozen) for name in modules]
    inputs = {name: graph.read(run / name, graph.MAX_JSON) for name in
              ('observer-build-inputs.json', 'runtime-manifest.json')}
    build, manifest = [graph.object_json(value) for value in inputs.values()]
    require(reader.typed_equal(build, manifest.get('compiled_observer')) and
            manifest.get('selected_observer_matches_build') is True, 'condition source/run build differs')
    observer = build['observer_sha256']
    binding_name, binding, inputs_binding = _condition_binding(graph, run, observer)
    inputs[binding_name] = inputs_binding
    batch = graph.absolute(binding['batch'])
    ready_raw, batch_raw = [graph.read(batch / name, graph.MAX_JSON) for name in ('ready.json', 'inputs.json')]
    ready, tested = map(graph.object_json, (ready_raw, batch_raw))
    require(graph.sha(ready_raw) == binding.get('batch_ready_sha256') and
            graph.sha(batch_raw) == ready.get('inputs_sha256'), 'condition source/batch binding differs')
    sources = build['sources']
    require({name: entry['sha256'] for name, entry in sources.items()} == tested['groups']['production'],
            'condition build/tested production source set differs')
    selected_sources = _condition_source_set(sources)
    for name, digest in selected_sources.items():
        entry = sources[str(BASE / name)]
        require(entry['sha256'] == digest and entry['archive_path'] ==
                str((BASE / name).relative_to(graph.NATIVE.parent.parent)), 'unreviewed condition ledger/hook source: ' + name)
    abi_raw = graph.read(batch / 'abi.json', graph.MAX_JSON)
    abi = graph.object_json(abi_raw)
    require(graph.sha(abi_raw) == ready.get('abi_sha256') and type(abi.get('returncode')) is int and
            abi['returncode'] == 0 and abi.get('observer_sha256') == observer and
            abi.get('source_archive_sha256') == build['source_archive_sha256'] and
            abi.get('source_count') == len(sources) and abi.get('capture_verified') is False and
            abi.get('regression_sha256') == ready.get('regression_sha256'), 'condition original ABI/source build differs')
    files, selected = manifest['files'], manifest['selected_initramfs_verified_files']
    require(files.get(str(BASE / 'observer-build-inputs.json')) == graph.sha(inputs['observer-build-inputs.json']) and
            files.get(str(BASE / 'menu-observe.so')) == observer == selected.get('simulation/menu-observe.so'),
            'condition actual/selected observer manifest differs')
    guest_source, scope_inputs = BASE / 'menu-initramfs.cpio', {}
    if binding['schema'] in SCOPE_BINDING_VERSIONS or binding['schema'] in (SHUTTER_GATE_RUN, SHUTTER_GATE_V2_RUN):
        guest_source, scope_inputs = _condition_scope_binding(graph, reader, run, binding, manifest, build, tested,
            **({} if gate_v2_trust is None else {'gate_v2_trust': gate_v2_trust}))
    else:
        require(gate_v2_trust is None, 'gate v2 trust cannot authorize legacy source binding')
    retained = run / 'selected-initramfs.cpio'
    retention_path = run / 'selected-initramfs-retention.json'
    if scope_inputs:
        require(retained.is_file() and retention_path.is_file(), 'condition scope retained image pair missing')
    observer_basis, image_sha, retention_raw = 'current', None, None
    if any(path.exists() or path.is_symlink() for path in (retained, retention_path)):
        retention_raw = graph.read(retention_path, graph.MAX_JSON)
        retention = graph.object_json(retention_raw)
        image_sha = files.get(str(guest_source))
        require(retention.get('selected_initramfs_sha256') == image_sha == binding.get('guest_sha256') and
                retention.get('source_path') == str(guest_source) and
                retention.get('retained_path') == str(retained) and retention.get('batch') == str(batch) and
                retention.get('batch_ready_sha256') == graph.sha(ready_raw) and
                retention.get('capture_verified') is False and binding.get('capture_verified') is False and
                ready.get('capture_verified') is False and tested.get('capture_verified') is False and
                type(retention.get('bytes')) is int and 0 < retention['bytes'] <= MAX_RETAINED_IMAGE,
                'condition retained image/run/batch binding differs')
        image_raw = graph.read(retained, MAX_RETAINED_IMAGE)
        require(len(image_raw) == retention['bytes'], 'condition retained image size differs')
        reader.digest_binding(image_raw, image_sha, 'condition retained initramfs')
        retained_observers = {'simulation/menu-observe.so': observer}
        if binding['schema'] == SHUTTER_GATE_V2_RUN:
            retained_observers['simulation/file-media-config.so'] = selected['simulation/file-media-config.so']
        image.verify_image(_ImageBytes(image_raw), retained_observers)
        observer_basis = 'image'
        del image_raw
    else:
        for path in (BASE / 'menu-observe.so', BASE / 'menu-root/simulation/menu-observe.so'):
            reader.digest_binding(reader.read_absolute(path), observer, 'condition actual observer')
    archive_raw = reader.read(run, 'observer-build-sources.tar.gz')
    reader.digest_binding(archive_raw, build['source_archive_sha256'], 'condition original source archive')
    index = {entry['archive_path']: entry['sha256'] for entry in sources.values()}
    require(len(index) == len(sources) and 'source-inputs.json' not in index, 'condition source index ambiguous')
    index_raw, total, count = None, 0, 0
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode='r:gz') as archive:
        for member in archive:
            count += 1
            total += member.size
            require(count <= 8192 and 0 <= member.size <= graph.MAX_SOURCE and total <= reader.MAX_FILE and
                    (member.isfile() or member.isdir() and member.size == 0), 'condition archive exceeds bounds')
            if member.name == 'source-inputs.json':
                require(index_raw is None and member.isfile() and member.size <= graph.MAX_JSON,
                        'condition archived source index ambiguous/oversized')
                with archive.extractfile(member) as stream:
                    index_raw = stream.read(graph.MAX_JSON + 1)
    require(index_raw is not None and reader.typed_equal(graph.object_json(index_raw), sources),
            'condition archived source index differs')
    reader.archive(archive_raw, {**index, 'source-inputs.json': graph.sha(index_raw)})
    console = graph.read(run / 'console.log', graph.MAX_LOG)
    parsed, _ = graph.console_records(console)
    scope = lambda rows: [r for r in rows if r['tag'].startswith((PREFIX + '_', STATE + '_'))]
    require(scope(log.records) == scope(legacy.Log(parsed).records), 'condition trace differs from original same-run bytes')
    for name, value in inputs.items():
        require(graph.read(run / name, graph.MAX_JSON) == value, 'condition source binding changed: ' + name)
    for path, value in scope_inputs.items():
        require(graph.read(path, max(graph.MAX_SOURCE, len(value))) == value, 'condition scope binding changed: ' + str(path))
    require(_condition_binding_name(run) == binding_name, 'condition source/run binding selection changed')
    if retention_raw is not None:
        require(graph.read(retention_path, graph.MAX_JSON) == retention_raw, 'condition image retention changed')
    require(graph.read(batch / 'ready.json', graph.MAX_JSON) == ready_raw and
            graph.read(batch / 'inputs.json', graph.MAX_JSON) == batch_raw and
            graph.read(batch / 'abi.json', graph.MAX_JSON) == abi_raw, 'condition batch changed')
    return {**({'shutter_gate_config_scope': dict(binding['scope_observer_expected']['build_metadata'],
                staged_library=str(run / 'readonly-scope-observer.so'),
                qemu_binary=binding['candidate_qemu']['path'],
                plan_binding={key: binding[key] for key in SHUTTER_GATE_PLAN_FIELDS})}
                if binding['schema'] in (SHUTTER_GATE_RUN, SHUTTER_GATE_V2_RUN) else {}),
            'run': str(run), 'source_sha256': selected_sources,
            'observer_sha256': observer, 'observer_basis': observer_basis, 'selected_initramfs_sha256': image_sha,
            'source_archive_sha256': graph.sha(archive_raw),
            'build_inputs_sha256': graph.sha(inputs['observer-build-inputs.json']),
            'manifest_sha256': graph.sha(inputs['runtime-manifest.json']),
            'run_binding_sha256': graph.sha(inputs[binding_name]),
            'run_binding_path': str(run / binding_name), 'run_binding_schema': binding['schema'],
            'batch_ready_sha256': graph.sha(ready_raw), 'abi_sha256': graph.sha(abi_raw),
            'console_sha256': graph.sha(console),
            'basis': 'real free success then mutex retirement/active-alias guard; free note after unlock',
            'independent_retirement_sequence': None}


def _leases(log, kind, native=False, run=None, *, gate_v2_trust=None):
    """Match serials, not addresses: reuse after a complete lifetime is legal."""
    published = _kind(log, 'MESSAGE_PUBLISHED', kind)
    sent = _kind(log, 'MESSAGE_SENT', kind)
    retired = _kind(log, 'KERNEL_RETIRED' if native else 'NATIVE_FREE', kind)
    require(len(published) <= {1: 3, 2: 24, 3: 2}[kind], ('message bound exceeded', kind))
    require(len(published) == len(sent) == len(retired), ('incomplete message lifetimes', kind))
    serials = [number(r, 'lease') for r in published]
    require(all(s > 0 for s in serials) and len(set(serials)) == len(serials), 'repeated message lease')
    require({number(r, 'lease') for r in sent} == set(serials) ==
            {number(r, 'lease') for r in retired}, 'sent/free lease set differs')
    result = []
    for p in published:
        serial = p['fields']['lease']
        ss = [r for r in sent if r['fields']['lease'] == serial]
        ff = [r for r in retired if r['fields']['lease'] == serial]
        require(len(ss) == len(ff) == 1, 'duplicate message send/free')
        s, f = ss[0], ff[0]
        for row in (p, s, f):
            eq(row, pointer=p['fields']['pointer'], destination=p['fields']['destination'],
               lease=serial, kind=kind, bytes=p['fields']['bytes'], rc=0)
        eq(s, source=p['fields']['source'], index=p['fields']['index'], raw=p['fields']['raw'], tid=p['fields']['tid'])
        require(number(p, 'pointer') > 0 and p['line'] < s['line'] and p['line'] < f['line'], 'message publish/send/free order')
        if native:
            eq(f, source=p['fields']['source'], index=p['fields']['index'], raw=p['fields']['raw'], tid=p['fields']['tid'])
            require(f['line'] < s['line'], 'native retirement must precede sent note')
        else:
            eq(f, sender=p['fields']['tid'], receiver=f['fields']['tid'], received=1, consumed=1)
        result.append({'published': p, 'sent': s, 'freed': f})
    source_proof = None
    for index, item in enumerate(result):
        p = item['published']
        for earlier in result[:index]:
            if number(p, 'pointer') == number(earlier['published'], 'pointer'):
                require(earlier['sent']['line'] < p['line'], 'live message address reused before send completed')
                if earlier['freed']['line'] >= p['line']:
                    require(kind == 2 and not native and run is not None, 'live message address reused without source proof')
                    if source_proof is None:
                        source_proof = _condition_source_proof(log, run,
                            **({} if gate_v2_trust is None else {'gate_v2_trust': gate_v2_trust}))
                    # The reviewed mutex ledger rejects active pointers; its free note is written after unlock.
                    item.setdefault('late_free_note_predecessors', []).append({
                        'lease': number(earlier['published'], 'lease'), 'sent': earlier['sent'],
                        'free_note': earlier['freed'], 'source_proof': source_proof})
    return result


def verify_conditions(log, run=None, *, gate_v2_trust=None):
    """Require two exact batches and all 24 same-thread native frees, by serial."""
    for record in log.records:
        if record['tag'].startswith((PREFIX + '_', STATE + '_')):
            require(not any(word in record['tag'] for word in ('FAULT', 'REJECT', 'UNSUPPORTED', 'REFUSED')),
                    ('fault/rejection prevents condition acceptance', record))
    messages = _leases(log, 2, run=run, gate_v2_trust=gate_v2_trust)
    require(len(messages) == 24, 'requires all 24 condition receives/frees')
    tids = set()
    indices = tuple(range(11)) + (12,)
    for item, index, cid in zip(messages, indices + tuple(i + 13 for i in indices), IDS * 2):
        p, f = item['published'], item['freed']
        eq(p, source=hex(CONDITION_SOURCE), destination=hex(CONDITION_SID), index=index)
        require(raw(p, 20) == struct.pack('<5I', 2, cid, 1, 0, 0), 'condition ID/value/raw bytes differ')
        require(number(f, 'tid') > 1, 'invalid condition receiver TID')
        tids.add(f['fields']['tid'])
    require(len(tids) == 1, 'conditions not consumed by one actual receiver thread')
    return {'messages': messages, 'receiver_tid': next(iter(tids)),
            'condition_model_events_verified': False, 'scope': '24 received=1 same-thread native frees; no model-publication claim'}


def verify_hdmi_effects(log, run=None, *, gate_v2_trust=None):
    """Actual C effects only; host UPM frees are explicitly not native proof."""
    allowed = {'PROFILE', 'UNADMITTED', 'RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE',
        'RESOURCES_RESERVED', 'REQUEST', 'PEER_REQUEST', 'PEER_REPLY', 'EVENT6_ENQUEUED',
        'EVENT6_CONSUMED', 'VIDEO_MANAGER', 'INTERNAL_FREE', 'REPLY_QUEUED',
        'REQUEST_FREE', 'STATE_READBACK', 'NATIVE_REPLY_FREE'}
    state_allowed = {'MESSAGE_PUBLISHED', 'MESSAGE_SENT', 'NATIVE_FREE', 'KERNEL_RETIRED',
                     'DRIVER_CONSUMED', 'PENDING'}
    scoped = [r for r in log.records if r['tag'].startswith((PREFIX + '_', STATE + '_'))]
    require(scoped, 'missing edge evidence')
    for row in scoped:
        root = PREFIX if row['tag'].startswith(PREFIX + '_') else STATE
        require(row['tag'][len(root) + 1:] in (allowed if root == PREFIX else state_allowed),
                ('fault/reject/unsupported/unexpected effect', row))
        for key in ('original_CP_executed', 'original_cp_executed', 'hardware_verified',
                    'frames_verified', 'capture_verified', 'original_RTOS_scheduling_verified'):
            if key in row['fields']:
                eq(row, **{key: 0})
    tags = ('REQUEST', 'PEER_REQUEST', 'EVENT6_ENQUEUED', 'PEER_REPLY', 'EVENT6_CONSUMED',
            'VIDEO_MANAGER', 'REPLY_QUEUED', 'REQUEST_FREE', 'STATE_READBACK', 'NATIVE_REPLY_FREE')
    edge = {tag: one(log, PREFIX + '_' + tag) for tag in tags}
    req = raw(edge['REQUEST'], 64)
    caller = struct.unpack_from('<I', req)[0]
    require(caller >> 28 == 8 and caller & 0xfffffff, 'invalid dynamic AP sender SID')
    require(req == frame(64, 1, 2, S + P, caller, req[20:24]), 'original request differs')
    identity = (edge['REQUEST']['fields']['pid'], edge['REQUEST']['fields']['producer_tid'])
    require(all(int(v) > 1 for v in identity), 'invalid AP PID/TID')
    eq(edge['REQUEST'], source=hex(caller), destination=hex(S[3]))
    for tag, size, command, flags, source, destination, words in (
            ('PEER_REQUEST', 64, 0x100, 1, S[3], P[3], S + P),
            ('PEER_REPLY', 72, 0x8100, 1, P[3], S[3], S + P + (0, 0)),
            ('REPLY_QUEUED', 56, 0x8001, 2, S[3], caller, S + (0, 0))):
        row = edge[tag]
        eq(row, pid=identity[0], source=hex(source), destination=hex(destination))
        require(number(row, 'producer_tid') > 1, 'missing actual producer TID')
        require(raw(row, size) == frame(size, command, flags, words), ('wire differs', tag))
    final = edge['NATIVE_REPLY_FREE']
    eq(final, pid=identity[0], tid=identity[1], sender=identity[1], waiter=1,
       producer_tid=edge['REPLY_QUEUED']['fields']['producer_tid'], destination=hex(caller),
       expected=hex(caller), reply=edge['REPLY_QUEUED']['fields']['pointer'], bytes=56,
       command='0x8001', rc=0, faults=0, ap_consumed=1)
    eq(edge['REQUEST_FREE'], owner=hex(S[3]), pointer=edge['REQUEST']['fields']['pointer'], bytes=64, rc=0)
    pointers = [number(edge[tag], 'pointer') for tag in ('REQUEST', 'PEER_REQUEST', 'PEER_REPLY')]
    require(all(p > 0 for p in pointers) and len(set(pointers)) == 3 and
            number(edge['REPLY_QUEUED'], 'pointer') > 0 and
            number(edge['REPLY_QUEUED'], 'pointer') != pointers[0], 'live handshake allocations alias')
    eq(edge['EVENT6_ENQUEUED'], event=6, parameter_bytes=12, token_policy='owned-answer-plus24-map',
       phase=1, wait_primary=6, keep_pending=1, peer_posthandler_pending=1,
       original_CP_event_pointer_identity_verified=0)
    eq(edge['EVENT6_CONSUMED'], consumer_raw='0x5dd814', source_complete_raw='0x5839a6',
       parameter_bytes=12, parameter_fnv=fnv(struct.pack('<I', TOKEN) + bytes(8)),
       saved_request_fnv=fnv(req), token=hex(TOKEN), actual_parameter_read=1,
       full_peer_u32_verified=4, status=0, tail=0, consumed=1, pending=0)
    eq(edge['VIDEO_MANAGER'], selector_raw='0xf749c', manager_raw='0x5d55c0', object_raw='0x10f5004',
       vptr_raw='0xd27080', method_offset='0xc', gate_load_raw='0x5d55ce', gate_offset='0x6a',
       gate_ctor_known=1, gate=0, gate_reset_at_connect=0, typed_callback_called=1,
       DMM=0, notifications=0, clocks=0, markers=0)
    eq(edge['STATE_READBACK'], source_slot=7, peer_slot=0, source_state=0, peer_state=0,
       source_pending=0, event6_consumed=1, source_gate=0, peer_state_ready=1,
       AP_reply_after_peer_and_source_callbacks=1, pixels_consumed=0)
    ordered = [edge[t]['line'] for t in tags[:-1]]
    require(ordered == sorted(set(ordered)), 'request/event/callback/publication order')
    # send() may wake the AP before its producer writes REPLY_QUEUED.
    require(edge['VIDEO_MANAGER']['line'] < final['line'], 'AP free preceded source callback')
    frees = log.rows(PREFIX + '_INTERNAL_FREE')
    require(len(frees) == 2, 'expected two peer storage frees')
    for tag, low, high in (('PEER_REQUEST', edge['EVENT6_ENQUEUED']['line'], edge['PEER_REPLY']['line']),
                           ('PEER_REPLY', edge['VIDEO_MANAGER']['line'], edge['REPLY_QUEUED']['line'])):
        matches = [r for r in frees if r['fields'].get('pointer') == edge[tag]['fields']['pointer'] and low < r['line'] < high]
        require(len(matches) == 1, ('peer lifetime differs', tag))
        eq(matches[0], owner=hex(caller), rc=0)
    conditions = verify_conditions(log, run, gate_v2_trust=gate_v2_trust)
    condition = conditions['messages']
    native = bool(_kind(log, 'KERNEL_RETIRED', 3))
    require(not (native and _kind(log, 'NATIVE_FREE', 3)), 'UPM has a second user-space owner/free')
    upm = _leases(log, 3, native)
    require(len(upm) == 2, 'requires two UPM retirements')
    for index, item in enumerate(upm):
        p = item['published']
        eq(p, source=hex(P[3]), destination=hex(UPM), index=index)
        require(raw(p, 16) == struct.pack('<4I', 0x00920117, index * 2, 0x009a0000, 0), 'UPM raw body differs')
    driver = one(log, STATE + '_DRIVER_CONSUMED')
    eq(driver, virtual_resource=1, job=6, slot=4, row=0, column=8, policy=0,
       completion='070000000000000000000000', same_owner_op1_read=1, node_freed=1,
       original_cp_executed=0, hardware_verified=0)
    require(len(bytes.fromhex(driver['fields']['initialization'])) == 18 and
            len(bytes.fromhex(driver['fields']['config'])) == 36, 'driver initialization/config size differs')
    require(edge['REQUEST']['line'] < driver['line'] < upm[0]['published']['line'] and
            (not native or upm[-1]['freed']['line'] < condition[0]['published']['line']) and
            max(max(x['sent']['line'], x['freed']['line']) for x in condition + upm) < edge['PEER_REPLY']['line'],
            'peer reply preceded actual A consumers')
    serials = [number(r, 'lease') for r in log.rows(STATE + '_MESSAGE_PUBLISHED')]
    require(len(serials) == len(set(serials)), 'lease reused across kinds')
    early = log.rows(PREFIX + '_UNADMITTED')
    for row in early:
        require(row['line'] < edge['REQUEST']['line'], 'late unadmitted request')
        eq(row, **{k: v for k, v in {'requests': 0, 'faults_unchanged': 1}.items() if k in row['fields']})
    edge.update(REQUEST=edge['REQUEST'], REPLY_FREE=final, identity=identity, caller=caller,
        source_pin=S, sink_pin=P, internal_frees=frees, condition_messages=condition, UPM_messages=upm,
        condition_receiver_tid=conditions['receiver_tid'], driver=driver, native_UPM_join_required=native,
        early_unadmitted_requests=early, scope='offline actual C effects; native admission/UPM proof not asserted',
        condition_model_events_verified=False, transition_order_runtime_logged=False,
        prior_cache_readback_runtime_logged=False, unknown_request_padding=req[20:24].hex(),
        original_CP_executed=False, original_RTOS_scheduling_verified=False,
        hardware_verified=False, frames_verified=False, capture_verified=False)
    return edge


def verify_hdmi_upm(log, run, identity=None, upm_effective_second=3, *, gate_v2_trust=None):
    """Join actual native events and committed mailbox payloads; no full-edge claim."""
    w = _watch()
    receipts = w.read_receipts(run)
    require(len(receipts) == 2, 'requires exactly two validated native UPM receipts')
    root, _ = w.validate_run(run)
    config = w.read_config(root / (w.PREFIX + '-config.json'))
    source_proof = None
    scope = config.get('readonly_scope_observer')
    named_binding = root / 'readonly-scope-run-binding.json'
    gate_schema = (w.parse_json(w.checked_read(named_binding, 4 * 1024**2)).get('schema')
                   if named_binding.exists() else None)
    gate_profiles = {SHUTTER_GATE_RUN: SHUTTER_GATE_PROFILE, SHUTTER_GATE_V2_RUN: SHUTTER_GATE_V2_PROFILE}
    if gate_schema in gate_profiles or type(scope) is dict and scope.get('profile') in gate_profiles.values():
        source_proof = _condition_source_proof(log, root,
            **({} if gate_v2_trust is None else {'gate_v2_trust': gate_v2_trust}))
        require(type(scope) is dict and
                gate_profiles.get(source_proof['run_binding_schema']) == scope.get('profile') and
                config.get('running_QEMU_sha256') == w.READONLY_SCOPE_QEMU_SHA and
                config.get('scope_build_receipt') == scope.get('build_receipt') and
                w.json.dumps(scope, sort_keys=True, allow_nan=False) ==
                w.json.dumps(source_proof['shutter_gate_config_scope'], sort_keys=True, allow_nan=False),
                'shutter gate native config/source binding differs')
    else:
        require(gate_v2_trust is None, 'gate v2 trust requires exact gate v2 source/config binding')
    result = w.read_result(config)
    coordinator = w.parse_json(w.checked_read(root / 'hdmi-upm-coordinator.json', 1024 * 1024))
    require(result.get('detached') is True and not result.get('error') and result.get('receipts') == 2 and
            result.get('dedicated_receipt_transport') is True and result.get('observations_only') is False,
            'native observer did not complete/detach cleanly')
    cleanup = coordinator.get('cleanup', {})
    require(coordinator.get('armed') is True and not coordinator.get('error') and not coordinator.get('cleanup_error') and
            cleanup.get('safe_to_close') is True and cleanup.get('detached') is True and
            cleanup.get('debugger_stopped') is True and not cleanup.get('errors'), 'native coordinator cleanup unsafe')
    deliveries = result.get('mailbox_deliveries', [])
    require(len(deliveries) == 2, 'requires both GDB mailbox commits')
    require(config['context']['module_sha256'] == w.SHAS, 'original module hashes differ')
    items = _leases(log, 3, native=True)
    require(len(items) == 2 and not _kind(log, 'NATIVE_FREE', 3), 'UPM requires only two kernel retirements')
    init = one(log, 'FULL_HDMI_UPM_MAILBOX_INIT')
    prepare = one(log, 'FULL_HDMI_UPM_MAILBOX_PREPARE')
    consumed = log.rows('FULL_HDMI_UPM_MAILBOX_CONSUMED')
    require(len(consumed) == 2 and not log.rows('FULL_HDMI_UPM_MAILBOX_REJECT'), 'guest did not consume both receipts')
    owner = str(identity[0]) if identity is not None else init['fields']['pid']
    mailbox = {'phys': number(init, 'physical'), 'nonce': number(init, 'nonce'), 'pid': int(owner)}
    w.mailbox_header(mailbox)
    require(config.get('mailbox') == mailbox, 'mailbox actual pagemap/nonce/PID differs from observer config')
    texts = {'upm': number(init, 'upm_text'), 'osal_uipc': number(init, 'osal_text')}
    require(texts == config['context']['module_texts'], 'actual module text bases differ')
    events = [w.parse_json(line) for line in w.checked_read(root / (w.PREFIX + '-events.jsonl'), 1024 * 1024).splitlines()]
    require(upm_effective_second in (2, 3), 'unknown UPM effective second ID')
    for index, (receipt, item, start, end, delivery) in enumerate(zip(receipts, items, (init, prepare), consumed, deliveries)):
        p, retired, sent = item['published'], item['freed'], item['sent']
        raw_body = struct.pack('<4I', 0x00920117, index * 2, 0x009a0000, 0).hex()
        effective = struct.pack('<4I', 0x00920117, upm_effective_second if index else 0, 0x009a0000, 0).hex()
        require(receipt['order'] == index + 1 and receipt['raw_hex'] == raw_body and receipt['effective_hex'] == effective and
                receipt['source'] == P[3] and receipt['u'] == number(p, 'pointer') and
                receipt['lease_serial'] == number(p, 'lease') and receipt['a_lease_binding_verified'] is True and
                receipt['native_allocation_retired'] is True, 'native receipt/A lease U/raw/order binding differs')
        require(receipt['producer_tid'] == number(p, 'tid') and receipt['tid'] != receipt['producer_tid'] and
                receipt['task'] != receipt['producer_task'], 'native task/actual producer binding differs')
        for row in (start, end):
            eq(row, pid=owner, tid=p['fields']['tid'], bytes=4096, version=1, record_bytes=256,
               lease=p['fields']['lease'], U=hex(receipt['u']), index=index, raw=raw_body, effective=effective,
               physical=init['fields']['physical'], nonce=init['fields']['nonce'], user_va=init['fields']['user_va'],
               upm_text=init['fields']['upm_text'], osal_text=init['fields']['osal_text'])
        require(p['line'] < start['line'] < end['line'] < retired['line'] < sent['line'], 'guest mailbox/retirement chronology differs')
        require(number(start, 'user_va') % 4096 == 0, 'mailbox user page not aligned')
        bridges = [e for e in events if e['kind'] == 'bridge' and e['seq'] == receipt['bridge_seq']]
        require(len(bridges) == 1, 'native receipt missing exact original bridge event')
        request = bytes.fromhex(bridges[0]['memory']['mailbox_record']['hex'])
        committed = w.mailbox_payload(mailbox, request, receipt)
        require(delivery == {'bridge_seq': receipt['bridge_seq'], 'lease_serial': receipt['lease_serial'],
                            'record_sha256': hashlib.sha256(committed).hexdigest()}, 'GDB mailbox commit/bridge/free sequence differs')
        if index:
            require(receipt['bridge_seq'] > receipts[0]['events']['free_return'] and
                    receipt['lease_serial'] > receipts[0]['lease_serial'] and
                    items[0]['sent']['line'] < p['line'], 'native lifetime reused before final retirement')
    return {'receipts': receipts, 'mailbox': init, 'guest_prepared': prepare, 'guest_consumed': consumed,
            'GDB_result': result, 'coordinator': coordinator,
            **({'source_proof': source_proof} if source_proof is not None else {}),
            'scope': 'two native UPM lifetimes only; no condition/AP completion claim',
            'native_UPM_verified': True, 'full_edge_verified': False}


def _get(log, key, identity, caller, after, before):
    owner, slot = ('PINMEM', 7) if key == S else ('HDMIPIN', 0)
    prefix = 'FULL_' + owner
    requests = [r for r in log.rows(prefix + '_REQUEST') if after < r['line'] < before and
                r['fields'].get('tid') == identity[1] and struct.unpack_from('<3I', raw(r, 48), 32) == key[:3]]
    require(len(requests) == 1, ('missing/duplicate canonical Get', key))
    request = requests[0]
    data = raw(request, 48)
    eq(request, source=hex(caller), destination=hex(key[3]), reply_destination=hex(caller))
    require(data == frame(48, 0, 2, key[:3] + (0,), caller, data[20:24]), 'canonical Get original bytes differ')
    replies = [r for r in log.rows(prefix + '_REPLY_QUEUED') if request['line'] < r['line'] < before and
               r['fields'].get('tid') == identity[1] and struct.unpack_from('<3I', raw(r, 56), 32) == key[:3]]
    require(len(replies) == 1, 'missing/duplicate canonical Get reply')
    reply = replies[0]
    eq(reply, source=hex(key[3]), destination=hex(caller))
    require(raw(reply, 56) == frame(56, 0x8000, 2, key[:3] + (1, key[3], 0)), 'canonical Get returned full key/state differs')
    pointer, lease = reply['fields']['reply'], reply['fields']['lease']
    require(int(pointer, 0) > 0 and int(lease) > 0, 'canonical Get lacks actual allocation/lease')
    commits = [r for r in log.rows(prefix + '_COMMIT') if r['fields'].get('lease') == lease]
    frees = [r for r in log.rows(prefix + '_NATIVE_REPLY_FREE') if r['fields'].get('lease') == lease]
    require(len(commits) == len(frees) == 1, 'canonical Get commit/free count differs')
    commit, freed = commits[0], frees[0]
    eq(commit, tid=identity[1], slot=slot, type=key[0], dir=key[1], index=key[2], pin_state=1,
       owner=hex(key[3]), status=0, reply=pointer, lease=lease, request_free_rc=0,
       connect_performed=0, pixels_consumed=0, camera_startup_verified=0)
    eq(freed, tid=identity[1], sender=identity[1], waiter=1, destination=hex(caller),
       expected=hex(caller), reply=pointer, lease=lease, bytes=56, rc=0)
    require(request['line'] < reply['line'] < commit['line'] < freed['line'] < before, 'Get not actually retired before connect')
    queries = [r for r in log.rows('PIN_QUERY') if after < r['line'] < request['line'] and
               r['fields'].get('tid') == identity[1] and r['fields'].get('raw') == data.hex()]
    require(len(queries) == 1, 'canonical Get lacks original AP query')
    eq(queries[0], source=hex(caller), destination=hex(key[3]), bytes=48)
    return {'key': key, 'original_AP_query': queries[0], 'request': request, 'reply': reply,
            'commit': commit, 'actual_same_sender_free': freed}


def _backup(log, edge):
    """Public CP bytes are reproducible; dynamic AP bytes remain runtime output."""
    keys = (0x010d008d, 0x003e0005, 0x009a0001, 0x009a0009, 0x009a000a,
            0x009a000b, 0x009a000c, 0x010704fd, 0x00920085)
    capacities = (1, 17, 28, 1, 1, 1, 4, 1, 8)
    records = [r for r in log.rows('FULL_HDMI_VIDEO_BACKUP_READ')
               if edge['REQUEST']['line'] < r['line'] < edge['driver']['line']]
    require(tuple(number(r, 'key') for r in records) == keys, 'actual Backup read keys/order/count differ')
    reader_path = BASE.parents[1] / 'report/cp3006-start/verify_public_seed.py'
    spec = importlib.util.spec_from_file_location('_hdmi11_public_seed_reader', reader_path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    public = reader.verify(BASE / 'menu-root/seed-backup.bin', keys[2:8])
    bank = public['records'][1]
    require(bank['offset'] == 0xed000 and bank['checksum_verified'], 'public CP bank identity differs')
    for record, key, capacity in zip(records, keys, capacities):
        eq(record, pid=edge['identity'][0], tid=edge['UPM_messages'][0]['published']['fields']['tid'],
           capacity=capacity, capture_verified=0)
        stored, rc = number(record, 'stored_bytes'), number(record, 'rc')
        if key in keys[2:8]:
            value = bank['keys'][f'{key:08x}']
            eq(record, source='pinned-public-CP-bank', bank_offset='0xed000', AP_runtime_value_claimed=0,
               stored_bytes=value['bytes'] if value['present'] else 0,
               rc=0 if value['present'] else 1, verified_absent=0 if value['present'] else 1)
        else:
            eq(record, private_bytes_logged=0, verified_absent=0)
            require('source' not in record['fields'], 'AP runtime read mislabeled as CP seed')
            if rc == 0:
                require(stored >= 0, 'successful AP Backup read has negative size')
                copied = min(stored, capacity)
                eq(record, copy_bytes=copied,
                   reason='bounded-read-complete' if copied else 'present-no-copy')
                if copied:
                    eq(record, read_rc=copied)
            else:
                require(key != 0x00920085 and rc < 0, 'required UPM AP Backup read failed')
        if key == 0x00920085:
            require(rc == 0 and 5 <= stored <= 8, 'UPM second-ID source unavailable')
    config = bytes.fromhex(bank['keys']['009a0001']['data']).ljust(28, b'\0')
    require(bytes.fromhex(edge['driver']['fields']['config']) == bytes(8) + config,
            'driver config not derived from actual pinned public CP input')
    initialization = bytes.fromhex(edge['driver']['fields']['initialization'])
    require(initialization[0] in (5, 6), 'driver initialization enum differs')
    model = records[1]
    if number(model, 'rc') == 0:
        copied = min(number(model, 'stored_bytes'), 17)
        require(initialization[1 + copied:] == bytes(17 - copied), 'initialization model tail not zero-filled')
    return {'reads': records, 'public_CP_bank_verified': True,
            'AP_runtime_bytes_independently_logged': False,
            'AP_runtime_basis': 'actual size/read return metadata and driver-consumed bytes; outer frozen reader required'}


def verify_hdmi_edge(log, previous_free, identity, first_graph_request, run, *, gate_v2_trust=None):
    """Require all virtual effects plus same-run native UPM/condition/AP proof."""
    edge = verify_hdmi_effects(log, run, gate_v2_trust=gate_v2_trust)
    identity = tuple(map(str, identity))
    require(edge['identity'] == identity, 'original AP PID/TID differs')
    start = edge['REQUEST']['line']
    require(first_graph_request <= previous_free < start, 'graph/predecessor bounds differ')
    for row in edge['early_unadmitted_requests']:
        require(row['line'] < first_graph_request, 'unadmitted request during/after graph phase')
    profiles = [r for r in log.rows(PREFIX + '_PROFILE') if r['fields'].get('pid') == identity[0]]
    require(len(profiles) == 1, 'missing/duplicate original AP constructor profile')
    profile = profiles[0]
    eq(profile, requested=PROFILE, enabled=1, first_missing='none', owner_pid=identity[0], initialized=1,
       hdmi_owner_pid=identity[0], hdmi_initialized=1, hdmi_state=1, initializing=1,
       hdmi_history_known=1, source_gate_known=1, source_gate=0, source_history_known=1, before_any_input=1)
    inputs = log.rows('HDMI_PHOTO_REQUEST')
    require(profile['line'] < first_graph_request and inputs and profile['line'] < min(r['line'] for r in inputs),
            'constructor was not before all HDMI input')
    gets = [_get(log, key, identity, edge['caller'], previous_free, start) for key in (S, P)]
    require(gets[0]['actual_same_sender_free']['line'] < gets[1]['request']['line'], 'source Get not retired before peer Get')
    require(edge['native_UPM_join_required'], 'host user-space UPM observations cannot prove native consumption')
    upm = verify_hdmi_upm(log, run, identity, gate_v2_trust=gate_v2_trust)
    backup = _backup(log, edge)
    prefix = _leases(log, 1)
    require(len(prefix) == 3, 'requires all three native prefix reply retirements')
    for item, command, value in zip(prefix, (0x102, 0x109, 0x127), (1, 0, CONDITION_SID)):
        p = item['published']
        requests = [r for r in inputs if r['fields'].get('command') == hex(command) and r['line'] < p['line']]
        require(len(requests) == 1, 'prefix lacks unique actual AP input')
        request = requests[0]
        eq(request, tid=identity[1], frame='0x2500', bytes=12, flags='0x1')
        require(number(request, 'value') == value, 'prefix input payload differs')
        eq(p, source=hex(P[3]), destination=request['fields']['source'], index=command)
        require(raw(p, 12) == struct.pack('<4HI', 0x2500, command | 0x8000, 12, 1, 0), 'prefix reply/status differs')
        require(max(item['sent']['line'], item['freed']['line']) < start, 'prefix not retired before connection')
    require(len(log.rows(STATE + '_MESSAGE_PUBLISHED')) == 29 and
            len(log.rows(STATE + '_MESSAGE_SENT')) == 29 and
            len(log.rows(STATE + '_NATIVE_FREE')) == 27 and
            len(log.rows(STATE + '_KERNEL_RETIRED')) == 2, 'full A lease census differs')
    subscriptions = [r for r in inputs if r['fields'].get('command') == '0x127' and r['line'] < start]
    require(len(subscriptions) == 1, 'requires actual single 0127 subscription')
    subscription = subscriptions[0]
    eq(subscription, tid=identity[1], frame='0x2500', bytes=12, flags='0x1', value=hex(CONDITION_SID))
    require(number(subscription, 'source') != CONDITION_SID, 'condition SID confused with original request source')
    receiver = edge['condition_receiver_tid']
    sites = [r for r in log.rows('RCV_SITE') if r['fields'].get('tid') == receiver and
             r['fields'].get('queue') == hex(CONDITION_SID)]
    # The production console filter omits RCV_*; received=1 is recorded by A's
    # frozen observe-after-real-receive hook before its same-thread real free.
    if sites:
        require(len(sites) == 1 and sites[0]['fields'].get('caller', '').endswith('/appFw.so+0x34e3fc4'),
                'condition receive site differs from original task_hdmi')
        eq(sites[0], timeout=-1)
    receives = [r for r in log.rows('RCV_MSG_TMO') if start < r['line'] < edge['PEER_REPLY']['line'] and
                r['fields'].get('queue') == hex(CONDITION_SID) and r['fields'].get('tid') == receiver]
    if receives:
        require(len(receives) == 24, 'incomplete optional original receive result trace')
        for received, item in zip(receives, sorted(edge['condition_messages'], key=lambda x: x['freed']['line'])):
            eq(received, result=0, bytes=20, timeout=-1, reply_code='0')
            require(item['published']['line'] < received['line'] < item['freed']['line'], 'condition receive/free lease chronology differs')
    edge.update(profile=profile, canonical_Get_retirements=gets, native_UPM=upm,
        backup_inputs=backup, prefix_reply_retirements=prefix,
        condition_subscription=subscription, condition_receiver_site=sites[0] if sites else None,
        actual_condition_receives=receives, condition_receive_site_runtime_logged=bool(sites),
        condition_receive_basis='received=1 and same receiver/TID in each original native free; outer frozen receive hook required',
        predecessor_free_line=previous_free, first_graph_request_line=first_graph_request,
        scope='same-run HDMI11 native consumers and AP retirement; outer build/locks/prior-edges/SD proof required',
        full_native_effects_verified=True)
    return edge
