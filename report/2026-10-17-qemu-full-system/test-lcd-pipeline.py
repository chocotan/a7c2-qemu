#!/usr/bin/env python3
"""Host C differential/fault tests; never runs a VM or writes a canonical root."""
import ast
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'lcd-pipeline.py'))
BUILD = runpy.run_path(str(HERE / 'build-imaging.py'))['build']
MENU = HERE / 'runtime/native-source-snapshots' / API['BASE_PIN_SHA256'] / 'runtime/analysis'
LENGTHS = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 32, 64]


class Plan(C.Structure):
    _fields_ = [(name, C.c_ulonglong if name in ('destination', 'source') else C.c_ulong)
                for name in ('destination', 'source', 'destination_span', 'source_span',
                             'destination_offset', 'source_offset', 'destination_pitch', 'source_pitch', 'line')]
    _fields_ += [('rows', C.c_uint)]


def compressed(tokens):
    out = bytearray([0xf0])
    for start in range(0, len(tokens), 8):
        group = tokens[start:start + 8]
        out.append(sum(1 << bit for bit, t in enumerate(group) if isinstance(t, bytes)))
        for token in group:
            out.extend(token if isinstance(token, bytes) else bytes([token]))
    return bytes(out)


HEADLESS_TEST = r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "headless-osd.h"
static int mode, interrupted, fs_interrupted, received, sent, errors;
static unsigned long checked, calls, maximum;
static unsigned char fix[12] = {2,16,0,0,0,0,0,0,3,16,0,0};
static unsigned char descriptor[36] = {3,16,0,0,0,0,0,0,2,4,0,0,0,0,0,0,0,0,0,0,128,2,224,1};
long __real_pread(int,void *,unsigned long,long);
long __real_write(int,const void *,unsigned long);
int __real_fsync(int), __real_close(int), __real_rename(const char *,const char *);
long __wrap_pread(int fd, void *buf, unsigned long count, long off) {
    if (mode==2 && !interrupted++) { errno=EINTR; return -1; }
    if (mode==3) { errno=EIO; return -1; }
    if (mode==9) return 0;
    if (mode==10) return count+1;
    if (mode==1 && count>17) count=17;
    long n=__real_pread(fd,buf,count,off);
    if (n>0) {
        if (mode==4 && (unsigned long)(off+n)>=HOSD_BYTES) ((unsigned char *)buf)[n-1]^=1;
        checked+=n; calls++; if ((unsigned long)n>maximum) maximum=n;
    }
    return n;
}
long __wrap_write(int fd,const void *buf,unsigned long count) {
    if (mode==5) { errno=EIO; return -1; }
    if (mode==11) return 0;
    if (mode==1 && count>23) count=23;
    return __real_write(fd,buf,count);
}
int __wrap_fsync(int fd) {
    if (mode==2 && !fs_interrupted++) { errno=EINTR; return -1; }
    if (mode==6) { errno=EIO; return -1; }
    return __real_fsync(fd);
}
int __wrap_close(int fd) { int rc=__real_close(fd); if(mode==7){errno=EIO;return -1;}return rc; }
int __wrap_rename(const char *a,const char *b) { if(mode==8){errno=EIO;return -1;}return __real_rename(a,b); }
static int receive_msg(unsigned int q,void **p,long timeout) {
    (void)timeout; assert(q==(received?HOSD_UPDATE:HOSD_CONTROL));
    *p=received++ ? descriptor : fix; return 0;
}
static unsigned int size_msg(void *p) { return p==fix?12:36; }
static unsigned int source_msg(void *p) { (void)p;return HOSD_AP; }
static int release_msg(unsigned int q,void *p) { (void)q;(void)p;return 0; }
static int allocate_msg(unsigned int q,void **p,unsigned int n,unsigned int flags) {
    static unsigned char reply[8];assert(q==HOSD_AP && n==8 && flags==1);*p=reply;return 0;
}
static void set_source(void *p,unsigned int source) { (void)p;assert(source==HOSD_CONTROL); }
static int send_msg(unsigned int q,void *p) { assert(q==HOSD_AP && ((unsigned char *)p)[0]==3);sent++;return 0; }
static int frame(struct hosd_frame *f,unsigned char *p) {
    f->physical=0x438a16100UL;
    for(unsigned long i=0;i<HOSD_PIXELS;i++) p[i]=(i*37+9)&255;
    return 0;
}
static void log_msg(const char *prefix,const char *text) {
    (void)text;if(!strcmp(prefix,"OSD_HEADLESS_FAILED ")) errors++;
}
int main(int argc,char **argv) {
    assert(argc==2);
    for(int trial=0;trial<12;trial++) {
        char path[512];snprintf(path,sizeof path,"%s/frame-%d",argv[1],trial);
        mode=trial;interrupted=fs_interrupted=received=sent=errors=0;checked=calls=maximum=0;
        struct hosd_state *s=calloc(1,sizeof *s);assert(s);
        struct hosd_ops ops={receive_msg,size_msg,source_msg,release_msg,allocate_msg,set_source,send_msg,frame,log_msg,0};
        assert(!hosd_step(s,&ops,path));
        int rc=hosd_step(s,&ops,path);
        if(trial<3) {
            assert(!rc && sent==1 && s->sequence==1 && !s->failed && !errors && checked==HOSD_BYTES);
            if(trial!=1) assert(maximum==VERIFY_BYTES && calls==(HOSD_BYTES+VERIFY_BYTES-1)/VERIFY_BYTES);
            mode=0;int fd=open(path,O_RDONLY);assert(fd>=0);
            unsigned char *raw=malloc(HOSD_BYTES);assert(read(fd,raw,HOSD_BYTES)==HOSD_BYTES);close(fd);
            unsigned long hash;memcpy(&hash,raw+40,8);memset(raw+40,0,8);assert(hash==hosd_hash(raw,HOSD_BYTES));
            assert(!memcmp(raw,"HOSDAP02",8));free(raw);
        } else {
            assert(rc==-1 && !sent && s->failed && errors==1 && !s->sequence);
            assert(hosd_step(s,&ops,path)==-1 && !sent);
        }
        free(s);
    }
    puts("HEADLESS_COMPLETE_READBACK_SHORT_EINTR_IO_CRC_NO_ACK_PASS");
}
'''


V2_WRAPPER_FIXTURE = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gpe-copy.h"
#include "gpe-sprite.h"
#include "sony-lz77.h"
#include "lcd-pipeline.h"
typedef unsigned long size_t;
static int mode, software_gpe=1, software_rgba4444=1, raster_fd=10, raster_failed;
static unsigned long osd_libobj_base=0x100000;
static int maps, unmaps, locks, unlocks, callbacks, logs, captures;
static unsigned char memory[2][4096], output[64];
static unsigned char headless_raster_mutex[64];
static int host_mutex_lock(void *p) { (void)p;locks++;if(mode==1){errno=EBUSY;return 16;}return 0; }
static int host_mutex_unlock(void *p) { (void)p;unlocks++;if(mode==5){errno=EIO;return 5;}return 0; }
static void *host_mmap(void *p,size_t n,int prot,int flags,int fd,unsigned long off) {
    (void)p;(void)n;(void)prot;(void)flags;(void)fd;(void)off;
    int index=maps++;if(mode==2 || (mode==3 && index==1)){errno=ENOMEM;return (void *)-1;}return memory[index&1];
}
static int host_munmap(void *p,size_t n) { (void)p;(void)n;unmaps++;if(mode==4){errno=EIO;return -1;}return 0; }
#define pthread_mutex_lock host_mutex_lock
#define pthread_mutex_unlock host_mutex_unlock
#define mmap host_mmap
#define munmap host_munmap
static int host_complete(unsigned int source,const void *data,size_t n) {
    assert(source==0x123 && n==4 && !*(const int *)data);callbacks++;errno=EPIPE;return mode!=6;
}
static int (*real_draw_complete)(unsigned int,const void *,size_t)=host_complete;
static int fallback_fill(int a,int b,unsigned int c,unsigned int d,const void *p) {
    (void)a;(void)b;(void)c;(void)d;(void)p;errno=ENOTTY;return -71;
}
static int fallback_blit(int a,int b,unsigned int c,unsigned int d,const void *p) {
    (void)a;(void)b;(void)c;(void)d;(void)p;errno=ENOTTY;return -72;
}
static int (*real_worker_fill)(int,int,unsigned int,unsigned int,const void *)=fallback_fill;
static int (*real_worker_blit)(int,int,unsigned int,unsigned int,const void *)=fallback_blit;
static void record(const char *prefix,const char *text) { assert(prefix && text);logs++;errno=EALREADY; }
static void capture_gpe(int a,int b,int c,const void *p,size_t n) { (void)a;(void)b;(void)c;(void)p;(void)n;captures++; }
extern int gpe_uniform_fill(unsigned char *,unsigned long,const unsigned int *);
static void *host_image_lock(void *p,unsigned int *stride) {
    (void)p;*stride=32;if(mode==1){errno=EBUSY;return 0;}return output;
}
static void host_image_unlock(void *p) { (void)p;unlocks++;errno=EPIPE; }
static void host_image_size(void *p,unsigned short *w,unsigned short *h) { (void)p;*w=2;*h=2; }
/* EXACT_BODIES */
int main(void) {
    unsigned int fill[16]={0x10000000,4,0,0,2,2,8,0,0,0x1ff00};
    unsigned int blit[36]={0};
    blit[0]=0x10000000;blit[1]=4;blit[4]=blit[5]=2;blit[12]=8;
    blit[14]=0x10001000;blit[15]=4;blit[18]=blit[19]=2;blit[22]=8;blit[28]=0xff0000;
    unsigned long stream_table[12]={0},image_table[12]={0};
    unsigned char stream[24]={0},image[16]={0},object[64]={0},input[68]={15,0,64,0};
    for(int i=4;i<68;i++)input[i]=(unsigned char)i;
    stream_table[11]=osd_libobj_base+0x133cc8;image_table[11]=(unsigned long)host_image_size;
    *(unsigned long *)stream=(unsigned long)stream_table;*(void **)(stream+16)=input;
    *(unsigned long *)image=(unsigned long)image_table;
    *(void **)(object+8)=stream;*(void **)(object+16)=image;
    *(unsigned int *)(object+24)=7;*(unsigned short *)(object+28)=2;*(unsigned short *)(object+30)=2;
    *(unsigned int *)(object+32)=68;
    for(mode=0;mode<10;mode++) {
        software_gpe=mode!=9;
        for(int operation=0;operation<4;operation++) {
            maps=unmaps=locks=unlocks=callbacks=logs=captures=0;raster_failed=0;
            memset(memory,0x5a,sizeof memory);memset(output,0xa5,sizeof output);
            unsigned int saved_flags=blit[28],saved_width=blit[8],saved_height=blit[9];
            if(operation==3) { blit[28]=0x7f0001;blit[8]=blit[9]=2; }
            if(mode==8) blit[28]=0x7f0000;
            errno=EDOM;
            long rc=operation==0 ? software_fill_worker(0,0,7,0x123,mode==7?0:fill)
                : (operation==1 || operation==3) ? software_blit_worker(0,0,7,0x123,mode==7?0:blit)
                : (long)software_lz_decode(mode==7?0:object);
            int error=errno;
            unsigned long hash=0;for(unsigned int i=0;i<sizeof memory;i++)hash=hash*33+((unsigned char *)memory)[i];
            for(unsigned int i=0;i<sizeof output;i++)hash=hash*33+output[i];
            printf("%d %d %ld %d %d %d %d %d %d %d %d %d %lu\n",mode,operation,rc,error,raster_failed,maps,unmaps,locks,unlocks,callbacks,logs,captures,hash);
            blit[28]=saved_flags;blit[8]=saved_width;blit[9]=saved_height;
        }
    }
#ifdef V2_CHECK_COUNTERS
    struct full_lcd_counters counters;full_lcd_snapshot(&counters);
    assert(counters.calls[FULL_LCD_FILL_TOTAL]==9 && counters.calls[FULL_LCD_BLIT_TOTAL]==18);
    assert(counters.calls[FULL_LCD_RESOURCE_TOTAL]==10);
    assert(counters.calls[FULL_LCD_FILL] && counters.calls[FULL_LCD_COPY] && counters.calls[FULL_LCD_SPRITE]);
    assert(counters.calls[FULL_LCD_LZ] && counters.bytes[FULL_LCD_LZ]);
#endif
    return 0;
}
'''


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        API['validate'](MENU, MENU / 'menu-observe.c')
        cls.temporary = tempfile.TemporaryDirectory(prefix='lcd-pipeline-host-')
        cls.work = Path(cls.temporary.name)
        cls.models = []
        for variant in ('base', 'derived'):
            dest = cls.work / variant
            dest.mkdir()
            for name, fn in [('sony-lz77.c', 'codec_source'), ('gpe-raster.c', 'raster_source')]:
                text = (MENU / name).read_text()
                (dest / name).write_text(API[fn](text) if variant == 'derived' else text)
            lib = dest / 'model.so'
            subprocess.run(['clang', '-O2', '-shared', '-fPIC', '-I', str(MENU),
                            str(dest / 'sony-lz77.c'), str(dest / 'gpe-raster.c'), '-o', str(lib)], check=True)
            model = C.CDLL(str(lib))
            model.sony_lz77_decode.argtypes = [C.c_void_p, C.c_ulong, C.c_void_p, C.c_ulong]
            model.gpe_copy_rows.argtypes = [C.c_void_p, C.c_ulong, C.c_void_p, C.c_ulong, C.POINTER(Plan)]
            model.gpe_uniform_fill.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(C.c_uint)]
            cls.models.append(model)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def decode(self, raw, count, expected=None):
        src = C.create_string_buffer(raw)
        results = []
        for model in self.models:
            target = C.create_string_buffer(b'\xa5' * (count + 16))
            rc = model.sony_lz77_decode(src, len(raw), target, count)
            self.assertEqual(target.raw[count:count + 16], b'\xa5' * 16)
            if rc:
                self.assertEqual(target.raw[:count], b'\xa5' * count)
            if expected is not None:
                self.assertEqual((rc, target.raw[:count]), (0, expected))
            results.append((rc, target.raw))
        self.assertEqual(*results)

    def test_codec_all_lengths_all_distances(self):
        for code, length in enumerate(LENGTHS):
            for distance in range(1, 4096):
                seed = bytes((i * 37 + 9) & 255 for i in range(distance))
                tokens = list(seed) + [bytes([(code << 4) | (distance >> 8), distance & 255]), b'\0\0']
                raw = compressed(tokens)
                expected = seed + (seed * ((length + distance - 1) // distance))[:length]
                self.decode(raw, len(expected), expected)

    def test_codec_literals_truncation_boundaries_random(self):
        rng = random.Random(0x1003)
        for length in (1, 2, 3, 15, 16, 255, 256, 4095, 65535):
            data = rng.randbytes(length)
            raw = b'\x0f\0' + length.to_bytes(2, 'little') + data
            self.decode(raw, length, data)
            self.decode(raw, length - 1)
            self.decode(raw[:-1], length)
        for code, length in enumerate(LENGTHS):
            raw = compressed(list(range(17)) + [bytes([code << 4, 17]), b'\0\0'])
            for end in range(len(raw)):
                self.decode(raw[:end], 17 + length)
            self.decode(raw + b'\0', 17 + length)
        for _ in range(250):
            data = rng.randbytes(rng.randint(1, 200))
            literal = b'\x0f\0' + len(data).to_bytes(2, 'little') + data
            self.decode(literal, len(data), data)
            damaged = bytearray(literal);damaged[rng.randrange(len(damaged))] ^= 0x80
            self.decode(bytes(damaged), len(data))
        for model in self.models:
            raw = C.create_string_buffer(b'\x0f\0\x01\0a' + b'\xa5' * 16)
            before = raw.raw
            self.assertEqual(model.sony_lz77_decode(raw, 5, raw, 1), 5)
            self.assertEqual(raw.raw, before)
            self.assertEqual(model.sony_lz77_decode(raw, 5, None, 0x1000001), 5)
            self.assertEqual(model.sony_lz77_decode(raw, 5, None, 1), 0)

    def test_rows_pitch_capacity_selfalias_overlap_sentinels(self):
        rng = random.Random(0x4444)
        for line in (0, 1, 2, 3, 16, 64):
            for dp in (0, 1, 15, 64, 128):
                for sp in (0, 1, 15, 64, 128):
                    for do, so in ((0, 0), (0, 1), (1, 0), (0, 17), (17, 0), (64, 128)):
                        for rows in (0, 1, 4):
                            plan = Plan(0, 0, do + max(rows - 1, 0) * dp + line,
                                        so + max(rows - 1, 0) * sp + line, do, so, dp, sp, line, rows)
                            initial = rng.randbytes(1024)
                            results = []
                            for model in self.models:
                                buf = C.create_string_buffer(initial)
                                rc = model.gpe_copy_rows(buf, 1024, buf, 1024, C.byref(plan))
                                self.assertEqual(rc, 0)
                                results.append(buf.raw)
                                bad = C.create_string_buffer(initial)
                                if plan.destination_span:
                                    self.assertEqual(model.gpe_copy_rows(bad, plan.destination_span - 1,
                                                                        bad, 1024, C.byref(plan)), 5)
                                    self.assertEqual(bad.raw[:1024], initial)
                                if plan.source_span:
                                    self.assertEqual(model.gpe_copy_rows(bad, 1024, bad,
                                                                        plan.source_span - 1, C.byref(plan)), 5)
                                    self.assertEqual(bad.raw[:1024], initial)
                            self.assertEqual(*results)

    def test_uniform_fill_pitch_capacity_value_sentinels(self):
        for fmt in (0, 1):
            for value in (0, 1, 15, 16, 127, 255):
                for width in (1, 2, 17):
                    for x in (0, 1, 5):
                        for height in (1, 4):
                            stride = width + x + 3
                            p = (C.c_uint * 14)(0, 0, x, 1, width, height, stride, fmt,
                                               value * 0x1010101, 0x1ff00)
                            last = ((height * stride) + x + width) * (4 if fmt else 2)
                            for capacity in (last - 1, last, 1024):
                                result = []
                                for model in self.models:
                                    buf = C.create_string_buffer(b'\xa5' * 1024)
                                    rc = model.gpe_uniform_fill(buf, capacity, p)
                                    if rc:
                                        self.assertEqual(buf.raw[:1024], b'\xa5' * 1024)
                                    result.append((rc, buf.raw))
                                self.assertEqual(*result)

    def test_headless_full_readback_faults_no_ack_and_timing(self):
        harness = self.work / 'headless-test.c'
        harness.write_text(HEADLESS_TEST)
        for variant, chunk in [('base', 4096), ('derived', 65536)]:
            work = self.work / ('hosd-' + variant);work.mkdir()
            source = work / 'headless-osd.c'
            text = (MENU / 'headless-osd.c').read_text()
            source.write_text(API['headless_source'](text) if variant == 'derived' else text)
            (work / 'lcd-pipeline.h').write_text(API['TIMING_HEADER'])
            log = work / 'pipeline.jsonl'
            binary = work / 'check'
            subprocess.run(['clang', '-O2', '-I', str(MENU), '-I', str(work),
                            f'-DVERIFY_BYTES={chunk}', '-DLCD_PIPELINE_PATH=' + json.dumps(str(log)),
                            str(harness), str(source),
                            *['-Wl,--wrap=' + n for n in ('pread', 'write', 'fsync', 'close', 'rename')],
                            '-o', str(binary)], check=True)
            result = subprocess.run([str(binary), str(work)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if variant == 'derived':
                self.assertEqual(log.stat().st_mode & 0o777, 0o600)
                lines = [json.loads(s) for s in log.read_text().splitlines()]
                self.assertEqual(len([s for s in lines if s['event'] == 'ack']), 3)
                for line in lines:
                    self.assertEqual(line['profile'], 'latency-v1')
                    self.assertEqual(line['command'], 0x1003)
                    values = [line[k + '_guest_ns'] for k in ('consume', 'capture', 'hash', 'persist', 'ack')]
                    values = [n for n in values if n]
                    self.assertEqual(values, sorted(values))
                    self.assertEqual(line['rc'] == 0, line['event'] == 'ack')

    def test_timing_sampling_input_suffix_and_errno(self):
        work = self.work / 'timing';work.mkdir()
        log = work / 'timing.jsonl'
        (work / 'lcd-pipeline.h').write_text(API['TIMING_HEADER'])
        source = work / 'check.c'
        source.write_text(r'''
#include <assert.h>
#include <errno.h>
#include <string.h>
#include "lcd-pipeline.h"
int main(void) {
    char text[256]="tid=7 code=0x17d status=0";
    errno=EDOM;lcd_pipeline_input_stamp(text,sizeof text);
    assert(errno==EDOM && strstr(text," status=0 guest_ns=") && strstr(text," profile=latency-v1"));
    const char *stages[]={"consume","capture","hash","persist","ack"};
    for(unsigned int cmd=0x1003;cmd<=0x1005;cmd+=2)
        for(unsigned long seq=1;seq<=33;seq++)
            for(int stage=0;stage<5;stage++) {
                errno=EDOM;lcd_pipeline_event(0,stages[stage],cmd,seq,seq,0);assert(errno==EDOM);
            }
    return 0;
}
''')
        binary = work / 'check'
        subprocess.run(['clang', '-O2', '-DLCD_PIPELINE_PATH=' + json.dumps(str(log)),
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
        lines = [json.loads(s) for s in log.read_text().splitlines()]
        self.assertEqual(len([s for s in lines if s['command'] == 0x1003]), 33)
        self.assertEqual([s['seq'] for s in lines if s['command'] == 0x1005], [16, 32])
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_wrong_base_unique_overlap_profile_and_scratch_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            fake = work / 'fake';fake.mkdir()
            for name in API['BASE_SHA256']:
                (fake / name).write_bytes((MENU / name).read_bytes())
            (fake / 'sony-lz77.c').write_text('unknown source')
            with self.assertRaisesRegex(ValueError, 'fixed base SHA256'):
                BUILD(fake, work / 'root', work / 'out', lcd_pipeline_profile='latency-v1')
            self.assertFalse((work / 'out').exists())
            with self.assertRaisesRegex(ValueError, 'Unknown LCD'):
                BUILD(None, None, work / 'out', lcd_pipeline_profile='unknown')
            with self.assertRaisesRegex(ValueError, 'scratch'):
                API['validate_scratch'](MENU, HERE / 'runtime/analysis/root', work / 'out')
            with self.assertRaisesRegex(ValueError, 'scratch'):
                API['validate_scratch'](MENU, work / 'a/root', work / 'b/out')
            API['validate_scratch'](MENU, work / 'root', work / 'out')
            fresh = HERE.parents[1] / 'analysis/scratch/profile-guard-check/runtime/analysis'
            API['validate_scratch'](MENU, fresh / 'root', fresh / 'pipeline-src')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            API['replace_unique']('aaaa', [('aa', 'b')])
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            API['replace_unique']('abcde', [('abc', 'x'), ('cde', 'y')])
        self.assertEqual(API['replace_unique']('abc', [('a', 'b'), ('b', 'c')]), 'bcc')

    def v2_sources(self, work):
        root = work / 'root';(root / 'simulation').mkdir(parents=True)
        def compiler(cmd, **kwargs):
            Path(cmd[cmd.index('-o') + 1]).write_bytes(b'host fake compiler; no VM')
        with patch('subprocess.run', compiler):
            v1 = BUILD(MENU, root, work / 'v1', lcd_pipeline_profile='latency-v1')
            v2 = BUILD(MENU, root, work / 'v2', lcd_pipeline_profile='latency-v2')
        return v1, v2

    def test_v2_known_v1_bytes_guards_and_profile(self):
        work = self.work / 'v2-guards';work.mkdir()
        v1, v2 = self.v2_sources(work)
        self.assertEqual(v1['lcd_pipeline']['profile'], 'latency-v1')
        self.assertEqual(v2['lcd_pipeline']['profile'], 'latency-v2')
        for name, digest in API['V1_DERIVED_SHA256'].items():
            self.assertEqual(hashlib.sha256((work / 'v1' / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(v2['lcd_pipeline']['v1_source_sha256'][name], digest)
        self.assertEqual((work / 'v1/headless-osd.c').read_bytes(), (work / 'v2/headless-osd.c').read_bytes())
        with self.assertRaisesRegex(ValueError, 'fresh output'):
            BUILD(MENU, work / 'root', work / 'v1', lcd_pipeline_profile='latency-v2')
        # A common adapter change must be rejected even when the original pin matches.
        before = (work / 'v1/menu-observe.c').read_text()
        self.assertEqual(before.count('static unsigned long software_lz_decode(void *object) {'), 1)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            API['observer_v2_source'](before.replace('    int result = gpe_uniform_fill(', '    int changed = gpe_uniform_fill('))
        fake = work / 'fake';fake.mkdir()
        for name in API['V2_BASE_SHA256']:
            (fake / name).write_bytes((MENU / name).read_bytes())
        (fake / 'gpe-sprite.c').write_text('unknown')
        with self.assertRaisesRegex(ValueError, 'fixed base SHA256'):
            API['validate_v2'](fake, work / 'fresh')
        observer = (work / 'v2/menu-observe.c').read_text()
        self.assertIn('if (v[2]==1) full_lcd_input_counters(input,sizeof input);', observer)
        self.assertEqual(observer.count('full_lcd_add(FULL_LCD_FILL,compute_start,'), 1)
        self.assertEqual(observer.count('full_lcd_add(use_sprite ? FULL_LCD_SPRITE : FULL_LCD_COPY,compute_start,'), 1)

    def test_v2_actual_wrapper_returns_errno_pixels_and_completion_unchanged(self):
        work = self.work / 'v2-wrappers';work.mkdir()
        self.v2_sources(work)
        results = []
        for variant in ('v1', 'v2'):
            dest = work / variant
            observer = (dest / 'menu-observe.c').read_text()
            resource_name = 'software_lz_decode' if variant == 'v1' else 'full_lcd_resource_body'
            begin = observer.index('static unsigned long ' + resource_name + '(void *object) {')
            resource = observer[begin:observer.index('static unsigned long observe_lz_decode(', begin)]
            resource = resource.replace('((lock_t)(osd_libobj_base + 0x130de8))', 'host_image_lock')
            resource = resource.replace('((unlock_t)(osd_libobj_base + 0x130e00))', 'host_image_unlock')
            # Host image lock/unlock replace only the two fixed firmware-address calls.
            worker_start = observer.index('static int raster_completion(unsigned int sequence, unsigned int source, const unsigned char *callback_info) {')
            workers = observer[worker_start:observer.index('int software_flush_worker(', worker_start)]
            bodies = resource + '\n' + workers
            if variant == 'v2':
                bodies = 'static unsigned long software_lz_decode(void *object);\n' + bodies + API['V2_OBSERVER_SUPPORT']
            else:
                (dest / 'lcd-pipeline.h').write_text(API['timing_v2_header']())
            source = dest / 'wrapper-check.c'
            source.write_text(V2_WRAPPER_FIXTURE.replace('/* EXACT_BODIES */', bodies))
            binary = dest / 'wrapper-check'
            subprocess.run(['clang', '-O2', '-I', str(dest), '-I', str(MENU),
                            *(['-DV2_CHECK_COUNTERS'] if variant == 'v2' else []),
                            str(source), str(dest / 'gpe-raster.c'), str(MENU / 'gpe-sprite.c'),
                            str(dest / 'sony-lz77.c'), '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            results.append(result.stdout)
        self.assertEqual(*results)
        self.assertEqual(len(results[0].splitlines()), 40)

    def test_v2_actual_record_mirror_maximum_counters_complete(self):
        work = self.work / 'v2-mirror';work.mkdir()
        self.v2_sources(work)
        observer = (work / 'v2/menu-observe.c').read_text()
        start = observer.index('static void record(const char *prefix, const char *name) {')
        record = observer[start:observer.index('void *dlopen(', start)]
        text = 'tid=9223372036854775807 queue=0x5503e0 message=0xffffffffffffffff code=0xffffffff status=1 prev=0 repeat=4294967295 from=4294967295 inh=255 guest_ns=18446744073709551615 profile=latency-v2 counters_guest_ns=18446744073709551615'
        text += ''.join(' ' + name + '=18446744073709551615' for name, _ in API['COUNTER_FIELDS'])
        self.assertLess(len(text), 1024)
        self.assertGreater(len(text), 512)
        source = work / 'check.c'
        source.write_text(r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
static unsigned char *memory_log;
static char mirror[2048];static unsigned long used;
static int mirror_open(const char *p,int flags,...) { (void)p;(void)flags;return 7; }
static long mirror_write(int fd,const void *p,unsigned long n) {
    assert(fd==7 && used+n<sizeof mirror);memcpy(mirror+used,p,n);used+=n;errno=EDOM;return (long)n;
}
#define open mirror_open
#define write mirror_write
#define MENU_OBSERVE_TRANSPORT_SELFTEST
''' + record + '\nint main(void) { const char *input=' + json.dumps(text) + r''';
    errno=EDOM;record("FULL_INPUT_RECEIVE ",input);
    assert(errno==EDOM && used==strlen(input)+strlen("OBS FULL_INPUT_RECEIVE ")+1 && mirror[used-1]=='\n');
    assert(!memcmp(mirror,"OBS FULL_INPUT_RECEIVE ",strlen("OBS FULL_INPUT_RECEIVE ")));
    assert(!memcmp(mirror+strlen("OBS FULL_INPUT_RECEIVE "),input,strlen(input)));
    fwrite(mirror,1,used,stdout);return 0;
}
''')
        binary = work / 'check'
        subprocess.run(['clang', '-O2', '-include', 'unistd.h', str(source), '-o', str(binary)], check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, 'OBS FULL_INPUT_RECEIVE ' + text + '\n')
        for name, _ in API['COUNTER_FIELDS']:
            self.assertIn(' ' + name + '=18446744073709551615', result.stdout)

    def test_v2_concurrent_monotone_snapshot_diff_and_consume_piggyback(self):
        work = self.work / 'v2-counters';work.mkdir()
        (work / 'lcd-pipeline.h').write_text(API['timing_v2_header']())
        support = API['V2_OBSERVER_SUPPORT'].split('int software_fill_worker(')[0]
        source = work / 'check.c'
        source.write_text(r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <string.h>
#define clock_gettime full_lcd_test_clock
#include "lcd-pipeline.h"
#undef clock_gettime
int full_lcd_test_clock(int id,struct lcd_pipeline_timespec *out) {
    struct timespec t;int rc=clock_gettime(id,&t);
    if (!rc) { out->tv_sec=t.tv_sec;out->tv_nsec=t.tv_nsec; }return rc;
}
''' + support + r'''
static void *writer(void *p) {
    (void)p;for(int i=0;i<2000;i++) { errno=EDOM;full_lcd_add(FULL_LCD_FILL,0,8);assert(errno==EDOM); }return 0;
}
int main(void) {
    struct full_lcd_counters previous={0},current,baseline;
    pthread_t threads[4];
    full_lcd_snapshot(&baseline);
    for(int i=0;i<4;i++)assert(!pthread_create(&threads[i],0,writer,0));
    for(int i=0;i<2000;i++) {
        full_lcd_snapshot(&current);
        for(int k=0;k<FULL_LCD_KINDS;k++) {
            assert(current.ns[k]>=previous.ns[k] && current.calls[k]>=previous.calls[k] && current.bytes[k]>=previous.bytes[k]);
        }
        previous=current;
    }
    for(int i=0;i<4;i++)assert(!pthread_join(threads[i],0));
    full_lcd_snapshot(&current);
    assert(current.calls[FULL_LCD_FILL]-baseline.calls[FULL_LCD_FILL]==8000);
    assert(current.bytes[FULL_LCD_FILL]-baseline.bytes[FULL_LCD_FILL]==64000);
    assert(current.ns[FULL_LCD_FILL]==0); /* unavailable start clock never creates bogus duration */
    char input[1024]="tid=1 code=0x30 status=1";errno=EDOM;
    lcd_pipeline_input_stamp(input,sizeof input);full_lcd_input_counters(input,sizeof input);
    assert(errno==EDOM && strstr(input,"profile=latency-v2") && strstr(input," gpe_calls=8000"));
    full_lcd_add(FULL_LCD_COPY,lcd_pipeline_guest_ns(),16);
    lcd_pipeline_event(0,"consume",0x1003,1,1,0);
    full_lcd_add(FULL_LCD_COPY,lcd_pipeline_guest_ns(),32);
    lcd_pipeline_event(0,"capture",0x1003,1,1,0);lcd_pipeline_event(0,"hash",0x1003,1,1,0);
    lcd_pipeline_event(0,"persist",0x1003,1,1,0);lcd_pipeline_event(0,"ack",0x1003,1,1,0);
    lcd_pipeline_event(0,"consume",0x1005,16,1,0);lcd_pipeline_event(0,"ack",0x1005,16,1,0);
    assert(errno==EDOM);return 0;
}
''')
        log = work / 'pipeline.jsonl';binary = work / 'check'
        subprocess.run(['clang', '-O2', '-pthread', '-DLCD_PIPELINE_PATH=' + json.dumps(str(log)),
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
        lines = [json.loads(s) for s in log.read_text().splitlines()]
        self.assertEqual(lines[0]['gpe_calls'], 8001)
        self.assertEqual(lines[0]['gpe_bytes'], 64016)
        self.assertEqual(lines[0]['profile'], 'latency-v2')
        self.assertNotIn('gpe_calls', lines[1])
        self.assertGreaterEqual(lines[0]['copy_ns'], 0)

    def test_strict_default_and_original_builder_outputs_identical(self):
        # Remove just the optional hook in memory; compare every emitted byte/receipt.
        tree = ast.parse((HERE / 'build-imaging.py').read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build')
        function.body = [n for n in function.body if not (
            isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name) and n.test.left.id == 'lcd_pipeline_profile')]
        legacy = {'__file__': str(HERE / 'build-imaging.py')}
        exec(compile(tree, str(HERE / 'build-imaging.py'), 'exec'), legacy)
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary);root = work / 'root';(root / 'simulation').mkdir(parents=True)
            def compiler(cmd, **kwargs):
                Path(cmd[cmd.index('-o') + 1]).write_bytes(b'host fake compiler; no VM')
            with patch('subprocess.run', compiler):
                default = BUILD(MENU, root, work / 'out')
                first = {p.name: p.read_bytes() for p in (work / 'out').iterdir()}
                strict = BUILD(MENU, root, work / 'out', lcd_pipeline_profile='strict')
                old = legacy['build'](MENU, root, work / 'out')
                self.assertEqual(default, strict)
                self.assertEqual(default, old)
                self.assertNotIn('lcd_pipeline', default)
                self.assertEqual(first, {p.name: p.read_bytes() for p in (work / 'out').iterdir()})
                latency = BUILD(MENU, root, work / 'profile', lcd_pipeline_profile='latency-v1')
                receipt = latency['lcd_pipeline']
                self.assertFalse(receipt['performance_verified'])
                for name in ('headless-osd.c', 'sony-lz77.c', 'gpe-raster.c', 'menu-observe.c'):
                    info = receipt['source_inputs'][name]
                    self.assertEqual(info['base_sha256'], API['BASE_SHA256'][name])
                    self.assertEqual(info['derived_sha256'], hashlib.sha256((work / 'profile' / name).read_bytes()).hexdigest())
                observer = (work / 'profile/menu-observe.c').read_text()
                self.assertEqual(observer.count('lcd_pipeline_input_stamp(input,sizeof input);'), 2)
                self.assertNotIn('lcd_pipeline_input_stamp(name', observer)


if __name__ == '__main__':
    unittest.main()
