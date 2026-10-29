"""Shared hardware staging must preserve source identity and reject repeat application."""
import difflib
import hashlib
import json

import pytest

import stage_hardware as hardware


@pytest.fixture
def source(tmp_path, monkeypatch):
    src = tmp_path / 'qemu'
    contents = {
        'hw/arm/virt.c': '#include "qemu/osdep.h"\nvoid board(void) {\n'
                         '    create_gic(vms, sysmem);\n    create_pcie(vms);\n}\n',
        'hw/dma/pl330.c': '/* fixture DMA source */\n',
        'hw/misc/meson.build': '# existing objects\n',
    }
    for name, text in contents.items():
        path = src / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    origins = tmp_path / 'origins'
    origins.mkdir()
    patch = origins / 'qemu-dma330.patch'
    patch.write_text('fixture delta, not applied by these tests\n')
    (origins / 'SOURCE-ORIGINS.json').write_text(json.dumps({
        'delta_patch_sha256': hardware.sha(patch),
        'source_files': {name: {'after': hardware.sha(src / name)}
                         for name in ('hw/arm/virt.c', 'hw/dma/pl330.c')},
    }))
    monkeypatch.setattr(hardware, 'DMA', origins)
    return src


def test_same_sources_are_copied_and_receipted_once(source):
    receipt = hardware.stage(source)
    for name, digest in receipt['model_source_sha256'].items():
        assert hardware.sha(source / 'hw/misc/sony-pcidma' / name) == digest
    for name, digest in receipt['atu_source_sha256'].items():
        assert hardware.sha(source / 'hw/misc' / name) == digest
    assert receipt['virt_after'] == hardware.sha(source / 'hw/arm/virt.c')
    text = (source / 'hw/arm/virt.c').read_text()
    assert text.count('"sony-backup-pci"') == 1
    assert text.index('create_pcie(vms);') < text.index('"sony-backup-pci"')
    meson = (source / 'hw/misc/meson.build').read_text()
    assert meson.startswith('# existing objects\n')
    assert meson.count("'sony-pcidma/sony_pcidma.c'") == 1
    before = (source / 'hw/arm/virt.c').read_bytes()
    with pytest.raises(ValueError):
        hardware.stage(source)
    assert (source / 'hw/arm/virt.c').read_bytes() == before


def test_native_delta_applies_before_hardware_staging(source):
    origin = hardware.DMA / 'SOURCE-ORIGINS.json'
    records = {}
    patch = []
    for name in ('hw/arm/virt.c', 'hw/dma/pl330.c'):
        before = (source / name).read_text()
        after = before + '/* applied DMA fixture delta */\n'
        patch.extend(difflib.unified_diff(before.splitlines(keepends=True),
                                         after.splitlines(keepends=True),
                                         fromfile='a/' + name, tofile='b/' + name))
        records[name] = {key: hashlib.sha256(text.encode()).hexdigest()
                         for key, text in (('before', before), ('after', after))}
    delta = hardware.DMA / 'qemu-dma330.patch'
    delta.write_text(''.join(patch))
    origin.write_text(json.dumps({'delta_patch_sha256': hardware.sha(delta),
                                  'source_files': records}))
    receipt = hardware.stage(source, apply_dma=True)
    assert hardware.sha(source / 'hw/dma/pl330.c') == records['hw/dma/pl330.c']['after']
    assert '/* applied DMA fixture delta */' in (source / 'hw/arm/virt.c').read_text()
    assert receipt['dma_delta_sha256'] == hardware.sha(delta)
    assert (source / 'hw/misc/sony-pcidma/sony_pcidma.c').is_file()


def test_changed_input_rejected_before_staging(source):
    (source / 'hw/dma/pl330.c').write_text('unrecognized DMA implementation\n')
    before = (source / 'hw/arm/virt.c').read_bytes()
    with pytest.raises(ValueError, match='staging input differs'):
        hardware.stage(source)
    assert not (source / 'hw/misc/sony-pcidma').exists()
    assert (source / 'hw/arm/virt.c').read_bytes() == before
