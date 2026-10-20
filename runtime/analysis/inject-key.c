/* Guest-only key event injector: deliver one 20-byte InfraInput key message through
 * the original osal message APIs. All fields come from argv so no value is invented
 * by this tool; the caller must supply evidence-backed key_code/status/from_type.
 * The message layout {key_code, sub_key_code, status, ex_info, from_type} matches
 * InfraInput::RecvThread parsing at libObj.so VA 0xd031c..0xd0354. */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern unsigned long strtoul(const char *, char **, int);
extern int osal_valloc_msg_wait(unsigned int, void **, unsigned int, int);
extern void osal_set_msg_src(void *, unsigned int);
extern int osal_snd_msg(unsigned int, void *);
extern int osal_free_msg(unsigned int,void *);
extern int strcmp(const char *,const char *);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
#ifndef INJECT_KEY_HOST_TEST
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
#endif
static unsigned int field(const char *text, int *ok) {
    char *end;
    unsigned long value = strtoul(text, &end, 0);
    if (*end || value > 0xffffffffUL) { *ok = 0; return 0; }
    return (unsigned int)value;
}
static int run(int argc, char **argv) {
    if(argc==2 && !strcmp(argv[1],"--cancel-apo1")) {
        /* Original upm.ko 0x9a40/0x8c70 consumes this request; it alone generates POWER_OFF_CANCEL. */
        const unsigned int queue=0x80920021,source=0x92840747;
        void *message=0;
        int result=osal_valloc_msg_wait(queue,&message,16,1);
        if(result || !message){printf("POWER_CANCEL_ALLOC=%d\n",result);return 3;}
        unsigned int *words=message;
        words[0]=0x00920142;words[1]=8;words[2]=0;words[3]=0;
        osal_set_msg_src(message,source);
        result=osal_snd_msg(queue,message);
        if(result)osal_free_msg(queue,message);
        printf("POWER_CANCEL_REQUEST queue=%#x src=%#x cmd=0x920142 factor=8 bytes=16 result=%d\n",queue,source,result);
        return result?4:0;
    }
    int app=argc==9 && !strcmp(argv[1],"--app");
    if(app){argc--;argv++;}
    /* usage: inject-key <queue> <src> <key_code> <sub_key_code> <status> <ex_info> <from_type> */
    if (argc != 8) { printf("INJECT_KEY_USAGE argc=%d\n", argc); return 2; }
    int ok = 1;
    unsigned int queue = field(argv[1], &ok), src = field(argv[2], &ok);
    unsigned int body[5];
    for (int i = 0; i < 5; ++i) body[i] = field(argv[3 + i], &ok);
    if (!ok || !queue || (app?(queue!=0x005503e0 || src!=queue):src==queue)) { printf("INJECT_KEY_BAD_ARGS\n"); return 2; }
    void *message = 0;
    unsigned int bytes=app?32:20;
    int result = osal_valloc_msg_wait(queue, &message, bytes, 1);
    if (result || !message) { printf("INJECT_KEY_ALLOC=%d\n", result); return 3; }
    unsigned int *words = message;
    if(app){
        for(int i=0;i<8;i++)words[i]=0;
        words[0]=body[0];words[1]=body[1];words[2]=body[2];
        words[4]=body[3];words[6]=body[4];
    }else for (int i = 0; i < 5; ++i) words[i] = body[i];
    osal_set_msg_src(message, src);
    result = osal_snd_msg(queue, message);
    if(result)osal_free_msg(queue,message);
    /* osal_stat_msgq hits a deliberate null-store trap on this queue family in our
       guest (kernel UIPC service layout), so depth polling was removed again. */
    printf("INJECT_KEY_SEND queue=%#x src=%#x key_code=%#x sub=%#x status=%#x ex=%#x from=%#x result=%d bytes=%u\n",
           queue, src, body[0], body[1], body[2], body[3], body[4], result,bytes);
    return result ? 4 : 0;
}
#ifndef INJECT_KEY_HOST_TEST
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
#endif
