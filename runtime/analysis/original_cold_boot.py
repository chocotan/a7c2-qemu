"""Prepare the original RAM0/init/pivot route in one isolated product disk."""
from pathlib import Path
from contextlib import ExitStack
import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys

import persistent_disk as disk
import persistent_storage as storage
import virtual_loader
from ext2_inventory import Ext2, quote

ANALYSIS=Path(__file__).resolve().parent
SOURCE=ANALYSIS/'cold'
PROFILE='original-init-v1'
RAM0_SHA='b249308ff1a42f8f441cedbd6244e8ffa0b4c88b984b2d5e71a436d09ab86529'
KERNEL_SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
ORIGINAL_SCRIPTS={
    '/sbin/init':'c83de1abeeb779f7473181b51face32ecfedfa3bd5c0fc346ae0c628f1b0ac5e',
    '/sbin/init2':'45d3b907e6ef96c9a930cd3e6f919db700bffb5f18c386abfdb655f4d9954aeb',
    '/sbin/initrc/setup_rootfs':'ee84d317484d8cb4a0f1e39d665f1f04f18bf4d193a36a6e9bf63f8666a6a34d',
    '/sbin/initrc/fstab.root':'c77d93236b89349bcc24853756f960bb49411e922c9430ede70b5b2cb8b6a4b2',
    '/sbin/initrc/fstab':'3936e6508ba89a025fc998c824434562c2d16234db96e179ec3f3a90a5a1d6f0',
    '/sbin/initrc/insmod_drv1':'22f29d06d7776fe5e8362c17049beabfd3e3bebffd222e51276e3704d483a591',
    '/sbin/initrc/insmod_drv2':'19757bdd450061f861e2da44a6a93be2525668e3f7edc64e5a99a25bde56564e',
}
BASE_GUEST={
    'QEMU_NO_CP_UPDATER':'1','QEMU_CAPID_SERVICE':'1','QEMU_SA_ADDRESS_SERVICE':'1',
    'QEMU_HDMI_FORMAT_SERVICE':'1','QEMU_HDMI_PHOTO_SERVICE':'1','QEMU_DMM_SERVICE':'1',
    'QEMU_SOFTWARE_GPE':'1','QEMU_GPE_RGBA4444':'1','QEMU_DISPLAY_INFO_SERVICE':'1',
    'QEMU_SOFTWARE_LZ77':'1','MENU_HEADLESS_OSD':'1','MENU_OBSERVE_INPUT':'1',
    'MENU_RM_FILE':'1','A7C2_FILE_MEDIA_TEST':'1','A7C2_SD_HOTPLUG':'1',
    'MENU_GUI_MODELS':'virtual-inline-v1','MENU_VDF_CONFIG':'1','MENU_HDMI_BOOT_CONFIG':'1',
    'MENU_AUDIO_BOOT_CONFIG':'1','MENU_DIG_LEVEL':'virtual','MENU_PANEL_REVERSE':'virtual',
    'MENU_DMM_UNIT_CONFIG':'1','MENU_PIN_REGISTRY':'1','MENU_PIN_CONTROL_MEMORY':'1','MENU_PIN_CONNECTION':'cold',
    'MENU_CP_TIME_SERVICE':'1','MENU_CRYPT_LIB':'1','MENU_BUSPOWER':'1',
    'MENU_CP_RELEASE_SERVICE':'1','MENU_OSD_OBSERVE':'1','MENU_FRAME_OBSERVE':'1',
}


def need(value,message):
    if not value:raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def product_input_bindings():
    imported=json.loads((ANALYSIS/'native-assets.json').read_bytes())
    need(imported.get('model')=='ILCE-7CM2' and imported.get('version')=='2.01','Cold route requires the product official2.01 import')
    build=json.loads((ANALYSIS/'observer-build-inputs.json').read_bytes())
    identities={
        'usr/bin/bootin.elf':'dab3ce4b6c28a6c9ffd9f0b893dce1d08f3ee7302a09df87e518409e728be2f2',
        'usr/bin/im.elf':'5171f576d8b76cfbf15581389183b390c445bd6ff9dd97fd6668c5f64e77dc91',
        'usr/lib/appFw.so':'2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
        'usr/lib/libObj.so':'c0897d72a40bf0a161fa7f89e9a34eef4d19e0506c7817a5c11a6f53897cdbbc',
        'usr/lib/libIMDB.so':'0ebba8dd2fefad4684419d1111a56c659c7fd04473c04da39e6f2e7d8ac0facf',
        'simulation/menu-observe.so':build['observer_sha256'],
        'simulation/pin-control-probe':build['pin_control_probe_sha256'],
        'simulation/system-sound-owner':build['system_sound_owner_sha256'],
    }
    for name,digest in identities.items():need(sha(ANALYSIS/'menu-root'/name)==digest,'Product cold input identity differs: '+name)
    need(sha(ANALYSIS/'observer-build-sources.tar.gz')==build['source_archive_sha256'],'Product observer source archive changed')
    return dict(guest_inputs=identities,observer_build_receipt_sha256=sha(ANALYSIS/'observer-build-inputs.json'),observer_source_archive_sha256=build['source_archive_sha256'])


