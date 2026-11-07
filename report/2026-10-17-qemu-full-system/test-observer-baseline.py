#!/usr/bin/env python3
"""Explicit baseline identity guards; no build, VM or firmware state changes."""
from pathlib import Path
import ast
import runpy
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BUILD = runpy.run_path(str(HERE / 'build-imaging.py'))['build']


class BaselineIdentity(unittest.TestCase):
    def test_boot_run_replay_preserves_registers_and_relocates_original_page(self):
        tree=ast.parse((HERE/'build-imaging.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build')
        node=next(n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='changes' for t in n.targets))
        before,after=next((a,b) for a,b in ast.literal_eval(node.value) if 'seq_run_continue' in a)
        menu=runpy.run_path(str(HERE/'native-input.py'))['resolve']()/'runtime/analysis'
        self.assertEqual((menu/'menu-observe.c').read_text().count(before),1)
        instructions=''.join(ast.literal_eval(line) for line in after.splitlines())
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'replay.S';obj=source.with_suffix('.o')
            source.write_text('.text\n'+instructions)
            subprocess.run(['clang','--target=aarch64-linux-gnu','-c',str(source),'-o',str(obj)],check=True)
            raw=obj.read_bytes();shoff=struct.unpack_from('<Q',raw,40)[0]
            size,count,names=struct.unpack_from('<HHH',raw,58)
            sections=[struct.unpack_from('<IIQQQQIIQQ',raw,shoff+i*size) for i in range(count)]
            strings=raw[sections[names][4]:sections[names][4]+sections[names][5]]
            text=next(s for s in sections if strings[s[0]:].split(b'\0',1)[0]==b'.text')
            code=raw[text[4]:text[4]+text[5]]
            self.assertEqual(code[:12],bytes.fromhex('fd7bb7a9fd030091f35301a9'))
            self.assertEqual(len(code),36)
            lo,hi,add=struct.unpack_from('<III',code,20)
            self.assertEqual(lo&0xff80001f,0xd2800014)
            self.assertEqual(hi&0xff80001f,0xf2800014)
            delta=((lo>>5)&0xffff)<<(((lo>>21)&3)*16)
            delta|=((hi>>5)&0xffff)<<(((hi>>21)&3)*16)
            self.assertEqual(0x305e9c8+delta,0x4c14000)
            self.assertEqual(add,0x8b140214)

    def test_dependency_trampoline_replays_all_original_prologue_bytes(self):
        tree=ast.parse((HERE/'build-imaging.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build')
        node=next(n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='changes' for t in n.targets))
        changes=ast.literal_eval(node.value)
        before,after=next((a,b) for a,b in changes if 'dep_wait_continue' in a)
        menu=runpy.run_path(str(HERE/'native-input.py'))['resolve']()/'runtime/analysis'
        original=(menu/'menu-observe.c').read_text()
        self.assertEqual(original.count(before),1)
        instructions=''.join(ast.literal_eval(line) for line in after.splitlines() if 'adrp' not in line)
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'replay.S';obj=source.with_suffix('.o')
            source.write_text('.text\n'+instructions)
            subprocess.run(['clang','--target=aarch64-linux-gnu','-c',str(source),'-o',str(obj)],check=True)
            raw=obj.read_bytes();shoff=struct.unpack_from('<Q',raw,40)[0]
            size,count,names=struct.unpack_from('<HHH',raw,58)
            sections=[struct.unpack_from('<IIQQQQIIQQ',raw,shoff+i*size) for i in range(count)]
            strings=raw[sections[names][4]:sections[names][4]+sections[names][5]]
            text=next(s for s in sections if strings[s[0]:].split(b'\0',1)[0]==b'.text')
            self.assertEqual(raw[text[4]:text[4]+text[5]],bytes.fromhex('fd7bbda9e2f301b2625595f2fd030091'))

    def test_source_requires_expected_digest_before_lock(self):
        result = subprocess.run([sys.executable, '-B', str(HERE / 'build-full-system.py'), '--observer-source', 'not-opened.c'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('must be specified together', result.stderr)

    def test_changed_snapshot_refused_before_output_or_compiler(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary);source = base / 'source.c';source.write_text('/* host fixture */\n')
            out = base / 'must-not-exist'
            with self.assertRaisesRegex(ValueError, 'SHA256 differs'):
                BUILD(None, None, out, source, '0' * 64)
            self.assertFalse(out.exists())
            alias = base / 'alias.c';alias.symlink_to(source)
            with self.assertRaisesRegex(ValueError, 'ordinary'):
                BUILD(None, None, out, alias, '0' * 64)


if __name__ == '__main__':
    unittest.main()
