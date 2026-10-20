/* ROM virtual HCI profile; no radio, links, chip firmware or host device access. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stddef.h>
#include <string.h>

struct vhci {
    uint8_t powered, advertising, scanning, duplicate_filter, host_le,bad_type;
    uint8_t address[6], event_mask[8], le_event_mask[8], event_mask2[8];
    uint8_t adv_params[15], adv_data[32], scan_response[32], scan_params[7];
    uint8_t local_name[248], device_class[3];
    uint8_t frame[259];
    uint8_t diag_enabled,last_diag[3];
    unsigned long diag_requests;
    size_t used;
    unsigned resets;
    int failed;
};
struct vhci_io {
    void *context;
    int (*emit)(void *, const uint8_t *, size_t);
    int (*entropy)(void *, uint8_t *, size_t);
    void (*log)(void *, const struct vhci *, uint16_t, const uint8_t *, size_t,
                const uint8_t *, size_t);
};
struct vhci_command { uint16_t opcode; uint8_t length, octet, bit; };
/* Core v4.0 Supported Commands bit positions; only implemented commands appear. */
static const struct vhci_command commands[] = {
    {0x0c01,8,5,6}, {0x0c03,0,5,7},
    {0x0c13,248,7,0}, {0x0c14,0,7,1},
    {0x0c19,0,7,6}, {0x0c1a,1,7,7},
    {0x0c23,0,9,0}, {0x0c24,3,9,1},
    {0x0c63,8,22,2}, {0x0c6c,0,24,5}, {0x0c6d,2,24,6},
    {0x1001,0,14,3}, {0x1002,0,14,4}, {0x1003,0,14,5},
    {0x1004,1,14,6}, {0x1005,0,14,7}, {0x1009,0,15,1},
    {0x1408,2,20,4},
    {0x2001,8,25,0}, {0x2002,0,25,1}, {0x2003,0,25,2},
    {0x2006,15,25,5}, {0x2007,0,25,6}, {0x2008,32,25,7},
    {0x2009,32,26,0}, {0x200a,1,26,1},
    {0x200b,7,26,2}, {0x200c,2,26,3},
    {0x200f,0,26,6}, {0x2010,0,26,7},
    {0x2018,0,27,7}, {0x201c,0,28,3},
    {0xfc01,6,255,0}, /* Vendor address programming has no Supported Commands bit. */
};
static unsigned le16(const uint8_t *p) { return p[0] | (unsigned)p[1]<<8; }
static inline int vhci_log_due(unsigned long n) { return n<=1024 || !(n&(n-1)); }
static void vhci_reset(struct vhci *s) {
    unsigned resets=s->resets+1;
    unsigned long diag_requests=s->diag_requests;
    uint8_t last_diag[3];memcpy(last_diag,s->last_diag,3);
    memset(s,0,sizeof *s);
    s->diag_requests=diag_requests;memcpy(s->last_diag,last_diag,3);
    s->resets=resets;
    s->powered=1;
    const uint8_t addr[]={1,2,0x7c,0,0,2};
    const uint8_t mask[]={255,255,255,255,255,0x1f,0,0};
    const uint8_t adv[]={0,8,0,8,3,0,0,0,0,0,0,0,0,7,0};
    const uint8_t scan[]={0,0x10,0,0x10,0,0,0};
    memcpy(s->address,addr,sizeof addr);
    memcpy(s->event_mask,mask,sizeof mask);
    s->le_event_mask[0]=0x1f;
    memcpy(s->adv_params,adv,sizeof adv);
    memcpy(s->scan_params,scan,sizeof scan);
    memcpy(s->local_name,"A7C2 virtual ROM",16);
}
static void vhci_init(struct vhci *s) {
    memset(s,0,sizeof *s);
    vhci_reset(s);
    s->resets=0;
    s->powered=0; /* Reset powers the virtual controller, process exit powers it off. */
}
static void features(uint8_t *r) {
    memset(r,0,8);
    r[4]=0x60; /* BR/EDR Not Supported, LE Supported; no encryption/SSP claim. */
    r[7]=0x80; /* Extended feature page 1 holds actual LE host support state. */
}
static int vhci_command(struct vhci *s, const struct vhci_io *io,
                        uint16_t op, const uint8_t *p, size_t n) {
    uint8_t ret[249]={0}, event[258];
    size_t count=1;
    const struct vhci_command *cmd=0;
    for (size_t i=0;i<sizeof commands/sizeof commands[0];++i)
        if (commands[i].opcode==op) { cmd=&commands[i]; break; }
    if (!cmd) ret[0]=0x01; /* Unknown HCI Command, including all vendor downloads. */
    else if (n!=cmd->length) ret[0]=0x12;
    else if (!s->powered && op!=0x0c03) ret[0]=0x0c;
    else switch (op) {
    case 0x0c03: vhci_reset(s); break;
    case 0x0c01: memcpy(s->event_mask,p,8); break;
    case 0x0c63: memcpy(s->event_mask2,p,8); break;
    case 0x0c13: memcpy(s->local_name,p,248); break;
    case 0x0c14: memcpy(ret+1,s->local_name,248); count=249; break;
    case 0x0c19: ret[1]=0; count=2; break;
    case 0x0c1a:
        if (p[0]>3) ret[0]=0x12;
        else if (p[0]) ret[0]=0x11; /* BR inquiry/page scanning is unavailable. */
        break;
    case 0x0c23: memcpy(ret+1,s->device_class,3); count=4; break;
    case 0x0c24: memcpy(s->device_class,p,3); break;
    case 0x0c6d:
        if (p[0]>1 || p[1]>1) ret[0]=0x12;
        else if (p[1]) ret[0]=0x11;
        else s->host_le=p[0];
        break;
    case 0x0c6c: ret[1]=s->host_le; ret[2]=0; count=3; break;
    case 0x1001: {
        /* HCI/LMP 5.0 legacy advertising; optional LE features remain explicitly zero. */
        const uint8_t version[]={0,9,1,0,9,255,255,1,0};
        memcpy(ret,version,sizeof version); count=sizeof version; break;
    }
    case 0x1002:
        count=65;
        for (size_t i=0;i<sizeof commands/sizeof commands[0];++i)
            if(commands[i].octet<64)ret[1+commands[i].octet]|=(uint8_t)(1U<<commands[i].bit);
        break;
    case 0x1003: features(ret+1); count=9; break;
    case 0x1004:
        count=11; ret[1]=p[0]; ret[2]=1;
        if (p[0]>1) ret[0]=0x12;
        else if (p[0]==0) features(ret+3);
        else ret[3]=(uint8_t)(s->host_le<<1);
        break;
    case 0x1005:
        /* No BR/SCO transport; LE uses its own buffers. */
        count=8; break;
    case 0x1009: memcpy(ret+1,s->address,6); count=7; break;
    case 0xfc01: memcpy(s->address,p,6); break;
    case 0x1408:
        /* BSA requires command support; there are deliberately no live links. */
        ret[0]=le16(p)>0x0eff ? 0x12 : 0x02;
        memcpy(ret+1,p,2); count=4; break;
    case 0x2001: memcpy(s->le_event_mask,p,8); break;
    case 0x2002:
        /* No connection/data role is exposed, hence no ACL buffer capacity. */
        count=4; break;
    case 0x2003: count=9; break; /* Baseline nonconnectable LE: no optional features. */
    case 0x2006:
        if (s->advertising) ret[0]=0x0c;
        else if (le16(p)<0x20 || le16(p+2)>0x4000 || le16(p)>le16(p+2) ||
                 p[4]>4 || p[5]>3 || p[6]>1 || !p[13] || (p[13]&~7) || p[14]>3)
            ret[0]=0x12;
        else if (p[4]!=3 || p[5] || p[14]) ret[0]=0x11;
        else memcpy(s->adv_params,p,15);
        break;
    case 0x2007: ret[1]=0; count=2; break; /* Virtual configured dBm; never radiated. */
    case 0x2008:
    case 0x2009:
        if (p[0]>31) ret[0]=0x12;
        else {
            uint8_t *target=op==0x2008 ? s->adv_data : s->scan_response;
            memset(target,0,32); memcpy(target,p,(size_t)p[0]+1);
        }
        break;
    case 0x200a:
        if (p[0]>1) ret[0]=0x12;
        else if (p[0] && s->scanning) ret[0]=0x0c;
        else s->advertising=p[0];
        break;
    case 0x200b:
        if (s->scanning) ret[0]=0x0c;
        else if (p[0]>1 || le16(p+1)<4 || le16(p+1)>0x4000 ||
                 le16(p+3)<4 || le16(p+3)>le16(p+1) || p[5]>3 || p[6]>1)
            ret[0]=0x12;
        else if (p[0] || p[5] || p[6]) ret[0]=0x11;
        else memcpy(s->scan_params,p,7);
        break;
    case 0x200c:
        if (p[0]>1 || p[1]>1) ret[0]=0x12;
        else if (p[0] && s->advertising) ret[0]=0x0c;
        else { s->scanning=p[0]; s->duplicate_filter=p[1]; }
        break;
    case 0x200f: ret[1]=0; count=2; break; /* Empty, zero-capacity accept list. */
    case 0x2010: break; /* Clearing an empty list has an actual empty backing set. */
    case 0x2018:
        count=9;
        if (!io->entropy || io->entropy(io->context,ret+1,8)) {
            memset(ret+1,0,8); ret[0]=0x03; /* Hardware failure, never fake entropy. */
        }
        break;
    case 0x201c:
        ret[1]=0x11; count=9; /* Nonconnectable advertising OR passive scan only. */
        break;
    }
    event[0]=4; event[1]=0x0e; event[2]=(uint8_t)(3+count);
    event[3]=1; event[4]=(uint8_t)op; event[5]=(uint8_t)(op>>8);
    memcpy(event+6,ret,count);
    if (io->log) io->log(io->context,s,op,p,n,event,count+6);
    return io->emit(io->context,event,count+6);
}
/* BCM's fixed 07 f0 00 disables LM diagnostics without an acknowledgement. */
static int vhci_feed(struct vhci *s, const struct vhci_io *io,
                     const uint8_t *bytes, size_t length) {
    if (s->failed) return -1;
    for (size_t i=0;i<length;++i) {
        if (!s->used && bytes[i]!=1 && bytes[i]!=7) { s->bad_type=bytes[i];s->failed=1; return -1; }
        s->frame[s->used++]=bytes[i];
        if(s->frame[0]==7) {
            if((s->used==2 && bytes[i]!=0xf0) || (s->used==3 && bytes[i]!=0)) {
                s->bad_type=7;s->failed=1;return -1;
            }
            if(s->used==3) {
                s->diag_enabled=0;s->diag_requests++;memcpy(s->last_diag,s->frame,3);s->used=0;
            }
            continue;
        }
        if (s->used>=4 && s->used==(size_t)s->frame[3]+4) {
            uint8_t p[255];
            size_t n=s->frame[3];
            unsigned op=le16(s->frame+1);
            memcpy(p,s->frame+4,n);
            s->used=0; /* Reset may clear the entire backing state. */
            if (vhci_command(s,io,(uint16_t)op,p,n)) { s->failed=1; return -1; }
        }
    }
    return 0;
}

