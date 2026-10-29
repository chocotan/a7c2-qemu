"""Bind only the leased host directory into the virtual-FAT USB profile."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat

from directory_sd import TOTAL_SECTORS
from usb_network import prepare_profile as usb_profile


def prepare_profile(native, lease, output_parent=None):
    fd = lease['fd']
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or
            (info.st_dev, info.st_ino) != (lease['device'], lease['inode'])):
        raise ValueError('Directory SD requires the pinned owned directory lease')
    env = usb_profile(native, output_parent)
    source = Path(env['MENU_KERNEL_SCRIPT'])
    script = source.read_text()
    bind = '    --bind "$output_dir" /out \\\n'
    storage = '      -device usb-net,id=sony-usb-network,netdev=sony_net \\\n'
    if script.count(bind) != 1 or script.count(storage) != 1:
        raise ValueError('USB directory launcher anchor changed')
    script = script.replace(bind, bind + f'    --dir /sd --bind-fd {fd} /sd \\\n', 1)
    script = script.replace(storage, storage +
        '      -blockdev driver=vvfat,node-name=sony_directory_sd,dir=/sd,rw=on,fat-type=32,'
        f'total-sectors={TOTAL_SECTORS} \\\n'
        '      -device usb-storage,id=sony-directory-sd,drive=sony_directory_sd,'
        'removable=on,serial=PI_DIRECTORY_SD256 \\\n', 1)
    scratch = source.parent/'vvfat-writeback'
    scratch.mkdir(mode=0o700, exist_ok=True)
    script = script.replace('    --dir /sd --bind-fd ' + str(fd) + ' /sd \\\n',
        '    --dir /sd --bind-fd ' + str(fd) + ' /sd \\\n'
        '    --dir /var/tmp --bind ' + shlex.quote(str(scratch)) + ' /var/tmp \\\n', 1)
    destination = source.with_name('kernel-directory-sd.sh')
    destination.write_text(script)
    proof = dict(scope='pinned host directory mapped as FAT32 USB storage, no physical passthrough',
                 total_sectors=TOTAL_SECTORS, bytes=TOTAL_SECTORS * 512,
                 source_profile=str(source.parent/'profile.json'),
                 derived_script_sha256=hashlib.sha256(script.encode()).hexdigest(),
                 host_directory_bind_only=True, external_edit_during_lease_allowed=False,
                 firmware_format_verified=False, original_io_verified=False)
    (source.parent/'directory-sd-profile.json').write_text(json.dumps(proof, indent=2)+'\n')
    env['MENU_KERNEL_SCRIPT'] = str(destination)
    env['A7C2_DIRECTORY_SD_PROFILE'] = 'directory-vvfat-256gb-v1'
    return env
