"""Complete source receipt validation; does not stage, compile or launch QEMU."""
import copy
from pathlib import Path
import runpy

import pytest


@pytest.fixture
def recipe():
    return runpy.run_path(str(Path(__file__).with_name('stage-peripherals.py')))


def proof(recipe):
    files=recipe['FILES'];runtime=recipe['RUNTIME_SOURCES'];bases=recipe['BASES'];sha=recipe['sha']
    destinations={('hw/gpio/notify-qemu.c' if name=='native-notify-qemu.c' else 'hw/misc/a7c2-cp/'+name) for name in files}
    destinations.update('hw/misc/a7c2-cp/'+name for name in runtime.values())
    result=dict(schema=recipe['SCHEMA'],profile=recipe['PROFILE'],default_off=True,
                parent_stage_sha256=recipe['PARENT_SHA'],base_sha256=copy.deepcopy(bases),
                inherited_sources={},upstream_sources=copy.deepcopy(recipe['UPSTREAM']),
                sources={name:sha((recipe['HERE']/name).read_bytes()) for name in files},
                runtime_sources={name:sha((recipe['PRODUCT']/name).read_bytes()) for name in runtime},
                outputs={name:'0'*64 for name in set(bases)|destinations},
                native_link_profile='virtual-native-ap-cp-link-v1',native_link_default_off=True,
                component_secure_groups_profile='virtual-native-component-gic-groups-v1',
                component_secure_groups_default_off=True,component_secure_groups_base=0x0b020000,
                component_secure_groups_bytes=64,
                key_gpio_profile='virtual-cp-key-gpio-v1',key_gpio_default_off=True,key_gpio_physical_mapping_verified=False,
                cp_dfs_base=0xf1388f48,cp_dfs_bytes=0x14,cp_dfs_physical_compatible=False,cp_dfs_clocks_changed=False,
                p1_spi_component_profile='virtual-p1-pl022-component-v1',p1_spi_component_default_off=True,p1_spi_peer_verified=False,
                p1_dma_max_bytes=24*1024*1024,
                ap_gpio_output_readback_profile='virtual-native-ap-gpio-output-readback-v1',
                ap_gpio_output_readback_default_off=True,ap_gpio_output_readback_mask=0x300,
                ap_gpio_output_source='local-port18-wdata-latch',ap_gpio_output_physical_readback_verified=False)
    for name, digest in result['sources'].items():
        target = 'hw/gpio/notify-qemu.c' if name=='native-notify-qemu.c' else 'hw/misc/a7c2-cp/'+name
        result['outputs'][target] = digest
    for name, digest in result['runtime_sources'].items():
        result['outputs']['hw/misc/a7c2-cp/'+runtime[name]] = digest
    result.update({name:False for name in ('physical_compatible','virtual_reset_measured','forced_slave_ack',
                   'tpu_runtime_supported','pl080_scu_reset_route_verified',
                   'native_physical_edge_encoding_verified','native_local_ram_unified')})
    return result


@pytest.mark.parametrize('parent',['PARENT_SHA','FRESH_PARENT_SHA'])
def test_complete_current_source_manifest_shape(recipe,parent):
    record=proof(recipe);record['parent_stage_sha256']=recipe[parent]
    recipe['validate_receipt'](record,{})


@pytest.mark.parametrize('target', ['hw/misc/a7c2-cp/scu.c', 'hw/misc/a7c2-cp/registers.c'])
def test_compiled_copy_must_match_current_source(recipe, target):
    record = proof(recipe)
    record['outputs'][target] = '0'*64
    with pytest.raises(ValueError, match='staged copy'):
        recipe['validate_receipt'](record, {})


