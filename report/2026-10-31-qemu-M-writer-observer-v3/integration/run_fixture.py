#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""NOT_RUN v3 fixture sources; importing this module never starts a process.

Only the parent's unified batch may compile/run the seven self-owned cases after
integrating the separate direct v3 reader and freezing its independent fixture8.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys

BASE = 0x40000000
ENTRY = BASE + 0x2E068CC
LRS = (BASE + 0x209EE80, BASE + 0x209EE88, BASE + 0x209EEA4)
HEADER = b"SCOPE_FIXTURE_V1\n"
RECORDS_MARKER = b"\nSCOPE_FIXTURE_RECORDS_OK\n"
ANCHOR = bytes.fromhex("fd7bb9a981d102d021e01791fd030091f76303a9b7830191")
CODE_SECTIONS = (".boot", ".callers", ".wrongcaller", ".observed")
GPRS = ('x0', 'x19', 'x20', 'x21', 'x23', 'x24', 'x29', 'x30')
PRODUCER_ENTRY = BASE + 0x276E710
PRODUCER2_ENTRY = BASE + 0x2845430
PRODUCER_X1 = BASE + 0x7E6A4D8
PRODUCER_TARGETS = BASE + 0x7E6A7C0
PRODUCER_ANCHOR = bytes.fromhex("01b702d0216013912168409120f002b920f802b9c0035fd6")
# Parent-pinned cached second24B; no original ELF/corpus is consumed here.
PRODUCER2_ANCHOR = bytes.fromhex("41b002f0216013912168409120f002b920f802b9c0035fd6")
PRODUCER2_SHA256 = 'f7509e03ad3d873673ad63d874b05a50e5141fdf2b82a940b153bc84ef661b19'
PRODUCER_HEADER = b"SCOPE_FIXTURE_V3_PRODUCERS\n"
PRODUCER_TRAILER = b"\nSCOPE_FIXTURE_OK calls=51 lanes=17,17,17 producer_calls=17,17\n"
PRODUCER_INPUTS = (0xFFFF000100000000, 0xFFFF0001FFFFFFFF,
    0x1234567880000000, 0x876543217FFFFFFF, 0xDEADBEEF00000001,
    0x01020304FFFFFFFE, 0x11223344DEAD0007, 0xAABBCCDD01000090,
    *(0xFFFF000100000000 | number for number in range(8, 16)), 0x13572468FFFFFFFF)
STORE_SEED = struct.pack('<4Q', 0x1122334455667788, 0x99AABBCC13572468,
                         0x0123456789ABCDEF, 0xFEDCBA9876543210)
PRODUCER_FRAME_BYTES = 2 * 432 + 2 * 32
PROFILE = 'qemu-readonly-scope-v3'
SCHEMA = 'readonly_scope_v3'
COMPONENT = '2026-10-31-qemu-M-writer-observer-v3'
PACKAGE_COMPONENT = 'a7c2-qemu'
API_CASES = ('anchor', 'one_byte_mutation', 'wrong_lr_only', 'producer',
             'producer_reverse_order', 'producer_corrupt', 'producer_short_tb')
API_ENV = tuple('A7C2_SCOPE_V3_TEST_' + suffix for suffix in
                ('QEMU', 'PLUGIN', 'OUTPUT', 'SCHEMA', 'RECEIPT', 'FIXTURE_SOURCES'))
FIXTURE_SOURCES = ('fixture.S', 'link.ld', 'run_fixture.py', 'test_fixture_driver.py',
                   'test_actual_scope_plugin.py', 'scope_trace_checks.py',
                   'test_scope_trace_checks.py', 'scope_trace_checks_v3.py')
RUNTIME_SOURCES = ('scope-observer.c', 'late-sites.inc', 'build-plugin.sh',
    'log-schema-v3.json', 'source-contract-v3.json', 'check_run_context_v3.py',
    'check_run_context.py', 'integration/scope_trace_checks_v3.py', 'integration/scope_trace_checks.py')
FIXTURE_SOURCE_NAMES = frozenset('integration/' + name for name in FIXTURE_SOURCES)
LIMIT = 2 * 1024 * 1024
SOURCE = Path(__file__).resolve().parent
# Legacy reader regressions use the original strict parser through this attribute.
TRACE_SPEC = importlib.util.spec_from_file_location('selfowned_scope_trace_checks', SOURCE / 'scope_trace_checks.py')
trace_checks = importlib.util.module_from_spec(TRACE_SPEC)
TRACE_SPEC.loader.exec_module(trace_checks)


class FixtureError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise FixtureError(message)


def ordinary_file(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink() and
            stat.S_ISREG(path.stat().st_mode), f"missing absolute ordinary artifact: {path}")
    return path


