#!/usr/bin/env python3
"""P1-only proposed build/activation adapter. Default OFF; no disk IO or VM startup."""
from pathlib import Path
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import secrets
import socket
import struct

HERE=Path(__file__).resolve().parent
PROFILE='virtual-p1-pmbp-block-slice-v1'
RUNTIME='simulation/pmbp-runtime'
BASE_PRELOAD='/simulation/p1-sd-observer.so\n/simulation/file-media-config.so\n'
_ACTUAL={}


def provider():
    key='p1_pmbp_provider_'+hashlib.sha256(str(HERE).encode()).hexdigest()[:16]
    if key not in sys.modules:
        spec=importlib.util.spec_from_file_location(key,HERE/'pmbp-provider.py')
        module=importlib.util.module_from_spec(spec);sys.modules[key]=module;spec.loader.exec_module(module)
    return sys.modules[key]


def selected(profile):
    return provider().selection(profile)


def preload(profile=None):
    selected(profile)
    return BASE_PRELOAD+('/simulation/pmbp-runtime/broker.so\n' if profile else '')


def prepare(root, checked_lease, output, *, profile=None):
    selected(profile)
    if profile is None:return dict(profile=None,assets={},preload=BASE_PRELOAD,guest_consumed=False)
    root=Path(root);output=Path(output)
    result=provider().build_candidate(root,checked_lease,output,profile=profile)
    dest=root/RUNTIME;dest.mkdir(mode=0o700,exist_ok=False)
    for name,row in result['assets'].items():
        shutil.copyfile(output/name,dest/name);(dest/name).chmod(row['mode'])
    result.update(assets={RUNTIME+'/'+n:r for n,r in result['assets'].items()},preload=preload(profile),
        build=dict(manifest=asdict(checked_lease.manifest),**checked_lease.proof),
        guest_consumed=False,formatter_verified=False,mount_verified=False,installation_verified=False)
    preflight(root,result)
    return result


def preflight(root,value):
    selected(value.get('profile'))
    if value.get('profile') is None:
        if value.get('assets'):raise ValueError('OFF declares PMBP assets')
        return {}
    provider().source_freeze(value['build']['reviewed_sources'])
    base=provider().secure(Path(root));runtime=provider().secure(base/RUNTIME,root_only=True)
    if value.get('preload') != preload(PROFILE):raise ValueError('Ordered PMBP preload differs')
    wanted={'broker.so','bootstrap','manifest.bin','profile','source.bundle','pmbp-pins.h'}
    if set(value['assets'])!={RUNTIME+'/'+n for n in wanted}:raise ValueError('Incomplete broker asset binding')
    for name,row in value['assets'].items():
        path=base/name;s=path.lstat()
        mode=0o700 if name==RUNTIME+'/bootstrap' else 0o600
        if row.get('mode')!=mode or not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)!=mode:raise ValueError('Broker asset ownership/mode differs: '+name)
        provider().stream_asset(dict(path=str(path),**row))
    bundle=provider().source_bundle()
    provider().stream_asset(dict(path=str(runtime/'source.bundle'),**bundle))
    m=provider().Manifest(**value['build']['manifest'])
    if bundle['sha256']!=m.source_sha:raise ValueError('Reviewed current/runtime bundle differs from manifest')
    if provider().original(runtime/'manifest.bin')[1]!=m.wire() or value['build'].get('build_provenance_only') is not True:raise ValueError('Build provenance differs')
    return value['assets']


def cpio_rows(root,value):
    rows=preflight(root,value)
    result={n:dict(bytes=r['bytes'],sha256=r['sha256'],mode=stat.S_IFREG|r['mode']) for n,r in rows.items()}
    if value.get('profile') is None:return result
    result[RUNTIME]=dict(bytes=0,sha256=hashlib.sha256(b'').hexdigest(),mode=stat.S_IFDIR|0o700)
    for name in ('init','etc/ld.so.preload','simulation/p1-sd-observer.so','simulation/file-media-config.so',
                 'simulation/sd-read-bindings','simulation/sd-read-binding-count','simulation/sony_persistent_flash.ko'):
        path=Path(root)/name;row=provider().original(path)[0]
        result[name]=dict(bytes=row['bytes'],sha256=row['sha256'],mode=path.lstat().st_mode)
    return result


def _recheck(row):
    return provider().stream_asset(row)[1]


