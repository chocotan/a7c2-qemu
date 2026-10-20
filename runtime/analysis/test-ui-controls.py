#!/usr/bin/env python3
"""Host-only UI assertions and optional isolated mock previews. Never starts QEMU."""
import argparse
from html.parser import HTMLParser
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from menu_control import BASE, ROOT, UI, Server, VM
from menu_live import (KEY_DEFINITIONS, KEYS, SINGLE_STATUS, NATIVE_BUTTONS,
                       control_catalog, key_command, key_definition, live_key_command)


class Buttons(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.keys = []; self.remote = []; self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'button' and 'data-key' in attrs: self.keys.append(attrs['data-key'])
        for name in ('src', 'href'):
            if attrs.get(name, '').startswith(('http:', 'https:', '//')): self.remote.append(attrs[name])


class UIControlsTests(unittest.TestCase):
    def test_catalog_is_the_only_declaration(self):
        catalog = control_catalog()
        self.assertEqual(set(catalog), set(KEY_DEFINITIONS))
        self.assertEqual(KEYS, {name: data['code'] for name, data in catalog.items() if data['code']})
        self.assertEqual(SINGLE_STATUS, {name: data['status'] for name, data in catalog.items() if data['status']})
        self.assertEqual(NATIVE_BUTTONS, {ord(data['native']): name for name, data in catalog.items() if data['native']})
        spec = importlib.util.spec_from_file_location('native_ui_entry', BASE / 'menu-native.py')
        native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
        self.assertIs(native.BUTTONS, NATIVE_BUTTONS)

    def test_every_visible_button_has_metadata_and_every_key_is_visible(self):
        self.assertEqual(UI, ROOT / 'analysis/qemu-control')
        self.assertTrue((UI / 'app.js').is_file())
        html = (UI / 'index.html').read_text()
        buttons = Buttons(html)
        self.assertEqual(set(buttons.keys), set(KEY_DEFINITIONS))
        self.assertEqual(len(buttons.keys), len(set(buttons.keys)))
        self.assertFalse(buttons.remote)
        self.assertIn('未验证', html)
        self.assertIn('真实机身电源事件未模拟', html)
        js = (UI / 'app.js').read_text()
        self.assertIn('entry.verification', js)
        self.assertIn('unavailable_reason', js)
        self.assertNotIn('0x1ab', js)
        self.assertIn("act('key', {key:button.dataset.key})", js)

    def test_unknown_and_unmapped_keys_are_rejected(self):
        for name in ('MENU; touch arbitrary', 'unknown', 'C1'):
            with self.assertRaises(KeyError): key_command(name)
            with self.assertRaises(KeyError): live_key_command(name)
        with self.assertRaises(ValueError):key_command('MODE')
        self.assertIsNone(live_key_command('MODE'))
        catalog = control_catalog()
        for name in ('C1','EXPOSURE_COMP'):
            self.assertFalse(catalog[name]['available'])
            self.assertEqual(catalog[name]['verification'], '未验证')
            self.assertIn('未验证', catalog[name]['unavailable_reason'])

    def test_buttons_generate_real_kevents_and_dials_are_single_send(self):
        with tempfile.TemporaryDirectory(prefix='ui-kevents-') as tmp:
            fake, log = Path(tmp) / 'kevents recorder', Path(tmp) / 'calls'
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$UI_KEY_LOG"\n')
            fake.chmod(0o700)
            for name in Buttons((UI / 'index.html').read_text()).keys:
                entry = key_definition(name)
                if not entry['code']: continue
                for app_input in (False, True):
                    if entry['positions']:
                        for position,value in entry['positions'].items():
                            log.write_text('')
                            command=key_command(name,app_input,position).replace('/simulation/inject-key',shlex.quote(str(fake)))
                            subprocess.run(['bash','-c',command],check=True,env=dict(os.environ,UI_KEY_LOG=str(log)))
                            prefix='--app 0x005503e0 0x005503e0' if app_input else '0x807a0020 0x92840747'
                            self.assertEqual(log.read_text().splitlines(),[f'{prefix} {entry["code"]} 0 {value} 0 {0 if app_input else 1}'])
                            self.assertNotIn('released',command)
                        continue
                    log.write_text('')
                    command = key_command(name, app_input).replace('/simulation/inject-key', shlex.quote(str(fake)))
                    subprocess.run(['bash', '-c', command], check=True, env=dict(os.environ, UI_KEY_LOG=str(log)))
                    prefix = '--app 0x005503e0 0x005503e0' if app_input else '0x807a0020 0x92840747'
                    source = 0 if app_input else 1
                    statuses = [entry['status']] if entry['status'] else ['1', '0']
                    self.assertEqual(log.read_text().splitlines(), [f'{prefix} {entry["code"]} 0 {status} 0 {source}' for status in statuses], name)
                    if entry['status']:
                        self.assertNotIn('sleep', command)
                        self.assertNotIn('released', command)
                        self.assertEqual(entry['verification'] if 'verification' in entry else control_catalog()[name]['verification'], '未验证')

    def test_independent_dial_codes_and_legacy_transport_limit(self):
        for side, status in [('LEFT', '0xfffffc00'), ('RIGHT', '0x400')]:
            commands = [key_command(prefix + '_' + side) for prefix in ('REAR', 'FRONT', 'CONTROL')]
            self.assertEqual(len(set(commands)),3)
            for command,code in zip(commands,('0x10000013','0x1000001c','0x1000001d')):
                self.assertIn(code+' 0 '+status,command)
            for prefix in ('REAR', 'FRONT', 'CONTROL'):
                entry = control_catalog(True)[prefix + '_' + side]
                self.assertFalse(entry['available'])
                self.assertIn('live 文件通道', entry['unavailable_reason'])
                self.assertIsNone(live_key_command(prefix + '_' + side))

    def test_vm_rejects_unavailable_and_non_whitelist_commands(self):
        vm = VM(natural_boot=True)
        vm.state = 'running'
        for command in ({'action':'key', 'key':'C1'}, {'action':'key', 'key':'MENU; whoami'},
                        {'action':'key', 'key':['MENU']}, {'action':'shell'}):
            with self.assertRaises(ValueError): vm.enqueue(command)
        vm.enqueue({'action':'key', 'key':'ENTER'})
        self.assertEqual(vm.commands.get_nowait(), {'action':'key', 'key':'ENTER'})
        vm.enqueue({'action':'key','key':'CONTROL_LEFT'})
        self.assertEqual(vm.commands.get_nowait(),{'action':'key','key':'CONTROL_LEFT'})
        vm.enqueue({'action':'position','key':'MODE','position':'A'})
        self.assertEqual(vm.commands.get_nowait(),{'action':'position','key':'MODE','position':'A'})
        for command in ({'action':'key','key':'MODE'},{'action':'position','key':'MODE','position':'A; arbitrary'},
                        {'action':'position','key':'MODE','position':[]},{'action':'position','key':'UP','position':'P'}):
            with self.assertRaises(ValueError):vm.enqueue(command)
        vm.state = 'exited'
        self.assertEqual(vm.status()['power_state'], 'disconnected')
        self.assertTrue(vm.status()['can_start'])
        self.assertFalse(vm.status()['can_stop'])

    def test_http_keeps_auth_size_and_fixed_whitelist(self):
        vm = VM(natural_boot=True); vm.state = 'running'
        server = Server(vm); worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            def request(path, payload, extra=None):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                headers = {'Origin':server.origin, 'X-Session-Token':server.token, 'Content-Type':'application/json'}
                headers.update(extra or {})
                conn.request('POST', path, json.dumps(payload), headers)
                response = conn.getresponse(); code = response.status; response.read(); conn.close(); return code
            self.assertEqual(server.server_address[0], '127.0.0.1')
            self.assertEqual(request('/api/key', {'key':'ENTER'}), 202)
            self.assertEqual(request('/api/key',{'key':'CONTROL_LEFT'}),202)
            for key in ('C1','MENU; whoami'):
                self.assertEqual(request('/api/key', {'key':key}), 400)
            self.assertEqual(request('/api/key', {'key':'ENTER'}, {'Host':'evil.invalid'}), 403)
            self.assertEqual(request('/api/key', {'key':'ENTER'}, {'Origin':'http://evil.invalid'}), 403)
            self.assertEqual(request('/api/key', {'key':'ENTER'}, {'X-Session-Token':'invalid'}), 403)
            self.assertEqual(request('/api/key', {'key':'ENTER'}, {'Content-Length':'257'}), 413)
        finally:
            server.shutdown(); server.server_close(); worker.join()


def preview(kind, port):
    # Explicit mock subprocess: no QEMU binary, build, flock or hardware access.
    vm = VM([sys.executable, str(BASE / 'mock_menu_vm.py'), 'normal'])
    if kind == 'web':
        server = Server(vm, port)
        print(server.origin + '/#' + server.token, flush=True)
        try: server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt: pass
        finally: server.server_close(); vm.close()
    else:
        from menu_ui import NativeControls
        panel = NativeControls(vm); panel.window.set_title('HOST MOCK · α7C II 机身控制')
        try:
            while panel.pump():
                panel.update(vm.status()); time.sleep(.03)
        finally: vm.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', choices=('web', 'native'))
    parser.add_argument('--port', type=int, default=0)
    args, remaining = parser.parse_known_args()
    if args.preview: preview(args.preview, args.port)
    else: unittest.main(argv=[sys.argv[0]] + remaining, verbosity=2)