def file_stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def sha256(path):
    path = ordinary_file(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    require(file_stamp(before) == file_stamp(path.stat()), f"artifact changed while hashing: {path}")
    return digest.hexdigest()


def read_small(path):
    path = ordinary_file(path)
    before = path.stat()
    require(before.st_size <= LIMIT, f"artifact exceeds {LIMIT} bytes: {path}")
    raw = path.read_bytes()
    require(file_stamp(before) == file_stamp(path.stat()) and len(raw) == before.st_size,
            f"artifact changed while reading: {path}")
    return raw


def private_root():
    return SOURCE.parents[2] / "runtime/analysis/scratch/functional-M-v3-actualapi-fixture"


def validate_paths(qemu, plugin, output):
    original = [Path(value).expanduser() for value in (qemu, plugin, output)]
    require(not any(path.is_symlink() for path in original), "QEMU/plugin/output cannot be symlinks")
    qemu, plugin, output = (path.resolve() for path in original)
    require(qemu.is_file() and os.access(qemu, os.X_OK | os.R_OK), f"explicit QEMU is not readable/executable: {qemu}")
    require(plugin.is_file() and os.access(plugin, os.R_OK), f"explicit plugin is not readable: {plugin}")
    require(qemu.stat().st_size > 0 and plugin.stat().st_size > 0, "QEMU/plugin must be nonempty")
    root = private_root().resolve()
    require(output != root and root in output.parents, f"output must be a new child of {root}")
    require(not output.exists(), f"refusing to reuse output: {output}")
    return qemu, plugin, output


def validate_v3_assets(qemu, plugin, schema, receipt, *, fixture_source_sha256):
    """Bind the explicit new runtime root/exact9 and independent parent fixture8."""
    root = SOURCE.parent
    require(SOURCE.is_absolute() and SOURCE.resolve() == SOURCE and
            (root.parent.name, root.name) == ('report', COMPONENT), 'unexpected v3 runtime source root')
    paths = [Path(value).expanduser() for value in (schema, receipt)]
    require(all(path.is_absolute() and path.resolve() == path and not path.is_symlink() for path in paths),
            "schema/receipt must be explicit absolute regular files")
    schema, receipt = paths
    schema_bytes, receipt_bytes = read_small(schema), read_small(receipt)
    build = json.loads(receipt_bytes)
    require(isinstance(build, dict) and build.get('schema') == PROFILE and build.get('trace_schema') == SCHEMA and
            type(build.get('plugin_api')) is int and build['plugin_api'] == 7 and
            build.get('readonly_imports_verified') is True, "new v3 API7 build receipt required")
    require(build.get('source_root', str(root)) == str(root), 'receipt selects another source root')
    schema_digest = hashlib.sha256(schema_bytes).hexdigest()
    require(schema == root / 'log-schema-v3.json' and
            build.get('trace_schema_sha256') == schema_digest and
            not {'schema_sha256', 'log_schema_sha256', 'v3_schema_sha256'} & build.keys(),
            "new v3 schema digest differs or uses a missing/legacy/alias field")
    declaration = json.loads(schema_bytes)
    require(declaration.get('schema') == SCHEMA and declaration.get('profile') == PROFILE,
            'schema declares an unknown generation/profile')
    require(build.get('library') == str(plugin) and build.get('library_sha256') == sha256(plugin),
            "plugin differs from the new build receipt")
    require(build.get('qemu') == str(qemu) and build.get('qemu_sha256') == sha256(qemu),
            "QEMU differs from the build receipt; no candidate replacement/fallback")
    require(all(build.get(key) is False for key in
                ('runtime_verified', 'capture_verified', 'physical_asic_compatibility_verified')),
            "build receipt promotes runtime, capture or physical proof")
    sources = build.get('source_sha256')
    require(isinstance(sources, dict) and set(sources) == set(RUNTIME_SOURCES), 'runtime source closure must be exact9')
    require(isinstance(fixture_source_sha256, dict) and set(fixture_source_sha256) == FIXTURE_SOURCE_NAMES,
            'parent frozen fixture source closure differs')
    inputs = {'qemu': {'path': str(qemu), 'sha256': build['qemu_sha256']},
              'plugin': {'path': str(plugin), 'sha256': build['library_sha256']},
              'schema': {'path': str(schema), 'sha256': schema_digest},
              'receipt': {'path': str(receipt), 'sha256': hashlib.sha256(receipt_bytes).hexdigest()}}
    for prefix, closure in (('source:', sources), ('fixture-source:', fixture_source_sha256)):
        for name, digest in closure.items():
            require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'invalid source closure digest')
            original = SOURCE.parent / name
            source_bytes = read_small(original)
            require(hashlib.sha256(source_bytes).hexdigest() == digest, 'source changed after parent freeze/build: ' + name)
            inputs[prefix + name] = {'path': str(original), 'sha256': digest}
    require(sources['log-schema-v3.json'] == schema_digest and
            build.get('source_contract_sha256') == sources['source-contract-v3.json'],
            'schema/source-contract not in the same runtime closure')
    contract = json.loads(read_small(root / 'source-contract-v3.json'))
    require(contract.get('schema') == 'readonly_scope_source_contract_v3' and contract.get('profile') == PROFILE and
            contract.get('trace_schema') == SCHEMA and contract.get('trace_schema_sha256') == schema_digest and
            not {'schema_sha256', 'log_schema_sha256', 'v3_schema_sha256'} & contract.keys(),
            'source contract does not pin the actual v3 schema')
    header = SOURCE.parent.parents[1] / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
    header_bytes = read_small(header)
    require(hashlib.sha256(header_bytes).hexdigest() == build.get('qemu_header_sha256') and
            re.search(rb'^#define QEMU_PLUGIN_VERSION 7\s*$', header_bytes, re.M), 'actual API7 header differs')
    inputs['qemu_header'] = {'path': str(header), 'sha256': hashlib.sha256(header_bytes).hexdigest()}
    audit = receipt.with_name('readonly-import-audit.json')
    audit_bytes = read_small(audit)
    require(hashlib.sha256(audit_bytes).hexdigest() == build.get('readonly_import_audit_sha256'),
            'read-only import audit differs from receipt')
    inputs['readonly_import_audit'] = {'path': str(audit), 'sha256': hashlib.sha256(audit_bytes).hexdigest()}
    return inputs


