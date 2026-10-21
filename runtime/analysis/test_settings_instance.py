"""Host publication/CAS/reset around real parser bytes; no guest save claim."""
import hashlib
from pathlib import Path
import struct
import sys

import pytest

N=Path(__file__).resolve().parent
sys.path.insert(0,str(N))
from instance_lifecycle import Instance
import setting_store
from settings_instance import load_for_boot,publish_snapshot,stage_restore,default_instance

FIRMWARE='a'*64


@pytest.fixture
def sample(tmp_path):
    seed=N/'menu-root/seed-backup.bin'
    if not seed.is_file():pytest.skip('official imported seed required; no Sony assets in source-only suite')
    image=bytearray(seed.read_bytes())
    assert hashlib.sha256(image).hexdigest()=='3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
    image[0x95556]=25;image[0x9555a]=2
    end=sum(struct.unpack_from('<II',image,24));struct.pack_into('<I',image,32,(sum(image[:32])+sum(image[36:end]))&0xffffffff)
    run=tmp_path/'run';(run/'SETTING').mkdir(parents=True)
    (run/'SETTING/Backup.bin').write_bytes(image)
    instance=tmp_path/'instance';instance.mkdir(mode=0o700)
    digest=hashlib.sha256(image).hexdigest()
    evidence={'ok':True,'language_date_consistency_verified':True,'file':'SETTING/Backup.bin',
              'guest_sha256':digest,'sha256':digest,'language':25,'date_format':2}
    return Instance(instance),run,evidence,bytes(image)


def test_publish_reload_and_offline_reset_preserve_sd_and_history(sample):
    instance,run,evidence,image=sample
    with instance.run_lease() as token:
        assert load_for_boot(token,FIRMWARE)['state']=='new'
        first=publish_snapshot(token,run,evidence,FIRMWARE,None)
        assert load_for_boot(token,FIRMWARE)['data']==image
        with pytest.raises(setting_store.Conflict):publish_snapshot(token,run,evidence,FIRMWARE,None)
    (Path(instance.path)/'card.img').write_bytes(b'preserve this SD')
    tombstone=instance.reset(first['generation'],confirmed=True)
    with instance.run_lease() as token:
        restored=load_for_boot(token,FIRMWARE)
        assert restored['state']=='reset' and restored['generation']==tombstone['generation']
        assert restored['data'] is None
    assert (Path(instance.path)/'card.img').read_bytes()==b'preserve this SD'
    assert (Path(instance.path)/('generation-'+first['generation'])/'backup.bin').read_bytes()==image


@pytest.mark.parametrize('field,value',[('ok',False),('guest_sha256','0'*64),('language',24),
                                       ('date_format',3),('file','../Backup.bin'),
                                       ('language_date_consistency_verified',False)])
def test_unverified_or_inconsistent_input_never_creates_generation(sample,field,value):
    instance,run,evidence,image=sample;evidence[field]=value
    with instance.run_lease() as token:
        with pytest.raises(ValueError):publish_snapshot(token,run,evidence,FIRMWARE,None)
        assert load_for_boot(token,FIRMWARE)['state']=='new'


def test_missing_manifest_after_commit_and_symlink_source_fail_closed(sample):
    instance,run,evidence,image=sample
    with instance.run_lease() as token:
        publish_snapshot(token,run,evidence,FIRMWARE,None)
        (Path(instance.path)/'current.json').unlink()
        with pytest.raises(setting_store.StoreError):load_for_boot(token,FIRMWARE)
    target=run/'SETTING/Backup.bin';target.rename(target.with_name('other'))
    target.symlink_to(target.with_name('other'))
    with instance.run_lease() as token:
        with pytest.raises(OSError):publish_snapshot(token,run,evidence,FIRMWARE,None)


def test_stage_restore_uses_only_current_verified_generation_and_both_seeds(sample,tmp_path,monkeypatch):
    instance,run,evidence,image=sample
    with instance.run_lease() as token:
        saved=publish_snapshot(token,run,evidence,FIRMWARE,None)
        source=Path(instance.path)/('generation-'+saved['generation'])/'backup.bin'
        observed=[]
        def builder(base,overlay,output):
            assert base==tmp_path/'base.cpio'
            assert (overlay/'seed-backup.bin').read_bytes()==image
            assert (overlay/'seed-setting/Backup.bin').read_bytes()==image
            observed.append(overlay)
            return {'entries':[{'path':name,'new_sha256':evidence['sha256']}
                               for name in ('seed-backup.bin','seed-setting/Backup.bin')]}
        monkeypatch.setattr('firmware_overlay.build_overlay_initramfs',builder)
        stage=tmp_path/'restored';stage.mkdir()
        out,manifest=stage_restore(source,saved['sha256'],tmp_path/'base.cpio',stage)
        assert out==stage/'settings-initramfs.cpio' and len(manifest['entries'])==2
        assert len(observed)==1
        badstage=tmp_path/'wrong';badstage.mkdir()
        with pytest.raises(ValueError,match='SHA'):
            stage_restore(source,'0'*64,tmp_path/'base.cpio',badstage)
        assert list(badstage.iterdir())==[]


def test_default_instance_creation_preserves_existing_state_and_rejects_links(tmp_path):
    root=tmp_path/'instances';path=default_instance(root)
    assert path==root/'default' and path.stat().st_mode&0o777==0o700
    (path/'marker').write_bytes(b'existing state')
    inode=path.stat().st_ino
    assert default_instance(root).stat().st_ino==inode
    assert (path/'marker').read_bytes()==b'existing state'
    alias=tmp_path/'alias';alias.symlink_to(root,target_is_directory=True)
    with pytest.raises(OSError):default_instance(alias)


def test_controller_stopped_reinitialization_keeps_sd_and_prior_generation(sample,tmp_path):
    from menu_control import VM,SETTINGS_FIRMWARE_SHA
    instance,run,evidence,image=sample
    with instance.run_lease() as token:
        previous=publish_snapshot(token,run,evidence,SETTINGS_FIRMWARE_SHA,None)
    vm=VM(instance=instance.path)
    card=tmp_path/'card.img';card.write_bytes(b'virtual card retained')
    vm.card_seed=card
    with pytest.raises(setting_store.StoreError):vm.reset_configuration(confirmed=False)
    with instance.run_lease() as token:
        vm.instance_lease=token
        with pytest.raises(ValueError,match='OFF'):vm.reset_configuration(confirmed=True)
        vm.instance_lease=None
    reset=vm.reset_configuration(confirmed=True)
    assert reset['state']=='reset' and vm.settings_generation==reset['generation']
    assert vm.card_seed==card and card.read_bytes()==b'virtual card retained'
    assert (Path(instance.path)/('generation-'+previous['generation'])/'backup.bin').read_bytes()==image
    with instance.run_lease() as token:
        assert load_for_boot(token,SETTINGS_FIRMWARE_SHA)['state']=='reset'
