/* Verify cold-bootstrap copies without adding firmware crypto dependencies. */
typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long size_t;
typedef unsigned long long u64;
extern int open(const char *, int, ...), close(int), fsync(int), chmod(const char *, unsigned int);
extern long read(int, void *, size_t), write(int, const void *, size_t), lseek(int, long, int);
extern int printf(const char *, ...), strcmp(const char *, const char *), *__errno_location(void);
extern unsigned long strtoul(const char *, char **, int);
extern unsigned long long strtoull(const char *, char **, int);
struct space_info {
    unsigned long bsize, frsize, blocks, bfree, bavail, files, ffree, favail, fsid, flags, namemax;
    int spare[6];
};
_Static_assert(sizeof(struct space_info) == 112, "LP64 glibc statvfs ABI");
extern int statvfs(const char *, struct space_info *);
extern int fork(void), execv(const char *, char *const []), waitpid(int, int *, int);
extern void _exit(int);
static const u32 rounds[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};
struct sha { u32 h[8]; u64 count; u8 block[64]; unsigned used; };
static u32 rotr(u32 x, unsigned n) { return (x >> n) | (x << (32-n)); }
static void transform(struct sha *s) {
    u32 w[64], a=s->h[0], b=s->h[1], c=s->h[2], d=s->h[3];
    u32 e=s->h[4], f=s->h[5], g=s->h[6], h=s->h[7];
    for (unsigned i=0;i<16;i++) w[i]=(u32)s->block[4*i]<<24|(u32)s->block[4*i+1]<<16|(u32)s->block[4*i+2]<<8|s->block[4*i+3];
    for (unsigned i=16;i<64;i++) w[i]=w[i-16]+(rotr(w[i-15],7)^rotr(w[i-15],18)^(w[i-15]>>3))+w[i-7]+(rotr(w[i-2],17)^rotr(w[i-2],19)^(w[i-2]>>10));
    for (unsigned i=0;i<64;i++) {
        u32 t=h+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+rounds[i]+w[i];
        u32 q=(rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c));
        h=g;g=f;f=e;e=d+t;d=c;c=b;b=a;a=t+q;
    }
    s->h[0]+=a;s->h[1]+=b;s->h[2]+=c;s->h[3]+=d;s->h[4]+=e;s->h[5]+=f;s->h[6]+=g;s->h[7]+=h;
}
static void start(struct sha *s) {
    const u32 initial[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    for (unsigned i=0;i<8;i++) s->h[i]=initial[i];
    s->count=0;s->used=0;
}
static void update(struct sha *s, const u8 *p, size_t n) {
    s->count+=n;
    while (n--) { s->block[s->used++]=*p++; if (s->used==64) { transform(s);s->used=0; } }
}
static void finish(struct sha *s, char result[65]) {
    u64 bits=s->count*8;u8 one=128, zero=0, length[8];
    update(s,&one,1);
    while (s->used!=56) update(s,&zero,1);
    for (unsigned i=0;i<8;i++) length[7-i]=(u8)(bits>>(8*i));
    update(s,length,8);
    const char *hex="0123456789abcdef";
    for (unsigned i=0;i<32;i++) { u8 b=(u8)(s->h[i/4]>>(24-8*(i%4)));result[2*i]=hex[b>>4];result[2*i+1]=hex[b&15]; }
    result[64]=0;
}
static int number(const char *s, u64 *value, int base) {
    char *end;if (!*s || *s=='-' || *s=='+') return 1;
    *__errno_location()=0;*value=strtoull(s,&end,base);
    return *end || *__errno_location();
}
static int transfer(int source, int destination, u64 expected_size, const char *expected_hash) {
    u8 buffer[65536];u64 total=0;struct sha hash;char actual[65];start(&hash);
    for (;;) {
        long n=read(source,buffer,sizeof buffer);
        if (n<0) { if (*__errno_location()==4) continue; return 1; }
        if (!n) break;
        total+=(u64)n;if (total>expected_size) return 1;update(&hash,buffer,(size_t)n);
        for (long off=0;destination>=0 && off<n;) {
            long done=write(destination,buffer+off,(size_t)(n-off));
            if (done<0 && *__errno_location()==4) continue;
            if (done<=0) return 1;off+=done;
        }
    }
    finish(&hash,actual);
    return total!=expected_size || strcmp(actual,expected_hash);
}
static int run(int argc, char **argv) {
    u64 bytes,mode;
    if (argc==3 && !strcmp(argv[1],"release") && !strcmp(argv[2],"/dev/ram0")) {
        int child=fork(), status=0, rc=-1, zero=0;
        if (child==0) {
            char *arguments[]={"busybox","freeramdisk",argv[2],0};
            execv("/bin/busybox",arguments);_exit(127);
        }
        if (child>0 && waitpid(child,&status,0)==child && !(status&127)) rc=(status>>8)&255;
        if (rc==0) {
            u8 prefix[512];int fd=open(argv[2],0x20000);
            if (fd>=0) {
                long n=read(fd,prefix,sizeof prefix);close(fd);
                if (n==512) { zero=1;for (unsigned i=0;i<512;i++) if (prefix[i]) zero=0; }
            }
        }
        printf("COLD_RAM0_RELEASE original_rc=%d zero_prefix=%d bytes=512\n",rc,zero);
        return rc==0 && zero ? 0 : 8;
    }
    if (argc==4 && !strcmp(argv[1],"space") && !number(argv[3],&bytes,10)) {
        struct space_info s={0};
        if (statvfs(argv[2],&s) || !s.frsize) return 3;
        u64 available=(u64)s.bavail*s.frsize;
        printf("COLD_SPACE path=%s available=%llu required=%llu\n",argv[2],available,bytes);
        return available<bytes ? 4 : 0;
    }
    if (argc!=7 || strcmp(argv[1],"copy") || number(argv[4],&bytes,10) ||
        number(argv[6],&mode,8) || mode>0777 || bytes>0x80000000ULL) return 2;
    unsigned length=0;while (argv[5][length]) { char c=argv[5][length++];if (!((c>='0'&&c<='9')||(c>='a'&&c<='f'))) return 2; }
    if (length!=64) return 2;
    int source=open(argv[2],0x20000); /* O_NOFOLLOW */
    if (source<0) return 5;
    int destination=open(argv[3],0x20000|0xc2,0600); /* O_NOFOLLOW|O_EXCL|O_CREAT|O_RDWR */
    if (destination<0) { close(source);return 6; }
    int bad=transfer(source,destination,bytes,argv[5]);close(source);
    if (!bad && (fsync(destination) || lseek(destination,0,0)<0 || transfer(destination,-1,bytes,argv[5]))) bad=1;
    if (close(destination)) bad=1;
    if (!bad && chmod(argv[3],(unsigned)mode)) bad=1;
    printf("COLD_COPY path=%s bytes=%llu verified=%d errno=%d\n",argv[3],bytes,!bad,*__errno_location());
    return bad ? 7 : 0;
}
#ifdef COLD_AUDIT_HOST
int main(int argc, char **argv) { return run(argc,argv); }
#else
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
#endif
