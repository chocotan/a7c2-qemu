#!/usr/bin/env python3
"""Boundary tests for the indexed guest->host container transfer.

A raw serial dump is interleaved with concurrent kernel log output, so the
transfer is framed per 4096-byte block. These tests pin the fail-closed rules:
an incomplete, duplicated, short or foreign chunk must reject rather than
produce a partial snapshot. Integrity beyond this is confirmed by the guest's
own COMMIT hash, which the verifier re-checks.
"""
import base64
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe_immutable_osd',HERE/'probe-immutable-osd.py')
TRANSFER=importlib.util.module_from_spec(spec);spec.loader.exec_module(TRANSFER)

SIZE=639458


def body():
    return bytes((index*31+7)&0xff for index in range(SIZE))


def frame(raw,indices=None):
    lines=[]
    for index in (indices if indices is not None else range(TRANSFER.CHUNK_COUNT)):
        block=raw[index*TRANSFER.CHUNK_BYTES:(index+1)*TRANSFER.CHUNK_BYTES]
        lines.append(b'OSDCHUNK %d %s\r\n'%(index,base64.b64encode(block)))
    return b''.join(lines)


class ContainerTransfer(unittest.TestCase):
    def setUp(self):
        self.raw=body()

    def test_complete_transfer_roundtrips_with_interleaved_log_noise(self):
        region=b'[  123.456] kernel chatter\r\n'+frame(self.raw)+b'/ # echo\r\n'
        self.assertEqual(TRANSFER.reassemble(region,SIZE),self.raw)

    def test_fnv_matches_the_guest_commit_hash(self):
        self.assertEqual(TRANSFER.fnv1a64(self.raw),TRANSFER.fnv1a64(body()))

    def test_missing_chunk_is_rejected(self):
        indices=[i for i in range(TRANSFER.CHUNK_COUNT) if i!=7]
        with self.assertRaisesRegex(ValueError,'Incomplete transfer'):
            TRANSFER.reassemble(frame(self.raw,indices),SIZE)

    def test_two_usable_copies_of_one_chunk_are_rejected(self):
        # Two different payloads that both decode to the full block are
        # ambiguous; guessing one would be silent corruption.
        other=bytes((byte^0xff) for byte in self.raw[:TRANSFER.CHUNK_BYTES])
        region=frame(self.raw)+b'OSDCHUNK 3 '+base64.b64encode(other)+b'\r\n'
        with self.assertRaisesRegex(ValueError,'usable copies'):
            TRANSFER.reassemble(region,SIZE)

    def test_interrupted_line_is_recovered_from_the_second_pass(self):
        # Concurrent kernel output truncates a line; the repeat pass carries a
        # clean copy, and only the full-length candidate is used.
        truncated=base64.b64encode(self.raw[2*TRANSFER.CHUNK_BYTES:2*TRANSFER.CHUNK_BYTES+1000])
        region=frame(self.raw)+b'OSDCHUNK 2 '+truncated+b'\r\nOSDCHUNK 2 '+ \
               base64.b64encode(self.raw[2*TRANSFER.CHUNK_BYTES:3*TRANSFER.CHUNK_BYTES])+b'\r\n'
        self.assertEqual(TRANSFER.reassemble(region,SIZE),self.raw)

    def test_only_a_truncated_copy_is_rejected(self):
        truncated=base64.b64encode(self.raw[5*TRANSFER.CHUNK_BYTES:5*TRANSFER.CHUNK_BYTES+700])
        lines=frame(self.raw).split(b'\r\n')
        lines[5]=b'OSDCHUNK 5 '+truncated
        with self.assertRaisesRegex(ValueError,'usable copies'):
            TRANSFER.reassemble(b'\r\n'.join(lines),SIZE)

    def test_hash_skips_the_stored_digest_field(self):
        # The guest helper reads bytes 40..47 back as zero while hashing, so the
        # transfer check must not hash the stored digest verbatim.
        baseline=TRANSFER.fnv1a64(self.raw)
        for filler in (b'\xff'*8,b'\x00'*8,b'\x5a'*8):
            with self.subTest(filler=filler[:1]):
                changed=bytearray(self.raw);changed[40:48]=filler
                self.assertEqual(TRANSFER.fnv1a64(bytes(changed)),baseline)
        mutated=bytearray(self.raw);mutated[39]^=0xff;mutated[48]^=0xff
        self.assertNotEqual(TRANSFER.fnv1a64(bytes(mutated)),baseline)
        same=bytearray(self.raw);same[41]=0x5a
        self.assertEqual(TRANSFER.fnv1a64(bytes(same)),baseline)

    def test_identical_duplicate_is_tolerated(self):
        block=self.raw[:TRANSFER.CHUNK_BYTES]
        region=frame(self.raw)+b'OSDCHUNK 0 '+base64.b64encode(block)+b'\r\n'
        self.assertEqual(TRANSFER.reassemble(region,SIZE),self.raw)

    def test_short_or_oversized_block_is_rejected(self):
        for index,replacement in ((0,b'AAAA'),(TRANSFER.CHUNK_COUNT-1,b'A'*(TRANSFER.CHUNK_BYTES//3*4+8))):
            with self.subTest(index=index):
                lines=frame(self.raw).split(b'\r\n')
                lines[index]=f'OSDCHUNK {index} '.encode()+replacement
                with self.assertRaisesRegex(ValueError,'usable copies'):
                    TRANSFER.reassemble(b'\r\n'.join(lines),SIZE)

    def test_non_base64_and_absent_chunks_are_rejected(self):
        for region in (b'',b'OSDCHUNK 0 not-base64!\r\n',frame(self.raw,b'') or b''):
            with self.subTest(region=region[:24]):
                with self.assertRaises(ValueError):
                    TRANSFER.reassemble(region,SIZE)

    def test_stale_chunk_count_constant_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Chunk count constant is stale'):
            TRANSFER.reassemble(frame(self.raw),SIZE-TRANSFER.CHUNK_BYTES)

    def test_echoed_command_block_is_not_mistaken_for_the_payload(self):
        # The camera console echoes the typed loop before running it, so both
        # markers appear twice; only the trailing pair is real output.
        echo=(b'for file in /log/qemu/immutable-osd/aa-*.hosd\r\ndo\r\n'
              b'echo OSD_EXPORT_BEGIN_aa\r\necho OSD_EXPORT_END_aa\r\ndone\r\n')
        console=b'OSD_IMMUTABLE_COMMIT nonce=aa\r\n'+echo+b'OSD_EXPORT_BEGIN_aa\r\n'+frame(self.raw)+b'OSD_EXPORT_END_aa\r\n'
        commit_end=console.index(b'\r\n')
        region=TRANSFER.export_region(console,b'aa',commit_end)
        self.assertEqual(TRANSFER.reassemble(region,SIZE),self.raw)

    def test_export_before_the_commit_record_is_rejected(self):
        console=b'OSD_EXPORT_BEGIN_aa\r\n'+frame(self.raw)+b'OSD_EXPORT_END_aa\r\n'
        late=len(console)
        with self.assertRaisesRegex(ValueError,'does not follow'):
            TRANSFER.export_region(console,b'aa',late)

    def test_export_command_frames_every_chunk_on_one_line(self):
        command=TRANSFER.export_command('ab'*16)
        self.assertIn('for pass in 1 2',command)
        self.assertIn(f'while [ $index -lt {TRANSFER.CHUNK_COUNT} ]',command)
        self.assertIn(f'bs={TRANSFER.CHUNK_BYTES}',command)
        self.assertIn('OSD_EXPORT_BEGIN_'+'ab'*16,command)
        self.assertIn('echo "OSDCHUNK $index $block"',command)
        # The raw dump form is what concurrent kernel output corrupts.
        self.assertNotIn('openssl base64 -A -in "$file" || exit',command)


if __name__=='__main__':unittest.main()
