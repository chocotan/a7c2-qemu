import hashlib
import importlib.util
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('cp_gpio18_stage', HERE / 'stage.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


def fixture_tree(tmp_path, monkeypatch):
    tree = tmp_path / 'qemu'
    originals = {'hw/core/null-machine.c': 'start\n' + stage.ANCHOR + '\nend\n',
                 'hw/gpio/meson.build': '# fixture\n'}
    for name, text in originals.items():
        path = tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    monkeypatch.setattr(stage, 'BASES', {n: hashlib.sha256(t.encode()).hexdigest() for n, t in originals.items()})
    return tree, originals


def test_stage_fixed_profile_default_off_and_exact_readback(tmp_path, monkeypatch):
    tree, originals = fixture_tree(tmp_path, monkeypatch)
    receipt = stage.stage(tree)
    assert receipt['default_off'] is True and receipt['physical_compatible'] is False
    assert receipt['peer_input_supplied'] is False
    assert stage.stage(tree) == receipt
    board = (tree / 'hw/core/null-machine.c').read_text()
    assert board.count(stage.INSERT) == 1
    assert 'QEMU_CP_GPIO18_PROFILE' in board
    assert '0xf102f000' in board
    for name, text in originals.items():
        assert (tree / 'cp-gpio18-before' / name).read_text() == text
    for name, digest in receipt['outputs'].items():
        assert hashlib.sha256((tree / name).read_bytes()).hexdigest() == digest


def test_stage_unknown_base_refuses_before_any_change(tmp_path, monkeypatch):
    tree, originals = fixture_tree(tmp_path, monkeypatch)
    (tree / 'hw/gpio/meson.build').write_text('changed')
    with pytest.raises(ValueError, match='base differs'):
        stage.stage(tree)
    assert (tree / 'hw/core/null-machine.c').read_text() == originals['hw/core/null-machine.c']
    assert not (tree / 'cp-gpio18-before').exists()


def test_stage_rerun_refuses_staged_source_drift(tmp_path, monkeypatch):
    tree, _ = fixture_tree(tmp_path, monkeypatch)
    stage.stage(tree)
    (tree / 'hw/gpio/gpio18.c').write_text('changed')
    with pytest.raises(ValueError, match='source changed'):
        stage.stage(tree)
