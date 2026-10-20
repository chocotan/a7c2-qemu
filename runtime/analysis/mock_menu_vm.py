"""Test subprocess only: never starts QEMU or acquires its lock."""
import os
from pathlib import Path
import socket
import sys
import time
from menu_live import receive_message, send_message, snapshot_message


def main():
    assert int(os.environ['MENU_CONTROL_FD']) >= 20, 'control fd must not collide with flock fd9'
    mode = sys.argv[1] if len(sys.argv) > 1 else 'normal'
    with socket.socket(fileno=int(os.environ['MENU_CONTROL_FD'])) as sock:
        if mode == 'exit':
            return 7
        if mode == 'startup-hang':
            time.sleep(60)
            return 0
        run = sys.argv[2] if len(sys.argv) > 2 else 'MOCK'
        if mode in ('idle-crash', 'inflight-crash'):
            (Path(run) / 'console.log').write_text('normal startup\n')
        send_message(sock, {'type': 'ready', 'run': run})
        snapshot = snapshot_message((Path(__file__).parent / 'fixtures/headless-osd.b64').read_bytes())
        while True:
            command = receive_message(sock, timeout=600)
            if mode in ('idle-crash', 'inflight-crash'):
                if mode == 'idle-crash':
                    send_message(sock, {'type': 'key', 'key': command['key']})
                    time.sleep(.1)
                with (Path(run) / 'console.log').open('a') as output:
                    output.write('\nEntering exception monitor.\nException> ')
                time.sleep(60)
                return 1
            if mode == 'hang':
                time.sleep(60)
            time.sleep(.1)
            if mode == 'bad-reply':
                send_message(sock, {'type': 'unexpected'})
            elif mode == 'corrupt':
                send_message(sock, {'type': 'error', 'error': 'MOCK 快照校验失败'})
            elif command['action'] == 'snapshot':
                snapshot['captured_at'] = time.time()
                send_message(sock, snapshot)
            elif command['action']=='export_sd' and mode=='sd-exit':return 9
            elif command['action']=='export_sd' and mode in ('sd-ok','sd-fail','sd-fault','sd-cleanup-hang'):
                assert command=={'action':'export_sd'},'private shutdown flag leaked onto wire'
                if mode=='sd-fault':
                    (Path(run)/'console.log').write_text('OBS GUI_MODEL_FAILED injected during SD export\n')
                    (Path(run)/'fault-written').write_text('1')
                    while not (Path(run)/'allow-recovery-reply').exists():time.sleep(.02)
                    (Path(run)/'recovery-done').write_text('1')
                send_message(sock,{'type':'sd_export','ok':mode in ('sd-ok','sd-cleanup-hang'),
                                   'error':'injected flush failure' if mode in ('sd-fail','sd-fault') else None})
                if mode=='sd-cleanup-hang':time.sleep(60)
            elif command['action']=='position':
                send_message(sock,{'type':'position','key':command['key'],'position':command['position']})
            else:
                send_message(sock, {'type': 'key', 'key': command['key']})


if __name__ == '__main__':
    raise SystemExit(main())
