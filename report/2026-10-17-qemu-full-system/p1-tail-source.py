#!/usr/bin/env python3
"""Proposed opt-in source decorator. No filesystem mutation or VM launch APIs."""
import copy
import gzip
import hashlib
import io
import json
import os
import re
import runpy
import stat
from pathlib import Path
from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError
HERE = Path(__file__).resolve().parent
PROFILE = 'original-p1-stock-tail-v1'
ENV = 'A7C2_P1_TAIL_PROFILE'
PMBP_ENV = 'A7C2_P1_TAIL_PMBP_PROFILE'
ROUTE_API = 'original-lr-at-runtime-v1'
PMBP_NAMES = ('broker.so','bootstrap','manifest.bin','profile','source.bundle','pmbp-pins.h')
VERSION_SCRIPT = 'OPENSSL_1_1_0 { global: SHA1_Final; SHA256; RSA_verify; };\n'
# Original source assets only; body has its own sourceRoot and never aliases sd root.
ASSETS = {
 'sd': ('usr/lib/libsdfileinputupdaterapi.so','1a6a3226993ce7c25659bd58e20871d91869083b31440650eec555a06d592d2f'),
 'crypto':('usr/lib/libcrypto.so.1.1','df69906d5f63a3afe9b7872e41cab741c346630e53ebcaadb86e457f0b803726'),
 'common':('usr/lib/libupdatercommon.so','b601bf34b09ca34b74d9ee99f0de0b83d34fab30e3d2648468ab479a0bf6eb05'),
 'body':('bodylib/libupdaterbody.so','d9a4945ac5760d820b6e10a91aa95380392f81be50960510706251ca87b13de4')}
PINS = [('sd','verifyKey',0xaaa0),('crypto','SHA1_Final',0x187d18),('crypto','SHA256',0x18a2d0),('crypto','RSA_verify',0x182c20),
 ('common','WriteAll',0x89c4),('common','Close',0x8810),('body','ShellPlugin',0x18824),('body','BuildInPlugin',0x19224),
 ('body','DllPlugin',0x18b94),('body','ThreadPluginJoin',0x18344),('body','EndUpdate',0x19510),('body','CompleteUpdate',0x1a390),
 ('body','ThreadPluginSetError',0x187e8),('body','ThreadPluginHasError',0x18124)]

def selection(profile=None, *, mode=None, install_profile=None, signature_schema=None):
    if profile is not None and (profile!=PROFILE or mode!='official' or
            install_profile!='original-p1-virtual-install-v1' or signature_schema!='p1-trust-key-abi-v1'):
        raise ValueError('Tail observation requires the exact explicit stock install profile')
    return profile

def effective_env(profile=None, inherited=None, *, pmbp_profile=None):
    if profile not in (None, PROFILE):raise ValueError('Unknown tail profile')
    if pmbp_profile not in (None, PMBP_PROFILE) or (pmbp_profile and profile!=PROFILE):
        raise ValueError('Explicit tail/PMBP runtime selection required')
    result=dict(inherited or {});result.pop(ENV,None);result.pop(PMBP_ENV,None)
    if profile:result[ENV]=profile
    if pmbp_profile:result[PMBP_ENV]=pmbp_profile
    return result

def _range(blob,va,size):
    try:e=ELFFile(io.BytesIO(blob))
    except ELFError as e:raise ValueError('Malformed pinned ELF') from e
    if e['e_machine']!='EM_AARCH64' or e.elfclass!=64 or not e.little_endian:raise ValueError('Expected AA64 ELF')
    for s in e.iter_segments():
        if s['p_type']=='PT_LOAD' and s['p_vaddr']<=va and va+size<=s['p_vaddr']+s['p_filesz']:
            offset=s['p_offset']+va-s['p_vaddr'];return blob[offset:offset+size]
    raise ValueError('Unmapped pinned ELF span')