def prepare_actual(execution, *, leased, lock, argv, cpio_readback):
    """Under a fresh actual camera-disk lease, before Popen; no build PID gate."""
    p=provider();p._check_p1_lock(leased,lock)
    value=execution['pmbp'];p.source_freeze(value['build']['reviewed_sources'])
    root=Path(execution['output'])/'root';preflight(root,value)
    m=p.Manifest(**value['build']['manifest']);s=os.fstat(leased['fd'])
    if (s.st_dev,s.st_ino,s.st_size)!=(m.disk_dev,m.disk_ino,m.disk_bytes):raise ValueError('Actual lease disk differs from build')
    state=leased['state']
    if (state['generation'],state['source_manifest_sha256'])!=(m.generation,m.instance_sha):raise ValueError('Actual generation/source differs')
    for name,current in [('instance.json',state),('geometry.json',leased['geometry'])]:
        row,data=p.original(Path(leased['path'])/name)
        if json.loads(data)!=current or (name=='geometry.json' and row['sha256']!=state['geometry_sha256']):raise ValueError('Actual metadata differs')
    slices=[r for r in leased['geometry']['slices'] if r['id']=='nflasha23']
    if len(slices)!=1 or (slices[0]['offset'],slices[0]['bytes'])!=(p.OFFSET,p.SIZE):raise ValueError('Actual p23 geometry differs')
    if p.sha(json.dumps(value['build']['profile_contract'],sort_keys=True).encode())!=m.parent_profile_sha:raise ValueError('Build profile contract changed')
    if any(execution['qemu'][k]!=value['build']['binary'][k] for k in ('path','bytes','sha256')):raise ValueError('Actual QEMU differs from build')
    for row in value['build']['build_inputs']+execution['inputs']+execution['artifacts']+[execution['state'],execution['geometry']]:_recheck(row)
    rows=cpio_rows(root,value)
    archive=Path(execution['output'])/'probe.cpio.gz'
    if cpio_readback(archive,rows)!=rows:raise ValueError('Actual CPIO readback differs')
    import runpy
    runpy.run_path(str(HERE/'p1-tail-source.py'))['_cpio_owners'](archive,set(rows))
    exe='/tools/'+Path(execution['qemu']['path']).name
    if argv.count(exe)!=1 or argv.count('-S')!=1:raise ValueError('P1 activation requires one explicit -S')
    offset=argv.index(exe)
    nonce=secrets.token_hex(32)
    argv[offset:offset]=['--setenv','QEMU_A7PF_PMBP_NONCE',nonce]
    offset+=3;qargv=argv[offset:]
    env={};prefix=argv[:offset]
    for i,word in enumerate(prefix):
        if word=='--setenv':
            key,val=prefix[i+1:i+3]
            if key in env:raise ValueError('Duplicate QEMU environment')
            env[key]=val
    want={f'QEMU_A7PF_{k}':str(v) for k,v in [('FD',leased['fd']),('DEV',s.st_dev),('INO',s.st_ino)]}
    want['QEMU_A7PF_PROFILE']='persistent-flash-cold-v1'
    want['QEMU_A7PF_PMBP_NONCE']=nonce
    if any(env.get(k)!=v for k,v in want.items()):raise ValueError('Actual bwrap QEMU ABI differs')
    # Source closure is checked before Popen, so an incomplete candidate cannot run a guest.
    spec=importlib.util.spec_from_file_location('pmbp_source_closure',HERE/'closure-source-check.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    coverage=module.check(root/'usr/lib/libInfraMediaCommon.so')
    if coverage['source_coverage_complete'] is not True:raise OSError(95,'Fixed p23 source closure incomplete: '+repr(coverage['remaining']))
    token=object();_ACTUAL[token]=dict(parent=(os.getpid(),p.process_starttime(os.getpid())),execution=execution,
        argv=qargv,env=want,fd=leased['fd'],lock=lock,stamp=(s.st_dev,s.st_ino,s.st_size),root=root,value=value)
    return token


def _child_identity(pid):
    text=Path(f'/proc/{pid}/stat').read_text();fields=text[text.rfind(')')+2:].split()
    return int(fields[1]),int(fields[19])


def _verify_child(context,owner,pid):
    """Read actual procfs; fixture tests use a labelled ordinary Python process."""
    p=provider();start=_child_identity(pid);cursor=pid;seen=set()
    while cursor!=owner.pid:
        if cursor in seen or cursor<=1:raise ValueError('QEMU is not a registered owner descendant')
        seen.add(cursor);cursor=_child_identity(cursor)[0]
    if _child_identity(owner.pid)[0]!=os.getpid() or owner.poll() is not None:raise ValueError('Registered launch owner changed/exited')
    row=context['execution']['qemu'];expected=_recheck(row);actual=os.stat(f'/proc/{pid}/exe')
    if (actual.st_dev,actual.st_ino)!=(expected.st_dev,expected.st_ino):raise ValueError('Actual QEMU executable differs')
    # /proc/PID/exe is an intentional procfs link; pin the opened fd to the checked asset.
    exe_fd=os.open(f'/proc/{pid}/exe',os.O_RDONLY|os.O_CLOEXEC)
    try:
        pinned=p.hash_descriptor(exe_fd,row)
        if (pinned.st_dev,pinned.st_ino)!=(expected.st_dev,expected.st_ino):raise ValueError('Actual QEMU executable raced')
    finally:os.close(exe_fd)
    args=Path(f'/proc/{pid}/cmdline').read_bytes().rstrip(b'\0').split(b'\0')
    if args!=[x.encode() for x in context['argv']]:raise ValueError('Actual QEMU arguments differ')
    pairs=[x.split(b'=',1) for x in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if x]
    env={k.decode():v.decode() for k,v in pairs}
    if len(env)!=len(pairs) or any(env.get(k)!=v for k,v in context['env'].items()):raise ValueError('Actual QEMU environment differs')
    fd=context['fd'];s=os.stat(f'/proc/{pid}/fd/{fd}')
    if (s.st_dev,s.st_ino,s.st_size)!=context['stamp']:raise ValueError('Actual QEMU inherited disk FD differs')
    witness=p.ofd_receipt(fd,pid)
    ids={line.split(':',1)[0]:line.split(':',1)[1].split() for line in Path(f'/proc/{pid}/status').read_text().splitlines() if line.startswith(('Uid:','Gid:'))}
    if ids.get('Uid')!=[str(os.geteuid())]*4 or ids.get('Gid')!=[str(os.getegid())]*4:raise ValueError('Actual QEMU credentials differ')
    if _child_identity(pid)!=start:raise ValueError('Actual QEMU PID changed')
    return dict(pid=pid,starttime=start[1],uid=os.geteuid(),gid=os.getegid(),fdinfo_sha=p.sha(witness.encode()))


def _context(token,leased,lock):
    context=_ACTUAL.get(token);p=provider()
    if context is None or context['parent']!=(os.getpid(),p.process_starttime(os.getpid())):raise ValueError('Fresh actual parent capability required')
    if context['lock'] is not lock or context['fd']!=leased['fd']:raise ValueError('Actual lease capability changed after preflight')
    p._check_p1_lock(leased,lock)
    return context


def _unique_child(context,owner):
    identity=(owner.pid,_child_identity(owner.pid)[1])
    if context.setdefault('owner',identity)!=identity:raise ValueError('Registered owner changed')
    if _child_identity(owner.pid)[0]!=os.getpid() or owner.poll() is not None:raise ValueError('Registered owner is not alive under this parent')
    expected=_recheck(context['execution']['qemu']);pending=[owner.pid];found=[];seen=set()
    while pending:
        pid=pending.pop()
        if pid in seen:raise ValueError('Repeated launch process')
        seen.add(pid)
        try:
            before=_child_identity(pid);s=os.stat(f'/proc/{pid}/exe')
            if (s.st_dev,s.st_ino)==(expected.st_dev,expected.st_ino):found.append(pid)
            pending.extend(map(int,Path(f'/proc/{pid}/task/{pid}/children').read_text().split()))
            if _child_identity(pid)!=before:raise ValueError('Launch process changed during discovery')
        except FileNotFoundError:continue
    if len(found)!=1:raise ValueError('Unique actual QEMU descendant unavailable')
    receipt=_verify_child(context,owner,found[0])
    if _child_identity(owner.pid)[1]!=identity[1]:raise ValueError('Owner PID changed')
    return receipt


def connect_verified(token, *, leased, lock, owner, path, timeout=3):
    """Authenticate this actual child before any QMP command, including cleanup."""
    context=_context(token,leased,lock);p=provider();receipt=_unique_child(context,owner)
    path=Path(path).absolute()
    if path.name!='qmp.sock':raise ValueError('P1 QMP socket name differs')
    p.secure(path.parent,root_only=True)
    connection=stream=None
    try:
        with p.checked_directory(path.parent) as directory:
            before=os.stat(path.name,dir_fd=directory,follow_symlinks=False)
            if not stat.S_ISSOCK(before.st_mode) or before.st_uid!=receipt['uid'] or before.st_gid!=receipt['gid'] or before.st_mode&0o077 or before.st_nlink!=1:raise ValueError('Unsafe P1 QMP endpoint')
            connection=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);connection.settimeout(timeout)
            connection.connect(f'/proc/self/fd/{directory}/{path.name}')
            def peer():
                actual=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))
                if actual!=(receipt['pid'],receipt['uid'],receipt['gid']):raise ValueError('Foreign QMP peer credentials')
                if _child_identity(receipt['pid'])[1]!=receipt['starttime'] or _child_identity(owner.pid)[1]!=context['owner'][1] or owner.poll() is not None:raise ValueError('QMP peer/owner PID changed')
                p._check_p1_lock(leased,lock)
            peer()
            after=os.stat(path.name,dir_fd=directory,follow_symlinks=False)
            if any(getattr(before,k)!=getattr(after,k) for k in p._STAMP):raise ValueError('QMP endpoint changed during connect')
        # No greeting read or command send occurs before SO_PEERCRED authentication.
        stream=connection.makefile('rb')
        def receive():
            line=stream.readline(65537)
            if not line.endswith(b'\n') or len(line)>65536:raise ValueError('Invalid bounded QMP frame')
            value=json.loads(line)
            if type(value) is not dict:raise ValueError('Invalid QMP object')
            return value
        greeting=receive()
        if set(greeting)!={'QMP'} or type(greeting['QMP']) is not dict:raise ValueError('Invalid QMP greeting')
        if _unique_child(context,owner)!=receipt:raise ValueError('QMP child changed before capabilities')
        sequence=0
        def command(name,args=None):
            nonlocal sequence
            peer();sequence+=1;request=dict(execute=name,id=sequence)
            if args is not None:request['arguments']=args
            connection.sendall(json.dumps(request,separators=(',',':')).encode()+b'\r\n')
            for _ in range(256):
                reply=receive()
                if 'event' in reply:continue
                if type(reply.get('id')) is not int or reply['id']!=sequence:raise ValueError('QMP response id differs')
                return {k:v for k,v in reply.items() if k!='id'}
            raise ValueError('QMP event budget exhausted')
        if command('qmp_capabilities')!={'return':{}}:raise ValueError('QMP capabilities rejected')
        context.setdefault('commands',set()).add(command)
        return connection,stream,command
    except BaseException:
        if stream is not None:stream.close()
        if connection is not None:connection.close()
        raise


