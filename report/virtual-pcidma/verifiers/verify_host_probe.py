#!/usr/bin/env python3
"""Original host registration/probe/notify/scan ordering; no live enable claim."""
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

HERE=Path(__file__).resolve().parent
KERNEL=HERE.parents[2]/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
BASE=0xffffff8008080000
SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
PINS={
    0x5c8d20:'adrp x0, #0x628000', 0x5c8d28:'add x0, x0, #0x5b0',
    0x5c8d2c:'bl #0x281b88',
    0x249f44:'str x1, [x24, #0xb0]', 0x249f4c:'bl #0x247a30',
    0x247d88:'ldr x0, [x20, #0xb0]', 0x247d8c:'ldr x1, [x0, #0x20]',
    0x247d90:'cbz x1, #0x247da0', 0x247d98:'blr x1',
    0x247d9c:'cbnz w0, #0x247df8',
    0x24a538:'mov w1, #0', 0x24a53c:'bl #0x248610',
    0x24a544:'bl #0x248110', 0x24a560:'cbz x0, #0x24a574',
    0x24a570:'cbnz x0, #0x24a5b8',
    0x24a578:'cbnz w0, #0x24a590', 0x24a580:'mov w1, #1',
    0x24a584:'bl #0x2469b8', 0x24a58c:'bl #0x2467b0',
    0x24a590:'mov x0, x19', 0x24a594:'bl #0x2479b0',
    0x24a598:'mov w0, w21', 0x24a59c:'mov w1, #1',
    0x24a5a0:'bl #0x31de10', 0x24a5a8:'mov w0, #0',
    0x2467cc:'mov w19, #0xa', 0x2467dc:'bl #0x246768',
    0x2467e0:'cbnz w0, #0x246820', 0x2467ec:'bl #0x422dc0',
    0x2467f0:'subs w19, w19, #1', 0x2467f4:'b.ne #0x2467d8',
    0x246808:'mov w0, #-0x6e',
    0x247f38:'bl #0x229060', 0x247f44:'cbz x0, #0x247df0',
    0x247f68:'bl #0x235b10', 0x247f70:'bl #0x235d38',
    0x247f98:'bl #0x226250',
    0x30bf84:'bl #0x308b70', 0x30bf88:'tst w0, #0xff',
    0x30bf8c:'b.eq #0x30c010', 0x30c010:'mov x19, #0',
    0x30c018:'mov x0, x19',
}
EXPORTS=(
    (0x584db0,0x281b88,0x59ea81,'__platform_driver_register'),
    (0x57f850,0x235b10,0x59c269,'pci_bus_size_bridges'),
    (0x57f7b0,0x235d38,0x59c250,'pci_bus_assign_resources'),
    (0x57f790,0x226250,0x59b694,'pci_bus_add_devices'),
    (0x57ee90,0x308b70,0x5a2fc0,'of_device_is_available'),
    (0x57fe40,0x2a2230,0x5a02e7,'pcidma_connect'),
)


def main():
    data=KERNEL.read_bytes()
    assert len(data)==6610952 and hashlib.sha256(data).hexdigest()==SHA
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    for offset,expected in PINS.items():
        ins=list(decoder.disasm(data[offset:offset+4],offset))
        assert len(ins)==1 and (ins[0].mnemonic+' '+ins[0].op_str).rstrip()==expected,hex(offset)
    def pointer(offset,target):assert struct.unpack_from('<Q',data,offset)[0]==BASE+target
    def string(offset,value):
        encoded=value.encode()+b'\0'; assert data[offset:offset+len(encoded)]==encoded
    pointer(0x6285b0,0x249770); pointer(0x6285d8,0x547040); string(0x547040,'dw-pcie')
    pointer(0x628600,0x460030); string(0x460070,'snps,dw-pcie')
    pointer(0x45ff88,0x24a508)
    for record,function,nameoffset,name in EXPORTS:
        pointer(record,function); pointer(record+8,nameoffset); string(nameoffset,name)
    # Pin the lack of return checking immediately after the failed-link helper:
    # MOV x0,x19 overwrites its w0 result before the next call and notify.
    after=list(decoder.disasm(data[0x24a590:0x24a5a4],0x24a590))
    assert [i.mnemonic for i in after]==['mov','bl','mov','mov','bl']
    result={'scope':'original static registration/order and OF gate; not current enumeration or device activation',
            'kernel_sha256':SHA,'instruction_pins':len(PINS),'export_names':[v[3] for v in EXPORTS],
            'probe':'0x249770','host_init_hook':'0x24a508',
            'notification_precedes_scan':True,'link_timeout_return_unchecked_in_hook':True,
            'disabled_node_skips_platform_device':True,'host_enable_producer_verified':False,
            'runtime_verified':False}
    (HERE/'host-probe-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(f'PASS original SHA, {len(PINS)} instruction pins, 6 exports, driver/OF/host-ops pointers')
    print('PASS static ordering: notify before scan/resource assignment/device publication; failed-link result not checked')
    print('PASS OF unavailable -> no platform device; real activation/PCI endpoint remains UNVERIFIED')


if __name__=='__main__':main()
