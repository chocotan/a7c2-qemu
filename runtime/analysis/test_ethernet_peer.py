"""Host tests for the isolated Ethernet peer (no QEMU, no guest).

A fake guest answers ARP and ICMP over a socketpair, so the peer's framing,
checksums and both ping directions are exercised deterministically.
"""
import socket
import struct
import threading
import time

import ethernet_peer as ep

OUR_IP = socket.inet_aton('10.0.0.1')
GUEST_IP = socket.inet_aton('10.0.0.2')
GUEST_MAC = bytes.fromhex('525400123456')


def _arp_reply(frame):
    return (frame[6:12] + GUEST_MAC + b'\x08\x06' + struct.pack('!2HBBH', 1, 0x0800, 6, 4, 2) +
            GUEST_MAC + GUEST_IP + frame[22:28] + OUR_IP)


def _valid_icmp(icmp):
    """The peer's own replies must carry a correct ICMP checksum."""
    return ep.checksum(icmp) == 0


def test_peer_answers_guest_echo_with_valid_checksum():
    peer = ep.EthernetPeer('unused')
    peer.guest_mac = GUEST_MAC
    peer.guest_ip = GUEST_IP
    ours = socket.inet_aton('10.0.0.1')
    payload = b'0123456789abcdef'*3 + b'01234567'
    request = bytes([8, 0, 0, 0]) + struct.pack('!2H', 0x1234, 1) + payload
    request = request[:2] + struct.pack('!H', ep.checksum(request)) + request[4:]
    header = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20+len(request), 0, 0, 64, 1, 0, GUEST_IP, ours)
    header = header[:10] + struct.pack('!H', ep.checksum(header)) + header[12:]
    sent = []
    peer._send = lambda frame: sent.append(frame)
    peer.our_ip = ours
    peer._handle_ipv4(ep.OUR_MAC + GUEST_MAC + b'\x08\x00' + header + request, 14)
    assert len(sent) == 1
    frame = sent[0]
    total = struct.unpack('!H', frame[16:18])[0]
    icmp = frame[14+(frame[14] & 0x0f)*4:14+total]
    assert icmp[0] == 0 and _valid_icmp(icmp), 'echo reply checksum invalid'
    assert icmp[8:] == payload


def _icmp_reply(frame):
    total = struct.unpack('!H', frame[16:18])[0]      # IP total: excludes Ethernet padding
    icmp = bytes([0, 0]) + frame[36:14+total]
    icmp = icmp[:2] + struct.pack('!H', ep.checksum(icmp)) + icmp[4:]
    header = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20+len(icmp), 0, 0, 64, 1, 0, GUEST_IP, OUR_IP)
    header = header[:10] + struct.pack('!H', ep.checksum(header)) + header[12:]
    return frame[6:12] + GUEST_MAC + b'\x08\x00' + header + icmp


def fake_guest(sock, stop):
    buffer = b''
    while not stop.is_set():
        try:
            chunk = sock.recv(65536)
        except OSError:
            return
        if not chunk:
            return
        buffer += chunk
        while len(buffer) >= 4:
            (length,) = struct.unpack('!I', buffer[:4])
            if len(buffer) < 4+length:
                break
            frame, buffer = buffer[4:4+length], buffer[4+length:]
            if frame[12:14] == b'\x08\x06' and struct.unpack('!H', frame[20:22])[0] == 1:
                out = _arp_reply(frame)
            elif frame[12:14] == b'\x08\x00' and frame[23] == 1 and frame[30:34] == GUEST_IP:
                out = _icmp_reply(frame)
            else:
                continue
            out = out + b'\0'*max(0, 60-len(out))
            sock.sendall(struct.pack('!I', len(out)) + out)


def test_peer_arp_and_both_ping_directions():
    peer = ep.EthernetPeer('unused')
    left, right = socket.socketpair()
    peer.sock = left
    stop = threading.Event()
    threading.Thread(target=peer._serve, daemon=True).start()
    threading.Thread(target=fake_guest, args=(right, stop), daemon=True).start()
    try:
        assert peer.arp_resolve(timeout=3) == GUEST_MAC
        reply = peer.ping_guest(timeout=3)
        assert reply and reply['payload_matched'], reply
        assert peer.echo_replies, 'host->guest echo reply not recorded'
        assert not peer.errors
    finally:
        stop.set()
        left.close()
        right.close()


def test_cached_reply_cannot_satisfy_a_new_ping():
    peer = ep.EthernetPeer('unused')
    peer.echo_replies.append((0x4201, 1, b'qemu-usb-net-icmp'))
    peer._send = lambda frame: None
    assert peer.ping_guest(timeout=0.01) is None


def test_a_previous_probe_reply_cannot_prove_reachability_after_link_down():
    peer = ep.EthernetPeer('unused')
    frames = []

    def answer_once(frame):
        frames.append(frame)
        if len(frames) == 1:
            peer._handle_ipv4(_icmp_reply(frame), 14)

    peer.guest_mac = GUEST_MAC
    peer._send = answer_once
    assert peer.ping_guest(timeout=1)['payload_matched']
    assert peer.ping_guest(timeout=0.01) is None
    assert frames[0][38:42] != frames[1][38:42]  # sequence and fresh nonce
