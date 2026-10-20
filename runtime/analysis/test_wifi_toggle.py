"""The Wi-Fi switch may not report success it cannot show.

Enabling counts only with the guest address actually taken *and* a matching host
echo reply; disabling counts only when the interface reports down *and* the same
host probe stops working. Command exit status, "we sent it", and a changed
picture are all explicitly not evidence here.
"""
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wifi_toggle', HERE/'wifi_toggle.py')
toggle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toggle)

UP_TEXT = b'usb0      Link encap:Ethernet  HWaddr 52:54:00:12:34:56\n' \
          b'          inet addr:10.0.0.2  Bcast:10.0.0.255  Mask:255.255.255.0\n' \
          b'          UP BROADCAST RUNNING MULTICAST  MTU:1500  Metric:1\n'
DOWN_TEXT = b'usb0      Link encap:Ethernet  HWaddr 52:54:00:12:34:56\n' \
            b'          inet addr:10.0.0.2  Bcast:10.0.0.255  Mask:255.255.255.0\n' \
            b'          BROADCAST MULTICAST  MTU:1500  Metric:1\n'
NO_ADDRESS_TEXT = b'usb0      Link encap:Ethernet  HWaddr 52:54:00:12:34:56\n' \
                  b'          BROADCAST MULTICAST  MTU:1500  Metric:1\n'
PING = {'rtt_ms': 200.1, 'payload_matched': True}


class FakeSerial:
    def __init__(self, up_text, down_text):
        self.up_text = up_text
        self.down_text = down_text
        self.commands = []

    def __call__(self, command, timeout=90, **kwargs):
        self.commands.append(command)
        return self.down_text if 'down' in command else self.up_text


class FakePeer:
    def __init__(self, arp=True, ping=PING):
        self.arp = arp
        self.ping = ping
        self.started = False
        self.stopped = False
        self.frames_in = 4
        self.frames_out = 4

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def arp_resolve(self, timeout=10):
        return self.arp

    def ping_guest(self, timeout=10):
        return self.ping


class Enable(unittest.TestCase):
    def test_enable_needs_the_address_and_a_matching_host_reply(self):
        peer = FakePeer()
        link = toggle.WifiLink(FakeSerial(UP_TEXT, DOWN_TEXT), lambda: peer)
        result = link.enable()
        self.assertTrue(result['ok'])
        self.assertTrue(result['configured'])
        self.assertTrue(result['interface_up'])
        self.assertEqual(result['host_ping'], PING)
        self.assertTrue(peer.started)
        self.assertTrue(link.enabled)

    def test_enable_without_the_address_does_not_start_a_peer_or_claim_success(self):
        peer = FakePeer()
        link = toggle.WifiLink(FakeSerial(NO_ADDRESS_TEXT, DOWN_TEXT), lambda: peer)
        result = link.enable()
        self.assertFalse(result['ok'])
        self.assertFalse(result['configured'])
        self.assertIn('did not take', result['error'])
        self.assertFalse(peer.started)
        self.assertFalse(link.enabled)

    def test_enable_reports_failure_when_the_host_ping_does_not_complete(self):
        peer = FakePeer(ping=None)
        link = toggle.WifiLink(FakeSerial(UP_TEXT, DOWN_TEXT), lambda: peer)
        result = link.enable()
        self.assertTrue(result['configured'])
        self.assertFalse(result['ok'])
        self.assertIsNone(result['host_ping'])
        self.assertFalse(link.enabled)

    def test_enable_without_arp_does_not_even_try_the_ping(self):
        peer = FakePeer(arp=False)
        link = toggle.WifiLink(FakeSerial(UP_TEXT, DOWN_TEXT), lambda: peer)
        result = link.enable()
        self.assertFalse(result['ok'])
        self.assertIsNone(result['host_ping'])


class Disable(unittest.TestCase):
    def _enabled_link(self, ping_after_down):
        peer = FakePeer(ping=ping_after_down)
        link = toggle.WifiLink(FakeSerial(UP_TEXT, DOWN_TEXT), lambda: peer)
        link.enable()
        peer.ping = ping_after_down
        return link, peer

    def test_disable_is_accepted_only_when_the_host_probe_stops_working(self):
        link, peer = self._enabled_link(None)
        result = link.disable()
        self.assertTrue(result['ok'])
        self.assertTrue(result['interface_down'])
        self.assertIsNone(result['host_ping'])
        self.assertFalse(peer.stopped)
        self.assertFalse(link.enabled)

    def test_disable_is_refused_when_the_host_can_still_reach_the_guest(self):
        link, peer = self._enabled_link(PING)
        result = link.disable()
        self.assertFalse(result['ok'])
        self.assertIn('still reach', result['error'])
        self.assertFalse(peer.stopped)

    def test_disable_is_refused_when_the_interface_still_reports_up(self):
        peer = FakePeer(ping=None)
        link = toggle.WifiLink(FakeSerial(UP_TEXT, UP_TEXT), lambda: peer)
        link.enable()
        peer.ping = None
        result = link.disable()
        self.assertFalse(result['ok'])
        self.assertFalse(result['interface_down'])
        self.assertIn('still reports up', result['error'])


class Switch(unittest.TestCase):
    def test_set_enabled_dispatches_both_ways(self):
        peer = FakePeer()
        link = toggle.WifiLink(FakeSerial(UP_TEXT, DOWN_TEXT), lambda: peer)
        self.assertTrue(link.set_enabled(True)['ok'])
        peer.ping = None
        self.assertTrue(link.set_enabled(False)['ok'])

    def test_close_stops_the_peer_without_claiming_a_state(self):
        peer = FakePeer()
        link = toggle.WifiLink(FakeSerial(UP_TEXT, DOWN_TEXT), lambda: peer)
        link.enable()
        link.close()
        self.assertTrue(peer.stopped)
        self.assertFalse(link.enabled)


if __name__ == '__main__':
    unittest.main()
