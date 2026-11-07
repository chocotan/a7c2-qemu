/* SPDX-License-Identifier: MIT */
/* Publish the 7-byte front-end media state packet that the CP firmware itself
 * builds and sends.
 *
 * Producer (verified): CP `cpapp-b.bin` file offset 0xb0f4a0 (Thumb) constructs
 *   [02 00 00, in3, in4, in5, in6] and sends it to OSAL SID 0x8028017c.
 * Layout:
 *   byte0 = 2                       event type (consumer requires byte0==2 && len>=7)
 *   byte1 = byte2 = 0               explicitly stored zero by the producer
 *   byte3 = enable mask             bit0=RM1, bit1=RM2, bit2=RM3 ("that channel's
 *                                   conversion ran"), NOT slot presence
 *   byte4/5/6 = RM1/RM2/RM3 state   bit0=hold, bit1=port_state, bits4..7=RemoveCnt
 *
 * This program models the CP publisher only. Everything downstream is the
 * original firmware: mcmn_drv caches the 7 bytes and replays them byte-for-byte
 * on cmd3 subscribe, MediaDetect parses them, appFw converts to its input event,
 * and the mount sequence / mmc driver / Fsys do the actual work.
 *
 * Usage: cp-rm-notify <byte0> <byte1> <byte2> <byte3> <byte4> <byte5> <byte6>
 *        (each argument one byte, decimal or 0x-prefixed hex)
 */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern int osal_valloc_msg_wait(unsigned int, void **, unsigned int, int);
extern int osal_snd_msg(unsigned int, void *);
extern int osal_free_msg(unsigned int, void *);
extern unsigned int osal_msg_size(void *);
extern unsigned long strtoul(const char *, char **, int);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
#ifndef CP_RM_NOTIFY_TEST
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
#endif

#define MEDIA_STATE_SID 0x8028017cu

static int parse_byte(const char *text, unsigned int *out) {
    char *end;
    unsigned long value = strtoul(text, &end, 0);
    if (end == text || *end || value > 0xffu) return 0;
    *out = (unsigned int)value;
    return 1;
}

static int run(int argc, char **argv) {
    unsigned char packet[7];
    if (argc != 8) {
        printf("CP_RM_NOTIFY_USAGE argc=%d need_7_bytes\n", argc);
        return 2;
    }
    for (int i = 0; i < 7; ++i) {
        unsigned int byte;
        if (!parse_byte(argv[i + 1], &byte)) {
            printf("CP_RM_NOTIFY_BAD_ARG index=%d text=%s\n", i, argv[i + 1]);
            return 2;
        }
        packet[i] = (unsigned char)byte;
    }
    /* The consumer requires byte0==2 and length>=7; refuse anything else rather
     * than sending a packet the original worker would drop. */
    if (packet[0] != 2 || packet[1] || packet[2] || (packet[3] & ~7u)) {
        printf("CP_RM_NOTIFY_REJECT byte0=%u (consumer requires 2)\n", packet[0]);
        return 2;
    }
    void *message = 0;
    int rc = osal_valloc_msg_wait(MEDIA_STATE_SID, &message, 7, 1);
    printf("CP_RM_NOTIFY_ALLOC rc=%d pointer=%p\n", rc, message);
    if (rc || !message) {
        if (message) printf("CP_RM_NOTIFY_PARTIAL_FREE rc=%d\n", osal_free_msg(MEDIA_STATE_SID, message));
        return 3;
    }
    unsigned char *payload = message;
    for (unsigned int i = 0; i < 7; ++i) payload[i] = packet[i];
    printf("CP_RM_NOTIFY_SEND destination=%#x bytes=7 payload=%02x%02x%02x%02x%02x%02x%02x\n",
           MEDIA_STATE_SID, packet[0], packet[1], packet[2], packet[3], packet[4], packet[5], packet[6]);
    unsigned int reported_size = osal_msg_size(message);
    if (reported_size != 7) {
        printf("CP_RM_NOTIFY_BAD_ALLOCATION bytes=%u free_rc=%d\n", reported_size,
               osal_free_msg(MEDIA_STATE_SID, message));
        return 3;
    }
    rc = osal_snd_msg(MEDIA_STATE_SID, message);
    /* A successful send transfers ownership; the receiver may already have freed it. */
    printf("CP_RM_NOTIFY_SENT rc=%d reported_size=%u\n", rc, reported_size);
    if (rc) {
        printf("CP_RM_NOTIFY_FREE_AFTER_FAILURE rc=%d\n", osal_free_msg(MEDIA_STATE_SID, message));
        return 4;
    }
    return 0;
}

#ifndef CP_RM_NOTIFY_TEST
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
#endif