@pytest.mark.parametrize('field,wrong',[
    ('schema','a7c2-cp-peripherals-stage-v1'),
    ('schema','a7c2-cp-peripherals-stage-v2'),
    ('schema','a7c2-cp-peripherals-stage-v3'),
    ('schema','a7c2-cp-peripherals-stage-v5'),
    ('cp_dfs_base',0xf1388f50),
    ('cp_dfs_bytes',0x18),
    ('cp_dfs_physical_compatible',True),
    ('cp_dfs_clocks_changed',True),
    ('p1_spi_component_profile','unknown'),
    ('p1_spi_component_default_off',False),
    ('p1_spi_peer_verified',True),
    ('p1_dma_max_bytes',8*1024*1024),
    ('key_gpio_profile','unknown'),
    ('key_gpio_default_off',False),
    ('key_gpio_physical_mapping_verified',True),
    ('ap_gpio_output_readback_profile','unknown'),
    ('ap_gpio_output_readback_default_off',False),
    ('ap_gpio_output_readback_mask',0x380),
    ('ap_gpio_output_source','peer-not-local'),
    ('ap_gpio_output_physical_readback_verified',True),
    ('component_secure_groups_profile','unknown'),
    ('component_secure_groups_default_off',False),
    ('component_secure_groups_default_off',1),
    ('component_secure_groups_base',0x0b020040),
    ('component_secure_groups_bytes',68),
])
def test_diagnostic_scope_drift_rejected(recipe,field,wrong):
    record=proof(recipe);record[field]=wrong
    with pytest.raises(ValueError):recipe['validate_receipt'](record,{})


@pytest.mark.parametrize('field',['component_secure_groups_profile','component_secure_groups_default_off',
                                  'component_secure_groups_base','component_secure_groups_bytes',
                                  'key_gpio_profile','key_gpio_default_off','key_gpio_physical_mapping_verified',
                                  'cp_dfs_base','cp_dfs_bytes','cp_dfs_physical_compatible','cp_dfs_clocks_changed',
                                  'p1_spi_component_profile','p1_spi_component_default_off','p1_spi_peer_verified','p1_dma_max_bytes',
                                  'ap_gpio_output_readback_profile','ap_gpio_output_readback_default_off',
                                  'ap_gpio_output_readback_mask','ap_gpio_output_source',
                                  'ap_gpio_output_physical_readback_verified'])
def test_missing_diagnostic_scope_rejected(recipe,field):
    record=proof(recipe);record.pop(field)
    with pytest.raises(ValueError):recipe['validate_receipt'](record,{})


def test_unknown_parent_rejected(recipe):
    record=proof(recipe);record['parent_stage_sha256']='0'*64
    with pytest.raises(ValueError):recipe['validate_receipt'](record,{})


@pytest.mark.parametrize('table',['sources','runtime_sources','outputs','base_sha256','inherited_sources','upstream_sources'])
def test_null_source_tables_rejected(recipe,table):
    record=proof(recipe);record[table]=None
    with pytest.raises(ValueError):recipe['validate_receipt'](record,{})


@pytest.mark.parametrize('table',['sources','runtime_sources','outputs'])
def test_deleted_source_or_output_is_not_accepted(recipe,table):
    record=proof(recipe);record[table].pop(next(iter(record[table])))
    with pytest.raises(ValueError):recipe['validate_receipt'](record,{})


def test_source_drift_is_not_hidden_by_unchanged_outputs(recipe):
    record=proof(recipe);record['sources']['native-edma-qemu.c']='0'*64
    with pytest.raises(ValueError,match='source or staged copy changed'):
        recipe['validate_receipt'](record,{})


@pytest.mark.parametrize('field',['physical_compatible','forced_slave_ack','tpu_runtime_supported',
                                  'pl080_scu_reset_route_verified','native_physical_edge_encoding_verified',
                                  'native_local_ram_unified'])
def test_host_receipt_cannot_promote_unknowns(recipe,field):
    record=proof(recipe);record[field]=True
    with pytest.raises(ValueError):recipe['validate_receipt'](record,{})


def test_new_destination_parent_symlink_rejected(recipe,tmp_path):
    target=tmp_path/'tree';target.mkdir();outside=tmp_path/'outside';outside.mkdir()
    (target/'hw').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='symlinks'):
        recipe['target_path'](target,'hw/misc/new.c')
    assert not (outside/'misc').exists()


@pytest.mark.parametrize('name',['/etc/file.c','../file.c','hw/../../file.c'])
def test_destination_traversal_rejected(recipe,tmp_path,name):
    with pytest.raises(ValueError):recipe['target_path'](tmp_path,name)
