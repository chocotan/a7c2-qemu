"""Virtual B0 loader functional model: evaluate the original 2.01 event table.

This models the documented loader route selection (25-entry table at 0xfe064538,
selector 0xfe051230) from virtual disk state before every boot. It is the
explicit virtual-functional profile authorized 2026-10-28: it never claims Sony
physical BootROM/CP compatibility. Inputs the physical loader would take from
the CP (H bit, ld slot) are explicit named defaults here, not observations.

Routes:
  updater (mode 3): p2 /updater/mode present with queryable content
  ssboot  (mode 11): p5 starts with the 4-byte WBI2 magic
  hotboot (mode 2): retained RAM session bound to this launch (default absent)
  cold    (mode 1): default branch, assets read from p3 like the real loader
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import io
import json
import os
import sys

import persistent_disk as disk
import boot_flow

SCHEMA = 'a7c2-virtual-loader-v1'
PROFILE = 'virtual-b0-loader-functional-v1'
WBI2_MAGIC = b'WBI2'
UPDATER_PATH = '/updater/mode'

# No physical CP/PMIC is modeled; these stand for loader inputs the real B0
# reads over its FA slots. Each default keeps the selector on the disk-driven
# branches and is recorded in every receipt.
DEFAULT_PREDICATES = {
    'adjust': False, 'wl_anki': False, 'bis_1st': False, 'bis_2nd': False,
    'ontimer': False, 'ontimrz': False, 'keychat': False, 'lowbatt': False,
    'panlopn': False, 'panlapo': False, 'batt_in': False, 'psw_off': False,
    'chg_app': False, 'usbcoff': False, 'rec_off': False, 'reallow': False,
    'usbchrg': False, 'hoff_en': False, 'ddr_off': False, 'bi_vali': False,
    'ss_bis': False, 'cldboot': False,
}


def _slices(fd, geometry):
    rows = {row['id']: row for row in geometry['slices']}
    for name in ('nflasha2', 'nflasha3', 'nflasha5'):
        if name not in rows:
            raise ValueError('Virtual disk geometry lacks ' + name)
    return rows


def read_updater_mode(fd, geometry):
    """Return (present, content) for p2 /updater/mode; unreadable content counts present."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor/fwtool-sdk'))
    from fwtool.archive.fat import readFat
    partition = _slices(fd, geometry)['nflasha2']
    source = io.BytesIO(os.pread(fd, partition['bytes'], partition['offset']))
    for entry in readFat(source):
        if entry.path == UPDATER_PATH:
            data = entry.contents.read(entry.size)
            return True, data.decode('ascii', errors='replace').strip('\x00\r\n')
    return False, None


def read_wbi2(fd, geometry):
    partition = _slices(fd, geometry)['nflasha5']
    head = os.pread(fd, len(WBI2_MAGIC), partition['offset'])
    return head == WBI2_MAGIC


def evaluate_fd(fd, geometry, *, retained_ram=False):
    updater_present, updater_content = read_updater_mode(fd, geometry)
    wbi2 = read_wbi2(fd, geometry)
    predicates = dict(DEFAULT_PREDICATES)
    predicates.update(updater=updater_present, hotboot=bool(retained_ram), ssboot=wbi2)
    route = boot_flow.select_route(predicates)
    resolve = boot_flow.resolve_resume(route, ld_read=True, ld=0, h=False,
                                      retained_ram_bound=bool(retained_ram))
    return dict(schema=SCHEMA, profile=PROFILE, physical_bootrom_compatible=False,
                predicates=predicates, predicate_defaults='CP/PMIC inputs fixed per DEFAULT_PREDICATES',
                disk_inputs=dict(updater_mode_present=updater_present,
                                 updater_mode_content=updater_content, wbi2_magic=wbi2),
                retained_ram=bool(retained_ram), route=route, resolve=resolve)


