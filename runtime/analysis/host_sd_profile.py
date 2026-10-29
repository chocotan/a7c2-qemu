"""Derive local-file USB storage from the already-supported virtual xHCI profile."""
import hashlib
import json
import os
from pathlib import Path
import stat

from host_sd import TOTAL
from usb_network import prepare_profile as usb_profile


def prepare_profile(native, lease, output_parent=None):
    fd=lease['fd'];st=os.fstat(fd)
    if (not stat.S_ISREG(st.st_mode) or st.st_uid!=os.geteuid() or st.st_nlink!=1 or
            st.st_size!=TOTAL or (st.st_dev,st.st_ino)!=(lease['device'],lease['inode'])):
        raise ValueError('Host SD profile requires the pinned owned256GB file lease')
    # The caller retains card_lease and passes this fd through its subprocess chain.
    env=usb_profile(native,output_parent)
    source=Path(env['MENU_KERNEL_SCRIPT'])
    script=source.read_text()
    bind='    --bind "$output_dir" /out \\\n'
    storage='      -device usb-net,id=sony-usb-network,netdev=sony_net \\\n'
    if script.count(bind)!=1 or script.count(storage)!=1:
        raise ValueError('USB storage launcher anchor changed')
    script=script.replace(bind,bind+f'    --dir /sd --bind-fd {fd} /sd/card.img \\\n',1)
    script=script.replace(storage,storage+
        '      -drive file=/sd/card.img,if=none,id=sony_sd,format=raw,cache=writeback \\\n'
        '      -device usb-storage,id=sony-local-sd,drive=sony_sd,removable=on,serial=PI_LOCAL_SD256 \\\n',1)
    destination=source.with_name('kernel-host-sd.sh')
    destination.write_text(script)
    proof=dict(scope='owned host regular-file backed virtual USB storage; no physical passthrough',
               bytes=TOTAL,source_profile=str(source.parent/'profile.json'),
               derived_script_sha256=hashlib.sha256(script.encode()).hexdigest(),
               fd_lifetime='caller must retain file lease and pass fd until owned VM exits',
               guest_probe_verified=False,firmware_format_verified=False)
    (source.parent/'host-sd-profile.json').write_text(json.dumps(proof,indent=2)+'\n')
    env['MENU_KERNEL_SCRIPT']=str(destination)
    return env
