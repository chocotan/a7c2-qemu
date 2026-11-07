#!/usr/bin/env python3
"""Synthetic newc path/owner checks; no firmware, private logs or VM required."""
import gzip
import hashlib
from pathlib import Path
import runpy
import stat
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SD = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
TAIL = runpy.run_path(str(HERE / 'p1-tail-source.py'))
NAME = 'simulation/pmbp-runtime/broker.so'
MODE = stat.S_IFREG | 0o600
GOOD = b'GOOD\n'
EXPECTED = {NAME: dict(bytes=len(GOOD), sha256=hashlib.sha256(GOOD).hexdigest(), mode=MODE)}


def member(name, data=GOOD, *, mode=MODE, uid=0, gid=0):
    encoded = name.encode('utf-8') + b'\0'
    fields = (1, mode, uid, gid, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0)
    return (b'070701' + b''.join(f'{value:08x}'.encode() for value in fields)
            + encoded + b'\0' * ((-110 - len(encoded)) % 4)
            + data + b'\0' * ((-len(data)) % 4))


class CpioPaths(unittest.TestCase):
    def archive(self, directory, *members):
        path = Path(directory) / 'synthetic.cpio.gz'
        with gzip.open(path, 'wb') as stream:
            stream.write(b''.join(members) + member('TRAILER!!!', b'', mode=0))
        return path

    def test_canonical_and_utf8_unbound_member(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.archive(root, member(NAME), member('extra/文案', b'extra'))
            self.assertEqual(SD['cpio_readback'](path, EXPECTED), EXPECTED)
            TAIL['_cpio_owners'](path, set(EXPECTED))

    def test_alias_cannot_shadow_pinned_bytes_or_owners(self):
        aliases = ('simulation//pmbp-runtime/broker.so', 'simulation/./pmbp-runtime/broker.so',
                   './' + NAME, '././' + NAME, 'simulation/pmbp-runtime/../pmbp-runtime/broker.so',
                   '/' + NAME, NAME + '\0ignored', '../' + NAME, '')
        for alias in aliases:
            for checker in ('bytes', 'owners'):
                with self.subTest(alias=alias, checker=checker), tempfile.TemporaryDirectory() as root:
                    path = self.archive(root, member(NAME), member(alias, b'EVIL\n', uid=1000))
                    with self.assertRaises(ValueError):
                        if checker == 'bytes':
                            SD['cpio_readback'](path, EXPECTED)
                        else:
                            TAIL['_cpio_owners'](path, set(EXPECTED))

    def test_owner_checker_rejects_alias_only(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.archive(root, member('./' + NAME))
            with self.assertRaises(ValueError):
                TAIL['_cpio_owners'](path, set(EXPECTED))

    def test_existing_content_mode_owner_and_duplicate_gates(self):
        for change in ('hash', 'mode', 'uid', 'duplicate'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as root:
                first = member(NAME, b'EVIL\n' if change == 'hash' else GOOD,
                               mode=MODE ^ 0o100 if change == 'mode' else MODE,
                               uid=1000 if change == 'uid' else 0)
                path = self.archive(root, first, *([member(NAME)] if change == 'duplicate' else []))
                with self.assertRaises(ValueError):
                    if change == 'uid':
                        TAIL['_cpio_owners'](path, set(EXPECTED))
                    else:
                        SD['cpio_readback'](path, EXPECTED)


if __name__ == '__main__':
    unittest.main()
