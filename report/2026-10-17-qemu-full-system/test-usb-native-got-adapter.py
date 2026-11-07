#!/usr/bin/env python3
"""Real dlopen App GOT, production finite adapter, host glibc only; no VM."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE / 'test-usb-start-observe.py'))
BUILD = runpy.run_path(str(HERE / 'usb-start-observe.py'))

INSPECT = r'''
static uintptr_t fixture_free_slot;
void *fixture_read_free_binding(void){assert(fixture_free_slot);return *(void**)fixture_free_slot;}
static int inspect_got(struct dl_phdr_info *info,size_t size,void *arg){
 (void)size;(void)arg;if(strcmp(info->dlpi_name,FIXTURE_APP))return 0;
 ElfW(Dyn)*dyn=0;for(unsigned i=0;i<info->dlpi_phnum;i++)if(info->dlpi_phdr[i].p_type==PT_DYNAMIC)dyn=(void*)(info->dlpi_addr+info->dlpi_phdr[i].p_vaddr);
 ElfW(Sym)*syms=0;const char*strs=0;ElfW(Rela)*rel=0;size_t bytes=0;
 for(;dyn&&dyn->d_tag;dyn++){if(dyn->d_tag==DT_SYMTAB)syms=(void*)dyn->d_un.d_ptr;if(dyn->d_tag==DT_STRTAB)strs=(void*)dyn->d_un.d_ptr;if(dyn->d_tag==DT_JMPREL)rel=(void*)dyn->d_un.d_ptr;if(dyn->d_tag==DT_PLTRELSZ)bytes=dyn->d_un.d_val;}
 void *olds[3]={0},*selected[3]={0};unsigned offsets[3]={0};
 const char *names[]={"osal_get_msg_src","osal_msg_size","osal_free_msg"};
 void *wrappers[]={tap_source,tap_size,tap_free};void **originals[]={(void**)&ee_real_source,(void**)&ee_real_size,(void**)&ee_real_free};
 unsigned count=0;
 for(unsigned i=0;i<bytes/sizeof(*rel);i++)for(unsigned j=0;j<3;j++){
  const char*n=strs+syms[ELF64_R_SYM(rel[i].r_info)].st_name;if(strcmp(n,names[j]))continue;
  assert(!offsets[j]);offsets[j]=(unsigned)rel[i].r_offset;count++;
  void *old=*(void**)(info->dlpi_addr+offsets[j]),*raw=lookup(RTLD_NEXT,n),*global=lookup(RTLD_DEFAULT,n);Dl_info mapped={0},original={0},binding={0};
  assert(dladdr(old,&mapped)&&dladdr(raw,&original)&&dladdr(global,&binding));
  unsigned plt=fixture_plt[j];
  if(getenv("FIXTURE_LAZY"))assert(old==(void*)(info->dlpi_addr+plt)&&(uintptr_t)mapped.dli_fbase==info->dlpi_addr);
  if(j==2)fixture_free_slot=info->dlpi_addr+offsets[j];
  fprintf(stderr,"APP_DSO_GOT name=%s slot=%#x binding=%s old=%p raw=%p AppBase=%#lx filePLT=%#x global=%p globalBinding=%s legacy_match=%d\n",n,offsets[j],mapped.dli_fname,old,raw,info->dlpi_addr,plt,global,binding.dli_fname,slot_matches(info->dlpi_addr,old,raw,plt));
  if(j==2)fprintf(stderr,"originalGlobalDefaultFree=%s lazy=%d oldInApp=%d\n",binding.dli_fname,!!getenv("FIXTURE_LAZY"),(uintptr_t)mapped.dli_fbase==info->dlpi_addr);
  if(j==2&&getenv("FIXTURE_BAD_RAW"))raw=lookup(RTLD_NEXT,"fixture_free");
  const struct ee_native_export *original_pin=fixture_original_pins+j;
  if(raw!=(void*)((uintptr_t)original.dli_fbase+original_pin->va)||!ee_code_identity(FIXTURE_UIPC,FIXTURE_UIPC_BYTES,FIXTURE_UIPC_SHA,(uintptr_t)original.dli_fbase,original_pin->va,original_pin->code))fatal("fixture original UIPC identity");
  olds[j]=old;unsigned calls=fixture_interposed_dlsym_calls;
  assert(ee_slot_original(info->dlpi_addr,raw,raw,plt,n,&ee_native_pins)==raw);
  assert(!ee_slot_original(info->dlpi_addr,old,raw,plt,"osal_snd_msg",&ee_native_pins));
#ifdef FIXTURE_LEGACY_GUARD
  selected[j]=slot_matches(info->dlpi_addr,old,raw,plt)?raw:0;
#elif defined(FIXTURE_OLD_ADAPTER)
  /* Exact old early branch; resolved slots share the unchanged strict pin checks. */
  selected[j]=slot_matches(info->dlpi_addr,old,raw,plt)?raw:ee_slot_original(info->dlpi_addr,old,raw,plt,n,&ee_native_pins);
#else
  selected[j]=ee_slot_original(info->dlpi_addr,old,raw,plt,n,&ee_native_pins);
#endif
  assert(calls==fixture_interposed_dlsym_calls);
  if(!selected[j])ee_guard_api("GOT-slot",n,info->dlpi_addr+offsets[j],(uintptr_t)raw,(uintptr_t)old);
 }
 assert(count==3);
 if(getenv("FIXTURE_LOADER_ONLY"))return 0;
 for(unsigned j=0;j<3;j++){
  ee_got(info->dlpi_addr,offsets[j],names[j],wrappers[j],originals[j],olds[j],selected[j]);
  assert(*(void**)(info->dlpi_addr+offsets[j])==wrappers[j]&&*originals[j]==selected[j]);
  fprintf(stderr,"HOST_GOT_COMMITTED name=%s old=%p selected=%p wrapper=%p\n",names[j],olds[j],selected[j],wrappers[j]);
 }
 return 0;
}
'''
PLUGIN = r'''
#include "chain.h"
uintptr_t Application_System_Init(void){fixture_original_init++;return 0xfedcba9876543210UL;}
void fixture_dso_calls(uintptr_t msg){
 errno=31;assert(osal_get_msg_src(msg)==0x90bf0274&&errno==49);
 errno=31;assert(osal_msg_size(msg)==fixture_msg_size&&errno==50);
 errno=31;assert(osal_free_msg(fixture_owner,msg)==(fixture_model_mode?0:-28)&&errno==51);
}
'''

# Synthetic eight-slot model: proves host routing/retirement only, never Sony semantics.
MODEL_NATIVE = r'''
static unsigned model_leases[8];
uintptr_t fixture_model_allocate(void){
 for(unsigned i=0;i<8;i++)if(!model_leases[i]){
  model_leases[i]=1;fixture_model_queued++;fixture_model_live++;
  return fixture_packet=(uintptr_t)fixture_model_packets[i];
 }
 return 0;
}
'''
MODEL_FREE = r'''
fixture_native[FREE]++;int saved=errno;
if(owner==0x5503e0&&fixture_msg_size==32)fprintf(stderr,"FULL_INPUT_FREE_ENTER owner=%#x message=%#lx\n",owner,msg);
errno=saved;int32_t result=free_next(owner,msg);saved=errno;
if(fixture_model_mode&&result==0){
 unsigned retired=0;assert(owner==0x5503e0);
 for(unsigned i=0;i<8;i++)if(model_leases[i]&&msg==(uintptr_t)fixture_model_packets[i]){
  model_leases[i]=0;fixture_model_retired++;fixture_model_live--;retired++;
 }
 assert(retired==1);
}
errno=saved;return result;
'''
MODEL_APP = r'''
 if(fixture_model_mode){
  uintptr_t(*allocate)(void)=dlsym(RTLD_DEFAULT,"fixture_model_allocate");assert(allocate);
  void(*consume)(uintptr_t)=dlsym(handle,"fixture_dso_calls");assert(consume);
  unsigned *native=dlsym(RTLD_DEFAULT,"fixture_native"),*usb=dlsym(RTLD_DEFAULT,"fixture_usb");assert(native&&usb);
  unsigned accepted=0,raw_route=!!getenv("FIXTURE_EXPECT_RAW");
  for(unsigned i=0;i<9;i++){
   uintptr_t msg=allocate();if(!msg){assert(raw_route&&i==8);break;}
   consume(msg);accepted++;
   assert(fixture_original[FREE]==accepted&&usb[FREE]==accepted);
   assert(native[FREE]==(raw_route?0:accepted)&&fixture_model_retired==(raw_route?0:accepted));
   printf("MODEL_STEP n=%u queued=%u retired=%u live=%u native=%u raw=%u\n",accepted,fixture_model_queued,fixture_model_retired,fixture_model_live,native[FREE],fixture_original[FREE]);
  }
  assert(accepted==(raw_route?8:9)&&fixture_model_live==(raw_route?8:0));
  printf("MODEL_SUMMARY accepted=%u native=%u raw=%u retired=%u live=%u ninth=%s synthetic=1\n",accepted,native[FREE],fixture_original[FREE],fixture_model_retired,fixture_model_live,accepted==9?"accepted":"refused");
  return 0;
 }
'''


def elf_window(path, va, size):
    import struct
    image = path.read_bytes()
    phoff = struct.unpack_from('<Q', image, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', image, 54)
    segments = [struct.unpack_from('<IIQQQQQQ', image, phoff + i * phsize) for i in range(phnum)]
    offsets = [off + va - start for kind, _, off, start, _, count, _, _ in segments
               if kind == 1 and start <= va and va + size <= start + count]
    if len(offsets) != 1:
        raise AssertionError((path, va, offsets))
    return image[offsets[0]:offsets[0] + size]


def elf_lazy_plt(path):
    text = subprocess.run(['readelf', '-rW', str(path)], check=True, capture_output=True, text=True, timeout=10).stdout
    slots = {}
    for line in text.splitlines():
        row = line.split()
        if len(row) >= 5 and row[2].endswith('JUMP_SLOT') and row[4] in BUILD['EE_IMPORTS']:
            slots[row[4]] = int.from_bytes(elf_window(path, int(row[0], 16), 8), 'little')
    if set(slots) != set(BUILD['EE_IMPORTS']):
        raise AssertionError(slots)
    sections = subprocess.run(['readelf', '-SW', str(path)], check=True, capture_output=True, text=True, timeout=10).stdout
    plt_ranges = [(int(start, 16), int(size, 16)) for start, size in re.findall(
        r'\[\s*\d+\]\s+\.plt(?:\.sec)?\s+PROGBITS\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)', sections)]
    for va in slots.values():
        if not any(start <= va < start + size for start, size in plt_ranges) or not elf_window(path, va, 4):
            raise AssertionError((va, plt_ranges))
    return [slots[name] for name in BUILD['EE_IMPORTS']]


def elf_symbol(path, name):
    text = subprocess.run(['readelf', '-Ws', str(path)], check=True, capture_output=True, text=True, timeout=10).stdout
    found = {int(va, 16) for va, symbol in re.findall(r'^\s*\d+:\s+([0-9a-f]+)\s+\d+\s+(?:FUNC|OBJECT)\s+\w+\s+DEFAULT\s+\d+\s+(\w+)\s*$', text, re.M) if symbol == name}
    if len(found) != 1:
        raise AssertionError((name, found))
    return found.pop()


class NativeGotAdapter(unittest.TestCase):
    def test_real_app_dso_got_preserves_native_chain_and_rejects_drift(self):
        versions = {'x86_64': 'GLIBC_2.2.5', 'aarch64': 'GLIBC_2.17'}
        if os.uname().machine not in versions:
            self.skipTest('glibc host fixture supports x86_64/AArch64')
        version = versions[os.uname().machine]
        evidence = []
        destination = os.environ.get('A7C2_USB_NATIVE_GOT_EVIDENCE')
        if destination:
            self.addCleanup(lambda: Path(destination).write_text('\n'.join(evidence)))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(destination).parent / 'adapter-host-fixture' if destination else Path(folder)
            root.mkdir(exist_ok=True)
            header = BASE['CHAIN_HEADER'].replace('fixture_message[12]', 'fixture_message[32]') + r'''
extern uint32_t fixture_owner;extern int32_t fixture_msg_size;
extern int fixture_model_mode;extern uintptr_t fixture_packet;
extern unsigned char fixture_model_packets[8][32];
extern unsigned fixture_model_queued,fixture_model_retired,fixture_model_live,fixture_interposed_dlsym_calls;
'''
            (root / 'chain.h').write_text(header)
            (root / 'host.map').write_text((HERE / 'usb-start-observe.map').read_text().replace('GLIBC_2.17', version))
            native = BASE['CHAIN_NATIVE'].replace('#include "chain.h"', '#include "chain.h"\n' + MODEL_NATIVE)
            native = native.replace('fixture_native[FREE]++;return free_next(owner,msg);', MODEL_FREE)
            native = native.replace('free_next=native_lookup(RTLD_NEXT,"osal_free_msg");',
                                    'free_next=native_lookup(RTLD_NEXT,"osal_free_msg");if(getenv("FIXTURE_BAD_NATIVE_CACHE"))free_next=fixture_free;')
            native = native.replace('void *dlsym(void *handle,const char *name){',
                                    'unsigned fixture_interposed_dlsym_calls;\nvoid *dlsym(void *handle,const char *name){fixture_interposed_dlsym_calls++;')
            uipc = BASE['CHAIN_UIPC'].replace('unsigned char fixture_message[12]', 'uint32_t fixture_owner=0x80021111;int32_t fixture_msg_size=12;\nunsigned char fixture_message[32]')
            uipc = uipc.replace('static struct fixture_taps taps;',
                                'int fixture_model_mode;unsigned fixture_model_queued,fixture_model_retired,fixture_model_live;uintptr_t fixture_packet=(uintptr_t)fixture_message;unsigned char fixture_model_packets[8][32];\nstatic struct fixture_taps taps;')
            uipc = uipc.replace('owner==0x80021111', 'owner==fixture_owner').replace('errno=50;return 12;', 'errno=50;return fixture_msg_size;')
            uipc = uipc.replace('msg==(uintptr_t)fixture_message', 'msg==fixture_packet').replace('return -28;', 'return fixture_model_mode?0:-28;')
            app = BASE['CHAIN_APP'].replace('fixture_queue_rc=atoi(argv[1]);',
                'fixture_queue_rc=atoi(argv[1]);fixture_owner=fixture_queue_rc?0x5503e0:0x80021111;fixture_msg_size=fixture_queue_rc?32:12;fixture_model_mode=!!getenv("FIXTURE_MODEL");\n'
                'if(getenv("FIXTURE_TAMPER_UIPC")){FILE*f=fopen(FIXTURE_UIPC,"ab");assert(f);fputc(0,f);fclose(f);}')
            app = app.replace('RTLD_NOW|RTLD_LOCAL|RTLD_DEEPBIND', '(getenv("FIXTURE_LAZY")?RTLD_LAZY:RTLD_NOW)|RTLD_LOCAL|RTLD_DEEPBIND')
            app = app.replace(' uintptr_t out=0,msg=0;', MODEL_APP + '\n uintptr_t out=0,msg=0;')
            start = app.index(' errno=31;assert(osal_get_msg_src(msg)')
            end = app.index(' errno=31;assert(osal_snd_msg', start)
            app = app[:start] + ' void(*consume)(uintptr_t)=dlsym(handle,"fixture_dso_calls");assert(consume);consume(msg);\n' + app[end:]
            app = app.replace('const unsigned expected_native[]={1,1,0,0,1,1},expected_usb[]={1,1,1,1,1,0};',
                              'unsigned expect_native=!getenv("FIXTURE_EXPECT_RAW"),expect_usb=!getenv("FIXTURE_LOADER_ONLY");\n const unsigned expected_native[]={1,1,0,0,expect_native,1},expected_usb[]={1,1,expect_usb,expect_usb,expect_usb,0};')
            app = app.replace(' printf("REG native=', r'''
 printf("FREE native=%u usb=%u raw=%u\n",native[FREE],usb[FREE],fixture_original[FREE]);
 if(getenv("FIXTURE_LOADER_ONLY")){
  void*(*binding)(void)=dlsym(RTLD_DEFAULT,"fixture_read_free_binding");assert(binding);
  assert(binding()==dlsym(RTLD_DEFAULT,"osal_free_msg"));
  printf("UNPATCHED_LAZY_RESOLVED_TO_GLOBAL=1\n");
 }
 printf("REG native=''' )
            targets = {name: root / ('app' if name == 'app' else 'libfixture-uipc.so' if name == 'uipc' else name + '.so')
                       for name in ('uipc', 'native', 'native_raw', 'usb', 'legacy', 'oldadapter', 'plugin', 'app', 'unknown')}

            def build(name, source, extra=()):
                path = root / (name + '.c');path.write_text(source)
                command = ['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Wno-unused-function', '-Wno-unused-variable',
                           '-I', str(root), '-I', str(HERE), '-DHOST_DLSYM_VERSION="' + version + '"',
                           '-DFIXTURE_UIPC="' + str(targets['uipc']) + '"', '-DFIXTURE_APP="' + str(targets['plugin']) + '"',
                           *(['-shared', '-fPIC'] if name != 'app' else []), *extra, str(path),
                           *(['-L', str(root), '-lfixture-uipc', '-Wl,-rpath,$ORIGIN'] if name != 'uipc' else []),
                           *(['-Wl,--version-script=' + str(root / 'host.map')] if name in ('usb', 'legacy', 'oldadapter') else []),
                           '-Wl,-z,' + ('lazy' if name == 'plugin' else 'now'), '-ldl', '-o', str(targets[name])]
                result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                evidence.append('BUILD ' + name + ' ' + repr(command) + '\nrc=' + str(result.returncode) + '\n' + result.stdout + result.stderr)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            for name, source in (('uipc', uipc), ('native', native), ('native_raw', native.replace('int32_t osal_free_msg(', 'int32_t fixture_unexported_free(')), ('plugin', PLUGIN), ('app', app),
                                 ('unknown', '#include "chain.h"\nint32_t osal_free_msg(uint32_t q,uintptr_t m){(void)q;(void)m;abort();}\n')):
                build(name, source)
            native_va = elf_symbol(targets['native'], 'osal_free_msg')
            native_cache = elf_symbol(targets['native'], 'free_next')
            # Host fixture LOAD has equal file/virtual offsets; assert this instead of assuming it.
            import struct
            image = targets['native'].read_bytes()
            phoff = struct.unpack_from('<Q', image, 32)[0];phnum = struct.unpack_from('<H', image, 56)[0]
            segments = [struct.unpack_from('<IIQQQQQQ', image, phoff + i * 56) for i in range(phnum)]
            offsets = [off + native_va - va for kind, _, off, va, _, size, _, _ in segments if kind == 1 and va <= native_va and native_va + 16 <= va + size]
            self.assertEqual(len(offsets), 1)
            pins = dict(guest_path=str(targets['native']), bytes=len(image), sha256=hashlib.sha256(image).hexdigest(),
                        exports=[dict(name='osal_free_msg', va=native_va, cached_va=native_cache, code_hex=image[offsets[0]:offsets[0]+16].hex())])
            guard = (HERE / 'usb-ee-zero-observe.inc').read_text()
            guard = guard[guard.index('static void ee_guard_api('):guard.index('static void ee_install(')]
            usb = BASE['CHAIN_USB'].replace('/* GUARD_IMPLEMENTATION */', '#include "fixture-pins.h"\n' + guard + INSPECT)
            usb = usb.replace('if(fixture_usb_installed)return;', 'if(fixture_usb_installed)return;dl_iterate_phdr(inspect_got,0);')
            usb = usb.replace('ee_real_size=fixture_size;ee_real_free=fixture_free;', '')
            usb = usb.replace('ee_real_queue=fixture_queue;ee_real_recv=fixture_recv;ee_real_source=fixture_source;',
                              'ee_real_queue=fixture_queue;ee_real_recv=fixture_recv;')
            usb = usb.replace('{tap_queue,tap_recv,tap_source,tap_size,tap_free}', '{tap_queue,tap_recv,0,0,0}')
            usb = usb.replace('memfd=open("/proc/self/mem",O_RDONLY);', 'logfd=memfd_create("usb-host-log",0);assert(logfd>=0);memfd=open("/proc/self/mem",O_RDONLY);')
            production = (HERE / 'usb-start-observe.c').read_text()
            loader = production[production.index('static void *usb_loader_dlopen('):production.rindex('\n#endif')]
            loader = loader.replace('void *handle=next_dlopen(name,flags);', 'fixture_usb_dlopen++;void *handle=next_dlopen(name,flags);')
            usb = usb[:usb.index('void *dlopen(')] + loader
            original_uipc = targets['uipc'].read_bytes()
            original_headers = []
            for name in BUILD['EE_IMPORTS']:
                va = elf_symbol(targets['uipc'], name)
                phoff = struct.unpack_from('<Q', original_uipc, 32)[0];phnum = struct.unpack_from('<H', original_uipc, 56)[0]
                segments = [struct.unpack_from('<IIQQQQQQ', original_uipc, phoff + i * 56) for i in range(phnum)]
                offsets = [off + va - start for kind, _, off, start, _, size, _, _ in segments if kind == 1 and start <= va and va + 16 <= start + size]
                self.assertEqual(len(offsets), 1)
                code = original_uipc[offsets[0]:offsets[0]+16]
                original_headers.append('{"' + name + '",' + hex(va) + ',0,{' + ','.join(map(str, code)) + '}}')
            original_header = 'static const struct ee_native_export fixture_original_pins[]={' + ','.join(original_headers) + '};\n'
            original_header += 'static const unsigned fixture_plt[]={' + ','.join(map(hex, elf_lazy_plt(targets['plugin']))) + '};\n'
            evidence.append('REAL ELF ON-DISK INITIAL APP PLT OFFSETS ' + repr(elf_lazy_plt(targets['plugin'])))

            extra = ['-DFIXTURE_UIPC_BYTES=' + str(len(original_uipc)), '-DFIXTURE_UIPC_SHA="' + hashlib.sha256(original_uipc).hexdigest() + '"']

            def compile_pins(contract, name='usb', legacy=False):
                (root / 'fixture-pins.h').write_text(BUILD['native_forwarder_header'](contract) + original_header)
                build(name, usb, [*extra, *(['-DFIXTURE_LEGACY_GUARD=1'] if legacy else []),
                                  *(['-DFIXTURE_OLD_ADAPTER=1'] if name == 'oldadapter' else [])])

            def execute(label, key='usb', rc=0, unknown=False, tamper=False, lazy=False,
                        native_raw=False, model=False, loader_only=False, bad_raw=False, bad_cache=False):
                preload = [*([str(targets['unknown'])] if unknown else []), str(targets['native_raw' if native_raw else 'native']), str(targets[key])]
                env = dict(os.environ, LD_PRELOAD=':'.join(preload))
                env.pop('LD_BIND_NOW', None)
                flags = dict(FIXTURE_TAMPER_UIPC=tamper, FIXTURE_LAZY=lazy, FIXTURE_MODEL=model,
                             FIXTURE_LOADER_ONLY=loader_only, FIXTURE_BAD_RAW=bad_raw, FIXTURE_BAD_NATIVE_CACHE=bad_cache,
                             FIXTURE_EXPECT_RAW=native_raw or key == 'oldadapter')
                for flag, enabled in flags.items():
                    env.pop(flag, None)
                    if enabled:
                        env[flag] = '1'
                result = subprocess.run([str(targets['app']), str(rc), str(targets['plugin'])],
                    env=env, capture_output=True, text=True, timeout=10)
                evidence.append(label + '\nrc=' + str(result.returncode) + '\n' + result.stdout + result.stderr)
                return result

            compile_pins(pins, 'legacy', True)
            old = execute('CORRECT LOADER ORIGINAL SLOT GUARD', key='legacy')
            self.assertEqual(old.returncode, 79, old.stdout + old.stderr)
            self.assertIn('EE GOT-slot api=osal_free_msg', old.stderr)
            self.assertIn('binding=' + str(targets['native']), old.stderr)
            compile_pins(pins)
            for label, kwargs, counters in (
                ('UNPATCHED REAL LAZY LOADER', dict(lazy=True, loader_only=True), 'FREE native=1 usb=0 raw=1'),
                ('LAZY RAW GLOBAL', dict(lazy=True, native_raw=True), 'FREE native=0 usb=1 raw=1'),
                ('RESOLVED RAW GLOBAL', dict(native_raw=True), 'FREE native=0 usb=1 raw=1'),
                ('LAZY NATIVE GLOBAL', dict(lazy=True), 'FREE native=1 usb=1 raw=1')):
                result = execute(label, **kwargs)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(counters, result.stdout)
                if kwargs.get('lazy'):
                    self.assertIn('lazy=1 oldInApp=1', result.stderr)
                if kwargs.get('loader_only'):
                    self.assertIn('UNPATCHED_LAZY_RESOLVED_TO_GLOBAL=1', result.stdout)
                if not kwargs.get('native_raw'):
                    self.assertIn('originalGlobalDefaultFree=' + str(targets['native']), result.stderr)
            compile_pins(pins, 'oldadapter')
            bypass = execute('OLD HEADER LAZY NATIVE BYPASS', key='oldadapter', lazy=True, rc=-19)
            self.assertEqual(bypass.returncode, 0, bypass.stdout + bypass.stderr)
            self.assertIn('originalGlobalDefaultFree=' + str(targets['native']), bypass.stderr)
            self.assertIn('lazy=1 oldInApp=1', bypass.stderr)
            self.assertIn('FREE native=0 usb=1 raw=1', bypass.stdout)
            self.assertNotIn('FULL_INPUT_FREE_ENTER', bypass.stderr)
            for key in ('oldadapter', 'usb'):
                result = execute('SYNTHETIC EIGHT LEASES ' + key, key=key, lazy=True, model=True, rc=-19)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                expected = ('accepted=8 native=0 raw=8 retired=0 live=8 ninth=refused' if key == 'oldadapter' else
                            'accepted=9 native=9 raw=9 retired=9 live=0 ninth=accepted')
                self.assertIn('MODEL_SUMMARY ' + expected + ' synthetic=1', result.stdout)
                self.assertEqual(result.stderr.count('FULL_INPUT_FREE_ENTER'), 0 if key == 'oldadapter' else 9)
            for rc in (0, -19):
                result = execute('FINITE ADAPTER rc=' + str(rc), rc=rc)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for name in ('osal_get_msg_src', 'osal_msg_size', 'osal_free_msg'):
                    self.assertIn('APP_DSO_GOT name=' + name, result.stderr)
                self.assertIn('REG native=1 usb=1 original=1 callback=1', result.stdout)
                self.assertIn('usb_preinit=1 native_selected=1 native_init=1 original_init=1', result.stdout)
                self.assertEqual(result.stderr.count('USB_EE FREE_ENTER'), 1)
                self.assertEqual(result.stderr.count('USB_EE FREE_RETURN'), 1)
                self.assertEqual(result.stderr.count('FULL_INPUT_FREE_ENTER'), int(rc != 0))
                self.assertIn('rc=-28 errno=51', result.stderr)
            for field, value in (('sha256', '0'*64), ('va', native_va+1), ('code_hex', '00'*16), ('cached_va', native_cache+8)):
                changed = json.loads(json.dumps(pins))
                (changed if field == 'sha256' else changed['exports'][0])[field] = value
                compile_pins(changed)
                for lazy in (False, True):
                    failed = execute('REJECT native ' + field + ' lazy=' + str(lazy), lazy=lazy)
                    self.assertEqual(failed.returncode, 79, failed.stdout + failed.stderr)
                    self.assertIn('EE GOT-slot api=osal_free_msg', failed.stderr)
                    self.assertNotIn('GOT_ARMED', failed.stderr)
                    self.assertNotIn('HOST_GOT_COMMITTED', failed.stderr)
            compile_pins(pins)
            for label, kwargs in (('REJECT unknown shim', dict(unknown=True)), ('REJECT changed original UIPC', dict(tamper=True)),
                                  ('REJECT wrong original raw function', dict(bad_raw=True)), ('REJECT wrong native cached function', dict(bad_cache=True))):
                for lazy in (False, True):
                    failed = execute(label + ' lazy=' + str(lazy), lazy=lazy, **kwargs)
                    targets['uipc'].write_bytes(original_uipc)
                    self.assertEqual(failed.returncode, 79, failed.stdout + failed.stderr)
                    self.assertNotIn('GOT_ARMED', failed.stderr)
                    self.assertNotIn('HOST_GOT_COMMITTED', failed.stderr)
            evidence.append('HOST ONLY: production ee_code_identity/ee_slot_original/ee_got and loader; real RTLD_LAZY/RTLD_NOW host ELF PLT slots and global resolver, synthetic eight-slot retirement model. No Sony AP/AArch64 execution; actualRootCause=unknown.')


if __name__ == '__main__':
    unittest.main()
