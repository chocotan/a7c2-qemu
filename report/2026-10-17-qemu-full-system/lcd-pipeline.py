#!/usr/bin/env python3
"""Scratch-only latency-v1 producer profile; strict builds never import this file.

Integration: build(menu, root, output, lcd_pipeline_profile='latency-v1') in
build-imaging.py returns the usual manifest plus lcd_pipeline. The caller must
use an isolated root/simulation and append the rebuilt observer to its fresh
initramfs and identity receipt. This module neither runs a VM nor creates cpio.

/log/qemu/lcd-pipeline.jsonl is 0600, append-only, guest CLOCK_MONOTONIC (not
host time). Every 0x1003 emits one summary with consume/capture/hash/persist/ack
timestamps; 0x1005 samples container sequences divisible by 16. A failed stage
emits its partial summary and original rc; diagnostics cannot authorize an ACK.
ack_guest_ns is after the original send, including a failed send. capture includes
metadata's retained-pixel copy; persist ends before immutable snapshot export.
diag_previous_ns measures the previous sampled summary's formatting/write cost.
root and output must be distinct siblings in an independent scratch directory;
canonical roots, the dump, pinned sources and symlinked paths are refused.
FULL_INPUT_RECEIVE/FREE_ENTER retain their original fields and gain only a
trailing guest_ns/profile. Log writes are not fsynced and can be incomplete on
abort. Clock failure is guest_ns=0. Original failure logs remain authoritative.

Source/host/cross-build are separate from VM/performance acceptance:
performance_verified=False, original_ap_100ms_verified=False until main's run.
"""
import hashlib
from pathlib import Path

