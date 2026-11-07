"""Check actual unified-collector statements without invoking a batch or VM."""
import ast
import hashlib
from pathlib import Path


HERE = Path(__file__).resolve().parent
COLLECTOR = HERE / 'scratch/validate-unified-camera.py'
GATE = '2026-10-31-qemu-shutter-gate-observer-v1'
GATE_V2 = '2026-11-02-qemu-shutter-gate-observer-v2'
LEGACY_SCOPES = ('2026-10-30-qemu-readonly-scope-observer', '2026-10-31-qemu-M-writer-observer-v3')


def tree_and_main():
    tree = ast.parse(COLLECTOR.read_bytes())
    return tree, next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')


def literal(tree, name):
    return ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)))


def test_new_actual_api_is_frozen_but_only_that_module_runs_in_the_asset_stage(tmp_path):
    tree, main = tree_and_main()
    report = tmp_path / 'report'
    names = (GATE, GATE_V2, *LEGACY_SCOPES, 'old-scope-component', GATE_V2 + '-alias')
    for name in names:
        folder = report / name
        (folder / 'integration').mkdir(parents=True)
        (folder / 'scope-observer.c').write_text('/* synthetic source */\n')
        (folder / 'test_scope_observer.py').write_text('raise AssertionError("must not import")\n')
        (folder / 'integration/test_actual_scope_plugin.py').write_text('raise AssertionError("must not import")\n')
        (folder / 'integration/test_actual_scope_plugin_shadow.py').write_text('raise AssertionError("must not import")\n')
        (folder / 'integration/test_fixture_driver.py').write_text('raise AssertionError("must not import")\n')
    component = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'component_files')
    loop = next(n for n in main.body if isinstance(n, ast.For)
                and isinstance(n.iter, ast.Name) and n.iter.id == 'COMPONENTS')
    namespace = dict(Path=Path, REPORT=report, COMPONENTS=names, missing=[], modules=[], extras=[])
    exec(compile(ast.Module(body=[component, loop], type_ignores=[]), str(COLLECTOR), 'exec'), namespace)
    for name in (GATE, GATE_V2):
        actual = report / name / 'integration/test_actual_scope_plugin.py'
        assert actual in namespace['extras']
        assert str(actual) not in namespace['modules']
    for name in (*LEGACY_SCOPES, 'old-scope-component', GATE_V2 + '-alias'):
        assert str(report / name / 'integration/test_actual_scope_plugin.py') in namespace['modules']
    for name in names:
        assert str(report / name / 'integration/test_actual_scope_plugin_shadow.py') in namespace['modules']
        assert str(report / name / 'test_scope_observer.py') in namespace['modules']
        assert str(report / name / 'integration/test_fixture_driver.py') in namespace['modules']
    assert namespace['missing'] == []


def test_run_manifest_indexes_passive_collector_and_its_direct_local_dependencies(tmp_path):
    collector = HERE / 'ee_entry_snapshot.py'
    local_dependencies = {node.module + '.py' for node in ast.walk(ast.parse(collector.read_bytes()))
                          if isinstance(node, ast.ImportFrom) and node.module and
                          (HERE / (node.module + '.py')).is_file()}
    assert 'capture_gate_readback.py' in local_dependencies
    tree = ast.parse((HERE / 'qemu-menu-probe.py').read_bytes())
    loop = next(node for node in tree.body if isinstance(node, ast.For) and isinstance(node.iter, ast.List) and
                any(isinstance(value, ast.Constant) and value.value == 'ee_entry_snapshot.py'
                    for value in ast.walk(node.iter)))
    base = tmp_path / 'native/runtime/analysis'
    (base / 'device-models').mkdir(parents=True)
    expected = {}
    for name in {'ee_entry_snapshot.py', *local_dependencies}:
        raw = ('actual passive source fixture: ' + name + '\n').encode()
        (base / name).write_bytes(raw)
        expected[str(base / name)] = hashlib.sha256(raw).hexdigest()
    manifest = {'files': {}}
    namespace = dict(Path=Path, base=base, command=[str(base / 'kernel')],
        kernel_script=base / 'kernel.sh', board_dtb=base / 'board.dtb', FONT_GUEST='fonts', FONT_SPECS={}, env={},
        manifest=manifest, sha256_file=lambda path: hashlib.sha256(path.read_bytes()).hexdigest())
    exec(compile(ast.Module(body=[loop], type_ignores=[]), 'actual-manifest-index-loop', 'exec'), namespace)
    assert manifest['files'] == expected


