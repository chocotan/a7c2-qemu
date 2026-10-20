from types import SimpleNamespace

from wifi_toggle import WifiLink
from camera_ui import CameraUI

UP = (b'usb0 Link encap:Ethernet\n'
      b' inet addr:10.0.0.2 Mask:255.255.255.0\n'
      b' UP BROADCAST RUNNING MULTICAST MTU:1500\n')
DOWN = UP.replace(b'UP BROADCAST RUNNING', b'BROADCAST')


class Peer:
    frames_in = frames_out = 0

    def __init__(self, reply=None):
        self.reply = reply
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def arp_resolve(self, timeout):
        return True

    def ping_guest(self, timeout):
        return self.reply


def test_command_echo_is_not_interface_configuration():
    echo = (b'ifconfig usb0 10.0.0.2 netmask 255.255.255.0 up; ifconfig usb0; true\n'
            b'ifconfig: usb0: error fetching interface information: No such device\n')
    peer = Peer({'payload_matched': True})
    result = WifiLink(lambda *a, **kw: echo, lambda: peer).enable()
    assert not result['configured']
    assert not peer.started


def test_host_reply_with_wrong_payload_is_not_success():
    peer = Peer({'payload_matched': False, 'rtt_ms': 1})
    assert not WifiLink(lambda *a, **kw: UP, lambda: peer).enable()['ok']


def test_up_without_running_is_not_down():
    text = UP.replace(b'RUNNING ', b'')
    link = WifiLink(lambda *a, **kw: text, lambda: Peer())
    link.peer = Peer()
    result = link.disable()
    assert not result['interface_down']
    assert not result['ok']


def test_no_peer_is_not_evidence_that_the_host_ping_failed():
    assert not WifiLink(lambda *a, **kw: DOWN, lambda: Peer()).disable()['ok']


def test_switch_requires_boolean_at_the_link_boundary():
    import pytest
    link = WifiLink(lambda *a, **kw: UP, lambda: Peer())
    for value in (1, 0, 'false', None):
        with pytest.raises(ValueError):
            link.set_enabled(value)


def test_failed_peer_start_cleans_up_the_peer():
    import pytest

    class BrokenPeer(Peer):
        stopped = False

        def start(self):
            raise RuntimeError('connect failed')

        def stop(self):
            self.stopped = True

    peer = BrokenPeer()
    link = WifiLink(lambda *a, **kw: UP, lambda: peer)
    with pytest.raises(RuntimeError, match='connect failed'):
        link.enable()
    assert peer.stopped
    assert link.peer is None


def test_configuration_transactions_are_short():
    commands = []

    def serial(command, **kwargs):
        commands.append(command)
        return UP

    WifiLink(serial, lambda: Peer({'payload_matched': True})).enable()
    assert all(len(command.encode('ascii')) < 100 for command in commands)


def test_on_off_on_reuses_transport_and_does_not_reload_drivers():
    peer = Peer({'payload_matched': True})
    serial_calls = []
    factory_calls = []

    def serial(command, **kwargs):
        serial_calls.append(command)
        return DOWN if 'usb0 down' in command else UP

    def factory():
        factory_calls.append(True)
        return peer

    link = WifiLink(serial, factory)
    assert link.enable()['ok']
    initial_modules = sum('insmod' in command for command in serial_calls)
    peer.reply = None
    assert link.disable()['ok']
    assert peer.started
    peer.reply = {'payload_matched': True}
    assert link.enable()['ok']
    assert len(factory_calls) == 1
    assert sum('insmod' in command for command in serial_calls) == initial_modules
    link.close()
    assert not peer.started


def test_wifi_rejection_with_no_previous_reply_does_not_crash():
    def reject(command):
        raise ValueError('run has no isolated network')

    ui = SimpleNamespace(closing=False, state={'wifi': None},
                         wifi_switch=SimpleNamespace(set_active=lambda value: None),
                         wifi_syncing=False, wifi_confirmed=False, local_error='',
                         vm=SimpleNamespace(enqueue=reject, status=lambda: {'wifi': None}),
                         update=lambda state: None)
    assert CameraUI.wifi(ui, True) is False
    assert 'run has no isolated network' in ui.local_error


def test_programmatic_switch_changes_do_not_enqueue_requests():
    ui = SimpleNamespace(closing=False, wifi_syncing=True)
    assert CameraUI.wifi(ui, True) is False
