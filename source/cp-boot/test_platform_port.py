"""Source-only platform boundary tests; no compiler, archive extraction or QEMU.

Not run by build-cp-native.sh. All synthetic material uses the product runtime/tmp.
"""
import difflib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('cp_platform_port', HERE / 'stage-platform.py')
port = importlib.util.module_from_spec(spec)
spec.loader.exec_module(port)


@pytest.fixture
def workspace():
    parent = HERE.parent.parent / 'runtime/tmp'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cp-platform-test-', dir=parent) as directory:
        yield Path(directory)


def tree_fixture(workspace, monkeypatch):
    tree = workspace / 'tree'
    board = 'hw/core/null-machine.c'
    model = 'hw/misc/model.c'
    original, replacement, model_data = b'old board\n', b'new board\n', b'runtime model\n'
    for name, data in ((board, original), ('VERSION', b'fixture\n')):
        path = tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (tree / 'hw/misc').mkdir()
    patch = ''.join(difflib.unified_diff(original.decode().splitlines(True),
                                        replacement.decode().splitlines(True),
                                        fromfile='a/' + board, tofile='b/' + board)).encode()
    origin = dict(sources={board: dict(before=port.sha(original), after=port.sha(replacement)),
                           model: dict(before=None, after=port.sha(model_data))},
                  source_models={model: port.sha(model_data)},
                  unchanged_inputs={'VERSION': port.sha(b'fixture\n')}, upstream={},
                  patch={'sha256': port.sha(patch)}, scope='synthetic source fixture')
    monkeypatch.setattr(port, 'recipe', lambda: (origin, port.sha(port.encoded(origin)),
                                                patch, {model: model_data}))
    return tree, board, model, original


def build_fixture(workspace, monkeypatch):
    product = workspace / 'product'
    (product / 'source/build').mkdir(parents=True)
    archive = workspace / 'qemu-11.1.2.tar.xz'
    archive.write_bytes(b'pinned synthetic archive bytes; never extracted\n')
    origin = {'upstream': {'archive': {'sha256': port.sha(archive.read_bytes())}}}
    monkeypatch.setattr(port, 'PRODUCT', product)
    monkeypatch.setattr(port, 'recipe', lambda: (origin, '0' * 64, b'', {}))
    monkeypatch.setattr(port.os, 'statvfs', lambda _: SimpleNamespace(f_bavail=128 * port.GIB // 4096,
                                                                    f_frsize=4096))
    return archive, product / 'source/build/new-cp'


def test_published_inventory_is_only_five_deltas_and_three_runtime_models():
    origin, _, _, models = port.recipe()
    assert set(origin['sources']) == {
        'hw/core/null-machine.c', 'hw/dma/meson.build', 'hw/misc/meson.build',
        'hw/watchdog/meson.build', 'hw/timer/sony_hwtimer.c',
        'hw/dma/sony_cp_edma.c', 'hw/misc/sony_cp_edma_gate.c', 'hw/watchdog/sony_cxd_wdt.c'}
    assert set(models) == {'hw/dma/sony_cp_edma.c', 'hw/misc/sony_cp_edma_gate.c',
                           'hw/watchdog/sony_cxd_wdt.c'}
    assert origin['sources']['hw/core/null-machine.c']['after'] == '8d4e4ab5863c5bd8408ba276f13c5f58b93bf1048750a68bb450e0fc4de06af3'
    assert origin['downstream']['notify_stage_sha256'] == '79041461b7b834ef3c1610bb98eff521574d567c5f789d5eb7d62b65b7d67c1e'
    assert origin['downstream']['recipe_files']['notify-qemu.c'] == 'a7f4031567c724700420259ac5bcc3170349ed5a15f5e55fcbca0dada03ecda4'
    assert all(origin['boundaries'][key] is False for key in origin['boundaries'])


def test_stage_readback_backup_and_idempotence(workspace, monkeypatch):
    tree, board, model, original = tree_fixture(workspace, monkeypatch)
    proof = port.stage(tree)
    assert proof['default_off'] is True and proof['physical_compatible'] is False
    assert port.stage(tree) == proof
    assert (tree / 'cp-platform-before' / board).read_bytes() == original
    assert (tree / model).read_bytes() == b'runtime model\n'
    for name, digest in proof['outputs'].items():
        assert port.sha((tree / name).read_bytes()) == digest


@pytest.mark.parametrize('changed', ('unknown-before', 'partial-after', 'unowned-model'))
def test_stage_unknown_base_rejected_before_writes(workspace, monkeypatch, changed):
    tree, board, model, _ = tree_fixture(workspace, monkeypatch)
    if changed == 'unowned-model':
        (tree / model).write_bytes(b'occupied\n')
    else:
        (tree / board).write_bytes(b'new board\n' if changed == 'partial-after' else b'unknown\n')
    before = {path.relative_to(tree): path.read_bytes() for path in tree.rglob('*') if path.is_file()}
    with pytest.raises(ValueError):
        port.stage(tree)
    assert not (tree / 'cp-platform-before').exists()
    assert not (tree / 'cp-platform-stage.json').exists()
    assert before == {path.relative_to(tree): path.read_bytes() for path in tree.rglob('*') if path.is_file()}


