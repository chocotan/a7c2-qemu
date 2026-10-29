"""Host-only bytes exercise the checker; never represent camera output."""
import importlib.util
import io
import json
from pathlib import Path
import struct
import pytest

SPEC = importlib.util.spec_from_file_location('capture_checker', Path(__file__).with_name('check_evidence.py'))
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


def fat_image():
    # Minimum convenient FAT16 superfloppy:4096 data clusters,2FATs,16rootentries.
    clusters, sectors = 4096, 17
    total = 1 + 2 * sectors + 1 + clusters
    b = bytearray(total * 512)
    b[:3] = b'\xeb\x3c\x90'
    struct.pack_into('<H', b, 11, 512)
    b[13] = 1
    struct.pack_into('<H', b, 14, 1)
    b[16] = 2
    struct.pack_into('<HH', b, 17, 16, total)
    b[21] = 0xf8
    struct.pack_into('<H', b, 22, sectors)
    b[510:512] = b'\x55\xaa'
    for at in (512, (1 + sectors) * 512):
        b[at:at+4] = b'\xf8\xff\xff\xff'
    return b, (1 + 2 * sectors) * 512, (2 + 2 * sectors) * 512


def set_link(b, cluster, value):
    for at in (512, 18 * 512):
        struct.pack_into('<H', b, at + cluster * 2, value)


def entry(b, at, name, cluster, data, attr=0x20):
    b[at:at+11] = name
    b[at+11] = attr
    struct.pack_into('<H', b, at+26, cluster)
    struct.pack_into('<I', b, at+28, len(data) if not attr & 0x10 else 0)


def parse(b):
    f = C.Fat16(io.BytesIO(b), len(b))
    f.walk()
    return f


def minimal_jpeg():
    # Syntactic fixture only: entropy is not a decodable image.
    return (b'\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
            b'\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x01\xff\xd9')


def test_container_candidates_are_never_firmware_capture():
    jpeg = C.candidate('/HOST.JPG', minimal_jpeg())
    assert jpeg['structure_valid'] and not jpeg['decoded'] and not jpeg['firmware_origin_verified']
    mp4 = b'\x00\x00\x00\x10ftypisom\x00\x00\x00\x00' + b'\x00\x00\x00\x08moov' + b'\x00\x00\x00\x09mdatx'
    result = C.candidate('/HOST.MP4', mp4)
    assert result['structure_valid'] and not result['decoded'] and not result['firmware_origin_verified']
    assert not C.candidate('/FAKE.JPG', b'PNG screenshot')['structure_valid']
    assert not C.candidate('/FAKE.MP4', b'not video')['structure_valid']
    assert not C.candidate('/CUT.JPG', minimal_jpeg()[:-1])['structure_valid']
    assert not C.candidate('/CUT.MP4', mp4[:-1])['structure_valid']


def test_files_directories_and_ignored_lfn_are_bounded():
    b, root, data = fat_image()
    entry(b, root, b'PRIVATE    ', 2, b'', 0x10)
    set_link(b, 2, 0xffff)
    entry(b, data, b'HOST    JPG', 3, minimal_jpeg())
    set_link(b, 3, 0xffff)
    b[data+512:data+512+len(minimal_jpeg())] = minimal_jpeg()
    # Malformed LFN records are deliberately not interpreted.
    b[root+32] = 1
    b[root+32+11] = 15
    result = parse(b)
    assert [e['path'] for e in result.entries] == ['/PRIVATE', '/PRIVATE/HOST.JPG']
    assert result.lfn_skipped == 1 and result.candidates[0]['structure_valid']


@pytest.mark.parametrize('corruption', ['cycle', 'crosslink', 'outside', 'fat-disagree', 'oversized', 'bad-bpb'])
def test_corrupt_filesystem_is_rejected(corruption):
    b, root, data = fat_image()
    entry(b, root, b'DATA    BIN', 2, b'x' * 512)
    set_link(b, 2, 0xffff)
    if corruption == 'cycle':
        set_link(b, 2, 2)
    elif corruption == 'crosslink':
        entry(b, root+32, b'OTHER   BIN', 2, b'x' * 512)
    elif corruption == 'outside':
        set_link(b, 2, 6000)
    elif corruption == 'fat-disagree':
        struct.pack_into('<H', b, 18*512+4, 0)
    elif corruption == 'oversized':
        struct.pack_into('<I', b, root+28, C.MAX_FILE+1)
    else:
        struct.pack_into('<H', b, 11, 4096)
    with pytest.raises(ValueError):
        parse(b)


