# SPDX-License-Identifier: MIT
"""NOT_RUN: a future unified batch must supply six explicit v2 inputs, including frozen fixture pins."""
import importlib.util
import json
import os
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('real_scope_v2_unified_fixture', Path(__file__).with_name('run_fixture.py'))
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def test_real_qemu_readonly_scope_v2_plugin_content():
    result = fixture.run_fixture(Path(os.environ['A7C2_SCOPE_V2_TEST_QEMU']),
                                 Path(os.environ['A7C2_SCOPE_V2_TEST_PLUGIN']),
                                 Path(os.environ['A7C2_SCOPE_V2_TEST_OUTPUT']),
                                 schema=Path(os.environ['A7C2_SCOPE_V2_TEST_SCHEMA']),
                                 receipt=Path(os.environ['A7C2_SCOPE_V2_TEST_RECEIPT']),
                                 fixture_source_sha256=json.loads(fixture.read_small(
                                     Path(os.environ['A7C2_SCOPE_V2_TEST_FIXTURE_SOURCES']))))
    assert result['status'] == 'PASS_SELF_OWNED_QEMU_SCOPE_V2_FIXTURE'
    assert result['profile'] == 'qemu-readonly-scope-v2'
    assert result['trace_schema'] == 'readonly_scope_v2'
    assert result['scope_observer_verified'] is True and result['producer_observer_verified'] is True
    assert result['capture_verified'] is False and result['sony_branch_verified'] is False
    assert result['sony_store_verified'] is False and result['storecompletion'] is False
    assert result['instruction_retirement_verified'] is False and result['physical_asic_verified'] is False
    assert result['original_main_base_joined'] is False
    assert result['physical_asic_compatibility_verified'] is False and result['branchretirement'] is False
    expected_sources = json.loads(fixture.read_small(Path(os.environ['A7C2_SCOPE_V2_TEST_FIXTURE_SOURCES'])))
    assert result['fixture_source_sha256'] == expected_sources
    assert set(result['fixture_source_snapshots']) == set(expected_sources) == fixture.FIXTURE_SOURCE_NAMES
    for name, snapshot in result['fixture_source_snapshots'].items():
        assert snapshot['sha256'] == expected_sources[name]
        assert fixture.sha256(snapshot['source_path']) == fixture.sha256(snapshot['snapshot_path']) == expected_sources[name]
    assert set(result['variants']) == {'anchor', 'one_byte_mutation', 'wrong_lr_only', 'producer',
                                       'producer_corrupt', 'producer_short_tb'}
    producer = result['variants']['producer']
    assert producer['producer_calls'] == 17 and producer['producer_success_rows'] == 32
    assert producer['producer_early_rows'] == 2
    assert len(producer['runs']['plugin']['actual_producer']['calls']) == 17
    assert all(case['producer_success_rows'] == 0 for name, case in result['variants'].items() if name != 'producer')
    assert all(case['program_baseline_equal'] and case['guest_selfcheck_and_code_readback_exact'] and
               case['scope_schema_assertions'] == 'VERIFIED_SELF_OWNED_ONLY'
               for case in result['variants'].values())
