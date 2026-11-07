/* Test only an owned child: sender cannot publish ACK until parent observed STOP/CONT. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

static int reply_fd;
static void *sender(void *unused) {
    (void)unused;
    assert(!syscall(SYS_tgkill,getpid(),syscall(SYS_gettid),SIGSTOP));
    assert(write(reply_fd,"ACK",3)==3);
    return 0;
}

int main(void) {
    alarm(10);
    int channel[2];assert(!pipe2(channel,O_CLOEXEC|O_NONBLOCK));
    pid_t child=fork();assert(child>=0);
    if(!child) {
        close(channel[0]);reply_fd=channel[1];
        pthread_t thread;assert(!pthread_create(&thread,0,sender,0));
        assert(!pthread_join(thread,0));
        _exit(0);
    }
    close(channel[1]);
    int status;assert(waitpid(child,&status,WUNTRACED)==child);
    assert(WIFSTOPPED(status) && WSTOPSIG(status)==SIGSTOP);
    char reply[3];assert(read(channel[0],reply,3)==-1 && errno==EAGAIN);
    assert(!kill(child,SIGCONT));
    assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(read(channel[0],reply,3)==3 && reply[0]=='A' && reply[1]=='C' && reply[2]=='K');
    close(channel[0]);
    return 0;
}
