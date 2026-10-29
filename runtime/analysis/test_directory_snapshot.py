import hashlib
from pathlib import Path

import pytest

from directory_sd import directory_lease
from directory_snapshot import snapshot, read_commit_status

CLEAN = lambda: {'available': True, 'pending': False, 'closed_pending': False}
SYNC = b'HOST_SD_BLOCK_SYNC bytes=256000000000 fsync_rc=0 errno=0 no_data_writes=1\n'


def test_host_files_are_read_after_original_flush_not_as_disk_image(tmp_path):
    with directory_lease(tmp_path/'card') as lease:
        root = Path(lease['path'])
        (root/'PRIVATE').mkdir()
        content = b'original guest file bytes\x00\xff'
        (root/'PRIVATE'/'PROBE.BIN').write_bytes(content)
        calls = []
        result = snapshot(lease, quiesce=lambda: calls.append('quiesce') or {'owner_stopped': True},
                          guest_sync=lambda: calls.append('sync') or SYNC,
                          original_mount=lambda: True, commit_status=CLEAN)
        assert calls == ['quiesce', 'sync']
        assert result['ok'] and result['host_directory_verified']
        assert result['host_directory'] == str(root)
        assert result['file_count'] == 1
        assert result['files'][0]['path'] == 'PRIVATE/PROBE.BIN'
        assert result['files'][0]['bytes'] == len(content)
        assert result['files'][0]['sha256'] == hashlib.sha256(content).hexdigest()
        assert not result['original_capture_verified'] and not result['firmware_format_verified']


def test_symlink_is_rejected_and_original_stop_is_required(tmp_path):
    with directory_lease(tmp_path/'card') as lease:
        root = Path(lease['path'])
        (root/'link').symlink_to('/etc/passwd')
        with pytest.raises(ValueError, match='symlink'):
            snapshot(lease, quiesce=lambda: {'owner_stopped': True}, guest_sync=lambda: SYNC,
                     original_mount=lambda: True, commit_status=CLEAN)
        with pytest.raises(ValueError, match='STOP'):
            snapshot(lease, quiesce=lambda: None, guest_sync=lambda: SYNC,
                     original_mount=lambda: True, commit_status=CLEAN)


def test_mount_failure_is_not_a_directory_success(tmp_path):
    with directory_lease(tmp_path/'card') as lease:
        with pytest.raises(ValueError, match='mount'):
            snapshot(lease, quiesce=lambda: {'owner_stopped': True}, guest_sync=lambda: SYNC,
                     original_mount=lambda: False, commit_status=CLEAN)


def test_pending_commit_is_rejected(tmp_path):
    with directory_lease(tmp_path/'card') as lease:
        with pytest.raises(ValueError, match='commit'):
            snapshot(lease, quiesce=lambda: {'owner_stopped': True}, guest_sync=lambda: SYNC,
                     original_mount=lambda: True,
                     commit_status=lambda: {'available': True, 'pending': True, 'closed_pending': False})


def test_commit_event_parser_requires_ready_and_tracks_last_state(tmp_path):
    log = tmp_path/'console.log'
    log.write_bytes(b'vvfat: directory commit tracking ready\n'
                    b'vvfat: host directory commit pending\n'
                    b'vvfat: host directory commit pending\n')
    assert read_commit_status(log) == {'available': True, 'pending': True,
                                       'closed_pending': False, 'transitions': 1}
    with log.open('ab') as stream:
        stream.write(b'vvfat: host directory commit complete\n')
    assert read_commit_status(log) == {'available': True, 'pending': False,
                                       'closed_pending': False, 'transitions': 2}
    empty = tmp_path/'empty.log'
    empty.write_bytes(b'')
    assert not read_commit_status(empty)['available']


def test_missing_or_failed_sync_never_reports_success(tmp_path):
    with directory_lease(tmp_path/'card') as lease:
        with pytest.raises(ValueError, match='fsync not confirmed'):
            snapshot(lease, quiesce=lambda: {'owner_stopped': True}, guest_sync=lambda: b'',
                     original_mount=lambda: True, commit_status=CLEAN)
