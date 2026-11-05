"""Check actual unified-collector statements without invoking a batch or VM."""
import ast
from pathlib import Path


HERE = Path(__file__).resolve().parent
COLLECTOR = HERE / 'scratch/validate-unified-camera.py'
GATE = '2026-10-31-qemu-shutter-gate-observer-v1'


def tree_and_main():
    tree = ast.parse(COLLECTOR.read_bytes())
    return tree, next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')


def literal(tree, name):
    return ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)))


def test_new_actual_api_is_frozen_but_only_that_module_runs_in_the_asset_stage(tmp_path):
    tree, main = tree_and_main()
    report = tmp_path / 'report'
    names = (GATE, 'old-scope-component')
    for name in names:
        folder = report / name
        (folder / 'integration').mkdir(parents=True)
        (folder / 'scope-observer.c').write_text('/* synthetic source */\n')
        (folder / 'test_scope_observer.py').write_text('raise AssertionError("must not import")\n')
        (folder / 'integration/test_actual_scope_plugin.py').write_text('raise AssertionError("must not import")\n')
        (folder / 'integration/test_fixture_driver.py').write_text('raise AssertionError("must not import")\n')
    component = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'component_files')
    loop = next(n for n in main.body if isinstance(n, ast.For)
                and isinstance(n.iter, ast.Name) and n.iter.id == 'COMPONENTS')
    namespace = dict(Path=Path, REPORT=report, COMPONENTS=names, missing=[], modules=[], extras=[])
    exec(compile(ast.Module(body=[component, loop], type_ignores=[]), str(COLLECTOR), 'exec'), namespace)
    new_actual = report / GATE / 'integration/test_actual_scope_plugin.py'
    assert new_actual in namespace['extras']
    assert str(new_actual) not in namespace['modules']
    assert str(report / 'old-scope-component/integration/test_actual_scope_plugin.py') in namespace['modules']
    for name in names:
        assert str(report / name / 'test_scope_observer.py') in namespace['modules']
        assert str(report / name / 'integration/test_fixture_driver.py') in namespace['modules']
    assert namespace['missing'] == []


def test_collector_pins_fixture_assembly_and_linker_and_all_direct_gtk_callers():
    tree, main = tree_and_main()
    assert GATE in literal(tree, 'COMPONENTS')
    model_tests = literal(tree, 'MODEL_TESTS')
    assert len(model_tests) == len(set(model_tests))
    missing_before = {'test_body_control_probe.py', 'test_focus_controls_probe.py',
        'test_media_predicate_watch.py', 'test_natural_start_trace.py', 'test_reader_boot_wait.py',
        'test_request_queue_watch.py', 'test_tcin_device.py', 'test_touch_panel.py',
        'test_udate_distribution.py', 'test_key_injection.py', 'test-menu-control.py'}
    assert missing_before <= set(model_tests)
    assert Path(__file__).name in model_tests
    assignment = next(n for n in main.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'extras' for t in n.targets))
    report = Path('/synthetic/report')
    extras = eval(compile(ast.Expression(assignment.value), str(COLLECTOR), 'eval'), {'REPORT': report})
    assert report / GATE / 'integration/fixture.S' in extras
    assert report / GATE / 'integration/link.ld' in extras