def test_run_manifest_indexes_strict_gate_fixtures_and_independent_writer_assets(tmp_path):
    tree = ast.parse((HERE / 'qemu-menu-probe.py').read_bytes())
    loops = [node for node in tree.body if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and
             isinstance(node.test.left, ast.Name) and node.test.left.id in ('scope_observer', 'writer_observer')]
    assert len(loops) == 2
    base = tmp_path / 'native/runtime/analysis'
    base.mkdir(parents=True)
    scope_root, writer_root = base.parents[1] / 'gate', base.parents[1] / 'writer'
    scope, writer, expected = {}, {}, {}
    for metadata, root in ((scope, scope_root), (writer, writer_root)):
        for name in ('build.json', 'staged.so', 'runtime.py', 'integration/fixture.S'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('owned actual manifest-loop fixture: ' + str(path)).encode())
            expected[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        metadata.update(build_receipt=str(root / 'build.json'), library=str(root / 'staged.so'),
                        source_sha256={'runtime.py': expected[str(root / 'runtime.py')]})
    scope.update(profile='qemu-readonly-shutter-gate-v2',
                 fixture_source_sha256={'integration/fixture.S': expected[str(scope_root / 'integration/fixture.S')]})
    writer['source_sha256']['integration/fixture.S'] = expected[str(writer_root / 'integration/fixture.S')]
    manifest = {'files': {}}
    namespace = dict(Path=Path, base=base, scope_observer=scope, writer_observer=writer,
                     scope_source_root=lambda native, profile: scope_root, writer_component=writer_root,
                     manifest=manifest, sha256_file=lambda path: hashlib.sha256(path.read_bytes()).hexdigest())
    exec(compile(ast.Module(body=loops, type_ignores=[]), 'actual-scope-writer-manifest-loops', 'exec'), namespace)
    assert manifest['files'] == expected


def test_actual_writer_profile_selection_is_explicit_and_v1_default_is_retained(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    import pytest
    tree = ast.parse((HERE / 'qemu-menu-probe.py').read_bytes())
    first = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign) and
                 any(isinstance(t, ast.Name) and t.id == 'writer_observer' for t in node.targets))
    last = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.If) and
                isinstance(node.test, ast.Name) and node.test.id == 'writer_requested')
    block = compile(ast.Module(body=tree.body[first:last + 1], type_ignores=[]), 'actual-writer-selection', 'exec')
    base = tmp_path / 'native/runtime/analysis'
    base.mkdir(parents=True)
    def execute(env):
        stage = Mock(return_value={'owned': True})
        api = SimpleNamespace(stage=stage)
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=Mock()))
        namespace = dict(Path=Path, base=base, out=base / 'run', scope_observer={'primary': True},
                         env=dict(env), sys=SimpleNamespace(path=[]))
        with patch('importlib.util.spec_from_file_location', return_value=spec) as loader, \
                patch('importlib.util.module_from_spec', return_value=api):
            try:
                exec(block, namespace)
            except ValueError:
                loader.assert_not_called()
                stage.assert_not_called()
                raise
        return namespace, stage, loader
    namespace, stage, loader = execute({})
    assert namespace['writer_observer'] is None and namespace['writer_profile'] == 'qemu-readonly-shutter-writer-v1'
    stage.assert_not_called()
    loader.assert_not_called()
    for version in (1, 2, 3, 4, 5, 6, 7):
        env = dict(A7C2_SHUTTER_WRITER_BUILD='/owned/receipt.json', A7C2_SHUTTER_WRITER_BUILD_SHA256='a' * 64,
                   QEMU_SYSTEM_DIR='/owned', QEMU_SYSTEM_BINARY='qemu')
        if version != 1:
            env['A7C2_SHUTTER_WRITER_PROFILE'] = f'qemu-readonly-shutter-writer-v{version}'
        namespace, stage, loader = execute(env)
        component = base.parents[1] / ('report/2026-11-04-qemu-shutter-pointer-observer-v7' if version == 7 else
                                     'report/2026-11-04-qemu-shutter-pointer-observer-v6' if version == 6 else
                                     'report/2026-11-04-qemu-shutter-descriptor-observer-v5' if version == 5 else
                                     'report/2026-11-04-qemu-shutter-record-observer-v4' if version == 4 else
                                     f'report/2026-11-03-qemu-shutter-writer-observer-v{version}')
        module = {1: 'writer_runtime.py', 2: 'writer_origin_runtime.py', 3: 'writer_upstream_runtime.py',
                  4: 'writer_record_runtime.py', 5: 'writer_descriptor_runtime.py',
                  6: 'writer_pointer_runtime.py', 7: 'writer_pointer7_runtime.py'}[version]
        assert loader.call_args.args == ('camera_auxiliary_writer', component / module)
        assert stage.call_args.args == (component, env, base / 'run', Path('/owned/qemu'), {'primary': True})
        assert namespace['writer_observer'] == {'owned': True}
    for env in ({'A7C2_SHUTTER_WRITER_PROFILE': 'other'},
                {'A7C2_SHUTTER_WRITER_PROFILE': ''},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v2'},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v3'},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v3', 'A7C2_SHUTTER_WRITER_BUILD': '/only'},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v4'},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v4', 'A7C2_SHUTTER_WRITER_BUILD_SHA256': 'a' * 64},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v5'},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v5', 'A7C2_SHUTTER_WRITER_BUILD': '/only'},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v6'},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v6', 'A7C2_SHUTTER_WRITER_BUILD_SHA256': 'a' * 64},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v7'},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v7', 'A7C2_SHUTTER_WRITER_BUILD': '/only'},
                {'A7C2_SHUTTER_WRITER_PROFILE': 'qemu-readonly-shutter-writer-v1', 'A7C2_SHUTTER_WRITER_BUILD': '/only'}):
        with pytest.raises(ValueError):
            execute(env)


