/* Real Linux loop attachment for the Sony kernel; its BusyBox lacks losetup. */
typedef unsigned long size_t;
typedef unsigned long long u64;
typedef unsigned int u32;
extern int open(const char *, int, ...), close(int), ioctl(int, unsigned long, ...);
extern long lseek(int, long, int), pread(int, void *, size_t, long);
extern int printf(const char *, ...), snprintf(char *, size_t, const char *, ...);
extern unsigned long strtoul(const char *, char **, int);
extern int strcmp(const char *, const char *), strncmp(const char *, const char *, size_t);
extern int memcmp(const void *, const void *, size_t), *__errno_location(void);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
struct loop_info64 {
    u64 device, inode, rdevice, offset, sizelimit;
    u32 number, encrypt_type, encrypt_key_size, flags;
    unsigned char file_name[64], crypt_name[64], encrypt_key[32];
    u64 init[2];
};
_Static_assert(sizeof(struct loop_info64) == 232, "Linux loop_info64 ABI");
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc, char **argv) {
    if (argc != 4 || strncmp(argv[2], "/partitions/", 12) ||
        (strcmp(argv[3], "ro") && strcmp(argv[3], "rw"))) return 2;
    char *end, path[32];
    unsigned long index = strtoul(argv[1], &end, 10);
    if (*end || index > 31) return 2;
    int control = open("/dev/loop-control", 2);
    if (control >= 0) {
        int result = ioctl(control, 0x4c80UL, index); /* LOOP_CTL_ADD */
        if (result < 0 && *__errno_location() != 17) {
            printf("LOOP_CONTROL_FAILED index=%lu errno=%d\n", index, *__errno_location());
            close(control); return 3;
        }
        close(control);
    }
    int image = open(argv[2], 0x8000 | (!strcmp(argv[3], "rw") ? 2 : 0));
    if (image < 0) return 4;
    long size = lseek(image, 0, 2);
    if (size < 512 || size > 0x80000000L) { close(image); return 4; }
    snprintf(path, sizeof path, "/dev/loop%lu", index);
    int loop = open(path, 2);
    if (loop < 0 || ioctl(loop, 0x4c00UL, image)) { /* LOOP_SET_FD */
        printf("LOOP_ATTACH_FAILED index=%lu errno=%d\n", index, *__errno_location());
        if (loop >= 0) close(loop);
        close(image); return 5;
    }
    struct loop_info64 info = {0}, verify = {0};
    info.flags = !strcmp(argv[3], "ro") ? 1 : 0;
    snprintf((char *)info.file_name, sizeof info.file_name, "%s", argv[2]);
    int result = ioctl(loop, 0x4c04UL, &info); /* LOOP_SET_STATUS64 */
    if (!result) result = ioctl(loop, 0x4c05UL, &verify);
    unsigned char source[512], block[512];
    if (result || verify.number != index || verify.flags != info.flags ||
        pread(image, source, sizeof source, 0) != sizeof source ||
        pread(loop, block, sizeof block, 0) != sizeof block || memcmp(source, block, sizeof source)) {
        printf("LOOP_VERIFY_FAILED index=%lu errno=%d\n", index, *__errno_location());
        ioctl(loop, 0x4c01UL, 0); /* Detach only this newly attached loop. */
        close(loop); close(image); return 6;
    }
    printf("FULLSYSTEM_LOOP_ATTACHED index=%lu bytes=%ld readonly=%u\n", index, size, verify.flags & 1);
    close(loop); close(image);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack+1), 0, 0, 0, stack);
    __builtin_trap();
}
