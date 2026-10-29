import os
from pathlib import Path
import pytest

from host_sd import card_lease,TOTAL


def test_fixed_sparse_capacity_persists_without_ram(tmp_path):
    with card_lease(tmp_path) as card:
        assert card['bytes']==TOTAL and card['created'] and card['allocated_before']==0
        for offset in (4*1024**3+37,TOTAL-1):
            assert os.pwrite(card['fd'],b'Z',offset)==1
        with pytest.raises(BlockingIOError):
            with card_lease(tmp_path):pass
    with card_lease(tmp_path) as card:
        assert not card['created'] and os.fstat(card['fd']).st_size==TOTAL
        assert os.fstat(card['fd']).st_blocks*512<1024**2
        for offset in (4*1024**3+37,TOTAL-1):
            assert os.pread(card['fd'],1,offset)==b'Z'


def test_refuses_bad_existing_image_without_truncation(tmp_path):
    (tmp_path/'card.img').write_bytes(b'keep me')
    with pytest.raises(ValueError,match='exactly256GB'):
        with card_lease(tmp_path):pass
    assert (tmp_path/'card.img').read_bytes()==b'keep me'


def test_refuses_symlink_and_hardlink(tmp_path):
    other=tmp_path/'other';other.write_bytes(b'keep')
    (tmp_path/'card.img').symlink_to(other)
    with pytest.raises(OSError):
        with card_lease(tmp_path):pass
    (tmp_path/'card.img').unlink()
    with card_lease(tmp_path):pass
    os.link(tmp_path/'card.img',tmp_path/'alias')
    with pytest.raises(ValueError,match='singly-linked'):
        with card_lease(tmp_path):pass


def test_refuses_path_replacement_during_lease(tmp_path):
    with pytest.raises(ValueError,match='changed during lease'):
        with card_lease(tmp_path):
            (tmp_path/'card.img').rename(tmp_path/'saved.img')
            with (tmp_path/'card.img').open('xb') as stream:stream.truncate(TOTAL)