def verify_fixture_snapshots(output, expected):
    """Bind both original fixture files and the exact compiler-input copies to parent ready."""
    require(isinstance(expected, dict) and set(expected) == FIXTURE_SOURCE_NAMES, 'fixture snapshot closure differs')
    snapshots = {}
    for name in FIXTURE_SOURCES:
        relative = 'integration/' + name
        original, copied = SOURCE / name, output / 'inputs' / name
        raw, staged = read_small(original), read_small(copied)
        require(hashlib.sha256(raw).hexdigest() == expected[relative] and raw == staged,
                'fixture source/snapshot changed after parent freeze: ' + relative)
        snapshots[relative] = {'source_path': str(original), 'snapshot_path': str(copied),
                               'sha256': expected[relative], 'bytes': len(staged)}
    return snapshots


def load_v3_checks():
    """Load the reader's real raw-v3 adapter; legacy trace_checks stays exported."""
    path = SOURCE / 'scope_trace_checks_v3.py'
    require(path.is_file() and not path.is_symlink(), 'integrate the separate v3 parser first')
    spec = importlib.util.spec_from_file_location('selfowned_scope_trace_checks_v3', path)
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    require(callable(getattr(checks, 'assert_scope_trace_v3', None)) and
            callable(getattr(checks, 'parse_trace', None)), 'direct v3 parser interface is missing')
    return checks


def tool(name):
    found = shutil.which(name)
    require(found is not None, f"required tool is unavailable: {name}; no skip/fallback")
    path = Path(found).resolve()
    require(Path("/usr") in path.parents, f"tool must be in the read-only /usr mount: {path}")
    return str(path)


def sandbox(output, mounts):
    command = [tool("bwrap"), "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
               "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
               "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib", "/lib64",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/in",
               "--dir", "/work", "--chdir", "/work", "--setenv", "HOME", "/tmp",
               "--setenv", "TMPDIR", "/tmp", "--setenv", "LANG", "C",
               "--setenv", "PATH", "/usr/bin:/bin",
               "--bind", str(output), "/out"]
    for host, guest in mounts:
        command += ["--ro-bind", str(host), guest]
    return command


def launch(output, relative, payload, mounts, commands, seconds, existing_log=None):
    """GNU timeout sends TERM to its own child; never signal any discovered PID."""
    directory = output / relative
    directory.mkdir(parents=True, exist_ok=False)
    if existing_log is not None:
        with (directory / "plugin.log").open("xb") as stream:
            stream.write(existing_log)
    command = sandbox(directory, mounts) + [tool("timeout"), "--signal=TERM", "--verbose", f"{seconds}s"] + payload
    receipt = {"command": command, "directory": relative, "limit_seconds": seconds,
               "returncode": None, "owned_pid_unreaped": None}
    commands.append(receipt)
    with (directory / "stdout.bin").open("xb") as stdout, (directory / "stderr.bin").open("xb") as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                   env={"PATH": "/usr/bin:/bin", "LANG": "C"}, start_new_session=True)
        try:
            receipt["returncode"] = process.wait(timeout=seconds + 10)
        except BaseException:
            # This Popen is ours. GNU timeout already provides the normal TERM deadline.
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    receipt["owned_pid_unreaped"] = process.pid
            receipt["returncode"] = process.poll()
            if receipt["owned_pid_unreaped"] is not None:
                raise FixtureError(f"owned fixture process did not reap after TERM: pid={process.pid}; {directory}")
            raise
    return receipt


def branch_target(word, pc, opcode):
    require(word >> 26 == opcode, f"unexpected branch opcode at {pc:#x}")
    immediate = word & 0x03FFFFFF
    if immediate & 0x02000000:
        immediate -= 0x04000000
    return pc + immediate * 4


def producer_callers(sections):
    address, code = sections['.boot']
    callers = {}
    for writer, entry in enumerate((PRODUCER_ENTRY, PRODUCER2_ENTRY)):
        sites = [address + offset for offset in range(0, len(code) - 3, 4)
                 if (word := int.from_bytes(code[offset:offset + 4], 'little')) >> 26 == 0x25 and
                 branch_target(word, address + offset, 0x25) == entry]
        require(len(sites) == 1, 'need one real self-owned BL to each writer')
        callers[writer] = (sites[0], sites[0] + 4)
    return callers


