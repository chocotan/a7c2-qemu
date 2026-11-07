#!/usr/bin/env python3
"""Opt-in, source-bound original P1 media init; local virtual disk, read-only guest.

The receipt admits an experiment, not successful initialization or physical media.
Default seven-resource builds do not call this module.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
PROFILE = 'original-p1-media-readonly-v1'
BACKUP_SHA = 'b863f8b61d1a979b964419a99c9a0f27169958f8f5cbb204b7a4eee3b127cdff'
BACKUP_BYTES = 2390264
BACKUP_DSO_SHA = 'ecef93660cbc660dcca19d57a31064f1a872417a2702660776f13af33ddf3d63'
QEMU_RECEIPT_SHA = '141b98a0b82a53730fc92e9970133f8f9ad49d8c85e3ac3755609caf32d223fa'
CONTEXT_SHA = 'f67dd54845d93a65a4285c8ba77d56b588dd2dab7e1ed76a91c4d54b5945ec6d'
CONTEXT_SERIAL_SHA = '71d37c05bc2ebff7403353bc0518e1c6a85d324a353eaecd51a48d71c3a1084a'
EXTRA = {'stream2': '04826829fd83f7c41e63dbd59d6808bc276f36673bc1308f3ef16b4c96238666',
    'mcmn_drv': '84fd64a01715b88cfc08ea0e6c43bc9c73dd30703d481fcae2f42168344600f8',
    'mmc_drv': 'eb5ae29db913c2faad941df6b0439b2790781daa9f294157942b5794e6ceda4f',
    'nvme-core': '05e22b01cf52d1872e087b877f4ece0523373bd487ae205de6ab6b9077c17dfa',
    'nvme': '0f37469de0a80d1b038d0f8e0c9d3deefce4b9587694b1af1743dbe275415b1b'}
IDS = (0xd900fa, 0xd90102, 0xd9010a, 0xd900b1, 0xd900ab, 0xd900ac)
# All windows retain section bytes AND relocations, including each literal pool.
RANGES = ((0xc70, 0xf0), (0x460, 0xe0), (0x2208, 0xd8), (0x9118, 0x40), (0x9374, 0xf0),
          (0x9834, 0xac), (0x9af0, 0xd8), (0xb2b0, 0x38), (0x11198, 0x178),
          (0x117b0, 0x130), (0x12a20, 0xb8), (0x13158, 0x70))

QUERY_SOURCE = r'''
extern int printf(const char *, ...), getpid(void), getuid(void), geteuid(void), getgid(void), getegid(void);
extern int Backup_get_datasize(unsigned), Backup_read(unsigned, void *), u_uipc_init(void);
extern int memcmp(const void *, const void *, unsigned long);
static int run(int argc, char **argv) {
    (void)argv;
    if (argc != 1) return 2;
    printf("UPDATE_MEDIA_QUERY pid=%d uid=%d euid=%d gid=%d egid=%d readonly=1\n",
           getpid(),getuid(),geteuid(),getgid(),getegid());
    if (getuid() || geteuid() || getgid() || getegid()) return 3;
    int uipc_rc=u_uipc_init();
    printf("UPDATE_MEDIA_QUERY_UIPC original_rc=%d\n",uipc_rc);
    if (uipc_rc) return 4;
    static const unsigned ids[]={0xd900fa,0xd90102,0xd9010a,0xd900b1,0xd900ab,0xd900ac};
    int failed=0;
    for (unsigned i=0;i<6;i++) {
        unsigned char data[8]={0xa5,0xa5,0xa5,0xa5,0xa5,0xa5,0xa5,0xa5};
        int size=Backup_get_datasize(ids[i]);
        int rc=size==1 ? Backup_read(ids[i],data) : -999;
        printf("UPDATE_MEDIA_BACKUP id=%06x size=%d rc=%d value=%02x\n",ids[i],size,rc,data[0]);
        if (size!=1 || rc!=size || data[0]) failed=1;
    }
    unsigned char path[25]={0};
    int size=Backup_get_datasize(0x4b0002);
    int rc=size==24 ? Backup_read(0x4b0002,path) : -999;
    printf("UPDATE_MEDIA_PATH id=4b0002 size=%d rc=%d hex=",size,rc);
    for (unsigned i=0;i<24;i++) printf("%02x",path[i]);
    printf("\n");
    static const char expected[24]="/nondev/rm2";
    if (size!=24 || rc!=size || memcmp(path,expected,24)) failed=1;
    printf("UPDATE_MEDIA_QUERY_RESULT rc=%d\n",failed);
    return failed;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
'''


def api():
    return runpy.run_path(str(HERE / 'p1-mmc-bootstrap.py'))


def evidence(root, kernel, qemu_receipt):
    m = api(); u = m['UPDATE']; root = Path(root)
    qrow = m['exact'](qemu_receipt, QEMU_RECEIPT_SHA)
    q = json.loads(Path(qemu_receipt).read_text())
    if q['status'] != 'compiled' or not q['production_unchanged']:
        raise ValueError('MMC provider build differs')
    for row in [q['qemu'], q['board'], *q['model_inputs']]:
        m['exact'](row['path'], row['sha256'])
    m['exact'](kernel, m['PROBE']['KERNEL_SHA'])
    context = PROJECT / 'analysis/scratch/p1-original-update-resources-20261106/guest-v3'
    previous = m['exact'](context / 'result.json', CONTEXT_SHA)
    serial = m['exact'](context / 'serial.log', CONTEXT_SERIAL_SHA)
    old = json.loads((context / 'result.json').read_text())
    if (not all(old[k] for k in ('verified','normal_exit_verified','disk_unchanged','original_resource_chain_loaded'))
            or old['native_uipc_getstatus_returncodes'] != [0] or old['power_ic_returncodes'] != [7]):
        raise ValueError('Reviewed seven-resource actual context differs')
    modules = []
    for name, digest in EXTRA.items():
        row = m['exact'](root / ('usr/kmod/' + name + '.ko'), digest)
        m['ABI']['require_abi'](m['ABI']['module_info'](row['path']))
        modules.append(row)
    dso = m['exact'](root / 'usr/lib/libbackup.so', BACKUP_DSO_SHA)
    script = m['exact'](root / 'usr/bin/execute_ufp.sh', '08edf12a2b4b33a285866e88b94ef1d973bf50cec373dea6796d0ad52d5e6b9b')
    source = u['record'](HERE / 'p1-media-init-probe.py')
    pins = [m['window'](root / 'usr/kmod/mcmn_drv.ko', '.text', offset, size) for offset,size in RANGES]
    # DSO ABI: W0=id; read consumes X1=buffer and returns a signed result in W0.
    dsopins = [m['window'](dso['path'], '.text', offset-0x1740, size)
               for offset,size in ((0x1e4c,0x3c),(0x1f04,0x40))]
    return dict(schema='a7c2.p1-media-source.v1', profile=PROFILE, status='source-verified',
        qemu_receipt=qrow, qemu=q['qemu'], provider_inputs=[q['board'], *q['model_inputs']],
        kernel=u['record'](kernel), previous_context=previous, previous_serial=serial,
        modules=modules, backup_dso=dso, original_script=script, helper_source=source,
        pins=pins, backup_api_pins=dsopins, backup=dict(bytes=BACKUP_BYTES, sha256=BACKUP_SHA, ids=list(IDS), expected=[0]*6,
            path_id=0x4b0002, path_hex=(b'/nondev/rm2'+b'\0'*13).hex(),
            active_bank='must be read through original API; no bank guess'),
        pcie_branch='cfg+30/+31/+32 from D900FA/D90102/D9010A; zero readback bypasses (2,3) branch',
        prepower_branch='core helper +460 copies cfg+0b/+0c/+0d to power+3/+4/+5; zero selects no channel',
        experiment_admitted=True, initialization_verified=False, physical_card_verified=False,
        bodydata_installation_verified=False)


def source(root, kernel, qemu_receipt, output):
    output = Path(output); output.mkdir(mode=0o700)
    try:
        result = evidence(root, kernel, qemu_receipt)
        (output / 'source-receipt.json').write_text(json.dumps(result, indent=2)+'\n')
        subprocess.run(['aarch64-linux-gnu-objdump','-dr',str(Path(root)/'usr/kmod/mcmn_drv.ko')],
            check=True, stdout=(output/'mcmn.disasm.txt').open('xb'), stderr=subprocess.PIPE, timeout=30)
        return result
    except BaseException as error:
        (output/'failure.json').write_text(json.dumps(dict(error=str(error),guest_started=False))+'\n')
        raise


def check(root, kernel, receipt):
    m = api(); value, row = m['UPDATE']['checked_json'](receipt)
    actual = evidence(root, kernel['path'], value['qemu_receipt']['path'])
    # Copied root paths/inodes differ; all semantic metadata and byte identities stay bound.
    def portable(v):
        if isinstance(v, dict):
            return {k:portable(x) for k,x in v.items() if k not in ('path','device','inode')}
        if isinstance(v, list): return [portable(x) for x in v]
        return v
    if portable(value) != portable(actual):
        raise ValueError('Media source receipt differs from exact source/provider/context')
    return value, row


def query_evidence(raw):
    text = raw.decode('utf-8', errors='replace').replace('\r','')
    rows = re.findall(r'^UPDATE_MEDIA_BACKUP id=([0-9a-f]{6}) size=(-?\d+) rc=(-?\d+) value=([0-9a-f]{2})$',text,re.M)
    expected = [(f'{i:06x}','1','1','00') for i in IDS]
    path = re.findall(r'^UPDATE_MEDIA_PATH id=4b0002 size=(-?\d+) rc=(-?\d+) hex=([0-9a-f]{48})$',text,re.M)
    credentials = re.findall(r'^UPDATE_MEDIA_QUERY pid=(\d+) uid=(\d+) euid=(\d+) gid=(\d+) egid=(\d+) readonly=1$',text,re.M)
    verified = (rows == expected and path == [('24','24',(b'/nondev/rm2'+b'\0'*13).hex())]
        and len(credentials)==1 and credentials[0][1:]==('0','0','0','0')
        and text.count('UPDATE_MEDIA_QUERY_UIPC original_rc=0\n')==1
        and text.count('UPDATE_MEDIA_QUERY_RESULT rc=0\n')==1
        and text.count('UPDATE_MEDIA_GUARD rc=0\n')==1)
    return dict(rows=rows, path=path, credentials=credentials, original_readback_verified=verified,
                bank_guessed=False, values_overridden=False)


def mode5_candidate(source_instance, instance, output, runtime):
    """Only add mode/mode5 on a fresh local clone; preserve every other FAT entry."""
    execution = runpy.run_path(str(HERE / 'p1-update-execution.py'))
    u, disk = execution['UPDATE'], execution['DISK']
    instance = execution['clone_instance'](source_instance, instance)
    output = Path(output); output.mkdir(mode=0o700)
    with disk['lease'](instance) as leased:
        part = next(r for r in leased['geometry']['slices'] if r['id']=='nflasha2')
        before = disk['hashed'](leased['fd'])
        p2 = output / 'p2-before.img'
        u['copy_range'](leased['fd'],part['offset'],part['bytes'],p2)
        fat, inv, tail = u['fat_view'](p2,output,'before')
        fat.close()
        state = u['setting_state'](inv)
        if state['flags'] != dict(mode=False,mode1=False,mode2=False,mode3=False,mode5=False,
                                  mode6=False,mode7=False,comp=True,uincomp=False):
            raise ValueError('Candidate requires the reviewed stock mode1 state')
        backup = inv['entries'].get('/Backup.bin',{})
        if backup.get('sha256')!=BACKUP_SHA or backup.get('size')!=BACKUP_BYTES:
            raise ValueError('Candidate original Backup identity differs')
        fs = output / 'before-filesystem.fat'
        flag = output / 'mode-flag';flag.write_bytes(b'1\n')
        env=dict(PATH=os.defpath,LC_ALL='C',MTOOLSRC='/dev/null',MTOOLS_SKIP_CHECK='1')
        for name in ('mode','mode5'):
            u['command']([u['tools'](Path(runtime)) / 'mcopy','-i',fs,flag,'::/updater/'+name],output,'add-'+name,env=env)
        fat, after, _ = u['fat_view'](fs,output,'after')
        fat.close()
        expected = dict(inv['entries'])
        for name in ('/updater/mode','/updater/mode5'):
            row=after['entries'].get(name,{})
            if row.get('kind')!='file' or row.get('size')!=2 or row.get('sha256')!=hashlib.sha256(b'1\n').hexdigest():
                raise ValueError('Candidate flags readback differs')
            expected[name]=row
        if after['entries']!=expected:
            raise ValueError('Candidate changed another FAT entry')
        suffix=part['offset']+part['bytes']
        surrounding=(disk['hashed'](leased['fd'],0,part['offset']), disk['hashed'](leased['fd'],suffix))
        raw=fs.read_bytes()
        if len(raw)>part['bytes'] or os.pwrite(leased['fd'],raw,part['offset'])!=len(raw):
            raise OSError('Short private p2 write')
        os.fsync(leased['fd'])
        if (os.pread(leased['fd'],len(raw),part['offset'])!=raw or
                (disk['hashed'](leased['fd'],0,part['offset']),disk['hashed'](leased['fd'],suffix))!=surrounding or
                disk['hashed'](leased['fd'],part['offset']+len(raw),part['bytes']-len(raw))!=tail['sha256']):
            raise ValueError('Candidate disk readback/range preservation differs')
        result=dict(profile=PROFILE,instance=str(instance),disk_before=before,disk_after=disk['hashed'](leased['fd']),
            only_new_files=['/updater/mode','/updater/mode5'], all_other_entries_unchanged=True,
            other_disk_bytes_unchanged=True,backup_sha256=BACKUP_SHA,guest_writes_allowed=False,
            original_p2=u['record'](p2),flags=u['setting_state'](after)['flags'])
        disk['save'](output/'candidate.json',result)
    return instance


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','kernel','qemu-receipt','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();os.umask(0o077)
    result=source(args.root,args.kernel,args.qemu_receipt,args.output)
    print(json.dumps(dict(status=result['status'],profile=PROFILE)))


if __name__=='__main__': main()
