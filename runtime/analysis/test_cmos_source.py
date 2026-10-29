"""Host tests for the synthetic imager source (no guest, no sensor)."""
from pathlib import Path
import ctypes
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
MODELS = HERE/'device-models'
SOURCES = [MODELS/'cmos-source.c', MODELS/'test-cmos-source.c']
MASK64 = (1 << 64) - 1


def expected_frame(width, height, bpp, stride, frame_index):
    """Independent byte oracle: deliberate per-lane offsets and x/y asymmetry."""
    frame = bytearray(stride * height)
    for row in range(height):
        for column in range(width):
            base = (column + 3 * row + frame_index * 0x9e3779b9) & MASK64
            for byte in range(bpp):
                frame[row * stride + column * bpp + byte] = (
                    (base >> (8 * (byte % 8))) + byte * 53) & 0xff
    frame[:16] = bytes(16)
    frame[:8] = frame_index.to_bytes(8, 'little')
    checksum = 0xcbf29ce484222325
    for value in frame:
        checksum = ((checksum ^ value) * 0x100000001b3) & MASK64
    frame[8:16] = checksum.to_bytes(8, 'little')
    return bytes(frame)


class CmosSource(unittest.TestCase):
    def test_pattern_contract_under_sanitizers(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary)/'test-cmos-source'
            compiled = subprocess.run(
                ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
                 '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-pthread',
                 *map(str, SOURCES), '-o', str(binary)],
                text=True, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout+compiled.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60,
                                 env={'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                                      'UBSAN_OPTIONS': 'halt_on_error=1',
                                      'PATH': '/usr/bin:/bin'})
            self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
            self.assertIn('PASS', run.stdout)

    def test_python_byte_oracle_and_corruption_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            library_path = Path(temporary)/'libcmos-source.so'
            compiled = subprocess.run(
                ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                 '-fPIC', '-shared', '-pthread', str(MODELS/'cmos-source.c'),
                 '-o', str(library_path)], text=True, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout+compiled.stderr)
            library = ctypes.CDLL(str(library_path))

            class Spec(ctypes.Structure):
                _fields_ = [('width', ctypes.c_uint32), ('height', ctypes.c_uint32),
                            ('bytes_per_pixel', ctypes.c_uint32), ('stride', ctypes.c_uint32)]

            library.cmos_source_init.argtypes = [ctypes.POINTER(Spec)]
            library.cmos_source_fill.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint64]
            library.cmos_source_retire.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
            library.cmos_frame_probe.argtypes = [
                ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
            for function in (library.cmos_source_init, library.cmos_source_fill,
                             library.cmos_source_retire, library.cmos_frame_probe):
                function.restype = ctypes.c_int

            width, height, bpp, stride = 9, 6, 2, 24  # 3:2, six real padding bytes/row
            spec = Spec(width, height, bpp, stride)
            self.assertEqual(library.cmos_source_init(ctypes.byref(spec)), 0)
            total = stride * height
            buffer7 = (ctypes.c_ubyte * total)()
            self.assertEqual(library.cmos_source_fill(buffer7, total, 7), total)
            expected7 = expected_frame(width, height, bpp, stride, 7)
            self.assertEqual(bytes(buffer7), expected7)
            index, checksum = ctypes.c_uint64(), ctypes.c_uint64()
            self.assertEqual(library.cmos_frame_probe(
                buffer7, total, stride, ctypes.byref(index), ctypes.byref(checksum)), 0)
            self.assertEqual(index.value, 7)
            self.assertEqual(checksum.value, int.from_bytes(expected7[8:16], 'little'))
            self.assertEqual(library.cmos_source_retire(buffer7, 7), 0)

            buffer8 = (ctypes.c_ubyte * total)()
            self.assertEqual(library.cmos_source_fill(buffer8, total, 8), total)
            expected8 = expected_frame(width, height, bpp, stride, 8)
            self.assertEqual(bytes(buffer8), expected8)
            self.assertNotEqual(expected7, expected8)
            pixel = slice(stride + 2 * bpp, stride + 3 * bpp)
            transposed = slice(2 * stride + bpp, 2 * stride + 2 * bpp)
            self.assertNotEqual(expected8[pixel], expected8[transposed])
            self.assertEqual(len(set(expected8[pixel])), bpp)
            for lane in range(bpp):
                self.assertNotEqual(expected7[pixel][lane], expected8[pixel][lane])

            for name, offset in (('generation', 0), ('checksum', 8),
                                 ('payload', stride), ('padding', stride + width * bpp)):
                with self.subTest(corruption=name):
                    corrupt = bytearray(expected8)
                    corrupt[offset] ^= 1
                    candidate = (ctypes.c_ubyte * total).from_buffer_copy(corrupt)
                    bad_index, bad_sum = ctypes.c_uint64(123), ctypes.c_uint64(456)
                    self.assertEqual(library.cmos_frame_probe(
                        candidate, total, stride, ctypes.byref(bad_index), ctypes.byref(bad_sum)), -84)
                    self.assertEqual((bad_index.value, bad_sum.value), (123, 456))
            self.assertEqual(library.cmos_source_retire(buffer8, 8), 0)

    def test_source_is_labelled_synthetic(self):
        """The header must keep saying this is a test pattern, not sensor data."""
        header = (HERE/'device-models'/'cmos-source.h').read_text()
        self.assertIn('TEST PATTERN', header)
        self.assertIn('never be', header)


if __name__ == '__main__':
    unittest.main()