def elf_layout(blob, mutated, producer=False, producer2_mutated=False):
    """Only bounded self-owned ELF64 headers/sections; no external ELF tool."""
    def unpack(fmt, offset):
        require(0 <= offset <= len(blob) - struct.calcsize(fmt), "truncated ELF table")
        return struct.unpack_from(fmt, blob, offset)

    require(len(blob) <= LIMIT, "sparse fixture ELF unexpectedly large")
    h = unpack("<16sHHIQQQIHHHHHH", 0)
    require(h[0][:7] == b"\x7fELF\x02\x01\x01" and h[1:4] == (2, 183, 1), "need little-endian AArch64 ET_EXEC")
    require(h[4] == BASE + 0x80000 and h[8] == 64, "unexpected ELF entry/header")
    require(h[9] == 56 and 1 <= h[10] <= 16 and h[11] == 64 and 1 <= h[12] <= 64,
            "unexpected ELF table sizes")
    require(h[13] < h[12], "bad ELF section-name table")
    loads = []
    for i in range(h[10]):
        p = unpack("<IIQQQQQQ", h[5] + 56 * i)
        if p[0] != 1:
            continue
        _, flags, offset, address, physical, filesz, memsz, _ = p
        if memsz == 0:
            require(filesz == 0, 'nonempty file data in an empty LOAD')
            continue
        ram_size = 0x8000000 if producer else 0x4000000
        require(physical == address and BASE <= address < address + memsz <= BASE + ram_size,
                "LOAD outside the fixture's private RAM")
        require(filesz <= memsz and offset <= len(blob) and filesz <= len(blob) - offset,
                "invalid LOAD file range")
        require(flags in (5, 6), "unexpected LOAD permissions")
        loads.append((address, memsz, offset, filesz, flags))
    require(len(loads) == (9 if producer else 6), "unexpected sparse LOAD segment count")
    for left, right in zip(sorted(loads), sorted(loads)[1:]):
        require(left[0] + left[1] <= right[0], "overlapping LOAD segments")
    table = [unpack("<IIQQQQIIQQ", h[6] + 64 * i) for i in range(h[12])]
    names_header = table[h[13]]
    require(names_header[4] <= len(blob) and names_header[5] <= len(blob) - names_header[4],
            "invalid ELF string table")
    names = blob[names_header[4]:names_header[4] + names_header[5]]
    code_sections = CODE_SECTIONS + (('.producer', '.producer2') if producer else ())
    sections = {}
    for sh in table:
        require(sh[0] < len(names), "invalid section name")
        end = names.find(b"\0", sh[0])
        require(end >= 0, "unterminated section name")
        name = names[sh[0]:end].decode("ascii")
        if sh[1] == 8:
            data = b""
        else:
            require(sh[4] <= len(blob) and sh[5] <= len(blob) - sh[4], "invalid section file range")
            data = blob[sh[4]:sh[4] + sh[5]]
        require(not (sh[2] & 4 and sh[5] and name not in code_sections), "unexpected executable section")
        require(name not in sections, f"duplicate ELF section: {name}")
        sections[name] = (sh[3], data)
        if name in code_sections or name == '.fixturedata' or (producer and name == '.producertargets'):
            require(any(address <= sh[3] and sh[3] + sh[5] <= address + filesz
                        and sh[4] - offset == sh[3] - address
                        for address, _, offset, filesz, _ in loads), f"section is not file-backed LOAD: {name}")
    expected = {'.boot': BASE + 0x80000, '.fixturedata': BASE + 0x100000,
                '.callers': BASE + 0x209EE7C, '.wrongcaller': BASE + 0x209EEA0, '.observed': ENTRY}
    if producer:
        expected.update({'.producer': PRODUCER_ENTRY, '.producer2': PRODUCER2_ENTRY,
                         '.producertargets': PRODUCER_TARGETS})
    for name, address in expected.items():
        require(name in sections and sections[name][0] == address, f"section VMA mismatch: {name}")
    anchor = bytearray(ANCHOR)
    if mutated:
        anchor[9] = 0xE4
    observed = sections['.observed'][1]
    require(len(observed) == 36 and observed[:24] == anchor, "six-word anchor/own epilogue layout mismatch")
    callers = sections['.callers'][1]
    wrong = sections['.wrongcaller'][1]
    require(len(callers) == 16 and len(wrong) == 8, "unexpected caller sizes")
    for name, offset in (('.callers', 0), ('.callers', 8), ('.wrongcaller', 0)):
        address, data = sections[name]
        require(branch_target(int.from_bytes(data[offset:offset + 4], 'little'), address + offset, 0x25) == ENTRY,
                'BL does not target the synthetic entry')
        target = branch_target(int.from_bytes(data[offset + 4:offset + 8], 'little'), address + offset + 4, 0x05)
        require(sections['.boot'][0] <= target < sections['.boot'][0] + len(sections['.boot'][1]),
                'post-call branch does not return to own boot code')
    if producer:
        require(sections['.producer'][1] == PRODUCER_ANCHOR, 'writer0 six-word anchor differs')
        require(hashlib.sha256(PRODUCER2_ANCHOR).hexdigest() == PRODUCER2_SHA256,
                'parent cached second24B pin differs')
        second = bytearray(PRODUCER2_ANCHOR)
        if producer2_mutated:
            second[5] = 0x70
        require(sections['.producer2'][1] == second and len(second) == 24, 'writer1 six-word anchor differs')
        require(sections['.producertargets'][1] == bytes(32), 'producer target segment differs')
        producer_callers(sections)
    return sections


