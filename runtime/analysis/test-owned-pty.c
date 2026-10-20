/* Host test: allocates only its own PTY; never opens an existing serial device. */
#define VHCI_CORE_TEST
#include "virtual-hci.c"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

static void transfer_read(int fd, uint8_t *p, size_t n) {
    while (n) {
        struct pollfd f={fd,POLLIN,0};
        assert(poll(&f,1,1000)==1);
        ssize_t got=read(fd,p,n);
        assert(got>0); p+=got; n-=(size_t)got;
    }
}
static int pty_emit(void *v, const uint8_t *p, size_t n) {
    int fd=*(int *)v;
    while (n) {
        ssize_t sent=write(fd,p,n);
        if (sent<0 && errno==EINTR) continue;
        if (sent<=0) return -1;
        p+=sent; n-=(size_t)sent;
    }
    return 0;
}
static void report_ioctl(int fd, unsigned long request, const char *name) {
    int bits=TIOCM_RTS|TIOCM_DTR;
    errno=0;
    int rc=ioctl(fd,request,&bits),error=errno;
    printf("owned-PTY %s rc=%d errno=%d bits=%x\n",name,rc,error,bits);
    assert(rc==0 || (rc==-1 && error==ENOTTY));
}
int main(void) {
    int master=posix_openpt(O_RDWR|O_NOCTTY|O_CLOEXEC);
    assert(master>=0 && !grantpt(master) && !unlockpt(master));
    char path[128]; assert(!ptsname_r(master,path,sizeof path));
    int slave=open(path,O_RDWR|O_NOCTTY|O_CLOEXEC|O_NOFOLLOW);
    assert(slave>=0);
    struct termios t; assert(!tcgetattr(slave,&t));
    cfmakeraw(&t); t.c_cflag|=CLOCAL|CREAD|CRTSCTS;
    assert(!cfsetispeed(&t,B115200) && !cfsetospeed(&t,B115200));
    assert(!tcsetattr(slave,TCSANOW,&t) && !tcflush(slave,TCIOFLUSH));
    report_ioctl(slave,TIOCMGET,"TIOCMGET");
    report_ioctl(slave,TIOCMSET,"TIOCMSET");
    report_ioctl(slave,TIOCMBIS,"TIOCMBIS");
    report_ioctl(slave,TIOCMBIC,"TIOCMBIC");
    struct vhci s; vhci_init(&s);
    struct vhci_io io={&master,pty_emit,0,0};
    const uint8_t reset[]={1,3,12,0};
    uint8_t command[12],reply[15];
    /* Transport a fragmented reset, then send its emitted event back over PTY. */
    for (size_t i=0;i<sizeof reset;++i) {
        assert(write(slave,reset+i,1)==1);
        transfer_read(master,command,1);
        assert(!vhci_feed(&s,&io,command,1));
    }
    transfer_read(slave,reply,7);
    assert(!memcmp(reply,(uint8_t[]){4,14,4,1,3,12,0},7));
    /* Raw mode must preserve NUL, XON, XOFF and LF inside binary H4 payload. */
    const uint8_t mask[]={1,1,12,8,0,0x11,0x13,10,0,1,2,3};
    assert(write(slave,mask,sizeof mask)==sizeof mask);
    transfer_read(master,command,sizeof mask);
    assert(!memcmp(command,mask,sizeof mask));
    assert(!vhci_feed(&s,&io,command,sizeof mask));
    transfer_read(slave,reply,7);
    assert(reply[6]==0 && !memcmp(s.event_mask,mask+4,8));
    const uint8_t addr[]={1,9,16,0};
    assert(write(slave,addr,sizeof addr)==sizeof addr);
    transfer_read(master,command,sizeof addr);
    assert(!vhci_feed(&s,&io,command,sizeof addr));
    transfer_read(slave,reply,13);
    assert(!memcmp(reply,(uint8_t[]){4,14,10,1,9,16,0,1,2,0x7c,0,0,2},13));
    assert(!close(slave) && !close(master));
    puts("PASS: owned PTY raw+115200+CRTSCTS, fragmented H4 round trip and binary transparency");
    return 0;
}