def guest_environment(host):
    # Only actual guest exports in the product probe may cross this boundary.
    tree=ast.parse((ANALYSIS/'qemu-menu-probe.py').read_text())
    allowed=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant) and isinstance(node.value,str):
            match=re.match(r'^export ([A-Z][A-Z0-9_]*)=',node.value)
            if match:allowed.add(match[1])
    selected=dict(BASE_GUEST)
    for name,value in host.items():
        if name in allowed and name.startswith('MENU_'):
            need(isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_./,:=+@-]*',value) is not None,'Unsafe cold guest option: '+name)
            selected[name]=value
    from sony_usb_device import selected as usb_selected
    if usb_selected(host):selected['PRODUCT_SONY_USB_DEVICE']='1'
    if host.get('A7C2_USB_SENSER') is not None:
        need(usb_selected(host) and host['A7C2_USB_SENSER']=='original-init2-v1','Senser startup requires the explicit USB device profile')
        selected['PRODUCT_USB_SENSER']='original-init2-v1'
    if host.get('A7C2_USB_MSC') is not None:
        need(usb_selected(host) and host['A7C2_USB_MSC']=='1' and not host.get('A7C2_USB_SENSER'),'MSC startup requires its exclusive USB device profile')
        selected['PRODUCT_USB_MSC']='1'
    return selected


def verify_chain_log(raw):
    tokens=[b'PRODUCT_COLD_BEFORE_ORIGINAL_INIT',b'+ . /sbin/initrc/setup_rootfs',
            b'+ /sbin/pivot_root . /rootfs/initrd',b'+ exec busybox chroot . /bin/ash -c',
            b'COLD_RAM0_RELEASE original_rc=0 zero_prefix=1 bytes=512',
            b'PRODUCT_COLD_INIT2 parent=1',b'PRODUCT_COLD_BOOTIN pid=']
    end=0;offsets=[]
    for token in tokens:
        position=raw.find(token,end);need(position>=0,'Original cold handoff missing or out of order: '+token.decode())
        offsets.append(position);end=position+len(token)
    return dict(original_script_handoff_order_verified=True,ordered_log_offsets=offsets,original_script_bytes_bound_by_build=True)


def verify_root_observation(raw):
    text=raw.decode('ascii',errors='replace').replace('\r','');roots=[];mounts=[]
    for line in text.splitlines():
        fields=line.split()
        if len(fields)<10 or '-' not in fields:continue
        split=fields.index('-')
        if split<6 or len(fields)<split+4:continue
        row=dict(device=fields[2],root=fields[3],target=fields[4],options=fields[5].split(','),filesystem=fields[split+1],source=fields[split+2],super_options=fields[split+3].split(','))
        mounts.append(row)
        if row['target']=='/':roots.append(row)
    need(len(roots)==1 and roots[0]['root']=='/' and roots[0]['filesystem']=='ext2' and roots[0]['source'] in ('/dev/nflasha7','/dev/cnflasha7') and 'ro' in roots[0]['options'] and 'ro' in roots[0]['super_options'],'Original p7 readonly root not observed')
    need(not any(row['target']=='/initrd' or row['target'].startswith('/initrd/') for row in mounts),'Original old-root mount still present')
    need(any(row['target']=='/usr' and row['filesystem']=='ext2' and row['source'] in ('/dev/nflasha15','/dev/cnflasha15') for row in mounts),'Original usr volume not mounted')
    for name in ('Uid','Gid'):
        need(len(re.findall(r'^'+name+r':[^\n]*$',text,re.M))==1 and re.search(r'^'+name+r':[ \t]*0[ \t]+0[ \t]+0[ \t]+0[ \t]*$',text,re.M) is not None,'Original cold guest root identity differs')
    return dict(p7_root=roots[0],old_root_unmounted_verified=True,root_uid_gid_four_zero_fields=True,internal_mounts=[row for row in mounts if row['source'].startswith(('/dev/nflasha','/dev/cnflasha'))])