def contract(root,body_root):
    roots={'sd':Path(root),'crypto':Path(root),'common':Path(body_root),'body':Path(body_root)}
    blobs={};files={}
    for tag,(name,sha) in ASSETS.items():
        b=(roots[tag]/name).read_bytes()
        if not sha or hashlib.sha256(b).hexdigest()!=sha:raise ValueError('Tail stock asset identity differs: '+tag)
        blobs[tag]=b;files[tag]={'name':name,'sha256':sha,'bytes':len(b)}
    pins=[]
    for tag,name,va in PINS:
        path='/tmp_updater/updater/bodyfs/bodylib/libupdaterbody.so' if tag=='body' else '/'+ASSETS[tag][0]
        pins.append(dict(name=name,path=path,sha256=files[tag]['sha256'],va=va,elf=blobs[tag][:64].hex(),code=_range(blobs[tag],va,64).hex()))
    e=ELFFile(io.BytesIO(blobs['sd']));sym=e.get_section_by_name('.dynsym');slots={}
    for r in e.get_section_by_name('.rela.plt').iter_relocations():
        n=sym.get_symbol(r['r_info_sym']).name
        if n in ('SHA1_Final','SHA256','RSA_verify'):slots[n]=r['r_offset']
    if slots!={'SHA1_Final':0x1e0f8,'SHA256':0x1e380,'RSA_verify':0x1e190}:raise ValueError('Stock crypto GOT differs')
    # Exact original BL-to-PLT chain, independent of exports or dlsym.
    imports=[]
    for name,call,plt,slot,raw in (('SHA1_Final',0xaba4,0x72a0,0x1e0f8,'bff1ff97'),
            ('SHA256',0xadec,0x77b0,0x1e380,'71f2ff97'),('RSA_verify',0xae08,0x73d0,0x1e190,'72f1ff97')):
        if _range(blobs['sd'],call,4).hex()!=raw:raise ValueError('Stock crypto callsite differs')
        imports.append(dict(symbol=name,call=call,plt=plt,slot=slot,call_code=raw,plt_code=_range(blobs['sd'],plt,16).hex(),version='OPENSSL_1_1_0'))
    return dict(schema='p1-stock-tail-source-v1',files=files,pins=pins,slots=slots,imports=imports,actual_verified=False)

def _once(source,old,new):
    if source.count(old)!=1:raise ValueError('Expected one source seam: '+old[:70])
    return source.replace(old,new)

def decorate(source, *, profile=None, source_contract=None, pmbp_profile=None):
    if profile is None:return source
    if profile!=PROFILE or not source_contract or source_contract.get('schema')!='p1-stock-tail-source-v1':raise ValueError('Tail source needs explicit stock contract')
    if len(source_contract.get('pins', []))!=len(PINS):raise ValueError('Incomplete tail pin set')
    rows=[]
    for p,(tag,name,va) in zip(source_contract['pins'],PINS):
        expected_path='/tmp_updater/updater/bodyfs/bodylib/libupdaterbody.so' if tag=='body' else '/'+ASSETS[tag][0]
        if (p.get('name')!=name or p.get('path')!=expected_path or p.get('va')!=va or p.get('sha256')!=ASSETS[tag][1] or
                len(bytes.fromhex(p.get('elf','')))!=64 or len(bytes.fromhex(p.get('code','')))!=64):
            raise ValueError('Tail pin identity/shape differs')
        numbers=lambda h:','.join(str(b) for b in bytes.fromhex(h))
        rows.append('{"%s","%s","%s",%d,{%s},{%s}}'%(p['name'],p['path'],p['sha256'],p['va'],numbers(p['elf']),numbers(p['code'])))
    imports=source_contract.get('imports',[])
    if len(imports)!=3:raise ValueError('Incomplete stock crypto import chain')
    ir=[]
    expected_imports=[('SHA1_Final',0xaba4,0x72a0,0x1e0f8,'bff1ff97'),('SHA256',0xadec,0x77b0,0x1e380,'71f2ff97'),('RSA_verify',0xae08,0x73d0,0x1e190,'72f1ff97')]
    for p,(symbol,call,plt,slot,code) in zip(imports,expected_imports):
        if (p.get('symbol'),p.get('call'),p.get('plt'),p.get('slot'),p.get('call_code'),p.get('version'))!=(symbol,call,plt,slot,code,'OPENSSL_1_1_0') or len(bytes.fromhex(p.get('plt_code','')))!=16:
            raise ValueError('Stock crypto import/caller guard differs')
        ir.append('{%d,%d,{%s},{%s}}'%(p['call'],p['plt'],numbers(p['call_code']),numbers(p['plt_code'])))
    helper=(HERE/'p1-tail-observer.inc').read_text().replace('/* __TAIL_PINS__ */',',\n'.join(rows)).replace('/* __TAIL_IMPORTS__ */',',\n'.join(ir))
    seam='struct PassivePin {const char *symbol,*path;'
    source=_once(source,seam,helper+'\n'+seam)
    start=source.index('int SHA1_Final(unsigned char *digest,void *context) {')
    end=source.index('/* void(this); C unwind tables',start)
    source=source[:start]+(HERE/'p1-tail-crypto.inc').read_text()+'\n'+source[end:]
    source=_once(source,'if(allocation_site)passive_borrow.live=0;','if(allocation_site)passive_borrow.live=0;\n    if(tail_site(0,caller,0xabc4))tail_binding("post-sha1");')
    io_source=(HERE/'p1-tail-io.inc').read_text()
    if pmbp_profile not in (None, PMBP_PROFILE):raise ValueError('Unknown explicit tail PMBP profile')
    # Every opt-in observer carries the bridge; only an audited E runtime choice enables it.
    source=(HERE/'p1-tail-pmbp.inc').read_text()+'\n'+source
    io_source=_once(io_source,'long (*fn)(int,const void *,unsigned long)=next("write");if(!fn)__builtin_trap();', '')
    io_source=_once(io_source,'long rc=fn(fd,data,bytes);', 'long rc=tail_pmbp_write(fd,data,bytes,caller);')
    io_source=_once(io_source,'int (*fn)(int)=next("close");if(!fn)__builtin_trap();', '')
    io_source=_once(io_source,'int rc=fn(fd),error=', 'int rc=tail_pmbp_close(fd,caller),error=')
    return source+'\n'+io_source+'\n'+(HERE/'p1-tail-native.inc').read_text()

