#!/usr/bin/env python3
"""Prepare/check a rollback-bound official P1 installation; never starts a VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
PROFILE = 'original-p1-virtual-install-v1'
SCHEMA = 'a7c2-p1-virtual-install-clone-v2'
NODES = ('pnflasha',) + tuple('cnflasha' + str(n) for n in (1,2,3,4,5,6,7,8,10,11,12,13,15,18,22,23,30)) + ('nflashaB0','nflashaB1')


WRITE_GUARD = r'''
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#if defined(__aarch64__)
/* Original glibc 2.25 exports __fxstat at +bb5c0; only version zero reaches syscall 80. */
extern int __fxstat(int,int,struct stat *);
#define target_stat(fd,st) __fxstat(0,fd,st)
#else
#define target_stat(fd,st) fstat(fd,st)
#endif
static const char *names[] = {"pnflasha","cnflasha1","cnflasha2","cnflasha3","cnflasha4","cnflasha5","cnflasha6","cnflasha7","cnflasha8","cnflasha10","cnflasha11","cnflasha12","cnflasha13","cnflasha15","cnflasha18","cnflasha22","cnflasha23","cnflasha30","nflashaB0","nflashaB1"};
static int run(int argc,char **argv) {
    const char *a=getenv("A7C2_FILE_MEDIA_TEST"),*b=getenv("A7C2_P1_FILE_MEDIA_PROFILE");
    if(argc!=21 || !a || !b || strcmp(a,"1") || strcmp(b,"original-sd-v1"))return 125;
    FILE *devices=fopen("/proc/devices","r");unsigned project=0,m;char line[256],kind[120],extra;
    if(!devices)return 125;
    int block=0,headers=0;
    while(fgets(line,sizeof line,devices)) {
        if(!strcmp(line,"Block devices:\n")){if(headers++){fclose(devices);return 125;}block=1;continue;}
        if(!strcmp(line,"Character devices:\n")){block=0;continue;}
        int fields=block?sscanf(line,"%u %119s %c",&m,kind,&extra):0;
        /* The original .186 register_blkdev name is stored in a 16-byte field. */
        if(fields>=2 && !strcmp(kind,"sony-persistent")) {
            if(fields!=2 || project || !m){fclose(devices);return 125;}project=m;
        }
    }
    fclose(devices);if(!project)return 125;
    FILE *modules=fopen("/proc/modules","r");int live=0;char state[32];
    if(!modules)return 125;
    while(fgets(line,sizeof line,modules)) {
        int fields=sscanf(line,"%119s %*u %*u %*s %31s",kind,state);
        if(fields>=1 && !strcmp(kind,"sony_persistent_flash")) {
            if(fields!=2 || live++ || strcmp(state,"Live")){fclose(modules);return 125;}
        }
    }
    fclose(modules);if(live!=1)return 125;
    unsigned seen=0;int failed=0;
    for(int i=1;i<argc;i++) {
        unsigned n;char path[180],expected[100];
        for(n=0;n<20;n++){snprintf(expected,sizeof expected,"/dev/%s",names[n]);if(!strcmp(argv[i],expected))break;}
        if(n==20 || (seen&(1u<<n)))return 125;seen|=1u<<n;
        snprintf(path,sizeof path,"/sys/block/%s/dev",names[n]);FILE *f=fopen(path,"r");unsigned ma=0,mi=0;
        int identity=f && fscanf(f,"%u:%u",&ma,&mi)==2 && ma==project;if(f)fclose(f);
        int fd=open(argv[i],O_RDONLY|O_NOFOLLOW),ro=1;struct stat st;
        identity=identity && fd>=0 && !target_stat(fd,&st) && S_ISBLK(st.st_mode) && major(st.st_rdev)==ma && minor(st.st_rdev)==mi;
        int rc=fd<0?-1:ioctl(fd,0x125eUL,&ro);
        printf("UPDATE_INSTALL_TARGET node=%s get_rc=%d readonly=%d project_backend=%d\n",argv[i],rc,ro,identity);
        if(fd>=0)close(fd);if(rc || ro!=0 || !identity)failed=1;
    }
    return failed || seen!=0xfffff ? 125:0;
}
'''


def api():
    return runpy.run_path(str(HERE / 'update-boot.py'))


def admit(profile, *, mode, read_only, allow_updater_writes, media, sd, module):
    u = api()
    if (profile != PROFILE or mode != 'official' or read_only is not False
            or allow_updater_writes is not True or not media or sd is None):
        raise ValueError('Install profile requires explicit official/media/SD/read_only=False/allow_updater_writes=True')
    module_admission(module)


def module_admission(module):
    """Shared fixed-driver write boundary; callers enforce their own profile/mode."""
    u = api()
    if not isinstance(module,dict) or not isinstance(module.get('driver'),dict):
        raise ValueError('Install profile requires exact module/driver contract')
    identity = (module.get('module_sha256'), module['driver'].get('sha256'))
    if identity == (u['TRIM_MODULE_SHA'], u['TRIM_DRIVER_SHA']):
        if (module.get('storage_profile') != u['TRIM_STORAGE_PROFILE']
                or not module.get('receipts') or module['receipts'][0].get('sha256') != u['TRIM_RECEIPT_SHA']
                or module.get('source_set_sha256') != u['TRIM_SOURCE_SET_SHA']):
            raise ValueError('Install trim module requires exact source/receipt/storage contract')
        replay = u['module_contract'](u['record'](module['storage_module']['path']),
            u['record'](module['storage_kernel']['path']), module['receipts'][0]['path'])
        if replay != module:
            raise ValueError('Install trim module/source/ABI contract changed')
    elif identity != (u['CURRENT_MODULE_SHA'], u['CURRENT_DRIVER_SHA']) or module.get('storage_profile') is not None:
        raise ValueError('Install profile requires exact fixed original-p1 module/driver pair')
    if (module.get('protocol') != u['PROTOCOL'] or module.get('build_bound') is not True
            or module.get('large_io_fix_bound') is not True or module.get('updater_write_eligible') is not True
            or module.get('kernel_sha256') != u['KERNEL_SHA']):
        raise ValueError('Install profile requires exact fixed original-p1 module/driver/kernel/protocol')


def ranges(fd, geometry):
    """Partition/boot hashes and every other byte, including SDM2 and gaps."""
    u = api(); d = u['DISK']; result = []; end = 0
    for row in sorted(geometry['slices'], key=lambda r:r['offset']):
        if row['offset'] < end or row['bytes'] <= 0:
            raise ValueError('Invalid install geometry range')
        if row['offset'] > end:
            result.append(dict(id='gap-' + str(end), offset=end, bytes=row['offset']-end))
        result.append({k:row[k] for k in ('id','offset','bytes')}); end=row['offset']+row['bytes']
    total=os.fstat(fd).st_size
    if end > total: raise ValueError('Install geometry exceeds disk')
    if end < total: result.append(dict(id='tail',offset=end,bytes=total-end))
    for row in result: row['sha256']=d['hashed'](fd,row['offset'],row['bytes'])
    return result


def candidate_from_media_instance_v2(source_instance, instance, output, *, expected_source_sha256):
    """Clone the caller's current, already mode5 media instance; no factory reseed."""
    u=api(); d=u['DISK']; execution=runpy.run_path(str(HERE/'p1-update-execution.py'))
    source,instance,output=map(u['absolute'],(source_instance,instance,output))
    if not isinstance(expected_source_sha256,str) or not re.fullmatch('[0-9a-f]{64}',expected_source_sha256):
        raise ValueError('Explicit current source SHA required')
    if source==instance or source.is_relative_to(instance) or instance.is_relative_to(source):
        raise ValueError('Install clone must be independent of baseline')
    output=execution['PERSIST']['fresh_output'](output,source,instance)
    with d['lease'](source) as leased:
        if leased['state'].get('state')!='stopped' or d['hashed'](leased['fd'])!=expected_source_sha256:
            raise ValueError('Current stopped source baseline SHA differs')
        baseline=u['record'](source/'camera.emmc')
    before=execution['clone_instance'](source,output/'before')
    execution['clone_instance'](before,instance)
    with d['lease'](instance) as leased:
        if d['hashed'](leased['fd'])!=expected_source_sha256:
            raise ValueError('Pre-upgrade clone readback differs')
        extent=next(r for r in leased['geometry']['slices'] if r['id']=='nflasha2')
        p2=u['copy_range'](leased['fd'],extent['offset'],extent['bytes'],output/'p2-before.img')
        fat,inventory,tail=u['fat_view'](Path(p2['path']),output,'p2-before');fat.close()
        media=runpy.run_path(str(HERE/'p1-media-init-probe.py'))
        backup=inventory['entries'].get('/Backup.bin',{})
        if (not u['setting_state'](inventory)['sd_dispatch_eligible'] or backup.get('sha256')!=media['BACKUP_SHA']
                or backup.get('size')!=media['BACKUP_BYTES']):
            raise ValueError('Source must already select mode5 with exact trusted Backup; no reseed')
        receipt=dict(schema=SCHEMA,profile=PROFILE,status='prepared',source_instance=str(source),source=baseline,
            expected_source_sha256=expected_source_sha256,before_instance=str(before),
            before=u['record'](before/'camera.emmc'),instance=str(instance),clone=u['record'](instance/'camera.emmc'),
            geometry=u['record'](instance/'geometry.json'),ranges=ranges(leased['fd'],leased['geometry']),
            p2_before=p2,p2_tree=inventory,p2_tail=tail,source_lease_held=True,readback_verified=True,
            source_reseeded=False,physical_devices_used=False,original_sources_opened_writable=False,
            installation_verified=False,read_verified=False,guest_started=False)
        if receipt['before']['sha256']!=expected_source_sha256 or u['record'](source/'camera.emmc')!=baseline:
            raise ValueError('Baseline/before changed during candidate preparation')
        d['save'](output/'clone-receipt.json',receipt)
    return receipt


