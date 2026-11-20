"""Synthetic owner-quarantine tests; no QEMU, devices or signal cleanup."""
import fcntl
import os

import pytest

import owner_quarantine as quarantine
import persistent_disk


@pytest.fixture
def leased(tmp_path):
    directory=os.open(tmp_path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    lock=os.open('.disk.lock',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
    disk=os.open('camera.emmc',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    fcntl.fcntl(disk,fcntl.F_OFD_SETLK,bytes(persistent_disk._DiskLock(fcntl.F_WRLCK,os.SEEK_SET,0,1,0)))
    try:yield directory,lock,disk,tmp_path
    finally:
        os.close(disk);os.close(lock);os.close(directory)


def test_marker_requires_locks_and_survives_close(leased):
    directory,lock,disk,path=leased
    token=quarantine.Marker(directory,lock,disk,'run-1','owner-1')
    try:
        token.arm_before_gate();token.require_armed_before_gate()
        raw=(path/quarantine.NAME).read_bytes()
        with pytest.raises(quarantine.Rejected,match='removal CLOSED'):
            token.finish(owner_generation='owner-1',quit_request_id='owner-1:1',
                         quit_reply={'id':'owner-1:1','return':{}},returncode=0)
        assert (path/quarantine.NAME).read_bytes()==raw
    finally:token.close()
    with pytest.raises(quarantine.Rejected,match='unfinished'):quarantine.refuse_unfinished(directory)


def test_marker_partial_write_keeps_gate_closed(leased,monkeypatch):
    directory,lock,disk,path=leased
    token=quarantine.Marker(directory,lock,disk,'run-1','owner-1')
    original=os.pwrite
    monkeypatch.setattr(quarantine.os,'pwrite',lambda fd,raw,offset:original(fd,raw[:3],offset))
    try:
        with pytest.raises(OSError,match='short quarantine write'):token.arm_before_gate()
        with pytest.raises(quarantine.Rejected,match='not armed'):token.require_armed_before_gate()
        assert (path/quarantine.NAME).read_bytes()==token.raw[:3]
    finally:token.close()
    with pytest.raises(quarantine.Rejected,match='unfinished'):quarantine.refuse_unfinished(directory)


def test_existing_dangling_marker_is_never_treated_as_absent(leased):
    directory,lock,disk,path=leased
    (path/quarantine.NAME).symlink_to(path/'missing')
    with pytest.raises(quarantine.Rejected,match='unfinished'):
        quarantine.Marker(directory,lock,disk,'run-1','owner-1')