def expected_record(round_number, lane, mutated):
    values = list(range(31))
    values[0] = 0xA0B0C0D0E0F00000 | round_number << 8 | lane
    values[1] = BASE + 0x88385F8 + int(mutated)
    values[16] = BASE + 0x100000
    values[19] = 0x191A1B1C1D1E0000 | round_number
    values[20] = 0x2021222324250000 | lane
    values[21] = 0x2122232425260000 | round_number << 8 | lane
    values[22] = round_number
    values[23] = 0x1122334455667700 + round_number
    values[24] = 0x2425262728292A2B
    values[25] = lane
    values[27] = BASE + 0x200000
    values[28] = LRS[lane]
    values[29] = 0x292A2B2C2D2E2F30
    values[30] = LRS[lane]
    stack = [0x6677889900000000 + i for i in range(18)]
    stack[2:4] = values[29:31]
    stack[8:10] = values[23:25]
    return struct.pack("<51Q", *values, BASE + 0x200000, (0xA0000000, 0x60000000, 0x30000000)[lane], *stack)


def expected_console(sections, mutated, wrong_only):
    order = (2,) if wrong_only else (0, 2, 1)
    records = b"".join(expected_record(number, lane, mutated) for number in range(1, 18) for lane in order)
    trailer = b"\nSCOPE_FIXTURE_OK calls=17 lanes=0,0,17\n" if wrong_only else b"\nSCOPE_FIXTURE_OK calls=51 lanes=17,17,17\n"
    return HEADER + records + RECORDS_MARKER + b"".join(sections[name][1] for name in CODE_SECTIONS) + trailer


def require_bytes(actual, expected, description):
    if actual != expected:
        offset = next((i for i, pair in enumerate(zip(actual, expected)) if pair[0] != pair[1]), min(len(actual), len(expected)))
        raise FixtureError(f"{description}: byte {offset:#x}, length {len(actual)}/{len(expected)}, "
                           f"actual={actual[offset:offset + 16].hex()} expected={expected[offset:offset + 16].hex()}")


def producer_registers(number, writer, lr, mutated, after):
    words = list(struct.unpack('<51Q', expected_record(number, writer, False)))
    words[0] = PRODUCER_INPUTS[number - 1]
    words[1] = PRODUCER_X1 + 4 * int(mutated and writer == 1) if after else 0x0102030405060708
    words[28] = words[30] = lr
    words[32] = 0x90000000
    words[33:] = [0x6677889900000000 + i for i in range(18)]
    return tuple(words)


def producer_stores(number, writer, mutated):
    result = bytearray(STORE_SEED)
    for offset in (8, 16):
        struct.pack_into('<I', result, offset + 4 * int(mutated and writer == 1),
                         PRODUCER_INPUTS[number - 1] & 0xFFFFFFFF)
    return bytes(result)


def check_producer_console(console, sections, mutated, short_tb=False, reverse=False):
    """Read independent guest dumps, admitting only the guest's defined changes."""
    require(console.startswith(PRODUCER_HEADER), 'missing producer guest header')
    callers = producer_callers(sections)
    offset = len(PRODUCER_HEADER)
    expected_rows, calls = {}, []
    sequence = 0
    for number in range(1, 18):
        if number == 2:
            scope = b''.join(expected_record(n, lane, False) for n in range(1, 18) for lane in (0, 2, 1))
            require_bytes(console[offset:offset + len(scope)], scope, 'interleaved original scope snapshots')
            offset += len(scope)
        for writer in ((1, 0) if reverse else (0, 1)):
            callsite, lr = callers[writer]
            start = offset
            frame = console[offset:offset + PRODUCER_FRAME_BYTES]
            require(len(frame) == PRODUCER_FRAME_BYTES, 'truncated producer boundary frame')
            before = struct.unpack_from('<54Q', frame, 0)
            after = struct.unpack_from('<54Q', frame, 432)
            require_bytes(frame[:408], struct.pack('<51Q', *producer_registers(number, writer, lr, mutated, False)),
                          'producer actual pre-call registers/stack')
            require_bytes(frame[432:840], struct.pack('<51Q', *producer_registers(number, writer, lr, mutated, True)),
                          'producer actual post-call registers/stack')
            require(before[51:] == after[51:], 'producer changed sampled CPSR/context tokens')
            require(before[51] & 0x1F == 5 and before[51] & 0xF0000000 == before[32],
                    'producer snapshot must retain real EL1h/NZCV')
            require_bytes(frame[864:896], STORE_SEED, 'producer target/guard input dump')
            require_bytes(frame[896:928], producer_stores(number, writer, mutated), 'producer target/guard result dump')
            calls.append({'round': number, 'writer': writer, 'before_console_offset': start,
                          'after_console_offset': start + 432,
                          'stores_before_console_offset': start + 864, 'stores_after_console_offset': start + 896,
                          'callsite': f'{callsite:#018x}', 'caller_raw': f'{before[30]:#018x}',
                          'x0_raw': f'{before[0]:#018x}', 'post_call_x1_raw': f'{after[1]:#018x}',
                          'raw_input_u32': f'{before[0] & 0xFFFFFFFF:#010x}', 'cpsr_raw': f'{before[51]:#010x}',
                          'context_mode': 'other_aarch64', 'after_scope_program_phase': number > 1})
            if number <= 16 and not short_tb and not (mutated and writer == 1):
                for site in (('entry', 'pre_M_store') if writer == 0 else ('second_entry',)):
                    sequence += 1
                    row = {'vcpu': 0, 'producer_sequence': sequence,
                           'event_pc': PRODUCER2_ENTRY if writer else PRODUCER_ENTRY + 12 * (site == 'pre_M_store'),
                           'candidate_base': BASE, 'scope_anchor_seen': int(number > 1), 'x0_raw': before[0],
                           'raw_input_u32': before[0] & 0xFFFFFFFF,
                           'proposed_u32': before[0] & 0xFFFFFFFF if site == 'pre_M_store' else 'unknown',
                           'x30_raw': before[30], 'caller_raw': before[30], 'cpsr_raw': before[51],
                           'cpsr_m': 5, 'context_mode': 'other_aarch64', 'nzcv': before[32],
                           'nzcv_mask': 0xF0000000,
                           'optional_raw': {'sp': before[31], 'ttbr0_el1': before[52], 'tpidr_el0': before[53]}}
                    if site == 'pre_M_store':
                        row.update(x1_raw=after[1], effective_destination_raw=after[1] + 0x2F0, destination_match=1)
                    expected_rows[site, number] = row
            offset += PRODUCER_FRAME_BYTES
    tail = RECORDS_MARKER + b''.join(sections[name][1] for name in (*CODE_SECTIONS, '.producer', '.producer2')) + PRODUCER_TRAILER
    require_bytes(console[offset:], tail, 'producer actual whole-code readback and self-check trailer')
    return expected_rows, {'callers': {str(writer): {'callsite': f'{pc:#018x}', 'caller_raw': f'{lr:#018x}'}
                                      for writer, (pc, lr) in callers.items()},
                           'snapshot_words': 54, 'frame_bytes': PRODUCER_FRAME_BYTES, 'calls': calls,
                           'low_va_actual_lr_high32_verified': False}


