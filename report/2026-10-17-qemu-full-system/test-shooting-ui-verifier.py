#!/usr/bin/env python3
"""Boundary tests for the strict shooting-UI verifier.

The verifier must keep failing when nothing attributable was drawn, and must not
accept a run whose only "pixels" are the recycled/empty teardown buffer.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('shooting_ui', HERE / 'verify-shooting-ui.py')
VERIFY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(VERIFY)

BLACK = b'\0' * (640 * 480 * 2)


def structured_frame(seed=1):
    """A frame with >8 distinct RGBA4444 values so it counts as structured."""
    words = bytearray()
    for index in range(640 * 480):
        value = ((index * seed) % 13) << 4 | 0xf
        words += struct.pack('<H', value & 0xffff)
    return bytes(words)


class ShootingUiVerifier(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shooting-ui-test-')
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.console = '\n'.join([
            'OBS CREATE_SCREEN_ARGS call=1 id=0x308 count=28',
            'OBS CREATE_SCREEN_ARGS call=12 id=0x347 count=28',
            'OBS MODE_SLOT4 mode=boot call=1',
            'OBS MODE_SLOT4 mode=shooting call=1',
            'OBS CREATE_SCREEN_ARGS call=16 id=0 count=565',
            'OBS RESOURCE_OPEN a', 'OBS RESOURCE_OPEN b', 'OBS RESOURCE_OPEN c',
            'OBS RESOURCE_LZ_CPU_OK a',
        ] + [f'OBS OSD_TRANSPORT_SEND call={i}' for i in range(30)]
          + ['OBS OSD_HEADLESS_ACK seq=1',
             'OBS FULL_PIN_CONNECT_REQUEST x', 'OBS FULL_PIN_CONNECT_NATIVE_REPLY_FREE x',
             'OBS FULL_SCALAR_CONNECT_REQUEST x', 'OBS FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE x',
             'OBS FULL_ADF_CONNECT_REQUEST x', 'OBS FULL_ADF_CONNECT_NATIVE_REPLY_FREE x',
             'OBS FULL_HDMI_CONNECT_REQUEST x', 'OBS FULL_HDMI_CONNECT_NATIVE_REPLY_FREE x',
             'OBS FULL_ADFAUDIO_CONNECT_REQUEST x', 'OBS FULL_ADFAUDIO_CONNECT_NATIVE_REPLY_FREE x',
             '']).encode()
        (self.run / 'console.log').write_bytes(self.console)
        self.result = {'terminal_evidence_checked': True,
                       'terminal_console_sha256': hashlib.sha256(self.console).hexdigest(),
                       'osd_frames_captured': {}}
        (self.run / 'osd-ap-pixels.bin').write_bytes(BLACK)
        (self.run / 'osd-fb-end.bin').write_bytes(BLACK)

    def write_result(self):
        (self.run / 'result.json').write_text(json.dumps(self.result))

    def add_frame(self, seq, data, name=None):
        name = name or f'osd-frame-{seq:03d}.bin'
        (self.run / name).write_bytes(data)
        self.result['osd_frames_captured'][str(seq)] = {'file': name}

    def inspected_main_pixels(self):
        from PIL import Image
        reference=HERE.parent/'2026-10-19-official-first-setup/evidence/entry-walk-01-shooting-main.png'
        image=Image.open(reference).convert('RGB')
        self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(),
            '2a6ad8bd1d9eb7e6c71e7e70618c0e677e6ab1ac10511dd3da4a90398591968e')
        lookup={}
        for word in range(65536):
            alpha=word&15
            color=tuple((((word>>shift)&15)*17*alpha+7)//15 for shift in (12,8,4))
            lookup[color]=word
        raw=bytearray()
        for color in zip(*[iter(image.tobytes())]*3):
            raw+=struct.pack('<H',lookup[color])
        return bytes(raw)

    def add_snapshot(self,seq,raw,*,pixel_source=None,boot=False):
        # Host-only synthetic container fixture, not guest/camera evidence.
        container=bytearray(128+24930+len(raw));container[:8]=b'HOSDAP02'
        for fmt,offset,value in (('Q',8,seq),('I',16,0x401),('I',20,640),('I',24,480),
                ('I',28,1),('Q',32,0x438a16100),('I',48,614400),('I',52,24930),
                ('I',56,0x1003),('Q',120,seq if pixel_source is None else pixel_source)):
            struct.pack_into('<'+fmt,container,offset,value)
        container[128+24930:]=raw
        hashed=0xcbf29ce484222325
        for byte in container:hashed=((hashed^byte)*0x100000001b3)&0xffffffffffffffff
        struct.pack_into('<Q',container,40,hashed)
        name=f'osd-snapshot-{seq}.hosd';(self.run/name).write_bytes(container)
        self.result['osd_frames_captured'][str(seq)]={'snapshot_file':name}
        record=(f'OBS OSD_HEADLESS_PERSISTED seq={seq} pixel_source_seq={seq} id=0x401 '
                f'phys=0x438a16100 geometry=640x480 bytes=614400 fnv1a64={hashed:016x}\n').encode()
        self.console=record+self.console if boot else self.console+record
        (self.run/'console.log').write_bytes(self.console)
        self.result['terminal_console_sha256']=hashlib.sha256(self.console).hexdigest()
        return name

    def test_zero_teardown_export_needs_attributed_frames(self):
        self.write_result()
        with self.assertRaisesRegex(ValueError, 'No frame was captured'):
            VERIFY.verify(self.run)

    def test_uniform_captured_frames_do_not_count(self):
        self.add_frame(2, BLACK)
        self.write_result()
        with self.assertRaisesRegex(ValueError, 'No attributable shooting pixels'):
            VERIFY.verify(self.run)

    def test_immutable_matching_shooting_frame_allows_zero_teardown(self):
        self.add_snapshot(2,self.inspected_main_pixels())
        self.write_result()
        proof = VERIFY.verify(self.run)
        self.assertTrue(proof['shooting_ui_drawn_verified'])
        self.assertTrue(proof['pixels']['end_export_zero_with_attributed_frames'])
        self.assertIn('2', proof['pixels']['structured_frame_sequences'])
        self.assertFalse(proof['camera_startup_verified'])

    def test_unlogged_sequence_is_not_attributable(self):
        self.add_frame(999,structured_frame());self.write_result()
        with self.assertRaisesRegex(ValueError,'No unique PERSISTED'):
            VERIFY.verify(self.run)

    def test_boot_color_does_not_prove_later_shooting_pixels(self):
        self.add_snapshot(1,self.inspected_main_pixels(),boot=True)
        self.add_snapshot(2,BLACK);self.write_result()
        with self.assertRaisesRegex(ValueError,'No attributable shooting pixels'):
            VERIFY.verify(self.run)

    def test_retained_boot_source_is_rejected_after_screen_transition(self):
        self.add_snapshot(2,self.inspected_main_pixels(),pixel_source=1);self.write_result()
        with self.assertRaisesRegex(ValueError,'earlier pixel source'):
            VERIFY.verify(self.run)

    def test_container_mutation_is_rejected(self):
        name=self.add_snapshot(2,self.inspected_main_pixels())
        raw=bytearray((self.run/name).read_bytes());raw[-1]^=1;(self.run/name).write_bytes(raw)
        self.write_result()
        with self.assertRaisesRegex(ValueError,'container hash differs'):
            VERIFY.verify(self.run)

    def test_sampled_pointer_dump_does_not_prove_a_logged_frame(self):
        self.add_snapshot(2,self.inspected_main_pixels())
        self.add_frame(2,self.inspected_main_pixels());self.write_result()
        with self.assertRaisesRegex(ValueError,'raw pointer dump is unattributed'):
            VERIFY.verify(self.run)

    def test_nonzero_teardown_export_alone_is_not_enough(self):
        (self.run / 'osd-ap-pixels.bin').write_bytes(structured_frame())
        self.write_result()
        with self.assertRaisesRegex(ValueError, 'No frame was captured'):
            VERIFY.verify(self.run)

    def test_changed_console_is_rejected(self):
        self.add_frame(2, structured_frame())
        self.write_result()
        (self.run / 'console.log').write_bytes(self.console + b'extra\n')
        with self.assertRaisesRegex(ValueError, 'Console changed'):
            VERIFY.verify(self.run)

    def test_missing_shooting_screen_is_rejected(self):
        self.add_frame(2, structured_frame())
        (self.run / 'console.log').write_bytes(self.console.replace(b'id=0x347', b'id=0x355'))
        self.result['terminal_console_sha256'] = hashlib.sha256((self.run / 'console.log').read_bytes()).hexdigest()
        self.write_result()
        with self.assertRaisesRegex(ValueError, '0x347'):
            VERIFY.verify(self.run)


if __name__ == '__main__':
    unittest.main()
