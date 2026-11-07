#!/usr/bin/env python3
"""Rebuild only explicit VM adapters and the private full-dump initramfs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import runpy

HERE = Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime',type=Path,default=HERE/'runtime',help='Independent runtime root; sources remain maintained in this report')
parser.add_argument('--observer-source',type=Path,help='explicit private observer snapshot; leaves the official working source unchanged')
parser.add_argument('--observer-source-sha256',help='required expected SHA256 for the explicit observer snapshot')
parser.add_argument('--card-seed',type=Path,help='read-only 128 MiB FAT16 card image for a new virtual card')
parser.add_argument('--usb-touch-profile',choices=['virtual-config-v1','virtual-config-tcin-inactive-v1'],help='explicit finite USB touch / inactive TCIN helper; default off')
parser.add_argument('--usb-touch-ap',type=Path,help='read-only exact original appFw ELF')
parser.add_argument('--usb-touch-cp',type=Path,help='read-only exact original CP source asset')
args=parser.parse_args()
runpy.run_path(str(HERE/'usb-touch-scope.py'))['prepare'](args.usb_touch_profile,args.usb_touch_ap,args.usb_touch_cp)
if (args.observer_source is None)!=(args.observer_source_sha256 is None):
    parser.error('Explicit observer source and SHA256 must be specified together')
if args.observer_source_sha256 is not None and (len(args.observer_source_sha256)!=64 or any(c not in '0123456789abcdef' for c in args.observer_source_sha256)):
    parser.error('Observer source SHA256 must be 64 lowercase hex characters')
BASE = args.runtime.resolve()/'analysis'
root = BASE/'root'
lock = runpy.run_path(str(HERE/'runtime-lock.py'))['open_runtime_lock'](BASE.parent)
if BASE.parent != HERE/'runtime' and not os.path.lexists(BASE.parent/'sources'):
    # Match prepare-full-system: isolated runtimes share read-only host tools.
    (BASE.parent/'sources').symlink_to(HERE/'runtime/sources',target_is_directory=True)
if not (BASE.parent/'sources/qemu-tools/usr/lib/libfdt.so.1').is_file():
    raise RuntimeError('Missing host libfdt; prepare the runtime host tools before building')
manifest = json.loads((BASE/'full-system.json').read_text())
board_adapter = BASE/'qemu-kernel-probe.sh'
text = board_adapter.read_text()
if 'ulimit -c 0' not in text:
    text = text.replace('set -euo pipefail\n','set -euo pipefail\nulimit -c 0\n',1)
if '-smp 1' in text:
    if text.count('-smp 1') != 1:
        raise ValueError('Ambiguous SMP adapter patch')
    text = text.replace('-smp 1','-smp "${QEMU_FULL_SMP:-1}"')
old = 'source = ctypes.create_string_buffer(path.read_bytes())\nbuffer = ctypes.create_string_buffer(16384)'
if old in text:
    text = text.replace(old, 'source = ctypes.create_string_buffer(path.read_bytes())\n'
        'if fdt.fdt_pack(source) != 0:\n    raise RuntimeError("Cannot pack QEMU board input")\n'
        'buffer = ctypes.create_string_buffer(65536)')
needle = "ptr = fdt.fdt_getprop(buffer, chosen, b'linux,initrd-start', ctypes.byref(length))\nif not ptr or length.value not in (4, 8):"
if needle in text and 'Cannot describe explicit full-system initrd load' not in text:
    text = text.replace(needle,
        "ptr = fdt.fdt_getprop(buffer, chosen, b'linux,initrd-start', ctypes.byref(length))\n"
        "if not ptr and sys.argv[5] == '1':\n"
        "    value = struct.pack('>Q', 0x440000000)\n"
        "    if fdt.fdt_setprop(buffer, chosen, b'linux,initrd-start', value, len(value)) != 0:\n"
        "        raise RuntimeError('Cannot describe explicit full-system initrd load')\n"
        "    ptr = fdt.fdt_getprop(buffer, chosen, b'linux,initrd-start', ctypes.byref(length))\n"
        "if not ptr or length.value not in (4, 8):")
needle = '-machine virt,secure=off -cpu cortex-a35 -smp'
if needle in text and '-accel tcg,thread=' not in text:
    text = text.replace(needle,'-accel tcg,thread="${QEMU_TCG_THREAD:-single}" ' + needle)
text = text.replace('-cpu cortex-a35 -smp','-cpu cortex-a35,cntfrq="${QEMU_ARCH_CNTFRQ:-62500000}" -smp')
needle = 'if [[ "$high_ddr" == 1 ]]; then\n  memory_config=24576'
if needle in text and 'full_boot_entry=' not in text:
    text = text.replace(needle,
        'full_boot_entry=0x400080000\nhandoff_bind=()\n'
        'if [[ "${QEMU_FULL_BOOT_SHIM:-0}" == 1 ]]; then\n'
        '  full_boot_entry=0x400010000\n'
        '  handoff_bind=(--ro-bind "$analysis_dir/boot-handoff.bin" /boot-handoff.bin)\nfi\n'+needle)
    text = text.replace('-device loader,addr=0x400080000,cpu-num=0)',
                        '-device loader,addr="$full_boot_entry",cpu-num=0)')
    text = text.replace('fi\nmkdir -p "$output_dir"',
        'fi\nif [[ "${QEMU_FULL_BOOT_SHIM:-0}" == 1 ]]; then\n'
        '  loader_args+=(-device loader,file=/boot-handoff.bin,addr=0x400010000,force-raw=on)\n'
        'fi\nmkdir -p "$output_dir"',1)
    text = text.replace('--ro-bind "$test_initrd" /initrd.img \\\n',
                        '--ro-bind "$test_initrd" /initrd.img \\\n    "${handoff_bind[@]}" \\\n')
if 'QEMU_FULL_USB_INIT' not in text:
    needle='  # This kernel uses the fixed-address DTB, so update that DTB\'s bootargs too.'
    if text.count(needle)!=1:
        raise ValueError('Ambiguous original USB initialization adapter')
    text=text.replace(needle,
        '  if [[ "${QEMU_FULL_USB_INIT:-skipped}" == original ]]; then\n'
        '    cmdline="${cmdline/,__boottime_sony_usb_init/}"\n'
        '  fi\n'+needle,1)
text=runpy.run_path(str(HERE/'usb-platform.py'))['adapt_script'](text)
text=text.replace('"$analysis_dir/../../usb-platform.py"',
                  '"${QEMU_FULL_ADAPTER_DIR:-$analysis_dir/../..}/usb-platform.py"')
text=runpy.run_path(str(HERE/'system-sound-region.py'))['adapt_script'](text)
text=runpy.run_path(str(HERE/'boot-fatal-probe.py'))['adapt_script'](text)
text=runpy.run_path(str(HERE/'avcam-preload.py'))['adapt_script'](text)
if 'FULLSYSTEM_PIN_CONTROL_RESERVATION' not in text:
    anchor='# Reject overlapping static virtual mappings before booting the unmodified kernel.'
    if text.count(anchor)!=1:raise ValueError('Ambiguous pin control reservation insertion')
    code=('# FULLSYSTEM_PIN_CONTROL_RESERVATION: new finite owner, not original DMM capacity.\n'
          'if "fullsystem.pin-control-memory=1" in sys.argv[3].split():\n'
          '    runpy.run_path(str(Path(sys.argv[7]).with_name("pin-buffer-region.py")))["add_dtb_reservation"](fdt,buffer,sys.argv[3])\n')
    text=text.replace(anchor,code+anchor,1)
# FULLSYSTEM_SONY_IOMAP_SUPERSEDES_SHIMS: each "({} if board_io else {" shim dict
# must end with "}).items():"; a half-applied edit would leave the board-DTB patch
# script with an unbalanced parenthesis, so this runs every build and self-heals.
def _repair_sony_iomap_dicts(text):
    """Keep the two shim dicts balanced; both edits are exact and idempotent."""
    repairs = (("b'size': struct.pack('>Q', 0x20000),\n        b'memtype': struct.pack('>I', 1),\n    }.items():",
                "b'size': struct.pack('>Q', 0x20000),\n        b'memtype': struct.pack('>I', 1),\n    }).items():"),
               ("b'size': struct.pack('>Q', 0x2000), b'memtype': struct.pack('>I', 1),\n    }.items():",
                "b'size': struct.pack('>Q', 0x2000), b'memtype': struct.pack('>I', 1),\n    }).items():"),
               ("b'size': struct.pack('>Q', 0x4000), b'memtype': struct.pack('>I', 1),\n    }).items():",
                "b'size': struct.pack('>Q', 0x4000), b'memtype': struct.pack('>I', 1),\n    }.items():"))
    for broken, correct in repairs:
        if broken in text:
            text = text.replace(broken, correct, 1)
    return text


def _sony_iomap_patch_compiles(text):
    for part in text.split("<<'PY'\n")[1:]:
        body = part.split("\nPY\n", 1)[0]
        if 'fullsystem.iomap=sony' in body:
            compile(body, 'board-dtb-patch', 'exec')
            return True
    return False


if 'board_io = ' in text:
    text = _repair_sony_iomap_dicts(text)
    if not _sony_iomap_patch_compiles(text):
        raise ValueError('Board DTB patch script is not a valid program after Sony iomap edits')
    # Migration: a previous revision guarded the whole high-DDR block, which also
    # skipped the DDR memory-node relocation and made every RAM reservation fail.
    wrong = ("if sys.argv[5] == '1' and 'fullsystem.iomap=sony' not in sys.argv[3].split():\n"
             "    # Minimal GPIO register backing, not a behavioral camera-device model.")
    if wrong in text:
        text = text.replace(wrong, "if sys.argv[5] == '1':\n    # Minimal GPIO register backing, not a behavioral camera-device model.", 1)
    gic_props = "node = fdt.fdt_add_subnode(buffer, 0, b'sony-gic-alias')\nif node < 0:\n    raise RuntimeError('Cannot add GIC alias node')\nprops = {"
    if gic_props in text:
        text = text.replace(gic_props,
            "if 'fullsystem.iomap=sony' in sys.argv[3].split():\n"
            "    node = -1\nelse:\n"
            "    node = fdt.fdt_add_subnode(buffer, 0, b'sony-gic-alias')\n"
            "if node < 0 and 'fullsystem.iomap=sony' not in sys.argv[3].split():\n"
            "    raise RuntimeError('Cannot add GIC alias node')\n"
            "board_io = 'fullsystem.iomap=sony' in sys.argv[3].split()\n"
            "props = {} if board_io else {", 1)
if 'FULLSYSTEM_SONY_IOMAP_TIMER_GUARD' not in text:
    # The retail board DTB declares one iomap node covering the whole 0xF0000000
    # window, which already contains the local timer shim at 0xF1042000. Declaring
    # both would be rejected by the overlap check below, and the board window is the
    # correct description, so the shim node is only added when that window is absent.
    timer_node="if sys.argv[5] == '1':\n    node = fdt.fdt_add_subnode(buffer, 0, b'sony-timer-map')"
    if text.count(timer_node)!=1:
        raise ValueError('Ambiguous timer mapping insertion point')
    text=text.replace(timer_node,
        "# FULLSYSTEM_SONY_IOMAP_TIMER_GUARD: the declared board IO window already covers\n"
        "# the timer shim, so only declare a separate node when that window is absent.\n"
        "if sys.argv[5] == '1' and 'fullsystem.iomap=sony' not in sys.argv[3].split():\n"
        "    node = fdt.fdt_add_subnode(buffer, 0, b'sony-timer-map')",1)
if '# FULLSYSTEM_SONY_IOMAP: declare' not in text:
    pin_line='    runpy.run_path(str(Path(sys.argv[7]).with_name("pin-buffer-region.py")))["add_dtb_reservation"](fdt,buffer,sys.argv[3])\n'
    if text.count(pin_line)!=1:
        raise ValueError('Ambiguous Sony iomap insertion point')
    code=('# FULLSYSTEM_SONY_IOMAP: declare the retail board\'s fixed IO windows so the\n'
          '# original map_io() (arch/arm64/mm/mmu.c:925, CONFIG_ARCH_EJ) maps them.\n'
          '# Values come from the signed package\'s own board DTB, never a private dump.\n'
          'if "fullsystem.iomap=sony" in sys.argv[3].split():\n'
          '    runpy.run_path(str(Path(sys.argv[7]).with_name("sony-iomap.py")))["add_iomap_nodes"](fdt,buffer)\n')
    text=text.replace(pin_line,pin_line+code,1)
if 'QEMU_SONY_USB_DWC3' not in text:
    anchor='bootfs="$analysis_dir/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked"'
    if text.count(anchor)!=1:raise ValueError('Ambiguous DWC3 controller sandbox setup')
    text=text.replace(anchor,
        'if [[ "${QEMU_FULL_USB_CONTROLLER:-off}" == upstream-host ]]; then\n'
        '  timer_environment+=(--setenv QEMU_SONY_USB_DWC3 1)\nfi\n'+anchor,1)
if 'FULLSYSTEM_MEDIA_DETECT_ENV' not in text:
    anchor='bootfs="$analysis_dir/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked"'
    if text.count(anchor)!=1:
        raise ValueError('Ambiguous media detect sandbox insertion')
    text=text.replace(anchor,
        '# FULLSYSTEM_MEDIA_DETECT_ENV: bwrap clears ambient variables.\n'
        'if [[ -n "${QEMU_SONY_MEDIA_DETECT:-}" ]]; then\n'
        '  timer_environment+=(--setenv QEMU_SONY_MEDIA_DETECT "$QEMU_SONY_MEDIA_DETECT")\n'
        'fi\n'+anchor,1)
if 'FULLSYSTEM_MMC_TRACE_ENV' not in text:
    anchor2='bootfs="$analysis_dir/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked"'
    if text.count(anchor2)!=1:
        raise ValueError('Ambiguous MMC trace sandbox insertion')
    text=text.replace(anchor2,
        '# FULLSYSTEM_MMC_TRACE_ENV: bwrap clears ambient variables.\n'
        'if [[ -n "${QEMU_SONY_MMC_TRACE:-}" ]]; then\n'
        '  timer_environment+=(--setenv QEMU_SONY_MMC_TRACE "$QEMU_SONY_MMC_TRACE")\n'
        'fi\n'+anchor2,1)
board_adapter.write_text(text)
subprocess.run(['clang','--target=aarch64-none-elf','-fuse-ld=lld','-nostdlib',
                '-Wl,-Ttext=0x400010000','-Wl,--oformat=binary','-Wl,-e,_start',
                str(HERE/'boot-handoff.S'),'-o',str(BASE/'boot-handoff.bin')],check=True)
boards = BASE/'boards'
boards.mkdir(exist_ok=True)
tools = HERE/'runtime/sources/qemu-11.1.2/build-sony-ui'
if not (boards/'virt-four.dtb').is_file():
    subprocess.run(['bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv',
        '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib','/lib64',
        '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',str(tools),'/tools',
        '--bind',str(boards),'/out','--chdir','/out','--setenv','LC_ALL','C',
        '/tools/qemu-system-aarch64','-machine','virt,secure=off,dumpdtb=/out/virt-four.dtb',
        '-cpu','cortex-a35','-smp','4','-m','4096','-nodefaults','-display','none','-nic','none',
        '-monitor','none','-serial','none'],check=True)
for src, target in [('init','init'),('insmod','sbin/insmod'),('bootin-wrapper','simulation/bootin-wrapper'),
                    ('driver-audit.sh','simulation/driver-audit.sh'),('stack-census.sh','simulation/stack-census.sh'),
                    ('upm-notify-observe.sh','simulation/upm-notify-observe.sh'),
                    ('getty','sbin/getty'),('delayed-census.sh','simulation/delayed-census.sh')]:
    if (root/target).is_symlink():
        (root/target).unlink()  # Never overwrite BusyBox by following its applet link.
    shutil.copyfile(HERE/'guest'/src, root/target)
    (root/target).chmod(0o755)
shutil.copyfile(HERE/'guest/host-census.sh',root/'simulation/host-census.sh')
(root/'simulation/host-census.sh').chmod(0o755)
shutil.copyfile(HERE/'guest/uart-input-observe.sh',root/'simulation/uart-input-observe.sh')
(root/'simulation/uart-input-observe.sh').chmod(0o755)
shutil.copyfile(HERE/'guest/proc-census.sh',root/'simulation/proc-census.sh')
(root/'simulation/proc-census.sh').chmod(0o755)
lib = root/'lib'
native_input=runpy.run_path(str(HERE/'native-input.py'))['resolve']()
menu=native_input/'runtime/analysis'
manifest['native_dependency_snapshot']=native_input.name
build_observer=runpy.run_path(str(HERE/'build-imaging.py'))['build']
manifest['imaging_observer']=build_observer(menu,root,BASE/'observer-src',args.observer_source,args.observer_source_sha256,
    usb_touch_profile=args.usb_touch_profile,usb_touch_ap=args.usb_touch_ap,usb_touch_cp=args.usb_touch_cp)
backup_dependency=BASE/'original-link-deps/libbackup.so'
backup_expected='6a3c5f6067620c00d790cbe520844acdbb721fa5d0e7433b00a227f922ab9d0d'
backup_dependency.parent.mkdir(exist_ok=True)
if not backup_dependency.is_file():
    quoted=str(backup_dependency)
    if any(c in quoted for c in '\\"\r\n'):raise ValueError('Unsupported dependency extraction path')
    subprocess.run(['debugfs','-R',f'dump /lib/libbackup.so "{quoted}"',str(root/'partitions/a7c2-usr.img')],
                   check=True,capture_output=True)
if backup_dependency.is_symlink() or hashlib.sha256(backup_dependency.read_bytes()).hexdigest()!=backup_expected:
    raise ValueError('Original libbackup link dependency identity differs')
manifest['bluetooth_policy_libbackup_sha256']=backup_expected
gate_fields=runpy.run_path(str(HERE/'capture-gates.py'))['field_header']()
(BASE/'capture-gates-fields.h').write_text(gate_fields)
for name in ('attach-loop','init-clock','board-regs','init-gic','thread-snapshot','system-sound-owner','bounded-log','pin-control-probe','uart-input-observe','upm-notify-check','hdmi-backup-probe','inject-key','inject-event','gpio-pad-state','bluetooth-policy','backup-sync','mcmn-query','cp-rm-notify','card-export','capture-gates-reader'):
    sources=[HERE/file for file in ('pin-buffer-owner.c','pin-buffer-guest.c','pin-buffer-probe.c')] if name=='pin-control-probe' else [HERE/(name+'.c')]
    subprocess.run(['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-O2',
                *(['-mno-outline-atomics'] if name=='pin-control-probe' else []),
                '-Wl,--no-undefined','-Wl,-e,_start','-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
                '-I',str(BASE),*map(str,sources),'-Wl,--no-as-needed',
                *([str(menu/'menu-root/usr/lib/libosal_uipc.so'),
                   str(menu/'menu-root/usr/lib/libosal_utm.so')]
                  if name in ('init-clock','upm-notify-check','inject-key','inject-event','bluetooth-policy','backup-sync','mcmn-query','cp-rm-notify') else []),
                *([str(backup_dependency)] if name in ('bluetooth-policy','backup-sync') else []), '-Wl,--allow-shlib-undefined',
                str(lib/'libc-2.25.so'),str(lib/'libpthread-2.25.so'),str(lib/'libdl-2.25.so'),str(lib/'ld-2.25.so'),
                '-o',str(root/'simulation'/name)],check=True)
manifest['pin_control_probe_program_sha256']=hashlib.sha256((root/'simulation/pin-control-probe').read_bytes()).hexdigest()
manifest['uart_input_probe_program_sha256']=hashlib.sha256((root/'simulation/uart-input-observe').read_bytes()).hexdigest()
manifest['upm_notify_program_sha256']=hashlib.sha256((root/'simulation/upm-notify-check').read_bytes()).hexdigest()
manifest['hdmi_backup_probe_program_sha256']=hashlib.sha256((root/'simulation/hdmi-backup-probe').read_bytes()).hexdigest()
manifest['inject_key_program_sha256']=hashlib.sha256((root/'simulation/inject-key').read_bytes()).hexdigest()
manifest['inject_event_program_sha256']=hashlib.sha256((root/'simulation/inject-event').read_bytes()).hexdigest()
manifest['gpio_pad_program_sha256']=hashlib.sha256((root/'simulation/gpio-pad-state').read_bytes()).hexdigest()
manifest['gpio_pad_source_sha256']=hashlib.sha256((HERE/'gpio-pad-state.c').read_bytes()).hexdigest()
manifest['bluetooth_policy_program_sha256']=hashlib.sha256((root/'simulation/bluetooth-policy').read_bytes()).hexdigest()
manifest['bluetooth_policy_source_sha256']=hashlib.sha256((HERE/'bluetooth-policy.c').read_bytes()).hexdigest()
manifest['backup_sync_program_sha256']=hashlib.sha256((root/'simulation/backup-sync').read_bytes()).hexdigest()
manifest['backup_sync_source_sha256']=hashlib.sha256((HERE/'backup-sync.c').read_bytes()).hexdigest()
manifest['mcmn_query_program_sha256']=hashlib.sha256((root/'simulation/mcmn-query').read_bytes()).hexdigest()
manifest['mcmn_query_source_sha256']=hashlib.sha256((HERE/'mcmn-query.c').read_bytes()).hexdigest()
manifest['cp_rm_notify_program_sha256']=hashlib.sha256((root/'simulation/cp-rm-notify').read_bytes()).hexdigest()
manifest['cp_rm_notify_source_sha256']=hashlib.sha256((HERE/'cp-rm-notify.c').read_bytes()).hexdigest()
# Observation-only interposer for the media-detection state machine (no behaviour change).
subprocess.run(['clang','--target=aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-O2',
                '-mno-outline-atomics','-Wl,--no-undefined','-shared','-fPIC',
                str(HERE/'detect-observe.c'),
                str(lib/'libc-2.25.so'),str(lib/'libdl-2.25.so'),str(lib/'libpthread-2.25.so'),
                str(lib/'ld-2.25.so'),
                '-o',str(root/'simulation/detect-observe.so')],check=True)
manifest['detect_observe_source_sha256']=hashlib.sha256((HERE/'detect-observe.c').read_bytes()).hexdigest()
manifest['detect_observe_program_sha256']=hashlib.sha256((root/'simulation/detect-observe.so').read_bytes()).hexdigest()
manifest['card_export_program_sha256']=hashlib.sha256((root/'simulation/card-export').read_bytes()).hexdigest()
manifest['card_export_source_sha256']=hashlib.sha256((HERE/'card-export.c').read_bytes()).hexdigest()
manifest['capture_gates_reader_source_sha256']=hashlib.sha256((HERE/'capture-gates-reader.c').read_bytes()).hexdigest()
manifest['capture_gates_reader_program_sha256']=hashlib.sha256((root/'simulation/capture-gates-reader').read_bytes()).hexdigest()
manifest['capture_gates_fields_sha256']=hashlib.sha256(gate_fields.encode()).hexdigest()
# The firmware's OWN file media backend (libInfraMediaCommon's dummy driver) is
# selected by flipping EXISTMEDIADRIVER after the original mcmn_param_init runs;
# see FILE-MEDIA-BACKEND-PORT.md. Build the preload and a deterministic 128 MiB
# FAT16 template, and record both identities so a stale runtime fails closed.
subprocess.run(['clang','--target=aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-O2',
                '-mno-outline-atomics','-Wl,--no-undefined','-shared','-fPIC',
                str(HERE/'file-media-config.c'),
                str(lib/'libc-2.25.so'),str(lib/'libdl-2.25.so'),str(lib/'libpthread-2.25.so'),
                str(lib/'ld-2.25.so'),
                '-o',str(root/'simulation/file-media-config.so')],check=True)
manifest['file_media_config_source_sha256']=hashlib.sha256((HERE/'file-media-config.c').read_bytes()).hexdigest()
manifest['file_media_config_program_sha256']=hashlib.sha256((root/'simulation/file-media-config.so').read_bytes()).hexdigest()
# The file-backed RM/media provider (ported from the sibling deliverable) plus the
# preload that starts it with the ORIGINAL osal entry points.
subprocess.run(['clang','--target=aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-O2',
                '-mno-outline-atomics','-Wl,--no-undefined','-shared','-fPIC',
                str(HERE/'rm-file-device.c'),str(HERE/'rm-file-preload.c'),
                str(lib/'libc-2.25.so'),str(lib/'libdl-2.25.so'),str(lib/'libpthread-2.25.so'),
                str(lib/'ld-2.25.so'),
                '-o',str(root/'simulation/rm-file.so')],check=True)
for key,name in (('rm_file_device','rm-file-device.c'),('rm_file_preload','rm-file-preload.c'),
                 ('rm_file_header','rm-file-device.h')):
    manifest[key+'_source_sha256']=hashlib.sha256((HERE/name).read_bytes()).hexdigest()
manifest['rm_file_program_sha256']=hashlib.sha256((root/'simulation/rm-file.so').read_bytes()).hexdigest()
template_api=runpy.run_path(str(HERE/'file-media-template.py'))
card_template=BASE/'file-media-template-128m.fat'
if args.card_seed is not None:
    manifest['file_media_seed']=template_api['copy_seed'](args.card_seed,card_template)
else:
    template_api['create'](card_template)
    manifest['file_media_seed']={'generated':True}
shutil.copyfile(card_template,root/'simulation/media-template.fat')
manifest['file_media_template_sha256']=template_api['digest'](card_template)
manifest['file_media_template_source_sha256']=hashlib.sha256((HERE/'file-media-template.py').read_bytes()).hexdigest()
subprocess.run(['debugfs','-R',f'dump /kmod/upm.ko {BASE / "upm-observer-source.ko"}',
                str(root/'partitions/a7c2-usr.img')],check=True,capture_output=True)
manifest['upm_observer_module_sha256']=hashlib.sha256((BASE/'upm-observer-source.ko').read_bytes()).hexdigest()
if manifest['upm_observer_module_sha256']!='a8b16e1484be48d32c4a401897d13378cf45e5ef6654ebdcfdef5fc593da32eb':
    raise ValueError('UPM observation module identity differs from the verified original')
subprocess.run(['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu',
    '-fuse-ld=lld','-nostdlib','-O2','-fno-builtin','-fPIC','-shared','-Wl,--no-undefined',
    '-Wl,-soname,liro-observe.so',str(HERE/'liro-observe.c'),
    *[str(lib/name) for name in ('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')],
    '-o',str(root/'simulation/liro-observe.so')],check=True)
manifest['liro_observer']={'source_sha256':hashlib.sha256((HERE/'liro-observe.c').read_bytes()).hexdigest(),
    'program_sha256':hashlib.sha256((root/'simulation/liro-observe.so').read_bytes()).hexdigest()}
names = b'\0'.join(os.fsencode(str(p.relative_to(root))) for p in sorted(root.rglob('*')))+b'\0'
image = BASE/'full-system.cpio.new'
with image.open('wb') as target:
    subprocess.run(['cpio','--null','-o','-H','newc','--quiet'],cwd=root,input=names,stdout=target,check=True)
with image.open('rb') as stream:
    manifest['initrd_sha256'] = hashlib.file_digest(stream,'sha256').hexdigest()
manifest['adapter_sources'] = {p.relative_to(HERE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
    for p in [HERE/'attach-loop.c',HERE/'init-clock.c',HERE/'board-regs.c',HERE/'init-gic.c',
              HERE/'boot-handoff.S',HERE/'build-imaging.py',HERE/'usb-touch-scope.py',HERE/'imaging-device.c',HERE/'imaging-device.h',
              HERE/'usb-core-probe.py',HERE/'run-full-system.py',
              HERE/'usb-platform.py',
              HERE/'boot-fatal-probe.py',
              HERE/'upm-message-probe.py',HERE/'upm-notify-check.c',HERE/'hdmi-backup-probe.c',
              HERE/'thread-snapshot.c',
              HERE/'uart-input-observe.c',
              HERE/'bounded-log.c',
              HERE/'avcam-preload.py',
              HERE/'sony-iomap.py',HERE/'reserved-region.py',HERE/'card-export-region.py',HERE/'sd_flush_barrier.py',HERE/'pin-buffer-region.py',HERE/'pin-buffer-owner.c',
              HERE/'pin-buffer-owner.h',HERE/'pin-buffer-guest.c',HERE/'pin-buffer-probe.c',
              HERE/'system-sound-owner.c',HERE/'system-sound-owner.h',HERE/'system-sound-region.py',
              *(HERE/'guest').iterdir()] if p.is_file()}
manifest['boot_handoff_sha256'] = hashlib.sha256((BASE/'boot-handoff.bin').read_bytes()).hexdigest()
manifest['board_adapter_sha256'] = hashlib.sha256(board_adapter.read_bytes()).hexdigest()
manifest['four_cpu_template_sha256'] = hashlib.sha256((boards/'virt-four.dtb').read_bytes()).hexdigest()
image.replace(BASE/'full-system.cpio')
(BASE/'full-system.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('FULLSYSTEM_ADAPTERS_BUILT',manifest['initrd_sha256'])
