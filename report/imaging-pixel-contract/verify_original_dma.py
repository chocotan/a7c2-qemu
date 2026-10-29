#!/usr/bin/env python3
"""Independently accept one original-driver DMA run; reject abort even if bytes match."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verify(run):
    result = json.loads((run/'result.json').read_text())
    require(result.get('ok') and result.get('original_mmio_snapshot_verified'), 'run/MMIO failed')
    require(result.get('original_dma_client_pass') and result.get('dma_executed'), 'client did not pass')
    require(result.get('dma_callback_fields') == [1, 0, 1, 0, 1], 'callback/status/cookie/submit/bytes failed')
    require(not result.get('dma_owner_uncertain'), 'request owner uncertain')
    require(result.get('vm_exited') and result.get('cpu_resumed_guest_output'), 'CPU recovery/normal exit missing')
    require(not result.get('camera_app_started') and not result.get('sd_attached'), 'unexpected scope')
    require(result['module_sha256'] == '9ba277f011b3ddcfbc3fa610d22b63ae3be1e0ded385b42ff2c7cf0a83e520ab', 'provider identity')
    client = (run/'original-dma-client.txt').read_bytes().replace(b'\r', b'')
    digest = result['dma_client_sha256'].encode()
    require(re.search(rb'^SHA(?:2-256|256)\(/tmp/sony_dma_probe\.ko\)=\s*'+digest+rb'$', client, re.M), 'actual guest client digest absent')
    addresses = [int(value, 16) for value in result['dma_buffer_addresses']]
    require(len(set(addresses)) == 3 and len(addresses) == 3, 'independent pages required')
    require(all(0x400000000 <= a <= 0x4fdfff000 and not a & 4095 for a in addresses), 'physical page domain')
    pages = {name:(run/'output'/(name+'-page.bin')).read_bytes()
             for name in ('source', 'destination', 'descriptor')}
    require(all(len(p) == 4096 for p in pages.values()), 'complete independent QMP page exports required')
    payload = bytes((i*29+7)&255 for i in range(256))
    require(pages['source'] == b'\x5a'*16+payload+b'\x5a'*(4096-272), 'source/page guards changed')
    require(pages['destination'] == b'\xa5'*16+payload+b'\xa5'*(4096-272), 'destination/page guards mismatch')
    descriptor = struct.pack('<3I', 256, (addresses[1]+16)&0xffffffff, (addresses[2]+16)&0xffffffff)
    require(pages['descriptor'] == descriptor+b'\0'*(4096-12), 'original consumed descriptor/guard mismatch')
    registers = (run/'post-dma-registers.txt').read_bytes().replace(b'\r', b'')
    normal = re.search(rb'^\s*112:\s+(\d+).*\b330d-0_0\s*$', registers, re.M)
    abort = re.search(rb'^\s*144:\s+(\d+).*\b330d-0_abort\s*$', registers, re.M)
    require(normal and int(normal[1]) >= 1 and abort and int(abort[1]) == 0, 'normal/abort IRQ evidence')
    trace = (run/'output/boot-trace.log').read_bytes()
    require(not re.search(rb'^pl330_fault(?:\s|_abort)', trace, re.M), 'PL330 fault trace present')
    return {'scope':'one original DMA330 request, 256 bytes; no camera firmware frame consumption',
            'status':'PASS', 'callback_fields':result['dma_callback_fields'],
            'normal_irq_count':int(normal[1]), 'abort_irq_count':int(abort[1]),
            'page_sha256':{name:hashlib.sha256(value).hexdigest() for name,value in pages.items()},
            'candidate_sha256':result['candidate_binary_sha256'], 'provider_sha256':result['module_sha256'],
            'client_sha256':result['dma_client_sha256'], 'pages_retained_by_resident_client_until_vm_exit':True,
            'capture_verified':False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    evidence = verify(args.run)
    (args.run/'main-original-dma-review.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(evidence, indent=2))
