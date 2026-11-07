#!/usr/bin/env python3
"""Explicit mailbox-v1 -> original InfraInput; uart remains a separate profile.

prepare() only accepts a runtime below the dedicated low-input scratch directory.
No import-time hooks, global sockets, VM attachment or implicit UART fallback.
"""
import argparse
import ctypes
import fcntl
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import runpy
import secrets
import shutil
import stat
import struct
import subprocess
import tempfile
import threading
import time

HERE=Path(__file__).resolve().parent
PROFILE='mailbox-v1'
PHYSICAL=0x41ef00000
CAPACITY=4096
RAM_BASE=0x40000000
RAM_BYTES=24*1024**3
OFFSET=PHYSICAL-RAM_BASE
MAGIC=0x31504e494c374137
RESERVATION='memrsv=0x00001000@0x41ef00000:uc'
CONTACTS={0x1ab,0x1ac,3,0x30,0x15,0x1af,0x1f8,0x66,0x1f7,0x0f000004,0x7095,0x1f1,0xa7,0x1f0}
DIALS={0x10000013,0x10000016,0x1000001c,0x1000001d}
RAW=re.compile(r'/simulation/inject-key 0x807a0020 0x92840747 (0x[0-9a-f]+|[0-9]+) 0 (0x[0-9a-f]+|[0-9]+) 0 1')


