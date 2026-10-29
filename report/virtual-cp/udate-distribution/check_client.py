#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
path = HERE.parents[1] / 'virtual-dma330/dma330-kernel-client-abi/check_elf.py'
spec = importlib.util.spec_from_file_location('udate_kernel_abi', path)
abi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(abi)
module = abi.ELF(HERE / 'sony_udate_distribution.ko')
module.descriptor('sony_udate_distribution', [(0x158, 257, 'init_module', 0)])
module.no_versions()
expected = {
    'printk', 'osal_reg_public', 'osal_valloc_msg_wait', 'osal_set_msg_src',
    'osal_get_msg_src', 'osal_snd_msg', 'osal_free_msg', 'osal_dynamic_id',
    'osal_rcv_msg_tmo', 'osal_snd_sync_direct', 'param_ops_bool',
    'pci_get_domain_bus_and_slot', 'pci_enable_device', 'pci_disable_device',
    'pci_set_master', 'pci_dev_put', 'pci_bus_read_config_dword', 'pci_iomap_range',
    'pci_iounmap', '__memcpy_fromio', 'pcidma_connect',
}
parameter=module.byname['__param']
abi.require((parameter['size'],parameter['align'])==(40,8),'bool parameter record ABI')
parameter_bytes=bytearray(40);parameter_bytes[26]=0xff
abi.require(module.data(parameter)==parameter_bytes,'default bool parameter fields')
abi.require(sorted((r['offset'],r['type'],r['symbol'],r['addend']) for r in module.relocs
                   if r['section']=='__param')==[
    (0,257,'backup_param_name',0),(8,257,'__this_module',0),
    (16,257,'param_ops_bool',0),(32,257,'backup_model',0)],'bool parameter relocations')
flag=module.named('backup_model')
abi.require(flag['size']==1 and module.sections[flag['shndx']]['type']==8,
            'Backup parameter must be one zero-initialized byte')
imports = {s['name'] for s in module.symbols if s['shndx'] == 0 and s['name']}
abi.require(imports == expected, 'normal exported kernel OSAL/PCI APIs only')
abi.require(all(r['type'] in (257, 282, 283) for r in module.relocs), 'unsupported relocation')
abi.require(not any(s['name'] == 'cleanup_module' for s in module.symbols),
            'resident until guest shutdown; no unsafe unwind')
print(json.dumps({
    'scope': 'sole kernel public sender; UDATE with opt-in guarded Backup PCI fixture, not CP firmware or runtime proof',
    'backup_default_off': True,
    'size': len(module.raw),
    'sha256': hashlib.sha256(module.raw).hexdigest(),
    'imports': sorted(imports),
    'resident': True,
}, indent=2))
