# SPDX-License-Identifier: MIT
"""Paused functional AP image-bus reads; no native writer/ASIC/capture claim."""
import errno
import hashlib
import re
import struct

OP, ORIGIN, BASE_BYTES, FRAME_BYTES, PAGE = 11, 1, 360, 224, 4096
COMMAND, PROFILE, U64 = 0x02820746, 'virtual-functional-camera-v1', 1 << 64
UNITS = {0x1d9: 0x64000, 0x1da: 0xc800, 0x1db: 0xd100}
TOKEN_BASE = 1 << 63
CLAIMS = dict(source_model='paused-source-snapshot-v1', native_global_writer_exclusion_verified=False,
              physical_ASIC=False, physicalBackingObjectVerified=False, capture=False,
              capture_verified=False, physical_asic_compatibility_verified=False,
              source_writer_completion_verified=False, native_source_atomicity_verified=False)


def need(ok, why):
    if not ok:
        raise ValueError(why)


def number(raw, at, size=4):
    return int.from_bytes(raw[at:at + size], 'little')


def fnv64(raw):
    value = 0xcbf29ce484222325
    for byte in raw:
        value = ((value ^ byte) * 0x100000001b3) & (U64 - 1)
    return value


def binding(header):
    return header[8:12] + header[16:24] + header[52:56] + header[96:116] + header[120:128]


def validate_origin(header):
    need(len(header) == 512 and number(header, 52) == ORIGIN and
         number(header, 108) == COMMAND and number(header, 112) == 40 and
         0 < number(header, 96) < 2**31 and number(header, 100) and number(header, 104),
         'API40 source origin/flags/command/bytes differs')


def packet(raw, header, mailbox):
    validate_origin(header)
    need(type(raw) is bytes and BASE_BYTES <= len(raw) <= BASE_BYTES + 8 * 102,
         'Source snapshot request size differs')
    v = lambda at: number(raw, at)
    q = lambda at: number(raw, at, 8)
    unit, ap, cp, length, cp_count, sdk_count = (v(at) for at in (4, 8, 12, 16, 20, 24))
    need(v(0) == 1 and unit in UNITS and length == UNITS[unit] and v(28) == 3 and v(124) == 0 and
         cp_count == (length + PAGE - 1) // PAGE and sdk_count in (1, 2) and
         len(raw) == BASE_BYTES + 8 * (cp_count + sdk_count), 'Unit/length/count/reserved/source facts differs')
    need(0 < ap < 0x8000 and ap >> 10 > 0 and ap & 0x3ff != 0x3ff and
         0x8000 <= cp <= 0xffff and (cp & 0x7fff) >> 10 > 0 and
         cp & 0x3ff == unit - 0x1d9 + 2 and v(108) == ap >> 10 and v(104) != 0 and v(112) <= 0xffff,
         'AP/CP handle generation/index/relation differs')
    need(all(q(at) for at in (32, 40, 48, 56)) and
         0 < q(80) < q(88) < q(96) and v(116) == mailbox['pid'] == number(header, 8) and
         v(120) == number(header, 96) and number(header, 16, 8) == mailbox['nonce'],
         'Allocation/CP ownership/sequence/PID/TID/nonce differs')
    share, opened = bytearray(40), bytearray(40)
    struct.pack_into('<I', share, 0, 0x21)
    struct.pack_into('<2I', share, 4, unit, ap)
    struct.pack_into('<I', opened, 0, 0x24)
    struct.pack_into('<2I', opened, 8, ap, 0xffffffff)
    need(raw[128:168] == share and raw[208:248] == opened, 'Original Share21/Open24 request differs')
    for at, command in ((168, 0x8021), (248, 0x8024)):
        need(struct.unpack_from('<Hh', raw, at) == (command, 0), 'Original Share/Open reply status differs')
    physical = q(64)
    need(number(raw, 256, 2) == 1 and v(260) == ap and q(272) == physical and v(280) == length and
         physical > 0 and physical + length <= U64, 'Original Open24 physical span differs')
    frame, api_pointer, api = q(288), q(296), raw[304:344]
    need(frame > 0 and frame % 16 == 0 and frame + FRAME_BYTES <= U64 and
         api_pointer == frame + 0xb8 and sdk_count == ((frame % PAGE) + FRAME_BYTES + PAGE - 1) // PAGE,
         'SDK frame/API pointer/page coverage differs')
    source, destination, count, mode, callback, context = struct.unpack('<QQIIQQ', api)
    need((source, destination, count, mode, context) == (frame + 0x68, frame + 0x70, length, 1, frame + 0x60) and
         callback != 0 and raw[344:352] == struct.pack('<2I', ap, 0) and
         raw[352:360] == struct.pack('<2I', cp, 0) and fnv64(api) == q(72) == number(header, 120, 8),
         'Original API40/descriptors/offset/FNV differs')
    pages = list(struct.unpack_from('<' + 'Q' * (cp_count + sdk_count), raw, BASE_BYTES))
    need(all(p and p % PAGE == 0 and p + PAGE <= U64 for p in pages), 'Invalid CP/SDK GPA page')
    return dict(unit=unit, ap_handle=ap, cp_handle=cp, length=length, physical=physical,
                allocation_token=q(32), cp_epoch=q(40), cp_registration=q(48), owner=q(56),
                birth=q(80), share=q(88), opened=q(96), relation=v(104), generation=v(108), extent_id=v(112),
                frame=frame, api_pointer=api_pointer, api_fnv=q(72), cp_pages=pages[:cp_count], sdk_pages=pages[cp_count:])