@contextmanager
def _lease(instance):
    with disk.lease(Path(instance).absolute()) as leased:
        yield leased


def evaluate(instance, *, retained_ram=False):
    with _lease(instance) as leased:
        return evaluate_fd(leased['fd'], leased['geometry'], retained_ram=retained_ram)


def cold_boot_assets_fd(fd, geometry, *, kernel_sha256, ram0_sha256):
    """Read the mode-1 boot assets straight from p3, like the real loader path."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor/fwtool-sdk'))
    from fwtool.archive.fat import readFat
    partition = _slices(fd, geometry)['nflasha3']
    source = io.BytesIO(os.pread(fd, partition['bytes'], partition['offset']))
    assets = {}
    for entry in readFat(source):
        if entry.path in ('/initrd.img', '/vmlinux.bin'):
            data = entry.contents.read(entry.size)
            digest = hashlib.sha256(data).hexdigest()
            expected = ram0_sha256 if entry.path == '/initrd.img' else kernel_sha256
            assets[entry.path] = dict(bytes=len(data), sha256=digest, expected_sha256=expected,
                                      identity_matches=digest == expected)
    return assets


def boot_plan(instance, *, kernel_sha256, ram0_sha256, retained_ram=False):
    """Full loader decision for one boot. Non-cold routes report their backend status."""
    with _lease(instance) as leased:
        decision = evaluate_fd(leased['fd'], leased['geometry'], retained_ram=retained_ram)
        plan = dict(decision)
        mode = (decision.get('route') or {}).get('mode') if decision['route'].get('status') == 'selected' else None
        if mode == 1:
            plan['assets'] = cold_boot_assets_fd(leased['fd'], leased['geometry'],
                                                 kernel_sha256=kernel_sha256, ram0_sha256=ram0_sha256)
            plan['boot_path'] = 'cold'
            plan['backend'] = 'product-original-init-cold'
        elif mode == 3:
            plan['boot_path'] = 'updater'
            plan['backend'] = 'not-integrated-in-product'
        elif mode in (2, 11):
            plan['boot_path'] = 'ram-hotboot' if mode == 2 else 'wbi-resume'
            plan['backend'] = 'not-integrated-in-product'
        else:
            plan['boot_path'] = None
            plan['backend'] = 'route-unknown'
        return plan


WBI_HEADER_BYTES = 0x58
WBI_SECTION_BYTES = 0x40


def parse_wbi_fd(fd, geometry):
    """Parse the documented WBI2 image (0x58B header, 0x40B sections, data after 512B).

    Structure and field offsets follow the boot-loading-chain research; the
    holes between represented regions are unknown on real hardware and are
    reported, never assumed zero.
    """
    import struct
    partition = _slices(fd, geometry)['nflasha5']
    head = os.pread(fd, WBI_HEADER_BYTES, partition['offset'])
    if head[:4] != WBI2_MAGIC:
        raise ValueError('p5 does not start with the WBI2 magic')
    sections, = struct.unpack_from('<Q', head, 8)
    flag, = struct.unpack_from('<Q', head, 0x10)
    resume_vector, = struct.unpack_from('<Q', head, 0x18)
    r_data_size, = struct.unpack_from('<Q', head, 0x30)
    o_data_size, = struct.unpack_from('<Q', head, 0x50)
    if not 0 < sections < 0x10000 or resume_vector == 0:
        raise ValueError('WBI header fields out of documented bounds')
    table_offset = 512 + r_data_size
    rows = []
    data_cursor = 512
    for index in range(sections):
        raw = os.pread(fd, WBI_SECTION_BYTES, partition['offset'] + table_offset + index * WBI_SECTION_BYTES)
        if len(raw) != WBI_SECTION_BYTES:
            raise ValueError('WBI section table truncated at ' + str(index))
        target, rlen, cksum, sflag, olen = struct.unpack_from('<QQQQQ', raw, 0)
        if sflag & 1 and rlen == 0:
            kind, source_offset = 'zero', None
        else:
            if rlen == 0 or rlen % 512:
                raise ValueError('WBI data section length invalid at ' + str(index))
            kind, source_offset = 'data', data_cursor
            data_cursor += rlen
        rows.append(dict(index=index, target=target, rlen=rlen, olen=olen,
                         flag=sflag, cksum=cksum, kind=kind, source_offset=source_offset))
    if data_cursor - 512 != r_data_size:
        raise ValueError('WBI section data does not sum to the header r_data_size')
    return dict(magic=WBI2_MAGIC.decode(), sections=sections, flag=flag,
                resume_vector=resume_vector, r_data_size=r_data_size,
                o_data_size=o_data_size, rows=rows,
                unknown_holes='regions of p5 outside header/data/section-table are unknown on real hardware')


def wbi_resume_plan(instance):
    # Load BI for mode 11: section data back to target PAs, zero fills, resume entry.
    with _lease(instance) as leased:
        parsed = parse_wbi_fd(leased['fd'], leased['geometry'])
        runs = []
        for row in parsed['rows']:
            if row['kind'] == 'data':
                runs.append(dict(kind='data', target=row['target'], length=row['rlen'],
                                 source_offset=row['source_offset']))
            else:
                runs.append(dict(kind='zero', target=row['target'], length=row['olen']))
        runs.sort(key=lambda item: item['target'])
        return dict(schema=SCHEMA, profile=PROFILE,
                    wbi=dict(parsed, rows=runs),
                    entry=parsed['resume_vector'],
                    backend='wbi-load-bi-sections',
                    physical_wbi_resume_compatible=False)


DDR_BASE = 0x400000000
DDR_SIZE = 24576 * 1024 * 1024


def wbi_resume_assets(instance, out_dir, *, ram_bytes=DDR_SIZE):
    'Build the sparse DDR image with every WBI data section at its target PA.'
    with _lease(instance) as leased:
        return _write_wbi_assets(leased, out_dir, ram_bytes)


def _write_wbi_assets(leased, out_dir, ram_bytes):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ram = out_dir / 'wbi-ram.bin'
    if ram.exists():
        raise ValueError('WBI resume output must be fresh')
    parsed = parse_wbi_fd(leased['fd'], leased['geometry'])
    fd = os.open(ram, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        os.ftruncate(fd, ram_bytes)
        written = 0
        partition_offset = _slices(leased['fd'], leased['geometry'])['nflasha5']['offset']
        for row in parsed['rows']:
            if row['kind'] != 'data':
                continue
            offset = row['target'] - DDR_BASE
            if offset < 0 or offset + row['rlen'] > ram_bytes:
                raise ValueError('WBI section target escapes the DDR window')
            remaining = row['rlen']
            cursor = row['source_offset']
            while remaining:
                count = min(remaining, 1024 * 1024)
                data = os.pread(leased['fd'], count, partition_offset + cursor)
                if len(data) != count:
                    raise ValueError('Short WBI section read')
                if os.pwrite(fd, data, offset) != count:
                    raise OSError('Short WBI DDR write')
                offset += count
                cursor += count
                remaining -= count
                written += count
        os.fsync(fd)
    finally:
        os.close(fd)
    return dict(ram=str(ram), ram_bytes=ram_bytes, entry=parsed['resume_vector'],
                sections=parsed['sections'], data_bytes=parsed['r_data_size'],
                written=written, schema=SCHEMA, profile=PROFILE,
                physical_wbi_resume_compatible=False)


def save_receipt(run_dir, plan):
    run_dir = Path(run_dir)
    payload = json.dumps(plan, indent=2, sort_keys=True) + '\n'
    temporary = run_dir / 'virtual-loader-receipt.json.new'
    temporary.write_text(payload)
    temporary.replace(run_dir / 'virtual-loader-receipt.json')
    return run_dir / 'virtual-loader-receipt.json'
