"""Finite original settings snapshot transport; no instance mutation."""
import hashlib
import json
from pathlib import Path
import re
import struct

SIZE=2390264
SCOPE=b'sid02cf_language_date_bank0_only'


def fnv(data):
    value=14695981039346656037
    for byte in data:value=((value^byte)*1099511628211)&((1<<64)-1)
    return f'{value:016x}'


def inspect_backup(data):
    if len(data)!=SIZE:raise ValueError('Backup whole-file length differs')
    base=0;banks=[];settings=None
    for index in range(2):
        if base+256>len(data):raise ValueError('Truncated bank')
        view=memoryview(data)[base:]
        counts,properties,offset,length,checksum=struct.unpack_from('<5I',view,16)
        if (bytes(view[12:16])!=b'BK4\0' or counts!=819
                or properties!=(37680 if index==0 else 33018)
                or offset!=(231264 if index==0 else 203296)
                or length!=(737717 if index==0 else 1216216)
                or offset+length>len(view)):
            raise ValueError('Pinned public bank layout differs')
        end=offset+length
        if (sum(view[:32])+sum(view[36:end]))&0xffffffff!=checksum:
            raise ValueError('Original bank checksum differs')
        for sid in range(819):
            count,first=struct.unpack_from('<HI',view,256+sid*6)
            if first>properties or count>properties-first:raise ValueError('Invalid SID property range')
        if index==0:
            count,first=struct.unpack_from('<HI',view,256+0x2cf*6)
            if (count,first)!=(6873,30536):raise ValueError('Known settings SID layout differs')
            values=[]
            for key in (0x401,0x403):
                attr,pointer=struct.unpack_from('<HI',view,256+819*6+(first+key)*6)
                position=pointer&0xffffff
                if attr!=64 or pointer>>24!=1 or not offset<=position<end:
                    raise ValueError('Known setting outside bank data')
                values.append(view[position])
            if values[1]>3:raise ValueError('Date-format value outside original domain')
            settings={'language':values[0],'date_format':values[1]}
        banks.append({'checksum_valid':True,'offset':base,'size':end,
                      'writeComp_u32':struct.unpack_from('<I',view,8)[0]})
        base+=(end+4095)&~4095 if index==0 else end
    if base!=len(data):raise ValueError('Unexpected data after original banks')
    return {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'banks':banks,**settings}


def _one(pattern,raw):
    values=re.findall(pattern,raw,re.M)
    if len(values)!=1:raise ValueError('Missing or ambiguous original settings evidence')
    return values[0]


def snapshot(serial,qmp,run):
    """One serialized helper/RAM/readback transaction before the SD exporter.

    Caller retains VM ownership on failure; this function never stops a process,
    changes a host generation or claims all subsystems have been committed.
    """
    run=Path(run)
    target=run/'SETTING'
    target.mkdir(mode=0o700,exist_ok=True)
    if target.is_symlink() or target.resolve().parent!=run.resolve():
        raise ValueError('Invalid owned settings output directory')
    result={'ok':False,'scope':'whole Backup snapshot, language/date API-file consistency only',
            'all_settings_verified':False,'configuration_persistence_verified':False}
    raw=b''
    try:
        command='/simulation/user-settings-checkpoint snapshot; rc=$?; echo SETTINGS_SNAPSHOT_RC=$rc; true'
        raw=serial(command,timeout=90)
        (target/'serial.txt').write_bytes(raw)
        if _one(rb'^SETTINGS_SNAPSHOT_RC=([0-9]+)\r?$',raw)!=b'0':
            raise RuntimeError('Original settings snapshot helper failed')
        if _one(rb'^USER_SETTINGS_DONE rc=([0-9]+) scope='+SCOPE+rb'\r?$',raw)!=b'0':
            raise RuntimeError('Settings snapshot did not complete')
        language,date=_one(rb'^USER_SETTINGS_SNAPSHOT_MATCH lang=([0-9]+) date=([0-3]) scope='+SCOPE+rb'\r?$',raw)
        guest_fnv=_one(rb'^USER_SETTINGS_EXPORTED physical=0x41e600000 bytes=2390264 fnv1a64=([0-9a-f]{16}) scope='+SCOPE+rb'\r?$',raw).decode()
        qmp('pmemsave',{'val':0x41e600000,'size':SIZE,'filename':'/out/SETTING/Backup.bin'})
        image=target/'Backup.bin'
        if image.is_symlink() or not image.is_file() or image.stat().st_size!=SIZE:
            raise ValueError('Missing original full-file capture')
        data=image.read_bytes()
        if fnv(data)!=guest_fnv:raise ValueError('Guest RAM/file transport digest differs')
        inspected=inspect_backup(data)
        if (inspected['language'],inspected['date_format'])!=(int(language),int(date)):
            raise ValueError('Original file differs from stable original API values')
        # A separately obtained guest SHA is required by the host generation store.
        sha_raw=serial('/usr/bin/openssl dgst -sha256 /setting/Backup.bin',timeout=30)
        (target/'guest-sha.txt').write_bytes(sha_raw)
        guest_sha=_one(rb'^[A-Za-z0-9-]+\(/setting/Backup.bin\)= ([0-9a-f]{64})\r?$',sha_raw).decode()
        if guest_sha!=inspected['sha256']:
            raise ValueError('Guest file changed or independent guest SHA differs')
        result.update(inspected,ok=True,guest_sha256=guest_sha,guest_fnv64=guest_fnv,
                      file='SETTING/Backup.bin',language_date_consistency_verified=True)
    except (OSError,ValueError,RuntimeError) as error:
        result['error']=f'{type(error).__name__}: {error}'
        raise
    finally:
        (target/'checkpoint.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
