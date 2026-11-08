from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,time,os
from elftools.elf.elffile import ELFFile
HERE=Path(__file__).resolve().parent
EXPECTED_UNDEFINED={'bdget_disk','bdput','freeze_bdev','thaw_bdev','__ioremap','__iounmap','alloc_disk','arm64_const_caps_ready','bio_endio','blk_alloc_queue','blk_cleanup_queue','blk_queue_logical_block_size','blk_queue_make_request','blk_queue_max_hw_sectors','blk_queue_split','blk_queue_write_cache','cpu_hwcap_keys','cpu_hwcaps','del_gendisk','device_add_disk','flush_dcache_page','kfree','kimage_voffset','kmalloc_add_trace','kmalloc_caches','kmem_cache_alloc','memcpy','memstart_addr','mutex_lock','mutex_unlock','param_ops_charp','param_ops_ulong','printk','put_disk','register_blkdev','snprintf','strcmp','strlcpy','unregister_blkdev'}
def need(ok,message):
 if not ok:raise ValueError(message)
def sha(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();source=args.source.resolve(strict=True);out=args.output.absolute();need(not out.exists(),'Fresh module output required');out.mkdir(parents=True,mode=0o700)
 manifest=json.loads((source/'abi-manifest.json').read_bytes());need(manifest['kernel_release']=='4.9.337-scel+','Unknown module ABI version')
 expected_headers={name for name in manifest['files'] if name.startswith('abi/')};actual_headers={str(path.relative_to(source)) for path in (source/'abi').rglob('*') if path.is_file() or path.is_symlink()};need(actual_headers==expected_headers,'Persistent kernel ABI header inventory differs')
 for name,row in manifest['files'].items():
  path=source/name;need(not path.is_symlink() and path.resolve().is_relative_to(source) and path.stat().st_size==row['bytes'] and sha(path)==row['sha256'],'Module ABI/source identity changed: '+name)
 cc=shutil.which('aarch64-linux-gnu-gcc');ld=shutil.which('aarch64-linux-gnu-ld');need(cc and ld,'AArch64 GCC/binutils required');system_headers=subprocess.run([cc,'-print-file-name=include'],capture_output=True,text=True,check=True).stdout.strip();need(Path(system_headers).is_dir(),'Cross compiler builtin headers missing')
 def command(index):
  argv=[]
  for word in manifest['commands'][index]:
   if word=='aarch64-linux-gnu-gcc':argv.extend([cc,'-isystem',system_headers])
   elif word=='aarch64-linux-gnu-ld':argv.append(ld)
   elif word.startswith('-Iabi/'):argv.append('-I'+str(source/word[2:]))
   elif word.startswith('abi/') or word in ('sony_persistent_flash.c','./sony_persistent_flash.c','sony_persistent_flash.mod.c','./sony_persistent_flash.mod.c','module-common.lds'):argv.append(str(source/word))
   else:argv.append(word)
  result=subprocess.run(argv,cwd=out,capture_output=True,timeout=60);(out/('command-'+str(index)+'.stdout')).write_bytes(result.stdout);(out/('command-'+str(index)+'.stderr')).write_bytes(result.stderr);need(result.returncode==0,'Portable module command failed '+str(index)+': '+result.stderr.decode(errors='replace'));return dict(argv=argv,returncode=0)
 with ThreadPoolExecutor(max_workers=2) as pool:commands=list(pool.map(command,(0,1)))
 commands.append(command(2));module=out/'sony_persistent_flash.ko'
 with module.open('rb') as stream:
  elf=ELFFile(stream);need(elf['e_machine']=='EM_AARCH64' and elf['e_type']=='ET_REL','Wrong module architecture/type');undefined={s.name for s in elf.get_section_by_name('.symtab').iter_symbols() if s['st_shndx']=='SHN_UNDEF' and s.name};need(undefined==EXPECTED_UNDEFINED,'Original kernel symbol ABI differs: '+str(undefined^EXPECTED_UNDEFINED));layout=elf.get_section_by_name('.gnu.linkonce.this_module');need(layout['sh_size']==768 and layout['sh_addralign']==64,'Original struct module ABI differs');info=elf.get_section_by_name('.modinfo').data().split(b'\0');need(b'vermagic=4.9.337-scel+ SMP preempt mod_unload aarch64' in info and b'license=GPL' in info,'Original vermagic/license differs')
 value=dict(schema='a7c2-portable-persistent-module-build-v1',kernel_release='4.9.337-scel+',module=dict(bytes=module.stat().st_size,sha256=sha(module)),source_manifest_sha256=sha(source/'abi-manifest.json'),all_header_source_hashes_verified=True,original_module_layout_bytes=768,original_module_alignment=64,expected_original_kernel_symbols_verified=True,original_symbols_plus_page_cache_maintenance=True,standard_cross_compiler_builtin_headers_used=True,full_kernel_tree_used=False,original_guest_insmod_verified=False,commands=commands)
 with (out/'result.json').open('x') as stream:stream.write(json.dumps(value,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
 print('PORTABLE_PERSISTENT_MODULE_BUILD_PASS',out,value['module']['sha256'],flush=True)
if __name__=='__main__':main()