def link_flags(profile=None):
    if profile is None:return []
    if profile!=PROFILE:raise ValueError('Unknown tail profile')
    return ['-I',str(HERE),'-Wl,--version-script='+str(HERE/'p1-tail-openssl.map')]

PMBP_PROFILE = 'virtual-p1-pmbp-block-slice-v1'

SOURCES = ('p1-tail-source.py','p1-tail-budget.h','p1-tail-observer.inc','p1-tail-crypto.inc',
           'p1-tail-io.inc','p1-tail-native.inc','p1-tail-pmbp.inc','p1-tail-openssl.map','tail_merge.py',
           'p1-rawlog-collector.sh','p1-rawlog-collector.py')
DIRECTORY = 'simulation/p1-tail'

def _record(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):raise ValueError('Tail input must be regular')
        with os.fdopen(fd,'rb',closefd=False) as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()
        after=os.fstat(fd)
        if any(getattr(before,k)!=getattr(after,k) for k in
               ('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')):
            raise ValueError('Tail input changed while hashing')
        return dict(path=str(Path(path).resolve()),bytes=before.st_size,sha256=sha)
    finally:os.close(fd)

def _encoded(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode('ascii')

def bootstrap_source(source, profile=None):
    if profile is None:return source
    if profile!=PROFILE:raise ValueError('Unknown tail profile')
    anchor='    [ -z "$path$bytes$hash$rest" ] && [ "$binding_count" -eq "$binding_expected" ] || return 125\n'
    source=_once(source,'#!/bin/sh\n','#!/bin/sh\nunset '+ENV+' '+PMBP_ENV+'\n')
    source=_once(source,'        echo "UPDATE_SD_RECEIVER_EXIT pid=$receiver_pid rc=$receiver_rc"\n',
        '        echo "UPDATE_SD_RECEIVER_WAIT pid=$receiver_pid rc=$receiver_rc"\n'
        '        echo "UPDATE_SD_RECEIVER_EXIT pid=$receiver_pid rc=$receiver_rc"\n'
        '        (\n'
        '            unset LD_PRELOAD\n'
        '            . /simulation/p1-tail/sources/p1-rawlog-collector.sh\n'
        '            p1_collect_rawlogs "$receiver_pid" "$receiver_rc"\n'
        '        )\n'
        '        collector_rc=$?\n'
        '        echo "P1_RAWLOG_COLLECT_RC pid=$receiver_pid rc=$collector_rc"\n')
    return _once(source,anchor,anchor+
        '    [ -f /simulation/p1-tail/env ] && [ ! -L /simulation/p1-tail/env ] || return 125\n'
        '    [ "$(/bin/busybox cat /simulation/p1-tail/env)" = '+ENV+'='+PROFILE+' ] || return 125\n'
        '    export '+ENV+'='+PROFILE+'\n'
        '    [ -f /simulation/p1-tail/pmbp-env ] && [ ! -L /simulation/p1-tail/pmbp-env ] || return 125\n'
        '    case "$(/bin/busybox cat /simulation/p1-tail/pmbp-env)" in\n'
        '        off) unset '+PMBP_ENV+' ;;\n'
        '        '+PMBP_ENV+'='+PMBP_PROFILE+') export '+PMBP_ENV+'='+PMBP_PROFILE+' ;;\n'
        '        *) return 125 ;;\n'
        '    esac\n')

def _broker(root, profile):
    if profile is None:return None
    if profile!=PMBP_PROFILE:raise ValueError('Unknown explicit tail PMBP profile')
    path=Path(root)/'simulation/pmbp-runtime/broker.so'
    row=_record(path)
    try:elf=ELFFile(io.BytesIO(path.read_bytes()))
    except ELFError as exc:raise ValueError('Malformed tail broker ELF') from exc
    if elf['e_type']!='ET_DYN' or elf['e_machine']!='EM_AARCH64' or elf.elfclass!=64 or not elf.little_endian:
        raise ValueError('Tail PMBP broker must be AA64')
    if elf.get_section_by_name('.dynsym') is None:raise ValueError('Tail broker has no dynamic exports')
    symbols={s.name for s in elf.get_section_by_name('.dynsym').iter_symbols()
             if s['st_shndx']!='SHN_UNDEF' and s['st_info']['bind'] in ('STB_GLOBAL','STB_WEAK') and s['st_info']['type']=='STT_FUNC' and s['st_other']['visibility']=='STV_DEFAULT'}
    if not {'pmbp_native_io','pmbp_open64_at','pmbp_write_at','pmbp_close_at'}<=symbols:
        raise ValueError('Explicit tail PMBP broker lacks required _at/native IO exports')
    if _record(path)!=row:raise ValueError('Tail broker changed during ELF inspection')
    return dict(bytes=row['bytes'],sha256=row['sha256'])

def prepare(root, output, *, profile=None, mode=None, install_profile=None,
            signature_schema=None, body_root=None, pmbp_profile=None):
    selection(profile,mode=mode,install_profile=install_profile,signature_schema=signature_schema)
    if profile is None:
        if body_root is not None:raise ValueError('tail_body_root requires explicit tail profile')
        return None
    root=Path(root);body_root=Path(body_root) if body_root is not None else root/'tmp_updater/updater/bodyfs'
    source_contract=contract(root,body_root)
    if pmbp_profile is not None:raise ValueError('Tail U preparation cannot select a future E broker')
    broker=None
    directory=root/DIRECTORY;directory.mkdir(parents=True,exist_ok=False)
    inputs=[];assets={}
    for tag,(name,sha) in ASSETS.items():
        original=(root if tag in ('sd','crypto') else body_root)/name
        row=_record(original)
        if row['sha256']!=sha:raise ValueError('Tail original input drift: '+tag)
        inputs.append(row)
        destination=directory/'original'/tag;destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(original.read_bytes())
        assets[destination.relative_to(root).as_posix()]={k:row[k] for k in ('bytes','sha256')}
    for name in SOURCES:
        row=_record(HERE/name);inputs.append(row)
        destination=directory/'sources'/name;destination.parent.mkdir(exist_ok=True)
        destination.write_bytes((HERE/name).read_bytes())
        assets[destination.relative_to(root).as_posix()]={k:row[k] for k in ('bytes','sha256')}
    for name,data in [('profile',(PROFILE+'\n').encode()),('env',(ENV+'='+PROFILE+'\n').encode()),
                      ('pmbp-env',_route_env(pmbp_profile)),
                      ('source-contract.json',_encoded(source_contract))]:
        path=directory/name;path.write_bytes(data)
        row=_record(path);assets[path.relative_to(root).as_posix()]={k:row[k] for k in ('bytes','sha256')}
    runtime_files=sorted(assets)+[DIRECTORY+'/build.json']
    if broker is not None:runtime_files.append('simulation/pmbp-runtime/broker.so')
    value=dict(schema='p1-stock-tail-build-v1',profile=profile,mode=mode,install_profile=install_profile,
        signature_schema=signature_schema,pmbp_profile=pmbp_profile,broker=broker,route_api=ROUTE_API,
        source_roots=dict(receiver=str(root.resolve()),body=str(body_root.resolve())),
        source_contract=source_contract,sources=inputs,assets=assets,runtime_files=runtime_files,
        actual_verified=False,rawlogs_complete=False,installation_verified=False)
    (directory/'build.json').write_bytes(_encoded(value))
    (root/'init').write_text(bootstrap_source((root/'init').read_text(encoding='ascii'),profile),encoding='ascii')
    return value

def recheck(root, value=None, *, rows=None, cpio_path=None, cpio_bindings=None):
    if value is None:return None
    root=Path(root)
    if value.get('schema')!='p1-stock-tail-build-v1':raise ValueError('Prepared tail contract required')
    selection(value.get('profile'),mode=value.get('mode'),install_profile=value.get('install_profile'),
              signature_schema=value.get('signature_schema'))
    if value.get('profile')!=PROFILE:raise ValueError('Tail prepared profile missing')
    if value.get('route_api')!=ROUTE_API:raise ValueError('Tail observer predates the runtime LR bridge; rebuild in a new root')
    if 'derived_from' in value:
        parent=value['derived_from']
        if Path(parent['root']).resolve()==root.resolve() or parent['tail'].get('pmbp_profile') is not None:
            raise ValueError('Tail derived contract must reference an independent unselected U root')
        recheck(parent['root'],parent['tail'])
        if parent['tail']['source_contract']!=value['source_contract'] or parent['tail']['sources']!=value['sources']:
            raise ValueError('Tail derived source provenance differs')
        if _pmbp_binding(root,value['pmbp_binding']['contract'])!=value['pmbp_binding']:
            raise ValueError('Tail PMBP assets/ownership/source binding drift')
    elif value.get('pmbp_profile') is not None:
        raise ValueError('PMBP selection requires a genuine E derived contract')
    body=Path(value['source_roots']['body'])
    if contract(root,body)!=value['source_contract']:raise ValueError('Tail stock source contract drift')
    if _broker(root,value['pmbp_profile'])!=value['broker']:raise ValueError('Tail broker identity drift')
    for row in value['sources']:
        if _record(row['path'])!=row:raise ValueError('Tail source input drift: '+row['path'])
    expected_assets={DIRECTORY+'/original/'+tag for tag in ASSETS}
    expected_assets|={DIRECTORY+'/sources/'+name for name in SOURCES}
    expected_assets|={DIRECTORY+'/'+name for name in ('profile','env','pmbp-env','source-contract.json')}
    if set(value['assets'])!=expected_assets:raise ValueError('Tail exact runtime asset membership differs')
    expected_originals=[]
    for tag,(name,sha) in ASSETS.items():
        source_root=Path(value['source_roots']['receiver']) if tag in ('sd','crypto') else body
        original=_record(source_root/name)
        if original['sha256']!=sha:raise ValueError('Tail original source provenance drift')
        expected_originals.append(original)
    expected_sources=[_record(HERE/n) for n in SOURCES]
    if value['sources']!=expected_originals+expected_sources:raise ValueError('Tail exact source set differs')
    expected_runtime=sorted(value['assets'])+[DIRECTORY+'/build.json']
    if value['broker'] is not None:expected_runtime+=['simulation/pmbp-runtime/'+n for n in PMBP_NAMES]
    if (root/DIRECTORY/'pmbp-env').read_bytes()!=_route_env(value['pmbp_profile']):
        raise ValueError('Tail PMBP runtime environment drift')
    if value['runtime_files']!=expected_runtime:raise ValueError('Tail runtime asset set differs')
    if (root/DIRECTORY/'build.json').read_bytes()!=_encoded(value):raise ValueError('Tail build receipt drift')
    if (root/DIRECTORY/'source-contract.json').read_bytes()!=_encoded(value['source_contract']):
        raise ValueError('Tail original source contract receipt drift')
    for name,expected in value['assets'].items():
        row=_record(root/name)
        if {k:row[k] for k in ('bytes','sha256')}!=expected:raise ValueError('Tail runtime asset drift: '+name)
    audit_args=(rows,cpio_path,cpio_bindings)
    if any(x is not None for x in audit_args):
        if any(x is None for x in audit_args):raise ValueError('Tail requires full audit rows and CPIO')
        for name in value['runtime_files']:
            row=_record(root/name);logical=dict(path=str(root/name),bytes=row['bytes'],sha256=row['sha256'])
            matches=[r for r in rows if r['path']==logical['path']]
            if len(matches)!=1 or any(matches[0].get(k)!=v for k,v in logical.items()):
                raise ValueError('Tail audit row missing or duplicate: '+name)
            expected=dict(mode=(root/name).lstat().st_mode,bytes=row['bytes'],sha256=row['sha256'])
            if cpio_bindings.get(name)!=expected:raise ValueError('Tail CPIO binding missing: '+name)
        runpy.run_path(str(HERE/'p1-sd-read-probe.py'))['cpio_readback'](cpio_path,cpio_bindings)
        if value.get('pmbp_binding'):
            _cpio_owners(cpio_path,set(value['runtime_files'])|{'simulation/pmbp-runtime','init','etc/ld.so.preload','simulation/p1-sd-observer.so'})
    return value

def extra_bindings(root,value=None):
    if value is None:return []
    recheck(root,value)
    return [dict(_record(Path(root)/name),path=str(Path(root)/name)) for name in value['runtime_files']]

def postrun(raw, *, receiver_pid=None, ledger=None, rawlogs_complete=False):
    if not isinstance(raw,bytes):raise ValueError('Tail postrun requires raw bytes')
    starts=re.findall(rb'^UPDATE_SD_RECEIVER_START pid=(\d+) original=/usr/bin/sdfileinput.elf\r?$',raw,re.M)
    result=dict(schema='p1-tail-postrun-v1',rawlogs_complete=rawlogs_complete,installation_verified=False,
                serial_sha256=hashlib.sha256(raw).hexdigest(),tail_merge=None)
    if len(starts)!=1 or (receiver_pid is not None and int(starts[0])!=receiver_pid):
        return dict(result,blocked='Exact unique original receiver PID is unavailable',receiver_pid=None)
    result['receiver_pid']=int(starts[0])
    if rawlogs_complete is not True or ledger is None:
        return dict(result,blocked='Full hostpostrun rawlog collection and independent ledger are not wired in this runner')
    result['tail_merge']=runpy.run_path(str(HERE/'tail_merge.py'))['merge'](raw,result['receiver_pid'],ledger)
    return result

def _route_env(profile):
    if profile not in (None,PMBP_PROFILE):raise ValueError('Unknown tail PMBP selection')
    return ((PMBP_ENV+'='+profile if profile else 'off')+'\n').encode('ascii')

def pmbp_api():
    return runpy.run_path(str(HERE/'pmbp-integration.py'))

def _pmbp_binding(root,value):
    if value.get('profile')!=PMBP_PROFILE:raise ValueError('Real selected PMBP contract required')
    root=Path(root)
    rows=pmbp_api()['preflight'](root,value)
    if set(rows)!={'simulation/pmbp-runtime/'+n for n in PMBP_NAMES}:
        raise ValueError('Tail requires exactly the six actual PMBP assets')
    directory=root/'simulation/pmbp-runtime';st=directory.lstat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode)!=0o700 or st.st_uid!=os.geteuid():
        raise ValueError('Tail broker root ownership/mode differs')
    assets={}
    for name in sorted(rows):
        path=root/name;st=path.lstat();row=_record(path)
        mode=0o700 if name=='simulation/pmbp-runtime/bootstrap' else 0o600
        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=os.geteuid() or stat.S_IMODE(st.st_mode)!=mode:
            raise ValueError('Tail broker asset ownership/mode differs: '+name)
        if rows[name]!=dict(bytes=row['bytes'],sha256=row['sha256'],mode=mode):
            raise ValueError('Tail broker asset row differs: '+name)
        assets[name]=dict(bytes=row['bytes'],sha256=row['sha256'],mode=st.st_mode,host_uid=st.st_uid,host_gid=st.st_gid,guest_uid=0,guest_gid=0)
    st=directory.lstat()
    return dict(contract=copy.deepcopy(value),assets=assets,
        root=dict(path='simulation/pmbp-runtime',mode=st.st_mode,host_uid=st.st_uid,host_gid=st.st_gid,guest_uid=0,guest_gid=0),
        source_bundle_sha256=assets['simulation/pmbp-runtime/source.bundle']['sha256'],
        manifest_sha256=assets['simulation/pmbp-runtime/manifest.bin']['sha256'])

