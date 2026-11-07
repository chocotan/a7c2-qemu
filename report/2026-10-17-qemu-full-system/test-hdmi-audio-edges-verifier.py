#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import runpy
import struct
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
VERIFY=runpy.run_path(str(HERE/'verify-hdmi-audio-connections.py'))['verify']


def envelope(command,size,flags,S,P,tail=b''):
    # 32 B header: reply SID, magic, version, size, body offset, total, zero, frame, cmd, body, flags.
    wire=struct.pack('<IIHHIII4H',0,0xa0a0a0a0,1,size,24,size,0,0x1000,command,size-32,flags)
    wire+=struct.pack('<4I',*S)+struct.pack('<4I',*P)+tail
    assert len(wire)==size
    return wire.hex()


def envelope_s(command,size,flags,S,tail):
    wire=struct.pack('<IIHHIII4H',0,0xa0a0a0a0,1,size,24,size,0,0x1000,command,size-32,flags)
    wire+=struct.pack('<4I',*S)+tail
    assert len(wire)==size
    return wire.hex()


def edge_logs(prefix,S,P,source_slot,peer_slot,byte,other,own=1,skip=None,waiter=1):
    rows=[]
    def add(tag,text):rows.append('OBS '+prefix+tag+' '+text)
    add('REQUEST',f'tid=526 source={S[3]:#x} destination={S[3]:#x} pointer=0x1 bytes=64 raw={envelope(1,64,2,S,P)}')
    add('PEER_REQUEST',f'tid=526 source={S[3]:#x} destination={P[3]:#x} pointer=0x2 bytes=64 raw={envelope(0x100,64,1,S,P)}')
    add('PEER_REPLY',f'tid=526 source={P[3]:#x} destination={S[3]:#x} pointer=0x3 bytes=72 raw={envelope(0x8100,72,1,S,P,struct.pack("<II",0,0))}')
    add('YC_DIRECTION_CHECK',f'command=0x8100 selected_group=source type={P[0]} dir=2 index={S[2]} format_published=0 buffer_allocated=0')
    add('EVENT6_CONSUMED',f'source={S[0]},2,{S[2]},{S[3]:#x} peer={P[0]},1,{P[2]},{P[3]:#x} status=0')
    add('REPLY_QUEUED',f'tid=526 source={S[3]:#x} destination={S[3]:#x} pointer=0x4 bytes=56 raw={envelope_s(0x8001,56,2,S,struct.pack('<II',0,0))}')
    add('NATIVE_REPLY_FREE',f'tid=526 sender=526 waiter={waiter} destination={S[3]:#x} expected={S[3]:#x} reply=0x4 bytes=56 command=0x8001 rc=0')
    add('STATE_READBACK',f'tid=526 source_slot={source_slot} source_state=0 source_self={S[0]},{S[1]},{S[2]},{S[3]:#x} '
        f'source_peer={P[0]},{P[1]},{P[2]},{P[3]:#x} peer_slot={peer_slot} peer_state=0 peer_self={P[0]},{P[1]},{P[2]},{P[3]:#x} '
        f'peer_peer={S[0]},{S[1]},{S[2]},{S[3]:#x} source_pending=0 event6_consumed=1 {byte}={own} yc_format_published=0 pixels_consumed=0')
    if skip:rows=[r for r in rows if skip not in r]
    return rows


HDMI=(4,2,0,0x90590818),(4,1,0,0x909a015a)
AUDIO=(5,2,0,0x9058003f),(5,1,0,0x909a015a)


def build(run,hdmi_kw=None,audio_kw=None,enabled=True,sha_ok=True):
    rows=edge_logs('FULL_HDMI_CONNECT_',*HDMI,7,0,'video_connected','audio_connected',**(hdmi_kw or {}))
    rows+=edge_logs('FULL_ADFAUDIO_CONNECT_',*AUDIO,9,1,'audio_connected','video_connected',**(audio_kw or {}))
    console=('\n'.join(rows)+'\n').encode()
    (run/'console.log').write_bytes(console)
    digest=hashlib.sha256(console).hexdigest()
    (run/'result.json').write_text(json.dumps({'state':'observation-completed','terminal_evidence_checked':True,
        'terminal_console_sha256':digest if sha_ok else '0'*64,'camera_startup_verified':False}))
    (run/'inputs.json').write_text(json.dumps({'experiment':{
        'hdmi_connection':'control' if enabled else 'off',
        'adf_audio_connection':'control' if enabled else 'off'}}))


class Edges(unittest.TestCase):
    def test_both_edges_verified_and_distinct_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);build(run)
            proof=VERIFY(run)
            self.assertTrue(proof['fourth_edge_verified'])
            self.assertTrue(proof['fifth_edge_verified'])
            self.assertEqual(proof['edges']['hdmi']['source_slot'],7)
            self.assertEqual(proof['edges']['adf_audio']['source_slot'],9)
            self.assertFalse(proof['camera_startup_verified'])

    def test_missing_waiter_free_foreign_thread_and_short_frame_fail(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);build(run,hdmi_kw={'skip':'NATIVE_REPLY_FREE'})
            with self.assertRaises(ValueError):VERIFY(run)
            build(run,hdmi_kw={'waiter':0})
            with self.assertRaises(ValueError):VERIFY(run)
            build(run);(run/'console.log').write_bytes(
                (run/'console.log').read_bytes().replace(b'bytes=72 raw=',b'bytes=72 raw=00'))
            with self.assertRaises((ValueError,IndexError)):VERIFY(run)

    def test_cross_edge_byte_contamination_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);build(run)
            data=(run/'console.log').read_bytes()
            # AUDIO edge also claiming the VIDEO byte must be refused.
            (run/'console.log').write_bytes(data.replace(b'event6_consumed=1 audio_connected=1',
                                                         b'event6_consumed=1 audio_connected=1 video_connected=1'))
            with self.assertRaises(ValueError):VERIFY(run)

    def test_unchecked_console_and_disabled_edge(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);build(run,sha_ok=False)
            with self.assertRaises(ValueError):VERIFY(run)
            build(run,enabled=False)
            proof=VERIFY(run)
            self.assertTrue(proof['fourth_edge_verified'])
            self.assertFalse(proof['camera_startup_verified'])


if __name__=='__main__':unittest.main()