def test_collector_pins_fixture_assembly_and_linker_and_all_direct_gtk_callers():
    tree, main = tree_and_main()
    assert {GATE, GATE_V2, *LEGACY_SCOPES,
            '2026-11-03-qemu-shutter-writer-observer-v3',
            '2026-11-04-qemu-shutter-record-observer-v4',
            '2026-11-04-qemu-shutter-descriptor-observer-v5',
            '2026-11-04-qemu-shutter-pointer-observer-v6',
            '2026-11-04-qemu-shutter-pointer-observer-v7'} <= set(literal(tree, 'COMPONENTS'))
    model_tests = literal(tree, 'MODEL_TESTS')
    assert len(model_tests) == len(set(model_tests))
    missing_before = {'test_body_control_probe.py', 'test_focus_controls_probe.py',
        'test_media_predicate_watch.py', 'test_natural_start_trace.py', 'test_reader_boot_wait.py',
        'test_request_queue_watch.py', 'test_tcin_device.py', 'test_touch_panel.py',
        'test_udate_distribution.py', 'test_key_injection.py', 'test-menu-control.py'}
    assert missing_before <= set(model_tests)
    assert Path(__file__).name in model_tests
    assert {'test_bb_timecode_control.py', 'test_bb_timecode_main_wiring.py',
            'test_bb_timecode_presets.py', 'test_identity_refused.py'} <= set(model_tests)
    assignment = next(n for n in main.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'extras' for t in n.targets))
    report = Path('/synthetic/report')
    extras = eval(compile(ast.Expression(assignment.value), str(COLLECTOR), 'eval'), {'REPORT': report})
    for name in (GATE, GATE_V2, *LEGACY_SCOPES, '2026-11-03-qemu-shutter-writer-observer-v3',
                 '2026-11-04-qemu-shutter-record-observer-v4',
                 '2026-11-04-qemu-shutter-descriptor-observer-v5',
                 '2026-11-04-qemu-shutter-pointer-observer-v6',
                 '2026-11-04-qemu-shutter-pointer-observer-v7'):
        assert report / name / 'integration/fixture.S' in extras
        assert report / name / 'integration/link.ld' in extras
    assert report / '2026-11-04-qemu-shutter-record-observer-v4/record-taps.inc' in extras
    for name in ('record-taps.inc','descriptor-taps.inc'):
        assert report / '2026-11-04-qemu-shutter-descriptor-observer-v5' / name in extras
    for version in (6, 7):
        for name in ('record-taps.inc','descriptor-taps.inc','pointer-taps.inc'):
            assert report / f'2026-11-04-qemu-shutter-pointer-observer-v{version}' / name in extras
