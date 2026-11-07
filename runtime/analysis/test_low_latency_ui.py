"""Product display/input transport checks; synthetic QMP never starts a VM."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from PIL import Image
import pytest
import menu_live

from continuous_lcd import ContinuousLCD
from console_wakeup import ConsoleWakeup


def test_persistent_app_sender_checks_real_pipe_replies_and_returns_shell(tmp_path):
    from persistent_app_input import PersistentAppInput
    script = r'''
import re,sys
for command in sys.stdin:
 marker=re.search(r'APP_INPUT_SHELL_[a-f0-9]+',command).group()
 print('APP_INPUT_SERVER_READY',flush=True)
 for line in sys.stdin:
  fields=line.split()
  if fields[0]=='STOP':print(marker+':0',flush=True);break
  sequence,code,sub,status,extra,origin=map(int,fields)
  print('APP_INPUT_RESULT %d %d'%(
   sequence+1 if code==0x888 else sequence,4 if code==0x999 else 0),flush=True)
'''
    console = tmp_path/'console.log'
    with console.open('wb') as output:
        proc = subprocess.Popen([sys.executable,'-u','-c',script],stdin=subprocess.PIPE,stdout=output,stderr=output)
        transport = PersistentAppInput(proc, console, SimpleNamespace(check=lambda: None))
        try:
            command = menu_live.key_status_command('ENTER', 1, True)
            assert b'APP_INPUT_RESULT 1 0' in transport(command)
            assert transport.active and proc._app_input_transport is transport
            transport.pause(); assert not transport.active and proc.poll() is None
            assert b'APP_INPUT_RESULT 3 0' in transport(menu_live.key_status_command('ENTER', 0, True))
            with pytest.raises(RuntimeError, match='allocation/send failed rc=4'):
                transport('/simulation/inject-key --app 0x5503e0 0x5503e0 0x999 0 1 0 0')
            assert not getattr(proc,'_menu_serial_desynchronized',False)
            with pytest.raises(ValueError, match='requires the original App32 route'):
                transport('/simulation/inject-key --app 1 1 4 0 1 0 0')
            with pytest.raises(ValueError, match='never retry'):
                transport('/simulation/inject-key 1 2 3 0 1 0 0')
            wait = transport._wait
            transport._wait = lambda offset, pattern: wait(offset,pattern,.15)
            with pytest.raises(TimeoutError, match='retain uncertain contact'):
                transport('/simulation/inject-key --app 0x5503e0 0x5503e0 0x888 0 1 0 0')
            assert proc._menu_serial_desynchronized
            with pytest.raises(RuntimeError, match='no retry'):
                transport(command)
        finally:
            proc.stdin.close(); proc.wait(timeout=10)


def test_new_lcd_frame_wakes_gtk_once_and_never_draws_after_close(monkeypatch):
    from camera_ui import CameraUI, GLib
    queued, frames = [], []
    ui = SimpleNamespace(closed=False,lcd_idle_pending=False,
                         vm=SimpleNamespace(status=lambda: {'snapshot': 'latest original frame'}),
                         _read_frame=frames.append)
    ui._present_lcd = lambda: CameraUI._present_lcd(ui)
    monkeypatch.setattr(GLib,'idle_add',lambda callback,**kw: queued.append((callback,kw)))
    CameraUI._notify_lcd(ui); CameraUI._notify_lcd(ui)
    assert frames == [] and len(queued) == 1 and ui.lcd_idle_pending
    assert queued[0][1] == {'priority': GLib.PRIORITY_HIGH_IDLE}
    assert queued[0][0]() is False and not ui.lcd_idle_pending
    assert frames == [{'snapshot':'latest original frame'}]
    ui.closed = True
    CameraUI._notify_lcd(ui); CameraUI._present_lcd(ui)
    assert len(queued) == 1 and len(frames) == 1


def test_navigation_detector_tracks_fixed_focus_text_not_button_geometry():
    import runpy
    from PIL import ImageDraw
    helper = runpy.run_path(str(Path(__file__).resolve().parents[2]/'tools/measure-startup-navigation.py'))
    before = Image.new('RGB',(640,480),'black')
    ImageDraw.Draw(before).rectangle((80,275,560,330),fill=(180,60,0))
    after = before.copy()
    ImageDraw.Draw(after).text((250,298),'language changed',fill='white')
    assert helper['focused_pixels'](before) != helper['focused_pixels'](after)
    assert helper['focused_pixels'](Image.new('RGB',(640,480),'white')) is None
    assert helper['focused_pixels'](Image.new('RGB',(640,480),'black')) is None


def test_fast_tap_keeps_fifty_milliseconds_before_original_release(monkeypatch):
    module = menu_live.camera_input_module()
    events = []
    monkeypatch.setattr(module.time, 'sleep', lambda duration: events.append(('hold', duration)))
    session = module.InputSession(lambda command: events.append(command) or b'checked rc=0', app_input=True)
    result = session.handle(dict(action='camera_input', op='tap', key='ENTER', source='test-tap'))
    assert result['ok'] is True
    assert events == [menu_live.key_status_command('ENTER', 1, True), ('hold', .05),
                      menu_live.key_status_command('ENTER', 0, True)]
    assert result['input_state']['held'] == [] and result['input_state']['uncertain_codes'] == []


def test_live_lcd_does_not_enqueue_automatic_serial_snapshots():
    from camera_ui import SnapshotPoller
    requests = []
    vm = SimpleNamespace(enqueue=requests.append)
    state = dict(state='running', continuous_display=True, pending=0, busy='', events=[])
    poller = SnapshotPoller(); poller.after_input(0)
    assert poller.request(vm, state, 1) is False and requests == []
    assert poller.request(vm, state, 1, force=True) is True
    assert requests == [{'action': 'snapshot'}]


def test_real_frame_decode_hash_and_unchanged_frames_are_separate(tmp_path):
    received = []
    view = ContinuousLCD(tmp_path, None, lambda png, info: received.append((png, info)))
    p = tmp_path / 'lcd.ppm'
    Image.new('RGB', (640, 480), (25, 70, 113)).save(p)
    view._frame(p); view._frame(p)
    assert view.samples == 2 and view.changes == 1 and len(received) == 1
    with Image.open(io.BytesIO(received[0][0])) as image:
        assert image.size == (640, 480) and image.getpixel((0, 0)) == (25, 70, 113)
    Image.new('RGB', (640, 480), (51, 70, 113)).save(p)
    view._frame(p)
    assert received[-1][1]['transport_samples'] == 3
    assert received[-1][1]['changed_frames'] == 2
    assert received[0][1]['sha256'] != received[-1][1]['sha256']


def test_invalid_or_linked_frame_is_not_published(tmp_path):
    view = ContinuousLCD(tmp_path, None, lambda *_: pytest.fail('invalid frame published'))
    p = tmp_path / 'lcd.ppm'; Image.new('RGB', (320, 240)).save(p)
    with pytest.raises(ValueError, match='640x480'): view._frame(p)
    link = tmp_path / 'link.ppm'; link.symlink_to(p)
    with pytest.raises(OSError): view._frame(link)
    p.write_bytes(b'not a screen')
    with pytest.raises(OSError): view._frame(p)
    assert view.samples == view.changes == 0


def test_qmp_error_eof_and_event_budget_are_not_success():
    class Duplex:
        def __init__(self, responses): self.responses = iter(responses); self.requests = []
        def write(self, raw): self.requests.append(json.loads(raw))
        def flush(self): pass
        def readline(self, _): return next(self.responses, b'')
    stream = Duplex([b'{"event":"RESET"}\n', b'{"return":{}}\n'])
    assert ContinuousLCD._command(stream, 'screendump', {'filename':'/out/lcd.ppm'}) == {}
    assert stream.requests == [{'execute':'screendump','arguments':{'filename':'/out/lcd.ppm'}}]
    with pytest.raises(RuntimeError): ContinuousLCD._command(Duplex([b'{"error":{"desc":"bad"}}\n']), 'screendump')
    with pytest.raises(EOFError): ContinuousLCD._command(Duplex([]), 'screendump')
    with pytest.raises(ValueError): ContinuousLCD._command(Duplex([b'{"event":"X"}\n'] * 128), 'screendump')


def test_real_qmp_stream_uses_own_channel_and_joins(tmp_path):
    # Short AF_UNIX name via the same dir-FD connector used by the product.
    from menu_live import connect_in_run
    run = Path('/var/tmp') / ('a7-lcd-' + str(os.getpid()) + '-' + str(time.monotonic_ns()))
    run.mkdir(mode=0o700); path = run / 'lcd-qmp.sock'
    server = socket.socket(socket.AF_UNIX); server.bind(str(path)); server.listen(1)
    requests = []; errors = []; done = threading.Event()
    def peer():
        try:
            with server.accept()[0] as client, client.makefile('rwb') as wire:
                wire.write(b'{"QMP":{"version":{}}}\n'); wire.flush()
                while raw := wire.readline():
                    message = json.loads(raw); requests.append(message['execute'])
                    if message['execute'] == 'screendump':
                        assert message['arguments'] == {'filename':'/out/lcd-continuous.ppm'}
                        Image.new('RGB',(640,480),(len(requests)%255,20,30)).save(run/'lcd-continuous.ppm')
                    wire.write(b'{"return":{}}\n'); wire.flush()
        except Exception as error: errors.append(error)
        finally: done.set()
    worker = threading.Thread(target=peer, daemon=True); worker.start()
    published = threading.Event()
    view = ContinuousLCD(run, SimpleNamespace(pid=os.getpid(), poll=lambda: None),
                         lambda *_: published.set()).start()
    try:
        assert published.wait(3), view.error
        view.stop()
        assert done.wait(1) and not errors
        assert view.samples >= 1 and view.changes >= 1 and view.peer == os.getpid()
        assert requests[0] == 'qmp_capabilities' and 'screendump' in requests
        assert not view.thread.is_alive()
    finally:
        view.stop(); server.close(); worker.join(timeout=1)
        for file in run.iterdir(): file.unlink()
        run.rmdir()


def test_console_completion_uses_real_file_event(tmp_path):
    p = tmp_path/'console.log'; p.write_bytes(b'old')
    with ConsoleWakeup(p) as wake:
        with p.open('ab') as stream: stream.write(b'new'); stream.flush()
        start = time.monotonic(); wake.wait(1)
        assert time.monotonic()-start < .1
    with pytest.raises(ValueError): wake.wait(0)


def test_console_rename_cannot_silently_rebind_transaction(tmp_path):
    p = tmp_path/'console.log'; p.write_bytes(b'old')
    with ConsoleWakeup(p) as wake:
        p.rename(tmp_path/'old.log'); p.write_bytes(b'other console')
        with pytest.raises(OSError, match='bound file'): wake.wait(1)
