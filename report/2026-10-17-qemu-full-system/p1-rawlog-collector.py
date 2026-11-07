#!/usr/bin/env python3
"""Strict offline decoder for the selected P1 post-wait envelope; no guest I/O."""
import base64
import hashlib
import os
from pathlib import Path
import re
import runpy
import stat

HERE = Path(__file__).resolve().parent
TAIL = 'original-p1-stock-tail-v1'
BROKER = 'virtual-p1-pmbp-block-slice-v1'
PATHS = {'tail': '/simulation/p1-tail/receiver.log', 'broker': '/simulation/pmbp-runtime/receiver.log'}
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'
NUMBER = r'(?:0|[1-9][0-9]{0,19})'

def terminal(raw):
    return re.search(rb'^P1_RAWLOG_COLLECT_RC pid=[1-9][0-9]* rc=[0-9]+\r?\n', raw, re.M) is not None


def decode(raw, *, tail_profile, pmbp_profile=None, paths=None):
    if tail_profile != TAIL or pmbp_profile not in (None, BROKER):
        raise ValueError('Exact explicit rawlog selection required')
    if not isinstance(raw, bytes):
        raise ValueError('Expected untouched serial bytes')
    paths = PATHS if paths is None else paths
    lines = raw.split(b'\n')
    lines = [line[:-1] if line.endswith(b'\r') else line for line in lines]
    def unique(prefix, pattern):
        found = [(i, re.fullmatch(pattern, line)) for i, line in enumerate(lines) if line.startswith(prefix)]
        if len(found) != 1 or found[0][1] is None:
            raise ValueError('Missing, duplicate or malformed ' + prefix.decode('ascii'))
        return found[0]
    start, sm = unique(b'UPDATE_SD_RECEIVER_START ', rb'UPDATE_SD_RECEIVER_START pid=([1-9][0-9]*) original=/usr/bin/sdfileinput\.elf')
    waited, wm = unique(b'UPDATE_SD_RECEIVER_WAIT ', rb'UPDATE_SD_RECEIVER_WAIT pid=([1-9][0-9]*) rc=([0-9]+)')
    exited, em = unique(b'UPDATE_SD_RECEIVER_EXIT ', rb'UPDATE_SD_RECEIVER_EXIT pid=([1-9][0-9]*) rc=([0-9]+)')
    collected, cm = unique(b'P1_RAWLOG_COLLECT_RC ', rb'P1_RAWLOG_COLLECT_RC pid=([1-9][0-9]*) rc=0')
    pid, rc = int(sm[1]), int(wm[2])
    if not 0 <= rc <= 255 or wm[1] != sm[1] or em.groups() != wm.groups() or cm[1] != sm[1]:
        raise ValueError('Original receiver start/wait/exit/collector identity differs')
    begin, bm = unique(b'P1_RAWLOG BEGIN ', ('P1_RAWLOG BEGIN nonce=(' + UUID + ') nonce_source=proc-uuid actor=guest-postwait pid=(' + NUMBER + ') wait_rc=(' + NUMBER + ') files=([12]) broker=(off|' + BROKER + ')').encode())
    done, dm = unique(b'P1_RAWLOG DONE ', ('P1_RAWLOG DONE nonce=(' + UUID + ') pid=(' + NUMBER + ') actor=guest-postwait wait_rc=(' + NUMBER + ') rc=0').encode())
    nonce = bm[1].decode()
    broker = pmbp_profile or 'off'
    names = ['tail', 'broker'] if pmbp_profile else ['tail']
    if (not start < waited < exited < begin < done < collected or bm[2] != sm[1] or int(bm[3]) != rc
            or int(bm[4]) != len(names) or bm[5].decode() != broker
            or dm[1] != bm[1] or dm[2] != sm[1] or int(dm[3]) != rc):
        raise ValueError('Envelope nonce, actor, selection or epoch order differs')
    # A partial final line is never a completed record; stray protocol lines are fatal.
    if (collected >= len(lines)-1 or any(len(line) > 512 for line in lines[begin:done+1])
            or any(line.startswith(b'P1_RAWLOG ') for line in lines[:begin] + lines[done+1:])):
        raise ValueError('Stray/partial rawlog envelope')
    cursor = begin + 1
    payloads, metadata = {}, {}
    def take(pattern):
        nonlocal cursor
        if cursor >= done or len(lines[cursor]) > 512:
            raise ValueError('Partial or oversized envelope record')
        match = re.fullmatch(pattern.encode('ascii'), lines[cursor])
        cursor += 1
        if match is None:
            raise ValueError('Malformed, injected or out-of-order rawlog record')
        return match
    for name in names:
        common = ' nonce=' + nonce + ' pid=' + str(pid) + ' name=' + name
        take(re.escape('P1_RAWLOG FILE' + common + ' path=' + paths[name] + ' actor=guest-postwait'))
        prefix = 'P1_RAWLOG BEFORE' + common + ' type=regular links=1 inode=([1-9][0-9]{0,19}) bytes=([1-9][0-9]{0,5}) sha256=([0-9a-f]{64})'
        before = take(prefix)
        length = int(before[2])
        if length > 262144:
            raise ValueError('Rawlog exceeds per-file budget')
        read = take('P1_RAWLOG READ' + common + r' rc=0 diagnostic_rc=0 diagnostic_b64=([A-Za-z0-9+/]*={0,2})')
        try:
            diagnostic = base64.b64decode(read[1], validate=True)
        except ValueError as error:
            raise ValueError('Invalid raw read diagnostic') from error
        if base64.b64encode(diagnostic) != read[1]:
            raise ValueError('Noncanonical raw read diagnostic')
        chunks = []
        for seq in range((4*((length+2)//3) + 63)//64):
            m = take('P1_RAWLOG DATA' + common + ' seq=' + str(seq) + r' b64=([A-Za-z0-9+/]{1,64}={0,2})')
            chunks.append(m[1])
        encoded = b''.join(chunks)
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ValueError('Invalid rawlog base64') from error
        if (base64.b64encode(data) != encoded or len(data) != length
                or hashlib.sha256(data).hexdigest().encode() != before[3]):
            raise ValueError('Rawlog length/base64/hash differs')
        after = take(prefix.replace(' BEFORE', ' AFTER'))
        if after.groups() != before.groups():
            raise ValueError('Rawlog inode/length/hash changed during collection')
        take('P1_RAWLOG END' + common + ' encode_rc=0 meta_rc=0 hash_rc=0 rc=0')
        payloads[name] = data
        metadata[name] = dict(path=paths[name], inode=int(before[1]), bytes=length, sha256=before[3].decode(), read_diagnostic_b64=read[1].decode())
    if cursor != done or sum(len(data) for data in payloads.values()) > 524288:
        raise ValueError('Duplicate/extra bytes or total log budget exceeded')
    tail_lines = payloads['tail'].splitlines(keepends=True)
    if not tail_lines or not payloads['tail'].endswith(b'\n'):
        raise ValueError('Partial Tail file')
    receipts = []
    for line in tail_lines:
        match = re.fullmatch(rb'P1_TAIL pid=([1-9][0-9]*) family=([0-7]) op=([^ ]+) (.*) rc=(-?[0-9]+) errno=(-?[0-9]+) caller=(\S+)\n', line)
        if match is None or int(match[1]) != pid:
            raise ValueError('Malformed/cross-PID Tail file')
        if match[3] == b'receipt':
            if match[2] != b'7' or b' epoch_closed=1 install_verified=0' not in b' ' + match[4]:
                raise ValueError('Tail receipt does not close this epoch')
            receipts.append(line.rstrip(b'\n'))
    if len(receipts) != 1 or receipts[0] != tail_lines[-1].rstrip(b'\n'):
        raise ValueError('Missing/duplicate/nonfinal original Tail destructor receipt')
    serial_tail = [line for line in lines[start+1:waited] if line.startswith(b'P1_TAIL ')]
    if serial_tail != [line.rstrip(b'\n') for line in tail_lines]:
        raise ValueError('Raw Tail file differs from original serial epoch')
    if pmbp_profile:
        data = payloads['broker']
        if not data.endswith(b'\n'):
            raise ValueError('Partial broker file')
        for line in data.splitlines():
            m = re.fullmatch(rb'PMBP_RAW pid=([1-9][0-9]*) (PMBP_(?:CHECKPOINT|IO) .+)', line)
            if m is None or int(m[1]) != pid:
                raise ValueError('Broker actor is unknown or crosses PID')
            for actor in re.findall(rb'(?:^| )pid=([0-9]+)(?: |$)', m[2]):
                if int(actor) != pid:
                    raise ValueError('Broker payload crosses PID')
    return dict(receiver_pid=pid, receiver_returncode=rc, nonce=nonce, metadata=metadata, payloads=payloads)


def collect_postrun(raw, output, *, tail_profile, pmbp_profile=None, ledger=None):
    result = dict(schema='p1-rawlogs-postwait-v1', rawlogs_complete=False,
                  installation_verified=False, serial_sha256=hashlib.sha256(raw).hexdigest())
    try:
        decoded = decode(raw, tail_profile=tail_profile, pmbp_profile=pmbp_profile)
        output = Path(output)
        output.mkdir(mode=0o700, exist_ok=False)
        files = {}
        for name, data in decoded['payloads'].items():
            path = output / (name + '.log')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            readback = path.read_bytes()
            if (readback != data or stat.S_IMODE(path.lstat().st_mode) != 0o600
                    or hashlib.sha256(readback).hexdigest() != decoded['metadata'][name]['sha256']):
                raise ValueError('Local rawlog readback differs')
            files[name] = dict(decoded['metadata'][name], local_path=str(path))
        result.update(rawlogs_complete=True, receiver_pid=decoded['receiver_pid'],
                      receiver_returncode=decoded['receiver_returncode'], nonce=decoded['nonce'], files=files)
        # The merger receives untouched serial plus the existing independent disk-range ledger.
        result['tail_postrun'] = runpy.run_path(str(HERE / 'p1-tail-source.py'))['postrun'](
            raw, rawlogs_complete=True, receiver_pid=decoded['receiver_pid'], ledger=ledger)
    except (ValueError, OSError) as error:
        result.update(rawlogs_complete=False, blocked=type(error).__name__ + ': ' + str(error))
    return result