BASE_PIN_SHA256 = 'f52bcbda4c15c2b238dc7bb88199af9ef95160b7722db9e2a0e94d006c19e441'
BASE_SHA256 = {
    'headless-osd.c': 'e1ccf70c9b903d245becfbb5b2e0dd7b802a54371e54a7f5d6d791061ec87848',
    'sony-lz77.c': 'cad2ac49979f08dd93cf7bd498ef66691dce35b924eccf5986eda03824328bbf',
    'gpe-raster.c': '2801954265ed4b9da5e81d2b07d1100147df63e65365ecf1405ea249fa5af4fa',
    'headless-osd.h': 'b408c13cfe820d72a91c98858a0ea86efbffbd5681c8ec4be04774a4c62db4a7',
    'sony-lz77.h': 'd11d5730a66867e564aeccc3020e4e6fa9ba63eda50885d73da47273bd9606ab',
    'gpe-copy.h': '6b7b54705cd8770cfaecf73d28d4e7c919d632bc90ab21e795c031d744fc4b00',
    'menu-observe.c': '98a0c3a77c324adbb514da470a8fc3343bc5b6455e0efc2d20c442a0c48704b2',
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def validate(menu, observer_source):
    """Reject unknown or symlinked originals before creating any output."""
    for name, expected in BASE_SHA256.items():
        path = Path(observer_source) if name == 'menu-observe.c' else Path(menu) / name
        if path.is_symlink() or not path.is_file() or sha256(path.read_bytes()) != expected:
            raise ValueError('latency-v1 fixed base SHA256 differs: ' + name)


def validate_scratch(menu, root, output):
    from tempfile import gettempdir
    root, output = Path(root).absolute(), Path(output).absolute()
    for path in (root, output):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('latency-v1 scratch paths must not contain symlinks')
    root, output = root.resolve(), output.resolve()
    # A copied build helper's HERE/root is the intended scratch, not the canonical root.
    work = root.parent
    temporary = Path(gettempdir()).resolve()
    scratch = any(p.name == 'scratch' for p in (work, *work.parents)) or temporary in work.parents
    protected = Path(menu).resolve()
    if not scratch or root == output or root.parent != output.parent or any(
            path == protected or protected in path.parents or path in protected.parents
            for path in (root, output)):
        raise ValueError('latency-v1 requires independent scratch sibling root/output')


def replace_unique(source, changes):
    """All anchors refer to the same original, and may not overlap."""
    spans = []
    for before, after in changes:
        if not before or source.count(before) != 1:
            raise ValueError('latency-v1 ambiguous source anchor: ' + before[:72])
        start = source.index(before)
        spans.append((start, start + len(before), after))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError('latency-v1 overlapping source anchors')
    for start, end, after in reversed(spans):
        source = source[:start] + after + source[end:]
    return source


TIMING_HEADER = r'''/* latency-v1: diagnostic-only, AArch64 glibc 2.25 long/long timespec ABI. */
#ifndef LCD_PIPELINE_H
#define LCD_PIPELINE_H
struct lcd_pipeline_timespec { long tv_sec, tv_nsec; };
extern int clock_gettime(int, struct lcd_pipeline_timespec *);
extern int *__errno_location(void);
extern int snprintf(char *, unsigned long, const char *, ...);
extern int open(const char *, int, ...), close(int), fchmod(int, unsigned int);
extern long write(int, const void *, unsigned long);
static unsigned long lcd_pipeline_guest_ns(void) {
    int saved = *__errno_location();
    struct lcd_pipeline_timespec t = {0, 0};
    int rc = clock_gettime(1, &t); /* CLOCK_MONOTONIC */
    *__errno_location() = saved;
    return !rc && t.tv_sec >= 0 && t.tv_nsec >= 0 && t.tv_nsec < 1000000000L
        ? (unsigned long)t.tv_sec * 1000000000UL + (unsigned long)t.tv_nsec : 0;
}
static void lcd_pipeline_input_stamp(char *text, unsigned long capacity) {
    int saved = *__errno_location();
    unsigned long n = 0, ns = lcd_pipeline_guest_ns();
    while (n < capacity && text[n]) ++n;
    if (n < capacity) snprintf(text+n, capacity-n, " guest_ns=%lu profile=latency-v1", ns);
    *__errno_location() = saved;
}
#ifndef LCD_PIPELINE_PATH
#define LCD_PIPELINE_PATH "/log/qemu/lcd-pipeline.jsonl"
#endif
#ifdef __aarch64__
#define LCD_PIPELINE_NOFOLLOW 0x8000
#else
#define LCD_PIPELINE_NOFOLLOW 0x20000
#endif
static void lcd_pipeline_event(void (*log)(const char *, const char *),
    const char *event, unsigned int command, unsigned long seq, unsigned long pixels, int rc) {
    if (command != 0x1003 && (seq & 15)) return;
    int saved = *__errno_location();
    unsigned long ns = lcd_pipeline_guest_ns();
    /* Only the original serial headless worker calls this sink. */
    static unsigned long consume_ns, capture_ns, hash_ns, persist_ns, ack_ns, diag_previous_ns;
    if (event[0] == 'c' && event[1] == 'o') {
        consume_ns = ns; capture_ns = hash_ns = persist_ns = ack_ns = 0;
    } else if (event[0] == 'c') capture_ns = ns;
    else if (event[0] == 'h') hash_ns = ns;
    else if (event[0] == 'p') persist_ns = ns;
    else if (event[0] == 'a') ack_ns = ns;
    if (!rc && event[0] != 'a') { *__errno_location() = saved; return; }
    static int fd = -2, reported;
    if (fd == -2) {
        fd = open(LCD_PIPELINE_PATH, LCD_PIPELINE_NOFOLLOW | 0x441, 0600);
        if (fd >= 0 && fchmod(fd, 0600)) { close(fd); fd = -1; }
    }
    char line[512];
    int n = snprintf(line, sizeof line,
        "{\"profile\":\"latency-v1\",\"event\":\"%s\",\"guest_ns\":%lu,\"seq\":%lu,\"command\":%u,\"pixel_source_seq\":%lu,\"rc\":%d,\"consume_guest_ns\":%lu,\"capture_guest_ns\":%lu,\"hash_guest_ns\":%lu,\"persist_guest_ns\":%lu,\"ack_guest_ns\":%lu,\"diag_previous_ns\":%lu}\n",
        event, ns, seq, command, pixels, rc, consume_ns, capture_ns, hash_ns, persist_ns, ack_ns, diag_previous_ns);
    int ok = fd >= 0 && n > 0 && (unsigned long)n < sizeof line;
    unsigned long done = 0;
    while (ok && done < (unsigned long)n) {
        long written = write(fd, line+done, (unsigned long)n-done);
        if (written < 0 && *__errno_location() == 4) continue;
        if (written <= 0 || (unsigned long)written > (unsigned long)n-done) ok = 0;
        else done += written;
    }
    if (!ok && !reported && log) {
        reported = 1;
        log("FULL_LCD_PIPELINE_LOG_ERROR ", "latency-v1 timing sink unavailable/incomplete; original rc/ACK unchanged");
    }
    unsigned long end_ns = lcd_pipeline_guest_ns();
    diag_previous_ns = end_ns >= ns && ns ? end_ns - ns : 0;
    *__errno_location() = saved;
}
#endif
'''


def codec_source(source):
    return replace_unique(source, [
        ('#include "sony-lz77.h"', '#include "sony-lz77.h"\nextern void *memcpy(void *, const void *, unsigned long);'),
        ('if (dst) for (unsigned int i = 0; i < count; ++i) dst[out + i] = src[in + i];',
         'if (dst) memcpy(dst + out, src + in, count);'),
        ('if (dst) for (unsigned int i = 0; i < count; ++i) dst[out + i] = dst[out + i - distance];',
         'if (dst) {\n'
         '                            if (count <= distance) memcpy(dst + out, dst + out - distance, count);\n'
         '                            else for (unsigned int i = 0; i < count; ++i) dst[out + i] = dst[out + i - distance];\n'
         '                        }'),
    ])


def raster_source(source):
    return replace_unique(source, [
        ('#include "gpe-copy.h"', '#include "gpe-copy.h"\nextern void *memcpy(void *, const void *, size_t);\nextern void *memset(void *, int, size_t);'),
        ('    for (unsigned int row = 0; row < plan->rows; ++row)\n'
         '        for (unsigned long byte = 0; byte < plan->line; ++byte)\n'
         '            destination[plan->destination_offset + row * plan->destination_pitch + byte] =\n'
         '                source[plan->source_offset + row * plan->source_pitch + byte];',
         '    for (unsigned int row = 0; row < plan->rows; ++row) {\n'
         '        if (!plan->line) continue;\n'
         '        unsigned char *d = destination + plan->destination_offset + row * plan->destination_pitch;\n'
         '        const unsigned char *s = source + plan->source_offset + row * plan->source_pitch;\n'
         '        unsigned long da = (unsigned long)d, sa = (unsigned long)s;\n'
         '        /* Public callers can bypass the planner: preserve forward overlap semantics. */\n'
         '        if (da <= sa ? plan->line <= sa - da : plan->line <= da - sa) memcpy(d, s, plan->line);\n'
         '        else for (unsigned long byte = 0; byte < plan->line; ++byte) d[byte] = s[byte];\n'
         '    }'),
        ('        for (size_t i = 0; i < (size_t)width * bpp; ++i) memory[((size_t)(y + row) * stride + x) * bpp + i] = value;',
         '        memset(memory + ((size_t)(y + row) * stride + x) * bpp, value, (size_t)width * bpp);'),
    ])


def headless_source(source):
    def event(stage, rc, seq='s->sequence + 1'):
        pixels = 's->pending == 0x1003 ? ' + seq + ' : s->pixel_source_seq'
        return f'    lcd_pipeline_event(o->log, "{stage}", s->pending, {seq}, {pixels}, {rc});'
    return replace_unique(source, [
        ('#include "headless-osd.h"', '#include "headless-osd.h"\n#include "lcd-pipeline.h"'),
        ('unsigned char verify[4096];', 'unsigned char verify[65536];'),
        ('    s->phase = "validate-frame";', event('consume', '0') + '\n    s->phase = "validate-frame";'),
        ('        f.physical >= 0x410000000UL && f.physical <= 0x500000000UL - HOSD_PIXELS;\n    if (ok) {',
         '        f.physical >= 0x410000000UL && f.physical <= 0x500000000UL - HOSD_PIXELS;\n' + event('capture', 'ok ? 0 : -1') + '\n    if (ok) {'),
        ('        put64(snapshot + 40, hash);', '        put64(snapshot + 40, hash);\n' + event('hash', '0')),
        ('        ok = hosd_persist(path, snapshot, HOSD_BYTES) == 0;',
         '        ok = hosd_persist(path, snapshot, HOSD_BYTES) == 0;\n' + event('persist', 'ok ? 0 : -1')),
        ('            result = o->send(HOSD_AP, reply);',
         '            result = o->send(HOSD_AP, reply);\n' + event('ack', 'result', 's->sequence')),
    ])


def observer_source(source):
    changes = []
    for prefix in ('FULL_INPUT_RECEIVE ', 'FULL_INPUT_FREE_ENTER '):
        anchor = f'        record("{prefix}",input);'
        changes.append((anchor, '        lcd_pipeline_input_stamp(input,sizeof input);\n' + anchor))
    changes.append(('const unsigned int *v=message; char input[192];',
                    'const unsigned int *v=message; char input[256];'))
    return '#include "lcd-pipeline.h"\n' + replace_unique(source, changes)


def prepare(menu, output, observer, headless, *, profile='latency-v1'):
    """Internal build hook, after build-imaging's unchanged common adapters.

    validate() must run on the selected original observer before common hooks;
    this function also rechecks the pinned model originals. No live fallback.
    """
    if profile not in ('latency-v1', 'latency-v2', 'latency-v3'):
        raise ValueError('Unknown LCD pipeline profile')
    menu, output = Path(menu), Path(output)
    validate(menu, menu / 'menu-observe.c')
    sources = {
        'menu-observe.c': observer_source(observer),
        'headless-osd.c': headless_source(headless),
        'sony-lz77.c': codec_source((menu / 'sony-lz77.c').read_text()),
        'gpe-raster.c': raster_source((menu / 'gpe-raster.c').read_text()),
        'lcd-pipeline.h': TIMING_HEADER,
    }
    v1_hashes = {name: sha256(text.encode()) for name, text in sources.items()}
    if profile in ('latency-v2', 'latency-v3') and v1_hashes != V1_DERIVED_SHA256:
        raise ValueError(profile + ' unknown v1 derived source SHA256')
    if profile == 'latency-v2':
        sources['menu-observe.c'] = observer_v2_source(sources['menu-observe.c'])
        sources['sony-lz77.c'] = codec_v2_source(sources['sony-lz77.c'])
        sources['lcd-pipeline.h'] = timing_v2_header()
    if profile == 'latency-v3':
        sources['menu-observe.c'] = observer_v3_source(sources['menu-observe.c'])
        sources['lcd-pipeline.h'] = timing_v3_header()
        for name in ('lcd-map-cache.c', 'lcd-map-cache.h'):
            sources[name] = Path(__file__).with_name(name).read_text()
    output.mkdir(parents=True, exist_ok=True)
    for name, text in sources.items():
        (output / name).write_text(text)
    return {
        'sources': {name: output / name for name in sources},
        'receipt': {
            'profile': profile, 'base_pin_sha256': BASE_PIN_SHA256,
            'implementation_sha256': sha256(Path(__file__).read_bytes()),
            'source_inputs': {name: {'base_sha256': BASE_SHA256.get(name),
                                    'derived_sha256': sha256(text.encode())}
                              for name, text in sources.items()},
            'base_headers': {name: digest for name, digest in BASE_SHA256.items() if name.endswith('.h')},
            'timing': {'path': '/log/qemu/lcd-pipeline.jsonl', 'mode': '0600',
                       'clock': 'guest CLOCK_MONOTONIC; not host time',
                       'newpixel_1003': 'one summary per transaction, all completed stage timestamps',
                       'metadata_1005': 'container seq divisible by 16 (1/16)',
                       'diagnostic_cost': 'diag_previous_ns: previous sampled summary formatting/write duration',
                       'stages': ['consume', 'capture', 'hash', 'persist', 'ack']},
            'performance_verified': False, 'original_ap_100ms_verified': False,
            'vm_executed': False,
            **({'v1_source_sha256': v1_hashes, 'v2_base_sha256': V2_BASE_SHA256,
                'aggregation': {
                    'unit': 'guest CLOCK_MONOTONIC elapsed wall ns; concurrent calls may overlap',
                    'scope': 'process cumulative completed calls; fields individually atomic, not a simultaneous cross-field transaction',
                    'input_baseline': 'FULL_INPUT_RECEIVE status=1 counters_guest_ns; no resets',
                    'frame_snapshot': '1003 consume_guest_ns; appended to its existing ACK/failed-stage summary',
                    'comparison': 'subtract the ON snapshot from the consume snapshot; window aggregate only, no causal key attribution',
                    'compute': 'gpe_fill_ns/sprite_ns/copy_ns around exact gpe_* calls; lz_ns includes codec validation and decode',
                    'whole': 'gpe_fill_total_ns/gpe_blit_total_ns/resource_total_ns include original logs/completion and all returns',
                    'other_cost': 'whole minus compute over a window is an approximation: completed outer/inner calls can cross snapshot boundaries',
                    'bytes': 'successful requested output bytes; LZ validation-only calls count zero bytes',
                }} if profile == 'latency-v2' else {}),
            **({'v1_source_sha256': v1_hashes, 'cache_contract': CACHE_CONTRACT,
                'cache_model_sources': {name: sha256(sources[name].encode())
                                        for name in ('lcd-map-cache.c', 'lcd-map-cache.h')}}
               if profile == 'latency-v3' else {}),
        },
    }


# Frozen v1 generated bytes: v2 refuses changes in common observer adapters as well.
V1_DERIVED_SHA256 = {
    'headless-osd.c': 'e77ac985a36b48dd52ed02eec15cd8ee750467f921f0d41b7caaca75d956dcb6',
    'gpe-raster.c': '9cf59f0717b33f45de4692a47f925191f2b0361538661ff8fe7a23e81b4a1b86',
    'sony-lz77.c': '8742e1dc6ea1a8345c519848aa509ca78f28041867c7ed768999f050c63eb4fc',
    'lcd-pipeline.h': '319623dc4779928420571654cf68aebe3794adc0cdf8b7b39f723c89b3d8cec4',
    'menu-observe.c': '6fc7e589efd4e480ac13c9dd10eb7af4952dba603430b9a67437899b49ff9150',
}
V2_BASE_SHA256 = {
    'gpe-sprite.c': '4f3169c27a95bd16958b2b530d116e64ffde4bcb956d945093f103ef10939832',
    'gpe-sprite.h': '991033c3ab7e1521fc5a8578fc60518868b3cc41b9b16350da9fcb68699f6819',
}


def validate_v2(menu, output):
    for name, expected in V2_BASE_SHA256.items():
        path = Path(menu) / name
        if path.is_symlink() or not path.is_file() or sha256(path.read_bytes()) != expected:
            raise ValueError('latency-v2 fixed base SHA256 differs: ' + name)
    if Path(output).exists() and any(Path(output).iterdir()):
        raise ValueError('latency-v2 requires fresh output; existing v1 sources retained')


V2_COUNTER_API = r'''
enum full_lcd_kind { FULL_LCD_FILL, FULL_LCD_SPRITE, FULL_LCD_COPY, FULL_LCD_LZ,
    FULL_LCD_FILL_TOTAL, FULL_LCD_BLIT_TOTAL, FULL_LCD_RESOURCE_TOTAL, FULL_LCD_KINDS };
struct full_lcd_counters { unsigned long ns[FULL_LCD_KINDS], calls[FULL_LCD_KINDS], bytes[FULL_LCD_KINDS]; };
__attribute__((visibility("hidden"))) void full_lcd_snapshot(struct full_lcd_counters *);
__attribute__((visibility("hidden"))) void full_lcd_add(enum full_lcd_kind, unsigned long, unsigned long);
'''
COUNTER_FIELDS = [
    ('gpe_fill_ns', 's->ns[FULL_LCD_FILL]'), ('sprite_ns', 's->ns[FULL_LCD_SPRITE]'),
    ('copy_ns', 's->ns[FULL_LCD_COPY]'), ('lz_ns', 's->ns[FULL_LCD_LZ]'),
    ('gpe_fill_total_ns', 's->ns[FULL_LCD_FILL_TOTAL]'),
    ('gpe_blit_total_ns', 's->ns[FULL_LCD_BLIT_TOTAL]'),
    ('resource_total_ns', 's->ns[FULL_LCD_RESOURCE_TOTAL]'),
    ('gpe_calls', 's->calls[0]+s->calls[1]+s->calls[2]'), ('lz_calls', 's->calls[FULL_LCD_LZ]'),
    ('gpe_worker_calls', 's->calls[FULL_LCD_FILL_TOTAL]+s->calls[FULL_LCD_BLIT_TOTAL]'),
    ('resource_calls', 's->calls[FULL_LCD_RESOURCE_TOTAL]'),
    ('gpe_bytes', 's->bytes[0]+s->bytes[1]+s->bytes[2]'), ('lz_bytes', 's->bytes[FULL_LCD_LZ]'),
]


def timing_v2_header():
    args = ', '.join(value for _, value in COUNTER_FIELDS)
    import json
    json_format = json.dumps(''.join(',"' + name + '":%lu' for name, _ in COUNTER_FIELDS))
    input_format = json.dumps(' counters_guest_ns=%lu' + ''.join(' ' + name + '=%lu' for name, _ in COUNTER_FIELDS))
    helpers = V2_COUNTER_API + r'''
static int full_lcd_append_json(char *text, unsigned long cap, int n, const struct full_lcd_counters *s) {
    if (n < 2 || (unsigned long)n >= cap) return -1;
    int saved = *__errno_location();
    unsigned long used = (unsigned long)n - 2;
    int extra = snprintf(text+used, cap-used, JSON_FORMAT, COUNTER_ARGS);
    if (extra < 0 || (unsigned long)extra + 3 > cap-used) n = -1;
    else { used += extra; text[used++] = '}'; text[used++] = '\n'; text[used] = 0; n = (int)used; }
    *__errno_location() = saved;
    return n;
}
static void full_lcd_input_counters(char *text, unsigned long cap) {
    int saved = *__errno_location();
    unsigned long used = 0, ns = lcd_pipeline_guest_ns();
    struct full_lcd_counters counters; full_lcd_snapshot(&counters);
    const struct full_lcd_counters *s = &counters;
    while (used < cap && text[used]) ++used;
    if (used < cap) snprintf(text+used, cap-used, INPUT_FORMAT, ns, COUNTER_ARGS);
    *__errno_location() = saved;
}
'''
    helpers = helpers.replace('JSON_FORMAT', json_format).replace('INPUT_FORMAT', input_format).replace('COUNTER_ARGS', args)
    source = replace_unique(TIMING_HEADER, [
        ('static void lcd_pipeline_event(', helpers + '\nstatic void lcd_pipeline_event('),
        ('    static unsigned long consume_ns, capture_ns, hash_ns, persist_ns, ack_ns, diag_previous_ns;',
         '    static unsigned long consume_ns, capture_ns, hash_ns, persist_ns, ack_ns, diag_previous_ns;\n'
         '    static struct full_lcd_counters consume_counters;'),
        ('        consume_ns = ns; capture_ns = hash_ns = persist_ns = ack_ns = 0;',
         '        consume_ns = ns; capture_ns = hash_ns = persist_ns = ack_ns = 0;\n'
         '        if (command == 0x1003) full_lcd_snapshot(&consume_counters);'),
        ('    char line[512];', '    char line[1536];'),
        ('    int ok = fd >= 0 && n > 0 && (unsigned long)n < sizeof line;',
         '    if (command == 0x1003) n = full_lcd_append_json(line,sizeof line,n,&consume_counters);\n'
         '    int ok = fd >= 0 && n > 0 && (unsigned long)n < sizeof line;'),
    ])
    return source.replace('latency-v1', 'latency-v2')


V2_OBSERVER_SUPPORT = r'''
/* Diagnostic counters have no ownership, transport or renderer state. */
static struct full_lcd_counters full_lcd_totals;
void full_lcd_snapshot(struct full_lcd_counters *out) {
    for (unsigned int k=0;k<FULL_LCD_KINDS;k++) {
        out->ns[k]=__atomic_load_n(&full_lcd_totals.ns[k],__ATOMIC_RELAXED);
        out->calls[k]=__atomic_load_n(&full_lcd_totals.calls[k],__ATOMIC_RELAXED);
        out->bytes[k]=__atomic_load_n(&full_lcd_totals.bytes[k],__ATOMIC_RELAXED);
    }
}
void full_lcd_add(enum full_lcd_kind kind, unsigned long start, unsigned long bytes) {
    int saved=*__errno_location();
    unsigned long end=lcd_pipeline_guest_ns(), elapsed=start && end>=start ? end-start : 0;
    __atomic_fetch_add(&full_lcd_totals.ns[kind],elapsed,__ATOMIC_RELAXED);
    __atomic_fetch_add(&full_lcd_totals.bytes[kind],bytes,__ATOMIC_RELAXED);
    __atomic_fetch_add(&full_lcd_totals.calls[kind],1,__ATOMIC_RELAXED);
    *__errno_location()=saved;
}
int software_fill_worker(int gpe,int core,unsigned int sequence,unsigned int source,const void *parameters) {
    if (!software_gpe) return full_lcd_fill_body(gpe,core,sequence,source,parameters);
    unsigned long start=lcd_pipeline_guest_ns();
    int result=full_lcd_fill_body(gpe,core,sequence,source,parameters);
    full_lcd_add(FULL_LCD_FILL_TOTAL,start,0);
    return result;
}
int software_blit_worker(int gpe,int core,unsigned int sequence,unsigned int source,const void *parameters) {
    if (!software_gpe) return full_lcd_blit_body(gpe,core,sequence,source,parameters);
    unsigned long start=lcd_pipeline_guest_ns();
    int result=full_lcd_blit_body(gpe,core,sequence,source,parameters);
    full_lcd_add(FULL_LCD_BLIT_TOTAL,start,0);
    return result;
}
static unsigned long software_lz_decode(void *object) {
    unsigned long start=lcd_pipeline_guest_ns();
    unsigned long result=full_lcd_resource_body(object);
    full_lcd_add(FULL_LCD_RESOURCE_TOTAL,start,0);
    return result;
}
'''


def observer_v2_source(source):
    return replace_unique(source, [
        ('static unsigned long software_lz_decode(void *object) {',
         'static unsigned long software_lz_decode(void *object);\n'
         'static unsigned long full_lcd_resource_body(void *object) {'),
        ('int software_fill_worker(int gpe, int core, unsigned int sequence, unsigned int source, const void *parameters) {',
         'static int full_lcd_fill_body(int gpe, int core, unsigned int sequence, unsigned int source, const void *parameters) {'),
        ('int software_blit_worker(int gpe, int core, unsigned int sequence, unsigned int source, const void *parameters) {',
         'static int full_lcd_blit_body(int gpe, int core, unsigned int sequence, unsigned int source, const void *parameters) {'),
        ('    int result = gpe_uniform_fill((unsigned char *)mapped + offset, bytes, p);\n'
         '    if (result && software_rgba4444) result = gpe_fill_rgba4444((unsigned char *)mapped + offset, bytes, p);',
         '    unsigned long compute_start=lcd_pipeline_guest_ns();\n'
         '    int result = gpe_uniform_fill((unsigned char *)mapped + offset, bytes, p);\n'
         '    if (result && software_rgba4444) result = gpe_fill_rgba4444((unsigned char *)mapped + offset, bytes, p);\n'
         '    full_lcd_add(FULL_LCD_FILL,compute_start,result ? 0 : (unsigned long)p[4]*p[5]*(p[7] ? 4 : 2));'),
        ('    int result = use_sprite\n'
         '        ? gpe_draw_sprite((unsigned char *)dst + dst_offset, plan.destination_span,\n'
         '                          (const unsigned char *)src + src_offset, plan.source_span, &sprite)\n'
         '        : gpe_copy_rows((unsigned char *)dst + dst_offset, plan.destination_span,\n'
         '                        (const unsigned char *)src + src_offset, plan.source_span, &plan);',
         '    unsigned long compute_start=lcd_pipeline_guest_ns();\n'
         '    int result = use_sprite\n'
         '        ? gpe_draw_sprite((unsigned char *)dst + dst_offset, plan.destination_span,\n'
         '                          (const unsigned char *)src + src_offset, plan.source_span, &sprite)\n'
         '        : gpe_copy_rows((unsigned char *)dst + dst_offset, plan.destination_span,\n'
         '                        (const unsigned char *)src + src_offset, plan.source_span, &plan);\n'
         '    full_lcd_add(use_sprite ? FULL_LCD_SPRITE : FULL_LCD_COPY,compute_start,result ? 0 : plan.line*plan.rows);'),
        ('                char line[512];\n'
         '                int n = snprintf(line, sizeof line, "OBS %s%s\\n", prefix, name ? name : "");\n'
         '                if (n > 0) {',
         '                char line[2048];\n'
         '                int n = snprintf(line, sizeof line, "OBS %s%s\\n", prefix, name ? name : "");\n'
         '                if (n > 0) {\n'
         '                    if ((unsigned long)n >= sizeof line) n = (int)sizeof line - 1;'),
        ('const unsigned int *v=*message; char input[256];', 'const unsigned int *v=*message; char input[1024];'),
        ('        record("FULL_INPUT_RECEIVE ",input);',
         '        if (v[2]==1) full_lcd_input_counters(input,sizeof input);\n'
         '        record("FULL_INPUT_RECEIVE ",input);'),
    ]) + '\n' + V2_OBSERVER_SUPPORT


def codec_v2_source(source):
    source = replace_unique(source, [
        ('#include "sony-lz77.h"', '#include "sony-lz77.h"\n#include "lcd-pipeline.h"'),
        ('int sony_lz77_decode(const unsigned char *src, unsigned long size, unsigned char *dst, unsigned long output_size) {',
         'static int full_lcd_lz_body(const unsigned char *src, unsigned long size, unsigned char *dst, unsigned long output_size) {'),
    ])
    return source + r'''
int sony_lz77_decode(const unsigned char *src,unsigned long size,unsigned char *dst,unsigned long output_size) {
    unsigned long start=lcd_pipeline_guest_ns();
    int result=full_lcd_lz_body(src,size,dst,output_size);
    full_lcd_add(FULL_LCD_LZ,start,!result && dst ? output_size : 0);
    return result;
}
'''


V2_DERIVED_SHA256 = {
    'menu-observe.c': '9d4be8d263db5736b9fb7f4e792aff7afcf56af4ae227e00182886c1c89995c8',
    'headless-osd.c': V1_DERIVED_SHA256['headless-osd.c'],
    'sony-lz77.c': 'd818b18ef2fe180bc3f34039a6a9efef44cdb91372085a01bbb89280eb65a3e5',
    'gpe-raster.c': V1_DERIVED_SHA256['gpe-raster.c'],
    'lcd-pipeline.h': '4018e9157459a6ce60fe691105873db07c5aaa09c460bebdb89d00a308f4e992',
}
CACHE_CONTRACT = {
    'model': 'explicit latency-v3 functional guest /dev/mem MAP_SHARED VMA reuse',
    'base': 'frozen latency-v1; no v2 per-call clocks; original input release unchanged',
    'slots': 8, 'alignment_bytes': 1048576, 'max_mapped_bytes': 134217728,
    'physical_range': '0x410000000 <= requested and padded spans < 0x500000000',
    'permissions': 'exact fd; complete coverage; RO never upgraded; an existing RW destination entry may serve a read request',
    'access': 'alias points to original request; no added pixel reads/writes, no bitmap reference retained',
    'bounds': 'original plan checks retained; bounded cache may reject memory/slot pressure even when individual plans fit',
    'synchronization': 'mutations use original headless_raster_mutex; stats are individually atomic',
    'release': 'commands release borrow tokens; only zero-borrow entries can be evicted',
    'flush': 'original FIFO flush, under raster mutex, really unmaps all idle entries before original completion',
    'failure': 'real unmap errors retain the VMA and errno; sticky failed state forbids later successful flush/completion',
    'fin': 'native worker-stop is unproved: no unmap in fin; clean empty cache is sealed before original fin, otherwise fin refused',
    'lifetime': 'fd must not be closed/reused while cached; no cache restart after sealed fin in the same process',
    'stats': '1003 consume snapshot appended to existing frame summary; first/every64/error flush summaries mirrored FULL_LCD_CACHE_',
    'path': 'HOSD_PATH and headless-osd.h unchanged; transport overlay is independent',
    'performance_verified': False,
}


def validate_v3(menu, output):
    validate_v2(menu, output)
    for name in ('lcd-map-cache.c', 'lcd-map-cache.h'):
        path = Path(__file__).with_name(name)
        if path.is_symlink() or not path.is_file():
            raise ValueError('latency-v3 requires ordinary project cache source: ' + name)


V3_OBSERVER_SUPPORT = r'''
void full_lcd_map_snapshot(struct lcd_map_stats *out) { lcd_map_snapshot(&full_lcd_maps,out); }
static int full_lcd_map_finish_batch(void) {
    if (pthread_mutex_lock(headless_raster_mutex)) { raster_failed=1;return 5; }
    int result=lcd_map_flush(&full_lcd_maps), saved=*__errno_location();
    if (pthread_mutex_unlock(headless_raster_mutex)) { raster_failed=1;return 5; }
    struct lcd_map_stats s; lcd_map_snapshot(&full_lcd_maps,&s);
    if (result || s.flushes==1 || !(s.flushes & 63)) {
        char text[512];
        snprintf(text,sizeof text,"profile=latency-v3 flush=%lu rc=%d errno=%d hits=%lu misses=%lu maps=%lu unmaps=%lu errors=%lu active=%lu bytes=%lu entries=%lu failed=%lu sealed=%lu",
            s.flushes,result,saved,s.hits,s.misses,s.maps,s.unmaps,s.errors,s.active,s.bytes,s.entries,s.failed,s.sealed);
        record("FULL_LCD_CACHE_FLUSH ",text);
    }
    *__errno_location()=saved;
    if (result) { raster_failed=1;return 5; }
    return 0;
}
static int full_lcd_map_fin_admit(void) {
    if (pthread_mutex_lock(headless_raster_mutex)) return -1;
    int result=lcd_map_seal_clean(&full_lcd_maps), saved=*__errno_location();
    if (pthread_mutex_unlock(headless_raster_mutex)) result=-1;
    *__errno_location()=saved;
    return result;
}
'''


def observer_v3_source(source):
    source = replace_unique(source, [
        ('#include "lcd-pipeline.h"', '#include "lcd-pipeline.h"\n'
         'static struct lcd_map_cache full_lcd_maps;\n'
         'static int full_lcd_map_finish_batch(void);\n'
         'static int full_lcd_map_fin_admit(void);'),
        ('    void *mapped = mmap(0, length, 3, 1, raster_fd, base);\n'
         '    if (mapped == (void *)-1) { pthread_mutex_unlock(headless_raster_mutex); return 5; }',
         '    struct lcd_map_borrow mapped_borrow={0};\n'
         '    if (lcd_map_acquire(&full_lcd_maps,raster_fd,base,length,3,&mapped_borrow)) { pthread_mutex_unlock(headless_raster_mutex); return 5; }\n'
         '    void *mapped=mapped_borrow.address;'),
        ('    if (munmap(mapped, length)) result = 5;',
         '    if (lcd_map_release(&full_lcd_maps,&mapped_borrow)) result = 5;'),
        ('    void *dst = mmap(0, dst_length, 3, 1, raster_fd, dst_base);\n'
         '    if (dst == (void *)-1) { pthread_mutex_unlock(headless_raster_mutex); return 5; }\n'
         '    void *src = mmap(0, src_length, 1, 1, raster_fd, src_base);\n'
         '    if (src == (void *)-1) { munmap(dst, dst_length); pthread_mutex_unlock(headless_raster_mutex); return 5; }',
         '    struct lcd_map_borrow dst_borrow={0},src_borrow={0};\n'
         '    if (lcd_map_acquire(&full_lcd_maps,raster_fd,dst_base,dst_length,3,&dst_borrow)) { pthread_mutex_unlock(headless_raster_mutex); return 5; }\n'
         '    void *dst=dst_borrow.address;\n'
         '    if (lcd_map_acquire(&full_lcd_maps,raster_fd,src_base,src_length,1,&src_borrow)) { lcd_map_release(&full_lcd_maps,&dst_borrow); pthread_mutex_unlock(headless_raster_mutex); return 5; }\n'
         '    void *src=src_borrow.address;'),
        ('    if (munmap(src, src_length)) result = 5;\n'
         '    if (munmap(dst, dst_length)) result = 5;',
         '    if (lcd_map_release(&full_lcd_maps,&src_borrow)) result = 5;\n'
         '    if (lcd_map_release(&full_lcd_maps,&dst_borrow)) result = 5;'),
        ('    if (!parameters || gpe != 0 || core != 0 || raster_fd < 0 || raster_failed) return 5;',
         '    if (!parameters || gpe != 0 || core != 0 || raster_fd < 0) return 5;\n'
         '    if (full_lcd_map_finish_batch()) return 5;\n'
         '    if (raster_failed) return 5;'),
        ('    __atomic_store_n(&headless_stop, 1, __ATOMIC_RELEASE);',
         '    if (full_lcd_map_fin_admit()) {\n'
         '        int error=*__errno_location();\n'
         '        record("OSD_HEADLESS_FAILED ","latency-v3 fin refused: flush a clean cache before native fin; no unproven worker unmap");\n'
         '        pthread_mutex_unlock(headless_lifecycle_mutex);\n'
         '        *__errno_location()=error;return (unsigned long)-1;\n'
         '    }\n'
         '    __atomic_store_n(&headless_stop, 1, __ATOMIC_RELEASE);'),
        ('static const char *mirrored[] = {', 'static const char *mirrored[] = { "FULL_LCD_CACHE_",'),
        ('                char line[512];\n'
         '                int n = snprintf(line, sizeof line, "OBS %s%s\\n", prefix, name ? name : "");\n'
         '                if (n > 0) {',
         '                char line[2048];\n'
         '                int n = snprintf(line, sizeof line, "OBS %s%s\\n", prefix, name ? name : "");\n'
         '                if (n > 0) {\n'
         '                    if ((unsigned long)n >= sizeof line) n = (int)sizeof line - 1;'),
    ])
    return source + '\n' + V3_OBSERVER_SUPPORT


def timing_v3_header():
    fields = ('hits', 'misses', 'maps', 'unmaps', 'errors', 'active', 'bytes', 'entries', 'flushes', 'failed', 'sealed')
    import json
    fmt = json.dumps(''.join(',"map_' + name + '":%lu' for name in fields))
    args = ','.join('s->' + name for name in fields)
    api = r'''
#include "lcd-map-cache.h"
__attribute__((visibility("hidden"))) void full_lcd_map_snapshot(struct lcd_map_stats *);
static int full_lcd_map_json(char *text,unsigned long cap,int n,const struct lcd_map_stats *s) {
    if (n<2 || (unsigned long)n>=cap) return -1;
    int saved=*__errno_location();unsigned long used=(unsigned long)n-2;
    int extra=snprintf(text+used,cap-used,CACHE_FORMAT,CACHE_ARGS);
    if (extra<0 || (unsigned long)extra+3>cap-used) n=-1;
    else { used+=extra;text[used++]='}';text[used++]='\n';text[used]=0;n=(int)used; }
    *__errno_location()=saved;return n;
}
'''.replace('CACHE_FORMAT', fmt).replace('CACHE_ARGS', args)
    source = replace_unique(TIMING_HEADER, [
        ('static void lcd_pipeline_event(', api + '\nstatic void lcd_pipeline_event('),
        ('    static unsigned long consume_ns, capture_ns, hash_ns, persist_ns, ack_ns, diag_previous_ns;',
         '    static unsigned long consume_ns, capture_ns, hash_ns, persist_ns, ack_ns, diag_previous_ns;\n'
         '    static struct lcd_map_stats consume_maps;'),
        ('        consume_ns = ns; capture_ns = hash_ns = persist_ns = ack_ns = 0;',
         '        consume_ns = ns; capture_ns = hash_ns = persist_ns = ack_ns = 0;\n'
         '        if (command == 0x1003) full_lcd_map_snapshot(&consume_maps);'),
        ('    char line[512];', '    char line[1536];'),
        ('    int ok = fd >= 0 && n > 0 && (unsigned long)n < sizeof line;',
         '    if (command == 0x1003) n=full_lcd_map_json(line,sizeof line,n,&consume_maps);\n'
         '    int ok = fd >= 0 && n > 0 && (unsigned long)n < sizeof line;'),
    ])
    return source.replace('latency-v1', 'latency-v3')
