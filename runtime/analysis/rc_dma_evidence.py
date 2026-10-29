"""Correlate experimental RC enable observations with MMIO writes, not pixels.

Usage: python3 rc_dma_evidence.py menu-runs/run-NAME
Supports single-chunk format 0/1 -> 0 row contracts, not pixel interpretation.
"""
import json
from pathlib import Path
import re
import struct
import sys

from resize_mmio_watch import ENGINE_BANKS, KERNEL_BASE


def correlate(events, console):
    snapshots, registers = [], {}
    for line in console.splitlines():
        match = re.fullmatch(r'(?:REGFILE_WR|SONY_RC_MMIO_WR) (0x[0-9a-f]+) = (0x[0-9a-f]+)', line.strip())
        if not match:
            continue
        address, value = (int(item, 16) for item in match.groups())
        registers[address] = value
        if address-0x2000 in ENGINE_BANKS and value == 1:
            snapshots.append((address-0x2000, registers.copy()))

    reports, submitted, gate = [], None, None
    for event in events:
        kind = event['kind']
        if kind == 'resize_submit':
            submitted, gate = event, None
        elif kind == 'resize_enable_gate':
            gate = event
        elif kind == 'resize_mmio_enable':
            if not submitted or not gate or event.get('original_entry_verified') is not True:
                raise ValueError('Enable lacks an original submit/gate')
            if (submitted.get('original_entry_verified') is not True or
                    gate.get('original_entry_verified') is not True or
                    gate['setup_status'] != 0 or gate['enable_mode'] not in (1,2)):
                raise ValueError('Original execution gate not verified')
            base = event['bank0_physical']
            if (base not in ENGINE_BANKS or event['bank1_physical'] != base+0x2000 or
                    int(gate['context_pointer'],16) != event['expected_context'] or
                    event['expected_context'] != KERNEL_BASE+0xb1ff50+ENGINE_BANKS.index(base)*0x60):
                raise ValueError('RC bank/context mismatch')
            index = len(reports)
            if index >= len(snapshots) or snapshots[index][0] != base:
                raise ValueError('Original enable entry has no matching MMIO enable write')
            regs = snapshots[index][1]
            p = bytes.fromhex(gate['parameter_hex'])
            if len(p) != 0x1b4:
                raise ValueError('RC parameter snapshot length differs')
            u32 = lambda offset: struct.unpack_from('<I',p,offset)[0]
            input_format = u32(0x84)
            if input_format not in (0,1) or any(u32(offset) for offset in (0x88,0x8c,0x100,0x104,0x108)):
                raise ValueError('Unsupported RC format/depth/address mode')
            if u32(0x174) != 0 or u32(0x178) != 1:
                raise ValueError('Only the observed single-chunk contract is supported')
            channels = {}
            for name, channel, bpp, address_offset in (('input',0x1200,2 if input_format == 0 else 1,0x18),('output',0x1280,2,0xa0)):
                width,height = submitted[name+'_geometry'][:2]
                pa = submitted[name+'_address']
                parameter_pa = struct.unpack_from('<Q',p,address_offset)[0]
                # Original raw table maps [0x400000000,0x600000000) to bus [0,0x200000000).
                if not 0x400000000 <= pa < 0x600000000 or pa != parameter_pa:
                    raise ValueError('DMA physical address differs from the original request')
                d = base+channel
                expected = {d:3, d+0x18:(pa-0x400000000)>>32<<8,
                            d+0x20:(pa-0x400000000)&0xffffffff,
                            d+0x24:width*bpp,d+0x28:0,d+0x2c:height-1,
                            d+0x30:0,d+0x34:0}
                if width <= 0 or height <= 0 or any(regs.get(k) != v for k,v in expected.items()):
                    raise ValueError('DMA channel registers differ from the observed row contract')
                if width*height*bpp > submitted[name+'_bytes']:
                    raise ValueError('DMA rectangle exceeds submitted capacity')
                channels[name] = dict(physical_address=hex(pa),bus_address=hex(pa-0x400000000),
                                      row_bytes=width*bpp,rows=height,
                                      rectangle_bytes=width*height*bpp,
                                      submitted_capacity=submitted[name+'_bytes'])
            if regs.get(base+0x1008) != 0xff:
                raise ValueError('Both DMA channel interrupt masks not enabled')
            if regs.get(base+0x2028) != (submitted['input_geometry'][0]<<16|submitted['input_geometry'][1]):
                raise ValueError('RC input geometry register differs')
            if regs.get(base+0x202c) != (submitted['output_geometry'][0]<<16|submitted['output_geometry'][1]):
                raise ValueError('RC output geometry register differs')
            reports.append(dict(bank0=hex(base),bank1=hex(base+0x2000),channels=channels,
                input_format=input_format,output_format=0,
                same_format_and_canvas_observed=input_format == 0 and
                    submitted['input_geometry'][:2] == submitted['output_geometry'][:2],
                identity_operation_verified=False))
            submitted,gate = None,None
    if not reports or len(reports) != len(snapshots):
        raise ValueError('Unmatched RC enable entries/writes')
    return dict(rc_enable_and_dma_configuration_verified=True,operations=reports,
                pixel_processing_verified=False,completion_verified=False,
                limitation='Row/address contract only; component packing, pixels and IRQ completion unverified')


if __name__ == '__main__':
    run = Path(sys.argv[1])
    events = [json.loads(line) for line in (run/'resize-watch-events.jsonl').read_text().splitlines()]
    console=(run/'console.log').read_text(errors='replace')
    trace=(run/'boot-trace.log').read_text(errors='replace') if (run/'boot-trace.log').exists() else ''
    print(json.dumps(correlate(events,console+'\n'+trace),indent=2))
