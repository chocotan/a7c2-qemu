"""Meaningful transport corruptions and source-parser faults; no VM."""
import hashlib
import json
from pathlib import Path
import struct

import pytest

from settings_checkpoint import inspect_backup,snapshot,fnv

N=Path(__file__).resolve().parent


@pytest.fixture
def saved():
    seed=N/'menu-root/seed-backup.bin'
    if not seed.is_file():
        pytest.skip('original ALLLANG seed-backup.bin is not distributed')
    data=seed.read_bytes()
    assert hashlib.sha256(data).hexdigest()=='3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
    data=bytearray(data);data[0x95556]=25;data[0x9555a]=2
    end=sum(struct.unpack_from('<II',data,24))
    struct.pack_into('<I',data,32,(sum(data[:32])+sum(data[36:end]))&0xffffffff)
    return bytes(data)


@pytest.mark.parametrize('fault',['none','ram-corrupt','guest-sha','wrong-api','missing-done','ambiguous','helper-fail'])
def test_original_snapshot_transaction_accepts_only_consistent_evidence(tmp_path,saved,fault):
    scope='scope=sid02cf_language_date_bank0_only'
    marker=(f'USER_SETTINGS_SNAPSHOT_MATCH lang={26 if fault=="wrong-api" else 25} date=2 {scope}\n'
            f'USER_SETTINGS_EXPORTED physical=0x41e600000 bytes=2390264 fnv1a64={fnv(saved)} {scope}\n'
            f'USER_SETTINGS_DONE rc=0 {scope}\nSETTINGS_SNAPSHOT_RC={1 if fault=="helper-fail" else 0}\n').encode()
    if fault=='missing-done':marker=marker.replace(f'USER_SETTINGS_DONE rc=0 {scope}\n'.encode(),b'')
    if fault=='ambiguous':marker+=b'SETTINGS_SNAPSHOT_RC=0\n'
    def serial(command,timeout):
        if ' snapshot;' in command:return marker
        return ('SHA2-256(/setting/Backup.bin)= '+('0'*64 if fault=='guest-sha' else hashlib.sha256(saved).hexdigest())+'\n').encode()
    def qmp(command,args):
        assert command=='pmemsave' and args=={'val':0x41e600000,'size':2390264,'filename':'/out/SETTING/Backup.bin'}
        data=bytearray(saved)
        if fault=='ram-corrupt':data[100]^=1
        (tmp_path/'SETTING/Backup.bin').write_bytes(data)
    if fault=='none':
        result=snapshot(serial,qmp,tmp_path)
        assert result['ok'] and result['language']==25 and result['date_format']==2
        assert result['guest_sha256']==hashlib.sha256(saved).hexdigest()
        assert result['all_settings_verified'] is False
    else:
        with pytest.raises((ValueError,RuntimeError)):snapshot(serial,qmp,tmp_path)
        result=json.loads((tmp_path/'SETTING/checkpoint.json').read_text())
        assert result['ok'] is False and 'error' in result


def test_bank_corruption_and_out_of_bounds_property_fail_closed(saved):
    for offset in (100,970752+100):
        data=bytearray(saved);data[offset]^=1
        with pytest.raises(ValueError,match='checksum'):inspect_backup(data)
    for data in (saved[:-1],saved+b'x'):
        with pytest.raises(ValueError):inspect_backup(data)