def chinese_language_rows(image):
    if image.size!=(640,480):return dict(target=None,selected=None)
    templates={'545d8ede6f6078a4a961419e5d4ab06180f99ac7273efeacc57ebb31330c5af9','6b15a886028f8d40ee5f32e9171aef0c0ba84bd0534965029dfafeb6efcaf0cf'}
    targets=[];selected=[]
    for row in range(5):
        top=71+70*row;mask=image.crop((180,top,460,top+45)).convert('L').point(lambda value:255 if value>=128 else 0,'1')
        if hashlib.sha256(mask.tobytes()).hexdigest() in templates:targets.append(row)
        count=sum(r>120 and r>1.4*g and g>1.5*b for r,g,b in image.crop((100,top,540,top+45)).convert('RGB').getdata())
        if count>1000:selected.append(row)
    return dict(target=targets[0] if len(targets)==1 else None,selected=selected[0] if len(selected)==1 else None)


def original_menu_pixels(image):
    # Reviewed original 2.01 Chinese "MENU close" control, independent of HUD updates.
    if image.size!=(640,480):return False
    mask=image.crop((490,432,640,480)).convert('L').point(lambda value:255 if value>=128 else 0,'1')
    return hashlib.sha256(mask.tobytes()).hexdigest()=='f76f446097088810cb417f3cafc761d758dcc980a994a12ea2c977bc45d421d7'


def guest_identity_script(bindings):
    lines=['#!/bin/busybox sh','set -e']
    for name in ('usr/bin/im.elf','usr/lib/appFw.so','usr/lib/libObj.so'):
        digest=bindings['guest_inputs'][name];target='/'+name
        need(re.fullmatch(r'[0-9a-f]{64}',digest) is not None,'Invalid original ELF digest')
        lines+=['digest=$(/usr/bin/openssl dgst -sha256 '+target+')',
                'case "$digest" in "SHA256('+target+')= '+digest+'"|"SHA2-256('+target+')= '+digest+'") echo PRODUCT_COLD_GUEST_ELF_VERIFIED='+target+':'+digest+';; *) exit 78;; esac']
    return '\n'.join(lines)+'\n'


def font_install_script(fonts):
    commands=['#!/bin/busybox sh','set -e']
    for name,path in sorted(fonts.items()):
        need(re.fullmatch(r'[A-Za-z0-9_.+-]+',name) is not None,'Unsafe font basename')
        target='/tmp/images/'+name;digest=sha(path);valid='"SHA256('+target+')= '+digest+'"|"SHA2-256('+target+')= '+digest+'"'
        commands+=['digest=$(/usr/bin/openssl dgst -sha256 '+target+' 2>/dev/null) || digest=',
                   'case "$digest" in '+valid+') ;; *)',
                   '  /simulation/audit space /tmp '+str(path.stat().st_size+1024**2)+' || exit 1',
                   '  /bin/busybox cp /simulation/language-fonts/'+name+' '+target,
                   '  digest=$(/usr/bin/openssl dgst -sha256 '+target+')',
                   '  case "$digest" in '+valid+') ;; *) exit 1;; esac;; esac']
    return '\n'.join(commands)+'\n'


def _checked(command,log,timeout=90):
    result=subprocess.run(command,capture_output=True,text=True,timeout=timeout,env={**os.environ,'LC_ALL':'C'})
    log.write_text(result.stdout+result.stderr)
    need(result.returncode==0,'Cold preparation command failed; see '+str(log))
    return result