def mtree(text):
    """Narrow h71 formatter grammar, copied from the reviewed offline parser."""
    need(type(text) is str and len(text) <= 256 * 1024, 'Invalid/oversized mtree reply')
    views = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.fullmatch(r'FlatView #(\d+)', line)
        if m:
            need(not any(v['id'] == int(m[1]) for v in views), 'duplicate FlatView')
            views.append(dict(id=int(m[1]), AS=[], rows=[]))
            continue
        need(bool(views), 'line before FlatView')
        v = views[-1]
        m = re.fullmatch(r' AS "([^"]+)", root: (.+)', line)
        if m:
            v['AS'].append(dict(name=m[1], root=m[2]))
            continue
        m = re.fullmatch(r' Root memory region: (.+)', line)
        if m:
            need('root' not in v, 'duplicate root')
            v['root'] = m[1]
            continue
        if line == '  No rendered FlatView':
            need(v.get('root') == '(none)' and not v['rows'], 'invalid unrendered view')
            continue
        m = re.fullmatch(r'  ([0-9a-f]{16})-([0-9a-f]{16}) \(prio (-?\d+), (ram|rom|romd|i/o|container)\): (.+?)(?: @([0-9a-f]{16}))? (owner|parent):\{([^{}]+)\}', line)
        need(m is not None, 'unregistered mtree line')
        a, z, off = int(m[1], 16), int(m[2], 16), int(m[6] or '0', 16)
        need(a <= z < U64 and off + z - a + 1 <= U64, 'row/offset overflow')
        need(not v['rows'] or v['rows'][-1]['end'] <= a, 'overlapping/unsorted FlatView')
        need(' @' not in m[5] and ' owner:' not in m[5], 'malformed region name')
        v['rows'].append(dict(start=a, end=z + 1, type=m[4], name=m[5], offset=off,
                              owner_kind=m[7], owner=m[8]))
    need(views and all('root' in v and v['AS'] for v in views), 'incomplete FlatView')
    return views


def selected(views):
    hits = [[(v, a) for v in views for a in v['AS'] if a['name'] == name] for name in ('memory', 'cpu-memory-0')]
    need(all(len(h) == 1 and h[0][1]['root'] == 'system' for h in hits) and
         hits[0][0][0] is hits[1][0][0] and hits[0][0][0]['root'] == 'system', 'CPU/system AS ambiguity')
    return hits[0][0][0]


def cover(view, address, length):
    need(type(address) is int and type(length) is int and 0 <= address < U64 and
         0 < length < U64 and address + length <= U64, 'empty/overflowing span')
    cursor, end, pieces = address, address + length, []
    for row in view['rows']:
        a, z = max(address, row['start']), min(end, row['end'])
        if a >= z:
            continue
        need(a == cursor and row['type'] == 'ram', 'gap/overlay/non-RAM')
        off = row['offset'] + a - row['start']
        need(off + z - a <= U64, 'offset overflow')
        key = (view['root'], row['owner_kind'], row['owner'], row['name'],
               row['start'], row['end'], row['offset'])
        if pieces:
            need(pieces[-1][0] == key and pieces[-1][2] == off, 'cross-MR/discontinuous offset')
        pieces.append((key, off, off + z - a))
        cursor = z
    need(cursor == end, 'uncovered span')
    return pieces


def disjoint(text, source, mailbox):
    view = selected(mtree(text))
    spans = [(source['physical'], source['length'])] + [
        (p, PAGE) for p in source['cp_pages'] + source['sdk_pages'] + list(mailbox['pages'])]
    pieces = [piece for a, n in spans for piece in cover(view, a, n)]
    # Different rows do not serialize a shared MR/RAMBlock object key.
    need(len({p[0] for p in pieces}) == 1, 'Cross-MR/winning-row backing alias cannot be excluded')
    canonical = sorted((a, z) for _, a, z in pieces)
    need(all(z <= a for (_, z), (a, _) in zip(canonical, canonical[1:])), 'RAM MR-offset alias/duplicate page')
    return dict(flatview=view['id'], root=view['root'], spans=len(spans), pieces=len(pieces),
                canonical_ranges=[dict(root=key[0], owner_kind=key[1], owner=key[2], name=key[3],
                                       offset=a, end=z) for key, a, z in pieces],
                actual_cpu_as_ram_coverage=True, one_winning_ram_row_verified=True, canonical_mr_offsets_disjoint=True,
                physicalBackingObjectVerified=False)


