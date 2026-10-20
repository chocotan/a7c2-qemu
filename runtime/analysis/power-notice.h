#ifndef A7C2_POWER_NOTICE_H
#define A7C2_POWER_NOTICE_H
/* Original callback's native little-endian body; no state changes or replies. */
static inline int power_notice_decode(const void *message,unsigned int length,unsigned int words[4]) {
    unsigned int command;
    if(!message || length<4)return 0;
    __builtin_memcpy(&command,message,4);
    if(command==0x00920143U && length<16)return 0;
    words[0]=command;words[1]=words[2]=words[3]=0;
    if(length>=16)__builtin_memcpy(words+1,(const unsigned char *)message+4,12);
    return 1;
}
#endif
