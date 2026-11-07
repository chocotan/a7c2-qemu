#!/usr/bin/env python3
"""Host regression tests, or explicit --actual two-VM filesystem persistence proof."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'persistent-boot.py'))


def test_bounded_slice(tmp_path):
    import pytest
    p=tmp_path/'file';p.write_bytes(b'prefix'+b'hello'+b'tail')
    with p.open('rb') as f:
        view=API['Slice'](f.fileno(),6,5)
        assert view.read(3)==b'hel';assert view.read(99)==b'lo';assert view.read()==b''
        view.seek(-2,2);assert view.read()==b'lo'
        with pytest.raises(ValueError):view.seek(6)
        with pytest.raises(ValueError):view.seek(-1)
        with pytest.raises(ValueError):view.seek(0,3)


def manifest():
    return dict(schema=1,profile=API['PROFILE'],build_verified=True,ram0_image='/tmp/small.ext2',
        cold_cmdline='root=/dev/ram0 rootfstype=ext2 rw noatime init=/sbin/persistent-bootstrap ramdisk_size=32768 persistent.profile='+API['PROFILE'])


def template():
    # Prepared full-system adapters differ from the raw pinned native template.
    data=(HERE/'runtime/analysis/qemu-kernel-probe.sh').read_bytes()
    assert hashlib.sha256(data).hexdigest()=='0380975245b8efc42e73bfe037575670af32e2dc98c6d2761d9b134323484b11'
    return data.decode()


def test_production_launch_contract(tmp_path):
    text=API['launch_script'](template(),manifest())
    script=tmp_path/'launch.sh';script.write_text(text)
    subprocess.run(['bash','-n',str(script)],check=True)
    assert '--bind "$PERSISTENT_INSTANCE" /instance' in text
    assert '--setenv QEMU_A7PF_FD "$PERSISTENT_DISK_FD"' in text
    assert '--setenv QEMU_A7PF_PROFILE persistent-flash-cold-v1' in text
    assert 'coldchain.profile=ram0-loop-v1' not in text
    assert "cmdline+=' rdinit=/init'" not in text
    assert '-kernel /kernel.img -initrd /initrd.img' not in text
    assert 'persistent-flash@b000000' in text
    assert 'persistent.profile=*|persistent.proof=*' in text
    assert '/qemu-input/partitions' not in API['BOOTSTRAP']
    assert 'exec /bin/busybox sh -x /sbin/init' in API['BOOTSTRAP']


def test_launch_refuses_wrong_profile_and_missing_anchors():
    import pytest
    wrong=manifest();wrong['profile']='ram0-loop-v1'
    with pytest.raises(ValueError):API['launch_script'](template(),wrong)
    with pytest.raises(ValueError):API['launch_script'](template().replace('bwrap --unshare-all','changed --unshare-all'),manifest())
    with pytest.raises(ValueError):API['launch_script'](template()+'\n-S\n',manifest())


def test_guest_scripts_syntax(tmp_path):
    for name in ('BOOTSTRAP','INSMOD','PROOF'):
        text=API[name];text.encode('ascii');p=tmp_path/name;p.write_text(text)
        subprocess.run(['sh','-n',str(p)],check=True)
    assert 'mount --bind /usr/bin/bootin.elf /dev/qemu-simulation/bootin-original' in API['INSMOD']
    assert 'PERSISTENT_PROOF_REMOVED readback_absent=1' in API['PROOF']


@pytest.fixture
def prepared_launch(tmp_path,monkeypatch):
    """Real small disk and real disk lease; only board preparation is simulated."""
    instance=tmp_path/'instance';instance.mkdir()
    disk=instance/'camera.emmc'
    disk.write_bytes(b'82462.00'+b'\0'*504+b'3'*512+b'7'*512+b'F'*512)
    geometry=dict(schema=API['DISK']['SCHEMA'],backing_bytes=2048,slices=[
        dict(id=name,offset=(i+1)*512,bytes=512) for i,name in enumerate(API['FIRMWARE_SLICES'])])
    (instance/'geometry.json').write_text(json.dumps(geometry))
    state=dict(schema=API['DISK']['SCHEMA'],generation=7,source_manifest_sha256='a'*64,
        geometry_sha256=API['COLD']['digest'](instance/'geometry.json'),source_class='official-bodydata-derived')
    (instance/'instance.json').write_text(json.dumps(state));(instance/'.disk.lock').touch()
    def write_wire(camera,path):
        Path(path).write_bytes(json.dumps(camera,sort_keys=True).encode())
    monkeypatch.setitem(API['GEOMETRY'],'write_camera_wire',write_wire)
    wire=instance/'persistent-geometry.bin';write_wire(geometry,wire)
    runtime=tmp_path/'prepared/analysis';runtime.mkdir(parents=True)
    (runtime.parent/'sources').mkdir()
    for name in ('boot-handoff.bin','boards/virt-four.dtb',API['KERNEL_ASSET'],
                 'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt'):
        path=runtime/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'helper-runtime-asset')
    (runtime/'qemu-kernel-probe.sh').write_text(template())
    work=tmp_path/'built';work.mkdir()
    kernel=work/'current-kernel.bin';kernel.write_bytes(b'current-disk-kernel')
    kernel_sha=API['COLD']['digest'](kernel)
    monkeypatch.setitem(API['COLD'],'KERNEL_SHA',kernel_sha)
    ram0=work/'ram0.ext2';ram0.write_bytes(b'small-original-ram0')
    built=dict(manifest(),instance=str(instance),source='official-bodydata-derived',helper_source_class='private-device-dump',
        firmware_binding_schema=1,instance_generation=7,instance_source_manifest_sha256='a'*64,
        instance_geometry=geometry,instance_wire_sha256=API['COLD']['digest'](wire),inputs=[],
        actual_kernel=dict(source_slice='nflasha3',fat_path='vmlinux.bin',path=str(kernel),bytes=kernel.stat().st_size,sha256=kernel_sha),
        ram0_image=str(ram0),ram0_sha256=API['COLD']['digest'](ram0))
    with API['DISK']['lease'](instance) as leased:built['partition_bindings']=API['partition_bindings'](leased)
    qemu_build=tmp_path/'production/build';qemu_build.mkdir(parents=True)
    binary=qemu_build/'qemu-system-aarch64';binary.write_bytes(b'bound-production-qemu')
    (qemu_build.parent/'qemu-result.json').write_text(json.dumps(dict(status='compiled',board_profile=API['PROFILE'],
        test_fixture_only=False,qemu_binary_sha256=API['COLD']['digest'](binary))))
    original_run=subprocess.run
    def prepare_only(command,**kwargs):
        if kwargs.get('env',{}).get('QEMU_PREPARE_ONLY')=='1':
            run=Path(kwargs['env']['QEMU_OUTPUT_DIR']);run.mkdir()
            (run/'cold-cmdline.txt').write_text(built['cold_cmdline']+'\n')
            (run/'virt.dtb').write_bytes(b'prepared-dtb')
            return subprocess.CompletedProcess(command,0)
        return original_run(command,**kwargs)
    monkeypatch.setattr(subprocess,'run',prepare_only)
    launch=API['prepare_launch'](runtime,built,tmp_path/'launch',qemu_build=qemu_build)
    return SimpleNamespace(instance=instance,disk=disk,geometry=geometry,state=state,runtime=runtime,
        built=built,launch=launch,qemu_build=qemu_build)


def test_prepare_uses_current_disk_kernel(prepared_launch):
    fixture=prepared_launch;launch=fixture.launch
    target=Path(launch['runtime_analysis'])/API['KERNEL_ASSET']
    assert target.read_bytes()==b'current-disk-kernel'
    assert target.read_bytes()!=(fixture.runtime/API['KERNEL_ASSET']).read_bytes()
    assert target.stat().st_ino!=Path(fixture.built['actual_kernel']['path']).stat().st_ino
    assert launch['source']=='official-bodydata-derived'
    for name in API['IDENTITY_FIELDS']:assert launch[name]==fixture.built[name]


def test_lease_outlives_registered_owner(prepared_launch):
    fixture=prepared_launch;state={'waited':False}
    class Child:
        def poll(self):return None
        def wait(self):
            with pytest.raises(BlockingIOError):
                with API['DISK']['lease'](fixture.instance):pass
            state['waited']=True
    with pytest.raises(RuntimeError,match='executor failed'):
        with API['leased_launch'](fixture.launch) as bound:
            assert bound['pass_fds']==(bound['fd'],)
            assert bound['qmp_parent']==fixture.launch['qmp_parent']
            assert bound['env']['PERSISTENT_DISK_FD']==str(bound['fd'])
            assert int(bound['env']['PERSISTENT_DISK_INO'])==fixture.disk.stat().st_ino
            subprocess.run([sys.executable,'-c',
                'import os; assert os.pread('+str(bound['fd'])+',8,0)==b"82462.00"'],pass_fds=bound['pass_fds'],check=True)
            bound['children'].append(Child())
            raise RuntimeError('executor failed')
    assert state['waited']
    with API['DISK']['lease'](fixture.instance):pass


@pytest.mark.parametrize('name',API['FIRMWARE_SLICES'])
def test_lease_rejects_partition_mutated_after_prepare(prepared_launch,name,monkeypatch):
    fixture=prepared_launch;row=next(r for r in fixture.launch['partition_bindings'] if r['id']==name)
    # A distinct legitimate root task obtains/releases the same lock after prepare.
    with API['DISK']['lease'](fixture.instance) as leased:
        old=os.pread(leased['fd'],1,row['offset'])
        os.pwrite(leased['fd'],bytes([old[0]^1]),row['offset']);os.fdatasync(leased['fd'])
    started=[]
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:started.append(a))
    with pytest.raises(API['IdentityMismatch']) as error:
        with API['leased_launch'](fixture.launch):subprocess.Popen(['must-not-start'])
    assert started==[]
    assert error.value.identity['label']==name+' SHA256'
    assert error.value.identity['expected']==row['sha256']
    assert error.value.identity['actual']!=row['sha256']
    retained=list(Path(fixture.launch['identity_failure_dir']).glob('prelaunch-failure-*.json'))
    assert len(retained)==1
    evidence=json.loads(retained[0].read_text())
    assert evidence['expected']==row['sha256'] and evidence['guest_started'] is False


@pytest.mark.parametrize('drift',('generation','source-manifest','wire','canonical-wire','qemu','script','kernel','dtb','range','geometry'))
def test_lease_rejects_other_prelaunch_identity_drift(prepared_launch,drift,monkeypatch):
    fixture=prepared_launch;launch=fixture.launch
    if drift in ('generation','source-manifest'):
        state=dict(fixture.state)
        state['generation' if drift=='generation' else 'source_manifest_sha256']=8 if drift=='generation' else 'b'*64
        (fixture.instance/'instance.json').write_text(json.dumps(state))
    elif drift=='wire':(fixture.instance/'persistent-geometry.bin').write_bytes(b'changed-wire')
    elif drift=='canonical-wire':
        monkeypatch.setitem(API['GEOMETRY'],'write_camera_wire',lambda camera,path:Path(path).write_bytes(b'noncanonical'))
    elif drift in ('qemu','script','kernel','dtb'):
        path=launch['actual_kernel']['path'] if drift=='kernel' else launch[{'qemu':'qemu_binary','script':'script','dtb':'dtb'}[drift]]
        Path(path).write_bytes(b'changed')
    elif drift=='range':launch['partition_bindings'][0]['offset']+=1
    else:
        # A new self-consistent geometry must not inherit an old launch receipt.
        geometry=json.loads((fixture.instance/'geometry.json').read_text());geometry['slices'][0]['offset']+=1
        (fixture.instance/'geometry.json').write_text(json.dumps(geometry))
        state=dict(fixture.state,geometry_sha256=API['COLD']['digest'](fixture.instance/'geometry.json'))
        (fixture.instance/'instance.json').write_text(json.dumps(state))
    started=[];monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:started.append(a))
    with pytest.raises(ValueError):
        with API['leased_launch'](launch):subprocess.Popen(['must-not-start'])
    assert started==[]
    assert len(list(Path(launch['identity_failure_dir']).glob('prelaunch-failure-*.json')))==1


def test_legacy_manifest_explicitly_rejected(prepared_launch,tmp_path):
    fixture=prepared_launch
    legacy=dict(fixture.built);legacy.pop('partition_bindings')
    with pytest.raises(ValueError,match='Legacy persistent manifest unsupported'):
        API['prepare_launch'](fixture.runtime,legacy,tmp_path/'legacy',qemu_build=fixture.qemu_build)
    legacy_launch=dict(fixture.launch);legacy_launch.pop('instance_generation')
    with pytest.raises(ValueError,match='Legacy persistent manifest unsupported'):
        with API['leased_launch'](legacy_launch):pytest.fail('legacy yielded')


def test_prepare_rejects_kernel_readback_drift(prepared_launch,tmp_path):
    fixture=prepared_launch;kernel=Path(fixture.built['actual_kernel']['path'])
    kernel.write_bytes(b'x'*kernel.stat().st_size)
    with pytest.raises(API['IdentityMismatch'],match='current disk kernel SHA256'):
        API['prepare_launch'](fixture.runtime,fixture.built,tmp_path/'kernel-drift',qemu_build=fixture.qemu_build)


def test_prepare_rejects_production_change_during_prepare(prepared_launch,tmp_path,monkeypatch):
    fixture=prepared_launch;original_run=subprocess.run
    def mutate_after_prepare(command,**kwargs):
        result=original_run(command,**kwargs)
        if kwargs.get('env',{}).get('QEMU_PREPARE_ONLY')=='1':
            Path(fixture.launch['qemu_binary']).write_bytes(b'changed-during-prepare')
        return result
    monkeypatch.setattr(subprocess,'run',mutate_after_prepare)
    with pytest.raises(ValueError,match='Source changed'):
        API['prepare_launch'](fixture.runtime,fixture.built,tmp_path/'qemu-during-prepare',qemu_build=fixture.qemu_build)
    assert not (tmp_path/'qemu-during-prepare/launch.json').exists()
    assert (tmp_path/'qemu-during-prepare/failure.json').is_file()


def test_camera_profile_keyword_preserves_strict_boundary(prepared_launch,tmp_path):
    fixture=prepared_launch
    assert fixture.launch['camera_profile']=='strict'
    with pytest.raises(ValueError,match='Unknown persistent camera profile'):
        API['prepare_launch'](fixture.runtime,fixture.built,tmp_path/'unknown-profile',
            qemu_build=fixture.qemu_build,camera_profile='unknown-camera-profile')
    assert not (tmp_path/'unknown-profile').exists()


@pytest.mark.parametrize('case',('valid','wrong-kernel','missing-kernel','duplicate-kernel','wrong-prepared','short-kernel'))
def test_current_p3_kernel_extraction(tmp_path,monkeypatch,case):
    ram=b'original-ram0';kernel=b'original-kernel'
    monkeypatch.setitem(API['COLD'],'ORIGINAL_RAMROOT_BYTES',len(ram))
    monkeypatch.setitem(API['COLD'],'ORIGINAL_RAMROOT_SHA',hashlib.sha256(ram).hexdigest())
    monkeypatch.setitem(API['COLD'],'KERNEL_SHA',hashlib.sha256(kernel).hexdigest())
    prepared=dict(bytes=len(kernel),sha256=hashlib.sha256(kernel).hexdigest())
    if case=='wrong-prepared':prepared['sha256']='f'*64
    values=[('initrd.img',ram),('vmlinux.bin',b'x'*len(kernel) if case=='wrong-kernel' else kernel)]
    if case=='missing-kernel':values.pop()
    if case=='duplicate-kernel':values.append(values[-1])
    entries=[SimpleNamespace(path='/'+name,size=len(data),mode=stat.S_IFREG,contents=io.BytesIO(data)) for name,data in values]
    if case=='short-kernel':entries[-1].contents=io.BytesIO(kernel[:-1])
    traversals=[]
    def read_fat(view):
        traversals.append(view)
        yield from entries
    if case=='valid':
        result=API['extract_boot_files'](None,read_fat,tmp_path,prepared)
        assert Path(result['path']).read_bytes()==kernel
        assert result['source_slice']=='nflasha3' and result['fat_path']=='vmlinux.bin'
        assert (tmp_path/'ram0.ext2').read_bytes()==ram
    else:
        with pytest.raises(ValueError):API['extract_boot_files'](None,read_fat,tmp_path,prepared)
    assert len(traversals)==(0 if case=='wrong-prepared' else 1)


def test_real_fat_kernel_and_ram0_readback(tmp_path,monkeypatch):
    read_fat=runpy.run_path(str(HERE/'prepare-full-system.py'))['readFat']
    fat=read_fat.__globals__;ram=b'ram0-from-fat';kernel=b'kernel-from-fat'
    image=io.BytesIO()
    fat['writeFat']([fat['UnixFile'](name,len(data),946684800,stat.S_IFREG,0,0,io.BytesIO(data))
        for name,data in (('initrd.img',ram),('vmlinux.bin',kernel))],2*1024**2,image)
    disk=tmp_path/'fat-disk';disk.write_bytes(b'prefix'+image.getvalue()+b'suffix')
    monkeypatch.setitem(API['COLD'],'ORIGINAL_RAMROOT_BYTES',len(ram))
    monkeypatch.setitem(API['COLD'],'ORIGINAL_RAMROOT_SHA',hashlib.sha256(ram).hexdigest())
    monkeypatch.setitem(API['COLD'],'KERNEL_SHA',hashlib.sha256(kernel).hexdigest())
    with disk.open('rb') as stream:
        result=API['extract_boot_files'](API['Slice'](stream.fileno(),6,len(image.getvalue())),read_fat,tmp_path,
            dict(bytes=len(kernel),sha256=hashlib.sha256(kernel).hexdigest()))
    assert Path(result['path']).read_bytes()==kernel
    assert (tmp_path/'ram0.ext2').read_bytes()==ram


def test_fresh_output_does_not_overlap_source(tmp_path):
    import pytest
    source=tmp_path/'source';source.mkdir()
    with pytest.raises(ValueError):API['fresh_output'](source/'nested',source)
    with pytest.raises(ValueError):API['fresh_output'](source,source)


def test_real_bwrap_preserves_prebound_fd():
    with tempfile.TemporaryFile() as f:
        f.write(b'prebound-fd-proof');f.flush()
        args=['bwrap','--unshare-all','--clearenv','--ro-bind','/usr','/usr','--symlink','usr/lib','/lib',
              '--symlink','usr/lib','/lib64','--proc','/proc','--dev','/dev','/usr/bin/python3','-c',
              'import os; assert os.pread('+str(f.fileno())+',17,0)==b"prebound-fd-proof"']
        subprocess.run(args,pass_fds=(f.fileno(),),check=True,timeout=10)


def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2)+'\n')


def actual(manifest_path,output,seconds=100):
    """Touch only the build's declared instance, never source images or physical IO."""
    cold=json.loads(manifest_path.read_text());output.mkdir(mode=0o700,parents=True,exist_ok=False)
    owner=runpy.run_path(str(HERE/'boot-execution.py'))
    result=dict(profile=API['PROFILE'],instance=cold['instance'],ram0_bytes=cold['ram0_bytes'],
                original_kernel_sha256=API['COLD']['KERNEL_SHA'],phases=[],verified=False)
    try:
        for phase in ('write','read'):
            print('PERSISTENT_PROOF_PREPARE '+phase,flush=True)
            launch=API['prepare_launch'](cold['prepared_runtime_analysis'],cold,output/phase,proof=phase)
            serial=output/phase/'serial.log';connection=stream=command=None
            with API['leased_launch'](launch) as bound:
                with serial.open('xb') as out:
                    process=subprocess.Popen(bound['command'],env=bound['env'],pass_fds=bound['pass_fds'],
                        stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT)
                bound['children'].append(process)
                record=dict(phase=phase,pid=process.pid,pass_fds=list(bound['pass_fds']),command=bound['command'],
                            inherited_disk_dev=bound['env']['PERSISTENT_DISK_DEV'],inherited_disk_ino=bound['env']['PERSISTENT_DISK_INO'])
                save(output/phase/'owner.json',record);print('PERSISTENT_PROOF_OWNER '+str(process.pid)+' '+phase,flush=True)
                deadline=time.monotonic()+seconds;matched=False;error=None
                try:
                    while time.monotonic()<deadline:
                        text=serial.read_text(errors='replace').replace('\r','')
                        if command is None and Path(launch['qmp_socket']).exists():
                            connection,stream,command=owner['qmp_connect'](launch['qmp_socket'])
                        if 'PERSISTENT_PROOF_COMPLETE mode='+phase in text:
                            matched=True;break
                        if 'PERSISTENT_BOOTSTRAP_FAILED' in text or 'Kernel panic' in text or 'Internal error: Oops' in text:
                            error='Original guest failed; retained serial';break
                        if process.poll() is not None:
                            error='Owner exited before proof marker';break
                        time.sleep(.1)
                    if not matched and error is None:error='Proof observation deadline reached'
                finally:
                    if process.poll() is None:
                        if command is None:connection,stream,command=owner['qmp_connect'](launch['qmp_socket'])
                        record['qmp_quit']=command('quit');process.wait(timeout=20)
                    if stream:stream.close()
                    if connection:connection.close()
                    record['returncode']=process.returncode
                    record['vm_signals']=[] if process.returncode is not None and process.returncode>=0 else [process.returncode]
                    record['proof_marker']=matched;record['error']=error
                    save(output/phase/'owner.json',record)
                text=serial.read_text(errors='replace').replace('\r','')
                record['capacity_rows']=len(re.findall(r'^PERSISTENT_CAPACITY .*expected=([0-9]+) actual=\1$',text,re.M))
                record['module_loaded']='PERSISTENT_FLASH_INSMOD rc=0' in text
                record['p7_mounted']='PERSISTENT_PROOF_P7_MOUNT verified=1' in text
                record['proof_cleanup']=phase!='read' or 'PERSISTENT_PROOF_REMOVED readback_absent=1' in text
                result['phases'].append(record);save(output/'result.json',result)
                if error or process.returncode or record['capacity_rows']!=20 or not record['module_loaded'] or not record['p7_mounted'] or not record['proof_cleanup']:
                    raise RuntimeError(error or 'Incomplete original guest evidence; inspect serial')
            print('PERSISTENT_PROOF_PHASE_PASS '+phase,flush=True)
        result.update(verified=True,filesystem_restart_verified=True,proof_file_removed=True,
            payload_sha256=cold['proof']['payload_sha256'],same_backend_inode=result['phases'][0]['inherited_disk_ino']==result['phases'][1]['inherited_disk_ino'],
            original_init_ap_boot_verified=False,physical_compatibility=False)
        save(output/'result.json',result);print(json.dumps(result,indent=2),flush=True)
        return result
    except BaseException as e:
        result.update(error=type(e).__name__+': '+str(e));save(output/'result.json',result);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actual',action='store_true',required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();actual(args.manifest.resolve(),args.output.resolve())
