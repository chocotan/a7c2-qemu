"""Host-side Ethernet peer for the isolated USB network.

Talks to QEMU's `-netdev stream` endpoint, which frames every packet with a
4-byte big-endian length (net/socket.c: net_socket_send -> net_fill_rstate).
Sending bare Ethernet frames makes QEMU read a frame header as a huge length
and silently wait for data, so the length prefix is part of the protocol.

The guest's usb0 then runs on a link that exists only between this process and
the guest. No host namespace, TAP device or bridge is involved.

Implemented here (not in the guest): ARP request/answer, ICMP echo request
(host -> guest, proving the host can reach the guest) and ICMP echo reply
(guest -> host, proving the guest can reach the host).
"""
import secrets
import socket
import struct
import threading
import time

OUR_MAC = bytes.fromhex('5a0000000001')
BROADCAST = b'\xff' * 6


def checksum(data):
    if len(data) % 2:
        data += b'\0'
    total = sum(struct.unpack('!%dH' % (len(data)//2), data))
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return (~total) & 0xffff


class EthernetPeer:
    def __init__(self, path, our_ip='10.0.0.1', guest_ip='10.0.0.2', connect_timeout=20):
        self.path = str(path)
        self.our_ip = socket.inet_aton(our_ip)
        self.guest_ip = socket.inet_aton(guest_ip)
        self.connect_timeout = connect_timeout
        self.sock = None
        self.thread = None
        self.stopping = threading.Event()
        self.guest_mac = None
        self.frames_in = 0
        self.frames_out = 0
        self.arp_requests = 0
        self.arp_replies = 0
        self.echo_replies = []      # (id, seq, payload) from guest
        self.ping_sequence = 0
        self.echo_requests = 0      # from guest (guest pinging us)
        self.answered_requests = 0
        self.errors = []
        self.lock = threading.Lock()

    # ---- plumbing -----------------------------------------------------
    def start(self):
        deadline = time.monotonic() + self.connect_timeout
        while True:
            candidate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                candidate.connect(self.path)
                self.sock = candidate
                break
            except OSError as error:
                candidate.close()
                if time.monotonic() > deadline:
                    raise RuntimeError(f'cannot connect to isolated netdev: {error}')
                time.sleep(0.1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def _send(self, frame):
        if self.sock is None:
            raise RuntimeError('peer not started')
        # net_socket_fd_init_stream -> net_socket_send -> net_fill_rstate:
        # 4-byte big-endian length, then the frame bytes.
        self.sock.sendall(struct.pack('!I', len(frame)) + frame)
        with self.lock:
            self.frames_out += 1

    def _serve(self):
        buffer = b''
        while not self.stopping.is_set():
            try:
                chunk = self.sock.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buffer += chunk
            while len(buffer) >= 4:
                (length,) = struct.unpack('!I', buffer[:4])
                if length > 65536:
                    raise RuntimeError(f'implausible stream frame length {length}')
                if len(buffer) < 4+length:
                    break
                frame, buffer = buffer[4:4+length], buffer[4+length:]
                try:
                    self._handle(frame)
                except Exception as error:      # a malformed frame must not stop the peer
                    self.errors.append(f'{type(error).__name__}: {error}')

    # ---- protocols ----------------------------------------------------
    def _handle(self, frame):
        with self.lock:
            self.frames_in += 1
        ethertype = frame[12:14] if frame[12:14] != b'\x81\x00' else frame[16:18]
        offset = 14 if frame[12:14] != b'\x81\x00' else 18
        if ethertype == b'\x08\x06':
            self._handle_arp(frame, offset)
        elif ethertype == b'\x08\x00':
            self._handle_ipv4(frame, offset)

    def _handle_arp(self, frame, offset):
        # ARP payload: htype, ptype, hlen(1), plen(1), oper(2), then addresses.
        htype, ptype = struct.unpack('!2H', frame[offset:offset+4])
        hlen, plen = frame[offset+4], frame[offset+5]
        oper = struct.unpack('!H', frame[offset+6:offset+8])[0]
        if (htype, ptype, hlen, plen) != (1, 0x0800, 6, 4):
            return
        sha = frame[offset+8:offset+14]
        spa = frame[offset+14:offset+18]
        tpa = frame[offset+24:offset+28]
        with self.lock:
            self.guest_mac = sha
        if oper == 1:
            with self.lock:
                self.arp_requests += 1
            if tpa != self.our_ip:
                return
            reply = sha + OUR_MAC + b'\x08\x06' + struct.pack('!2HBBH', 1, 0x0800, 6, 4, 2)
            reply += OUR_MAC + self.our_ip + sha + spa
            self._send(reply + b'\0'*max(0, 60-len(reply)))
        elif oper == 2:
            with self.lock:
                self.arp_replies += 1

    def _handle_ipv4(self, frame, offset):
        header = frame[offset:]
        if len(header) < 20 or header[0] >> 4 != 4:
            return
        ihl = (header[0] & 0x0f) * 4
        total = struct.unpack('!H', header[2:4])[0]
        protocol = header[9]
        src = header[12:16]
        dst = header[16:20]
        payload = header[ihl:total]
        if protocol != 1 or len(payload) < 8:
            return
        kind, code = payload[0], payload[1]
        if kind == 8 and code == 0 and dst == self.our_ip:
            with self.lock:
                self.echo_requests += 1
            # Echo reply: type/code 0, checksum recomputed over the bytes we send,
            # and addressed to the guest MAC (the request's source ADDRESS is not
            # a hardware address). Both mistakes make the guest kernel drop it.
            reply = bytes([0, 0, 0, 0]) + payload[4:]
            reply = reply[:2] + struct.pack('!H', checksum(reply)) + reply[4:]
            self._send(self._ipv4_frame(self.guest_mac, reply))
            with self.lock:
                self.answered_requests += 1
        elif kind == 0 and code == 0 and src == self.guest_ip:
            ident, seq = struct.unpack('!2H', payload[4:8])
            with self.lock:
                self.echo_replies.append((ident, seq, payload[8:]))

    def _ipv4_frame(self, dst_mac, icmp):
        mac = dst_mac or self.guest_mac or BROADCAST
        header = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20+len(icmp), 0, 0, 64, 1, 0,
                            self.our_ip, self.guest_ip)
        header = header[:10] + struct.pack('!H', checksum(header)) + header[12:]
        frame = mac + OUR_MAC + b'\x08\x00' + header + icmp
        return frame + b'\0'*max(0, 60-len(frame))

    # ---- actions ------------------------------------------------------
    def arp_resolve(self, timeout=8):
        request = BROADCAST + OUR_MAC + b'\x08\x06' + struct.pack('!2HBBH', 1, 0x0800, 6, 4, 1)
        request += OUR_MAC + self.our_ip + b'\0'*6 + self.guest_ip
        request += b'\0'*max(0, 60-len(request))          # real NICs pad to the 60-byte minimum
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._send(request)
            time.sleep(0.3)
            if self.guest_mac is not None:
                return self.guest_mac
        return None

    def ping_guest(self, timeout=8, ident=0x4201, payload=b'qemu-usb-net-icmp'):
        # Match this probe only, including replies delayed across sequence wrap.
        with self.lock:
            self.ping_sequence = (self.ping_sequence % 65535) + 1
            sequence = self.ping_sequence
        probe_payload = payload + secrets.token_bytes(8)
        icmp = bytes([8, 0, 0, 0]) + struct.pack('!2H', ident, sequence) + probe_payload
        icmp = icmp[:2] + struct.pack('!H', checksum(icmp)) + icmp[4:]
        started = time.monotonic()
        deadline = started + timeout
        while time.monotonic() < deadline:
            self._send(self._ipv4_frame(None, icmp))
            time.sleep(0.2)
            with self.lock:
                matched = (ident, sequence, probe_payload) in self.echo_replies
            if matched:
                return {'rtt_ms': round((time.monotonic()-started)*1000, 2), 'payload_matched': True}
        return None
