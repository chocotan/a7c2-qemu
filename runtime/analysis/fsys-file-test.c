/* Standalone original-Fsys test. This is not a camera capture/encoder implementation. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
#include <sys/mman.h>
#include <dlfcn.h>

#define IMAGE_BYTES 0x400000U
#define EXPORT_PHYS UINT64_C(0x41e600000)
extern void mcmn_init(void);
extern uint32_t mcmn_param_getul(int32_t);
extern int32_t mcmn_param_getl(int32_t);
extern int32_t Fsys_Init(void);
extern int32_t Fsys_Mount(const char *, uint32_t, char *, const void *);
extern int32_t Fsys_Mkdir(const char *);
extern int32_t Fsys_Open(const char *, uint64_t *, uint32_t);
extern int32_t Fsys_Write(uint64_t, const void *, int32_t);
extern int32_t Fsys_Read(uint64_t, void *, int32_t);
extern int32_t Fsys_Flush(uint64_t);
extern int32_t Fsys_Close(uint64_t);
extern int32_t Fsys_Unmount(unsigned char, uint32_t);
extern int32_t Fsys_GetFreeSpace(unsigned char,void *);
extern int32_t Fsys_FlushVolume(unsigned char);
extern int osal_stat_msgq(unsigned int,unsigned int *);
extern int osal_reg_msg_queue_cb(unsigned int,void **,void (*)(void *,unsigned long),unsigned long);
extern int osal_unreg_msg_queue_cb(unsigned int,void *);
extern int osal_valloc_msg_wait(unsigned int,void **,unsigned int,unsigned int);
extern unsigned int osal_msg_size(void *);
extern void osal_set_msg_src(void *,unsigned int);
extern unsigned int osal_get_msg_src(void *);
extern int osal_snd_msg(unsigned int,void *),osal_free_msg(unsigned int,void *);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");

static void require_zero(const char *operation, int32_t result) {
    printf("FSYS_CALL %s result=%#x\n", operation, (uint32_t)result); fflush(0);
    if (result) _exit(10);
}
static int export_image(void) {
    char cmdline[8192];
    int fd = open("/proc/cmdline", O_RDONLY);
    if (fd < 0) return 1;
    ssize_t n = read(fd, cmdline, sizeof cmdline - 1); close(fd);
    if (n <= 0) return 1;
    cmdline[n] = 0;
    if (!strstr(cmdline, " memrsv=0x00400000@0x41e600000:uc ")) return 1;
    fd = open("/image_mmca", O_RDONLY);
    if (fd < 0 || lseek(fd, 0, SEEK_END) != IMAGE_BYTES || lseek(fd, 0, SEEK_SET)) {
        if (fd >= 0) close(fd);
        return 1;
    }
    int memory = open("/dev/mem", O_RDWR);
    if (memory < 0) { close(fd); return 1; }
    unsigned char *mapped = mmap(0, IMAGE_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED, memory, EXPORT_PHYS);
    close(memory);
    if (mapped == MAP_FAILED) { close(fd); return 1; }
    unsigned total = 0;
    while (total < IMAGE_BYTES) {
        n = read(fd, mapped + total, IMAGE_BYTES - total);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        total += n;
    }
    close(fd);
    uint64_t hash = UINT64_C(14695981039346656037);
    for (unsigned i = 0; i < total; i++) hash = (hash ^ mapped[i]) * UINT64_C(1099511628211);
    __sync_synchronize();
    munmap(mapped, IMAGE_BYTES);
    if (total != IMAGE_BYTES) return 1;
    printf("FSYS_IMAGE_EXPORTED physical=0x%llx bytes=%u fnv1a64=%016llx\n",
           (unsigned long long)EXPORT_PHYS, total, (unsigned long long)hash);
    fflush(0);
    return 0;
}
#define RM_QUEUE 0x80d9016eU
static const unsigned char queue_pattern[32]={
    'R','M','Q','T',1,2,3,4,5,6,7,8,9,10,11,12,
    13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28};
struct queue_result {unsigned int done,count;int content,release;};
static void queue_receiver(void *message,unsigned long arg) {
    struct queue_result *out=(void *)arg;
    if(message) {
        int valid=osal_msg_size(message)==sizeof queue_pattern &&
            !memcmp(message,queue_pattern,sizeof queue_pattern);
        int result=osal_free_msg(RM_QUEUE,message);
        __atomic_store_n(&out->content,valid,__ATOMIC_RELAXED);
        __atomic_store_n(&out->release,result,__ATOMIC_RELAXED);
    }
    __atomic_fetch_add(&out->count,1,__ATOMIC_RELAXED);
    __atomic_store_n(&out->done,1,__ATOMIC_RELEASE);
}
static int queue_idle(void) {
    unsigned int state[4]={0};int result=osal_stat_msgq(RM_QUEUE,state);
    printf("RM_QUEUE_IDLE result=%d words=%u,%u,%u,%u\n",result,state[0],state[1],state[2],state[3]);fflush(0);
    if(result || state[0] || state[1])return 20;
    puts("RM_QUEUE_IDLE_PASS");fflush(0);return 0;
}
/* No registration/send: test Front ownership without replacing a consumer. */
static int front_owner_test(void) {
    const unsigned int owner=0x8028017cU;
    void *message=0;
    int allocated=osal_valloc_msg_wait(owner,&message,7,1);
    printf("FRONT_OWNER_ALLOC owner=%#x bytes=7 rc=%d pointer=%p\n",owner,allocated,message);
    if(!message){fflush(0);return 24;}
    unsigned int size=0,source=0;int content=0;
    if(!allocated) {
        size=osal_msg_size(message);
        if(size==7) {
            const unsigned char pattern[7]={'O','W','N','E','R',1,2};
            memcpy(message,pattern,7);
            osal_set_msg_src(message,owner);
            source=osal_get_msg_src(message);
            content=!memcmp(message,pattern,7);
        }
    }
    int released=osal_free_msg(owner,message);
    printf("FRONT_OWNER_RESULT allocation_rc=%d size=%u source=%#x content=%d free_rc=%d scope=allocation_only_not_media_notification\n",
           allocated,size,source,content,released);fflush(0);
    if(released)return 26;
    return allocated || size!=7 || source!=owner || !content?25:0;
}
static int queue_transport_test(void) {
    if(queue_idle())return 20;
    void *receiver=0;static struct queue_result received={0,0,0,-1};
    int result=osal_reg_msg_queue_cb(RM_QUEUE,&receiver,queue_receiver,(unsigned long)&received);
    printf("RM_QUEUE_REGISTER result=%d handle=%p\n",result,receiver);fflush(0);
    if(result)return 21;
    unsigned int state[4]={0};int ready=0;
    for(int i=0;i<1500;i++) {
        result=osal_stat_msgq(RM_QUEUE,state);
        if(result)break;
        if(state[1]){ready=1;break;}
        usleep(1000);
    }
    printf("RM_QUEUE_REAL_RECEIVER ready=%d result=%d words=%u,%u,%u,%u\n",ready,result,state[0],state[1],state[2],state[3]);fflush(0);
    if(!ready){osal_unreg_msg_queue_cb(RM_QUEUE,receiver);return 22;}
    void *message=0;result=osal_valloc_msg_wait(RM_QUEUE,&message,sizeof queue_pattern,1);
    printf("RM_QUEUE_ALLOC result=%d message=%p\n",result,message);fflush(0);
    int sent=-1;
    if(!result && message) {
        memcpy(message,queue_pattern,sizeof queue_pattern);sent=osal_snd_msg(RM_QUEUE,message);
        if(sent)osal_free_msg(RM_QUEUE,message);
    }
    for(int i=0;i<3000 && !__atomic_load_n(&received.done,__ATOMIC_ACQUIRE);i++)usleep(1000);
    int unregistered=osal_unreg_msg_queue_cb(RM_QUEUE,receiver);
    unsigned int done=__atomic_load_n(&received.done,__ATOMIC_ACQUIRE),count=__atomic_load_n(&received.count,__ATOMIC_ACQUIRE);
    int content=__atomic_load_n(&received.content,__ATOMIC_ACQUIRE),released=__atomic_load_n(&received.release,__ATOMIC_ACQUIRE);
    printf("RM_QUEUE_RESULTS send=%d unregister=%d callbacks=%u content=%d free=%d\n",sent,unregistered,
           count,content,released);fflush(0);
    if(result || sent || unregistered || !done || count!=1 || !content || released)return 23;
    puts("RM_QUEUE_TRANSPORT_PASS bytes=32 scope=transport_only_not_media_ready");fflush(0);return 0;
}
static int run(int argc, char **argv) {
    if(argc==2 && !strcmp(argv[1],"front-owner"))return front_owner_test();
    if(argc==2 && !strcmp(argv[1],"queue"))return queue_transport_test();
    if(argc==2 && !strcmp(argv[1],"queue-idle"))return queue_idle();
    int verify_only = argc == 2 && !strcmp(argv[1], "verify");
    int host_nested = argc == 2 && !strcmp(argv[1], "host-nested");
    int host_block = host_nested || (argc == 2 && !strcmp(argv[1], "host-256"));
    if (argc > 2 || (argc == 2 && !verify_only && !host_block)) return 2;
    unsigned (*configured)(void) = dlsym(RTLD_DEFAULT, "file_media_configured");
    if (!configured) return 3;
    uint32_t mount_flags=verify_only?0x100:0;
    printf("FSYS_FILE_TEST_BEGIN verify_only=%d mount_flags=%#x\n", verify_only,mount_flags); fflush(0);
    mcmn_init();
    if (configured() != 1 || mcmn_param_getul(0x69) || mcmn_param_getul(0xf9)) return 4;
    for (int id = 0xa5; id <= 0xad; id++) if (mcmn_param_getl(id)) return 5;
    for (int id = 0xba; id <= 0xc2; id++) if (mcmn_param_getul(id)) return 6;
    require_zero("Init", Fsys_Init());
    char drive = 0, directory[32], path[64];
    require_zero("Mount", Fsys_Mount("/dev/mmca", mount_flags, &drive, 0));
    if (drive < 'A' || drive > 'Z') return 7;
    if(host_block) {
        uint32_t space[8]={0};
        require_zero("GetFreeSpace",Fsys_GetFreeSpace((unsigned char)drive,space));
        uint64_t free_bytes=(uint64_t)space[1]*space[6]*space[7];
        printf("FSYS_HOST_SPACE total_clusters=%u free_clusters=%u sector=%u cluster_sectors=%u free_bytes=%llu\n",
               space[0],space[1],space[6],space[7],(unsigned long long)free_bytes);fflush(0);
        if(free_bytes<UINT64_C(250000000000) || free_bytes>UINT64_C(256000000000) || space[6]!=512)return 12;
    }
    snprintf(directory, sizeof directory, "%c:/QTEST", drive);
    snprintf(path, sizeof path, "%c:/QTEST/PROBE.BIN", drive);
    unsigned char expected[4096], got[4096];
    for (unsigned i = 0; i < sizeof expected; i++) expected[i] = (i * 37U + 9U) & 255U;
    uint64_t handle = 0;
    if (!verify_only) {
        require_zero("Mkdir", Fsys_Mkdir(directory));
        require_zero("OpenWrite", Fsys_Open(path, &handle, 0xf));
        int32_t bytes = Fsys_Write(handle, expected, sizeof expected);
        printf("FSYS_WRITE actual=%d expected=%u\n", bytes, (unsigned)sizeof expected); fflush(0);
        if (bytes != sizeof expected) return 8;
        require_zero("Flush", Fsys_Flush(handle));
        require_zero("CloseWrite", Fsys_Close(handle));
    }
    require_zero("OpenRead", Fsys_Open(path, &handle, 1));
    int32_t bytes = Fsys_Read(handle, got, sizeof got);
    if (bytes != sizeof got || memcmp(expected, got, sizeof got)) return 9;
    require_zero("CloseRead", Fsys_Close(handle));
    if (host_nested) {
        unsigned char *chunk = malloc(131072), *readback = malloc(131072);
        if (!chunk || !readback) return 13;
        snprintf(directory, sizeof directory, "%c:/QTEST/NESTED", drive);
        require_zero("MkdirNested", Fsys_Mkdir(directory));
        snprintf(directory, sizeof directory, "%c:/QTEST/NESTED/DEEP", drive);
        require_zero("MkdirDeep", Fsys_Mkdir(directory));
        snprintf(path, sizeof path, "%c:/QTEST/NESTED/DEEP/BIG.BIN", drive);
        require_zero("OpenNestedWrite", Fsys_Open(path, &handle, 0xf));
        for (unsigned part = 0; part < 8; part++) {
            for (unsigned i = 0; i < 131072; i++)
                chunk[i] = ((part * 131072U + i) * 37U + 9U) & 255U;
            int32_t written = Fsys_Write(handle, chunk, 131072);
            printf("FSYS_NESTED_WRITE part=%u actual=%d expected=131072\n", part, written); fflush(0);
            if (written != 131072) return 14;
        }
        require_zero("FlushNested", Fsys_Flush(handle));
        require_zero("CloseNestedWrite", Fsys_Close(handle));
        require_zero("OpenNestedRead", Fsys_Open(path, &handle, 1));
        for (unsigned part = 0; part < 8; part++) {
            for (unsigned i = 0; i < 131072; i++)
                chunk[i] = ((part * 131072U + i) * 37U + 9U) & 255U;
            int32_t got_bytes = Fsys_Read(handle, readback, 131072);
            if (got_bytes != 131072 || memcmp(chunk, readback, 131072)) return 15;
        }
        require_zero("CloseNestedRead", Fsys_Close(handle));
        free(chunk); free(readback);
        puts("FSYS_HOST_NESTED_TEST_PASS bytes=1048576 scope=original_Fsys_nested_diagnostic_not_media"); fflush(0);
    }
    if(host_block)require_zero("FlushVolume",Fsys_FlushVolume((unsigned char)drive));
    require_zero("Unmount", Fsys_Unmount((unsigned char)drive, 0));
    printf("FSYS_FILE_CONTENT_PASS bytes=%u verify_only=%d\n", (unsigned)sizeof got, verify_only); fflush(0);
    if (verify_only && export_image()) return 11;
    printf("FSYS_FILE_TEST_DONE result=0 verify_only=%d mount_flags=%#x\n", verify_only,mount_flags); fflush(0);
    if(host_block){puts("FSYS_HOST_BLOCK_TEST_PASS scope=original_Fsys_diagnostic_not_camera_format_or_photo");fflush(0);}
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