def scope_expectations(console, producer=False):
    """Use the checked actual post-call dumps of registers restored by the scope epilogue."""
    offset = len(PRODUCER_HEADER) + 2 * PRODUCER_FRAME_BYTES if producer else len(HEADER)
    records = console[offset:offset + 51 * 408]
    require(len(records) == 51 * 408, 'truncated actual scope snapshots')
    expected = {}
    for index in range(51):
        words = struct.unpack_from('<51Q', records, index * 408)
        ordinal, slot = index // 3 + 1, (0, 2, 1)[index % 3]
        if ordinal <= 16 and slot in (0, 1):
            expected[slot, ordinal] = {**{name: words[int(name[1:])] for name in GPRS},
                'actual_pc': ENTRY, 'translated_entry_pc': ENTRY, 'candidate_base': BASE,
                'lr': words[30], 'sp': words[31], 'nzcv': words[32], 'cpsr_m': 5,
                'context_mode': 'other_aarch64'}
    return expected


def vm_command(plugin_arguments, producer=False, short_tb=False):
    command = ['/qemu', '-no-user-config', '-machine', 'virt,secure=off,virtualization=off,gic-version=2',
               '-accel', 'tcg,thread=single' + (',one-insn-per-tb=on' if short_tb else ''),
               '-cpu', 'cortex-a35', '-smp', 'cpus=1,maxcpus=1',
               '-m', '128M' if producer else '64M',
               '-nodefaults', '-nographic', '-display', 'none', '-serial', 'none', '-monitor', 'none',
               '-nic', 'none', '-no-reboot', '-kernel', '/in/fixture.elf',
               '-chardev', 'file,id=semi,path=/out/console.bin',
               '-semihosting-config', 'enable=on,target=native,chardev=semi']
    if plugin_arguments is not None:
        command += ['-plugin', '/observer.so' + (',' + ','.join(plugin_arguments) if plugin_arguments else '')]
    return command