def clone_contract(instance, receipt_path, receipt_sha256):
    u=api();d=u['DISK']; value,row=u['checked_json'](receipt_path)
    if (row['sha256']!=receipt_sha256 or value.get('schema')!=SCHEMA or value.get('profile')!=PROFILE
            or value.get('status')!='prepared' or value.get('source_reseeded') is not False
            or value.get('physical_devices_used') is not False or value.get('readback_verified') is not True):
        raise ValueError('Install clone receipt schema/profile/hash/policy differs')
    leased=instance if isinstance(instance,dict) else None
    instance=u['absolute'](instance['path'] if leased else instance)
    paths=[u['absolute'](value[k]) for k in ('source_instance','before_instance','instance')]
    if paths[2]!=instance or len(set(paths))!=3 or any(a.is_relative_to(b) for a in paths for b in paths if a!=b):
        raise ValueError('Install clone/before/baseline must be independent instances')
    records=[]
    for path,key in zip(paths,('source','before','clone')):
        actual=u['record'](path/'camera.emmc'); expected=value[key]
        if any(actual[k]!=expected[k] for k in ('device','inode','bytes','sha256')):
            raise ValueError('Install '+key+' identity/hash differs')
        records.append(actual)
    if len({(r['device'],r['inode']) for r in records})!=3:
        raise ValueError('Install clone aliases baseline or before')
    if any(r['sha256']!=value['expected_source_sha256'] for r in records):
        raise ValueError('Install pre-candidate baseline hash differs')
    geometry=u['record'](instance/'geometry.json')
    if any(geometry[k]!=value['geometry'][k] for k in ('bytes','sha256')):
        raise ValueError('Install geometry differs')
    p2=u['record'](value['p2_before']['path'])
    if any(p2[k]!=value['p2_before'][k] for k in ('bytes','sha256')):
        raise ValueError('Install old p2 evidence differs')
    if leased is not None:
        if (d['stamp'](leased['fd'])[:3]!=(records[2]['device'],records[2]['inode'],records[2]['bytes'])
                or d['hashed'](leased['fd'])!=records[2]['sha256']):
            raise ValueError('Install caller lease differs from clone')
    # The execution runner checks the same FD again immediately before Popen.
    return dict(receipt=row,value=value,profile=PROFILE,exclusive_clone_required=True,
                rollback='new instance from before after owner exit and exclusive lease; never overwrite another run')


