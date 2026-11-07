#!/usr/bin/env python3
"""Explicit, no-install original P1 FAT input observation; local QEMU only.

The frozen file-media hook supplies the functional file adapter. The separate
observer below only reports original returns, errno and /proc state.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess

HERE = Path(__file__).resolve().parent
PROFILE = 'original-p1-sd-readonly-v1'
INSTALL_PROFILE = 'original-p1-virtual-install-v1'
HOOK_SHA = 'f0f359603d69b85b14acac6051809c0d61a8db722c04e7fd8f512b4d98add852'
DSO_SHA = '30925f265910eded6d95e7e7d9635b2f8e17272763b861377786cbe0d1c4c72a'
QEMU_SHA = '2c4ea6c9343771225915c604c4ab81ec2f45bb922e3365931710e295c4d9d83c'
STOCK_SHA = 'eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'
ENV = {'A7C2_FILE_MEDIA_TEST': '1', 'A7C2_P1_FILE_MEDIA_PROFILE': 'original-sd-v1'}
PRELOAD = '/simulation/p1-sd-observer.so\n/simulation/file-media-config.so\n'
TRUST_PROFILE = 'virtual-p1-pinned-key-v1'
TRUST_ENV = 'A7C2_P1_TRUST_PROFILE'
KEY = ('etc/VerificationKey.pem', 451, '8281413b5607446939613e07d020b2c7d8ee2371349099de56bc8288f7be0a43')
CRYPTO = ('usr/lib/libcrypto.so.1.1', 2349584, 'df69906d5f63a3afe9b7872e41cab741c346630e53ebcaadb86e457f0b803726')
UIPC = ('usr/lib/libosal_uipc.so', 47848, '2d899fdbb3befed231f05ae7efd1a3689921e07e1125527d1c9fc602a67ebbec')
SKD = ('usr/lib/libInfraSKD.so', 8020712, '8052390d5d043db47dd0aa83b3f65be7ec980288c5c72c01f46229b597b12f20')
TRUST_SOURCES = ('p1-trust-key.c', 'p1-trust-key.h', 'p1-trust-key.inc')
PASSIVE_WINDOWS = (
    ('sd', 0x9368, 0x94c4, '4875b2a51def1876a691b140a42249a57ee4646c07c765afbaaf5c15e569b21e'),
    ('sd', 0x9508, 0x9624, 'b16c6cfd3abbc869dba05a445cfc4280b9368f70e0a3113c3f01e307c693cb98'),
    ('sd', 0x96a8, 0x9ae4, 'acec7a191f8f4dd36ee91ad235e3f5569d41c3a1b9c589b354444f3ff8555604'),
    ('core', 0xb584, 0xb6a4, '1dfbf21d8b245d9e87cfd14087662547c0960e0e00b81d6ce65fefc647d31c3a'),
)
VERIFY_SUM = '_ZN7Updater15DecryptorModule9verifySumEv'

# No redirects, emulated returns, ACKs, node creation or writes to input/targets.
OBSERVER = r'''
#include <stdarg.h>
#include <stddef.h>
extern char *getenv(const char *);
extern void *dlvsym(void *,const char *,const char *);
extern int *__errno_location(void), getpid(void), close(int), snprintf(char *,size_t,const char *,...);
extern long write(int,const void *,unsigned long), read(int,void *,unsigned long);
extern int strcmp(const char *,const char *), readlink(const char *,char *,unsigned long);
static void *next(const char *s) {
    void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
    return lookup ? lookup((void *)-1,s) : 0;
}
static int selected(void) {
    int (*op)(const char *,int,...)=next("open");
    char name[32];int fd=op?op("/proc/self/comm",0):-1;
    long n=fd>=0?read(fd,name,31):-1;if(fd>=0)close(fd);
    if(n<0)return 0;name[n]=0;if(strcmp(name,"sdfileinput.elf\n"))return 0;
    char exe[128];n=readlink("/proc/self/exe",exe,127);if(n<0)return 0;exe[n]=0;
    return !strcmp(exe,"/usr/bin/sdfileinput.elf");
}
static void logline(const char *text) {
    int saved=*__errno_location();
    int (*op)(const char *,int,...)=next("open");
    int fd=op?op("/dev/console",1):-1;
    if(fd>=0){unsigned n=0;while(text[n])n++;write(fd,text,n);close(fd);}
    *__errno_location()=saved;
}
static int watched(const char *p) {
    return p && (!strcmp(p,"/dev/mcmn") || !strcmp(p,"/dev/stream2") ||
        !strcmp(p,"/dev/mmca") || !strcmp(p,"/nondev/rm2") || !strcmp(p,"/image_mmca"));
}
static int opened(const char *symbol,const char *path,int flags,unsigned mode,void *caller) {
    int before=*__errno_location();
    int (*fn)(const char *,int,...)=next(symbol);
    if(!fn)__builtin_trap();
    *__errno_location()=before;
    /* This exported frame owns the original LR, including the no-Tail profile. */
    const char *profile=getenv("A7C2_P1_PMBP_PROFILE");
    int route=profile && path && !strcmp(path,"/image_nflasha23");
    int (*broker)(const char *,int,unsigned,unsigned long)=0;
    if(route) {
        if(strcmp(profile,"virtual-p1-pmbp-block-slice-v1")){*__errno_location()=71;return -1;}
        const void *(*native)(void)=next("pmbp_native_io");
        broker=next("pmbp_open64_at");
        if(!native || !broker || !native()){*__errno_location()=71;return -1;}
    }
    *__errno_location()=before;
    int rc=route ? broker(path,flags,mode,(unsigned long)caller) : fn(path,flags,mode);
    int error=*__errno_location();
    if(watched(path) && selected()) {
        char line[300];snprintf(line,sizeof line,
          "P1_SD_NATIVE pid=%d op=%s path=%.100s flags=%x rc=%d errno=%d caller=%p callee=%p\n",
          getpid(),symbol,path,flags,rc,error,caller,fn);logline(line);
    }
    *__errno_location()=error;return rc;
}
int open(const char *path,int flags,...) {
    unsigned mode=0;if((flags&0x40) || (flags&0x410000)==0x410000){va_list ap;va_start(ap,flags);mode=va_arg(ap,unsigned);va_end(ap);}
    return opened("open",path,flags,mode,__builtin_return_address(0));
}
int open64(const char *path,int flags,...) {
    unsigned mode=0;if((flags&0x40) || (flags&0x410000)==0x410000){va_list ap;va_start(ap,flags);mode=va_arg(ap,unsigned);va_end(ap);}
    return opened("open64",path,flags,mode,__builtin_return_address(0));
}
void *mmap64(void *address,unsigned long length,int prot,int flags,int fd,long long offset) {
    int before=*__errno_location();
    void *(*fn)(void *,unsigned long,int,int,int,long long)=next("mmap64");if(!fn)__builtin_trap();
    *__errno_location()=before;
    void *rc=fn(address,length,prot,flags,fd,offset);int error=*__errno_location();
    if(selected()){char line[300];snprintf(line,sizeof line,
       "P1_SD_NATIVE pid=%d op=mmap64 fd=%d length=%lu offset=%lld rc=%p errno=%d caller=%p callee=%p\n",
       getpid(),fd,length,offset,rc,error,__builtin_return_address(0),fn);logline(line);}
    *__errno_location()=error;return rc;
}
int Fsys_Init(void) {
    int before=*__errno_location();int (*fn)(void)=next("Fsys_Init");if(!fn)__builtin_trap();
    *__errno_location()=before;int rc=fn(),error=*__errno_location();
    if(selected()){char line[220];snprintf(line,sizeof line,
       "P1_SD_NATIVE pid=%d op=Fsys_Init rc=%d errno=%d caller=%p callee=%p\n",
       getpid(),rc,error,__builtin_return_address(0),fn);logline(line);}
    *__errno_location()=error;return rc;
}
int Fsys_FindFirst(const char *path,int flags,void *output) {
    int before=*__errno_location();int (*fn)(const char *,int,void *)=next("Fsys_FindFirst");if(!fn)__builtin_trap();
    *__errno_location()=before;int rc=fn(path,flags,output),error=*__errno_location();
    if(selected()){char line[300];snprintf(line,sizeof line,
       "P1_SD_NATIVE pid=%d op=Fsys_FindFirst path=%.100s flags=%x rc=%d errno=%d caller=%p callee=%p\n",
       getpid(),path,flags,rc,error,__builtin_return_address(0),fn);logline(line);}
    *__errno_location()=error;return rc;
}
'''

# Passive Initialize observations; machine ABI is pinned below, opaque layouts stay opaque.
INIT_SYMBOLS = [
    ('manager', 'sd', '_ZN7Updater25SDFileInputUpdaterManager10InitializeEPKcS2_', 0x7df0, 636, 0x1d800),
    ('buffer', 'sd', '_ZN7Updater13BufferManager10InitializeEv', 0x9b38, 312, 0x1daa0),
    ('sdfile', 'sd', '_ZN7Updater13SDFileManager10InitializeEv', 0xa758, 236, 0x1dca0),
    ('module', 'core', '_ZN7Updater10BaseModule10InitializeEPNS_15BufferContainerEPS0_PNS_17CallbackInterfaceE', 0xb2dc, 164, 0x20678),
    ('information', 'core', '_ZN7Updater15CurrentFirmware14GetInformationEPN10UpdaterAPI22firmware_information_t11informationE', 0xc060, 728, 0x20c60),
    ('mountpoint', 'common', '_ZN7Updater10MountPoint5MountEPKcj', 0x7988, 88, 0x1d788),
]
CORE = ('usr/lib/libupdatercorecommon.so', 72864, 'b2b066b963a42d96556f811a773579eb16a0358de1b3a9206a1845c0df99bb74')
OBSERVER += r'''
extern int memcmp(const void *,const void *,unsigned long);
typedef struct {const char *file; void *base; const char *symbol; void *address;} Info;
extern int dladdr(const void *,Info *);
static unsigned diagnostic_lines;
static int init_identity;
static void event(const char *op,const char *phase,const void *a0,const void *a1,const void *a2,const void *a3,
                  long rc,int error,void *caller,void *callee) {
    if(!selected() || diagnostic_lines>=96)return;
    diagnostic_lines++;
    char line[500],result[32];Info ci={0},fi={0};
    if(!strcmp(op,"buffer_void") || !strcmp(op,"module_void") || !strcmp(op,"information_void"))snprintf(result,sizeof result,"void");
    else snprintf(result,sizeof result,"%ld",rc);
    dladdr(caller,&ci);dladdr(callee,&fi);
    snprintf(line,sizeof line,"P1_SD_INIT pid=%d op=%s phase=%s a0=%p a1=%p a2=%p a3=%p rc=%s errno=%d caller=%p callee=%p caller_va=%lx callee_va=%lx identity=%d source_class=original-passive\n",
       getpid(),op,phase,a0,a1,a2,a3,result,error,caller,callee,
       (unsigned long)caller-(unsigned long)ci.base,(unsigned long)callee-(unsigned long)fi.base,init_identity);
    logline(line);
}
struct InitPin {const char *op,*symbol,*path,*sha;unsigned long va,slot,length;unsigned char entry[728];};
static const struct InitPin init_pins[] = { /* __INIT_PINS__ */ };
static void init_check(void) __attribute__((constructor));
static void init_check(void) {
    int saved=*__errno_location();
    if(selected()) {
        int good=sizeof init_pins/sizeof init_pins[0]==6;char line[450];
        for(unsigned i=0;i<sizeof init_pins/sizeof init_pins[0];i++) {
            const struct InitPin *p=init_pins+i;void *fn=next(p->symbol);Info info={0};
            int ok=fn && dladdr(fn,&info) && !strcmp(info.file,p->path) &&
                (char *)fn==(char *)info.base+p->va && !memcmp(fn,p->entry,p->length);
            void *slot=ok?*(void **)((char *)info.base+p->slot):0;
            void *expected=0;
            void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
            if(lookup)expected=lookup(0,p->symbol);
            ok=ok && slot==expected;good=good&&ok;
            snprintf(line,sizeof line,"P1_SD_TAP pid=%d op=%s bound=%d original=%p slot=%p wrapper=%p path=%s sha256=%s entry=whole-checked\n",
                getpid(),p->op,ok,fn,slot,expected,p->path,p->sha);logline(line);
        }
        init_identity=good;
        void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
        const char *symbols[]={"mcmn_param_init","Fsys_Init","Fsys_FindFirst"};
        for(unsigned i=0;i<3;i++) {
            void *binding=lookup?lookup(0,symbols[i]):0;Info info={0};if(binding)dladdr(binding,&info);
            snprintf(line,sizeof line,"P1_SD_RESOLVE pid=%d op=%s resolved=%p path=%s before_manager=1\n",getpid(),symbols[i],binding,info.file?info.file:"unknown");logline(line);
        }
        snprintf(line,sizeof line,"P1_SD_READY pid=%d identity=%d taps=6 budget=96 source_class=original-passive\n",getpid(),good);logline(line);
    }
    *__errno_location()=saved;
}
#define WRAP_HEAD(sym,type) int before=*__errno_location(); type=next(sym); if(!fn)__builtin_trap(); void *caller=__builtin_return_address(0)
#define ENTER(op) event(op,"enter",a0,a1,a2,a3,0,before,caller,fn); *__errno_location()=before
#define LEAVE(op,rc) int error=*__errno_location(); event(op,"return",a0,a1,a2,a3,rc,error,caller,fn); *__errno_location()=error
int _ZN7Updater25SDFileInputUpdaterManager10InitializeEPKcS2_(void *a0,const char *a1,const char *a2) {
    void *a3=0; WRAP_HEAD("_ZN7Updater25SDFileInputUpdaterManager10InitializeEPKcS2_",int (*fn)(void *,const char *,const char *));
    ENTER("manager");int rc=fn(a0,a1,a2);LEAVE("manager",rc);return rc;
}
void _ZN7Updater13BufferManager10InitializeEv(void *a0) {
    void *a1=0,*a2=0,*a3=0;WRAP_HEAD("_ZN7Updater13BufferManager10InitializeEv",void (*fn)(void *));
    ENTER("buffer");fn(a0);LEAVE("buffer_void",0);
}
int _ZN7Updater13SDFileManager10InitializeEv(void *a0) {
    void *a1=0,*a2=0,*a3=0;WRAP_HEAD("_ZN7Updater13SDFileManager10InitializeEv",int (*fn)(void *));
    ENTER("sdfile");int rc=fn(a0);LEAVE("sdfile",rc);return rc;
}
void _ZN7Updater10BaseModule10InitializeEPNS_15BufferContainerEPS0_PNS_17CallbackInterfaceE(void *a0,void *a1,void *a2,void *a3) {
    WRAP_HEAD("_ZN7Updater10BaseModule10InitializeEPNS_15BufferContainerEPS0_PNS_17CallbackInterfaceE",void (*fn)(void *,void *,void *,void *));
    ENTER("module");fn(a0,a1,a2,a3);LEAVE("module_void",0);
}
void _ZN7Updater15CurrentFirmware14GetInformationEPN10UpdaterAPI22firmware_information_t11informationE(void *a0,void *a1) {
    void *a2=0,*a3=0;WRAP_HEAD("_ZN7Updater15CurrentFirmware14GetInformationEPN10UpdaterAPI22firmware_information_t11informationE",void (*fn)(void *,void *));
    ENTER("information");fn(a0,a1);LEAVE("information_void",0);
}
unsigned char _ZN7Updater10MountPoint5MountEPKcj(void *a0,const char *a1,unsigned flags) {
    void *a2=(void *)(unsigned long)flags,*a3=0;WRAP_HEAD("_ZN7Updater10MountPoint5MountEPKcj",unsigned char (*fn)(void *,const char *,unsigned));
    ENTER("mountpoint");unsigned char rc=fn(a0,a1,flags);LEAVE("mountpoint",rc);return rc;
}
int mount(const char *source,const char *target,const char *fs,unsigned long flags,const void *data) {
    int before=*__errno_location();int (*fn)(const char *,const char *,const char *,unsigned long,const void *)=next("mount");if(!fn)__builtin_trap();
    *__errno_location()=before;int rc=fn(source,target,fs,flags,data),error=*__errno_location();
    if(selected() && diagnostic_lines<96){diagnostic_lines++;char line[600];snprintf(line,sizeof line,
        "P1_SD_INIT pid=%d op=mount phase=return source=%.100s target=%.100s fs=%.30s flags=%lx data=%p rc=%d errno=%d caller=%p callee=%p identity=%d source_class=original-passive\n",
        getpid(),source?source:"-",target?target:"-",fs?fs:"-",flags,data,rc,error,__builtin_return_address(0),fn,init_identity);logline(line);}
    *__errno_location()=error;return rc;
}
void __cxa_throw(void *object,void *type,void (*destroy)(void *)) __attribute__((noreturn));
void __cxa_throw(void *object,void *type,void (*destroy)(void *)) {
    int saved=*__errno_location();void (*fn)(void *,void *,void (*)(void *))=next("__cxa_throw");if(!fn)__builtin_trap();
    if(selected() && diagnostic_lines<96){
        diagnostic_lines++;const char *name="opaque";unsigned code=0;int known=0;
        void *api=next("_ZTIN7Updater12ApiExceptionE");
        /* Only the pinned exact ApiException type permits its verified +8 u32/+12 u8 layout. */
        if(init_identity && type==api && object){name="Updater::ApiException";__builtin_memcpy(&code,(char *)object+8,4);known=1;}
        char line[450];snprintf(line,sizeof line,"P1_SD_EXCEPTION pid=%d object=%p type=%p name=%s code_known=%d code=%x destroy=%p caller=%p callee=%p errno=%d\n",
            getpid(),object,type,name,known,code,destroy,__builtin_return_address(0),fn,saved);logline(line);
    }
    *__errno_location()=saved;fn(object,type,destroy);__builtin_unreachable();
}
'''

RO_GUARD = r'''
extern int open(const char *,int,...),close(int),ioctl(int,unsigned long,...),printf(const char *,...);
extern char *getenv(const char *);
extern int strcmp(const char *,const char *);
static int run(int argc,char **argv) {
    const char *a=getenv("A7C2_FILE_MEDIA_TEST"),*b=getenv("A7C2_P1_FILE_MEDIA_PROFILE");
    if(argc!=21 || !a || !b || strcmp(a,"1") || strcmp(b,"original-sd-v1"))return 125;
    int failed=0;
    for(int i=1;i<argc;i++) {
        int fd=open(argv[i],0),ro=0,rc=fd<0?-1:ioctl(fd,0x125eUL,&ro);
        printf("UPDATE_SD_TARGET_RO node=%s get_rc=%d readonly=%d\n",argv[i],rc,ro);
        if(fd>=0)close(fd);if(rc || ro!=1)failed=1;
    }
    return failed?125:0;
}
'''


def api():
    return runpy.run_path(str(HERE / 'update-boot.py'))


def admit(profile, *, mode, read_only, media, sd, module):
    if profile == INSTALL_PROFILE:
        runpy.run_path(str(HERE / 'newp1-virtual-install.py'))['admit'](profile, mode=mode,
            read_only=read_only, allow_updater_writes=True, media=media, sd=sd, module=module)
        return
    if profile != PROFILE or mode != 'official' or read_only is not True or not media or sd is None:
        raise ValueError('SD read profile requires explicit official/media/SD/read-only/no-install combination')
    if module.get('module_sha256') != api()['CURRENT_MODULE_SHA'] or not module.get('large_io_fix_bound'):
        raise ValueError('SD read profile requires fixed original-p1 module')


def package(path, output):
    # Inspection only: never call install_sd/apply_stream/decode to target images.
    v = runpy.run_path(str(HERE / 'virtual-update.py'))
    source = v['_Source'](path)
    fd = v['FAT'].secure_open(output, directory=True)
    try:
        result = v['_inspect_package'](source, fd)
        source.verify()
        if result['sha256'] != STOCK_SHA or result['signature']['status'] != 'valid':
            raise ValueError('SD read profile requires exact local official 2.01 signed BODYDATA')
        return result
    finally:
        os.close(fd)
        source.close()


def single_body_fat(image, output):
    with api()['FAT']['FatImage'](image, output, mtools_dir='/usr/bin', fmask=0, dmask=0,
                                max_file_bytes=2*1024**3, max_total_bytes=3*1024**3) as fat:
        entries=fat.inventory()['entries']
        if (set(entries) != {'/', '/BODYDATA.DAT'} or entries['/']['kind'] != 'dir'
                or entries['/BODYDATA.DAT']['kind'] != 'file' or fat.bits != 32):
            raise ValueError('SD read profile requires a single root BODYDATA.DAT on FAT32')


def initialize_contract(root):
    """Exact DSO hashes + exports/vtable relocations; never infer ABI from names."""
    root = Path(root)
    original = runpy.run_path(str(HERE / 'p1-file-media-contract.py'))
    original['inspect'](root)
    samples = dict(original['SAMPLES'], core=CORE)
    core = (root / CORE[0]).read_bytes()
    if len(core) != CORE[1] or hashlib.sha256(core).hexdigest() != CORE[2]:
        raise ValueError('P1 Initialize identity differs: ' + CORE[0])
    exports = {}
    pins = []
    for op, sample, symbol, va, size, slot in INIT_SYMBOLS:
        relative, _, digest = samples[sample]
        if sample not in exports:
            exports[sample] = subprocess.check_output(['readelf', '-WdWrWs', str(root / relative)], text=True)
        elf = exports[sample]
        if ('SYMBOLIC' in elf or not re.search(
                rf'\b{va:016x}\s+{size}\s+FUNC\s+GLOBAL\s+DEFAULT\s+\d+\s+{symbol}\s', elf)
                or not re.search(rf'{slot:016x}\s+\S+\s+R_AARCH64_ABS64\s+{va:016x}\s+{symbol}\s+\+ 0', elf)):
            raise ValueError('P1 Initialize export/relocation differs: ' + op)
        data = (root / relative).read_bytes()
        offset = original['va_offset'](data, va, size)
        code = data[offset:offset + size]
        pins.append(dict(op=op, symbol=symbol, path='/' + relative, sha256=digest,
                         va=va, size=size, slot=slot, text_sha256=hashlib.sha256(code).hexdigest(), code=code.hex()))
    return dict(schema='p1-sd-initialize-passive-v1', pins=pins, core=dict(path=CORE[0], bytes=CORE[1], sha256=CORE[2]))


def effective_env(trust_profile=None, inherited=None, *, newdecrypt_profile=None, tail_profile=None, pmbp_profile=None):
    """Clear inherited model activation; only an explicit option can enable it."""
    if trust_profile not in (None, TRUST_PROFILE):
        raise ValueError('Unknown P1 trust profile')
    result = dict(inherited or {})
    result.pop(TRUST_ENV, None)
    result.update(ENV)
    if trust_profile is not None:
        result[TRUST_ENV] = trust_profile
    if newdecrypt_profile is not None and trust_profile != TRUST_PROFILE:
        raise ValueError('P1 CBC profile requires the explicit pinned-key service')
    result.pop('A7C2_P1_CBC_PROFILE', None)
    result.pop('A7C2_P1_TAIL_PROFILE', None)
    result.pop('A7C2_P1_TAIL_PMBP_PROFILE', None)
    if pmbp_profile is not None and tail_profile is None:raise ValueError('PMBP tail env requires explicit tail')
    if tail_profile is not None:
        if trust_profile != TRUST_PROFILE:raise ValueError('Tail requires explicit pinned-key trust')
        result = tail_api()['effective_env'](tail_profile, result, pmbp_profile=pmbp_profile)
    if newdecrypt_profile is None:
        return result
    model = newdecrypt_api()
    return model['effective_env'](model['selection'](newdecrypt_profile), result)


def _trust_contract(root, receiver_proof=None):
    """Internal pin construction; public stock/dev admission stays separate."""
    root = Path(root)
    original = runpy.run_path(str(HERE / 'p1-file-media-contract.py'))
    sd = original['SAMPLES']['sd']
    files = {}
    for relative, length, digest in (sd, KEY, CRYPTO, UIPC, SKD, CORE):
        if relative == sd[0] and receiver_proof is not None:
            length, digest = receiver_proof['bytes'], receiver_proof['sha256']
        data = (root / relative).read_bytes()
        if len(data) != length or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('P1 trust original identity differs: ' + relative)
        files[relative] = dict(bytes=length, sha256=digest)
    signatures = [
        (sd[0], '_ZN7Updater21SignatureVerification9verifyKeyEPKc', 0xaaa0, 584,
         'b1328d379f29881198d228c93d6bf5e472a206845275746b05cfda88de83e5ee'),
        (sd[0], '_ZN7Updater21SignatureVerification15VerifySignatureENS_13verify_info_tEPKc', 0xace8, 372,
         '885b124de00f44596dcb2b8f3af75b1b4ccea6d332517f9014189b645643ebd6'),
        (CORE[0], VERIFY_SUM, 0xb5cc, 216, None),
        (UIPC[0], 'osal_valloc_msg_wait', 0x7138, 440, None),
        (UIPC[0], 'osal_snd_sync_msg', 0x6de8, 12, None),
        (UIPC[0], 'osal_free_msg', 0x72f0, 928, None),
        (CRYPTO[0], 'SHA1', 0x187b10, 140, None),
        (CRYPTO[0], 'SHA1_Final', 0x187d18, 416, None),
        (CRYPTO[0], 'SHA256', 0x18a2d0, 120, None),
        (CRYPTO[0], 'RSA_verify', 0x182c20, 40, None),
    ]
    pins = []
    exports = {}
    for relative, symbol, va, length, expected in signatures:
        if relative not in exports:
            exports[relative] = subprocess.check_output(['readelf', '-Ws', str(root / relative)], text=True)
        if not re.search(rf'\b{va:016x}\s+{length}\s+FUNC\s+GLOBAL\s+DEFAULT\s+\d+\s+{re.escape(symbol)}(?:@@[^\s]+)?\s', exports[relative]):
            raise ValueError('P1 trust exported ABI differs: ' + symbol)
        data = (root / relative).read_bytes()
        offset = original['va_offset'](data, va, length)
        code = data[offset:offset + length]
        digest = hashlib.sha256(code).hexdigest()
        checked_code = code
        if receiver_proof is not None and relative == sd[0] and va == 0xace8:
            patch = 0xae08 - va
            if code[patch:patch + 4] != bytes.fromhex('20008052'):
                raise ValueError('Dev trust expected exact patched instruction')
            checked_code = code[:patch] + bytes.fromhex('72f1ff97') + code[patch + 4:]
        if expected is not None and hashlib.sha256(checked_code).hexdigest() != expected:
            raise ValueError('P1 trust original function text differs: ' + symbol)
        pins.append(dict(symbol=symbol, path='/' + relative, va=va, size=length,
                         text_sha256=digest, code=code.hex()))
    passive_windows = []
    for sample, va, end, expected in PASSIVE_WINDOWS:
        relative = sd[0] if sample == 'sd' else CORE[0]
        data = (root / relative).read_bytes()
        offset = original['va_offset'](data, va, end - va)
        code = data[offset:offset + end - va]
        if hashlib.sha256(code).hexdigest() != expected:
            raise ValueError('P1 passive original window differs: ' + hex(va))
        passive_windows.append(dict(path='/' + relative, va=va, size=end - va,
            symbol='_ZN7Updater21SignatureVerification9verifyKeyEPKc' if sample == 'sd' else VERIFY_SUM,
            symbol_va=0xaaa0 if sample == 'sd' else 0xb5cc, code=code.hex(), text_sha256=expected))
    relocations = subprocess.check_output(['readelf', '-WdWr', str(root / sd[0])], text=True)
    if ('SYMBOLIC' in relocations or not re.search(
            rf'000000000001e030\s+\S+\s+R_AARCH64_JUMP_SLOT\s+0000000000000000\s+{VERIFY_SUM}\s+\+ 0', relocations)):
        raise ValueError('P1 passive verifySum PLT binding differs')
    result = dict(schema='p1-trust-key-abi-v1', files=files, pins=pins,
                passive=dict(schema='p1-decrypt-passive-abi-v1', windows=passive_windows,
                    helper_args=9, helper_interposed=False, caller_returns=dict(allocate=0x93d0,
                        sync=0x9434, input_copy=0x9428, copy=0x9460, free=0x949c, verify_sum=0x99a4),
                    copy_observer=dict(schema='p1-native-caller-copy-passive-v1',
                        input=dict(call=0x9424, return_va=0x9428, phase='before',
                            read_source='original-memcpy-source'),
                        output=dict(call=0x945c, return_va=0x9460, phase='after',
                            read_source='original-memcpy-destination'),
                        native_copy_calls=1, allocation_sid=0x025906be, allocation_return=0x93d0,
                        free_return=0x949c, owner='live-native-allocation-same-pid-tid',
                        capacity_payload_limits={'56':16, '552':512, '1064':1024},
                        expected_operation_source='checked-original-caller-allocation-and-copy-shape',
                        operation_zero='unobserved-or-unrecognized; not-native-opcode-zero',
                        header_eio_policy='opcode-unknown; original-passthrough; no-reader-fallback',
                        failed_sample='unknown; preserve-native-return-and-errno',
                        normal_buffer_only=True, zero_length=False, unsigned_ranges_checked=True,
                        opaque8_source='original-memcpy-destination', actual_verified=False),
                    verify_sum_slot=0x1e030, verify_sum_abi='void(this)',
                    reader=dict(backend='proc-self-mem-pread64', path='/proc/self/mem',
                        flags=['O_RDONLY', 'O_CLOEXEC', 'O_NOFOLLOW'], per_read_open_close=True,
                        offset_bits=64, max_read_bytes=1084, max_packet_payload_bytes=1024,
                        max_verify_block_bytes=1024, caller_errno_preserved=True,
                        alternate_backend=False, actual_verified=False),
                    log_budget=dict(total=128, pin_identity=32, observations=96),
                    verify_signature_coverage='unknown', aes_binding_coverage='unknown',
                    op2_actual=False, op3_actual=False, sha_actual=False, rsa_actual=False,
                    payload_actual=False, file_write_actual=False),
                caller_returns=dict(allocate=0xabc4, sync=0xabf4, copy=0xac18, compare=0xac94,
                                    sha1_final=0xaba8, rsa=0xae0c),
                sid=0x025906be, request_bytes=60, query_u64=[1, 0, 0, 0, 20],
                reply_write_ranges=[[0, 8], [32, 60]], native_provider_typed_getter_verified=False)
    if receiver_proof is not None:
        result.update(schema='p1-dev-trust-key-abi-v1', receiver_proof=receiver_proof)
    return result


def trust_contract(root):
    """Strict stock admission; no alternate expected hashes or derived receiver."""
    return _trust_contract(root)


def dev_trust_contract(root, receiver_receipt):
    """Separate dev API: prove the entire inverse patch, pin actual patched bytes.

    This never creates a stock view or modifies root. verifyKey remains pinned to
    its stock 584B; the 372B VerifySignature pin contains the actual ae08 patch.
    The caller/adapter must separately admit its explicit dev profile/receipt.
    """
    root = Path(root)
    dev = runpy.run_path(str(HERE / 'dev-update-profile.py'))
    proof = dev['verify_derived_receiver'](root / 'usr/lib/libsdfileinputupdaterapi.so', receiver_receipt)
    return _trust_contract(root, proof)


TRUST_ACTIVATION_SOURCE = r'''
extern int setenv(const char *,const char *,int);
static void service_select_profile(void) __attribute__((constructor));
static void service_select_profile(void) {
    int saved=*__errno_location();
    if(selected() && init_identity && trust_identity && trust_marker()) {
        unsigned char digest[20];
        if(p1_trust_key_read(P1_TRUST_PROFILE,P1_TRUST_ASSET,next("SHA1"),next("SHA256"),digest))
            setenv("A7C2_P1_TRUST_PROFILE",P1_TRUST_PROFILE,1);
    }
    *__errno_location()=saved;
}
'''


def passive_source(signature):
    rows = []
    for p in signature.get('passive', {}).get('windows', []):
        code = ','.join(str(b) for b in bytes.fromhex(p['code']))
        rows.append('{"%s","%s",%d,%d,%d,{%s}}' %
                    (p['symbol'], p['path'], p['symbol_va'], p['va'], p['size'], code))
    return (HERE / 'p1-trust-key.inc').read_text(encoding='ascii').replace(
        '/* __PASSIVE_PINS__ */', ',\n'.join(rows))


def trust_service_source(initializer, signature, *, trust_profile=None, newdecrypt=None, tail=None):
    """Standalone provider for the main-owned adapter, after both frozen preloads.

    Pass the builder's already verified six-pin initializer and either strict
    trust_contract(root) or dev_trust_contract(root, receiver_receipt). This emits
    no Initialize/open/Fsys wrappers, preserving the frozen hook's RTLD_NEXT.
    Link p1-trust-key.c and put this DSO AFTER sd PRELOAD, not ahead of it.
    Explicit trust_profile=TRUST_PROFILE adds selected-process activation after
    native pins, the profile marker and actual pinned PEM have all validated;
    this preserves the dev bootstrap's exact text/environment contract.
    """
    effective_env(trust_profile)
    if len(initializer['pins']) != 6 or signature.get('schema') not in ('p1-trust-key-abi-v1', 'p1-dev-trust-key-abi-v1'):
        raise ValueError('Trust service requires six initializer pins and validated trust contract')
    rows = []
    for p in initializer['pins']:
        code = ','.join(str(b) for b in bytes.fromhex(p['code']))
        rows.append('{"%s","%s",%d,%d,%d,{%s}}' % (p['symbol'], p['path'], p['va'], p['slot'], p['size'], code))
    source = OBSERVER[:OBSERVER.index('static int watched(')] + r'''
extern int memcmp(const void *,const void *,unsigned long);
typedef struct {const char *file; void *base; const char *symbol; void *address;} Info;
extern int dladdr(const void *,Info *);
static int init_identity;
struct ServiceInitPin {const char *symbol,*path;unsigned long va,slot,length;unsigned char code[728];};
static const struct ServiceInitPin service_init_pins[]={ /* __SERVICE_INIT_PINS__ */ };
static void service_init_check(void) __attribute__((constructor));
static void service_init_check(void) {
    int saved=*__errno_location();
    if(selected()) {
        int good=1;void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
        for(unsigned i=0;i<sizeof service_init_pins/sizeof service_init_pins[0];i++) {
            const struct ServiceInitPin *p=service_init_pins+i;Info info={0};void *fn=next(p->symbol);
            int ok=fn && dladdr(fn,&info) && !strcmp(info.file,p->path) &&
                (char *)fn==(char *)info.base+p->va && !memcmp(fn,p->code,p->length);
            good=good && ok && lookup && *(void **)((char *)info.base+p->slot)==lookup(0,p->symbol);
        }
        init_identity=good;
    }
    *__errno_location()=saved;
}
'''
    source = source.replace('/* __SERVICE_INIT_PINS__ */', ',\n'.join(rows))
    rows = []
    for p in signature['pins']:
        code = ','.join(str(b) for b in bytes.fromhex(p['code']))
        rows.append('{"%s","%s",%d,%d,{%s}}' % (p['symbol'], p['path'], p['va'], p['size'], code))
    source += passive_source(signature).replace('/* __TRUST_PINS__ */', ',\n'.join(rows))
    if trust_profile is not None:
        source += TRUST_ACTIVATION_SOURCE
    if newdecrypt is not None and signature.get('schema') != 'p1-trust-key-abi-v1':
        raise ValueError('P1 CBC supports only the original stock receiver')
    source = newdecrypt_source(source, selection=newdecrypt)
    if tail is not None:
        if signature is None or signature.get('schema') != 'p1-trust-key-abi-v1':
            raise ValueError('Tail supports only the exact original stock trust schema')
        source = tail_api()['decorate'](source, profile=tail['profile'], source_contract=tail['source_contract'],
                                        pmbp_profile=tail['pmbp_profile'])
    return source


def observer_source(contract, signature=None, *, trust_profile=None, newdecrypt=None, tail=None):
    effective_env(trust_profile)
    if trust_profile is not None and signature is None:
        raise ValueError('P1 trust activation requires its guarded signature contract')
    rows = []
    for p in contract['pins']:
        code = ','.join(str(b) for b in bytes.fromhex(p['code']))
        rows.append('{"%s","%s","%s","%s",%d,%d,%d,{%s}}' %
                    (p['op'], p['symbol'], p['path'], p['sha256'], p['va'], p['slot'], p['size'], code))
    source = OBSERVER.replace('/* __INIT_PINS__ */', ',\n'.join(rows))
    if signature is not None:
        rows = []
        for p in signature['pins']:
            code = ','.join(str(b) for b in bytes.fromhex(p['code']))
            rows.append('{"%s","%s",%d,%d,{%s}}' % (p['symbol'], p['path'], p['va'], p['size'], code))
        source += passive_source(signature).replace('/* __TRUST_PINS__ */', ',\n'.join(rows))
    if trust_profile is not None:
        source += TRUST_ACTIVATION_SOURCE
    if newdecrypt is not None and (signature is None or signature.get('schema') != 'p1-trust-key-abi-v1'):
        raise ValueError('P1 CBC supports only the original stock receiver')
    source = newdecrypt_source(source, selection=newdecrypt)
    if tail is not None:
        if signature is None or signature.get('schema') != 'p1-trust-key-abi-v1':
            raise ValueError('Tail supports only the exact original stock trust schema')
        source = tail_api()['decorate'](source, profile=tail['profile'], source_contract=tail['source_contract'],
                                        pmbp_profile=tail['pmbp_profile'])
    return source


def tail_api():
    return runpy.run_path(str(HERE / 'p1-tail-source.py'))


def _pinned_snapshot(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_mode & 0o222 or
                before.st_size != KEY[1] or before.st_nlink != 1):
            raise ValueError('P1 pinned snapshot must be an independent read-only regular 451B PEM')
        data = os.read(fd, KEY[1] + 1)
        after = os.fstat(fd)
        if (len(data) != KEY[1] or os.read(fd, 1) or hashlib.sha256(data).hexdigest() != KEY[2] or
                any(getattr(before, k) != getattr(after, k) for k in
                    ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_nlink', 'st_mtime_ns', 'st_ctime_ns'))):
            raise ValueError('P1 pinned snapshot content or identity differs')
        return data
    finally:
        os.close(fd)


def install(root, output, *, trust_profile=None, pinned_key=None, newdecrypt_profile=None, package_source=None,
            tail_profile=None, tail_body_root=None, mode=None, install_profile=None, pmbp_profile=None):
    """Build passive taps; an explicit profile additionally provisions the anchor.

    Main must call this on its isolated copied root, then bind runtime_files in
    CPIO and use effective_env(). Neither a default nor inherited ENV enables it.
    """
    env = effective_env(trust_profile, newdecrypt_profile=newdecrypt_profile, tail_profile=tail_profile)
    if newdecrypt_profile is None and package_source is not None:
        raise ValueError('P1 CBC package input requires explicit profile')
    root, output = Path(root), Path(output)
    signature, initializer = trust_contract(root), initialize_contract(root)
    data = None
    if trust_profile is not None:
        if pinned_key is None:
            raise ValueError('Explicit P1 trust profile requires independently provisioned pinned_key')
        pinned_key = Path(pinned_key)
        if pinned_key.resolve().is_relative_to(root.resolve()) or os.path.samefile(pinned_key, root / KEY[0]):
            raise ValueError('P1 pinned snapshot cannot be caller mutable PEM or an asset inside prepared root')
        data = _pinned_snapshot(pinned_key)
    elif pinned_key is not None:
        raise ValueError('P1 pinned_key requires explicit trust profile')
    tail = None
    if tail_profile is not None or tail_body_root is not None:
        tail = tail_api()['prepare'](root, output, profile=tail_profile, body_root=tail_body_root,
            mode=mode, install_profile=install_profile, signature_schema=signature['schema'], pmbp_profile=pmbp_profile)
    decrypt = None
    if newdecrypt_profile is not None:
        decrypt = newdecrypt_api()['prepare'](root, output, profile=newdecrypt_profile, package_source=package_source)
    sim = root / 'simulation'
    sim.mkdir(exist_ok=True)
    artifact = sim / 'p1-trust-key'
    artifact.mkdir(exist_ok=False)
    runtime_files = ['simulation/p1-trust-key/profile', 'simulation/p1-trust-key/contract.json',
                     'simulation/p1-sd-observer.so']
    profile_text = (trust_profile or 'strict') + '\n'
    (artifact / 'profile').write_text(profile_text, encoding='ascii')
    if data is not None:
        snapshot = artifact / 'sony-original.pem'
        snapshot.write_bytes(data)
        snapshot.chmod(0o444)
        if _pinned_snapshot(snapshot) != data:
            raise ValueError('P1 pinned snapshot readback differs')
        runtime_files.append('simulation/p1-trust-key/sony-original.pem')
    sources = [api()['record'](HERE / name) for name in TRUST_SOURCES]
    if data is not None:
        sources.append(api()['record'](pinned_key))
    value = dict(schema='p1-trust-key-service-v1', profile=trust_profile, environment=env,
                 source_class='virtual-provisioned-trust-anchor' if data is not None else 'original-passive',
                 contract=signature, sources=sources, runtime_files=runtime_files,
                 asset=dict(path='/simulation/p1-trust-key/sony-original.pem', bytes=KEY[1], sha256=KEY[2],
                            sha1=hashlib.sha1(data).hexdigest()) if data is not None else None,
                 modeled_hardware_history_verified=False, original_compare_executed=False,
                 rsa_executed=False, guest_verified=False, fsys_read_observer_implemented=False)
    if decrypt is not None:
        value['newdecrypt'] = decrypt
        runtime_files += decrypt['runtime_files']
    if tail is not None:
        value['tail'] = tail
        runtime_files += tail['runtime_files']
        sources += tail['sources']
    (artifact / 'contract.json').write_text(json.dumps(value, sort_keys=True) + '\n', encoding='ascii')
    source = output / 'p1-sd-observer.c' 
    source.write_text(observer_source(initializer, signature, trust_profile=trust_profile, newdecrypt=decrypt, **(dict(tail=tail) if tail is not None else {})), encoding='ascii')
    extra = newdecrypt_api()['compile_inputs'](root, decrypt) if decrypt is not None else []
    if tail is not None:extra += tail_api()['link_flags'](tail_profile)
    api()['command'](['clang', '--target=aarch64-linux-gnu', '--sysroot=/usr/aarch64-linux-gnu',
        '-fuse-ld=lld', '-nostdlib', '-O2', '-fno-builtin', '-fexceptions', '-funwind-tables',
        '-mno-outline-atomics', '-Wl,--no-undefined', '-shared', '-fPIC', '-I', HERE,
        source, HERE / 'p1-trust-key.c', *extra, root / 'lib/libc-2.25.so', root / 'lib/libdl-2.25.so',
        root / 'lib/ld-2.25.so', '-o', sim / 'p1-sd-observer.so'], output, 'sd-observer-build')
    if decrypt is not None:
        newdecrypt_api()['finish'](root, output, decrypt)
        (artifact / 'contract.json').write_text(json.dumps(value, sort_keys=True) + '\n', encoding='ascii')
    return value


def trust_preflight(root, value):
    root = Path(root)
    decrypt = value.get('newdecrypt')
    decrypt_profile = decrypt['selection']['profile'] if decrypt else None
    tail = value.get('tail')
    if tail is not None:tail_api()['recheck'](root, tail)
    if value.get('schema') != 'p1-trust-key-service-v1' or value.get('environment') != effective_env(value.get('profile'), newdecrypt_profile=decrypt_profile, tail_profile=tail['profile'] if tail else None, pmbp_profile=tail['pmbp_profile'] if tail else None):
        raise ValueError('P1 trust profile/environment binding differs')
    if trust_contract(root) != value.get('contract'):
        raise ValueError('P1 trust ABI binding differs')
    runtime_files = ['simulation/p1-trust-key/profile', 'simulation/p1-trust-key/contract.json',
                     'simulation/p1-sd-observer.so']
    if value['profile'] is not None:
        runtime_files.append('simulation/p1-trust-key/sony-original.pem')
    if decrypt is not None:
        newdecrypt_api()['validate'](decrypt)
        runtime_files += decrypt['runtime_files']
    if tail is not None:runtime_files += tail['runtime_files']
    if value.get('runtime_files') != runtime_files:
        raise ValueError('P1 trust runtime asset set differs')
    installed = root / 'simulation/p1-trust-key'
    if json.loads((installed / 'contract.json').read_text(encoding='ascii')) != value:
        raise ValueError('P1 trust runtime contract drift')
    if (installed / 'profile').read_text(encoding='ascii') != (value['profile'] or 'strict') + '\n':
        raise ValueError('P1 trust runtime profile drift')
    snapshot = installed / 'sony-original.pem'
    if value['profile'] is None:
        if snapshot.exists():
            raise ValueError('Strict P1 root has an unrequested trust asset')
    elif hashlib.sha1(_pinned_snapshot(snapshot)).hexdigest() != value['asset']['sha1']:
        raise ValueError('P1 trust provisioned asset drift')
    for row in value['sources']:
        now = api()['record'](row['path'])
        if any(now[k] != row[k] for k in ('bytes', 'sha256')):
            raise ValueError('P1 trust source drift')
    return value


def binding_rows(root, contract, *, trust_key=None, trusted_key_model=None, newdecrypt=None, pmbp=None):
    """Keep every verified native/trust asset in the guest audit, once per path."""
    root = Path(root); u = api()
    names = [row['path'] for row in contract['inputs'].values()]
    names += [CORE[0], 'simulation/file-media-config.so', 'simulation/p1-sd-observer.so']
    if trust_key:
        names += list(trust_key['contract']['files']) + trust_key['runtime_files']
    if trust_key and trust_key.get('tail') is not None:
        names += [Path(row['path']).relative_to(root).as_posix()
                  for row in tail_api()['extra_bindings'](root, trust_key['tail'])]
    if trusted_key_model:
        names += list(trusted_key_model['original_bindings']) + list(trusted_key_model['assets'])
    if newdecrypt is not None:
        newdecrypt_api()['validate'](newdecrypt)
        names += newdecrypt['runtime_files']
    if pmbp is not None:
        names += list(runpy.run_path(str(HERE/'pmbp-integration.py'))['preflight'](root,pmbp))
    return [u['record'](root / name) for name in sorted(set(names))]


def binding_texts(root, rows):
    if not 1 <= len(rows) <= 4096:
        raise ValueError('SD binding count outside 1..4096')
    paths = set(); lines = []
    for row in rows:
        name = '/' + Path(row['path']).relative_to(root).as_posix()
        if (name in paths or any(c.isspace() for c in name) or not name.isascii()
                or '..' in Path(name).parts or name in ('/simulation/sd-read-bindings', '/simulation/sd-read-binding-count')
                or type(row['bytes']) is not int or row['bytes'] < 0
                or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
            raise ValueError('Invalid or duplicate SD binding row: ' + name)
        paths.add(name)
        lines.append(f'{name} {row["bytes"]} {row["sha256"]}\n')
    return {'simulation/sd-read-bindings': ''.join(lines),
            'simulation/sd-read-binding-count': str(len(rows)) + '\n'}


def binding_preflight(root, value, expected_rows, source_root):
    root = Path(root)
    declared = [dict(row, path=str(root / Path(row['path']).relative_to(source_root)))
                for row in value['bindings']]
    texts = binding_texts(root, expected_rows)
    if binding_texts(root, declared) != texts:
        raise ValueError('SD binding rows differ from verified sources')
    for name, text in texts.items():
        path = root / name
        if (name not in value['cpio_bindings'] or path.is_symlink()
                or path.read_bytes() != text.encode('ascii')):
            raise ValueError('SD binding text/count or CPIO contract differs: ' + name)
    return texts


def configure(root, update, output, *, profile=PROFILE, trust_profile=None, pinned_key=None, newdecrypt_profile=None,
              tail_profile=None, tail_body_root=None):
    if profile not in (PROFILE, INSTALL_PROFILE): raise ValueError('Unknown SD execution profile')
    install_mode = profile == INSTALL_PROFILE
    if trust_profile is not None and not install_mode:
        raise ValueError('P1 trust model requires explicit virtual-install profile')
    effective_env(trust_profile, newdecrypt_profile=newdecrypt_profile, tail_profile=tail_profile)
    if tail_profile is not None or tail_body_root is not None:
        tail_api()['selection'](tail_profile, mode=update['mode'], install_profile=profile,
                               signature_schema='p1-trust-key-abi-v1' if trust_profile==TRUST_PROFILE else None)
    u = api(); root = Path(root); sim = root / 'simulation'
    if (update['sd'].get('fat_bits') != 32 or update['sd']['bodydata'].get('size') != update['sd_read_package']['bytes']
            or update['sd']['bodydata'].get('sha256') != STOCK_SHA):
        raise ValueError('SD read profile requires matching official BODYDATA FAT32')
    single_body_fat(update['sd']['image']['path'], output)
    c = runpy.run_path(str(HERE / 'p1-file-media-contract.py'))['inspect'](root)
    hook = update['file_media']
    if (hook['source']['sha256'] != HOOK_SHA or hook['output']['sha256'] != DSO_SHA
            or u['record'](root / 'simulation/file-media-config.so')['sha256'] != DSO_SHA):
        raise ValueError('SD read profile frozen hook binding differs')
    (sim / 'sd-read-profile').write_text(profile + '\n', encoding='ascii')
    sd_env = tail_api()['effective_env'](tail_profile, ENV, pmbp_profile=update.get('pmbp_profile', (update.get('pmbp') or {}).get('profile'))) if tail_profile is not None else ENV
    (sim / 'sd-read-env').write_text(''.join(f'{k}={v}\n' for k,v in sd_env.items()), encoding='ascii')
    if install_mode:
        install_api = runpy.run_path(str(HERE / 'newp1-virtual-install.py'))
        (sim / 'install-authorization').write_text(install_api['authorization'](update['virtual_install']), encoding='ascii')
    else:
        (sim / 'sd-no-install').write_text('target-block-readonly-20\n', encoding='ascii')
    init_contract = initialize_contract(root)
    install_options = dict(trust_profile=trust_profile, pinned_key=pinned_key)
    if newdecrypt_profile is not None:
        install_options.update(newdecrypt_profile=newdecrypt_profile, package_source=update['sd_read_package_source']['path'])
    if tail_profile is not None or tail_body_root is not None:
        install_options.update(tail_profile=tail_profile, tail_body_root=tail_body_root, mode=update['mode'],
                               install_profile=profile, pmbp_profile=update.get('pmbp_profile'))
    trust_key = install(root, output, **install_options)
    source = Path(output) / 'p1-sd-observer.c'
    (root / 'etc/ld.so.preload').write_text(PRELOAD, encoding='ascii')
    target = root / 'sbin/sdfileinput.elf'
    if os.path.lexists(target): raise ValueError('SD receiver adapter path already exists')
    target.symlink_to('/init')
    rows = binding_rows(root, c, trust_key=trust_key)
    for name, text in binding_texts(root, rows).items():
        (root / name).write_text(text, encoding='ascii')
    return dict(profile=profile, source_kind='functional-adapter', no_install=not install_mode,
        target_block_readonly_count=0 if install_mode else 20, target_block_writable_count=20 if install_mode else 0,
        environment=sd_env, source_contract=c, initialize_contract=init_contract, trust_key=trust_key,
        hook=hook, observer_source=u['record'](source), observer=u['record'](sim / 'p1-sd-observer.so'),
        package=update['sd_read_package'], package_source=update['sd_read_package_source'], bindings=rows, coverage=False, read_verified=False,
        bypass_configured=False, bypass_executed=False, bodywriter_completed=False, installation_verified=False)


def cpio_name(raw):
    if not raw.endswith(b'\0') or b'\0' in raw[:-1]:
        raise ValueError('Invalid SD CPIO name terminator')
    name = raw[:-1].decode('utf-8')
    if any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('Noncanonical SD CPIO name: ' + repr(name))
    return name


def cpio_readback(path, expected):
    """Stream all concatenated gzip/newc members, hash exact input bytes and modes."""
    found = {}
    with gzip.open(path, 'rb') as stream:
        while True:
            header = stream.read(110)
            if not header: break
            if len(header)!=110 or header[:6]!=b'070701': raise ValueError('Invalid SD CPIO header')
            fields=[int(header[i:i+8],16) for i in range(6,110,8)]
            mode,size,namesize=fields[1],fields[6],fields[11]
            if not 1<=namesize<=4096: raise ValueError('Invalid SD CPIO name')
            name=stream.read(namesize)
            if len(name)!=namesize or name[-1:]!=b'\0': raise ValueError('Truncated SD CPIO name')
            name=cpio_name(name);stream.read((-110-namesize)%4)
            digest=hashlib.sha256();left=size
            while left:
                block=stream.read(min(left,1024*1024))
                if not block: raise ValueError('Truncated SD CPIO input')
                digest.update(block);left-=len(block)
            stream.read((-size)%4)
            if name in expected:
                if name in found: raise ValueError('Duplicate SD CPIO binding: '+name)
                row=dict(bytes=size,sha256=digest.hexdigest(),mode=mode)
                if row!=expected[name]: raise ValueError('SD CPIO binding differs: '+name)
                found[name]=row
    if set(found)!=set(expected): raise ValueError('Missing SD CPIO bindings')
    return found


def bindings(root, card, *, newdecrypt=None, pmbp=None):
    u=api();root=Path(root)
    names=['init','etc/ld.so.preload','sbin/sdfileinput.elf','simulation/sd-read-profile',
           'simulation/sd-read-env','simulation/sd-read-bindings','simulation/sd-read-binding-count',
           'simulation/file-media-config.so','simulation/p1-sd-observer.so']
    names += ['simulation/install-authorization' if (root/'simulation/install-authorization').exists() else 'simulation/sd-no-install']
    names += [row[0] for row in runpy.run_path(str(HERE/'p1-file-media-contract.py'))['SAMPLES'].values()]
    names += [CORE[0]]
    trust_file = root / 'simulation/p1-trust-key/contract.json'
    if trust_file.exists():
        trust_key = json.loads(trust_file.read_text(encoding='ascii'))
        trust_preflight(root, trust_key)
        names += list(trust_key['contract']['files']) + trust_key['runtime_files']
    if newdecrypt is not None:
        newdecrypt_api()['validate'](newdecrypt)
        names += newdecrypt['runtime_files']
    result={}
    for name in dict.fromkeys(names):
        p=root/name; mode=p.lstat().st_mode
        data=os.readlink(p).encode() if stat.S_ISLNK(mode) else p.read_bytes()
        result[name]=dict(mode=mode,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    if pmbp is not None:result.update(runpy.run_path(str(HERE/'pmbp-integration.py'))['cpio_rows'](root,pmbp))
    result['image_mmca']=dict(mode=stat.S_IFREG|0o600,bytes=card['bytes'],sha256=card['sha256'])
    return result


def preflight(update, root, read_only, media, profile):
    u=api(); admit(profile,mode=update['mode'],read_only=read_only,media=media,sd=update.get('sd'),module=update['module_contract'])
    value=update.get('sd_read_observation') or {}
    install=profile==INSTALL_PROFILE
    trust_key = value.get('trust_key')
    tail = trust_key.get('tail') if trust_key else None
    tail_profile = tail['profile'] if tail else None
    if update.get('tail_profile') != tail_profile:
        raise ValueError('Declared tail selection differs from prepared observer')
    if tail is not None and update.get('pmbp_profile', (update.get('pmbp') or {}).get('profile')) != tail['pmbp_profile']:
        raise ValueError('Explicit tail/PMBP selections differ')
    sd_env = tail_api()['effective_env'](tail_profile, ENV, pmbp_profile=update.get('pmbp_profile', (update.get('pmbp') or {}).get('profile'))) if tail_profile is not None else ENV
    if trust_key:
        effective_env(trust_key.get('profile'))
    if (trust_key and trust_key.get('profile') is not None and not install):
        raise ValueError('P1 trust model mixed with read-only profile')
    if (value.get('profile')!=profile or value.get('no_install') is not (not install) or
            value.get('source_kind')!='functional-adapter' or value.get('environment')!=sd_env or
            value.get('target_block_readonly_count')!=(0 if install else 20) or
            (install and value.get('target_block_writable_count')!=20) or update.get('bypass_configured') is not False):
        raise ValueError('Missing SD no-install binding' if not install else 'Missing SD install binding')
    root=Path(root)
    binding_root=Path(value.get('binding_root',Path(update['output'])/'root'))
    pmbp=selected_pmbp(update,root)
    if 'binding_root' in value and (not (pmbp or (tail and tail.get('derived_from'))) or binding_root.resolve()!=root.resolve()):
        raise ValueError('Explicit E binding root requires a genuine derived contract')
    if install and any((root/'simulation'/n).exists() for n in ('sd-no-install','read-only-probe','block-readonly-verified')):
        raise ValueError('Install profile mixed with read-only markers')
    for name,expected in value['cpio_bindings'].items():
        if name == 'image_mmca': continue
        path=root/name
        mode=path.lstat().st_mode
        data=os.readlink(path).encode() if stat.S_ISLNK(mode) else (b'' if stat.S_ISDIR(mode) else path.read_bytes())
        if dict(mode=mode,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) != expected:
            raise ValueError('SD prepared-root/CPIO binding drift: '+name)
    texts={'simulation/sd-read-profile':profile+'\n',
        'simulation/sd-read-env':''.join(f'{k}={v}\n' for k,v in sd_env.items()),'etc/ld.so.preload':pmbp['preload'] if pmbp else PRELOAD}
    if not install: texts['simulation/sd-no-install']='target-block-readonly-20\n'
    for name,text in texts.items():
        if (root/name).read_text(encoding='ascii')!=text: raise ValueError('SD environment/profile drift: '+name)
    if u['record'](HERE/'file-media-config.c')['sha256']!=HOOK_SHA: raise ValueError('Frozen hook source drift')
    for row in value['sources'] + [update['sd_read_package_source']]:
        now=u['record'](row['path'])
        if any(now[k]!=row[k] for k in ('bytes','sha256')): raise ValueError('SD source input drift')
    for row in value['bindings']:
        relative=Path(row['path']).relative_to(binding_root)
        now=u['record'](root/relative)
        if any(now[k]!=row[k] for k in ('bytes','sha256')): raise ValueError('SD DSO/original binding differs')
    if u['record'](update['sd']['image']['path'])['sha256']!=update['sd']['image']['sha256']:
        raise ValueError('SD image input changed')
    source_contract = runpy.run_path(str(HERE/'p1-file-media-contract.py'))['inspect'](root)
    if initialize_contract(root) != value.get('initialize_contract'):
        raise ValueError('P1 Initialize contract drift')
    if trust_key:
        trust_preflight(root, trust_key)
        required = set(trust_key['runtime_files']) | set(trust_key['contract']['files'])
        if not required.issubset(value['cpio_bindings']):
            raise ValueError('P1 trust CPIO bindings incomplete')
    binding_preflight(root, value, binding_rows(root, source_contract, trust_key=trust_key,pmbp=pmbp),
                      binding_root)
    if trust_key and trust_key.get('newdecrypt') is not None:
        current_rows = [dict(row, path=str(root / Path(row['path']).relative_to(binding_root)))
                        for row in value['bindings']]
        newdecrypt_preflight(root, selection=trust_key['newdecrypt'], rows=[{k:r[k] for k in ('path','bytes','sha256')} for r in current_rows],
                            cpio_path=update['initrd']['path'], cpio_bindings=value['cpio_bindings'])
    if tail is not None:
        current_rows = [dict(row, path=str(root / Path(row['path']).relative_to(binding_root)))
                        for row in value['bindings']]
        tail_api()['recheck'](root, tail, rows=current_rows, cpio_path=update['initrd']['path'],
                               cpio_bindings=value['cpio_bindings'])
    if pmbp is not None:
        owner_rows=runpy.run_path(str(HERE/'pmbp-integration.py'))['cpio_rows'](root,pmbp)
        tail_api()['_cpio_owners'](update['initrd']['path'],set(owner_rows))
    return value


def observations(raw, manifest):
    text=raw.decode('utf-8',errors='replace').replace('\r','')
    starts=re.findall(r'^UPDATE_SD_RECEIVER_START pid=(\d+) original=/usr/bin/sdfileinput.elf$',text,re.M)
    exits=[dict(pid=int(pid),rc=int(rc)) for pid,rc in re.findall(
        r'^UPDATE_SD_RECEIVER_EXIT pid=(\d+) rc=(\d+)$',text,re.M)]
    native=[line for line in text.splitlines() if line.startswith('P1_SD_NATIVE ')]
    initializer=[line for line in text.splitlines() if line.startswith(('P1_SD_INIT ', 'P1_SD_EXCEPTION '))]
    taps=[line for line in text.splitlines() if line.startswith(('P1_SD_TAP ', 'P1_SD_READY ', 'P1_SD_RESOLVE '))]
    initializer_failures=[line for line in initializer if 'op=mount phase=return ' in line and re.search(r'\brc=-\d+\b',line)]
    fsys=[line for line in text.splitlines() if line.startswith('FILE_MEDIA_FSYS ')]
    failures=[line for line in native if re.search(r'\bop=(?:open|open64) .*\brc=-\d+\b',line)
              or re.search(r'\bop=Fsys_(?:Init|FindFirst) .*\brc=(?!0\b)-?\d+\b',line)
              or re.search(r'\bop=mmap64 .*\brc=0xffffffffffffffff\b',line)]
    failures += [line for line in fsys if re.search(r'\bresult=(?!0\b)-?\d+',line)]
    body=dict(observations=[],coverage=False,read_verified=False,observed_byte_coverage=False)
    if len(starts)==1:
        expected=Path(manifest['sd_read_observation']['package_source']['path']).read_bytes()
        body=runpy.run_path(str(HERE/'p1-file-media-contract.py'))['body_observations'](text,expected,int(starts[0]))
    ro=re.findall(r'^UPDATE_SD_TARGET_RO node=(\S+) get_rc=(-?\d+) readonly=(\d+)$',text,re.M)
    return dict(profile=PROFILE,source_kind='functional-adapter',receiver_pids=list(map(int,starts)),
        receiver_exits=exits,original_native_returns=native,original_fsys_returns=fsys,
        initializer_events=initializer,initializer_bindings=taps,
        trust_key_observations=[line for line in text.splitlines() if line.startswith('P1_TRUST_KEY ')],
        initializer_identity_before_manager=(len(starts)==1 and
            f'P1_SD_READY pid={starts[0]} identity=1 taps=6 budget=96 source_class=original-passive' in text and
            text.index(f'P1_SD_READY pid={starts[0]} identity=1') < text.find(f'P1_SD_INIT pid={starts[0]} op=manager phase=enter')),
        first_verified_blocker=(initializer_failures + failures)[0] if initializer_failures or failures else None,
        target_ro_checks=ro,target_ro_before_receiver_verified=(len(ro)==40 and
            all(len({r[0] for r in ro[i:i+20]})==20 and all(r[1:]==('0','1') for r in ro[i:i+20]) for i in (0,20)) and
            text.count('UPDATE_SD_EXEC_GUARD profile='+PROFILE+' source_kind=functional-adapter no_install=1 target_ro=20\n')==2),
        p1body_observations=body,read_verified=False,coverage=False,complete_media_init_verified=False,
        receiver_completed=False,bypass_configured=False,bypass_executed=False,bodywriter_completed=False,
        installation_verified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update-manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--qemu-build',type=Path,required=True)
    parser.add_argument('--actual',action='store_true')
    parser.add_argument('--seconds',type=float,default=90)
    args=parser.parse_args(); e=runpy.run_path(str(HERE/'p1-update-execution.py'))
    update,_=e['UPDATE']['checked_json'](args.update_manifest)
    output=e['PERSIST']['fresh_output'](args.output,args.update_manifest.parent)
    manifest=e['build'](args.update_manifest,output/'build',read_only=True,qemu_build=args.qemu_build,
        media_resources=update['original_resources']['media_receipt']['path'],sd_read_profile=PROFILE)
    result=e['actual'](manifest,output/'guest',seconds=args.seconds) if args.actual else manifest
    print(json.dumps(dict(status=result['status'],profile=PROFILE,installation_verified=False)))


def newdecrypt_api():
    return runpy.run_path(str(HERE / 'p1-cbc-functional-provider.py'))


def newdecrypt_source(source, *, selection=None):
    if selection is None:
        return source
    model = newdecrypt_api()
    model['validate'](selection)
    return model['wrapper_source'](source)


def newdecrypt_environment(selection=None, inherited=None):
    return newdecrypt_api()['effective_env'](selection, inherited)


def newdecrypt_bindings(root, *, selection=None):
    return newdecrypt_api()['extra_bindings'](root, selection)


def newdecrypt_preflight(root, *, selection=None, rows=None, cpio_path=None, cpio_bindings=None):
    return newdecrypt_api()['preflight'](root, selection, rows=rows,
        cpio_path=cpio_path, cpio_bindings=cpio_bindings)


if __name__=='__main__': main()

def derive_tail_pmbp(update,root,pmbp_contract):
    """E-only: after PMBP.prepare and before archive; return a new observation."""
    import copy
    root=Path(root);source_root=Path(update['output'])/'root'
    old=update['sd_read_observation'];trust=old['trust_key'];tail=trust['tail']
    model=tail_api()
    model['recheck'](source_root,tail,rows=old['bindings'],cpio_path=update['initrd']['path'],cpio_bindings=old['cpio_bindings'])
    # Verify the producer actually emitted this bridge, not just a source capability label.
    generated=observer_source(old['initialize_contract'],trust['contract'],trust_profile=trust['profile'],newdecrypt=trust.get('newdecrypt'),tail=tail)
    source=Path(old['observer_source']['path'])
    if source.read_text(encoding='ascii')!=generated or 'tail_pmbp_selected' not in generated:
        raise ValueError('U observer source lacks the exact compiled runtime LR bridge')
    for key in ('observer_source','observer'):
        if api()['record'](old[key]['path'])!=old[key]:raise ValueError('U observer producer row drift')
    expected=api()['record'](root/'simulation/p1-sd-observer.so')
    if any(expected[k]!=old['observer'][k] for k in ('bytes','sha256')):raise ValueError('Copied observer ELF differs')
    from elftools.elf.elffile import ELFFile
    with (root/'simulation/p1-sd-observer.so').open('rb') as stream:
        elf=ELFFile(stream)
        exports={sym.name for sym in elf.get_section_by_name('.dynsym').iter_symbols() if sym['st_shndx']!='SHN_UNDEF'}
        if elf['e_machine']!='EM_AARCH64' or not {'write','close'}<=exports:raise ValueError('Observer original-LR exports missing')
    value=copy.deepcopy(old);key=value['trust_key']
    selected=model['derive_pmbp'](root,tail,source_root=source_root,pmbp_contract=pmbp_contract)
    key['tail']=selected
    key['runtime_files']=[n for n in key['runtime_files'] if n not in tail['runtime_files']]+selected['runtime_files']
    key['environment']=effective_env(key['profile'],newdecrypt_profile=key['newdecrypt']['selection']['profile'] if key.get('newdecrypt') else None,
        tail_profile=selected['profile'],pmbp_profile=selected['pmbp_profile'])
    value['environment']=model['effective_env'](selected['profile'],ENV,pmbp_profile=selected['pmbp_profile'])
    (root/'simulation/p1-trust-key/contract.json').write_text(json.dumps(key,sort_keys=True)+'\n',encoding='ascii')
    (root/'simulation/sd-read-env').write_text(''.join(f'{k}={v}\n' for k,v in value['environment'].items()),encoding='ascii')
    source_contract=runpy.run_path(str(HERE/'p1-file-media-contract.py'))['inspect'](root)
    value['bindings']=binding_rows(root,source_contract,trust_key=key)
    value['binding_root']=str(root.resolve())
    for name,text in binding_texts(root,value['bindings']).items():(root/name).write_text(text,encoding='ascii')
    value['cpio_bindings']=bindings(root,update['sd']['image'],newdecrypt=key.get('newdecrypt'),pmbp=pmbp_contract)
    value.pop('cpio_readback',None)
    trust_preflight(root,key)
    return value


def selected_pmbp(update,root):
    value=update.get('pmbp')
    declared=update.get('pmbp_profile',value.get('profile') if value else None)
    observation=update.get('sd_read_observation') or {}
    tail=(observation.get('trust_key') or {}).get('tail')
    observed=observation.get('pmbp') or ((tail.get('pmbp_binding') or {}).get('contract') if tail else None)
    if value is None:
        if declared is not None or observed is not None or (Path(root)/'simulation/pmbp-runtime').exists():
            raise ValueError('Unselected PMBP declaration/assets')
        return None
    if declared!='virtual-p1-pmbp-block-slice-v1' or value.get('profile')!=declared or observed!=value:
        raise ValueError('Explicit PMBP manifest/observation differs')
    if update.get('install_profile') not in (INSTALL_PROFILE,'original-p1-virtual-dev-install-v1'):
        raise ValueError('PMBP requires an existing explicit install manifest')
    runpy.run_path(str(HERE/'pmbp-integration.py'))['preflight'](root,value)
    return value


def derive_pmbp(update,root,pmbp_contract):
    """Bind a genuine E-built broker in the no-Tail observation and guest audit."""
    import copy
    root=Path(root);source_root=Path(update['output'])/'root'
    if root.resolve()==source_root.resolve() or root.resolve().is_relative_to(source_root.resolve()) or source_root.resolve().is_relative_to(root.resolve()):
        raise ValueError('PMBP requires an independent execution root')
    value=copy.deepcopy(update['sd_read_observation'])
    if (value.get('trust_key') or {}).get('tail') is not None or value.get('pmbp') is not None:
        raise ValueError('No-Tail derivation requires the unselected U observation')
    if 'pmbp_open64_at' not in Path(value['observer_source']['path']).read_text(encoding='ascii'):
        raise ValueError('Rebuild U observer with the original-LR open route')
    for name in ('observer_source','observer'):
        now=api()['record'](value[name]['path'])
        if any(now[k]!=value[name][k] for k in ('bytes','sha256')):raise ValueError('U observer producer row drift')
    now=api()['record'](root/'simulation/p1-sd-observer.so')
    if any(now[k]!=value['observer'][k] for k in ('bytes','sha256')):raise ValueError('Copied observer differs')
    adapter=runpy.run_path(str(HERE/'pmbp-integration.py'))
    adapter['preflight'](root,pmbp_contract)
    value['pmbp']=copy.deepcopy(pmbp_contract)
    value['binding_root']=str(root.resolve())
    value['bindings']=binding_rows(root,value['source_contract'],trust_key=value.get('trust_key'),
        trusted_key_model=update.get('trusted_key_model'),pmbp=pmbp_contract)
    for name,text in binding_texts(root,value['bindings']).items():(root/name).write_text(text,encoding='ascii')
    value['cpio_bindings']=bindings(root,update['sd']['image'],pmbp=pmbp_contract)
    value.pop('cpio_readback',None)
    return value
