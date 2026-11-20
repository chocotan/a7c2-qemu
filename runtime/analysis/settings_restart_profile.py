#!/usr/bin/env python3
"""One explicit profile: functional-camera 1GiB RAM capture card plus one
independent persistent internal disk, resumed across two separate boots.

Default off.  Nothing here opens the combination by itself: the product launcher,
the menu and the admitted RAM-card driver keep their current routes unless the
exact profile string is present.  Existing identity, exclusive-lease, quarantine
and freeze guards are reused, never replaced by an environment flag.

Capture media stays the 1GiB RAM card (`/image_mmca`); only `/setting`, `/usr`,
`/tmp` and `/log` come from the internal disk.  A second boot is admitted only
from the original-App normal-shutdown receipts this module reads as data; the
driver that produces them is not imported, so producer and consumer stay
decoupled behind one explicit schema.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

PROFILE = 'functional-ram-card-independent-internal-v1'
RAM_MEDIA = 'direct-bootin-ram-card-1g-v1'
RAM_CONSUMER = 'inherited-ram-card-fds-v1'
PRODUCER = 'production-derive-v1'
STORAGE = 'product-single-disk-v1'
BOOT = 'direct-bootin'
INTERNAL_BYTES = 1954545664 + 2 * 4194304
GIB = 1024**3
RESERVE_BYTES = 64 * GIB
CHUNK = 1024**2
EXPECTED = {
    'A7C2_SETTINGS_RESTART_PROFILE': PROFILE,
    'A7C2_FUNCTIONAL_CAMERA_MEDIA': RAM_MEDIA,
    'A7C2_FUNCTIONAL_RAM_CONSUMER': RAM_CONSUMER,
    'A7C2_RAM_CARD_PRODUCER_ADMITTED': PRODUCER,
    'A7C2_STORAGE_PROFILE': STORAGE,
    'A7C2_BOOT_PROFILE': BOOT,
    'MENU_BACKUP_SAVE': '1',
    'QEMU_CPU_COUNT': '1',
}
# Every other storage/media route stays closed for this profile.
CONFLICTS = ('A7C2_DIRECTORY_SD', 'A7C2_DIRECTORY_SD_PROFILE', 'A7C2_HOST_SD',
             'A7C2_SD_SPARSE', 'A7C2_SD_HOTPLUG', 'MENU_USB_NET', 'A7C2_USB_NET',
             'QEMU_SONY_USB_NET', 'A7C2_USB_NET_SELFTEST', 'QEMU_NATIVE_AP_CP_LINK',
             'A7C2_RAM_WINDOW', 'A7C2_RAM_RESTORE_STREAM', 'A7C2_RAM_QEMU',
             'A7C2_SETTINGS_RESTORE', 'A7C2_SETTINGS_RESTORE_SHA', 'A7C2_SETTINGS_PERSIST',
             'A7C2_ORIGINAL_COLD', 'A7C2_STORAGE_RESTORE_FILE', 'A7C2_STORAGE_RESTORE_SELECTION',
             'A7C2_USE_PERSISTENT_STORAGE')
POWEROFF_SCHEMA = 'a7c2-original-poweroff-v1'
SECOND_BOOT_SCHEMA = 'a7c2-second-boot-shutdown-v1'
PREPARE_SCHEMA = 'a7c2-settings-restart-prepare-v1'
FREEZE_SCHEMA = 'a7c2-settings-restart-freeze-v1'
STOPPED_SCHEMA = 'a7c2-settings-restart-stopped-v1'
POWEROFF_RECEIPT = 'poweroff-receipt.json'
SECOND_BOOT_RECEIPT = 'second-boot-shutdown-receipt.json'
SETTINGS_TREE = ('echo SETTINGS_RESTART_TREE_BEGIN; '
                 '/bin/busybox wc -c < /setting/Backup.bin; '
                 '/usr/bin/openssl dgst -sha256 /setting/Backup.bin; '
                 '/bin/busybox find /setting -type f -exec /bin/busybox wc -c {} + ; '
                 'echo SETTINGS_RESTART_TREE_END; true')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save_new(path, value):
    """Exclusive publication: an older receipt or failure record is never replaced."""
    raw = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    with Path(path).open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(Path(path).read_bytes() == raw, 'Receipt readback differs: ' + str(path))


def digest_range(fd, offset, length):
    h = hashlib.sha256()
    while length:
        raw = os.pread(fd, min(length, CHUNK), offset)
        require(bool(raw), 'Truncated disk readback')
        h.update(raw)
        offset += len(raw)
        length -= len(raw)
    return h.hexdigest()


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require_combination(environment):
    """Exact explicit combination, and nothing else may select storage or media."""
    require(all(environment.get(key) == value for key, value in EXPECTED.items()),
            'the exact explicit settings-restart combination is required')
    require(not any(environment.get(key) for key in CONFLICTS),
            'conflicting storage/USB/CP/restore route selected')
    require(bool(environment.get('A7C2_SD_IMAGE')), 'the original 1GiB RAM seed path is required')
    for key in ('A7C2_EMMC_FD', 'A7C2_EMMC_DEV', 'A7C2_EMMC_INO'):
        value = environment.get(key, '')
        require(value.isascii() and value.isdigit(), 'inherited internal identity is required: ' + key)


def required_peak(driver_peak_bytes):
    """Disk plus its full separate rollback copy plus the caller's own peak."""
    require(type(driver_peak_bytes) is int and driver_peak_bytes >= 0,
            'declare every other concurrent byte peak explicitly')
    return 2 * INTERNAL_BYTES + driver_peak_bytes


