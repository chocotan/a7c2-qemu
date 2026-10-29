from types import SimpleNamespace
import os
from unittest.mock import patch
import pytest

from host_sd import card_lease
from host_sd_snapshot import snapshot

SYNC=b'HOST_SD_BLOCK_SYNC bytes=256000000000 fsync_rc=0 errno=0 no_data_writes=1\n'


def test_sparse_snapshot_requires_original_quiesce_then_block_sync(tmp_path):
    with card_lease(tmp_path) as lease:
        assert os.pwrite(lease['fd'],b'original guest test bytes',4*1024**3)==25
        order=[]
        def quiet():order.append('quiesce');return {'owner_stopped':True}
        def sync():order.append('fsync');return SYNC
        def check(command,**kwargs):
            assert command[:2]==['fsck.fat','-n'] and order==['quiesce','fsync']
            assert len(kwargs['pass_fds'])==1
            with pytest.raises(OSError):os.write(kwargs['pass_fds'][0],b'not permitted')
            return SimpleNamespace(returncode=0,stdout=b'checked',stderr=b'')
        with patch('host_sd_snapshot.subprocess.run',side_effect=check):
            result=snapshot(lease,quiesce=quiet,guest_sync=sync)
        assert result['ok'] and result['guest_block_sync_confirmed'] and not result['card_published']
        assert not result['full_logical_sha256_verified'] and result['data_bytes']<=65536
        assert result['extents'][0]['offset']<=4*1024**3


def test_failed_fsck_is_preserved_not_repaired(tmp_path):
    with card_lease(tmp_path) as lease:
        with patch('host_sd_snapshot.subprocess.run',return_value=SimpleNamespace(
                returncode=1,stdout=b'Free cluster summary wrong',stderr=b'')):
            result=snapshot(lease,quiesce=lambda:{'owner_stopped':True},guest_sync=lambda:SYNC)
        assert not result['ok'] and result['fsck_rc']==1
        assert 'Free cluster summary wrong' in result['fsck_output']


@pytest.mark.parametrize('sync',[b'',SYNC+SYNC,SYNC.replace(b'fsync_rc=0',b'fsync_rc=-1')])
def test_reject_unconfirmed_real_block_sync(tmp_path,sync):
    with card_lease(tmp_path) as lease:
        with pytest.raises(ValueError,match='fsync not confirmed'):
            snapshot(lease,quiesce=lambda:{'owner_stopped':True},guest_sync=lambda:sync)


def test_refuses_snapshot_without_confirmed_original_owner_stop(tmp_path):
    with card_lease(tmp_path) as lease:
        with pytest.raises(ValueError,match='STOP must be confirmed'):
            snapshot(lease,quiesce=lambda:None,guest_sync=lambda:SYNC)


def test_changed_card_during_readonly_validation_is_not_accepted(tmp_path):
    with card_lease(tmp_path) as lease:
        def mutate(*args,**kwargs):
            os.pwrite(lease['fd'],b'changed',0)
            return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
        with patch('host_sd_snapshot.subprocess.run',side_effect=mutate):
            with pytest.raises(ValueError,match='changed while quiesced'):
                snapshot(lease,quiesce=lambda:{'owner_stopped':True},guest_sync=lambda:SYNC)


def test_extent_limit_is_an_explicit_refusal_not_truncated_success(tmp_path):
    with card_lease(tmp_path) as lease:
        os.pwrite(lease['fd'],b'present',0)
        with patch('host_sd_snapshot.MAX_DATA',0):
            with pytest.raises(ValueError,match='no silent truncation'):
                snapshot(lease,quiesce=lambda:{'owner_stopped':True},guest_sync=lambda:SYNC)
