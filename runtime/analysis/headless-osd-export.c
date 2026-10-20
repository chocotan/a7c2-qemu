/* One open inode: concurrent atomic snapshot replacement cannot mix frames. */
#include "headless-osd.h"
#ifdef GUI_MODEL_EXPORT
#include "gui-model-store.h"
#define EXPORT_PATH GUI_MODEL_STORE_PATH
#define EXPORT_SIZE GUI_MODEL_STORE_BYTES
#define EXPORT_BEGIN "\nGUI_MODEL_BEGIN\n"
#define EXPORT_END "GUI_MODEL_END\n"
#else
#define EXPORT_PATH HOSD_PATH
#define EXPORT_SIZE HOSD_BYTES
#define EXPORT_BEGIN "\nHEADLESS_OSD_BEGIN\n"
#define EXPORT_END "HEADLESS_OSD_END\n"
#endif
extern int open(const char *, int, ...), close(int);
extern long read(int, void *, unsigned long), write(int, const void *, unsigned long);
extern void _exit(int);
extern int *__errno_location(void);
static int output(const void *data, unsigned long n) {
    const unsigned char *p = data;
    while (n) {
        long written = write(1, p, n);
        if (written < 0 && *__errno_location() == 4) continue;
        if (written <= 0 || (unsigned long)written > n) return -1;
        p += written; n -= written;
    }
    return 0;
}
int hosd_export(const char *path) {
    int fd = open(path, 0);
    if (fd < 0) return 1;
    static const char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    unsigned char raw[768]; char encoded[1025];
    unsigned long total = 0;
    unsigned long expected = EXPORT_SIZE;
    if (output(EXPORT_BEGIN, sizeof(EXPORT_BEGIN)-1)) { close(fd); return 1; }
    for (;;) {
        long n = read(fd, raw, sizeof raw);
        if (n < 0 && *__errno_location() == 4) continue;
        if (!n) break;
        if (n < 0 || total + n > EXPORT_SIZE) { close(fd); return 1; }
#ifdef GUI_MODEL_EXPORT
        if (!total) {
            if(n<64){close(fd);return 1;}
            expected=(unsigned long)raw[60]|(unsigned long)raw[61]<<8|
                     (unsigned long)raw[62]<<16|(unsigned long)raw[63]<<24;
            if(expected<GUI_MODEL_STORE_BASE_BYTES+8 || expected>EXPORT_SIZE){close(fd);return 1;}
        }
#endif
        total += n;
        unsigned int k = 0;
        for (long i = 0; i < n; i += 3) {
            unsigned int v = (unsigned int)raw[i] << 16;
            if (i + 1 < n) v |= (unsigned int)raw[i + 1] << 8;
            if (i + 2 < n) v |= raw[i + 2];
            encoded[k++] = alphabet[v >> 18]; encoded[k++] = alphabet[(v >> 12) & 63];
            encoded[k++] = i + 1 < n ? alphabet[(v >> 6) & 63] : '=';
            encoded[k++] = i + 2 < n ? alphabet[v & 63] : '=';
        }
        encoded[k++] = '\n';
        if (output(encoded, k)) { close(fd); return 1; }
    }
    if (close(fd) || total != expected) return 1;
    return output(EXPORT_END, sizeof(EXPORT_END)-1) ? 1 : 0;
}
#ifndef HOSD_EXPORT_TEST
void _start(void) { _exit(hosd_export(EXPORT_PATH)); }
#endif
