"""Owned text/ELF-placeholder fixtures for host tests; never used as camera evidence."""
from pathlib import Path
import json
import writer_origin_trace as trace

encode = trace.wire
B = 0x40000000


def writer_row(site, value, ordinal, sequence, global_sequence):
    index = trace.SITES.index(site)
    row = dict(kind='shutter_writer', site=site, vcpu='0x0', ordinal=hex(ordinal),
        writer_sequence=hex(sequence), observation_sequence=hex(global_sequence),
        callback_phase='before_instruction', event_pc=hex(B + trace.base.OFFSETS[index]),
        gdb_pc_raw='0x42767978', candidate_base=hex(B), anchor_length='0xc',
        x0_raw=hex(value), input_w0=hex(value), x1_raw='0x47e5d000' if index else '0x0',
        x30_raw='0x40200014', cpsr_raw='0x400003c5', cpsr_m='0x5', context_mode='other_aarch64',
        expected_destination='0x47e5d570', destination_base_checked=hex(int(index != 0)), api_ok='0x1',
        store_retirement_verified='0x0', memory_readback_verified='0x0', **trace.base.SCOPE)
    for name in trace.base.REGISTERS:
        row.update({name + '_read_length': '0x4' if name == 'cpsr' else '0x8', name + '_api_ok': '0x1'})
    for name in trace.base.OPTIONALS:
        row.update({name + '_available': '0x1', name + '_raw': '0x47fff000' if name == 'sp' else '0x0',
                    name + '_read_length': '0x8', name + '_api_ok': '0x1'})
    return row


def origin_row(site, value, ordinal, sequence, global_sequence):
    index = trace.ORIGINS.index(site)
    row = dict(kind='writer_origin', site=site, vcpu='0x0', ordinal=hex(ordinal),
        origin_sequence=hex(sequence), observation_sequence=hex(global_sequence),
        callback_phase='before_instruction', event_pc=hex(B + trace.ORIGIN_OFFSETS[index]),
        gdb_pc_raw=hex(B + trace.ORIGIN_OFFSETS[index]), candidate_base=hex(B),
        anchor_length=hex(trace.ORIGIN_LENGTHS[index]), selector_u32='0x17c', x0_raw='0x17c',
        x1_raw=hex(value), x2_raw=hex(int(ordinal == 2)), x3_raw=hex(ordinal + 2),
        x4_raw=hex(ordinal + 9), x5_raw='0x0', x30_raw='0x40200014', cpsr_raw='0x400003c5',
        cpsr_m='0x5', context_mode='other_aarch64', api_ok='0x1', invocation_pairing_verified='0x0',
        store_retirement_verified='0x0', memory_readback_verified='0x0', **trace.base.SCOPE)
    for name in trace.ORIGIN_REGISTERS:
        row.update({name + '_read_length': '0x4' if name == 'cpsr' else '0x8', name + '_api_ok': '0x1'})
    for name in trace.base.OPTIONALS:
        row.update({name + '_available': '0x1', name + '_raw': '0x47fff000' if name == 'sp' else '0x0',
                    name + '_read_length': '0x8', name + '_api_ok': '0x1'})
    return row


def terminal(writer_count, origin_count, origin_mask):
    row = dict(kind='end', stop='none', ambiguous='0x0', candidate_found=hex(int(writer_count != 0)),
        candidate_base=hex(B if writer_count else 0), conflicting_base='0x0',
        anchor_seen_mask='0x7' if writer_count else '0x0', writer_sequence=hex(writer_count),
        fault_lines='0x0', faults='0x0', suppressed_faults='0x0', close_result='unknown',
        origin_base=hex(B if origin_mask else 0), origin_anchor_mask=hex(origin_mask),
        origin_sequence=hex(origin_count), observation_sequence=hex(writer_count + origin_count), **trace.base.SCOPE)
    for index in range(3):
        row.update({f'site{index}_records': hex(writer_count // 3), f'site{index}_suppressed': '0x0'})
    for index in range(2):
        row.update({f'origin{index}_records': hex(origin_count // (2 if origin_mask == 3 else 1)
                   if origin_mask & (1 << index) else 0), f'origin{index}_suppressed': '0x0',
                   f'origin{index}_skipped': '0x0'})
    return row


def fixture_rows():
    return [dict(trace.BEGIN), *(writer_row(site, 1, 1, index + 1, index + 1)
            for index, site in enumerate(trace.SITES)), terminal(3, 0, 0)]


def case_rows(case):
    rows = [dict(trace.BEGIN)]
    writers = origins = 0
    mask = 0 if case == 'short-tb' else 2 if case == 'origin-mutation' else 3
    for ordinal, value in enumerate((1, 0, 0xffffffff), 1):
        for index, site in enumerate(trace.ORIGINS):
            if mask & (1 << index):
                origins += 1
                rows.append(origin_row(site, value, ordinal, origins, len(rows)))
        if case not in ('equivalent-setter-mutation', 'short-tb'):
            for site in trace.SITES:
                writers += 1
                rows.append(writer_row(site, value, ordinal, writers, len(rows)))
    return [*rows, terminal(writers, origins, mask)]


def seed_evidence(root):
    import writer_origin_bundle as bundle
    root = Path(root)
    root.mkdir()
    commands = []
    for case in ('original', 'equivalent-setter-mutation', 'origin-mutation', 'short-tb'):
        folder = root / case
        folder.mkdir()
        raw = encode(case_rows(case))
        observed = trace.parse_trace(raw)
        primary = b'HOST_TEST primary trace placeholder, never used as original evidence\n'
        console = b'ORIGIN_V2_CPU_READBACK_PASS values=1,0,ffffffff flags=0,1,0\n'
        elf = b'self-owned ELF fixture placeholder: ' + case.encode()
        for name, value in (('readonly-shutter-writer.log', raw), ('readonly-scope-trace.log', primary),
                            ('console.bin', console), ('fixture.elf', elf)):
            (folder / name).write_bytes(value)
        writers, origins = len(observed['events']), len(observed['origins'])
        result = dict(CPU_readback_verified=True, writer_callbacks=writers, origin_callbacks=origins,
            writer_trace_sha256=bundle.digest(raw), primary_trace_sha256=bundle.digest(primary),
            console_sha256=bundle.digest(console), observed=observed, capture_verified=False)
        (folder / 'content-result.json').write_text(json.dumps(result))
        commands.append(dict(case=case, qemu_sha256=bundle.QEMU_SHA256, plugin_sha256='a' * 64,
            primary_sha256='c8ad5719d5620b65451bfe09a0d0a0f6c59ca527f1876ba525c29f873aa9d2a0',
            returncode=0, timed_out=False, signals_sent=0, QMP_calls=0, CPU_readback_verified=True,
            writer_callbacks=writers, origin_callbacks=origins, elf_sha256=bundle.digest(elf)))
    manifest = dict(status='PASS_SELF_OWNED_WRITER_ORIGIN_V2_FOUR_ACTUAL_QEMU_CASES_NOT_SONY_RUNTIME',
        returncode=0, QEMU_actual_API_run=True, Sony_guest_run=False, normal_writer_runtime_observed=False,
        AP_identity_verified=False, invocation_pairing_verified=False, store_retirement_verified=False,
        capture_verified=False, physical_asic_compatibility_verified=False, library_sha256='a' * 64, commands=commands)
    path = root / 'terminal.json'
    path.write_text(json.dumps(manifest))
    return path, manifest