#ifndef VHCI_CORE_TEST
#if !defined(__aarch64__)
#error "Guest-only executable: host tests must define VHCI_CORE_TEST"
#endif
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>

struct guest { int master; };
static volatile sig_atomic_t stopping;
static void stop_handler(int signo) { (void)signo; stopping=1; }
static int write_all(int fd, const uint8_t *p, size_t n) {
    while (n) {
        ssize_t done=write(fd,p,n);
        if (done<0 && errno==EINTR && !stopping) continue;
        if (done<=0) return -1;
        p+=done; n-=(size_t)done;
    }
    return 0;
}
static int guest_emit(void *v, const uint8_t *p, size_t n) {
    return write_all(((struct guest *)v)->master,p,n);
}
static int guest_entropy(void *v, uint8_t *p, size_t n) {
    (void)v;
    while (n) {
        long done=syscall(SYS_getrandom,p,n,0);
        if (done<0 && errno==EINTR && !stopping) continue;
        if (done<=0 || (size_t)done>n) return -1;
        p+=done; n-=(size_t)done;
    }
    return 0;
}
static void hexlog(const char *name, const uint8_t *p, size_t n) {
    fprintf(stderr," %s=",name);
    for (size_t i=0;i<n;++i) fprintf(stderr,"%02x",p[i]);
}
static void guest_log(void *v, const struct vhci *s, uint16_t op,
                      const uint8_t *p, size_t n, const uint8_t *e, size_t en) {
    (void)v;
    static unsigned long calls;
    if(!vhci_log_due(++calls))return;
    fprintf(stderr,"VHCI trace=%lu policy=first1024_then_powers_of_two ",calls);
    fprintf(stderr,"VHCI op=%04x status=%02x powered=%u adv=%u scan=%u duplicates=%u host_le=%u resets=%u",
            op,e[6],s->powered,s->advertising,s->scanning,s->duplicate_filter,s->host_le,s->resets);
    hexlog("params",p,n); hexlog("event",e,en);
    hexlog("address_le",s->address,6);
    hexlog("event_mask",s->event_mask,8); hexlog("le_mask",s->le_event_mask,8);
    hexlog("mask2",s->event_mask2,8); hexlog("adv_params",s->adv_params,15);
    hexlog("adv_data",s->adv_data,32); hexlog("scan_response",s->scan_response,32);
    hexlog("scan_params",s->scan_params,7);
    fprintf(stderr," diag_enabled=%u diag_requests=%lu",s->diag_enabled,s->diag_requests);
    fputc('\n',stderr); fflush(stderr);
}
static int guest_run(int argc, char **argv) {
    if (argc!=2 || strcmp(argv[1],"--virtual-rom")) {
        fprintf(stderr,"usage: virtual-hci --virtual-rom (guest only)\n"); return 2;
    }
    struct guest g={-1};
    struct vhci state;
    int slave=-1,rc=1;
    char path[128];
    struct termios t;
    vhci_init(&state);
    struct sigaction action;
    memset(&action,0,sizeof action); action.sa_handler=stop_handler;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGTERM,&action,0) || sigaction(SIGINT,&action,0)) goto finish;
    /* The only TTY accepted is the slave allocated by this master. */
    g.master=open("/dev/ptmx",O_RDWR|O_NOCTTY|O_CLOEXEC);
    if (g.master<0 || grantpt(g.master) || unlockpt(g.master) ||
        ptsname_r(g.master,path,sizeof path)) goto finish;
    slave=open(path,O_RDWR|O_NOCTTY|O_CLOEXEC|O_NOFOLLOW);
    if (slave<0 || tcgetattr(slave,&t)) goto finish;
    cfmakeraw(&t); t.c_cflag|=CLOCAL|CREAD;
    t.c_cflag&=~CRTSCTS; t.c_cc[VMIN]=1; t.c_cc[VTIME]=0;
    if (tcsetattr(slave,TCSANOW,&t)) goto finish;
    /* Linux PTYs normally reject modem control. Report the actual result. */
    int modem=0;
    errno=0;
    int modem_rc=ioctl(slave,TIOCMGET,&modem),modem_errno=errno;
    fprintf(stderr,"VHCI virtual-rom MAC=02:00:00:7c:02:01 TIOCMGET_rc=%d errno=%d bits=%x\n",
            modem_rc,modem_errno,modem);
    printf("%s\n",path);
    if (fflush(stdout)) goto finish;
    struct vhci_io io={&g,guest_emit,guest_entropy,guest_log};
    uint8_t input[512];
    while (!stopping) {
        ssize_t n=read(g.master,input,sizeof input);
        if (n<0 && errno==EINTR) continue;
        if (n<=0) goto finish;
        unsigned long before_diag=state.diag_requests;
        if (vhci_feed(&state,&io,input,(size_t)n)) {
            fprintf(stderr,"VHCI fatal H4/emit error type=%02x; no packet resynchronization",state.bad_type);
            hexlog("read",input,(size_t)n);fputc('\n',stderr);
            goto finish;
        }
        if(state.diag_requests!=before_diag && vhci_log_due(state.diag_requests)) {
            fprintf(stderr,"VHCI_DIAG enabled=%u count=%lu no_reply=1 policy=first1024_then_powers_of_two",state.diag_enabled,state.diag_requests);
            hexlog("request",state.last_diag,3);fputc('\n',stderr);fflush(stderr);
        }
    }
    rc=state.used ? 3 : 0;
finish:
    if (rc) fprintf(stderr,"VHCI exit rc=%d errno=%d partial=%zu\n",rc,errno,state.used);
    state.powered=0;
    if (slave>=0 && close(slave)) rc=1;
    if (g.master>=0 && close(g.master)) rc=1;
    return rc;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,
                           void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(guest_run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
#endif