def digest(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def checksum(data):
    value=2166136261
    for byte in data:value=((value^byte)*16777619)&0xffffffff
    return value


def packet(op,code=0,status=0,pulse=0):
    if type(op) is not int or op not in (1,2,3,4,5):raise ValueError('Unknown mailbox operation')
    if any(type(value) is not int or not 0<=value<=0xffffffff for value in (code,status,pulse)):
        raise ValueError('Mailbox fields must be u32')
    if op in (3,4):
        if code or status or pulse:raise ValueError('Cancel/stop cannot carry input')
    elif op==5:
        if code or status or pulse!=50:raise ValueError('Fixed shutter sequence requires four 50ms stages')
    else:
        signed=status if status<0x80000000 else status-0x100000000
        valid=(code in CONTACTS and status in (0,1)) or (code in DIALS and 0<abs(signed)<=32768) or (
            code==0x71c9 and status in (1,2,3)) or (code==0x7025 and status in (1,3,4,5,6,7,19,20))
        if not valid:raise ValueError('Unknown raw input key/status domain')
        if op==2 and (code not in CONTACTS or status!=1 or pulse!=50):raise ValueError('Pulse requires an original contact and 50ms release')
        if op==1 and pulse:raise ValueError('Single edge cannot carry a pulse')
    body=struct.pack('<7I',op,code,status,pulse,32,0,0)
    return body+struct.pack('<I',checksum(body))


def parse_command(command):
    if not isinstance(command,str):raise ValueError('Input command must be text')
    if '/simulation/inject-' not in command:return None
    if len(command)>4096:raise ValueError('Input command exceeds bounded text contract')
    command=command.strip()
    shutter=''.join(f'/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 {status:#x} 0 1; step{index}=$?; sleep 0.05; '
        for index,(code,status) in enumerate(((0x1f1,1),(0xa7,1),(0xa7,0),(0x1f1,0))))
    shutter+='test "$step0" = 0 && test "$step1" = 0 && test "$step2" = 0 && test "$step3" = 0'
    if command==shutter:return packet(5,0,0,50)
    pieces=command.split('; pressed=$?; sleep 0.05; ')
    if len(pieces)==2:
        first=RAW.fullmatch(pieces[0])
        tail='; released=$?; test "$pressed" = 0 && test "$released" = 0'
        second=RAW.fullmatch(pieces[1][:-len(tail)]) if pieces[1].endswith(tail) else None
        if first and second:
            a,b=([int(value,0) for value in match.groups()] for match in (first,second))
            if a[0]==b[0] and a[1]==1 and b[1]==0:return packet(2,a[0],1,50)
    match=RAW.fullmatch(command)
    if match:
        code,status=(int(value,0) for value in match.groups())
        return packet(1,code,status)
    raise ValueError('Input shape/route is not admitted by explicit mailbox-v1; no UART fallback')


def ram_backend_adapter(adapter, *, prepared=False):
    assignments=[value.strip() for value in re.findall(r'^\s*memory_config=([^\n#]+)',adapter,re.M)]
    mib=RAM_BYTES//1024**2
    if assignments!=['"$ram_mb"','16384',str(mib)] or adapter.count(
            f'if [[ "$high_ddr" == 1 ]]; then\n  memory_config={mib}\n')!=1:
        raise ValueError('Unknown full-system RAM capacity/override order; expected final high-DDR 24576 MiB')
    if adapter.count('-m "$memory_config"')!=1:
        raise ValueError('Unknown full-system machine memory argument')
    old='-accel tcg,thread="${QEMU_TCG_THREAD:-single}" -machine virt,secure=off -cpu'
    new=f'-object memory-backend-file,id=lowinputram,size={RAM_BYTES},mem-path=/out/low-input-ram.bin,share=on -accel tcg,thread="${{QEMU_TCG_THREAD:-single}}" -machine virt,secure=off,memory-backend=lowinputram -cpu'
    if prepared:
        if adapter.count(new)!=1 or adapter.count('memory-backend-file')!=1:
            raise ValueError('Prepared backend size/wiring differs from the 24GiB machine RAM contract')
        return adapter
    if adapter.count(old)!=1 or 'memory-backend-file' in adapter:
        raise ValueError('Prepared QEMU command shape is unknown')
    return adapter.replace(old,new)


def validate_runtime(runtime,profile):
    runtime=Path(runtime)
    manifest=json.loads((runtime/'analysis/full-system.json').read_text())
    metadata=manifest.get('low_latency_input')
    if profile=='uart':
        if metadata is not None:raise ValueError('Mailbox-prepared RAM requires explicit mailbox-v1, not the UART profile')
        return
    if profile!=PROFILE or not isinstance(metadata,dict) or metadata.get('profile')!=PROFILE:
        raise ValueError('Explicit mailbox-v1 requires its independently prepared runtime')
    if any(metadata.get(key)!=value for key,value in {'physical':PHYSICAL,'capacity':CAPACITY,'ram_base':RAM_BASE,'ram_bytes':RAM_BYTES}.items()):
        raise ValueError('Low-input mailbox/RAM geometry differs from the explicit profile')
    adapter=runtime/'analysis/qemu-kernel-probe.sh'
    actual_adapter=digest(adapter)
    if manifest.get('board_adapter_sha256')!=actual_adapter or metadata.get('board_adapter_sha256')!=actual_adapter:
        raise ValueError('Low-input board adapter identity differs from the prepared manifest')
    ram_backend_adapter(adapter.read_text(),prepared=True)
    if metadata.get('machine_ram_mib')!=RAM_BYTES//1024**2:
        raise ValueError('Low-input machine/backend RAM capacity binding differs')
    if metadata.get('host_source_sha256')!=digest(HERE/'low-latency-input.py'):
        raise ValueError('Low-input host source changed after preparation')
    if metadata.get('source_sha256')!=digest(HERE/'guest/low-latency-input.c') or metadata.get('helper_sha256')!=digest(runtime/'analysis/root/simulation/low-latency-input'):
        raise ValueError('Low-input guest source/program identity differs')


class LowLatencyInput:
    def __init__(self,run,qmp,serial,*,timeout=3):
        self.run=Path(run).resolve(strict=True)
        self.owner=os.getpid()
        inputs=json.loads((self.run/'inputs.json').read_text())
        self.metadata=inputs.get('low_latency_input')
        if inputs.get('host_runner_pid')!=self.owner or not isinstance(self.metadata,dict) or self.metadata.get('profile')!=PROFILE:
            raise ValueError('Foreign run owner or missing explicit mailbox profile')
        if any(self.metadata.get(key)!=value for key,value in {'physical':PHYSICAL,'capacity':CAPACITY,'ram_base':RAM_BASE,'ram_bytes':RAM_BYTES}.items()):
            raise ValueError('Mailbox physical mapping identity differs')
        if inputs.get('experiment',{}).get('low_latency_input')!=PROFILE:
            raise ValueError('This owner did not select the mailbox-v1 input profile')
        self.qmp,self.serial=qmp,serial
        self.sequence=0
        self.fault=''
        self.failed_result=None
        self.failed_sequence=None
        self.quiesced_after_fault=None
        self.closed=False
        self.fd=self.lease=self.mapping=None
        self.lock=threading.Lock()
        self.cookie=secrets.token_bytes(16)
        try:
            self.lease=os.open(self.run/'low-input.lease',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
            if os.fstat(self.lease).st_nlink!=1:raise ValueError('Mailbox lease must be private')
            fcntl.flock(self.lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.fd=os.open(self.run/'low-input-ram.bin',os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC)
            info=os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or info.st_size!=RAM_BYTES:
                raise ValueError('Mailbox backend must be the owned exact-size regular QEMU RAM file')
            self.mapping=mmap.mmap(self.fd,CAPACITY,offset=OFFSET)
            if any(self.mapping[:96]):raise ValueError('Mailbox RAM was already owned or reused')
            self.mapping[:64]=struct.pack('<Q',MAGIC)+self.cookie+struct.pack('<QIIQQII',1,0,0,0,0,0,0)
            self.mapping.flush()
            qmp('pmemsave',{'val':PHYSICAL,'size':64,'filename':'/out/low-input-map-readback.bin'})
            if (self.run/'low-input-map-readback.bin').read_bytes()!=self.mapping[:64]:
                raise ValueError('QMP physical readback does not match this owned RAM mailbox')
            command=f'/simulation/low-latency-input {self.cookie.hex()} >/log/qemu/low-input.log 2>&1 & echo LOW_INPUT_DAEMON_PID=$!'
            serial(command,timeout=10)
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                if self._u32(32)==1 and self._u32(36):break
                if self._u32(32) in (2,3):raise RuntimeError('Guest daemon failed during startup: '+str(self._u32(56)))
                time.sleep(.001)
            else:raise TimeoutError('Guest low-input daemon readiness was not observed')
            self.pid=self._u32(36)
            self._journal('ready',pid=self.pid,physical=hex(PHYSICAL))
        except BaseException:
            self.dispose()
            raise

    def _u32(self,offset):return struct.unpack_from('<I',self.mapping,offset)[0]
    def _u64(self,offset):return struct.unpack_from('<Q',self.mapping,offset)[0]

    def _journal(self,event,**fields):
        with (self.run/'low-input.jsonl').open('a') as out:
            out.write(json.dumps(dict(event=event,host_ns=time.monotonic_ns(),owner_pid=self.owner,**fields))+'\n')

    def check(self):
        if os.getpid()!=self.owner:raise ValueError('Mailbox sender crossed process owner')
        if self.closed:raise RuntimeError('Mailbox input session is closed')
        if self.mapping[:24]!=struct.pack('<Q',MAGIC)+self.cookie:raise RuntimeError('Mailbox cookie/identity changed')
        ready=self._u32(32)
        if ready!=1:
            if (not self.fault and ready==3 and self.sequence>0 and
                    self._u64(40)==self._u64(48)==self.sequence and self._u32(56)):
                self.failed_sequence=self.sequence
                self.failed_result=self._u32(56)
            self.fault=self.fault or f'Guest low-input daemon state={ready}, rc={self._u32(56)}, held={self._u32(60)}'
        if self.fault:raise RuntimeError(self.fault)
        struct.pack_into('<Q',self.mapping,24,self._u64(24)+1)

    def submit(self,body,*,timeout=1):
        if not isinstance(body,bytes) or len(body)!=32:raise ValueError('Mailbox command must contain exactly 32 bytes')
        fields=struct.unpack('<8I',body)
        if packet(*fields[:4])!=body:raise ValueError('Mailbox packet length/checksum mismatch')
        if not 0<timeout<=30:raise ValueError('Mailbox timeout must be within 0..30 seconds')
        with self.lock:
            self.check()
            if self._u64(40)!=self._u64(48):
                self.fault='Mailbox already has an unacknowledged owner'
                raise RuntimeError(self.fault)
            sequence=self.sequence+1
            self.mapping[64:96]=body
            self.mapping.flush()
            self._journal('publish',sequence=sequence,op=fields[0],code=fields[1],status=fields[2])
            struct.pack_into('<Q',self.mapping,40,sequence)
            self.sequence=sequence
            deadline=time.monotonic()+timeout
            try:
                while time.monotonic()<deadline:
                    if self._u64(48)==sequence:
                        result=self._u32(56)
                        if result:
                            self.failed_sequence=sequence
                            self.failed_result=result
                            raise RuntimeError(f'Original low-input send failed rc={result}, held={self._u32(60)}')
                        if fields[0]!=4:self.check()
                        self._journal('ack',sequence=sequence,result=result,held=self._u32(60))
                        return f'LOW_INPUT_DONE profile={PROFILE} seq={sequence} rc=0 op={fields[0]} original_queue=0x807a0020\n'.encode()
                    self.check()
                    time.sleep(.001)
                raise TimeoutError(f'Guest low-input ACK missing for sequence={sequence}; original release/ownership uncertain')
            except BaseException as error:
                self.fault=str(error)
                self._journal('blocked',sequence=sequence,reason=self.fault)
                raise

    def execute(self,command,*,timeout=1):
        body=parse_command(command)
        if body is None:return None
        return self.submit(body,timeout=timeout)

    def cancel(self):return self.submit(packet(3))

    def _confirm_fault_quiesced(self):
        if os.getpid()!=self.owner:raise ValueError('Mailbox sender crossed process owner')
        if self.mapping[:24]!=struct.pack('<Q',MAGIC)+self.cookie:
            raise RuntimeError('Mailbox cookie/identity changed during fault cleanup')
        if (not self.fault or self.failed_result not in (10,11) or self.failed_sequence!=self.sequence or
                self.sequence<=0 or self._u32(32)!=3 or self._u32(36)!=self.pid or self._u32(60) or
                self._u64(40)!=self.sequence or self._u64(48)!=self.sequence or
                self._u32(56)!=self.failed_result):
            return False
        # A fault exit with no contacts releases the lease, without turning the original request into success.
        confirmed=dict(original_fault=self.fault,result=self.failed_result,sequence=self.sequence,
                       guest_state=3,confirmed_no_held=True)
        self._journal('quiesced_after_fault',**confirmed)
        self.quiesced_after_fault=confirmed
        self.closed=True
        return True

    def close(self):
        if self.closed:return
        try:
            if self._confirm_fault_quiesced():return
            self.submit(packet(4))
            deadline=time.monotonic()+1
            while self._u32(32)==1 and time.monotonic()<deadline:time.sleep(.001)
            if self._u32(32)!=2 or self._u32(60):raise RuntimeError('Guest low-input stop did not release all original contacts')
            self._journal('closed',sequence=self.sequence,pid=self.pid)
            self.closed=True
        finally:self.dispose()

    def dispose(self):
        if self.mapping is not None:self.mapping.close();self.mapping=None
        for name in ('fd','lease'):
            fd=getattr(self,name,None)
            if fd is not None:os.close(fd);setattr(self,name,None)


def prepare(runtime,source=HERE):
    """Append only one compiled helper; preserve original AP/partitions and adapters."""
    runtime=Path(runtime).resolve(strict=True);source=Path(source).resolve(strict=True)
    permitted=HERE.parents[1]/'analysis/scratch/a7c2-ui-latency-20261106/low-input'
    if not runtime.is_relative_to(permitted.resolve()):raise ValueError('Preparation requires the dedicated independent low-input runtime copy')
    analysis=runtime/'analysis'
    with runpy.run_path(str(source/'runtime-lock.py'))['open_runtime_lock'](runtime):
        manifest=json.loads((analysis/'full-system.json').read_text())
        if 'low_latency_input' in manifest:raise ValueError('Low-input runtime is already prepared')
        if digest(analysis/'full-system.cpio')!=manifest['initrd_sha256'] or digest(analysis/'qemu-kernel-probe.sh')!=manifest['board_adapter_sha256']:
            raise ValueError('Prepared runtime source identities differ')
        workspace_path=analysis/'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt'
        workspace=workspace_path.read_text()
        reserved=runpy.run_path(str(source/'reserved-region.py'))
        reserved['validate_workspace'](workspace,PHYSICAL,CAPACITY)
        libc=ctypes.CDLL(str(runtime/'sources/qemu-tools/usr/lib/libfdt.so.1'))
        boards={}
        for name in ['boards/virt-four.dtb','qemu-virt-board/virt-packed.dtb']:
            original=analysis/name
            storage=ctypes.create_string_buffer(2*1024*1024)
            raw=ctypes.create_string_buffer(original.read_bytes())
            if libc.fdt_open_into(raw,storage,len(storage)):raise ValueError('Cannot expand independent board')
            # Apply the same explicit high-DDR relocation as the pinned launcher before validating ownership.
            libc.fdt_getprop.restype=ctypes.c_void_p
            node=libc.fdt_next_node(storage,-1,None)
            while node>=0:
                length=ctypes.c_int()
                pointer=libc.fdt_getprop(storage,node,b'device_type',ctypes.byref(length))
                if pointer and ctypes.string_at(pointer,length.value)==b'memory\0':
                    pointer=libc.fdt_getprop(storage,node,b'reg',ctypes.byref(length))
                    original_ram=ctypes.string_at(pointer,length.value) if pointer else b''
                    if original_ram!=struct.pack('>QQ',0x40000000,0x100000000):
                        raise ValueError('Unknown pre-relocation board RAM geometry')
                    high_ram=struct.pack('>QQ',0x400000000,0x200000000)
                    if libc.fdt_setprop(storage,node,b'reg',high_ram,len(high_ram)):
                        raise ValueError('Cannot apply original full-dump DDR relocation')
                    break
                node=libc.fdt_next_node(storage,node,None)
            else:raise ValueError('Missing original board memory node')
            reserved['add_reservation'](libc,storage,workspace+' '+RESERVATION,
                physical=PHYSICAL,capacity=CAPACITY,command=RESERVATION,key=b'qemu,a7c2-low-input')
            if libc.fdt_pack(storage):raise ValueError('Cannot pack independent board')
            size=int.from_bytes(storage.raw[4:8],'big')
            boards[name]=storage.raw[:size]
        adapter=ram_backend_adapter((analysis/'qemu-kernel-probe.sh').read_text())
        helper=analysis/'root/simulation/low-latency-input'
        helper.parent.mkdir(parents=True,exist_ok=True)
        native=runpy.run_path(str(source/'native-input.py'))['resolve']()
        lib=source/'runtime/analysis/root/lib'
        if not lib.is_dir():raise ValueError('Pinned original guest libc directory unavailable')
        libraries=[native/'runtime/analysis/menu-root/usr/lib'/name for name in ['libosal_uipc.so','libosal_utm.so']]
        libraries += [lib/name for name in ['libc-2.25.so','libpthread-2.25.so','libdl-2.25.so','ld-2.25.so']]
        subprocess.run(['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-O2','-mno-outline-atomics',
            '-Wl,--no-undefined','-Wl,-e,_start','-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',str(source/'guest/low-latency-input.c'),
            '-Wl,--no-as-needed','-Wl,--allow-shlib-undefined',*map(str,libraries),'-o',str(helper)],check=True,timeout=30)
        # cpio append keeps the private root image bytes; only the new simulation helper is added.
        subprocess.run(['cpio','--null','-o','-A','-H','newc','--quiet','-F',str((analysis/'full-system.cpio').resolve())],
            cwd=analysis/'root',input=b'simulation/low-latency-input\0',check=True,timeout=30)
        metadata={'profile':PROFILE,'physical':PHYSICAL,'capacity':CAPACITY,'ram_base':RAM_BASE,'ram_bytes':RAM_BYTES,
            'machine_ram_mib':RAM_BYTES//1024**2,'board_adapter_sha256':hashlib.sha256(adapter.encode()).hexdigest(),
            'source_sha256':digest(source/'guest/low-latency-input.c'),'helper_sha256':digest(helper),
            'host_source_sha256':digest(source/'low-latency-input.py'),'parent_initrd_sha256':manifest['initrd_sha256'],
            'parent_board_adapter_sha256':manifest['board_adapter_sha256'],'libraries':{str(p.relative_to(source)) if p.is_relative_to(source) else p.name:digest(p) for p in libraries},
            'transport_scope':'Explicit functional mailbox; original InfraInput raw 20-byte API, AP consumption requires separate evidence'}
        workspace_path.write_text(workspace+'\n'+RESERVATION+'\n')
        for name,data in boards.items():(analysis/name).write_bytes(data)
        (analysis/'qemu-kernel-probe.sh').write_text(adapter)
        manifest.update(low_latency_input=metadata,initrd_sha256=digest(analysis/'full-system.cpio'),
            board_adapter_sha256=digest(analysis/'qemu-kernel-probe.sh'),four_cpu_template_sha256=digest(analysis/'boards/virt-four.dtb'))
        (analysis/'full-system.json').write_text(json.dumps(manifest,indent=2)+'\n')
        return metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-runtime',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.prepare_runtime),indent=2))