def run_fixture(qemu, plugin, output, *, schema, receipt, fixture_source_sha256):
    """Explicit v3 execution with the parent's independently frozen fixture8."""
    qemu, plugin, output = validate_paths(qemu, plugin, output)
    require(isinstance(fixture_source_sha256, dict), 'explicit parent frozen fixture map required')
    fixture_source_sha256 = dict(fixture_source_sha256)
    inputs = validate_v3_assets(qemu, plugin, schema, receipt, fixture_source_sha256=fixture_source_sha256)
    checks = load_v3_checks()
    clang = tool('clang')
    tool('bwrap')
    tool('timeout')
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'status': 'EXECUTING', 'profile': PROFILE, 'trace_schema': SCHEMA,
                'trace_schema_sha256': inputs['schema']['sha256'],
                'capture_verified': False, 'physical_asic_verified': False,
                'physical_asic_compatibility_verified': False, 'branchretirement': False,
                'cap': False, 'capture': False, 'physical': False,
                'sony_branch_verified': False, 'sony_store_verified': False, 'original_main_base_joined': False,
                'instruction_retirement_verified': False, 'storecompletion': False,
                'scope_observer_verified': False, 'producer_observer_verified': False,
                'scope_schema_assertions': 'PENDING_EXECUTION', 'inputs': inputs,
                'fixture_source_sha256': fixture_source_sha256, 'fixture_source_snapshots': {},
                'commands': [], 'variants': {}, 'startup_negatives': {}, 'failure': None}
    try:
        source_copy = output / 'inputs'
        source_copy.mkdir()
        for name in FIXTURE_SOURCES:
            data = read_small(SOURCE / name)
            require(hashlib.sha256(data).hexdigest() == fixture_source_sha256['integration/' + name],
                    'fixture source changed before staging: ' + name)
            copied = source_copy / name
            with copied.open('xb') as stream:
                stream.write(data)
            copied.chmod(0o400)
        manifest['fixture_source_snapshots'] = verify_fixture_snapshots(output, fixture_source_sha256)
        for name in ('schema', 'receipt', 'readonly_import_audit'):
            original = Path(inputs[name]['path'])
            raw = read_small(original)
            require(hashlib.sha256(raw).hexdigest() == inputs[name]['sha256'], 'asset changed before staging: ' + name)
            with (source_copy / original.name).open('xb') as stream:
                stream.write(raw)
        for variant in API_CASES:
            mutated = variant == 'one_byte_mutation'
            wrong_only = variant == 'wrong_lr_only'
            producer = variant.startswith('producer')
            producer2_mutated = variant == 'producer_corrupt'
            short_tb = variant == 'producer_short_tb'
            reverse = variant == 'producer_reverse_order'
            verify_fixture_snapshots(output, fixture_source_sha256)
            build_relative = 'build/producer' if short_tb else f'build/{variant}'
            elf = output / build_relative / 'fixture.elf'
            if not short_tb:
                payload = [clang, '--target=aarch64-linux-gnu', '-march=armv8-a', '-fuse-ld=lld', '-nostdlib',
                           '-static', '-no-pie', '-x', 'assembler-with-cpp', f'-DFIXTURE_MUTATED={int(mutated)}',
                           f'-DFIXTURE_WRONG_LR_ONLY={int(wrong_only)}', f'-DFIXTURE_PRODUCER={int(producer)}',
                           f'-DFIXTURE_PRODUCER2_MUTATED={int(producer2_mutated)}',
                           f'-DFIXTURE_PRODUCER_REVERSE={int(reverse)}', '/src/fixture.S',
                           '-Wl,-T,/src/link.ld,-z,max-page-size=4096,--build-id=none',
                           '-Wl,-Map,/out/fixture.map', '-o', '/out/fixture.elf']
                build = launch(output, build_relative, payload, [(source_copy, '/src')], manifest['commands'], 60)
                require(build['returncode'] == 0, f'clang/lld failed: {output / build_relative / "stderr.bin"}')
            elf_hash = sha256(elf)
            sections = elf_layout(read_small(elf), mutated, producer, producer2_mutated)
            results, baseline_console = {}, None
            for mode in ('baseline', 'plugin'):
                relative = f'cases/{variant}-{mode}'
                arguments = ['log=/out/plugin.log'] if mode == 'plugin' else None
                result = launch(output, relative, vm_command(arguments, producer, short_tb),
                                [(qemu, '/qemu'), (plugin, '/observer.so'), (elf, '/in/fixture.elf')],
                                manifest['commands'], 30)
                require(result['returncode'] == 0,
                        f'QEMU {variant}/{mode} failed, rc={result["returncode"]}; {output / relative / "stderr.bin"}')
                console = read_small(output / relative / 'console.bin')
                expected_producers, actual_producer = {}, None
                if producer:
                    expected_producers, actual_producer = check_producer_console(
                        console, sections, producer2_mutated, short_tb, reverse)
                else:
                    require_bytes(console, expected_console(sections, mutated, wrong_only),
                                  f'{variant}/{mode} self-check, snapshot and own-code readback')
                if mode == 'baseline':
                    baseline_console = console
                else:
                    require_bytes(console, baseline_console, f'{variant} plugin/baseline full boundary dumps')
                    raw_log = read_small(output / relative / 'plugin.log')
                    require(b'scope_observer_host_error' not in read_small(output / relative / 'stderr.bin'),
                            'observer reported a host I/O or install failure')
                    expected_entries = scope_expectations(baseline_console, producer) if not (mutated or wrong_only or short_tb) else {}
                    if producer:
                        expected_producers, _ = check_producer_console(
                            baseline_console, sections, producer2_mutated, short_tb, reverse)
                    candidate_base = None if mutated or short_tb else BASE
                    other_lr = 0 if candidate_base is None else 17 if wrong_only else 16
                    trace_result = checks.assert_scope_trace_v3(
                        raw_log, expected_entries, candidate_base, other_lr,
                        expected_producers=expected_producers,
                        producer_base=BASE if producer and not short_tb else None,
                        producer2_base=BASE if producer and not short_tb and not producer2_mutated else None)
                    require(isinstance(trace_result, dict) and isinstance(trace_result.get('rows'), list),
                            'direct v3 adapter must return parsed original raw rows')
                results[mode] = {'console': f'{relative}/console.bin', 'returncode': result['returncode'],
                                 'plugin_log': f'{relative}/plugin.log' if mode == 'plugin' else None,
                                 'actual_producer': actual_producer}
            require(sha256(elf) == elf_hash, 'fixture ELF changed during execution')
            actual_rows = [row for row in trace_result['rows'] if row['kind'] == 'M_producer']
            discovered = list(dict.fromkeys(1 if row['site'] == 'second_entry' else 0 for row in actual_rows))
            manifest['variants'][variant] = {'runs': results, 'elf_sha256': elf_hash,
                'program_baseline_equal': True, 'guest_selfcheck_and_code_readback_exact': True,
                'synthetic_base': hex(BASE), 'synthetic_entry': hex(ENTRY), 'lrs': [hex(lr) for lr in LRS],
                'call_order': [2] if wrong_only else [0, 2, 1], 'rounds': 17,
                'producer_calls': 34 if producer else 0, 'producer_calls_per_writer': [17, 17] if producer else [0, 0],
                'producer_success_rows': len(actual_rows),
                'producer_early_rows': sum(int(row['scope_anchor_seen'], 16) == 0 for row in actual_rows),
                'producer_site_counts': {site: sum(row['site'] == site for row in actual_rows)
                                         for site in ('entry', 'pre_M_store', 'second_entry')},
                'producer_call_order': [1, 0] if reverse else [0, 1] if producer else [],
                'producer_discovery_order': discovered,
                'trace_sha256': hashlib.sha256(raw_log).hexdigest(),
                'trace_schema_sha256': inputs['schema']['sha256'],
                'trace_adapter': 'scope_trace_checks_v3.assert_scope_trace_v3',
                'short_tb': short_tb, 'scope_schema_assertions': 'VERIFIED_SELF_OWNED_ONLY'}
        elf = output / 'build/anchor/fixture.elf'
        for name in ('missing_log_argument', 'existing_log'):
            relative = f'cases/{name}'
            sentinel = b'exclusive-log-sentinel\n'
            arguments = ['log=/out/plugin.log'] if name == 'existing_log' else []
            result = launch(output, relative, vm_command(arguments),
                            [(qemu, '/qemu'), (plugin, '/observer.so'), (elf, '/in/fixture.elf')],
                            manifest['commands'], 30, existing_log=sentinel if name == 'existing_log' else None)
            require(result['returncode'] > 0 and result['returncode'] not in (124, 125, 126, 127),
                    f'{name} was not a normal startup rejection; {output / relative / "stderr.bin"}')
            require(b'scope_observer_host_error' in read_small(output / relative / 'stderr.bin'),
                    f'{name}: plugin rejection diagnostic missing')
            console = output / relative / 'console.bin'
            require(not console.exists() or read_small(console) == b'', f'{name}: own guest unexpectedly started')
            if name == 'existing_log':
                require_bytes(read_small(output / relative / 'plugin.log'), sentinel, 'exclusive log must remain unchanged')
            manifest['startup_negatives'][name] = {'returncode': result['returncode'], 'guest_started': False}
        manifest['fixture_source_snapshots'] = verify_fixture_snapshots(output, fixture_source_sha256)
        for name, item in inputs.items():
            digest = (sha256(item['path']) if name in ('qemu', 'plugin') else
                      hashlib.sha256(read_small(item['path'])).hexdigest())
            require(digest == item['sha256'], f'input changed during run: {item["path"]}')
        for name in ('schema', 'receipt', 'readonly_import_audit'):
            require(sha256(source_copy / Path(inputs[name]['path']).name) == inputs[name]['sha256'],
                    'staged asset changed during run: ' + name)
        manifest['scope_observer_verified'] = True
        manifest['producer_observer_verified'] = True
        manifest['scope_schema_assertions'] = 'VERIFIED_SELF_OWNED_ONLY'
        manifest['status'] = 'PASS_SELF_OWNED_QEMU_SCOPE_V3_FIXTURE'
    except BaseException as error:
        manifest['status'] = 'FAILED'
        manifest['failure'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        manifest['artifacts'] = {str(path.relative_to(output)): {'sha256': sha256(path), 'bytes': path.stat().st_size}
                                 for path in sorted(output.rglob('*')) if path.is_file() and not path.is_symlink()}
        with (output / 'manifest.json').open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.write('\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', required=True, type=Path, help='explicit unchanged API7 candidate, no default')
    parser.add_argument('--plugin', required=True, type=Path, help='explicit newly receipted v3 observer .so')
    parser.add_argument('--schema', required=True, type=Path, help='explicit new log-schema-v3.json')
    parser.add_argument('--receipt', required=True, type=Path, help='explicit new v3 build-receipt.json/exact9 runtime closure')
    parser.add_argument('--fixture-sources', required=True, type=Path,
                        help='ordinary JSON fixture_source_sha256 map pinned by this new batch parent ready')
    parser.add_argument('--output', required=True, type=Path, help='new child of the private v3 fixture scratch root')
    args = parser.parse_args()
    try:
        result = run_fixture(args.qemu, args.plugin, args.output, schema=args.schema, receipt=args.receipt,
                             fixture_source_sha256=json.loads(read_small(args.fixture_sources)))
    except (FixtureError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'fixture failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps({'status': result['status'], 'scope_observer_verified': result['scope_observer_verified'],
                      'producer_observer_verified': result['producer_observer_verified'],
                      'capture_verified': False, 'physical_asic_verified': False,
                      'manifest': str(args.output.resolve() / 'manifest.json')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
