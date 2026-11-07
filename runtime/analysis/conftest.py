"""Public export test inputs; these fixtures never establish firmware provenance."""
import hashlib
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

import backup_profile as backup

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope='module')
def synthetic_backup_profile(tmp_path_factory):
    """Exercise profile/receipt logic with declared synthetic seed and board inputs."""
    directory = tmp_path_factory.mktemp('synthetic-backup-profile')
    native = directory/'runtime/analysis'
    seed = native/'menu-root/seed-backup.bin'
    seed.parent.mkdir(parents=True)
    pattern = b'SYNTHETIC PUBLIC EXPORT TEST INPUT; NOT SONY BACKUP\n'
    raw = (pattern * (2390264 // len(pattern) + 1))[:2390264]
    seed.write_bytes(raw)
    primary = raw[0xed000:]
    assert len(primary) == backup.PRIMARY_BYTES
    seed_sha = hashlib.sha256(raw).hexdigest()
    primary_sha = hashlib.sha256(primary).hexdigest()
    assert seed_sha != backup.SEED_SHA and primary_sha != backup.PRIMARY_SHA
    (directory/'report').symlink_to(HERE.parents[1]/'report', target_is_directory=True)
    load_module = backup.load_module
    parser = load_module('synthetic_backup_dtb_parser',
                         HERE.parents[1]/'report/virtual-pcidma/verifiers/verify_enumeration.py')

    def synthetic_board(base, output, official, **flags):
        # The official-DTB derivation is a separate asset-dependent boundary.
        assert Path(official) == native/'unpacked/firmware.tar_unpacked/0800_appli/setting/cxd90057.dtb'
        assert flags == dict(all_pcie_wrappers=True, ccf_provider=True,
                             phy_upload=True, dma_window=True, backup_control=True)
        raw_board = Path(base).read_bytes()
        before = parser.fdt_nodes(raw_board)
        assert '/usb@b000000' in before and '/sony-test-pcie0' not in before
        header = list(struct.unpack_from('>10I', raw_board))
        structure = raw_board[header[2]:header[2] + header[9]]
        assert structure[-8:] == struct.pack('>2I', 2, 9)
        added = bytearray()
        for name in (b'sony-test-pcie0\0', b'synthetic-profile-fixture\0'):
            added.extend(struct.pack('>I', 1) + name + b'\0' * (-len(name) % 4))
            added.extend(struct.pack('>I', 2))
        structure = structure[:-8] + added + structure[-8:]
        strings = raw_board[header[3]:header[3] + header[8]]
        header[3] = header[2] + len(structure)
        header[9] = len(structure)
        header[1] = header[3] + len(strings)
        derived = bytearray(raw_board[:header[2]] + structure + strings)
        struct.pack_into('>10I', derived, 0, *header)
        output = Path(output)
        assert not output.exists()
        output.write_bytes(derived)
        after = parser.fdt_nodes(output.read_bytes())
        assert after.pop('/sony-test-pcie0') == {}
        assert after.pop('/synthetic-profile-fixture') == {}
        assert after == before
        return output

    def fixture_module(name, path):
        if name == 'backup_iomap_board':
            assert Path(path).resolve() == (HERE.parents[1]/'report/virtual-pcidma/iomap_board.py').resolve()
            return SimpleNamespace(prepare=synthetic_board)
        return load_module(name, path)

    def prepare(env):
        assert seed.read_bytes() == raw
        return backup.prepare_profile(native, env)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(backup, 'SEED_SHA', seed_sha)
        patch.setattr(backup, 'PRIMARY_SHA', primary_sha)
        patch.setattr(backup, 'load_module', fixture_module)
        yield prepare
