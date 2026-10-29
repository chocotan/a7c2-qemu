#!/usr/bin/env python3
"""Isolated original-provider diagnostics with explicit DMA/ATU opt-in; no camera or SD."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time

COMPONENTS = Path(__file__).resolve().parents[1]
PRODUCT = COMPONENTS.parents[1]
N = PRODUCT/'runtime/analysis'


def parse_observation(data, expected):
    normalized = data.replace(b'\r', b'')
    symbol = re.search(rb'^[0-9a-fA-F]+\s+[tT]\s+dma330_mem_transfer_async(?:\s+\[dma330\])?\s*$',
                       normalized, re.M)
    checks = {
        'guest_identity': bool(re.search(rb'^SHA(?:2-256|256)\(/kmod/dma330\.ko\)=\s*'
                                         + expected.encode()+rb'$', normalized, re.M)),
        'root_uid': bool(re.search(rb'^Uid:\s+0\s+0\s+0\s+0\s*$', normalized, re.M)),
        'root_gid': bool(re.search(rb'^Gid:\s+0\s+0\s+0\s+0\s*$', normalized, re.M)),
        'module_rc_zero': b'\nDMA330_LOAD_RC=0\n' in normalized,
        'module_live': bool(re.search(rb'^dma330\s+[0-9]+\s+[0-9]+\s+\S+\s+Live\b', normalized, re.M)),
        'symbol_listed': symbol is not None,
    }
    return {'ok': all(checks.values()), 'checks': checks}


def parse_monitor_words(output, count):
    words = []
    for line in output.splitlines():
        if ':' in line:
            words.extend(int(v, 16) for v in re.findall(r'0x([0-9a-fA-F]+)', line.split(':', 1)[1]))
    if len(words) != count:
        raise ValueError('monitor did not return the exact requested word count')
    return words


def parse_device_words(values):
    # Actual 330d-0 record: 24-byte name, u32 count +18h, pointer +20h.
    channels, count = values[4], values[3] & 0xffffffff
    if not 0xffffff8000000000 <= channels or count != 18:
        raise RuntimeError('Actual UDIF channel pointer/count differs from expected layout')
    return channels, count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', action='store_true', help='passively snapshot actual UDIF device/channel records')
    parser.add_argument('--pl330-candidate', type=Path, help='explicit private candidate stage with content proof')
    parser.add_argument('--snapshot-registers', action='store_true', help='original read_regs=1 diagnostic snapshot only')
    parser.add_argument('--marker-client', action='store_true', help='load the independently checked marker-only ABI client')
    parser.add_argument('--mmio-adapter', action='store_true', help='map validated original DMA resources before driver load')
    parser.add_argument('--dma-client', action='store_true', help='one owned original-provider async request')
    parser.add_argument('--fixed-io-baseline', action='store_true', help='Task76 normal fixed IOVA mapping baseline only')
    parser.add_argument('--atu-provider', action='store_true', help='Task76 fixed ATU mapping and original provider load only')
    parser.add_argument('--atu-client', action='store_true', help='original ATU map/data/unmap on an explicit TESTPCI peer')
    parser.add_argument('--pcidma-map-only', action='store_true', help='normal two-page PCI DMA fixed mapping only; no PCI connection or transfer')
    parser.add_argument('--dw-test-host', action='store_true', help='owned quirk-compatible TEST host, normal PCI enumeration only; no DMA')
    parser.add_argument('--early-iomap-only', action='store_true', help='narrow original-schema iomaps in derived board; check existing translations, no runtime mapper')
    parser.add_argument('--native-pcidma-init-only', action='store_true', help='restore only original PCI DMA boot initcall with early maps; observe IRQ registration, no host/transfer')
    parser.add_argument('--native-pcie-udif-init-only', action='store_true', help='restore original PCIe UDIF plus PCI DMA lifecycle using explicit stateful SCU; no SoC host/link/transfer')
    parser.add_argument('--native-ccf-provider-only', action='store_true', help='original CCF provider and seven normal clock APIs with stateful registers; no SoC host/PHY/DMA')
    parser.add_argument('--native-phy-upload-only', action='store_true', help='original OF probe upload under explicit TEST SRAM-clear policy; expect lane timeout, no host/link/DMA')
    parser.add_argument('--native-phy-frontier', action='store_true', help='probe passes TEST lane gate then aborts at first unmodeled DBI access; frontier evidence only, no host')
    parser.add_argument('--native-soc0-host', action='store_true', help='original SoC host probe binds and enumerates real TEST peer; no DMA submitted')
    parser.add_argument('--native-pcidma-transfer', action='store_true', help='original pcidma_connect/transfer_async one 256B AP->PCI write + PCI->AP read-back with real IRQ/callback; data verified both sides')
    args = parser.parse_args()
    if args.native_pcidma_transfer:
        if args.native_ccf_provider_only or args.native_pcie_udif_init_only or args.native_phy_upload_only or args.native_phy_frontier or args.native_soc0_host:
            parser.error('PCI DMA transfer mode includes its own provider/UDIF/host inputs')
        args.native_pcie_udif_init_only=True
    if args.native_soc0_host:
        if args.native_ccf_provider_only or args.native_pcie_udif_init_only or args.native_phy_upload_only or args.native_phy_frontier:
            parser.error('SoC host mode includes its own provider/UDIF inputs')
        args.native_pcie_udif_init_only=True
    if args.native_phy_frontier:
        if args.native_ccf_provider_only or args.native_pcie_udif_init_only or args.native_phy_upload_only:
            parser.error('PHY frontier mode is self-contained')
    if args.native_phy_upload_only:
        if args.native_ccf_provider_only or args.native_pcie_udif_init_only:
            parser.error('PHY upload mode includes its own provider/UDIF inputs and bounded failure observation')
        args.native_pcie_udif_init_only=True
    if args.native_ccf_provider_only:
        if args.native_pcie_udif_init_only:
            parser.error('CCF provider mode already includes native UDIF verification')
        args.native_pcie_udif_init_only=True
    if args.native_pcie_udif_init_only:
        if args.native_pcidma_init_only or args.early_iomap_only:
            parser.error('PCIe UDIF mode already includes native PCI DMA and early-map verification')
        args.native_pcidma_init_only=True
    if args.native_pcidma_init_only:
        if args.early_iomap_only:
            parser.error('native PCI DMA init already includes early-map verification')
        args.early_iomap_only=True
    if args.early_iomap_only and (not args.pl330_candidate or args.dw_test_host or args.pcidma_map_only
        or args.atu_provider or args.atu_client or args.fixed_io_baseline or args.mmio_adapter
        or args.snapshot_registers or args.dma_client or args.marker_client or args.resources):
        parser.error('early iomap proof requires its candidate and excludes other diagnostic actions')
    if args.dw_test_host:
        if (not args.pl330_candidate or args.pcidma_map_only or args.atu_provider or args.fixed_io_baseline
            or args.mmio_adapter or args.snapshot_registers or args.dma_client or args.marker_client or args.resources):
            parser.error('DW TEST host requires its candidate and excludes other diagnostic actions')
        args.pcidma_map_only=True
    if args.snapshot_registers and not (args.resources and args.pl330_candidate):
        parser.error('register snapshot requires the explicit candidate and resource observation')
    if args.mmio_adapter and not (args.snapshot_registers and args.pl330_candidate):
        parser.error('MMIO adapter requires explicit candidate and original register snapshot')
    if args.dma_client and not args.mmio_adapter:
        parser.error('original DMA client requires validated MMIO adapter and register snapshot')
    if args.fixed_io_baseline and (not args.pl330_candidate or args.mmio_adapter or args.snapshot_registers or args.dma_client):
        parser.error('fixed IOVA baseline requires candidate and excludes DMA/adaptor/snapshot actions')
    if args.atu_provider and (not args.pl330_candidate or args.mmio_adapter or args.snapshot_registers or args.dma_client or args.fixed_io_baseline):
        parser.error('ATU provider mode requires its explicit candidate, excludes unrelated DMA actions')
    if args.atu_client and not args.atu_provider:
        parser.error('ATU client requires the explicit ATU provider mode')
    if args.pcidma_map_only and (not args.pl330_candidate or args.atu_provider or args.fixed_io_baseline
        or args.mmio_adapter or args.snapshot_registers or args.dma_client or args.marker_client or args.resources):
        parser.error('PCI DMA mapping-only requires its candidate and excludes unrelated actions')
    spec = importlib.util.spec_from_file_location('admission', COMPONENTS/'admission.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    sys.path.insert(0, str(N))
    from menu_live import serial_command, connect_in_run
    module = N/'menu-root/kmod/dma330.ko'
    expected = '9ba277f011b3ddcfbc3fa610d22b63ae3be1e0ded385b42ff2c7cf0a83e520ab'
    assert hashlib.sha256(module.read_bytes()).hexdigest() == expected
    source = (N/'qemu-kernel-probe.sh').read_text()
    if args.native_pcidma_init_only:
        anchor=',__boottime___udif_init_pcidma'
        assert source.count(anchor)==1 and source.count('__boottime___udif_init_udif_pcie')==1
        source=source.replace(anchor,'',1)
    if args.native_pcie_udif_init_only:
        anchor=',__boottime___udif_init_udif_pcie'
        assert source.count(anchor)==1
        source=source.replace(anchor,'',1)
        anchor='-no-reboot -sandbox on'
        assert source.count(anchor)==1
        source=source.replace(anchor,'-trace enable=memory_region_ops_write '+anchor)
    # Native upload keeps write-only MMIO tracing: read tracing made trial-85fheds1
    # produce 10.5GB of pl011 flag-poll lines. Read-side evidence uses model counters.
    candidate_proof = None
    if args.pl330_candidate:
        args.pl330_candidate = args.pl330_candidate.resolve()
        candidate_proof = json.loads((args.pl330_candidate/'build-proof.json').read_text())
        candidate_binary = args.pl330_candidate/'build/qemu-system-aarch64'
        assert hashlib.sha256(candidate_binary.read_bytes()).hexdigest() == candidate_proof['binary_sha256']
        if args.dw_test_host and 'test_root_dbi.c' not in candidate_proof.get('model_source_sha256',{}):
            raise ValueError('DW TEST host requires the explicit bounded DBI hardware model')
        if args.native_pcidma_init_only and 'test_pcie_peer.c' not in candidate_proof.get('model_source_sha256',{}):
            raise ValueError('native PCI DMA init needs the real TEST PCIe engine profile')
        if args.native_pcie_udif_init_only and 'test_pcie_scu.c' not in candidate_proof.get('model_source_sha256',{}):
            raise ValueError('native PCIe UDIF init requires the explicit stateful SCU profile')
        if args.native_ccf_provider_only and 'test_ccf_scu.c' not in candidate_proof.get('model_source_sha256',{}):
            raise ValueError('native CCF needs the explicit extended CCF register model')
        if args.native_phy_upload_only or args.native_phy_frontier or args.native_soc0_host or args.native_pcidma_transfer:
            if 'qemu_phy_init.c' not in candidate_proof.get('model_source_sha256',{}):
                raise ValueError('Bounded original upload requires the separate TEST timed-clear model')
            hardware=json.loads((COMPONENTS.parent/'virtual-pcidma/phy-init-hardware-validation.json').read_text())
            if hardware.get('binary_sha256')!=candidate_proof['binary_sha256'] or not hardware.get('test_clear_policy_verified'):
                raise ValueError('This exact TEST clear-policy candidate requires independent hardware validation first')
        anchor = 'timer_environment=(--setenv QEMU_SONY_TIMERS 1)'
        assert source.count(anchor) == 1
        source = source.replace(anchor, 'timer_environment=(--setenv QEMU_SONY_TIMERS 1 --setenv QEMU_SONY_DMA330 1)')
        if args.atu_provider:
            source = source.replace('--setenv QEMU_SONY_DMA330 1)', '--setenv QEMU_SONY_DMA330 1 --setenv QEMU_SONY_ATU_TEST 1)')
        if args.pcidma_map_only or args.native_pcidma_init_only:
            source = source.replace('--setenv QEMU_SONY_DMA330 1)', '--setenv QEMU_SONY_DMA330 1 --setenv QEMU_SONY_PCIE_PEER_TEST 1)')
        if args.dw_test_host:
            source = source.replace('--setenv QEMU_SONY_PCIE_PEER_TEST 1)', '--setenv QEMU_SONY_PCIE_PEER_TEST 1 --setenv QEMU_SONY_PCIE_DBI_TEST 1)')
        if args.native_pcie_udif_init_only:
            source = source.replace('--setenv QEMU_SONY_PCIE_PEER_TEST 1)', '--setenv QEMU_SONY_PCIE_PEER_TEST 1 --setenv QEMU_SONY_PCIE_SCU_TEST 1)')
        if args.native_ccf_provider_only or args.native_phy_upload_only or args.native_soc0_host or args.native_pcidma_transfer:
            source = source.replace('--setenv QEMU_SONY_PCIE_SCU_TEST 1)', '--setenv QEMU_SONY_PCIE_SCU_TEST 1 --setenv QEMU_SONY_CCF_TEST 1)')
        if args.native_phy_upload_only or args.native_soc0_host or args.native_pcidma_transfer:
            source = source.replace('--setenv QEMU_SONY_CCF_TEST 1)', '--setenv QEMU_SONY_CCF_TEST 1 --setenv QEMU_SONY_PHY_INIT_TEST 1)')
        if args.native_phy_frontier:
            anchor='--setenv QEMU_SONY_DMA330 1)'
            assert source.count(anchor)==1
            source = source.replace(anchor,'--setenv QEMU_SONY_DMA330 1 --setenv QEMU_SONY_PCIE_PEER_TEST 1 --setenv QEMU_SONY_PCIE_SCU_TEST 1 --setenv QEMU_SONY_CCF_TEST 1 --setenv QEMU_SONY_PHY_INIT_TEST 1)')
            anchor='-no-reboot -sandbox on'
            assert source.count(anchor)==1
            source=source.replace(anchor,'-trace enable=memory_region_ops_write '+anchor)
        if args.dma_client:
            anchor = '-no-reboot -sandbox on'
            assert source.count(anchor) == 1
            source = source.replace(anchor, '-trace enable=pl330_* '+anchor)
    run = Path(tempfile.mkdtemp(prefix='trial-', dir=Path(__file__).parent))
    for old, new in (
        ('project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"',
         'project_dir='+shlex.quote(str(PRODUCT/'runtime'))),
        ('output_dir="$analysis_dir/qemu-kernel-output-$ram_mb"',
         'output_dir='+shlex.quote(str(run/'prepared'))+'-"$ram_mb"'),
    ):
        assert source.count(old) == 1
        source = source.replace(old, new)
    script = run/'kernel-probe.sh'
    script.write_text(source)
    subprocess.run(['bash', '-n', str(script)], check=True)
    out = run/'output'
    out.mkdir()
    console = run/'console.log'
    result = {'scope': 'module-load/symbol only; no DMA or driver-start proof',
              'ok': False, 'camera_app_started': False, 'sd_attached': False,
              'udif_driver_start_requested': False, 'dma_executed': False,
              'capture_verified': False, 'module_sha256': expected}
    if args.dma_client:
        result['scope'] = 'one original DMA330 request and resident-owned pages; no camera frame/capture'
    elif args.snapshot_registers:
        result['scope'] = 'original module/MMIO snapshot only; no DMA request'
    elif args.atu_client:
        result['scope'] = 'original pciatu_map/unmap and actual TESTPCI peer/aperture bytes; no CP/CMOS'
    elif args.atu_provider:
        result['scope'] = 'normal fixed ATU mapping and original-provider load only; no PCI data'
    elif args.native_pcidma_transfer:
        result['scope']='original pcidma_connect/transfer_async direct 256B write+read-back via real IRQ/callback; data verified both guest and QEMU; no capture'
        result.update(udif_driver_start_requested=True,native_pcidma_boot_init_requested=True,
            native_pcie_udif_boot_init_requested=True,native_soc0_host_requested=True,
            native_pcidma_transfer_requested=True,original_silicon_init_producer_verified=False)
    elif args.native_soc0_host:
        result['scope']='original SoC host probe binds and enumerates real TEST peer via DBI/viewport; engines enabled-idle after notify; NO DMA submitted'
        result.update(udif_driver_start_requested=True,native_pcidma_boot_init_requested=True,
            native_pcie_udif_boot_init_requested=True,native_soc0_host_requested=True,
            original_silicon_init_producer_verified=False)
    elif args.native_phy_frontier:
        result['scope']='original probe passes TEST lane gate then expected abort at first unmodeled DBI read; frontier evidence only, no host/PHY-silicon claim'
        result.update(native_phy_frontier_requested=True,native_of_host_success=False,
            original_silicon_init_producer_verified=False)
    elif args.native_phy_upload_only:
        result['scope']='original OF probe SRAM upload under explicit TEST clear policy; expected lane timeout, NOT host/PHY/link success'
        result.update(udif_driver_start_requested=True,native_pcidma_boot_init_requested=True,
            native_pcie_udif_boot_init_requested=True,native_phy_upload_requested=True,
            original_silicon_init_producer_verified=False,native_of_host_success=False)
    elif args.native_ccf_provider_only:
        result['scope'] = 'original CCF provider and seven clock APIs with real register readback only; no SoC host/PHY/DMA'
        result['udif_driver_start_requested'] = True
        result['native_pcidma_boot_init_requested'] = True
        result['native_pcie_udif_boot_init_requested'] = True
        result['native_ccf_provider_requested'] = True
    elif args.native_pcie_udif_init_only:
        result['scope'] = 'original PCIe UDIF/PCI DMA lifecycle with TEST SCU gate/reset state; no SoC host/link/transfer'
        result['udif_driver_start_requested'] = True
        result['native_pcidma_boot_init_requested'] = True
        result['native_pcie_udif_boot_init_requested'] = True
    elif args.native_pcidma_init_only:
        result['scope'] = 'original PCI DMA boot initcall/IRQ registration with early maps only; no PCIe host/connect/transfer'
        result['udif_driver_start_requested'] = True
        result['native_pcidma_boot_init_requested'] = True
    elif args.early_iomap_only:
        result['scope'] = 'original setup_arch/map_io, narrow derived original-schema windows, existing PAR translations only; no mapper/DMA'
    elif args.dw_test_host:
        result['scope'] = 'owned compatible TEST host, normal kernel PCI enumeration/sysfs/config only; no DMA/PHY/CP'
    elif args.pcidma_map_only:
        result['scope'] = 'normal original-export PCI DMA fixed mapping and PAR physical proof only; no connection/data'
    if candidate_proof:
        result['candidate_binary_sha256'] = candidate_proof['binary_sha256']
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('MENU_', 'A7C2_', 'QEMU_', 'SONY_'))}
    env.update(SONY_TIMER_MODEL='1', QEMU_UI_LIVE='1', QEMU_TIMEOUT_SECONDS='0',
               QEMU_OUTPUT_DIR=str(out), QEMU_TRACE_FLAGS='guest_errors,unimp')
    if args.native_phy_upload_only or args.native_phy_frontier or args.native_soc0_host or args.native_pcidma_transfer:
        env['QEMU_TRACE_FLAGS']+=',invalid_mem'
        result['native_invalid_mem_logging_enabled']=True
    if candidate_proof:
        env['QEMU_SYSTEM_DIR'] = str(args.pl330_candidate/'build')
    proc = control = wire = None
    adapter_command = 'DMA_ADAPTER_OK=1'
    if args.mmio_adapter or args.fixed_io_baseline or args.atu_provider or args.pcidma_map_only or args.early_iomap_only:
        adapter = COMPONENTS/'sony-pl330-mmio' if args.mmio_adapter else COMPONENTS.parent/'virtual-atu/fixed-map'
        if args.pcidma_map_only:
            adapter = COMPONENTS.parent/'virtual-pcidma/fixed-map'
        if args.early_iomap_only:
            adapter = COMPONENTS.parent/'virtual-pcidma/early-map-check'
        checker = adapter/('check_adapter.py' if args.mmio_adapter else 'check_client.py')
        module_name = 'sony_dma_map' if args.mmio_adapter else ('sony_atu_map' if args.atu_provider else 'sony_fixed_io')
        if args.pcidma_map_only:
            module_name = 'sony_pcidma_map'
        if args.early_iomap_only:
            module_name = 'sony_early_io_check'
        check_args = [sys.executable, '-B', str(checker)]+(['--atu'] if args.atu_provider else [])
        checked = subprocess.run(check_args, check=True,
                                 capture_output=True, text=True)
        record = json.loads(checked.stdout)
        payload = (adapter/(module_name+'.ko')).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        assert digest == record['sha256']
        result['mmio_adapter_sha256'] = digest
        adapter_command = ('DMA_ADAPTER_OK=0\ncat > /tmp/sony_dma_map.b64 <<\'MMIO_ADAPTER_B64_END\'\n'
            +base64.encodebytes(payload).decode('ascii')+'MMIO_ADAPTER_B64_END\n'
            '/usr/bin/openssl base64 -d -in /tmp/sony_dma_map.b64 -out /tmp/sony_dma_map.ko\n'
            '/usr/bin/openssl dgst -sha256 /tmp/sony_dma_map.ko > /tmp/map.sha\ncat /tmp/map.sha\n'
            'if grep -q "'+digest+'$" /tmp/map.sha; then\n'
            'insmod /tmp/sony_dma_map.ko\nDMA_ADAPTER_RC=$?\necho MMIO_ADAPTER_RC=$DMA_ADAPTER_RC\n'
            'if test "$DMA_ADAPTER_RC" = 0; then DMA_ADAPTER_OK=1; fi\nfi')

    def qmp(command, arguments=None):
        request = {'execute': command}
        if arguments is not None:
            request['arguments'] = arguments
        wire.write((json.dumps(request)+'\n').encode())
        wire.flush()
        while True:
            reply = json.loads(wire.readline())
            if 'error' in reply:
                raise RuntimeError(str(reply['error']))
            if 'return' in reply:
                return reply['return']

    with gate.idle_lock(N/'.menu-probe.lock'):
        print('DMA330_MODULE_PROBE_RUN', run, flush=True)
        boot_board = N/'qemu-virt-board/virt-packed.dtb'
        if args.early_iomap_only or args.native_phy_frontier or args.native_soc0_host or args.native_pcidma_transfer:
            spec = importlib.util.spec_from_file_location('iomap_board',COMPONENTS.parent/'virtual-pcidma/iomap_board.py')
            board = importlib.util.module_from_spec(spec);spec.loader.exec_module(board)
            boot_board = board.prepare(boot_board,run/'derived-iomap.dtb',
                N/'unpacked/firmware.tar_unpacked/0800_appli/setting/cxd90057.dtb',
                all_pcie_wrappers=args.native_pcie_udif_init_only,
                ccf_provider=args.native_ccf_provider_only or args.native_phy_upload_only or args.native_phy_frontier or args.native_soc0_host or args.native_pcidma_transfer,
                phy_upload=args.native_phy_upload_only or args.native_phy_frontier or args.native_soc0_host or args.native_pcidma_transfer,
                dma_window=args.native_pcidma_transfer)
            result['derived_iomap_board_sha256'] = hashlib.sha256(boot_board.read_bytes()).hexdigest()
        with console.open('wb') as log:
            try:
                if args.early_iomap_only or args.native_phy_frontier:
                    with (run/'early-iomap-preparation.log').open('wb') as prep:
                        subprocess.run(['bash',str(script),'4096',str(boot_board),'1','1',
                            str(N/'menu-initramfs.cpio')],cwd=N,env=dict(env,QEMU_PREPARE_ONLY='1'),
                            stdout=prep,stderr=subprocess.STDOUT,check=True,timeout=45)
                    result['early_iomap_preparation_passed']=True
                proc = subprocess.Popen(['bash', str(script), '4096',
                    str(boot_board), '1', '1',
                    str(N/'menu-initramfs.cpio')], cwd=N, env=env,
                    stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True)
                # Establish owned control before the potentially faulting module load.
                deadline = time.monotonic()+60
                while not (out/'qmp.sock').exists():
                    if proc.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('No owned QMP socket')
                    time.sleep(.05)
                control = socket.socket(socket.AF_UNIX)
                control.settimeout(10)
                connect_in_run(control, out, 'qmp.sock')
                wire = control.makefile('rwb', buffering=0)
                assert 'QMP' in json.loads(wire.readline())
                qmp('qmp_capabilities')
                if args.native_phy_frontier:
                    fault_deadline = time.monotonic()+300
                    while b'Internal error' not in console.read_bytes():
                        if proc.poll() is not None or time.monotonic() >= fault_deadline:
                            raise RuntimeError('Expected DBI frontier fault did not occur')
                        time.sleep(.1)
                    spec=importlib.util.spec_from_file_location('phy_frontier_observation',
                        COMPONENTS.parent/'virtual-pcidma/observe_phy_frontier.py')
                    frontier=importlib.util.module_from_spec(spec);spec.loader.exec_module(frontier)
                    frontier.check(qmp,run,console,result)
                    result['ok']=bool(result.get('native_phy_frontier_verified'))
                while not args.native_phy_frontier and b'/ #' not in console.read_bytes():
                    if proc.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('Kernel did not reach shell')
                    time.sleep(.05)
                command = '\n'.join([
                    'mount -t proc proc /proc', 'mount -t sysfs sysfs /sys',
                    'mount -t tmpfs tmpfs /tmp',
                    'grep -E "^(Uid|Gid):" /proc/$$/status',
                    '/usr/bin/openssl dgst -sha256 /kmod/dma330.ko > /tmp/dma330.sha',
                    'cat /tmp/dma330.sha',
                    'if grep -q "'+expected+'$" /tmp/dma330.sha; then',
                    'insmod /kmod/devno.ko', 'echo DEVNO_LOAD_RC=$?',
                    adapter_command, 'if test "$DMA_ADAPTER_OK" = 1; then',
                    'insmod /kmod/dma330.ko phy_inst_area=0x4102E4000',
                    'echo DMA330_LOAD_RC=$?',
                    'grep "^dma330 " /proc/modules',
                    'grep " dma330_mem_transfer_async" /proc/kallsyms',
                    'fi',
                    'else echo DMA330_IDENTITY_REJECTED; fi',
                    # Bulk payload tty echo can interleave earlier output.
                    # Re-read identities after its input has been fully consumed;
                    # keep strict full-line predicates, never strip echo prefixes.
                    'grep -E "^(Uid|Gid):" /proc/$$/status',
                    '/usr/bin/openssl dgst -sha256 /kmod/dma330.ko',
                    'echo DMA330_OBSERVATION_DONE', 'true'])
                if not args.native_phy_frontier:
                    data = serial_command(proc, console, command, timeout=45)
                    (run/'module-observation.txt').write_bytes(data)
                    result.update(parse_observation(data, expected))
                if args.early_iomap_only:
                    result['early_iomap_existing_verified'] = b'EARLY_IOMAP_PASS: ten existing translations, original boot mapping; no mapper/MMIO/DMA' in data
                    result['ok'] = result['ok'] and result['early_iomap_existing_verified']
                    token = 'EARLY_IOMAP_CPU_RESUMED_'+run.name.replace('-','_')
                    resumed = serial_command(proc,console,'echo '+token,timeout=15)
                    (run/'early-iomap-cpu-resumed.txt').write_bytes(resumed)
                    result['early_iomap_cpu_resumed'] = ('\n'+token+'\n').encode() in resumed.replace(b'\r',b'')
                    result['ok'] = result['ok'] and result['early_iomap_cpu_resumed']
                if args.native_pcidma_init_only and not args.native_phy_upload_only and not args.native_soc0_host and not args.native_pcidma_transfer and result['ok']:
                    spec=importlib.util.spec_from_file_location('native_init_observation',
                        COMPONENTS.parent/'virtual-pcidma/observe_native_init.py')
                    native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
                    native.observe(qmp,serial_command,run,proc,console,result)
                if args.native_phy_upload_only and result['ok']:
                    spec=importlib.util.spec_from_file_location('phy_upload_observation',
                        COMPONENTS.parent/'virtual-pcidma/observe_phy_upload.py')
                    phy=importlib.util.module_from_spec(spec);spec.loader.exec_module(phy)
                    phy.observe(qmp,serial_command,run,proc,console,result)
                if args.native_soc0_host and result['ok']:
                    spec=importlib.util.spec_from_file_location('soc0_host_observation',
                        COMPONENTS.parent/'virtual-pcidma/observe_soc0_host.py')
                    host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
                    host.observe(qmp,serial_command,run,proc,console,result)
                if args.native_pcidma_transfer and result['ok']:
                    spec=importlib.util.spec_from_file_location('soc0_host_observation',
                        COMPONENTS.parent/'virtual-pcidma/observe_soc0_host.py')
                    host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
                    host.observe(qmp,serial_command,run,proc,console,result)
                    spec=importlib.util.spec_from_file_location('pcidma_transfer_observation',
                        COMPONENTS.parent/'virtual-pcidma/observe_pcidma_transfer.py')
                    xfer=importlib.util.module_from_spec(spec);spec.loader.exec_module(xfer)
                    xfer.observe(qmp,serial_command,run,proc,console,result)
                if args.native_ccf_provider_only and result['ok']:
                    spec=importlib.util.spec_from_file_location('ccf_client_observation',
                        COMPONENTS.parent/'virtual-pcidma/observe_ccf_client.py')
                    ccf=importlib.util.module_from_spec(spec);spec.loader.exec_module(ccf)
                    ccf.observe(qmp,serial_command,run,proc,console,result)
                if args.fixed_io_baseline:
                    result['fixed_io_baseline_verified'] = b'FIXED_IO_PASS: original mapper, fixed VA, PID30, no DMA' in data
                    result['ok'] = result['ok'] and result['fixed_io_baseline_verified']
                if args.pcidma_map_only:
                    result['fixed_pcidma_map_verified'] = b'FIXED_PCIDMA_MAP_PASS: two pages, original mapper and PAR physical verified; no DMA' in data
                    result['ok'] = result['ok'] and result['fixed_pcidma_map_verified']
                if args.dw_test_host and result['ok']:
                    spec = importlib.util.spec_from_file_location('dw_test_host_observation',
                        COMPONENTS.parent/'virtual-pcidma/observe_dw_host.py')
                    dw = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(dw)
                    dw.run_host(qmp,serial_command,run,proc,console,result)
                if args.atu_provider and result['ok']:
                    digest = '08c61d2d889f4fc8e7219ddc269fb8170a090ffb4e207cf52ed1afce6fb82c35'
                    command = ('/usr/bin/openssl dgst -sha256 /usr/kmod/pcieatu.ko > /tmp/atu.sha\n'
                        'cat /tmp/atu.sha\nif grep -q "'+digest+'$" /tmp/atu.sha; then\n'
                        'insmod /usr/kmod/pcieatu.ko\necho ORIGINAL_ATU_LOAD_RC=$?\n'
                        'grep "^pcieatu " /proc/modules\ngrep " pciatu_map" /proc/kallsyms\n'
                        'grep " pciatu_unmap" /proc/kallsyms\nelse echo ATU_IDENTITY_REJECTED; fi\ntrue')
                    observed = serial_command(proc, console, command, timeout=20)
                    (run/'original-atu-provider.txt').write_bytes(observed)
                    clean = observed.replace(b'\r', b'')
                    result['original_atu_provider_loaded'] = bool(b'\nORIGINAL_ATU_LOAD_RC=0\n' in clean
                        and re.search(rb'^pcieatu\s+\d+\s+\d+\s+\S+\s+Live\b', clean, re.M)
                        and re.search(rb'^[0-9a-f]+\s+[tT]\s+pciatu_map\s+\[pcieatu\]', clean, re.M)
                        and re.search(rb'^[0-9a-f]+\s+[tT]\s+pciatu_unmap\s+\[pcieatu\]', clean, re.M)
                        and b'FIXED_ATU_MAP_PASS:' in data)
                    result['ok'] = result['ok'] and result['original_atu_provider_loaded']
                if args.atu_client and result['ok']:
                    spec = importlib.util.spec_from_file_location('atu_client_observation',
                        COMPONENTS.parent/'virtual-atu/observe_client.py')
                    atu = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(atu)
                    atu.run_client(qmp, serial_command, run, proc, console, result)
                if args.marker_client and result['ok']:
                    client_dir = COMPONENTS/'dma330-kernel-client-abi'
                    subprocess.run([sys.executable, '-B', str(client_dir/'check_elf.py')], check=True,
                                   stdout=(run/'client-host-check.json').open('wb'))
                    payload = (client_dir/'dma330_abi_diag.ko').read_bytes()
                    digest = hashlib.sha256(payload).hexdigest()
                    checked_client = json.loads((run/'client-host-check.json').read_text())
                    assert digest == checked_client['output']['sha256']
                    encoded = base64.encodebytes(payload).decode('ascii')
                    command = ('cat > /tmp/dma330_abi_diag.b64 <<\'ABI_CLIENT_BASE64_END\'\n'
                               + encoded+'ABI_CLIENT_BASE64_END\n'
                               '/usr/bin/openssl base64 -d -in /tmp/dma330_abi_diag.b64 -out /tmp/dma330_abi_diag.ko\n'
                               '/usr/bin/openssl dgst -sha256 /tmp/dma330_abi_diag.ko > /tmp/abi.sha\n'
                               'cat /tmp/abi.sha\n'
                               'if grep -q "'+digest+'$" /tmp/abi.sha; then\n'
                               'insmod /tmp/dma330_abi_diag.ko\necho ABI_CLIENT_LOAD_RC=$?\n'
                               'grep "^dma330_abi_diag " /proc/modules\n'
                               'else echo ABI_CLIENT_IDENTITY_REJECTED; fi\ntrue')
                    observed = serial_command(proc, console, command, timeout=20)
                    (run/'marker-client-observation.txt').write_bytes(observed)
                    clean = observed.replace(b'\r', b'')
                    result['marker_client_loaded'] = (b'\nABI_CLIENT_LOAD_RC=0\n' in clean
                        and bool(re.search(rb'^dma330_abi_diag\s+\d+\s+\d+\s+\S+\s+Live\b', clean, re.M))
                        and b'dma330_abi_diag: marker-only init' in clean)
                    result['ok'] = result['ok'] and result['marker_client_loaded']
                if args.snapshot_registers and result['ok']:
                    report = COMPONENTS/'verifiers/verify_dma_snapshot.py'
                    subprocess.run([sys.executable, '-B', str(report)], check=True)
                    registers = serial_command(proc, console, '\n'.join([
                        'echo read_regs=1 > /proc/udm/dma330',
                        'echo DMA330_READ_REGS_RC=$?',
                        'cat /proc/udm/dma330', 'true']), timeout=20)
                    (run/'original-register-snapshot.txt').write_bytes(registers)
                    normalized = registers.replace(b'\r', b'')
                    result['original_snapshot_command_rc_zero'] = b'\nDMA330_READ_REGS_RC=0\n' in normalized
                    result['original_snapshot_pid30_count'] = len(re.findall(rb'periph_id_n\[0\]=0x30\b', normalized))
                    result['original_mmio_snapshot_verified'] = (result['original_snapshot_command_rc_zero']
                                                               and result['original_snapshot_pid30_count'] == 2)
                    result['ok'] = result['ok'] and result['original_mmio_snapshot_verified']
                if args.dma_client and result['ok']:
                    client = COMPONENTS/'sony-pl330-client'
                    checked = subprocess.run([sys.executable, '-B', str(client/'check_client.py')],
                                             check=True, capture_output=True, text=True)
                    identity = json.loads(checked.stdout)
                    payload = (client/'sony_dma_probe.ko').read_bytes()
                    digest = hashlib.sha256(payload).hexdigest()
                    assert digest == identity['sha256']
                    result['dma_client_sha256'] = digest
                    # Set before ordinary insmod: exceptions cannot reclaim an
                    # admitted request whose callback has not been observed.
                    result['dma_owner_uncertain'] = True
                    commands = ('cat > /tmp/sony_dma_probe.b64 <<\'OWNED_DMA_CLIENT_END\'\n'
                        +base64.encodebytes(payload).decode('ascii')+'OWNED_DMA_CLIENT_END\n'
                        '/usr/bin/openssl base64 -d -in /tmp/sony_dma_probe.b64 -out /tmp/sony_dma_probe.ko\n'
                        '/usr/bin/openssl dgst -sha256 /tmp/sony_dma_probe.ko > /tmp/client.sha\ncat /tmp/client.sha\n'
                        'if grep -q "'+digest+'$" /tmp/client.sha; then\n'
                        'insmod /tmp/sony_dma_probe.ko\necho OWNED_DMA_CLIENT_LOAD_RC=$?\n'
                        'else echo OWNED_DMA_CLIENT_IDENTITY_REJECTED; fi\ntrue')
                    observed = serial_command(proc, console, commands, timeout=30)
                    (run/'original-dma-client.txt').write_bytes(observed)
                    clean = observed.replace(b'\r', b'')
                    before_submit_rejected = (b'DMA_CLIENT_NOT_SUBMITTED:' in clean
                                              or b'OWNED_DMA_CLIENT_IDENTITY_REJECTED\n' in clean)
                    settled = re.search(rb'DMA_CLIENT_SETTLED callbacks=(\d+) status=(-?\d+) cookie=(\d+) submit=(-?\d+) bytes=(\d+)', clean)
                    result['dma_owner_uncertain'] = not (before_submit_rejected or settled is not None)
                    result['original_dma_client_pass'] = bool(settled and settled.groups() == (b'1', b'0', b'1', b'0', b'1')
                        and b'DMA_CLIENT_PASS:' in clean and b'\nOWNED_DMA_CLIENT_LOAD_RC=0\n' in clean)
                    result['dma_executed'] = result['original_dma_client_pass']
                    result['ok'] = result['ok'] and result['original_dma_client_pass']
                    if settled:
                        result['dma_callback_fields'] = [int(v) for v in settled.groups()]
                    address = re.search(rb'DMA_CLIENT_ADDRESSES desc=([0-9a-f]+) source=([0-9a-f]+) destination=([0-9a-f]+) bytes=256', clean)
                    if address and settled:
                        result['dma_buffer_addresses'] = [hex(int(v, 16)) for v in address.groups()]
                        for label, value in zip(('descriptor', 'source', 'destination'), address.groups()):
                            physical = int(value, 16)
                            if not 0x400000000 <= physical <= 0x4fdfff000:
                                raise RuntimeError('Observed client page outside admitted domain')
                            qmp('pmemsave', {'val': physical, 'size': 4096, 'filename': f'/out/{label}-page.bin'})
                    if settled:
                        qmp('pmemsave', {'val': 0x4102e4000, 'size': 0xc440,
                                         'filename': '/out/original-channel0-microcode.bin'})
                        diagnostic = serial_command(proc, console,
                            'echo read_regs=1 > /proc/udm/dma330\ncat /proc/udm/dma330\ncat /proc/interrupts\ntrue', timeout=20)
                        (run/'post-dma-registers.txt').write_bytes(diagnostic)
                if args.resources and result['ok']:
                    observation = serial_command(proc, console, '\n'.join([
                        'grep " udif_devices" /proc/kallsyms',
                        'cat /proc/iomem', 'cat /proc/interrupts',
                        'ls -l /proc/udm', 'cat /proc/udm/drivers',
                        'cat /proc/udm/dma330',
                        'cat /sys/module/dma330/sections/.bss', 'true']), timeout=20)
                    (run/'resource-observation.txt').write_bytes(observation)
                    match = re.search(rb'^([0-9a-fA-F]+)\s+[bBdDrR]\s+udif_devices\s*$',
                                      observation.replace(b'\r', b''), re.M)
                    if match is None:
                        raise RuntimeError('No exact runtime UDIF device table symbol')
                    address = int(match[1], 16)+0x240
                    if address < 0xffffff8000000000:
                        raise RuntimeError('UDIF table pointer is not a visible kernel address')
                    snapshot = {'scope': 'passive device/channel records only', 'device_address': hex(address)}
                    qmp('stop')
                    try:
                        if qmp('query-status')['running']:
                            raise RuntimeError('Owned VM did not pause')
                        raw = qmp('human-monitor-command', {'command-line': f'x /6gx 0x{address:x}'})
                        (run/'udif-device-monitor.txt').write_text(raw)
                        values = parse_monitor_words(raw, 6)
                        snapshot['device_words'] = [hex(v) for v in values]
                        channels, count = parse_device_words(values)
                        raw = qmp('human-monitor-command', {'command-line': f'x /342gx 0x{channels:x}'})
                        (run/'udif-channels-monitor.txt').write_text(raw)
                        snapshot['channel_words'] = [hex(v) for v in parse_monitor_words(raw, 342)]
                        snapshot['channel_count'] = count
                        if candidate_proof:
                            tree = qmp('human-monitor-command', {'command-line': 'info qtree'})
                            (run/'candidate-qtree.txt').write_text(tree)
                            snapshot['pl330_qom_instances'] = tree.count('dev: pl330,')
                            snapshot['pl330_readonly_ids'] = []
                            for physical in (0xf1056fe0, 0xf1057fe0):
                                reads = {}
                                for view, address, command_name in (
                                        ('physical', physical, 'xp'),
                                        ('kernel_virtual', int(snapshot['channel_words'][3 if physical == 0xf1056fe0 else 8*19+3], 16)+0xfe0, 'x')):
                                    raw = qmp('human-monitor-command', {'command-line': f'{command_name} /1wx 0x{address:x}'})
                                    (run/f'pl330-id-{physical:x}-{view}.txt').write_text(raw)
                                    try:
                                        reads[view] = parse_monitor_words(raw, 1)[0]
                                    except ValueError:
                                        if view != 'kernel_virtual':
                                            raise
                                        reads[view] = None  # explicit negative observation, not a zero register
                                snapshot['pl330_readonly_ids'].append(reads)
                        bss_match = re.search(rb'^(0xffffff[0-9a-f]+)\s*$', observation.replace(b'\r', b''), re.M)
                        if bss_match:
                            bss = int(bss_match[1], 16)
                            raw = qmp('human-monitor-command', {'command-line': f'x /9gx 0x{bss+0x2868:x}'})
                            (run/'channel-state-monitor.txt').write_text(raw)
                            snapshot['channel_state_words_2868'] = [hex(v) for v in parse_monitor_words(raw, 9)]
                    finally:
                        qmp('cont')
                        # Fresh guest output, independent of QMP running status, proves execution resumed.
                        token = 'DMA330_RESOURCE_CPU_RESUMED_'+run.name.replace('-', '_')
                        resumed = serial_command(proc, console, 'echo '+token, timeout=15)
                        (run/'resource-cpu-resumed.txt').write_bytes(resumed)
                        result['cpu_resumed_guest_output'] = ('\n'+token+'\n').encode() in resumed.replace(b'\r', b'')
                        if not result['cpu_resumed_guest_output']:
                            raise RuntimeError('No fresh guest CPU-resume output')
                    (run/'runtime-resources.json').write_text(json.dumps(snapshot, indent=2)+'\n')
                    result['resources_snapshot_complete'] = True
            except Exception as error:
                result['ok'] = False
                result['error'] = type(error).__name__+': '+str(error)
            finally:
                if (result.get('dma_owner_uncertain') or result.get('atu_owner_uncertain')) and proc is not None and proc.poll() is None:
                    result.update(ok=False, vm_exited=False, retained_no_force_kill=True)
                    (run/'result.json').write_text(json.dumps(result, indent=2)+'\n')
                    print('OWNED_DMA_VM_RETAINED_NO_COMPLETION', run, flush=True)
                    # Keep stdin/control and admission alive until the main
                    # session deliberately recovers this owned request/VM.
                    proc.wait()
                if proc is not None and proc.poll() is None:
                    try:
                        if wire is None:
                            raise RuntimeError('No owned control; retain process, do not force-kill')
                        qmp('quit')
                        proc.wait(timeout=15)
                    except Exception as error:
                        result['cleanup_error'] = str(error)
                result['vm_exited'] = proc is not None and proc.poll() is not None
                result['retained_no_force_kill'] = proc is not None and not result['vm_exited']
                if wire:
                    wire.close()
                if control:
                    control.close()
                (run/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        print('DMA330_MODULE_PROBE_RESULT', json.dumps(result), flush=True)
    return 0 if result['ok'] and result['vm_exited'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