def derive_pmbp(root,parent,*,source_root,pmbp_contract):
    """Only an E copy can select the already built broker; U's receipt is immutable."""
    root,source_root=Path(root),Path(source_root)
    if root.resolve()==source_root.resolve() or root.resolve().is_relative_to(source_root.resolve()) or source_root.resolve().is_relative_to(root.resolve()):
        raise ValueError('E must be an independent copied root')
    if parent.get('pmbp_profile') is not None or 'derived_from' in parent:
        raise ValueError('Tail parent must be the unselected U contract')
    recheck(source_root,parent);recheck(root,parent)
    binding=_pmbp_binding(root,pmbp_contract)
    broker=_broker(root,PMBP_PROFILE)
    value=copy.deepcopy(parent)
    value.update(pmbp_profile=PMBP_PROFILE,broker=broker,pmbp_binding=binding,
        derived_from=dict(root=str(source_root.resolve()),tail=copy.deepcopy(parent)))
    value['runtime_files']+=['simulation/pmbp-runtime/'+n for n in PMBP_NAMES]
    path=root/DIRECTORY/'pmbp-env';path.write_bytes(_route_env(PMBP_PROFILE))
    row=_record(path);value['assets'][DIRECTORY+'/pmbp-env']={k:row[k] for k in ('bytes','sha256')}
    (root/DIRECTORY/'build.json').write_bytes(_encoded(value))
    return recheck(root,value)

