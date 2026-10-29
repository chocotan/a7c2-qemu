#!/usr/bin/env python3
"""Original CP init table and executable ARM dispatch; no runtime gate values."""
import hashlib
import json
import struct
from pathlib import Path

CP = Path(__file__).resolve().parents[2]/'runtime/analysis/menu-root/cp/cpapp-b.bin'
BASE = 0x108000


def main():
    raw = CP.read_bytes()
    assert len(raw) == 18090880
    assert hashlib.sha256(raw).hexdigest() == 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'

    def read(address, length):
        start = address-BASE
        assert 0 <= start <= len(raw)-length
        return raw[start:start+length]

    def pin(address, value):
        expected = bytes.fromhex(value)
        assert read(address, len(expected)) == expected, hex(address)

    count, = struct.unpack('<I', read(0xeb56dc, 4))
    assert count == 14
    names = ('TOPPERS_KERNEL', 'USER_TSK_INIT1', 'PCIDMA_INIT', 'OSAL_UIPC_INIT',
             'SNDCMD_INIT', 'PCIEIF_INIT', 'OSAL_UTIMER_INIT', 'BACKUP_INIT',
             'OSAL_ULOGIO_INIT', 'SENSER_SLAVE_INIT', 'KBD_INIT', 'UDATE_INIT',
             'USER_TSK_DRV_INIT', 'USER_TSK_INIT2')
    table = []
    for index, expected in enumerate(names):
        pointer, = struct.unpack('<I', read(0xeb56e0+4*index, 4))
        assert read(pointer, len(expected)+1) == expected.encode()+b'\0'
        flags, argument, function, mode_mask, id_mask = struct.unpack('<5I', read(0xeb55c4+20*index, 20))
        table.append({'index': index, 'name': expected, 'flags': flags,
                      'argument': argument, 'function_pointer': hex(function),
                      'mode_mask': hex(mode_mask), 'id_mask': hex(id_mask)})
    assert struct.unpack('<5I', read(0xeb55c4+7*20, 20)) == (0, 0, 0x55dca5, 0xfffffffe, 1)
    assert table[0]['function_pointer'] == '0x601c48'  # ARM pointer is valid too.
    pin(0x6349b8, '0b018be0002096e50130a0e300a187e0')  # table + index*20
    pin(0x6349c8, '0c109ae5130211e1f400000a')          # mode-mask gate
    pin(0x634d28, '58109de510009ae50120a0e3011041e2120110e11900000a')
    pin(0x634d74, '03009ae931ff2fe1')  # ARM LDMIB {r0,r1}; BLX r1
    print(json.dumps({'scope': 'static table, labels, gates and ARM dispatch only',
                      'table_base': '0xeb55c4', 'record_bytes': 20, 'records': table,
                      'backup_callback_field': '0xeb5658 (record7+8, not record start)',
                      'actual_mode_id_or_startup_execution_verified': False,
                      'initial_0x04000000_contents_verified': False,
                      'capture_verified': False}, indent=2))


if __name__ == '__main__':
    main()
