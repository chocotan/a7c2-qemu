"""The real neutral-source builder must not store after first publication."""
from pathlib import Path
import subprocess


def test_neutral_builder_accepts_readonly_pixels_after_first_frame(tmp_path):
    module = Path(__file__).resolve().parents[2]/'report/virtual-cp/yc-inject/yc_inject.c'
    source = module.read_text()
    # Compile the actual metadata builder and digest, not a test reimplementation.
    digest_start = source.index('static u64 input_digest(')
    digest = source[digest_start:source.index('\n}\n', digest_start)+3]
    start = source.index('static void build_metadata_and_frame(')
    builder = source[start:source.index('/* PIN_CONNECT', start)]
    harness = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdarg.h>
#include <stddef.h>
#include <sys/mman.h>
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long u64;
#define FRAME_W 1920u
#define FRAME_H 1080u
#define FRAME_BYTES (FRAME_W * FRAME_H * (uncompressed_input ? 5u : 2u) / 2u)
#define ACTIVE_PIXEL_TYPE 0x431u
static int uncompressed_input = 1, input_loaded, neutral_initialized;
static u8 metadata[3][0x600];
static u8 *meta_va[3] = {metadata[0], metadata[1], metadata[2]};
static u8 *pix_va;
static u32 pix_h = 0x415, pix_len = 0x500000;
static u64 pix_addr = 0x425558000UL;
static int logs;
static int printk(const char *format, ...) { (void)format; ++logs; return 0; }
static void put16(u8 *p, u16 v) { p[0] = v; p[1] = v >> 8; }
static void put32(u8 *p, u32 v) { for (int i=0;i<4;++i) p[i] = v >> (8*i); }
static void put64(u8 *p, u64 v) { for (int i=0;i<8;++i) p[i] = v >> (8*i); }
'''
    harness += digest + builder + r'''
int main(void) {
    size_t length = FRAME_BYTES;
    pix_va = mmap(0, length, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
    assert(pix_va != MAP_FAILED);
    build_metadata_and_frame(0);
    for (size_t i=0;i<length;++i) assert(pix_va[i] == 128);
    /* A store on either later submission must fault instead of silently passing. */
    assert(mprotect(pix_va, length, PROT_READ) == 0);
    build_metadata_and_frame(1);
    build_metadata_and_frame(2);
    assert(neutral_initialized && logs == 3);
    for (int i=0;i<3;++i) assert(metadata[i][0] == 'S' && metadata[i][3] == 'C');
    assert(munmap(pix_va, length) == 0);
    return 0;
}
'''
    test = tmp_path/'immutable.c'
    test.write_text(harness)
    binary = tmp_path/'immutable'
    subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', str(test), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=30)