def budget(free_bytes, peak_bytes):
    require(type(peak_bytes) is int and peak_bytes >= 0, 'full peak budget must be explicit')
    require(type(free_bytes) is int and free_bytes >= RESERVE_BYTES + peak_bytes,
            '64GiB reserve plus this run peak is not available')


def persistent_environment(binary=None, proof_path=None):
    """Reuse the product persistent build proof for exactly this executable."""
    import persistent_storage
    return persistent_storage.binary_environment(binary, proof_path=proof_path)


def create_once(base):
    """Create the one independent instance; an existing instance is never reused."""
    import persistent_storage
    base = Path(os.path.abspath(base))
    require('..' not in base.parts and not any(p.is_symlink() for p in (*base.parents, base)),
            'independent instance requires ordinary absolute directories')
    require(base != persistent_storage.ANALYSIS / 'persistent-storage',
            'the product default instance is not a task instance')
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(stat.S_IMODE(base.stat().st_mode) == 0o700 and base.stat().st_uid == os.geteuid(),
            'independent instance parent must be private and owned')
    require(not os.path.lexists(base / 'default'),
            'independent instance already exists; never recreate or reseed')
    instance = persistent_storage.ensure_instance(base)
    require(instance == base / 'default' and instance.is_dir(), 'instance creation route differs')
    return instance


def require_prepared_instance(instance):
    """Accept only this task's independently prepared instance, never the default one."""
    import persistent_storage
    instance = Path(os.path.abspath(instance))
    require(instance != persistent_storage.ANALYSIS / 'persistent-storage' / 'default',
            'the product default instance is not a task instance')
    receipt = instance.parent / 'prepare.json'
    require(receipt.is_file() and not receipt.is_symlink(),
            'independent instance has no prepare receipt')
    value = json.loads(receipt.read_bytes())
    require(value.get('schema') == PREPARE_SCHEMA and value.get('instance') == str(instance),
            'independent instance prepare receipt belongs to another instance')
    require(value.get('created_once') is True and value.get('default_instance_untouched') is True,
            'independent instance was not created exactly once')
    require(value.get('restore', {}).get('sha256') == value.get('baseline', {}).get('sha256'),
            'restore point does not bind the pre-boot baseline')
    return value


