"""Bounded, opaque SA2 program/MMU readback; no readiness or completion changes."""
import hashlib
import json
import re


def request(console):
    registers={}
    for address,value in re.findall(r'(?:REGFILE_WR|SONY_SA_MMIO_WR) (0xf317[0-9a-f]{4}) = (0x[0-9a-f]+)(?=\s|$)',console):
        registers[int(address,16)-0xf3170000]=int(value,16)
    if not all(registers.get(offset,0)&1 for offset in (0,4)):
        return None
    if not all(offset in registers for offset in (0x30,0x60,0x110,0x114)):
        raise ValueError('SA2 launch has incomplete program/MMU register evidence')
    if registers[0x60]!=0:raise ValueError('Only the observed low program-address window is captured')
    program=registers[0x30]
    first,second=registers[0x110]<<2,registers[0x114]<<2
    if not all(0<address<0x100000000 for address in (program,first,second)):
        raise ValueError('SA2 capture address exceeds the original first conversion window')
    # Slot roles are operation-dependent; the observed slot0 is parameters,
    # while slot1 contains builder-format translation records.
    spans=dict(program=(0x400000000+(program&~0xfff),0x2000),
               slot0=(0x400000000+first,0x200),slot1=(0x400000000+second,0x200))
    if any(address+size>0x500000000 for address,size in spans.values()):
        raise ValueError('SA2 opaque readback exceeds the conversion window')
    return dict(program_entry_physical_address=hex(0x400000000+program),
        register_values={hex(offset):hex(registers[offset]) for offset in (0,4,0x30,0x60,0x110,0x114)},
        regions={name:dict(physical_address=address,bytes=size) for name,(address,size) in spans.items()})


def capture(qmp,run,console):
    trace=run/'boot-trace.log'
    dedicated=trace.read_text(errors='replace') if trace.exists() else ''
    decoded=request(dedicated if 'SONY_SA_MMIO_WR ' in dedicated else console)
    if decoded is None:return None
    target=run/'sa2-job-readback.json'
    if target.exists():
        previous=json.loads(target.read_text())
        if previous['request']!=decoded:raise ValueError('SA2 job identity changed after bounded snapshot')
        return previous
    files={}
    for name,region in decoded['regions'].items():
        filename=f'sa2-{name}.bin'
        qmp('pmemsave',dict(val=region['physical_address'],size=region['bytes'],filename='/out/'+filename))
        raw=(run/filename).read_bytes()
        if len(raw)!=region['bytes']:raise ValueError('Short SA2 program/MMU readback')
        files[name]=dict(file=filename,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    result=dict(observations_only=True,request=decoded,files=files,
        program_region_is_partial=True,slot_roles_verified=False,mmu_record_count_verified=False,
        snapshot_consistency_verified=False,payload_address_decoded=False,
        program_execution_verified=False,completion_verified=False)
    target.write_text(json.dumps(result,indent=2)+'\n')
    return result