def test_evidence_leaf_and_parent_symlinks_are_rejected(tmp_path):
    source = tmp_path/'real'
    source.write_bytes(b'safe')
    (tmp_path/'alias').symlink_to(source)
    with pytest.raises(OSError):
        C.read_owned(tmp_path, 'alias')
    folder = tmp_path/'sub'
    folder.mkdir()
    (tmp_path/'linkdir').symlink_to(folder, target_is_directory=True)
    with pytest.raises(OSError):
        C.read_owned(tmp_path, 'linkdir/file')
    with pytest.raises(ValueError):
        C.read_owned(tmp_path, '../real')


def test_actual_input_order_png_digest_and_malformed_proof(tmp_path):
    from PIL import Image
    import hashlib
    im = Image.new('RGB', (640, 480), 'red')
    im.save(tmp_path/'frame.png')
    (tmp_path/'console.log').write_text(
        'OBS INPUT_EVENT32 n=1 tid=3 words=[0xa7,0,1,0,0,0,0,0]\n'
        'OBS INPUT_EVENT32 n=2 tid=3 words=[0xa7,0,0,0,0,0,0,0]\n')
    proof = {'images': [{'image': 'frame.png', 'pixel_sha256': hashlib.sha256(im.tobytes()).hexdigest()}]}
    assert C.check_input(tmp_path, proof, [(0xa7, 1), (0xa7, 0)])['ok']
    with pytest.raises(ValueError):
        C.check_input(tmp_path, proof, [(0xa7, 0), (0xa7, 1)])
    proof['images'][0]['pixel_sha256'] = 'bad'
    assert not C.check_input(tmp_path, proof, [(0xa7, 1), (0xa7, 0)])['ok']
    with pytest.raises(ValueError):
        C.check_input(tmp_path, {'images': [None]}, [(0xa7, 1), (0xa7, 0)])


def test_missing_or_host_only_run_never_raises_capture_verified(tmp_path):
    result = C.inspect(tmp_path, [(0xa7, 1)])
    assert not result['input']['ok'] and not result['disk']['ok']
    assert result['firmwareCaptureProof']['capture_verified'] is False


def test_bad_atom_lengths_and_trailing_jpeg_bytes_rejected():
    for blob in (b'\x00\x00\x00\x04ftyp', b'\x00\x00\x00\x00ftyp', b'\x00\x00\x00\x01ftyp'):
        with pytest.raises(ValueError):
            C.mp4_structure(blob)
    with pytest.raises(ValueError):
        C.jpeg_structure(minimal_jpeg()+b'junk')


def test_legal_jpeg_marker_fill_is_accepted_as_structure_only():
    result = C.jpeg_structure(minimal_jpeg()[:-2]+b'\xff\xff\xff\xd9')
    assert result['structure_valid'] and not result['decoded']


def test_bomb_png_preserves_other_result_sections(tmp_path, monkeypatch):
    import zlib
    def chunk(kind, payload):
        return struct.pack('>I', len(payload))+kind+payload+struct.pack('>I', zlib.crc32(kind+payload))
    bomb = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', 20000, 20000, 8, 2, 0, 0, 0))+chunk(b'IEND', b'')
    (tmp_path/'bomb.png').write_bytes(bomb)
    (tmp_path/'console.log').write_text('OBS INPUT_EVENT32 n=1 tid=3 words=[0xa7,0,1,0,0,0,0,0]\n')
    (tmp_path/'gtk-input-proof.json').write_text(json.dumps({'images': [{'image': 'bomb.png'}]}))
    called = []
    def disk(root):
        called.append(root)
        return {'ok': True}, []
    monkeypatch.setattr(C, 'check_disk', disk)
    result = C.inspect(tmp_path, [(0xa7, 1)])
    assert called == [tmp_path] and result['disk']['ok']
    assert not result['input']['ok'] and 'safety bound' in result['input']['png'][0]['error']
    assert result['firmwareCaptureProof']['capture_verified'] is False


def test_tiny_png_is_not_original_lcd(tmp_path):
    from PIL import Image
    p = tmp_path/'tiny.png'
    Image.new('RGB', (3, 2), 'red').save(p)
    with p.open('rb') as f, pytest.raises(ValueError, match='640x480'):
        C.png_digest(f)


