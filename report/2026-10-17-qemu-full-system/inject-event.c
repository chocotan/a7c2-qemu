/* Guest-side event injector for the appFw input queue.
 *
 * appFw's `App::input_infra_callback` (ELF VA 0x17988b4) does:
 *     osal_valloc_msg_wait(0x5503e0, &msg, 0x20, 1);
 *     copy 32 bytes from the InfraInputEvent;
 *     osal_set_msg_src(msg, 0x5503e0);
 *     osal_snd_msg(0x5503e0, msg);
 * so posting the same 32-byte record to that queue reproduces the callback's
 * effect without needing to run code inside the appFw process.
 *
 * The payload is supplied as 64 hex characters so this tool never invents a
 * field value; the caller must supply an evidence-backed record.
 */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern unsigned long strtoul(const char *, char **, int);
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

#define PAYLOAD 32

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int run(int argc, char **argv) {
    /* usage: inject-event <queue> <src> <64 hex chars> */
    if (argc != 4) { printf("INJECT_EVENT_USAGE argc=%d\n", argc); return 2; }
    char *end;
    unsigned long queue = strtoul(argv[1], &end, 0);
    if (*end || !queue || queue > 0xffffffffUL) { printf("INJECT_EVENT_BAD_QUEUE\n"); return 2; }
    unsigned long src = strtoul(argv[2], &end, 0);
    if (*end || !src || src > 0xffffffffUL) { printf("INJECT_EVENT_BAD_SRC\n"); return 2; }
    const char *hex = argv[3];
    if (hex[0] == '0' && (hex[1] == 'x' || hex[1] == 'X')) hex += 2;
    for (int i = 0; i < PAYLOAD * 2; ++i)
        if (hex_nibble(hex[i]) < 0 || hex[i] == 0) { printf("INJECT_EVENT_BAD_HEX at=%d\n", i); return 2; }
    if (hex[PAYLOAD * 2] != 0) { printf("INJECT_EVENT_HEX_TOO_LONG\n"); return 2; }

    void *message = 0;
    int result = osal_valloc_msg_wait((unsigned int)queue, &message, PAYLOAD, 1);
    if (result || !message) { printf("INJECT_EVENT_ALLOC=%d\n", result); return 3; }
    unsigned char *bytes = message;
    for (int i = 0; i < PAYLOAD; ++i)
        bytes[i] = (unsigned char)((hex_nibble(hex[i * 2]) << 4) | hex_nibble(hex[i * 2 + 1]));
    osal_set_msg_src(message,(unsigned int)src);
    unsigned int actual_source=osal_get_msg_src(message);
    if(actual_source!=(unsigned int)src){
        int cleanup=osal_free_msg((unsigned int)queue,message);
        printf("INJECT_EVENT_SOURCE_ERROR actual=%#x expected=%#lx free_result=%d\n",actual_source,src,cleanup);
        return cleanup?6:4;
    }
    /* snd transfers ownership; never read message fields after it returns. */
    unsigned int code = *(unsigned int *)bytes;
    int status = *(int *)(bytes + 8), prev = *(int *)(bytes + 12);
    unsigned int from = *(unsigned int *)(bytes + 24);
    result = osal_snd_msg((unsigned int)queue, message);
    printf("INJECT_EVENT_SEND queue=%#lx src=%#lx code=%#x status=%d prev=%d from=%#x result=%d\n",
           queue, src,
           code, status, prev, from, result);
    if(result){
        int cleanup=osal_free_msg((unsigned int)queue,message);
        printf("INJECT_EVENT_REJECT_CLEANUP free_result=%d\n",cleanup);
        if(cleanup)return 6;
    }
    return result ? 4 : 0;
}
#ifndef INPUT_INJECT_TEST
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
#endif