@pytest.mark.parametrize('drift', ('output', 'backup', 'receipt-inventory'))
def test_idempotence_checks_all_outputs_backups_and_receipt(workspace, monkeypatch, drift):
    tree, board, model, _ = tree_fixture(workspace, monkeypatch)
    proof = port.stage(tree)
    if drift == 'output':
        (tree / model).write_bytes(b'drift\n')
    elif drift == 'backup':
        (tree / 'cp-platform-before' / board).write_bytes(b'drift\n')
    else:
        del proof['outputs'][model]
        (tree / 'cp-platform-stage.json').write_bytes(port.encoded(proof))
    with pytest.raises(ValueError):
        port.stage(tree)


def test_stage_rejects_symlink_source_without_touching_target(workspace, monkeypatch):
    tree, board, _, _ = tree_fixture(workspace, monkeypatch)
    destination = workspace / 'original.c'
    (tree / board).rename(destination)
    (tree / board).symlink_to(destination)
    with pytest.raises(ValueError, match='symlink'):
        port.stage(tree)
    assert destination.read_bytes() == b'old board\n'
    assert not (tree / 'cp-platform-before').exists()


def test_build_preflight_is_read_only_and_budgets_both_sources_and_build(workspace, monkeypatch):
    archive, output = build_fixture(workspace, monkeypatch)
    proof = port.preflight_build(archive, output)
    assert proof['workers'] == 2 and proof['default_binary_replaced'] is False
    assert proof['storage']['required_bytes'] == 80 * port.GIB
    assert proof['storage']['reserve_bytes'] == 64 * port.GIB
    assert not output.exists()


def test_build_rejects_bad_archive_sha_before_output(workspace, monkeypatch):
    archive, output = build_fixture(workspace, monkeypatch)
    archive.write_bytes(b'bad archive\n')
    with pytest.raises(ValueError, match='archive SHA256'):
        port.preflight_build(archive, output)
    assert not output.exists()


@pytest.mark.parametrize('where', ('archive', 'output-parent', 'output'))
def test_build_rejects_symlink_paths(workspace, monkeypatch, where):
    archive, output = build_fixture(workspace, monkeypatch)
    if where == 'archive':
        link = workspace / 'archive-link'
        link.symlink_to(archive)
        archive = link
    elif where == 'output-parent':
        link = output.parent / 'redirect'
        link.symlink_to(workspace, target_is_directory=True)
        output = link / 'new-cp'
    else:
        output.symlink_to(workspace / 'missing')
    with pytest.raises(ValueError, match='symlink'):
        port.preflight_build(archive, output)


def test_build_rejects_existing_output_and_retains_its_bytes(workspace, monkeypatch):
    archive, output = build_fixture(workspace, monkeypatch)
    output.mkdir()
    keeper = output / 'keeper'
    keeper.write_bytes(b'existing output\n')
    with pytest.raises(ValueError, match='already exists'):
        port.preflight_build(archive, output)
    assert keeper.read_bytes() == b'existing output\n'


def test_build_rejects_output_outside_owned_build_area(workspace, monkeypatch):
    archive, _ = build_fixture(workspace, monkeypatch)
    output = workspace / 'external'
    with pytest.raises(ValueError, match='source/build'):
        port.preflight_build(archive, output)
    assert not output.exists()


def test_build_rejects_tmp_output(workspace, monkeypatch):
    archive, _ = build_fixture(workspace, monkeypatch)
    with pytest.raises(ValueError, match='outside /tmp'):
        port.preflight_build(archive, Path('/tmp/cp-platform-port-forbidden'))


@pytest.mark.parametrize('available', (None, 79 * 1024 ** 3))
def test_build_rejects_unknown_or_insufficient_space(workspace, monkeypatch, available):
    archive, output = build_fixture(workspace, monkeypatch)
    def space(_):
        if available is None:
            raise OSError('no filesystem data')
        return SimpleNamespace(f_bavail=available // 4096, f_frsize=4096)
    monkeypatch.setattr(port.os, 'statvfs', space)
    with pytest.raises(ValueError, match='space'):
        port.preflight_build(archive, output)
    assert not output.exists()


def test_fresh_parent_checked_without_rewriting_historical_metadata(workspace):
    tree = workspace / 'fresh-parent'
    tree.mkdir()
    raw = port.encoded(dict(inherited_sources={}, outputs={}, default_off=True))
    path = tree / 'cp-notify-stage.json'
    path.write_bytes(raw)
    assert port.check(tree, path.name, port.sha(raw)) == raw
    assert path.read_bytes() == raw
    assert 'source_update' not in json.loads(path.read_bytes())
    path.write_bytes(raw + b' ')
    with pytest.raises(ValueError):
        port.check(tree, path.name, port.sha(raw))
