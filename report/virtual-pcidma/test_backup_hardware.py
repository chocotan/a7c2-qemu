#!/usr/bin/env python3
"""QEMU Backup-sized PCI/ATU data proof; synthetic input, no original CP/capture."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
import tempfile

from test_hardware import hardware, idle_lock, prepare, check_irq, address
from test_hardware import B, PEER, GIC, IRQ, BIT, AP_SOURCE

HERE = Path(__file__).resolve().parent
PCI = AP_ROOT = 0x404000000
DEST = 0x4040ed000
SIZE = 0x15a8f8
WINDOW = 2 * 1024 * 1024
APERTURE = 0xc0000000
ATU = 0xf7300000
CHUNK = 65536
CHANNEL = 4
CONTROL = 0xe1000000
DATA_BAR = 0xe0000000


def configure_control(m):
    ecam=0x3f000000
    port,endpoint=ecam+0x8000,ecam+0x100000
    m.writel(port+0x18,0x00010100)
    m.writel(port+0x20,0xe1f0e000)
    m.writel(port+4,6)
    assert m.readl(endpoint)==0x00051b36
    m.writel(endpoint+0x10,DATA_BAR)
    m.writel(endpoint+0x14,CONTROL)
    m.writel(endpoint+4,6)
    assert m.readl(CONTROL)==0x42555031
    assert m.readl(CONTROL+4)==1 and m.readl(CONTROL+8)==SIZE


def write(m, at, data):
    for offset in range(0, len(data), CHUNK):
        m.write(at + offset, data[offset:offset + CHUNK])


def read(m, at, size):
    return b''.join(m.read(at + offset, min(CHUNK, size - offset))
                    for offset in range(0, size, CHUNK))


def transfer(m, source, size):
    status, channel = prepare(m, 1, CHANNEL)
    m.writel(B + channel + 8, size)
    address(m, channel + 0xc, source)
    address(m, channel + 0x14, DEST)
    m.writel(B + 0x30, CHANNEL)
    return status


def program_atu(m):
    for offset, value in ((0x14, PCI & 0xffffffff), (0x18, PCI >> 32),
                          (8, APERTURE), (0xc, 0), (0x10, APERTURE + WINDOW - 1),
                          (0x20, 0), (4, 0x80000000)):
        m.writel(ATU + offset, value)


def exercise(m, enabled):
    tree = m.qmp('human-monitor-command', {'command-line': 'info qtree'})
    assert ('dev: sony-virtual-atu,' in tree) == enabled
    budget = m.qmp('qom-get', {'path': '/machine/sony-pcidma-test', 'property': 'max-bytes'})
    assert budget == (WINDOW if enabled else 0x100000)
    m.writel(GIC, 1)
    m.writel(GIC + 0x100 + 4 * (IRQ // 32), BIT)
    root = b'\x69' * (DEST - AP_ROOT - 16) + b'\xa5' * 16
    write(m, AP_ROOT, root)
    write(m, DEST, b'\xa5' * (SIZE + 16))
    if not enabled:
        status = transfer(m, PCI, 256)
        assert read(m, DEST, SIZE + 16) == b'\xa5' * (SIZE + 16)
        assert read(m, AP_ROOT, len(root)) == root
        check_irq(m, status, CHANNEL, abort=True)
        return {'default_off': True, 'unmapped_source_aborts': True, 'budget': budget}

    payload = bytes((i * 37 + (i >> 8) * 11 + (i >> 16)) & 255 for i in range(SIZE))
    peer = bytearray(payload + b'\x6b' * (WINDOW - SIZE))
    write(m, PEER, peer)
    program_atu(m)
    assert read(m, APERTURE, SIZE) == payload
    replacement = b'ATU-consumed-after-1MiB'
    offset = 0x100003
    m.write(APERTURE + offset, replacement)
    peer[offset:offset + len(replacement)] = replacement
    assert read(m, PEER, WINDOW) == peer
    assert read(m, AP_ROOT, len(root)) == root
    configure_control(m)
    assert m.readl(CONTROL+12)==0
    m.writel(CONTROL+24,1)
    peer[9]=1
    epoch=m.readl(CONTROL+16)
    assert m.readl(CONTROL+12)==1 and m.readl(CONTROL+32)==0
    m.writel(CONTROL+24,2)
    assert m.readl(CONTROL+12)==1
    for target in (PEER+9,APERTURE+9,DATA_BAR+9):
        m.write(target,b'\x42')
        assert read(m,PEER,WINDOW)==peer
    assert m.readl(CONTROL+28)>=3
    write(m,AP_SOURCE,bytes(range(256)))
    failed,channel=prepare(m,0,0)
    m.writel(B+channel+8,256)
    address(m,channel+0xc,AP_SOURCE)
    address(m,channel+0x14,PCI)
    m.writel(B+0x10,0)
    assert read(m,PEER,WINDOW)==peer
    check_irq(m,failed,0,abort=True)
    status = transfer(m, PCI, SIZE)
    assert read(m, DEST - 16, SIZE + 32) == b'\xa5' * 16 + peer[:SIZE] + b'\xa5' * 16
    assert read(m, AP_ROOT, len(root)) == root
    assert read(m, PEER, WINDOW) == peer
    check_irq(m, status, CHANNEL)
    assert m.readl(CONTROL+32)==1
    address(m,0x300+CHANNEL*0x200+0xc,0x804000000)
    assert m.readl(CONTROL+32)==1
    m.writel(CONTROL+24,2)
    assert m.readl(CONTROL+12)==0 and m.readl(CONTROL+16)==epoch

    m.writel(ATU + 4, 0)
    m.write(APERTURE + offset, b'no-write-through-disabled-window')
    assert read(m, PEER, WINDOW) == peer
    for source, count, copied in ((0x804000000, 256, 0),
                                  (PCI + WINDOW - SIZE + 1, SIZE, SIZE // 256 * 256)):
        write(m, DEST, b'\xa5' * (SIZE + 16))
        status = transfer(m, source, count)
        start = source - PCI
        expected = peer[start:start + copied] if copied else b''
        assert read(m, DEST, SIZE + 16) == expected + b'\xa5' * (SIZE + 16 - copied)
        assert read(m, AP_ROOT, len(root)) == root
        assert read(m, PEER, WINDOW) == peer
        check_irq(m, status, CHANNEL, abort=True)
    m.writel(CONTROL+24,1)
    assert m.readl(CONTROL+12)==1 and m.readl(CONTROL+16)==epoch+1
    m.writel(CONTROL+24,2)
    assert m.readl(CONTROL+12)==1 and m.readl(CONTROL+32)==0
    # Same byte total from a different LLI destination cannot borrow stale SAR/DAR.
    status,channel=prepare(m,1,CHANNEL,linked=True)
    m.writel(B+channel+8,SIZE)
    address(m,channel+0xc,PCI)
    address(m,channel+0x14,DEST)
    descriptor=0x410030000
    other_destination=0x410400000
    write(m,other_destination,b'\xa5'*SIZE)
    m.write(descriptor,struct.pack('<IIQQ',9,SIZE,PCI,other_destination)+
                       struct.pack('<IIQQ',6,0,descriptor,0))
    address(m,channel+0x1c,descriptor)
    m.writel(B+0x30,CHANNEL)
    assert read(m,other_destination,SIZE)==peer[:SIZE]
    check_irq(m,status,CHANNEL)
    assert m.readl(CONTROL+32)==0
    m.writel(CONTROL+24,2)
    assert m.readl(CONTROL+12)==1
    return {'bytes': SIZE, 'controller': 0, 'channel': CHANNEL, 'budget': budget, 'payload_sha256': hashlib.sha256(peer[:SIZE]).hexdigest(),
            'independent_same_address_domains': True, 'source_root_guards_unchanged': True,
            'atu_and_dma_share_actual_backing': True, 'atu_disable_prevents_write': True,
            'high_address_and_partial_tail_abort': True, 'gic_mask_w1c_verified': True,
            'guarded_romd_all_normal_write_paths_verified': True,
            'freeze_requires_fresh_full_dma_and_rejects_stale_epoch': True,
            'post_completion_register_changes_do_not_rewrite_evidence': True,
            'different_lli_transfer_cannot_borrow_direct_metadata': True,
            'privileged_loader_debug_writes_excluded_during_active_epoch': True,
            'phy_dbi_overlap_profile_present': True,
            'native_host_identity_mem_window_verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    with binary.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    output = Path(tempfile.mkdtemp(prefix='backup-pci-qtest-', dir='/var/tmp'))
    print('BACKUP_PCI_OUTPUT', output, flush=True)
    result = {'scope': 'explicit virtual primary window, not NOR alias or original CP execution',
              'binary_sha256': digest, 'hardware_verified': False, 'capture_verified': False}
    seed=(HERE.parents[1]/'runtime/analysis/menu-root/seed-backup.bin').read_bytes()
    assert hashlib.sha256(seed).hexdigest()=='3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
    fixture=seed[0xed000:]
    assert len(fixture)==SIZE
    fixture_path=output/'public-primary.bin'
    fixture_path.write_bytes(fixture)
    try:
        with idle_lock(HERE.parents[1] / 'runtime/analysis/.menu-probe.lock'):
            for enabled in (False, True):
                run = output / ('enabled' if enabled else 'disabled')
                run.mkdir()
                m = hardware.Machine(binary, run, True, pci_peer_test=True, low_ecam=True,
                                     scu_test=enabled, ccf_test=enabled, phy_init_test=enabled,
                                     backup_test=enabled, backup_image=fixture_path if enabled else None)
                try:
                    m.connect()
                    if enabled:
                        assert read(m,PEER,SIZE)==fixture
                        result['public_fixture_loaded_and_read_back']=True
                    result[run.name] = exercise(m, enabled)
                finally:
                    m.close()
            result['invalid_fixture_rejections']=[]
            for label,contents,reason in (
                    ('truncated',fixture[:-1],'wrong length or read failure'),
                    ('modified',fixture[:-1]+bytes([fixture[-1]^1]),'not the pinned public fixture')):
                invalid=output/(label+'.bin');invalid.write_bytes(contents)
                run=output/label;run.mkdir()
                m=hardware.Machine(binary,run,False,pci_peer_test=True,backup_test=True,backup_image=invalid)
                try:
                    code=m.proc.wait(timeout=10)
                    assert code!=0 and reason in (run/'qemu.log').read_text()
                    result['invalid_fixture_rejections'].append(label)
                finally:m.close()
        result['hardware_verified'] = True
        print('BACKUP_PCI_PASS: full-size data, AP/PCI isolation, ATU, actual GIC, default-off and faults', flush=True)
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