def preflight(update, root, read_only, media, profile, *, allow_updater_writes):
    u=api();sd=runpy.run_path(str(HERE/'p1-sd-read-probe.py'))
    admit(profile,mode=update['mode'],read_only=read_only,allow_updater_writes=allow_updater_writes,
          media=media,sd=update.get('sd'),module=update['module_contract'])
    value=sd['preflight'](update,root,read_only,media,profile)
    binding=update.get('virtual_install') or {}
    actual=clone_contract(update['instance']['path'],binding['receipt']['path'],binding['receipt']['sha256'])
    if actual!=binding: raise ValueError('Install clone authorization differs')
    if len(update.get('original_module_allowlist',[]))!=12:
        raise ValueError('Install profile requires twelve exact original modules')
    if (Path(root)/'simulation/install-authorization').read_text(encoding='ascii')!=authorization(actual):
        raise ValueError('Install host receipt authorization differs')
    return value


def authorization(binding):
    return PROFILE+' '+binding['receipt']['sha256']+' '+binding['value']['clone']['sha256']+'\n'


def restore(receipt_path, receipt_sha256, output):
    """Only a fresh restore instance after the installation owner's lease is free."""
    u=api();d=u['DISK'];value,row=u['checked_json'](receipt_path)
    if row['sha256']!=receipt_sha256 or value.get('schema')!=SCHEMA or value.get('profile')!=PROFILE:
        raise ValueError('Unknown rollback receipt')
    execution=runpy.run_path(str(HERE/'p1-update-execution.py'))
    with d['lease'](value['instance']) as current:
        if current['state'].get('state')!='stopped': raise ValueError('Install owner not stopped')
        before=u['record'](Path(value['before_instance'])/'camera.emmc')
        if any(before[k]!=value['before'][k] for k in ('bytes','sha256','device','inode')):
            raise ValueError('Rollback before identity differs')
        restored=execution['clone_instance'](value['before_instance'],output)
        if u['record'](restored/'camera.emmc')['sha256']!=value['expected_source_sha256']:
            raise ValueError('Rollback full readback differs')
    return restored


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-instance',type=Path,required=True)
    parser.add_argument('--instance',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--expected-source-sha256',required=True)
    args=parser.parse_args();os.umask(0o077)
    value=candidate_from_media_instance_v2(args.source_instance,args.instance,args.output,
        expected_source_sha256=args.expected_source_sha256)
    print(json.dumps(dict(status=value['status'],profile=PROFILE,guest_started=False)))


if __name__=='__main__': main()
