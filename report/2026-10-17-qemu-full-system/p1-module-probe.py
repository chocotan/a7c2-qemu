#!/usr/bin/env python3
"""Original p1 read-only module ABI probe; no updater, p2 change, USB or UI.

Source API (all outputs must be fresh, all paths are local regular files):
    create_instance(source_images, partinf, capacity_record, output)
    manifest = build(instance, p1_manifest, module_receipt, output,
                     qemu_build=..., board_runtime=..., qemu_user=...)
    result = actual(manifest, evidence_output, seconds=100)
    result = collect(serial_bytes, manifest)

CLI creates a dedicated disk from the read-only original dump, builds a minimal
p1 BusyBox/libc CPIO and a high-DDR/GICv2 diagnostic board, then optionally runs:
    python3 p1-module-probe.py --source IMAGES --partinf partinf.conf \
      --capacity-record block-devices.json --p1-manifest update-boot.json \
      --module-receipt p1-persistent-module.json --output NEW --actual

The production device requires O_RDWR on the inherited private disk FD. The
probe issues only reads and ro mounts; before/after full-disk SHA256 must match.
The lease remains held until the QEMU owner exits after normal QMP quit. Failed
QMP shutdown retains the owner and lease, with no TERM/KILL fallback. Evidence
is private (0600 files/0700 directories), including original error bytes and PC.
A pass establishes this module's exercised read path on the original p1 kernel;
all original init/updater execution and complete block ABI compatibility remain
unverified. The explicit initcall blacklist describes missing board peripherals.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import time

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
PERSIST = runpy.run_path(str(HERE / 'persistent-boot.py'))
DISK, COLD, GEOMETRY = (PERSIST[k] for k in ('DISK', 'COLD', 'GEOMETRY'))
UPDATE = runpy.run_path(str(HERE / 'update-boot.py'))
OWNER = runpy.run_path(str(HERE / 'boot-execution.py'))
PROFILE = 'original-p1-module-readonly-v1'
KERNEL_SHA = '9812ab13f73e6a98d0113f9500853739edcd5bb06e2952c42295b9dae06c758e'
MODULE_SHA = '5d069cd2c2eb5fbbd9d933e4768a65b0b71e3505fadcf245d5541a2e99a74383'
LEGACY_MODULE_SHA = 'cb602cc77e0d6bcac47b02844ff23edec86bd2b0a6abc8b118dfd15bbef39cb0'
MODULE_GENERATIONS = {LEGACY_MODULE_SHA: 'v4-readonly-large-write-bug', MODULE_SHA: 'v5-blk-queue-split'}
RELEASE = '4.9.186-scel'
DEFAULT_QEMU = PROJECT / 'analysis/scratch/a7c2-persistent-flash-20261106/production/build'
BLACKLIST = ('__boottime___udif_init_udif_wdt', '__boottime___udif_init_udif_fusb_otg',
             '__boottime___udif_init_udif_pcie', '__boottime___udif_init_udif_ddrc',
             '__boottime___udif_init_pcidma', '__boottime_sony_usb_init')


def save(path, value):
    DISK['save'](Path(path), value)


def binding(path):
    return COLD['binding'](path, 'p1-probe-input')


def module_generation(digest):
    if digest not in MODULE_GENERATIONS:
        raise ValueError('Unknown original-p1 module generation')
    return MODULE_GENERATIONS[digest]


def checked(row):
    actual_row = binding(row['path'])
    for key in ('bytes', 'sha256'):
        if actual_row[key] != row[key]:
            raise ValueError('Input identity differs: ' + row['path'] + ' ' + key)
    return actual_row


def create_instance(source_images, partinf, capacity_record, output):
    """One-time private instance creation; never read an active shared instance."""
    GEOMETRY['from_evidence'](partinf, capacity_record,
        PROJECT / 'analysis/extracted/firmware/0100_config/mount.conf', Path(source_images) / 'manifest.json')
    return DISK['create'](source_images, partinf, output, capacity_record=capacity_record)


def command_line(original):
    replaced = ('init=', 'rdinit=', 'initrd=', 'console=', 'rootfstype=', 'ramdisk_size=')
    words = [word for word in original.split() if word not in ('kemco', '*')
             and not word.startswith(replaced)]
    if any(word.startswith('initcall_blacklist=') for word in words):
        raise ValueError('Unexpected blacklist in original p1 parameters')
    return ' '.join(words + ['console=ttyAMA0', 'earlycon=pl011,0x09000000', 'loglevel=8',
        'init=/p1-probe', 'rdinit=/p1-probe', 'p1.probe=' + PROFILE,
        'initcall_debug', 'initcall_blacklist=' + ','.join(BLACKLIST)])


def board(base, libfdt, output, cmdline, initrd_bytes, *, mmc_iomap=False):
    """Adapt resource descriptions; MMC identification is a separate opt-in page."""
    if type(mmc_iomap) is not bool:
        raise ValueError('mmc_iomap must be an explicit bool')
    lib = ctypes.CDLL(str(libfdt))
    source = ctypes.create_string_buffer(Path(base).read_bytes())
    if lib.fdt_pack(source):
        raise ValueError('Cannot pack base DTB')
    buf = ctypes.create_string_buffer(65536)
    if lib.fdt_open_into(source, buf, len(buf)):
        raise ValueError('Cannot expand base DTB')
    def node(path):
        result = lib.fdt_path_offset(buf, path.encode())
        if result < 0:
            raise ValueError('Missing DTB node ' + path)
        return result
    def prop(offset, name, value):
        if lib.fdt_setprop(buf, offset, name.encode(), value, len(value)):
            raise ValueError('Cannot set DTB property ' + name)
    def add(name, properties):
        offset = lib.fdt_add_subnode(buf, 0, name.encode())
        if offset < 0:
            raise ValueError('DTB node collision ' + name)
        for key, value in properties.items():
            prop(offset, key, value)
    q = lambda value: value.to_bytes(8, 'big')
    chosen = node('/chosen')
    prop(chosen, 'bootargs', cmdline.encode('ascii') + b'\0')
    prop(chosen, 'linux,initrd-start', q(0x440000000))
    prop(chosen, 'linux,initrd-end', q(0x440000000 + initrd_bytes))
    prop(node('/memory@40000000'), 'reg', q(0x400000000) + q(0x200000000))
    for name, phys, virt, size in (
        ('sony-gic-alias', 0x08000000, 0xfffffffff13a1000, 0x1000),
        ('sony-register-backing', 0xf101d000, 0xfffffffff101d000, 0x20000),
        ('sony-scu-map', 0xf1388000, 0xfffffffff1388000, 0x2000),
        ('sony-timer-map', 0xf1042000, 0xfffffffff1042000, 0x4000)):
        add(name, {'device_type': b'iomap\0', 'phys': q(phys), 'virt': q(virt),
                   'size': q(size), 'memtype': (1).to_bytes(4, 'big')})
    if mmc_iomap:
        # udif_ioremap returns the original nonzero VA; never span the GIC alias.
        add('sony-mmc-identification-map', {
            'device_type': b'iomap\0', 'phys': q(0xf13b8000),
            'virt': q(0xfffffffff13b8000), 'size': q(0x1000),
            'memtype': (1).to_bytes(4, 'big')})
    add('persistent-flash@b000000', {
        'compatible': b'project,a7c2-functional-persistent-flash-v1\0',
        'reg': q(0x0b000000) + q(4096), 'status': b'okay\0'})
    if lib.fdt_pack(buf):
        raise ValueError('Cannot pack diagnostic DTB')
    Path(output).write_bytes(buf.raw[:int.from_bytes(buf.raw[4:8], 'big')])
    Path(output).chmod(0o600)


def read_contract(leased):
    """20 capacities and two independently checked sectors per exposed disk."""
    geometry = leased['geometry']
    rows = [dict(node='pnflasha', offset=0, bytes=geometry['user_bytes'])]
    for row in geometry['slices']:
        suffix = row['id'].removeprefix('nflasha')
        rows.append(dict(node=row['id'] if suffix.startswith('B') else 'cnflasha' + suffix,
                         offset=row['offset'], bytes=row['bytes']))
    if len(rows) != 20 or geometry['user_bytes'] != GEOMETRY['CAPACITY']:
        raise ValueError('Expected 20 original-capacity devices')
    samples = []
    for row in rows:
        sectors = row['bytes'] // 512
        random_sector = 1 + int.from_bytes(os.urandom(8), 'little') % (sectors - 1)
        for sector in (0, random_sector):
            data = os.pread(leased['fd'], 512, row['offset'] + sector * 512)
            if len(data) != 512:
                raise OSError('Short host sample')
            samples.append(dict(node=row['node'], sector=sector, bytes=512,
                                sha256=hashlib.sha256(data).hexdigest()))
    p7 = PERSIST['ext2_identities'](PERSIST['part'](leased, 'nflasha7'), ['/sbin/init2'])['/sbin/init2']
    files = [dict(id='p7', fs='ext2', node='cnflasha7', path='/sbin/init2', **p7)]
    read_fat = runpy.run_path(str(HERE / 'prepare-full-system.py'))['readFat']
    for entry in read_fat(PERSIST['part'](leased, 'nflasha11')):
        if entry.path != '/AccessLog.dat':
            continue
        if not stat.S_ISREG(entry.mode) or not 0 < entry.size < 4 * 1024**2:
            raise ValueError('Invalid original p11 AccessLog.dat')
        data = entry.contents.read(entry.size + 1)
        if len(data) != entry.size:
            raise OSError('Short original p11 file')
        files.append(dict(id='p11', fs='vfat', node='cnflasha11', path=entry.path,
                          bytes=entry.size, sha256=hashlib.sha256(data).hexdigest()))
    if len(files) != 2:
        raise ValueError('Missing original p11 readback file')
    return dict(capacities={row['node']: row['bytes'] // 512 for row in rows}, samples=samples, files=files)


def build(instance, p1_manifest, module_receipt, output, *, qemu_build=DEFAULT_QEMU,
          board_runtime=HERE / 'runtime', qemu_user=None):
    """Build a minimal diagnostic CPIO without modifying its p1 inputs or disk."""
    os.umask(0o077)
    instance, p1_manifest, module_receipt, qemu_build, board_runtime = map(
        lambda p: Path(p).resolve(strict=True), (instance, p1_manifest, module_receipt, qemu_build, board_runtime))
    output = PERSIST['fresh_output'](output, instance, p1_manifest.parent, module_receipt.parent, qemu_build, board_runtime)
    inputs = [binding(p1_manifest), binding(module_receipt), binding(qemu_build.parent / 'qemu-result.json')]
    try:
        p1 = json.loads(p1_manifest.read_text())
        receipt = json.loads(module_receipt.read_text())
        production = json.loads((qemu_build.parent / 'qemu-result.json').read_text())
        if (receipt.get('schema') != 'a7c2-original-p1-persistent-module-v1' or receipt.get('status') != 'compiled'
                or receipt.get('exports', {}).get('status') != 'verified' or receipt['exports'].get('missing') != []
                or receipt.get('force_load_allowed') is not False):
            raise ValueError('Expected checked p1 module receipt; force load refused')
        kernel = checked(receipt['original_kernel'])
        module = checked(receipt['module']['file'])
        generation = module_generation(module['sha256'])
        if kernel['sha256'] != KERNEL_SHA or kernel['bytes'] != 6582280:
            raise ValueError('Expected original p1 kernel')
        checked(p1['p1']['kernel.img'])
        if p1['p1']['kernel.img']['sha256'] != KERNEL_SHA:
            raise ValueError('p1 manifest kernel differs')
        if receipt['module']['vermagic'] != [RELEASE + ' SMP preempt mod_unload aarch64']:
            raise ValueError('Original p1 module vermagic differs')
        binary = binding(qemu_build / 'qemu-system-aarch64')
        if (production.get('status') != 'compiled' or production.get('board_profile') != 'persistent-flash-cold-v1'
                or production.get('test_fixture_only') is not False or binary['sha256'] != production.get('qemu_binary_sha256')):
            raise ValueError('Expected SHA-bound production persistent QEMU')
        squash = checked(p1['p1']['p1-root.squashfs'])
        kemco = checked(p1['p1']['kemco.txt'])
        inputs.extend((kernel, module, binary, squash, kemco, binding(HERE / 'guest/p1-module-probe-init'),
                       binding(HERE / 'guest/cold-start-audit.c'), binding(Path(__file__))))
        original = output / 'original-root'
        command = ['unsquashfs', '-no-progress', '-no-xattrs', '-processors', '2', '-d', str(original), squash['path']]
        result = subprocess.run(command, capture_output=True, timeout=40)
        (output / 'unsquashfs.stdout').write_bytes(result.stdout)
        (output / 'unsquashfs.stderr').write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError('p1 original squashfs extraction rc=' + str(result.returncode))
        root = output / 'root'
        for name in ('bin', 'lib', 'proc', 'sys', 'dev', 'tmp', 'qemu', 'mnt/p7', 'mnt/p11'):
            (root / name).mkdir(parents=True, exist_ok=True)
        helper_bindings = []
        for source in [original / 'bin/busybox', *sorted((original / 'lib').iterdir())]:
            destination = root / source.relative_to(original)
            if source.is_symlink():
                target = os.readlink(source)
                if Path(target).name != target or not (original / 'lib' / target).is_file():
                    raise ValueError('Unexpected original p1 library link')
                destination.symlink_to(target)
            else:
                row = binding(source); helper_bindings.append(row)
                COLD['clone'](source, destination, row['sha256'])
                destination.chmod(0o755)
        if b'2.25' not in (root / 'lib/libc-2.25.so').read_bytes():
            raise ValueError('Expected original p1 libc 2.25')
        (root / 'bin/sh').symlink_to('busybox')
        script = HERE / 'guest/p1-module-probe-init'
        script.read_bytes().decode('ascii')
        COLD['clone'](script, root / 'p1-probe', COLD['digest'](script)); (root / 'p1-probe').chmod(0o755)
        COLD['_compile_audit'](HERE / 'guest/cold-start-audit.c', root / 'lib/libc-2.25.so', root / 'qemu/audit')
        COLD['clone'](Path(module['path']), root / 'qemu/sony_persistent_flash.ko', module['sha256'])
        qemu_user = Path(qemu_user).resolve(strict=True) if qemu_user else qemu_build / 'qemu-aarch64'
        inputs.append(binding(qemu_user))
        applets = subprocess.run([str(qemu_user), '-L', str(root), str(root / 'bin/busybox'), '--list'],
                                 capture_output=True, timeout=15)
        (output / 'busybox.stdout').write_bytes(applets.stdout)
        (output / 'busybox.stderr').write_bytes(applets.stderr)
        required = {'sh', 'mount', 'umount', 'insmod', 'cat', 'dd', 'rm', 'sleep', 'uname'}
        if applets.returncode or not required <= set(applets.stdout.decode('ascii').split()):
            raise ValueError('Original p1 BusyBox lacks required applets')
        with DISK['lease'](instance) as leased:
            if (leased['state'].get('generation') != 0 or leased['state'].get('source_class') != 'private-device-dump'
                    or (instance / 'persistent-boot-adapter.json').exists()):
                raise ValueError('Probe requires an independent unadapted dump instance')
            disk_sha = DISK['hashed'](leased['fd'])
            if disk_sha != leased['state']['initial_disk_sha256']:
                raise ValueError('Probe disk differs from its original creation binding')
            contract = read_contract(leased)
            GEOMETRY['write_camera_wire'](leased['geometry'], output / 'persistent-geometry.bin')
            instance_binding = dict(instance=str(instance), disk_sha256=disk_sha,
                state=binding(instance / 'instance.json'), geometry=binding(instance / 'geometry.json'))
        (root / 'qemu/capacities').write_text(''.join(f'{n} {s}\n' for n, s in contract['capacities'].items()), encoding='ascii')
        (root / 'qemu/samples').write_text(''.join(f'{r["node"]} {r["sector"]} {r["sha256"]}\n' for r in contract['samples']), encoding='ascii')
        (root / 'qemu/files').write_text(''.join(f'{r["id"]} {r["fs"]} {r["node"]} {r["path"]} {r["bytes"]} {r["sha256"]}\n' for r in contract['files']), encoding='ascii')
        initrd = output / 'probe.cpio.gz'; UPDATE['archive'](root, initrd)
        cmdline = command_line(Path(kemco['path']).read_text())
        (output / 'cmdline.txt').write_text(cmdline + '\n', encoding='ascii')
        for source, name in ((Path(kernel['path']), 'kernel.img'),
                             (board_runtime / 'analysis/boot-handoff.bin', 'boot-handoff.bin')):
            row = binding(source); inputs.append(row); COLD['clone'](source, output / name, row['sha256'])
        base = board_runtime / 'analysis/boards/virt-four.dtb'
        libfdt = (board_runtime / 'sources/qemu-tools/usr/lib/libfdt.so.1').resolve(strict=True)
        inputs.extend((binding(base), binding(libfdt)))
        board(base, libfdt, output / 'virt.dtb', cmdline, initrd.stat().st_size)
        artifacts = [binding(p) for p in (output / 'kernel.img', output / 'boot-handoff.bin', initrd,
                     output / 'virt.dtb', output / 'persistent-geometry.bin', output / 'cmdline.txt')]
        for row in inputs + helper_bindings:
            checked(row)
        manifest = dict(schema=PROFILE, status='built', **instance_binding, **contract,
            output=str(output), kernel=kernel, module=module, module_generation=generation, qemu=binary, cmdline=cmdline,
            p1_parameter_reference=kemco, inputs=inputs, artifacts=artifacts,
            helpers=helper_bindings, applets=sorted(required), dynamic_loader_mode='0755',
            initrd_bytes=initrd.stat().st_size, original_squashfs=squash,
            board=dict(host_ram_mib=24576, linux_ddr_base=hex(0x400000000), linux_ddr_bytes=0x200000000,
                       kernel_load=hex(0x400080000), initrd_load=hex(0x440000000),
                       dtb_load=hex(0x400002000), entry=hex(0x400010000), gic_version=2,
                       counter_hz=2000000, initcall_blacklist=list(BLACKLIST)),
            guest_abi_verified=False, full_block_abi_verified=False, updater_executed=False,
            p2_flags_changed=False, physical_devices_used=False)
        save(output / 'manifest.json', manifest)
        return manifest
    except BaseException as error:
        save(output / 'failure.json', dict(error=type(error).__name__ + ': ' + str(error), guest_started=False))
        raise


def launch_command(manifest, fd, output):
    """Only the geometry is mounted from the instance; disk access uses pass_fds."""
    work = Path(manifest['output']); binary = Path(manifest['qemu']['path'])
    command = ['bwrap', '--unshare-all', '--new-session', '--clearenv',
        '--ro-bind', '/usr', '/usr', '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib', '/lib64',
        '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
        '--ro-bind', str(binary.parent), '/tools', '--ro-bind', str(work), '/probe',
        '--dir', '/instance', '--ro-bind', str(work / 'persistent-geometry.bin'), '/instance/persistent-geometry.bin',
        '--bind', str(output), '/out', '--chdir', '/', '--setenv', 'LC_ALL', 'C',
        '--setenv', 'QEMU_SONY_TIMERS', '1', '--setenv', 'QEMU_A7PF_PROFILE', 'persistent-flash-cold-v1']
    st = os.fstat(fd)
    for key, value in (('FD', fd), ('DEV', st.st_dev), ('INO', st.st_ino)):
        command += ['--setenv', 'QEMU_A7PF_' + key, str(value)]
    command += ['/tools/' + binary.name, '-accel', 'tcg,thread=single', '-machine', 'virt,secure=off,gic-version=2',
        '-cpu', 'cortex-a35,cntfrq=2000000', '-smp', '4', '-m', '24576', '-nodefaults',
        '-display', 'none', '-monitor', 'none', '-serial', 'stdio', '-nic', 'none',
        '-no-reboot', '-sandbox', 'on', '-qmp', 'unix:/out/qmp.sock,server=on,wait=off']
    for name, address in (('virt.dtb', '0x400002000'), ('kernel.img', '0x400080000'),
                          ('probe.cpio.gz', '0x440000000'), ('boot-handoff.bin', '0x400010000')):
        command += ['-device', f'loader,file=/probe/{name},addr={address},force-raw=on']
    command += ['-device', 'loader,addr=0x400010000,cpu-num=0', '-d', 'guest_errors,unimp', '-D', '/out/trace.log']
    return command


def collect(raw, manifest):
    text = raw.decode('utf-8', errors='replace').replace('\r', '')
    credentials = re.findall(r'^P1_CREDENTIAL kind=(Uid:|Gid:) values=(.*)$', text, re.M)
    modules = re.findall(r'^P1_MODULES_BEGIN\n(.*?)^P1_MODULES_END$', text, re.M | re.S)
    capacity = re.findall(r'^P1_CAPACITY node=(\S+) expected=(\d+) actual=(\d+)$', text, re.M)
    reads = re.findall(r'^P1_READ node=(\S+) sector=(\d+) bytes=(\d+) sha256=([0-9a-f]{64})$', text, re.M)
    expected_reads = [(r['node'], str(r['sector']), str(r['bytes']), r['sha256']) for r in manifest['samples']]
    mount_results = {}
    for row in manifest['files']:
        identity = row['id']
        info = re.findall(r'^P1_MOUNTINFO_BEGIN id=' + identity + r'\n(.*?)^P1_MOUNTINFO_END id=' + identity + '$', text, re.M | re.S)
        mounted_ro = False
        if len(info) == 1:
            for line in info[0].splitlines():
                fields = line.split()
                if len(fields) >= 10 and fields[4] == '/mnt/' + identity and '-' in fields:
                    sep = fields.index('-')
                    mounted_ro = (fields[sep+1:sep+3] == [row['fs'], '/dev/' + row['node']]
                        and 'ro' in fields[5].split(',') and 'ro' in fields[sep+3].split(','))
        mount_results[identity] = dict(mounted_readonly=mounted_ro,
            file_readback=text.count(f'P1_FILE id={identity} bytes={row["bytes"]} sha256={row["sha256"]}\n') == 1,
            unmounted=text.count(f'P1_UNMOUNT id={identity} rc=0\n') == 1)
    failures = re.findall(r'^P1_FAIL stage=(\S+) rc=(\S+)$', text, re.M)
    result = dict(root_verified=credentials == [('Uid:', '0,0,0,0'), ('Gid:', '0,0,0,0')],
        module_loaded=(text.count('P1_INSMOD rc=0\n') == 1 and len(modules) == 1 and
            re.search(r'^sony_persistent_flash \d+ \d+ .* Live ', modules[0], re.M) is not None),
        kernel_release_verified=text.count('P1_RELEASE value=' + RELEASE + '\n') == 1,
        capacity_rows=len(capacity), capacities_verified=(len(capacity) == len(manifest['capacities']) and
            sorted(capacity) == sorted((n, str(s), str(s)) for n, s in manifest['capacities'].items())),
        sample_rows=len(reads), readback_verified=reads == expected_reads, mounts=mount_results,
        completed=text.count('P1_PROBE_COMPLETE\n') == 1,
        first_guest_error=dict(stage=failures[0][0], rc=failures[0][1]) if failures else None,
        original_error_lines=re.findall(r'^.*(?:Kernel panic|Internal error|Unknown symbol|disagrees about version|Failed to execute|invalid module format).*$' , text, re.M),
        raw_serial_sha256=hashlib.sha256(raw).hexdigest(), full_block_abi_verified=False,
        original_init_executed=False, updater_executed=False, physical_compatibility=False)
    result['guest_read_path_verified'] = (all(result[k] for k in ('root_verified', 'module_loaded',
        'kernel_release_verified', 'capacities_verified', 'readback_verified', 'completed'))
        and all(all(value.values()) for value in mount_results.values()) and not failures
        and not any(error in text for error in ('Kernel panic', 'Internal error: Oops', 'BUG:')))
    return result


def actual(manifest, output, seconds=100):
    """Retain the lease through normal QMP quit and an observed owner exit."""
    if manifest.get('schema') != PROFILE or manifest.get('status') != 'built' or seconds <= 0:
        raise ValueError('Invalid probe manifest/deadline')
    os.umask(0o077)
    output = PERSIST['fresh_output'](output, manifest['instance'], manifest['output'])
    serial = output / 'serial.log'
    result = dict(schema=PROFILE, status='starting', vm_signals=[], guest_started=False, verified=False)
    process = connection = stream = command = None
    with DISK['lease'](manifest['instance']) as leased:
        try:
            for row in manifest['inputs'] + manifest['artifacts'] + [manifest['state'], manifest['geometry']]:
                checked(row)
            before = DISK['hashed'](leased['fd'])
            if before != manifest['disk_sha256']:
                raise ValueError('Private probe disk changed before launch')
            argv = launch_command(manifest, leased['fd'], output)
            with serial.open('xb') as log:
                process = subprocess.Popen(argv, env=dict(PATH=os.defpath, LC_ALL='C'),
                    pass_fds=(leased['fd'],), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            result.update(status='running', guest_started=True, pid=process.pid, command=argv,
                pass_fds=[leased['fd']], disk_before_sha256=before,
                disk_dev=os.fstat(leased['fd']).st_dev, disk_ino=os.fstat(leased['fd']).st_ino)
            save(output / 'result.json', result)
            deadline = time.monotonic() + seconds
            while True:
                raw = serial.read_bytes()
                if b'P1_PROBE_COMPLETE' in raw or b'P1_FAIL ' in raw or b'Kernel panic' in raw or b'Internal error: Oops' in raw:
                    break
                if process.poll() is not None:
                    result['first_host_error'] = 'Owner exited before terminal guest evidence'; break
                if time.monotonic() >= deadline:
                    result['first_host_error'] = 'Observation deadline reached'; break
                time.sleep(.1)
        except BaseException as error:
            result['first_host_error'] = type(error).__name__ + ': ' + str(error)
        finally:
            if process is not None and process.poll() is None:
                try:
                    connection, stream, command = OWNER['qmp_connect'](output / 'qmp.sock')
                    result['qmp_status'] = command('query-status')
                    result['registers'] = command('human-monitor-command', {'command-line': 'info registers'})
                    result['qmp_quit'] = command('quit')
                    process.wait(timeout=20)
                except BaseException as error:
                    result.update(shutdown_error=type(error).__name__ + ': ' + str(error),
                                  status='owner-retained', lease_held_until_exit=True)
                    save(output / 'result.json', result)
                    process.wait()
                finally:
                    if stream: stream.close()
                    if connection: connection.close()
            if process is not None:
                result['owner_returncode'] = process.returncode
                result['vm_signals'] = [process.returncode] if process.returncode is not None and process.returncode < 0 else []
            result.update(collect(serial.read_bytes() if serial.exists() else b'', manifest))
            after = DISK['hashed'](leased['fd'])
            result['disk_after_sha256'] = after
            result['disk_unchanged'] = after == result.get('disk_before_sha256')
            result['normal_exit_verified'] = (result.get('owner_returncode') == 0 and
                result.get('qmp_quit') == {'return': {}} and not result['vm_signals'])
            result['verified'] = (result['guest_read_path_verified'] and result['disk_unchanged'] and
                result['normal_exit_verified'] and not result.get('first_host_error') and not result.get('shutdown_error'))
            result['status'] = 'passed' if result['verified'] else 'failed'
            save(output / 'result.json', result)
    result['lease_released_after_owner_exit'] = True
    save(output / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('source', 'partinf', 'capacity-record', 'p1-manifest', 'module-receipt', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu-build', type=Path, default=DEFAULT_QEMU)
    parser.add_argument('--board-runtime', type=Path, default=HERE / 'runtime')
    parser.add_argument('--actual', action='store_true')
    parser.add_argument('--seconds', type=float, default=100)
    args = parser.parse_args()
    os.umask(0o077)
    output = PERSIST['fresh_output'](args.output, args.source, args.p1_manifest.parent, args.module_receipt.parent)
    create_instance(args.source, args.partinf, args.capacity_record, output / 'instance')
    manifest = build(output / 'instance', args.p1_manifest, args.module_receipt, output / 'build',
                     qemu_build=args.qemu_build, board_runtime=args.board_runtime)
    if args.actual:
        result = actual(manifest, output / 'guest', seconds=args.seconds)
        print(json.dumps(result, indent=2), flush=True)
        return 0 if result['verified'] else 1
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
