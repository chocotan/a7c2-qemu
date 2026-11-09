from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import persistent_settings as settings


@pytest.fixture
def instance(tmp_path,monkeypatch):
    base=tmp_path/'storage';factory=base/'factory';factory.mkdir(parents=True)
    root=base/'default';root.mkdir();image=root/'camera.emmc'
    old=b'FIRMWARE_START'+b'A'*60000+b'SD_AND_FIRMWARE_TAIL';image.write_bytes(old)
    source=factory/'nflasha2.img';source.write_bytes(b'OFFICIAL_SETTINGS'+b'\0'*(4096-17))
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    manifest=dict(bodydata_sha256=settings.storage.PACKAGE_SHA,images=[dict(name=source.name,bytes=4096,sha256=digest)])
    raw=json.dumps(manifest).encode();(factory/'manifest.json').write_bytes(raw);(factory/'FACTORY-IMAGES-COMPLETE').write_text(hashlib.sha256(raw).hexdigest()+'\n')
    @contextmanager
    def lease(path):
        assert Path(path)==root
        fd=os.open(image,os.O_RDWR)
        try:yield dict(fd=fd,geometry={'slices':[dict(id='nflasha2',offset=512,bytes=4096)]},state={'source_images':[dict(name='nflasha2.img',bytes=4096,sha256=digest)]})
        finally:os.close(fd)
    monkeypatch.setattr(settings.storage,'instance_lease',lease)
    monkeypatch.setattr(settings.os,'statvfs',lambda _:SimpleNamespace(f_bavail=80,f_frsize=1024**3))
    return root,image,source,old


def test_reset_changes_only_official_settings_and_retains_complete_before_image(instance):
    root,image,source,old=instance;calls=[]
    result=settings.reset(root,lambda:calls.append('logical-reset') or dict(generation='new'))
    actual=image.read_bytes()
    assert actual[:512]==old[:512] and actual[4608:]==old[4608:]
    assert actual[512:4608]==source.read_bytes() and calls==['logical-reset']
    assert Path(result['before']).read_bytes()==old[512:4608]
    assert result['state']=='committed' and result['other_disk_bytes_unchanged']
    assert not (root/settings.PENDING).exists()


def test_host_configuration_failure_restores_original_complete_partition(instance):
    root,image,source,old=instance
    def rejected():raise OSError('host generation publication refused')
    with pytest.raises(OSError,match='publication refused'):settings.reset(root,rejected)
    assert image.read_bytes()==old and not (root/settings.PENDING).exists()
    receipt=json.loads(next((root/'configuration-resets').glob('reset-*/result.json')).read_bytes())
    assert receipt['rollback_verified'] is True and receipt['state']=='rolled-back'


def test_partial_partition_write_failure_rolls_back_without_touching_other_bytes(instance,monkeypatch):
    root,image,source,old=instance;original=settings._copy;calls=[]
    def partial(src,dst,count,**kwargs):
        calls.append(kwargs)
        if len(calls)==2:
            os.pwrite(dst,b'partial',kwargs['target_offset']);raise OSError('injected partial disk write')
        return original(src,dst,count,**kwargs)
    monkeypatch.setattr(settings,'_copy',partial)
    with pytest.raises(OSError,match='partial disk write'):settings.reset(root,lambda:pytest.fail('must not commit logical reset'))
    assert image.read_bytes()==old and len(calls)==3 and not (root/settings.PENDING).exists()


def test_unverified_rollback_retains_recovery_journal_and_blocks_next_boot(instance,monkeypatch):
    root,image,source,old=instance;original=settings._copy;calls=[]
    def partial(src,dst,count,**kwargs):
        calls.append(kwargs)
        if len(calls)>=2:raise OSError('disk write unavailable')
        return original(src,dst,count,**kwargs)
    monkeypatch.setattr(settings,'_copy',partial)
    with pytest.raises(OSError,match='write unavailable'):settings.reset(root,lambda:pytest.fail('must not commit'))
    marker=json.loads((root/settings.PENDING).read_bytes())
    assert marker['state']=='recovery-required' and marker['rollback_verified'] is False
    with pytest.raises(ValueError,match='未完成'):settings.require_complete(root)


def test_changed_official_settings_or_pending_marker_never_writes_disk(instance):
    root,image,source,old=instance;source.write_bytes(b'wrong')
    with pytest.raises(ValueError,match='image changed'):settings.reset(root,lambda:pytest.fail('no logical commit'))
    assert image.read_bytes()==old
    marker=root/settings.PENDING;marker.symlink_to(root/'missing')
    with pytest.raises(ValueError,match='未完成'):settings.require_complete(root)