def disk_fixture(root, monkeypatch):
    import hashlib
    b, directory, data = fat_image()
    entry(b, directory, b'DATA    BIN', 2, b'x')
    set_link(b, 2, 0xffff)
    b[data] = ord('x')
    sd = root/'SD'
    sd.mkdir()
    image = sd/'card.img'
    image.write_bytes(b)
    evidence = 'export-'+'1'*32
    (sd/evidence).mkdir()
    (sd/evidence/'fsck.txt').write_text('fsck.fat 4.2\nfixture: 1 files, 1/4096 clusters\n')
    report = dict(expected_total=len(b), sha256=hashlib.sha256(b).hexdigest(), ok=True,
        card_published=True, fsck_rc=0, sequence=17, evidence=evidence,
        quiesce=dict(original_Fsys_FlushVolume_rc=0, owner_stopped=True, sequence=17, pid=31),
        flush_lifecycle=dict(ok=True, resumed=True, status='resumed', sequence=17, pid=31))
    monkeypatch.setattr(C, 'CARD_SIZE', len(b))
    (sd/'export.json').write_text(json.dumps(report))
    return image, report, directory


def test_disk_hash_and_tree_use_identical_bytes_even_if_source_changes(tmp_path, monkeypatch):
    image, report, directory = disk_fixture(tmp_path, monkeypatch)
    original_digest = C.digest_file
    def change_after_hash(f, snapshot=None):
        result = original_digest(f, snapshot)
        with image.open('r+b') as writer:
            writer.seek(directory)
            writer.write(b'OTHER   BIN')
        return result
    monkeypatch.setattr(C, 'digest_file', change_after_hash)
    result, candidates = C.check_disk(tmp_path)
    assert result['sha256'] == report['sha256']
    assert result['entries'][0]['path'] == '/DATA.BIN'  # source now says OTHER.BIN
    assert result['tree_and_hash_share_private_snapshot']
    assert not result['source_atomic_snapshot_claimed'] and candidates == []


@pytest.mark.parametrize('bad', ['digest', 'sequence', 'pid', 'flush-bool', 'fsck', 'symlink'])
def test_export_records_and_fsck_path_are_checked(tmp_path, monkeypatch, bad):
    image, report, _ = disk_fixture(tmp_path, monkeypatch)
    if bad == 'digest':
        report['sha256'] = '0'*64
    elif bad == 'sequence':
        report['flush_lifecycle']['sequence'] = 18
    elif bad == 'pid':
        report['flush_lifecycle']['pid'] = 32
    elif bad == 'flush-bool':
        report['quiesce']['original_Fsys_FlushVolume_rc'] = False
    elif bad == 'fsck':
        (tmp_path/'SD'/report['evidence']/'fsck.txt').write_text('not fsck evidence')
    else:
        image.unlink()
        image.symlink_to(tmp_path/'absent-image')
    (tmp_path/'SD/export.json').write_text(json.dumps(report))
    with pytest.raises((ValueError, OSError)):
        C.check_disk(tmp_path)


def test_cli_output_boundary_and_failure_report(tmp_path):
    import subprocess
    import sys
    own = tmp_path/'checker'
    own.mkdir()
    script = own/'check_evidence.py'
    script.write_bytes(Path(C.__file__).read_bytes())
    run = tmp_path/'run'
    run.mkdir()
    output = own/'result.json'
    args = [sys.executable, str(script), str(run), '--expect', '0xa7:1']
    result = subprocess.run([*args, '--output', str(output)], capture_output=True)
    assert result.returncode == 1
    report = json.loads(output.read_text())
    assert not report['firmwareCaptureProof']['capture_verified']
    forbidden = run/'output.json'
    result = subprocess.run([*args, '--output', str(forbidden)], capture_output=True)
    assert result.returncode == 2 and not forbidden.exists()


def test_private_snapshot_space_failure_returns_disk_error(tmp_path, monkeypatch):
    from types import SimpleNamespace
    image, report, _ = disk_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(C.os, 'fstatvfs', lambda fd: SimpleNamespace(f_bavail=0, f_frsize=4096))
    result = C.inspect(tmp_path, [(0xa7, 1)])
    assert not result['disk']['ok'] and 'snapshot space' in result['disk']['error']
    assert not result['firmwareCaptureProof']['capture_verified']
    assert image.exists()


def test_private_snapshot_creation_failure_is_a_structured_error(tmp_path, monkeypatch):
    disk_fixture(tmp_path, monkeypatch)
    def unavailable():
        raise OSError('fixture: temporary storage unavailable')
    monkeypatch.setattr(C.tempfile, 'TemporaryFile', unavailable)
    result = C.inspect(tmp_path, [(0xa7, 1)])
    assert not result['disk']['ok'] and 'temporary storage unavailable' in result['disk']['error']
    assert not result['firmwareCaptureProof']['capture_verified']
