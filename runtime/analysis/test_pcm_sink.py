"""Host test for the PCM sink: firmware audio data becomes a verifiable WAV.

The sink records what the device model is handed. It never invents audio and does
not prove that the original firmware produced sound; that stays a device-model
integration question.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
MODELS = HERE/'device-models'
SOURCES = [MODELS/'pcm-sink.c', MODELS/'test-pcm-sink.c']


class PcmSink(unittest.TestCase):
    def test_tone_roundtrip_under_sanitizers(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary)/'test-pcm-sink'
            compiled = subprocess.run(
                ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
                 '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 *map(str, SOURCES), '-lm', '-o', str(binary)],
                text=True, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout+compiled.stderr)
            run = subprocess.run([str(binary)], cwd=temporary, text=True,
                                 capture_output=True, timeout=60,
                                 env={'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                                      'UBSAN_OPTIONS': 'halt_on_error=1',
                                      'PATH': '/usr/bin:/bin'})
            self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
            self.assertIn('PASS', run.stdout)
            self.assertFalse(list(Path(temporary).glob('*.wav')))

    def test_sink_is_documented_as_recording_only(self):
        header = (MODELS/'pcm-sink.h').read_text()
        self.assertIn('does not claim the firmware played anything', header)


if __name__ == '__main__':
    unittest.main()
