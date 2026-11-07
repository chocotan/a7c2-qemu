/* Guest-only key event injector: deliver one 20-byte InfraInput key message through
 * the original osal message APIs. All fields come from argv so no value is invented
 * by this tool; the caller must supply evidence-backed key_code/status/from_type.
 * The message layout {key_code, sub_key_code, status, ex_info, from_type} matches
 * InfraInput::RecvThread parsing at libObj.so VA 0xd031c..0xd0354. */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern unsigned long strtoul(const char *, char **, int);
extern int strcmp(const char *,const char *);
struct input_timespec { long seconds,nanoseconds; };
extern int nanosleep(const struct input_timespec *,struct input_timespec *);
extern int *__errno_location(void);
extern int osal_valloc_msg_wait(unsigned int, void **, unsigned int, int);
extern void osal_set_msg_src(void *, unsigned int);
extern unsigned int osal_get_msg_src(void *);
extern int osal_snd_msg(unsigned int, void *);
extern int osal_free_msg(unsigned int, void *);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
#ifndef INPUT_INJECT_TEST
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
#endif
static unsigned int field(const char *text, int *ok) {
    char *end;
    unsigned long value = strtoul(text, &end, 0);
    if (end==text || *end || value > 0xffffffffUL) { *ok = 0; return 0; }
    return (unsigned int)value;
}
static int send_key(unsigned int queue,unsigned int src,const unsigned int body[5]) {
    void *message = 0;
    int result = osal_valloc_msg_wait(queue, &message, 20, 1);
    if (result || !message) { printf("INJECT_KEY_ALLOC=%d\n", result); return 3; }
    unsigned int *words = message;
    for (int i = 0; i < 5; ++i) words[i] = body[i];
    osal_set_msg_src(message,src);
    unsigned int actual_source=osal_get_msg_src(message);
    if(actual_source!=src){
        int cleanup=osal_free_msg(queue,message);
        printf("INJECT_KEY_SOURCE_ERROR actual=%#x expected=%#x free_result=%d\n",actual_source,src,cleanup);
        return cleanup?6:4;
    }
    result = osal_snd_msg(queue, message);
    /* osal_stat_msgq hits a deliberate null-store trap on this queue family in our
       guest (kernel UIPC service layout), so depth polling was removed again. */
    printf("INJECT_KEY_SEND queue=%#x src=%#x key_code=%#x sub=%#x status=%#x ex=%#x from=%#x result=%d\n",
           queue, src, body[0], body[1], body[2], body[3], body[4], result);
    if(result){
        int cleanup=osal_free_msg(queue,message);
        printf("INJECT_KEY_REJECT_CLEANUP free_result=%d\n",cleanup);
        if(cleanup)return 6;
    }
    return result ? 4 : 0;
}
static int run(int argc, char **argv) {
    /* Optional pulse keeps key-up inside the guest, independent of serial RTT. */
    if (argc != 8 && argc != 10) { printf("INJECT_KEY_USAGE argc=%d\n", argc); return 2; }
    int ok = 1;
    unsigned int queue = field(argv[1], &ok), src = field(argv[2], &ok);
    unsigned int body[5],milliseconds=0;
    for (int i = 0; i < 5; ++i) body[i] = field(argv[3 + i], &ok);
    if (argc==10) {
        milliseconds=field(argv[9],&ok);
        if (strcmp(argv[8],"--pulse-ms") || milliseconds<1 || milliseconds>200 || body[2]!=1) ok=0;
    }
    if (!ok || !queue || src == queue) { printf("INJECT_KEY_BAD_ARGS\n"); return 2; }
    int rc=send_key(queue,src,body);
    if (rc || !milliseconds) return rc;
    struct input_timespec delay={0,(long)milliseconds*1000000L},remaining;
    int sleep_error=0;
    while (nanosleep(&delay,&remaining)) {
        if (*__errno_location()!=4) { sleep_error=1;break; }
        delay=remaining;
    }
    body[2]=0;
    rc=send_key(queue,src,body);
    if (rc) printf("INJECT_KEY_RELEASE_FAILED result=%d\n",rc);
    return rc?rc:sleep_error?5:0;
}
#ifndef INPUT_INJECT_TEST
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
#endif
