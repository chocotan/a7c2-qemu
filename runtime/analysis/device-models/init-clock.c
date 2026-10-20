/* Seed the original clock using the dump's default local date and timezone.
 * UTC conversion is explicit; all advancement and GET replies remain native udate.
 */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern unsigned int sleep(unsigned int);
extern int osal_snd_sync_direct(unsigned int, void *);
static const unsigned int month_days[] = {31,28,31,30,31,30,31,31,30,31,30,31};
static int leap(unsigned int y) { return !(y%4) && (y%100 || !(y%400)); }
static unsigned int u16(const unsigned char *p) { return p[0] | (unsigned int)p[1]<<8; }
static void put16(unsigned char *p, unsigned int x) { p[0]=x; p[1]=x>>8; }
struct message { unsigned long q[6]; };
static unsigned char *b(struct message *m) { return (void *)m; }
static int valid(struct message *m) {
    const unsigned char *p=b(m)+20;
    unsigned int y=u16(p), mon=p[2], d=p[3];
    return y>=2000 && y<=2037 && mon>=1 && mon<=12 && d>=1 &&
        d<=month_days[mon-1]+(mon==2 && leap(y)) && p[4]<24 && p[5]<60 && p[6]<60 &&
        u16(p+8)<1000 && p[12]==0;
}
static long seconds(struct message *m) {
    const unsigned char *p=b(m)+20;
    long n=0;
    for(unsigned int y=2000;y<u16(p);y++) n+=365+leap(y);
    for(unsigned int mon=1;mon<p[2];mon++) n+=month_days[mon-1]+(mon==2&&leap(u16(p)));
    return (((n+p[3]-1)*24+p[4])*60+p[5])*60+p[6];
}
static int set_seconds(struct message *m,long value) {
    if(value<0) return 1;
    unsigned int y=2000,mon=1;
    long days=value/86400,rem=value%86400;
    while(y<=2037 && days>=365+leap(y)) { days-=365+leap(y); y++; }
    if(y>2037) return 1;
    while(mon<12 && days>=month_days[mon-1]+(mon==2&&leap(y))) {
        days-=month_days[mon-1]+(mon==2&&leap(y));mon++;
    }
    unsigned char *p=b(m)+20;
    put16(p,y);p[2]=mon;p[3]=days+1;p[4]=rem/3600;p[5]=(rem/60)%60;p[6]=rem%60;
    return 0;
}
static int call(struct message *m,unsigned int op) {
    put16(b(m)+16,op);put16(b(m)+18,0x7fff);
    int r=osal_snd_sync_direct(0x90013d,m),status=(short)u16(b(m)+18);
    printf("FULL_CLOCK_CALL op=%u transport=%d status=%d\n",op,r,status);
    return r||status;
}
static int get(struct message *m,unsigned int op) {
    *m=(struct message){{48,0,0,0,0,0}};
    return call(m,op);
}
int full_clock_init(void) {
    struct message current,initial,after;
    if(get(&current,2)) return 3;
    if(!valid(&current)) {
        if(b(&current)[32]!=3 || get(&initial,3) || !valid(&initial)) return 4;
        int area=(short)u16(b(&initial)+36),dst=(short)u16(b(&initial)+38);
        if(area < -1440 || area > 1440 || dst < -1440 || dst > 1440 || u16(b(&initial)+40)) return 5;
        long expected=seconds(&initial);
        if(set_seconds(&initial,expected-(area+dst)*60L)) return 6;
        b(&initial)[32]=1;put16(b(&initial)+44,4);
        if(call(&initial,0) || get(&current,2) || !valid(&current)) return 7;
        long elapsed=seconds(&current)-expected;
        if(elapsed<0 || elapsed>10) return 8;
    }
    sleep(2);
    if(get(&after,2) || !valid(&after)) return 9;
    long elapsed=seconds(&after)-seconds(&current);
    if(elapsed<1 || elapsed>10) return 10;
    printf("FULLSYSTEM_CLOCK_READY native-readback=valid elapsed=%ld\n",elapsed);
    return 0;
}
#ifndef FULL_CLOCK_TEST
extern int __libc_start_main(int (*)(int,char **),int,char **,void(*)(void),void(*)(void),void(*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc,char **argv) { (void)argv; return argc==1?full_clock_init():2; }
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
#endif
