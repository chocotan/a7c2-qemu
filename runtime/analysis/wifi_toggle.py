"""Isolated Wi-Fi link switch: guest interface plus host peer, honestly reported.

The camera has no real wireless chip, so "Wi-Fi" here means the isolated USB
Ethernet path between this host and the one VM: the original kernel's usbnet
driver on the guest side, and a host peer that answers ICMP.

Nothing in this module decides success from a command's exit status or from
"we sent something". Enabling counts only when the guest interface actually took
the address *and* the host received a matching echo reply; disabling counts only
when the interface reports down *and* the same host ping stops working.
"""
import re

MOUNT_MODULES = ('mii usbnet cdc_ether rndis_host xhci-hcd xhci-plat-hcd')

LOAD = ('for m in ' + MOUNT_MODULES + '; do /sbin/insmod /usr/kmod/$m.ko 2>/dev/null; done; sleep 3')
ADDRESS = '10.0.0.2'
ALIAS_LOCAL = '10.0.0.1'


def interface_state(text):
    """Parse only usb0's ifconfig stanza, excluding serial command echoes."""
    match = re.search(rb'^usb0\s[^\r\n]*(?:\r?\n[ \t]+[^\r\n]*)*', text, re.M)
    if match is None:
        return {'observed': False, 'configured': False, 'up': None, 'running': None}
    stanza = match[0]
    flags = re.search(rb'flags=\d+<([^>]+)>', stanza)
    if flags:
        words = set(flags[1].split(b','))
    else:
        flags = re.search(rb'^\s+((?:(?:UP|BROADCAST|RUNNING|MULTICAST|LOOPBACK|POINTOPOINT|NOARP)\s+)+)MTU:', stanza, re.M)
        if flags is None:
            return {'observed': True, 'configured': False, 'up': None, 'running': None}
        words = set(flags[1].split())
    address = re.search(rb'\binet (?:addr:)?(\d+\.\d+\.\d+\.\d+)\b', stanza)
    return {'observed': True, 'configured': bool(address and address[1] == ADDRESS.encode()),
            'up': b'UP' in words, 'running': b'RUNNING' in words}


class WifiLink:
    def __init__(self, serial, peer_factory, ping_timeout=10):
        self._serial = serial
        self._peer_factory = peer_factory
        self._ping_timeout = ping_timeout
        self.peer = None
        self.enabled = False
        self._modules_loaded = False

    def _host_ping(self):
        if self.peer is None:
            return None
        if not self.peer.arp_resolve(timeout=self._ping_timeout):
            return None
        return self.peer.ping_guest(timeout=self._ping_timeout)

    def enable(self):
        # Short transactions avoid the interactive shell's physical-line limit.
        if not self._modules_loaded:
            for module in MOUNT_MODULES.split():
                self._serial(f'/sbin/insmod /usr/kmod/{module}.ko 2>/dev/null; true', timeout=30)
            self._serial('sleep 3', timeout=30)
            self._modules_loaded = True
        text = self._serial(f'ifconfig usb0 {ADDRESS} netmask 255.255.255.0 up; '
                            f'ifconfig usb0; true', timeout=60)
        state = interface_state(text)
        configured = state['configured']
        running = state['running']
        if not configured or state['up'] is not True:
            self.enabled = False
            return {'action': 'wifi', 'enabled': True, 'ok': False,
                    'configured': configured, 'interface_up': state['up'],
                    'host_ping': None, 'error': 'guest interface did not take ' + ADDRESS}
        try:
            if self.peer is None:
                self.peer = self._peer_factory()
                self.peer.start()
            ping = self._host_ping()
        except Exception:
            self.close()
            raise
        self.enabled = bool(isinstance(ping, dict) and ping.get('payload_matched') is True)
        result = {'action': 'wifi', 'enabled': True, 'configured': True,
                  'interface_up': state['up'], 'interface_running': running, 'host_ping': ping,
                  'peer_frames_in': self.peer.frames_in,
                  'peer_frames_out': self.peer.frames_out,
                  'ok': self.enabled}
        if not self.enabled:
            result['error'] = 'host ping did not complete'
        return result

    def disable(self):
        text = self._serial('ifconfig usb0 down; ifconfig usb0; true', timeout=30)
        state = interface_state(text)
        interface_down = state['observed'] and state['up'] is False
        # The same host probe must now fail; a still-working ping means the link
        # is not actually down and the switch must not report success.
        probe_attempted = self.peer is not None
        still = self._host_ping()
        # Keep the VM's transport connected. OFF is proved by the real guest
        # interface being down and a fresh failed probe, not by removing a peer.
        self.enabled = False
        ok = bool(interface_down and probe_attempted and still is None)
        result = {'action': 'wifi', 'enabled': False, 'interface_down': interface_down,
                  'host_ping': still, 'probe_attempted': probe_attempted, 'ok': ok}
        if not ok:
            result['error'] = ('interface still reports up' if not interface_down
                               else 'no host probe was available' if not probe_attempted
                               else 'host could still reach the guest')
        return result

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Wi-Fi enabled must be a boolean')
        return self.enable() if enabled else self.disable()

    def close(self):
        if self.peer is not None:
            self.peer.stop()
            self.peer = None
        self.enabled = False
