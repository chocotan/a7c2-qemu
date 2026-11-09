"""Run the original-init route through the product's existing owned GUI protocol."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import socket
import stat
import struct
import tempfile
import time

from original_cold_boot import ANALYSIS, need, sha
import persistent_storage as storage


def validate_control(environment):
    need(environment.get('A7C2_BOOT_PROFILE')=='original-init-cold','Cold GUI route requires its explicit boot profile')
    need(environment.get('A7C2_USE_PERSISTENT_STORAGE')=='1','Original init requires the persistent internal disk')
    for name in ('A7C2_HOST_SD','A7C2_DIRECTORY_SD','A7C2_FUNCTIONAL_CAMERA','A7C2_USB_NET'):
        need(not environment.get(name),'This cold GUI route does not support '+name)
    descriptor=int(environment['MENU_CONTROL_FD']);owner=int(environment['MENU_CONTROL_OWNER_PID'])
    need(descriptor>2 and owner>1,'Invalid cold GUI control identity')
    with socket.socket(fileno=os.dup(descriptor)) as control:
        pid,uid,_=struct.unpack('3i',control.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        need(pid==owner and uid==os.geteuid(),'Cold GUI control is not the declared controller socket')
    lock=int(environment['MENU_PROBE_LOCK_FD'])
    opened=os.fstat(lock);named=(ANALYSIS/'.menu-probe.lock').lstat()
    need(stat.S_ISREG(opened.st_mode) and opened.st_uid==os.geteuid() and (opened.st_dev,opened.st_ino)==(named.st_dev,named.st_ino),'Cold GUI build lock descriptor differs')
    return descriptor


def saved_for_close(run):
    """A previous successful export cannot hide a later rejected shutdown."""
    try:
        row=json.loads((Path(run)/'cold-live-session.json').read_text())
        internal=json.loads((Path(run)/'persistent-shutdown.json').read_text())
        exported=json.loads((Path(run)/'SD/export.json').read_text())
        raw=(Path(run)/'persistent-shutdown.raw').read_bytes()
        return (row.get('save_verified') is True and internal.get('frozen_verified') is True
                and internal.get('frozen_partitions')==19 and internal.get('original_freeze_bdev_used') is True
                and internal.get('raw_sha256')==hashlib.sha256(raw).hexdigest()
                and exported.get('ok') is True and exported.get('flush_lifecycle',{}).get('ok') is True
                and row.get('sd_export_sha256')==sha(Path(run)/'SD/export.json'))
    except (OSError,ValueError,KeyError,TypeError):return False


def live_session(process,run,qmp,built,*,leased=None,ram_enabled=False,build_result=None,restored=None):
    from menu_live import serial_command,run_live,display_snapshot_message
    from sd_transport import export_card,directory,report
    from sd_export_lifecycle import export_with_flush_lifecycle
    from sd_flush_barrier import cancel_resume
    from sd_hotplug import SDHotplug
    from settings_checkpoint import snapshot
    run=Path(run);sequence=0;last_export=None;pending=None
    receipt=run/'cold-live-session.json'
    state=dict(profile='original-init-cold',save_verified=False,capture_verified=False,full_boot_verified=False)
    def save():storage._save(receipt,state)
    save()
    def serial(command,*,timeout=30,cleanup=False):
        return serial_command(process,run/'console.log',command,timeout=timeout,allow_faulted_cleanup=cleanup)
    def display():
        nonlocal sequence
        sequence+=1
        from sony_usb_device import selected,guest_diagnostic
        if selected(os.environ):
            (run/('usb-diagnostic-'+str(sequence)+'.raw')).write_bytes(serial(guest_diagnostic(),timeout=30))
        qmp('screendump',dict(filename='/out/ui-display.ppm'))
        return display_snapshot_message(run/'ui-display.ppm',sequence)
    def download(request):
        need(request.get('execute')=='pmemsave','Unexpected cold SD QMP command')
        args=dict(request['arguments']);prefix='/proc/'+str(os.getpid())+'/fd/'
        need(args['filename'].startswith(prefix) and args['filename'][len(prefix):].isdigit(),'SD export requires an owned output descriptor')
        fd=int(args['filename'][len(prefix):]);opened=os.fstat(fd)
        path=Path(os.readlink(args['filename']));relative=path.relative_to(run)
        named=path.lstat()
        need(stat.S_ISREG(named.st_mode) and (opened.st_dev,opened.st_ino)==(named.st_dev,named.st_ino),'Cold SD output identity changed')
        args['filename']='/out/'+relative.as_posix()
        return qmp('pmemsave',args)
    def export():
        nonlocal last_export,pending
        state['save_verified']=False;save()
        from sony_usb_device import require_disconnected
        require_disconnected(run)
        if os.environ.get('A7C2_USB_SENSER')=='original-init2-v1':
            raw=serial('/simulation/usb-senser-mode restore',timeout=30)
            (run/'usb-senser-mode-restored.raw').write_bytes(raw)
            need(b'PRODUCT_USB_SENSER_ORIGINAL_MODE_RESTORED' in raw,'Original Senser startup setting was not restored')
        # Keep the same helper/RAM/guest-SHA checks and original Fsys flush owner recovery.
        settings=snapshot(serial,qmp,run,persistent=True) if os.environ.get('A7C2_SETTINGS_PERSIST')=='1' else None
        if pending is not None:cancel_resume(serial,pending);pending=None
        pending=time.monotonic_ns()
        def publish(row):
            nonlocal last_export,pending
            if row.get('card_published'):last_export=row['sha256']
            if row.get('flush_lifecycle',{}).get('ok'):pending=None
            with directory(run/'SD') as parent:report(parent,row)
        row=export_with_flush_lifecycle(lambda quiesce:export_card(run,built['sd_card']['bytes'],serial_command=lambda command:serial(command,timeout=90,cleanup=True),qmp=download,expected_old_sha256=last_export,quiesce=quiesce,sparse=True),serial,pending,publish)
        if settings is not None:row['settings']=settings
        save()
        return row
    def shutdown(serial,output):
        result=storage.prepare_shutdown(serial,output)
        state.update(save_verified=True,sd_export_sha256=sha(run/'SD/export.json'))
        save()
        return result
    build_result=Path(build_result) if build_result is not None else run/'build/result.json'
    def capture_ram():
        from original_ram_restore import capture,receipt_path
        need(ram_enabled and leased is not None,'No owned RAM capture lease')
        need(saved_for_close(run),'RAM capture requires the current verified SD save and nineteen frozen volumes')
        state['save_verified']=False;save()
        stream=run/'ram.qevm'
        free=os.statvfs(run)
        need(free.f_bavail*free.f_frsize>=5*1024**3+64*1024**3,'RAM capture needs a 5GiB stream budget plus 64GiB free reserve')
        binary=Path(os.environ['QEMU_SYSTEM_DIR'])/os.environ['QEMU_SYSTEM_BINARY']
        captured=capture(qmp,stream,run,leased,serial,built,sha(binary))
        captured.update(build_result=str(build_result),build_result_sha256=sha(build_result))
        storage._save(receipt_path(stream),captured)
        value={name:captured[name] for name in ('stream','stream_bytes','stream_sha256','source_identity')}
        value.update(completed=True,receipt_sha256=sha(receipt_path(stream)),sony_wbi_resume_executed=False)
        state.update(ram_capture=value,save_verified=True);save()
        return value
    storage._save(run/'runtime-manifest.json',dict(boot_profile='original-init-cold',original_cold_profile='original-init-v1',natural_boot=True,persistent_storage=True,internal_storage_profile=storage.PROFILE,rm_file_image_bytes=built['sd_card']['bytes'],sd_card=built['sd_card'],ram0_sha256=built['ram0_sha256'],kernel_sha256=built['kernel_sha256'],cold_build_result_sha256=sha(build_result),files=built['helper_sources'],original_libraries_unchanged=not built['overwrite']['entries'],ram_session=ram_enabled,ram_restore_verified=bool(restored and restored.get('same_boot_id') and restored.get('new_original_menu_and_shooting_pixels_verified')),capture_verified=False,full_boot_verified=False))
    try:
        run_live(process,run,int(os.environ['MENU_CONTROL_FD']),display_capture=display,sd_export=export,sd_card=SDHotplug(serial,run),storage_shutdown=shutdown,ram_capture=capture_ram if ram_enabled else None)
    except RuntimeError as error:
        if str(error)!='VM 控制通道已关闭':raise
    need(saved_for_close(run),'Cold GUI controller ended without a current SD save, recovered flush owner and nineteen frozen internal volumes; retain owner')
    return dict(state,internal_storage=json.loads((run/'persistent-shutdown.json').read_text()))


def main():
    validate_control(os.environ)
    instance=(Path(os.environ['A7C2_COLD_STORAGE_INSTANCE']).absolute() if os.environ.get('A7C2_COLD_STORAGE_INSTANCE') else storage.ensure_instance())
    runs=ANALYSIS/'menu-runs';runs.mkdir(exist_ok=True)
    output=Path(tempfile.mkdtemp(prefix='run-',dir=runs))
    runner=runpy.run_path(str(ANALYSIS.parents[1]/'tools/run-original-cold.py'))
    mode=os.environ.get('A7C2_RAM_WINDOW','')
    need(mode in ('','1'),'Unknown window RAM mode')
    restored=os.environ.get('A7C2_RAM_RESTORE_STREAM')
    built=None
    if restored:
        from original_ram_restore import live_build
        need(mode=='1','RAM restore requires the explicit window mode')
        built=live_build(restored)
    # A populated 1GiB card is fully hashed in guest before original AP admission.
    result=runner['run'](instance,output,300,live=True,ram_session=mode=='1',ram_restore=restored,built=built)
    return 0 if result['verified'] else 1


if __name__=='__main__':raise SystemExit(main())
