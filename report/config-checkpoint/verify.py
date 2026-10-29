#!/usr/bin/env python3
"""Verify finite original SID51 commit/restore artifacts, without guest writes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def require(value,message):
    if not value:raise ValueError(message)


def fnv(data):
    result=14695981039346656037
    for byte in data:result=((result^byte)*1099511628211)&((1<<64)-1)
    return f'{result:016x}'


def parse(image):
    require(len(image)==2390264,'Original whole-file size differs')
    banks=[];base=0;record=None
    for index in range(2):
        require(base+256<=len(image),'Truncated bank header')
        data=image[base:]
        require(data[12:16]==b'BK4\0','Original bank magic differs')
        sid_count,prop_count,offset,size,checksum=struct.unpack_from('<5I',data,16)
        require(sid_count==819 and prop_count==(37680 if index==0 else 33018),'Table count differs')
        require(offset==(231264 if index==0 else 203296) and size==(737717 if index==0 else 1216216),'Bank layout differs')
        end=offset+size;require(end<=len(data),'Bank data outside file')
        require((sum(data[:32])+sum(data[36:end]))&0xffffffff==checksum,'Bank checksum differs')
        if index==0:
            count,first=struct.unpack_from('<HI',data,256+0x51*6)
            require(count==95 and first<=prop_count-count,'SID51 record range differs')
            attr,pointer=struct.unpack_from('<HI',data,256+819*6+(first+0x4a)*6)
            position=pointer&0xffffff;length=pointer>>24
            require(attr==2 and length==128 and offset<=position<=end-128,'Boot record outside valid data')
            record=data[position:position+128]
        banks.append({'offset':base,'size':end,'writeComp_u32':struct.unpack_from('<I',data,8)[0],
                      'writeComp_low_byte':data[8],'checksum_valid':True})
        base+=(end+4095)&~4095 if index==0 else end
    require(base==len(image),'Unexpected file tail')
    return banks,record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-run',type=Path,required=True)
    parser.add_argument('--restored-run',type=Path,required=True)
    args=parser.parse_args()
    saved=args.saved_run;restored=args.restored_run
    try:
        require(saved.resolve()!=restored.resolve(),'Separate VM runs required')
        payload=(saved/'setting-checkpoint.bin').read_bytes();banks,record=parse(payload)
        file_sha=hashlib.sha256(payload).hexdigest();record_fnv=fnv(record)
        serial=(saved/'backup-checkpoint-serial.txt').read_bytes()
        require(re.findall(rb'^BACKUP_CHECKPOINT_EXPORTED physical=0x41e600000 bytes=2390264 fnv1a64=([0-9a-f]{16})\r?$',serial,re.M)==[fnv(payload).encode()],'Export digest differs')
        require(re.findall(rb'^BACKUP_CHECKPOINT_SYNC sid=0x51 rc=([0-9]+)\r?$',serial,re.M)==[b'0'],'Original sync did not succeed')
        require(re.findall(rb'^BACKUP_CHECKPOINT_DONE rc=([0-9]+) scope=public_AP_boot_record_only_not_all_settings\r?$',serial,re.M)==[b'0'],'Original full-file/API check did not finish')
        require(banks[0]['writeComp_low_byte']==1 and struct.unpack_from('<6I',record)==(0,2,1,1,0,1),'Original saved record differs')
        runtime=(restored/'console.log').read_bytes()
        require(re.findall(rb'^BACKUP_RESTORE_MATCH key=0x0051004a bytes=128 fnv64=([0-9a-f]{16}) scope=boot_record_only_not_all_settings\r?$',runtime,re.M)==[record_fnv.encode()],'Original restored getter differs')
        require(re.findall(rb'^BACKUP_RESTORE_FILE_BEGIN\r?\n[A-Za-z0-9-]+\(/setting/Backup.bin\)= ([0-9a-f]{64})\r?\nBACKUP_RESTORE_FILE_END\r?$',runtime,re.M)==[file_sha.encode()],'Pre-app file digest differs')
        proof=json.loads((restored/'backup-original-restore.json').read_text())
        require(proof['ok'] and proof['seed_power_on'] is False and proof['backup_sha256']==file_sha and proof['record_fnv64']==record_fnv,'Restore scope/identity differs')
        manifest=json.loads((restored/'overwrite-manifest.json').read_text())
        entries={entry['path']:entry for entry in manifest['entries']}
        require(all(entries[name]['new_sha256']==file_sha for name in ('seed-backup.bin','seed-setting/Backup.bin')),'Derived restored seeds differ')
        # No POWER_ON_SEED marker from the skipped helper may appear.
        require(not re.search(rb'^POWER_ON_SEED_',runtime,re.M),'Restore executed power seed')
        print(json.dumps({'ok':True,'scope':'original SID51 boot record save and pre-app restore only',
            'backup_sha256':file_sha,'record_fnv64':record_fnv,'banks':banks,
            'post_app_file_changed':proof['post_app_file_changed'],
            'configuration_persistence_verified':False,'all_settings_verified':False,
            'capture_verified':False},indent=2))
    except (OSError,ValueError,KeyError,TypeError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
