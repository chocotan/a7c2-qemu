"""Exercise the integration driver's actual closures without starting a VM."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

SOURCE = Path(__file__).with_name('check-natural-gtk-input.py')


def driver_tree():
    outer = ast.parse(SOURCE.read_text())
    assignment = next(node for node in outer.body if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'DRIVER' for t in node.targets))
    return ast.parse(ast.literal_eval(assignment.value))


def test_actual_status_closure_exports_mapped_button_centres(tmp_path):
    tree = driver_tree()
    status = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'observed_status')
    import threading
    window = object()
    def button(point, size, mapped=True):
        def translate(target, x, y):
            assert target is window and (x, y) == (0, 0)
            return point
        return SimpleNamespace(translate_coordinates=translate, get_mapped=lambda: mapped,
                               get_allocated_width=lambda: size[0],
                               get_allocated_height=lambda: size[1])
    ui = SimpleNamespace(window=window, buttons={
        'C1': button((1100, 220), (60, 40)),
        'SHUTTER_HALF': button((990, 100), (90, 30)),
        'SHUTTER': button((990, 134), (90, 60)),
        'UNMAPPED': button((0, 0), (0, 0), False)})
    state = dict(state='running', error=None, run=str(tmp_path), busy='', pending=0,
                 snapshot=None, events=[])
    import os
    namespace = dict(original_status=lambda self: dict(state), ui_instance=ui,
                     main_thread=threading.get_ident(), threading=threading,
                     geometry=tmp_path/'geometry.json', json=json, os=os)
    exec(compile(ast.Module(body=[status], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    vm = SimpleNamespace(lock=threading.RLock(), png=None)
    namespace['observed_status'](vm)
    positions = json.loads(namespace['geometry'].read_text())['button_positions']
    assert positions == {'C1': [1130, 240], 'SHUTTER_HALF': [1035, 115],
                         'SHUTTER': [1035, 164]}


def test_actual_ui_constructor_wrapper_keeps_owned_instance():
    tree = driver_tree()
    setup = next(node for node in tree.body if isinstance(node, ast.If)
                 and isinstance(node.test, ast.Name) and node.test.id == 'new_ui')
    calls = []
    class UI:
        def __init__(self, vm, timer=True):
            calls.append((vm, timer))
    namespace = dict(new_ui=True, module=SimpleNamespace(CameraUI=UI), ui_instance=None)
    exec(compile(ast.Module(body=[setup], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    vm = object()
    ui = UI(vm, timer=False)
    assert calls == [(vm, False)] and namespace['ui_instance'] is ui


def test_probe_rejects_sustain_before_launch(monkeypatch):
    import runpy
    api = runpy.run_path(str(SOURCE))
    monkeypatch.setattr('sys.argv', [str(SOURCE), '--new-ui', '--firstboot',
                                   '--body-controls-probe', '--sustain'])
    with pytest.raises(ValueError, match='without --sustain'):
        api['main']()