def _patch(image,work,files,links=()):
    fs=Ext2(image,work);before=fs.inventory();original=dict(before['entries']);directories=set()
    entry='/sbin/init' if image.name=='ram0.ext2' else '/sbin/init2'
    for name,digest in ORIGINAL_SCRIPTS.items():
        if name in ('/sbin/init','/sbin/init2') and name!=entry:continue
        need(original.get(name,{}).get('sha256')==digest,'Original cold script identity differs: '+name)
        need(name not in files and name not in dict(links),'Refuse replacing original cold script: '+name)
    for path in [*files,*dict(links)]:
        need(path.startswith('/') and '..' not in Path(path).parts,'Nonlocal cold image path')
        for parent in Path(path).parents:
            if str(parent)!='/':directories.add(str(parent))
    for directory in sorted(directories,key=lambda x:(x.count('/'),x)):
        if directory not in original:fs.command('mkdir '+quote(directory),write=True)
        else:need(original[directory]['kind']=='dir','Cold directory conflicts with original file')
    touched=set(files)|set(dict(links))
    for path,source in files.items():
        if path in original:
            need(original[path]['kind']!='dir','Refuse replacing original directory')
            fs.command('rm '+quote(path),write=True)
        fs.command('write '+quote(source)+' '+quote(path),write=True)
        mode=stat.S_IMODE(source.stat().st_mode)&0o777
        for field,value in (('mode','0'+format(stat.S_IFREG|mode,'o')),('uid','0'),('gid','0')):
            fs.command('set_inode_field '+quote(path)+' '+field+' '+value,write=True)
    for path,target in links:
        if path in original:
            need(original[path].get('kind')=='symlink' and original[path].get('target')==target,'Cold symlink conflicts with existing path')
        else:fs.command('symlink '+quote(path)+' '+quote(target),write=True)
    _checked(['e2fsck','-fn',str(image)],work/(image.stem+'-fsck.log'))
    after=fs.inventory()
    for path,node in original.items():
        if path not in touched:need(after['entries'].get(path)==node,'Unintended original root change: '+path)
    expected=set(original)|set(files)|set(dict(links))|directories
    need(set(after['entries'])==expected,'Unexpected cold root tree entry')
    remaining_links=sorted(sorted(set(group)-touched) for group in before['hardlinks'] if len(set(group)-touched)>1)
    need(after['hardlinks']==remaining_links,'Unexpected original hardlink change in cold root')
    for path,source in files.items():
        node=after['entries'][path]
        need(node.get('sha256')==sha(source) and node.get('size')==source.stat().st_size,'Cold image file readback differs: '+path)
    for path,target in links:need(after['entries'][path].get('target')==target,'Cold image symlink differs')
    return dict(original_tree_sha256=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),adapted_tree_sha256=hashlib.sha256(json.dumps(after,sort_keys=True).encode()).hexdigest(),original_untouched_entries_verified=True,changed_or_added=sorted(touched|directories),original_scripts={p:n['sha256'] for p,n in original.items() if p.startswith('/sbin/init') and n.get('kind')=='file' and p not in touched})


def stage_file_selection(payload,host):
    """Snapshot an explicit overwrite through the existing no-symlink scanner."""
    from firmware_overlay import _parent,_fd,_scan,_signature,_check_anchors
    from firmware_development import guest_path,MAX_FILE_BYTES
    directory=Path(host.get('A7C2_OVERWRITE_DIR',str(ANALYSIS.parents[1]/'overwrite')))
    entries=[]
    if host.get('A7C2_OVERWRITE_DIR'):need(os.path.lexists(directory),'Explicit cold overwrite directory is missing')
    if os.path.lexists(directory):
        with ExitStack() as stack:
            path,parent,name,anchors=_parent(stack,directory)
            descriptor=_fd(stack,name,os.O_RDONLY|os.O_DIRECTORY,parent)
            anchors.append((parent,name,os.fstat(descriptor)))
            files,directories=_scan(stack,descriptor)
            for relative,(parent,name,info) in sorted(files.items()):
                guest_path('/'+relative);original=ANALYSIS/'menu-root'/relative
                need(relative.startswith('usr/') and original.is_file() and not original.is_symlink(),'Cold file tests require an existing restorable /usr file: '+relative)
                need(info.st_size<=MAX_FILE_BYTES,'Cold file test exceeds file budget')
                source=_fd(stack,name,os.O_RDONLY|os.O_NONBLOCK,parent)
                need(_signature(os.fstat(source))==_signature(info),'Cold file selection changed before copy')
                target=payload/('cold-file-'+str(len(entries)))
                with os.fdopen(os.dup(source),'rb') as stream,target.open('xb') as output:
                    shutil.copyfileobj(stream,output,1024**2)
                need(_signature(os.fstat(source))==_signature(info) and target.stat().st_size==info.st_size,'Cold file selection changed while copying')
                entries.append(dict(path=relative,source=str(target),selection_source=str(path/relative),new_sha256=sha(target),size=info.st_size,mode=info.st_mode))
            for fd,info,names in directories:
                need(_signature(os.fstat(fd))==_signature(info) and sorted(os.listdir(fd))==names,'Cold file selection directory changed')
            _check_anchors(anchors)
    return dict(entries=entries,source_class='user_overwrite',overwrite_dir=str(directory.absolute()))