def parse_xp(text, address, length):
    need(type(text) is str and len(text) <= 4 * 1024 * 1024 and type(length) is int and
         0 < length <= max(UNITS.values()) and type(address) is int and 0 <= address < U64 and
         address + length <= U64, 'Invalid physical dump bounds/type')
    output = bytearray()
    for line in text.splitlines():
        m = re.fullmatch(r'([0-9a-fA-F]{8,16}):((?: 0x[0-9a-fA-F]{2}){1,8})', line)
        need(m is not None and int(m[1], 16) == address + len(output),
             'Invalid/noncontiguous physical dump line: ' + repr(line[:256]))
        values = m[2].split()
        need(len(values) == min(8, length - len(output)) and len(output) < length,
             'Short/extra physical dump line: ' + repr(line[:256]))
        output.extend(int(v, 16) for v in values)
    need(len(output) == length, f'Short physical dump tail: actual={len(output)} expected={length}')
    return bytes(output)


class Snapshot:
    """One immutable host allocation; the broker owns stream reconstruction."""
    def __init__(self, enabled):
        self.enabled, self.serial, self.active, self.fault = enabled, 0, None, None

    def open(self, raw, header, mailbox, qmp, window=None):
        need(self.enabled, 'Source snapshot functional profile disabled')
        need(self.active is None and self.fault is None, 'Source snapshot active/faulted')
        source = packet(raw, header, mailbox)
        def command(line):
            result = qmp.execute('human-monitor-command', {'command-line': line})
            if window is not None:
                window['commands'].append(dict(command='human-monitor-command', arguments={'command-line': line},
                    qmp_id=getattr(qmp, 'serial', None), reply_type=type(result).__name__,
                    reply_bytes=len(result.encode()) if type(result) is str else None,
                    reply_sha256=hashlib.sha256(result.encode()).hexdigest() if type(result) is str else None))
            return result
        try:
            need(command('cpu 0') == '', 'Monitor CPU0 selection refused')
            text = command('info mtree -f -o')
            mapping = disjoint(text, source, mailbox)
            mapping.update(mtree_raw=text, mtree_sha256=hashlib.sha256(text.encode()).hexdigest(),
                           mtree_bytes=len(text.encode()), monitor_cpu=0, monitor_selection_reply='')
            xp_command = f'xp /{source["length"]}bx 0x{source["physical"]:x}'
            dumps = []
            for _ in range(2):
                reply = command(xp_command)
                evidence = dict(kind='xp', bytes=len(reply) if type(reply) is str else None,
                                sha256=hashlib.sha256(reply.encode()).hexdigest() if type(reply) is str else None,
                                raw_prefix=reply[:256] if type(reply) is str else None,
                                raw_tail=reply[-256:] if type(reply) is str else None)
                dumps.append(evidence)
                body = parse_xp(reply, source['physical'], source['length'])
                evidence.update(decoded_bytes=len(body), decoded_sha256=hashlib.sha256(body).hexdigest())
                if len(dumps) == 1:
                    first = body
                else:
                    need(first == body, 'Source changed across paused full-span reads')
            need(self.serial < TOKEN_BASE - 1, 'Source token namespace exhausted')
            self.serial += 1
            self.active = dict(token=TOKEN_BASE | self.serial, data=first, binding=binding(header), source=source,
                               fnv1a64=fnv64(first), sha256=hashlib.sha256(first).hexdigest())
            return self.active, dict(**CLAIMS, mapping=mapping, full_span_reads=dumps,
                                     exact_double_read_equal=True, bytes=len(first), sha256=self.active['sha256'])
        except (ValueError, OSError, EOFError, TimeoutError) as error:
            self.fault = dict(error=str(error), dumps=locals().get('dumps', []),
                              mtree_sha256=hashlib.sha256(text.encode()).hexdigest() if type(locals().get('text')) is str else None,
                              **CLAIMS)
            raise

    def stream(self, header, incoming, transfer):
        validate_origin(header)
        active = self.active
        if not active or transfer is None or number(incoming, 0, 8) != active['token']:
            return -errno.ESTALE, b'', 0
        if binding(header) != active['binding']:
            return -errno.EPERM, b'', 0
        offset = number(incoming, 8, 8)
        if number(header, 32) == 64:
            if offset != transfer['cursor'] or offset >= len(active['data']):
                return -errno.ERANGE, b'', 0
            count = min(number(incoming, 16), number(header, 40), len(active['data']) - offset)
            return 0, active['data'][offset:offset + count], offset
        if transfer['cursor'] != len(active['data']) or offset != active['fnv1a64']:
            return -errno.EBADMSG, b'', 0
        self.active = None
        return 0, b'', 0

    def cancel(self):
        active = self.active
        self.active = None
        return dict(token=active['token'] if active else 0, discarded_bytes=len(active['data']) if active else 0,
                    host_snapshot_cleared=True, **CLAIMS)