def adapted_setup(commands, mount_commands, *, boot):
    """Rewrite one candidate RAM-card setup so /setting comes from the internal disk.

    Boot 1 keeps the original power-on record preparation of the admitted
    first-boot route.  Boot 2 repeats no seed at all: no seed copy, no identity
    image, no power-on record and no date/clock reseed.
    """
    require(boot in (1, 2), 'boot must be 1 or 2')
    replacements = {
        'mount -t tmpfs tmpfs /tmp': [],
        'mount -t tmpfs tmpfs /setting': [],
        'cp /seed-backup.bin /setting/Backup.bin': [
            'test -s /setting/Backup.bin || { echo SETTINGS_RESTART_FAILED=backup; exit 1; }'],
        'insmod /usr/kmod/backup.ko Backup_load=1 Backup_save=0': [
            'insmod /usr/kmod/backup.ko Backup_load=1 Backup_save=1 || { echo SETTINGS_RESTART_FAILED=backup-module; exit 1; }'],
        'cp -a /seed-setting/. /setting/': [
            'test -s /setting/DmmCfg.bin || { echo SETTINGS_RESTART_FAILED=dmmcfg; exit 1; }'],
        'mkdir -p /setting/updater /mnt; cp /simulation/firmware-version.dat4 /setting/updater/dat4': [
            'mkdir -p /mnt; test -s /setting/updater/dat4 || { echo SETTINGS_RESTART_FAILED=dat4; exit 1; }'],
        # The internal disk already owns /dev/nflasha1; the RAM alias would shadow it.
        'mknod /dev/ram1 b 1 1; ln -s /dev/ram1 /dev/nflasha1': [
            'test -b /dev/nflasha1 || { echo SETTINGS_RESTART_FAILED=identity-alias; exit 1; }'],
        'dd if=/simulation/firmware-identity.fat of=/dev/ram1 bs=4096': [],
        'if { test -d /sys/module/udate || insmod /usr/kmod/udate.ko; } && /simulation/seed-date-clock; then touch /tmp/date-clock.ready; echo DATE_CLOCK_INIT_OK; else echo DATE_CLOCK_INIT_FAILED; exit 1; fi': [
            # seed-date-clock would commit the firmware default under Backup_save=1.
            '{ test -d /sys/module/udate || insmod /usr/kmod/udate.ko; } || { echo SETTINGS_RESTART_FAILED=udate; exit 1; }',
            'echo DATE_CLOCK_RESTORE=original-loader'],
    }
    power_on = '/simulation/seed-power-on 1 && echo POWER_ON_SEED_STATUS=0 || { echo POWER_ON_SEED_FAILED; exit 1; }'
    require(commands.count(power_on) == 1, 'candidate setup source drift: power-on record')
    require(all(commands.count(command) == 1 for command in replacements),
            'candidate setup source drift: settings seed')
    require(commands.count('mount -t sysfs sysfs /sys') == 1, 'unique sysfs mount required')
    require(any('/dev/cnflasha2 /setting' in command for command in mount_commands),
            'the product internal /setting mount is required')
    result = []
    for command in commands:
        if command == power_on and boot == 2:
            # Boot 2 must not rewrite the loader boot-type record on the saved disk.
            result.append('echo POWER_ON_RECORD=preserved')
            continue
        result.extend(replacements.get(command, [command]))
        if command == 'mount -t sysfs sysfs /sys':
            result.extend(mount_commands)
    require(not any('/seed-setting' in command or '/seed-backup.bin' in command
                    for command in result), 'a settings seed survived the rewrite')
    require(sum('/dev/ram1' in command for command in result) == 0, 'RAM identity alias survived')
    if boot == 2:
        require(power_on not in result and not any('seed-power-on' in c for c in result),
                'boot 2 must not reseed the power-on record')
    return result