def launch_env(root,value=None,*,pmbp_contract=None,inherited=None,rows=None,cpio_path=None,cpio_bindings=None):
    """Consume final contracts immediately before Popen; no inherited route activation."""
    if value is None:return effective_env(None,inherited)
    if any(arg is None for arg in (rows,cpio_path,cpio_bindings)):
        raise ValueError('Tail launch requires final audit rows and actual CPIO')
    recheck(root,value,rows=rows,cpio_path=cpio_path,cpio_bindings=cpio_bindings)
    if value.get('pmbp_profile'):
        if pmbp_contract!=value['pmbp_binding']['contract']:
            raise ValueError('Execution and tail PMBP contracts differ')
        if (root/'etc/ld.so.preload').read_text(encoding='ascii')!=pmbp_contract['preload']:
            raise ValueError('Tail ordered preload contract differs')
    elif pmbp_contract is not None:raise ValueError('Execution broker has no selected tail contract')
    return effective_env(value['profile'],inherited,pmbp_profile=value['pmbp_profile'])

def _cpio_owners(path,names):
    """Narrow owner gate supplements the existing byte/mode/duplicate CPIO checker."""
    name_checked=runpy.run_path(str(HERE/'p1-sd-read-probe.py'))['cpio_name']
    seen=set()
    with gzip.open(path,'rb') as stream:
        def skip(n):
            while n:
                data=stream.read(min(n,1024*1024))
                if not data:raise ValueError('Truncated CPIO ownership payload')
                n-=len(data)
        while True:
            first=stream.read(1)
            while first==b'\0':first=stream.read(1)
            if not first:break
            header=first+stream.read(109)
            if len(header)!=110 or header[:6]!=b'070701':raise ValueError('Malformed ownership newc header')
            fields=[int(header[i:i+8],16) for i in range(6,110,8)]
            length=fields[11]
            if not 1<=length<=4096:raise ValueError('Invalid ownership path length')
            raw=stream.read(length)
            if len(raw)!=length or raw[-1:]!=b'\0':raise ValueError('Truncated ownership path')
            name=name_checked(raw)
            skip((-(110+length))%4)
            if name in names:
                if name in seen or fields[2:4]!=[0,0]:raise ValueError('CPIO owner/duplicate differs: '+name)
                if name=='simulation/pmbp-runtime' and fields[1]!=(stat.S_IFDIR|0o700):
                    raise ValueError('CPIO broker root mode differs')
                seen.add(name)
            skip(fields[6]);skip((-fields[6])%4)
    if seen!=names:raise ValueError('CPIO ownership membership incomplete')