def activate_paused(token, *, leased, lock, owner, qmp, owner_name):
    """Only a connection issued above may admit this paused actual child."""
    context=_context(token,leased,lock);p=provider()
    if qmp not in context.get('commands',()) or context.get('activated'):raise ValueError('Verified fresh P1 QMP connection required')
    p.source_freeze(context['value']['build']['reviewed_sources']);preflight(context['root'],context['value'])
    receipt=_unique_child(context,owner)
    if qmp('query-name')!={'return':{'name':owner_name}}:raise ValueError('QMP owner name differs')
    status=qmp('query-status').get('return',{})
    if status.get('status')!='prelaunch' or status.get('running') is not False:raise ValueError('QEMU has left -S prelaunch state')
    for row in context['execution']['inputs']+context['execution']['artifacts']:_recheck(row)
    p._check_p1_lock(leased,lock)
    if _unique_child(context,owner)!=receipt:raise ValueError('QEMU child changed during admission')
    status=qmp('query-status').get('return',{})
    if status.get('status')!='prelaunch' or status.get('running') is not False:raise ValueError('QEMU state changed during admission')
    if qmp('cont')!={'return':{}}:raise ValueError('Original QEMU cont failed')
    context['activated']=True
    return dict(**receipt,actual_parent_pid=os.getpid(),actual_parent_starttime=p.process_starttime(os.getpid()),
        activation_verified=True,guest_consumed=False,build_parent_is_provenance_only=True)


def forget_actual(token, *, owner):
    if owner is None:
        context=_ACTUAL.get(token)
        if context is None or any(key in context for key in ('owner','commands','activated')):
            raise ValueError('Only an unregistered, unactivated Popen-failure context may omit its owner')
    elif owner.poll() is None:
        raise ValueError('Live owner retains its P1 capability and lease')
    _ACTUAL.pop(token,None)


if __name__=='__main__':
    raise SystemExit('Use explicit P1 build/actual call sites; JSON does not supply a live lease')
