/* Forked children must not touch a mutex inherited locked from the owner. */
#include "file-media-flush-hook.c"
#include <assert.h>
#include <sys/wait.h>

static void *unexpected_lookup(void *handle,const char *name) {
    (void)handle;(void)name;assert(0);return 0;
}
int main(void) {
    assert(!setenv("A7C2_FILE_MEDIA_TEST","1",1));
    owner=getpid();
    assert(!pthread_mutex_lock(&lock));
    pid_t child=fork();assert(child>=0);
    if(!child) {
        alarm(2);
        full_file_media_before_send(0x9088076bU,unexpected_lookup,0);
        _exit(0);
    }
    int status;assert(waitpid(child,&status,0)==child);
    assert(WIFEXITED(status) && WEXITSTATUS(status)==0);
    assert(!pthread_mutex_unlock(&lock));
    return 0;
}
