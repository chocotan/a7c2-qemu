#!/usr/bin/env python3
"""Real file-backed MAP_SHARED cache/worker tests. No camera, physical disk or VM."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'lcd-pipeline.py'))
BUILD = runpy.run_path(str(HERE / 'build-imaging.py'))['build']
MENU = HERE / 'runtime/native-source-snapshots' / API['BASE_PIN_SHA256'] / 'runtime/analysis'

SEAM = r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "lcd-map-cache.h"
extern void *mmap(void *, unsigned long, int, int, int, unsigned long);
extern int munmap(void *, unsigned long);
static int file_fd, map_fail_after, unmap_fail_once, raster_locked;
static unsigned long map_calls, unmap_calls;
static int map_prots[256];
static void *host_map(void *p,unsigned long n,int prot,int flags,int fd,unsigned long physical) {
    assert(flags==1 && (prot==1 || prot==3) && physical>=LCD_MAP_PHYS_LOW && n<=LCD_MAP_PHYS_HIGH-physical);
    if (map_calls<256) map_prots[map_calls]=prot;
    map_calls++;
    if (map_fail_after && !--map_fail_after) { errno=ENOMEM;return (void *)-1; }
    return mmap(p,n,prot,flags,fd,physical-LCD_MAP_PHYS_LOW);
}
static int host_unmap(void *p,unsigned long n) {
    unmap_calls++;
    if (unmap_fail_once) { unmap_fail_once=0;errno=EIO;return -1; }
    return munmap(p,n);
}
#define LCD_MAP_MMAP host_map
#define LCD_MAP_MUNMAP host_unmap
#include "lcd-map-cache.c"
static void open_backing(const char *path) {
    file_fd=open(path,O_RDWR|O_CREAT|O_EXCL,0600);assert(file_fd>=0);
    assert(!ftruncate(file_fd,256UL*1024*1024)); /* Sparse host fixture, no physical device. */
}
static struct lcd_map_stats stats(struct lcd_map_cache *c) {
    struct lcd_map_stats s;lcd_map_snapshot(c,&s);
    assert(s.bytes<=LCD_MAP_MAX_BYTES && s.entries<=LCD_MAP_SLOTS);return s;
}
'''

CORE = r'''
static void aliases_permissions(void) {
    struct lcd_map_cache c={0};struct lcd_map_borrow a={0},b={0},r={0},w={0},other={0};
    unsigned long p=LCD_MAP_PHYS_LOW+0x16123;
    assert(!lcd_map_acquire(&c,file_fd,p,128,3,&a));
    assert(c.entries[a.slot].physical==LCD_MAP_PHYS_LOW && c.entries[a.slot].length==LCD_MAP_GRANULE);
    assert(a.address==(unsigned char *)c.entries[a.slot].mapping+0x16123);
    memset(a.address,0x5a,128);
    assert(!lcd_map_acquire(&c,file_fd,p+17,64,1,&b));
    assert(b.address==(unsigned char *)a.address+17 && b.slot==a.slot);
    assert(((unsigned char *)b.address)[63]==0x5a);
    unsigned char check[128];assert(pread(file_fd,check,128,0x16123)==128);
    for(int i=0;i<128;i++)assert(check[i]==0x5a);
    assert(!lcd_map_release(&c,&b) && !lcd_map_release(&c,&a));
    assert(stats(&c).hits==1 && stats(&c).maps==1 && !stats(&c).active);
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+2*LCD_MAP_GRANULE+3,32,1,&r));
    unsigned long before=map_calls;
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+2*LCD_MAP_GRANULE+3,32,3,&w));
    assert(map_calls==before+1 && r.slot!=w.slot && c.entries[r.slot].prot==1 && c.entries[w.slot].prot==3);
    memset(w.address,0x6b,32);assert(((unsigned char *)r.address)[31]==0x6b);
    int second_fd=dup(file_fd);assert(second_fd>=0);
    assert(!lcd_map_acquire(&c,second_fd,p,8,1,&other));assert(c.entries[other.slot].fd==second_fd);
    assert(!lcd_map_release(&c,&r) && !lcd_map_release(&c,&w) && !lcd_map_release(&c,&other));
    assert(!lcd_map_flush(&c));assert(!stats(&c).entries && !stats(&c).bytes);
    assert(stats(&c).maps==stats(&c).unmaps);assert(!close(second_fd));
    puts("ALIASES_PERMISSIONS_SHARED_CONTENT_PASS");
}
static void ranges(void) {
    struct lcd_map_cache c={0};struct lcd_map_borrow a={0},b={0};
    unsigned long before=map_calls;
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW-1,1,1,&a)==-1 && errno==EINVAL);
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_HIGH,1,1,&a)==-1);
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_HIGH-1,2,1,&a)==-1);
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,0,1,&a)==-1);
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,1,2,&a)==-1);
    assert(lcd_map_acquire(&c,-1,LCD_MAP_PHYS_LOW,1,1,&a)==-1 && errno==EBADF);
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,LCD_MAP_MAX_BYTES+1,1,&a)==-1 && errno==ENOMEM);
    assert(map_calls==before && !a.active && !stats(&c).entries);
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,32,1,&a));
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+LCD_MAP_GRANULE-16,32,3,&b));
    assert(a.slot!=b.slot && c.entries[b.slot].length==2*LCD_MAP_GRANULE);
    memset(b.address,0x7c,32);assert(((unsigned char *)b.address)[31]==0x7c);
    assert(!lcd_map_release(&c,&a) && !lcd_map_release(&c,&b));assert(!lcd_map_flush(&c));
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_HIGH-1,1,1,&a)); /* Bounds only; no file byte outside fixture accessed. */
    assert(c.entries[a.slot].physical+c.entries[a.slot].length==LCD_MAP_PHYS_HIGH);
    assert(!lcd_map_release(&c,&a) && !lcd_map_flush(&c));puts("PHYSICAL_AND_CROSS_ENTRY_BOUNDS_PASS");
}
static void slots_and_borrows(void) {
    struct lcd_map_cache c={0};struct lcd_map_borrow b[8]={{0}},extra={0};
    for(int i=0;i<8;i++) assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+i*LCD_MAP_GRANULE,16,3,&b[i]));
    assert(stats(&c).active==8 && stats(&c).entries==8);
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+9*LCD_MAP_GRANULE,16,1,&extra)==-1 && errno==EBUSY);
    assert(stats(&c).unmaps==0 && stats(&c).active==8);
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,16,3,&b[0])==-1 && errno==EBUSY);
    struct lcd_map_borrow stale=b[0];
    assert(!lcd_map_release(&c,&b[0]));
    assert(lcd_map_release(&c,&b[0])==-1 && errno==EINVAL);
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+9*LCD_MAP_GRANULE,16,1,&extra));
    assert(lcd_map_release(&c,&stale)==-1 && errno==EINVAL);
    assert(stats(&c).active==8 && stats(&c).entries==8 && stats(&c).unmaps==1);
    for(int i=1;i<8;i++)assert(!lcd_map_release(&c,&b[i]));
    assert(!lcd_map_release(&c,&extra) && !lcd_map_flush(&c));
    assert(!stats(&c).entries && !stats(&c).active && stats(&c).maps==9 && stats(&c).unmaps==9);
    puts("ALL_BUSY_BORROW_RELEASE_GENERATION_PASS");
}
static void budget(void) {
    struct lcd_map_cache c={0};struct lcd_map_borrow a={0},b={0},d={0};
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,64UL*1024*1024,1,&a));
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+64UL*1024*1024,64UL*1024*1024,1,&b));
    assert(stats(&c).bytes==LCD_MAP_MAX_BYTES);
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+128UL*1024*1024,1,1,&d)==-1 && errno==EBUSY);
    assert(!lcd_map_release(&c,&a));
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+128UL*1024*1024,1,1,&d));
    assert(stats(&c).bytes==65UL*1024*1024 && stats(&c).unmaps==1);
    assert(!lcd_map_release(&c,&b) && !lcd_map_release(&c,&d) && !lcd_map_flush(&c));
    puts("TOTAL_BYTE_BUDGET_PASS");
}
static void failed_map(void) {
    struct lcd_map_cache c={0};struct lcd_map_borrow a={0};map_fail_after=1;
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,32,3,&a)==-1 && errno==ENOMEM);
    assert(!a.active && !stats(&c).entries && !stats(&c).active && !stats(&c).bytes && !stats(&c).maps);
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,32,3,&a));
    assert(!lcd_map_release(&c,&a) && !lcd_map_flush(&c));puts("REAL_MAP_ERROR_NO_FAKE_POINTER_PASS");
}
static void failed_eviction(void) {
    struct lcd_map_cache c={0};struct lcd_map_borrow b[8]={{0}},extra={0};
    for(int i=0;i<8;i++) { assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+i*LCD_MAP_GRANULE,1,1,&b[i]));assert(!lcd_map_release(&c,&b[i])); }
    unmap_fail_once=1;
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+9*LCD_MAP_GRANULE,1,1,&extra)==-1 && errno==EIO);
    assert(stats(&c).entries==8 && stats(&c).bytes==8*LCD_MAP_GRANULE && stats(&c).failed && !stats(&c).unmaps);
    assert(lcd_map_flush(&c)==-1 && errno==EIO);
    assert(!stats(&c).entries && !stats(&c).bytes && stats(&c).unmaps==8 && stats(&c).failed);
    assert(lcd_map_flush(&c)==-1 && errno==EIO);
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,1,1,&extra)==-1 && errno==EIO);
    assert(lcd_map_seal_clean(&c)==-1 && errno==EIO);puts("FAILED_UNMAP_RETAINED_STICKY_NO_SUCCESS_PASS");
}
static void active_flush(void) {
    struct lcd_map_cache c={0};struct lcd_map_borrow a={0},b={0};
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,1,1,&a));
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW+LCD_MAP_GRANULE,1,1,&b));
    assert(!lcd_map_release(&c,&b));
    assert(lcd_map_flush(&c)==-1 && errno==EBUSY);
    assert(stats(&c).entries==1 && stats(&c).active==1 && stats(&c).failed);
    assert(!lcd_map_release(&c,&a));assert(lcd_map_flush(&c)==-1 && errno==EBUSY);
    assert(!stats(&c).entries && !stats(&c).bytes);puts("ACTIVE_MAPPING_NEVER_UNMAPPED_PASS");
}
static void fin_seal(void) {
    struct lcd_map_cache c={0};struct lcd_map_borrow a={0};
    assert(!lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,1,1,&a));assert(!lcd_map_release(&c,&a));
    assert(lcd_map_seal_clean(&c)==-1 && errno==EBUSY && !stats(&c).sealed);
    assert(!lcd_map_flush(&c) && !lcd_map_seal_clean(&c));
    assert(stats(&c).sealed && !stats(&c).entries);
    assert(lcd_map_acquire(&c,file_fd,LCD_MAP_PHYS_LOW,1,1,&a)==-1 && errno==ESHUTDOWN);
    assert(!lcd_map_flush(&c));puts("FIN_EMPTY_SEAL_NO_LATE_BORROW_PASS");
}
int main(int argc,char **argv) {
    assert(argc==2);open_backing(argv[1]);
    aliases_permissions();ranges();slots_and_borrows();budget();failed_map();failed_eviction();active_flush();fin_seal();
    assert(!close(file_fd));assert(!unlink(argv[1]));return 0;
}
'''

WORKER = r'''
#include "gpe-copy.h"
#include "gpe-sprite.h"
extern int gpe_uniform_fill(unsigned char *,unsigned long,const unsigned int *);
static int software_gpe=1,software_rgba4444=1,raster_fd,raster_failed;
static unsigned long headless_raster_mutex[6],headless_lifecycle_mutex[6];
static unsigned int headless_stop,headless_thread_live;static unsigned long headless_thread;
static int (*headless_join)(unsigned long,void **);
static int completes,callbacks,native_fin_calls,life_locked;
static unsigned int current_sequence;
static int host_lock(void *p) {
    int *held=p==headless_raster_mutex?&raster_locked:&life_locked;
    assert(!*held);*held=1;return 0;
}
static int host_unlock(void *p) {
    int *held=p==headless_raster_mutex?&raster_locked:&life_locked;
    assert(*held);*held=0;return 0;
}
static unsigned long host_finish(void) { native_fin_calls++;errno=EDOM;return 0x77; }
static unsigned long (*headless_finish)(void)=host_finish;
static int complete(unsigned int source,const void *message,unsigned long size) {
    assert(source==0x123 && size==4 && !*(const int *)message && !raster_locked);completes++;return 1;
}
static int (*real_draw_complete)(unsigned int,const void *,unsigned long)=complete;
static int (*real_worker_fill)(int,int,unsigned int,unsigned int,const void *);
static int (*real_worker_blit)(int,int,unsigned int,unsigned int,const void *);
static int (*real_worker_flush)(int,int,unsigned int,unsigned int,const void *);
static void record(const char *prefix,const char *text) { assert(prefix && text); }
static void capture_gpe(int a,int b,int c,const void *p,unsigned long n) { (void)a;(void)b;(void)c;(void)p;(void)n; }
static void callback(const void *data) {
    const unsigned int *v=data;const unsigned long *q=data;
    assert(v[0]==current_sequence && !v[1] && q[1]==42 && !raster_locked);callbacks++;
}
#define pthread_mutex_lock host_lock
#define pthread_mutex_unlock host_unlock
#define mmap host_map
#define munmap host_unmap
/* ACTUAL_WORKERS */
static unsigned long content_hash(void) {
    unsigned char buffer[256];assert(pread(file_fd,buffer,sizeof buffer,0x16100)==sizeof buffer);
    unsigned long hash=0;for(unsigned int i=0;i<sizeof buffer;i++)hash=hash*33+buffer[i];return hash;
}
int main(int argc,char **argv) {
    assert(argc==3);int mode=atoi(argv[2]);open_backing(argv[1]);raster_fd=file_fd;
    unsigned char seed[4096];for(unsigned int i=0;i<sizeof seed;i++)seed[i]=(i*37+9)&255;
    assert(pwrite(file_fd,seed,sizeof seed,0x28000)==sizeof seed);
    unsigned long destination=LCD_MAP_PHYS_LOW+0x16100,source=LCD_MAP_PHYS_LOW+0x28100;
    unsigned int fill[16]={0},blit[36]={0},flush[8]={0};
    *(unsigned long *)fill=destination;fill[4]=fill[5]=2;fill[6]=8;fill[9]=0x1ff00;
    *(unsigned long *)(fill+10)=(unsigned long)callback;*(unsigned long *)(fill+12)=42;
    *(unsigned long *)blit=destination;*(unsigned long *)(blit+14)=source;
    blit[4]=blit[5]=blit[8]=blit[9]=blit[18]=blit[19]=2;blit[12]=blit[22]=8;blit[28]=0xff0000;
    int rc;
    if(mode==0) {
        for(int frame=0;frame<20;frame++) {
            current_sequence=frame+1;
            assert(!software_fill_worker(0,0,current_sequence,0x123,fill));
            assert(!software_blit_worker(0,0,current_sequence,0x123,blit));
            blit[28]=0xff0001;assert(!software_blit_worker(0,0,current_sequence,0x123,blit));blit[28]=0xff0000;
            assert(!software_flush_worker(0,0,current_sequence,0x123,flush));
            printf("frame=%d complete=%d callback=%d hash=%lu failed=%d\n",frame,completes,callbacks,content_hash(),raster_failed);
        }
        assert(completes==80 && callbacks==20);
#ifndef V3_CACHE
        assert(map_calls==100 && unmap_calls==100);
#endif
    } else if(mode==1 || mode==4) {
        current_sequence=1;
        if(mode==1) { map_fail_after=1;rc=software_fill_worker(0,0,1,0x123,fill); }
        else { *(unsigned long *)(blit+14)=LCD_MAP_PHYS_LOW+0x281000;map_fail_after=2;rc=software_blit_worker(0,0,1,0x123,blit); }
        assert(rc==5 && errno==ENOMEM && !completes && raster_failed);
        assert(software_flush_worker(0,0,1,0x123,flush)==5 && !completes && errno==ENOMEM);
        printf("failed-map=%d errno=%d complete=%d failed=%d\n",mode,errno,completes,raster_failed);
    }
#ifdef V3_CACHE
    else if(mode==2) {
        current_sequence=1;assert(!software_fill_worker(0,0,1,0x123,fill));assert(completes==1);
        unmap_fail_once=1;
        assert(software_flush_worker(0,0,1,0x123,flush)==5 && errno==EIO && completes==1 && raster_failed);
        struct lcd_map_stats s=stats(&full_lcd_maps);assert(s.entries==1 && s.failed && !s.active);
        unsigned long before=unmap_calls;
        assert(observe_grm_fin()==(unsigned long)-1 && !native_fin_calls && !headless_stop && unmap_calls==before);
        assert(software_flush_worker(0,0,1,0x123,flush)==5 && completes==1);
        assert(!stats(&full_lcd_maps).entries && stats(&full_lcd_maps).failed);
        assert(observe_grm_fin()==(unsigned long)-1 && !native_fin_calls);
        puts("FLUSH_REAL_UNMAP_FAILURE_NO_COMPLETION_FIN_REFUSED_PASS");
    } else if(mode==3) {
        current_sequence=1;assert(!software_fill_worker(0,0,1,0x123,fill));
        unsigned long before=unmap_calls;
        assert(observe_grm_fin()==(unsigned long)-1 && !native_fin_calls && !headless_stop && unmap_calls==before);
        assert(!stats(&full_lcd_maps).sealed && stats(&full_lcd_maps).entries==1);
        assert(!software_flush_worker(0,0,1,0x123,flush));
        assert(observe_grm_fin()==0x77 && native_fin_calls==1 && headless_stop);
        before=map_calls;
        assert(software_fill_worker(0,0,1,0x123,fill)==5 && errno==ESHUTDOWN && map_calls==before);
        puts("DIRTY_FIN_REFUSED_CLEAN_FIN_SEALED_PASS");
    }
    if(mode!=2 && mode!=3) {
        struct lcd_map_stats s=stats(&full_lcd_maps);assert(!s.entries && !s.active && !s.bytes && !s.failed);
        if(mode==0) assert(s.maps==20 && s.hits==80 && s.unmaps==20 && s.flushes==20);
    }
#endif
    if(mode!=2 && mode!=3) {
        assert(observe_grm_fin()==0x77 && native_fin_calls==1);
        printf("fin=%d errno=%d\n",native_fin_calls,errno);
    }
    assert(!raster_locked && !life_locked && !close(file_fd) && !unlink(argv[1]));return 0;
}
'''


class MapCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='lcd-map-cache-host-')
        cls.work = Path(cls.temp.name)
        cls.core = cls.work / 'core.c';cls.core.write_text(SEAM + CORE)
        cls.binaries = []
        for name, flags in [('normal', ['-O2']), ('sanitized', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer'])]:
            binary = cls.work / ('core-' + name)
            subprocess.run(['clang', '-std=c11', '-D_GNU_SOURCE', '-Wall', '-Wextra', *flags,
                            '-I', str(HERE), str(cls.core), '-o', str(binary)], check=True)
            cls.binaries.append(binary)
        root = cls.work / 'root';(root / 'simulation').mkdir(parents=True)
        cls.receipts = {}
        def fake_compiler(cmd, **kwargs):
            Path(cmd[cmd.index('-o') + 1]).write_bytes(b'host source fixture only')
        with patch('subprocess.run', fake_compiler):
            for profile in ('latency-v1', 'latency-v2', 'latency-v3'):
                cls.receipts[profile] = BUILD(MENU, root, cls.work / profile, lcd_pipeline_profile=profile)
        cls.workers = {}
        for profile in ('latency-v1', 'latency-v3'):
            folder = cls.work / profile
            observer = (folder / 'menu-observe.c').read_text()
            start = observer.index('static int raster_completion(unsigned int sequence, unsigned int source, const unsigned char *callback_info) {')
            workers = observer[start:observer.index('int observe_gpe_fill(', start)]
            start = observer.index('static unsigned long observe_grm_fin(void) {')
            fin = observer[start:observer.index('static int install_headless_fin(', start)]
            support = ''
            if profile == 'latency-v3':
                support = 'static struct lcd_map_cache full_lcd_maps;\nstatic int full_lcd_map_finish_batch(void);\nstatic int full_lcd_map_fin_admit(void);\n'
                workers += API['V3_OBSERVER_SUPPORT']
            text = SEAM + WORKER.replace('/* ACTUAL_WORKERS */', support + workers + fin)
            source = folder / 'worker.c';source.write_text(text)
            binary = folder / 'worker'
            subprocess.run(['clang', '-std=c11', '-D_GNU_SOURCE', '-O2', '-I', str(folder), '-I', str(HERE), '-I', str(MENU),
                            *(['-DV3_CACHE'] if profile == 'latency-v3' else []), str(source),
                            str(folder / 'gpe-raster.c'), str(MENU / 'gpe-sprite.c'), '-o', str(binary)], check=True)
            cls.workers[profile] = binary

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_binary(self, binary, label, *args):
        path = self.work / (label + '.sparse')
        env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
        result = subprocess.run([str(binary), str(path), *map(str, args)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_core_real_shared_mapping(self):
        output = self.run_binary(self.binaries[0], 'core-normal')
        self.assertEqual(output.count('_PASS'), 8)

    def test_core_asan_ubsan(self):
        output = self.run_binary(self.binaries[1], 'core-sanitized')
        self.assertEqual(output.count('_PASS'), 8)

    def test_actual_workers_pixels_callbacks_and_real_fin(self):
        for mode in (0, 1, 4):
            old = self.run_binary(self.workers['latency-v1'], 'old-' + str(mode), mode)
            new = self.run_binary(self.workers['latency-v3'], 'new-' + str(mode), mode)
            self.assertEqual(old, new)

    def test_flush_failure_no_completion_and_fin_no_unmap(self):
        text = self.run_binary(self.workers['latency-v3'], 'unmap-failure', 2)
        self.assertIn('FLUSH_REAL_UNMAP_FAILURE_NO_COMPLETION_FIN_REFUSED_PASS', text)

    def test_dirty_fin_rejected_and_clean_fin_seals_admission(self):
        text = self.run_binary(self.workers['latency-v3'], 'dirty-fin', 3)
        self.assertIn('DIRTY_FIN_REFUSED_CLEAN_FIN_SEALED_PASS', text)

    def test_profile_freezes_and_source_receipts(self):
        for profile, expected in [('latency-v1', API['V1_DERIVED_SHA256']), ('latency-v2', API['V2_DERIVED_SHA256'])]:
            for name, digest in expected.items():
                self.assertEqual(hashlib.sha256((self.work / profile / name).read_bytes()).hexdigest(), digest)
        v3 = self.receipts['latency-v3']['lcd_pipeline']
        self.assertEqual(v3['profile'], 'latency-v3')
        self.assertEqual(v3['v1_source_sha256'], API['V1_DERIVED_SHA256'])
        self.assertFalse(v3['performance_verified'])
        for name in ('lcd-map-cache.c', 'lcd-map-cache.h'):
            self.assertEqual(v3['cache_model_sources'][name], hashlib.sha256((HERE / name).read_bytes()).hexdigest())
            self.assertEqual((HERE / name).read_bytes(), (self.work / 'latency-v3' / name).read_bytes())
        for name in ('headless-osd.c', 'sony-lz77.c', 'gpe-raster.c'):
            self.assertEqual((self.work / 'latency-v1' / name).read_bytes(), (self.work / 'latency-v3' / name).read_bytes())
        observer = (self.work / 'latency-v3/menu-observe.c').read_text()
        self.assertNotIn('full_lcd_add(', observer)
        self.assertEqual(observer.count('lcd_map_acquire(&full_lcd_maps,'), 3)
        self.assertIn('FULL_LCD_CACHE_', observer)
        with self.assertRaisesRegex(ValueError, 'fresh output'):
            BUILD(MENU, self.work / 'root', self.work / 'latency-v1', lcd_pipeline_profile='latency-v3')
        before = (self.work / 'latency-v1/menu-observe.c').read_text()
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            API['observer_v3_source'](before.replace('void *dst = mmap(0, dst_length,', 'void *dst = changed(0, dst_length,'))

    def test_frame_snapshot_and_original_v1_stage_timing(self):
        folder = self.work / 'latency-v3'
        log = self.work / 'frame-stats.jsonl'
        source = self.work / 'frame-stats.c'
        source.write_text(r'''
#include <assert.h>
#include <errno.h>
#include "lcd-pipeline.h"
static struct lcd_map_stats state;
void full_lcd_map_snapshot(struct lcd_map_stats *out) { *out=state; }
int main(void) {
    state.hits=80;state.maps=20;state.unmaps=20;state.flushes=20;
    errno=EDOM;lcd_pipeline_event(0,"consume",0x1003,1,1,0);state.hits=999;
    lcd_pipeline_event(0,"capture",0x1003,1,1,0);lcd_pipeline_event(0,"hash",0x1003,1,1,0);
    lcd_pipeline_event(0,"persist",0x1003,1,1,0);lcd_pipeline_event(0,"ack",0x1003,1,1,0);
    assert(errno==EDOM);return 0;
}
''')
        binary = self.work / 'frame-stats'
        subprocess.run(['clang', '-O2', '-I', str(folder), '-DLCD_PIPELINE_PATH=' + json.dumps(str(log)),
                        str(source), '-o', str(binary)], check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        line = json.loads(log.read_text())
        self.assertEqual(line['profile'], 'latency-v3')
        self.assertEqual(line['map_hits'], 80)
        self.assertEqual(line['map_maps'], 20)
        self.assertEqual(line['map_unmaps'], 20)
        self.assertEqual(line['map_flushes'], 20)
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        stages = [line[name + '_guest_ns'] for name in ('consume', 'capture', 'hash', 'persist', 'ack')]
        self.assertEqual(stages, sorted(stages))


if __name__ == '__main__':
    unittest.main()
