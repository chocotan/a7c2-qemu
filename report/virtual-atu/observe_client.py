#!/usr/bin/env python3
"""Owned original-ATU diagnostic observation; no CP/capture acceptance."""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def parse_client(data):
    clean = data.replace(b'\r', b'')
    maps = re.findall(rb'ATU_CLIENT_MAP_RC=(-?\d+) phys=([0-9a-f]+) bytes=100000\b', clean)
    mapped = maps[0] if len(maps) == 1 else None
    slot = int(mapped[0]) if mapped else None
    physical = int(mapped[1], 16) if mapped else None
    unmaps = re.findall(rb'ATU_CLIENT_UNMAP_RC=(-?\d+) slot=(-?\d+)\b', clean)
    controls = re.findall(rb'ATU_CLIENT_CTRL_AFTER_UNMAP=([0-9a-f]{8}) slot=(-?\d+)\b', clean)
    uncertain = b'ATU_CLIENT_OWNER_UNCERTAIN:' in clean
    release = bool(mapped and 0 <= slot <= 7 and len(unmaps) == len(controls) == 1
        and tuple(map(int, unmaps[0])) == (0, slot)
        and int(controls[0][1]) == slot and not int(controls[0][0], 16)&0x80000000
        and b'ATU_CLIENT_OWNER_RELEASED:' in clean and not uncertain)
    refused = bool(mapped and slot < 0 and b'ATU_CLIENT_NOT_MAPPED:' in clean and not uncertain)
    loader_rejected = bool(b'ATU_CLIENT_BEGIN:' not in clean and (
        b'OWNED_ATU_CLIENT_IDENTITY_REJECTED' in clean or
        re.search(rb'^OWNED_ATU_CLIENT_LOAD_RC=[1-9]\d*$', clean, re.M)))
    loaded = bool(b'\nOWNED_ATU_CLIENT_LOAD_RC=0\n' in clean and
        re.search(rb'^sony_atu_client\s+\d+\s+\d+\s+\S+\s+Live\b', clean, re.M))
    markers = (b'ATU_CLIENT_PEER_INITIALIZED:', b'ATU_CLIENT_APERTURE_READ_PASS:',
               b'ATU_CLIENT_APERTURE_WRITTEN:', b'ATU_CLIENT_DATA_PASS:', b'ATU_CLIENT_PASS:')
    data_pass = bool(loaded and release and physical is not None and
        0xc0000000 <= physical <= 0xe0000000-0x100000 and physical%0x100000 == 0
        and all(marker in clean for marker in markers) and b'ATU_CLIENT_FAIL:' not in clean)
    return {'atu_client_loaded':loaded, 'atu_owner_uncertain':not (release or refused or loader_rejected),
            'original_atu_client_pass':data_pass, 'atu_slot':slot,
            'atu_aperture_physical':hex(physical) if physical is not None else None,
            'atu_slot_release_verified':release}


def verify_peer_page(data):
    expected = bytes(((i-16)*53+0x91)&255 if 16 <= i < 272 else 0xa5 for i in range(4096))
    if data != expected:
        raise ValueError('Actual TESTPCI peer page differs in data, guards or full length')
    return hashlib.sha256(data).hexdigest()


def run_client(qmp, serial_command, run, proc, console, result):
    client = HERE/'original-client'
    checked = subprocess.run([sys.executable, '-B', str(client/'check_client.py')],
                             check=True, capture_output=True, text=True)
    (run/'atu-client-host-check.json').write_text(checked.stdout)
    payload = (client/'sony_atu_client.ko').read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert digest == json.loads(checked.stdout)['sha256']
    result['atu_client_sha256'] = digest
    # Set before admitting any ordinary insmod. Missing retirement must retain
    # the VM, control streams and admission, just as an unresolved DMA owner.
    result['atu_owner_uncertain'] = True
    command = ('cat > /tmp/sony_atu_client.b64 <<\'OWNED_ATU_CLIENT_B64_END\'\n'
        +base64.encodebytes(payload).decode('ascii')+'OWNED_ATU_CLIENT_B64_END\n'
        '/usr/bin/openssl base64 -d -in /tmp/sony_atu_client.b64 -out /tmp/sony_atu_client.ko\n'
        '/usr/bin/openssl dgst -sha256 /tmp/sony_atu_client.ko > /tmp/atu-client.sha\ncat /tmp/atu-client.sha\n'
        'if grep -q "'+digest+'$" /tmp/atu-client.sha; then\n'
        'insmod /tmp/sony_atu_client.ko\necho OWNED_ATU_CLIENT_LOAD_RC=$?\n'
        'grep "^sony_atu_client " /proc/modules\n'
        'else echo OWNED_ATU_CLIENT_IDENTITY_REJECTED; fi\ntrue')
    observed = serial_command(proc, console, command, timeout=30)
    (run/'original-atu-client.txt').write_bytes(observed)
    result.update(parse_client(observed))
    result['ok'] = result['ok'] and result['original_atu_client_pass']
    if not result['original_atu_client_pass']:
        return
    qmp('stop')
    try:
        assert not qmp('query-status')['running']
        qmp('pmemsave', {'val':0x600000000, 'size':4096, 'filename':'/out/atu-peer-page.bin'})
        address = 0xf7300004+result['atu_slot']*0x200
        text = qmp('human-monitor-command', {'command-line':f'xp /1wx 0x{address:x}'})
        (run/'atu-unmapped-control-monitor.txt').write_text(text)
        values = re.findall(r'0x([0-9a-fA-F]+)', text.split(':', 1)[-1])
        assert len(values) == 1 and not int(values[0], 16)&0x80000000
        result['atu_qmp_control_disabled'] = True
    finally:
        qmp('cont')
    token = 'ATU_CLIENT_CPU_RESUMED_'+run.name.replace('-', '_')
    resumed = serial_command(proc, console, 'echo '+token, timeout=15)
    (run/'atu-client-cpu-resumed.txt').write_bytes(resumed)
    assert ('\n'+token+'\n').encode() in resumed.replace(b'\r', b'')
    result['atu_cpu_resumed_guest_output'] = True
    result['atu_peer_page_sha256'] = verify_peer_page((run/'output/atu-peer-page.bin').read_bytes())
    result['atu_independent_peer_page_verified'] = True