class Session:
    """Create once, lease, snapshot, freeze, and admit exactly one second boot."""

    def __init__(self, base, *, driver_peak_bytes, binary=None, proof_path=None):
        self.base = Path(os.path.abspath(base))
        self.driver_peak_bytes = driver_peak_bytes
        self.binary = binary
        self.proof_path = proof_path
        self.peak_bytes = required_peak(driver_peak_bytes)
        self.instance = None
        self.context = None
        self.leased = None
        self.inherited = None
        self.baseline = None
        self.restore = None
        self.frozen = None
        self.stopped = None
        self.boot = 1

    # -- creation, rollback point, reads -------------------------------------
    def prepare(self):
        require(self.leased is None and self.context is None, 'session already prepared')
        self.base.parent.mkdir(parents=True, exist_ok=True)
        mount = os.statvfs(self.base.parent)
        free = mount.f_bavail * mount.f_frsize
        budget(free, self.peak_bytes)
        self.instance = create_once(self.base)
        import persistent_storage
        self.context = persistent_storage.instance_lease(self.instance)
        self.leased = self.context.__enter__()
        slices = self.leased['geometry']['slices']
        require(len(slices) == 19 and len({row['id'] for row in slices}) == 19,
                'nineteen distinct internal slices required')
        self.baseline = self.snapshot()
        # Restore point is a recovery-only artifact never consumed on the happy
        # path; materializing it costs a full 2GiB write + readback per run.
        # Bind it lazily to the verified baseline (sha equality still required
        # by require_prepared_instance); restore_copy refuses until it exists.
        self.restore = dict(lazy=True, bytes=self.baseline['bytes'],
                            sha256=self.baseline['sha256'], path=None,
                            source=dict(device=self.baseline['device'],
                                        inode=self.baseline['inode'],
                                        bytes=self.baseline['bytes']))
        save_new(self.base / 'prepare.json', dict(
            schema=PREPARE_SCHEMA, profile=PROFILE, instance=str(self.instance),
            internal_bytes=INTERNAL_BYTES, peak_bytes=self.peak_bytes,
            available_before=free, budget_ok=True, created_once=True,
            default_instance_untouched=True, baseline=self.baseline, restore=self.restore,
            lease=dict(path=str(self.leased['path']), fd=self.leased['fd'])))
        return self.baseline

    def snapshot(self):
        """Full disk plus all nineteen slices, while the exclusive lease is held."""
        require(self.leased is not None, 'snapshot requires the held lease')
        fd = self.leased['fd']
        before = os.fstat(fd)
        named = Path(self.leased['path']) / 'camera.emmc'
        info = named.lstat()
        require(stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == (before.st_dev, before.st_ino),
                'internal disk path identity changed')
        geometry = self.leased['geometry']
        require(before.st_size == geometry['backing_bytes'], 'internal backing length changed')
        for row in geometry['slices']:
            require(type(row['offset']) is int and type(row['bytes']) is int and
                    row['offset'] >= 0 and row['bytes'] > 0 and
                    row['offset'] + row['bytes'] <= before.st_size, 'invalid internal slice range')
        value = dict(path=str(named), device=before.st_dev, inode=before.st_ino,
                     bytes=before.st_size, sha256=digest_range(fd, 0, before.st_size),
                     slices={row['id']: digest_range(fd, row['offset'], row['bytes'])
                             for row in geometry['slices']})
        after = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size) ==
                (after.st_dev, after.st_ino, after.st_size), 'internal disk changed during readback')
        return value

    def restore_point(self):
        """One full separate copy taken before the first writable consumer.

        Only a disk this session created may be copied, and only while this
        session holds the exclusive lease; a live instance is never cloned.
        """
        require(self.restore is None, 'restore point is taken exactly once')
        require(self.leased is not None and self.baseline is not None, 'restore requires the held lease')
        require(not any(self.instance.glob('run-*')), 'instance already carries run receipts; not fresh')
        target = self.base / 'restore-point' / 'camera.emmc'
        directory = target.parent
        require(not os.path.lexists(directory), 'restore point already exists')
        directory.mkdir(mode=0o700)
        source = self.leased['fd']
        before = os.fstat(source)
        h = hashlib.sha256()
        with target.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            offset = 0
            while offset < before.st_size:
                raw = os.pread(source, min(CHUNK, before.st_size - offset), offset)
                require(bool(raw), 'truncated restore-point source read')
                stream.write(raw)
                h.update(raw)
                offset += len(raw)
            stream.flush()
            os.fsync(stream.fileno())
        require(h.hexdigest() == self.baseline['sha256'], 'restore point differs from the baseline')
        with target.open('rb') as stream:
            require(hashlib.file_digest(stream, 'sha256').hexdigest() == self.baseline['sha256'],
                    'restore point readback differs')
        info = target.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == before.st_size,
                'restore point must be one ordinary file, never a link')
        after = os.fstat(source)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                'internal disk changed while copying the restore point')
        return dict(path=str(target), bytes=info.st_size, sha256=self.baseline['sha256'],
                    device=info.st_dev, inode=info.st_ino, links=info.st_nlink,
                    source=dict(device=before.st_dev, inode=before.st_ino, bytes=before.st_size))

    def restore_copy(self, target_dir):
        """Recover the pre-first-boot state into a new directory; never in place."""
        require(self.restore is not None, 'no verified restore point in this session')
        require(not self.restore.get('lazy'), 'restore point is lazy-bound; no materialized copy exists')
        require(not os.path.lexists(target_dir), 'restore target must be fresh')
        target = Path(os.path.abspath(target_dir))
        target.mkdir(mode=0o700, parents=False)
        destination = target / 'camera.emmc'
        with Path(self.restore['path']).open('rb') as stream, destination.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            while True:
                raw = stream.read(CHUNK)
                if not raw:
                    break
                output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        require(file_sha(destination) == self.restore['sha256'], 'restored copy differs from the restore point')
        save_new(target / 'restore-source.json',
                 dict(source=self.restore['path'], sha256=self.restore['sha256']))
        return str(destination)

    # -- environment and derivation -----------------------------------------
    def bind_environment(self, environment, number=60):
        """Add the inherited internal descriptor and the exact profile markers."""
        require(self.leased is not None, 'bind requires the held lease')
        import persistent_storage
        dup = fcntl.fcntl(self.leased['fd'], fcntl.F_DUPFD_CLOEXEC, number)
        info = os.fstat(dup)
        require(dup != self.leased['fd'] and info.st_size == INTERNAL_BYTES,
                'inherited internal descriptor is not the instance disk')
        merged = dict(environment)
        merged.update(A7C2_SETTINGS_RESTART_PROFILE=PROFILE, MENU_BACKUP_SAVE='1')
        merged.update(persistent_storage.inherited_environment(
            dict(self.leased, fd=dup), self.binary, proof_path=self.proof_path))
        self.inherited = dict(fd=dup, device=info.st_dev, inode=info.st_ino,
                              path=str(self.leased['path']), bytes=info.st_size)
        require_combination(merged)
        return merged

    def derive(self, base, seed, output_dir, *, base_sha256, seed_sha256, parallel_peak_bytes):
        """Verified base, then the product adapter, then the RAM-card derivation.

        The adapter output is the derive input so the published v3 receipt covers
        the exact archive that the consumer will bind.
        """
        import functional_ram_initramfs as ram
        import persistent_storage
        require(type(parallel_peak_bytes) is int and parallel_peak_bytes >= 0,
                'declare every other concurrent byte peak explicitly')
        out = Path(os.path.abspath(output_dir))
        require(not os.path.lexists(out), 'derivation output must be fresh')
        out.mkdir(mode=0o700)
        augmented = out / 'persistent-base.cpio'
        manifest = persistent_storage.augment_initramfs(Path(base), augmented)
        binding = ram.derive(augmented, seed, out / 'ram-card',
                            base_sha256=file_sha(augmented), seed_sha256=seed_sha256,
                            functional_camera=True, parallel_peak_bytes=parallel_peak_bytes)
        verified = ram.verify_for_consumer(binding)
        receipt = dict(schema='a7c2-settings-restart-derivation-v1', profile=PROFILE,
                       base=dict(path=str(Path(base).absolute()), sha256=base_sha256),
                       adapter=dict(path=str(augmented), sha256=file_sha(augmented)),
                       adapter_manifest=manifest, binding=binding, verified=verified,
                       order='verified base -> persistent_storage.augment_initramfs -> '
                             'functional_ram_initramfs.derive -> verify_for_consumer')
        save_new(out / 'settings-restart-derivation.json', receipt)
        return receipt

    # -- shutdown, freeze, second boot --------------------------------------
    def require_normal_shutdown(self, run):
        """Only the original normal shutdown receipts admit a second boot."""
        run = Path(run)
        second_path = run / SECOND_BOOT_RECEIPT
        poweroff_path = run / POWEROFF_RECEIPT
        require(second_path.is_file() and not second_path.is_symlink(),
                'no normal shutdown receipt; a second boot is not admitted')
        require(poweroff_path.is_file() and not poweroff_path.is_symlink(),
                'no original power-off receipt; a second boot is not admitted')
        second = json.loads(second_path.read_bytes())
        poweroff = json.loads(poweroff_path.read_bytes())
        require(second.get('schema') == SECOND_BOOT_SCHEMA, 'unknown second-boot receipt schema')
        require(second.get('natural_shutdown') is True, 'shutdown was not a natural original shutdown')
        require(second.get('run') == str(run), 'second-boot receipt belongs to another run')
        require(re.fullmatch('[0-9a-f]{64}', str(second.get('shutdown_receipt_sha256'))) is not None,
                'second-boot receipt carries no shutdown receipt digest')
        require(second['shutdown_receipt_sha256'] == file_sha(poweroff_path),
                'second-boot receipt does not bind this power-off receipt')
        require(poweroff.get('schema') == POWEROFF_SCHEMA, 'unknown power-off receipt schema')
        require(poweroff.get('quit_authorized') is True, 'power-off receipt does not authorize the stop')
        require(poweroff.get('signals_sent') == [] and poweroff.get('qmp_quit_sent') is False,
                'power-off receipt is not observation-only')
        require(second.get('settings_identity') == poweroff.get('settings_identity'),
                'second-boot receipt settings identity differs')
        return dict(schema=SECOND_BOOT_SCHEMA, run=str(run),
                    shutdown_receipt_sha256=second['shutdown_receipt_sha256'],
                    second_boot_sha256=file_sha(second_path),
                    settings_identity=poweroff.get('settings_identity'))

    def freeze(self, serial, run):
        """Existing product freeze (1 19) plus a frozen disk and settings readback."""
        run = Path(run)
        import persistent_storage
        receipt = persistent_storage.prepare_shutdown(serial, run)
        self.frozen = self.snapshot()
        raw = serial(SETTINGS_TREE)
        (run / 'settings-restart-tree.raw').write_bytes(raw)
        body = raw.replace(b'\r\n', b'\n')
        require(b'SETTINGS_RESTART_TREE_BEGIN\n' in body and b'SETTINGS_RESTART_TREE_END' in body,
                'frozen settings tree readback is incomplete')
        backup = re.findall(rb'\b([0-9a-f]{64})\b', body)
        sizes = re.findall(rb'^([0-9]+) ', body, re.M)
        value = dict(schema=FREEZE_SCHEMA, run=str(run), profile=PROFILE,
                     frozen_partitions=receipt.get('frozen_partitions'),
                     frozen_receipt=receipt, disk=self.frozen,
                     settings_tree_sha256=hashlib.sha256(raw).hexdigest(),
                     settings_backup_sha256=backup[0].decode() if backup else None,
                     settings_entries=len(sizes), clock_reseeded=False,
                     power_on_record_rewritten=False)
        require(value['frozen_partitions'] == 19, 'nineteen frozen internal volumes required')
        save_new(run / 'settings-restart-freeze.json', value)
        return value

    def finish_boot(self, run):
        """After confirmed QMP exit: unchanged frozen content, then a stopped receipt."""
        run = Path(run)
        require(self.frozen is not None, 'no frozen readback for this boot')
        stopped = self.snapshot()
        require(stopped == self.frozen, 'internal disk content changed between freeze and confirmed exit')
        value = dict(schema=STOPPED_SCHEMA, run=str(run), boot=self.boot, profile=PROFILE,
                     disk=stopped, frozen_sha256=self.frozen['sha256'],
                     restore_point_sha256=self.restore['sha256'],
                     same_instance=dict(path=self.instance.as_posix()))
        save_new(run / 'settings-restart-stopped.json', value)
        self.stopped = value
        return value

    def release(self):
        require(self.context is not None, 'no lease to release')
        if self.inherited is not None:
            duplicate, self.inherited = self.inherited, None
            os.close(duplicate['fd'])
        context, self.context = self.context, None
        self.leased = None
        context.__exit__(None, None, None)

    def reacquire(self):
        """Take the same instance back for the new boot and prove it is unchanged."""
        require(self.stopped is not None, 'second boot requires a stopped receipt')
        require(self.context is None and self.leased is None, 'release the first lease first')
        import persistent_storage
        self.context = persistent_storage.instance_lease(self.instance)
        self.leased = self.context.__enter__()
        current = self.snapshot()
        require(current == self.stopped['disk'],
                'reacquired internal disk differs from the stopped receipt before mount')
        self.boot = 2
        save_new(self.base / f'reacquire-{self.instance.name}.json', dict(
            schema='a7c2-settings-restart-reacquire-v1', profile=PROFILE,
            instance=str(self.instance), boot=2, disk=current,
            previous=dict(path=self.stopped['disk']['path'], device=self.stopped['disk']['device'],
                          inode=self.stopped['disk']['inode'], sha256=self.stopped['disk']['sha256'])))
        return current

    def require_new_boot(self, previous, current):
        """A restart is a new run and a new QEMU process, never the same round."""
        require(previous.get('run') and current.get('run') and previous['run'] != current['run'],
                'second boot repeats the first run directory')
        require(previous.get('qemu_identity') and current.get('qemu_identity') and
                previous['qemu_identity'] != current['qemu_identity'],
                'second boot is not a new QEMU process')
        require(current.get('settings_restart_boot') == 2, 'second boot is not marked as boot 2')


def plan():
    return dict(schema='a7c2-settings-restart-implementation-v1', profile=PROFILE,
                default_off=True, runtime_admitted=False, capture_verified=False,
                physical_compatible=False, ram_card_bytes=GIB,
                internal_disk_bytes=INTERNAL_BYTES, settings_on_ram_card=False,
                capture_media='/image_mmca from simulation/sd-card.fat',
                settings_mount='/dev/cnflasha2 -> /setting',
                explicit=EXPECTED, conflicts=list(CONFLICTS),
                budget='64GiB reserve + 2x internal disk + declared driver peak',
                order='create once -> exclusive lease -> baseline -> restore point -> '
                      'boot 1 -> original normal shutdown receipt -> freeze 1 19 -> '
                      'QMP exit -> unchanged readback -> stopped receipt -> release -> '
                      'reacquire same disk -> boot 2 without any seed')


def main():
    print(json.dumps(plan(), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
