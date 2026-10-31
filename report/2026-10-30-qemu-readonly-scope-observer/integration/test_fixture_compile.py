"""Opt-in sandboxed assembly/link integration; separate from host parser tests."""
from pathlib import Path
import hashlib
import importlib.util
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('scope_v2_compile_fixture', Path(__file__).with_name('run_fixture.py'))
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


class FixtureCompileTests(unittest.TestCase):
    def test_five_variants_link_with_fixed_callers_entry_and_private_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            commands = []
            variants = (("anchor", False, False, False, False), ("one_byte_mutation", True, False, False, False),
                        ("wrong_lr_only", False, True, False, False), ("producer", False, False, True, False),
                        ("producer_corrupt", False, False, True, True))
            for variant, mutated, wrong_only, producer, producer_mutated in variants:
                with self.subTest(variant=variant):
                    payload = [fixture.tool("clang"), "--target=aarch64-linux-gnu", "-march=armv8-a", "-fuse-ld=lld",
                               "-nostdlib", "-static", "-no-pie", "-x", "assembler-with-cpp",
                               f"-DFIXTURE_MUTATED={int(mutated)}", f"-DFIXTURE_WRONG_LR_ONLY={int(wrong_only)}",
                               f"-DFIXTURE_PRODUCER={int(producer)}",
                               f"-DFIXTURE_PRODUCER_MUTATED={int(producer_mutated)}",
                               "/src/fixture.S", "-Wl,-T,/src/link.ld,-z,max-page-size=4096,--build-id=none",
                               "-Wl,-Map,/out/fixture.map", "-o", "/out/fixture.elf"]
                    result = fixture.launch(output, variant, payload, [(fixture.SOURCE, "/src")], commands, 60)
                    self.assertEqual(result["returncode"], 0, (output / variant / "stderr.bin").read_bytes())
                    sections = fixture.elf_layout(fixture.read_small(output / variant / "fixture.elf"),
                                                  mutated, producer, producer_mutated)
                    self.assertEqual((sections[".callers"][0] + 4, sections[".callers"][0] + 12,
                                      sections[".wrongcaller"][0] + 4), fixture.LRS)
                    self.assertEqual(sections[".observed"][0], fixture.ENTRY)
                    sp = sections[".stack"][0] + 0x4000
                    self.assertEqual(sp, fixture.BASE + 0x200000)
                    self.assertEqual(sp % 16, 0)
                    if producer:
                        self.assertEqual(sections['.producer'][0], fixture.PRODUCER_ENTRY)
                        self.assertEqual(sections['.producertargets'][0], fixture.PRODUCER_TARGETS)
                        self.assertLess(fixture.PRODUCER_TARGETS + 32, fixture.BASE + 0x8000000)
                        self.assertEqual(len(sections['.producer'][1]), 24)
                        callsite, lr = fixture.producer_caller(sections)
                        self.assertEqual(lr, callsite + 4)
                        if not producer_mutated:
                            self.assertEqual(hashlib.sha256(sections['.producer'][1]).hexdigest(),
                                             '3db23e642b92d1592250e675534b988d42c41a0b43581f10aa72d3085a02e74d')
