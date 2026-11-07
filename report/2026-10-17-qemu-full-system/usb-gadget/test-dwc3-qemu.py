#!/usr/bin/env python3
"""Test the isolated QEMU with the generated board fragment enabled.

No guest firmware, descriptor, physical USB or USB/IP attachment is involved.
The board must enable that fragment with QEMU_SONY_DWC3_CORE_TEST=1.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile


def run(binary, output):
    output.mkdir(parents=True, exist_ok=True)
    # AF_UNIX sun_path is usually 108 bytes; the evidence path may be longer.
    with tempfile.TemporaryDirectory(prefix='sdwc-') as directory:
        run_dir = Path(directory)
        listeners = []
        for name in ('qtest', 'qmp'):
            listener = socket.socket(socket.AF_UNIX)
            listener.settimeout(10)
            listener.bind(str(run_dir / name))
            listener.listen(1)
            listeners.append(listener)
        stderr = (output / 'qtest-stderr.log').open('wb')
        process = subprocess.Popen([
            str(binary), '-machine', 'virt,gic-version=3', '-cpu', 'cortex-a53',
            '-m', '64M', '-S', '-nodefaults', '-display', 'none', '-serial', 'none',
            '-monitor', 'none', '-qtest', f'unix:{run_dir}/qtest',
            '-qmp', f'unix:{run_dir}/qmp', '-qtest-log', str(output / 'qtest-wire.log'),
        ], env={**os.environ, 'QEMU_SONY_DWC3_CORE_TEST': '1'}, stderr=stderr)
        qmp_file = None
        try:
            qtest, _ = listeners[0].accept()
            qmp, _ = listeners[1].accept()
            for sock in (qtest, qmp):
                sock.settimeout(10)
            qtest_file = qtest.makefile('rwb', buffering=0)
            qmp_file = qmp.makefile('rwb', buffering=0)
            assert json.loads(qmp_file.readline())['QMP']
            def qmp_call(op, arguments=None):
                qmp_file.write(json.dumps({'execute': op, 'arguments': arguments or {}}).encode() + b'\n')
                while True:
                    result = json.loads(qmp_file.readline())
                    if 'event' not in result:
                        assert 'return' in result, result
                        return result['return']
            qmp_call('qmp_capabilities')
            children = qmp_call('qom-list', {'path': '/machine/unattached'})
            gadget = next(x['name'] for x in children if x['type'] == 'child<sony-dwc3-gadget>')
            gic = next(x['name'] for x in children if x['type'] == 'child<arm-gicv3>')
            gadget = '/machine/unattached/' + gadget
            gic = '/machine/unattached/' + gic
            edges = []
            def qt(command):
                qtest_file.write(command.encode() + b'\n')
                while True:
                    response = qtest_file.readline().decode().strip()
                    if response.startswith('IRQ '):
                        edges.append(response)
                        continue
                    assert response.startswith('OK'), (command, response)
                    return response[2:].strip()
            def wr(offset, value):
                qt(f'writel {0xf10c0000 + offset:#x} {value:#x}')
            def rd(offset):
                return int(qt(f'readl {0xf10c0000 + offset:#x}'), 0)
            qt(f'irq_intercept_in {gic}')
            assert rd(0xc120) == 0x5533290a
            wr(0xc400, 0x40001000)
            wr(0xc404, 0)
            wr(0xc408, 0x1000)
            wr(0xc708, 7)
            wr(0xc704, 1 << 31)
            assert not rd(0xc70c) & (1 << 22)
            qt(f'set_irq_in {gadget} vbus 0 1')
            assert rd(0xc40c) == 8
            assert int(qt('readl 0x40001000'), 0) == 0x101
            assert int(qt('readl 0x40001004'), 0) == 0x201
            assert 'IRQ raise 184' in edges, edges
            wr(0xc408, 0x80001000)
            assert edges[-1] == 'IRQ lower 184', edges
            wr(0xc408, 0x1000)
            assert edges[-1] == 'IRQ raise 184', edges
            wr(0xc40c, 8)
            assert rd(0xc40c) == 0 and edges[-1] == 'IRQ lower 184'
            qt(f'set_irq_in {gadget} vbus 0 0')
            assert rd(0xc40c) == 4
            assert int(qt('readl 0x40001008'), 0) == 1
            assert edges[-1] == 'IRQ raise 184'
            qmp_call('quit')
            assert process.wait(timeout=10) == 0
            result = {'profile': 'virtual-functional-dwc3-device-v1',
                      'qemu_mmio_event_dma_pass': True, 'gic_spi': 184, 'irq_edges': edges,
                      'qmp_quit_rc': 0, 'original_driver_enumerated': False,
                      'host_usb_attached': False, 'jiritsu_authenticated': False}
            (output / 'qtest-result.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2))
        finally:
            if process.poll() is None:
                if qmp_file is None:
                    qmp, _ = listeners[1].accept()
                    qmp.settimeout(10)
                    qmp_file = qmp.makefile('rwb', buffering=0)
                    qmp_file.readline()
                    qmp_file.write(b'{"execute":"qmp_capabilities"}\n')
                    qmp_file.readline()
                qmp_file.write(b'{"execute":"quit"}\n')
                process.wait(timeout=10)
            for listener in listeners:
                listener.close()
            stderr.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(args.binary.resolve(), args.output.resolve())