def settings_import(payload,host):
    """Migrate the old RAM-route snapshot once; later boots keep the actual internal volume."""
    marker='/log/qemu/original-cold-settings-imported'
    lines=['#!/bin/busybox sh','set -e','if [ ! -f '+marker+' ]; then','  /bin/busybox mkdir -p /log/qemu']
    source=host.get('A7C2_SETTINGS_RESTORE')
    if source:
        from settings_checkpoint import inspect_backup
        fd=disk.secure_open(str(Path(source).absolute()))
        try:
            need(os.fstat(fd).st_size==2390264,'Cold settings snapshot size differs')
            data=os.pread(fd,2390265,0);proof=inspect_backup(data)
        finally:os.close(fd)
        need(proof['sha256']==host.get('A7C2_SETTINGS_RESTORE_SHA'),'Cold settings snapshot digest differs')
        target=payload/'settings-restore.bin';target.write_bytes(data);target.chmod(0o600)
        digest=proof['sha256']
        lines+=['  if [ -f /setting/Backup.bin ]; then /bin/busybox cp /setting/Backup.bin /log/qemu/original-cold-settings-before; /bin/busybox cmp /setting/Backup.bin /log/qemu/original-cold-settings-before; fi',
                '  /bin/busybox cp /simulation/settings-restore.bin /setting/Backup.bin',
                '  digest=$(/usr/bin/openssl dgst -sha256 /setting/Backup.bin)',
                '  case "$digest" in "SHA256(/setting/Backup.bin)= '+digest+'"|"SHA2-256(/setting/Backup.bin)= '+digest+'") ;; *) exit 1;; esac','  /bin/busybox sync']
    lines+=['  echo '+(host.get('A7C2_SETTINGS_RESTORE_SHA') if source else 'no-legacy-snapshot')+' > '+marker,'  /bin/busybox sync','fi']
    script=payload/'install-settings.sh';script.write_text('\n'.join(lines)+'\n',encoding='ascii');script.chmod(0o755)
    return {name:payload/name for name in ('install-settings.sh','settings-restore.bin') if (payload/name).exists()}


