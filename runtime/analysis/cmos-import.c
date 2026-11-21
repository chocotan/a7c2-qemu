/* SPDX-License-Identifier: MIT */
/* Guest tool: decode the host-supplied 640x480 baseline JPEG into the raw RGB24
 * virtual CMOS source consumed by ramfb-viewer (hot swap), or remove it to
 * restore the default color chart. Software virtual CMOS only.
 *   cmos-import --begin         start a new upload (/tmp/virtual-cmos-upload.jpg)
 *   cmos-import --chunk <b64>   append base64-decoded bytes (serial lines are short)
 *   cmos-import --commit        decode upload -> /tmp/virtual-cmos-custom.rgb (atomic rename)
 *   cmos-import --reset         remove the custom source (default color chart) */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "device-models/virtual-cmos-capture.h"

extern int __libc_start_main(int (*)(int, char **, char **), int, char **,
                             void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");

#define UPLOAD_PATH "/tmp/virtual-cmos-upload.jpg"
static int b64v(int c) {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    return c == '+' ? 62 : c == '/' ? 63 : -1;
}
static int append_chunk(const char *text) {
    size_t n = strlen(text);
    if (!n || n > 1000 || (n & 3)) return 2;
    uint8_t out[768];
    size_t o = 0;
    for (size_t i = 0; i < n; i += 4) {
        int a = b64v(text[i]), b = b64v(text[i + 1]);
        int c = text[i + 2] == '=' ? -2 : b64v(text[i + 2]);
        int d = text[i + 3] == '=' ? -2 : b64v(text[i + 3]);
        if (a < 0 || b < 0 || c == -1 || d == -1 || (c == -2 && d != -2) || (d == -2 && i + 4 != n)) return 2;
        out[o++] = (uint8_t)(a << 2 | b >> 4);
        if (c >= 0) out[o++] = (uint8_t)((b & 15) << 4 | c >> 2);
        if (d >= 0) out[o++] = (uint8_t)((c & 3) << 6 | d);
    }
    int fd = open(UPLOAD_PATH, O_WRONLY | O_APPEND);
    if (fd < 0) return 1;
    size_t done = 0;
    while (done < o) {
        long w = write(fd, out + done, o - done);
        if (w <= 0) { close(fd); return 1; }
        done += (size_t)w;
    }
    return close(fd) ? 1 : 0;
}
static int run(int argc, char **argv, char **envp) {
    (void)envp;
    if (argc == 3 && !strcmp(argv[1], "--chunk")) return append_chunk(argv[2]);
    if (argc != 2) { dprintf(2, "CMOS_IMPORT_USAGE\n"); return 2; }
    if (!strcmp(argv[1], "--begin")) {
        int fd = open(UPLOAD_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0600);
        return fd < 0 || close(fd) ? 1 : 0;
    }
    if (strcmp(argv[1], "--commit") && strcmp(argv[1], "--reset")) { dprintf(2, "CMOS_IMPORT_USAGE\n"); return 2; }
    if (!strcmp(argv[1], "--reset")) {
        unlink(VIRTUAL_CMOS_CUSTOM_RGB_PATH);
        dprintf(1, "CMOS_IMPORT_RESET default-color-chart\n");
        return 0;
    }
    int fd = open(UPLOAD_PATH, O_RDONLY);
    if (fd < 0) { dprintf(2, "CMOS_IMPORT_OPEN_FAILED\n"); return 1; }
    size_t cap = 4u << 20, len = 0;
    uint8_t *jpeg = malloc(cap);
    if (!jpeg) return 1;
    for (;;) {
        if (len == cap) { dprintf(2, "CMOS_IMPORT_TOO_LARGE\n"); return 1; }
        long n = read(fd, jpeg + len, cap - len);
        if (n < 0) return 1;
        if (!n) break;
        len += (size_t)n;
    }
    close(fd);
    unlink(UPLOAD_PATH);
    static uint8_t rgb[VIRTUAL_CMOS_RGB_BYTES];
    unsigned w = 0, h = 0;
    if (virtual_cmos_decode_jpeg(jpeg, len, rgb, &w, &h, 0, 0) != 0 || w != VIRTUAL_CMOS_W || h != VIRTUAL_CMOS_H) {
        dprintf(2, "CMOS_IMPORT_DECODE_FAILED w=%u h=%u\n", w, h);
        return 1;
    }
    const char *tmp = VIRTUAL_CMOS_CUSTOM_RGB_PATH ".tmp";
    int out = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (out < 0) return 1;
    size_t done = 0;
    while (done < sizeof rgb) {
        long n = write(out, rgb + done, sizeof rgb - done);
        if (n <= 0) { close(out); unlink(tmp); return 1; }
        done += (size_t)n;
    }
    if (fsync(out) || close(out) || rename(tmp, VIRTUAL_CMOS_CUSTOM_RGB_PATH)) { unlink(tmp); return 1; }
    dprintf(1, "CMOS_IMPORT_OK jpeg_bytes=%lu\n", (unsigned long)len);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