def usb_imdb(host,payload):
    if host.get('A7C2_USB_MSC')!='1':return {}
    source=ANALYSIS/'prepare-assets.py'
    spec=importlib.util.spec_from_file_location('a7c2_prepare_assets',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original=ANALYSIS/'menu-root/usr/lib/libIMDB.so'
    data=module.usb_msc_imdb(original.read_bytes())
    target=payload/'libIMDB-msc.so';target.write_bytes(data);target.chmod(0o555)
    need(sha(target)==module.MSC_IMDB_SHA,'MSC IMDB payload readback differs')
    # bootin searches /simulation first; binding only /usr/lib would leave the default IMDB consumed.
    return {'libIMDB-msc.so':target,'libIMDB.so':target}


def prepare(instance,output,host_environment):
    input_bindings=product_input_bindings()
    output=Path(output).absolute();need(not output.exists(),'Fresh cold output required');output.mkdir(mode=0o700)
    work=output/'work';work.mkdir();payload=output/'payload';payload.mkdir()
    need(shutil.disk_usage(output).free>512*1024**2,'Insufficient room for small original RAM0 and audit')
    sys.path.insert(0,str(ANALYSIS/'vendor/fwtool-sdk'))
    from fwtool.archive.fat import readFat
    with disk.lease(Path(instance).absolute()) as leased:
        slices={row['id']:row for row in leased['geometry']['slices']};p3=slices['nflasha3']
        loader=virtual_loader.evaluate_fd(leased['fd'],leased['geometry'])
        need(loader['route'].get('status')=='selected' and loader['route'].get('mode')==1 and loader['resolve'].get('path')=='cold',
             'Virtual loader selected a non-cold route; this build only boots cold: '+json.dumps(loader,sort_keys=True))
        virtual_loader.save_receipt(output,loader)
        original_disk_before=disk.hashed(leased['fd'])
        source=io.BytesIO(os.pread(leased['fd'],p3['bytes'],p3['offset']));found={}
        for entry in readFat(source):
            if entry.path in ('/initrd.img','/vmlinux.bin'):
                data=entry.contents.read(entry.size);need(len(data)==entry.size,'Short p3 boot file')
                expected=RAM0_SHA if entry.path=='/initrd.img' else KERNEL_SHA
                need(hashlib.sha256(data).hexdigest()==expected,'Current disk p3 boot identity differs')
                name='ram0.original.ext2' if entry.path=='/initrd.img' else 'kernel.original.img';path=output/name;path.write_bytes(data);need(sha(path)==expected,'Extracted original boot file readback differs');found[name]=dict(bytes=len(data),sha256=expected)
        need(len(found)==2,'Original p3 kernel/RAM0 missing')
        ram=output/'ram0.ext2';shutil.copyfile(output/'ram0.original.ext2',ram)
        audit=payload/'audit';_checked(['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-O2','-fno-stack-protector','-Wl,--no-undefined','-Wl,-e,_start','-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',str(SOURCE/'cold-start-audit.c'),str(ANALYSIS/'menu-root/lib/libc-2.25.so'),'-o',str(audit)],output/'audit-build.log');audit.chmod(0o755)
        helpers={}
        for path in (ANALYSIS/'menu-root/simulation').rglob('*'):
            if path.is_file() and path.name!='media-camera.fat':
                need(not path.is_symlink(),'Cold helper symlink refused')
                relative=str(path.relative_to(ANALYSIS/'menu-root/simulation'));target=payload/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target);target.chmod(stat.S_IMODE(path.stat().st_mode)&0o777);need(sha(path)==sha(target),'Cold helper copy differs');helpers[relative]=target
        for name,source in (('audit',audit),('bootin-wrapper',SOURCE/'bootin.sh')):
            if source!=payload/name:shutil.copyfile(source,payload/name)
            (payload/name).chmod(0o755);helpers[name]=payload/name
        (payload/'bootin-original').write_bytes(b'');(payload/'bootin-original').chmod(0o755);helpers['bootin-original']=payload/'bootin-original'
        overwrite=stage_file_selection(payload,host_environment)
        entries=storage.stage_file_tests(payload,overwrite,host_environment.get('A7C2_STORAGE_RESTORE_FILE'),host_environment.get('A7C2_STORAGE_RESTORE_SELECTION'))
        for path in payload.glob('persistent-*'):helpers[path.name]=path
        helpers.update(settings_import(payload,host_environment))
        from sony_usb_device import prepare_observer
        helpers.update(prepare_observer(host_environment,payload))
        helpers.update(usb_imdb(host_environment,payload))
        expected_bindings={**input_bindings,'guest_inputs':dict(input_bindings['guest_inputs'])}
        if host_environment.get('A7C2_USB_MSC')=='1':
            expected_bindings['guest_inputs']['usr/lib/libIMDB.so']=sha(helpers['libIMDB-msc.so'])
        for entry in entries:expected_bindings['guest_inputs'][entry['path']]=entry['new_sha256']
        from sparse_seed import build as build_sd_seed
        sd_source=host_environment.get('A7C2_SD_IMAGE',str(ANALYSIS/'menu-root/simulation/media-camera.fat'))
        sd_card=build_sd_seed(sd_source,payload/'sd-seed')
        for path in (payload/'sd-seed').rglob('*'):
            if path.is_file():
                name=str(path.relative_to(payload));helpers[name]=path
        shutil.copyfile(SOURCE/'install-sd.sh',payload/'install-sd.sh');(payload/'install-sd.sh').chmod(0o755)
        helpers['install-sd.sh']=payload/'install-sd.sh'
        environment=guest_environment(host_environment);envfile=payload/'environment.sh';envfile.write_text('\n'.join('export '+k+'='+shlex.quote(v) for k,v in sorted(environment.items()))+'\n');envfile.chmod(0o600);helpers['environment.sh']=envfile
        reset=payload/'reset-runtime.sh';reset.write_text('#!/bin/busybox sh\nset -e\n'+'\n'.join(storage.runtime_reset_commands())+'\n');reset.chmod(0o755);helpers['reset-runtime.sh']=reset
        fonts={name[len('language-fonts/'):]:path for name,path in helpers.items() if name.startswith('language-fonts/')}
        need(len(fonts)==3,'Exact three product language fonts required')
        fontinstaller=payload/'install-fonts.sh';fontinstaller.write_text(font_install_script(fonts));fontinstaller.chmod(0o755);helpers['install-fonts.sh']=fontinstaller
        originalcheck=payload/'verify-originals.sh';originalcheck.write_text(guest_identity_script(expected_bindings));originalcheck.chmod(0o755);helpers['verify-originals.sh']=originalcheck
        helper_bytes=sum(p.stat().st_size for p in helpers.values())
        need(helper_bytes<480*1024**2,'Cold RAM helper budget exceeded')
        ram_bytes=max(192*1024**2,((helper_bytes+64*1024**2+64*1024**2-1)//(64*1024**2))*(64*1024**2))
        need(ram_bytes<=544*1024**2,'Cold RAM0 exceeds the bounded high-DDR image')
        with ram.open('r+b') as stream:stream.truncate(ram_bytes)
        _checked(['resize2fs',str(ram)],output/'ram0-resize.log')
        helperbudget=payload/'helper-bytes';helperbudget.write_text(str(helper_bytes+1024**2)+'\n')
        helperlist=payload/'helpers';helperlist.write_text(''.join(n+' '+str(p.stat().st_size)+' '+sha(p)+' '+format(p.stat().st_mode&0o777,'o')+'\n' for n,p in sorted(helpers.items())))
        capacities=payload/'capacities';capacities.write_text(''.join(('nflashaB'+n[-1] if n.startswith('nflashaB') else 'cnflasha'+n[len('nflasha'):])+' '+str(row['bytes']//512)+'\n' for n,row in slices.items()))
        freeram=payload/'freeramdisk';freeram.write_text('#!/bin/busybox sh\nexec /simulation/audit release "$@"\n');freeram.chmod(0o755)
        for name in ('bootstrap.sh','insmod.sh'):subprocess.run(['sh','-n',str(SOURCE/name)],check=True)
        newfiles={'/sbin/product-cold-bootstrap':SOURCE/'bootstrap.sh','/sbin/insmod':SOURCE/'insmod.sh','/qemu/audit':audit,'/qemu/helpers':helperlist,'/qemu/helper-bytes':helperbudget,'/qemu/capacities':capacities,'/qemu/sony_persistent_flash.ko':storage.module_file()}
        newfiles.update(('/qemu/simulation/'+n,p) for n,p in helpers.items())
        ramproof=_patch(ram,work,newfiles)
        p7=slices['nflasha7'];before=output/'p7.original.ext2';before.write_bytes(os.pread(leased['fd'],p7['bytes'],p7['offset']));adapted=output/'p7.ext2';shutil.copyfile(before,adapted)
        empty=payload/'image_mmca';empty.write_bytes(b'');empty.chmod(0o600)
        p7proof=_patch(adapted,work,{'/sbin/insmod':SOURCE/'insmod.sh','/sbin/freeramdisk':freeram,'/image_mmca':empty},[('/simulation','/dev/qemu-simulation')])
        raw=adapted.read_bytes();need(len(raw)==p7['bytes'],'Derived p7 capacity changed');need(os.pwrite(leased['fd'],raw,p7['offset'])==len(raw),'Short p7 write');os.fsync(leased['fd']);need(disk.hashed(leased['fd'],p7['offset'],p7['bytes'])==sha(adapted),'Derived p7 disk readback differs')
        result=dict(schema='a7c2-product-original-cold-preparation-v1',profile=PROFILE,instance=str(Path(instance).absolute()),virtual_loader=loader,ram0=str(ram),ram0_bytes=ram.stat().st_size,ram0_sha256=sha(ram),original_boot_files=found,ram0_tree=ramproof,p7_tree=p7proof,p7_before_sha256=sha(before),p7_after_sha256=sha(adapted),original_disk_before_sha256=original_disk_before,derived_disk_sha256=disk.hashed(leased['fd']),guest_environment=environment,helper_sources={n:dict(bytes=p.stat().st_size,sha256=sha(p)) for n,p in helpers.items()},sd_card=sd_card,kernel_sha256=KERNEL_SHA,source_class='official-bodydata-derived-with-explicit-virtual-adapters',product_input_bindings=input_bindings,expected_guest_inputs=expected_bindings['guest_inputs'],overwrite=dict(overwrite,entries=entries),helper_bytes=helper_bytes,original_guest_executed=False,full_boot_verified=False)
        storage._save(output/'result.json',result)
    return result
